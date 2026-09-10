"""Inline the shared chrome -- the 'About this site' panel and the footer.

The panel explains how match statistics become the published ratings, and has
to read the same on all three pages. It lives in simulation/sitenote.html and is
substituted in at build time rather than pasted into each template, because
three copies of one paragraph drift apart.

The ratings board is the awkward one: it is written by the notebook, which
substitutes only its own data marker, so its page is patched here after the
fact. tests/test_sitenote.py checks all three built pages carry the panel.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'simulation' / 'sitenote.html'
FOOT_SOURCE = ROOT / 'simulation' / 'sitefoot.html'
MARKER = '<!--__SITENOTE__-->'

# The page-specific footers this replaces. Two pages carried a full one and the
# season page carried none at all -- no copyright, no disclaimer -- which is
# exactly the drift a shared fragment exists to stop.
OLD_FOOTER = re.compile(r'[ \t]*<footer class="foot">.*?</footer>\n?', re.S)

# The shared footer as it appears once inlined -- its leading comment, its style
# block and the footer itself. Matched so a page that ALREADY carries it is
# refreshed from source rather than skipped: the ratings board is written by the
# notebook and patched afterwards, so skipping it left the board a version
# behind the other two the first time the footer changed. A fragment that exists
# to stop drift has to overwrite, not step around.
SHARED_FOOTER = re.compile(
    r'(?:<!--(?:(?!-->).)*?-->\s*)?<style>\s*\.sitefoot\{.*?</footer>', re.S)


def html() -> str:
    return SOURCE.read_text()


def foot_html() -> str:
    return FOOT_SOURCE.read_text()


def inline(page: str) -> str:
    """Add the About panel and the shared footer to a built page.

    Idempotent: running a build twice never doubles either up. The footer is
    rewritten from source each time rather than left alone, so a page built by
    some other route still picks up a change to the shared fragment.
    """
    if MARKER in page:
        page = page.replace(MARKER, html())
    elif 'id="snwrap"' not in page:
        page = page + '\n' + html()

    foot = foot_html()
    if SHARED_FOOTER.search(page):
        page = SHARED_FOOTER.sub(lambda _: foot.strip(), page, count=1)
    elif OLD_FOOTER.search(page):
        # a page with its own footer has it replaced in place, so the shared one
        # lands where the old one sat rather than after the closing markup
        page = OLD_FOOTER.sub(lambda _: foot, page, count=1)
    else:
        page = page + '\n' + foot
    return page


def inline_file(path: Path) -> bool:
    before = path.read_text()
    after = inline(before)
    if after != before:
        path.write_text(after)
        return True
    return False
