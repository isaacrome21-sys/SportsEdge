#!/usr/bin/env python3
"""Run a zero-authority MLB MONEYLINE SHADOW_P / PAPER card.

The predictive side uses the same market-blind SportsEdge MONEYLINE engine and
live-observed MLB StatsAPI history as the production-parity forward predictor.
DraftKings prices are optional manual inputs and are used only after the model
probability has been produced. Output is written only under ``artifacts/`` by
default and grants no Model_P, Truth Gate, promotion, evidence, staking, or
OFFICIAL authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from math import isfinite
import os
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.mlb_moneyline_forward_prediction import (
    DEFAULT_SIMULATIONS,
    build_forward_prediction,
)
from sportsedge.mlb_source import fetch_schedule

CHICAGO_TZ = ZoneInfo("America/Chicago")
DEFAULT_OUTPUT = "artifacts/mlb/mlb_moneyline_shadow_card.json"
SCHEMA_VERSION = "MLB_MONEYLINE_SHADOW_CARD_V1"


class MLBShadowCardError(ValueError):
    pass


def american_implied(odds: float) -> float:
    value = float(odds)
    if not isfinite(value) or value == 0:
        raise MLBShadowCardError("American odds must be finite and non-zero")
    return 100.0 / (100.0 + value) if value > 0 else (-value) / ((-value) + 100.0)


def american_decimal(odds: float) -> float:
    value = float(odds)
    if not isfinite(value) or value == 0:
        raise MLBShadowCardError("American odds must be finite and non-zero")
    return 1.0 + (value / 100.0 if value > 0 else 100.0 / (-value))


def fair_american(probability: float) -> float:
    p = float(probability)
    if not isfinite(p) or not 0.0 < p < 1.0:
        raise MLBShadowCardError("probability must be strictly between 0 and 1")
    if p >= 0.5:
        return -100.0 * p / (1.0 - p)
    return 100.0 * (1.0 - p) / p


def price_side(probability: float, odds: float) -> dict[str, float]:
    p = float(probability)
    decimal = american_decimal(odds)
    implied = american_implied(odds)
    ev = p * (decimal - 1.0) - (1.0 - p)
    return {
        "probability": p,
        "fair_american": fair_american(p),
        "draftkings_odds": float(odds),
        "draftkings_raw_implied_p": implied,
        "edge_vs_raw_implied": p - implied,
        "ev_per_dollar": ev,
    }


def _decode_manual_board(raw: str, source: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MLBShadowCardError(f"invalid {source} JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise MLBShadowCardError(f"{source} JSON must be an array")
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, row in enumerate(payload):
        if not isinstance(row, Mapping):
            raise MLBShadowCardError(f"{source} row {index} must be an object")
        try:
            game_pk = int(row["game_pk"])
            home_odds = float(row["home_odds"])
            away_odds = float(row["away_odds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MLBShadowCardError(
                f"{source} row {index} requires game_pk, home_odds, away_odds"
            ) from exc
        if game_pk in seen:
            raise MLBShadowCardError(f"duplicate game_pk in {source}: {game_pk}")
        # Validate before accepting the row.
        american_implied(home_odds)
        american_implied(away_odds)
        seen.add(game_pk)
        rows.append(
            {
                "game_pk": game_pk,
                "home_odds": home_odds,
                "away_odds": away_odds,
            }
        )
    return rows


def load_manual_board(path: str | None = None, inline_json: str | None = None) -> tuple[list[dict[str, Any]], str]:
    if path:
        file_path = Path(path)
        if not file_path.is_file():
            raise MLBShadowCardError(f"manual DK board not found: {file_path}")
        return _decode_manual_board(file_path.read_text(encoding="utf-8"), "manual-file"), "MANUAL_JSON_FILE"
    raw = (inline_json or "").strip()
    if raw:
        return _decode_manual_board(raw, "manual-inline"), "MANUAL_JSON_INLINE"
    return [], "NO_DK_PRICE_INPUT"


def _authority() -> dict[str, bool]:
    return {
        "model_p": False,
        "truth_gate": False,
        "promotion": False,
        "eligibility": False,
        "forward_evidence": False,
        "staking": False,
        "backfill": False,
        "official": False,
    }


def build_shadow_card(
    *,
    schedule: Iterable[Any],
    history: Any,
    now: datetime,
    dk_rows: Iterable[Mapping[str, Any]] = (),
    dk_source: str = "NO_DK_PRICE_INPUT",
    simulations: int = DEFAULT_SIMULATIONS,
    min_ev: float = 0.01,
    predictor: Callable[..., Mapping[str, Any]] = build_forward_prediction,
) -> dict[str, Any]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise MLBShadowCardError("now must be timezone-aware")
    now_utc = now.astimezone(timezone.utc)
    dk_index = {int(row["game_pk"]): dict(row) for row in dk_rows}
    games: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for snapshot in schedule:
        if str(getattr(snapshot, "status", "")) != "Preview":
            continue
        game_pk = int(getattr(snapshot, "game_pk"))
        try:
            prediction = dict(
                predictor(
                    snapshot=snapshot,
                    history=history,
                    now=now_utc,
                    simulations=int(simulations),
                )
            )
            home_p = float(prediction["model_p"])
            if not 0.0 < home_p < 1.0:
                raise MLBShadowCardError("engine probability out of range")
        except Exception as exc:
            blocked.append({
                "game_pk": game_pk,
                "away_team": str(getattr(snapshot, "away_name", "")),
                "home_team": str(getattr(snapshot, "home_name", "")),
                "reason": str(exc),
            })
            continue

        away_p = 1.0 - home_p
        row: dict[str, Any] = {
            "game_pk": game_pk,
            "away_team": str(getattr(snapshot, "away_name", prediction.get("away_team", ""))),
            "home_team": str(getattr(snapshot, "home_name", prediction.get("home_team", ""))),
            "event_start_ts": str(prediction.get("event_start_ts", getattr(snapshot, "game_date", ""))),
            "status": "SHADOW_P_PAPER_ONLY",
            "market": "MONEYLINE",
            "shadow_p_home": home_p,
            "shadow_p_away": away_p,
            "fair_american_home": fair_american(home_p),
            "fair_american_away": fair_american(away_p),
            "governed_model_p": None,
            "truth_gate": False,
            "official": False,
            "production_engine_dispatch": prediction.get("production_engine_dispatch"),
            "engine_version": prediction.get("engine_version"),
            "model_artifact_sha256": prediction.get("model_artifact_sha256"),
            "feature_source_hash": prediction.get("feature_source_hash"),
            "distribution_sha256": prediction.get("distribution_sha256"),
            "mc_paths": prediction.get("mc_paths"),
            "market_blind": bool(prediction.get("market_blind", True)),
            "paper_candidate": False,
            "paper_side": None,
            "paper_ev_per_dollar": None,
        }

        quote = dk_index.get(game_pk)
        if quote is not None:
            home_price = price_side(home_p, float(quote["home_odds"]))
            away_price = price_side(away_p, float(quote["away_odds"]))
            row["draftkings"] = {"HOME": home_price, "AWAY": away_price}
            best_side, best = max(
                (("HOME", home_price), ("AWAY", away_price)),
                key=lambda item: item[1]["ev_per_dollar"],
            )
            if best["ev_per_dollar"] >= float(min_ev):
                row["paper_candidate"] = True
                row["paper_side"] = best_side
                row["paper_ev_per_dollar"] = best["ev_per_dollar"]
        games.append(row)

    status = "READY" if games else "NO_PREVIEW_GAMES"
    if blocked and not games:
        status = "BLOCKED_MODEL_RUNTIME"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now_utc.isoformat(),
        "status": "PAPER_ONLY",
        "run_status": status,
        "label": "SHADOW_P",
        "market": "MONEYLINE",
        "predictive_source": "SPORTSEDGE_CANONICAL_MONEYLINE_ENGINE_WITH_LIVE_MLB_HISTORY",
        "dk_price_source": dk_source,
        "min_paper_ev": float(min_ev),
        "simulations_requested": int(simulations),
        "games": games,
        "blocked_games": blocked,
        "authority": _authority(),
        "notes": [
            "SHADOW_P is executable SportsEdge research output, not governed Model_P.",
            "Manual DraftKings prices are downstream market inputs only and cannot create model probability.",
            "This artifact is not forward-validation evidence and cannot restore the closed 2026 MLB promotion window.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--slate-date", default="")
    parser.add_argument("--dk-json", default="")
    parser.add_argument("--simulations", type=int, default=DEFAULT_SIMULATIONS)
    parser.add_argument("--min-ev", type=float, default=0.01)
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    slate_date = args.slate_date.strip() or now.astimezone(CHICAGO_TZ).date().isoformat()
    try:
        dk_rows, dk_source = load_manual_board(
            args.dk_json.strip() or None,
            os.getenv("MLB_DK_MONEYLINE_JSON", ""),
        )
        schedule = fetch_schedule(slate_date, now=now)
        history = MLBGenericHistorySource(retrieved_at=now)
        payload = build_shadow_card(
            schedule=schedule,
            history=history,
            now=now,
            dk_rows=dk_rows,
            dk_source=dk_source,
            simulations=args.simulations,
            min_ev=args.min_ev,
        )
    except Exception as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": now.isoformat(),
            "status": "PAPER_ONLY",
            "run_status": "BLOCKED_INPUT_OR_RUNTIME",
            "label": "SHADOW_P",
            "market": "MONEYLINE",
            "reason": str(exc),
            "games": [],
            "blocked_games": [],
            "authority": _authority(),
        }

    out = Path(args.output)
    if not str(out).replace("\\", "/").startswith("artifacts/"):
        raise SystemExit("MLB_SHADOW_CARD_OUTPUT_MUST_BE_UNDER_ARTIFACTS")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "run_status": payload["run_status"],
        "games": len(payload.get("games", [])),
        "blocked_games": len(payload.get("blocked_games", [])),
        "output": str(out),
    }, sort_keys=True))
    return 0 if payload["run_status"] not in {"BLOCKED_INPUT_OR_RUNTIME", "BLOCKED_MODEL_RUNTIME"} else 2


if __name__ == "__main__":
    sys.exit(main())
