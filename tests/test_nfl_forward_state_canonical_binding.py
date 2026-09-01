from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_nfl_forward_state.py"
spec = importlib.util.spec_from_file_location("update_nfl_forward_state", SCRIPT)
state = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(state)

UTC = timezone.utc
CAPTURED = datetime(2026, 9, 10, 23, 10, tzinfo=UTC)
MODEL_SHA = "1" * 40
MODEL_HASH = "b" * 64
SOURCE_HASH = "a" * 64


def _features(*games):
    return {
        "schema_version": 3,
        "sport": "nfl",
        "asof_ts": "2026-09-10T23:00:00+00:00",
        "source_manifest_sha256": SOURCE_HASH,
        "games": list(games),
    }


def _game(game_id):
    return {
        "game_id": game_id,
        "game_start_ts": "2026-09-11T00:20:00+00:00",
        "home_team": "ALP",
        "away_team": "BET",
        "provider_home_team": "Alpha Aces",
        "provider_away_team": "Beta Bears",
    }


def _rows(game_id):
    return [
        {"game_id": game_id, "market": "moneyline", "side": "ALP", "book": "draftkings", "gate_result": "SHADOW_QUALIFIED"},
        {"game_id": game_id, "market": "spread", "side": "ALP", "book": "draftkings", "gate_result": "SHADOW_QUALIFIED"},
        {"game_id": game_id, "market": "total", "side": "over", "book": "draftkings", "gate_result": "REJECTED_NO_POSITIVE_EV"},
    ]


class NFLForwardStateCanonicalBindingTests(unittest.TestCase):
    def test_decision_mode_routes_only_new_games_through_canonical_live_core(self):
        old_game = "2026_01_OLD_ALP"
        new_game = "2026_01_NEW_ALP"
        existing = _rows(old_game)
        features = _features(_game(old_game), _game(new_game))
        events = [{"id": "evt-new"}]
        artifact = {"model_id": "nfl_m2_ridge_v1", "feature_contract": "NFL_M2_V1_MARKET_BLIND"}
        model = object()
        written = []

        def read_json(path):
            return features if Path(path).name == "features.json" else events

        def read_jsonl(path):
            return list(existing) if Path(path).name == "decisions.jsonl" else []

        def write_jsonl(path, rows):
            written.append((Path(path).name, list(rows)))

        with (
            patch.object(state, "_release", return_value=(artifact, MODEL_SHA, MODEL_HASH)),
            patch.object(state, "_bind_release"),
            patch.object(state, "load_nfl_m2_model_artifact", return_value=model),
            patch.object(state, "_json", side_effect=read_json),
            patch.object(state, "_jsonl", side_effect=read_jsonl),
            patch.object(state, "_write_jsonl", side_effect=write_jsonl),
            patch.object(state, "run_canonical_nfl_live", return_value=_rows(new_game)) as canonical,
        ):
            result = state.decision_mode(
                Path("state"), Path("model.json"), Path("features.json"), Path("odds.json"), CAPTURED
            )

        canonical.assert_called_once()
        kwargs = canonical.call_args.kwargs
        self.assertIs(kwargs["model"], model)
        self.assertEqual(kwargs["live_features"]["source_manifest_sha256"], SOURCE_HASH)
        self.assertEqual([row["game_id"] for row in kwargs["live_features"]["games"]], [new_game])
        self.assertEqual(kwargs["odds_events"], events)
        self.assertEqual(kwargs["captured_at"], CAPTURED)
        self.assertEqual(kwargs["identity"], {
            "code_git_sha": MODEL_SHA,
            "model_id": artifact["model_id"],
            "feature_contract": artifact["feature_contract"],
            "model_artifact_sha256": MODEL_HASH,
        })
        self.assertEqual(result["added_decisions"], 3)
        self.assertEqual(result["decision_row_count"], 6)
        self.assertEqual(len(written), 1)
        self.assertEqual([row["game_id"] for row in written[0][1]], [old_game] * 3 + [new_game] * 3)

    def test_partial_existing_game_still_fails_before_canonical_runner(self):
        game_id = "2026_01_BET_ALP"
        features = _features(_game(game_id))
        partial = _rows(game_id)[:2]

        def read_json(path):
            return features if Path(path).name == "features.json" else []

        def read_jsonl(path):
            return list(partial) if Path(path).name == "decisions.jsonl" else []

        with (
            patch.object(state, "_release", return_value=({"model_id":"nfl_m2_ridge_v1","feature_contract":"NFL_M2_V1_MARKET_BLIND"}, MODEL_SHA, MODEL_HASH)),
            patch.object(state, "_bind_release"),
            patch.object(state, "load_nfl_m2_model_artifact", return_value=object()),
            patch.object(state, "_json", side_effect=read_json),
            patch.object(state, "_jsonl", side_effect=read_jsonl),
            patch.object(state, "run_canonical_nfl_live") as canonical,
        ):
            with self.assertRaisesRegex(SystemExit, f"NFL_FORWARD_STATE_PARTIAL_GAME_DECISION:{game_id}"):
                state.decision_mode(
                    Path("state"), Path("model.json"), Path("features.json"), Path("odds.json"), CAPTURED
                )
        canonical.assert_not_called()


if __name__ == "__main__":
    unittest.main()
