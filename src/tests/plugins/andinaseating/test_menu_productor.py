#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
El productor tiene "Mis ventas" en el menú de entrada (sin pasar por Organizadores) y un recuadro
grande con el botón "Ver mis ventas" en el Tablero.
"""
import pytest
from django_scopes import scopes_disabled

from pretix.base.models import Team, User

MIS_VENTAS = '/control/organizer/teatro/mis-ventas/'


@pytest.fixture
def productor(env, client):
    event, _item, _user = env
    with scopes_disabled():
        user = User.objects.create_user('esteban@example.com', 'esteban')
        team = Team.objects.create(organizer=event.organizer, name='.danza',
                                   limit_organizer_permissions={'andina.productor:read': True})
        team.members.add(user)
        event.settings.andina_productor_team = team.pk
    client.login(email='esteban@example.com', password='esteban')
    return client


def menu(html):
    """El menú de la izquierda (hasta el contenido de la página)."""
    return html[html.find('<ul class="nav" id="side-menu">'):html.find('id="page-wrapper"')]


@pytest.mark.django_db
def test_productor_tiene_mis_ventas_en_el_menu_y_el_tablero(productor):
    html = productor.get('/control/').content.decode()
    assert MIS_VENTAS in menu(html) and 'Mis ventas' in menu(html)
    assert 'Ver mis ventas' in html


@pytest.mark.django_db
def test_quien_no_es_productor_no_lo_tiene_en_el_menu(env, client):
    client.login(email='boleteria@example.com', password='boleteria')
    html = client.get('/control/').content.decode()
    assert MIS_VENTAS not in menu(html)
