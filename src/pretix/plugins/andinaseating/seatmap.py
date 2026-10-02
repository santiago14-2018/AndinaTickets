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
import json

from pretix.base.models import SeatingPlan

ROW_LABEL_OFFSET = 40  # distancia del rótulo de la fila a la primera butaca
TITLE_SPACE = 45       # lugar para el nombre del sector, arriba de su primera fila


def seat_name(s):
    """Texto legible de una butaca: "Platea · Fila A · Butaca 3"."""
    return ' · '.join(p for p in (
        s.zone,
        s.row_label or 'Fila {}'.format(s.row),
        s.seat_label or 'Butaca {}'.format(s.number),
    ) if p)


def seats_to_blocks(seats, state=None, titles=False):
    """
    ``seats``: iterable de objetos con zone, row, row_label, number, seat_label, guid, x, y.
    ``state(seat)``: devuelve un dict extra para cada butaca (por ejemplo salable,
    selected o title). Sin ``state``, todas las butacas son seleccionables.
    ``titles``: agrega el nombre de cada sector arriba de sus butacas (ver ``_add_titles``).

    El ``title`` de cada butaca es el texto del cartel que aparece al pasar el mouse
    (un renglón por cada salto de línea); la librería no lo dibuja sobre la butaca.
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
            'title': seat_name(s),
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
    out = list(blocks.values())
    if titles:
        _add_titles(out)
    _shift_to_origin(out)
    return out


def _add_titles(blocks):
    """
    seatmap-canvas escribe el nombre del sector en el centro del bloque, debajo de las
    butacas, y no se lee. Lo agregamos como dos rótulos más arriba de la primera fila: el
    nombre a la izquierda y uno vacío a la derecha, para que el fondo del bloque (que la
    librería calcula con butacas y rótulos) haga lugar parejo. El JavaScript del comprador
    les da estilo. Los sectores de abajo se corren para que no se encimen.
    """
    ordered = sorted((b for b in blocks if b['title'] and b['seats']),
                     key=lambda b: min(s['y'] for s in b['seats']))
    for i, b in enumerate(ordered):
        points = b['seats'] + b['labels']
        for p in points:
            p['y'] += i * TITLE_SPACE
        y = min(s['y'] for s in b['seats']) - TITLE_SPACE
        b['labels'].append({'title': b['title'], 'x': min(p['x'] for p in points), 'y': y})
        b['labels'].append({'title': '', 'x': max(s['x'] for s in b['seats']), 'y': y})


def _shift_to_origin(blocks, margin=20):
    """
    seatmap-canvas centra el plano suponiendo que las coordenadas empiezan en 0; lo que
    quede en negativo (por ejemplo, los rótulos de fila) aparece cortado. Corremos todo.
    """
    points = [p for b in blocks for p in b['seats'] + b['labels']]
    if not points:
        return
    dx = margin - min(p['x'] for p in points)
    dy = margin - min(p['y'] for p in points)
    for p in points:
        p['x'] += dx
        p['y'] += dy


class _Seat:
    __slots__ = ('zone', 'row', 'row_label', 'number', 'seat_label', 'guid', 'x', 'y', 'category', 'obj')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def plan_seats(plan):
    """Butacas de una sala (SeatingPlan), con coordenadas absolutas."""
    return [
        _Seat(zone=s.zone, row=s.row, row_label=s.row_label, number=s.number, seat_label=s.seat_label,
              guid=s.guid, x=s.x, y=s.y, category=s.category)
        for s in plan.iter_all_seats()
    ]


def layout_seats(layout):
    """Butacas de un plano que todavía no se guardó (por ejemplo, la vista previa del generador)."""
    return plan_seats(SeatingPlan(layout=json.dumps(layout)))


def event_seats(queryset):
    """Butacas de un evento o fecha (modelo Seat)."""
    return [
        _Seat(zone=s.zone_name, row=s.row_name, row_label=s.row_label, number=s.seat_number,
              seat_label=s.seat_label, guid=s.seat_guid, x=s.x, y=s.y, obj=s)
        for s in queryset.order_by('sorting_rank', 'seat_guid')
    ]
