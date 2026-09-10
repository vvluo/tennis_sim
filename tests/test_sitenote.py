"""The shared chrome -- the About panel and the footer -- on every page.

It explains how match statistics become the published ratings, so it has to
read identically on the tournament simulator, the season simulator and the
ratings board. Keeping one copy is the whole point: three pasted copies of a
paragraph drift, and the ratings board is the one most likely to be left
behind because the notebook writes it and substitutes only its own data marker.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import sitenote

ROOT = Path(__file__).resolve().parents[1]
PAGES = ['tournament.html', 'season.html', 'ratings_board.html']
BUILT = [ROOT / p for p in PAGES]


@pytest.mark.parametrize('page', BUILT, ids=lambda p: p.name)
def test_every_page_carries_the_panel(page):
    if not page.exists():
        pytest.skip(f'{page.name} is not built')
    text = page.read_text()
    assert 'id="snwrap"' in text, f'{page.name} has no About panel'
    assert 'id="snopen"' in text or "id = 'snopen'" in text or 'snopen' in text, (
        f'{page.name} has the panel but nothing opens it')


@pytest.mark.parametrize('page', BUILT, ids=lambda p: p.name)
def test_panel_names_the_ratings_board(page):
    if not page.exists():
        pytest.skip(f'{page.name} is not built')
    assert 'Tour Ratings Board' in page.read_text(), (
        f'{page.name}: the panel does not say where the ratings are shown')


def test_no_page_carries_it_twice():
    for page in BUILT:
        if not page.exists():
            continue
        assert page.read_text().count('id="snwrap"') == 1, (
            f'{page.name} has the panel more than once')


def test_all_pages_carry_the_same_text():
    """One source, so the wording cannot diverge between pages."""
    def body(text):
        m = re.search(r'<div class="snbody">(.*?)</div>\s*</div>\s*</div>', text, re.S)
        return re.sub(r'\s+', ' ', m.group(1)).strip() if m else None

    bodies = {p.name: body(p.read_text()) for p in BUILT if p.exists()}
    assert all(bodies.values()), f'could not read the panel from {list(bodies)}'
    distinct = set(bodies.values())
    assert len(distinct) == 1, (
        'the About panel differs between pages:\n  '
        + '\n  '.join(f'{k}: {v[:90]}...' for k, v in bodies.items()))


def test_it_matches_the_shared_source():
    src = sitenote.html()
    assert 'Tour Ratings Board' in src
    for page in BUILT:
        if page.exists():
            assert 'z&#8209;scored against the tour' in page.read_text(), (
                f'{page.name} does not carry the current wording')


def test_no_unsubstituted_marker_survives():
    for page in BUILT:
        if page.exists():
            assert sitenote.MARKER not in page.read_text(), (
                f'{page.name} still has the raw {sitenote.MARKER} marker')


# ---- the shared footer ---------------------------------------------------

PROFILE_LINKS = ['https://github.com/vvluo', 'https://vvluo.github.io/']


@pytest.mark.parametrize('page', BUILT, ids=lambda p: p.name)
def test_every_page_has_the_shared_footer(page):
    """The season page shipped with no copyright and no disclaimer at all.

    Two pages carried a hand-written footer and the third built a plain line of
    text in JavaScript, so the legal wording existed on two thirds of the site.
    """
    if not page.exists():
        pytest.skip(f'{page.name} is not built')
    text = page.read_text()
    assert 'class="sitefoot"' in text, f'{page.name} has no shared footer'
    assert '&copy; 2026 | Aaron Guo' in text, f'{page.name} has no copyright line'
    assert 'independent, fan-made simulation' in text, f'{page.name} has no disclaimer'
    assert 'sportradar.com' in text, f'{page.name} does not credit the data source'


@pytest.mark.parametrize('page', BUILT, ids=lambda p: p.name)
def test_profile_links_are_present_and_open_safely(page):
    if not page.exists():
        pytest.skip(f'{page.name} is not built')
    text = page.read_text()
    foot = text[text.index('class="sitefoot"'):]
    for url in PROFILE_LINKS:
        assert url in foot, f'{page.name}: {url} is missing from the footer'
    # every outbound link in the footer opens in a new tab without leaking the opener
    import re
    for tag in re.findall(r'<a [^>]*href="https?://[^"]+"[^>]*>', foot):
        assert 'rel="noopener noreferrer"' in tag, f'{page.name}: unsafe link {tag[:70]}'


@pytest.mark.parametrize('page', BUILT, ids=lambda p: p.name)
def test_the_coffee_button_is_present(page):
    """Buy Me a Coffee ships its own button, so the footer carries their script.

    It writes its own anchor at runtime, so the URL never appears as an href in
    the built page and the profile-link check above cannot see it -- the slug in
    the script tag is what actually points it at the right account.
    """
    if not page.exists():
        pytest.skip(f'{page.name} is not built')
    text = page.read_text()
    foot = text[text.index('class="sitefoot"'):]
    assert 'cdnjs.buymeacoffee.com/1.0.0/button.prod.min.js' in foot, (
        f'{page.name} has no Buy Me a Coffee button')
    assert 'data-slug="vvluo"' in foot, f'{page.name}: the button has the wrong slug'
    # inside .sitelinks it would be forced into a 30px square
    links = foot[foot.index('class="sitelinks"'):]
    assert 'buymeacoffee' not in links[:links.index('</span>')], (
        f'{page.name}: the button sits inside the 30px icon row')


def test_the_old_per_page_footers_are_gone():
    """Replaced in place, not left alongside the shared one."""
    for page in BUILT:
        if not page.exists():
            continue
        text = page.read_text()
        assert '<footer class="foot">' not in text, (
            f'{page.name} still carries its own footer as well as the shared one')
        assert text.count('class="sitefoot"') == 1, (
            f'{page.name} has the shared footer more than once')


def test_footer_is_identical_across_pages():
    import re
    def foot(text):
        m = re.search(r'<footer class="sitefoot">(.*?)</footer>', text, re.S)
        return re.sub(r'\s+', ' ', m.group(1)).strip() if m else None
    got = {p.name: foot(p.read_text()) for p in BUILT if p.exists()}
    assert all(got.values()), f'could not read the footer from {list(got)}'
    assert len(set(got.values())) == 1, 'the footer differs between pages'


def test_inlining_twice_does_not_duplicate():
    once = sitenote.inline('<html><body>hi</body></html>')
    twice = sitenote.inline(once)
    assert once == twice, 'inline() is not idempotent; a rebuild would double the chrome'


def test_panel_does_not_overclaim_the_point_model():
    """The derivatives give each statistic its DIRECTION, not its weight.

    contribution() returns 5 + 2z or 5 - 2z on the sign of the slope and never
    reads its magnitude; the magnitude is split-half reliability, measured by
    compute_weights(). An earlier wording said the weights came from the point
    model, which is checkable and wrong.
    """
    src = sitenote.html()
    assert 'weights taken from the simulator' not in src, (
        'the panel credits the point model with the weights; it supplies the '
        'orientation, and reliability supplies the weight')
    assert 'repeatably' in src or 'reliab' in src, (
        'the panel does not say where the weighting actually comes from')


def test_personal_site_icon_is_a_globe():
    """The first attempt used a contact card, which read as a CV rather than a
    site. A globe is the convention, and solid-filled so it sits beside the
    GitHub mark rather than looking like a different set."""
    src = sitenote.foot_html()
    foot = src[src.index('Personal website'):]
    assert '<circle cx="12" cy="12" r="10"' in foot, 'the globe body is missing'
    assert 'M14.5 2H6' not in src, 'the contact-card icon is still in the footer'
    assert 'fill="currentColor"' in foot, (
        'the globe does not inherit the footer colour, so it will not follow the theme')


@pytest.mark.parametrize('page', BUILT, ids=lambda p: p.name)
def test_the_built_footer_matches_the_source(page):
    """Every page carries the CURRENT shared footer, not a version of it.

    Carrying one was never the hard part -- keeping three copies the same is.
    The ratings board is written by the notebook rather than a build script, so
    the first time the footer changed it kept the old one while the other two
    moved on, and every check here still passed.
    """
    if not page.exists():
        pytest.skip(f'{page.name} is not built')
    import sitenote
    built = sitenote.SHARED_FOOTER.search(page.read_text())
    assert built, f'{page.name} has no shared footer block'
    want = sitenote.SHARED_FOOTER.search(sitenote.foot_html())
    assert want, 'the footer source no longer matches its own pattern'
    assert built.group(0).strip() == want.group(0).strip(), (
        f'{page.name} carries a stale copy of the shared footer')
