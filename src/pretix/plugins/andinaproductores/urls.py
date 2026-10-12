#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django.urls import re_path

from .views import (
    EventPdfView, EventReportView, LiquidacionPdfView, MisVentasView,
    ProductoresAdminView,
)

urlpatterns = [
    re_path(r'^control/organizer/(?P<organizer>[^/]+)/mis-ventas/$', MisVentasView.as_view(), name='mis_ventas'),
    re_path(r'^control/organizer/(?P<organizer>[^/]+)/mis-ventas/(?P<evento>[^/]+)/$', EventReportView.as_view(),
            name='evento'),
    re_path(r'^control/organizer/(?P<organizer>[^/]+)/mis-ventas/(?P<evento>[^/]+)/pdf/$', EventPdfView.as_view(),
            name='pdf'),
    re_path(r'^control/organizer/(?P<organizer>[^/]+)/mis-ventas/(?P<evento>[^/]+)/liquidacion/(?P<numero>\d+)\.pdf$',
            LiquidacionPdfView.as_view(), name='liquidacion_pdf'),
    re_path(r'^control/organizer/(?P<organizer>[^/]+)/productores/$', ProductoresAdminView.as_view(), name='admin'),
]
