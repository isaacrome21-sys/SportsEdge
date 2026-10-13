"""Directory-completeness regression tests for PublicContext.teams (2026-10-13).

Defect (CFB coverage dry-run, COVERAGE.md §(b) item 2): the ESPN site team
directory for college-football holds 762 teams (live-verified), but the fetch
asked for limit=500, so identity resolution ran against a truncated
directory. SMU (2567), Tennessee (2633), Texas Tech (2641), Wyoming (2751),
Lindenwood (2815), Western Illinois (2710) and Southeast Missouri State
(2546) were absent from the fetched page and fixtures touching them failed
closed at ESPN_TEAM_IDENTITY_UNMATCHED even though ESPN has the teams.

Contract pinned here:
- A response that saturates the requested limit is indistinguishable from a
  truncated one: escalate once to the large limit; if that response also
  saturates, REFUSE (empty directory + DIRECTORY_TRUNCATED receipt) rather
  than resolving identities against a partial directory.
- A complete directory resolves every team it contains, by ID-bearing
  directory entries, including all seven teams named above.
- A directory that fits in the first page behaves exactly as before: one
  request, same URL, same results, no truncation receipt.
"""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MOD = Path(__file__).resolve().parents[1] / 'artifacts' / 'free_models.py'
spec = importlib.util.spec_from_file_location('free_models_directory', MOD)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)

NOW = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)

# The seven teams the truncated directory dropped, with the display names the
# live complete directory (limit=1000/2000, 762 teams) carries for them.
NAMED_TEAMS = [
    ('2567', 'SMU Mustangs'),
    ('2633', 'Tennessee Volunteers'),
    ('2641', 'Texas Tech Red Raiders'),
    ('2751', 'Wyoming Cowboys'),
    ('2815', 'Lindenwood Lions'),
    ('2710', 'Western Illinois Leathernecks'),
    ('2546', 'Southeast Missouri State Redhawks'),
]


def team_entry(team_id, display_name):
    return {'team': {'id': team_id, 'displayName': display_name,
                     'name': display_name, 'abbreviation': 'X'}}


def directory_payload(entries):
    return {'sports': [{'leagues': [{'teams': entries}]}]}


def server_getter(full_entries, calls):
    """Simulate the ESPN site server: it holds the full directory and
    truncates the response to the requested limit, exactly as live."""
    def getter(url):
        if '/teams?limit=' in url:
            calls.append(url)
            limit = int(parse_qs(urlparse(url).query)['limit'][0])
            return directory_payload(full_entries[:limit])
        raise AssertionError(f'unexpected fetch: {url}')
    return getter


def full_directory(total, named_first=False):
    named = [team_entry(tid, name) for tid, name in NAMED_TEAMS]
    filler = [team_entry(str(900000 + i), f'Filler Team {i}')
              for i in range(total - len(named))]
    return named + filler if named_first else filler + named


def test_complete_directory_resolves_all_seven_named_teams():
    # Live-verified true size of the college-football directory: 762 teams.
    # The seven named teams sit past position 500, as live: a limit=500 page
    # does not contain them.
    calls = []
    ctx = model.PublicContext(NOW, getter=server_getter(full_directory(762), calls))
    teams = ctx.teams('CFB')
    assert len(teams) == 762
    for team_id, display_name in NAMED_TEAMS:
        team = ctx.identify('CFB', display_name)
        assert team is not None, display_name
        assert str(team['id']) == team_id, display_name
    assert not any(r.get('reason') == 'DIRECTORY_TRUNCATED' for r in ctx.receipts)


def test_saturated_directory_refuses_with_directory_truncated():
    # A directory larger than even the escalated limit: both responses
    # saturate, so completeness can never be established. Identity
    # resolution must refuse, not run against a partial directory.
    calls = []
    ctx = model.PublicContext(
        NOW, getter=server_getter(full_directory(1500, named_first=True), calls))
    assert ctx.teams('CFB') == []
    assert ctx.identify('CFB', 'Filler Team 42') is None
    truncated = [r for r in ctx.receipts if r.get('reason') == 'DIRECTORY_TRUNCATED']
    # Each teams() consultation that refuses records its own receipt (the
    # teams() + identify() calls above); the contract is that the refusal is
    # always named, never silent.
    assert len(truncated) >= 1
    assert all(r['status'] == 'UNAVAILABLE' for r in truncated)
    assert '/teams?limit=' in truncated[0]['source']


def test_small_directory_single_page_behavior_unchanged():
    entries = [team_entry('1', 'Detroit Lions'),
               team_entry('2', 'Arizona Cardinals'),
               team_entry('3', 'Green Bay Packers')]
    calls = []
    ctx = model.PublicContext(NOW, getter=server_getter(entries, calls))
    assert [str(t['id']) for t in ctx.teams('NFL')] == ['1', '2', '3']
    team = ctx.identify('NFL', 'Green Bay Packers')
    assert team is not None and str(team['id']) == '3'
    # Exactly one request, at the historical URL: no escalation, no receipt.
    assert len(calls) == 1 and calls[0].endswith('/teams?limit=500')
    assert not any(r.get('reason') == 'DIRECTORY_TRUNCATED' for r in ctx.receipts)


def test_directory_fetch_failure_still_fails_closed_without_escalation():
    calls = []

    def failing_getter(url):
        calls.append(url)
        raise OSError('network down')

    ctx = model.PublicContext(NOW, getter=failing_getter)
    assert ctx.teams('CFB') == []
    assert ctx.identify('CFB', 'SMU Mustangs') is None
    assert len(calls) == 1  # a failed fetch is empty, not saturated: no retry
    assert any(r.get('status') == 'UNAVAILABLE' for r in ctx.receipts)
    assert not any(r.get('reason') == 'DIRECTORY_TRUNCATED' for r in ctx.receipts)
