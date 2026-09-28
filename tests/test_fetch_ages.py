"""Ages for the ranked field: free on the WTA side, a call per player on the ATP.

Nothing here touches the network. The budget guard is the point of most of it:
a trial month is about a thousand calls, and an accidental full-field pull would
spend half of it and leave the weekly refresh unable to run.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fetch_ages  # noqa: E402


def test_a_birth_date_is_found_wherever_the_feed_puts_it():
    """Sportradar returns it under `info` on some tiers and on the competitor on
    others; a parser that knew only one shape would silently find no ages at all
    and the run would look like a feed with no dates rather than a bug."""
    assert fetch_ages.dob_from_profile({'info': {'date_of_birth': '1998-05-05'}}) == '1998-05-05'
    assert fetch_ages.dob_from_profile(
        {'competitor': {'date_of_birth': '2001-05-31'}}) == '2001-05-31'
    assert fetch_ages.dob_from_profile({'date_of_birth': '1990-01-02'}) == '1990-01-02'
    assert fetch_ages.dob_from_profile({'competitor': {'name': 'X'}}) is None
    assert fetch_ages.dob_from_profile({}) is None


def test_an_age_is_measured_from_the_snapshot():
    # A birthday exactly N years back must come out at N; the fractional case is
    # checked as a range, because 22.45 rounds either way depending on the float
    # and pinning the digit would be testing the rounding, not the arithmetic.
    assert fetch_ages.years('2000-01-01', date(2026, 1, 1)) == pytest.approx(26.0, abs=0.05)
    mid = fetch_ages.years('2004-03-13', date(2026, 8, 25))
    assert 22.3 < mid < 22.6, mid


def test_the_wta_side_costs_nothing_and_covers_the_field():
    """The registry is on disk, so these need no API call at all. If this ever
    collapses, the fix is a name join -- not spending the ATP's budget twice."""
    _snapshot, rows = fetch_ages.ranked(limit_atp=250)
    women = [r for r in rows if r[0] == 'WTA']
    found = fetch_ages.wta_ages(rows)
    assert len(women) >= 400, 'the snapshot has no WTA field to match against'
    assert len(found) / len(women) > 0.90, (
        f'only {len(found)}/{len(women)} women matched the registry')
    for name, dob in found.items():
        assert re.fullmatch(r'(19|20)\d{2}-\d{2}-\d{2}', dob), f'{name}: {dob}'


@pytest.fixture
def empty_cache(tmp_path, monkeypatch):
    """Point the script's client at a cache with nothing in it.

    Otherwise these two say nothing: once the profiles are on disk the run costs
    zero calls, so there is no budget left to refuse and the guard is never
    reached. cache_dir is bound as a default argument at import, so the client
    itself has to be replaced rather than the module's CACHE_DIR patched.
    """
    import sportradar_data
    real = sportradar_data.Client
    monkeypatch.setattr(sportradar_data, 'Client',
                        lambda **kw: real(cache_dir=tmp_path, **kw))
    return tmp_path


def test_no_atp_profile_is_fetched_without_a_budget_for_it(empty_cache, tmp_path, monkeypatch):
    """The guard that stops a quarter of a trial month going out by accident."""
    out = tmp_path / 'ages.json'
    monkeypatch.setattr(sys, 'argv',
                        ['fetch_ages.py', '--top', '250', '--budget', '0',
                         '--out', str(out)])
    with pytest.raises(SystemExit) as e:
        fetch_ages.main()
    assert 'budget' in str(e.value).lower(), f'refused for the wrong reason: {e.value}'
    assert not out.exists(), 'a refused run still wrote its output'


def test_a_dry_run_spends_nothing_and_writes_nothing(empty_cache, tmp_path, monkeypatch, capsys):
    out = tmp_path / 'ages.json'
    monkeypatch.setattr(sys, 'argv',
                        ['fetch_ages.py', '--top', '250', '--dry-run', '--out', str(out)])
    assert fetch_ages.main() == 0
    assert not out.exists()
    printed = capsys.readouterr().out
    assert 'dry run' in printed
    assert '250 to fetch' in printed, printed
