#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Mercado Pago (Checkout Pro) como medio de pago.

Modelo actual: todo el dinero entra a UNA cuenta (la de la plataforma). Las credenciales
se cargan una sola vez en la configuración global de pretix; cada evento solo activa el
medio de pago.

Flujo:
1. execute_payment crea una "preferencia" en Mercado Pago y manda al comprador a pagar.
2. Al volver (ReturnView) o cuando Mercado Pago avisa (webhook), se consulta el pago a la
   API de Mercado Pago -nunca se confía en los parámetros recibidos- y process_mp_payment
   actualiza el pago de pretix.
"""
import json
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings as django_settings
from django.db import transaction
from django.template.loader import get_template
from django.urls import reverse
from django.utils.html import escape

from pretix.base.models import Order, OrderPayment, OrderRefund, Quota
from pretix.base.payment import BasePaymentProvider, PaymentException
from pretix.base.settings import GlobalSettingsObject
from pretix.helpers import OF_SELF
from pretix.multidomain.urlreverse import eventreverse_absolute

from .mp_api import MercadoPagoAPI, MercadoPagoError

logger = logging.getLogger(__name__)

IDENTIFIER = 'mercadopago'
SECRET_TAG = 'plugins:andinamercadopago'
# Solo medios que se acreditan al instante: sin efectivo (Rapipago, Pago Fácil) ni cajeros.
EXCLUDED_PAYMENT_TYPES = [{'id': 'ticket'}, {'id': 'atm'}]
PENDING_STATUSES = ('pending', 'in_process', 'authorized', 'in_mediation')
FAILED_STATUSES = ('rejected', 'cancelled')
REFUNDED_STATUSES = ('refunded', 'charged_back')


def global_setting(key):
    return GlobalSettingsObject().settings.get('payment_andinamp_' + key) or ''


def access_token(testmode):
    return global_setting('test_access_token' if testmode else 'access_token')


def external_reference(payment):
    """Identifica el pago de pretix en Mercado Pago: organizador/evento/pedido-P-n."""
    order = payment.order
    return '{}/{}/{}'.format(order.event.organizer.slug, order.event.slug, payment.full_id)


def _dinero(valor):
    """Monto de la API de Mercado Pago (número o texto) como texto con dos decimales, o None."""
    if valor is None or valor == '':
        return None
    try:
        return str(Decimal(str(valor)).quantize(Decimal('0.01')))
    except (InvalidOperation, ValueError):
        return None


def costos_de_cobro(data):
    """
    Lo que cobró Mercado Pago por este pago, en el formato común de AndinaTickets para todas las
    pasarelas (lo lee el programa privado de Liquidaciones por la API de pretix, en los detalles del
    pago, clave "costos"). Montos en texto con dos decimales; None si la pasarela no lo informa:

    - pasarela: "mercadopago"
    - bruto: lo que pagó el comprador
    - comision: comisiones de la pasarela a cargo nuestro (fee_details con fee_payer "collector")
    - impuestos: impuestos y retenciones que descontó la pasarela (charges_details de tipo "tax")
    - neto: lo que se acredita en la cuenta (transaction_details.net_received_amount)
    - costo_total: bruto − neto (todo lo que se quedó la pasarela); si no hay neto, comision + impuestos
    - acreditacion: cuándo se libera la plata (money_release_date)
    - detalle: el desglose tal como lo da Mercado Pago (nombre, tipo y monto de cada cargo)

    Las otras pasarelas que se agreguen deben guardar lo mismo, para que el informe las sume igual.
    """
    if not data.get('id'):
        return None
    comisiones = [f for f in (data.get('fee_details') or []) if f.get('fee_payer', 'collector') == 'collector']
    cargos = data.get('charges_details') or []
    impuestos = [c for c in cargos if c.get('type') == 'tax'
                 and (c.get('accounts') or {}).get('from', 'collector') == 'collector']

    def suma(montos):
        montos = [Decimal(m) for m in montos if m is not None]
        return str(sum(montos, Decimal('0.00')).quantize(Decimal('0.01'))) if montos else None

    def monto_cargo(c):
        a = c.get('amounts') or {}
        original, devuelto = _dinero(a.get('original')), _dinero(a.get('refunded')) or '0.00'
        return str(Decimal(original) - Decimal(devuelto)) if original is not None else None

    bruto = _dinero(data.get('transaction_amount'))
    neto = _dinero((data.get('transaction_details') or {}).get('net_received_amount'))
    comision = suma(_dinero(f.get('amount')) for f in comisiones)
    impuesto = suma(monto_cargo(c) for c in impuestos) if 'charges_details' in data else None
    if bruto is not None and neto is not None:
        costo_total = str(Decimal(bruto) - Decimal(neto))
    else:
        costo_total = suma([comision, impuesto])
    return {
        'pasarela': 'mercadopago',
        'bruto': bruto,
        'comision': comision,
        'impuestos': impuesto,
        'neto': neto,
        'costo_total': costo_total,
        'acreditacion': data.get('money_release_date'),
        'detalle': [{'nombre': f.get('type'), 'tipo': 'comision', 'monto': _dinero(f.get('amount'))}
                    for f in comisiones]
        + [{'nombre': c.get('name'), 'tipo': c.get('type'), 'monto': monto_cargo(c)}
           for c in cargos if (c.get('accounts') or {}).get('from', 'collector') == 'collector'],
    }


def payment_summary(data):
    """Lo que guardamos del pago de Mercado Pago (sin datos de tarjeta), con lo que nos cobró."""
    keys = ('id', 'status', 'status_detail', 'external_reference', 'transaction_amount', 'currency_id',
            'payment_method_id', 'payment_type_id', 'installments', 'date_created', 'date_approved',
            'live_mode', 'transaction_amount_refunded', 'money_release_date')
    resumen = {k: data.get(k) for k in keys if k in data}
    if 'costos' in data:  # ya es un resumen guardado (por ejemplo, el de los detalles para la API)
        resumen['costos'] = data['costos']
    elif data.get('id'):
        resumen['costos'] = costos_de_cobro(data)
    return resumen


def process_mp_payment(payment: OrderPayment, data: dict, source: str):
    """
    Aplica a ``payment`` (de pretix) el estado de ``data`` (pago de Mercado Pago, tal como
    lo devuelve la API). Devuelve un mensaje para el comprador o '' si no hay nada que decir.
    """
    if data.get('external_reference') != external_reference(payment):
        logger.warning('Mercado Pago: referencia %s no corresponde al pago %s',
                       data.get('external_reference'), payment.full_id)
        return ''
    if data.get('currency_id') != payment.order.event.currency or \
            Decimal(str(data.get('transaction_amount', '0'))) != payment.amount:
        logger.warning('Mercado Pago: monto o moneda no coinciden para %s', payment.full_id)
        payment.order.log_action('pretix.plugins.andinamercadopago.amount_mismatch', data=payment_summary(data))
        return 'El monto pagado no coincide con el pedido. Contactanos para resolverlo.'

    status = data.get('status')
    with transaction.atomic():
        payment = OrderPayment.objects.select_for_update(of=OF_SELF).get(pk=payment.pk)
        payment.order.log_action('pretix.plugins.andinamercadopago.event', data={
            'source': source, **payment_summary(data),
        })

        if status == 'approved':
            if payment.state == OrderPayment.PAYMENT_STATE_CONFIRMED:
                return ''
            payment.info = json.dumps(payment_summary(data))
            payment.save(update_fields=['info'])
            try:
                payment.confirm()
            except Quota.QuotaExceededException as e:
                # Se cobró pero ya no hay lugar (el pedido había vencido): queda para revisión manual.
                payment.order.log_action('pretix.plugins.andinamercadopago.confirm_failed', data={'error': str(e)})
                return 'Recibimos tu pago, pero la entrada ya no estaba disponible. Te vamos a contactar.'
            return ''

        if status in PENDING_STATUSES:
            if payment.state in (OrderPayment.PAYMENT_STATE_CREATED, OrderPayment.PAYMENT_STATE_PENDING):
                payment.state = OrderPayment.PAYMENT_STATE_PENDING
                payment.info = json.dumps(payment_summary(data))
                payment.save(update_fields=['state', 'info'])
            return 'Tu pago está en proceso. Te avisamos por email cuando se acredite.'

        if status in FAILED_STATUSES:
            if payment.state in (OrderPayment.PAYMENT_STATE_CREATED, OrderPayment.PAYMENT_STATE_PENDING):
                payment.fail(info=payment_summary(data), log_data={'source': source})
            return 'El pago no se pudo completar. Podés intentar de nuevo con otro medio de pago.'

        if status in REFUNDED_STATUSES and payment.state == OrderPayment.PAYMENT_STATE_CONFIRMED:
            # Devolución hecha desde el panel de Mercado Pago (o contracargo): la registramos en pretix.
            refunded = Decimal(str(data.get('transaction_amount_refunded') or data.get('transaction_amount')))
            known = sum(r.amount for r in payment.refunds.filter(
                state__in=(OrderRefund.REFUND_STATE_DONE, OrderRefund.REFUND_STATE_TRANSIT)))
            if refunded > known:
                payment.create_external_refund(amount=refunded - known, info=json.dumps(payment_summary(data)))
    return ''


class MercadoPago(BasePaymentProvider):
    identifier = IDENTIFIER
    verbose_name = 'Mercado Pago'
    public_name = 'Mercado Pago'
    execute_payment_needs_user = True

    @property
    def test_mode_message(self):
        if access_token(True):
            return ('Modo de prueba: se usan las credenciales de prueba de Mercado Pago. '
                    'Pagá con una tarjeta de prueba; no se cobra dinero real.')
        return 'Modo de prueba: falta cargar el access token de prueba de Mercado Pago.'

    def settings_content_render(self, request):
        # Las credenciales son globales (una sola cuenta); acá solo se muestra si están cargadas.
        return get_template('pretixplugins/andinamercadopago/settings.html').render({
            'configured': bool(access_token(False)),
            'test_configured': bool(access_token(True)),
            'webhook_secret': bool(global_setting('webhook_secret')),
            'global_url': reverse('control:global.settings'),
            'webhook_url': eventreverse_absolute(self.event, 'plugins:andinamercadopago:webhook'),
            'currency_ok': self.event.currency == 'ARS',
        }, request=request)

    def is_allowed(self, request, total=None):
        return (
            super().is_allowed(request, total) and
            self.event.currency == 'ARS' and
            bool(access_token(self.event.testmode))
        )

    def payment_form_render(self, request, total=None, order=None):
        return get_template('pretixplugins/andinamercadopago/checkout_payment_form.html').render({
            # Mismo criterio que execute_payment: el regreso automático solo funciona con un sitio https.
            'regreso_automatico': django_settings.SITE_URL.startswith('https://'),
        }, request=request)

    def checkout_prepare(self, request, cart):
        return True

    def payment_prepare(self, request, payment):
        return True

    def payment_is_valid_session(self, request):
        return True

    def checkout_confirm_render(self, request, order=None, info_data=None):
        return get_template('pretixplugins/andinamercadopago/checkout_confirm.html').render({}, request=request)

    def api(self, testmode):
        token = access_token(testmode)
        if not token:
            raise PaymentException('Mercado Pago no está configurado. Avisanos para resolverlo.')
        return MercadoPagoAPI(token)

    def return_url(self, payment):
        order = payment.order
        return eventreverse_absolute(self.event, 'plugins:andinamercadopago:return', kwargs={
            'order': order.code, 'hash': order.tagged_secret(SECRET_TAG), 'payment': payment.pk,
        })

    def execute_payment(self, request, payment: OrderPayment):
        order = payment.order
        back = self.return_url(payment)
        preference = {
            'items': [{
                'id': order.code,
                'title': '{} – Pedido {}'.format(self.event.name, order.code)[:250],
                'quantity': 1,
                'unit_price': float(payment.amount),
                'currency_id': self.event.currency,
            }],
            'external_reference': external_reference(payment),
            'back_urls': {'success': back, 'failure': back, 'pending': back},
            # Solo "aprobado" o "rechazado": las butacas no quedan esperando pagos a confirmar.
            'binary_mode': True,
            'payment_methods': {'excluded_payment_types': EXCLUDED_PAYMENT_TYPES},
            'metadata': {'organizer': self.event.organizer.slug, 'event': self.event.slug,
                         'order': order.code, 'payment': payment.local_id},
        }
        # En modo de prueba no se pasa el correo del pedido: Mercado Pago exige que el comprador
        # también sea una cuenta de prueba, y con un correo común frena el pago ("No pudimos
        # procesar tu pago") antes de intentarlo.
        if order.email and not order.testmode:
            preference['payer'] = {'email': order.email}
        if order.expires:
            preference['expires'] = True
            preference['expiration_date_to'] = order.expires.isoformat(timespec='milliseconds')
        descriptor = global_setting('statement_descriptor')
        if descriptor:
            preference['statement_descriptor'] = descriptor
        # Mercado Pago solo puede avisar a una dirección pública (no a localhost en desarrollo), y
        # rechaza el regreso automático a una dirección que no es pública ("auto_return invalid.
        # back_url.success must be defined"). En desarrollo, el comprador vuelve con el botón
        # "Volver al sitio" de Mercado Pago.
        if django_settings.SITE_URL.startswith('https://'):
            preference['notification_url'] = eventreverse_absolute(self.event, 'plugins:andinamercadopago:webhook')
            preference['auto_return'] = 'approved'

        try:
            result = self.api(order.testmode).create_preference(preference)
        except MercadoPagoError as e:
            order.log_action('pretix.plugins.andinamercadopago.error', data={'step': 'preference', 'error': str(e)})
            raise PaymentException('No pudimos iniciar el pago con Mercado Pago: {}'.format(e))

        payment.info = json.dumps({'preference_id': result.get('id')})
        payment.save(update_fields=['info'])
        return result.get('init_point')

    def payment_pending_render(self, request, payment):
        return get_template('pretixplugins/andinamercadopago/pending.html').render({
            'payment': payment, 'info': payment.info_data,
            # Consulta el pago a Mercado Pago por la referencia del pedido (ReturnView): para quien
            # pagó y no volvió a la tienda, y en desarrollo, donde no llegan los avisos.
            'verificar_url': self.return_url(payment) if payment.info_data.get('preference_id') else None,
        }, request=request)

    def payment_control_render(self, request, payment):
        return get_template('pretixplugins/andinamercadopago/control.html').render({
            'info': payment.info_data,
        }, request=request)

    def payment_control_render_short(self, payment):
        mp_id = payment.info_data.get('id')
        return 'Mercado Pago #{}'.format(escape(mp_id)) if mp_id else ''

    def matching_id(self, payment):
        return payment.info_data.get('id')

    def api_payment_details(self, payment):
        return payment_summary(payment.info_data)

    def payment_refund_supported(self, payment):
        return bool(payment.info_data.get('id'))

    def payment_partial_refund_supported(self, payment):
        return bool(payment.info_data.get('id'))

    def execute_refund(self, refund: OrderRefund):
        payment = refund.payment
        mp_id = payment.info_data.get('id')
        if not mp_id:
            raise PaymentException('No encontramos el pago de Mercado Pago para devolver.')
        partial = refund.amount != payment.amount
        try:
            result = self.api(payment.order.testmode).refund(
                mp_id, amount=refund.amount if partial else None, idempotency_key=refund.full_id,
            )
        except MercadoPagoError as e:
            refund.order.log_action('pretix.plugins.andinamercadopago.error', data={'step': 'refund', 'error': str(e)})
            raise PaymentException('Mercado Pago no aceptó la devolución: {}'.format(e))
        refund.info = json.dumps({k: result.get(k) for k in ('id', 'status', 'amount', 'date_created')})
        refund.save(update_fields=['info'])
        if result.get('status') in ('approved', None):
            refund.done()
        else:
            refund.state = OrderRefund.REFUND_STATE_TRANSIT
            refund.save(update_fields=['state'])

    def shred_payment_info(self, obj):
        info = obj.info_data
        # Los costos del cobro no son datos personales y hacen falta para la contabilidad: se conservan.
        obj.info = json.dumps({k: info.get(k) for k in ('id', 'status', 'transaction_amount', 'currency_id', 'costos')
                               if k in info})
        obj.save(update_fields=['info'])

    def order_pending_mail_render(self, order, payment):
        return ''

    def render_invoice_text(self, order: Order, payment: OrderPayment) -> str:
        if order.status == Order.STATUS_PAID:
            return 'Pagado con Mercado Pago.'
        return ''
