#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Cortesías directas: el organizador elige a quién y qué butacas (o cuántas, sin numerar), y
al invitado le llegan las entradas con QR por email. Sin email: lista de invitados.
"""
import pytest
from django.core import mail as djmail
from django_scopes import scopes_disabled

from pretix.base.models import Order
from pretix.plugins.andinaproductores.report import build_report
from pretix.plugins.andinaseating.boleteria import (
    COURTESY_CHANNEL, enable_for_event, seats_by_guid,
)
from pretix.plugins.andinaseating.cortesias import (
    create_courtesy, download_problem,
)


def seats(event, *guids):
    found, errors = seats_by_guid(event, list(guids), enable_for_event(event, COURTESY_CHANNEL))
    assert errors == []
    return found


@pytest.mark.django_db
def test_cortesia_por_email_con_butacas(env):
    event, item, user = env
    djmail.outbox = []
    with scopes_disabled():
        # El email sale en el idioma del evento (los de AndinaTickets, en español).
        event.settings.locales = ['es']
        event.settings.locale = 'es'
        # Con la descarga de entradas en PDF activada, como tiene que estar en un evento real.
        assert download_problem(event) is not None
        event.plugins += ',pretix.plugins.ticketoutputpdf'
        event.save()
        event.settings.ticket_download = True
        event.settings.ticketoutput_pdf__enabled = True
        assert download_problem(event) is None
        order = create_courtesy(event, None, user, 'Laura Gómez', 'laura@example.com',
                                seats=seats(event, 'platea-A-1', 'platea-A-2'))
        positions = list(order.positions.all())
        assert order.status == Order.STATUS_PAID and order.total == 0
        assert order.sales_channel.identifier == COURTESY_CHANNEL
        assert order.email == 'laura@example.com'
        assert {p.attendee_name for p in positions} == {'Laura Gómez'}
        assert {p.seat.seat_guid for p in positions} == {'platea-A-1', 'platea-A-2'}
    assert len(djmail.outbox) == 1
    msg = djmail.outbox[0]
    assert msg.to == ['laura@example.com']
    assert 'cortesía' in msg.subject and 'Hamlet' in msg.subject
    assert any(a[0].endswith('.pdf') for a in msg.attachments)  # la entrada con el QR


@pytest.mark.django_db
def test_sin_email_queda_en_la_lista_de_invitados(env):
    event, item, user = env
    djmail.outbox = []
    with scopes_disabled():
        order = create_courtesy(event, None, user, 'Prensa Diario Sur', '', seats=seats(event, 'platea-B-5'))
        assert order.email is None or order.email == ''
        assert order.positions.get().attendee_name == 'Prensa Diario Sur'
    assert djmail.outbox == []


@pytest.mark.django_db
def test_se_puede_dar_una_butaca_reservada_para_boleteria(env):
    event, item, user = env
    with scopes_disabled():
        event.seats.filter(seat_guid='platea-A-5').update(blocked=True)
        # La tienda online no la ofrece, pero se puede regalar.
        assert not event.free_seats(sales_channel='web').filter(seat_guid='platea-A-5').exists()
        order = create_courtesy(event, None, user, 'Elenco', '', seats=seats(event, 'platea-A-5'))
        assert order.positions.get().seat.seat_guid == 'platea-A-5'


@pytest.mark.django_db
def test_nombre_y_apellido_separados(env):
    event, item, user = env
    with scopes_disabled():
        event.settings.name_scheme = 'given_family'
        order = create_courtesy(event, None, user, 'Juan Carlos Pérez', '', seats=seats(event, 'platea-B-4'))
        parts = order.positions.get().attendee_name_parts
        assert (parts['given_name'], parts['family_name']) == ('Juan', 'Carlos Pérez')


@pytest.mark.django_db
def test_sin_numerar_por_cantidad(env_general):
    event, item, user = env_general
    with scopes_disabled():
        order = create_courtesy(event, None, user, 'Familia Ruiz', 'ruiz@example.com', item=item, quantity=3)
        assert order.positions.count() == 3
        assert all(p.seat is None for p in order.positions.all())


@pytest.mark.django_db
def test_el_informe_del_productor_las_cuenta_como_cortesias_digitales(env):
    event, item, user = env
    with scopes_disabled():
        create_courtesy(event, None, user, 'Laura', '', seats=seats(event, 'platea-A-1', 'platea-A-2'))
        report = build_report(event)
    assert report['tickets'] == 0 and report['gross'] == 0
    assert report['courtesy_online'] == 2
    assert report['courtesy_box'] == 0


@pytest.mark.django_db
def test_pantalla_dar_reenviar_y_anular(env, client):
    event, item, user = env
    client.login(email='boleteria@example.com', password='boleteria')
    url = '/control/event/teatro/hamlet/cortesias/'
    # El evento de prueba no permite descargar entradas: la pantalla lo avisa.
    assert 'recibirían el email <strong>sin</strong> la entrada' in client.get(url).content.decode()
    djmail.outbox = []
    r = client.post(url, {'action': 'create', 'name': 'Laura Gómez', 'email': 'laura@example.com',
                          'seats': 'pullman-J-2,pullman-J-3'}, follow=True)
    content = r.content.decode()
    assert 'Listo: 2 entradas de cortesía para Laura Gómez. Se las mandamos a laura@example.com.' in content
    assert 'Laura Gómez' in content and 'Fila J' in content
    with scopes_disabled():
        order = Order.objects.get(event=event, sales_channel__identifier=COURTESY_CHANNEL)
    r = client.post(url, {'action': 'resend', 'order': order.code}, follow=True)
    assert 'Se reenviaron las entradas a laura@example.com.' in r.content.decode()
    assert len(djmail.outbox) == 2
    r = client.post(url, {'action': 'cancel', 'order': order.code}, follow=True)
    assert 'anulada' in r.content.decode()
    with scopes_disabled():
        order.refresh_from_db()
        assert order.status == Order.STATUS_CANCELED


@pytest.mark.django_db
def test_pantalla_exige_butacas_o_cantidad(env, env_general, client):
    client.login(email='boleteria@example.com', password='boleteria')
    r = client.post('/control/event/teatro/hamlet/cortesias/', {'action': 'create', 'name': 'X'})
    assert 'Elegí al menos una butaca en el plano.' in r.content.decode()
    general, item, _user = env_general
    r = client.post('/control/event/teatro/standup/cortesias/', {
        'action': 'create', 'name': 'X', 'item': item.pk, 'quantity': 9})
    assert 'quedan 3 lugares; pediste 9' in r.content.decode()
