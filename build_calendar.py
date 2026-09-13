"""Derive each tour's season calendar from the cached match feed.

The feed has no calendar endpoint cached, so the calendar is reconstructed from
the matches that were actually played: every competition at 250 level or above
that appears in the cached window, with its main-draw span, its verified draw
shape, and an inferred surface (the feed carries no surface at all -- every row
is null -- so surfaces.py's name rules are the only signal).

The window is a rolling twelve months, not a January-December year. It holds one
complete cycle: no competition appears in two calendar years within it, so each
recurring event is captured exactly once, dated from whichever side of the seam
it fell on.

    python build_calendar.py                 # writes atp_calendar.csv, wta_calendar.csv
"""

from __future__ import annotations

import argparse
import csv
import pickle
from pathlib import Path

from surfaces import surface_of, published_surface

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'sportradar_cache' / '_year_tour.pkl'
SHAPES = ROOT / 'tournament_shapes.csv'

LEVELS = {
    'ATP': {'grand_slam': 'Grand Slam', 'atp_1000': 'ATP 1000', 'atp_500': 'ATP 500',
            'atp_250': 'ATP 250', 'atp_world_tour_finals': 'ATP Finals',
            'atp_next_generation': 'Next Gen Finals'},
    'WTA': {'grand_slam': 'Grand Slam', 'wta_1000': 'WTA 1000', 'wta_500': 'WTA 500',
            'wta_250': 'WTA 250', 'wta_championships': 'WTA Finals'},
}
GENDER = {'ATP': 'men', 'WTA': 'women'}
# round-robin finals have no bracket, so the draw arithmetic does not apply
ROUND_ROBIN = {'ATP Finals', 'Next Gen Finals', 'WTA Finals'}

# Most feed names already read "City, Country"; the events that do not are the
# ones whose name is the event rather than the place.
# The feed calls the clay major the French Open; it is shown by the name the
# tournament itself uses. Same for the grass 500 the feed files under its city:
# both tours play it at Queen's Club, and "London" is ambiguous in a calendar
# that also holds Wimbledon.
RENAME = {'French Open': 'Roland Garros',
          'London, Great Britain': "Queen's Club"}

VENUE = {
    'Australian Open': 'Melbourne, Australia',
    'Roland Garros': 'Paris, France',
    'Wimbledon': 'London, Great Britain',
    "Queen's Club": 'London, Great Britain',
    'US Open': 'New York, USA',
    'World Tour Finals': 'Turin, Italy',
    'Next Gen ATP Finals': 'Jeddah, Saudi Arabia',
    'Finals': 'Riyadh, Saudi Arabia',
}


# Host country as the three-letter code the ranking feed uses for players, so a
# home player can be recognised by a straight comparison. Most of these come
# from the feed itself; the handful that do not are countries no ranked player
# comes from -- Qatar, Saudi Arabia, the UAE -- where nobody is ever at home.
HOST_CODE = {
    'Argentina':'ARG', 'Australia':'AUS', 'Austria':'AUT', 'Belgium':'BEL',
    'Brazil':'BRA', 'Canada':'CAN', 'Chile':'CHL', 'China':'CHN',
    'Colombia':'COL', 'Croatia':'HRV', 'Czech Republic':'CZE', 'France':'FRA',
    'Germany':'DEU', 'Great Britain':'GBR', 'Greece':'GRC', 'Hong Kong':'HKG',
    'Italy':'ITA', 'Japan':'JPN', 'Kazakhstan':'KAZ', 'Korea Republic':'KOR',
    'India':'IND', 'Mexico':'MEX', 'Monaco':'MCO', 'Morocco':'MAR', 'Netherlands':'NLD',
    'New Zealand':'NZL', 'Portugal':'PRT', 'Qatar':'QAT', 'Romania':'ROU',
    'Saudi Arabia':'SAU', 'Spain':'ESP', 'Sweden':'SWE', 'Switzerland':'CHE',
    'UAE':'ARE', 'USA':'USA',
}


def host_country(location):
    """Three-letter code for where an event is played, or '' if unrecognised."""
    if not location:
        return ''
    tail = location.strip().rstrip(',').split(',')[-1].strip()
    return HOST_CODE.get(tail, '')


def _place(name):
    """Split a calendar name into a short label and a location."""
    name = RENAME.get(name, name)
    if name in VENUE:
        return name, VENUE[name]
    if ',' in name:
        return name.split(',')[0].strip(), name
    return name, name


MIN_SIMULATABLE_DRAW = 16      # below this a derived draw is nonsense, not a small event

# Draw sizes taken from the published tour calendars, for events the cached
# feed cannot settle on its own. Keyed by (tour, calendar name).
#   ATP  2026-atp-tour-calendar-december-2025.pdf
#   WTA  wtafiles.wtatennis.com/pdf/calendar/calendar.pdf
# Washington is not actually missing anything -- its 31 cached main-draw matches
# are exactly a complete 32 draw. The derivation counted a cancelled match and
# produced 33, which no bracket can hold.
DRAW_OVERRIDES = {
    ('ATP', 'Washington'): 32,
    ('ATP', 'Winston Salem'): 48,
    ('WTA', 'Monterrey'): 28,
}

