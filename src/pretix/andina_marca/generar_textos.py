"""
AndinaTickets: arma andina_marca/locale/es/LC_MESSAGES/django.po con las frases en castellano
de pretix que nombran al sistema ("su cuenta de pretix", "Bienvenido a pretix", ...), cambiando
"pretix" por el nombre de la marca.

Django lee esta carpeta antes que la traducción de pretix, así que solo se reemplazan esas frases
y la traducción original queda intacta. Se deja "pretix" donde habla del programa en sí (licencia,
versiones, actualizaciones, pretix.eu, pretixSCAN, "basado en pretix").

Volver a correr después de actualizar pretix:

    docker exec andina-tickets-web-1 python /pretix/src/pretix/andina_marca/generar_textos.py

y reiniciar (o "python manage.py compilemessages") para que se compile el .mo.
"""
import os
import re

import polib

MARCA = 'AndinaTickets'
AQUI = os.path.dirname(os.path.abspath(__file__))
ORIGEN = os.path.join(AQUI, '..', 'locale', 'es', 'LC_MESSAGES', 'django.po')
DESTINO = os.path.join(AQUI, 'locale', 'es', 'LC_MESSAGES', 'django.po')

PALABRA = re.compile(r'\b[Pp]retix\b(?![.\-]?[A-Za-z])')
# Frases que hablan de pretix como programa: se dejan como están.
DEJAR = re.compile(
    r'pretix\.eu|enterprise|licen|agpl|basado en|creado por|impulsad|proveído|versión anterior|'
    r'pretix \d|firma de pretix|actualizaci|instalaci|cambios en pretix|uso de pretix|'
    r'código fuente|traducciones|stripe|paypal|pretixdroid|pretixdesk|equipo de pretix|permiso adicional|'
    r'propia empresa|otros organizadores|desarrollado por',
    re.IGNORECASE
)


def cambiar(texto):
    texto = PALABRA.sub(MARCA, texto)
    # La traducción de pretix se come el signo de apertura.
    return re.sub(r'^Bienvenido a ', '¡Bienvenido a ', texto)


def main():
    origen = polib.pofile(ORIGEN)
    nuevo = polib.POFile()
    nuevo.metadata = {
        'Project-Id-Version': 'AndinaTickets',
        'Language': 'es',
        'MIME-Version': '1.0',
        'Content-Type': 'text/plain; charset=UTF-8',
        'Content-Transfer-Encoding': '8bit',
        'Plural-Forms': origen.metadata.get('Plural-Forms', 'nplurals=2; plural=n != 1;'),
    }
    for e in origen:
        if e.obsolete or 'fuzzy' in e.flags:
            continue
        textos = [e.msgstr] + list(e.msgstr_plural.values())
        if not any(PALABRA.search(t) for t in textos) or any(DEJAR.search(t) for t in textos):
            continue
        copia = polib.POEntry(
            msgid=e.msgid, msgid_plural=e.msgid_plural, msgctxt=e.msgctxt,
            msgstr=cambiar(e.msgstr),
            msgstr_plural={k: cambiar(v) for k, v in e.msgstr_plural.items()},
            flags=[f for f in e.flags if f != 'fuzzy'],
        )
        nuevo.append(copia)
    os.makedirs(os.path.dirname(DESTINO), exist_ok=True)
    nuevo.save(DESTINO)
    print(len(nuevo), 'frases en', DESTINO)
    for c in nuevo:
        print(' -', (c.msgstr or c.msgstr_plural.get(0, ''))[:110].replace('\n', ' '))


if __name__ == '__main__':
    main()
