import importlib.util
from pathlib import Path

from sportsedge.canonical_manual_mlb import CanonicalManualMLBError
from sportsedge.mlb_source import GameSnapshot

SPEC = importlib.util.spec_from_file_location(
    "run_manual_mlb_snapshot", Path("scripts/run_manual_mlb_snapshot.py")
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


def _snap(pk: int, when: str, away: str, home: str) -> GameSnapshot:
    return GameSnapshot(
        game_pk=pk,
        game_date=when,
        status="Scheduled",
        away_id=1,
        away_name=away,
        home_id=2,
        home_name=home,
        away_probable_pitcher_id=None,
        away_probable_pitcher_name=None,
        home_probable_pitcher_id=None,
        home_probable_pitcher_name=None,
        retrieved_at="2026-09-30T04:47:41+00:00",
    )


def _row(game_id: str, game_pk, first_pitch: str) -> dict:
    return {
        "game_id": game_id,
        "game_pk": game_pk,
        "market_type": "MONEYLINE",
        "side": "AWAY",
        "line": 0,
        "price": -117,
        "paired_side": "HOME",
        "paired_price": -103,
        "book": "draftkings",
        "observed_at": "2026-09-30T04:47:41+00:00",
        "first_pitch_at": first_pitch,
        "source": "MANUAL",
    }


def test_1256_shape_prices_bound_pk_and_isolates_forced_error(monkeypatch) -> None:
    phi_tue = _snap(101, "2026-09-29T17:20:00+00:00", "Philadelphia Phillies", "Atlanta Braves")
    phi_wed = _snap(202, "2026-09-30T17:20:00+00:00", "Philadelphia Phillies", "Atlanta Braves")
    cws = _snap(303, "2026-09-30T23:00:00+00:00", "Chicago White Sox", "Houston Astros")
    schedule = [phi_tue, phi_wed, cws]

    def fake_run(rows, *, history_cache_dir, schedule):
        scoped = list(schedule or [])
        if len(scoped) != 1:
            raise CanonicalManualMLBError(f"MANUAL_GAME_RESOLUTION_FAILED found={len(scoped)}")
        if rows[0]["game_id"].startswith("Chicago"):
            raise CanonicalManualMLBError("FORCED_FAIL")
        game = scoped[0]
        return {
            "resolved_game": {"game_pk": game.game_pk, "away_team": game.away_name, "home_team": game.home_name},
            "observed_at_utc": "2026-09-30T04:47:41+00:00",
            "market_resolution": [],
            "feature_lineage": [],
            "results": [{"game_id": str(game.game_pk), "ok": True}],
        }

    monkeypatch.setattr(MOD, "run_canonical_manual_mlb", fake_run)
    rows = [
        _row("Philadelphia Phillies@Atlanta Braves", 202, "2026-09-30T17:20:00+00:00"),
        _row("Chicago White Sox@Houston Astros", 303, "2026-09-30T23:00:00+00:00"),
    ]
    payload, blocked = MOD._run_canonical_rows(rows, history_cache_dir=".", schedule=schedule)
    priced_pks = []
    if payload.get("resolved_game"):
        priced_pks.append(payload["resolved_game"]["game_pk"])
    priced_pks.extend(g.get("resolved_game", {}).get("game_pk") for g in payload.get("games") or [])
    assert 202 in priced_pks
    assert 101 not in priced_pks
    assert any(item["reason"] == "FORCED_FAIL" for item in blocked)


def test_no_game_pk_without_snapshot_uses_old_path(monkeypatch) -> None:
    seen = {}

    def fake_run(rows, *, history_cache_dir, schedule):
        seen["schedule"] = schedule
        seen["game_pk"] = rows[0].get("game_pk")
        return {
            "resolved_game": {"game_pk": 999, "away_team": "A", "home_team": "B"},
            "observed_at_utc": "2026-09-30T04:47:41+00:00",
            "market_resolution": [],
            "feature_lineage": [],
            "results": [{"ok": True}],
        }

    monkeypatch.setattr(MOD, "run_canonical_manual_mlb", fake_run)
    rows = [_row("Philadelphia Phillies@Atlanta Braves", None, "2026-09-30T17:20:00+00:00")]
    payload, blocked = MOD._run_canonical_rows(rows, history_cache_dir=".", schedule=None)
    assert blocked == []
    assert seen["schedule"] is None
    assert payload.get("resolved_game", {}).get("game_pk") == 999
