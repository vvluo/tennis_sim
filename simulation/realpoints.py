"""Split each ranked player's REAL points into a schedule the season page can
cycle out as the simulated season awards its own.

Three tiers, in the order they are preferred:

  1. `ev`   the result was won at a tournament that is ON the simulated
            calendar, so it is dropped when the simulation plays that
            tournament. This is what makes defending a title mean something:
            the Shanghai champion arrives at the simulated Shanghai holding
            those points and either backs them up or loses them.
  2. `wk`   the result is dated but has no counterpart in the simulation -- a
            Challenger, a WTA 125 -- so it is dropped when its week elapses.
            Nothing pays it back, which is correct: the simulation does not
            play those tiers.
  3. `rest` whatever is left over once 1 and 2 are accounted for: qualifying,
            ITF, events the cache does not carry, and imprecision in the points
            tables below. It has no date to drop on, so it decays smoothly
            across the season -- the proxy, used only where nothing better
            exists.

Everything here reads the cache on disk. No API calls are made.

The per-event point values do not have to be exactly right: each player's
schedule is scaled so that a full season of drops sums to the total the feed
reports for them, which is what `scale` in the output records. An error in a
round value moves WHEN points leave, never HOW MANY.
"""

from __future__ import annotations

import glob
import gzip
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / 'sportradar_cache'

# Rounds a player can go out in, shallowest first. Keying on the round itself
# rather than on "how many wins" is what makes byes come out right.
LADDER = ['round_of_128', 'round_of_64', 'round_of_32', 'round_of_16',
          'quarterfinal', 'semifinal', 'final']
REACH = dict(zip(LADDER, ['R128', 'R64', 'R32', 'R16', 'QF', 'SF', 'F']))

# Mirrors POINTS in simulation/season_template.html. Duplicated deliberately --
# the page cannot import Python -- and tests/test_season_page.py checks the two
# against each other so they cannot drift apart unnoticed.
POINTS = {
    ('ATP', 'grand_slam'): [([128], dict(W=2000, F=1300, SF=800, QF=400, R16=200, R32=100, R64=50, R128=10))],
    ('ATP', 'atp_1000'): [([96], dict(W=1000, F=650, SF=400, QF=200, R16=100, R32=50, R64=30, R128=10)),
                          ([56, 48], dict(W=1000, F=650, SF=400, QF=200, R16=100, R32=50, R64=10))],
    ('ATP', 'atp_500'): [([48], dict(W=500, F=330, SF=200, QF=100, R16=50, R32=25, R64=16)),
                         ([32], dict(W=500, F=330, SF=200, QF=100, R16=50, R32=25, R64=13))],
    ('ATP', 'atp_250'): [([48], dict(W=250, F=165, SF=100, QF=50, R16=25, R32=13, R64=8, R128=4)),
                         ([32, 28], dict(W=250, F=165, SF=100, QF=50, R16=25, R32=13, R64=7))],
    ('WTA', 'grand_slam'): [([128], dict(W=2000, F=1300, SF=780, QF=430, R16=240, R32=130, R64=70, R128=10))],
    ('WTA', 'wta_1000'): [([96], dict(W=1000, F=650, SF=390, QF=215, R16=120, R32=65, R64=35, R128=10)),
                          ([56, 48], dict(W=1000, F=650, SF=390, QF=215, R16=120, R32=65, R64=10))],
    ('WTA', 'wta_500'): [([56, 48], dict(W=500, F=325, SF=195, QF=108, R16=60, R32=32, R64=1)),
                         ([32, 28], dict(W=500, F=325, SF=195, QF=108, R16=60, R32=1))],
    ('WTA', 'wta_250'): [([32, 28], dict(W=250, F=163, SF=98, QF=54, R16=30, R32=1))],
    # The feed carries no Challenger tier -- all 240 events come back flat --
    # so one blended row stands for CH50 through CH175. It is the biggest
    # approximation here, and the per-player scaling absorbs it.
    ('ATP', 'challenger'): [([48, 32], dict(W=110, F=65, SF=40, QF=22, R16=9, R32=0, R64=0, R128=0))],
    ('WTA', 'wta_125'): [([32, 28], dict(W=125, F=80, SF=48, QF=26, R16=13, R32=1))],
    ('WTA', 'wta_international'): [([32, 28], dict(W=250, F=163, SF=98, QF=54, R16=30, R32=1))],
    ('WTA', 'wta_elite_trophy'): [([32, 28], dict(W=250, F=163, SF=98, QF=54, R16=30, R32=1))],
}
# Only the professional circuits award ranking points. The junior events are the
# trap here: they carry their parent's level, so "Juniors US Open" arrives priced
# as a grand slam and a junior champion is credited 2000 points. That was 24% of
# the WTA's off-calendar total before this list existed.
RANKING_CATEGORIES = {'ATP', 'WTA', 'Challenger', 'WTA 125K', 'ITF Men', 'ITF Women'}

