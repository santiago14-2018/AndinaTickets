/*
 * AndinaTickets: agregados del editor de entradas en PDF.
 *
 * 1) La lista "Contenido" de un campo de texto (Nombre del evento, Fecha, Butaca, Precio…) queda en
 *    orden alfabético y con buscador: se escribe una parte del nombre ("butaca", "fecha") y quedan
 *    solo las opciones que la contienen, sin importar mayúsculas ni tildes. Usa select2, que el panel
 *    de pretix ya carga. "Otros…" y "Otros… (multilingüe)" (texto libre) quedan al final.
 *    El editor cambia la opción elegida por código, sin avisar (al tocar otro texto de la hoja): por
 *    eso se envuelve editor._update_toolbox, para que el buscador muestre siempre la opción correcta.
 *    El editor engancha esa función al lienzo recién cuando termina de cargar el PDF, después de esto.
 *
 * 2) "Volver al fondo original": después de subir otro PDF o de crear un fondo vacío, vuelve al fondo
 *    de pretix (el de los recuadros y la tijera). Lo sube como si se eligiera ese PDF con "Subir PDF
 *    como fondo", así que también queda pendiente hasta tocar Guardar. Solo en el editor de entradas
 *    (la señal pasa la dirección del fondo en data-fondo-original).
 *
 * 3) Los textos nuevos ("Campo de texto") copian el estilo del texto elegido y aparecen debajo de él;
 *    sin texto elegido, salen con la letra de AndinaTickets (Bricolage Grotesque), la del diseño de
 *    fábrica, y no con "Open Sans", que pretix trae fija. Los botones de duplicar y eliminar llevan su
 *    nombre ("Duplicar", "Eliminar") además del ícono.
 *
 * Se carga solo en la página del editor (andina_marca/signals.py, html_page_start).
 */
