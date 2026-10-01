#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Convierte butacas de pretix al formato de bloques de seatmap-canvas
(static/pretixplugins/andinaseating/vendor/seatmap-canvas). Un bloque por sector.

No usamos el conversor de pretix que trae la librería: acumula la posición de las
filas y usa campos que no existen en el formato de pretix.
"""
ROW_LABEL_OFFSET = 40  # distancia del rótulo de la fila a la primera butaca


def seats_to_blocks(seats, state=None):
    """
    ``seats``: iterable de objetos con zone, row, row_label, number, guid, x, y.
    ``state(seat)``: devuelve un dict extra para cada butaca (por ejemplo salable o
    selected). Sin ``state``, todas las butacas son seleccionables.
    """
    blocks = {}
    rows = {}
    for s in seats:
        zone = s.zone or ''
        block = blocks.setdefault(zone, {
            'id': zone or 'sector', 'title': zone, 'color': '#2c2828', 'labels': [], 'seats': [],
        })
        seat = {
            'id': s.guid,
            'x': s.x or 0,
            'y': s.y or 0,
            'title': s.number,
            'salable': True,
            'custom_data': {'row': s.row_label or s.row, 'zone': zone},
        }
        if state:
            seat.update(state(s))
        block['seats'].append(seat)

        key = (zone, s.row)
        first = rows.get(key)
        if first is None or seat['x'] < first['x']:
            rows[key] = {'x': seat['x'], 'y': seat['y'], 'title': s.row, 'zone': zone}

    for r in rows.values():
        blocks[r['zone']]['labels'].append({
            'title': r['title'], 'x': r['x'] - ROW_LABEL_OFFSET, 'y': r['y'],
        })
    return list(blocks.values())


class _Seat:
    __slots__ = ('zone', 'row', 'row_label', 'number', 'guid', 'x', 'y', 'category', 'obj')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def plan_seats(plan):
    """Butacas de una sala (SeatingPlan), con coordenadas absolutas."""
    return [
        _Seat(zone=s.zone, row=s.row, row_label=s.row_label, number=s.number, guid=s.guid,
              x=s.x, y=s.y, category=s.category)
        for s in plan.iter_all_seats()
    ]


def event_seats(queryset):
    """Butacas de un evento o fecha (modelo Seat)."""
    return [
        _Seat(zone=s.zone_name, row=s.row_name, row_label=s.row_label, number=s.seat_number,
              guid=s.seat_guid, x=s.x, y=s.y, obj=s)
        for s in queryset.order_by('sorting_rank', 'seat_guid')
    ]
