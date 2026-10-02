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

## 2026-10-02

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
| Boletería | Lectura y validación del CSV de boletos | La carga de entradas (hoy usa el importador de pedidos de pretix) |
| Productores | El armado del PDF con reportlab | Los cálculos (hoy leen los pedidos de pretix) y los permisos |
