#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.apps import AppConfig

from pretix import __version__ as version
from pretix.base.plugins import PLUGIN_LEVEL_ORGANIZER


class AndinaProductoresApp(AppConfig):
    name = 'pretix.plugins.andinaproductores'
    verbose_name = 'Productores'

    class PretixPluginMeta:
        name = 'Productores'
        author = 'AndinaTickets'
        version = version
        category = 'FEATURE'
        description = ('Portal de solo lectura para productores: sus ventas, la recaudación, la comisión del '
                       'servicio y el neto a liquidar, con descarga en PDF.')
        level = PLUGIN_LEVEL_ORGANIZER

    def ready(self):
        from . import signals  # NOQA
