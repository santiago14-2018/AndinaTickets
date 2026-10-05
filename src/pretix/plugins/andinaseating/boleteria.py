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
- Cada carga es de venta (al precio del producto) o de cortesía (regalo, a $0). Una
  cortesía es simplemente una entrada de precio 0: así la reconocen la boletería y el
  informe del productor, sin campos extra.
- También se pueden generar los boletos al revés: AndinaTickets crea los códigos y arma
  el paquete para la imprenta (ver imprenta.py). Sirve para eventos con y sin numerar.
"""
import csv
import io
import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.timezone import now
from i18nfield.strings import LazyI18nString

from pretix.base.models import CachedFile, Order, OrderPosition
from pretix.base.services.modelimport import DataImportError, import_orders
from pretix.base.services.orders import OrderChangeManager, _cancel_order

CHANNEL_IDENTIFIER = 'api.boleteria'
COURTESY_CHANNEL = 'api.cortesias'  # cortesías por email (cortesias.py)
KIND_SALE = 'venta'
KIND_COURTESY = 'cortesia'
MAX_GENERATE = 500  # boletos por generación
GENERATED_COMMENT = 'Boletos generados para la imprenta'

CSV_COLUMNS = {
    'code': ('codigo', 'código', 'code', 'barcode', 'codigo_barras', 'código de barras'),
    'row': ('fila', 'row'),
    'seat': ('butaca', 'asiento', 'numero', 'número', 'seat'),
    'sector': ('sector', 'zona', 'zone'),
}


CHANNEL_LABELS = {
    CHANNEL_IDENTIFIER: {'es': 'Boletería', 'en': 'Box office'},
    COURTESY_CHANNEL: {'es': 'Cortesías', 'en': 'Complimentary tickets'},
}


def get_channel(organizer, identifier=CHANNEL_IDENTIFIER):
    channel, _ = organizer.sales_channels.get_or_create(
        identifier=identifier,
        defaults={'type': 'api', 'label': LazyI18nString(CHANNEL_LABELS[identifier])},
    )
    return channel


def enable_for_event(event, identifier=CHANNEL_IDENTIFIER):
    """
    Crea el canal si hace falta y le permite usar butacas bloqueadas en este evento (las
    reservadas para boletería también se pueden dar de cortesía).
    """
    channel = get_channel(event.organizer, identifier)
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


def is_courtesy(position):
    return position.price == 0


def run_import(event, subevent, user, channel, rows, comment, courtesy=False, email=''):
    """
    Crea UN pedido pagado con el importador de pedidos de pretix (que valida producto, butaca
    y código). ``rows``: dicts con item (pk), y opcionales seat (seat_guid) y secret; sin
    secret, pretix genera el código. Las cortesías van a precio 0. El comentario lleva un
    número de lote único: con él se encuentra el pedido creado (el importador no lo devuelve).
    """
    lote = secrets.token_hex(4).upper()
    comment = '{} · lote {}'.format(comment, lote)
    cols = ['item', 'seat', 'secret', 'subevent', 'price', 'email']
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(cols)
    for r in rows:
        writer.writerow([r['item'], r.get('seat', ''), r.get('secret', ''), subevent.pk if subevent else '',
                         '0' if courtesy else '', email])

    cf = CachedFile.objects.create(expires=now() + timedelta(days=1), date=now(),
                                   filename='import.csv', type='text/csv')
    cf.file.save('import.csv', ContentFile(out.getvalue().encode('utf-8')))
    settings = {
        'orders': 'one',
        'status': 'paid',
        'testmode': event.testmode,
        'item': 'csv:item',
        'sales_channel': 'static:' + channel.identifier,
        'comment': 'static:' + comment,
    }
    if any(r.get('seat') for r in rows):
        settings['seat'] = 'csv:seat'
    if any(r.get('secret') for r in rows):
        settings['secret'] = 'csv:secret'
    if courtesy:
        settings['price'] = 'csv:price'
    if subevent:
        settings['subevent'] = 'csv:subevent'
    if email:
        settings['email'] = 'csv:email'
    result = import_orders.apply(kwargs={
        'event': event.pk, 'fileid': str(cf.id), 'settings': settings, 'locale': 'es', 'user': user.pk,
        'charset': 'utf-8',
    })
    if result.failed():
        exc = result.result
        if isinstance(exc, (DataImportError, ValidationError)):
            raise ValidationError(str(exc))
        raise exc
    return Order.objects.get(event=event, sales_channel=channel, comment=comment)


def import_tickets(event, subevent, resolved, user, filename, kind=KIND_SALE):
    """
    Crea un pedido pagado en el canal Boletería con una entrada por boleto impreso
    (código = código del boleto) y deja esas butacas reservadas para boletería.
    Las cortesías se cargan a precio 0.
    """
    courtesy = kind == KIND_COURTESY
    channel = enable_for_event(event)
    rows = [{'item': seat.product_id, 'seat': seat.seat_guid, 'secret': code} for code, seat in resolved]
    run_import(event, subevent, user, channel, rows,
               '{} ({})'.format('Cortesías impresas' if courtesy else 'Boletos impresos', filename),
               courtesy=courtesy)
    (subevent or event).seats.filter(pk__in=[s.pk for _, s in resolved]).update(blocked=True)
    return len(resolved)


# ---------------------------------------------------------------- elegir butacas o cantidad

def seats_by_guid(target, guids, channel):
    """Butacas elegidas en el plano, libres para ``channel``. Devuelve ([Seat], [errores])."""
    guids = [g for g in dict.fromkeys(guids) if g]
    if not guids:
        return [], ['Elegí al menos una butaca en el plano.']
    if len(guids) > MAX_GENERATE:
        return [], ['Son demasiadas butacas juntas (máximo {}).'.format(MAX_GENERATE)]
    seats = {s.seat_guid: s for s in target.seats.filter(seat_guid__in=guids).select_related('product')}
    free = set(target.free_seats(sales_channel=channel.identifier).values_list('pk', flat=True))
    out, errors = [], []
    for g in guids:
        seat = seats.get(g)
        if not seat:
            errors.append('La butaca {} no existe en esta sala.'.format(g))
        elif not seat.product:
            errors.append('La butaca {} no tiene producto (revisá Plan de butacas).'.format(seat))
        elif seat.pk not in free:
            errors.append('La butaca {} ya está vendida o reservada.'.format(seat))
        else:
            out.append(seat)
    return out, errors


def unnumbered_items(event):
    """Productos que se pueden entregar por cantidad (sin butaca)."""
    return event.items.filter(active=True, admission=True, variations__isnull=True).order_by('position', 'pk')


def check_quota(item, subevent, quantity):
    """Error si no quedan ``quantity`` lugares en los cupos del producto (el importador no los mira)."""
    _avail, num = item.check_quotas(subevent=subevent, count_waitinglist=False)
    if num is None or num >= quantity:  # None = sin límite
        return None
    if not item.quotas.filter(subevent=subevent).exists():
        return '"{}" no tiene cupo{}: creale uno en Cuotas.'.format(item.name, ' en esta fecha' if subevent else '')
    return 'De "{}" quedan {} lugar{}; pediste {}.'.format(item.name, num, '' if num == 1 else 'es', quantity)


def rows_for(seats=None, item=None, quantity=0):
    if seats:
        return [{'item': s.product_id, 'seat': s.seat_guid} for s in seats]
    return [{'item': item.pk} for _ in range(quantity)]


def generate_tickets(event, subevent, user, kind, seats=None, item=None, quantity=0):
    """
    AndinaTickets crea los códigos de boletos que va a imprimir la imprenta (canal Boletería):
    con butacas elegidas en el plano o, sin numerar, una cantidad de un producto. Las butacas
    quedan reservadas para boletería, igual que al cargar boletos de la imprenta. Devuelve el
    pedido creado; su paquete para la imprenta lo arma imprenta.printer_package.
    """
    courtesy = kind == KIND_COURTESY
    channel = enable_for_event(event)
    comment = '{} ({})'.format(GENERATED_COMMENT, 'cortesías' if courtesy else 'venta')
    order = run_import(event, subevent, user, channel, rows_for(seats, item, quantity), comment, courtesy=courtesy)
    if seats:
        (subevent or event).seats.filter(pk__in=[s.pk for s in seats]).update(blocked=True)
    return order


def generated_orders(event, subevent):
    return Order.objects.filter(
        event=event, sales_channel__identifier=CHANNEL_IDENTIFIER, comment__startswith=GENERATED_COMMENT,
        all_positions__subevent=subevent,
    ).distinct().order_by('-datetime')


def cancel_ticket(position, user):
    """Anula un boleto: su código deja de servir en la puerta. La butaca sigue reservada."""
    order = position.order
    if order.positions.count() == 1:
        _cancel_order(order.pk, user, send_mail=False)
    else:
        ocm = OrderChangeManager(order, user=user, notify=False)
        ocm.cancel(position)
        ocm.commit()
