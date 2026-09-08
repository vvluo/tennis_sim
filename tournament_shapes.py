"""Draw size and seed count for every ATP/WTA event at 250 level and above.

Neither figure is published by the feed. `seasons/{id}/info.json` carries
`number_of_qualified_competitors` (the draw) but costs a call per season and says
nothing about seeds, and there is no seed-count field anywhere. Both are
therefore reconstructed from the match records, which is free.

Three details make the reconstruction correct rather than approximate:

* Qualifying is a separate draw with its OWN seeding, and the phase label for it
  is not consistent -- Charleston says `qualification`, Kosice says
  `qualification_playoffs`. Anything starting with "qualification" is excluded,
  or its seeds (1-12) contaminate the main draw's (1-8).
* `cancelled` records are fixtures that never happened. Charleston carries three,
  which is exactly why a 48 draw appeared to hold 50 matches.
* The seed COUNT is a property of the draw -- 8, 16 or 32 seeded positions,
  being a quarter of the bracket -- and that is what `seeds` records. Seed
  NUMBERS can run past it: when a seed withdraws, the replacement is seeded
  behind the last one, so Charleston 2026 issued a 17 in a draw built for 16.
  `seeds_issued_max` keeps that, and `seeds_withdrawn` lists the numbers that
  never played. The count is 16; the 17 is what the withdrawal did to it.
* A single-elimination draw of N players plays N-1 matches, byes included, so the
  draw size follows from the match count once the two filters above are applied.

Run: python tournament_shapes.py  ->  tournament_shapes.csv
"""

from __future__ import annotations

import collections
import csv
import glob
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'sportradar_cache'
OUT = ROOT / 'tournament_shapes.csv'

# 250 and above, both tours. wta_125 and the Challengers sit below this line.
LEVELS = {
    'grand_slam', 'atp_1000', 'atp_500', 'atp_250',
    'atp_world_tour_finals', 'atp_next_generation',
    'wta_1000', 'wta_500', 'wta_250', 'wta_championships',
}
# Every round after the first has a fixed size in a bracket of B slots.
LATE_ROUNDS = {'final': 1, 'semifinal': 2, 'quarterfinal': 4,
               'round_of_16': 8, 'round_of_32': 16, 'round_of_64': 32}
ROUND_SLOTS = {'final': 2, 'semifinal': 4, 'quarterfinal': 8, 'round_of_16': 16,
               'round_of_32': 32, 'round_of_64': 64, 'round_of_128': 128}


def is_qualifying(phase) -> bool:
    return str(phase or '').startswith('qualification')


def next_power_of_two(n: int) -> int:
    p = 1
    while p < n:
        p *= 2
    return p


def collect():
    seasons = collections.defaultdict(lambda: {
        'matches': 0, 'cancelled': 0, 'seeds': set(), 'rounds': collections.Counter(),
        'slots': set(), 'name': None, 'level': None, 'year': None, 'surface': set(),
        'gender': None, 'best_of': set(),
    })
    for path in sorted(glob.glob(str(CACHE / 'daily_*.json.gz'))):
        with gzip.open(path, 'rt') as fh:
            for summary in json.load(fh).get('summaries', []):
                event = summary['sport_event']
                ctx = event.get('sport_event_context', {})
                comp = ctx.get('competition') or {}
                if comp.get('type') != 'singles' or comp.get('level') not in LEVELS:
                    continue
                if is_qualifying((ctx.get('stage') or {}).get('phase')):
                    continue
                season = (ctx.get('season') or {}).get('id')
                if not season:
                    continue
                rec = seasons[season]
                rec['name'] = comp.get('name')
                rec['level'] = comp.get('level')
                rec['gender'] = comp.get('gender')
                rec['year'] = (ctx.get('season') or {}).get('year')
                if (ctx.get('mode') or {}).get('best_of'):
                    rec['best_of'].add(ctx['mode']['best_of'])
                status = summary.get('sport_event_status', {}) or {}
                if status.get('status') == 'cancelled':
                    rec['cancelled'] += 1          # a fixture that never happened
                    continue
                rec['matches'] += 1
                rec['rounds'][(ctx.get('round') or {}).get('name')] += 1
                for c in event.get('competitors', []):
                    if c.get('seed') is not None:
                        rec['seeds'].add(c['seed'])
                    if c.get('bracket_number') is not None:
                        rec['slots'].add(c['bracket_number'])
    return seasons


