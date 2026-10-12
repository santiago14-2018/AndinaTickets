#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.text import slugify
from django.views import View
from django.views.generic import TemplateView

from pretix.base.models import SeatingPlan
from pretix.base.models.seating import SeatingPlanLayoutValidator
from pretix.base.services.seating import (
    SeatProtected, generate_seats, validate_plan_change,
)
from pretix.control.permissions import OrganizerPermissionRequiredMixin
from pretix.control.views.organizer import OrganizerDetailViewMixin

from .forms import GeneratorForm, SalaForm, SectorUploadForm
from .layout import (
    add_sector, empty_layout, export_sector, generate_sector,
    parse_sector_file, remove_sector, sectors_summary,
)
from .seatmap import (
    layout_seats, plan_seats, row_label_sides, seats_to_blocks,
    set_row_label_side,
)


def sector_names(plan):
    return [z.get('name') for z in plan.layout_data.get('zones', []) if z.get('name')]


def generator_params(plan, name):
    """La configuración con que se generó (o se editó por última vez) un sector, sacada del historial
    de la sala. None si el sector se subió desde un archivo o no hay datos."""
    for entry in plan.all_logentries().filter(action_type='pretix.seatingplan.changed').order_by('-datetime', '-pk'):
        data = entry.parsed_data or {}
        if data.get('sector') == name:
            return data.get('generator')
        if data.get('sector_removed') == name:
            return None
    return None


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
        for s in ctx['sectors']:
            s['editable'] = generator_params(plan, s['name']) is not None
        ctx['total_seats'] = sum(s['seats'] for s in ctx['sectors'])
        ctx['events'] = list(plan.events.all()) + [se for se in plan.subevents.select_related('event')]
        ctx['form'] = kwargs.get('form') or SectorUploadForm()
        gen_form = kwargs.get('gen_form')
        editar = self.request.GET.get('editar', '')
        if gen_form is None and editar in sector_names(plan) and generator_params(plan, editar):
            # "Editar": el formulario con la configuración del sector, que se guarda en su mismo lugar.
            initial = dict(generator_params(plan, editar))
            initial.update(name=editar, editing=editar, placement='auto', reference='')
            initial.setdefault('row_labels', row_label_sides(plan).get(editar, 'izquierda'))
            gen_form = GeneratorForm(initial=initial, sectors=sector_names(plan))
            kwargs['gen_form'] = gen_form
        ctx['gen_form'] = gen_form or GeneratorForm(sectors=sector_names(plan))
        ctx['editing'] = ctx['gen_form'].editing_name
        ctx['open_generator'] = 'gen_form' in kwargs
        # Al entrar (y después de guardar) la pantalla queda lista para el alta de un sector: plano
        # vacío y formulario en blanco; mientras se completa se ve solo ese sector. "Editar" muestra
        # solo el sector que se edita. La sala entera se dibuja solo si se pide (?ver=sala).
        ctx['show_generator'] = not self.request.GET.get('ver') or bool(ctx['editing'] or gen_form is not None)
        ctx['view_url'] = self.request.path
        if ctx['show_generator']:
            ctx['blocks'] = []
        else:
            ctx['blocks'] = seats_to_blocks(plan_seats(plan), sides=row_label_sides(plan)) if ctx['total_seats'] else []
        ctx['preview_url'] = reverse('plugins:andinaseating:sala.preview', kwargs={
            'organizer': self.request.organizer.slug, 'sala': plan.pk,
        })
        ctx['export_url'] = reverse('plugins:andinaseating:sala.export', kwargs={
            'organizer': self.request.organizer.slug, 'sala': plan.pk,
        })
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

        elif action == 'generate':
            form = GeneratorForm(request.POST, sectors=sector_names(plan))
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(gen_form=form))
            try:
                params, side, placement, reference = form.sector_params()
                sides = row_label_sides(plan)
                zone, categories = generate_sector(**params)
                sides[zone['name']] = side
                layout = add_sector(plan.layout_data, zone, categories, placement, reference, sides)
                save_layout(plan, layout, request.user, {'sector': zone['name'], 'generator': {
                    k: v for k, v in form.cleaned_data.items()
                }})
                set_row_label_side(plan, zone['name'], side)
            except (ValidationError, SeatProtected) as e:
                form.add_error(None, _error_text(e))
                return self.render_to_response(self.get_context_data(gen_form=form))
            n = sum(len(r['seats']) for r in zone['rows'])
            messages.success(request, 'Sector "{}" {} con {} butacas. Ya podés crear otro.'.format(
                zone['name'], 'actualizado' if form.editing_name else 'guardado', n))

        elif action == 'delete_sector':
            name = request.POST.get('sector', '')
            try:
                save_layout(plan, remove_sector(plan.layout_data, name), request.user, {'sector_removed': name})
            except (ValidationError, SeatProtected) as e:
                messages.error(request, 'No se pudo quitar el sector: {}'.format(_error_text(e)))
            else:
                set_row_label_side(plan, name, 'izquierda')  # olvida de qué lado iba su letra
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


