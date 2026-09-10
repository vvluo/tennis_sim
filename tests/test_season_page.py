"""The season page must play a whole calendar and add up.

A season is ~2600 matches. The page plays only the ones involving the player you
picked point by point and settles the rest with the closed-form forecaster, so
these check both that the bookkeeping balances and that the fast path is
actually being taken -- a regression that quietly reverted to simMatch would
still produce correct standings, just slowly and with the heap full of point
records, and no other test would notice.

The driver runs the SHIPPED page's own script, so what is tested is what is
served rather than a re-implementation of it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'sportradar_cache' / '_year_tour.pkl'
DRIVER = Path(__file__).with_name('season_sim.js')
PAGE = ROOT / 'season.html'

HAVE_NODE = shutil.which('node') is not None
if not HAVE_NODE and os.environ.get('PARITY_REQUIRE_NODE'):
    raise RuntimeError('PARITY_REQUIRE_NODE is set but node is not installed')

pytestmark = [
    pytest.mark.skipif(not HAVE_NODE, reason='node is needed to run the page script'),
    pytest.mark.skipif(not PAGE.exists(), reason='run run_season.py first'),
]


@pytest.fixture(scope='module')
def season():
    proc = subprocess.run(['node', str(DRIVER)], capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)['tours']


def test_both_tours_have_a_calendar(season):
    assert set(season) == {'ATP', 'WTA'}
    for tour, v in season.items():
        assert v['simulated'] >= 45, f'{tour} only simulates {v["simulated"]} events'


def test_every_match_has_a_winner_and_a_loser(season):
    for tour, v in season.items():
        assert v['wins'] == v['losses'], (
            f'{tour}: {v["wins"]} wins against {v["losses"]} losses')
        assert v['wins'] > 1500, f'{tour}: only {v["wins"]} matches in a season'


def test_every_event_produces_exactly_one_champion(season):
    for tour, v in season.items():
        assert v['titles'] == v['champions'], (
            f'{tour}: {v["titles"]} titles awarded across {v["champions"]} events')


def test_forecaster_carries_the_season(season):
    """With nobody selected NOTHING should be played point by point.

    This is the check that the fast path is real. If runEvent ever falls back to
    simMatch for ordinary matches the standings stay correct, so only this fails.
    """
    for tour, v in season.items():
        assert v['pointByPointWithNobodySelected'] == 0, (
            f'{tour}: {v["pointByPointWithNobodySelected"]} matches were played '
            f'point by point although no player was selected')


def test_only_your_own_matches_are_played_out(season):
    for tour, v in season.items():
        you = v['you']
        assert you['matches'] == you['record'][0] + you['record'][1], (
            f'{tour}: {you["matches"]} point-by-point records for a '
            f'{you["record"][0]}-{you["record"][1]} season')


def test_a_season_is_a_plausible_number_of_events(season):
    """Entry is calibrated so a season looks like a season.

    A flat per-event rate put every player in nearly all fifty-odd events and
    140-plus matches. The bands below are deliberately wide: this sits at the
    low end of a real top-ten season (about 16 events against a real ~20), and
    the point of the test is to catch the model collapsing, not to pin a tune.
    """
    for tour, v in season.items():
        b = v['bands']
        assert 12 <= b['top10'] <= 24, (
            f'{tour}: a top-ten player enters {b["top10"]:.1f} events')
        you = v['you']
        assert 25 <= sum(you['record']) <= 95, (
            f'{tour}: playing as {you["name"]} gave {sum(you["record"])} matches')


def test_mid_ranked_players_enter_the_most_events(season, real_entries):
    """The shape of the ranking curve, which a flat entry rate cannot produce.

    The top of the game skips the small events, players just below them take
    nearly everything, and further down they stop making the draws at all. The
    peak sits in 11-30 in the real season on both tours, so that is what is
    asserted -- an earlier version compared 31-60 against the top ten directly
    and those two run close enough to swap places on a re-fit.
    """
    for tour, v in season.items():
        b = v['bands']
        peak = max(b, key=b.get)
        # The middle of the ranking plays most. WHICH middle band peaks is not
        # worth asserting: 11-30 and 31-60 run within a couple of tenths of each
        # other, and an earlier version pinned the exact one and broke on a
        # change that moved it by 0.2.
        assert peak in ('r11_30', 'r31_60'), (
            f'{tour}: entries peak at {peak}, not in the middle of the ranking '
            f'({ {k: round(x, 1) for k, x in b.items()} })')
        # Only the peak band has to clear the top ten. The other middle band can
        # sit level with it: the top eight now play the season finals as well,
        # which is a real event they enter and the bands below them do not.
        assert max(b['r11_30'], b['r31_60']) > b['top10'], (
            f'{tour}: neither middle band beats the top ten '
            f'({ {k: round(x, 1) for k, x in b.items()} })')
        assert b['r61_120'] < b['r31_60'], (
            f'{tour}: ranks 61-120 enter {b["r61_120"]:.1f}, more than the '
            f'{b["r31_60"]:.1f} of ranks 31-60')
        assert b['r121_250'] < b['r61_120'], f'{tour}: the tail does not fall away'
        # and the real season peaks there too, so this is not a model artefact
        real = real_entries[tour]
        assert real['11-30'] == max(real.values()), (
            f'{tour}: the real season no longer peaks at 11-30, so this test '
            f'is asserting the wrong shape')


def test_concurrent_events_of_one_level_get_comparable_fields(season):
    """Two 250s in the same week must not end up strong and weak.

    Allocating each draw independently, or letting a strict level precedence
    order them, gives whichever came first in the calendar the better field.
    """
    for tour, v in season.items():
        assert v['twinGap'] <= 25, (
            f'{tour}: same-level events in one week differ by {v["twinGap"]} '
            f'ranking places at the median')


def test_bigger_events_pull_higher_ranked_entries(season):
    """500s and 250s share a priority tier, so the pull is in the entry curve.

    Without this a 500 and a 250 are interchangeable, and the whole reason the
    two sit in one tier is that the difference is a matter of degree.
    """
    for tour, v in season.items():
        top500, top250 = v['entryCurve500'][0], v['entryCurve250'][0]
        assert top500 > top250 + 0.10, (
            f'{tour}: the world number one enters a 500 at {top500:.2f} and a '
            f'250 at {top250:.2f} -- not enough of a gap to matter')


def test_entry_rises_monotonically_down_the_ranking(season):
    """Better-ranked players skip the optional events; worse-ranked take them.

    This is the shape, independent of where the fitted pivots land. An earlier
    version of this test also demanded a hard floor on how often rank 60 enters
    a 250, on the theory that small draws would otherwise not fill -- they fill
    because the pool is 500 deep, and the fitted curve puts that figure near
    0.2. Whether draws actually fill is checked directly instead.
    """
    for tour, v in season.items():
        for level in ('250', '500'):
            curve = v['entryCurve' + level]
            assert all(a <= b + 1e-9 for a, b in zip(curve, curve[1:])), (
                f'{tour} {level}: entry chance by ranking is not monotone: {curve}')
            assert curve[-1] > curve[0], (
                f'{tour} {level}: rank 250 is no likelier to enter than rank 1')


def test_players_take_weeks_off_but_not_through_a_major(season):
    for tour, v in season.items():
        assert v['rested'] > 100, f'{tour}: only {v["rested"]} weeks off in a season'
        assert v['restSmallWeek'] > v['restMajorWeek'] * 5, (
            f'{tour}: resting is {v["restSmallWeek"]:.3f} in a small week against '
            f'{v["restMajorWeek"]:.3f} in a major week -- majors are not special enough')


def test_wear_produces_some_injuries(season):
    for tour, v in season.items():
        assert 5 <= v['injuries'] <= 120, (
            f'{tour}: {v["injuries"]} injuries in a season')


def test_no_draw_has_to_be_padded_out(season):
    """A field that cannot fill is filled from the bottom of the ranking.

    That path exists so a thin week cannot break the draw, but it should not be
    load-bearing: if events are routinely short, the entry curve is wrong.
    """
    for tour, v in season.items():
        assert v['thin'] == 0, (
            f'{tour}: {v["thin"]} events could not fill and were padded')


def test_selected_player_enters_every_mandatory_event(season):
    """Majors and 1000s are close to compulsory, so you are always in them."""
    for tour, v in season.items():
        mandatory = sum(1 for lv in v['levels'] if lv == 'Grand Slam' or lv.endswith('1000'))
        assert v['you']['entered'] >= mandatory, (
            f'{tour}: entered {v["you"]["entered"]} events but {mandatory} are mandatory')


def test_points_tables_cover_every_level_played(season):
    for tour, v in season.items():
        # finals events are round robin and skipped, so they need no table
        need = {lv for lv in v['levels'] if 'Finals' not in lv}
        assert need <= set(v['pointsTables']), (
            f'{tour}: no ranking points for {sorted(need - set(v["pointsTables"]))}')


def test_page_has_no_unsubstituted_markers():
    text = PAGE.read_text()
    for marker in ('__THEME__', '__ENGINE__', '__FORECAST__', '__DATA__'):
        assert marker not in text, f'{marker} survived into the built page'
    assert 'simulateTournament' in text, 'the engine was not inlined'
    assert 'quickMatch' in text, 'the forecaster was not inlined'
    assert '--ground' in text, 'the shared theme was not inlined'


def test_nobody_plays_two_tournaments_at_once(season):
    """Entry has to respect the calendar, not just a per-event dropout roll.

    Draws were built independently, so the same player could be accepted into
    two events running the same week -- Basel and Vienna, Cluj-Napoca and
    Ostrava. A commitment ledger now holds a player until their current event is
    nearly over. The unscheduled count is measured in the same run so this
    cannot pass by the clash detector silently breaking.
    """
    for tour, v in season.items():
        assert v['clashesWithoutLedger'] > 20, (
            f'{tour}: the detector found only {v["clashesWithoutLedger"]} clashes '
            f'without the ledger, so it is not actually detecting them')
        assert v['clashes'] == 0, (
            f'{tour}: {v["clashes"]} of {v["entries"]} entries put a player in two '
            f'overlapping tournaments')


# The bands the entry curve is fitted against, and how far each may drift.
BANDS = [(0, 10, 'top 10'), (10, 30, '11-30'), (30, 60, '31-60'),
         (60, 120, '61-120'), (120, 250, '121-250')]
BAND_TOLERANCE = 3.0


@pytest.fixture(scope='module')
def real_entries():
    """Events entered per player last season, counted from the cache itself.

    This is the target the entry curve was fitted to, recomputed here rather
    than pasted in, so it moves when the data does. Same event set as the
    simulator: 250 and above, main draw only, both sides of every match.
    """
    if not CACHE.exists():
        pytest.skip('cached season not present')
    import pickle
    from run_tournament import candidates, rankings

    levels = {'ATP': {'grand_slam', 'atp_1000', 'atp_500', 'atp_250'},
              'WTA': {'grand_slam', 'wta_1000', 'wta_500', 'wta_250'}}
    gender = {'ATP': 'men', 'WTA': 'women'}
    df = pickle.load(CACHE.open('rb'))
    df = df[df['set'] == 'Total'].drop_duplicates('match_id')
    ranks = rankings()

    out = {}
    for tour in ('ATP', 'WTA'):
        order = [p['name'] for p in candidates(tour, ranks)]
        d = df[(df['gender'] == gender[tour]) & df['level'].isin(levels[tour])]
        d = d[~d['round'].astype(str).str.startswith('qualification')]
        played = {}
        for row in d.itertuples():
            for who in (row.player, row.opponent):
                played.setdefault(who, set()).add(row.competition)
        counts = [len(played.get(n, ())) for n in order]
        out[tour] = {name: (sum(counts[a:b]) / len(counts[a:b]) if counts[a:b] else 0)
                     for a, b, name in BANDS}
    return out


def test_participation_matches_the_target_schedule(season):
    """Entries per season for a player who stayed fit, by ranking band.

    The target is a schedule, not the cache: around twenty events for the very
    top of the game, who go deep and skip the small tournaments, and more for
    the band below them, who can enter anything their ranking reaches and want
    the points. Injured players are excluded -- the target is stated for a fit
    player and an all-players mean is dragged down by whoever spent nine weeks
    out.

    This deliberately sits ABOVE the figure counted from the cache, which is a
    lower bound rather than the truth: a player whose only match at an event is
    among the 262 missing from the feed loses that whole event from their tally
    (DATA_ISSUES.md, section 5). The bias is worst on the WTA, which carries 230
    of the 294 continuity breaks -- and that is exactly where the cache-derived
    figure sits furthest below this target. test_participation_keeps_the_real_
    seasons_shape still holds the band ORDERING to the data.
    """
    for tour, v in season.items():
        b = v['fitBands']
        assert 17.5 <= b['top10'] <= 22.0, (
            f'{tour}: a fit top-10 player enters {b["top10"]:.1f} events, not about 20')
        for band in ('r11_30', 'r31_60'):
            assert b[band] > b['top10'], (
                f'{tour}: {band} enters {b[band]:.1f}, no more than the top ten\'s '
                f'{b["top10"]:.1f} -- the top of the game should play LESS, not the same')
            assert 21.0 <= b[band] <= 27.0, (
                f'{tour}: {band} enters {b[band]:.1f} events; a fit player who '
                f'qualifies by ranking anywhere should play in the mid twenties')
        # ...and the ceiling is real: 34 weeks carry an event, and a major eats two
        assert b['r31_60'] < 30, f'{tour}: {b["r31_60"]:.1f} entries is past the calendar'


def test_participation_keeps_the_real_seasons_shape(season, real_entries):
    """The LEVEL is set by the target above; the SHAPE still comes from the data.

    The cache undercounts entries, so it cannot say how many events a band
    plays -- but it is perfectly good for the shape: the top of the game plays
    less than the band below it, and participation falls away down the ranking.

    Which of the two middle bands peaks is deliberately NOT asserted. They run
    close together, the real season and the simulation disagree about the order
    by under two events, and an earlier version of this suite pinned the exact
    band and broke on a change that moved it by 0.2.
    """
    for tour, v in season.items():
        real, got = real_entries[tour], v['bands']
        middle = max(got['r11_30'], got['r31_60'])
        assert middle > got['top10'], (
            f'{tour}: the top ten enter {got["top10"]:.1f}, as many as the bands '
            f'below them -- the real season has them clearly lower')
        assert got['r61_120'] < middle, f'{tour}: 61-120 does not fall below the middle'
        assert got['r121_250'] < got['r61_120'], f'{tour}: the tail does not fall away'
        # the data has to agree that this is the shape, or the test is asserting
        # something the real season never showed
        assert max(real['11-30'], real['31-60']) > real['top 10'] > real['121-250'], (
            f'{tour}: the real season no longer has this shape ({real})')


def test_the_real_target_is_actually_loaded(real_entries):
    """Guards the test above: an empty target would let anything pass."""
    for tour, bands in real_entries.items():
        assert bands['top 10'] > 5, f'{tour}: real top-10 entries came out as {bands["top 10"]}'
        assert bands['11-30'] > bands['121-250'], f'{tour}: real bands look wrong'


@pytest.fixture(scope='module')
def calendars():
    """The calendars as the built page actually receives them."""
    import re
    m = re.search(r'const DATA = (\{.*?\});', PAGE.read_text(), re.S)
    assert m, 'DATA was not inlined into the page'
    return json.loads(m.group(1))['calendars']


def test_season_runs_january_to_december(calendars):
    """Order by position in the CALENDAR year, not by the cache's raw dates.

    The cache is a rolling August-to-August window, so ordering on its raw
    dates started the season in late August and ran into the next August.
    """
    for tour, cal in calendars.items():
        first, last = cal[0], cal[-1]
        assert first['start'][5:7] == '01', (
            f'{tour} opens with {first["name"]} on {first["start"][5:]}, not in January')
        assert 'Finals' in last['level'], (
            f'{tour} ends with {last["name"]} ({last["level"]})')


def test_season_finals_play_last(calendars):
    for tour, cal in calendars.items():
        finals = [i for i, e in enumerate(cal) if 'Finals' in e['level']]
        assert finals, f'{tour} has no season finals'
        assert finals == list(range(len(cal) - len(finals), len(cal))), (
            f'{tour}: finals sit at {finals} of {len(cal) - 1}, not at the end')


def test_season_days_advance(calendars):
    """sday must not go backwards, or the commitment ledger and the load decay
    -- both differences between day numbers -- unwind instead of advancing."""
    for tour, cal in calendars.items():
        body = [e for e in cal if 'Finals' not in e['level']]
        for a, b in zip(body, body[1:]):
            assert a['sday'] <= b['sday'], (
                f'{tour}: {b["name"]} (day {b["sday"]}) follows '
                f'{a["name"]} (day {a["sday"]})')
        for e in cal:
            assert e['sday_end'] >= e['sday'], (
                f'{tour}: {e["name"]} ends before it starts in season days -- '
                f'it spans the year boundary')
            assert e['sweek'] == e['sday'] // 7


def test_concurrent_events_share_a_season_week(calendars):
    """Whatever else changes, events starting the same day must allocate together."""
    for tour, cal in calendars.items():
        by_day = {}
        for e in cal:
            by_day.setdefault(e['start'], []).append(e)
        for day, evs in by_day.items():
            weeks = {e['sweek'] for e in evs}
            assert len(weeks) == 1, (
                f'{tour}: {[e["name"] for e in evs]} all start {day} '
                f'but land in weeks {weeks}')


def test_finals_are_forced_last_even_when_dated_early():
    """Directly exercises the ordering, which the calendars cannot.

    As they stand the finals are already the latest events, so reordering by
    date alone gives the same answer and the calendar-level tests above cannot
    tell the two apart. This gives the ordering an event the data never does.
    """
    from run_season import order_season
    rows = [
        {'name': 'Tour Finals', 'level': 'ATP Finals', 'sday': 40},
        {'name': 'Rome', 'level': 'ATP 1000', 'sday': 120},
        {'name': 'Brisbane', 'level': 'ATP 250', 'sday': 3},
        {'name': 'Next Gen', 'level': 'Next Gen Finals', 'sday': 10},
    ]
    # The finals go last, and keep their own order by date between them --
    # which is what puts the Tour Finals in November ahead of Next Gen in
    # December on the real calendar.
    assert [e['name'] for e in order_season(rows)] == \
        ['Brisbane', 'Rome', 'Next Gen', 'Tour Finals'], \
        'a finals event dated mid-season was not moved to the end'


WINDOW_MESSAGE = 'the cached season opens after this tournament began'


def test_window_edge_is_named_before_the_symptom():
    """A tournament clipped by the window edge must not be blamed on the feed.

    The cache is a rolling twelve months, so an event already under way when it
    opens keeps only its closing rounds. That is indistinguishable from a feed
    gap by shape alone -- worse, the draw arithmetic can appear to SUCCEED on
    the surviving rounds, because late rounds are self-consistent, which is how
    Cleveland came out as a 14 draw. This is exercised directly because the
    calendars no longer contain such an event to test against.
    """
    from build_calendar import _classify, _clipped_by_window

    clipped = {'draw': '14', 'bracket': '16', 'draw_complete': 'True'}
    assert _classify(clipped) is not None, 'a 14 draw should not be simulatable'
    assert _clipped_by_window(20250820, 20250820), 'same day as the window opens'
    assert _clipped_by_window(20250821, 20250820), 'one day after'
    assert not _clipped_by_window(20260727, 20250820), 'eleven months later'

    assert _classify({'draw': '32', 'bracket': '32', 'draw_complete': 'True'}) is None
    assert _classify({'draw': '33', 'bracket': '32', 'draw_complete': 'True'}) is not None
    assert _classify({'draw': '', 'bracket': '', 'draw_complete': 'False'}) is not None
    assert _classify(None) is not None


def test_published_draw_sizes_are_applied():
    """Draw sizes taken from the tour calendars, for shapes the feed cannot settle.

    Washington is the one that matters: its 31 cached main-draw matches are
    exactly a complete 32 draw, but the derivation counted a cancelled match and
    produced 33 -- a draw no bracket can hold.
    """
    from build_calendar import _override, DRAW_OVERRIDES
    assert DRAW_OVERRIDES, 'no published draw sizes are recorded'
    row = _override('ATP', 'Washington', {'draw': '33', 'bracket': '32', 'byes': '-1'})
    assert row['draw'] == '32' and row['bracket'] == '32' and row['byes'] == '0'
    row = _override('ATP', 'Winston Salem', None)
    assert row['draw'] == '48' and row['bracket'] == '64' and row['byes'] == '16'
    untouched = {'draw': '28', 'bracket': '32', 'byes': '4'}
    assert _override('ATP', 'Rome', untouched) == untouched


def test_discontinued_events_are_not_played(calendars):
    """The rolling window can hold both a dropped event and its replacement.

    Cleveland ran in August 2025 and was cancelled; the Memphis Classic took
    that slot for 2026. Both fall inside the cached twelve months, so keeping
    Cleveland would play the same week of the calendar twice.
    """
    from build_calendar import DISCONTINUED
    assert DISCONTINUED, 'nothing is recorded as discontinued'
    for tour, name in DISCONTINUED:
        assert not any(e['name'] == name for e in calendars[tour]), (
            f'{tour} {name} is discontinued but still on the calendar')
    # and the replacement really is there, or the slot has silently vanished
    assert any(e['name'] == 'Memphis' for e in calendars['WTA']), \
        'Cleveland was dropped but its replacement is missing'


def test_next_gen_is_the_only_event_left_unplayed(calendars):
    """With the published draw sizes in and the finals implemented, only one left.

    The round robins used to be skipped wholesale. The tour finals are played
    now, so the only event still carried unsimulated is Next Gen, whose field is
    an age cut-off the source data cannot supply.
    """
    for tour, cal in calendars.items():
        odd = [e for e in cal if e.get('skip') and e['level'] != 'Next Gen Finals']
        assert not odd, (
            f'{tour}: {[(e["name"], e["skip"]) for e in odd]}')


def test_allocating_a_week_with_nothing_to_play_is_safe(season):
    """Calling the allocator for a skipped event must not throw.

    The run loop only allocates inside `if(!ev.skip)`, so this never fires
    today -- but a round-robin final whose week holds no other event made
    ensureFields hand allocateWeek an empty list, and it crashed reading
    evs[0]. The guard is checked here because the live path cannot reach it.
    """
    assert season['ATP']['emptyWeekOk'], 'allocateWeek([]) threw'
    assert season['ATP']['skippedEnsureOk'], 'ensureFields on a skipped event threw'


def test_entry_curve_is_a_gradient_not_a_step(season):
    """Every band of the ranking must have a real chance at every level.

    Fitting width freely drove the WTA 250 curve to a step: the world number
    one entered a 250 twice in a thousand, anyone past 120 entered nearly all
    of them. The band totals fitted well and the individual seasons did not --
    a top player reached October with no tournament left to enter, because the
    late WTA calendar is almost entirely 250s. Aggregate accuracy cannot see
    that, so the shape of the curve is asserted directly.

    entryCurve250 is sampled at ranks 1, 30, 60, 120 and 250.
    """
    for tour, v in season.items():
        curve = v['entryCurve250']
        assert curve[0] >= 0.03, (
            f'{tour}: the world number one enters a 250 with probability '
            f'{curve[0]:.3f} -- that is a step, not a curve')
        assert all(a < b for a, b in zip(curve, curve[1:])), (
            f'{tour}: the 250 curve is not monotone in ranking: '
            f'{[round(x, 3) for x in curve]}')
        assert curve[2] / curve[0] < 12, (
            f'{tour}: rank 60 is {curve[2] / curve[0]:.0f}x likelier than rank 1 '
            f'to enter a 250; the transition is too sharp')


def test_width_floor_does_not_disturb_the_fitted_curves(season):
    """The floor is a guard, not a correction.

    A flat minimum width was wrong: ATP 500s pivot at rank 1 with a width of 2,
    which is not a step across the ranking -- it says nearly everyone plays them
    -- and widening it cost ranks 11-30 four events a season. The floor is a
    fraction of the pivot instead, and must leave every fitted curve untouched.
    """
    for tour, v in season.items():
        top500, top250 = v['entryCurve500'][0], v['entryCurve250'][0]
        assert top500 > top250, (
            f'{tour}: a 500 pulls the top of the ranking no harder than a 250')
        assert v['entryCurve500'][3] > 0.9, (
            f'{tour}: a player ranked 120 enters a 500 only '
            f'{v["entryCurve500"][3]:.2f} of the time; the 500 curve was widened')


def test_points_depend_on_draw_size(season):
    """A 56-draw Masters pays its opening round 10; the 96-draw row pays 30 there.

    This checks what is actually CREDITED, not the shape of the table. An earlier
    version only asserted that the source held one row per draw family, and a
    mutation that ignored the lookup and always took the first row passed it --
    silently paying every 56-draw Masters at 96-draw rates.
    """
    r = season['ATP'].get('openingRound') or {}
    a56, a96 = r.get('atp56'), r.get('atp96')
    assert a56 and a96, 'the opening-round probe did not run'
    assert a56['draw'] == 56 and a56['firstRound'] == 'R64', a56
    assert a56['points'] == 10, (
        f"{a56['event']} is a {a56['draw']} draw: its opening round ({a56['firstRound']}) "
        f"should pay 10, not {a56['points']} -- the 96-draw row is being used")
    assert a96['draw'] == 96 and a96['points'] == 10, a96


def test_points_are_keyed_by_round_not_by_a_progress_label():
    """Byes fall out for free this way.

    A seed with a first-round bye at a 28-draw 250 who loses next time out is
    beaten in the round of 32 -- that event's opening round -- and takes its 13
    points. Counting "rounds survived" instead would pay them as though they had
    won a match first.
    """
    page = PAGE.read_text()
    assert 'table[name]' in page, 'points are still looked up by an exit label'
    assert 'table[labels[name]]' not in page, 'the old exit-label lookup survives'


# Main-draw qualifier counts as the tours publish them.
QUALIFIERS_BY_DRAW = {
    'ATP': {128: 16, 96: 12, 56: 7, 48: 6, 32: 4, 28: 4},
    'WTA': {128: 16, 96: 12, 56: 8, 48: 6},        # small draws vary by event
}
# The WTA 500s, confirmed in both directions: these seven take six, the other
# nine take four.
WTA_500_SIX = {'Brisbane', 'Adelaide 1', 'Charleston', 'Strasbourg',
               'London', 'Berlin', 'Merida'}


def test_qualifier_counts_match_the_published_breakdowns(season):
    """One in eight reproduces every ATP figure; the WTA departs from it twice.

    A 56-draw WTA 1000 sends EIGHT through where the flat rule gives seven, and
    several small-draw events run a 24-player qualifying rather than 16, which
    is a property of the event and cannot be derived from its size or level.
    """
    bad = []
    for tour, events in ((t, season[t]['qualifierCounts']) for t in season):
        for name, e in events.items():
            want = QUALIFIERS_BY_DRAW[tour].get(e['draw'])
            if want is None:
                continue                      # small WTA draws, checked below
            if e['q'] != want:
                bad.append(f"{tour} {name} ({e['draw']} draw): {e['q']}, expected {want}")
    assert not bad, 'qualifier counts differ from the published tables:\n  ' + '\n  '.join(bad)


def test_wta_500_qualifiers_are_fully_accounted_for(season):
    """All sixteen, from both published lists -- nothing left to assumption."""
    events = {n: e for n, e in season['WTA']['qualifierCounts'].items()
              if e['level'] == 'WTA 500'}
    assert len(events) == 16, f'expected 16 WTA 500s, found {len(events)}'
    for name, e in events.items():
        want = 6 if name in WTA_500_SIX else 4
        assert e['q'] == want, (
            f'WTA {name} ({e["draw"]} draw): {e["q"]} qualifiers, published says {want}')
    assert set(events) & WTA_500_SIX == WTA_500_SIX, (
        f'not on the calendar: {WTA_500_SIX - set(events)}')


def test_a_56_draw_wta_1000_differs_from_the_atp(season):
    """The single clearest departure from one-in-eight, worth its own check."""
    wta = [e for e in season['WTA']['qualifierCounts'].values()
           if e['draw'] == 56 and e['level'] == 'WTA 1000']
    atp = [e for e in season['ATP']['qualifierCounts'].values()
           if e['draw'] == 56 and e['level'] == 'ATP 1000']
    assert wta and atp, 'no 56-draw 1000s on one of the calendars'
    assert all(e['q'] == 8 for e in wta), f'WTA 56-draw should send 8: {wta}'
    assert all(e['q'] == 7 for e in atp), f'ATP 56-draw should send 7: {atp}'


def test_draws_are_built_the_way_a_grand_slam_is(season):
    """Seeds spread geometrically, byes to the top seeds, the rest shuffled.

    The season page calls the engine's own buildDraw, so this is the same code
    the grand-slam page runs -- but nothing checked that the season path reached
    it with a well-formed field, and a draw built any other way would still
    simulate happily.
    """
    draws = season['ATP'].get('draws') or []
    assert draws, 'the draw-structure probe did not run'
    for d in draws:
        t_ = d['trials']
        assert d['halves'] == t_, (
            f"{d['name']}: seeds 1 and 2 shared a half in {t_ - d['halves']} of {t_} draws")
        assert d['quarters'] == t_, (
            f"{d['name']}: seeds 1-4 were not in four separate quarters in "
            f"{t_ - d['quarters']} of {t_} draws")
        if d['byes']:
            assert d['byesToSeeds'] == t_, (
                f"{d['name']}: byes did not go to the top seeds in "
                f"{t_ - d['byesToSeeds']} of {t_} draws")


def test_qualifiers_come_from_below_the_cutoff(season):
    """Qualifying is stood in for by a heavy dropout, as on the grand-slam page.

    Without it the qualifiers would simply be the next names on the ranking --
    barely distinguishable from the last direct entrants, which is not what
    coming through three rounds of qualifying looks like.
    """
    assert season['ATP']['qualifyingDropout'] == 0.6, (
        f"qualifying dropout is {season['ATP']['qualifyingDropout']}, not the "
        f"0.60 the engine's buildField uses")
    for d in season['ATP'].get('draws') or []:
        direct, qual = d['medianDirectRank'], d['medianQualifierRank']
        assert qual is not None and direct is not None, d['name']
        assert qual > direct * 1.4, (
            f"{d['name']}: qualifiers median rank {qual} against direct {direct} -- "
            f"they are not being drawn from below the cutoff")
        # and SCATTERED, not simply the next names down. Without the dropout the
        # qualifiers arrive as a contiguous block about as wide as their own
        # number; the dropout spreads them over two to three times that.
        assert d['qualifierSpread'] > 1.8, (
            f"{d['name']}: qualifier ranks span only {d['qualifierSpread']:.1f}x their "
            f"own count -- they are the next names below the cutoff, not a field "
            f"that came through qualifying")


def test_home_players_are_over_represented_below_1000_level(season):
    """A home crowd pulls players in, for PARTICIPATION only.

    Nothing about a home player's strength changes -- the boost lives entirely
    in entryChance. It is measured as the home country's share of the field
    against its share of the pool, so a country with many players is not
    credited simply for being large.
    """
    for tour, v in season.items():
        h = v['home']
        assert h['belowCount'] >= 15, f'{tour}: only {h["belowCount"]} events measured'
        assert h['below1000'] > 1.25, (
            f'{tour}: home players are only {h["below1000"]:.2f}x their pool share at '
            f'500s and 250s -- the boost is not noticeable')


def test_home_advantage_does_not_reach_the_compulsory_levels(season):
    """Majors and 1000s are mandatory or near enough, so the boost is not applied.

    This has to be checked on entryChance itself. In a field the guard is nearly
    invisible: those levels already sit at ~0.96, and multiplying odds by four
    moves that by a single point, so a draw looks the same either way.
    """
    for tour, v in season.items():
        curve = v['home']['curve']
        for level in ('Grand Slam', f'{tour} 1000'):
            if level not in curve:
                continue
            c = curve[level]
            assert c['home'] == c['away'], (
                f'{tour} {level}: home {c["home"]:.3f} against away {c["away"]:.3f} -- '
                f'the boost is reaching a compulsory level')
        for level in (f'{tour} 250',):
            c = curve[level]
            assert c['home'] > c['away'] + 0.10, (
                f'{tour} {level}: home {c["home"]:.3f} against away {c["away"]:.3f} -- '
                f'the boost is not reaching the optional levels')


def test_neutral_players_are_never_at_home(season):
    """They carry no country, and no event is held where they are from."""
    for tour, v in season.items():
        assert v['home']['neutralAtHome'] == 0, (
            f'{tour}: a neutral-designated player was treated as playing at home')


def test_picked_player_is_not_forced_into_draws_their_rank_cannot_reach(season):
    """Picking a player must not fabricate an acceptance list place for them.

    Majors and 1000s are near-compulsory for players who are actually in the
    draw, so the allocator seeds the picked player into one directly. That
    shortcut used to ignore rank entirely, which put a world number 420 into
    all four grand slams and every Masters, where they were promptly destroyed.
    The guarantee now stops at the direct cut-off.
    """
    for tour, v in season.items():
        bands = {m['rank']: m for m in v['mandatory']}
        deep = [m for r, m in bands.items() if r >= 300]
        assert deep, f'{tour}: no deep-ranked band measured'
        for m in deep:
            assert m['slams'] == 0, (
                f'{tour}: #{m["rank"]} entered {m["slams"]:.1f} grand slams a season')
            assert m['masters'] == 0, (
                f'{tour}: #{m["rank"]} entered {m["masters"]:.1f} Masters a season')


def test_picked_top_player_still_gets_the_mandatory_events(season):
    """The rank guard must not cost the players it was never aimed at."""
    for tour, v in season.items():
        bands = {m['rank']: m for m in v['mandatory']}
        top = [m for r, m in bands.items() if r <= 40]
        assert len(top) >= 2, f'{tour}: no top band measured'
        for m in top:
            assert m['slams'] >= 3.5, (
                f'{tour}: #{m["rank"]} only played {m["slams"]:.1f} slams a season')
            assert m['masters'] >= 6, (
                f'{tour}: #{m["rank"]} only played {m["masters"]:.1f} Masters a season')


def test_your_scorelines_read_from_your_players_side(season):
    """"lost to X" must not be followed by a scoreline that says you won.

    setScoreStrings orients from the match winner, which is what the neutral
    "winner d. loser" panel on the grand-slam page wants. The season page's
    "your matches" table is written from the picked player's side, so it has to
    pass that player's own draw index instead. Verified against each set's
    recorded winner, which is a draw-side index and so carries no orientation.
    """
    for tour, v in season.items():
        o = v['scoreOrientation']
        assert o['checked'] >= 40, f'{tour}: only {o["checked"]} sets measured'
        assert o['losses'] >= 3, (
            f'{tour}: only {o["losses"]} losses seen -- a winner-oriented score '
            f'is indistinguishable on wins, so the probe proves nothing')
        assert o['wrong'] == 0, (
            f'{tour}: {o["wrong"]} of {o["checked"]} set scores are written from '
            f'the wrong side')


def test_mandatory_draws_never_reach_past_their_acceptance_list(season):
    """A slam or Masters that cannot fill takes a SHORT field, not a deep one.

    In an ordinary week this ceiling is never loaded: direct entry and qualifying
    exhaust themselves around the world 150-260, far above the cut, so measuring a
    normal season cannot tell an enforced rule from a coincidence. The probe
    depletes the week instead -- everyone inside the top 250 committed elsewhere --
    which is the case that used to put a world 403 into a grand slam and a 370
    into a Masters. The right answer is a 22-player field, not a full one.
    """
    for tour, v in season.items():
        for e in v['acceptanceCeiling']:
            assert e['size'] < e['draw'], (
                f'{tour} {e["level"]}: filled all {e["draw"]} places from a pool '
                f'whose acceptance list was exhausted -- the field was topped up '
                f'from the bottom of the rankings')
            assert e['worst'] <= 280, (
                f'{tour} {e["level"]}: admitted world #{e["worst"]}, who is not on '
                f'any qualifying entry list for this event')


# ---- the tour finals -----------------------------------------------------

def test_finals_qualification_is_the_simulated_season_not_the_seed_ranking(season):
    """The eight are the season's own points table, not the ratings' rankings.

    The seed rankings are a year of results that never happened in this run, so
    reading the field off them would send the same eight players every time
    however the season went. The check is that the field IS the points order,
    and separately that it demonstrably diverges from the seed order.
    """
    for tour, v in season.items():
        divergence = 0
        for f in v['finals']:
            pts = [p['points'] for p in f['field']]
            assert pts == sorted(pts, reverse=True), (
                f'{tour}: the finals field is not in season-points order: {pts}')
            seeds = [p['rank'] for p in f['field']]
            if seeds != sorted(seeds):
                divergence += 1
        assert divergence >= len(v['finals']) // 2, (
            f'{tour}: the qualifiers matched seed-ranking order in all but '
            f'{divergence} seasons -- the season points may not be driving it')


def test_finals_group_tables_count_only_the_round_robin(season):
    """Three matches each, and no knockout results leaking into the group.

    play() writes into one tally per player and keeps writing through the semis
    and the final, so a group table built from live references showed the
    champion 5-0 in a group of three matches.
    """
    for tour, v in season.items():
        for f in v['finals']:
            for g in f['groups']:
                assert len(g['rows']) == 4, f'{tour} {g["label"]}: {len(g["rows"])} players'
                for r in g['rows']:
                    assert r['mw'] + r['ml'] == 3, (
                        f'{tour} {g["label"]}: {r["name"]} played '
                        f'{r["mw"] + r["ml"]} group matches, not 3')
                won = sum(r['mw'] for r in g['rows'])
                assert won == 6, f'{tour} {g["label"]}: {won} wins across 6 matches'


def test_finals_groups_are_drawn_in_seeded_pairs(season):
    """One of 1/2, one of 3/4, one of 5/6, one of 7/8 in each group."""
    for tour, v in season.items():
        for f in v['finals']:
            for g in f['groups']:
                pairs = sorted((r['seed'] - 1) // 2 for r in g['rows'])
                assert pairs == [0, 1, 2, 3], (
                    f'{tour} {g["label"]}: seeds {sorted(r["seed"] for r in g["rows"])} '
                    f'are not one from each seeded pair')


def test_finals_group_order_follows_the_stated_tiebreakers(season):
    """Matches won, then set win percentage, then game win percentage."""
    def key(r):
        sets = r['sw'] / (r['sw'] + r['sl']) if r['sw'] + r['sl'] else 0
        games = r['gw'] / (r['gw'] + r['gl']) if r['gw'] + r['gl'] else 0
        return (-r['mw'], -sets, -games)

    for tour, v in season.items():
        for f in v['finals']:
            for g in f['groups']:
                got = [key(r) for r in g['rows']]
                assert got == sorted(got), (
                    f'{tour} {g["label"]}: ordered '
                    f'{[(r["name"], r["mw"], r["sw"], r["sl"]) for r in g["rows"]]}')


def test_finals_semifinals_cross_the_groups(season):
    """A1 meets B2 and A2 meets B1, so the group winners can only meet in the final."""
    for tour, v in season.items():
        for f in v['finals']:
            a = [r['name'] for r in f['groups'][0]['rows']][:2]
            b = [r['name'] for r in f['groups'][1]['rows']][:2]
            semis = [{m['winner'], m['loser']} for m in f['closing'] if m['round'] == 'SF']
            assert len(semis) == 2, f'{tour}: {len(semis)} semi-finals'
            assert {a[0], b[1]} in semis, f'{tour}: {a[0]} (A1) did not meet {b[1]} (B2)'
            assert {a[1], b[0]} in semis, f'{tour}: {a[1]} (A2) did not meet {b[0]} (B1)'
            finals = [m for m in f['closing'] if m['round'] == 'F']
            assert len(finals) == 1 and finals[0]['winner'] == f['champion']


def test_finals_points_are_paid_per_win(season):
    """200 a round-robin win, 400 the semi, 500 the final -- 1,500 for all five.

    Nothing is paid for turning up, so a player who loses all three group
    matches leaves with nothing.
    """
    for tour, v in season.items():
        legal = {0, 200, 400, 600, 800, 1000, 1200, 1400, 1500,
                 900, 1100, 1300}       # every reachable total
        seen_max = 0
        for f in v['finals']:
            by_name = {p['name']: g for p, g in zip(f['field'], f['gained'])}
            rr = {r['name']: r['mw'] for g in f['groups'] for r in g['rows']}
            sf = {m['winner'] for m in f['closing'] if m['round'] == 'SF'}
            fw = {m['winner'] for m in f['closing'] if m['round'] == 'F'}
            for name, gained in by_name.items():
                want = (200 * rr[name] + 400 * (name in sf) + 500 * (name in fw))
                assert gained == want, (
                    f'{tour}: {name} took {gained} for {rr[name]} group wins'
                    f'{", a semi" if name in sf else ""}'
                    f'{" and the final" if name in fw else ""} -- expected {want}')
                assert gained in legal, f'{tour}: {name} took an impossible {gained}'
                seen_max = max(seen_max, gained)
        assert seen_max <= 1500, f'{tour}: {seen_max} exceeds the 1,500 maximum'


def test_finals_are_simulated_and_next_gen_is_not(season):
    """Next Gen is left out for want of ages, and says so rather than "round robin"."""
    for tour, v in season.items():
        rr = [e for e in v['calendar'] if e['format'] == 'rr']
        assert len(rr) == 1, f'{tour}: {len(rr)} round-robin events'
        assert rr[0]['skip'] is None, f'{tour}: the finals are still skipped'
        assert rr[0]['level'].endswith('Finals')
        for e in v['calendar']:
            if e['level'] == 'Next Gen Finals':
                assert e['skip'] and 'age' in e['skip'] and 'dates of birth' in e['skip'], (
                    f'Next Gen is skipped as {e["skip"]!r}, which no longer says why')


def test_an_injured_qualifier_is_replaced_by_the_next_player_down(season):
    """Injury is the ONLY way to lose a finals place, and the place is refilled.

    Driven from a made-up standings table rather than a played season: an injury
    landing on one of the eight in that particular week is rare, so a handful of
    seasons would usually show none and the test would never touch the path.
    """
    for tour, v in season.items():
        f = v['finalsInjury']
        assert f, f'{tour}: no round-robin event to test'
        assert len(f['healthy']) == 8, f'{tour}: {len(f["healthy"])} qualified when all fit'
        assert f['healthy'] == f['standings'][:8], (
            f'{tour}: a fully fit field is not simply the top eight')
        assert len(f['after']) == 8, (
            f'{tour}: {len(f["after"])} qualified after two withdrew -- the places '
            f'were not refilled')
        for n in f['hurt']:
            assert n not in f['after'], f'{tour}: injured {n} still played'
        # the replacements are the next two down, in order, and nobody else moved
        assert f['after'] == [n for n in f['standings'] if n not in f['hurt']][:8], (
            f'{tour}: replacements were not taken in standings order: {f["after"]}')


# ---- what counts towards a ranking ---------------------------------------

ATP_OPTIONAL_1000 = {'Monte Carlo'}
WTA_COMPULSORY_1000 = {'Indian Wells', 'Miami', 'Madrid', 'Rome', 'Toronto', 'Beijing'}
# Written out here rather than read off the page. Taking them from the page made
# every one of these tests agree with whatever the page happened to do: widening
# the optional slots to ten, or letting every non-combined 1000 count in full,
# both moved the page and the test together and nothing failed.
OTHER_SLOTS = 7          # ATP best 19 = 12 compulsory + 7; WTA best 18 = 11 + 7
WTA_FLOATING_SLOTS = 1   # one non-combined 1000 counts in full


def _recompute(tour, player, other_slots=OTHER_SLOTS, floating_slots=WTA_FLOATING_SLOTS):
    """The ranking from the raw results, worked out independently of the page."""
    mand = [g['pts'] for g in player['results'] if g['slot'] in ('mand', 'finals')]
    floats = sorted((g['pts'] for g in player['results'] if g['slot'] == 'float'),
                    reverse=True)
    other = [g['pts'] for g in player['results'] if g['slot'] == 'other']
    total = sum(mand)
    if tour == 'ATP':
        other += floats
    else:
        total += sum(floats[:floating_slots])
        other += floats[floating_slots:]
    return total + sum(sorted(other, reverse=True)[:other_slots])


def test_ranking_points_are_the_counting_slots_not_the_season_total(season):
    """Best 19 (ATP) / best 18 (WTA), plus the finals -- not a running sum."""
    for tour, v in season.items():
        assert v['slots'] == {'other': OTHER_SLOTS, 'wtaFloating': WTA_FLOATING_SLOTS}, (
            f'{tour}: the page counts {v["slots"]}, not the documented '
            f'{OTHER_SLOTS} optional slots and {WTA_FLOATING_SLOTS} floating 1000')
        for p in v['ranking']:
            want = _recompute(tour, p)
            assert p['points'] == want, (
                f'{tour}: {p["name"]} shows {p["points"]} but the slots come to {want}')


def test_the_best_of_cap_actually_drops_results(season):
    """A season busier than the slots must lose its weakest optional results.

    Without this the test above passes on any player who never filled seven
    optional slots, and the cap would be untested.
    """
    for tour, v in season.items():
        capped = [p for p in v['ranking']
                  if sum(g['pts'] for g in p['results']) > p['points']]
        assert len(capped) >= 5, (
            f'{tour}: only {len(capped)} of {len(v["ranking"])} players had any '
            f'result dropped -- the cap is not biting')
        for p in capped:
            # The optional pool is not just the 'other' results: on the WTA every
            # non-combined 1000 past the first floating slot spills into it too.
            floats = len([g for g in p['results'] if g['slot'] == 'float'])
            spill = floats if tour == 'ATP' else max(0, floats - WTA_FLOATING_SLOTS)
            optional = len([g for g in p['results'] if g['slot'] == 'other']) + spill
            assert optional > OTHER_SLOTS, (
                f'{tour}: {p["name"]} lost points with only {optional} optional '
                f'results, which all fit in {OTHER_SLOTS} slots')


def test_a_skipped_compulsory_event_cannot_be_replaced(season):
    """The whole point of the split: a missing major is a hole, not a swap.

    Checked by adding a good optional result to a player who skipped one and
    confirming the total moves by the best-of margin, never by the missing
    event's worth.
    """
    for tour, v in season.items():
        cap = 12 if tour == 'ATP' else 10
        skippers = [p for p in v['ranking']
                    if len([g for g in p['results'] if g['slot'] == 'mand']) < cap]
        assert skippers, f'{tour}: nobody skipped a compulsory event'
        for p in skippers:
            optional = sorted((g['pts'] for g in p['results'] if g['slot'] == 'other'),
                              reverse=True)
            counted = sum(optional[:OTHER_SLOTS])
            # the compulsory part is a plain sum of what they actually played
            mand = sum(g['pts'] for g in p['results'] if g['slot'] in ('mand', 'finals'))
            floats = sorted((g['pts'] for g in p['results'] if g['slot'] == 'float'),
                            reverse=True)
            if tour == 'ATP':
                counted = sum(sorted(optional + floats, reverse=True)[:OTHER_SLOTS])
            else:
                mand += sum(floats[:WTA_FLOATING_SLOTS])
                counted = sum(sorted(optional + floats[WTA_FLOATING_SLOTS:],
                                     reverse=True)[:OTHER_SLOTS])
            assert p['points'] == mand + counted, (
                f'{tour}: {p["name"]} does not split cleanly into a compulsory '
                f'sum and a best-of')


def test_slot_limits_are_never_exceeded(season):
    """At most 12/10 compulsory, one finals, and one result per tournament."""
    for tour, v in season.items():
        cap = 12 if tour == 'ATP' else 10
        for p in v['ranking']:
            slots = [g['slot'] for g in p['results']]
            assert slots.count('mand') <= cap, (
                f'{tour}: {p["name"]} has {slots.count("mand")} compulsory results, '
                f'more than the {cap} such events on the calendar')
            assert slots.count('finals') <= 1, f'{tour}: {p["name"]} has two finals'
            events = [g['event'] for g in p['results']]
            assert len(events) == len(set(events)), (
                f'{tour}: {p["name"]} is credited twice for one tournament -- '
                f'the finals pay five times over and must be banked once')


def test_the_right_events_are_compulsory(season):
    """Majors always; Monte Carlo never; the WTA's six combined 1000s yes.

    The slot label is what drives the arithmetic, so it is checked against the
    rule directly. Deriving the expected label from the page instead let a
    version that treated the four majors as ordinary optional events pass every
    other test in this file.
    """
    for tour, v in season.items():
        slams = 0
        for p in v['ranking']:
            for g in p['results']:
                if g['level'] == 'Grand Slam':
                    slams += 1
                    assert g['slot'] in ('mand', 'other'), (
                        f'{tour}: {g["event"]} counted as {g["slot"]!r} for {p["name"]}')
                    # 'other' is only legitimate for someone who qualified in
                    assert g['slot'] == 'mand' or g['round'] in ('R128', 'R64', 'R32'), (
                        f'{tour}: {p["name"]} treated {g["event"]} as optional after '
                        f'reaching {g["round"]}')
                if not g['level'].endswith('1000'):
                    continue
                if tour == 'ATP':
                    want = 'other' if g['event'] in ATP_OPTIONAL_1000 else 'mand'
                else:
                    want = 'mand' if g['event'] in WTA_COMPULSORY_1000 else 'float'
                # a qualifier was never on the direct entry list, so it is optional
                assert g['slot'] in (want, 'other'), (
                    f'{tour}: {g["event"]} counted as {g["slot"]!r} for '
                    f'{p["name"]}, expected {want!r}')
        assert slams > 50, f'{tour}: only {slams} major results seen'


def test_only_one_floating_thousand_counts_for_the_wta(season):
    """Four non-combined 1000s on the calendar, one compulsory slot between them."""
    v = season['WTA']
    seen = False
    for p in v['ranking']:
        floats = [g for g in p['results'] if g['slot'] == 'float']
        if len(floats) < 2:
            continue
        seen = True
        counted = [g for g in floats if g['event'] in p['counted']]
        best = max(g['pts'] for g in floats)
        assert any(g['pts'] == best for g in counted), (
            f'WTA: {p["name"]}\'s best other 1000 did not take the floating slot')
        # Any float counted beyond the first has to have earned an optional slot
        # on its own points, so it cannot be worth less than the weakest optional
        # result that got in.
        pool = sorted([g['pts'] for g in p['results'] if g['slot'] == 'other']
                      + sorted((g['pts'] for g in floats), reverse=True)[1:],
                      reverse=True)[:OTHER_SLOTS]
        extra = sorted((g['pts'] for g in counted), reverse=True)[1:]
        for pts in extra:
            assert pool and pts >= min(pool), (
                f'WTA: {p["name"]} counted a second non-combined 1000 worth {pts} '
                f'that did not make the best-of cut')
    assert seen, 'WTA: nobody played two non-combined 1000s, so nothing was tested'


def test_wear_redirects_a_schedule_rather_than_suppressing_it(season):
    """A tired player drops the optional events so they can play the major.

    Wear used to scale entry to everything at once, so a top-10 player carrying a
    season's load was offered 0.85 at Wimbledon and skipped it -- and the whole
    grass swing with it -- for no injury and no reason shown anywhere. What should
    happen instead is a reallocation: the major is untouched, a compulsory 1000
    gives way barely, and the 250s and 500s absorb all of it.
    """
    for tour, v in season.items():
        w = v['wear']
        # a major is never skipped for load: being too broken down to play one is
        # an injury, and the injury model owns that
        assert len(set(round(x, 6) for x in w['slam'])) == 1, (
            f'{tour}: load moves the chance of entering a major '
            f'({[round(x, 3) for x in w["slam"]]})')
        assert w['slam'][0] > 0.97, f'{tour}: a major sits at only {w["slam"][0]:.3f}'
        # a compulsory 1000 gives way, but only just
        assert w['m1000'][-1] < w['m1000'][0], f'{tour}: load does nothing to a 1000'
        assert w['m1000'][-1] > 0.88, (
            f'{tour}: a heavy load drops a compulsory 1000 to {w["m1000"][-1]:.3f}')
        # and the optional events take the whole of it
        drop_1000 = 1 - w['m1000'][-1] / w['m1000'][0]
        drop_opt = 1 - w['optional'][-1] / w['optional'][0]
        assert drop_opt > 4 * drop_1000, (
            f'{tour}: load costs an optional event {drop_opt:.1%} against a '
            f'compulsory 1000\'s {drop_1000:.1%} -- wear is not being redirected')


def test_a_looming_major_pulls_players_out_of_the_optional_events(season):
    """The other half: the week before a slam is when a tired player withdraws."""
    for tour, v in season.items():
        t = v['taper']
        assert t['far'] == 1.0, f'{tour}: an event far from a major is tapered {t["far"]}'
        assert t['week1'] > t['week2'] > t['week3'] > t['far'], (
            f'{tour}: the taper does not build towards a major {t}')
        # a loaded player is markedly likelier to sit out the week before a major
        near, far = v['wear']['optionalNear'], v['wear']['optional']
        heavy = v['wear']['loads'].index(10)
        assert near[heavy] < 0.9 * far[heavy], (
            f'{tour}: a 250 the week before a major is {near[heavy]:.3f} against '
            f'{far[heavy]:.3f} elsewhere -- the taper is not biting')
        assert near[0] == far[0], (
            f'{tour}: the taper moves a FRESH player, but it should only act '
            f'through carried load')


# ---- why the picked player is absent -------------------------------------

def test_an_absence_always_says_which_kind_it_was(season):
    """"Not in the draw" covered injury, withdrawal and a ranking too low."""
    known = {'injured', 'load management', 'rest', 'declined', 'playing elsewhere',
             'not qualified', 'lost in qualifying', 'draw full',
             'did not qualify'}
    for tour, v in season.items():
        for a in v['absence']:
            assert a['reasons'], f'{tour}: #{a["rank"]} was never absent'
            unknown = set(a['reasons']) - known
            assert not unknown, f'{tour}: #{a["rank"]} absent for {unknown}'
            assert 'not in the draw' not in a['reasons'], (
                f'{tour}: #{a["rank"]} still gets the old catch-all')
            # "did not play" belongs to a player who IS in the draw, so it must
            # never turn up as a reason for being absent from one.
            assert 'did not play' not in a['reasons'], (
                f'{tour}: #{a["rank"]} is absent AND in the draw')


def test_a_deeply_ranked_player_reaches_no_major_and_no_thousand(season):
    """From a world 400's point of view: the big draws are simply shut.

    And the reason given must be their ranking, never load management -- they
    carry no load, because they are not playing.
    """
    for tour, v in season.items():
        deep = next(a for a in v['absence'] if a['rank'] >= 400)
        assert deep['entered'] == 0, (
            f'{tour}: #{deep["rank"]} entered {deep["entered"]} main draws in '
            f'{deep["seasons"]} seasons')
        assert deep['missedSlams'] == 4 * deep['seasons'], (
            f'{tour}: #{deep["rank"]} was in a major draw')
        assert deep['missed1000'] >= 8 * deep['seasons'], (
            f'{tour}: #{deep["rank"]} was in a 1000 draw')
        assert 'load management' not in deep['reasons'], (
            f'{tour}: #{deep["rank"]} is "managing a workload" they do not have')
        share = deep['reasons'].get('not qualified', 0) / sum(deep['reasons'].values())
        assert share > 0.9, (
            f'{tour}: only {share:.0%} of #{deep["rank"]}\'s absences are put down '
            f'to their ranking')


def test_a_top_player_rests_up_rather_than_failing_to_qualify(season):
    """The world number one skips the small events to be fresh for the big ones."""
    for tour, v in season.items():
        top = next(a for a in v['absence'] if a['rank'] <= 5)
        total = sum(top['reasons'].values())
        managed = top['reasons'].get('load management', 0) / total
        assert managed > 0.2, (
            f'{tour}: only {managed:.0%} of #{top["rank"]}\'s absences are load '
            f'management -- a top player carrying a season of matches should be '
            f'resting up, not merely declining ({top["reasons"]})')
        # ...but not EVERY decline is load management. A fresh top player
        # skipping a 250 is just declining a 250, and blaming that on a
        # workload they have not yet built is the opposite error.
        plain = top['reasons'].get('declined', 0) / total
        assert plain > 0.05, (
            f'{tour}: {plain:.0%} of #{top["rank"]}\'s absences are plain declines '
            f'-- everything is being blamed on load ({top["reasons"]})')
        assert top['reasons'].get('not qualified', 0) == 0, (
            f'{tour}: #{top["rank"]} was told they did not qualify for something')
        assert top['missedSlams'] <= 0.5 * 4 * top['seasons'], (
            f'{tour}: #{top["rank"]} missed {top["missedSlams"]} majors in '
            f'{top["seasons"]} seasons')
