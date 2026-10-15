#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.dispatch import receiver
from django.template.loader import get_template
from django.urls import resolve, reverse

from pretix.base.permissions import PermissionGroup, PermissionOption
from pretix.base.signals import register_organizer_permission_groups
from pretix.control.signals import (
    nav_global, nav_organizer, user_dashboard_widgets,
)


@receiver(register_organizer_permission_groups, dispatch_uid="andinaproductores_permissions")
def register_permissions(sender, **kwargs):
    return [
        PermissionGroup(
            name='andina.productor',
            label='Portal del productor (AndinaTickets)',
            actions=['read'],
            options=[
                PermissionOption(actions=tuple(), label='Sin acceso'),
                PermissionOption(actions=('read',), label='Ver sus ventas'),
            ],
            help_text='Para equipos de productores: solo ven "Mis ventas" de los eventos que les asignes en '
                      'Productores. No les des acceso a eventos ni otros permisos.',
        ),
    ]


@receiver(nav_organizer, dispatch_uid="andinaproductores_nav_organizer")
def nav(sender, request=None, **kwargs):
    from .views import is_admin, producer_teams

    url = resolve(request.path_info)
    active = url.namespace == 'plugins:andinaproductores'
    org = request.organizer.slug
    items = []
    if is_admin(request) or producer_teams(request):
        items.append({
            'label': 'Mis ventas',
            'url': reverse('plugins:andinaproductores:mis_ventas', kwargs={'organizer': org}),
            'active': active and url.url_name != 'admin',
            'icon': 'line-chart',
        })
    if is_admin(request):
        items.append({
            'label': 'Productores',
            'url': reverse('plugins:andinaproductores:admin', kwargs={'organizer': org}),
            'active': active and url.url_name == 'admin',
            'icon': 'handshake-o',
        })
    return items


@receiver(user_dashboard_widgets, dispatch_uid="andinaproductores_dashboard")
def dashboard(sender, user, **kwargs):
    """Al entrar, el productor ve un acceso directo a sus ventas."""
    widgets = []
    for team in user.teams.select_related('organizer'):
        if team.has_organizer_permission('andina.productor:read') and not team.all_organizer_permissions:
            widgets.append({
                'content': get_template('pretixplugins/andinaproductores/widget.html').render({'organizer': team.organizer}),
                'display_size': 'big',
                'priority': 100,
                'url': reverse('plugins:andinaproductores:mis_ventas', kwargs={'organizer': team.organizer.slug}),
            })
    return widgets[:1]


@receiver(nav_global, dispatch_uid="andinaproductores_nav_global")
def nav_principal(sender, request=None, **kwargs):
    """
    "Mis ventas" en el menú de entrada (Tablero, Eventos, Organizadores…) para quien está en un
    equipo de productor: así no tiene que pasar por Organizadores. Uno por organizador, si fueran
    varios. Los administradores no lo necesitan: lo tienen dentro del organizador.
    """
    if not request or not request.user.is_authenticated:
        return []
    url = resolve(request.path_info)
    activo = url.namespace == 'plugins:andinaproductores' and url.url_name != 'admin'
    equipos = [t for t in request.user.teams.select_related('organizer')
               if t.has_organizer_permission('andina.productor:read') and not t.all_organizer_permissions]
    organizadores = list({t.organizer.pk: t.organizer for t in equipos}.values())
    return [{
        'label': 'Mis ventas' if len(organizadores) == 1 else 'Mis ventas ({})'.format(o.name),
        'url': reverse('plugins:andinaproductores:mis_ventas', kwargs={'organizer': o.slug}),
        'active': activo and request.resolver_match.kwargs.get('organizer') == o.slug,
        'icon': 'line-chart',
    } for o in organizadores]
