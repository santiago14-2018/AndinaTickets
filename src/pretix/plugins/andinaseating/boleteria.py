#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Boletería: butacas reservadas para venta presencial y boletos impresos por una imprenta.

- Las butacas reservadas quedan "bloqueadas" (Seat.blocked): la tienda online no las vende.
- El canal de venta "Boletería" (api.boleteria) sí puede usarlas.
- Los boletos impresos se cargan con un CSV (código, fila, butaca). Cada código queda
  como el código de la entrada en pretix, así que en la puerta se escanea el boleto de
  papel igual que una entrada online. La carga usa el importador de pedidos de pretix.
"""
import csv
import io
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.timezone import now
from i18nfield.strings import LazyI18nString

from pretix.base.models import CachedFile, OrderPosition
from pretix.base.services.modelimport import DataImportError, import_orders
from pretix.base.services.orders import OrderChangeManager, _cancel_order

CHANNEL_IDENTIFIER = 'api.boleteria'

CSV_COLUMNS = {
    'code': ('codigo', 'código', 'code', 'barcode', 'codigo_barras', 'código de barras'),
    'row': ('fila', 'row'),
    'seat': ('butaca', 'asiento', 'numero', 'número', 'seat'),
    'sector': ('sector', 'zona', 'zone'),
}


def get_channel(organizer):
    channel, _ = organizer.sales_channels.get_or_create(
        identifier=CHANNEL_IDENTIFIER,
        defaults={'type': 'api', 'label': LazyI18nString({'es': 'Boletería', 'en': 'Box office'})},
    )
    return channel


def enable_for_event(event):
    """Crea el canal si hace falta y le permite vender butacas bloqueadas en este evento."""
    channel = get_channel(event.organizer)
    allowed = list(event.settings.seating_allow_blocked_seats_for_channel or [])
    if channel.identifier not in allowed:
        event.settings.seating_allow_blocked_seats_for_channel = allowed + [channel.identifier]
    return channel


def boleteria_positions(event, subevent):
    # OrderPosition.all incluye las anuladas, para mostrarlas como "Anulado".
    return OrderPosition.all.filter(
        order__event=event, subevent=subevent, order__sales_channel__identifier=CHANNEL_IDENTIFIER,
    ).select_related('order', 'seat', 'item').prefetch_related('checkins').order_by('seat__sorting_rank', 'pk')


def parse_tickets_csv(content: bytes):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('latin-1')
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    lines = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(lines) < 2:
        raise ValidationError('El CSV está vacío o no tiene encabezado.')

    header = [h.strip().lower() for h in lines[0]]
    col = {}
    for key, names in CSV_COLUMNS.items():
        col[key] = next((i for i, h in enumerate(header) if h in names), None)
    missing = [n for n, k in (('codigo', 'code'), ('fila', 'row'), ('butaca', 'seat')) if col[k] is None]
    if missing:
        raise ValidationError('Faltan columnas en el CSV: {}.'.format(', '.join(missing)))

    out = []
    for n, line in enumerate(lines[1:], start=2):
        def cell(key):
            i = col[key]
            return line[i].strip() if i is not None and i < len(line) else ''
        out.append({'line': n, 'code': cell('code'), 'row': cell('row'), 'seat': cell('seat'),
                    'sector': cell('sector')})
    return out


def resolve_tickets(event, subevent, rows, channel):
    """Devuelve ([(código, Seat)], [errores]). No modifica nada."""
    ev = subevent or event
    seats = list(ev.seats.select_related('product'))
    index = {}
    for s in seats:
        index.setdefault((s.row_name.lower(), s.seat_number.lower()), []).append(s)
    free = set(ev.free_seats(sales_channel=channel.identifier).values_list('pk', flat=True))
    existing = set(OrderPosition.all.filter(
        order__event__organizer=event.organizer, secret__in=[r['code'] for r in rows],
    ).values_list('secret', flat=True))

    resolved, errors, codes, used = [], [], set(), set()
    for r in rows:
        where = 'Línea {}'.format(r['line'])
        if not r['code'] or not r['row'] or not r['seat']:
            errors.append('{}: faltan código, fila o butaca.'.format(where))
            continue
        if r['code'] in codes:
            errors.append('{}: el código {} está repetido en el archivo.'.format(where, r['code']))
            continue
        if r['code'] in existing:
            errors.append('{}: el código {} ya existe en otra entrada.'.format(where, r['code']))
            continue
        matches = index.get((r['row'].lower(), r['seat'].lower()), [])
        if r['sector']:
            matches = [s for s in matches if s.zone_name.lower() == r['sector'].lower()]
        if not matches:
            errors.append('{}: no existe la butaca fila {} butaca {}{}.'.format(
                where, r['row'], r['seat'], ' en el sector ' + r['sector'] if r['sector'] else ''))
            continue
        if len(matches) > 1:
            errors.append('{}: la fila {} butaca {} existe en varios sectores; agregá la columna "sector".'.format(
                where, r['row'], r['seat']))
            continue
        seat = matches[0]
        if seat.pk in used:
            errors.append('{}: la butaca {} está repetida en el archivo.'.format(where, seat))
            continue
        if not seat.product:
            errors.append('{}: la butaca {} no tiene producto (revisá Plan de butacas).'.format(where, seat))
            continue
        if seat.pk not in free:
            errors.append('{}: la butaca {} ya está vendida o reservada.'.format(where, seat))
            continue
        codes.add(r['code'])
        used.add(seat.pk)
        resolved.append((r['code'], seat))
    return resolved, errors


def import_tickets(event, subevent, resolved, user, filename):
    """
    Crea un pedido pagado en el canal Boletería con una entrada por boleto impreso
    (código = código del boleto) y deja esas butacas reservadas para boletería.
    """
    channel = enable_for_event(event)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['item', 'seat', 'secret', 'subevent'])
    for code, seat in resolved:
        writer.writerow([seat.product_id, seat.seat_guid, code, subevent.pk if subevent else ''])

    cf = CachedFile.objects.create(expires=now() + timedelta(days=1), date=now(),
                                   filename='import.csv', type='text/csv')
    cf.file.save('import.csv', ContentFile(out.getvalue().encode('utf-8')))
    settings = {
        'orders': 'one',
        'status': 'paid',
        'testmode': event.testmode,
        'item': 'csv:item',
        'seat': 'csv:seat',
        'secret': 'csv:secret',
        'sales_channel': 'static:' + channel.identifier,
        'comment': 'static:Boletos impresos ({})'.format(filename),
    }
    if subevent:
        settings['subevent'] = 'csv:subevent'
    result = import_orders.apply(kwargs={
        'event': event.pk, 'fileid': str(cf.id), 'settings': settings, 'locale': 'es', 'user': user.pk,
        'charset': 'utf-8',
    })
    if result.failed():
        exc = result.result
        if isinstance(exc, (DataImportError, ValidationError)):
            raise ValidationError(str(exc))
        raise exc

    (subevent or event).seats.filter(pk__in=[s.pk for _, s in resolved]).update(blocked=True)
    return len(resolved)


def cancel_ticket(position, user):
    """Anula un boleto: su código deja de servir en la puerta. La butaca sigue reservada."""
    order = position.order
    if order.positions.count() == 1:
        _cancel_order(order.pk, user, send_mail=False)
    else:
        ocm = OrderChangeManager(order, user=user, notify=False)
        ocm.cancel(position)
        ocm.commit()
