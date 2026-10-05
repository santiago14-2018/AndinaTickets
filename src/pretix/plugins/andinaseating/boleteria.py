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
- Los boletos de venta se activan al venderlos: hasta que el boletero los vende en el
  mostrador (sell_tickets) son pedidos pendientes y no entran en la puerta. Así un boleto
  perdido sin vender no sirve, y los informes muestran lo vendido de verdad (cuándo, por
  quién y con qué medio de pago). Las cortesías de papel son válidas desde que se cargan.
"""
import csv
import io
import json
import secrets
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.timezone import now
from i18nfield.strings import LazyI18nString

from pretix.base.models import (
    CachedFile, Order, OrderPayment, OrderPosition, Quota,
)
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


def lote_comment(comment, lote):
    return '{} · lote {}'.format(comment, lote)


def run_import(event, subevent, user, channel, rows, comment, courtesy=False, email='', pending=False):
    """
    Crea entradas con el importador de pedidos de pretix (que valida producto, butaca y
    código). ``rows``: dicts con item (pk), y opcionales seat (seat_guid) y secret; sin secret,
    pretix genera el código. Las cortesías van a precio 0.

    - Pagadas (cortesías): un solo pedido para todas.
    - ``pending`` (boletos de papel para vender): un pedido pendiente por boleto, así cada uno se
      vende por separado (sell_tickets). Un pedido pendiente no entra en la puerta. Vencen al día
      siguiente de la función: lo que no se vendió se anula solo.

    El comentario lleva un número de lote único, con el que se encuentran los pedidos creados
    (el importador no los devuelve). Devuelve (lote, [pedidos]).
    """
    lote = secrets.token_hex(4).upper()
    comment = lote_comment(comment, lote)
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
        'orders': 'many' if pending else 'one',
        'status': 'pending' if pending else 'paid',
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
    orders = list(Order.objects.filter(event=event, sales_channel=channel, comment=comment).order_by('pk'))
    if pending:
        when = subevent or event
        Order.objects.filter(pk__in=[o.pk for o in orders]).update(
            expires=(when.date_to or when.date_from) + timedelta(days=1))
    return lote, orders


def import_tickets(event, subevent, resolved, user, filename, kind=KIND_SALE):
    """
    Carga los boletos impresos por la imprenta (código = código del boleto) en el canal
    Boletería y deja esas butacas reservadas para boletería. Los de venta quedan sin vender
    hasta que se venden en el mostrador; las cortesías, válidas y a precio 0.
    """
    courtesy = kind == KIND_COURTESY
    channel = enable_for_event(event)
    rows = [{'item': seat.product_id, 'seat': seat.seat_guid, 'secret': code} for code, seat in resolved]
    run_import(event, subevent, user, channel, rows,
               '{} ({})'.format('Cortesías impresas' if courtesy else 'Boletos impresos', filename),
               courtesy=courtesy, pending=not courtesy)
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
    quedan reservadas para boletería. Los de venta quedan sin vender (no entran en la puerta)
    hasta que se venden en el mostrador; las cortesías, válidas. Devuelve (lote, [pedidos]); el
    paquete para la imprenta lo arma imprenta.printer_package.
    """
    courtesy = kind == KIND_COURTESY
    channel = enable_for_event(event)
    comment = '{} ({})'.format(GENERATED_COMMENT, 'cortesías' if courtesy else 'venta')
    lote, orders = run_import(event, subevent, user, channel, rows_for(seats, item, quantity), comment,
                              courtesy=courtesy, pending=not courtesy)
    if seats:
        (subevent or event).seats.filter(pk__in=[s.pk for s in seats]).update(blocked=True)
    return lote, orders


def lote_orders(event, lote):
    return Order.objects.filter(event=event, sales_channel__identifier=CHANNEL_IDENTIFIER,
                                comment__endswith=' · lote {}'.format(lote))


def generated_lotes(event, subevent):
    """Lotes generados para la imprenta en esta fecha, del más nuevo al más viejo."""
    lotes = {}
    positions = OrderPosition.all.filter(
        order__event=event, subevent=subevent, order__sales_channel__identifier=CHANNEL_IDENTIFIER,
        order__comment__startswith=GENERATED_COMMENT,
    ).select_related('order')
    for p in positions:
        lote = p.order.comment.rsplit(' · lote ', 1)[-1]
        g = lotes.setdefault(lote, {'lote': lote, 'datetime': p.order.datetime, 'courtesy': p.price == 0,
                                    'count': 0, 'sold': 0, 'pending': 0, 'canceled': 0})
        g['count'] += 1
        state = ticket_state(p)
        if state in (STATE_SOLD, STATE_VALID):
            g['sold'] += 1
        elif state == STATE_UNSOLD:
            g['pending'] += 1
        else:
            g['canceled'] += 1
    # Un lote anulado entero ya no sirve para nada: no se muestra.
    return sorted((g for g in lotes.values() if g['canceled'] < g['count']),
                  key=lambda g: g['datetime'], reverse=True)


# ---------------------------------------------------------------- vender en el mostrador

STATE_UNSOLD, STATE_SOLD, STATE_VALID, STATE_CANCELED = 'sin vender', 'vendido', 'válido', 'anulado'

