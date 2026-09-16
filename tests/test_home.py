"""The landing page, and the way back to it from every other page."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / 'home.html'
FEATURES = ['season.html', 'tournament.html', 'matchup.html', 'ratings_board.html']
PAGES = [ROOT / p for p in ['home.html'] + FEATURES]


@pytest.fixture(scope='module')
def home():
    if not HOME.exists():
        pytest.skip('home.html is not built -- run run_home.py')
    return HOME.read_text()


def _rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css)
    assert m, f'no rule for {selector}'
    return m.group(1)


def test_one_panel_per_feature(home):
    hrefs = re.findall(r'<a class="panel [^"]*" href="([^"]+)"', home)
    assert sorted(hrefs) == sorted(FEATURES), f'panels link to {hrefs}'


def test_shadows_are_black_except_under_the_black_panel(home):
    """A black shadow under a black panel is no shadow at all, so that one alone
    takes US Open yellow. Every other panel must fall back to black."""
    base = _rule(home, '.panel')
    assert re.search(r'box-shadow:\s*10px 10px 0 var\(--psh, #141414\)', base), (
        'the resting shadow is not a hard, unblurred black offset')
    black = _rule(home, '.p-black')
    assert re.search(r'background:\s*#141414', black)
    assert re.search(r'--psh:\s*#E2B84A', black), 'the black panel casts a black shadow'
    for other in ('.p-clay', '.p-grass', '.p-hard'):
        assert '--psh' not in _rule(home, other), f'{other} overrides the black shadow'


def _press(rule: str):
    t = re.search(r'translate\((\d+)px,\s*(\d+)px\)', rule)
    s = re.search(r'box-shadow:\s*(\d+)(?:px)?\s+(\d+)(?:px)?\s+0', rule)
    assert t and s, f'no translate/shadow pair in: {rule}'
    return int(t[1]) + int(s[1]), int(t[2]) + int(s[2])


def test_pressing_sinks_the_panel_into_its_own_shadow(home):
    """What makes it read as an imprint: the panel moves exactly as far as the
    shadow shrinks, so the shadow's far edge stays put. Moving further than that
    and it floats off the board; less, and the shadow visibly jumps."""
    rest = re.search(r'box-shadow:\s*(\d+)px', _rule(home, '.panel'))
    depth = int(rest[1])
    assert _press(_rule(home, '.panel:hover,.panel:focus-visible')) == (depth, depth)
    active = _rule(home, '.panel:active')
    assert _press(active) == (depth, depth)
    assert re.search(r'box-shadow:\s*0 0 0', active), 'fully pressed still casts a shadow'


def test_rounded_like_the_rest_of_the_site(home):
    assert re.search(r'border-radius:\s*1[0-6]px', _rule(home, '.panel'))


def test_an_old_shared_draw_is_forwarded_to_the_tournament(home):
    """Draws shared before this page existed link to the site root with ?r=."""
    fwd = home.find("location.replace('tournament.html' + location.search")
    assert fwd != -1, 'a ?r= link to the root would now land on the home page'
    assert fwd < home.find('<div class="wrap">'), 'the forward runs after the page paints'


@pytest.mark.parametrize('page', PAGES, ids=lambda p: p.name)
def test_the_ball_and_the_title_link_home(page):
    if not page.exists():
        pytest.skip(f'{page.name} is not built')
    h1 = re.search(r'<h1[^>]*>(.*?)</h1>', page.read_text(), re.S)
    assert h1, f'{page.name} has no h1'
    inner = h1.group(1)
    link = re.fullmatch(r'<a class="homelink" href="index.html"[^>]*>(.*)</a>', inner, re.S)
    assert link, f'{page.name}: the title is not wrapped in a link home'
    assert 'class="ball"' in link.group(1), f'{page.name}: the ball sits outside the link'


def test_each_feature_wears_its_colour(home):
    want = {'season.html': 'p-clay', 'tournament.html': 'p-grass',
            'matchup.html': 'p-hard', 'ratings_board.html': 'p-black'}
    got = dict((href, cls) for cls, href in
               re.findall(r'<a class="panel (p-[\w-]+)" href="([^"]+)"', home))
    assert got == want, f'panel colours are {got}'


def test_the_colours_are_the_season_simulators(home):
    """Same three surfaces the season page paints its timeline in, read from that
    page rather than copied here, so a retune there cannot leave these behind."""
    season = (ROOT / 'simulation' / 'season_template.html').read_text()
    surface = dict(re.findall(r"^\s*(hardEarly|clay|grass):\s*'(#[0-9A-Fa-f]{6})'", season, re.M))
    assert len(surface) == 3, f'could not read SURFACE_BG from the season page: {surface}'
    for cls, key in (('.p-clay', 'clay'), ('.p-grass', 'grass'), ('.p-hard', 'hardEarly')):
        bg = re.search(r'background:\s*(#[0-9A-Fa-f]{6})', _rule(home, cls))[1]
        assert bg.upper() == surface[key].upper(), f'{cls} is {bg}, the season page uses {surface[key]}'


def _lum(hex_):
    def ch(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(hex_[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_panel_text_clears_aa_on_its_ground(home):
    """Grass and the hard-court blue are light enough that white type fails on
    them, which is why the season page switches to near-black there."""
    for cls in ('.p-clay', '.p-grass', '.p-hard', '.p-black'):
        rule = _rule(home, cls)
        bg = re.search(r'background:\s*(#[0-9A-Fa-f]{6})', rule)[1]
        ink = re.search(r'(?<![-\w])color:\s*(#[0-9A-Fa-f]{6})', rule)[1]
        hi, lo = sorted((_lum(bg), _lum(ink)), reverse=True)
        ratio = (hi + 0.05) / (lo + 0.05)
        assert ratio >= 4.5, f'{cls}: {ink} on {bg} is {ratio:.2f}:1'


def test_no_panel_text_is_faded(home):
    """Opacity blends the ink toward the ground and quietly undoes the ratio above."""
    for sel in ('.kicker', '.pname', '.pdesc', '.go'):
        assert 'opacity' not in _rule(home, sel), f'{sel} is faded'


def test_the_two_columns_are_the_same_width(home):
    cols = re.search(r'grid-template-columns:\s*([^;}]+)', _rule(home, '.board'))[1]
    assert re.fullmatch(r'repeat\(2,\s*minmax\(0,\s*1fr\)\)', cols.strip()), (
        f'the board columns are {cols!r}, so one side is wider than the other')


def test_the_arrow_stands_alone(home):
    arrows = re.findall(r'<span class="go"[^>]*>(.*?)</span>', home)
    assert arrows == ['&rarr;'] * 4, f'the arrows read {arrows}'


# ---- each page arrives on the colour its panel wears -----------------------

def _panel_colours(home):
    classes = dict((href, cls) for cls, href in
                   re.findall(r'<a class="panel (p-[\w-]+)" href="([^"]+)"', home))
    return {href: re.search(r'background:\s*(#[0-9A-Fa-f]{6})', _rule(home, '.' + cls))[1].upper()
            for href, cls in classes.items()}


def _ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize('name', ['tournament.html', 'matchup.html', 'ratings_board.html'])
def test_a_page_defaults_to_its_panel_colour(home, name):
    page = ROOT / name
    if not page.exists():
        pytest.skip(f'{name} is not built')
    text = page.read_text()
    m = re.search(r'body\{--page:(#[0-9A-Fa-f]{6})(?:;--page-ink:(#[0-9A-Fa-f]{6}))?', text)
    assert m, f'{name} does not set its own ground'
    ground, ink = m[1].upper(), (m[2] or '#FFFFFF').upper()
    assert ground == _panel_colours(home)[name], (
        f'{name} sits on {ground}; its home panel is {_panel_colours(home)[name]}')
    assert _ratio(ground, ink) >= 4.5, f'{name}: {ink} on {ground} is {_ratio(ground, ink):.2f}:1'


def test_the_season_page_rests_on_its_panel_colour(home):
    """The season page repaints its ground by surface as a run plays, so its
    DEFAULT is what has to match -- and applyGround picks the ink."""
    text = (ROOT / 'season.html').read_text()
    default = re.search(r'const DEFAULT_BG = SURFACE_BG\.(\w+);', text)[1]
    colour = re.search(rf"^\s*{default}:\s*'(#[0-9A-Fa-f]{{6}})'", text, re.M)[1].upper()
    assert colour == _panel_colours(home)['season.html'], (
        f'the season page rests on {default} {colour}')


def test_the_nav_does_not_assume_a_navy_ground():
    """On grass and the hard-court blue the type goes near-black; pills still drawn
    in translucent white would be invisible there. The shared theme must read
    the ground's tokens, and every page that repaints must set them all."""
    theme = (ROOT / 'simulation' / 'tournament_template.html').read_text()
    block = re.search(r'<style>(.*?)</style>', theme, re.S)[1]
    for sel in ('.navlink', '.navlink:hover', '.navlink.on', '.themebtn',
                '.themebtn:hover', '.linknote', '.navlink.on .sv'):
        body = _rule(block, sel)
        assert 'rgba(255,255,255' not in body and '#74CE8E' not in body, (
            f'{sel} hard-codes a colour meant for a navy ground')
    tokens = ['--pill-fill', '--pill-hover', '--pill-on', '--pill-edge', '--pill-dot', '--page-glow']
    season = (ROOT / 'simulation' / 'season_template.html').read_text()
    apply = re.search(r'function applyGround\(hex\)\{(.*?)\n\}', season, re.S)[1]
    for t in tokens:
        assert f"'{t}'" in apply, f'applyGround never sets {t}'
    for name in ('tournament.html', 'matchup.html'):
        text = (ROOT / name).read_text()
        rule = re.search(r'body\{--page:[^}]*\}', text)[0]
        for t in tokens:
            assert t + ':' in rule, f'{name} sits on a light ground but leaves {t} white'


