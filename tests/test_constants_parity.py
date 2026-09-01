"""The two engines must agree on every shared constant.

test_engine_parity drives simMatch directly off pre-built player objects, so it
never exercises toPlayer or buildField -- SHRINK, the draw sizes and the round
names all sit outside its reach, and a value changed on one side only would sail
through it green. This reads the numbers straight out of simulation/engine.js
and compares them with the Python they were ported from.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from simulation import player as P
from simulation import tournament as T

ENGINE = Path(__file__).resolve().parents[1] / 'simulation' / 'engine.js'
SOURCE = ENGINE.read_text()


def js_block(name):
    """The `const <name> = { ... };` object literal, as a dict of numbers."""
    match = re.search(r'const\s+' + name + r'\s*=\s*\{(.*?)\}\s*;', SOURCE, re.S)
    assert match, f'{name} not found in engine.js'
    body = re.sub(r'//.*', '', match.group(1))
    return {k: float(v) for k, v in re.findall(r'(\w+)\s*:\s*(-?[\d.]+)', body)}


def js_number(name):
    match = re.search(r'\b' + name + r'\s*=\s*(-?[\d.]+)', SOURCE)
    assert match, f'{name} not found in engine.js'
    return float(match.group(1))


def test_player_constants_match():
    js = js_block('K')
    names = ['BASE_FIRST_SERVE_PERCENTAGE', 'FIRST_SERVE_GRADIENT',
             'BASE_DOUBLE_FAULT_RATE', 'DOUBLE_FAULT_GRADIENT',
             'FIRST_SERVE_BOOST', 'SECOND_SERVE_BOOST', 'RETURN_GRADIENT',
             'BASE_SHOT_ACCURACY', 'BASE_INCONSISTENCY',
             'INCONSISTENCY_GRADIENT', 'RALLY_ADVANTAGE_GRADIENT',
             'BASE_FORM_SD', 'FORM_SD_GRADIENT']
    assert set(js) == set(names), f'engine.js K has {sorted(set(js) ^ set(names))} unexpected/missing'
    for name in names:
        assert js[name] == pytest.approx(getattr(P, name)), (
            f'{name}: python {getattr(P, name)}, engine.js {js[name]}')


def test_shrink_matches():
    js = js_block('SHRINK')
    assert js == pytest.approx({k: float(v) for k, v in T.SHRINK.items()}), (
        f'python {T.SHRINK}, engine.js {js}')


@pytest.mark.parametrize('name', ['DRAW_SIZE', 'SEEDS', 'DIRECT_ENTRANTS', 'QUALIFIERS'])
def test_draw_sizes_match(name):
    assert js_number(name) == getattr(T, name), (
        f'{name}: python {getattr(T, name)}, engine.js {js_number(name)}')


def test_round_names_match():
    match = re.search(r"const ROUND_NAMES\s*=\s*\[(.*?)\]", SOURCE, re.S)
    assert match, 'ROUND_NAMES not found in engine.js'
    assert re.findall(r"'([^']+)'", match.group(1)) == T.ROUND_NAMES
