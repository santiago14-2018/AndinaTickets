# Marca de AndinaTickets

Todo lo que cambia la cara de pretix por la de AndinaTickets, en un solo lugar. Django busca
**primero acá** y después en pretix (`ANDINA_MARCA_DIR` en `src/pretix/_base_settings.py`), así
que los archivos de pretix quedan intactos y las actualizaciones de pretix no chocan.

| Carpeta | Qué hay | Cómo se arma |
|---|---|---|
| `static/` | Íconos de la pestaña (favicon), logos del login, del panel y de las páginas de error, íconos del celular y el logo de los boletos PDF. Tienen **los mismos nombres que los de pretix** (por ejemplo `pretixbase/img/pretix-logo.svg`) para reemplazarlos sin tocar plantillas. | `generar_marca.py` |
| `templates/` | Plantillas que reemplazan a las de pretix: pie de los correos, línea separadora de los correos y la página de inicio (`/`). | A mano |
| `locale/es/` | Las frases en castellano de pretix que nombran al sistema ("su cuenta de pretix" → "su cuenta de AndinaTickets"). Solo esas; el resto de la traducción sigue siendo la de pretix. | `generar_textos.py` |

## Cambiar el logo, los colores o el nombre

1. Editar las constantes de arriba de `generar_marca.py` (nombre, colores; el dibujo del ícono
   es `CERROS`). Cuando esté el logo definitivo, reemplazar el dibujo por el logo.
2. Generar:

   ```bash
   docker exec andina-tickets-web-1 python /pretix/src/pretix/andina_marca/generar_marca.py
   ```

3. En el navegador, recargar con **Ctrl+F5** (guarda las imágenes viejas un tiempo).

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
- **pretixSCAN** es el nombre de la app de pretix: nuestra versión propia del escáner se renombra
  en su propio repositorio (AndinaTickets-Puerta).
