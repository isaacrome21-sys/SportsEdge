"""Offline tests for the StatsAPI history acquisition (no network)."""
import json

import pytest

from sportsedge import statsapi_history as sh


def _sched(games):
    return {"dates": [{"games": [
        {"gamePk": pk, "gameType": "R",
         "status": {"abstractGameState": st, "detailedState": det}}
        for pk, st, det in games]}]}


def _log(rows):
    return {"stats": [{"splits": [
        {"game": {"gamePk": pk}, "stat": {"gamesStarted": gs}} for pk, gs in rows]}]}


def test_complete_requires_exactly_two_starters_and_no_failures():
    final = sh.final_regular_games([_sched([(1, "Final", "Final"),
                                            (2, "Final", "Final"),
                                            (3, "Preview", "Scheduled"),
                                            (4, "Final", "Postponed")])])
    assert final == {1, 2}
    starts = sh.starts_by_game([_log([(1, 1), (2, 1)]), _log([(1, 1), (2, 1), (2, 0)])])
    assert sh.completeness(final, starts, [])["status"] == "COMPLETE"


def test_missing_starter_is_incomplete_and_listed():
    final = {1, 2}
    starts = sh.starts_by_game([_log([(1, 1), (1, 1), (2, 1)])])
    c = sh.completeness(final, starts, [])
    assert c["status"] == "INCOMPLETE" and c["games_with_one_starter"] == [2]


def test_any_fetch_failure_is_incomplete():
    starts = sh.starts_by_game([_log([(1, 1), (1, 1)])])
    c = sh.completeness({1}, starts, [{"url": "x", "error": "e"}])
    assert c["status"] == "INCOMPLETE" and c["fetch_failures"] == 1


def test_acquire_records_failures_never_drops_them():
    def fetch(url):
        if "bad" in url:
            raise RuntimeError("boom")
        return b'{"ok":1}'
    recs, fails = sh.acquire(["u/good", "u/bad"], fetch)
    assert [r["url"] for r in recs] == ["u/good"]
    assert fails and fails[0]["url"] == "u/bad"
    assert recs[0]["sha256"] == sh.sha256_bytes(b'{"ok":1}')


def test_bundle_is_deterministic_and_verified(tmp_path):
    recs = [{"url": "b", "retrieved_at_utc": "t", "sha256": sh.sha256_bytes(b"{}"), "body": "{}"},
            {"url": "a", "retrieved_at_utc": "t", "sha256": sh.sha256_bytes(b"[]"), "body": "[]"}]
    h1 = sh.write_bundle(str(tmp_path / "x.gz"), recs)
    h2 = sh.write_bundle(str(tmp_path / "y.gz"), list(reversed(recs)))
    assert h1 == h2
    assert [r["url"] for r in sh.read_bundle(str(tmp_path / "x.gz"))] == ["a", "b"]


def test_tampered_bundle_rejected(tmp_path):
    recs = [{"url": "a", "retrieved_at_utc": "t", "sha256": "0" * 64, "body": "{}"}]
    sh.write_bundle(str(tmp_path / "x.gz"), recs)
    with pytest.raises(ValueError):
        sh.read_bundle(str(tmp_path / "x.gz"))


def test_rate_limiter_waits_and_retries():
    slept, t = [], [0.0]
    calls = {"n": 0}

    def raw(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient")
        return b"{}"
    f = sh.RateLimitedFetcher(raw, min_interval=0.25, sleep=slept.append, clock=lambda: t[0])
    assert f("u") == b"{}"
    assert calls["n"] == 2 and slept  # retried after a backoff sleep


def test_pitcher_ids_and_manifest_labels():
    body = {"people": [{"id": 5, "primaryPosition": {"abbreviation": "P"}},
                       {"id": 7, "primaryPosition": {"abbreviation": "SS"}},
                       {"id": 9, "primaryPosition": {"abbreviation": "TWP"}}]}
    assert sh.pitcher_ids(body) == [5, 9]
    m = sh.manifest(2026, {}, {}, {"status": "COMPLETE"}, [], "Copyright 2026 MLB", {})
    assert m["provenance_label"] == "ACQUIRED_POSTHOC_FROM_PUBLIC_STATSAPI"
    assert "PREGAME_SNAPSHOT" in m["is_not"] and "ISSUE_2344_RECOVERED_ORIGINAL" in m["is_not"]
    assert json.dumps(m)  # serializable


def test_cancelled_final_games_are_not_counted_as_played():
    # Observed in real data: 2024 HOU@CLE (746577) and 2026 BAL@NYY (823490)
    # are abstractGameState=Final, detailedState=Cancelled, with no starters.
    final = sh.final_regular_games([_sched([(746577, "Final", "Cancelled"),
                                            (1, "Final", "Final")])])
    assert final == {1}


def test_hitters_and_boxscore_completeness():
    body = {"people": [{"id": 5, "primaryPosition": {"type": "Pitcher"}},
                       {"id": 7, "primaryPosition": {"type": "Infielder"}},
                       {"id": 9, "primaryPosition": {"type": "Two-Way Player"}}]}
    assert sh.hitter_ids(body) == [7, 9]
    assert sh.hitting_log_url(7, 2026).endswith("group=hitting&season=2026")
    starts = sh.starts_by_game([_log([(1, 1), (1, 1)])])
    assert sh.completeness({1}, starts, [], boxscore_games={1})["status"] == "COMPLETE"
    c = sh.completeness({1}, starts, [], boxscore_games=set())
    assert c["status"] == "INCOMPLETE" and c["games_missing_boxscore"] == [1]
