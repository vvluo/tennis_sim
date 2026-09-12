"""Build matchup.html -- two players, N matches, whatever scoring you ask for.

Pure assembly, like run_season.py: the page carries the rated pool and plays the
matches in the browser, so there are no API calls here. The theme, the engine and
the About panel all come from the same sources the other pages use.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import sitenote
from run_season import theme_css
from run_tournament import candidates, rankings, nationalities

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / 'simulation' / 'matchup_template.html'
ENGINE = ROOT / 'simulation' / 'engine.js'
FORECAST = ROOT / 'simulation' / 'forecast.js'
RATINGS = ROOT / 'ratings.json'
MIN_POOL = 100

MARKERS = ('/*__THEME__*/', '/*__ENGINE__*/', '/*__FORECAST__*/', '/*__DATA__*/')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default='matchup.html')
    args = ap.parse_args()

    ranks = rankings()
    nations = nationalities()
    pools = {}
    for tour in ('ATP', 'WTA'):
        pool = candidates(tour, ranks, nations)
        if len(pool) < MIN_POOL:
            raise SystemExit(f'only {len(pool)} rated+ranked {tour} players')
        pools[tour] = pool
        print(f'{tour}: {len(pool)} players')

    built = datetime.fromtimestamp(RATINGS.stat().st_mtime).date().isoformat()
    payload = {'pools': pools, 'built': built}

    page = (TEMPLATE.read_text()
            .replace('/*__THEME__*/', theme_css())
            .replace('/*__ENGINE__*/', ENGINE.read_text())
            .replace('/*__FORECAST__*/', FORECAST.read_text())
            .replace('/*__DATA__*/', json.dumps(payload, separators=(',', ':'))))
    page = sitenote.inline(page)
    for marker in MARKERS:
        if marker in page:
            raise SystemExit(f'{marker} was not substituted')
    if sitenote.MARKER in page:
        raise SystemExit('the About panel marker was not substituted')
    Path(args.out).write_text(page)
    print(f'data set dated {built}')
    print(f'wrote {args.out}  ({Path(args.out).stat().st_size / 1024:.0f} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
