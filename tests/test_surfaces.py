"""Surface inference is name-keyed and order-sensitive, which hides two faults.

SURFACE_RULES is scanned in order and the first substring hit wins, so a broad
early rule can shadow a narrower later one and the later rule becomes dead code
that never fires. That is exactly how ATP Stuttgart -- grass since 2015 -- was
being handed clay parameters by a rule meant for the WTA event in the same city.

The feed carries no surface at all (every row is null), so these rules are the
only surface signal the model has; a wrong one silently feeds the wrong serve
and rally bases into every simulated match at that event.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

import surfaces
from surfaces import SURFACE_RULES, surface_of

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'sportradar_cache' / '_year_tour.pkl'


def test_no_rule_is_shadowed():
    """Every rule must be reachable: no earlier needle contains a later one."""
    for i, (needle, _) in enumerate(SURFACE_RULES):
        for earlier, _ in SURFACE_RULES[:i]:
            assert earlier not in needle, (
                f'rule {needle!r} is unreachable -- the earlier rule '
                f'{earlier!r} matches every name it would match')


def test_conflicting_rules_are_tour_qualified():
    """Two rules disagreeing on a city must both name a tour, or one is wrong."""
    by_city = {}
    for needle, surface in SURFACE_RULES:
        city = needle.replace('atp ', '').replace('wta ', '')
        by_city.setdefault(city, set()).add(surface)
    for city, found in by_city.items():
        if len(found) > 1:
            qualified = [n for n, _ in SURFACE_RULES
                         if n.replace('atp ', '').replace('wta ', '') == city]
            assert all(n.startswith(('atp ', 'wta ')) for n in qualified), (
                f'{city!r} has rules for {sorted(found)} but they are not '
                f'tour-qualified, so one silently wins for both tours')


def test_stuttgart_splits_by_tour():
    """The regression that prompted this file."""
    assert surface_of('ATP Stuttgart, Germany Men Singles') == 'grass'
    assert surface_of('WTA Stuttgart, Germany Women Singles') == 'clay'


def test_every_surface_value_is_known():
    known = {surfaces.HARD, surfaces.CLAY, surfaces.GRASS, surfaces.INDOOR}
    for needle, surface in SURFACE_RULES:
        assert surface in known, f'{needle!r} maps to unknown surface {surface!r}'


@pytest.mark.skipif(not CACHE.exists(), reason='needs the cached season')
def test_slams_resolve_from_rules_not_the_default():
    """The four slams must never fall through to the hard default."""
    for name, want in [('French Open Men Singles', 'clay'),
                       ('Wimbledon Men Singles', 'grass'),
                       ('Australian Open Men Singles', 'hard'),
                       ('US Open Men Singles', 'hard')]:
        assert surface_of(name, default=None) == want, f'{name} fell through'


@pytest.mark.skipif(not CACHE.exists(), reason='needs the cached season')
def test_audited_non_hard_events_have_rules():
    """Events verified as clay/grass must resolve from a rule, not the default.

    A count of "how many events fall through" would fail on every data refresh,
    so this pins the specific events whose surface has actually been checked.
    Add a name here only after confirming the surface.
    """
    audited = {
        'ATP Geneva, Switzerland Men Singles': 'clay',
        'ATP Houston, USA Men Singles': 'clay',
        'ATP Stuttgart, Germany Men Singles': 'grass',
        'WTA Stuttgart, Germany Women Singles': 'clay',
        'ATP Marrakech, Morocco Men Singles': 'clay',
        'ATP Bucharest, Romania Men Singles': 'clay',
        'ATP Gstaad, Switzerland Men Singles': 'clay',
        'ATP Bastad, Sweden Men Singles': 'clay',
        'ATP Umag, Croatia Men Singles': 'clay',
        'ATP Kitzbuhel, Austria Men Singles': 'clay',
        'ATP Estoril, Portugal Men Singles': 'clay',
        'ATP Buenos Aires, Argentina Men Singles': 'clay',
        'ATP Santiago, Chile Men Singles': 'clay',
        'ATP Mallorca, Spain Men Singles': 'grass',
        'ATP Eastbourne, Great Britain Men Singles': 'grass',
        'ATP S-Hertogenbosch, Netherlands Men Singles': 'grass',
        'ATP Halle, Germany Men Singles': 'grass',
        'ATP London, Great Britain Men Singles': 'grass',
    }
    for name, want in audited.items():
        got = surface_of(name, default=None)
        assert got == want, (
            f'{name}: rules give {got!r}, audited as {want!r}'
            + ('  (falling through to the hard default)' if got is None else ''))


@pytest.mark.skipif(not CACHE.exists(), reason='needs the cached season')
def test_audited_events_are_actually_in_the_cache():
    """Guards the list above from rotting into names that no longer exist."""
    df = pickle.load(open(CACHE, 'rb'))
    played = set(df['competition'].unique())
    for name in ['ATP Geneva, Switzerland Men Singles',
                 'ATP Houston, USA Men Singles',
                 'ATP Stuttgart, Germany Men Singles']:
        assert name in played, f'{name} is no longer in the cached season'


# ---- surfaces as published by the tours -----------------------------------

def test_no_calendar_event_falls_back_to_the_default():
    """Every event's surface is stated by its tour, not assumed.

    The feed carries no surface at all -- every row is null -- so before the
    published calendars were transcribed, 24 ATP and 35 WTA events were simply
    taken to be outdoor hard. Two of them were not.
    """
    import csv
    for tour in ('atp', 'wta'):
        path = ROOT / f'{tour}_calendar.csv'
        if not path.exists():
            pytest.skip(f'{path.name} not built')
        rows = list(csv.DictReader(path.open()))
        assumed = [r['name'] for r in rows if r['surface_from'] == 'default(hard)']
        assert not assumed, (
            f'{tour.upper()}: surface assumed rather than known for {assumed}')
        assert all(r['surface_from'] in ('published calendar', 'name rule')
                   for r in rows)


def test_published_table_covers_every_event_and_nothing_else():
    """A stale entry is as bad as a missing one: it would quietly do nothing."""
    import csv
    from surfaces import PUBLISHED
    listed = set(PUBLISHED)
    on_calendar = set()
    for tour in ('atp', 'wta'):
        path = ROOT / f'{tour}_calendar.csv'
        if not path.exists():
            pytest.skip(f'{path.name} not built')
        for r in csv.DictReader(path.open()):
            on_calendar.add((tour.upper(), r['name']))
    assert not (on_calendar - listed), f'not in the table: {sorted(on_calendar - listed)}'
    assert not (listed - on_calendar), f'in the table but not on any calendar: {sorted(listed - on_calendar)}'


def test_the_two_stuttgarts_and_two_parises_differ():
    """Exactly the pairs a substring rule cannot separate."""
    from surfaces import PUBLISHED
    assert PUBLISHED[('ATP', 'Stuttgart')] == 'grass'
    assert PUBLISHED[('WTA', 'Stuttgart')] == 'clay'
    assert PUBLISHED[('ATP', 'Roland Garros')] == 'clay'
    assert PUBLISHED[('ATP', 'Paris')] == 'indoor_hard'
