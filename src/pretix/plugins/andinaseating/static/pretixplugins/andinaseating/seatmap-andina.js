/*
 * AndinaTickets: dibuja planos con seatmap-canvas (window.SeatMapCanvas).
 *
 * <div class="andina-seatmap" id="X" data-source="ID_JSON" data-mode="..."></div>
 *
 * Modos:
 * - preview: solo mirar. Con data-generator-form y data-preview-url, el plano se
 *   actualiza en vivo mientras se completa el generador de sectores.
 * - select: clic en una butaca la marca o desmarca; las marcadas se escriben (seat_guid
 *   separados por coma) en el input oculto data-input. Los botones
 *   [data-andina-row="sector|fila"][data-andina-map="X"] marcan una fila completa.
 * - shop: plano para el comprador. Cada butaca libre corresponde a una casilla de la
 *   lista (input name=custom_data.field value=id). El plano y la lista se sincronizan:
 *   la casilla es la que se envía al carrito.
 */
(function () {
    'use strict';

    var COLORS = {
        free: '#ffffff',
        selected: '#e69f00',
        hover: '#f6c86b',
        notSalable: '#9e9e9e',
        shopSelected: '#5b2a73',
        shopHover: '#c9b3d6'
    };

    function allSeats(map) {
        var out = [];
        map.data.getBlocks().forEach(function (b) {
            b.seats.forEach(function (s) { out.push(s); });
        });
        return out;
    }

    function createMap(el, mode) {
        var interactive = mode === 'select' || mode === 'shop';
        var selected = mode === 'shop' ? COLORS.shopSelected : COLORS.selected;
        var hover = mode === 'shop' ? COLORS.shopHover : COLORS.hover;
        return new window.SeatMapCanvas('#' + el.id, {
            legend: false,
            style: {
                seat: {
                    radius: 11,
                    color: COLORS.free,
                    selected: selected,
                    hover: interactive ? hover : COLORS.free,
                    focus: interactive ? hover : COLORS.free,
                    not_salable: COLORS.notSalable,
                    check_icon_color: '#ffffff'
                },
                block: {title_color: '#333333'}
            }
        });
    }

    function setSelected(seat, on) {
        if (!seat.svg) {
            seat.selected = on;
        } else if (on) {
            seat.svg.select();
        } else {
            seat.svg.unSelect();
        }
    }

    /* ---------- select (boletería) ---------- */

    function initSelect(el, map) {
        var input = document.getElementById(el.getAttribute('data-input'));
        var counter = document.querySelector('[data-andina-count="' + input.id + '"]');

        function write() {
            input.value = allSeats(map)
                .filter(function (s) { return s.selected && s.salable; })
                .map(function (s) { return s.id; })
                .join(',');
            if (counter) {
                counter.textContent = input.value ? input.value.split(',').length : 0;
            }
        }
        write();

        map.eventManager.addEventListener('SEAT.CLICK', function (seat) {
            if (!seat.item.salable) {
                return;
            }
            setSelected(seat.item, !seat.isSelected());
            write();
        });

        document.querySelectorAll('[data-andina-map="' + el.id + '"][data-andina-row]').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                var key = btn.getAttribute('data-andina-row');
                var row = allSeats(map).filter(function (s) {
                    return s.salable && (s.custom_data.zone + '|' + s.custom_data.row) === key;
                });
                var allSelected = row.every(function (s) { return s.selected; });
                row.forEach(function (s) { setSelected(s, !allSelected); });
                write();
            });
        });
    }

    /* ---------- shop (comprador) ---------- */

    function initShop(el, map) {
        var form = el.closest('form') || document;

        function checkboxFor(seat) {
            var field = seat.custom_data && seat.custom_data.field;
            if (!field) {
                return null;
            }
            return form.querySelector('input[type="checkbox"][name="' + field + '"][value="' + seat.id + '"]');
        }

        // Estado inicial: lo que ya está marcado en la lista (por ejemplo al volver atrás).
        allSeats(map).forEach(function (s) {
            var cb = checkboxFor(s);
            if (cb && cb.checked) {
                setSelected(s, true);
            }
        });

        map.eventManager.addEventListener('SEAT.CLICK', function (seat) {
            if (!seat.item.salable) {
                return;
            }
            var cb = checkboxFor(seat.item);
            if (!cb) {
                return;
            }
            cb.checked = !cb.checked;
            setSelected(seat.item, cb.checked);
        });

        form.addEventListener('change', function (e) {
            var cb = e.target;
            if (!cb.matches || !cb.matches('input[type="checkbox"]')) {
                return;
            }
            allSeats(map).forEach(function (s) {
                if (s.id === cb.value && s.custom_data.field === cb.name) {
                    setSelected(s, cb.checked);
                }
            });
        });
    }

    /* ---------- generador de sectores (vista previa en vivo) ---------- */

    function initGenerator(el, state) {
        var form = document.getElementById(el.getAttribute('data-generator-form'));
        var url = el.getAttribute('data-preview-url');
        var status = document.getElementById('gen-status');
        if (!form || !url) {
            return;
        }
        var timer = null;
        var seq = 0;

        function refresh() {
            var params = new URLSearchParams(new FormData(form));
            params.delete('csrfmiddlewaretoken');
            params.delete('action');
            var mine = ++seq;
            fetch(url + '?' + params.toString(), {credentials: 'same-origin'})
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (mine !== seq) {
                        return;  // llegó una respuesta vieja
                    }
                    if (data.errors) {
                        if (status) {
                            status.textContent = 'Revisá los valores: ' + data.errors.join(' ');
                        }
                        return;
                    }
                    var empty = el.querySelector('.andinaseating-map-empty');
                    if (empty) {
                        empty.remove();
                    }
                    if (!state.map) {
                        state.map = createMap(el, 'preview');
                    }
                    state.map.data.replaceData(data.blocks);
                    if (status) {
                        status.textContent = 'Sector generado: ' + data.sector_seats + ' butacas (en naranja). ' +
                            'Total de la sala: ' + data.total_seats + '. Todavía no se guardó.';
                    }
                })
                .catch(function () {
                    if (status) {
                        status.textContent = 'No se pudo actualizar la vista previa.';
                    }
                });
        }

        form.addEventListener('input', function () {
            clearTimeout(timer);
            timer = setTimeout(refresh, 350);
        });
        form.addEventListener('change', function () {
            clearTimeout(timer);
            timer = setTimeout(refresh, 100);
        });
        if (form.getAttribute('data-open') === 'true') {
            refresh();
        }
    }

    /* ---------- arranque ---------- */

    function init(el) {
        if (typeof window.SeatMapCanvas === 'undefined') {
            return;
        }
        var source = document.getElementById(el.getAttribute('data-source'));
        var blocks = source ? JSON.parse(source.textContent) : [];
        var mode = el.getAttribute('data-mode') || 'preview';
        var state = {map: null};

        if (blocks.length) {
            var box = mode === 'shop' ? el.closest('.andinaseating') : null;
            if (box) {
                // El plano del comprador está oculto hasta acá; se muestra antes de crearlo
                // porque la librería toma el tamaño del contenedor al arrancar.
                box.classList.add('andinaseating-has-map');
            }
            state.map = createMap(el, mode);
            state.map.data.replaceData(blocks);
            if (mode === 'select') {
                initSelect(el, state.map);
            } else if (mode === 'shop') {
                initShop(el, state.map);
                // Con el plano funcionando, la lista queda plegada (sigue siendo la que se envía).
                var list = box.querySelector('details.andinaseating-list');
                if (list) {
                    list.open = false;
                }
            }
        }
        if (el.hasAttribute('data-generator-form')) {
            initGenerator(el, state);
        }
    }

    function start() {
        document.querySelectorAll('.andina-seatmap[data-source]').forEach(init);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
