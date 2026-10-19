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
