#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils.timezone import now
from django_scopes import scopes_disabled

from pretix.base.models import Event, Organizer, SeatingPlan, Team, User
from pretix.base.services.seating import generate_seats
from pretix.plugins.andinaseating.layout import (
    add_sector, empty_layout, generate_sector,
)

PRICE = Decimal('30000.00')


@pytest.fixture
def env(db):
    """
    Teatro con dos sectores: Platea (filas A y B, 5 butacas cada una, $30.000) y
    Pullman (fila J, 5 butacas, $18.000). Devuelve (evento, producto Platea, usuario
    con acceso al evento).
    """
    with scopes_disabled():
        # andinaseating es HYBRID: tiene que estar activo en el organizador y en el evento.
        o = Organizer.objects.create(name='Teatro', slug='teatro',
                                     plugins='pretix.plugins.andinaseating,pretix.plugins.andinaproductores')
        event = Event.objects.create(
            organizer=o, name='Hamlet', slug='hamlet', currency='ARS', date_from=now() + timedelta(days=10),
            plugins='pretix.plugins.andinaseating,pretix.plugins.andinaproductores', live=True,
        )
        platea = event.items.create(name='Platea', default_price=PRICE, admission=True)
        pullman = event.items.create(name='Pullman', default_price=Decimal('18000.00'), admission=True)
        quota = event.quotas.create(name='Sala', size=15)
        quota.items.add(platea, pullman)

        layout = add_sector(empty_layout('Teatro'), *generate_sector('Platea', rows=2, seats_per_row=5))
        layout = add_sector(layout, *generate_sector('Pullman', rows=1, seats_per_row=5, first_row='J'))
        plan = SeatingPlan.objects.create(organizer=o, name='Teatro', layout=json.dumps(layout))
        event.seating_plan = plan
        event.save()
        mapping = {'Platea': platea, 'Pullman': pullman}
        for category, item in mapping.items():
            event.seat_category_mappings.create(layout_category=category, product=item)
        generate_seats(event, None, plan, mapping)

        user = User.objects.create_user('boleteria@example.com', 'boleteria')
        team = Team.objects.create(organizer=o, all_event_permissions=True)
        team.members.add(user)
        team.limit_events.add(event)
        yield event, platea, user


@pytest.fixture
def env_general(env):
    """
    Evento sin numerar del mismo organizador: "General" ($12.000) con un cupo de 3.
    Devuelve (evento, producto General, usuario con acceso).
    """
    event, _platea, user = env
    with scopes_disabled():
        general = Event.objects.create(
            organizer=event.organizer, name='Stand-up', slug='standup', currency='ARS',
            date_from=now() + timedelta(days=12), plugins=event.plugins, live=True,
        )
        item = general.items.create(name='General', default_price=Decimal('12000.00'), admission=True)
        general.quotas.create(name='Salón', size=3).items.add(item)
        user.teams.first().limit_events.add(general)
        yield general, item, user
