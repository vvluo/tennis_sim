"""Build home.html -- the landing page.

A title, a line of description, and the four features as panels. Pure assembly:
no data, no API calls. The theme and the About panel come from the same sources
the other pages use, so the frame and the navbar sit exactly where they do on
every other tab.

    python run_home.py --out home.html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import sitenote
from run_season import theme_css

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / 'simulation' / 'home_template.html'
THEME = '/*__THEME__*/'


def build(out: Path) -> Path:
    page = TEMPLATE.read_text().replace(THEME, theme_css())
    page = sitenote.inline(page)
    if THEME in page:
        raise SystemExit(f'{THEME} was not substituted')
    if sitenote.MARKER in page:
        raise SystemExit('the About panel marker was not substituted')
    out.write_text(page)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default='home.html')
    args = ap.parse_args()
    out = build(Path(args.out))
    print(f'wrote {out}  ({out.stat().st_size / 1024:.0f} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
