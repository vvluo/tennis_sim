"""Rebuild the ratings and the published site. Entry point for the weekly job.

    python build_ratings.py                 # rebuild from whatever is cached
    python build_ratings.py --budget 60     # cap live API calls
    python build_ratings.py --prune         # drop cache files outside the window

Runs empirical_rating_model.ipynb, which owns the pipeline, then checks it
actually produced what it claims and stages the site for deployment. Exits
non-zero on any failure so a scheduled run fails loudly rather than quietly
publishing yesterday's numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTEBOOK = ROOT / 'empirical_rating_model.ipynb'
CACHE = ROOT / 'sportradar_cache'
SITE = ROOT / 'site'
OUTPUTS = ('ratings.json', 'ratings_board.html')
WINDOW_DAYS = 365


def prune_cache(keep_days: int = WINDOW_DAYS, slack: int = 14) -> int:
    """Drop cached days that have fallen out of the rating window.

    The window rolls forward every week but the files do not expire on their
    own, so without this the cache grows without bound to serve a fixed span.
    `slack` keeps a couple of weeks either side, since the window edge moves.
    """
    if not CACHE.exists():
        return 0
    cutoff = date.today() - timedelta(days=keep_days + slack)
    removed = 0
    for path in CACHE.glob('daily_*.json.gz'):
        found = re.search(r'daily_(\d{4})-(\d{2})-(\d{2})', path.name)
        if found and date(*map(int, found.groups())) < cutoff:
            path.unlink()
            removed += 1
    return removed


def run_notebook() -> None:
    """Execute the pipeline notebook in place, surfacing the failing cell."""
    import nbformat
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError

    notebook = nbformat.read(NOTEBOOK, as_version=4)
    client = NotebookClient(notebook, timeout=3600, kernel_name='python3',
                            resources={'metadata': {'path': str(ROOT)}})
    try:
        client.execute()
    except CellExecutionError as error:
        nbformat.write(notebook, NOTEBOOK)          # keep the traceback visible
        raise SystemExit(f'notebook failed:\n{error}') from error
    nbformat.write(notebook, NOTEBOOK)


def check_outputs() -> dict:
    """Refuse to publish a build that did not actually produce fresh ratings."""
    for name in OUTPUTS:
        if not (ROOT / name).exists():
            raise SystemExit(f'missing expected output: {name}')

    records = json.loads((ROOT / 'ratings.json').read_text())
    if not records:
        raise SystemExit('ratings.json is empty')

    board = (ROOT / 'ratings_board.html').read_text()
    if '/*__DATA__*/' in board:
        raise SystemExit('ratings_board.html still holds the template placeholder')

    tours = {r['t'] for r in records}
    if tours != {'ATP', 'WTA'}:
        raise SystemExit(f'expected both tours, got {sorted(tours)}')
    return {'players': len(records),
            'atp': sum(r['t'] == 'ATP' for r in records),
            'wta': sum(r['t'] == 'WTA' for r in records)}


def build_tournament() -> None:
    """Rebuild the landing page against the ratings that just came out.

    The page carries the ranked pool and simulates in the browser, so this is
    pure assembly -- no API calls beyond the rankings already in the cache. It
    used to be copied through untouched, which shipped last week's pool.
    """
    import run_tournament
    argv = sys.argv[1:]
    sys.argv = ['run_tournament.py', '--out', str(ROOT / 'tournament.html')]
    try:
        if run_tournament.main() != 0:
            raise SystemExit('run_tournament failed')
    finally:
        sys.argv = ['build_ratings.py'] + argv


def stage_site() -> None:
    """Collect the pages to publish. The tournament is the landing page."""
    SITE.mkdir(exist_ok=True)
    for name in ('ratings_board.html', 'match_output.html', 'tournament.html'):
        source = ROOT / name
        if source.exists():
            shutil.copy(source, SITE / name)
    landing = ROOT / 'tournament.html'
    shutil.copy(landing if landing.exists() else ROOT / 'ratings_board.html',
                SITE / 'index.html')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=int, default=None,
                        help='cap on live API calls; the loader refuses to start '
                             'a pull it cannot finish within this')
    parser.add_argument('--prune', action='store_true',
                        help='delete cached days older than the rating window')
    parser.add_argument('--site-only', action='store_true',
                        help='rebuild and stage the pages from the committed '
                             'ratings, without running the notebook or spending '
                             'a single API call; for deploying front-end changes')
    args = parser.parse_args()

    if args.site_only:
        # No notebook, no key, no network: run_tournament reads ratings.json and
        # the cached rankings through a Client with a budget of zero, so a cache
        # miss fails loudly rather than quietly spending the trial quota.
        build_tournament()
        stage_site()
        print('staged site from the committed ratings; no API calls made')
        return 0

    if not os.environ.get('SPORTRADAR_API_KEY') and not (ROOT / '.sportradar_key').exists():
        raise SystemExit('no API key: set $SPORTRADAR_API_KEY or write .sportradar_key')

    if args.budget is not None:
        os.environ['SPORTRADAR_BUDGET'] = str(args.budget)

    if args.prune:
        print(f'pruned {prune_cache()} cached days outside the window')
        # Client.get has no TTL, so the rankings snapshot would otherwise be
        # served from disk for ever and every week's ratings would be scored
        # against whatever the standings were the day it was first fetched.
        # Dropping it here costs exactly one call on the next run.
        rankings = CACHE / 'rankings.json.gz'
        if rankings.exists():
            rankings.unlink()
            print('dropped the rankings snapshot; it refetches in one call')

    cached_before = len(list(CACHE.glob('daily_*.json.gz'))) if CACHE.exists() else 0
    print(f'cache holds {cached_before} page files before the run')

    run_notebook()
    summary = check_outputs()
    build_tournament()
    stage_site()

    cached_after = len(list(CACHE.glob('daily_*.json.gz'))) if CACHE.exists() else 0
    print(f"built {summary['players']} players "
          f"(ATP {summary['atp']}, WTA {summary['wta']}); "
          f'cache grew by {cached_after - cached_before} pages')
    return 0


if __name__ == '__main__':
    sys.exit(main())
