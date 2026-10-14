#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.dispatch import receiver
from django.template.loader import get_template
from django.templatetags.static import static
from django.urls import resolve, reverse
from django.utils.html import format_html

from pretix.base.signals import order_fee_calculation
from pretix.base.templatetags.money import money_filter
from pretix.control.signals import nav_event, nav_organizer
from pretix.presale.signals import (
    fee_calculation_for_cart, html_head, render_seating_plan,
    seatingframe_html_head,
)

from .cargo import cargo_del_carrito
from .seatmap import (
    enabled_seats, event_seats, row_label_sides, seat_name, seats_to_blocks,
)

PRODUCT_COLORS = 6  # number of .andinaseating-cN color classes in seating.css


def _css_link(filename):
    return format_html('<link rel="stylesheet" type="text/css" href="{}">',
                       static('pretixplugins/andinaseating/' + filename))


def _shop_css():
    return _css_link('vendor/seatmap-canvas/seatmap.canvas.css') + _css_link('seating.css')


@receiver(html_head, dispatch_uid="andinaseating_html_head")
def andinaseating_html_head(sender, request=None, **kwargs):
    if sender.seating_plan_id or sender.has_subevents:
        return _shop_css()
    return ""


@receiver(seatingframe_html_head, dispatch_uid="andinaseating_seatingframe_html_head")
def andinaseating_seatingframe_html_head(sender, request=None, **kwargs):
    return _shop_css()


@receiver(nav_organizer, dispatch_uid="andinaseating_nav_organizer")
def andinaseating_nav_organizer(sender, request=None, **kwargs):
    if not request.user.has_organizer_permission(request.organizer, 'organizer.seatingplans:write', request=request):
        return []
    url = resolve(request.path_info)
    return [{
        'label': 'Salas',
        'url': reverse('plugins:andinaseating:salas', kwargs={'organizer': request.organizer.slug}),
        'active': url.namespace == 'plugins:andinaseating',
        'icon': 'th',
    }]


@receiver(nav_event, dispatch_uid="andinaseating_nav_event")
def andinaseating_nav_event(sender, request=None, **kwargs):
    url = resolve(request.path_info)
    kw = {'organizer': request.organizer.slug, 'event': request.event.slug}
    nav = []
    if request.user.has_event_permission(request.organizer, request.event, 'event.items:write', request=request):
        nav.append({
            'label': 'Plan de butacas',
            'url': reverse('plugins:andinaseating:event', kwargs=kw),
            'active': url.namespace == 'plugins:andinaseating' and url.url_name == 'event',
            'icon': 'th',
        })
    if request.user.has_event_permission(request.organizer, request.event, 'event.orders:write', request=request):
        nav.append({
            'label': 'Boletería',
            'url': reverse('plugins:andinaseating:boleteria', kwargs=kw),
            'active': url.namespace == 'plugins:andinaseating' and url.url_name == 'boleteria',
            'icon': 'ticket',
        })
        nav.append({
            'label': 'Cortesías',
            'url': reverse('plugins:andinaseating:cortesias', kwargs=kw),
            'active': url.namespace == 'plugins:andinaseating' and url.url_name == 'cortesias',
            'icon': 'gift',
        })
    return nav


def _is_sellable(item, voucher):
    if not item or not item.is_available() or item.has_variations:
        return False
    if (item.require_voucher or item.hide_without_voucher) and not voucher:
        return False
    if voucher and not voucher.applies_to(item):
        return False
    return True


