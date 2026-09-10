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

ROOT = Path(__file__).resolve().parents[1]
# The ratings board template lives at the repo root, not in simulation/ -- it was
# outside this test's reach and carried the same duplicated-token defect unseen.
TEMPLATES = sorted((ROOT / 'simulation').glob('*_template.html')) + \
            sorted(ROOT.glob('*_template.html'))
assert TEMPLATES, 'no page templates found'

# A template that pulls the theme in at build time has no :root of its own, so
# checking the template would silently skip and cover nothing. Check what it
# builds INTO instead -- that is where the stylesheet actually lands.
THEME_MARKER = '/*__THEME__*/'


def _subject(template: Path) -> Path:
    if THEME_MARKER in template.read_text():
        return ROOT / template.name.replace('_template', '')
    return template


SUBJECTS = [_subject(t) for t in TEMPLATES]


def _source(subject: Path) -> str:
    if not subject.exists():
        pytest.skip(f'{subject.name} is not built yet -- run its build script')
    return subject.read_text()


def test_no_page_escapes_these_checks():
    """Guards the suite: a template whose theme is injected must map to a page
    that exists, or these checks quietly cover nothing at all."""
    injected = [t for t in TEMPLATES if THEME_MARKER in t.read_text()]
    for t in injected:
        built = _subject(t)
        assert built != t, f'{t.name} maps to itself'
        assert built.exists(), (
            f'{t.name} injects its theme at build time, so it is only checked '
            f'through {built.name} -- which is missing, leaving it unchecked')

BLOCKS = {
    'light':        r'^:root\{(.*?)^\}',
    'media dark':   r'@media \(prefers-color-scheme:dark\)\{(.*?)^\}',
    'stamped dark': r'^:root\[data-theme="dark"\]\{(.*?)^\}',
}


def defined(block: str) -> set[str]:
    return set(re.findall(r'(--[\w-]+)\s*:', block))


@pytest.mark.parametrize('template', SUBJECTS, ids=lambda p: p.name)
def test_every_token_is_defined_in_every_theme(template):
    source = _source(template)
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


@pytest.mark.parametrize('template', SUBJECTS, ids=lambda p: p.name)
def test_no_token_is_declared_twice_in_a_block(template):
    """A duplicated declaration means a patch landed in the wrong block."""
    source = _source(template)
    for name, pattern in BLOCKS.items():
        match = re.search(pattern, source, re.S | re.M)
        if match is None:
            continue
        names = re.findall(r'(--[\w-]+)\s*:', match.group(1))
        dupes = {n for n in names if names.count(n) > 1}
        assert not dupes, f'{template.name}: {sorted(dupes)} declared twice in {name}'


@pytest.mark.parametrize('template', SUBJECTS, ids=lambda p: p.name)
def test_every_token_used_is_defined(template):
    """Only var() calls WITHOUT a fallback are at risk.

    `var(--gamecols, 2)` is set from JS at runtime and carries its own default,
    so it cannot render broken; `var(--hold)` with no fallback must resolve.
    """
    source = _source(template)
    match = re.search(BLOCKS['light'], source, re.S | re.M)
    if match is None:
        pytest.skip('no :root block')
    used = set(re.findall(r'var\(\s*(--[\w-]+)\s*\)', source))
    missing = used - defined(match.group(1))
    assert not missing, f'{template.name}: var() references undefined {sorted(missing)}'
