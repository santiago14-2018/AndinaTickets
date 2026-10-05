#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.html import format_html
from django.views import View
from django.views.generic import TemplateView

from pretix.base.models import Order, OrderPosition, Seat
from pretix.base.services.orders import OrderError
from pretix.control.permissions import EventPermissionRequiredMixin

from .boleteria import (
    CHANNEL_IDENTIFIER, GENERATED_COMMENT, KIND_COURTESY, boleteria_positions,
    cancel_ticket, check_quota, enable_for_event, generate_tickets,
    generated_orders, import_tickets, is_courtesy, parse_tickets_csv,
    resolve_tickets, seats_by_guid, unnumbered_items,
)
from .forms import GenerateForm, TicketsUploadForm
from .imprenta import printer_package
from .seatmap import event_seats, seats_to_blocks


class EventDateMixin:
    """Pantallas de evento que en una serie trabajan fecha por fecha (?fecha=<id>)."""
    url_name = None

    @cached_property
    def subevent(self):
        event = self.request.event
        if not event.has_subevents:
            return None
        raw = self.request.POST.get('fecha') or self.request.GET.get('fecha')
        qs = event.subevents.order_by('date_from', 'pk')
        if raw:
            try:
                return qs.get(pk=raw)
            except (ValueError, event.subevents.model.DoesNotExist):
                raise Http404()
        return qs.filter(seating_plan__isnull=False).first() or qs.first()

    @property
    def target(self):
        return self.subevent or self.request.event

    @property
    def has_plan(self):
        return bool(self.target and self.target.seating_plan_id)

    def url(self, name=None):
        url = reverse('plugins:andinaseating:' + (name or self.url_name), kwargs={
            'organizer': self.request.organizer.slug, 'event': self.request.event.slug,
        })
        return url + ('?fecha={}'.format(self.subevent.pk) if self.subevent else '')

    def date_context(self):
        event = self.request.event
        return {
            'series': event.has_subevents,
            'subevent': self.subevent,
            'subevents': event.subevents.order_by('date_from', 'pk') if event.has_subevents else [],
            'has_plan': self.has_plan,
            'plan_url': reverse('plugins:andinaseating:event', kwargs={
                'organizer': event.organizer.slug, 'event': event.slug,
            }),
        }

    def pick_blocks(self, channel_identifier, form=None):
        """Plano para elegir butacas libres para el canal (marcadas las del formulario, si volvió con error)."""
        free = set(self.target.free_seats(sales_channel=channel_identifier).values_list('pk', flat=True))
        chosen = set((form.data.get('seats') or '').split(',')) if form is not None and form.is_bound else set()
        seats = event_seats(self.target.seats.all())
        return seats_to_blocks(seats, state=lambda s: {
            'salable': s.obj.pk in free, 'selected': s.obj.pk in free and s.guid in chosen,
        }), seats

    @staticmethod
    def row_buttons(seats):
        rows, seen = [], set()
        for s in seats:
            key = '{}|{}'.format(s.zone or '', s.row_label or s.row)
            if key not in seen:
                seen.add(key)
                rows.append({'key': key, 'zone': s.zone, 'label': s.row_label or s.row})
        return rows

    def pick(self, form, channel):
        """(butacas, producto, cantidad, errores) a partir de un PickForm válido."""
        if self.has_plan:
            seats, errors = seats_by_guid(self.target, form.cleaned_data['guids'], channel)
            return seats, None, 0, errors
        item, quantity = form.cleaned_data['item'], form.cleaned_data['quantity']
        error = check_quota(item, self.subevent, quantity)
        return None, item, quantity, [error] if error else []


