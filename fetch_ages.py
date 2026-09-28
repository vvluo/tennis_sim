"""Birth dates for the ranked field, and the ages they imply.

The two tours cost very different amounts.

  WTA  free. wta_data/wta_players.csv -- the Sackmann registry -- carries a birth
       date for 483 of the 500 ranked women, matched on name. No API calls.
  ATP  one API call per player. That registry is women-only, so the men have no
       birth date anywhere on disk, and the profile feed has no bulk form. The
       cost is priced up front and the run is refused if the budget cannot cover
       it: a trial month is about 1,000 calls and the weekly refresh needs its
       share, so spending it all here by accident is the failure to avoid.

Profiles cache like every other feed, so the cost is paid once; a re-run over the
same players is free.

    python fetch_ages.py --top 250 --dry-run     # what it would cost
    python fetch_ages.py --top 250 --budget 260  # actually pull
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / 'wta_data' / 'wta_players.csv'
RANKINGS = ROOT / 'sportradar_cache' / 'rankings.json.gz'
OUT = ROOT / 'ages.json'


def norm(s: str) -> str:
    s = unicodedata.normalize('NFKD', str(s))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace('-', ' ').replace("'", '').replace('.', ' ')
    s = re.sub(r'\(\d{4}\)', ' ', s)          # "Lee, Eunhye (2000)"
    return re.sub(r'\s+', ' ', s).strip()


def ranked(limit_atp: int):
    """The ranked field from the cached snapshot: (tour, rank, name, id)."""
    with gzip.open(RANKINGS) as fh:
        payload = json.load(fh)
    snapshot = date(*(int(x) for x in payload['generated_at'][:10].split('-')))
    rows = []
    for lst in payload['rankings']:
        tour = lst['name']
        if tour not in ('ATP', 'WTA'):
            continue
        for e in lst['competitor_rankings']:
            if tour == 'ATP' and e['rank'] > limit_atp:
                continue
            rows.append((tour, e['rank'], e['competitor']['name'], e['competitor']['id']))
    return snapshot, rows


def dob_from_profile(payload: dict) -> str | None:
    """The feed puts it under `info` on some tiers and on the competitor on
    others, so both are tried before giving up on a player."""
    for holder in (payload.get('info'), payload.get('competitor'), payload):
        if isinstance(holder, dict):
            raw = holder.get('date_of_birth')
            if raw:
                return str(raw)[:10]
    return None


def registry_dobs() -> dict[tuple[str, str], str]:
    """(first, last) -> YYYYMMDD, for players plausibly still active."""
    out: dict[tuple[str, str], str] = {}
    if not REGISTRY.exists():
        return out
    with REGISTRY.open() as fh:
        for r in csv.DictReader(fh):
            dob = (r.get('dob') or '').strip()
            if not re.fullmatch(r'(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', dob):
                continue
            if dob < '19850101':
                continue
            out[(norm(r['name_first']), norm(r['name_last']))] = dob
    return out


def wta_ages(rows) -> dict[str, str]:
    """Name-matched birth dates, exact first+last then a UNIQUE first token --
    "Miyazaki, Yuriko Lily" is the registry's "Miyazaki, Yuriko". Anything
    ambiguous is left out rather than guessed at."""
    reg = registry_dobs()
    by_token: dict[tuple[str, str], list[str]] = {}
    for (first, last), dob in reg.items():
        if first:
            by_token.setdefault((last, first.split()[0]), []).append(dob)
    found = {}
    for tour, _rank, name, _id in rows:
        if tour != 'WTA':
            continue
        last, _, first = (norm(p) for p in (name.partition(',')))
        hit = reg.get((first, last))
        if hit is None and first:
            same = by_token.get((last, first.split()[0]), [])
            hit = same[0] if len(same) == 1 else None
        if hit:
            found[name] = f'{hit[:4]}-{hit[4:6]}-{hit[6:]}'
    return found


def years(dob: str, at: date) -> float:
    y, m, d = (int(x) for x in dob.split('-'))
    return round((at - date(y, m, d)).days / 365.2425, 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--top', type=int, default=250,
                    help='how far down the ATP ranking to go (default 250)')
    ap.add_argument('--budget', type=int, default=0,
                    help='cap on live API calls; 0 means cache-only')
    ap.add_argument('--dry-run', action='store_true',
                    help='report what it would cost and change nothing')
    ap.add_argument('--out', default=str(OUT))
    args = ap.parse_args()

    from sportradar_data import BudgetExceeded, Client

    snapshot, rows = ranked(args.top)
    atp = [r for r in rows if r[0] == 'ATP']
    client = Client(budget=args.budget)

    uncached = [r for r in atp if not client._cache_path(
        'profile_' + r[3].replace(':', '_')).exists()]
    print(f'snapshot {snapshot}   ATP top {args.top}: {len(atp)} players, '
          f'{len(atp) - len(uncached)} profiles already cached, {len(uncached)} to fetch')

    women = wta_ages(rows)
    print(f'WTA: {len(women)} of {sum(1 for r in rows if r[0] == "WTA")} '
          f'birth dates from the registry, no API calls')

    if args.dry_run:
        print(f'dry run: would spend {len(uncached)} calls')
        return 0
    if len(uncached) > args.budget:
        raise SystemExit(
            f'{len(uncached)} profiles are not cached but the budget is {args.budget}. '
            f'Re-run with --budget {len(uncached)} once you mean to spend them.')

    men, missing = {}, []
    for tour, rank, name, cid in atp:
        try:
            dob = dob_from_profile(client.competitor_profile(cid))
        except BudgetExceeded:
            print(f'budget exhausted at #{rank} {name}', file=sys.stderr)
            break
        if dob:
            men[name] = dob
        else:
            missing.append(f'#{rank} {name}')

    out = {'snapshot': snapshot.isoformat(), 'atp_top': args.top,
           'ATP': {n: {'dob': d, 'age': years(d, snapshot)} for n, d in men.items()},
           'WTA': {n: {'dob': d, 'age': years(d, snapshot)} for n, d in women.items()}}
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True))
    print(f'ATP: {len(men)}/{len(atp)} with a birth date '
          f'({client.requests_made} calls spent)')
    if missing:
        print(f'  no date of birth in the feed for {len(missing)}: {missing[:5]}')
    print(f'wrote {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
