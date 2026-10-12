#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.text import slugify
from django.views import View
from django.views.generic import TemplateView

from pretix.control.views.organizer import OrganizerDetailViewMixin
from pretix.plugins.andinaseating.cargo import (
    SETTING as CARGO_SETTING, porcentaje as cargo_porcentaje,
)

from .report import (
    build_report, event_commission, event_producer_team, render_pdf,
)

PRODUCER_PERMISSION = 'andina.productor:read'
ADMIN_PERMISSION = 'organizer.settings.general:write'


def is_admin(request):
    return request.user.has_organizer_permission(request.organizer, ADMIN_PERMISSION, request=request)


def producer_teams(request):
    """Equipos del usuario que tienen el permiso de productor en este organizador."""
    return [t for t in request.user.teams.filter(organizer=request.organizer)
            if t.has_organizer_permission(PRODUCER_PERMISSION)]


def visible_events(request):
    events = request.organizer.events.order_by('-date_from')
    if is_admin(request):
        return list(events)
    team_ids = {t.pk for t in producer_teams(request)}
    return [e for e in events if event_producer_team(e) in team_ids]


class ProducerMixin(OrganizerDetailViewMixin):
    def dispatch(self, request, *args, **kwargs):
        if not (is_admin(request) or producer_teams(request)):
            raise PermissionDenied()
        return super().dispatch(request, *args, **kwargs)

    def get_event(self):
        for e in visible_events(self.request):
            if e.slug == self.kwargs['evento']:
                return e
        raise Http404()

    def get_subevent(self, event):
        raw = self.request.GET.get('fecha')
        if not raw or not event.has_subevents:
            return None
        try:
            return event.subevents.get(pk=raw)
        except (ValueError, event.subevents.model.DoesNotExist):
            raise Http404()


class MisVentasView(ProducerMixin, TemplateView):
    template_name = 'pretixplugins/andinaproductores/mis_ventas.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['reports'] = [build_report(e) for e in visible_events(self.request)]
        ctx['is_admin'] = is_admin(self.request)
        return ctx


class EventReportView(ProducerMixin, TemplateView):
    template_name = 'pretixplugins/andinaproductores/evento.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event = self.get_event()
        ctx['report'] = build_report(event, self.get_subevent(event))
        ctx['subevents'] = event.subevents.order_by('date_from') if event.has_subevents else []
        return ctx


class EventPdfView(ProducerMixin, View):
    def get(self, request, *args, **kwargs):
        event = self.get_event()
        subevent = self.get_subevent(event)
        teams = producer_teams(request)
        pdf = render_pdf(build_report(event, subevent), producer_name=teams[0].name if teams else '')
        name = 'liquidacion-{}{}.pdf'.format(slugify(event.slug), '-{}'.format(subevent.pk) if subevent else '')
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="{}"'.format(name)
        return response


def porcentaje_valido(raw, default):
    """Un porcentaje escrito en la pantalla (acepta coma), o None si no es un número entre 0 y 100."""
    raw = (raw if raw is not None else str(default)).replace(',', '.').strip() or str(default)
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if Decimal('0') <= value <= Decimal('100') else None


class ProductoresAdminView(OrganizerDetailViewMixin, TemplateView):
    """Para la plataforma: qué productor ve cada evento, con qué comisión y qué cargo por servicio
    paga el comprador (andinaseating/cargo.py; 10 % si no se cambia)."""
    template_name = 'pretixplugins/andinaproductores/admin.html'

    def dispatch(self, request, *args, **kwargs):
        if not is_admin(request):
            raise PermissionDenied()
        return super().dispatch(request, *args, **kwargs)

    def teams(self):
        return [t for t in self.request.organizer.teams.order_by('name')
                if t.has_organizer_permission(PRODUCER_PERMISSION) and not t.all_organizer_permissions]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['teams'] = self.teams()
        ctx['rows'] = [{
            'event': e,
            'team': event_producer_team(e),
            'commission': event_commission(e),
            'cargo': cargo_porcentaje(e),
        } for e in self.request.organizer.events.order_by('-date_from')]
        ctx['teams_url'] = reverse('control:organizer.teams', kwargs={'organizer': self.request.organizer.slug})
        return ctx

    def post(self, request, *args, **kwargs):
        valid_teams = {t.pk for t in self.teams()}
        changed = 0
        for e in request.organizer.events.all():
            raw_team = request.POST.get('team_{}'.format(e.pk))
            if raw_team is None:
                continue
            pct = porcentaje_valido(request.POST.get('commission_{}'.format(e.pk)), '0')
            cargo = porcentaje_valido(request.POST.get('cargo_{}'.format(e.pk)), cargo_porcentaje(e))
            if pct is None or cargo is None:
                messages.error(request, '{}: la comisión y el cargo por servicio tienen que ser números entre '
                                        '0 y 100.'.format(e.name))
                return redirect(request.path)
            team = int(raw_team) if raw_team.isdigit() and int(raw_team) in valid_teams else None
            if team != event_producer_team(e) or pct != event_commission(e) or cargo != cargo_porcentaje(e):
                if team:
                    e.settings.andina_productor_team = team
                else:
                    e.settings.delete('andina_productor_team')
                e.settings.andina_comision = str(pct)
                e.settings.set(CARGO_SETTING, str(cargo))
                e.log_action('pretix.plugins.andinaproductores.changed', user=request.user,
                             data={'team': team, 'commission': str(pct), 'cargo': str(cargo)})
                changed += 1
        messages.success(request, 'Guardado ({} evento{} con cambios).'.format(changed, '' if changed == 1 else 's'))
        return redirect(request.path)
