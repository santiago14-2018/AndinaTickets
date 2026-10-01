#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
import re
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.views.generic import TemplateView

from pretix.base.models import Item, Quota, SeatingPlan
from pretix.base.services.seating import (
    SeatProtected, generate_seats, validate_plan_change,
)
from pretix.control.permissions import EventPermissionRequiredMixin

from .layout import categories_summary

NEW_PRODUCT = 'new'


def parse_price(text):
    """Acepta "30000", "30.000", "30.000,50" o "30000.50"."""
    s = (text or '').strip().replace('$', '').replace(' ', '')
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'\d{1,3}(\.\d{3})+', s):
        s = s.replace('.', '')
    try:
        value = Decimal(s)
    except InvalidOperation:
        raise ValidationError('"{}" no es un precio válido.'.format(text))
    if value < 0:
        raise ValidationError('El precio no puede ser negativo.')
    return value


class EventSeatingView(EventPermissionRequiredMixin, TemplateView):
    """
    Elegir la sala y conectar cada categoría de butaca con un producto (existente o
    nuevo) y su cupo. En una serie, se aplica a las fechas elegidas. Hace lo mismo que
    el PATCH de la API sobre el evento o sobre cada fecha.
    """
    permission = 'event.items:write'
    template_name = 'pretixplugins/andinaseating/event.html'

    def url(self):
        return reverse('plugins:andinaseating:event', kwargs={
            'organizer': self.request.organizer.slug, 'event': self.request.event.slug,
        })

    @cached_property
    def subevents(self):
        if not self.request.event.has_subevents:
            return []
        return list(self.request.event.subevents.select_related('seating_plan').order_by('date_from', 'pk'))

    def current_plan(self):
        if not self.request.event.has_subevents:
            return self.request.event.seating_plan
        return next((se.seating_plan for se in self.subevents if se.seating_plan_id), None)

    def get_selected_plan(self):
        data = self.request.POST if self.request.method == 'POST' else self.request.GET
        raw = data.get('sala')
        if raw is None:
            return self.current_plan()
        if raw == '':
            return None
        try:
            return self.request.organizer.seating_plans.get(pk=raw)
        except (SeatingPlan.DoesNotExist, ValueError):
            raise Http404()

    def current_mapping(self, plan):
        """Conexiones actuales de esta sala: del evento, o de la primera fecha que la usa."""
        event = self.request.event
        if event.has_subevents:
            ref = next((se for se in self.subevents if plan and se.seating_plan_id == plan.pk), None)
            if not ref:
                return {}
        elif plan != event.seating_plan or not plan:
            return {}
        else:
            ref = None
        return {
            m.layout_category: m.product
            for m in event.seat_category_mappings.filter(subevent=ref).select_related('product')
        }

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event = self.request.event
        plan = self.get_selected_plan()
        current = self.current_mapping(plan)
        # Fechas donde se aplica por defecto: las que ya usan esta sala o no tienen ninguna.
        checked = kwargs.get('checked_dates')
        dates = []
        for se in self.subevents:
            dates.append({
                'se': se,
                'plan': se.seating_plan,
                'total': se.seats.count(),
                'taken': se.taken_seats().count() if se.seating_plan_id else 0,
                'free': se.free_seats().count() if se.seating_plan_id else 0,
                'checked': (str(se.pk) in checked) if checked is not None else se.seating_plan_id in (None, plan and plan.pk),
            })
        targets = [None] if not event.has_subevents else [d['se'] for d in dates if d['checked']]

        categories = []
        for c in categories_summary(plan.layout_data) if plan else []:
            product = current.get(c['name'])
            note, warning = '', ''
            if product:
                missing = sum(1 for t in targets if not product.quotas.filter(subevent=t).exists())
                small = [q.size for t in targets for q in product.quotas.filter(subevent=t)
                         if q.size is not None and q.size < c['seats']]
                if missing:
                    note = 'Al guardar se crea un cupo de {}{}.'.format(
                        c['seats'], ' en {} fecha{}'.format(missing, 's' if missing > 1 else '') if event.has_subevents else '')
                if small:
                    warning = 'Hay un cupo de {} (menos que las butacas): se venderán hasta ese número.'.format(min(small))
            categories.append({**c, 'product': product, 'note': note, 'warning': warning})

        ctx.update({
            'series': event.has_subevents,
            'plans': event.organizer.seating_plans.order_by('name'),
            'plan': plan,
            'plan_changed': plan != self.current_plan(),
            'categories': categories,
            'dates': dates,
            'items': event.items.filter(variations__isnull=True).order_by('position', 'pk'),
            'NEW_PRODUCT': NEW_PRODUCT,
            'errors': kwargs.get('errors', []),
            'stats': {
                'total': event.seats.filter(subevent=None).count(),
                'free': event.free_seats().count() if event.seating_plan_id else 0,
                'taken': event.taken_seats().count() if event.seating_plan_id else 0,
            } if not event.has_subevents else None,
            'salas_url': reverse('plugins:andinaseating:salas', kwargs={'organizer': event.organizer.slug}),
        })
        return ctx

    def post(self, request, *args, **kwargs):
        event = request.event
        plan = self.get_selected_plan()
        errors = []

        if event.has_subevents:
            chosen = set(request.POST.getlist('dates'))
            targets = [se for se in self.subevents if str(se.pk) in chosen]
            if not targets:
                errors.append('Elegí al menos una fecha.')
        else:
            chosen = None
            targets = [None]

        items = {str(i.pk): i for i in event.items.filter(variations__isnull=True)}
        wanted = []  # (categoría, producto existente | None, nombre nuevo, precio nuevo, butacas)
        for n, c in enumerate(categories_summary(plan.layout_data) if plan else []):
            if request.POST.get('category_{}'.format(n)) != c['name']:
                errors = ['La sala cambió mientras editabas. Volvé a cargar la página.']
                break
            choice = request.POST.get('product_{}'.format(n), '')
            if choice == NEW_PRODUCT:
                name = request.POST.get('new_name_{}'.format(n), '').strip() or c['name']
                try:
                    price = parse_price(request.POST.get('new_price_{}'.format(n)))
                except ValidationError as e:
                    errors.append('{}: {}'.format(c['name'], ' '.join(e.messages)))
                    continue
                wanted.append((c['name'], None, name, price, c['seats']))
            elif choice in items:
                wanted.append((c['name'], items[choice], None, None, c['seats']))

        if not errors:
            try:
                with transaction.atomic():
                    self._save(event, plan, wanted, targets, request.user)
            except SeatProtected as e:
                errors.append(str(e))
        if errors:
            return self.render_to_response(self.get_context_data(errors=errors, checked_dates=chosen))

        where = '{} fecha{}'.format(len(targets), 's' if len(targets) > 1 else '') if event.has_subevents else 'el evento'
        if plan:
            messages.success(request, 'Listo: sala "{}" aplicada a {}.'.format(plan.name, where))
        else:
            messages.success(request, 'Se quitó el plano de butacas de {}.'.format(where))
        return redirect(self.url())

    def _save(self, event, plan, wanted, targets, user):
        for se in targets:
            validate_plan_change(event, se, plan)

        mapping, seats_by_category = {}, {}
        for category, item, new_name, new_price, seats in wanted:
            if item is None:
                item = Item.objects.create(
                    event=event, name=new_name, default_price=new_price, admission=True,
                    tax_rule=event.cached_default_tax_rule,
                    position=(event.items.aggregate(p=Max('position'))['p'] or 0) + 1,
                )
                item.log_action('pretix.event.item.added', user=user, data={
                    'name': new_name, 'default_price': str(new_price), 'seating_category': category,
                })
            mapping[category] = item
            seats_by_category[category] = seats

        for se in targets:
            obj = se or event
            obj.seating_plan = plan
            obj.save(update_fields=['seating_plan'])

            current = {m.layout_category: m for m in event.seat_category_mappings.filter(subevent=se)}
            for category, m in current.items():
                if category not in mapping:
                    m.delete()
                elif m.product_id != mapping[category].pk:
                    m.product = mapping[category]
                    m.save(update_fields=['product'])
            for category, item in mapping.items():
                if category not in current:
                    event.seat_category_mappings.create(layout_category=category, product=item, subevent=se)
                # Un producto conectado sin cupo no se puede vender: le creamos uno del tamaño de la categoría.
                if not item.quotas.filter(subevent=se).exists():
                    quota = Quota.objects.create(event=event, subevent=se, name=str(item.name),
                                                 size=seats_by_category[category])
                    quota.items.add(item)
                    quota.log_action('pretix.event.quota.added', user=user, data={
                        'name': str(item.name), 'size': quota.size, 'items': [item.pk],
                        'subevent': se.pk if se else None,
                    })

            generate_seats(event, se, plan, mapping)
            obj.log_action('pretix.subevent.changed' if se else 'pretix.event.changed', user=user, data={
                'seating_plan': plan.pk if plan else None,
                'seat_category_mapping': {k: v.pk for k, v in mapping.items()},
            })
        event.cache.clear()
