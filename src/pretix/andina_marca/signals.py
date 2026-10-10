#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.db.models.signals import post_save
from django.dispatch import receiver

from pretix.presale.style import register_fonts

LETRA = 'Bricolage Grotesque'
# El .woff2 es la letra variable completa (todos los grosores) para el navegador; los .ttf son
# versiones fijas para los PDF (reportlab no lee letras variables). Licencia: fonts/bricolage/OFL.txt
WEB = 'fonts/bricolage/BricolageGrotesque.woff2'


@receiver(register_fonts, dispatch_uid="andina_marca_fonts")
def letra_de_la_marca(sender, **kwargs):
    return {
        LETRA: {
            'regular': {'truetype': 'fonts/bricolage/BricolageGrotesque-Regular.ttf', 'woff2': WEB},
            'bold': {'truetype': 'fonts/bricolage/BricolageGrotesque-Bold.ttf', 'woff2': WEB},
            'sample': 'AndinaTickets',
        },
    }


def _con_letra_de_la_marca(layout):
    return layout.replace('"fontfamily": "Open Sans"', '"fontfamily": "{}"'.format(LETRA))


@receiver(post_save, sender='ticketoutputpdf.TicketLayout', dispatch_uid="andina_marca_ticketlayout")
def boleto_con_letra_de_la_marca(sender, instance, created, **kwargs):
    """Los diseños de boleto nuevos salen con la letra de la marca en lugar de Open Sans
    (el diseño de fábrica es de pretix y no lo tocamos)."""
    if created and instance.layout and '"fontfamily": "Open Sans"' in instance.layout:
        instance.layout = _con_letra_de_la_marca(instance.layout)
        instance.save(update_fields=['layout'])
