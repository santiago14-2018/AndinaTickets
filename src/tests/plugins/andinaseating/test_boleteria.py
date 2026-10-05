#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Pruebas de la boletería: boletos impresos para la venta y de cortesía (regalo, a $0),
y cómo los muestra el informe del productor.

Correr (dentro del contenedor web; ver ANDINA.md, "Pruebas automáticas"):
    cd /pretix/src && python3 -m pytest --ds=tests.settings tests/plugins/andinaseating -p no:cacheprovider
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.timezone import now
from django_scopes import scopes_disabled

from pretix.base.models import Order, OrderPosition
from pretix.plugins.andinaproductores.report import build_report
from pretix.plugins.andinaseating.boleteria import (
    KIND_COURTESY, KIND_SALE, boleteria_positions, enable_for_event,
    import_tickets, parse_tickets_csv, resolve_tickets, sell_tickets,
)

from .conftest import PRICE


def csv_bytes(*lines):
    return ('codigo;fila;butaca\n' + '\n'.join(lines) + '\n').encode('utf-8')


def load(event, user, content, kind):
    channel = enable_for_event(event)
    resolved, errors = resolve_tickets(event, None, parse_tickets_csv(content), channel)
    assert errors == []
    return import_tickets(event, None, resolved, user, 'boletos.csv', kind=kind)


@pytest.mark.django_db
def test_venta_se_carga_al_precio_del_producto_sin_vender(env):
    event, item, user = env
    with scopes_disabled():
        assert load(event, user, csv_bytes('0001;A;1', '0002;A;2'), KIND_SALE) == 2
        positions = list(boleteria_positions(event, None))
        assert {p.secret for p in positions} == {'0001', '0002'}
        assert all(p.price == PRICE for p in positions)
        # Un pedido por boleto, pendiente: se activa al venderlo en el mostrador.
        assert len({p.order_id for p in positions}) == 2
        assert all(p.order.status == Order.STATUS_PENDING for p in positions)
        assert all(p.order.comment.startswith('Boletos impresos') for p in positions)
        # La butaca queda reservada para boletería: la tienda online no la vende.
        assert all(p.seat.blocked for p in positions)


@pytest.mark.django_db
def test_cortesia_se_carga_a_cero(env):
    event, item, user = env
    with scopes_disabled():
        assert load(event, user, csv_bytes('R001;B;1', 'R002;B;2', 'R003;B;3'), KIND_COURTESY) == 3
        positions = list(boleteria_positions(event, None))
        assert all(p.price == 0 for p in positions)
        order = positions[0].order
        assert order.status == Order.STATUS_PAID
        assert order.total == 0
        assert order.comment.startswith('Cortesías impresas')
        assert all(p.seat.blocked for p in positions)


@pytest.mark.django_db
def test_cortesia_no_reusa_codigos_ni_butacas(env):
    event, item, user = env
    with scopes_disabled():
        load(event, user, csv_bytes('0001;A;1'), KIND_SALE)
        channel = enable_for_event(event)
        _, errors = resolve_tickets(event, None, parse_tickets_csv(csv_bytes('0001;A;2', 'R001;A;1')), channel)
    assert any('0001 ya existe' in e for e in errors)
    assert any('ya está vendida o reservada' in e for e in errors)


@pytest.mark.django_db
def test_pantalla_carga_cortesias(env, client):
    event, item, user = env
    client.login(email='boleteria@example.com', password='boleteria')
    url = '/control/event/teatro/hamlet/boleteria/'
    r = client.post(url, {
        'action': 'import', 'kind': 'cortesia',
        'file': SimpleUploadedFile('regalos.csv', csv_bytes('R001;A;1', 'R002;A;2'), content_type='text/csv'),
    }, follow=True)
    assert r.status_code == 200
    content = r.content.decode()
    assert 'Se cargaron 2 cortesías (sin cargo).' in content
    assert 'Cortesía</span>' in content
    assert '2 de cortesía' in content
    with scopes_disabled():
        assert OrderPosition.objects.filter(order__event=event, price=0).count() == 2


@pytest.mark.django_db
def test_pantalla_exige_elegir_el_tipo(env, client):
    event, item, user = env
    client.login(email='boleteria@example.com', password='boleteria')
    r = client.post('/control/event/teatro/hamlet/boleteria/', {
        'action': 'import',
        'file': SimpleUploadedFile('boletos.csv', csv_bytes('0001;A;1'), content_type='text/csv'),
    })
    assert r.status_code == 200
    with scopes_disabled():
        assert not OrderPosition.objects.filter(order__event=event).exists()


@pytest.mark.django_db
def test_informe_del_productor_separa_cortesias(env):
    event, item, user = env
    with scopes_disabled():
        load(event, user, csv_bytes('0001;A;1', '0002;A;2', '0003;A;3'), KIND_SALE)
        sell_tickets(event, ['0001', '0002'], 'efectivo', user)  # el 0003 queda sin vender: no cuenta
        load(event, user, csv_bytes('R001;B;1'), KIND_COURTESY)
        # Una venta online y una cortesía online (por ejemplo, con un vale al 100 %).
        web = event.organizer.sales_channels.get(identifier='web')
        for code, price in (('WEB01', PRICE), ('WEB02', Decimal('0.00'))):
            order = Order.objects.create(code=code, event=event, email='x@example.com', status=Order.STATUS_PAID,
                                         datetime=now(), expires=now(), total=price, sales_channel=web)
            OrderPosition.objects.create(order=order, item=item, price=price)

        event.settings.andina_comision = '10'
        report = build_report(event)

    assert report['tickets'] == 1
    assert report['gross'] == PRICE
    assert report['commission'] == Decimal('3000.00')
    assert report['box_count'] == 2
    assert report['box_value'] == 2 * PRICE
    assert report['courtesy_online'] == 1
    assert report['courtesy_box'] == 1


def test_csv_sin_columnas_obligatorias():
    with pytest.raises(ValidationError):
        parse_tickets_csv(b'codigo;butaca\n0001;1\n')
