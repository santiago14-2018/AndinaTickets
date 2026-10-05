#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Cortesías directas: el organizador elige a quién (nombre y email) y qué butacas (o, sin
numerar, cuántas entradas de un producto), y AndinaTickets le manda las entradas con QR por
email. Sin email, la cortesía queda cargada con el nombre ("lista de invitados"): en la
puerta se busca por nombre en el check-in.

Cada cortesía es un pedido pagado de $0 en el canal "Cortesías" (api.cortesias). El
informe del productor las cuenta aparte de las ventas, junto con las de los vales.
Para que el invitado elija su butaca existen los vales (Vales → crear varios y enviarlos
por email), que vienen con pretix.
"""
from i18nfield.strings import LazyI18nString

from pretix.base.email import get_email_context
from pretix.base.models import Order, OrderPosition
from pretix.base.settings import PERSON_NAME_SCHEMES

from .boleteria import COURTESY_CHANNEL, enable_for_event, rows_for, run_import

COMMENT = 'Cortesía'
MAIL_SUBJECT = LazyI18nString({
    'es': 'Tu entrada de cortesía para {event}',
    'en': 'Your complimentary ticket for {event}',
})
MAIL_TEXT = LazyI18nString({
    'es': 'Hola:\n\n'
          'Te invitamos a **{event}**. Te mandamos tu entrada adjunta en PDF: mostrá el código QR en la '
          'puerta, impreso o en el celular.\n\n'
          'También podés verla y descargarla acá:\n\n{url}\n\n'
          '¡Te esperamos!',
    'en': 'Hello,\n\nyou are invited to **{event}**. Your ticket is attached as a PDF: show the QR code at the '
          'entrance, printed or on your phone.\n\nYou can also view and download it here:\n\n{url}\n\nSee you there!',
})


def name_parts(event, name):
    """Nombre del invitado según cómo pide los nombres el evento (completo, o nombre y apellido)."""
    scheme = event.settings.name_scheme
    fields = [f[0] for f in PERSON_NAME_SCHEMES[scheme]['fields']]
    parts = {'_scheme': scheme}
    if 'full_name' in fields:
        parts['full_name'] = name
    elif 'given_name' in fields and 'family_name' in fields:
        given, _, family = name.partition(' ')
        parts['given_name'], parts['family_name'] = given, family
    else:
        parts[fields[0]] = name
    return parts


def download_problem(event):
    """
    Por qué el invitado no recibiría la entrada en el email (pretix solo la adjunta si el evento
    permite descargar entradas en PDF), o None si está todo bien.
    """
    if 'pretix.plugins.ticketoutputpdf' not in event.get_plugins():
        return 'falta activar el plugin "PDF ticket output" en Ajustes → Plugins'
    if not event.settings.ticket_download:
        return 'la descarga de entradas está desactivada (Ajustes → Entradas: "Permitir descargar entradas")'
    if not event.settings.get('ticketoutput_pdf__enabled', as_type=bool):
        return 'la salida en PDF está desactivada (Ajustes → Entradas → PDF)'
    if not event.settings.mail_attach_tickets:
        return 'los correos no adjuntan las entradas (Ajustes → Correo electrónico: "Adjuntar entradas")'
    return None


def send_mail(order, user=None):
    order.send_mail(
        MAIL_SUBJECT, MAIL_TEXT, get_email_context(event=order.event, order=order),
        'pretix.event.order.email.order_free', user=user, attach_tickets=True,
    )


def create_courtesy(event, subevent, user, name, email='', seats=None, item=None, quantity=0):
    """Crea la cortesía y, si hay email, le manda las entradas. Devuelve el pedido."""
    channel = enable_for_event(event, COURTESY_CHANNEL)
    order = run_import(event, subevent, user, channel, rows_for(seats, item, quantity),
                       '{}: {}'.format(COMMENT, name), courtesy=True, email=email)
    parts = name_parts(event, name)
    for p in order.positions.all():
        p.attendee_name_parts = parts
        p.save(update_fields=['attendee_name_parts', 'attendee_name_cached'])
    if email:
        send_mail(order, user=user)
    return order


def courtesy_orders(event, subevent):
    return Order.objects.filter(
        event=event, sales_channel__identifier=COURTESY_CHANNEL, all_positions__subevent=subevent,
    ).distinct().prefetch_related(
        'all_positions__seat', 'all_positions__item',
    ).order_by('-datetime')


def courtesy_name(order):
    first = OrderPosition.all.filter(order=order).order_by('pk').first()
    return first.attendee_name if first else ''
