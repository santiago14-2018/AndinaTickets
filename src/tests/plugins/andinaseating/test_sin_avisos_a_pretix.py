#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
AndinaTickets no le manda nada a pretix.eu: la comprobación de actualizaciones está anulada
(base/services/update_check.py), viene apagada y no se puede activar desde el panel. Los valores de
fábrica del plazo de pago son 40 minutos.
"""
import pytest
import responses

from pretix.base.services import update_check
from pretix.base.settings import GlobalSettingsObject
from pretix.control.forms.global_settings import UpdateSettingsForm


@pytest.mark.django_db
@responses.activate
def test_la_comprobacion_no_manda_nada_aunque_se_active():
    gs = GlobalSettingsObject()
    gs.settings.set('update_check_perform', True)
    # responses frena cualquier pedido a una dirección no registrada: si saliera algo, fallaría.
    update_check.run_update_check(None)
    update_check.update_check.apply(throw=True)
    assert len(responses.calls) == 0
    assert not gs.settings.update_check_id
    assert gs.settings.update_check_result is None


@pytest.mark.django_db
def test_viene_apagada_y_sin_cartel():
    gs = GlobalSettingsObject()
    assert gs.settings.update_check_perform is False
    assert gs.settings.update_check_ack is True
    assert UpdateSettingsForm().fields['update_check_perform'].disabled


@pytest.mark.django_db
def test_plazo_de_pago_de_fabrica_40_minutos(env):
    event = env[0]
    assert event.settings.payment_term_mode == 'minutes'
    assert event.settings.payment_term_minutes == 40
