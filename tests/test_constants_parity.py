"""The two engines must agree on every shared constant.

test_engine_parity drives simMatch directly off pre-built player objects, so it
never exercises toPlayer or buildField -- SHRINK, the draw sizes and the round
names all sit outside its reach, and a value changed on one side only would sail
through it green. This reads the numbers straight out of simulation/engine.js
and compares them with the Python they were ported from.
"""

from __future__ import annotations

import json
import re
import subprocess
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
             'BASE_SERVE_RETURN', 'BASE_RALLY_RETURN', 'BASE_INCONSISTENCY',
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


def js_object(name):
    """The `const <name> = {...};` literal, brace-matched rather than regexed.

    A regex cannot do this: TOUR_BASE is written on one line and SURFACE_OFFSET
    over several, so any single pattern runs past one or stops short of the other.
    """
    start = SOURCE.index('const ' + name)
    open_brace = SOURCE.index('{', start)
    depth, i = 0, open_brace
    while i < len(SOURCE):
        if SOURCE[i] == '{':
            depth += 1
        elif SOURCE[i] == '}':
            depth -= 1
            if depth == 0:
                break
        i += 1
    return SOURCE[open_brace + 1:i]


def js_nested(name):
    """A two-level table of numbers, as a dict of dicts."""
    body = js_object(name)
    out = {}
    for key, inner in re.findall(r'(\w+)\s*:\s*\{([^{}]*)\}', body):
        out[key] = {k: float(v) for k, v in re.findall(r'(\w+)\s*:\s*(-?[\d.+]+)', inner)}
    return out


def js_deep(name):
    """A three-level table: tour -> surface -> {serve, rally}."""
    body = js_object(name)
    out = {}
    for tour, block in re.findall(r'(\w+)\s*:\s*\{((?:[^{}]|\{[^{}]*\})*)\}', body):
        inner = {}
        for surface, pair in re.findall(r'(\w+)\s*:\s*\{([^{}]*)\}', block):
            inner[surface] = {k: float(v) for k, v in
                              re.findall(r'(\w+)\s*:\s*(-?[\d.+]+)', pair)}
        if inner:
            out[tour] = inner
    return out


def test_tour_bases_match():
    """The two fitted baselines, per tour."""
    js = js_nested('TOUR_BASE')
    assert set(js) == set(P.TOUR_BASE), f'tours differ: {sorted(set(js) ^ set(P.TOUR_BASE))}'
    for tour, want in P.TOUR_BASE.items():
        for key, value in want.items():
            assert js[tour][key] == pytest.approx(value), (
                f'TOUR_BASE[{tour}][{key}]: python {value}, engine.js {js[tour][key]}')


def test_surface_offsets_match():
    """Per-tour, per-surface offsets to those baselines."""
    js = js_deep('SURFACE_OFFSET')
    assert set(js) == set(P.SURFACE_OFFSET)
    for tour, surfaces in P.SURFACE_OFFSET.items():
        assert set(js[tour]) == set(surfaces), f'{tour} surfaces differ'
        for surface, want in surfaces.items():
            for key, value in want.items():
                assert js[tour][surface][key] == pytest.approx(value), (
                    f'SURFACE_OFFSET[{tour}][{surface}][{key}]: '
                    f'python {value}, engine.js {js[tour][surface][key]}')


@pytest.mark.parametrize('draw', [2, 3, 7, 9, 15, 16, 28, 30, 32, 48, 56, 64, 96, 128, 200, 256])
def test_draw_shape_matches(draw):
    """The shape rules are functions now, so compare what they return.

    A draw of N sits in a bracket of the next power of two, a quarter of that is
    seeded (none below four), and the empty seats are byes.
    """
    js = f"""
      {SOURCE}
      const out = {{ bracket: bracketFor({draw}), seeds: seedsFor({draw}),
                     rounds: roundNames(bracketFor({draw})) }};
      process.stdout.write(JSON.stringify(out));
    """
    got = json.loads(subprocess.run(['node', '-e', js], capture_output=True,
                                    text=True, check=True).stdout)
    assert got['bracket'] == T.bracket_for(draw)
    assert got['seeds'] == T.seeds_for(draw)
    assert got['rounds'] == T.round_names(T.bracket_for(draw))
