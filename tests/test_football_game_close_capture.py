from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/capture_football_game_closes.py"
SPEC = importlib.util.spec_from_file_location("football_game_close_capture", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _policy() -> dict:
    return json.loads((ROOT / "config/football_game_close_policy_v1.json").read_text())


def _row(start: str = "2026-09-11T20:00:00+00:00") -> dict:
    return {
        "evidence_id": "ev-1",
        "sport": "CFB",
        "game_id": "game-1",
        "provider_home_team": "Home",
        "provider_away_team": "Away",
        "game_start_ts": start,
        "qualifies_for_evidence": True,
    }


def test_policy_freezes_named_book_and_devig() -> None:
    policy = _policy()
    assert policy["sports"]["CFB"]["bookmaker"] == "draftkings"
    assert policy["sports"]["NFL"]["bookmaker"] == "draftkings"
    assert policy["pricing"]["devig_method"] == "POWER_V1"
    assert policy["pricing"]["book_switching_allowed_within_evidence_unit"] is False
    assert policy["capture"]["missing_rule"] == "CLOSE_MISSED"


def test_close_key_never_falls_back_to_shared_odds_key(monkeypatch) -> None:
    monkeypatch.delenv("SPORTSEDGE_FOOTBALL_CLOSE_ODDS_API_KEY", raising=False)
    monkeypatch.setenv("SPORTSEDGE_ODDS_API_KEY", "shared-reserve-key")
    assert mod._close_api_key() == ""
    monkeypatch.setenv("SPORTSEDGE_FOOTBALL_CLOSE_ODDS_API_KEY", "dedicated-close-key")
    assert mod._close_api_key() == "dedicated-close-key"


def test_finalizer_selects_last_valid_prestart_observation(tmp_path: Path) -> None:
    row = _row()
    obs_dir, final_path = mod._dirs(tmp_path, row)
    obs_dir.mkdir(parents=True)
    for stamp, odds in (("2026-09-11T19:47:00+00:00", -110), ("2026-09-11T19:56:00+00:00", -115)):
        payload = {
            "observed_at": stamp,
            "bookmaker": "draftkings",
            "markets": [{"key": "h2h", "outcomes": [{"name": "Home", "price": odds}]}],
            "observation_sha256": f"sha-{odds}",
        }
        name = stamp.replace(":", "").replace("+00", "Z") + ".json"
        (obs_dir / name).write_text(json.dumps(payload))
    changed = mod._finalize(
        row=row,
        policy=_policy(),
        ledger=tmp_path,
        now=datetime(2026, 9, 11, 20, 1, tzinfo=timezone.utc),
    )
    assert changed is True
    final = json.loads(final_path.read_text())
    assert final["status"] == "CAPTURED"
    assert final["selected_observed_at"] == "2026-09-11T19:56:00+00:00"
    assert final["observation_sha256"] == "sha--115"


def test_finalizer_marks_missing_close_without_backfill(tmp_path: Path) -> None:
    row = _row()
    _, final_path = mod._dirs(tmp_path, row)
    changed = mod._finalize(
        row=row,
        policy=_policy(),
        ledger=tmp_path,
        now=datetime(2026, 9, 11, 20, 1, tzinfo=timezone.utc),
    )
    assert changed is True
    final = json.loads(final_path.read_text())
    assert final["status"] == "CLOSE_MISSED"
    assert "markets" not in final


def test_candidate_filter_requires_explicit_evidence_qualification(tmp_path: Path) -> None:
    path = tmp_path / "candidates.json"
    row = _row()
    row["qualifies_for_evidence"] = False
    path.write_text(json.dumps({"candidates": [row]}))
    assert mod._candidate_rows(path) == []
