"""Build the grand slam page.

The page now simulates in the browser, so this script no longer plays a
tournament: it collects the rated-and-ranked pool for each tour and inlines it
with the JS engine. Every draw the visitor asks for is generated client-side,
which is the only way a static Pages site can offer a Simulate button.

    python run_tournament.py --out tournament.html
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import sitenote

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / 'simulation' / 'tournament_template.html'
ENGINE = ROOT / 'simulation' / 'engine.js'
MATCHVIEW = ROOT / 'simulation' / 'matchview.js'
RATINGS = ROOT / 'ratings.json'

MIN_POOL = 200          # a 128 draw with 10% dropout needs well over 128


def candidates(tour: str, ranks_by_tour, nations_by_tour=None,
               points_by_tour=None):
    """Ranked pool for one tour: everyone with both a rating and a ranking.

    `country` is the three-letter code the ranking feed carries, or None for a
    player under the neutral designation. No tournament is held in the countries
    those players come from, so a missing code costs them nothing.

    `points` is the player's real ranking points at the snapshot, carried only
    when `points_by_tour` is supplied. The season page needs it: a simulated
    season starts everyone on zero, so until the real total has been cycled out
    there is nothing to rank anybody by. The tournament page has no season to
    cycle and leaves it out.
    """
    ranks = ranks_by_tour[tour]
    nations = (nations_by_tour or {}).get(tour, {})
    points = (points_by_tour or {}).get(tour, {})
    pool = []
    for row in json.loads(RATINGS.read_text()):
        if row['t'] != tour or row['p'] not in ranks:
            continue
        entry = {'name': row['p'], 'rank': ranks[row['p']],
                 'ratings': {'SRV': row['s'], 'RET': row['r'],
                             'SHOT': row['h'], 'CONS': row['c']}}
        code = nations.get(row['p'])
        if code:
            entry['country'] = code
        if row['p'] in points:
            entry['points'] = points[row['p']]
        pool.append(entry)
    return sorted(pool, key=lambda p: p['rank'])


def entry_points():
    """Real ranking points per player, from the same cached rankings call.

    This is the total the feed reports, not a per-tournament breakdown -- the
    rankings endpoint carries no breakdown at all. The season page decays this
    total as the simulated season awards its own points.
    """
    from sportradar_data import Client
    client = Client(budget=0)                       # cache only, never spends

    def flip(name):
        last, _, first = name.partition(',')
        return f'{first.strip()} {last.strip()}' if first else name.strip()

    out = {}
    for ranking in client.rankings():
        if ranking['name'] not in ('ATP', 'WTA'):
            continue
        out[ranking['name']] = {flip(e['competitor']['name']): e['points']
                                for e in ranking['competitor_rankings']
                                if e.get('points') is not None}
    return out


def nationalities():
    """Three-letter country code per player, from the same cached rankings call.

    Players under the neutral designation carry a country of 'Neutral' and no
    code; they are simply left out, which is what the boost expects.
    """
    from sportradar_data import Client
    client = Client(budget=0)

    def flip(name):
        last, _, first = name.partition(',')
        return f'{first.strip()} {last.strip()}' if first else name.strip()

    out = {}
    for ranking in client.rankings():
        if ranking['name'] not in ('ATP', 'WTA'):
            continue
        out[ranking['name']] = {
            flip(e['competitor']['name']): e['competitor'].get('country_code')
            for e in ranking['competitor_rankings']
            if e['competitor'].get('country_code')}
    return out


def rankings():
    from sportradar_data import Client
    client = Client(budget=0)                       # cache only, never spends

    def flip(name):                                 # "Sinner, Jannik" -> "Jannik Sinner"
        last, _, first = name.partition(',')
        return f'{first.strip()} {last.strip()}' if first else name.strip()

    out = {}
    for ranking in client.rankings():
        if ranking['name'] not in ('ATP', 'WTA'):
            continue
        out[ranking['name']] = {flip(e['competitor']['name']): e['rank']
                                for e in ranking['competitor_rankings']}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='tournament.html')
    args = parser.parse_args()

    ranks = rankings()
    nations = nationalities()
    pools = {}
    for tour in ('ATP', 'WTA'):
        pool = candidates(tour, ranks, nations)
        if len(pool) < MIN_POOL:
            raise SystemExit(f'only {len(pool)} rated+ranked {tour} players; '
                             f'need at least {MIN_POOL}')
        pools[tour] = pool
        print(f'{tour}: {len(pool)} players, ranks {pool[0]["rank"]}-{pool[-1]["rank"]}')

    # The date belongs to the RATINGS, not to this build: a front-end-only
    # rebuild must not relabel the data set. ratings.json's own mtime is the
    # closest honest source, and it only moves when the notebook rewrites it.
    built = datetime.fromtimestamp(RATINGS.stat().st_mtime).date().isoformat()
    payload = {'pools': pools, 'built': built}
    print(f'data set dated {built}')

    page = (TEMPLATE.read_text()
            .replace('/*__ENGINE__*/', ENGINE.read_text())
            .replace('/*__MATCHVIEW__*/', MATCHVIEW.read_text())
            .replace('/*__DATA__*/', json.dumps(payload, separators=(',', ':'))))
    page = sitenote.inline(page)
    for marker in ('/*__ENGINE__*/', '/*__MATCHVIEW__*/', '/*__DATA__*/'):
        if marker in page:
            raise SystemExit(f'{marker} was not substituted')
    Path(args.out).write_text(page)
    print(f'wrote {args.out}  ({Path(args.out).stat().st_size / 1024:.0f} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
