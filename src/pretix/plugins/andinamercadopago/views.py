#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
import json
import logging
import re

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from pretix.base.models import Order, OrderPayment
from pretix.helpers.http import redirect_to_url
from pretix.multidomain.urlreverse import eventreverse

from .mp_api import MercadoPagoAPI, MercadoPagoError, verify_webhook_signature
from .payment import (
    IDENTIFIER, SECRET_TAG, access_token, external_reference, global_setting,
    process_mp_payment,
)

logger = logging.getLogger(__name__)


@method_decorator(xframe_options_exempt, 'dispatch')
class ReturnView(View):
    """
    El comprador vuelve de Mercado Pago (pagó, lo rechazaron o tocó "volver").
    Consultamos el pago a Mercado Pago y lo llevamos a la página de su pedido.
    """

    def dispatch(self, request, *args, **kwargs):
        try:
            self.order = request.event.orders.get_with_secret_check(
                code=kwargs['order'], received_secret=kwargs['hash'].lower(), tag=SECRET_TAG,
            )
        except Order.DoesNotExist:
            raise Http404('Pedido desconocido')
        self.payment = get_object_or_404(self.order.payments, pk=kwargs['payment'], provider=IDENTIFIER)
        return super().dispatch(request, *args, **kwargs)

    def order_url(self):
        self.order.refresh_from_db()
        return eventreverse(self.request.event, 'presale:event.order', kwargs={
            'order': self.order.code, 'secret': self.order.secret,
        }) + ('?paid=yes' if self.order.status == Order.STATUS_PAID else '')

    def get(self, request, *args, **kwargs):
        api = MercadoPagoAPI(access_token(self.order.testmode))
        mp_id = request.GET.get('payment_id') or request.GET.get('collection_id')
        try:
            if mp_id and mp_id.isdigit():
                data = api.get_payment(mp_id)
            else:
                # Volvió sin pagar, o Mercado Pago no mandó el número: buscamos por referencia.
                results = api.search_payments(external_reference(self.payment))
                data = results[0] if results else None
        except MercadoPagoError:
            messages.error(request, 'No pudimos confirmar el estado del pago con Mercado Pago. '
                                    'Si pagaste, se va a acreditar en unos minutos.')
            return redirect_to_url(self.order_url())

        if not data:
            messages.info(request, 'No se completó el pago. Podés intentarlo de nuevo desde esta página.')
            return redirect_to_url(self.order_url())

        message = process_mp_payment(self.payment, data, source='return')
        if message:
            messages.warning(request, message)
        return redirect_to_url(self.order_url())


REFERENCE_RE = re.compile(r'^(?P<organizer>[^/]+)/(?P<event>[^/]+)/(?P<order>[A-Z0-9]+)-P-(?P<local_id>\d+)$')


@csrf_exempt
@require_POST
def webhook(request, *args, **kwargs):
    """
    Aviso de Mercado Pago. Solo usamos el número de pago para volver a consultarlo a la API:
    aunque alguien falsificara un aviso, no podría marcar un pago como aprobado.
    Si hay una clave secreta cargada, además verificamos la firma.
    """
    try:
        body = json.loads(request.body.decode() or '{}')
    except ValueError:
        body = {}
    kind = request.GET.get('type') or request.GET.get('topic') or body.get('type')
    data_id = request.GET.get('data.id') or (body.get('data') or {}).get('id') or request.GET.get('id')
    if kind != 'payment' or not data_id or not str(data_id).isdigit():
        return HttpResponse(status=200)  # avisos que no son de pagos: no hay nada que hacer

    secret = global_setting('webhook_secret')
    signature = request.headers.get('x-signature')
    if secret and signature and not verify_webhook_signature(
            secret, signature, request.headers.get('x-request-id'), data_id):
        logger.warning('Mercado Pago: firma inválida en aviso del pago %s', data_id)
        return HttpResponse('Firma inválida', status=401)

    data = None
    for testmode in (False, True):
        token = access_token(testmode)
        if not token:
            continue
        try:
            data = MercadoPagoAPI(token).get_payment(data_id)
            break
        except MercadoPagoError as e:
            if e.status != 404:
                return HttpResponse('Error consultando el pago', status=502)  # Mercado Pago reintenta
    if not data:
        return HttpResponse(status=200)

    m = REFERENCE_RE.match(data.get('external_reference') or '')
    if not m or m.group('organizer') != request.organizer.slug or m.group('event') != request.event.slug:
        return HttpResponse(status=200)
    try:
        payment = OrderPayment.objects.get(
            order__event=request.event, order__code=m.group('order'), local_id=m.group('local_id'),
            provider=IDENTIFIER,
        )
    except OrderPayment.DoesNotExist:
        return HttpResponse(status=200)

    process_mp_payment(payment, data, source='webhook')
    return HttpResponse(status=200)
