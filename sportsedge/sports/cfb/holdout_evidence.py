"""Strict forward-holdout evidence for the CFB joint score challenger.

This module evaluates already-produced, provenance-bound holdout predictions. It
never fetches data, chooses a promotion threshold, or promotes a model. Sportsbook
lines are benchmark-only readouts and are prohibited from predictive features.
"""
from __future__ import annotations

from hashlib import sha256
import json
from math import isfinite, log, sqrt
from typing import Any, Iterable, Mapping, Sequence


class CFBHoldoutEvidenceError(ValueError):
    pass


CONTRACT = "CFB_FORWARD_HOLDOUT_EVIDENCE_V1"
SOURCE_EVIDENCE_CLASS = "CHECKSUM_VERIFIED_SPORTSDATAVERSE_RELEASE"
VERIFIED_BENCHMARK_SOURCES = frozenset({"summary_pickcenter", "core_odds_api"})
PREGAME_WEATHER_CLASSES = frozenset({
    "ARCHIVED_PREGAME_WEATHER",
    "PREGAME_WEATHER_SNAPSHOT",
    "VERIFIED_INDOOR_PREGAME_ENVIRONMENT",
})
_HEX = frozenset("0123456789abcdef")
_BANNED_EXACT = frozenset({
    "spread", "spread_line", "game_spread", "home_team_spread", "total", "total_line",
    "over_under", "line", "price", "american_odds", "decimal_odds", "odds", "odds_source",
    "book", "sportsbook", "closing_line", "closing_price", "home_moneyline", "away_moneyline",
    "implied_probability", "implied_prob", "market_probability", "novig_prob", "no_vig_prob",
})


