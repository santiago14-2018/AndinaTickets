#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.urls import include, re_path

from pretix.multidomain import event_url

from .views import ReturnView, webhook

event_patterns = [
    re_path(r'^mercadopago/', include([
        event_url(r'^webhook/$', webhook, name='webhook', require_live=False),
        event_url(r'^return/(?P<order>[^/]+)/(?P<hash>[^/]+)/(?P<payment>[0-9]+)/$', ReturnView.as_view(),
                  name='return', require_live=False),
    ])),
]
