#!/usr/bin/env python3
"""Run the pre-registered one-shot 2025 CFB joint-score holdout."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from sportsedge.sports.cfb.joint_model import (
    fit_cfb_joint_score_model,
    price_cfb_game_markets,
    simulate_cfb_joint_distribution,
)

CONFIRM = "RUN_2025_HOLDOUT_ONCE"


class CFBHoldoutError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_training_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise CFBHoldoutError("CFB_HOLDOUT_TRAINING_EMPTY")
    bad = [row for row in rows if int(row.get("season", 9999)) >= 2025]
    if bad:
        raise CFBHoldoutError("CFB_HOLDOUT_2025_DATA_IN_TRAINING")


def _validate_prior_target_row(row: Mapping[str, Any]) -> None:
    if int(row.get("season", -1)) != 2025:
        raise CFBHoldoutError("CFB_HOLDOUT_TARGET_SEASON_INVALID")
    week = int(row.get("week", 0))
    if week < 1:
        raise CFBHoldoutError("CFB_HOLDOUT_TARGET_WEEK_INVALID")
    for side in ("home_metrics", "away_metrics"):
        metric = row.get(side)
        if not isinstance(metric, Mapping):
            raise CFBHoldoutError(f"CFB_HOLDOUT_METRIC_MISSING:{side}")
        season = int(metric.get("season", -1))
        through_week = int(metric.get("through_week", -1))
        source = str(metric.get("sample_source") or "").upper()
        if week == 1:
            if season != 2024 or source != "PRIOR_SEASON_FALLBACK":
                raise CFBHoldoutError(f"CFB_HOLDOUT_WEEK1_NOT_STRICT_PRIOR:{side}")
        else:
            if season != 2025 or through_week != week - 1 or source != "CURRENT_SEASON_PRIOR_WEEKS":
                raise CFBHoldoutError(f"CFB_HOLDOUT_TARGET_WEEK_LEAK:{side}")


def _identity_seed(root_seed: int, game_id: str, model_sha: str) -> int:
    payload = f"{root_seed}|{game_id}|{model_sha}|CFB_GAME_PATH_V1".encode()
    return int.from_bytes(sha256(payload).digest()[:8], "big", signed=False)


def _rmse(errors: Sequence[float]) -> float:
    if not errors:
        raise CFBHoldoutError("CFB_HOLDOUT_RMSE_EMPTY")
    return math.sqrt(sum(float(x) ** 2 for x in errors) / len(errors))


def _half_point(value: float) -> bool:
    doubled = float(value) * 2.0
    nearest = round(doubled)
    return abs(doubled - nearest) <= 1e-9 and abs(nearest) % 2 == 1


def _select_provider(lines: Mapping[str, Any], game_ids: set[str]) -> tuple[str, dict[str, dict[str, float]]]:
    if lines.get("schema") != "CFB_2025_CFBD_LAST_STORED_LINES_V1":
        raise CFBHoldoutError("CFB_HOLDOUT_LINES_SCHEMA_INVALID")
    by_provider: dict[str, dict[str, dict[str, float]]] = {}
    for raw in lines.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        gid = str(raw.get("game_id") or "")
        provider = str(raw.get("provider") or "").strip()
        if gid not in game_ids or not provider:
            continue
        try:
            spread = float(raw["home_spread"])
            total = float(raw["total"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(spread) or not math.isfinite(total):
            continue
        by_provider.setdefault(provider, {})[gid] = {"home_spread": spread, "total": total}
    if not by_provider:
        raise CFBHoldoutError("CFB_HOLDOUT_NO_MATCHED_PROVIDER")
    ranked = sorted(by_provider, key=lambda p: (-len(by_provider[p]), p.casefold(), p))
    provider = ranked[0]
    return provider, by_provider[provider]


def _calibration(rows: Sequence[tuple[float, float]]) -> dict[str, float | int | None]:
    if not rows:
        return {"n": 0, "predicted_rate": None, "observed_rate": None, "gap": None, "brier": None}
    predicted = sum(p for p, _ in rows) / len(rows)
    observed = sum(y for _, y in rows) / len(rows)
    brier = sum((p - y) ** 2 for p, y in rows) / len(rows)
    return {
        "n": len(rows),
        "predicted_rate": predicted,
        "observed_rate": observed,
        "gap": abs(predicted - observed),
        "brier": brier,
    }


def run(*, rows: Sequence[Mapping[str, Any]], lines: Mapping[str, Any], freeze: Mapping[str, Any]) -> dict[str, Any]:
    train = [dict(row) for row in rows if int(row.get("season", -1)) < 2025]
    target = [dict(row) for row in rows if int(row.get("season", -1)) == 2025]
    validate_training_rows(train)
    if not target:
        raise CFBHoldoutError("CFB_HOLDOUT_TARGET_EMPTY")
    for row in target:
        _validate_prior_target_row(row)

    params = freeze.get("parameters") or {}
    if int((freeze.get("training_window") or {}).get("max_season", 9999)) != 2024:
        raise CFBHoldoutError("CFB_HOLDOUT_FREEZE_TRAINING_WINDOW_INVALID")
    model = fit_cfb_joint_score_model(train, ridge_alpha=float(params["ridge_alpha"]))
    model_sha = model.artifact_sha256()
    provider, selected_lines = _select_provider(lines, {str(row["game_id"]) for row in target})

    margin_model_errors: list[float] = []
    margin_market_errors: list[float] = []
    total_model_errors: list[float] = []
    total_market_errors: list[float] = []
    cover_half: list[tuple[float, float]] = []
    over_half: list[tuple[float, float]] = []
    evaluated = 0

    for row in target:
        gid = str(row["game_id"])
        close = selected_lines.get(gid)
        if close is None:
            continue
        seed = _identity_seed(int(params["root_seed"]), gid, model_sha)
        distribution = simulate_cfb_joint_distribution(
            model, row, seed=seed, n_paths=int(params["simulation_paths"])
        )
        market = price_cfb_game_markets(
            distribution,
            spread_line=float(close["home_spread"]),
            total_line=float(close["total"]),
        )
        actual_margin = float(row["home_score"]) - float(row["away_score"])
        actual_total = float(row["home_score"]) + float(row["away_score"])
        predicted_margin = sum(float(x["margin"]) for x in distribution) / len(distribution)
        predicted_total = sum(float(x["total"]) for x in distribution) / len(distribution)

        margin_model_errors.append(predicted_margin - actual_margin)
        margin_market_errors.append((-float(close["home_spread"])) - actual_margin)
        total_model_errors.append(predicted_total - actual_total)
        total_market_errors.append(float(close["total"]) - actual_total)
        evaluated += 1

        if _half_point(float(close["home_spread"])):
            cover_half.append(
                (
                    float(market["spread"]["home"]),
                    1.0 if actual_margin + float(close["home_spread"]) > 0 else 0.0,
                )
            )
        if _half_point(float(close["total"])):
            over_half.append(
                (
                    float(market["total"]["over"]),
                    1.0 if actual_total > float(close["total"]) else 0.0,
                )
            )

    if evaluated == 0:
        raise CFBHoldoutError("CFB_HOLDOUT_NO_EVALUATED_GAMES")

    margin_model = _rmse(margin_model_errors)
    margin_close = _rmse(margin_market_errors)
    total_model = _rmse(total_model_errors)
    total_close = _rmse(total_market_errors)
    cover = _calibration(cover_half)
    over = _calibration(over_half)

    margin_pass = margin_model <= margin_close + 0.25
    cover_pass = cover["gap"] is not None and float(cover["gap"]) < 0.05
    over_pass = over["gap"] is not None and float(over["gap"]) < 0.05
    verdict = "PASS" if margin_pass and cover_pass and over_pass else "FAIL"

    return {
        "schema": "CFB_2025_HOLDOUT_RESULT_V1",
        "freeze_id": freeze.get("freeze_id"),
        "engine_version": freeze.get("engine_version"),
        "verdict": verdict,
        "one_shot": True,
        "training_seasons": sorted({int(row["season"]) for row in train}),
        "holdout_season": 2025,
        "season_type": "regular",
        "classification": "fbs",
        "strict_prior_team_metrics": True,
        "historical_pit_created": False,
        "line_source": "CFBD_LAST_STORED_HISTORICAL_LINE_NOT_TIMESTAMP_CERTIFIED",
        "selected_provider": provider,
        "games_evaluated": evaluated,
        "model_artifact_sha256": model_sha,
        "metrics": {
            "home_margin_rmse_model": margin_model,
            "home_margin_rmse_cfbd_close": margin_close,
            "home_margin_rmse_allowed_max": margin_close + 0.25,
            "total_rmse_model": total_model,
            "total_rmse_cfbd_close": total_close,
            "half_point_home_cover": cover,
            "half_point_over": over,
        },
        "pass_checks": {
            "margin_within_0_25_of_close": margin_pass,
            "home_cover_gap_under_5pp": cover_pass,
            "over_gap_under_5pp": over_pass,
        },
        "phone_card_action": "WIRE_FROZEN_CFB_LINES" if verdict == "PASS" else "KEEP_NO_MODEL",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--lines", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args(argv)

    if args.confirm != CONFIRM:
        raise SystemExit("CFB_HOLDOUT_CONFIRMATION_REQUIRED")
    if args.out.exists():
        raise SystemExit("CFB_HOLDOUT_RESULT_ALREADY_EXISTS_NO_RERUN")

    rows = _load(args.rows)
    if not isinstance(rows, list):
        raise SystemExit("CFB_HOLDOUT_ROWS_NOT_LIST")
    lines = _load(args.lines)
    freeze = _load(args.freeze)
    result = run(rows=rows, lines=lines, freeze=freeze)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "CFB_2025_HOLDOUT_COMPLETE", "verdict": result["verdict"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
