"""Build the season simulation page.

Like run_tournament.py this inlines the engine and the player pools, but it also
inlines the closed-form forecaster and both tours' calendars. A season is ~2600
matches; the page plays only the ones involving the player you pick point by
point and settles the rest with forecast.js, which keeps the point records --
not the arithmetic -- off the heap.

The stylesheet is lifted from the tournament page at build time rather than
copied into this template, so the two pages cannot drift apart on theme tokens.

    python run_season.py --out season.html
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import sitenote

from run_tournament import (candidates, rankings, nationalities,
                            entry_points, MIN_POOL)

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / 'simulation' / 'season_template.html'
THEME_SOURCE = ROOT / 'simulation' / 'tournament_template.html'
ENGINE = ROOT / 'simulation' / 'engine.js'
FORECAST = ROOT / 'simulation' / 'forecast.js'
MATCHVIEW = ROOT / 'simulation' / 'matchview.js'
RATINGS = ROOT / 'ratings.json'

# An event whose draw could not be derived from the cache has no shape to
# simulate. It is carried in the calendar for completeness but skipped by the
# simulator, which says so.
SKIP_SHAPE_OK = 'verified'

# The two tour finals are round robins, not brackets: eight qualifiers, two
# groups, then a knockout. They carry no draw size in the calendar because they
# have no draw, so the shape check cannot pass them -- they are named instead.
ROUND_ROBIN = {'ATP Finals', 'WTA Finals'}
ROUND_ROBIN_FIELD = 8

# Next Gen is a round robin too, but its field is an age cut-off and the source
# data carries no dates of birth, so there is no way to say who qualifies.
NO_AGE_DATA = {'Next Gen Finals'}

# The season-ending events, which play last whatever their date says.
SEASON_ENDING = {'ATP Finals', 'WTA Finals', 'Next Gen Finals'}


def season_day(iso):
    """Day of the year, 0-based, ignoring which year the date fell in.

    The cache is a rolling twelve months (August to August), so its raw dates
    run 2025-08 .. 2026-08. A season is played January to December, so events
    are ordered and spaced by where they sit in the CALENDAR year instead. Using
    the raw dates would send the run backwards in time halfway through -- and
    with it the commitment ledger and the load decay, which are both differences
    between day numbers.
    """
    y, m, d = (int(x) for x in iso.split('-'))
    return (date(2001, m, d) - date(2001, 1, 1)).days      # 2001: not a leap year


def calendar(tour):
    path = ROOT / f'{tour.lower()}_calendar.csv'
    if not path.exists():
        raise SystemExit(f'{path.name} is missing -- run build_calendar.py first')
    out = []
    for r in csv.DictReader(path.open()):
        rr = r['level'] in ROUND_ROBIN
        playable = rr or (r['shape'] == SKIP_SHAPE_OK and r['draw'].isdigit())
        if r['level'] in NO_AGE_DATA:
            skip = 'no dates of birth in the source data, so the age cut-off ' \
                   'that decides the field cannot be applied'
        elif playable:
            skip = None
        else:
            skip = r['shape']
        out.append({
            'name': r['name'], 'location': r['location'], 'level': r['level'],
            'country': r.get('country') or None,
            'start': r['start'], 'end': r['end'], 'surface': r['surface'],
            'draw': ROUND_ROBIN_FIELD if rr else (int(r['draw']) if playable else None),
            'seeds': ROUND_ROBIN_FIELD if rr
                     else (int(r['seeds']) if playable and r['seeds'].isdigit() else None),
            'format': 'rr' if rr else None,
            'skip': skip,
        })
    for e in out:
        e['sday'] = season_day(e['start'])
        e['sday_end'] = season_day(e['end'])
        e['sweek'] = e['sday'] // 7
        # An event that runs across new year would wrap to a tiny sday; none in
        # the current calendars do, and a silent wrap would reorder the season.
        if e['sday_end'] < e['sday']:
            raise SystemExit(f"{e['name']} spans the year boundary; "
                             f"the season ordering cannot place it")
    return order_season(out)


def order_season(rows):
    """Playing order: January first, season finals last however they are dated.

    Forcing the finals is insurance rather than a correction -- as the calendars
    stand they are already the latest events, so this changes nothing today and
    holds if a date moves.
    """
    return sorted(rows, key=lambda e: (e['level'] in SEASON_ENDING, e['sday'], e['name']))


def theme_css():
    """The <style> block from the tournament page, verbatim."""
    m = re.search(r'<style>(.*?)</style>', THEME_SOURCE.read_text(), re.S)
    if not m:
        raise SystemExit('no <style> block found in the tournament template')
    css = m.group(1)
    for token in ('--ground', '--surface', '--ink', '--accent', '--atp', '--wta'):
        if token not in css:
            raise SystemExit(f'theme is missing {token}; refusing to build')
    return css


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default='season.html')
    args = ap.parse_args()

    ranks = rankings()
    nations = nationalities()
    points = entry_points()
    pools, cals = {}, {}
    for tour in ('ATP', 'WTA'):
        pool = candidates(tour, ranks, nations, points)
        if len(pool) < MIN_POOL:
            raise SystemExit(f'only {len(pool)} rated+ranked {tour} players')
        pools[tour] = pool
        cals[tour] = calendar(tour)
        playable = [e for e in cals[tour] if not e['skip']]
        biggest = max(e['draw'] for e in playable)
        if len(pool) < biggest:
            raise SystemExit(f'{tour} pool holds {len(pool)}, but the calendar '
                             f'has a {biggest} draw')
        # Every WTA 1000 has to fall in one of the two named groups, or its
        # ranking slot silently becomes "best of the rest". A calendar change
        # that renames or adds one would be invisible at runtime.
        if tour == 'WTA':
            compulsory = {'Indian Wells', 'Miami', 'Madrid', 'Rome', 'Toronto',
                          'Beijing', 'Cincinnati'}
            wta_only = {'Doha', 'Dubai', 'Wuhan'}
            thousands = {e['name'] for e in cals[tour]
                         if e['level'].endswith('1000') and not e['skip']}
            stray = thousands - compulsory - wta_only
            missing = (compulsory | wta_only) - thousands
            if stray:
                raise SystemExit(f'WTA 1000s not classified for the ranking '
                                 f'slots: {sorted(stray)}')
            if missing:
                raise SystemExit(f'WTA 1000s named in the ranking slots but not '
                                 f'on the calendar: {sorted(missing)}')

        # A missing host country is invisible at runtime -- the home boost simply
        # never fires for that event -- so it fails the build instead.
        homeless = [e['name'] for e in cals[tour] if not e['country']]
        if homeless:
            raise SystemExit(f'{tour}: no host country for {homeless}; the '
                             f'home-tournament boost would never fire for them')
        print(f'{tour}: {len(pool)} players, {len(cals[tour])} events '
              f'({len(playable)} simulated, {len(cals[tour]) - len(playable)} skipped)')

    # When each player's real points should leave the ranking, so the simulated
    # season can cycle them out rather than starting everyone on zero.
    sys.path.insert(0, str(ROOT / 'simulation'))
    import realpoints
    drops = realpoints.schedules({t: {e['name'] for e in cals[t]} for t in cals})
    for tour in cals:
        have = sum(1 for p in pools[tour] if p['name'] in drops.get(tour, {}))
        placed = sum(sum(v for _, v in d['ev'] + d['wk'] + d['sub'])
                     for d in drops.get(tour, {}).values())
        rest = sum(d['rest'] for d in drops.get(tour, {}).values())
        share = 100 * placed / (placed + rest) if placed + rest else 0
        print(f'{tour}: drop schedule for {have}/{len(pools[tour])} players, '
              f'{share:.0f}% of their points dated, the rest decays')

    # `scale` is a diagnostic -- how much the schedule had to be stretched to
    # meet the reported total -- and the page has no use for it.
    lean = {t: {n: {k: v for k, v in d.items() if k != 'scale'}
                for n, d in rows.items()}
            for t, rows in drops.items()}

    built = datetime.fromtimestamp(RATINGS.stat().st_mtime).date().isoformat()
    payload = {'pools': pools, 'calendars': cals, 'built': built, 'drops': lean}
    print(f'data set dated {built}')

    page = (TEMPLATE.read_text()
            .replace('/*__THEME__*/', theme_css())
            .replace('/*__ENGINE__*/', ENGINE.read_text())
            .replace('/*__FORECAST__*/', FORECAST.read_text())
            .replace('/*__MATCHVIEW__*/', MATCHVIEW.read_text())
            .replace('/*__DATA__*/', json.dumps(payload, separators=(',', ':'))))
    page = sitenote.inline(page)
    for marker in ('/*__THEME__*/', '/*__ENGINE__*/', '/*__FORECAST__*/',
                   '/*__MATCHVIEW__*/', '/*__DATA__*/'):
        if marker in page:
            raise SystemExit(f'{marker} was not substituted')
    Path(args.out).write_text(page)
    print(f'wrote {args.out}  ({Path(args.out).stat().st_size / 1024:.0f} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
