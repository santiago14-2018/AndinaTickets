#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Boletos generados por AndinaTickets para que los imprima la imprenta (con y sin numerar),
y el paquete ZIP que se le manda (PDF, QR y planilla).
"""
import csv
import io
import zipfile
from decimal import Decimal

import pytest
from django_scopes import scopes_disabled

from pretix.base.models import Order
from pretix.plugins.andinaseating.boleteria import (
    CHANNEL_IDENTIFIER, KIND_COURTESY, KIND_SALE, check_quota,
    enable_for_event, generate_tickets, seats_by_guid,
)
from pretix.plugins.andinaseating.imprenta import printer_package

from .conftest import PRICE


def generate(event, user, guids, kind=KIND_COURTESY):
    seats, errors = seats_by_guid(event, guids, enable_for_event(event))
    assert errors == []
    return generate_tickets(event, None, user, kind, seats=seats)


@pytest.mark.django_db
def test_genera_cortesias_con_butaca(env):
    event, item, user = env
    with scopes_disabled():
        order = generate(event, user, ['platea-A-1', 'platea-A-2'])
        positions = list(order.positions.all())
        assert order.status == Order.STATUS_PAID and order.total == 0
        assert order.sales_channel.identifier == CHANNEL_IDENTIFIER
        assert {p.seat.seat_guid for p in positions} == {'platea-A-1', 'platea-A-2'}
        # Cada boleto con su código propio, generado por pretix.
        assert len({p.secret for p in positions}) == 2 and all(len(p.secret) >= 16 for p in positions)
        # Quedan reservadas para boletería: la tienda online no las vende.
        assert all(p.seat.blocked for p in positions)


@pytest.mark.django_db
def test_genera_boletos_de_venta_al_precio(env):
    event, item, user = env
    with scopes_disabled():
        order = generate(event, user, ['platea-B-1'], kind=KIND_SALE)
        assert order.total == PRICE


@pytest.mark.django_db
def test_no_genera_sobre_butacas_vendidas(env):
    event, item, user = env
    with scopes_disabled():
        generate(event, user, ['platea-A-1'])
        _, errors = seats_by_guid(event, ['platea-A-1', 'platea-Z-9'], enable_for_event(event))
    assert any('ya está vendida o reservada' in e for e in errors)
    assert any('no existe' in e for e in errors)


@pytest.mark.django_db
def test_paquete_para_la_imprenta(env):
    event, item, user = env
    with scopes_disabled():
        order = generate(event, user, ['platea-A-1', 'pullman-J-1'])
        codes = {p.secret for p in order.positions.all()}
        filename, content = printer_package(order)
    assert filename.endswith('.zip')
    z = zipfile.ZipFile(io.BytesIO(content))
    names = set(z.namelist())
    assert {'LEEME.txt', 'planilla.csv', 'entradas.pdf'} <= names
    assert {'qr/{}.png'.format(c) for c in codes} <= names
    assert z.read('entradas.pdf').startswith(b'%PDF')
    for c in codes:
        assert z.read('qr/{}.png'.format(c)).startswith(b'\x89PNG')
    rows = list(csv.DictReader(io.StringIO(z.read('planilla.csv').decode('utf-8-sig')), delimiter=';'))
    assert {r['codigo'] for r in rows} == codes
    expected = {('Platea', 'Fila A', 'Butaca 1'), ('Pullman', 'Fila J', 'Butaca 1')}
    assert {(r['sector'], r['fila'], r['butaca']) for r in rows} == expected
    assert {r['tipo'] for r in rows} == {'Cortesía'}


@pytest.mark.django_db
def test_qr_contiene_el_codigo(env):
    from PIL import Image
    event, item, user = env
    with scopes_disabled():
        order = generate(event, user, ['platea-A-3'])
        code = order.positions.get().secret
        _, content = printer_package(order)
    img = Image.open(io.BytesIO(zipfile.ZipFile(io.BytesIO(content)).read('qr/{}.png'.format(code))))
    assert img.size[0] >= 200  # se puede imprimir a 2,5 cm sin pixelarse


@pytest.mark.django_db
def test_sin_numerar_por_cantidad_y_respeta_el_cupo(env_general):
    event, item, user = env_general
    with scopes_disabled():
        assert check_quota(item, None, 4) == 'De "General" quedan 3 lugares; pediste 4.'
        assert check_quota(item, None, 2) is None
        order = generate_tickets(event, None, user, KIND_COURTESY, item=item, quantity=2)
        assert order.positions.count() == 2
        assert all(p.seat is None and p.price == Decimal('0.00') for p in order.positions.all())
        assert check_quota(item, None, 2) == 'De "General" quedan 1 lugar; pediste 2.'
        _, content = printer_package(order)
    rows = list(csv.DictReader(io.StringIO(
        zipfile.ZipFile(io.BytesIO(content)).read('planilla.csv').decode('utf-8-sig')), delimiter=';'))
    assert len(rows) == 2 and all(r['producto'] == 'General' and r['fila'] == '' for r in rows)


@pytest.mark.django_db
def test_pantalla_genera_y_descarga_el_paquete(env, client):
    event, item, user = env
    client.login(email='boleteria@example.com', password='boleteria')
    r = client.post('/control/event/teatro/hamlet/boleteria/', {
        'action': 'generate', 'kind': 'cortesia', 'seats': 'platea-B-1,platea-B-2,platea-B-3',
    }, follow=True)
    assert r.status_code == 200
    content = r.content.decode()
    assert 'Se generaron 3 boletos de cortesía.' in content
    assert 'Paquete para la imprenta (ZIP)' in content
    with scopes_disabled():
        order = Order.objects.get(event=event, comment__startswith='Boletos generados para la imprenta')
    r = client.get('/control/event/teatro/hamlet/boleteria/paquete/{}/'.format(order.code))
    assert r.status_code == 200
    assert r['Content-Type'] == 'application/zip'
    assert len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) == 3 + 3  # 3 QR + LEEME, planilla, PDF


@pytest.mark.django_db
def test_pantalla_sin_numerar(env_general, client):
    event, item, user = env_general
    client.login(email='boleteria@example.com', password='boleteria')
    url = '/control/event/teatro/standup/boleteria/'
    assert 'no tiene butacas numeradas' in client.get(url).content.decode()
    r = client.post(url, {'action': 'generate', 'kind': 'venta', 'item': item.pk, 'quantity': 5})
    assert 'quedan 3 lugares; pediste 5' in r.content.decode()
    r = client.post(url, {'action': 'generate', 'kind': 'venta', 'item': item.pk, 'quantity': 3}, follow=True)
    assert 'Se generaron 3 boletos para la venta.' in r.content.decode()


@pytest.mark.django_db
def test_paquete_de_otro_pedido_no_se_descarga(env, client):
    event, item, user = env
    client.login(email='boleteria@example.com', password='boleteria')
    assert client.get('/control/event/teatro/hamlet/boleteria/paquete/ABCDE/').status_code == 404
