# Registro de cambios de AndinaTickets

Qué le fuimos agregando y corrigiendo a pretix, del más nuevo al más viejo.

## Punto de partida

- **pretix** (Community Edition, AGPLv3 con términos adicionales), rama `master` al
  25/09/2026: commit `2af8d29ca`, versión `2026.8.0.dev0` (posterior a `v2026.7.0`).
- Todo lo de pretix es de pretix. Este registro anota solo lo que cambió desde ahí.

## Cómo leer cada renglón

Cada cambio empieza con una marca que dice de quién es:

| Marca | Qué significa | ¿Sirve para un sistema nuevo? |
|---|---|---|
| **[PROPIO]** | Lo escribimos nosotros, en archivos nuevos (plugins `andina*`, Docker, documentos). | Sí: la idea siempre, y el código según lo que dice la tabla del final. |
| **[PRETIX]** | Arreglo nuestro dentro de un archivo de pretix. | Solo la idea: el archivo es de pretix. |
| **[TERCEROS]** | Código de otro proyecto, con su propia licencia. | Sí, respetando su licencia. |

Regla: cada cambio nuevo suma un renglón acá, en la misma entrega (commit) que el cambio.

---

## 2026-10-13

- [PROPIO] `andinaseating` (tienda): un recuadro por sector, cada uno con su plano, su leyenda y su
  lista de butacas. Solo aparecen los sectores habilitados (con producto en el evento); los que
  quedaron "Sin asignar" no se muestran. Antes se veía toda la sala junta en un solo plano.
- [PRETIX] Plantillas base (tienda, panel, ingreso, error y check-in web): la dirección del ícono de
  la pestaña lleva `?v=andina`, para que el navegador deje de mostrar el ícono de pretix que tenía
  guardado de antes (el servidor ya entregaba el nuestro).
- [PRETIX] `settings.py`: los eventos nuevos arrancan con nuestros complementos activos (butacas,
  boletería, cortesías y cargo por servicio; Mercado Pago; entradas en PDF; check-in web). Antes
  pretix solo activaba correo, estadísticas y listas de ingreso, y en un evento nuevo no aparecía
  "Plan de butacas" ni se cobraba el cargo por servicio.

## 2026-10-12

