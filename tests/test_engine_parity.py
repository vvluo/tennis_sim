"""The JS engine must reproduce the Python engine point for point.

simulation/engine.js is a hand port of player.py, match.py and tournament.py,
and the page runs the port, not the original. Aggregate agreement (hold rate,
points per match) is too coarse to catch a swapped boost or a mis-ordered
server switch, so this drives both engines off ONE shared random stream and
requires identical records: same winner, same games, same shots on every point.

If the two ever ask for a different number of draws the stream desynchronises
and the records diverge immediately, so the draw ORDER is under test too.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from simulation.match import Match
from simulation.player import Player
from simulation.frontend import match_payload, match_stats

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(__file__).with_name('engine_parity.js')

HAVE_NODE = shutil.which('node') is not None

# Skipping is a convenience for machines without node, but a skip exits zero, so
# on CI a missing node would turn this gate into a vacuous pass. Setting
# PARITY_REQUIRE_NODE makes its absence a failure instead.
if not HAVE_NODE and os.environ.get('PARITY_REQUIRE_NODE'):
    raise RuntimeError('PARITY_REQUIRE_NODE is set but node is not installed')

pytestmark = pytest.mark.skipif(not HAVE_NODE,
                                reason='node is needed to run the JS engine')


class Stream:
    """Stands in for random.random / random.gauss, handing out fixed values."""

    def __init__(self, uniforms, normals):
        self.uniforms, self.normals = uniforms, normals
        self.ui = self.zi = 0

    def random(self):
        value = self.uniforms[self.ui]        # IndexError = the engines desynced
        self.ui += 1
        return value

    def gauss(self, mu, sd):
        z = self.normals[self.zi]
        self.zi += 1
        return mu + sd * z


def make_players(count, seed):
    rng = random.Random(seed)
    out = []
    for i in range(count):
        ratings = [round(rng.uniform(2.0, 8.5), 3) for _ in range(4)]
        out.append({'name': 'A' if i % 2 == 0 else 'B',
                    'srv': ratings[0], 'cons': ratings[1],
                    'ret': ratings[2], 'shot': ratings[3], 'vol': ratings[1]})
    return out


def normalise(match, p1_id):
    """Python match record -> the same shape the Node driver prints."""
    side = lambda i: 0 if i == p1_id else 1
    sets = []
    for _, _, set_winner, _, games in match.get_match_record()[4]:
        rows = []
        for kind, server_id, winner_id, _, points in games:
            rows.append({'k': 't' if kind == 'tiebreak' else 'g',
                         'srv': side(server_id), 'win': side(winner_id),
                         'pts': [[side(p[0]), p[1], 1 if p[2] else 0] for p in points]})
        sets.append({'win': side(set_winner), 'games': rows})
    return {'winner': side(match.match_record[2]), 'sets': sets}


@pytest.mark.parametrize('best_of,final_tb', [(5, 10), (3, 7)])
def test_js_engine_matches_python_point_for_point(monkeypatch, best_of, final_tb):
    seed = 20260831 + best_of
    source = random.Random(seed)
    uniforms = [source.random() for _ in range(400_000)]
    normals = [source.gauss(0.0, 1.0) for _ in range(4_000)]

    players = make_players(60, seed)
    pairs = [(players[i], players[i + 1]) for i in range(0, len(players), 2)]

    # --- Python, reading the stream -------------------------------------
    py_stream = Stream(uniforms, normals)
    monkeypatch.setattr(random, 'random', py_stream.random)
    monkeypatch.setattr(random, 'gauss', py_stream.gauss)

    py_records, py_stats, py_scores = [], [], []
    for top, bottom in pairs:
        a = Player('A', top['srv'], top['cons'], top['ret'], top['shot'],
                   volatility=top['vol'])
        b = Player('B', bottom['srv'], bottom['cons'], bottom['ret'],
                   bottom['shot'], volatility=bottom['vol'])
        played = Match(a, b, best_of=best_of, final_set_tiebreak=final_tb)
        py_records.append(normalise(played, a.id))
        rows, _ = match_stats(played)
        py_stats.append([[r['label'], r['a'], r['b'], r['better']] for r in rows])
        payload = match_payload(played, 1)
        py_scores.append({
            'score': payload['score'],
            'setScores': [s['score'] for s in payload['sets']],
            'gameScores': [[g['score'] for g in s['games']] for s in payload['sets']],
            'pointScores': [[[pt['s'] for pt in g['points']] for g in s['games']]
                            for s in payload['sets']],
        })

    monkeypatch.undo()

    # --- JavaScript, reading the same stream -----------------------------
    spec = {'stream': uniforms, 'normals': normals, 'bestOf': best_of,
            'finalSetTiebreak': final_tb,
            'matches': [{'top': t, 'bottom': b} for t, b in pairs]}
    proc = subprocess.run(['node', str(DRIVER)], input=json.dumps(spec),
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    js = json.loads(proc.stdout)

    assert js['uniforms'] == py_stream.ui, (
        f"engines drew a different number of uniforms: "
        f"python {py_stream.ui}, js {js['uniforms']}")
    assert js['normals'] == py_stream.zi

    for i, (want, got) in enumerate(zip(py_records, js['result'])):
        assert want['winner'] == got['winner'], f'match {i}: different winner'
        assert want['sets'] == got['sets'], f'match {i}: records diverge'
        assert py_stats[i] == got['stats'], f'match {i}: statistics diverge'
        for key in ('score', 'setScores', 'gameScores', 'pointScores'):
            assert py_scores[i][key] == got[key], f'match {i}: {key} diverges'
