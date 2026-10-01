#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Textos del historial del pedido para los eventos de Mercado Pago.

Sin esto, el historial muestra el nombre técnico del evento
("pretix.plugins.andinamercadopago.event") en lugar de una frase legible.
"""
from pretix.base.logentrytypes import (
    ClearDataShredderMixin, OrderLogEntryType, log_entry_types,
)

STATUS = {
    'approved': 'aprobado',
    'rejected': 'rechazado',
    'cancelled': 'cancelado',
    'pending': 'pendiente',
    'in_process': 'en proceso',
    'authorized': 'autorizado',
    'in_mediation': 'en mediación',
    'refunded': 'devuelto',
    'charged_back': 'con contracargo',
}
SOURCE = {
    'return': 'al volver el comprador',
    'webhook': 'por aviso automático',
}
STEP = {
    'preference': 'iniciar el pago',
    'refund': 'hacer la devolución',
}


class MercadoPagoLogEntryType(ClearDataShredderMixin, OrderLogEntryType):
    """Los datos del registro no tienen datos personales; igual se borran si se anonimiza el pedido."""


@log_entry_types.new()
class MercadoPagoPaymentEvent(MercadoPagoLogEntryType):
    action_type = 'pretix.plugins.andinamercadopago.event'

    def display(self, logentry, data):
        data = data or {}
        status = data.get('status') or '?'
        text = 'Mercado Pago informó el pago #{}: {}'.format(data.get('id', '?'), STATUS.get(status, status))
        details = []
        if data.get('payment_method_id'):
            method = data['payment_method_id']
            if (data.get('installments') or 1) > 1:
                method += ' en {} cuotas'.format(data['installments'])
            details.append(method)
        if data.get('status_detail'):
            details.append(data['status_detail'])
        if details:
            text += ' ({})'.format(', '.join(details))
        if data.get('source') in SOURCE:
            text += ', ' + SOURCE[data['source']]
        return text + '.'


@log_entry_types.new()
class MercadoPagoAmountMismatch(MercadoPagoLogEntryType):
    action_type = 'pretix.plugins.andinamercadopago.amount_mismatch'

    def display(self, logentry, data):
        data = data or {}
        return ('Mercado Pago informó el pago #{} por {} {}, que no coincide con el pedido. '
                'No se confirmó: revisalo.').format(
            data.get('id', '?'), data.get('transaction_amount', '?'), data.get('currency_id', ''),
        )


@log_entry_types.new()
class MercadoPagoConfirmFailed(MercadoPagoLogEntryType):
    action_type = 'pretix.plugins.andinamercadopago.confirm_failed'

    def display(self, logentry, data):
        return ('Se cobró en Mercado Pago, pero el pedido no se pudo confirmar porque ya no había lugar '
                '({}). Hay que resolverlo a mano y, si corresponde, devolver el dinero.').format(
            (data or {}).get('error', 'sin detalle'),
        )


@log_entry_types.new()
class MercadoPagoError(MercadoPagoLogEntryType):
    action_type = 'pretix.plugins.andinamercadopago.error'

    def display(self, logentry, data):
        data = data or {}
        step = STEP.get(data.get('step'), data.get('step') or 'comunicarse')
        return 'Error de Mercado Pago al {}: {}'.format(step, data.get('error', 'sin detalle'))