- [PRETIX] `settings.py`: plantillas en memoria también en desarrollo, y en desarrollo los estilos
  SCSS con un compilador que guarda el resultado ([PROPIO] `pretix/helpers/andina_sass.py`). Las
  páginas del entorno de desarrollo bajaron de ~8 segundos (12 la lista de pedidos) a 1–2. La
  causa: leer el código de `D:\` desde Docker es ~100 veces más lento que dentro de Linux. Ver
  `ANDINA.md`, "Entorno de desarrollo lento".
- [PROPIO] Mercado Pago: el regreso automático (`auto_return`) solo se pide con un sitio público
  https, como los avisos. En la primera prueba real (modo de prueba, en esta PC) Mercado Pago lo
  rechazaba: "auto_return invalid. back_url.success must be defined". Prueba nueva en
  `test_mercadopago.py`; pasos para probar con cuentas de prueba en `ANDINA.md`.
- [PROPIO] Mercado Pago, modo de prueba: no se pasa el correo del pedido como comprador (Mercado
  Pago frenaba el pago con "No pudimos procesar tu pago" porque el comprador no era una cuenta de
  prueba). En pedidos reales se sigue pasando.
- [PRETIX] `pretixpresale/event/checkout_base.html`: el carrito se ve siempre completo en la compra
  (con el cargo por servicio y el total), sin el botón "Mostrar carrito completo".
- [PROPIO] Mercado Pago: el texto del pago dice "tocá Volver al sitio" cuando el regreso no es
  automático (sitio sin https).
- [PROPIO] Mercado Pago: botón "Ya pagué: verificar el pago" en el pedido pendiente, que busca el
  pago en Mercado Pago por la referencia del pedido. Para quien pagó y no volvió a la tienda (en
  la prueba del 12/10, Mercado Pago no mostró ningún botón para volver).
- [PROPIO] Portal del productor: recuadro **Liquidación** en Mis ventas → evento, con el
  comprobante en PDF, que se le pide al programa privado nuevo **AndinaTickets-Liquidaciones**
  (caja 3: repositorio aparte, lee las ventas por la API). El PDF de "Mis ventas" pasa a llamarse
  `ventas-…pdf` (era `liquidacion-…pdf`). Configuración `ANDINA_LIQUIDACIONES_URL` y
  `ANDINA_LIQUIDACIONES_CLAVE`. Pruebas en `test_portal_liquidacion.py`.
- Equipo de pretix nuevo "Liquidaciones (solo lectura)" (ver pedidos de todos los eventos), con
  el token que usa ese programa.
- [PROPIO] Cartelera: propiedades de evento **genero** (lista: Teatro, Humor, Música, Danza,
  Infantil, Fiesta), **ciudad** y **destacado** (Sí/No) en el organizador, cargadas en los tres
  eventos de prueba (en la base, no en el código).
- [PROPIO] Salas, generador de sectores: opción **Numeración** (corrida 1, 2, 3…; impares 1, 3,
  5…; pares 2, 4, 6…), que se combina con "Primera butaca" y "de derecha a izquierda". Los
  sectores impares y pares se ponen uno al lado del otro a mano.
- [PROPIO] Planos del panel (Salas y Boletería): cada butaca muestra su **número**
  (`seatmap-andina.js` lo dibuja; la librería no lo hace). En la vista previa el sector nuevo va
  en naranja, sin el tilde que tapaba el número. `seats_to_blocks` suma `custom_data` en lugar de
  reemplazarlo.
- [PROPIO] Generador: los errores se marcan y se borran **mientras se escribe** y "Agregar a la
  sala" se deshabilita mientras haya uno. Antes, un error de un intento anterior quedaba en rojo
  aunque el valor ya estuviera bien. Pruebas en `test_generador.py`.
- [PROPIO] Planos del panel (Salas, Boletería y Cortesías) más altos (620 px, eran 460) y
  **agrandables** arrastrando la esquina de abajo a la derecha (`resize: vertical` en
  `control.css`). Al soltar, el plano se reacomoda y se vuelve a ver la sala entera; el alto
  elegido se recuerda en ese navegador. El plano de la tienda no cambia.
- [PROPIO] Salas, generador: **Letra de la fila** a la izquierda, a la derecha o a los dos lados,
  en todos los planos (Salas, Boletería, Cortesías y tienda). Se guarda por sala y sector en la
  configuración del organizador (`andina_rotulos_<sala>`): el formato de salas de pretix no
  admite datos extra. Al quitar un sector se olvida su lado.
- [PROPIO] Salas, generador: **Ubicación** del sector (debajo de todo, o a la derecha, a la
  izquierda o debajo de otro sector de la sala). Antes siempre iba abajo de todo, y al
  regenerar un sector existente se mudaba abajo: ahora queda donde estaba. Si un sector queda
  a la izquierda del primero, se corre toda la sala. Pruebas en `test_generador.py`.
- [PROPIO] Salas: cada sector es independiente. El generador ya no pide "Categoría" (la categoría
  de pretix es el nombre del sector), tiene el botón **"Nuevo sector"** (formulario en blanco) y
  "Guardar sector"; el nombre es obligatorio. La lista "Sectores" ya no muestra categorías.
- [PROPIO] Salas: **Nuevo** y **Editar** separados. "Nuevo sector" no deja repetir un nombre de
  la sala (avisa mientras se escribe). "Editar", en la lista "Sectores", carga la configuración
  con que se generó el sector (sale del historial de la sala) y al guardar lo reemplaza en su
  lugar (ubicación "Donde está"); el nombre no se cambia al editar. Los sectores subidos desde
  archivo no se pueden editar (se quitan y se suben de nuevo).
- [PROPIO] Salas: al entrar (y después de guardar) la pantalla queda lista para el **alta** de un
  sector: plano vacío y formulario en blanco; mientras se completa se ve **solo ese sector**.
  "Editar" muestra solo el sector que se edita. La ubicación en la sala es opcional y va plegada
  (con la casilla "Ver junto con los otros sectores"). La sala entera se dibuja solo con "Ver la
  sala completa" (`?ver=sala`), en la lista de sectores.
- [PROPIO] Planos del panel: el nombre de cada sector (que la librería escribe en el medio, en
  gris oscuro sobre fondo oscuro) va blanco con borde oscuro: se lee sobre cualquier fondo.
- [PROPIO] Salas: botones **"Exportar"** (cada sector) y **"Exportar sala completa"**: bajan un JSON en
  el formato de planos de pretix (validado), que se vuelve a subir con "Subir un sector desde un
  archivo" o se importa en cualquier pretix (`export_sector` en `layout.py`, vista
  `SalaExportView`). La letra de la fila a la derecha no viaja en el archivo. Las salas de hoy
  quedaron exportadas en `privado/salas/` (no va a Git).
- [PROPIO] Salas: al ubicar un sector al lado de otro se deja lugar para las letras de las filas
  (antes los sectores se encimaban si las letras quedaban en el medio).
- [PROPIO] Evento → Plan de butacas habla de **sectores**: cada sector se conecta con un producto
  (varios sectores pueden ir con el mismo producto). Si una sala subida desde archivo agrupa
  sectores en una categoría, se ven los sectores y, abajo, la categoría.
- Copias de seguridad nuevas en `privado/copias/` (base de datos y archivos subidos), después de
  que Docker Desktop, al actualizarse, pasara al modo VMM con un disco vacío (se volvió a WSL 2).

## 2026-10-10

- [PROPIO] Marca propia en `src/pretix/andina_marca/` (ver su `LEEME.md`), que Django busca antes
  que lo de pretix: favicon de la pestaña, logos del login, del panel y de las páginas de error,
  íconos del celular y logo de los boletos PDF (ícono provisorio de cerros blancos sobre violeta,
  hecho por `generar_marca.py`); pie y línea separadora de los correos; página de inicio `/`; y las
  36 frases en castellano que decían "pretix" por el sistema (`generar_textos.py`).
- [PRETIX] `_base_settings.py`: `ANDINA_MARCA_DIR` primero en textos, plantillas y archivos
  estáticos; color principal `#5b2a73` (correos y tiendas sin color propio). `settings.py`: nombre
  del sistema por defecto "AndinaTickets" (era "pretix.de": salía en la pestaña, como remitente y
  en los correos de cuenta y contraseña).