# Tiers this simulation does not play at all. Points won here expire on their
# date and are replaced at par: the player is still on that circuit, still
# winning roughly as much, and nothing here can pay them back. An event at 250
# or above that happens to be off our calendar is NOT one of these -- we do run
# that tier, so those points expire unreplaced like any other.
BELOW_TOUR_LEVELS = {'challenger', 'wta_125'}

ROUND_ROBIN_LEVELS = {'atp_world_tour_finals', 'wta_championships'}
NO_POINTS = {'atp_next_generation'}                    # an age cut-off, not a ranking event
FINALS = dict(rr=200, sf=400, f=500)

# Slot rules, mirroring slotOf/SLOTS on the page.
ATP_OPTIONAL_1000 = {'Monte Carlo'}
WTA_SLOTTED_1000 = {'Indian Wells', 'Miami', 'Madrid', 'Rome', 'Toronto', 'Beijing'}
WTA_ONLY_1000 = {'Doha', 'Dubai', 'Wuhan'}
SLOTS = {'ATP': dict(majors=10 ** 9, mand=10 ** 9, float=0, other=7),
         'WTA': dict(majors=10 ** 9, mand=10 ** 9, float=1, other=5)}

# The competition names the feed uses against the names the calendars use.
ALIAS = {'French Open': 'Roland Garros'}


def sim_name(competition: str) -> str:
    """'ATP Madrid, Spain Men Singles' -> 'Madrid'; 'French Open ...' -> 'Roland Garros'."""
    base = re.sub(r'\s+(Men|Women)\s+Singles$', '', competition)
    base = re.sub(r'^(?:\d{4}\s+)?(?:ATP|WTA)(?:\s+125K?|\s+Challenger)?\s+', '', base)
    city = base.split(',')[0].strip()
    return ALIAS.get(city, city)


def season_week(d: date) -> int:
    """Week of the CALENDAR year, matching how the page numbers its weeks."""
    return (date(2001, d.month, d.day) - date(2001, 1, 1)).days // 7


def _table(tour, level, draw):
    rows = POINTS.get((tour, level))
    if not rows:
        return None
    for draws, pts in rows:
        if draw in draws:
            return pts
    best, gap = rows[0][1], 10 ** 9
    for draws, pts in rows:
        for d in draws:
            if abs(d - draw) < gap:
                gap, best = abs(d - draw), pts
    return best


def _singles_matches():
    """Every closed singles match in the cache, as flat dicts. Cache only."""
    levels = {}
    comp_path = CACHE / 'competitions.json.gz'
    if comp_path.exists():
        with gzip.open(comp_path) as fh:
            for c in json.load(fh)['competitions']:
                levels[c['id']] = c.get('level')
    seen, out = set(), []
    for path in glob.glob(str(CACHE / 'daily_*.json.gz')):
        with gzip.open(path) as fh:
            for item in json.load(fh).get('summaries', []):
                ev = item.get('sport_event') or {}
                eid = ev.get('id')
                if not eid or eid in seen:
                    continue
                ctx = ev.get('sport_event_context') or {}
                comp = ctx.get('competition') or {}
                if comp.get('type') != 'singles':
                    continue
                status = item.get('sport_event_status') or {}
                if status.get('status') != 'closed' or not status.get('winner_id'):
                    continue
                cs = ev.get('competitors') or []
                if len(cs) != 2:
                    continue
                category = (ctx.get('category') or {}).get('name')
                if category not in RANKING_CATEGORIES:
                    continue
                level = levels.get(comp.get('id'))
                if level is None and category == 'Challenger':
                    level = 'challenger'
                if level is None:
                    continue
                rnd = ctx.get('round') or {}
                seen.add(eid)
                out.append(dict(
                    date=ev.get('start_time', '')[:10], competition=comp.get('name', ''),
                    level=level, gender=comp.get('gender', ''),
                    round=rnd.get('name') or (str(rnd['number']) if rnd.get('number') else None),
                    p1=cs[0].get('id'), p2=cs[1].get('id'), winner=status['winner_id']))
    return out