# Events in the cached window that are no longer on the tour calendar. The
# window is a rolling twelve months, so it can hold BOTH a discontinued event
# and its replacement -- Cleveland ran in August 2025 and was cancelled, and the
# Memphis Classic took its place for 2026. Memphis is already in the window with
# a complete 32 draw, so keeping Cleveland would play that slot twice.
DISCONTINUED = {('WTA', 'Cleveland')}


def _shapes(gender):
    if not SHAPES.exists():
        return {}
    return {r['tournament']: r for r in csv.DictReader(SHAPES.open())
            if r['gender'] == gender}


# A tournament already under way when the cached window opens keeps only the
# rounds played after that date. It looks exactly like a feed gap -- and worse,
# the draw arithmetic can still "succeed" on the surviving rounds, because late
# rounds are self-consistent -- so the window edge is checked first and named
# for what it is.
WINDOW_EDGE_DAYS = 2


def _clipped_by_window(first_day, window_start):
    if first_day is None or window_start is None:
        return False
    from datetime import date
    def d(v):
        v = str(int(v))
        return date(int(v[:4]), int(v[4:6]), int(v[6:]))
    return (d(first_day) - d(window_start)).days <= WINDOW_EDGE_DAYS


def _classify(row):
    """Whether a shape can be simulated, and if not, what is actually wrong.

    "plausible" in tournament_shapes.csv also demands that the SEED count
    reconcile, which is stricter than the simulator needs -- it derives seeds
    from the draw size. Queen's was being skipped for a seeding anomaly (seed 17
    issued into a 28 draw after eleven withdrawals) despite a complete and
    perfectly consistent draw.
    """
    if row is None:
        return 'no draw in the source data'
    draw = row['draw']
    if not draw.isdigit():
        return 'only the closing rounds are in the source data'
    draw, bracket = int(draw), int(row['bracket'] or 0)
    if row['draw_complete'] != 'True':
        return 'only the closing rounds are in the source data'
    if bracket < draw:
        return 'the draw in the source data does not add up'
    if draw < MIN_SIMULATABLE_DRAW:
        return 'the draw in the source data does not add up'
    return None


def _override(tour, name, row):
    """Apply a published draw size to a shape the feed could not settle."""
    draw = DRAW_OVERRIDES.get((tour, name))
    if draw is None:
        return row
    bracket = 1
    while bracket < draw:
        bracket *= 2
    row = dict(row or {})
    row.update(draw=str(draw), bracket=str(bracket), byes=str(bracket - draw),
               draw_complete='True', source='published calendar')
    return row


def build(tour, df=None):
    if df is None:
        df = pickle.load(CACHE.open('rb'))
    df = df[df['set'] == 'Total'].drop_duplicates('match_id')
    levels = LEVELS[tour]
    sel = df[(df['gender'] == GENDER[tour]) & df['level'].isin(levels)]
    shapes = _shapes(GENDER[tour])
    window_start = df['match_date'].min()

    rows = []
    for comp, g in sel.groupby('competition'):
        # qualifying rounds are not part of the tournament's own span
        main = g[~g['round'].astype(str).str.startswith('qualification')]
        if main.empty:
            continue
        d0, d1 = str(main['match_date'].min()), str(main['match_date'].max())
        level = levels[g['level'].iloc[0]]
        name = (comp.replace(' Men Singles', '').replace(' Women Singles', '')
                    .replace(' Women, Singles', '').removeprefix('ATP ')
                    .removeprefix('WTA ').removesuffix(' Singles'))
        label, location = _place(name)
        if (tour, label) in DISCONTINUED:
            continue
        # The tour's own calendar first; the name rules are the fallback for
        # anything it does not list, and the hard default the last resort.
        surface, surface_from = published_surface(tour, label)
        if surface is None:
            surface = surface_of(comp)
            surface_from = 'name rule' if surface_of(comp, default=None) else 'default(hard)'
        s = _override(tour, label, shapes.get(comp))
        problem = _classify(s)
        if problem and _clipped_by_window(main['match_date'].min(), window_start):
            problem = 'the cached season opens after this tournament began'
        s = s or {}
        rows.append({
            'tournament': name,
            'name': label,
            'location': location,
            'country': host_country(location),
            'competition': comp,
            'level': level,
            'start': f'{d0[:4]}-{d0[4:6]}-{d0[6:]}',
            'end': f'{d1[:4]}-{d1[4:6]}-{d1[6:]}',
            'surface': surface,
            'surface_from': surface_from,
            'draw': s.get('draw', ''),
            'seeds': s.get('seeds', ''),
            'byes': s.get('byes', ''),
            'main_draw_matches': len(main),
            'shape': ('round robin' if level in ROUND_ROBIN
                      else problem or 'verified'),
        })
    order = list(levels.values())
    rows.sort(key=lambda r: (order.index(r['level']), r['start']))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tour', choices=['ATP', 'WTA', 'both'], default='both')
    args = ap.parse_args()
    df = pickle.load(CACHE.open('rb'))
    for tour in (['ATP', 'WTA'] if args.tour == 'both' else [args.tour]):
        rows = build(tour, df)
        out = ROOT / f'{tour.lower()}_calendar.csv'
        with out.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        span = f"{min(r['start'] for r in rows)} .. {max(r['end'] for r in rows)}"
        print(f'{tour}: {len(rows):>3} events  {span}  -> {out.name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