- [PRETIX] Violetas de la marca en los `.scss` de pretix (`#5b2a73`, barra superior `#3e1b4f`) y en
  el color de la barra del navegador (`theme-color`, manifiesto, gráficos de estadísticas).
- [PRETIX] Correos (`pretixbase/email/base.html` y `simple_logo.html`): franja violeta arriba en
  lugar del semicírculo de "boleto" de pretix, y fondo lila.
- [PROPIO] `docker-compose.dev.yml`: remitente `andinatickets@localhost` (era `pretix@localhost`).
- [TERCEROS] Letra de la marca **Bricolage Grotesque** (licencia SIL OFL 1.1, de Google Fonts) en
  `andina_marca/static/fonts/bricolage/`: la variable completa en `.woff2` para el navegador y
  versiones fijas `.ttf` para los PDF, con su `OFL.txt`.
- [PROPIO] `andina_marca` pasa a ser también una app (`pretix.andina_marca` en `INSTALLED_APPS`)
  que registra la letra en pretix (se puede elegir en tiendas, boletos y facturas) y hace que los
  diseños de boleto nuevos salgan con ella. Los tres diseños de boleto de los eventos de prueba
  se pasaron a la letra nueva.
- [PRETIX] La letra de la marca en todos lados: `webfont.scss` (se agrega), `_theme_variables.scss`
  (letra por defecto del panel y la tienda), `auth.scss` y `error.scss` (ahora cargan la letra),
  `base/settings.py` (letra por defecto de tiendas y facturas) y los correos (`email/base.html`,
  `simple_logo.html`, con la letra descargada de nuestro servidor; si el programa de correo no la
  carga, usa una parecida).
- [PRETIX] `pretixpresale/base.html`: barra con el logo de AndinaTickets arriba de toda la tienda
  (`andina_marca/templates/andina_marca/barra_tienda.html`, estilo en `andina_marca/marca.css`);
  lleva a la cartelera (`ANDINA_CARTELERA_URL` en `docker-compose.dev.yml` y en el `.env`).
- [PROPIO] Logos con el nombre dibujado con la letra de la marca (en curvas: se ve igual aunque la
  computadora no tenga la letra). `generar_marca.py` ahora corre en un contenedor aparte.
