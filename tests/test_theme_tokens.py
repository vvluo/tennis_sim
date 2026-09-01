"""Every colour token must be defined in all three theme blocks.

A token defined only in :root falls back to its LIGHT value when the toggle
stamps data-theme="dark" on a system that prefers light -- which is how the game
tiles in the popup ended up with pale backgrounds under light-on-dark text. The
media query and the stamped block are separate selectors and both must be
complete.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES = sorted((Path(__file__).resolve().parents[1] / 'simulation').glob('*_template.html'))
assert TEMPLATES, 'no page templates found'

BLOCKS = {
    'light':        r'^:root\{(.*?)^\}',
    'media dark':   r'@media \(prefers-color-scheme:dark\)\{(.*?)^\}',
    'stamped dark': r'^:root\[data-theme="dark"\]\{(.*?)^\}',
}


def defined(block: str) -> set[str]:
    return set(re.findall(r'(--[\w-]+)\s*:', block))


@pytest.mark.parametrize('template', TEMPLATES, ids=lambda p: p.name)
def test_every_token_is_defined_in_every_theme(template):
    source = template.read_text()
    found = {}
    for name, pattern in BLOCKS.items():
        match = re.search(pattern, source, re.S | re.M)
        if match is None:
            pytest.skip(f'{template.name} has no {name} block')
        found[name] = defined(match.group(1))

    light = found['light']
    for name in ('media dark', 'stamped dark'):
        missing = light - found[name]
        assert not missing, (
            f'{template.name}: {sorted(missing)} defined only in :root, so they '
            f'keep their light values in the {name} theme')


@pytest.mark.parametrize('template', TEMPLATES, ids=lambda p: p.name)
def test_no_token_is_declared_twice_in_a_block(template):
    """A duplicated declaration means a patch landed in the wrong block."""
    source = template.read_text()
    for name, pattern in BLOCKS.items():
        match = re.search(pattern, source, re.S | re.M)
        if match is None:
            continue
        names = re.findall(r'(--[\w-]+)\s*:', match.group(1))
        dupes = {n for n in names if names.count(n) > 1}
        assert not dupes, f'{template.name}: {sorted(dupes)} declared twice in {name}'


@pytest.mark.parametrize('template', TEMPLATES, ids=lambda p: p.name)
def test_every_token_used_is_defined(template):
    """Only var() calls WITHOUT a fallback are at risk.

    `var(--gamecols, 2)` is set from JS at runtime and carries its own default,
    so it cannot render broken; `var(--hold)` with no fallback must resolve.
    """
    source = template.read_text()
    match = re.search(BLOCKS['light'], source, re.S | re.M)
    if match is None:
        pytest.skip('no :root block')
    used = set(re.findall(r'var\(\s*(--[\w-]+)\s*\)', source))
    missing = used - defined(match.group(1))
    assert not missing, f'{template.name}: var() references undefined {sorted(missing)}'
