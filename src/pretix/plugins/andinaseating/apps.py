#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

from pretix import __version__ as version
from pretix.base.plugins import PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID


class AndinaSeatingApp(AppConfig):
    name = 'pretix.plugins.andinaseating'
    verbose_name = _("Seating plan")

    class PretixPluginMeta:
        name = _("Seating plan")
        author = "AndinaTickets"
        version = version
        category = 'FEATURE'
        description = _("Salas con sectores (subidos como JSON o CSV) y selector de butacas en grilla "
                        "para que el comprador elija su lugar.")
        # Organizer level: the "Salas" page. Event level: the seat selector in the shop.
        level = PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID

    def ready(self):
        from . import signals  # NOQA