- [PROPIO] Se borró el APK de prueba del lector (`static/andina_apk/`): el aro de enfoque funciona.
- [PROPIO] `ANDINA.md`: AndinaScan anotada como excepción a "no duplicar lo que pretix trae libre".
- [PROPIO] **Cargo por servicio** (`andinaseating/cargo.py`): el comprador paga un porcentaje del
  precio de las entradas (10 % por defecto), online (señales de cargos de pretix, se ve en el
  carrito, el correo y el pedido) y en la boletería (se suma al vender cada boleto de papel). Las
  cortesías no pagan. La caja de la boletería separa entradas y cargo. Pruebas en `test_cargo.py`;
  `test_venta_boleteria.py` ahora espera el total con cargo.
- [PROPIO] Organizador → Productores: columna "Cargo por servicio (%)" para cambiarlo en cada
  evento (por ejemplo, menos para un festival grande).

## 2026-10-07

- [PROPIO] `docker-compose.dev.yml`: PostgreSQL con 300 conexiones (eran 100). Con escáneres
  conectados, el servidor de desarrollo agotaba las conexiones (pretix las mantiene 2 minutos) y
  la app recibía un error 500 al escanear ("too many clients already").
- [PROPIO] `docker-compose.dev.yml`: la dirección del sistema se puede cambiar con `ANDINA_URL` en
  `deployment/docker/.env` (Git lo ignora; por defecto sigue `http://localhost:8130`). Hace falta
  para conectar celulares de la red local con pretixSCAN: el QR de conexión lleva esa dirección.

## 2026-10-05

- [PROPIO] Boletería, ajustes de pantalla: los códigos largos de la tabla de boletos se parten
  en dos renglones (la tabla entra en el panel), el botón de "Paquetes generados" dice
  "Descargar ZIP", y los lotes anulados enteros ya no se listan.
- [PROPIO] Documentación (en `privado/documentacion/`, no va a Git): Manual de usuario v4 y guía
  técnica v5, con la boletería, la venta en el mostrador, las cortesías y la descarga de entradas.
- [PROPIO] Boletería: los boletos de papel de **venta se activan al venderlos** (generados o
  traídos por la imprenta). Hasta que el boletero los vende no entran en la puerta: un boleto
  perdido sin vender no sirve. Panel "Vender boletos de papel" (se escanean uno tras otro, se
  elige el medio de pago; todo o nada), "Caja de la boletería" por medio de pago y por
  boletero, estado de cada boleto (sin vender, vendido, válido, anulado) y "Anular los sin
  vender". Cada boleto de venta es su propio pedido; vence al día siguiente de la función. El
  informe del productor cuenta solo lo vendido. El paquete para la imprenta se arma por lote.
  7 pruebas nuevas (`test_venta_boleteria.py`): 57 en total.
- [PROPIO] Boletería: **generar boletos para la imprenta**. AndinaTickets crea los códigos
  (con butacas elegidas en el plano o, sin numerar, por cantidad) y arma un paquete ZIP:
  entradas en PDF listas para imprimir, un QR por boleto (PNG), planilla y LEEME para la
  imprenta (`imprenta.py`). De venta o de cortesía; las butacas quedan reservadas.
- [PROPIO] La Boletería funciona también en eventos y fechas sin butacas numeradas (solo la
  generación por cantidad; reservar butacas y cargar el CSV de la imprenta siguen siendo para
  numeradas). Controla los cupos, que el importador de pretix no mira.
- [PROPIO] Pantalla nueva **Cortesías** (Evento → Cortesías): nombre, email y butacas (o
  cantidad); al invitado le llega la entrada con QR por email. Sin email queda como lista de
  invitados. Reenviar y anular. Canal de venta nuevo `api.cortesias`; el informe del productor
  las cuenta como cortesías digitales. Avisa si el evento no permite descargar entradas.
- [PROPIO] `boleteria.py`: una sola función (`run_import`) para crear entradas con el
  importador de pedidos; la usan la carga de la imprenta, la generación y las cortesías.
- [PROPIO] 17 pruebas nuevas (`test_imprenta.py`, `test_cortesias.py`).
- [PROPIO] Datos: en DEMO – Hamlet y DEMO – Noches de Risa se activó la descarga de entradas en
  PDF (venía apagada, como en pretix por defecto): sin eso los compradores no reciben la
  entrada. Es configuración en la base, no código.

## 2026-10-03

- [PROPIO] `ANDINA.md`: nueva "caja 3" (programas privados aparte que usan solo la API y los
  webhooks de pretix), con sus reglas. Cambia la decisión del 02/10 de no armar programas
  aparte. La lista de ideas es plan de negocio y queda en `privado/`.