PAYMENT_METHODS = (
    ('efectivo', 'Efectivo'),
    ('debito', 'Tarjeta de débito'),
    ('credito', 'Tarjeta de crédito'),
    ('transferencia', 'Transferencia o QR'),
)


def ticket_state(position):
    """Sin vender (pendiente) · vendido (venta pagada) · válido (cortesía) · anulado."""
    if position.canceled or position.order.status in (Order.STATUS_CANCELED, Order.STATUS_EXPIRED):
        return STATE_CANCELED
    if position.order.status == Order.STATUS_PENDING:
        return STATE_UNSOLD
    return STATE_VALID if position.price == 0 else STATE_SOLD


def parse_codes(text):
    return [c for c in dict.fromkeys(line.strip() for line in (text or '').splitlines()) if c]


def sell_tickets(event, codes, method, user):
    """
    Vende en el mostrador los boletos de papel con esos códigos: quedan pagados (medio de pago
    "Boletería" de pretix, con el medio y quién vendió) y desde ahí entran en la puerta. Todo o
    nada: si un código no sirve, no se vende ninguno. Devuelve ([OrderPosition], total).
    """
    if not codes:
        raise ValidationError('Escaneá o escribí al menos un código.')
    if len(codes) > MAX_GENERATE:
        raise ValidationError('Son demasiados boletos juntos (máximo {}).'.format(MAX_GENERATE))
    found = {p.secret: p for p in OrderPosition.all.filter(
        order__event=event, order__sales_channel__identifier=CHANNEL_IDENTIFIER, secret__in=codes,
    ).select_related('order', 'seat', 'item', 'subevent')}
    errors = []
    for code in codes:
        p = found.get(code)
        state = ticket_state(p) if p else None
        if not p:
            errors.append('{}: no es un boleto de papel de este evento.'.format(code))
        elif state == STATE_CANCELED:
            errors.append('{}: está anulado.'.format(code))
        elif state == STATE_SOLD:
            errors.append('{}: ya estaba vendido.'.format(code))
        elif state == STATE_VALID:
            errors.append('{}: es de cortesía, no se vende.'.format(code))
        elif p.order.positions.count() != 1:
            errors.append('{}: está en un pedido con otros boletos; vendelo desde el pedido.'.format(code))
    if errors:
        raise ValidationError(errors)

    label = dict(PAYMENT_METHODS)[method]
    seller = user.email if user else ''
    positions = [found[c] for c in codes]
    total = Decimal('0.00')
    for p in positions:
        order = p.order
        payment = order.payments.create(
            provider='boxoffice', amount=order.pending_sum, state=OrderPayment.PAYMENT_STATE_CREATED,
            info=json.dumps({
                'pos_id': 'AndinaTickets · Boletería', 'receipt_id': '{} · {}'.format(label, seller),
                'payment_type': method, 'payment_data': {}, 'medio': method, 'vendedor': seller,
            }),
        )
        try:
            payment.confirm(user=user, send_mail=False, ignore_date=True)
        except Quota.QuotaExceededException as e:
            raise ValidationError('{}: {}'.format(p.secret, e))
        total += payment.amount
    return positions, total


def cancel_unsold(event, subevent, user):
    """Anula los boletos de papel de venta que no se vendieron (fin de la función). Devuelve cuántos."""
    orders = Order.objects.filter(
        event=event, sales_channel__identifier=CHANNEL_IDENTIFIER, status=Order.STATUS_PENDING,
        all_positions__subevent=subevent,
    ).distinct()
    n = 0
    for order in orders:
        n += order.positions.count()
        _cancel_order(order.pk, user, send_mail=False)
    return n


def box_office_summary(event, subevent):
    """Caja de la boletería en esta fecha: lo vendido por medio de pago y por vendedor."""
    payments = OrderPayment.objects.filter(
        order__event=event, order__sales_channel__identifier=CHANNEL_IDENTIFIER, provider='boxoffice',
        state=OrderPayment.PAYMENT_STATE_CONFIRMED, order__all_positions__subevent=subevent,
    ).distinct().select_related('order')
    labels = dict(PAYMENT_METHODS)
    by_method, by_seller = {}, {}
    total = Decimal('0.00')
    for pay in payments:
        info = pay.info_data
        for key, target in ((labels.get(info.get('medio'), 'Otro'), by_method),
                            (info.get('vendedor') or '—', by_seller)):
            row = target.setdefault(key, {'name': key, 'tickets': 0, 'total': Decimal('0.00')})
            row['tickets'] += pay.order.positions.count()
            row['total'] += pay.amount
        total += pay.amount
    return {
        'by_method': sorted(by_method.values(), key=lambda r: r['name']),
        'by_seller': sorted(by_seller.values(), key=lambda r: r['name']),
        'total': total,
        'tickets': sum(r['tickets'] for r in by_method.values()),
    }


def cancel_ticket(position, user):
    """Anula un boleto: su código deja de servir en la puerta. La butaca sigue reservada."""
    order = position.order
    if order.positions.count() == 1:
        _cancel_order(order.pk, user, send_mail=False)
    else:
        ocm = OrderChangeManager(order, user=user, notify=False)
        ocm.cancel(position)
        ocm.commit()
