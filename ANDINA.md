# AndinaTickets

AndinaTickets es un fork de [pretix](https://pretix.eu/) adaptado para Argentina:
butacas numeradas, salas por sectores, boletería, Mercado Pago y portal de productores.

Este archivo es la guía del fork: qué cambiamos de pretix, dónde vive lo nuestro y
cómo traer actualizaciones de pretix sin perder nuestro trabajo. La lista de cambios, con
qué es propio y qué no, está en [CAMBIOS.md](CAMBIOS.md). Para instalar todo en otra PC
con Windows (y pasarle los datos), ver [INSTALAR.md](INSTALAR.md).

## Dónde vive lo nuestro

| Qué | Dónde |
|---|---|
| Entorno de desarrollo (Docker) | `deployment/docker/Dockerfile.dev`, `dev-entrypoint.sh`, `docker-compose.dev.yml` |
| Salas, plan de butacas, selector, boletería | `src/pretix/plugins/andinaseating/` (plugin propio) |
| Cobro con Mercado Pago (Checkout Pro) | `src/pretix/plugins/andinamercadopago/` (plugin propio) |
| Portal de solo lectura para productores | `src/pretix/plugins/andinaproductores/` (plugin propio) |
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

Cada carga es de **venta** (al precio del producto) o de **cortesía** (regalo, a $0). Una
cortesía es simplemente una entrada de precio 0, sin campos extra: así la reconocen la
Boletería y el portal del productor. Las cortesías digitales se hacen con los vales de pretix
(precio fijado en 0); el plano de butacas muestra el precio del vale y solo los productos a
los que se aplica.

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
- El historial del pedido muestra los eventos de Mercado Pago con texto legible (`logentries.py`).

### Pruebas automáticas

```bash
docker exec -e PRETIX_DATABASE_BACKEND=sqlite3 -e PRETIX_DATABASE_NAME= andina-tickets-web-1   sh -c 'cd /pretix/src && python3 -m pytest --ds=tests.settings tests/plugins/andinamercadopago tests/plugins/andinaseating -p no:cacheprovider'
```

- `tests/plugins/andinamercadopago`: cobro, avisos y devoluciones de Mercado Pago.
- `tests/plugins/andinaseating`: boletería (venta y cortesía), canje de vales con plano e
  informe del productor. `andinaseating` es HYBRID: en las pruebas hay que activarlo en el
  organizador y en el evento (ver `conftest.py`).

- `--ds=tests.settings` es obligatorio: el contenedor define `DJANGO_SETTINGS_MODULE=pretix.settings`
  y pytest le da prioridad sobre `setup.cfg`.
- Las variables de base de datos hacen que use SQLite en memoria y no toque la base de desarrollo.
- La API de Mercado Pago se simula con `responses`: no hace falta conexión ni credenciales.

### Plugin andinaproductores

- Permiso propio "Portal del productor → Ver sus ventas" (a nivel organizador).
- El equipo del productor se crea en Equipos con SOLO ese permiso y sin eventos: así pretix no le
  da acceso a ninguna pantalla operativa (verificado: eventos, pedidos, productos, salas,
  boletería, configuración y exportaciones quedan bloqueados).
- Organizador → Productores (solo administradores): a cada evento se le asigna el equipo del
  productor y la comisión del servicio (%).
- Organizador → Mis ventas: entradas vendidas online, recaudación, comisión y neto, por tipo de
  entrada, por función y por día, con descarga en PDF. Sin datos de compradores. La boletería se
  informa aparte (ese dinero lo cobra el teatro).
- Importante: no usar el parámetro de URL `event` en vistas de organizador: el middleware de
  permisos del panel lo trata como pantalla de evento (por eso se llama `evento`).

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
| `src/pretix/_base_settings.py` | `'pretix.plugins.andinaseating'`, `'pretix.plugins.andinamercadopago'` y `'pretix.plugins.andinaproductores'` en `INSTALLED_APPS` | Cargar nuestros plugins |
| `src/pretix/presale/views/event.py` | `itemnum` se cuenta antes de quitar los productos con butaca | Que un producto sin butaca no aparezca precargado con cantidad 1 junto al plano |
| `src/pretix/presale/templates/pretixpresale/event/index.html` | Se pasa `add_to_cart_below` a la señal `render_seating_plan` | Mostrar un solo botón "Agregar al carrito" |
| `src/pretix/locale/es/LC_MESSAGES/django.po` | Se quitó un `<a` sobrante al final de "impulsado por {name} … basado en pretix" | Error de la traducción de pretix: rompía el pie de página |

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

- La excepción del punto 1 de `LICENSE` (no compartir el código) **no nos cubre**: el
  punto 1(d) excluye a quien usa pretix para vender productos o servicios de terceros, y
  AndinaTickets vende entradas de productores.
- Por eso hay que ofrecer el código fuente completo de lo que corre (núcleo modificado y
  plugins propios) a todos los que usan el sitio: compradores y productores.
- El aviso del pie de página no se puede quitar. Se reescribe como "impulsado por
  AndinaTickets · basado en pretix · Código fuente", con pretix enlazado a https://pretix.eu/.
- No se puede presentar como una distribución oficial de pretix.

Componentes de terceros incluidos en el plugin conservan su licencia (por ejemplo,
seatmap-canvas: MIT).

La única forma de no compartir el código es una licencia comercial de pretix. La Enterprise
estándar no permite vender entradas de terceros: para este caso piden una oferta individual
(https://pretix.eu/about/en/pricing/selfhosted, sales@pretix.eu).

### Qué es público y qué es privado

| Caja | Qué va | Dónde |
|---|---|---|
| **Público** (obligatorio) | Núcleo de pretix con nuestros cambios, plugins propios (`andina*`), Docker de desarrollo, pruebas, `ANDINA.md` | Este repositorio (público en GitHub) |
| **Privado** (permitido) | Contraseñas y credenciales, datos de compradores y ventas, copias de la base, planos reales de salas, configuración del servidor de producción, contratos, precios y comisiones de productores, plan de negocio | Carpeta `privado/` (Git la ignora) o fuera del repo |
| **Programas aparte** (permitido, cerrado) | Programas separados que solo hablan con AndinaTickets por la API y los webhooks de pretix (ver "Caja 3") | Otro repositorio, privado |

Decisión (03/10/2026): todo lo que corre dentro de AndinaTickets va en este repositorio
público, cumpliendo la licencia. Lo que nos diferencia a futuro puede ir en programas
privados aparte (caja 3), si cumplen sus reglas. Hasta el 02/10/2026 la decisión era no
armarlos.

Reglas:

- Si algo nuevo corre **dentro** de AndinaTickets (plugin, plantilla, cambio al núcleo), es público.
- Las credenciales nunca van en archivos: se cargan en el panel y quedan en la base de datos.
- Los datos de compradores están protegidos por la Ley 25.326: nunca van a Git ni a la carpeta `privado/`.
- Antes de cada `git push`, mirar `git status` y `git diff`: lo que se sube a GitHub queda
  público para siempre, aunque después se borre.

### Caja 3: programas privados aparte

Un código de activación en los plugins no protege nada: el código es público y la AGPL
permite quitarlo (y prohíbe sumar restricciones). Lo que sí puede ser cerrado es un programa
**separado** que use AndinaTickets desde afuera, como cualquier otro sistema.

Reglas para que un programa sea de la caja 3:

- Vive en **otro repositorio, privado**. Nunca en este.
- Corre como un programa aparte (otro contenedor o servidor), no adentro de pretix.
- Habla con AndinaTickets **solo** por la API REST y los webhooks (avisos automáticos de
  pretix: pedido creado, pagado, cancelado, devolución, ingreso en puerta, etc.).
- No importa ni copia código de pretix ni de los plugins `andina*`.
- Si algo tiene que aparecer dentro de la tienda o del panel (un botón, un link), esa parte
  va en un plugin público y se mantiene chica; la "inteligencia" queda afuera.
- Si saca datos de compradores fuera de pretix, rige la Ley 25.326: consentimiento para
  marketing (casilla en la compra), base protegida y registrada, y forma de darse de baja.
- No duplicar lo que pretix ya trae libre: lista de espera, widget para webs de productores,
  app de control de acceso (pretixSCAN) y exportaciones básicas.

La lista de ideas y el orden en que se piensan hacer son plan de negocio (caja 2): están en
`privado/PlanDeNegocios.md`, que no se sube a Git.

Otras protecciones que no son código: registrar la marca AndinaTickets en el INPI (la AGPL
no da derecho a usar el nombre) y, si se quiere cerrar los plugins actuales, pedirle una
licencia comercial a pretix (sales@pretix.eu).

### Verificación de la licencia (en cada instalación)

En *Parametrizaciones globales → Verificación de la licencia* (solo administradores):

| Campo | Valor |
|---|---|
| Uso | Vender entradas de otros organizadores (empresa de ticketing) |
| Cambios | Incluye cambios o extensiones al código fuente |
| Licencia | AGPLv3 sin restricción de uso (sin el permiso adicional) |
| Plugins | Marcar solo "creados internamente" (los `andina*`) |
| Nombre del pie | `AndinaTickets` |
| Link del nombre | `https://github.com/santiago14-2018/AndinaTickets` (o el sitio de AndinaTickets cuando exista) |
| Instrucciones del código fuente | Link a este repositorio, a pretix y a `LICENSE` |

Con eso el pie de cada página muestra "impulsado por AndinaTickets · basado en pretix ·
Código fuente", y "Código fuente" lleva a `/agpl_source`. La pantalla solo deja dos avisos
amarillos que recuerdan publicar los cambios y los plugins: es lo que hace este repositorio.