- [PROPIO] La documentación en Word pasa a `privado/documentacion/` (las versiones viejas en
  `anteriores/`), así se respalda junto con el resto de `privado/`. `INSTALAR.md` y
  `privado/LEEME.md` actualizados.
- [PROPIO] `.dockerignore`: se excluye `privado/`, para que al armar la imagen Docker no lea
  las copias de la base ni los documentos (los Dockerfile ya no los copiaban).

## 2026-10-02

- [PROPIO] Arreglo: en el plano del comprador todas las butacas libres eran blancas y no se
  sabía cuál era de Platea y cuál de Pullman. seatmap-canvas guarda un color por butaca pero
  no lo usa al dibujar; ahora nuestro código le pone la clase de color de su producto y el CSS
  la pinta de ese color sólido. La leyenda pasó a cuadrados sólidos del mismo color (y gris
  para "No disponible"). La butaca elegida lleva borde blanco y tilde.
- [PROPIO] Arreglo: el nombre del sector quedaba tapado por las butacas. Ahora va en blanco
  arriba de la primera fila, dentro del fondo del sector (`seatmap.py`, `_add_titles`), y se
  oculta el título original de la librería. Solo en el plano del comprador. Con pruebas
  (`test_plano.py`).
- [PROPIO] Plano del comprador más grande: el alto de la caja ya no es fijo (420 px) sino que
  se calcula con la forma de la sala, entre 320 px y el 80 % de la pantalla
  (`seatmap-andina.js`, `fitHeight`). Las butacas se ven más grandes y sin costados vacíos.
- [PROPIO] Datos: en la sala Teatro Andino el Pullman salteaba la fila I (iba de J a M). Se
  renombró a I–L en la sala y en DEMO – Hamlet, con sus identificadores (`pullman-I-1`…).
  Las 8 entradas vendidas siguen en el mismo asiento físico, con la letra nueva. Es un
  cambio en la base de datos, no código; antes se guardó una copia en `privado/copias/`.
- [PROPIO] `docker-compose.dev.yml`: arreglo de la dirección del sistema (`PRETIX_PRETIX_URL`),
  que quedaba en `http://localhost:8000` aunque el panel está en el 8130. Los links del panel
  ("URL de la tienda") y de los correos apuntaban a un puerto donde no hay nada.
- [PROPIO] `INSTALAR.md`: guía para instalar el entorno en otra PC con Windows, pasarle los
  datos (copia de la base y de la clave secreta) y trabajar por escritorio remoto.
- [PROPIO] `docker-compose.dev.yml`: el comentario decía puerto 8124; el real es 8130.
- [PROPIO] Boletería: al cargar boletos impresos se elige **venta** (precio del producto) o
  **cortesía** (regalo, $0). La tabla muestra el tipo y el total de cortesías.
- [PROPIO] Portal del productor (pantalla y PDF): las cortesías (vales a $0 y boletos de
  cortesía) no cuentan como vendidas; se informan aparte, sin dinero ni comisión.
- [PROPIO] Arreglo: al canjear un vale, el plano de butacas mostraba el precio normal y
  ofrecía productos a los que el vale no se aplica. Ahora muestra el precio del vale y solo
  sus productos.
- [PROPIO] Pruebas automáticas de boletería, cortesías, canje de vales e informe del productor.
- [PROPIO] Reglas de qué es público y qué es privado (`ANDINA.md`) y carpeta `privado/`, que
  Git ignora.
- [PRETIX] Arreglo de la traducción al español: el texto "impulsado por … basado en pretix"
  terminaba con un `<a` suelto que rompía el pie de página
  (`src/pretix/locale/es/LC_MESSAGES/django.po`).
- [PROPIO] Configuración de la verificación de la licencia: pie "impulsado por AndinaTickets ·
  basado en pretix · Código fuente". Es configuración en la base de datos, no código.
- [PROPIO] Este registro de cambios.

## 2026-10-01

### Mercado Pago
- [PROPIO] Plugin `andinamercadopago`: cobro con Mercado Pago Checkout Pro, todo a una sola
  cuenta. Tarjeta de crédito, débito y dinero en cuenta, sin efectivo, en modo binario
  (aprobado o rechazado).
