"""The exported point log must agree with the engine that produced it.

exportRows() lives in simulation/matchview.js, shared by the grand-slam page and
the season page, and re-derives things the engine records only implicitly --
above all WHO SERVED each point. A tiebreak rotates serve after the first point and every
two points after that, so reading the server off the game record (which holds
only the player who served point one) mislabels roughly half the points and
silently inverts server_won for them. These tests replay real simulated matches
through the shipped exportRows and check every point against the rotation rule
the engine actually plays out in simTiebreak.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(__file__).with_name('export_rows.js')

HAVE_NODE = shutil.which('node') is not None
if not HAVE_NODE and os.environ.get('PARITY_REQUIRE_NODE'):
    raise RuntimeError('PARITY_REQUIRE_NODE is set but node is not installed')

pytestmark = pytest.mark.skipif(not HAVE_NODE,
                                reason='node is needed to run the JS engine')


@pytest.fixture(scope='module')
def matches(tmp_path_factory):
    from run_tournament import candidates
    pool = [{'name': f'P{i}', 'rank': i + 1,
             'ratings': {'SRV': 5 + (i % 7) / 2, 'RET': 5 + (i % 5) / 2,
                         'SHOT': 5 + (i % 3), 'CONS': 5 + (i % 4) / 2}}
            for i in range(64)]
    pool_file = tmp_path_factory.mktemp('pool') / 'pool.json'
    pool_file.write_text(json.dumps(pool))
    proc = subprocess.run(['node', str(DRIVER), str(pool_file), '8'],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out, 'the driver produced no matches'
    return out


def _games(match):
    """Group the exported rows back into games, in order."""
    games, cur = [], None
    for row in match['rows']:
        if cur is None or row['overall_game'] != cur[0]:
            cur = (row['overall_game'], [])
            games.append(cur)
        cur[1].append(row)
    return [rows for _, rows in games]


def test_driver_saw_tiebreaks(matches):
    """Guards the suite itself: these assertions are vacuous with no tiebreak."""
    n = sum(1 for m in matches for g in _games(m) if g[0]['tiebreak'])
    assert n >= 5, f'only {n} tiebreaks in the sample -- raise the draw count'


def test_row_count_matches_engine(matches):
    for m in matches:
        played = [g for s in m['truth'] for g in s]
        assert len(_games(m)) == len(played)
        for rows, g in zip(_games(m), played):
            assert len(rows) == g['n']


def test_tiebreak_serve_rotates(matches):
    """Serve changes after point 1, then every two points."""
    for m in matches:
        played = [g for s in m['truth'] for g in s]
        for rows, g in zip(_games(m), played):
            if g['k'] != 't':
                continue
            for i, row in enumerate(rows):
                expected = g['srv'] ^ ((i + 1) // 2 % 2)
                assert row['server'] == m['names'][expected], (
                    f"tiebreak point {i + 1}: exported server {row['server']}, "
                    f"engine served {m['names'][expected]}")
                assert row['returner'] == m['names'][1 - expected]
                assert row['server_won'] == int(row['winner'] == row['server'])


def test_tiebreak_serve_counts_are_balanced(matches):
    """Over a tiebreak neither player may serve more than one extra point."""
    for m in matches:
        for rows in _games(m):
            if not rows[0]['tiebreak']:
                continue
            a = sum(1 for r in rows if r['server'] == m['names'][0])
            assert abs(2 * a - len(rows)) <= 1, (
                f'{a} of {len(rows)} tiebreak points served by one player')


def test_regular_game_holds_one_server(matches):
    for m in matches:
        for rows in _games(m):
            if rows[0]['tiebreak']:
                continue
            assert len({r['server'] for r in rows}) == 1


def test_server_alternates_between_games(matches):
    """Serve passes to the other player after each completed game."""
    for m in matches:
        by_set = {}
        for rows in _games(m):
            by_set.setdefault(rows[0]['set'], []).append(rows)
        for rows_in_set in by_set.values():
            for prev, cur in zip(rows_in_set, rows_in_set[1:]):
                # the first point of a tiebreak is served by whoever would have
                # served the next game, so the rule holds across it too
                assert cur[0]['server'] != prev[0]['server'], (
                    f"set {cur[0]['set']} game {cur[0]['game']}: "
                    f"{cur[0]['server']} served consecutive games")


def test_tiebreak_is_numbered_as_a_game(matches):
    for m in matches:
        for rows in _games(m):
            assert rows[0]['game'] != '', 'every game, tiebreak included, is numbered'
            if rows[0]['tiebreak']:
                assert rows[0]['game'] == 13


def test_no_break_points_in_a_tiebreak(matches):
    for m in matches:
        for rows in _games(m):
            if rows[0]['tiebreak']:
                assert all(r['break_point'] == 0 for r in rows)