def _sha(value: Any, name: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in _HEX for ch in text):
        raise CFBHoldoutEvidenceError(f"{name}:SHA256_REQUIRED")
    return text


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise CFBHoldoutEvidenceError(f"{name}:INTEGER_REQUIRED")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CFBHoldoutEvidenceError(f"{name}:INTEGER_REQUIRED") from exc


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise CFBHoldoutEvidenceError(f"{name}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBHoldoutEvidenceError(f"{name}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBHoldoutEvidenceError(f"{name}:FINITE_REQUIRED")
    return out


def _prob(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0 or out > 1.0:
        raise CFBHoldoutEvidenceError(f"{name}:PROBABILITY_REQUIRED")
    return out


def _assert_market_blind(value: Any, path: str = "predictive_features") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).strip().lower()
            if (
                name in _BANNED_EXACT
                or "implied_prob" in name
                or "no_vig" in name
                or "novig" in name
            ):
                raise CFBHoldoutEvidenceError(f"CFB_MARKET_DATA_PROHIBITED:{path}.{key}")
            _assert_market_blind(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_market_blind(child, f"{path}[{index}]")


def _content_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _binary_metrics(probs: Sequence[float], refs: Sequence[int]) -> dict[str, Any]:
    n = len(probs)
    if n != len(refs):
        raise AssertionError("metric vectors differ")
    if n == 0:
        return {"n": 0, "brier": None, "log_loss": None, "decision_n": 0, "decision_accuracy": None}
    eps = 1e-15
    brier = sum((p - y) ** 2 for p, y in zip(probs, refs)) / n
    ll = -sum(
        y * log(max(p, eps)) + (1 - y) * log(max(1.0 - p, eps))
        for p, y in zip(probs, refs)
    ) / n
    decisions = [(p, y) for p, y in zip(probs, refs) if abs(p - 0.5) > 1e-12]
    correct = sum((p > 0.5) == bool(y) for p, y in decisions)
    return {
        "n": n,
        "brier": brier,
        "log_loss": ll,
        "decision_n": len(decisions),
        "decision_accuracy": None if not decisions else correct / len(decisions),
    }


def _error_metrics(errors: Sequence[float]) -> dict[str, Any]:
    if not errors:
        return {"n": 0, "mae": None, "rmse": None, "bias": None}
    n = len(errors)
    return {
        "n": n,
        "mae": sum(abs(x) for x in errors) / n,
        "rmse": sqrt(sum(x * x for x in errors) / n),
        "bias": sum(errors) / n,
    }


def _normalize_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CFBHoldoutEvidenceError("HOLDOUT_ROW_OBJECT_REQUIRED")
    game_id = str(raw.get("game_id") or "").strip()
    if not game_id:
        raise CFBHoldoutEvidenceError("HOLDOUT_GAME_ID_REQUIRED")
    season = _int(raw.get("season"), "season")
    seed = raw.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise CFBHoldoutEvidenceError("CFB_EXPLICIT_INTEGER_SEED_REQUIRED")
    n_paths = raw.get("n_paths")
    if isinstance(n_paths, bool) or not isinstance(n_paths, int) or n_paths <= 0:
        raise CFBHoldoutEvidenceError("CFB_N_PATHS_INVALID")

    weather_class = str(raw.get("weather_evidence_class") or "").strip().upper()
    if weather_class not in PREGAME_WEATHER_CLASSES:
        raise CFBHoldoutEvidenceError("CFB_PREGAME_WEATHER_EVIDENCE_REQUIRED")

    features = raw.get("predictive_features")
    if not isinstance(features, Mapping):
        raise CFBHoldoutEvidenceError("CFB_PREDICTIVE_FEATURES_MAPPING_REQUIRED")
    _assert_market_blind(features)

    home_score = _finite(raw.get("home_score"), "home_score")
    away_score = _finite(raw.get("away_score"), "away_score")
    if home_score < 0 or away_score < 0:
        raise CFBHoldoutEvidenceError("CFB_NEGATIVE_REALIZED_SCORE")
    home_mu = _finite(raw.get("predicted_home_mean"), "predicted_home_mean")
    away_mu = _finite(raw.get("predicted_away_mean"), "predicted_away_mean")
    if home_mu < 0 or away_mu < 0:
        raise CFBHoldoutEvidenceError("CFB_NEGATIVE_PREDICTED_SCORE")
    home_win_p = _prob(raw.get("home_win_p"), "home_win_p")

    benchmark = raw.get("benchmark")
    if benchmark is None:
        benchmark = {}
    if not isinstance(benchmark, Mapping):
        raise CFBHoldoutEvidenceError("CFB_BENCHMARK_MAPPING_REQUIRED")
    odds_source = str(benchmark.get("odds_source") or "").strip().lower()
    benchmark_eligible = odds_source in VERIFIED_BENCHMARK_SOURCES

    out = {
        "game_id": game_id,
        "season": season,
        "seed": int(seed),
        "n_paths": int(n_paths),
        "weather_evidence_class": weather_class,
        "predictive_features_sha256": _content_sha(dict(features)),
        "home_score": home_score,
        "away_score": away_score,
        "predicted_home_mean": home_mu,
        "predicted_away_mean": away_mu,
        "home_win_p": home_win_p,
        "benchmark_eligible": benchmark_eligible,
        "odds_source": odds_source,
    }
    if not benchmark_eligible:
        return out

    home_spread = _finite(benchmark.get("home_team_spread"), "home_team_spread")
    total_line = _finite(benchmark.get("over_under"), "over_under")
    if total_line <= 0:
        raise CFBHoldoutEvidenceError("CFB_BENCHMARK_TOTAL_INVALID")
    spread_home = _prob(raw.get("spread_home_cover_p"), "spread_home_cover_p")
    spread_push = _prob(raw.get("spread_push_p"), "spread_push_p")
    total_over = _prob(raw.get("total_over_p"), "total_over_p")
    total_push = _prob(raw.get("total_push_p"), "total_push_p")
    if spread_home + spread_push > 1.0 + 1e-12:
        raise CFBHoldoutEvidenceError("CFB_SPREAD_PROBABILITY_MASS_INVALID")
    if total_over + total_push > 1.0 + 1e-12:
        raise CFBHoldoutEvidenceError("CFB_TOTAL_PROBABILITY_MASS_INVALID")
    out.update({
        "home_team_spread": home_spread,
        "over_under": total_line,
        "spread_home_cover_p": spread_home,
        "spread_push_p": spread_push,
        "total_over_p": total_over,
        "total_push_p": total_push,
    })
    return out


def analyze_cfb_holdout(
    raw_rows: Iterable[Mapping[str, Any]],
    *,
    model_artifact_sha256: str,
    train_seasons: Iterable[int],
    train_game_ids: Iterable[str],
    source_manifest_sha256s: Iterable[str],
    source_evidence_class: str,
    paired_historical_price_evidence_complete: bool = False,
) -> dict[str, Any]:
    model_sha = _sha(model_artifact_sha256, "model_artifact_sha256")
    source_class = str(source_evidence_class or "").strip().upper()
    if source_class != SOURCE_EVIDENCE_CLASS:
        raise CFBHoldoutEvidenceError("CFB_HISTORICAL_SOURCE_EVIDENCE_CLASS_INVALID")
    manifests = tuple(sorted({_sha(x, "source_manifest_sha256") for x in source_manifest_sha256s}))
    if not manifests:
        raise CFBHoldoutEvidenceError("CFB_SOURCE_MANIFEST_REQUIRED")

    trains = tuple(sorted({_int(x, "train_season") for x in train_seasons}))
    if not trains:
        raise CFBHoldoutEvidenceError("CFB_TRAIN_SEASONS_REQUIRED")
    train_ids = frozenset(str(x).strip() for x in train_game_ids if str(x).strip())
    if not train_ids:
        raise CFBHoldoutEvidenceError("CFB_TRAIN_GAME_IDS_REQUIRED")
    if type(paired_historical_price_evidence_complete) is not bool:
        raise CFBHoldoutEvidenceError("CFB_PAIRED_PRICE_EVIDENCE_BOOL_REQUIRED")

    rows = [_normalize_row(row) for row in raw_rows]
    if not rows:
        raise CFBHoldoutEvidenceError("CFB_HOLDOUT_ROWS_REQUIRED")
    rows.sort(key=lambda x: (x["season"], x["game_id"]))
    holdout_ids = [row["game_id"] for row in rows]
    if len(set(holdout_ids)) != len(holdout_ids):
        raise CFBHoldoutEvidenceError("CFB_HOLDOUT_GAME_ID_DUPLICATE")
    if train_ids.intersection(holdout_ids):
        raise CFBHoldoutEvidenceError("CFB_TRAIN_HOLDOUT_GAME_OVERLAP")
    max_train = max(trains)
    if any(row["season"] <= max_train for row in rows):
        raise CFBHoldoutEvidenceError("CFB_HOLDOUT_NOT_STRICTLY_FORWARD")

    score_errors: list[float] = []
    margin_errors: list[float] = []
    total_errors: list[float] = []
    home_win_probs: list[float] = []
    home_win_refs: list[int] = []
    spread_probs: list[float] = []
    spread_refs: list[int] = []
    total_probs: list[float] = []
    total_refs: list[int] = []
    spread_pushes = 0
    total_pushes = 0
    excluded: dict[str, str] = {}
    evidence_rows: list[dict[str, Any]] = []

    for row in rows:
        hs, aas = row["home_score"], row["away_score"]
        hm, am = row["predicted_home_mean"], row["predicted_away_mean"]
        score_errors.extend((hm - hs, am - aas))
        margin_errors.append((hm - am) - (hs - aas))
        total_errors.append((hm + am) - (hs + aas))
        home_win_probs.append(row["home_win_p"])
        home_win_refs.append(1 if hs > aas else 0)

        ev_row = {
            "game_id": row["game_id"],
            "season": row["season"],
            "seed": row["seed"],
            "n_paths": row["n_paths"],
            "weather_evidence_class": row["weather_evidence_class"],
            "predictive_features_sha256": row["predictive_features_sha256"],
            "benchmark_eligible": row["benchmark_eligible"],
            "odds_source": row["odds_source"],
        }
        if not row["benchmark_eligible"]:
            excluded[row["game_id"]] = "CFB_BENCHMARK_ODDS_SOURCE_UNVERIFIED"
            evidence_rows.append(ev_row)
            continue

        margin_settlement = (hs - aas) + row["home_team_spread"]
        total_settlement = (hs + aas) - row["over_under"]
        ev_row["home_team_spread"] = row["home_team_spread"]
        ev_row["over_under"] = row["over_under"]

        if abs(margin_settlement) <= 1e-12:
            spread_pushes += 1
        else:
            non_push = 1.0 - row["spread_push_p"]
            if non_push <= 1e-15:
                raise CFBHoldoutEvidenceError("CFB_SPREAD_SETTLED_SAMPLE_SPACE_EMPTY")
            spread_probs.append(row["spread_home_cover_p"] / non_push)
            spread_refs.append(1 if margin_settlement > 0 else 0)
        if abs(total_settlement) <= 1e-12:
            total_pushes += 1
        else:
            non_push = 1.0 - row["total_push_p"]
            if non_push <= 1e-15:
                raise CFBHoldoutEvidenceError("CFB_TOTAL_SETTLED_SAMPLE_SPACE_EMPTY")
            total_probs.append(row["total_over_p"] / non_push)
            total_refs.append(1 if total_settlement > 0 else 0)
        evidence_rows.append(ev_row)

    spread = _binary_metrics(spread_probs, spread_refs)
    spread["settled_n"] = spread.pop("n")
    spread["push_n"] = spread_pushes
    total = _binary_metrics(total_probs, total_refs)
    total["settled_n"] = total.pop("n")
    total["push_n"] = total_pushes

    blockers: list[str] = []
    if not paired_historical_price_evidence_complete:
        blockers.append("CFB_PAIRED_HISTORICAL_PRICE_EVIDENCE_REQUIRED")
    blockers.append("CFB_FROZEN_PROMOTION_POLICY_REQUIRED")
    promotion_state = "BLOCKED" if not paired_historical_price_evidence_complete else "READY_FOR_FROZEN_POLICY"
    benchmark_eligible_n = sum(row["benchmark_eligible"] for row in rows)

    report: dict[str, Any] = {
        "contract": CONTRACT,
        "source_evidence_class": source_class,
        "model_artifact_sha256": model_sha,
        "source_manifest_sha256s": manifests,
        "train_seasons": trains,
        "holdout_seasons": tuple(sorted({row["season"] for row in rows})),
        "train_game_count": len(train_ids),
        "holdout_game_count": len(rows),
        "score": _error_metrics(score_errors),
        "margin": _error_metrics(margin_errors),
        "total_points": _error_metrics(total_errors),
        "moneyline_outcome": _binary_metrics(home_win_probs, home_win_refs),
        "spread": spread,
        "total": total,
        "benchmark_eligible_n": benchmark_eligible_n,
        "benchmark_excluded_n": len(rows) - benchmark_eligible_n,
        "benchmark_exclusion_reasons": dict(sorted(excluded.items())),
        "evidence_state": "COMPLETE" if benchmark_eligible_n == len(rows) else "PARTIAL_BENCHMARK",
        "paired_historical_price_evidence_complete": paired_historical_price_evidence_complete,
        "promotion_state": promotion_state,
        "promotion_blockers": tuple(blockers),
        "promoted": False,
        "rows": tuple(evidence_rows),
    }
    report["report_sha256"] = _content_sha(report)
    return report
