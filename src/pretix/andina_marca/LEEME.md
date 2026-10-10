# Marca de AndinaTickets

Todo lo que cambia la cara de pretix por la de AndinaTickets, en un solo lugar. Django busca
**primero acá** y después en pretix (`ANDINA_MARCA_DIR` en `src/pretix/_base_settings.py`), así
que los archivos de pretix quedan intactos y las actualizaciones de pretix no chocan.

| Carpeta o archivo | Qué hay | Cómo se arma |
|---|---|---|
| `static/pretixbase/`, `static/pretixpresale/` | Íconos de la pestaña (favicon), logos del login, del panel y de las páginas de error, íconos del celular y el logo de los boletos PDF. Tienen **los mismos nombres que los de pretix** (por ejemplo `pretixbase/img/pretix-logo.svg`) para reemplazarlos sin tocar plantillas. | `generar_marca.py` |
| `static/fonts/bricolage/` | Letra de la marca, **Bricolage Grotesque** (licencia SIL OFL 1.1, ver `OFL.txt`): la variable completa en `.woff2` para el navegador y `.ttf` fijas para los PDF. | Bajada de Google Fonts el 10/10/2026 |
| `static/andina_marca/marca.css` | Estilo de la barra de arriba de la tienda. | A mano |
| `templates/` | Plantillas que reemplazan a las de pretix (pie y línea separadora de los correos, página de inicio `/`) y las nuestras (`andina_marca/barra_tienda.html`, `andina_marca/email_letra.html`). | A mano |
| `locale/es/` | Las frases en castellano de pretix que nombran al sistema ("su cuenta de pretix" → "su cuenta de AndinaTickets"). Solo esas; el resto de la traducción sigue siendo la de pretix. | `generar_textos.py` |
| `apps.py`, `signals.py` | La app `pretix.andina_marca`: registra la letra en pretix (para tiendas, boletos y facturas) y hace que los diseños de boleto nuevos salgan con ella. | A mano |

## Cambiar el logo, los colores o el nombre

1. Editar las constantes de arriba de `generar_marca.py` (nombre, colores; el dibujo del ícono
   es `CERROS`). Cuando esté el logo definitivo, reemplazar el dibujo por el logo.
2. Generar (desde la carpeta del repositorio; usa un contenedor descartable):

   ```bash
   MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD/src/pretix/andina_marca:/marca" python:3.13-slim sh -c "pip install -q pillow fonttools uharfbuzz && python /marca/generar_marca.py"
   ```

3. En el navegador, recargar con **Ctrl+F5** (guarda las imágenes viejas un tiempo).

Usar el mismo ícono en la cartelera (`AndinaTickets-Cartelera`: `public/favicon.svg` y la cabecera
en `src/layouts/Base.astro`) y en la app de la puerta (`AndinaTickets-Puerta`:
`andina/marca/generar.py`).

El nombre del sistema que aparece en la pestaña, en el remitente y en los correos es
`PRETIX_INSTANCE_NAME` (`src/pretix/settings.py`, o `instance_name` en `pretix.cfg`). Los colores
del panel y la tienda están en los `.scss` de pretix marcados con "AndinaTickets" (ver
`ANDINA.md`, "Cambios al núcleo de pretix").

## Después de actualizar pretix

```bash
docker exec andina-tickets-web-1 python /pretix/src/pretix/andina_marca/generar_textos.py
```

y reiniciar el contenedor `web` (compila los textos al arrancar). Revisar también si pretix
cambió las plantillas que reemplazamos en `templates/`.

## Lo que se deja a propósito

- **"impulsado por AndinaTickets basado en pretix (Código fuente)"** al pie de las páginas: la
  licencia de pretix (punto 2 de los términos adicionales) obliga a mantenerlo, con "pretix"
  enlazado a pretix.eu. Se configura en el panel: Administración → Licencia.
- En los correos, el pie dice "AndinaTickets · basado en pretix".
- Las frases sobre la licencia, las versiones y las actualizaciones de pretix siguen diciendo
  "pretix", porque hablan del programa.
- Cada productora puede cargar su logo y sus colores en el panel: se ven debajo de la barra de
  AndinaTickets, que está siempre.
