#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from collections import OrderedDict

from django import forms
from django.dispatch import receiver

from pretix.base.forms import SecretKeySettingsField
from pretix.base.signals import (
    register_global_settings, register_payment_providers,
)

from . import logentries  # NOQA: registra los textos del historial


@receiver(register_payment_providers, dispatch_uid="payment_andinamercadopago")
def register_payment_provider(sender, **kwargs):
    from .payment import MercadoPago
    return MercadoPago


@receiver(register_global_settings, dispatch_uid='andinamercadopago_global_settings')
def register_global_settings(sender, **kwargs):
    """
    Credenciales de la cuenta de Mercado Pago que recibe todo el dinero. Se cargan una
    sola vez para toda la plataforma (Administración → Configuración global).
    """
    return OrderedDict([
        ('payment_andinamp_access_token', SecretKeySettingsField(
            label='Mercado Pago: Access token (producción)',
            help_text='Credenciales de producción de tu aplicación en el panel de desarrolladores de Mercado Pago. '
                      'Empieza con APP_USR-.',
            required=False,
        )),
        ('payment_andinamp_test_access_token', SecretKeySettingsField(
            label='Mercado Pago: Access token de prueba',
            help_text='Se usa para los eventos en modo de prueba (con el usuario vendedor de prueba de Mercado Pago).',
            required=False,
        )),
        ('payment_andinamp_webhook_secret', SecretKeySettingsField(
            label='Mercado Pago: Clave secreta de notificaciones',
            help_text='Opcional. Panel de desarrolladores → Webhooks → clave secreta. Si está cargada, se verifica '
                      'la firma de cada aviso.',
            required=False,
        )),
        ('payment_andinamp_statement_descriptor', forms.CharField(
            label='Mercado Pago: Texto en el resumen de la tarjeta',
            help_text='Opcional. Por ejemplo ANDINATICKETS.',
            max_length=22,
            required=False,
        )),
    ])
