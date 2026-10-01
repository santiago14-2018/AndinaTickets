#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

from pretix import __version__ as version


class AndinaMercadoPagoApp(AppConfig):
    name = 'pretix.plugins.andinamercadopago'
    verbose_name = 'Mercado Pago'

    class PretixPluginMeta:
        name = 'Mercado Pago'
        author = 'AndinaTickets'
        version = version
        category = 'PAYMENT'
        description = _('Cobrar con Mercado Pago (Checkout Pro): tarjeta de crédito, débito y dinero en cuenta.')

    def ready(self):
        from . import signals  # NOQA
