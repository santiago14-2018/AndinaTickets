#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Boletos de papel de venta: se activan al venderlos en el mostrador. Hasta entonces no entran
en la puerta; al venderlos queda registrado el medio de pago, quién vendió y el total.
"""
import json

import pytest
from django.core.exceptions import ValidationError
from django_scopes import scopes_disabled

from pretix.base.models import Order
from pretix.base.services.checkin import CheckInError, perform_checkin
from pretix.plugins.andinaseating.boleteria import (
    KIND_COURTESY, KIND_SALE, box_office_summary, cancel_unsold,
    enable_for_event, generate_tickets, import_tickets, parse_codes,
    parse_tickets_csv, resolve_tickets, seats_by_guid, sell_tickets,
)

from .conftest import PRICE


def generate(event, user, guids, kind=KIND_SALE):
    seats, errors = seats_by_guid(event, guids, enable_for_event(event))
    assert errors == []
    _lote, orders = generate_tickets(event, None, user, kind, seats=seats)
    return [p for o in orders for p in o.positions.all()]


@pytest.fixture
def puerta(env):
    event, _item, _user = env
    with scopes_disabled():
        return event.checkin_lists.create(name='Puerta', all_products=True)


@pytest.mark.django_db
def test_sin_vender_no_entra_y_vendido_si(env, puerta):
    event, item, user = env
    with scopes_disabled():
        (p,) = generate(event, user, ['platea-A-1'])
        with pytest.raises(CheckInError) as e:
            perform_checkin(p, puerta, {}, user=user)
        assert e.value.code == 'unpaid'

        sold, total = sell_tickets(event, [p.secret], 'efectivo', user)
        assert total == PRICE
        p.order.refresh_from_db()
        assert p.order.status == Order.STATUS_PAID
        perform_checkin(p, puerta, {}, user=user)  # ahora entra
        assert p.checkins.count() == 1


@pytest.mark.django_db
def test_la_venta_registra_medio_y_vendedor(env):
    event, item, user = env
    with scopes_disabled():
        positions = generate(event, user, ['platea-A-1', 'platea-A-2', 'platea-A-3'])
        sell_tickets(event, [positions[0].secret, positions[1].secret], 'efectivo', user)
        sell_tickets(event, [positions[2].secret], 'debito', user)
        pay = positions[2].order.payments.get()
        info = json.loads(pay.info)
        assert pay.provider == 'boxoffice' and pay.amount == PRICE
        assert (info['medio'], info['vendedor']) == ('debito', 'boleteria@example.com')
        summary = box_office_summary(event, None)
    assert summary['total'] == 3 * PRICE and summary['tickets'] == 3
    assert [(r['name'], r['tickets'], r['total']) for r in summary['by_method']] == [
        ('Efectivo', 2, 2 * PRICE), ('Tarjeta de débito', 1, PRICE)]
    assert summary['by_seller'][0]['name'] == 'boleteria@example.com'


@pytest.mark.django_db
def test_todo_o_nada(env):
    event, item, user = env
    with scopes_disabled():
        a, b = generate(event, user, ['platea-B-1', 'platea-B-2'])
        (regalo,) = generate(event, user, ['platea-B-3'], kind=KIND_COURTESY)
        sell_tickets(event, [a.secret], 'efectivo', user)
        with pytest.raises(ValidationError) as e:
            sell_tickets(event, [b.secret, a.secret, regalo.secret, 'NOEXISTE'], 'efectivo', user)
        msgs = ' '.join(e.value.messages)
        assert 'ya estaba vendido' in msgs and 'es de cortesía' in msgs and 'NOEXISTE: no es un boleto' in msgs
        b.order.refresh_from_db()
        assert b.order.status == Order.STATUS_PENDING  # no se vendió ninguno


@pytest.mark.django_db
def test_anular_los_sin_vender(env, puerta):
    event, item, user = env
    with scopes_disabled():
        a, b, c = generate(event, user, ['platea-B-1', 'platea-B-2', 'platea-B-3'])
        sell_tickets(event, [a.secret], 'efectivo', user)
        assert cancel_unsold(event, None, user) == 2
        for p in (b, c):
            p.order.refresh_from_db()
            assert p.order.status == Order.STATUS_CANCELED
            with pytest.raises(CheckInError):
                perform_checkin(p, puerta, {}, user=user)
            with pytest.raises(ValidationError):
                sell_tickets(event, [p.secret], 'efectivo', user)
        a.order.refresh_from_db()
        assert a.order.status == Order.STATUS_PAID  # lo vendido sigue vendido


@pytest.mark.django_db
def test_boletos_de_la_imprenta_tambien_se_activan_al_vender(env):
    event, item, user = env
    content = b'codigo;fila;butaca\nIMP001;A;4\nIMP002;A;5\n'
    with scopes_disabled():
        channel = enable_for_event(event)
        resolved, errors = resolve_tickets(event, None, parse_tickets_csv(content), channel)
        assert errors == []
        import_tickets(event, None, resolved, user, 'imprenta.csv', kind=KIND_SALE)
        sold, total = sell_tickets(event, parse_codes('IMP001\n IMP002 \n\nIMP001\n'), 'credito', user)
    assert len(sold) == 2 and total == 2 * PRICE


@pytest.mark.django_db
def test_pantalla_vender(env, client):
    event, item, user = env
    with scopes_disabled():
        a, b = generate(event, user, ['pullman-J-1', 'pullman-J-2'])
    client.login(email='boleteria@example.com', password='boleteria')
    url = '/control/event/teatro/hamlet/boleteria/'
    content = client.get(url).content.decode()
    assert 'Vender boletos de papel' in content and 'Sin vender' in content
    r = client.post(url, {'action': 'sell', 'method': 'efectivo', 'codes': '{}\r\n{}\r\n'.format(a.secret, b.secret)},
                    follow=True)
    content = r.content.decode()
    assert 'Vendidos 2 boletos' in content and 'en efectivo' in content
    assert 'Total cobrado' in content
    r = client.post(url, {'action': 'sell', 'method': 'efectivo', 'codes': a.secret})
    assert 'ya estaba vendido' in r.content.decode()