def shape(rec):
    """One season -> its draw size, seed count, and how much to trust them.

    The draw is derived twice and only reported when the two agree:

        from the bracket   D = B/2 + (matches in the first round)
        from the total     D = (all matches) + 1

    The first is blind to missing late rounds, the second to missing early ones,
    so agreement means the cache holds the whole event. Without this a partly
    cached tournament reports a plausible-looking but wrong draw.
    """
    seeds = sorted(rec['seeds'])
    rounds = rec['rounds']
    played = [r for r in ROUND_SLOTS if rounds.get(r)]
    bracket = max((ROUND_SLOTS[r] for r in played), default=0)
    first = next((r for r in ROUND_SLOTS if ROUND_SLOTS[r] == bracket), None)

    from_bracket = bracket // 2 + rounds.get(first, 0) if bracket else 0
    from_total = rec['matches'] + 1
    # every round after the first must be exactly its full size
    # Only rounds AFTER the first are full size -- the first round is short by
    # exactly the number of byes, which is the whole point of a 48 or 96 draw.
    later_ok = all(rounds.get(r, 0) == n for r, n in LATE_ROUNDS.items()
                   if ROUND_SLOTS[r] < bracket)
    complete = bool(bracket) and later_ok and from_bracket == from_total

    draw = from_total if complete else None
    # A quarter of the bracket is seeded: 8 in a 32, 16 in a 64, 32 in a 128.
    seed_count = bracket // 4 if complete else None
    issued = max(seeds) if seeds else 0
    # Sanity: byes are handed to seeds, so there cannot be more byes than seeds,
    # and the numbers issued should not run far past the seeded positions. Both
    # fail on a partly cached event, where missing early rounds mimic a small draw.
    # A draw cannot exceed its bracket; if it does, an extra match slipped in.
    #
    # One blind spot remains, and it cannot be closed from the match records:
    # the two draw derivations reduce to the same expression once the later
    # rounds are full, so an event MISSING first-round matches yields a smaller
    # draw that is internally consistent. WTA Cleveland 2025 reads as a 14 draw
    # here and is declared 32 -- its whole first round is absent from the cache.
    # Draws below half the smallest real tier are therefore treated as suspect;
    # anything unusual is worth one seasons/{id}/info.json call to confirm.
    plausible = (bool(complete) and draw <= bracket and draw >= 16
                 and (bracket - draw) <= seed_count and issued <= seed_count + 4)
    # Seeds who withdrew before playing never appear in a match, so the numbers
    # observed have holes. They were issued; they just never took the court.
    missing = [n for n in range(1, issued + 1) if n not in rec['seeds']]
    return {
        'tournament': rec['name'],
        'year': rec['year'],
        'level': rec['level'],
        'gender': rec['gender'],
        'best_of': min(rec['best_of']) if rec['best_of'] else '',
        'draw': draw or '',
        'bracket': bracket if complete else '',
        'byes': (bracket - draw) if complete else '',
        'seeds': seed_count if plausible else '',          # seeded positions in the draw
        'seeds_issued_max': issued or '',                  # highest number actually given out
        'replacements': max(0, issued - seed_count) if plausible else '',
        'seeds_seen': len(seeds),
        'seeds_withdrawn': ' '.join(map(str, missing)),
        'plausible': plausible,
        'draw_complete': complete,
        'matches': rec['matches'],
        'cancelled': rec['cancelled'],
    }


def main():
    rows = [shape(r) for r in collect().values()]
    rows.sort(key=lambda r: (str(r['level']), str(r['tournament'])))
    with OUT.open('w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    good = [r for r in rows if r['plausible']]
    withrep = [r for r in good if r['replacements']]
    print(f'{len(rows)} ATP/WTA singles seasons at 250+ in the cache')
    print(f'  {sum(r["draw_complete"] for r in rows)} with a complete draw')
    print(f'  {len(good)} that also pass the bye/seed sanity checks\n')
    print(f'  {len(withrep)} issued a seed number past the seeded positions '
          f'(withdrawal replacements)')
    print(f'  seed counts recorded: '
          f'{sorted({r["seeds"] for r in good})}')
    print(f'  draw sizes recorded:  {sorted({r["draw"] for r in good})}')
    if withrep:
        print('\n  where a withdrawal pushed the numbering past the count:')
        for r in sorted(withrep, key=lambda r: -r['replacements'])[:6]:
            print(f"    {r['tournament'][:42]:<42} draw {r['draw']:>3}  "
                  f"seeds {r['seeds']:>2}  highest issued {r['seeds_issued_max']:>2}"
                  f"  withdrew: {r['seeds_withdrawn'] or '-'}")
    return rows


if __name__ == '__main__':
    main()
