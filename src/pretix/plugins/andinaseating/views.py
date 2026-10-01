#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from pretix.base.models import SeatingPlan
from pretix.base.models.seating import SeatingPlanLayoutValidator
from pretix.base.services.seating import (
    SeatProtected, generate_seats, validate_plan_change,
)
from pretix.control.permissions import OrganizerPermissionRequiredMixin
from pretix.control.views.organizer import OrganizerDetailViewMixin

from .forms import SalaForm, SectorUploadForm
from .layout import (
    add_sector, empty_layout, parse_sector_file, remove_sector,
    sectors_summary,
)
from .seatmap import plan_seats, seats_to_blocks


def _error_text(e):
    if isinstance(e, ValidationError):
        return ' '.join(e.messages)
    return str(e)


@transaction.atomic
def save_layout(plan, layout, user, action_data):
    """
    Guarda el plano y, si ya lo usa algún evento, regenera sus butacas. Falla sin
    guardar nada si el cambio quitaría butacas ya vendidas.
    """
    SeatingPlanLayoutValidator()(layout)
    plan.layout_data = layout

    usages = [(e, None) for e in plan.events.all()] + [(se.event, se) for se in plan.subevents.select_related('event')]
    for event, subevent in usages:
        validate_plan_change(event, subevent, plan)

    plan.save()
    for event, subevent in usages:
        generate_seats(event, subevent, plan, {
            m.layout_category: m.product
            for m in event.seat_category_mappings.select_related('product').filter(subevent=subevent)
        })
    plan.log_action('pretix.seatingplan.changed', user=user, data=action_data)


class SalaMixin(OrganizerPermissionRequiredMixin, OrganizerDetailViewMixin):
    permission = 'organizer.seatingplans:write'

    def list_url(self):
        return reverse('plugins:andinaseating:salas', kwargs={'organizer': self.request.organizer.slug})

    def detail_url(self, plan):
        return reverse('plugins:andinaseating:sala', kwargs={
            'organizer': self.request.organizer.slug, 'sala': plan.pk,
        })


class SalaListView(SalaMixin, TemplateView):
    template_name = 'pretixplugins/andinaseating/salas.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        salas = []
        for plan in self.request.organizer.seating_plans.annotate(
            n_events=Count('events', distinct=True), n_subevents=Count('subevents', distinct=True)
        ).order_by('name'):
            summary = sectors_summary(plan.layout_data)
            salas.append({
                'plan': plan,
                'sectors': len(summary),
                'seats': sum(s['seats'] for s in summary),
                'in_use': plan.n_events + plan.n_subevents,
            })
        ctx['salas'] = salas
        ctx['form'] = kwargs.get('form') or SalaForm()
        return ctx

    def post(self, request, *args, **kwargs):
        form = SalaForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        plan = SeatingPlan(organizer=request.organizer, name=form.cleaned_data['name'])
        plan.layout_data = empty_layout(plan.name)
        plan.save()
        plan.log_action('pretix.seatingplan.added', user=request.user, data={'name': plan.name})
        messages.success(request, 'Sala creada. Ahora subí sus sectores.')
        return redirect(self.detail_url(plan))


class SalaDetailView(SalaMixin, TemplateView):
    template_name = 'pretixplugins/andinaseating/sala.html'

    def get_plan(self):
        try:
            return self.request.organizer.seating_plans.get(pk=self.kwargs['sala'])
        except SeatingPlan.DoesNotExist:
            raise Http404()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        plan = self.get_plan()
        ctx['plan'] = plan
        ctx['sectors'] = sectors_summary(plan.layout_data)
        ctx['total_seats'] = sum(s['seats'] for s in ctx['sectors'])
        ctx['events'] = list(plan.events.all()) + [se for se in plan.subevents.select_related('event')]
        ctx['form'] = kwargs.get('form') or SectorUploadForm()
        ctx['blocks'] = seats_to_blocks(plan_seats(plan)) if ctx['total_seats'] else []
        return ctx

    def post(self, request, *args, **kwargs):
        plan = self.get_plan()
        action = request.POST.get('action')

        if action == 'upload':
            form = SectorUploadForm(request.POST, request.FILES)
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(form=form))
            name = form.cleaned_data['name'].strip()
            f = form.cleaned_data['file']
            try:
                zone, categories = parse_sector_file(f.read(), f.name, name)
                layout = add_sector(plan.layout_data, zone, categories)
                save_layout(plan, layout, request.user, {'sector': name, 'file': f.name})
            except (ValidationError, SeatProtected) as e:
                form.add_error('file', _error_text(e))
                return self.render_to_response(self.get_context_data(form=form))
            n = sum(len(r['seats']) for r in zone['rows'])
            messages.success(request, 'Sector "{}" guardado con {} butacas.'.format(name, n))

        elif action == 'delete_sector':
            name = request.POST.get('sector', '')
            try:
                save_layout(plan, remove_sector(plan.layout_data, name), request.user, {'sector_removed': name})
            except (ValidationError, SeatProtected) as e:
                messages.error(request, 'No se pudo quitar el sector: {}'.format(_error_text(e)))
            else:
                messages.success(request, 'Sector "{}" quitado.'.format(name))

        elif action == 'delete_sala':
            if plan.events.exists() or plan.subevents.exists():
                messages.error(request, 'La sala está en uso en un evento y no se puede borrar.')
            else:
                plan.log_action('pretix.seatingplan.deleted', user=request.user)
                plan.delete()
                messages.success(request, 'Sala borrada.')
                return redirect(self.list_url())

        return redirect(self.detail_url(plan))
