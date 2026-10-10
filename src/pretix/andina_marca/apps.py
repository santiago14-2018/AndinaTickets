#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.apps import AppConfig


class AndinaMarcaApp(AppConfig):
    """Marca de AndinaTickets: registra la letra de la marca. Los íconos, plantillas y textos
    de esta carpeta se cargan por la configuración (ANDINA_MARCA_DIR), no por esta app."""
    name = 'pretix.andina_marca'
    label = 'andina_marca'
    verbose_name = 'AndinaTickets: marca'

    def ready(self):
        from . import signals  # NOQA
