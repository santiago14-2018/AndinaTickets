#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Generador de sectores (Organizador → Salas): numeración corrida, de pares o de impares, y la
vista previa en vivo (números de butaca, sector nuevo marcado y errores por campo).
"""
import json

import pytest
from django_scopes import scopes_disabled

from pretix.base.models import SeatingPlan
from pretix.plugins.andinaseating.layout import empty_layout, generate_sector


def numeros(zone):
    return [[s['seat_number'] for s in r['seats']] for r in zone['rows']]


def test_numeracion_corrida_impares_y_pares():
    corrida, _ = generate_sector('A', rows=1, seats_per_row=4)
    impares, _ = generate_sector('A', rows=1, seats_per_row=4, numbering='impares')
    pares, _ = generate_sector('A', rows=1, seats_per_row=4, numbering='pares')
    assert numeros(corrida) == [['1', '2', '3', '4']]
    assert numeros(impares) == [['1', '3', '5', '7']]
    assert numeros(pares) == [['2', '4', '6', '8']]


def test_impares_de_derecha_a_izquierda_y_primera_butaca():
    # Un sector a la izquierda del pasillo central: impares que crecen hacia afuera.
    zona, _ = generate_sector('Platea izquierda', rows=2, seats_per_row=5, numbering='impares', right_to_left=True)
    assert numeros(zona)[0] == ['9', '7', '5', '3', '1']
    # Pares desde la 10 (si la primera no es par, se usa la siguiente).
    zona, _ = generate_sector('Platea derecha', rows=1, seats_per_row=3, numbering='pares', first_number=9)
    assert numeros(zona) == [['10', '12', '14']]
    assert len({s['seat_guid'] for r in zona['rows'] for s in r['seats']}) == 3


@pytest.mark.django_db
def test_vista_previa_numeros_y_errores(env, client):
    event, _item, user = env
    with scopes_disabled():
        team = user.teams.first()
        team.all_organizer_permissions = True
        team.save()
        plan = SeatingPlan.objects.create(organizer=event.organizer, name='Sala vacía',
                                          layout=json.dumps(empty_layout('Sala vacía')))
    client.login(email='boleteria@example.com', password='boleteria')
    url = '/control/organizer/teatro/salas/{}/vista-previa/'.format(plan.pk)
    base = {'name': 'Platea', 'rows': 1, 'seats_per_row': 3, 'first_row': 'A', 'first_number': 1,
            'numbering': 'pares', 'aisle_after': 0, 'curve': 0, 'seat_spacing': 35, 'row_spacing': 40}

    data = client.get(url, base).json()
    seats = data['blocks'][0]['seats']
    assert [s['custom_data']['number'] for s in seats] == ['2', '4', '6']
    assert all(s['custom_data']['nuevo'] for s in seats)
    assert not any(s.get('selected') for s in seats)  # sin el tilde: se ve el número

    r = client.get(url, dict(base, aisle_after=5))
    assert r.status_code == 400
    assert r.json()['field_errors'] == {'aisle_after': ['El pasillo tiene que quedar entre dos butacas de la fila.']}


def test_letra_de_la_fila_a_la_derecha_o_a_los_dos_lados():
    from pretix.plugins.andinaseating.layout import add_sector
    from pretix.plugins.andinaseating.seatmap import (
        layout_seats, seats_to_blocks,
    )

    layout = add_sector(empty_layout('Sala'), *generate_sector('Platea derecha', rows=2, seats_per_row=3))
    seats = layout_seats(layout)

    def rotulos(sides):
        block = seats_to_blocks(seats, sides=sides)[0]
        xs = [s['x'] for s in block['seats']]
        return [(lbl['title'], 'izq' if lbl['x'] < min(xs) else 'der') for lbl in block['labels']]

    assert rotulos(None) == [('A', 'izq'), ('B', 'izq')]
    assert rotulos({'Platea derecha': 'derecha'}) == [('A', 'der'), ('B', 'der')]
    assert sorted(rotulos({'Platea derecha': 'ambos'})) == [('A', 'der'), ('A', 'izq'), ('B', 'der'), ('B', 'izq')]


@pytest.mark.django_db
def test_el_lado_se_guarda_al_agregar_y_se_olvida_al_quitar(env, client):
    from pretix.plugins.andinaseating.seatmap import row_label_sides

    event, _item, user = env
    with scopes_disabled():
        team = user.teams.first()
        team.all_organizer_permissions = True
        team.save()
        plan = SeatingPlan.objects.create(organizer=event.organizer, name='Sala nueva',
                                          layout=json.dumps(empty_layout('Sala nueva')))
    client.login(email='boleteria@example.com', password='boleteria')
    url = '/control/organizer/teatro/salas/{}/'.format(plan.pk)
    client.post(url, {'action': 'generate', 'name': 'Platea derecha', 'rows': 2, 'seats_per_row': 4,
                      'first_row': 'A', 'first_number': 1, 'numbering': 'pares', 'row_labels': 'derecha',
                      'aisle_after': 0, 'curve': 0, 'seat_spacing': 35, 'row_spacing': 40})
    with scopes_disabled():
        plan.refresh_from_db()
        assert row_label_sides(plan) == {'Platea derecha': 'derecha'}
    client.post(url, {'action': 'delete_sector', 'sector': 'Platea derecha'})
    with scopes_disabled():
        plan.refresh_from_db()
        assert row_label_sides(plan) == {}


def test_ubicacion_al_lado_de_otro_sector():
    from pretix.plugins.andinaseating.layout import (
        SECTOR_GAP, _zone_box, add_sector,
    )

    izq, _ = generate_sector('Platea izquierda', rows=3, seats_per_row=4)
    layout = add_sector(empty_layout('Sala'), izq, [])
    zonas = lambda lay: {z['name']: z for z in lay['zones']}  # noqa: E731

    # A la derecha: misma altura, pegado con la separación entre sectores.
    der, _ = generate_sector('Platea derecha', rows=3, seats_per_row=4)
    lay = add_sector(layout, der, [], 'derecha', 'Platea izquierda')
    a, b = _zone_box(zonas(lay)['Platea izquierda']), _zone_box(zonas(lay)['Platea derecha'])
    assert b[1] == a[1] and b[0] == a[2] + SECTOR_GAP

    # Debajo de: alineado a la izquierda, abajo.
    pullman, _ = generate_sector('Pullman', rows=1, seats_per_row=4)
    lay2 = add_sector(lay, pullman, [], 'abajo', 'Platea izquierda')
    c = _zone_box(zonas(lay2)['Pullman'])
    assert c[0] == a[0] and c[1] == a[3] + SECTOR_GAP

    # A la izquierda del primero: la sala se corre para que nada quede negativo.
    palco, _ = generate_sector('Palco', rows=1, seats_per_row=2)
    lay3 = add_sector(layout, palco, [], 'izquierda', 'Platea izquierda')
    p, q = _zone_box(zonas(lay3)['Palco']), _zone_box(zonas(lay3)['Platea izquierda'])
    assert p[0] >= 0 and p[2] + SECTOR_GAP == q[0]

    # Regenerar un sector que ya existe (ubicación "Debajo de todo") lo deja donde estaba.
    der2, _ = generate_sector('Platea derecha', rows=3, seats_per_row=4, numbering='pares')
    lay4 = add_sector(lay2, der2, [])
    assert zonas(lay4)['Platea derecha']['position'] == zonas(lay2)['Platea derecha']['position']


@pytest.mark.django_db
def test_nuevo_sector_no_repite_nombre_y_editar_lo_deja_en_su_lugar(env, client):
    from pretix.plugins.andinaseating.seatmap import row_label_sides

    event, _item, user = env
    with scopes_disabled():
        team = user.teams.first()
        team.all_organizer_permissions = True
        team.save()
        plan = SeatingPlan.objects.create(organizer=event.organizer, name='Teatrino',
                                          layout=json.dumps(empty_layout('Teatrino')))
    client.login(email='boleteria@example.com', password='boleteria')
    url = '/control/organizer/teatro/salas/{}/'.format(plan.pk)
    base = {'action': 'generate', 'rows': 2, 'seats_per_row': 4, 'first_row': 'A', 'first_number': 1,
            'numbering': 'corrida', 'aisle_after': 0, 'curve': 0, 'seat_spacing': 35, 'row_spacing': 40}

    client.post(url, dict(base, name='Platea izquierda'))
    client.post(url, dict(base, name='Platea derecha', row_labels='derecha', placement='derecha',
                          reference='Platea izquierda'))
    with scopes_disabled():
        plan.refresh_from_db()
        zonas = {z['name']: z for z in plan.layout_data['zones']}
    assert list(zonas) == ['Platea izquierda', 'Platea derecha']
    pos_derecha = zonas['Platea derecha']['position']

    # "Nuevo sector" con un nombre que ya existe: no se guarda y avisa.
    r = client.post(url, dict(base, name='Platea izquierda', seats_per_row=6))
    assert 'Ya hay un sector' in r.content.decode()

    # "Editar": el formulario viene con su configuración y, al guardar, queda en su lugar.
    html = client.get(url + '?editar=Platea+derecha').content.decode()
    assert 'Editar el sector "Platea derecha"' in html and 'value="derecha" selected' in html
    client.post(url, dict(base, name='Platea derecha', editing='Platea derecha', numbering='pares',
                          row_labels='derecha', placement='auto'))
    with scopes_disabled():
        plan.refresh_from_db()
        zonas = {z['name']: z for z in plan.layout_data['zones']}
        assert row_label_sides(plan) == {'Platea derecha': 'derecha'}
    assert zonas['Platea derecha']['position'] == pos_derecha
    assert [s['seat_number'] for s in zonas['Platea derecha']['rows'][0]['seats']] == ['2', '4', '6', '8']


@pytest.mark.django_db
def test_exportar_sector_y_subirlo_en_otra_sala(env, client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from pretix.base.models.seating import SeatingPlanLayoutValidator

    event, _item, user = env
    with scopes_disabled():
        team = user.teams.first()
        team.all_organizer_permissions = True
        team.save()
        origen = SeatingPlan.objects.create(organizer=event.organizer, name='Teatrino',
                                            layout=json.dumps(empty_layout('Teatrino')))
        destino = SeatingPlan.objects.create(organizer=event.organizer, name='Otra sala',
                                             layout=json.dumps(empty_layout('Otra sala')))
    client.login(email='boleteria@example.com', password='boleteria')
    base = {'action': 'generate', 'rows': 2, 'seats_per_row': 4, 'first_row': 'A', 'first_number': 1,
            'numbering': 'impares', 'aisle_after': 0, 'curve': 0, 'seat_spacing': 35, 'row_spacing': 40}
    url = '/control/organizer/teatro/salas/{}/'.format(origen.pk)
    client.post(url, dict(base, name='Platea izquierda'))
    client.post(url, dict(base, name='Platea derecha', placement='derecha', reference='Platea izquierda'))

    r = client.get(url + 'exportar/?sector=Platea+derecha')
    assert r['Content-Disposition'] == 'attachment; filename="teatrino-platea-derecha.json"'
    data = json.loads(r.content)
    SeatingPlanLayoutValidator()(data)  # formato de pretix
    assert [z['name'] for z in data['zones']] == ['Platea derecha']
    assert data['zones'][0]['position'] == {'x': 0, 'y': 0}
    assert client.get(url + 'exportar/?sector=No+existe').status_code == 404

    completa = json.loads(client.get(url + 'exportar/').content)
    assert [z['name'] for z in completa['zones']] == ['Platea izquierda', 'Platea derecha']

    client.post('/control/organizer/teatro/salas/{}/'.format(destino.pk), {
        'action': 'upload', 'name': 'Platea derecha',
        'file': SimpleUploadedFile('platea-derecha.json', r.content, content_type='application/json'),
    })
    with scopes_disabled():
        destino.refresh_from_db()
        filas = destino.layout_data['zones'][0]['rows']
    assert [s['seat_number'] for s in filas[0]['seats']] == ['1', '3', '5', '7']


@pytest.mark.django_db
def test_al_entrar_alta_vacia_y_vista_previa_sola(env, client):
    event, _item, user = env
    with scopes_disabled():
        team = user.teams.first()
        team.all_organizer_permissions = True
        team.save()
        plan = SeatingPlan.objects.create(organizer=event.organizer, name='Teatrino',
                                          layout=json.dumps(empty_layout('Teatrino')))
    client.login(email='boleteria@example.com', password='boleteria')
    url = '/control/organizer/teatro/salas/{}/'.format(plan.pk)
    base = {'rows': 2, 'seats_per_row': 4, 'first_row': 'A', 'first_number': 1, 'numbering': 'corrida',
            'aisle_after': 0, 'curve': 0, 'seat_spacing': 35, 'row_spacing': 40}
    client.post(url, dict(base, action='generate', name='Platea'))

    # Al entrar: lista para el alta (formulario en blanco, plano vacío, sin dibujar la sala).
    alta = client.get(url).content.decode()
    assert 'id="gen-form"' in alta and 'Completá los datos del sector' in alta
    assert 'id="sala-blocks" type="application/json">[]<' in alta
    # La sala entera, solo si se pide.
    sala = client.get(url + '?ver=sala').content.decode()
    assert 'La sala completa' in sala and 'id="gen-form"' not in sala and 'id="sala-blocks" type="application/json">[]<' not in sala

    preview = url + 'vista-previa/'
    solo = client.get(preview, dict(base, name='Pullman')).json()
    assert [b['title'] for b in solo['blocks']] == ['Pullman'] and solo['alone'] and solo['total_seats'] == 16
    junto = client.get(preview, dict(base, name='Pullman', con_sala='1')).json()
    assert sorted(b['title'] for b in junto['blocks']) == ['Platea', 'Pullman'] and not junto['alone']
