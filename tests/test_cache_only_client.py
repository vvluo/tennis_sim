"""The site deploy runs without a Sportradar key, and must keep working.

.github/workflows/deploy-site.yml rebuilds the pages from committed ratings and
the restored cache, with no secret in the environment and a budget of zero. That
only works if Client defers resolving its key until a live request is actually
due -- constructing one used to demand a key it would never send, which failed
the deploy.
"""

from __future__ import annotations

import gzip
import json

import pytest

import sportradar_data as sd


@pytest.fixture
def keyless(monkeypatch, tmp_path):
    """No key anywhere: not in the environment, not on disk."""
    monkeypatch.delenv('SPORTRADAR_API_KEY', raising=False)
    monkeypatch.setattr(sd, 'KEY_FILE', tmp_path / 'absent')
    return tmp_path


def test_client_constructs_without_a_key(keyless):
    sd.Client(budget=0, cache_dir=keyless)          # must not raise


def test_cache_hit_needs_no_key(keyless):
    client = sd.Client(budget=0, cache_dir=keyless)
    with gzip.open(client._cache_path('demo'), 'wt') as fh:
        json.dump({'rankings': [{'name': 'ATP'}]}, fh)
    assert client.get('anything.json', cache_key='demo')['rankings'][0]['name'] == 'ATP'
    assert 'x-api-key' not in client._session.headers


def test_cache_miss_reports_the_budget_not_the_key(keyless):
    """The budget check must come first, or the deploy blames the wrong thing."""
    client = sd.Client(budget=0, cache_dir=keyless)
    with pytest.raises(sd.BudgetExceeded):
        client.get('anything.json', cache_key='not_cached')


def test_a_live_call_still_requires_a_key(keyless):
    client = sd.Client(budget=5, cache_dir=keyless)
    with pytest.raises(RuntimeError, match='No API key'):
        client.get('anything.json', cache_key='not_cached')


def test_env_budget_is_a_ceiling(monkeypatch, keyless):
    """--budget has to cap the notebook's hardcoded Client(budget=520)."""
    monkeypatch.setenv('SPORTRADAR_BUDGET', '60')
    assert sd.Client(budget=520, cache_dir=keyless).budget == 60
    assert sd.Client(budget=0, cache_dir=keyless).budget == 0
    monkeypatch.setenv('SPORTRADAR_BUDGET', '900')
    assert sd.Client(budget=300, cache_dir=keyless).budget == 300


def test_access_level_follows_the_key(monkeypatch, keyless):
    """A production key aimed at /trial/ is rejected like a bad key."""
    monkeypatch.delenv('SPORTRADAR_ACCESS_LEVEL', raising=False)
    assert '/trial/' in sd.Client(budget=0, cache_dir=keyless).base
    monkeypatch.setenv('SPORTRADAR_ACCESS_LEVEL', 'production')
    assert '/production/' in sd.Client(budget=0, cache_dir=keyless).base
    assert '/trial/' in sd.Client(budget=0, cache_dir=keyless, access_level='trial').base
