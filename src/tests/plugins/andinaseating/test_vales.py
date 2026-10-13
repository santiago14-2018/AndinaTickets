#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Cortesías digitales: un vale a $0 se canjea eligiendo la butaca en el plano.
"""
import json
import re
from decimal import Decimal

import pytest
from django_scopes import scopes_disabled

from pretix.base.models import CartPosition


@pytest.fixture
def vale(env):
    event, platea, user = env
    with scopes_disabled():
        return event.vouchers.create(code='PRENSA', item=platea, price_mode='set', value=Decimal('0.00'),
                                     max_usages=2)


def plan_blocks(html):
    """Butacas de los planos (lo que dibuja seatmap-canvas; uno por sector), por nombre de sector."""
    maps = re.findall(r'<script id="andinaseating-blocks-\d+" type="application/json">(.*?)</script>', html, re.S)
    return {b['title']: b['seats'] for data in maps for b in json.loads(data)}


@pytest.mark.django_db
def test_canje_muestra_precio_del_vale_y_solo_su_sector(env, vale, client):
    r = client.get('/teatro/hamlet/redeem?voucher=PRENSA')
    assert r.status_code == 200
    html = r.content.decode()
    assert 'Platea' in html
    assert '30.000' not in html and '30,000' not in html
    blocks = plan_blocks(html)
    assert all(s['salable'] for s in blocks['Platea'])
    assert not any(s['salable'] for s in blocks['Pullman'])


@pytest.mark.django_db
def test_canje_pone_la_butaca_a_cero_en_el_carrito(env, vale, client):
    event, platea, user = env
    with scopes_disabled():
        seat = event.seats.get(seat_guid='platea-A-1')
    client.get('/teatro/hamlet/redeem?voucher=PRENSA')
    client.post('/teatro/hamlet/cart/add', {'_voucher_code': 'PRENSA', 'seat_{}'.format(platea.pk): seat.seat_guid})
    with scopes_disabled():
        cp = CartPosition.objects.get(event=event)
        assert cp.seat == seat
        assert cp.price == 0
        assert cp.voucher == vale
