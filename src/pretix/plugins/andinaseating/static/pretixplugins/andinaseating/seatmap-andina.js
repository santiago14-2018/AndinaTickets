/*
 * AndinaTickets: dibuja planos con seatmap-canvas (window.SeatMapCanvas).
 *
 * <div class="andina-seatmap" id="X" data-source="ID_JSON" data-mode="preview|select"
 *      data-input="ID_INPUT_HIDDEN"></div>
 *
 * - preview: solo mirar.
 * - select: clic en una butaca la marca o desmarca; las marcadas se escriben (seat_guid
 *   separados por coma) en el input oculto. Los botones [data-andina-row="sector|fila"]
 *   con data-andina-map="X" marcan o desmarcan una fila completa.
 */
(function () {
    'use strict';

    var COLORS = {
        free: '#ffffff',
        selected: '#e69f00',
        hover: '#f6c86b',
        notSalable: '#9e9e9e'
    };

    function allSeats(map) {
        var out = [];
        map.data.getBlocks().forEach(function (b) {
            b.seats.forEach(function (s) { out.push(s); });
        });
        return out;
    }

    function writeInput(map, input) {
        input.value = allSeats(map)
            .filter(function (s) { return s.selected && s.salable; })
            .map(function (s) { return s.id; })
            .join(',');
        var counter = document.querySelector('[data-andina-count="' + input.id + '"]');
        if (counter) {
            counter.textContent = input.value ? input.value.split(',').length : 0;
        }
    }

    function init(el) {
        var source = document.getElementById(el.getAttribute('data-source'));
        if (!source || typeof window.SeatMapCanvas === 'undefined') {
            return;
        }
        var blocks = JSON.parse(source.textContent);
        var mode = el.getAttribute('data-mode') || 'preview';
        var map = new window.SeatMapCanvas('#' + el.id, {
            legend: false,
            style: {
                seat: {
                    radius: 11,
                    color: COLORS.free,
                    selected: COLORS.selected,
                    hover: mode === 'select' ? COLORS.hover : COLORS.free,
                    focus: mode === 'select' ? COLORS.hover : COLORS.free,
                    not_salable: COLORS.notSalable,
                    check_icon_color: '#ffffff'
                },
                block: {title_color: '#333333'}
            }
        });
        map.data.replaceData(blocks);

        if (mode !== 'select') {
            return;
        }
        var input = document.getElementById(el.getAttribute('data-input'));
        writeInput(map, input);

        map.eventManager.addEventListener('SEAT.CLICK', function (seat) {
            if (!seat.item.salable) {
                return;
            }
            if (seat.isSelected()) {
                seat.unSelect();
            } else {
                seat.select();
            }
            writeInput(map, input);
        });

        document.querySelectorAll('[data-andina-map="' + el.id + '"][data-andina-row]').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                var key = btn.getAttribute('data-andina-row');
                var row = allSeats(map).filter(function (s) {
                    return s.salable && (s.custom_data.zone + '|' + s.custom_data.row) === key;
                });
                var allSelected = row.every(function (s) { return s.selected; });
                row.forEach(function (s) {
                    if (s.svg) {
                        if (allSelected) {
                            s.svg.unSelect();
                        } else {
                            s.svg.select();
                        }
                    }
                });
                writeInput(map, input);
            });
        });
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
