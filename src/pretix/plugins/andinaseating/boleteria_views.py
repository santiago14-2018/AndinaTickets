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

from pretix.base.models import OrderPosition, Seat
from pretix.base.services.orders import OrderError
from pretix.base.templatetags.money import money_filter
from pretix.control.permissions import EventPermissionRequiredMixin

from .boleteria import (
    CHANNEL_IDENTIFIER, GENERATED_COMMENT, KIND_COURTESY, PAYMENT_METHODS,
    STATE_CANCELED, STATE_SOLD, STATE_UNSOLD, STATE_VALID, boleteria_positions,
    box_office_summary, cancel_ticket, cancel_unsold, check_quota,
    enable_for_event, generate_tickets, generated_lotes, import_tickets,
    lote_orders, parse_codes, parse_tickets_csv, resolve_tickets,
    seats_by_guid, sell_tickets, ticket_state, unnumbered_items,
)
from .forms import GenerateForm, SellForm, TicketsUploadForm
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
            p.state = ticket_state(p)
        states = [p.state for p in positions]
        ctx.update({
            'form': kwargs.get('form') or TicketsUploadForm(),
            'generate_form': kwargs.get('generate_form') or self.generate_form(),
            'sell_form': kwargs.get('sell_form') or SellForm(),
            'errors': kwargs.get('errors', []),
            'positions': positions,
            'generated': generated_lotes(event, self.subevent),
            'summary': box_office_summary(event, self.subevent),
            'paper': {
                'unsold': states.count(STATE_UNSOLD),
                'sold': states.count(STATE_SOLD),
                'courtesies': states.count(STATE_VALID),
                'canceled': states.count(STATE_CANCELED),
            },
        })
        if not ctx['has_plan']:
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
            },
        })
        return ctx

    def post(self, request, *args, **kwargs):
        if not self.target:
            raise Http404()
        action = request.POST.get('action')
        if action == 'sell':
            return self.post_sell()
        if action == 'cancel_unsold':
            return self.post_cancel_unsold()
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

    def post_sell(self):
        form = SellForm(self.request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(sell_form=form))
        event = self.request.event
        method = form.cleaned_data['method']
        try:
            with transaction.atomic():
                positions, total = sell_tickets(event, parse_codes(form.cleaned_data['codes']), method,
                                                self.request.user)
        except ValidationError as e:
            return self.render_to_response(self.get_context_data(sell_form=form, errors=e.messages))
        n = len(positions)
        detail = ', '.join(str(p.seat) if p.seat else str(p.item.name) for p in positions[:6])
        messages.success(self.request, 'Vendido{s} {n} boleto{s}: {total} en {method}. Ya entran en la puerta. '
                                       '({detail}{more})'.format(
                                           s='' if n == 1 else 's', n=n, total=money_filter(total, event.currency),
                                           method=dict(PAYMENT_METHODS)[method].lower(), detail=detail,
                                           more='…' if n > 6 else ''))
        return redirect(self.url())

    def post_cancel_unsold(self):
        n = cancel_unsold(self.request.event, self.subevent, self.request.user)
        if n:
            messages.success(self.request, 'Se anularon {} boleto{} sin vender: ya no sirven en la puerta.'.format(
                n, '' if n == 1 else 's'))
        else:
            messages.info(self.request, 'No había boletos sin vender.')
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
                lote, orders = generate_tickets(event, self.subevent, self.request.user, kind,
                                                seats=seats, item=item, quantity=quantity)
        except ValidationError as e:
            return self.render_to_response(self.get_context_data(generate_form=form, errors=e.messages))
        n = sum(o.positions.count() for o in orders)
        courtesy = kind == KIND_COURTESY
        messages.success(self.request, format_html(
            'Se generaron {} boleto{} {} (lote {}). <a href="{}">Descargar el paquete para la imprenta</a>.{}',
            n, '' if n == 1 else 's', 'de cortesía' if courtesy else 'para la venta', lote,
            reverse('plugins:andinaseating:boleteria.paquete', kwargs={
                'organizer': event.organizer.slug, 'event': event.slug, 'lote': lote}),
            '' if courtesy else ' Quedan sin vender: entran en la puerta recién cuando se venden acá.',
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
        orders = lote_orders(request.event, kwargs['lote']).filter(comment__startswith=GENERATED_COMMENT)
        if not orders.exists():
            raise Http404()
        filename, content = printer_package(request.event, kwargs['lote'])
        request.event.log_action('pretix.plugins.andinaseating.package.downloaded', user=request.user,
                                 data={'lote': kwargs['lote']})
        resp = HttpResponse(content, content_type='application/zip')
        resp['Content-Disposition'] = 'attachment; filename="{}"'.format(filename)
        return resp