def _stages(matches):
    """Group matches into stagings of a competition.

    Keyed on a date gap, not on the calendar year: the cache spans two US Opens,
    and keying on the year fuses them -- which then drops BOTH, because the later
    staging was still running at the snapshot.
    """
    by_comp = defaultdict(list)
    for m in matches:
        by_comp[m['competition']].append(m)
    out = defaultdict(list)
    for comp, rows in by_comp.items():
        rows.sort(key=lambda r: r['date'])
        n, prev = 0, None
        for r in rows:
            d = date(*(int(x) for x in r['date'].split('-')))
            if prev is not None and (d - prev).days > 21:
                n += 1
            prev = d
            out[f'{comp} #{n}'].append(r)
    return out


def _results(matches, shapes):
    """Per player per staging: what they reached, what it paid, and when."""
    stages = _stages(matches)
    per = defaultdict(list)
    for inst, rows in stages.items():
        comp = rows[0]['competition']
        level = rows[0]['level']
        if level in NO_POINTS:
            continue
        tour = 'WTA' if rows[0]['gender'] == 'women' else 'ATP'
        end = max(date(*(int(x) for x in r['date'].split('-'))) for r in rows)
        main = [r for r in rows if not (r['round'] or '').startswith('qualification')]
        if not main:
            continue
        qualifiers = {r[side] for r in rows if (r['round'] or '').startswith('qualification')
                      for side in ('p1', 'p2')}
        played = defaultdict(list)
        for r in main:
            for side in ('p1', 'p2'):
                played[r[side]].append((r['round'], r[side] == r['winner']))
        if level in ROUND_ROBIN_LEVELS:
            for pid, games in played.items():
                pts = sum(FINALS['rr'] for rnd, won in games if rnd in ('1', '2', '3') and won)
                pts += sum(FINALS['sf'] for rnd, won in games if rnd == 'semifinal' and won)
                pts += sum(FINALS['f'] for rnd, won in games if rnd == 'final' and won)
                per[pid].append(dict(inst=inst, comp=comp, tour=tour, level='finals',
                                     pts=pts, end=end, qual=False))
            continue
        draw = shapes.get(comp)
        if draw is None:
            seen = [r['round'] for r in main if r['round'] in LADDER]
            deepest = min((LADDER.index(x) for x in seen), default=2)
            draw = {0: 128, 1: 64, 2: 32, 3: 16, 4: 8, 5: 4, 6: 2}[deepest]
        table = _table(tour, level, draw)
        if table is None:
            continue
        for pid, games in played.items():
            rounds = [rnd for rnd, _ in games if rnd in REACH]
            if not rounds:
                continue
            if any(rnd == 'final' and won for rnd, won in games):
                reach = 'W'
            else:
                reach = REACH[max(rounds, key=lambda r: LADDER.index(r))]
            per[pid].append(dict(inst=inst, comp=comp, tour=tour, level=level,
                                 pts=table.get(reach, 0), end=end,
                                 qual=pid in qualifiers))
    return per


def _slot(tour, g):
    if g['level'] == 'finals':
        return 'finals'
    if g['qual']:
        return 'other'
    if g['level'] == 'grand_slam':
        return 'majors'
    if not g['level'].endswith('1000'):
        return 'other'
    city = sim_name(g['comp'])
    if tour == 'ATP':
        return 'other' if city in ATP_OPTIONAL_1000 else 'mand'
    if city in WTA_SLOTTED_1000:
        return 'mand'
    return 'float' if city in WTA_ONLY_1000 else 'other'


def _counted(tour, results):
    """The results that make the ranking, under the same slot rules as the page."""
    bucket = defaultdict(list)
    for g in results:
        bucket[_slot(tour, g)].append(g)
    keep = {id(g) for g in bucket['finals']}
    pool = list(bucket['other'])
    S = SLOTS[tour]

    def take(rows, n, spill):
        rows.sort(key=lambda g: -g['pts'])
        for i, g in enumerate(rows):
            if i < n:
                keep.add(id(g))
            elif spill:
                pool.append(g)

    take(bucket['majors'], S['majors'], False)
    take(bucket['mand'], S['mand'], False)
    take(bucket['float'], S['float'], True)
    pool.sort(key=lambda g: -g['pts'])
    for g in pool[:S['other']]:
        keep.add(id(g))
    return [g for g in results if id(g) in keep]


