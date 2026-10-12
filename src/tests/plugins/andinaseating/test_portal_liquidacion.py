#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Portal del productor: el recuadro "Liquidación" muestra lo que responde el programa privado de
liquidaciones (con la clave compartida) y el comprobante en PDF se baja a través de AndinaTickets.
"""
import json
from urllib.error import HTTPError, URLError

import pytest
from django_scopes import scopes_disabled

from pretix.plugins.andinaproductores import liquidaciones

URL_LIQ = 'http://liquidaciones.test'
RESPUESTA = {
    'estado': 'cerrada',
    'liquidacion': {'codigo': 'L-0001', 'numero': 1, 'fecha': '2026-10-27T10:00:00-03:00',
                    'ventas_online': '48000.00', 'comision': '0.00', 'cargo_boleteria': '3000.00',
                    'persona_boleteria': '20000.00', 'a_transferir': '25000.00', 'transferido': '10000.00',
                    'saldo': '15000.00'},
    'transferencias': [{'fecha': '2026-10-28', 'monto': '10000.00', 'medio': 'Transferencia bancaria',
                        'referencia': 'OP-1'}],
}


class Respuesta:
    def __init__(self, tipo, contenido):
        self.headers = {'Content-Type': tipo}
        self.contenido = contenido

    def read(self):
        return self.contenido

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def servicio(monkeypatch, settings):
    """Simula el programa de liquidaciones: {url: Respuesta o excepción}. Guarda los pedidos recibidos."""
    settings.ANDINA_LIQUIDACIONES_URL = URL_LIQ
    settings.ANDINA_LIQUIDACIONES_CLAVE = 'secreta'
    rutas, recibidos = {}, []

    def falso_urlopen(pedido, timeout=None):
        recibidos.append(pedido)
        r = rutas.get(pedido.full_url, HTTPError(pedido.full_url, 404, 'no', {}, None))
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(liquidaciones, 'urlopen', falso_urlopen)
    return rutas, recibidos


@pytest.fixture
def admin_client(env, client):
    _event, _item, user = env
    with scopes_disabled():
        team = user.teams.first()
        team.all_organizer_permissions = True
        team.save()
    client.login(email='boleteria@example.com', password='boleteria')
    return client


@pytest.mark.django_db
def test_sin_configurar_no_aparece(admin_client, settings):
    settings.ANDINA_LIQUIDACIONES_URL = ''
    r = admin_client.get('/control/organizer/teatro/mis-ventas/hamlet/')
    assert r.status_code == 200 and 'Comprobante de la liquidación' not in r.content.decode()


@pytest.mark.django_db
def test_muestra_la_liquidacion_y_baja_el_pdf(admin_client, servicio):
    rutas, recibidos = servicio
    rutas[URL_LIQ + '/api/portal/teatro/hamlet/'] = Respuesta('application/json', json.dumps(RESPUESTA).encode())
    rutas[URL_LIQ + '/api/portal/teatro/hamlet/1.pdf'] = Respuesta('application/pdf', b'%PDF-1.4 prueba')
    html = admin_client.get('/control/organizer/teatro/mis-ventas/hamlet/').content.decode()
    assert 'Liquidación L-0001' in html and 'Falta transferir' in html and '28/10/2026' in html
    assert recibidos[0].get_header('Authorization') == 'Bearer secreta'
    r = admin_client.get('/control/organizer/teatro/mis-ventas/hamlet/liquidacion/1.pdf')
    assert r.status_code == 200 and r.content == b'%PDF-1.4 prueba'
    assert 'liquidacion-L-0001-hamlet.pdf' in r['Content-Disposition']


@pytest.mark.django_db
def test_si_no_responde_el_portal_sigue_andando(admin_client, servicio):
    rutas, _ = servicio
    rutas[URL_LIQ + '/api/portal/teatro/hamlet/'] = URLError('conexión rechazada')
    r = admin_client.get('/control/organizer/teatro/mis-ventas/hamlet/')
    assert r.status_code == 200 and 'No pudimos consultar la liquidación' in r.content.decode()
    assert admin_client.get('/control/organizer/teatro/mis-ventas/hamlet/liquidacion/9.pdf').status_code == 404
