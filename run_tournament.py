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
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / 'simulation' / 'tournament_template.html'
ENGINE = ROOT / 'simulation' / 'engine.js'
RATINGS = ROOT / 'ratings.json'

MIN_POOL = 200          # a 128 draw with 10% dropout needs well over 128


def candidates(tour: str, ranks_by_tour):
    """Ranked pool for one tour: everyone with both a rating and a ranking."""
    ranks = ranks_by_tour[tour]
    pool = []
    for row in json.loads(RATINGS.read_text()):
        if row['t'] != tour or row['p'] not in ranks:
            continue
        pool.append({'name': row['p'], 'rank': ranks[row['p']],
                     'ratings': {'SRV': row['s'], 'RET': row['r'],
                                 'SHOT': row['h'], 'CONS': row['c']}})
    return sorted(pool, key=lambda p: p['rank'])


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
    pools = {}
    for tour in ('ATP', 'WTA'):
        pool = candidates(tour, ranks)
        if len(pool) < MIN_POOL:
            raise SystemExit(f'only {len(pool)} rated+ranked {tour} players; '
                             f'need at least {MIN_POOL}')
        pools[tour] = pool
        print(f'{tour}: {len(pool)} players, ranks {pool[0]["rank"]}-{pool[-1]["rank"]}')

    page = (TEMPLATE.read_text()
            .replace('/*__ENGINE__*/', ENGINE.read_text())
            .replace('/*__DATA__*/', json.dumps(pools, separators=(',', ':'))))
    Path(args.out).write_text(page)
    print(f'wrote {args.out}  ({Path(args.out).stat().st_size / 1024:.0f} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
