#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Consulta al programa de liquidaciones (aparte y privado, ver ANDINA.md "Caja 3"): la liquidación
de un evento, sus transferencias y el PDF del comprobante. Acá no se calcula nada: solo se muestra
lo que ese programa responde. Si no está configurado o no responde, el portal sigue andando sin
ese recuadro.

Se usa urllib (de Python) y no requests a propósito: pretix bloquea con requests las conexiones a
direcciones privadas (protección para las direcciones que cargan los usuarios, como los webhooks),
y el programa de liquidaciones corre en la misma red. Esta dirección no la escribe ningún usuario:
sale de la configuración del servidor (ANDINA_LIQUIDACIONES_URL).
"""
import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)
TIEMPO = 5  # segundos


def configurado():
    return bool(settings.ANDINA_LIQUIDACIONES_URL and settings.ANDINA_LIQUIDACIONES_CLAVE)


def _get(event, archivo=''):
    """(tipo de contenido, bytes) de /api/portal/<organizador>/<evento>/<archivo>."""
    url = '{}/api/portal/{}/{}/{}'.format(settings.ANDINA_LIQUIDACIONES_URL, quote(event.organizer.slug),
                                          quote(event.slug), archivo)
    pedido = Request(url, headers={'Authorization': 'Bearer {}'.format(settings.ANDINA_LIQUIDACIONES_CLAVE)})
    with urlopen(pedido, timeout=TIEMPO) as r:  # noqa: S310 (dirección fija de la configuración)
        return r.headers.get('Content-Type', ''), r.read()


def consultar(event):
    """{'estado', 'liquidacion', 'transferencias'} del evento, o None si no se pudo consultar."""
    if not configurado():
        return None
    try:
        _tipo, contenido = _get(event)
        datos = json.loads(contenido)
        # Los montos llegan como texto ("45000.00") y las fechas en ISO ("2026-11-02").
        liq = datos.get('liquidacion')
        if liq:
            for k in ('ventas_online', 'comision', 'cargo_boleteria', 'persona_boleteria', 'a_transferir',
                      'transferido', 'saldo'):
                liq[k] = Decimal(liq[k])
        for t in datos.get('transferencias', []):
            t['monto'] = Decimal(t['monto'])
            t['fecha'] = date.fromisoformat(t['fecha']).strftime('%d/%m/%Y')
        return datos
    except (URLError, OSError, ValueError, KeyError, TypeError, InvalidOperation):
        logger.warning('No se pudo consultar la liquidación de %s', event.slug, exc_info=True)
        return None


def pdf(event, numero):
    """El PDF de la liquidación, o None."""
    if not configurado():
        return None
    try:
        tipo, contenido = _get(event, '{}.pdf'.format(int(numero)))
    except (URLError, OSError, ValueError):
        logger.warning('No se pudo traer el PDF de la liquidación %s de %s', numero, event.slug, exc_info=True)
        return None
    return contenido if tipo == 'application/pdf' else None