@receiver(render_seating_plan, dispatch_uid="andinaseating_render_seating_plan")
def andinaseating_render(sender, request, subevent=None, voucher=None, add_to_cart_below=False, **kwargs):
    ev = subevent or sender
    if not ev.seating_plan_id:
        return ""

    free_ids = set(
        ev.free_seats(ignore_voucher=voucher, sales_channel=request.sales_channel.identifier)
        .values_list('pk', flat=True)
    )
    if voucher and voucher.seat_id:
        # A voucher bound to a specific seat only allows that seat.
        free_ids = {voucher.seat_id}

    price_overrides = subevent.item_price_overrides if subevent else {}

    products = {}
    # Un recuadro por sector, cada uno con su plano, su leyenda y su lista. Solo los sectores
    # habilitados (con producto): los que quedaron "Sin asignar" en el evento no se muestran.
    sectors = []
    sector_by_zone = {}
    row_by_key = {}
    map_state = {}  # datos de cada butaca para el plano (seatmap-canvas)
    seats = enabled_seats(event_seats(ev.seats.select_related('product')))
    for s in seats:
        seat = s.obj
        zone = s.zone or ''
        if zone not in sector_by_zone:
            sector_by_zone[zone] = {'name': zone, 'rows': [], 'seats': [], 'free': {}}
            sectors.append(sector_by_zone[zone])
        sector = sector_by_zone[zone]
        sector['seats'].append(s)
        key = (zone, seat.row_name)
        if key not in row_by_key:
            row_by_key[key] = {'label': seat.row_label or seat.row_name, 'seats': []}
            sector['rows'].append(row_by_key[key])

        item = seat.product
        free = _is_sellable(item, voucher) and seat.pk in free_ids
        if item and item.pk not in products:
            price = price_overrides.get(item.pk, item.default_price)
            products[item.pk] = {
                'item': item,
                # Con un vale se muestra el precio del vale (por ejemplo $0 en una cortesía).
                'price': voucher.calculate_price(price) if voucher else price,
                'listed': not voucher or voucher.applies_to(item),
                'color': len(products) % PRODUCT_COLORS,
            }
        if item:
            sector['free'][item.pk] = sector['free'].get(item.pk, 0) + (1 if free else 0)
        field = 'seat_{}'.format(item.pk) if item else ''
        row_by_key[key]['seats'].append({
            'seat': seat,
            'number': seat.seat_number,
            'free': free,
            'field': field,
            'product': products.get(item.pk) if item else None,
        })
        sellable_now = free and ev.presale_is_running
        if sellable_now:
            detail = '{} – {}'.format(item.name, money_filter(products[item.pk]['price'], sender.currency))
        else:
            detail = 'No disponible'
        map_state[seat.pk] = {
            'salable': sellable_now,
            # Cartel al pasar el mouse: un renglón por cada salto de línea.
            'title': seat_name(s) + '\n' + detail,
            'custom_data': {
                'row': s.row_label or s.row, 'zone': zone, 'field': field,
                # El mismo color del producto que en la leyenda y la lista (.andinaseating-cN).
                'color': products[item.pk]['color'] if item else None,
            },
        }

    if not sectors:
        return ""

    sides = row_label_sides(ev.seating_plan)
    for i, sector in enumerate(sectors):
        sector['index'] = i
        sector['json_id'] = 'andinaseating-blocks-{}'.format(i)
        sector['first'] = i == 0
        sector['last'] = i == len(sectors) - 1
        sector['products'] = [
            dict(products[pk], free=n) for pk, n in sector['free'].items() if products[pk]['listed']
        ]
        sector['free_count'] = sum(sector['free'].values())
        # Cada plano con su sector solo; el nombre va en el título del recuadro.
        sector['blocks'] = seats_to_blocks(sector.pop('seats'), state=lambda s: map_state[s.obj.pk],
                                           sides=sides)

    free_count = sum(sector['free_count'] for sector in sectors)
    return get_template('pretixplugins/andinaseating/selector.html').render({
        'event': sender,
        'sectors': sectors,
        'free_count': free_count,
        'presale_is_running': ev.presale_is_running,
        # On the shop front page the core renders its own "Add to cart" button below the
        # product list if there are other products; one button submits everything.
        'show_submit': free_count and ev.presale_is_running and not add_to_cart_below,
    }, request=request)


# Cargo por servicio (cargo.py): pretix pregunta los cargos para mostrar el carrito y otra vez al
# crear el pedido; las dos respuestas tienen que coincidir.
@receiver(fee_calculation_for_cart, dispatch_uid="andinaseating_cargo_carrito")
def andinaseating_cargo_carrito(sender, positions=None, **kwargs):
    return cargo_del_carrito(sender, positions or [])


@receiver(order_fee_calculation, dispatch_uid="andinaseating_cargo_pedido")
def andinaseating_cargo_pedido(sender, positions=None, **kwargs):
    return cargo_del_carrito(sender, positions or [])
