"""The closed-form forecaster must agree with the point-by-point engine.

simulation/forecast.js computes a match winner without playing the points, so a
season can be simulated at a cost that does not scale with points played. That
is only sound if it gives the SAME distribution the engine would: points are
i.i.d. given the server and the drawn form, so a matchup reduces to two per-serve
point probabilities and everything above is exact arithmetic on them.

This drives both over identical matchups with form noise switched off (vol=None,
so drawForm returns zeros), which removes the only random input and lets the
closed form be compared against the simulator's win rate directly. Disagreement
beyond sampling error means the arithmetic has drifted from the point loop.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(__file__).with_name('forecast_parity.js')

HAVE_NODE = shutil.which('node') is not None
if not HAVE_NODE and os.environ.get('PARITY_REQUIRE_NODE'):
    raise RuntimeError('PARITY_REQUIRE_NODE is set but node is not installed')

pytestmark = pytest.mark.skipif(not HAVE_NODE,
                                reason='node is needed to run the JS engine')

N = 4000


@pytest.fixture(scope='module')
def _raw():
    proc = subprocess.run(['node', str(DRIVER), str(N)],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture(scope='module')
def rows(_raw):
    return _raw['matches']


def _unused():
    proc = None
    assert proc is None
@pytest.fixture(scope='module')
def tiebreaks(_raw):
    return _raw['tiebreaks']


def test_covers_both_tours_and_all_surfaces(rows):
    assert {r['tour'] for r in rows} == {'ATP', 'WTA'}
    assert {r['surface'] for r in rows} == {'hard', 'clay', 'grass'}
    assert {r['bestOf'] for r in rows} == {3, 5}
    assert {r['finalSetTiebreak'] for r in rows} == {7, 10}


def test_matchups_are_not_all_coin_flips(rows):
    """Guards the suite: equal players would pass any broken formula at 0.5."""
    spread = [r for r in rows if abs(r['simulated'] - 0.5) > 0.1]
    assert len(spread) >= len(rows) // 2, (
        'too many near-even matchups to discriminate a wrong formula')


def test_exact_probability_matches_simulated_rate(rows):
    """Each matchup individually, at 4 sigma."""
    bad = []
    for r in rows:
        p = r['simulated']
        se = math.sqrt(max(p * (1 - p), 1e-6) / r['n'])
        z = (p - r['exact']) / se
        if abs(z) > 4:
            bad.append(f"{r['tour']}/{r['surface']} bo{r['bestOf']} "
                       f"tb{r['finalSetTiebreak']}: simulated {p:.4f} vs "
                       f"exact {r['exact']:.4f}  (z={z:+.2f})")
    assert not bad, 'closed form disagrees with the engine:\n  ' + '\n  '.join(bad)


def test_residuals_are_consistent_overall(rows):
    """Many small same-signed biases would pass the per-row test but not this."""
    chi = 0.0
    for r in rows:
        p = r['simulated']
        se = math.sqrt(max(p * (1 - p), 1e-6) / r['n'])
        chi += ((p - r['exact']) / se) ** 2
    dof = len(rows)
    # chi2 well beyond the upper tail means a systematic offset, not noise
    assert chi < 2.5 * dof, f'chi2 {chi:.1f} on {dof} dof -- systematic drift'


def test_tiebreak_serve_rotation_matches_the_engine(tiebreaks):
    """Bucketed by opening server, so a rotation error cannot average away.

    The match-level tests above cannot see this: simMatch picks the opening
    server at random, and averaging over both halves cancels any phase error in
    the tiebreak rotation. Two deliberate mutations -- shifting the rotation by
    one point, and failing to flip the server after a tiebreak -- passed every
    other test in this file and are caught here.
    """
    assert tiebreaks, 'no tiebreaks collected'
    assert {t['first'] for t in tiebreaks} == {0, 1}, (
        'need both opening servers, otherwise the phase still averages out')
    bad = []
    for t in tiebreaks:
        p, n = t['simulated'], t['n']
        se = math.sqrt(max(p * (1 - p), 1e-6) / n)
        z = (p - t['exact']) / se
        if abs(z) > 4:
            bad.append(f"first-to-{t['len']}, opened by side {t['first']}: "
                       f"simulated {p:.4f} vs exact {t['exact']:.4f} "
                       f"(n={n}, z={z:+.2f})")
    assert not bad, 'tiebreak rotation disagrees:\n  ' + '\n  '.join(bad)


def test_tiebreak_probability_ignores_who_opens_it(_raw):
    """An exact property, so this catches a rotation phase error outright.

    Under the 1-2-2-2 rotation both sides have served equally after every even
    number of points, and the win-by-two tail is symmetric, so the opener does
    not shift the probability at all. Shifting the rotation by one point breaks
    this by about 0.05 -- an effect the sampled comparison above only sees at
    around 3.6 sigma, under its own 4 sigma threshold.
    """
    assert _raw['symmetry'] < 1e-12, (
        f"tiebreak probability shifts by {_raw['symmetry']:.2e} when the opening "
        f"server changes; the rotation is wrong")


def test_serve_carries_out_of_a_set_correctly(_raw):
    """The joint distribution of (who won the set, who serves the next one).

    A set decided in a tiebreak hands serve on from whoever STARTED the
    tiebreak, not from the last server, so it differs from a set decided on
    games. Getting this wrong leaves every later set served by the wrong player.
    """
    rows = _raw['carry']
    assert len(rows) == 2, 'need both opening servers'
    bad = []
    for r in rows:
        for i, (p, e) in enumerate(zip(r['simulated'], r['exact'])):
            se = math.sqrt(max(p * (1 - p), 1e-6) / r['n'])
            z = (p - e) / se
            if abs(z) > 4:
                bad.append(f"set opened by side {r['first']}, outcome "
                           f"(winner={i // 2}, next server={i % 2}): "
                           f"simulated {p:.4f} vs exact {e:.4f} "
                           f"(n={r['n']}, z={z:+.2f})")
    assert not bad, 'serve carry-over disagrees:\n  ' + '\n  '.join(bad)
