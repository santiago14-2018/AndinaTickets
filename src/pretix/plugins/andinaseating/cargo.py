#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Cargo por servicio de AndinaTickets: un porcentaje del precio de las entradas que paga el
comprador, en la tienda online y en la boletería (así comprar online no sale más caro que en el
mostrador). Las cortesías no pagan cargo (son a precio 0). El productor no paga comisión: el
cargo no se suma a sus ventas (el portal del productor cuenta el precio de las entradas).

Se guarda como cargo de pretix de tipo "Cargo por servicio" (OrderFee "service"), sin IVA, con
``internal_type`` = CARGO_INTERNO para reconocerlo.
"""
from decimal import ROUND_HALF_UP, Decimal

from pretix.base.models import OrderFee

PORCENTAJE = Decimal('10')  # por defecto; cada evento puede tener otro en la opción SETTING
SETTING = 'andina_cargo_servicio'
CARGO_INTERNO = 'andina_cargo_servicio'


def porcentaje(event):
    return event.settings.get(SETTING, as_type=Decimal, default=PORCENTAJE)


def calcular(event, base):
    """El cargo para un monto de entradas, redondeado a centavos."""
    if not base or base <= 0:
        return Decimal('0.00')
    return (Decimal(base) * porcentaje(event) / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def nuevo_cargo(valor):
    return OrderFee(fee_type=OrderFee.FEE_TYPE_SERVICE, value=valor, internal_type=CARGO_INTERNO, tax_rule=None)


def cargo_del_carrito(event, positions):
    """Lista con el cargo para estas entradas del carrito (vacía si no corresponde)."""
    base = sum((getattr(p, 'gross_price_before_rounding', None) or p.price for p in positions), Decimal('0.00'))
    valor = calcular(event, base)
    return [nuevo_cargo(valor)] if valor > 0 else []


def agregar_a_pedido(order, user=None):
    """
    Suma el cargo a un pedido ya creado (boletos de papel que se venden en la boletería). No hace
    nada si ya lo tiene o si las entradas son gratis. Devuelve el valor agregado.
    """
    from pretix.base.services.orders import OrderChangeManager

    if order.fees.filter(internal_type=CARGO_INTERNO).exists():
        return Decimal('0.00')
    valor = calcular(order.event, sum((p.price for p in order.positions.all()), Decimal('0.00')))
    if valor <= 0:
        return Decimal('0.00')
    fee = nuevo_cargo(valor)
    fee.order = order
    ocm = OrderChangeManager(order, user=user, notify=False, reissue_invoice=False)
    ocm.add_fee(fee)
    ocm.commit(check_quotas=False)
    return valor
