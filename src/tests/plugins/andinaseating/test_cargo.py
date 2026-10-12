#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Cargo por servicio: 10 % del precio de las entradas, que paga el comprador online y en la
boletería. Las cortesías no pagan. No se cobra dos veces.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils.timezone import now
from django_scopes import scopes_disabled

from pretix.base.models import CartPosition, OrderFee
from pretix.base.services.cart import get_fees
from pretix.base.signals import order_fee_calculation
from pretix.plugins.andinaseating.boleteria import (
    KIND_COURTESY, KIND_SALE, enable_for_event, generate_tickets,
    seats_by_guid,
)
from pretix.plugins.andinaseating.cargo import (
    CARGO_INTERNO, SETTING, agregar_a_pedido, calcular,
)

from .conftest import PRICE


def generate(event, user, guids, kind=KIND_SALE):
    seats, errors = seats_by_guid(event, guids, enable_for_event(event))
    assert errors == []
    _lote, orders = generate_tickets(event, None, user, kind, seats=seats)
    return orders


@pytest.mark.django_db
def test_calculo(env):
    event, _item, _user = env
    assert calcular(event, PRICE) == Decimal('3000.00')
    assert calcular(event, Decimal('12345.00')) == Decimal('1234.50')
    assert calcular(event, Decimal('0.00')) == Decimal('0.00')
    event.settings.set(SETTING, '5')  # cada evento puede tener otro porcentaje
    assert calcular(event, PRICE) == Decimal('1500.00')


@pytest.mark.django_db
def test_carrito_online(env):
    event, item, _user = env
    with scopes_disabled():
        cps = [CartPosition.objects.create(event=event, item=item, price=PRICE, cart_id='x',
                                           expires=now() + timedelta(minutes=10)) for _ in range(2)]
        fees = get_fees(event, None, invoice_address=None, payments=None, positions=cps)
    (fee,) = fees
    assert fee.fee_type == OrderFee.FEE_TYPE_SERVICE and fee.internal_type == CARGO_INTERNO
    assert fee.value == 2 * PRICE / 10 and fee.tax_value == 0


@pytest.mark.django_db
def test_pedido_online_cobra_el_mismo_cargo(env):
    event, item, _user = env
    with scopes_disabled():
        cp = CartPosition.objects.create(event=event, item=item, price=PRICE, cart_id='x',
                                         expires=now() + timedelta(minutes=10))
        fees = [f for _r, resp in order_fee_calculation.send(
            sender=event, invoice_address=None, total=PRICE, payment_requests=[], meta_info={},
            positions=[cp], gift_cards=[]) for f in resp]
    assert [f.value for f in fees] == [PRICE / 10]


@pytest.mark.django_db
def test_entrada_gratis_sin_cargo(env):
    event, item, _user = env
    with scopes_disabled():
        cp = CartPosition.objects.create(event=event, item=item, price=Decimal('0.00'), cart_id='x',
                                         expires=now() + timedelta(minutes=10))
        assert get_fees(event, None, invoice_address=None, payments=None, positions=[cp]) == []


@pytest.mark.django_db
def test_cortesia_sin_cargo_y_venta_una_sola_vez(env):
    event, _item, user = env
    with scopes_disabled():
        (cortesia,) = generate(event, user, ['platea-A-1'], kind=KIND_COURTESY)
        assert agregar_a_pedido(cortesia, user) == 0
        assert not cortesia.fees.exists()

        (venta,) = generate(event, user, ['platea-A-2'])
        assert agregar_a_pedido(venta, user) == PRICE / 10
        assert agregar_a_pedido(venta, user) == 0  # ya lo tenía
        venta.refresh_from_db()
        assert venta.fees.count() == 1 and venta.total == PRICE * Decimal('1.10')


@pytest.mark.django_db
def test_porcentaje_editable_en_productores(env, client):
    event, _item, user = env
    with scopes_disabled():
        team = user.teams.first()
        team.all_organizer_permissions = True
        team.save()
    client.login(email='boleteria@example.com', password='boleteria')
    url = '/control/organizer/teatro/productores/'
    r = client.get(url)
    assert r.status_code == 200 and 'name="cargo_{}" class="form-control"'.format(event.pk) in r.content.decode()

    # Festival grande: cargo más bajo (se acepta coma)
    client.post(url, {'team_{}'.format(event.pk): '', 'commission_{}'.format(event.pk): '0',
                      'cargo_{}'.format(event.pk): '7,5'})
    event.settings.flush()
    assert calcular(event, PRICE) == Decimal('2250.00')

    # Valor inválido: no se guarda
    r = client.post(url, {'team_{}'.format(event.pk): '', 'commission_{}'.format(event.pk): '0',
                          'cargo_{}'.format(event.pk): '150'}, follow=True)
    assert 'entre 0 y 100' in r.content.decode()
    event.settings.flush()
    assert calcular(event, PRICE) == Decimal('2250.00')
