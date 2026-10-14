#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Evento con plano y además un producto sin butaca ("Gallinero"): la boletería y las cortesías
dejan elegir butacas en el plano o el producto sin numerar con una cantidad.
"""
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django_scopes import scopes_disabled

from pretix.base.models import OrderPosition
from pretix.plugins.andinaseating.boleteria import (
    sell_tickets, unnumbered_items,
)

BOLETERIA = '/control/event/teatro/hamlet/boleteria/'
CORTESIAS = '/control/event/teatro/hamlet/cortesias/'


@pytest.fixture
def gallinero(env):
    event, platea, user = env
    with scopes_disabled():
        item = event.items.create(name='Gallinero', default_price=Decimal('8000.00'), admission=True)
        event.quotas.create(name='Gallinero', size=50).items.add(item)
    return item


@pytest.mark.django_db
def test_productos_sin_numerar_son_los_que_no_tienen_butaca(env, gallinero):
    event, platea, user = env
    with scopes_disabled():
        assert list(unnumbered_items(event)) == [gallinero]


@pytest.mark.django_db
def test_boleteria_ofrece_el_producto_sin_numerar(env, gallinero, client):
    client.login(email='boleteria@example.com', password='boleteria')
    html = client.get(BOLETERIA).content.decode()
    assert 'Producto sin numerar' in html and 'Gallinero' in html
    assert 'id="generate-map"' in html  # el plano sigue para las butacas


@pytest.mark.django_db
def test_boleteria_genera_boletos_sin_numerar(env, gallinero, client):
    event, platea, user = env
    client.login(email='boleteria@example.com', password='boleteria')
    r = client.post(BOLETERIA, {'action': 'generate', 'kind': 'venta', 'item': gallinero.pk, 'quantity': 3,
                                'seats': ''}, follow=True)
    assert 'Se generaron 3 boletos para la venta' in r.content.decode()
    with scopes_disabled():
        ps = OrderPosition.objects.filter(order__event=event, item=gallinero)
        assert ps.count() == 3
        assert all(p.seat is None for p in ps)


@pytest.mark.django_db
def test_boleteria_pide_butacas_o_producto(env, gallinero, client):
    client.login(email='boleteria@example.com', password='boleteria')
    r = client.post(BOLETERIA, {'action': 'generate', 'kind': 'venta', 'item': '', 'quantity': 1, 'seats': ''})
    assert 'Elegí butacas en el plano o un producto sin numerar y la cantidad.' in r.content.decode()


@pytest.mark.django_db
def test_cortesia_sin_numerar_en_evento_con_plano(env, gallinero, client):
    event, platea, user = env
    client.login(email='boleteria@example.com', password='boleteria')
    r = client.post(CORTESIAS, {'action': 'create', 'name': 'Laura Gómez', 'email': '', 'item': gallinero.pk,
                                'quantity': 2, 'seats': ''}, follow=True)
    assert 'Listo: 2 entradas de cortesía para Laura Gómez' in r.content.decode()
    with scopes_disabled():
        assert OrderPosition.objects.filter(order__event=event, item=gallinero, price=0).count() == 2


# ---------------------------------------------------- boletos sin numerar que trae la imprenta

def subir(client, url, texto, kind='venta'):
    archivo = SimpleUploadedFile('boletos.csv', texto.encode('utf-8'), content_type='text/csv')
    return client.post(url, {'action': 'import', 'kind': kind, 'file': archivo}, follow=True)


@pytest.mark.django_db
def test_carga_numerados_y_sin_numerar_en_el_mismo_archivo(env, gallinero, client):
    event, platea, user = env
    client.login(email='boleteria@example.com', password='boleteria')
    r = subir(client, BOLETERIA, 'codigo;fila;butaca;producto\nk7Qm2xP9aT4w;A;1;\nHd5Wy2Kp9Sx3;;;Gallinero\n'
                                 'Rb3Nf8Zq1Lc6;;;gallinero\n')
    assert 'Se cargaron 3 boletos impresos para la venta.' in r.content.decode()
    with scopes_disabled():
        g = OrderPosition.objects.filter(order__event=event, item=gallinero)
        assert sorted(p.secret for p in g) == ['Hd5Wy2Kp9Sx3', 'Rb3Nf8Zq1Lc6']
        assert all(p.seat is None for p in g)
        assert event.seats.get(seat_guid='platea-A-1').blocked


@pytest.mark.django_db
def test_carga_solo_sin_numerar_y_se_venden_en_el_mostrador(env, gallinero, client):
    event, platea, user = env
    client.login(email='boleteria@example.com', password='boleteria')
    subir(client, BOLETERIA, 'codigo;producto\nHd5Wy2Kp9Sx3;Gallinero\n')
    with scopes_disabled():
        positions, total = sell_tickets(event, ['Hd5Wy2Kp9Sx3'], 'efectivo', user)
    assert total == Decimal('8800.00')  # 8.000 + 10 % de cargo por servicio


@pytest.mark.django_db
def test_carga_rechaza_producto_desconocido_y_codigos_malos(env, gallinero, client):
    client.login(email='boleteria@example.com', password='boleteria')
    html = subir(client, BOLETERIA, 'codigo;producto\nHd5Wy2Kp9Sx3;Pullman\nABC 123;Gallinero\n'
                                    + 'x' * 33 + ';Gallinero\n').content.decode()
    assert 'no hay un producto sin numerar &quot;Pullman&quot; en este evento (los que hay: Gallinero)' in html
    assert 'el código ABC 123 no sirve' in html
    assert 'el código {} no sirve'.format('x' * 33) in html
    with scopes_disabled():
        assert not OrderPosition.objects.filter(item=gallinero).exists()


@pytest.mark.django_db
def test_carga_sin_numerar_controla_el_cupo(env, gallinero, client):
    with scopes_disabled():
        gallinero.quotas.update(size=1)
    client.login(email='boleteria@example.com', password='boleteria')
    html = subir(client, BOLETERIA, 'codigo;producto\nHd5Wy2Kp9Sx3;Gallinero\nRb3Nf8Zq1Lc6;Gallinero\n').content.decode()
    assert 'De &quot;Gallinero&quot; quedan 1 lugar; pediste 2.' in html


@pytest.mark.django_db
def test_carga_en_evento_sin_plano(env_general, client):
    event, item, user = env_general
    client.login(email='boleteria@example.com', password='boleteria')
    r = subir(client, '/control/event/teatro/standup/boleteria/', 'codigo;producto\nHd5Wy2Kp9Sx3;General\n')
    assert 'Se cargaron 1 boleto impreso para la venta.' in r.content.decode()
