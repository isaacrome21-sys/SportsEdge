from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import sportsedge.auto_joint_runner as auto_joint
import sportsedge.manual_hybrid_joint_runner as manual_hybrid
from sportsedge.auto_runner import _live_game
from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.mlb_joint_mode_bridge import build_feature_rows_for_quotes
from sportsedge.mlb_source import fetch_schedule
from sportsedge.quote_bridge import validate_canonical_quote
from sportsedge.unified_card import run_unified_card

UTC = timezone.utc
NOW = datetime(2026, 8, 11, 15, 0, tzinfo=UTC)
TARGET_DATE = date(2026, 8, 11)
KELLY = 0.25


class Resp:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


def schedule_payload():
    return {"dates": [{"date": TARGET_DATE.isoformat(), "games": [{"gamePk": 777,"gameDate": "2026-08-11T23:00:00Z","officialDate": TARGET_DATE.isoformat(),"gameNumber": 1,"doubleHeader": "N","venue": {"id": 10},"status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},"teams": {"away": {"team": {"id": 1, "name": "Away"}, "probablePitcher": {"id": 11, "fullName": "AP"}},"home": {"team": {"id": 2, "name": "Home"}, "probablePitcher": {"id": 22, "fullName": "HP"}}}}]}]}


def boxscore_payload():
    def players(start):
        return {f"ID{start + i}": {"person": {"id": start + i, "fullName": str(start + i)},"battingOrder": str((i + 1) * 100)} for i in range(9)}
    return {"teams": {"away": {"players": players(100)}, "home": {"players": players(200)}}}


def raw_quotes():
    common = {"game_id": "777","period": "FG","market": "MONEYLINE","entity_id": "777","line": 0.0,"book_key": "dk","sportsbook": "DraftKings","is_alternate": False,"raw_market_name": "Moneyline","retrieved_at": "2026-08-11T14:59:00Z","ttl_seconds": 300}
    return [{**common, "side": "HOME", "american_odds": -110, "offer_id": "home-ml"},{**common, "side": "AWAY", "american_odds": 100, "offer_id": "away-ml"}]


def team_history(team_id: int, season: int):
    runs = 4 if team_id == 1 else 5
    splits = []
    for i in range(12):
        month = 4 + (i // 4); day = 1 + (i % 4)
        splits.append({"date": f"{season}-{month:02d}-{day:02d}","stat": {"runs": runs, "homeRuns": 1}})
    return {"stats": [{"splits": splits}]}


def opener(req, timeout=15):
    url = req if isinstance(req, str) else req.full_url
    if url == "https://quotes": return Resp(raw_quotes())
    if "schedule?" in url: return Resp(schedule_payload())
    if "/boxscore" in url: return Resp(boxscore_payload())
    if "/teams/" in url and "/stats?" in url:
        parsed = urlparse(url); team_id = int(parsed.path.split("/teams/")[1].split("/")[0]); season = int(parse_qs(parsed.query)["season"][0])
        return Resp(team_history(team_id, season))
    raise AssertionError(url)


def canonical_quotes(): return [validate_canonical_quote(row) for row in raw_quotes()]
def live_game():
    snap = fetch_schedule(TARGET_DATE.isoformat(), opener=opener, now=NOW)[0]
    return _live_game(snap, boxscore=boxscore_payload(), projected={}, now=NOW)
def frozen_features(game, quotes):
    source = MLBGenericHistorySource(opener=opener, retrieved_at=NOW)
    return build_feature_rows_for_quotes(games=[game], quotes=quotes, source=source, target_date=TARGET_DATE)


def write_fixture_policy(root: Path):
    registry = root / "deployments.json"
    registry.write_text(json.dumps({"schema_version": 1,"markets": {"MONEYLINE": {"market": "MONEYLINE","eligible": True,"stage": "DEPLOYED","reason": "TEST_ONLY_PARITY_FIXTURE_NOT_PROMOTION_EVIDENCE"}}}), encoding="utf-8")
    floors = root / "truth_gate_floors.json"
    floors.write_text(json.dumps({"truth_gate": {"schema_version": 2,"production": {"fail_closed": True,"allow_cli_floor_override": False,"require_frozen_floor_for_eligible_market": True},"devig_policy": {"policy_id": "EDGE_FLOOR_DEVIG_V1","status": "FROZEN_PRE_DERIVATION","longshot_trigger_american_odds": 400,"longshot_trigger_rule": "EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400","sensitivity_methods": ["MULTIPLICATIVE_V1", "POWER_V1", "SHIN_V1"],"sensitivity_limit_absolute_probability_points": 0.01,"stable_candidate_estimator": "MULTIPLICATIVE_V1","longshot_candidate_estimator": "POWER_V1","haircut_probability_points": 0.0,"aggregation_rule": "ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS","sensitivity_failure": "BLOCK"},"edge_floors": {"MONEYLINE": {"status": "FROZEN","value_probability_points": 0.50,"method_version": "TEST_ONLY_PARITY_FIXTURE","evidence": {"evidence_sha256": "1" * 64,"derivation_code_sha256": "2" * 64,"oos_cutoff_utc": "2000-01-01T00:00:00Z"},"frozen": {"frozen_by_commit": "TEST_ONLY_NOT_A_PRODUCTION_PROMOTION"}}}}}), encoding="utf-8")
    return registry, floors


def core_snapshot(mock_call):
    kwargs = mock_call.call_args.kwargs
    return {"games": [asdict(g) for g in kwargs["games"]],"feature_rows": kwargs["feature_rows"],"quotes": kwargs["quotes"],"ingestion_now": kwargs["ingestion_now"],"finalization_now": kwargs["finalization_now"],"registry_path": kwargs["registry_path"],"require_confirmed_lineup": kwargs["require_confirmed_lineup"],"edge_floor_config_path": kwargs["edge_floor_config_path"],"kelly_multiplier": kwargs["kelly_multiplier"]}


def economics(rows):
    fields = ("game_id", "market", "entity_id", "line", "side", "american_odds","model_p", "model_input_hash", "distribution_sha256", "readout_sha256","implied_probability", "edge", "ev_per_dollar", "bet_status", "reason","book_key", "sportsbook", "quote_retrieved_at", "offer_id")
    return [tuple(getattr(row, field) for field in fields) for row in rows]


class MLBModeParityTests(unittest.TestCase):
    def test_manual_hybrid_automatic_normalize_to_identical_core_and_economics(self):
        game = live_game(); quotes = canonical_quotes(); frozen = frozen_features(game, quotes)
        self.assertEqual(len(frozen), 1, "paired prices must normalize to one predictive feature identity")
        with tempfile.TemporaryDirectory() as td:
            registry, floors = write_fixture_policy(Path(td))
            common = dict(games=[game], quotes=quotes, target_date=TARGET_DATE, now=NOW,registry_path=str(registry), require_confirmed_lineup=True,edge_floor_config_path=str(floors), kelly_multiplier=KELLY)
            with patch.object(manual_hybrid, "run_unified_card", wraps=run_unified_card) as manual_core:
                manual_results = manual_hybrid.run_manual_hybrid_joint_mlb(feature_rows=frozen, **common)
            manual_snapshot = core_snapshot(manual_core)
            with patch.object(manual_hybrid, "run_unified_card", wraps=run_unified_card) as hybrid_core:
                hybrid_results = manual_hybrid.run_manual_hybrid_joint_mlb(feature_rows=None, opener=opener, **common)
            hybrid_snapshot = core_snapshot(hybrid_core)
            with patch.object(auto_joint, "run_unified_card", wraps=run_unified_card) as auto_core:
                auto_report = auto_joint.run_auto_joint_mlb(quote_url="https://quotes", now=NOW, opener=opener,registry_path=str(registry), require_confirmed_lineup=True,edge_floor_config_path=str(floors), kelly_multiplier=KELLY)
            auto_snapshot = core_snapshot(auto_core)
        self.assertEqual(manual_snapshot, hybrid_snapshot); self.assertEqual(hybrid_snapshot, auto_snapshot)
        expected = economics(manual_results); self.assertEqual(expected, economics(hybrid_results)); self.assertEqual(expected, economics(auto_report.results))
        self.assertTrue(all(row.model_p is not None for row in manual_results)); self.assertTrue(all(row.implied_probability is not None for row in manual_results)); self.assertTrue(all(row.edge is not None and row.ev_per_dollar is not None for row in manual_results)); self.assertTrue(all(row.bet_status == "PASS" for row in manual_results))

    def test_production_policy_candidate_decision_is_mode_invariant(self):
        game = live_game(); quotes = canonical_quotes(); frozen = frozen_features(game, quotes)
        common = dict(games=[game], quotes=quotes, target_date=TARGET_DATE, now=NOW,require_confirmed_lineup=True, kelly_multiplier=KELLY)
        manual_results = manual_hybrid.run_manual_hybrid_joint_mlb(feature_rows=frozen, **common)
        hybrid_results = manual_hybrid.run_manual_hybrid_joint_mlb(feature_rows=None, opener=opener, **common)
        auto_results = auto_joint.run_auto_joint_mlb(quote_url="https://quotes", now=NOW, opener=opener,require_confirmed_lineup=True, kelly_multiplier=KELLY).results
        decisions = lambda rows: [(row.bet_status, row.reason) for row in rows]
        self.assertEqual(decisions(manual_results), decisions(hybrid_results)); self.assertEqual(decisions(hybrid_results), decisions(auto_results))
        self.assertTrue(all(row.bet_status == "MODEL_CANDIDATE" for row in manual_results))
        self.assertTrue(all(row.model_p is not None for row in manual_results))
        self.assertTrue(all("OFFICIAL_BLOCKED" in row.reason for row in manual_results))


if __name__ == "__main__":
    unittest.main()