class BoleteriaView(EventDateMixin, EventPermissionRequiredMixin, TemplateView):
    """
    Reservar butacas para venta presencial, cargar boletos impresos por una imprenta y
    generar boletos para que la imprenta los imprima. En una serie se trabaja fecha por fecha.
    """
    permission = 'event.orders:write'
    template_name = 'pretixplugins/andinaseating/boleteria.html'
    url_name = 'boleteria'

    def free_for_boleteria(self):
        enable_for_event(self.request.event)
        return set(self.target.free_seats(sales_channel=CHANNEL_IDENTIFIER).values_list('pk', flat=True))

    def generate_form(self, data=None):
        return GenerateForm(data, numbered=self.has_plan, items=unnumbered_items(self.request.event))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event, target = self.request.event, self.target
        ctx.update(self.date_context())
        positions = list(boleteria_positions(event, self.subevent))
        for p in positions:
            p.generated = (p.order.comment or '').startswith(GENERATED_COMMENT)
        ctx.update({
            'form': kwargs.get('form') or TicketsUploadForm(),
            'generate_form': kwargs.get('generate_form') or self.generate_form(),
            'errors': kwargs.get('errors', []),
            'positions': positions,
            'generated': [
                {'order': o, 'count': o.positions.count(), 'courtesy': o.total == 0}
                for o in generated_orders(event, self.subevent)
            ],
            'generated_comment': GENERATED_COMMENT,
        })
        if not ctx['has_plan']:
            ctx['stats'] = {
                'tickets': sum(1 for p in positions if not p.canceled),
                'courtesies': sum(1 for p in positions if not p.canceled and is_courtesy(p)),
            }
            return ctx

        free = self.free_for_boleteria()
        seats = event_seats(target.seats.all())
        blocks = seats_to_blocks(seats, state=lambda s: {
            'salable': s.obj.pk in free,
            'selected': s.obj.pk in free and s.obj.blocked,
        })
        pick_blocks, _ = self.pick_blocks(CHANNEL_IDENTIFIER, ctx['generate_form'])
        ctx.update({
            'blocks': blocks,
            'pick_blocks': pick_blocks,
            'rows': self.row_buttons(seats),
            'stats': {
                'total': len(seats),
                'online': target.free_seats(sales_channel='web').count(),
                'reserved': sum(1 for s in seats if s.obj.blocked and s.obj.pk in free),
                'tickets': sum(1 for p in positions if not p.canceled),
                'courtesies': sum(1 for p in positions if not p.canceled and is_courtesy(p)),
            },
        })
        return ctx

    def post(self, request, *args, **kwargs):
        if not self.target:
            raise Http404()
        action = request.POST.get('action')
        if action == 'generate':
            return self.post_generate()
        if action == 'cancel':
            return self.post_cancel()
        if not self.has_plan:
            raise Http404()
        if action == 'reserve':
            return self.post_reserve()
        if action == 'import':
            return self.post_import()
        return redirect(self.url())

    def post_reserve(self):
        wanted = {g for g in self.request.POST.get('blocked', '').split(',') if g}
        free = self.free_for_boleteria()
        changed = []
        for seat in self.target.seats.filter(pk__in=free):
            blocked = seat.seat_guid in wanted
            if seat.blocked != blocked:
                seat.blocked = blocked
                changed.append(seat)
        Seat.objects.bulk_update(changed, ['blocked'], batch_size=1000)
        if changed:
            self.request.event.log_action('pretix.event.seats.blocks.changed', user=self.request.user,
                                          data={'seats': [s.pk for s in changed], 'source': 'boleteria'})
        messages.success(self.request, 'Butacas de boletería guardadas ({} cambio{}).'.format(
            len(changed), '' if len(changed) == 1 else 's'))
        return redirect(self.url())

    def post_import(self):
        form = TicketsUploadForm(self.request.POST, self.request.FILES)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        f = form.cleaned_data['file']
        kind = form.cleaned_data['kind']
        event = self.request.event
        try:
            rows = parse_tickets_csv(f.read())
            channel = enable_for_event(event)
            resolved, errors = resolve_tickets(event, self.subevent, rows, channel)
            if errors:
                return self.render_to_response(self.get_context_data(form=form, errors=errors))
            with transaction.atomic():
                n = import_tickets(event, self.subevent, resolved, self.request.user, f.name, kind=kind)
        except ValidationError as e:
            return self.render_to_response(self.get_context_data(form=form, errors=e.messages))
        if kind == KIND_COURTESY:
            msg = 'Se cargaron {} cortesía{} (sin cargo).'.format(n, '' if n == 1 else 's')
        else:
            msg = 'Se cargaron {} boleto{} impreso{} para la venta.'.format(
                n, '' if n == 1 else 's', '' if n == 1 else 's')
        messages.success(self.request, msg)
        return redirect(self.url())

    def post_generate(self):
        form = self.generate_form(self.request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(generate_form=form))
        event = self.request.event
        channel = enable_for_event(event)
        kind = form.cleaned_data['kind']
        try:
            with transaction.atomic():
                seats, item, quantity, errors = self.pick(form, channel)
                if errors:
                    return self.render_to_response(self.get_context_data(generate_form=form, errors=errors))
                order = generate_tickets(event, self.subevent, self.request.user, kind,
                                         seats=seats, item=item, quantity=quantity)
        except ValidationError as e:
            return self.render_to_response(self.get_context_data(generate_form=form, errors=e.messages))
        n = order.positions.count()
        messages.success(self.request, format_html(
            'Se generaron {} boleto{} {}. <a href="{}">Descargar el paquete para la imprenta</a>.',
            n, '' if n == 1 else 's', 'de cortesía' if kind == KIND_COURTESY else 'para la venta',
            reverse('plugins:andinaseating:boleteria.paquete', kwargs={
                'organizer': event.organizer.slug, 'event': event.slug, 'code': order.code}),
        ))
        return redirect(self.url())

    def post_cancel(self):
        try:
            position = boleteria_positions(self.request.event, self.subevent).get(
                pk=self.request.POST.get('position'), canceled=False)
        except (ValueError, OrderPosition.DoesNotExist):
            messages.error(self.request, 'No se encontró ese boleto.')
            return redirect(self.url())
        try:
            cancel_ticket(position, self.request.user)
        except OrderError as e:
            messages.error(self.request, 'No se pudo anular el boleto: {}'.format(e))
        else:
            messages.success(self.request, 'Boleto {} anulado.{}'.format(
                position.secret, ' La butaca sigue reservada para boletería.' if position.seat_id else ''))
        return redirect(self.url())


class BoleteriaPackageView(EventPermissionRequiredMixin, View):
    """Descarga el paquete para la imprenta (ZIP) de un lote de boletos generados."""
    permission = 'event.orders:write'

    def get(self, request, *args, **kwargs):
        try:
            order = request.event.orders.get(
                code=kwargs['code'], sales_channel__identifier=CHANNEL_IDENTIFIER,
                comment__startswith=GENERATED_COMMENT,
            )
        except Order.DoesNotExist:
            raise Http404()
        filename, content = printer_package(order)
        order.log_action('pretix.plugins.andinaseating.package.downloaded', user=request.user)
        resp = HttpResponse(content, content_type='application/zip')
        resp['Content-Disposition'] = 'attachment; filename="{}"'.format(filename)
        return resp
