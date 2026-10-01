#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Pruebas del plugin andinamercadopago. La API de Mercado Pago se simula con `responses`:
ninguna prueba se conecta a Mercado Pago.

Correr (dentro del contenedor web; --ds hace falta porque el contenedor define
DJANGO_SETTINGS_MODULE=pretix.settings, que pytest prioriza sobre setup.cfg):
    cd /pretix/src && python3 -m pytest --ds=tests.settings tests/plugins/andinamercadopago -p no:cacheprovider
"""
import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from importlib import import_module
from urllib.parse import urlparse

import pytest
import responses
from django.conf import settings
from django.test import RequestFactory
from django.utils.timezone import now
from django_scopes import scopes_disabled

from pretix.base.models import (
    Event, LogEntry, Order, OrderPayment, OrderPosition, OrderRefund,
    Organizer,
)
from pretix.base.payment import PaymentException
from pretix.base.settings import GlobalSettingsObject
from pretix.plugins.andinamercadopago.mp_api import verify_webhook_signature
from pretix.plugins.andinamercadopago.payment import (
    MercadoPago, external_reference, process_mp_payment,
)

API = 'https://api.mercadopago.com'
SECRET = 'clave-de-prueba'


@pytest.fixture(autouse=True)
def credentials(db):
    gs = GlobalSettingsObject().settings
    gs.set('payment_andinamp_access_token', 'APP_USR-produccion')
    gs.set('payment_andinamp_test_access_token', 'APP_USR-prueba')
    gs.set('payment_andinamp_webhook_secret', SECRET)


@pytest.fixture(autouse=True)
def no_messages(monkeypatch):
    # Igual que en las pruebas de Stripe: no renderizar mensajes acelera las pruebas.
    monkeypatch.setattr("django.contrib.messages.api.add_message", lambda *args, **kwargs: None)


@pytest.fixture
def env():
    with scopes_disabled():
        o = Organizer.objects.create(name='Teatro', slug='teatro')
        event = Event.objects.create(
            organizer=o, name='Hamlet', slug='hamlet', currency='ARS', date_from=now() + timedelta(days=10),
            plugins='pretix.plugins.andinamercadopago', live=True,
        )
        event.settings.set('payment_mercadopago__enabled', True)
        item = event.items.create(name='Platea', default_price=Decimal('30000.00'), admission=True)
        quota = event.quotas.create(name='Platea', size=10)
        quota.items.add(item)
        order = Order.objects.create(
            code='ABC12', event=event, email='comprador@example.com', status=Order.STATUS_PENDING,
            datetime=now(), expires=now() + timedelta(days=2), total=Decimal('60000.00'),
            sales_channel=o.sales_channels.get(identifier='web'),
        )
        for _ in range(2):
            OrderPosition.objects.create(order=order, item=item, price=Decimal('30000.00'))
        payment = order.payments.create(provider='mercadopago', amount=order.total,
                                        state=OrderPayment.PAYMENT_STATE_CREATED)
        yield event, order, payment


def mp_payment(payment, mp_id=111, status='approved', amount=None, **extra):
    data = {
        'id': mp_id, 'status': status, 'status_detail': 'accredited',
        'external_reference': external_reference(payment),
        'transaction_amount': float(amount if amount is not None else payment.amount), 'currency_id': 'ARS',
        'payment_method_id': 'visa', 'payment_type_id': 'credit_card', 'installments': 3, 'live_mode': True,
    }
    data.update(extra)
    return data


def signature(data_id, request_id='req-1', ts='1700000000', secret=SECRET):
    v1 = hmac.new(secret.encode(), 'id:{};request-id:{};ts:{};'.format(data_id, request_id, ts).encode(),
                  hashlib.sha256).hexdigest()
    return {'HTTP_X_SIGNATURE': 'ts={},v1={}'.format(ts, v1), 'HTTP_X_REQUEST_ID': request_id}


def return_path(event, payment):
    return urlparse(MercadoPago(event).return_url(payment)).path


def webhook(client, event, data_id, headers):
    return client.post(
        '/{}/{}/mercadopago/webhook/?data.id={}&type=payment'.format(event.organizer.slug, event.slug, data_id),
        json.dumps({'type': 'payment', 'action': 'payment.updated', 'data': {'id': str(data_id)}}),
        content_type='application/json', **headers,
    )


# ---------- Firma de los avisos ----------

def test_signature_valid_and_invalid():
    headers = signature('123')
    assert verify_webhook_signature(SECRET, headers['HTTP_X_SIGNATURE'], 'req-1', '123')
    assert not verify_webhook_signature('otra-clave', headers['HTTP_X_SIGNATURE'], 'req-1', '123')
    assert not verify_webhook_signature(SECRET, headers['HTTP_X_SIGNATURE'], 'req-1', '999')
    assert not verify_webhook_signature(SECRET, 'ts=1', 'req-1', '123')
    assert not verify_webhook_signature(SECRET, '', None, '123')


# ---------- Disponibilidad en el checkout ----------

@pytest.mark.django_db
def test_allowed_only_in_ars_with_credentials(env):
    event, order, payment = env
    request = RequestFactory().get('/')
    request.session = import_module(settings.SESSION_ENGINE).SessionStore()
    request.event = event
    request.sales_channel = event.organizer.sales_channels.get(identifier='web')
    with scopes_disabled():
        assert MercadoPago(event).is_allowed(request, Decimal('100.00'))
        event.currency = 'USD'
        assert not MercadoPago(event).is_allowed(request, Decimal('100.00'))
        event.currency = 'ARS'
        GlobalSettingsObject().settings.delete('payment_andinamp_access_token')
        assert not MercadoPago(event).is_allowed(request, Decimal('100.00'))


# ---------- Crear el pago (preferencia) ----------

@pytest.mark.django_db
@responses.activate
def test_execute_payment_creates_preference(env):
    event, order, payment = env
    responses.add(responses.POST, API + '/checkout/preferences', json={
        'id': 'pref-1', 'init_point': 'https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=pref-1'})
    request = RequestFactory().get('/')
    request.event = event
    with scopes_disabled():
        url = MercadoPago(event).execute_payment(request, payment)
    assert url.endswith('pref_id=pref-1')
    body = json.loads(responses.calls[0].request.body)
    assert responses.calls[0].request.headers['Authorization'] == 'Bearer APP_USR-produccion'
    assert body['items'][0]['unit_price'] == 60000.0
    assert body['items'][0]['currency_id'] == 'ARS'
    assert body['binary_mode'] is True
    assert {t['id'] for t in body['payment_methods']['excluded_payment_types']} == {'ticket', 'atm'}
    assert body['external_reference'] == 'teatro/hamlet/ABC12-P-1'
    assert 'notification_url' not in body  # el sitio de pruebas no es https
    payment.refresh_from_db()
    assert payment.info_data['preference_id'] == 'pref-1'


@pytest.mark.django_db
@responses.activate
def test_execute_payment_uses_test_credentials_in_test_mode(env):
    event, order, payment = env
    order.testmode = True
    order.save()
    responses.add(responses.POST, API + '/checkout/preferences', json={'id': 'p', 'init_point': 'https://mp/x'})
    request = RequestFactory().get('/')
    request.event = event
    with scopes_disabled():
        MercadoPago(event).execute_payment(request, payment)
    assert responses.calls[0].request.headers['Authorization'] == 'Bearer APP_USR-prueba'


@pytest.mark.django_db
@responses.activate
def test_execute_payment_error_is_reported(env):
    event, order, payment = env
    responses.add(responses.POST, API + '/checkout/preferences', status=400, json={'message': 'invalid items'})
    request = RequestFactory().get('/')
    request.event = event
    with scopes_disabled():
        with pytest.raises(PaymentException):
            MercadoPago(event).execute_payment(request, payment)
        assert order.all_logentries().filter(action_type='pretix.plugins.andinamercadopago.error').exists()


# ---------- Vuelta del comprador ----------

@pytest.mark.django_db
@responses.activate
def test_return_approved_marks_order_paid(env, client):
    event, order, payment = env
    responses.add(responses.GET, API + '/v1/payments/111', json=mp_payment(payment))
    r = client.get(return_path(event, payment), {'payment_id': '111', 'status': 'approved'})
    assert r.status_code == 302 and 'paid=yes' in r['Location']
    with scopes_disabled():
        order.refresh_from_db()
        payment.refresh_from_db()
    assert order.status == Order.STATUS_PAID
    assert payment.state == OrderPayment.PAYMENT_STATE_CONFIRMED
    assert payment.info_data['id'] == 111


@pytest.mark.django_db
def test_return_with_wrong_hash_is_404(env, client):
    event, order, payment = env
    path = return_path(event, payment)
    parts = path.rstrip('/').split('/')
    parts[-2] = '0' * 64
    assert client.get('/'.join(parts) + '/', {'payment_id': '111'}).status_code == 404


@pytest.mark.django_db
@responses.activate
def test_return_rejected_fails_payment(env, client):
    event, order, payment = env
    responses.add(responses.GET, API + '/v1/payments/222', json=mp_payment(payment, 222, status='rejected'))
    client.get(return_path(event, payment), {'payment_id': '222'})
    with scopes_disabled():
        order.refresh_from_db()
        payment.refresh_from_db()
    assert payment.state == OrderPayment.PAYMENT_STATE_FAILED
    assert order.status == Order.STATUS_PENDING  # el comprador puede reintentar


@pytest.mark.django_db
@responses.activate
def test_return_without_payment_keeps_payment_open(env, client):
    event, order, payment = env
    responses.add(responses.GET, API + '/v1/payments/search', json={'results': []})
    client.get(return_path(event, payment), {'payment_id': 'null', 'status': 'null'})
    with scopes_disabled():
        payment.refresh_from_db()
    assert payment.state == OrderPayment.PAYMENT_STATE_CREATED


@pytest.mark.django_db
@responses.activate
def test_return_old_rejected_attempt_does_not_undo_paid_order(env, client):
    """Volver a abrir el link de un intento rechazado no puede cancelar un pedido ya pagado."""
    event, order, payment = env
    responses.add(responses.GET, API + '/v1/payments/111', json=mp_payment(payment))
    client.get(return_path(event, payment), {'payment_id': '111'})
    responses.add(responses.GET, API + '/v1/payments/333', json=mp_payment(payment, 333, status='rejected'))
    client.get(return_path(event, payment), {'payment_id': '333'})
    with scopes_disabled():
        order.refresh_from_db()
        payment.refresh_from_db()
    assert order.status == Order.STATUS_PAID
    assert payment.state == OrderPayment.PAYMENT_STATE_CONFIRMED


# ---------- Validaciones de process_mp_payment ----------

@pytest.mark.django_db
def test_amount_mismatch_is_not_confirmed(env):
    event, order, payment = env
    with scopes_disabled():
        message = process_mp_payment(payment, mp_payment(payment, amount=Decimal('100.00')), source='return')
        payment.refresh_from_db()
        assert message
        assert payment.state == OrderPayment.PAYMENT_STATE_CREATED
        assert order.all_logentries().filter(action_type='pretix.plugins.andinamercadopago.amount_mismatch').exists()


@pytest.mark.django_db
def test_wrong_currency_is_not_confirmed(env):
    event, order, payment = env
    with scopes_disabled():
        process_mp_payment(payment, mp_payment(payment, currency_id='USD'), source='return')
        payment.refresh_from_db()
    assert payment.state == OrderPayment.PAYMENT_STATE_CREATED


@pytest.mark.django_db
def test_reference_of_another_payment_is_ignored(env):
    event, order, payment = env
    with scopes_disabled():
        process_mp_payment(payment, mp_payment(payment, external_reference='otro/evento/ZZZ-P-1'), source='webhook')
        payment.refresh_from_db()
    assert payment.state == OrderPayment.PAYMENT_STATE_CREATED


@pytest.mark.django_db
def test_pending_status_sets_payment_pending(env):
    event, order, payment = env
    with scopes_disabled():
        process_mp_payment(payment, mp_payment(payment, status='in_process'), source='webhook')
        payment.refresh_from_db()
    assert payment.state == OrderPayment.PAYMENT_STATE_PENDING


# ---------- Avisos automáticos (webhook) ----------

@pytest.mark.django_db
@responses.activate
def test_webhook_signed_marks_order_paid(env, client):
    event, order, payment = env
    responses.add(responses.GET, API + '/v1/payments/444', json=mp_payment(payment, 444))
    r = webhook(client, event, 444, signature('444'))
    assert r.status_code == 200
    with scopes_disabled():
        order.refresh_from_db()
    assert order.status == Order.STATUS_PAID


@pytest.mark.django_db
@responses.activate
def test_webhook_bad_signature_is_rejected_without_calling_mp(env, client):
    event, order, payment = env
    r = webhook(client, event, 444, signature('444', secret='otra-clave'))
    assert r.status_code == 401
    assert len(responses.calls) == 0


@pytest.mark.django_db
@responses.activate
def test_webhook_ignores_other_topics_and_unknown_payments(env, client):
    event, order, payment = env
    r = client.post('/teatro/hamlet/mercadopago/webhook/?type=merchant_order&data.id=1', '{}',
                    content_type='application/json')
    assert r.status_code == 200 and len(responses.calls) == 0
    responses.add(responses.GET, API + '/v1/payments/555',
                  json=mp_payment(payment, 555, external_reference='teatro/otro-evento/XYZ-P-1'))
    assert webhook(client, event, 555, signature('555')).status_code == 200
    with scopes_disabled():
        payment.refresh_from_db()
    assert payment.state == OrderPayment.PAYMENT_STATE_CREATED


@pytest.mark.django_db
@responses.activate
def test_webhook_registers_refund_made_in_mercadopago(env, client):
    event, order, payment = env
    with scopes_disabled():
        process_mp_payment(payment, mp_payment(payment, 666), source='return')
    responses.add(responses.GET, API + '/v1/payments/666', json=mp_payment(
        payment, 666, status='refunded', transaction_amount_refunded=60000.0))
    webhook(client, event, 666, signature('666'))
    with scopes_disabled():
        refunds = list(payment.refunds.all())
    assert len(refunds) == 1
    assert refunds[0].amount == Decimal('60000.00')
    assert refunds[0].state == OrderRefund.REFUND_STATE_EXTERNAL


# ---------- Devoluciones desde pretix ----------

@pytest.mark.django_db
@responses.activate
def test_partial_refund(env):
    event, order, payment = env
    with scopes_disabled():
        process_mp_payment(payment, mp_payment(payment, 777), source='return')
        payment.refresh_from_db()
        refund = payment.refunds.create(order=order, amount=Decimal('30000.00'), provider='mercadopago',
                                        state=OrderRefund.REFUND_STATE_CREATED,
                                        source=OrderRefund.REFUND_SOURCE_ADMIN)
        responses.add(responses.POST, API + '/v1/payments/777/refunds',
                      json={'id': 9001, 'status': 'approved', 'amount': 30000.0})
        MercadoPago(event).execute_refund(refund)
        refund.refresh_from_db()
    assert refund.state == OrderRefund.REFUND_STATE_DONE
    assert json.loads(responses.calls[0].request.body) == {'amount': 30000.0}
    assert responses.calls[0].request.headers['X-Idempotency-Key'] == refund.full_id


@pytest.mark.django_db
@responses.activate
def test_full_refund_sends_no_amount(env):
    event, order, payment = env
    with scopes_disabled():
        process_mp_payment(payment, mp_payment(payment, 888), source='return')
        payment.refresh_from_db()
        refund = payment.refunds.create(order=order, amount=payment.amount, provider='mercadopago',
                                        state=OrderRefund.REFUND_STATE_CREATED,
                                        source=OrderRefund.REFUND_SOURCE_ADMIN)
        responses.add(responses.POST, API + '/v1/payments/888/refunds', json={'id': 9002, 'status': 'approved'})
        MercadoPago(event).execute_refund(refund)
    assert json.loads(responses.calls[0].request.body) == {}


@pytest.mark.django_db
@responses.activate
def test_refund_rejected_by_mercadopago_raises(env):
    event, order, payment = env
    with scopes_disabled():
        process_mp_payment(payment, mp_payment(payment, 999), source='return')
        payment.refresh_from_db()
        refund = payment.refunds.create(order=order, amount=payment.amount, provider='mercadopago',
                                        state=OrderRefund.REFUND_STATE_CREATED,
                                        source=OrderRefund.REFUND_SOURCE_ADMIN)
        responses.add(responses.POST, API + '/v1/payments/999/refunds', status=400,
                      json={'message': 'insufficient_amount'})
        with pytest.raises(PaymentException):
            MercadoPago(event).execute_refund(refund)


# ---------- Textos del historial ----------

@pytest.mark.django_db
def test_history_texts_are_readable(env):
    event, order, payment = env
    with scopes_disabled():
        process_mp_payment(payment, mp_payment(payment, 4242), source='webhook')
        order.log_action('pretix.plugins.andinamercadopago.error', data={'step': 'refund', 'error': 'sin saldo'})
        order.log_action('pretix.plugins.andinamercadopago.amount_mismatch',
                         data={'id': 5, 'transaction_amount': 100.0, 'currency_id': 'ARS'})
        order.log_action('pretix.plugins.andinamercadopago.confirm_failed', data={'error': 'cupo agotado'})
        texts = {e.action_type: str(e.display()) for e in LogEntry.objects.filter(
            action_type__startswith='pretix.plugins.andinamercadopago')}
    assert texts['pretix.plugins.andinamercadopago.event'] == (
        'Mercado Pago informó el pago #4242: aprobado (visa en 3 cuotas, accredited), por aviso automático.')
    assert texts['pretix.plugins.andinamercadopago.error'] == 'Error de Mercado Pago al hacer la devolución: sin saldo'
    assert '#5 por 100.0 ARS' in texts['pretix.plugins.andinamercadopago.amount_mismatch']
    assert 'cupo agotado' in texts['pretix.plugins.andinamercadopago.confirm_failed']
    assert not any(t.startswith('pretix.plugins') for t in texts.values())
