#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Organizador → Cargo por servicio: el porcentaje que paga el comprador sobre el precio de las
entradas en cada evento (cargo.py; 10 % si no se cambia). Solo para los administradores del
organizador.

El productor, su comisión y lo que ve cada uno no están acá: viven en el programa de
liquidaciones, aparte (ver ANDINA.md, "Caja 3").
"""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.views.generic import TemplateView

from pretix.control.views.organizer import OrganizerDetailViewMixin

from .cargo import PORCENTAJE, SETTING, porcentaje

PERMISO = 'organizer.settings.general:write'


def puede_editar(request):
    return request.user.has_organizer_permission(request.organizer, PERMISO, request=request)


def porcentaje_valido(texto):
    """El porcentaje escrito en la pantalla (acepta coma), o None si no es un número entre 0 y 100."""
    texto = (texto or '').replace(',', '.').strip()
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return None
    return valor if Decimal('0') <= valor <= Decimal('100') else None


class CargoView(OrganizerDetailViewMixin, TemplateView):
    template_name = 'pretixplugins/andinaseating/cargo.html'

    def dispatch(self, request, *args, **kwargs):
        if not puede_editar(request):
            raise PermissionDenied()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['eventos'] = [{'evento': e, 'cargo': porcentaje(e)}
                          for e in self.request.organizer.events.order_by('-date_from')]
        ctx['por_defecto'] = PORCENTAJE
        return ctx

    def post(self, request, *args, **kwargs):
        cambios = []
        for e in request.organizer.events.all():
            texto = request.POST.get('cargo_{}'.format(e.pk))
            if texto is None:
                continue
            valor = porcentaje_valido(texto)
            if valor is None:
                messages.error(request, '{}: el cargo por servicio tiene que ser un número entre 0 y 100.'.format(e.name))
                return redirect(request.path)
            if valor != porcentaje(e):
                cambios.append((e, valor))
        for e, valor in cambios:
            e.settings.set(SETTING, str(valor))
            e.log_action('pretix.plugins.andinaseating.cargo.changed', user=request.user, data={'cargo': str(valor)})
        messages.success(request, 'Guardado ({} evento{} con cambios).'.format(len(cambios), '' if len(cambios) == 1 else 's'))
        return redirect(request.path)
