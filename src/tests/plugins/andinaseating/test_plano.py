#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Plano del comprador: cada butaca lleva el color de su producto, el mismo de la leyenda,
y cada sector habilitado (con producto) va en su propio recuadro, con su plano.
"""
import json
import re

import pytest
from django_scopes import scopes_disabled

from .test_vales import plan_blocks


def legend_colors(html):
    """Color de cada producto en la leyenda: {'Platea': 0, 'Pullman': 1}."""
    legends = ''.join(re.findall(r'<ul class="andinaseating-legend.*?</ul>', html, re.S))
    return {
        name: int(c)
        for c, name in re.findall(r'andinaseating-c(\d+)"></span>\s*<strong>([^<]+)</strong>', legends)
    }


def map_sectors(html):
    """Sectores de cada plano de la página, en orden: [['Platea'], ['Pullman']]."""
    maps = re.findall(r'<script id="andinaseating-blocks-\d+" type="application/json">(.*?)</script>', html, re.S)
    return [[b['title'] for b in json.loads(data)] for data in maps]


@pytest.mark.django_db
def test_butacas_con_el_color_de_su_producto(env, client):
    html = client.get('/teatro/hamlet/').content.decode()
    colors = legend_colors(html)
    assert set(colors) == {'Platea', 'Pullman'}
    assert colors['Platea'] != colors['Pullman']

    blocks = plan_blocks(html)
    for sector, seats in blocks.items():
        assert {s['custom_data']['color'] for s in seats} == {colors[sector]}


@pytest.mark.django_db
def test_un_plano_por_sector_con_su_nombre(env, client):
    html = client.get('/teatro/hamlet/').content.decode()
    assert map_sectors(html) == [['Platea'], ['Pullman']]
    titles = re.findall(r'id="andinaseating-title-\d+">\s*([^<\s][^<]*?)\s*<', html)
    assert titles == ['Platea', 'Pullman']
    # Cada sector con su propio plano.
    assert html.count('id="andinaseating-map-') == 2


@pytest.mark.django_db
def test_sector_sin_producto_no_se_muestra(env, client):
    event, platea, user = env
    with scopes_disabled():
        event.seats.filter(zone_name='Pullman').update(product=None)
    html = client.get('/teatro/hamlet/').content.decode()
    assert map_sectors(html) == [['Platea']]
    assert set(legend_colors(html)) == {'Platea'}


@pytest.mark.django_db
def test_sin_sectores_habilitados_no_hay_plano(env, client):
    event, platea, user = env
    with scopes_disabled():
        event.seats.update(product=None)
    html = client.get('/teatro/hamlet/').content.decode()
    assert map_sectors(html) == []
    assert 'andinaseating-legend' not in html
