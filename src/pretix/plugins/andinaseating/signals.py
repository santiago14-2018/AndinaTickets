#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.dispatch import receiver
from django.template.loader import get_template
from django.templatetags.static import static
from django.urls import resolve, reverse
from django.utils.html import format_html

from pretix.control.signals import nav_event, nav_organizer
from pretix.presale.signals import (
    html_head, render_seating_plan, seatingframe_html_head,
)

PRODUCT_COLORS = 6  # number of .andinaseating-cN color classes in seating.css


def _css_link(filename):
    return format_html('<link rel="stylesheet" type="text/css" href="{}">',
                       static('pretixplugins/andinaseating/' + filename))


@receiver(html_head, dispatch_uid="andinaseating_html_head")
def andinaseating_html_head(sender, request=None, **kwargs):
    if sender.seating_plan_id or sender.has_subevents:
        return _css_link('seating.css')
    return ""


@receiver(seatingframe_html_head, dispatch_uid="andinaseating_seatingframe_html_head")
def andinaseating_seatingframe_html_head(sender, request=None, **kwargs):
    return _css_link('seating.css')


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
    if not request.user.has_event_permission(request.organizer, request.event, 'event.items:write', request=request):
        return []
    url = resolve(request.path_info)
    return [{
        'label': 'Plan de butacas',
        'url': reverse('plugins:andinaseating:event', kwargs={
            'organizer': request.organizer.slug, 'event': request.event.slug,
        }),
        'active': url.namespace == 'plugins:andinaseating' and url.url_name == 'event',
        'icon': 'th',
    }]


def _is_sellable(item, voucher):
    if not item or not item.is_available() or item.has_variations:
        return False
    if (item.require_voucher or item.hide_without_voucher) and not voucher:
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
    rows = []
    row_by_key = {}
    for seat in ev.seats.select_related('product').order_by('sorting_rank', 'seat_guid'):
        key = (seat.zone_name, seat.row_name)
        if key not in row_by_key:
            row_by_key[key] = {'zone': seat.zone_name, 'label': seat.row_label or seat.row_name, 'seats': []}
            rows.append(row_by_key[key])

        item = seat.product
        free = _is_sellable(item, voucher) and seat.pk in free_ids
        if item and item.pk not in products:
            products[item.pk] = {
                'item': item,
                'price': price_overrides.get(item.pk, item.default_price),
                'color': len(products) % PRODUCT_COLORS,
                'free': 0,
            }
        if free:
            products[item.pk]['free'] += 1
        row_by_key[key]['seats'].append({
            'seat': seat,
            'number': seat.seat_number,
            'free': free,
            'field': 'seat_{}'.format(item.pk) if item else '',
            'product': products.get(item.pk) if item else None,
        })

    # Show the zone name only when it changes, so multi-sector plans read as sections.
    last_zone = None
    for r in rows:
        r['zone_header'] = r['zone'] if r['zone'] != last_zone else None
        last_zone = r['zone']

    free_count = sum(p['free'] for p in products.values())
    return get_template('pretixplugins/andinaseating/selector.html').render({
        'event': sender,
        'rows': rows,
        'products': list(products.values()),
        'free_count': free_count,
        'presale_is_running': ev.presale_is_running,
        # On the shop front page the core renders its own "Add to cart" button below the
        # product list if there are other products; one button submits everything.
        'show_submit': free_count and ev.presale_is_running and not add_to_cart_below,
    }, request=request)