def _shapes():
    """Draw size per competition, from tournament_shapes.csv."""
    import csv
    path = ROOT / 'tournament_shapes.csv'
    out = {}
    if not path.exists():
        return out
    for r in csv.DictReader(path.open()):
        if r.get('draw', '').isdigit():
            out.setdefault(r['tournament'], int(r['draw']))
    return out


def schedules(cal_names, snapshot=None, window_weeks=53):
    """Per player, when their real points should leave the ranking.

    `cal_names` maps tour -> the event names the simulated calendar plays, in
    calendar order; a result matched to one of them is dropped when the
    simulation reaches it.

    Returns tour -> player name -> {'ev': [[name, pts], ...],
                                    'wk': [[week, pts], ...],
                                    'rest': pts, 'scale': float}

    `scale` is what the three tiers were multiplied by so that a whole season of
    drops sums to exactly the total the feed reports. Without it an imprecise
    round value would leave a player with points nobody can take away, or take
    away more than they had.
    """
    from sportradar_data import Client
    client = Client(budget=0)                          # cache only, never spends

    def flip(name):
        last, _, first = name.partition(',')
        return f'{first.strip()} {last.strip()}' if first else name.strip()

    ranked = {}
    generated = None
    for ranking in client.rankings():
        if ranking['name'] not in ('ATP', 'WTA'):
            continue
        for e in ranking['competitor_rankings']:
            ranked[e['competitor']['id']] = (ranking['name'],
                                             flip(e['competitor']['name']), e['points'])
    if snapshot is None:
        raw = getattr(client, 'rankings_generated_at', None)
        snapshot = date(*(int(x) for x in raw[:10].split('-'))) if raw else date.today()

    matches = [m for m in _singles_matches() if m['date']]
    cut = snapshot.toordinal()
    matches = [m for m in matches
               if 0 < cut - date(*(int(x) for x in m['date'].split('-'))).toordinal()
                    <= window_weeks * 7]
    per = _results(matches, _shapes())

    out = {tour: {} for tour in cal_names}
    for pid, results in per.items():
        if pid not in ranked:
            continue
        tour, name, total = ranked[pid]
        if tour not in out or not total:
            continue
        # A staging still running at the snapshot has paid nobody yet.
        results = [g for g in results if g['end'].toordinal() < cut]
        counted = _counted(tour, results)
        names = cal_names[tour]
        by_ev, by_wk, by_sub = defaultdict(float), defaultdict(float), defaultdict(float)
        for g in counted:
            city = sim_name(g['comp'])
            if g['level'] == 'finals' or city in names:
                by_ev[city] += g['pts']
            elif g['level'] in BELOW_TOUR_LEVELS:
                by_sub[season_week(g['end'])] += g['pts']
            else:
                by_wk[season_week(g['end'])] += g['pts']
        attributed = sum(by_ev.values()) + sum(by_wk.values()) + sum(by_sub.values())
        # Never drop more than the player actually has: the schedule is scaled to
        # their reported total, and anything it cannot account for decays instead.
        scale = min(1.0, total / attributed) if attributed > 0 else 0.0
        # Whole points, then reconciled so the three tiers sum to the reported
        # total EXACTLY. Rounding each entry independently can push the placed
        # sum a few points past the total, and clamping `rest` at zero then left
        # the player holding points that do not exist. Three points was enough to
        # reorder sixty-one adjacent players in week 0, before anyone had played.
        ev = [[k, round(v * scale)] for k, v in sorted(by_ev.items()) if v * scale >= 1]
        wk = [[k, round(v * scale)] for k, v in sorted(by_wk.items()) if v * scale >= 1]
        sub = [[k, round(v * scale)] for k, v in sorted(by_sub.items()) if v * scale >= 1]
        placed = sum(v for _, v in ev + wk + sub)
        if placed > total:
            # Trim the overshoot off the largest entry, which is always bigger
            # than the rounding error that caused it.
            biggest = max(ev + wk + sub, key=lambda r: r[1])
            biggest[1] -= placed - total
            placed = total
        out[tour][name] = {'ev': [r for r in ev if r[1] > 0],
                           'wk': [r for r in wk if r[1] > 0],
                           'sub': [r for r in sub if r[1] > 0],
                           'rest': total - placed,
                           'scale': round(scale, 4)}
    return out