- [PROPIO] El estado del pago siempre se consulta a la API de Mercado Pago (al volver el
  comprador y por aviso automático con firma verificada); nunca se confía en lo recibido.
- [PROPIO] Devoluciones totales y parciales desde el panel, y registro de devoluciones o
  contracargos hechos desde Mercado Pago.
- [PROPIO] Historial del pedido con textos legibles en español.
- [PROPIO] 22 pruebas automáticas con la API de Mercado Pago simulada.
- [PROPIO] Arreglo: se reemplazó `build_absolute_uri`, que pretix marca como obsoleta, por
  `eventreverse_absolute`.

### Portal de productores
- [PROPIO] Plugin `andinaproductores`: permiso "Portal del productor → Ver sus ventas". El
  productor solo ve sus ventas: entradas, recaudación, comisión del servicio y neto, por tipo
  de entrada, por función y por día, con descarga en PDF. Sin datos de compradores.
- [PROPIO] Pantalla de administración para asignar a cada evento su productor y su comisión.

### Butacas, salas y boletería
- [PROPIO] Plugin `andinaseating`: salas por organizador, con sectores subidos en JSON o CSV.
- [PROPIO] Generador de sectores por parámetros (filas, butacas, pasillo, curva, filas
  alternadas) con vista previa en vivo.
- [PROPIO] Plan de butacas por evento y por fecha de una serie: conecta cada categoría de la
  sala con un producto y crea su cupo.
- [PROPIO] Plano de butacas para el comprador en la tienda, sincronizado con una lista
  accesible de butacas.
- [PROPIO] Boletería: butacas reservadas para venta presencial y carga de boletos impresos de
  imprenta (CSV `codigo;fila;butaca`), que se escanean en la puerta como cualquier entrada.
- [TERCEROS] seatmap-canvas 2.7.6 (MIT, de Ali Sait Teke), incluido compilado en el plugin.
- [PROPIO] Ajustes sobre seatmap-canvas, en nuestros propios archivos: sin las "máscaras" de
  sectores, coordenadas corridas a valores positivos y cartel con el nombre de la butaca.
- [PRETIX] `src/pretix/_base_settings.py`: registrar los plugins `andina*`.
- [PRETIX] `src/pretix/presale/views/event.py`: un producto sin butaca ya no aparece
  precargado con cantidad 1 junto al plano.
- [PRETIX] `src/pretix/presale/templates/pretixpresale/event/index.html`: un solo botón
  "Agregar al carrito" cuando hay plano.

### Entorno y documentación
- [PROPIO] Entorno de desarrollo con Docker (`deployment/docker/`): proyecto `andina-tickets`
  con PostgreSQL, Redis y Mailpit, en español y con hora de Buenos Aires.
- [PROPIO] Arreglo: la imagen de desarrollo no compilaba porque faltaba copiar `_build/`.
- [PROPIO] `.gitattributes`: saltos de línea LF en los scripts de shell (en Windows fallaban
  dentro de Docker).
- [PROPIO] `ANDINA.md`: guía del fork, cambios al núcleo y cómo traer actualizaciones de pretix.

---

## Qué se puede llevar a un sistema nuevo

Las ideas, las reglas y los casos de prueba se llevan siempre. El código depende de cuánto
use las piezas de pretix (pedidos, pagos, butacas, permisos):

| Pieza | Código reutilizable tal cual | Hay que reescribir |
|---|---|---|
| Mercado Pago | `mp_api.py`: llamadas a la API y verificación de la firma de los avisos | La conexión con pedidos y pagos (`payment.py`, `views.py`) |
| Salas | `layout.py`: generador de sectores y lectura de CSV/JSON | El guardado de salas y butacas |
| Plano de butacas | `seatmap-andina.js` y `seatmap.py` (pasaje al formato de seatmap-canvas) | Las pantallas y el carrito |
| Boletería | Lectura y validación del CSV de boletos; QR, planilla y LEEME del paquete para la imprenta (`imprenta.py`) | La carga y generación de entradas (hoy usa el importador de pedidos de pretix) y el PDF de la entrada (hoy lo dibuja pretix) |
| Cortesías | El texto del email y el manejo de nombres (`cortesias.py`) | La creación del pedido y el envío con la entrada adjunta (hoy, pretix) |
| Productores | El armado del PDF con reportlab | Los cálculos (hoy leen los pedidos de pretix) y los permisos |