(function () {
    'use strict';
    var FONDO_ORIGINAL = (document.currentScript && document.currentScript.getAttribute('data-fondo-original')) || '';
    var ALFINAL = ['other_i18n', 'other'];
    var IDIOMA = {
        noResults: function () { return 'No hay coincidencias'; },
        searching: function () { return 'Buscando…'; },
    };

    function ordenar(select) {
        var valor = select.value;
        var opciones = Array.prototype.slice.call(select.options);
        var orden = new Intl.Collator('es', {sensitivity: 'base', numeric: true});
        var normales = opciones.filter(function (o) { return ALFINAL.indexOf(o.value) < 0; });
        var finales = opciones.filter(function (o) { return ALFINAL.indexOf(o.value) >= 0; });
        normales.sort(function (a, b) { return orden.compare(a.text.trim(), b.text.trim()); });
        normales.concat(finales).forEach(function (o) { select.appendChild(o); });
        select.value = valor;
    }

    // --- 3) Textos nuevos: estilo y lugar ---
    // pretix crea cada "Campo de texto" nuevo arriba a la izquierda, en "Open Sans" de 13 pt. Acá:
    // - si hay un texto elegido, el nuevo copia su estilo (letra, tamaño, color, negrita, cursiva,
    //   alineación, interlineado y ancho), aparece justo debajo y queda elegido;
    // - si no, sale con la letra de AndinaTickets (la del diseño de fábrica, andina_marca/signals.py).
    // Después se corrigen los pasos del historial, para que "Deshacer" no muestre la versión de pretix.
    // El editor engancha los botones a sus funciones al arrancar, que puede ser antes o después de este
    // script: por eso se envuelve la función y también se escucha el clic. Es idempotente.
    var LETRA = 'Bricolage Grotesque';
    var LETRA_PRETIX = 'Open Sans';
    var TIPOS_TEXTO = ['textcontainer', 'textarea'];
    var ESTILO = ['fontFamily', 'fontSize', 'fill', 'fontWeight', 'fontStyle', 'textAlign', 'lineHeight',
                  'verticalAlign'];
    var SEPARACION = 6;  // px entre el texto elegido y el nuevo
    var referencia = null;  // estilo y lugar del texto elegido al tocar "Campo de texto"

    function anotarReferencia() {
        var activo = window.editor.fabric && window.editor.fabric.getActiveObject();
        referencia = null;
        if (activo && TIPOS_TEXTO.indexOf(activo.type) >= 0) {
            referencia = {estilo: {}, left: activo.left, top: activo.top, alto: activo.getScaledHeight(),
                          ancho: activo.getScaledWidth(), tipo: activo.type};
            ESTILO.forEach(function (p) {
                if (activo[p] !== undefined) {
                    referencia.estilo[p] = activo[p];
                }
            });
        }
    }

    function hayLetraDeLaMarca() {
        return Array.prototype.some.call(document.querySelectorAll('#toolbox-fontfamily option'),
                                         function (o) { return (o.value || o.text) === LETRA; });
    }

    function prepararTexto(objeto) {
        if (!objeto || objeto._andinaListo || TIPOS_TEXTO.indexOf(objeto.type) < 0
            || objeto.fontFamily !== LETRA_PRETIX) {
            return;
        }
        objeto._andinaListo = true;
        var lienzo = window.editor.fabric;
        if (referencia) {
            objeto.set(referencia.estilo);
            if (objeto.type === 'textcontainer' && referencia.tipo === 'textcontainer') {
                objeto.set({width: referencia.ancho / (objeto.scaleX || 1)});
            }
            var alto = objeto.getScaledHeight();
            var top = referencia.top + referencia.alto + SEPARACION;
            if (top + alto > lienzo.getHeight()) {  // no entra abajo: va arriba
                top = Math.max(0, referencia.top - alto - SEPARACION);
            }
            objeto.set({left: referencia.left, top: top});
            objeto.setCoords();
        } else if (hayLetraDeLaMarca()) {
            objeto.set('fontFamily', LETRA);
        }
        lienzo.setActiveObject(objeto);
        lienzo.requestRenderAll();
        // Al agregar un texto, pretix guarda dos pasos de historial (uno al sumarlo al lienzo y otro al
        // terminar): se corrigen los del final que ya tienen el texto nuevo (misma cantidad de objetos).
        var historia = window.editor.history;
        if (historia && historia.length && !window.editor._history_pos) {
            var ahora = window.editor.dump();
            for (var i = historia.length - 1; i >= 0 && historia[i].length === ahora.length; i--) {
                historia[i] = ahora;
            }
        }
        window.editor._update_toolbox();
    }

    function textosConEstilo(nombre, boton) {
        var el = document.getElementById(boton);
        if (el) {
            // En la fase de captura: antes de que el editor cree el texto (y antes de que cambie la selección).
            el.addEventListener('click', anotarReferencia, true);
            el.addEventListener('click', function () {
                // Después del manejador del editor: el texto nuevo es el último del lienzo.
                window.setTimeout(function () {
                    var objetos = window.editor.fabric ? window.editor.fabric.getObjects() : [];
                    prepararTexto(objetos[objetos.length - 1]);
                }, 0);
            });
        }
        var original = window.editor[nombre];
        if (typeof original === 'function') {
            window.editor[nombre] = function () {
                var objeto = original.apply(this, arguments);
                prepararTexto(objeto);
                return objeto;
            };
        }
    }

    // Los botones de duplicar y eliminar del editor son solo un ícono: se les agrega el nombre.
    function nombresEnLosBotones() {
        [['toolbox-duplicate', 'Duplicar'], ['toolbox-delete', 'Eliminar']].forEach(function (par) {
            var b = document.getElementById(par[0]);
            if (b && !b.querySelector('.andina-etiqueta')) {
                var s = document.createElement('span');
                s.className = 'andina-etiqueta';
                s.textContent = ' ' + par[1];
                b.appendChild(s);
            }
        });
    }

    // --- 2) Volver al fondo original ---

    function volverAlFondoOriginal() {
        if (!window.confirm('¿Volver al fondo original? Reemplaza el fondo actual; los textos y códigos QR '
                            + 'quedan como están. Se guarda al tocar Guardar.')) {
            return;
        }
        var $ = jQuery;
        $('#loading-container, #loading-upload').show();
        $('#loading-upload .progress').hide();
        $('#fileupload').prop('disabled', true);
        $('.background-button').addClass('disabled');
        var listo = function () {
            $('#fileupload').prop('disabled', false);
            $('.background-button').removeClass('disabled');
        };
        var fallo = function () {
            window.alert('No se pudo volver al fondo original. Probá de nuevo.');
            $('#loading-container, #loading-upload').hide();
            listo();
        };
        fetch(FONDO_ORIGINAL, {credentials: 'same-origin'}).then(function (r) {
            if (!r.ok) {
                throw new Error(r.status);
            }
            return r.blob();
        }).then(function (pdf) {
            // Lo mismo que manda "Subir PDF como fondo": el archivo en el campo "background".
            var datos = new FormData();
            datos.append('csrfmiddlewaretoken', $('input[name=csrfmiddlewaretoken]').val());
            datos.append('background', new File([pdf], 'fondo-original.pdf', {type: 'application/pdf'}));
            return fetch(window.location.href, {method: 'POST', body: datos, credentials: 'same-origin'});
        }).then(function (r) {
            return r.json();
        }).then(function (data) {
            if (data.status !== 'ok') {
                throw new Error(data.error || 'error');
            }
            window.editor.uploaded_file_id = data.id;
            window.editor._replace_pdf_file(data.url);
            window.editor.dirty = true;
            window.editor._update_save_button();
            listo();
        }).catch(fallo);
    }

    function agregarBotonFondo() {
        var vacio = document.getElementById('pdf-empty');
        if (!FONDO_ORIGINAL || !vacio || !window.editor) {
            return;
        }
        var parrafo = document.createElement('p');
        parrafo.className = 'text-center';
        var boton = document.createElement('button');
        boton.type = 'button';
        boton.id = 'andina-fondo-original';
        boton.className = 'btn btn-default btn-block background-button';
        boton.innerHTML = '<i class="fa fa-undo"></i> Volver al fondo original';
        boton.addEventListener('click', volverAlFondoOriginal);
        var ayuda = document.createElement('small');
        ayuda.className = 'text-muted';
        ayuda.textContent = 'El fondo de fábrica, con los recuadros y la tijera.';
        parrafo.appendChild(boton);
        parrafo.appendChild(ayuda);
        var lugar = vacio.closest('p') || vacio;
        lugar.parentNode.insertBefore(parrafo, lugar.nextSibling);
    }

    function iniciar() {
        if (window.jQuery) {
            agregarBotonFondo();
        }
        if (window.editor) {
            textosConEstilo('_add_textcontainer', 'editor-add-textcontainer');
            textosConEstilo('_add_text', 'editor-add-text');
        }
        nombresEnLosBotones();
        var select = document.getElementById('toolbox-content');
        if (!select || !window.jQuery || !jQuery.fn.select2) {
            return;
        }
        ordenar(select);
        var $select = jQuery(select);
        $select.select2({
            width: '100%',
            language: IDIOMA,
            placeholder: 'Escribí para buscar…',
        });
        // Al abrir, el cursor va directo al buscador.
        $select.on('select2:open', function () {
            var campo = document.querySelector('.select2-container--open .select2-search__field');
            if (campo) {
                campo.focus();
            }
        });
        if (window.editor && typeof window.editor._update_toolbox === 'function') {
            var original = window.editor._update_toolbox;
            window.editor._update_toolbox = function () {
                var r = original.apply(this, arguments);
                $select.trigger('change.select2');  // solo redibuja el buscador; no dispara el editor
                return r;
            };
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciar);
    } else {
        iniciar();
    }
})();
