#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Cliente mínimo de la API de Mercado Pago (Checkout Pro), con ``requests``.

Solo usa lo necesario: crear una preferencia de pago, consultar un pago, buscar pagos
por referencia externa y devolver dinero. La documentación de Mercado Pago es la fuente
de verdad para los campos: https://www.mercadopago.com.ar/developers
"""
import hashlib
import hmac
import logging

import requests

logger = logging.getLogger(__name__)

API_BASE = 'https://api.mercadopago.com'
TIMEOUT = 20


class MercadoPagoError(Exception):
    def __init__(self, message, status=None, data=None):
        super().__init__(message)
        self.status = status
        self.data = data or {}


class MercadoPagoAPI:
    def __init__(self, access_token):
        self.access_token = access_token

    def _request(self, method, path, json=None, params=None, idempotency_key=None):
        headers = {'Authorization': 'Bearer {}'.format(self.access_token)}
        if idempotency_key:
            headers['X-Idempotency-Key'] = idempotency_key
        try:
            r = requests.request(method, API_BASE + path, json=json, params=params, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            logger.exception('Mercado Pago: error de conexión')
            raise MercadoPagoError('No pudimos comunicarnos con Mercado Pago. Probá de nuevo en unos minutos.') from e
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400:
            message = data.get('message') or data.get('error') or r.text[:200]
            logger.warning('Mercado Pago respondió %s en %s %s: %s', r.status_code, method, path, message)
            raise MercadoPagoError(message, status=r.status_code, data=data)
        return data

    def create_preference(self, preference):
        return self._request('POST', '/checkout/preferences', json=preference)

    def get_payment(self, payment_id):
        return self._request('GET', '/v1/payments/{}'.format(int(payment_id)))

    def search_payments(self, external_reference):
        data = self._request('GET', '/v1/payments/search', params={
            'external_reference': external_reference, 'sort': 'date_created', 'criteria': 'desc',
        })
        return data.get('results', [])

    def refund(self, payment_id, amount=None, idempotency_key=None):
        body = {'amount': float(amount)} if amount is not None else {}
        return self._request('POST', '/v1/payments/{}/refunds'.format(int(payment_id)), json=body,
                             idempotency_key=idempotency_key)


def verify_webhook_signature(secret, signature_header, request_id, data_id):
    """
    Verifica la firma de una notificación (encabezado ``x-signature``: "ts=...,v1=...").
    Mercado Pago firma con HMAC-SHA256 el texto "id:<data.id>;request-id:<x-request-id>;ts:<ts>;".
    """
    parts = {}
    for chunk in (signature_header or '').split(','):
        k, _, v = chunk.strip().partition('=')
        parts[k] = v
    ts, v1 = parts.get('ts'), parts.get('v1')
    if not ts or not v1:
        return False
    manifest = 'id:{};'.format(str(data_id).lower())
    if request_id:
        manifest += 'request-id:{};'.format(request_id)
    manifest += 'ts:{};'.format(ts)
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)
