#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Paquete para la imprenta (ZIP) con los boletos que generó AndinaTickets:

- entradas.pdf: una entrada por hoja, con el mismo diseño que las entradas online (QR,
  evento, fecha, sector, fila y butaca). Se puede imprimir tal cual.
- qr/<código>.png: el QR de cada boleto, para que la imprenta lo ponga en su propio diseño.
- planilla.csv: la lista de códigos con su butaca, para controlar.
- LEEME.txt: instrucciones para la imprenta.

El QR contiene exactamente el código de la entrada: es lo que lee el escáner en la puerta.
Los boletos de venta recién entran en la puerta cuando se venden en la boletería.
"""
import csv
import io
import zipfile

import qrcode
from django.utils.formats import date_format
from django.utils.text import slugify
from pypdf import PdfReader, PdfWriter

from pretix.base.models import Order, OrderPosition
from pretix.plugins.ticketoutputpdf.ticketoutput import PdfTicketOutput

from .boleteria import lote_orders

LEEME = """Boletos para imprimir - {event}
{date}

Contenido:
- entradas.pdf: una entrada por hoja, lista para imprimir tal cual.
- qr/: el código QR de cada boleto como imagen. El nombre del archivo es el código.
- planilla.csv: la lista de boletos (código, sector, fila, butaca, producto, tipo y precio).

Para la imprenta:
- Cada QR contiene exactamente el código del boleto. Es lo que se escanea en la puerta:
  no hay que cambiarlo, recortarlo ni redibujarlo.
- Tamaño mínimo del QR impreso: 2,5 x 2,5 cm, con un margen blanco alrededor.
- Conviene imprimir también el código en letras debajo del QR, por si hay que tipearlo.
- Cada boleto es único: no imprimir copias del mismo código.
{sale_note}
Cantidad de boletos: {count}
"""
SALE_NOTE = """- Los boletos de venta no entran en la puerta hasta que se venden en la boletería del
  teatro: un boleto perdido sin vender no sirve.
"""


def qr_png(code):
    img = qrcode.make(code, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def package_positions(orders):
    """Boletos del lote que se imprimen: sin los anulados."""
    return list(OrderPosition.objects.filter(order__in=orders).exclude(
        order__status__in=(Order.STATUS_CANCELED, Order.STATUS_EXPIRED),
    ).select_related('item', 'seat', 'subevent', 'order').order_by('seat__sorting_rank', 'pk'))


def tickets_pdf(event, positions):
    """Una hoja por boleto, con el diseño de las entradas online (PDF de pretix)."""
    output = PdfTicketOutput(event)
    writer = PdfWriter()
    for p in positions:
        _name, _ctype, pdf = output.generate(p)
        for page in PdfReader(io.BytesIO(pdf)).pages:
            writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def planilla(positions):
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';')
    writer.writerow(['codigo', 'sector', 'fila', 'butaca', 'producto', 'tipo', 'precio'])
    for p in positions:
        seat = p.seat
        writer.writerow([
            p.secret,
            seat.zone_name if seat else '',
            (seat.row_label or seat.row_name) if seat else '',
            (seat.seat_label or seat.seat_number) if seat else '',
            str(p.item.name),
            'Cortesía' if p.price == 0 else 'Venta',
            '{:.2f}'.format(p.price).replace('.', ','),
        ])
    # Con BOM, para que Excel abra bien los acentos.
    return '﻿' + out.getvalue()


def printer_package(event, lote):
    """Paquete de un lote generado. Devuelve (nombre de archivo, contenido del ZIP)."""
    positions = package_positions(lote_orders(event, lote))
    subevent = positions[0].subevent if positions else None
    when = (subevent or event).date_from
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('LEEME.txt', LEEME.format(
            event=event.name, date=date_format(when.astimezone(event.timezone), 'DATETIME_FORMAT'),
            count=len(positions), sale_note=SALE_NOTE if any(p.price for p in positions) else ''))
        z.writestr('planilla.csv', planilla(positions).encode('utf-8'))
        for p in positions:
            z.writestr('qr/{}.png'.format(p.secret), qr_png(p.secret))
        if positions:
            z.writestr('entradas.pdf', tickets_pdf(event, positions))
    filename = 'imprenta-{}-lote-{}.zip'.format(slugify(event.slug), lote)
    return filename, buf.getvalue()
