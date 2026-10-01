#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.views.generic import TemplateView

from pretix.base.models import OrderPosition, Seat
from pretix.base.services.orders import OrderError
from pretix.control.permissions import EventPermissionRequiredMixin

from .boleteria import (
    CHANNEL_IDENTIFIER, boleteria_positions, cancel_ticket, enable_for_event,
    import_tickets, parse_tickets_csv, resolve_tickets,
)
from .forms import TicketsUploadForm
from .seatmap import event_seats, seats_to_blocks


class BoleteriaView(EventPermissionRequiredMixin, TemplateView):
    """
    Reservar butacas para venta presencial y cargar boletos impresos por una imprenta.
    En una serie se trabaja fecha por fecha (?fecha=<id>).
    """
    permission = 'event.orders:write'
    template_name = 'pretixplugins/andinaseating/boleteria.html'

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

    def url(self):
        url = reverse('plugins:andinaseating:boleteria', kwargs={
            'organizer': self.request.organizer.slug, 'event': self.request.event.slug,
        })
        return url + ('?fecha={}'.format(self.subevent.pk) if self.subevent else '')

    def free_for_boleteria(self):
        enable_for_event(self.request.event)
        return set(self.target.free_seats(sales_channel=CHANNEL_IDENTIFIER).values_list('pk', flat=True))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event, target = self.request.event, self.target
        ctx.update({
            'series': event.has_subevents,
            'subevent': self.subevent,
            'subevents': event.subevents.order_by('date_from', 'pk') if event.has_subevents else [],
            'has_plan': bool(target and target.seating_plan_id),
            'plan_url': reverse('plugins:andinaseating:event', kwargs={
                'organizer': event.organizer.slug, 'event': event.slug,
            }),
            'form': kwargs.get('form') or TicketsUploadForm(),
            'errors': kwargs.get('errors', []),
        })
        if not ctx['has_plan']:
            return ctx

        free = self.free_for_boleteria()
        seats = event_seats(target.seats.all())
        blocks = seats_to_blocks(seats, state=lambda s: {
            'salable': s.obj.pk in free,
            'selected': s.obj.pk in free and s.obj.blocked,
        })
        rows, seen = [], set()
        for s in seats:
            key = '{}|{}'.format(s.zone or '', s.row_label or s.row)
            if key not in seen:
                seen.add(key)
                rows.append({'key': key, 'zone': s.zone, 'label': s.row_label or s.row})

        positions = list(boleteria_positions(event, self.subevent))
        ctx.update({
            'blocks': blocks,
            'rows': rows,
            'positions': positions,
            'stats': {
                'total': len(seats),
                'online': target.free_seats(sales_channel='web').count(),
                'reserved': sum(1 for s in seats if s.obj.blocked and s.obj.pk in free),
                'tickets': sum(1 for p in positions if not p.canceled),
            },
        })
        return ctx

    def post(self, request, *args, **kwargs):
        if not self.target or not self.target.seating_plan_id:
            raise Http404()
        action = request.POST.get('action')
        if action == 'reserve':
            return self.post_reserve()
        if action == 'import':
            return self.post_import()
        if action == 'cancel':
            return self.post_cancel()
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
        event = self.request.event
        try:
            rows = parse_tickets_csv(f.read())
            channel = enable_for_event(event)
            resolved, errors = resolve_tickets(event, self.subevent, rows, channel)
            if errors:
                return self.render_to_response(self.get_context_data(form=form, errors=errors))
            with transaction.atomic():
                n = import_tickets(event, self.subevent, resolved, self.request.user, f.name)
        except ValidationError as e:
            return self.render_to_response(self.get_context_data(form=form, errors=e.messages))
        messages.success(self.request, 'Se cargaron {} boleto{} impreso{}.'.format(
            n, '' if n == 1 else 's', '' if n == 1 else 's'))
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
            messages.success(self.request, 'Boleto {} anulado. La butaca sigue reservada para boletería.'.format(
                position.secret))
        return redirect(self.url())
