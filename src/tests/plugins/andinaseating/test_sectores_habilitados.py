#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Un sector "Sin asignar" en Plan de butacas (sus butacas sin producto) no se vende: no aparece en
los planos de la boletería ni en el de las cortesías, y guardar las reservas no toca sus butacas.
"""
import json
import re

import pytest
from django_scopes import scopes_disabled

BOLETERIA = '/control/event/teatro/hamlet/boleteria/'
CORTESIAS = '/control/event/teatro/hamlet/cortesias/'


def sectores(html, script_id):
    data = re.search(r'<script id="{}" type="application/json">(.*?)</script>'.format(script_id), html, re.S)
    return [b['title'] for b in json.loads(data.group(1))]


@pytest.fixture
def sin_pullman(env):
    """Hamlet con el Pullman sin producto, y dos butacas del Pullman reservadas para la boletería."""
    event, platea, user = env
    with scopes_disabled():
        event.seats.filter(zone_name='Pullman', seat_guid__in=['pullman-J-1', 'pullman-J-2']).update(blocked=True)
        event.seats.filter(zone_name='Pullman').update(product=None)
    return env


@pytest.mark.django_db
def test_boleteria_muestra_solo_sectores_habilitados(sin_pullman, client):
    client.login(email='boleteria@example.com', password='boleteria')
    html = client.get(BOLETERIA).content.decode()
    assert sectores(html, 'boleteria-blocks') == ['Platea']
    assert sectores(html, 'pick-blocks') == ['Platea']
    assert 'Pullman · Fila J' not in html  # botones de "Fila completa"


@pytest.mark.django_db
def test_cortesias_muestra_solo_sectores_habilitados(sin_pullman, client):
    client.login(email='boleteria@example.com', password='boleteria')
    html = client.get(CORTESIAS).content.decode()
    assert sectores(html, 'pick-blocks') == ['Platea']


@pytest.mark.django_db
def test_guardar_reservas_no_toca_sectores_ocultos(sin_pullman, client):
    event, platea, user = sin_pullman
    client.login(email='boleteria@example.com', password='boleteria')
    client.post(BOLETERIA, {'action': 'reserve', 'blocked': 'platea-A-1'})
    with scopes_disabled():
        bloqueadas = set(event.seats.filter(blocked=True).values_list('seat_guid', flat=True))
    assert bloqueadas == {'platea-A-1', 'pullman-J-1', 'pullman-J-2'}


@pytest.mark.django_db
def test_con_todos_los_sectores_habilitados_se_ven_todos(env, client):
    client.login(email='boleteria@example.com', password='boleteria')
    html = client.get(BOLETERIA).content.decode()
    assert sectores(html, 'boleteria-blocks') == ['Platea', 'Pullman']