class SalaExportView(SalaMixin, View):
    """
    Descarga en JSON (formato de planos de pretix): con ?sector=, ese sector solo (para guardarlo
    y volver a subirlo en otra sala); sin sector, la sala completa (copia de seguridad).
    """

    def get(self, request, *args, **kwargs):
        try:
            plan = request.organizer.seating_plans.get(pk=kwargs['sala'])
        except SeatingPlan.DoesNotExist:
            raise Http404()
        sector = request.GET.get('sector')
        if sector:
            data = export_sector(plan.layout_data, sector)
            if data is None:
                raise Http404()
            filename = '{}-{}.json'.format(slugify(plan.name) or 'sala', slugify(sector) or 'sector')
        else:
            data = plan.layout_data
            filename = '{}.json'.format(slugify(plan.name) or 'sala')
        SeatingPlanLayoutValidator()(data)  # lo que se descarga siempre se puede volver a subir
        response = HttpResponse(json.dumps(data, ensure_ascii=False, indent=2), content_type='application/json')
        response['Content-Disposition'] = 'attachment; filename="{}"'.format(filename)
        return response


class SalaGeneratorPreviewView(SalaMixin, View):
    """
    Vista previa en vivo del generador: devuelve el plano de la sala con el sector
    generado (marcado) en el formato de seatmap-canvas. No guarda nada.
    """

    def get(self, request, *args, **kwargs):
        try:
            plan = request.organizer.seating_plans.get(pk=kwargs['sala'])
        except SeatingPlan.DoesNotExist:
            raise Http404()
        form = GeneratorForm(request.GET, sectors=sector_names(plan))
        alone = not request.GET.get('con_sala')  # solo el sector que se está armando
        if not form.is_valid():
            errors = [' '.join(e) for e in form.errors.values()]
            # field_errors: para marcar en rojo cada campo mientras se escribe (y borrarlo al corregir).
            return JsonResponse({'errors': errors, 'field_errors': form.errors}, status=400)
        try:
            params, side, placement, reference = form.sector_params()
            sides = row_label_sides(plan)
            zone, categories = generate_sector(**params)
            sides[zone['name']] = side
            layout = add_sector(plan.layout_data, zone, categories, placement, reference, sides)
        except ValidationError as e:
            return JsonResponse({'errors': e.messages}, status=400)
        name = zone['name']
        total = sum(len(r['seats']) for z in layout['zones'] for r in z['rows'])
        if alone:
            layout = add_sector(empty_layout(plan.name), zone, categories, sides=sides)
        # Las butacas del sector nuevo van en naranja (seatmap-andina.js), con su número a la vista.
        blocks = seats_to_blocks(layout_seats(layout), state=lambda s: {'custom_data': {'nuevo': s.zone == name}},
                                 sides=sides)
        return JsonResponse({
            'blocks': blocks,
            'alone': alone,
            'sector_seats': sum(len(r['seats']) for r in zone['rows']),
            'total_seats': total,
        })
