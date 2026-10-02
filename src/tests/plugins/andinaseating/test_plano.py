#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Plano del comprador: cada butaca lleva el color de su producto, el mismo de la leyenda,
y cada sector muestra su nombre arriba de sus butacas.
"""
import json
import re

import pytest

from .test_vales import plan_blocks


def legend_colors(html):
    """Color de cada producto en la leyenda: {'Platea': 0, 'Pullman': 1}."""
    legend = re.search(r'<ul class="andinaseating-legend.*?</ul>', html, re.S).group(0)
    return {
        name: int(c)
        for c, name in re.findall(r'andinaseating-c(\d+)"></span>\s*<strong>([^<]+)</strong>', legend)
    }


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
def test_nombre_del_sector_arriba_de_sus_butacas(env, client):
    html = client.get('/teatro/hamlet/').content.decode()
    data = re.search(r'<script id="andinaseating-blocks" type="application/json">(.*?)</script>', html, re.S)
    blocks = sorted(json.loads(data.group(1)), key=lambda b: min(s['y'] for s in b['seats']))
    for b in blocks:
        top = min(s['y'] for s in b['seats'])
        names = [lb for lb in b['labels'] if lb['title'] == b['title']]
        assert len(names) == 1 and names[0]['y'] < top
    # El sector de abajo arranca (con su nombre) después de la última butaca del de arriba.
    first, second = blocks
    assert min(lb['y'] for lb in second['labels']) > max(s['y'] for s in first['seats'])
