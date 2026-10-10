"""
AndinaTickets: genera los íconos y logos de la marca que reemplazan a los de pretix.

Los archivos salen en andina_marca/static/ con los mismos nombres que usa pretix
(por ejemplo pretixbase/img/favicon.ico): Django busca primero en esa carpeta, así que
se muestran los nuestros sin tocar los originales.

El ícono es PROVISORIO (montañas blancas sobre violeta) hasta que esté el logo.
Para cambiar colores o nombre, editar las constantes de abajo y volver a correr:

    docker exec andina-tickets-web-1 python /pretix/src/pretix/andina_marca/generar_marca.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

NOMBRE = 'AndinaTickets'
VIOLETA = '#5b2a73'
VIOLETA_OSCURO = '#3e1b4f'
BLANCO = '#ffffff'
AVISO = '#e8870e'  # punto naranja del ícono de desarrollo

AQUI = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(AQUI, 'static')
LETRA = os.path.join(AQUI, '..', 'static', 'fonts', 'OpenSans-Bold.ttf')
LETRA_SVG = "'Bricolage Grotesque', 'Segoe UI', 'Open Sans', Arial, sans-serif"

# Dibujo en una grilla de 100 x 100: cuadrado redondeado y dos cerros.
RADIO = 22
CERROS = [(14, 74), (41, 29), (56, 52), (66, 39), (87, 74)]


def ruta(*partes):
    p = os.path.join(STATIC, *partes)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


# ---------- SVG ----------

def svg_cerros(color):
    puntos = ' '.join('{},{}'.format(x, y) for x, y in CERROS)
    return '<polygon points="{}" fill="{}"/>'.format(puntos, color)


def svg_icono(fondo, cerros):
    caja = '<rect width="100" height="100" rx="{}" fill="{}"/>'.format(RADIO, fondo) if fondo else ''
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '{}{}</svg>\n'.format(caja, svg_cerros(cerros)))


def svg_logo(color_texto, fondo_icono, cerros):
    # El texto se estira a un ancho fijo para que se vea igual con cualquier letra.
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 100">'
        '<rect width="100" height="100" rx="{radio}" fill="{fondo}"/>{cerros}'
        '<text x="118" y="68" font-family="{letra}" font-weight="800" font-size="52" '
        'letter-spacing="-1" textLength="398" lengthAdjust="spacingAndGlyphs" fill="{texto}">{nombre}</text>'
        '</svg>\n'
    ).format(radio=RADIO, fondo=fondo_icono, cerros=svg_cerros(cerros), letra=LETRA_SVG,
             texto=color_texto, nombre=NOMBRE)


def escribir(nombre, contenido):
    with open(ruta(*nombre.split('/')), 'w', encoding='utf-8') as f:
        f.write(contenido)


# ---------- PNG / ICO ----------

def png_icono(tam, aviso=False):
    """Ícono cuadrado; se dibuja 8 veces más grande y se achica para suavizar bordes."""
    g = tam * 8
    k = g / 100
    img = Image.new('RGBA', (g, g), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, g - 1, g - 1], radius=RADIO * k, fill=VIOLETA)
    d.polygon([(x * k, y * k) for x, y in CERROS], fill=BLANCO)
    if aviso:
        r = 17 * k
        d.ellipse([g - 2 * r - 2 * k, g - 2 * r - 2 * k, g - 2 * k, g - 2 * k], fill=AVISO, outline=BLANCO,
                  width=int(4 * k))
    return img.resize((tam, tam), Image.LANCZOS)


def png_logo(color_texto, ancho=1024, alto=629):
    """Ícono arriba y nombre abajo, para los boletos en PDF (en lugar de "powered by pretix").
    Mismas proporciones que la imagen de pretix, así ocupa el mismo lugar en los diseños ya hechos."""
    g = 2
    W, H = ancho * g, alto * g
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lado = int(H * 0.62)
    x0 = (W - lado) // 2
    k = lado / 100
    d.rounded_rectangle([x0, 0, x0 + lado - 1, lado - 1], radius=RADIO * k, fill=VIOLETA)
    d.polygon([(x0 + x * k, y * k) for x, y in CERROS], fill=BLANCO)
    tam = int(H * 0.27)
    letra = ImageFont.truetype(LETRA, tam)
    while d.textlength(NOMBRE, font=letra) > W * 0.98:
        tam -= 4
        letra = ImageFont.truetype(LETRA, tam)
    caja = d.textbbox((0, 0), NOMBRE, font=letra)
    x = (W - (caja[2] - caja[0])) / 2 - caja[0]
    y = H - (caja[3] - caja[1]) - caja[1] - H * 0.02
    d.text((x, y), NOMBRE, font=letra, fill=color_texto)
    return img.resize((ancho, alto), Image.LANCZOS)


def guardar_ico(nombre, aviso=False):
    tams = [16, 32, 48, 64]
    imgs = [png_icono(t, aviso) for t in tams]
    imgs[-1].save(ruta(*nombre.split('/')), format='ICO', sizes=[(t, t) for t in tams], append_images=imgs[:-1])


def main():
    # Logos e íconos que usan las plantillas de pretix.
    escribir('pretixbase/img/pretix-icon.svg', svg_icono(VIOLETA, BLANCO))
    escribir('pretixbase/img/pretix-icon-white-on-purple.svg', svg_icono(VIOLETA, BLANCO))
    escribir('pretixbase/img/pretix-icon-white-mini.svg', svg_icono(None, BLANCO))
    escribir('pretixbase/img/pretix-logo.svg', svg_logo(VIOLETA, VIOLETA, BLANCO))
    escribir('pretixbase/img/pretix-logo-white.svg', svg_logo(BLANCO, BLANCO, VIOLETA))
    escribir('pretixbase/img/icons/mstile.svg', svg_icono(None, '#000000'))
    escribir('pretixbase/img/icons/safari-pinned-tab.svg', svg_icono(None, '#000000'))

    # Pestaña del navegador (favicon). El "debug" lleva un punto naranja: se usa en desarrollo.
    guardar_ico('pretixbase/img/favicon.ico')
    guardar_ico('pretixbase/img/icons/favicon.ico')
    guardar_ico('pretixbase/img/favicon-debug.ico', aviso=True)
    for t in (16, 32, 64):
        png_icono(t).save(ruta('pretixbase', 'img', 'favicon-{}.png'.format(t)))
        png_icono(t, aviso=True).save(ruta('pretixbase', 'img', 'favicon-debug-{}.png'.format(t)))
    for nombre, t in [('favicon-16x16.png', 16), ('favicon-32x32.png', 32), ('favicon-180x180.png', 180),
                      ('favicon-194x194.png', 194), ('apple-touch-icon.png', 180),
                      ('android-chrome-192x192.png', 192), ('android-chrome-512x512.png', 512),
                      ('mstile-150x150.png', 150), ('mstile-310x310.png', 310)]:
        png_icono(t).save(ruta('pretixbase', 'img', 'icons', nombre))

    # Elemento "logo" del editor de boletos PDF (antes "powered by pretix").
    png_logo(VIOLETA_OSCURO).save(ruta('pretixpresale', 'pdf', 'powered_by_pretix_dark.png'))
    png_logo(BLANCO).save(ruta('pretixpresale', 'pdf', 'powered_by_pretix_white.png'))
    escribir('pretixpresale/pdf/powered_by_pretix_dark.svg', svg_logo(VIOLETA_OSCURO, VIOLETA, BLANCO))
    escribir('pretixpresale/pdf/powered_by_pretix_white.svg', svg_logo(BLANCO, VIOLETA, BLANCO))
    print('Listo: marca generada en', STATIC)


if __name__ == '__main__':
    main()
