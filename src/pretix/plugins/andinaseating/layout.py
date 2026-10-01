#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Una "sala" es un SeatingPlan de pretix. Cada "sector" es una zona dentro del plano.
Este módulo convierte archivos JSON o CSV de un sector en una zona y la combina con
el plano de la sala. No toca la base de datos.
"""
import csv
import io
import json
import math

from django.core.exceptions import ValidationError
from django.utils.text import slugify

SEAT_SPACING = 35     # separación entre butacas generadas desde CSV
SECTOR_GAP = 60       # separación vertical entre sectores
DEFAULT_COLORS = ['#E69F00', '#56B4E9', '#009E73', '#CC79A7', '#0072B2', '#D55E00']

CSV_COLUMNS = {
    'row': ('fila', 'row', 'row_number'),
    'seat': ('butaca', 'asiento', 'numero', 'número', 'seat', 'seat_number'),
    'guid': ('seat_guid', 'guid', 'id'),
    'category': ('categoria', 'categoría', 'category'),
}


def empty_layout(name):
    return {'name': name, 'size': {'width': 400, 'height': 300}, 'categories': [], 'zones': []}


def row_names(first, count):
    """Nombres de fila desde ``first``: 1, 2, 3… o A, B, … Z, AA, AB…"""
    first = (first or 'A').strip().upper()
    if first.isdigit():
        return [str(int(first) + i) for i in range(count)]

    def to_int(s):
        n = 0
        for ch in s:
            n = n * 26 + (ord(ch) - ord('A') + 1)
        return n

    def to_str(n):
        s = ''
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(ord('A') + r) + s
        return s

    if not first.isalpha() or not first.isascii():
        raise ValidationError('La primera fila tiene que ser un número o letras de la A a la Z.')
    start = to_int(first)
    return [to_str(start + i) for i in range(count)]


def generate_sector(name, rows, seats_per_row, first_row='A', first_number=1, right_to_left=False,
                    seat_spacing=SEAT_SPACING, row_spacing=40, aisle_after=0, stagger=False, curve=0,
                    category=''):
    """
    Arma un sector rectangular de ``rows`` filas por ``seats_per_row`` butacas.

    - ``aisle_after``: deja un pasillo (el ancho de una butaca) después de esa butaca
      contando desde la izquierda. 0 = sin pasillo.
    - ``stagger``: corre media butaca las filas alternadas.
    - ``curve``: cuántos píxeles más atrás queda el centro de la fila respecto de las
      puntas (las puntas quedan más cerca del escenario, que está arriba).
    """
    category = category or name
    prefix = slugify(name) or 'sector'
    width = (seats_per_row - 1) * seat_spacing + (seat_spacing if aisle_after else 0)
    half = width / 2 or 1
    zone = {'name': name, 'position': {'x': 0, 'y': 0}, 'rows': []}
    for ri, row in enumerate(row_names(first_row, rows)):
        shift = seat_spacing / 2 if stagger and ri % 2 else 0
        seats = []
        for si in range(seats_per_row):
            x = si * seat_spacing + (seat_spacing if aisle_after and si >= aisle_after else 0)
            t = (x - half) / half
            y = curve * (1 - t * t)
            number = first_number + (seats_per_row - 1 - si if right_to_left else si)
            seats.append({
                'seat_guid': '{}-{}-{}'.format(prefix, row, number),
                'seat_number': str(number),
                'category': category,
                'position': {'x': round(x + shift, 2), 'y': round(y, 2)},
            })
        zone['rows'].append({
            'row_number': row,
            'row_label': 'Fila {}'.format(row),
            'seat_label': 'Butaca %s',
            'position': {'x': 0, 'y': ri * row_spacing},
            'seats': seats,
        })
    return zone, []


def parse_sector_file(content: bytes, filename: str, sector_name: str):
    """
    Devuelve (zona, categorías) a partir del archivo subido. La zona queda con
    nombre = sector_name.
    """
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('latin-1')

    if filename.lower().endswith('.json'):
        return _parse_json(text, sector_name)
    if filename.lower().endswith('.csv'):
        return _parse_csv(text, sector_name)
    raise ValidationError('El archivo tiene que ser .json o .csv.')


def _fix_label(label):
    # Error común al generar el JSON desde Python: "%%s" en lugar de "%s".
    if isinstance(label, str):
        return label.replace('%%s', '%s')
    return label


def _parse_json(text, sector_name):
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValidationError('El JSON no es válido: {}'.format(e))
    if not isinstance(data, dict):
        raise ValidationError('El JSON tiene que ser un objeto.')

    if 'zones' in data:
        zones = data['zones']
        if len(zones) != 1:
            raise ValidationError(
                'El archivo tiene {} zonas. Subí un archivo por sector (una sola zona).'.format(len(zones))
            )
        zone = zones[0]
        categories = data.get('categories') or []
    elif 'rows' in data:
        zone = data
        categories = []
    else:
        raise ValidationError('No encontré "zones" ni "rows" en el JSON.')

    zone = dict(zone)
    zone['name'] = sector_name
    zone.setdefault('position', {'x': 0, 'y': 0})
    for r in zone.get('rows', []):
        r['row_label'] = _fix_label(r.get('row_label'))
        r['seat_label'] = _fix_label(r.get('seat_label'))
        for s in r.get('seats', []):
            if not s.get('category'):
                s['category'] = sector_name
            s.setdefault('position', {'x': 0, 'y': 0})
    return zone, categories


def _find_column(header, key):
    for i, h in enumerate(header):
        if h.strip().lower() in CSV_COLUMNS[key]:
            return i
    return None


def _parse_csv(text, sector_name):
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    lines = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(lines) < 2:
        raise ValidationError('El CSV está vacío o no tiene encabezado.')

    header, body = lines[0], lines[1:]
    col = {k: _find_column(header, k) for k in CSV_COLUMNS}
    if (col['row'] is None or col['seat'] is None) and col['guid'] is None:
        raise ValidationError(
            'El CSV necesita las columnas "fila" y "butaca" (o una columna "seat_guid" del tipo A-1).'
        )

    prefix = slugify(sector_name) or 'sector'
    rows = {}
    for n, line in enumerate(body, start=2):
        def cell(key):
            i = col[key]
            return line[i].strip() if i is not None and i < len(line) else ''

        row, seat, guid = cell('row'), cell('seat'), cell('guid')
        if (not row or not seat) and guid and '-' in guid:
            row, seat = guid.rsplit('-', 1)
        if not row or not seat:
            raise ValidationError('Línea {}: falta la fila o la butaca.'.format(n))
        rows.setdefault(row, []).append({
            'seat_guid': guid or '{}-{}-{}'.format(prefix, row, seat),
            'seat_number': seat,
            'category': cell('category') or sector_name,
        })

    def seat_sort(s):
        return (0, int(s['seat_number']), '') if s['seat_number'].isdigit() else (1, 0, s['seat_number'])

    zone = {'name': sector_name, 'position': {'x': 0, 'y': 0}, 'rows': []}
    for ri, (row, seats) in enumerate(rows.items()):
        seats.sort(key=seat_sort)
        for si, s in enumerate(seats):
            s['position'] = {'x': si * SEAT_SPACING, 'y': 0}
        zone['rows'].append({
            'row_number': row,
            'row_label': 'Fila {}'.format(row),
            'seat_label': 'Butaca %s',
            'position': {'x': 0, 'y': ri * SEAT_SPACING},
            'seats': seats,
        })
    return zone, []


def _zone_bottom_right(zone):
    zx, zy = zone['position']['x'], zone['position']['y']
    max_x = max_y = 0
    for r in zone.get('rows', []):
        rx, ry = r.get('position', {}).get('x', 0), r.get('position', {}).get('y', 0)
        for s in r.get('seats', []):
            max_x = max(max_x, rx + s['position']['x'])
            max_y = max(max_y, ry + s['position']['y'])
    return zx + max_x + SEAT_SPACING, zy + max_y + SEAT_SPACING


def _resize(layout):
    width, height = 400, 300
    for z in layout['zones']:
        right, bottom = _zone_bottom_right(z)
        width, height = max(width, right), max(height, bottom)
    # El esquema de pretix exige enteros (con filas alternadas las posiciones tienen decimales).
    layout['size'] = {'width': math.ceil(width), 'height': math.ceil(height)}


def add_sector(layout, zone, categories):
    """
    Agrega (o reemplaza, si ya existe uno con el mismo nombre) un sector al plano.
    Devuelve un plano nuevo; no modifica el original.
    """
    layout = json.loads(json.dumps(layout))
    layout['zones'] = [z for z in layout['zones'] if z.get('name') != zone['name']]

    taken = {s['seat_guid'] for z in layout['zones'] for r in z['rows'] for s in r['seats']}
    new_guids = [s['seat_guid'] for r in zone['rows'] for s in r['seats']]
    if not new_guids:
        raise ValidationError('El sector no tiene butacas.')
    dup_inside = {g for g in new_guids if new_guids.count(g) > 1}
    if dup_inside:
        raise ValidationError('Hay butacas repetidas en el archivo: {}'.format(', '.join(sorted(dup_inside)[:5])))
    dup = sorted(taken & set(new_guids))
    if dup:
        raise ValidationError(
            'Estos identificadores ya existen en otro sector de la sala: {}. '
            'Cada butaca de la sala necesita un seat_guid único.'.format(', '.join(dup[:5]))
        )

    bottom = max((_zone_bottom_right(z)[1] for z in layout['zones']), default=0)
    zone['position'] = {'x': 0, 'y': bottom + SECTOR_GAP if layout['zones'] else 0}
    layout['zones'].append(zone)

    known = {c['name'] for c in layout['categories']}
    for c in categories:
        if c.get('name') and c['name'] not in known:
            layout['categories'].append(c)
            known.add(c['name'])
    for r in zone['rows']:
        for s in r['seats']:
            if s['category'] not in known:
                color = DEFAULT_COLORS[len(layout['categories']) % len(DEFAULT_COLORS)]
                layout['categories'].append({'name': s['category'], 'color': color})
                known.add(s['category'])

    _resize(layout)
    return layout


def remove_sector(layout, sector_name):
    layout = json.loads(json.dumps(layout))
    layout['zones'] = [z for z in layout['zones'] if z.get('name') != sector_name]
    used = {s['category'] for z in layout['zones'] for r in z['rows'] for s in r['seats']}
    layout['categories'] = [c for c in layout['categories'] if c['name'] in used]
    _resize(layout)
    return layout


def categories_summary(layout):
    """Categorías del plano, en orden de aparición, con su cantidad de butacas y sectores."""
    out = {}
    for z in layout.get('zones', []):
        for r in z.get('rows', []):
            for s in r.get('seats', []):
                c = out.setdefault(s['category'], {'name': s['category'], 'seats': 0, 'sectors': []})
                c['seats'] += 1
                if z.get('name') and z['name'] not in c['sectors']:
                    c['sectors'].append(z['name'])
    return list(out.values())


def sectors_summary(layout):
    out = []
    for z in layout.get('zones', []):
        seats = [s for r in z.get('rows', []) for s in r.get('seats', [])]
        out.append({
            'name': z.get('name') or '(sin nombre)',
            'rows': len(z.get('rows', [])),
            'seats': len(seats),
            'categories': sorted({s.get('category', '') for s in seats}),
        })
    return out
