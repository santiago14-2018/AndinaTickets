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
from django.views.generic import TemplateView

from pretix.base.models import Order
from pretix.base.services.orders import OrderError, _cancel_order
from pretix.control.permissions import EventPermissionRequiredMixin

from .boleteria import COURTESY_CHANNEL, enable_for_event, unnumbered_items
from .boleteria_views import EventDateMixin
from .cortesias import (
    courtesy_orders, create_courtesy, download_problem, send_mail,
)
from .forms import CourtesyForm


class CortesiasView(EventDateMixin, EventPermissionRequiredMixin, TemplateView):
    """
    Cortesías directas: nombre, email y butacas (o producto y cantidad, sin numerar). Al
    invitado le llegan las entradas con QR por email. En una serie, fecha por fecha.
    """
    permission = 'event.orders:write'
    template_name = 'pretixplugins/andinaseating/cortesias.html'
    url_name = 'cortesias'

    def courtesy_form(self, data=None):
        return CourtesyForm(data, numbered=self.has_plan, items=unnumbered_items(self.request.event))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event = self.request.event
        ctx.update(self.date_context())
        orders = []
        for o in courtesy_orders(event, self.subevent):
            positions = list(o.all_positions.all())
            first = positions[0] if positions else None
            orders.append({
                'order': o,
                'name': first.attendee_name if first else '',
                'positions': positions,
                'checked_in': any(p.checkins.exists() for p in positions if not p.canceled),
            })
        ctx.update({
            'form': kwargs.get('form') or self.courtesy_form(),
            'errors': kwargs.get('errors', []),
            'orders': orders,
            'download_problem': download_problem(event),
            'count': sum(len([p for p in r['positions'] if not p.canceled]) for r in orders
                         if r['order'].status == Order.STATUS_PAID),
            'vouchers_url': reverse('control:event.vouchers.bulk', kwargs={
                'organizer': event.organizer.slug, 'event': event.slug}),
        })
        if self.has_plan:
            enable_for_event(event, COURTESY_CHANNEL)
            blocks, seats = self.pick_blocks(COURTESY_CHANNEL, ctx['form'])
            ctx.update({'pick_blocks': blocks, 'rows': self.row_buttons(seats)})
        return ctx

    def get_order(self):
        try:
            return courtesy_orders(self.request.event, self.subevent).get(code=self.request.POST.get('order'))
        except Order.DoesNotExist:
            raise Http404()

    def post(self, request, *args, **kwargs):
        if not self.target:
            raise Http404()
        action = request.POST.get('action')
        if action == 'create':
            return self.post_create()
        if action == 'resend':
            return self.post_resend()
        if action == 'cancel':
            return self.post_cancel()
        return redirect(self.url())

    def post_create(self):
        form = self.courtesy_form(self.request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        event = self.request.event
        channel = enable_for_event(event, COURTESY_CHANNEL)
        d = form.cleaned_data
        try:
            with transaction.atomic():
                seats, item, quantity, errors = self.pick(form, channel)
                if errors:
                    return self.render_to_response(self.get_context_data(form=form, errors=errors))
                order = create_courtesy(event, self.subevent, self.request.user, d['name'], d['email'],
                                        seats=seats, item=item, quantity=quantity)
        except ValidationError as e:
            return self.render_to_response(self.get_context_data(form=form, errors=e.messages))
        n = order.positions.count()
        what = '{} entrada{} de cortesía para {}'.format(n, '' if n == 1 else 's', d['name'])
        if d['email']:
            messages.success(self.request, 'Listo: {}. Se las mandamos a {}.'.format(what, d['email']))
        else:
            messages.success(self.request, 'Listo: {}, en la lista de invitados (sin email).'.format(what))
        return redirect(self.url())

    def post_resend(self):
        order = self.get_order()
        if not order.email or order.status != Order.STATUS_PAID:
            messages.error(self.request, 'Esa cortesía no tiene email o está anulada.')
        else:
            send_mail(order, user=self.request.user)
            messages.success(self.request, 'Se reenviaron las entradas a {}.'.format(order.email))
        return redirect(self.url())

    def post_cancel(self):
        order = self.get_order()
        try:
            _cancel_order(order.pk, self.request.user, send_mail=False)
        except OrderError as e:
            messages.error(self.request, 'No se pudo anular: {}'.format(e))
        else:
            messages.success(self.request, 'Cortesía {} anulada: sus entradas ya no sirven en la puerta.'.format(
                order.code))
        return redirect(self.url())
