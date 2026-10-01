# AndinaTickets

AndinaTickets es un fork de [pretix](https://pretix.eu/) adaptado para Argentina:
butacas numeradas, salas por sectores, boletería y (próximamente) MercadoPago.

Este archivo es la guía del fork: qué cambiamos de pretix, dónde vive lo nuestro y
cómo traer actualizaciones de pretix sin perder nuestro trabajo.

## Dónde vive lo nuestro

| Qué | Dónde |
|---|---|
| Entorno de desarrollo (Docker) | `deployment/docker/Dockerfile.dev`, `dev-entrypoint.sh`, `docker-compose.dev.yml` |
| Salas, plan de butacas, selector, boletería | `src/pretix/plugins/andinaseating/` (plugin propio) |
| Cobro con Mercado Pago (Checkout Pro) | `src/pretix/plugins/andinamercadopago/` (plugin propio) |
| Librería de planos seatmap-canvas (MIT, compilada) | `src/pretix/plugins/andinaseating/static/pretixplugins/andinaseating/vendor/seatmap-canvas/` |

### Plugin andinaseating: pantallas

| Pantalla | Dónde | Para qué |
|---|---|---|
| Salas | Organizador → Salas | Crear salas; generar sectores por parámetros (filas, butacas, pasillo, curva, filas alternadas) con vista previa en vivo, o subirlos como JSON o CSV |
| Tienda | Página del evento | Plano para elegir butacas (seatmap-canvas), sincronizado con la lista de butacas, que queda como alternativa accesible |
| Plan de butacas | Evento → Plan de butacas | Elegir sala (por fecha en una serie) y conectar categorías con productos y cupos |
| Boletería | Evento → Boletería | Reservar butacas para venta presencial y cargar boletos impresos (CSV `codigo;fila;butaca`) |

Los boletos impresos se cargan como entradas del canal de venta **Boletería**
(`api.boleteria`), con el código del boleto como código de la entrada. En la puerta se
escanean igual que una entrada online (pretixSCAN o check-in web).

### Plugin andinamercadopago

- Modelo: todo el dinero entra a una sola cuenta de Mercado Pago (la de la plataforma).
- Credenciales: Administración → Configuración global (access token de producción, de prueba,
  clave secreta de notificaciones y texto del resumen de tarjeta). En cada evento solo se activa
  "Mercado Pago" en Configuración → Pagos. La moneda del evento tiene que ser ARS.
- Medios: tarjeta de crédito, débito y dinero en cuenta. Sin efectivo ni cajeros, y en modo
  binario (aprobado o rechazado), para que las butacas no queden esperando pagos lentos.
- El estado del pago siempre se consulta a la API de Mercado Pago (al volver el comprador y por
  webhook); nunca se confía en los parámetros recibidos.
- Los avisos (webhook) solo se piden si el sitio es público con https.

### Actualizar seatmap-canvas

```bash
git clone https://github.com/alisaitteke/seatmap-canvas.git && cd seatmap-canvas
npm ci && npm run build
# copiar dist/cjs/seatmap.canvas.js como seatmap.canvas.min.js y dist/seatmap.canvas.css
# quitar la línea "//# sourceMappingURL=..." del .js (no incluimos el .map)
# actualizar VERSION.txt
```

Regla: **todo lo nuevo va en el plugin**. El núcleo de pretix se toca solo cuando no
hay otra forma, y cada cambio se marca con un comentario `AndinaTickets:` y se anota abajo.

## Cambios al núcleo de pretix

Revisar esta lista en cada actualización desde pretix.

| Archivo | Cambio | Por qué |
|---|---|---|
| `src/pretix/_base_settings.py` | `'pretix.plugins.andinaseating'` y `'pretix.plugins.andinamercadopago'` en `INSTALLED_APPS` | Cargar nuestros plugins |
| `src/pretix/presale/views/event.py` | `itemnum` se cuenta antes de quitar los productos con butaca | Que un producto sin butaca no aparezca precargado con cantidad 1 junto al plano |
| `src/pretix/presale/templates/pretixpresale/event/index.html` | Se pasa `add_to_cart_below` a la señal `render_seating_plan` | Mostrar un solo botón "Agregar al carrito" |

## Remotos de Git

| Remoto | URL | Uso |
|---|---|---|
| `origin` | https://github.com/santiago14-2018/AndinaTickets.git | Nuestro repositorio. Acá se sube todo. |
| `upstream` | https://github.com/pretix/pretix | pretix original. **Solo lectura**: el push está deshabilitado. |

## Traer una actualización de pretix

Usar solo versiones publicadas (tags `vAAAA.M.P`), nunca la rama `master` de pretix.

```bash
git fetch upstream --tags
git switch -c actualizar-pretix-v2026.8.0 main
git merge v2026.8.0
# resolver conflictos si los hay (mirar la tabla "Cambios al núcleo")
docker compose -f deployment/docker/docker-compose.dev.yml up -d --build
# probar: tienda, carrito con butacas, Salas, Plan de butacas, boletería
git switch main
git merge actualizar-pretix-v2026.8.0
git push origin main
```

Si una actualización trae migraciones de base de datos, el contenedor `web` las aplica
solo al arrancar (`dev-entrypoint.sh`).

## Licencia (resumen, no es asesoramiento legal)

pretix se publica bajo AGPLv3 con términos adicionales (ver `LICENSE`). AndinaTickets
es un trabajo derivado y hereda esas condiciones:

- Si se usa para vender entradas de terceros o se ofrece como servicio, hay que ofrecer
  el código fuente completo de AndinaTickets a sus usuarios.
- El aviso del pie de página no se puede quitar. Se puede reescribir como
  "powered by AndinaTickets based on pretix, source code available at
  https://github.com/santiago14-2018/AndinaTickets", con la palabra pretix enlazada a
  https://pretix.eu/.
- No se puede presentar como una distribución oficial de pretix.

Componentes de terceros incluidos en el plugin conservan su licencia (por ejemplo,
seatmap-canvas: MIT).
