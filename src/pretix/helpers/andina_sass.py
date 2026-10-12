#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
AndinaTickets: compilador de estilos (SCSS) que guarda el resultado, solo para desarrollo.

En desarrollo pretix compila los estilos en cada página. Con el código en D:\\ visto desde Docker
cada compilación tarda unos 6 segundos (leer archivos de Windows desde Linux es muy lento). Este
compilador guarda el resultado en el caché y solo vuelve a compilar si cambia el archivo o
cualquier .scss. Revisar los .scss tarda unos 2 segundos, así que se hace aparte (en segundo
plano), como mucho cada REVISAR segundos: un cambio en un .scss se ve en la página siguiente
a esa revisión. En producción no se usa: ahí los estilos se compilan una sola vez al instalar.
"""
import glob
import hashlib
import os
import threading
import time

from django.conf import settings
from django.core.cache import cache
from django_libsass import SassCompiler

REVISAR = 15  # segundos entre revisiones de los .scss

_lock = threading.Lock()
_estado = {'cuando': 0.0, 'version': None, 'revisando': False}


def _revisar():
    marcas = []
    for carpeta in settings.STATICFILES_DIRS:
        for f in glob.glob(os.path.join(carpeta, '**', '*.scss'), recursive=True):
            try:
                marcas.append('{}:{}'.format(f, os.stat(f).st_mtime_ns))
            except OSError:
                pass
    marcas.sort()
    version = hashlib.sha1('\n'.join(marcas).encode()).hexdigest()
    with _lock:
        _estado.update(version=version, cuando=time.monotonic(), revisando=False)
    return version


def _version_de_los_scss():
    """Una marca que cambia si se modifica, agrega o borra cualquier .scss de los estáticos."""
    with _lock:
        version = _estado['version']
        vencida = time.monotonic() - _estado['cuando'] >= REVISAR
        if version is not None and vencida and not _estado['revisando']:
            _estado['revisando'] = True
            threading.Thread(target=_revisar, daemon=True).start()
    # La primera vez no hay revisión anterior: se espera.
    return version if version is not None else _revisar()


class SassCompilerConCache(SassCompiler):
    def input(self, **kwargs):
        clave = 'andina_sass:' + hashlib.sha1('|'.join([
            self.filename or '', hashlib.sha1((self.content or '').encode()).hexdigest(), _version_de_los_scss(),
        ]).encode()).hexdigest()
        css = cache.get(clave)
        if css is None:
            css = super().input(**kwargs)
            cache.set(clave, css, 3600 * 24)
        return css
