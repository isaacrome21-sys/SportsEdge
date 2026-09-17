import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "nfl_forward_accrual", ROOT / "scripts" / "check_nfl_forward_accrual.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


class NFLForwardAccrualTests(unittest.TestCase):
    SHA = "1" * 40
    ARTIFACT = "2" * 64
    SOURCE = "3" * 64
    SNAPSHOT = "4" * 64
    GAME = "2026_02_TEST_A_TEST_B"
    START = "2026-09-18T00:20:00+00:00"

    def _schedule(self, root: Path) -> Path:
        path = root / "games.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["game_id", "season", "game_type", "gameday", "gametime"],
            )
            writer.writeheader()
            writer.writerow({
                "game_id": self.GAME,
                "season": "2026",
                "game_type": "REG",
                "gameday": "2026-09-17",
                "gametime": "20:20",
            })
        return path

    def _decision(self, market: str, gate: str = "SHADOW_QUALIFIED") -> dict:
        side = {"moneyline": "TEST_A", "spread": "TEST_A", "total": "over"}[market]
        return {
            "decision_ts": "2026-09-17T22:40:00+00:00",
            "game_start_ts": self.START,
            "game_id": self.GAME,
            "sport": "nfl",
            "market": market,
            "side": side,
            "book": "draftkings",
            "line_at_decision": None if market == "moneyline" else (-3.0 if market == "spread" else 47.5),
            "gate_result": gate,
            "selection_contract": "NFL_FORWARD_SHADOW_EV_V1",
            "provider_event_id": "provider-event-1",
            "provider_event_snapshot_sha256": self.SNAPSHOT,
            "code_git_sha": self.SHA,
            "model_artifact_sha256": self.ARTIFACT,
            "live_feature_source_manifest_sha256": self.SOURCE,
        }

    def _close(self, decision: dict) -> dict:
        return {
            "close_ts": "2026-09-18T00:10:00+00:00",
            "game_start_ts": self.START,
            "game_id": self.GAME,
            "sport": "nfl",
            "market": decision["market"],
            "side": decision["side"],
            "book": "draftkings",
            "probability_line": decision["line_at_decision"],
            "provider_event_id": decision["provider_event_id"],
            "provider_event_snapshot_sha256": "5" * 64,
            "code_git_sha": self.SHA,
            "model_artifact_sha256": self.ARTIFACT,
            "live_feature_source_manifest_sha256": self.SOURCE,
        }

    def _state(self, root: Path, decisions: list[dict], closes: list[dict] | None = None) -> Path:
        state_root = root / "runtime/nfl-forward"
        release = state_root / self.SHA
        release.mkdir(parents=True)
        (release / "release.json").write_text(json.dumps({
            "schema_version": 1,
            "model_code_git_sha": self.SHA,
            "model_artifact_sha256": self.ARTIFACT,
        }), encoding="utf-8")
        (release / "decisions.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in decisions), encoding="utf-8"
        )
        if closes is not None:
            (release / "closes.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in closes), encoding="utf-8"
            )
        return state_root

    def _complete(self, gate: str = "SHADOW_QUALIFIED") -> list[dict]:
        return [self._decision(market, gate) for market in ("moneyline", "spread", "total")]

    def test_no_due_window_is_not_expected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = MOD.forward_liveness(
                root / "runtime/nfl-forward",
                self._schedule(root),
                MOD._now("2026-09-17T18:00:00Z"),
                4.0,
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["evidence_state"], "NOT_EXPECTED")

    def test_due_decision_without_durable_rows_fails_even_if_runner_could_be_green(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = MOD.forward_liveness(
                root / "runtime/nfl-forward",
                self._schedule(root),
                MOD._now("2026-09-17T23:36:00Z"),
                4.0,
            )
            self.assertEqual(report["evidence_state"], "NO_ACCRUAL")
            self.assertIn(f"NFL_FORWARD_ZERO_VALID_DECISIONS:game={self.GAME}", report["failures"])

    def test_complete_contract_valid_decision_set_accrues(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = self._state(root, self._complete())
            report = MOD.forward_liveness(
                state,
                self._schedule(root),
                MOD._now("2026-09-17T23:36:00Z"),
                4.0,
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["evidence_state"], "ACCRUED")
            self.assertEqual(report["decision_accrued_games"], 1)

    def test_bad_source_hash_does_not_count_as_accrual(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decisions = self._complete()
            decisions[0]["live_feature_source_manifest_sha256"] = "bad"
            state = self._state(root, decisions)
            report = MOD.forward_liveness(
                state,
                self._schedule(root),
                MOD._now("2026-09-17T23:36:00Z"),
                4.0,
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["decision_accrued_games"], 0)

    def test_due_qualifying_close_without_durable_row_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decisions = self._complete()
            state = self._state(root, decisions, [])
            report = MOD.forward_liveness(
                state,
                self._schedule(root),
                MOD._now("2026-09-18T00:19:00Z"),
                4.0,
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["close_expected_rows"], 3)
            self.assertEqual(report["close_accrued_rows"], 0)
            self.assertTrue(any(x.startswith("NFL_FORWARD_ZERO_OR_INVALID_CLOSE:") for x in report["failures"]))

    def test_contract_valid_due_closes_accrue(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decisions = self._complete()
            closes = [self._close(row) for row in decisions]
            state = self._state(root, decisions, closes)
            report = MOD.forward_liveness(
                state,
                self._schedule(root),
                MOD._now("2026-09-18T00:19:00Z"),
                4.0,
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["evidence_state"], "ACCRUED")
            self.assertEqual(report["close_accrued_rows"], 3)

    def test_rejected_decisions_do_not_create_close_obligation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decisions = self._complete("REJECTED_NO_POSITIVE_EV")
            state = self._state(root, decisions, [])
            report = MOD.forward_liveness(
                state,
                self._schedule(root),
                MOD._now("2026-09-18T00:19:00Z"),
                4.0,
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["close_expected_rows"], 0)
            self.assertEqual(report["decision_accrued_games"], 1)


if __name__ == "__main__":
    unittest.main()
