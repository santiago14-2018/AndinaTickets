#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.urls import re_path

from .boleteria_views import BoleteriaView
from .event_views import EventSeatingView
from .views import SalaDetailView, SalaGeneratorPreviewView, SalaListView

urlpatterns = [
    re_path(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/butacas/$', EventSeatingView.as_view(),
            name='event'),
    re_path(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/boleteria/$', BoleteriaView.as_view(),
            name='boleteria'),
    re_path(r'^control/organizer/(?P<organizer>[^/]+)/salas/$', SalaListView.as_view(), name='salas'),
    re_path(r'^control/organizer/(?P<organizer>[^/]+)/salas/(?P<sala>\d+)/$', SalaDetailView.as_view(), name='sala'),
    re_path(r'^control/organizer/(?P<organizer>[^/]+)/salas/(?P<sala>\d+)/vista-previa/$',
            SalaGeneratorPreviewView.as_view(), name='sala.preview'),
]
