"""Where the stake labels sit in the point-by-point grid.

Every row of the grid shows the score AFTER its own point -- ladder() advances
the score and then renders it -- so a stake has to be attached to the point that
BRINGS IT UP, not to the point on which it exists. Hanging it on the point
itself put "BP" against a row reading 40-40: the score that had just saved the
break point, not the one that offered it.

The B / S / M markers are the other way round. They say what a point SETTLED, so
they belong on the point that settled it, and they stay on the last row.

Driven over real simulated matches rather than fixtures, and every expectation
is re-derived from the match record's own point list, so a change inside
pointStakes cannot move the test with it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(__file__).with_name('point_stakes.js')
HAVE_NODE = shutil.which('node') is not None

pytestmark = pytest.mark.skipif(not HAVE_NODE,
                                reason='node is needed to run the JS engine')


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    pool = [{'name': f'P{i}', 'rank': i + 1,
             'ratings': {'SRV': 5 + (i % 7) / 2, 'RET': 5 + (i % 5) / 2,
                         'SHOT': 5 + (i % 3), 'CONS': 5 + (i % 4) / 2}}
            for i in range(64)]
    pool_file = tmp_path_factory.mktemp('pool') / 'pool.json'
    pool_file.write_text(json.dumps(pool))
    proc = subprocess.run(['node', str(DRIVER), str(pool_file), '6'],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out['games'] > 500, f"only {out['games']} games simulated"
    assert out['stakes'] > 200, f"only {out['stakes']} stakes labelled at all"
    return out


def test_a_stake_sits_on_the_row_that_brings_it_up(grid):
    """The row carrying BP/SP/MP must DISPLAY a score at which that side is one
    point from the game. Recomputed from the match record's point list, so this
    is the definition of the label rather than a copy of how it is produced."""
    for r in grid['rows']:
        if not r['stake']:
            continue
        away = r['oneAway1'] if r['stakeSide'] == 1 else r['oneAway0']
        assert away, (
            f"a {r['stake']} sits on row {r['i']}, whose score does not leave "
            f"side {r['stakeSide']} one point from the game")


def test_no_stake_sits_on_the_row_that_ends_the_game(grid):
    """Once the game is over nobody is a point away from winning it, so the last
    row can carry an end marker and never a stake. This is what fails if the
    label is put back on the point where the stake exists: the converted one
    lands on the row that finished the game."""
    for r in grid['rows']:
        if r['last']:
            assert not r['stake'], (
                f"a {r['stake']} is on the row that ended the game")


def test_every_break_set_and_match_is_offered_before_it_is_taken(grid):
    """A converted stake must be visible: the row before B / S / M carries the
    matching BP / SP / MP. Without this the panel could drop the stakes entirely
    and both tests above would still pass, since neither requires any label to
    exist."""
    want = {'B': 'BP', 'S': 'SP', 'M': 'MP'}
    seen = {k: 0 for k in want}
    for r in grid['rows']:
        if r['end'] not in want:
            continue
        seen[r['end']] += 1
        assert r['prevStake'] == want[r['end']], (
            f"a game settled with {r['end']} but the row before it says "
            f"{r['prevStake']!r}, not {want[r['end']]!r}")
    assert seen['B'] > 20, f"only {seen['B']} breaks in the sample"
    assert seen['M'] > 0, 'no match was ever won in the sample'


def test_a_hold_is_never_labelled_a_break_point(grid):
    """The server cannot be broken on their own game point: a BP always belongs
    to the side that is not serving."""
    for r in grid['rows']:
        if r['stake'] == 'BP':
            assert r['stakeSide'] != r['srv'], (
                'a break point was credited to the server')
            assert not r['tb'], 'a tiebreak has no break points to label'
