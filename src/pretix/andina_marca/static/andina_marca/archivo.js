/*
 * AndinaTickets: campos para subir un archivo en el panel (plantilla
 * pretixbase/forms/widgets/thumbnailed_file_input.html de andina_marca).
 *
 * - Al elegir una imagen se ve la vista previa en el momento, antes de guardar.
 * - "Sin imagen" marca la imagen actual para quitarla al guardar (la atenúa y lo avisa).
 * Elegir un archivo nuevo desmarca "Sin imagen" y al revés: Django no acepta las dos cosas juntas.
 *
 * La plantilla carga este archivo una vez por campo: se registra una sola vez.
 */
(function () {
    'use strict';
    if (window.andinaArchivo) {
        return;
    }
    window.andinaArchivo = true;

    var MAX_ALTO = 120;   // px: la vista previa, parecida a la miniatura de la imagen guardada
    var MAX_ANCHO = 320;

    function caja(el) {
        return el.closest('[data-andina-archivo]');
    }

    function mostrarVista(box, archivo) {
        var vista = box.querySelector('.andina-archivo-vista');
        var img = vista.querySelector('img');
        if (!archivo || !/^image\//.test(archivo.type)) {
            vista.classList.add('hidden');
            img.removeAttribute('src');
            return;
        }
        // Como "data:" y no con URL.createObjectURL: la política de seguridad del panel solo deja
        // mostrar imágenes del sitio y "data:" (no "blob:").
        var lector = new FileReader();
        img.onload = function () {
            // Con ancho y no con alto: los estilos del panel ponen "height: auto" a las imágenes.
            img.width = Math.min(MAX_ANCHO, Math.round(MAX_ALTO * img.naturalWidth / (img.naturalHeight || 1)));
            vista.classList.remove('hidden');
        };
        lector.onload = function () {
            img.src = lector.result;
        };
        lector.readAsDataURL(archivo);
    }

    function marcarQuitar(box, quitar) {
        var actual = box.querySelector('.andina-archivo-actual');
        var aviso = box.querySelector('.andina-archivo-aviso');
        var boton = box.querySelector('.andina-archivo-quitar');
        if (actual) {
            actual.classList.toggle('text-muted', quitar);
            actual.querySelectorAll('img').forEach(function (img) {
                img.classList.toggle('hidden', quitar);
            });
        }
        if (aviso) {
            aviso.classList.toggle('hidden', !quitar);
        }
        if (boton) {
            boton.classList.toggle('active', quitar);
            boton.classList.toggle('btn-danger', quitar);
            boton.classList.toggle('btn-default', !quitar);
        }
    }

    document.addEventListener('change', function (e) {
        var el = e.target;
        var box = el && el.closest ? caja(el) : null;
        if (!box) {
            return;
        }
        if (el.type === 'file') {
            mostrarVista(box, el.files && el.files[0]);
            var check = box.querySelector('.andina-archivo-quitar input[type=checkbox]');
            if (check && el.files && el.files.length && check.checked) {
                check.checked = false;
                marcarQuitar(box, false);
            }
        } else if (el.type === 'checkbox' && el.closest('.andina-archivo-quitar')) {
            marcarQuitar(box, el.checked);
            if (el.checked) {
                var input = box.querySelector('input[type=file]');
                if (input) {
                    input.value = '';
                    mostrarVista(box, null);
                }
            }
        }
    });
})();
