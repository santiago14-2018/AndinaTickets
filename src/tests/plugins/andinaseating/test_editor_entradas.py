#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Los agregados del editor de PDF (andina_marca/editor_entradas.js: buscador de la lista "Contenido" y
botón "Volver al fondo original") se cargan solo en la página del editor; el fondo original, solo en el
de las entradas.
"""
from django.test import RequestFactory

from pretix.andina_marca.signals import editor_entradas


def test_se_carga_en_el_editor_de_entradas_con_el_fondo_original():
    html = editor_entradas(RequestFactory().get('/control/event/teatro/hamlet/pdfoutput/5/editor'))
    assert 'andina_marca/editor_entradas' in html
    assert 'data-fondo-original="/static/pretixpresale/pdf/ticket_default_a4.pdf"' in html


def test_en_otros_editores_va_sin_fondo_original():
    html = editor_entradas(RequestFactory().get('/control/event/teatro/hamlet/badges/3/editor'))
    assert 'andina_marca/editor_entradas' in html and 'data-fondo-original=""' in html


def test_no_se_carga_en_otras_paginas():
    for ruta in ('/control/', '/control/event/teatro/hamlet/pdfoutput/', '/control/event/teatro/hamlet/settings/'):
        assert editor_entradas(RequestFactory().get(ruta)) == ''