# ---- the board follows the light/dark control ------------------------------

DARK_ROUTES = {
    'stamped': r':root\[data-theme="dark"\] ',
    'system': r':root:not\(\[data-theme="light"\]\) ',
}


def _dark_rule(home, route, sel):
    m = re.search(DARK_ROUTES[route] + re.escape(sel) + r'\s*\{([^}]*)\}', home)
    assert m, f'no {route} dark rule for {sel}'
    return m.group(1)


def _hex(rule, prop):
    m = re.search(r'(?<![-\w])' + re.escape(prop) + r':\s*(#[0-9A-Fa-f]{6})', rule)
    assert m, f'no {prop} in: {rule}'
    return m[1].upper()


def test_the_light_board_is_cream(home):
    assert _hex(_rule(home, '.board'), 'background') == '#F3EDD9'


@pytest.mark.parametrize('route', DARK_ROUTES)
def test_the_dark_board_is_grey_with_white_shadows(home, route):
    """Both routes into dark must agree, or the look depends on whether the
    toggle was pressed or the system asked -- the same split the theme-token
    tests guard against."""
    board = _hex(_dark_rule(home, route, '.board'), 'background')
    r, g, b = (int(board[i:i + 2], 16) for i in (1, 3, 5))
    assert max(r, g, b) - min(r, g, b) <= 8 and max(r, g, b) < 0x40, (
        f'{route}: {board} is not a dark grey')
    assert _hex(_dark_rule(home, route, '.panel'), '--psh') == '#FFFFFF', (
        f'{route}: the shadows are not white on the dark board')


@pytest.mark.parametrize('route', DARK_ROUTES)
def test_in_dark_the_ratings_panel_turns_cream_with_a_lavender_shadow(home, route):
    """Lavender read from the ratings board's own dark theme, not copied here."""
    board_page = (ROOT / 'ratings_board_template.html').read_text()
    stamped = re.search(r'^:root\[data-theme="dark"\]\{(.*?)^\}', board_page, re.S | re.M)[1]
    lavender = re.search(r'--wta:\s*(#[0-9A-Fa-f]{6})', stamped)[1].upper()
    rule = _dark_rule(home, route, '.p-black')
    bg, ink = _hex(rule, 'background'), _hex(rule, 'color')
    assert bg == '#FDF8E6', f'{route}: the ratings panel is {bg}, not cream'
    assert _hex(rule, '--psh') == lavender, (
        f'{route}: its shadow is {_hex(rule, "--psh")}, the board paints WTA in {lavender}')
    assert _ratio(bg, ink) >= 4.5, f'{route}: {ink} on {bg} is {_ratio(bg, ink):.2f}:1'
