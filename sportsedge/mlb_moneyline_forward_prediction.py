"""Prospective, market-blind Model_P capture for MLB MONEYLINE.

This lane freezes one HOME-reference probability per game before the downstream
DraftKings decision quote. It never consumes sportsbook prices, implied
probabilities, consensus, public betting, or handicapper opinion and grants no
promotion, staking, or OFFICIAL authority.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Iterable

from .generic_market_engine import generic_market_engine_adapter
from .mlb_model_artifact import mlb_model_artifact_sha256
from .mlb_moneyline_pit import PIT_VERSION, MLBMoneylinePITError, build_moneyline_feature
from .mlb_source import parse_game_start

PREDICTION_VERSION = "mlb_moneyline_forward_model_p_v1"
EVIDENCE_DISPOSITION = "FORWARD_MODEL_P_PREDICTION"
PREDICTION_WINDOW_LOW_MIN = 40.0
PREDICTION_WINDOW_HIGH_MIN = 60.0
DEFAULT_SIMULATIONS = 100000


class MLBMoneylineForwardPredictionError(ValueError):
    pass


class MLBMoneylineForwardPredictionBlocked(RuntimeError):
    def __init__(self, reason: str, detail: Any = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MLBMoneylineForwardPredictionError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _module_sha256(module_file: str | None) -> str:
    if not module_file:
        raise MLBMoneylineForwardPredictionError("module file unavailable")
    return hashlib.sha256(Path(module_file).read_bytes()).hexdigest()


def _target_date(snapshot: Any, start: datetime) -> date:
    raw = getattr(snapshot, "official_date", None)
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError as exc:
            raise MLBMoneylineForwardPredictionError("official_date invalid") from exc
    return start.date()


def _team_observations(
    history: Any,
    *,
    team_id: int,
    target_date: date,
    clock: Callable[[], datetime],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Timestamp after the provider response has been consumed. This is
    # deliberately conservative: it makes no claim about when MLB published the
    # historical rows, only that SportsEdge had observed them by this instant.
    rows = list(history.team_rows(team_id=int(team_id), target_date=target_date))[-30:]
    observed = _utc(clock(), "source observed_at")
    if len(rows) < 10:
        raise MLBMoneylineForwardPredictionError(
            f"PIT_INSUFFICIENT_HISTORY: team_id={team_id} n={len(rows)} minimum=10"
        )
    observations: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []
    for row in rows:
        try:
            runs = float((row.get("stat") or {}).get("runs"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineForwardPredictionError(f"team_id={team_id}: runs invalid") from exc
        if not isfinite(runs) or runs < 0:
            raise MLBMoneylineForwardPredictionError(f"team_id={team_id}: runs invalid")
        source_date = row.get("date")
        source_date_text = source_date.isoformat() if hasattr(source_date, "isoformat") else str(source_date or "")
        if not source_date_text:
            raise MLBMoneylineForwardPredictionError(f"team_id={team_id}: source date missing")
        observations.append({
            "team_id": int(team_id),
            "runs": runs,
            "feature_asof_ts": observed.isoformat(),
            "source_game_pk": None,
        })
        retained.append({
            "team_id": int(team_id),
            "runs": runs,
            "source_date": source_date_text,
            "observed_at_utc": observed.isoformat(),
            "source": "MLB_STATSAPI_CHRONOLOGICAL_GAMELOG",
        })
    return observations, retained


def build_forward_prediction(
    *,
    snapshot: Any,
    history: Any,
    now: datetime,
    artifact_sha: str | None = None,
    simulations: int = DEFAULT_SIMULATIONS,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Build one immutable HOME-reference probability from live-observed baseball data."""
    window_now = _utc(now, "now")
    source_clock = clock or (lambda: datetime.now(timezone.utc))
    start = parse_game_start(getattr(snapshot, "game_date"))
    if not window_now < start:
        raise MLBMoneylineForwardPredictionError("prediction must precede event start")
    if str(getattr(snapshot, "status", "")) != "Preview":
        raise MLBMoneylineForwardPredictionError("prediction requires Preview game state")
    if simulations < 1000:
        raise MLBMoneylineForwardPredictionError("simulations must be >= 1000")

    target_date = _target_date(snapshot, start)
    away_obs, away_retained = _team_observations(
        history, team_id=int(snapshot.away_id), target_date=target_date, clock=source_clock
    )
    home_obs, home_retained = _team_observations(
        history, team_id=int(snapshot.home_id), target_date=target_date, clock=source_clock
    )
    try:
        feature = build_moneyline_feature(
            game_pk=int(snapshot.game_pk),
            away_team_id=int(snapshot.away_id),
            home_team_id=int(snapshot.home_id),
            event_start_ts=start,
            observations=[*away_obs, *home_obs],
            window=30,
            minimum=10,
        )
    except MLBMoneylinePITError as exc:
        raise MLBMoneylineForwardPredictionError(str(exc)) from exc

    model_input = {
        "game_id": str(snapshot.game_pk),
        "market": "MONEYLINE",
        "entity_id": str(snapshot.game_pk),
        "line": 0.0,
        "side": "HOME",
        "away_mean_runs": feature["away_mean_runs"],
        "home_mean_runs": feature["home_mean_runs"],
        "feature_source_hash": feature["feature_source_hash"],
        "simulations": int(simulations),
    }
    engine = generic_market_engine_adapter(model_input)
    generated_at = _utc(source_clock(), "prediction generated_at")
    if not generated_at < start:
        raise MLBMoneylineForwardPredictionError("prediction generation crossed event start")
    model_p = float(engine["model_p"])
    if not isfinite(model_p) or not 0.0 < model_p < 1.0:
        raise MLBMoneylineForwardPredictionError("Model_P invalid")

    bound_artifact = str(artifact_sha or mlb_model_artifact_sha256()).lower()
    if len(bound_artifact) != 64 or any(ch not in "0123456789abcdef" for ch in bound_artifact):
        raise MLBMoneylineForwardPredictionError("model_artifact_sha256 invalid")

    import sportsedge.mlb_moneyline_pit as pit_module
    return {
        "schema_version": PREDICTION_VERSION,
        "evidence_disposition": EVIDENCE_DISPOSITION,
        "promotion_authority": False,
        "market": "MONEYLINE",
        "game_pk": int(snapshot.game_pk),
        "away_team_id": int(snapshot.away_id),
        "away_team": str(snapshot.away_name),
        "home_team_id": int(snapshot.home_id),
        "home_team": str(snapshot.home_name),
        "model_side": "HOME",
        "reference_side_policy": "FIXED_HOME_REFERENCE_NO_MARKET_SELECTION",
        "model_p": model_p,
        "market_blind": True,
        "forbidden_market_inputs": list(feature["forbidden_market_inputs"]),
        "feature_asof_ts": feature["feature_asof_ts"],
        "event_start_ts": start.isoformat(),
        "prediction_generated_at_utc": generated_at.isoformat(),
        "model_artifact_sha256": bound_artifact,
        "pit_contract_version": PIT_VERSION,
        "pit_module_sha256": _module_sha256(getattr(pit_module, "__file__", None)),
        "prediction_module_sha256": _module_sha256(__file__),
        "feature_source_hash": feature["feature_source_hash"],
        "feature_observation_count": int(feature["observation_count"]),
        "feature_observations": [*away_retained, *home_retained],
        "away_mean_runs": float(feature["away_mean_runs"]),
        "home_mean_runs": float(feature["home_mean_runs"]),
        "model_input_hash": str(engine["model_input_hash"]),
        "engine_version": str(engine["engine_version"]),
        "seed_policy": str(engine["seed_policy"]),
        "mc_paths": int(engine["mc_paths"]),
        "source": "LIVE_OBSERVED_MLB_STATSAPI_GAMELOG",
        "source_timestamp_semantics": "POST_RESPONSE_RECEIPT_TIME_CONSERVATIVE",
    }


def prediction_window(minutes_before_start: float) -> bool:
    return PREDICTION_WINDOW_LOW_MIN < float(minutes_before_start) <= PREDICTION_WINDOW_HIGH_MIN


def capture_due_predictions(
    *,
    schedule: Iterable[Any],
    history: Any,
    now: datetime,
    output_dir: str | Path,
    artifact_sha: str | None = None,
    simulations: int = DEFAULT_SIMULATIONS,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Create-only capture for games currently inside the prospective Model_P window."""
    now_utc = _utc(now, "now")
    due: list[tuple[Any, float]] = []
    for snapshot in schedule:
        if str(getattr(snapshot, "status", "")) != "Preview":
            continue
        start = parse_game_start(getattr(snapshot, "game_date"))
        minutes_before = (start - now_utc).total_seconds() / 60.0
        if prediction_window(minutes_before):
            due.append((snapshot, minutes_before))
    if not due:
        return {
            "status": "NO_PREDICTION_DUE",
            "evidence_disposition": EVIDENCE_DISPOSITION,
            "promotion_authority": False,
            "games_due": 0,
            "predictions_retained": 0,
            "paths": [],
        }

    root = Path(output_dir) / now_utc.date().isoformat()
    written: list[str] = []
    existing: list[str] = []
    blocked: list[dict[str, Any]] = []
    for snapshot, minutes_before in due:
        path = root / f"game_{int(snapshot.game_pk)}.json"
        if path.exists():
            existing.append(str(path))
            continue
        try:
            record = build_forward_prediction(
                snapshot=snapshot,
                history=history,
                now=now_utc,
                artifact_sha=artifact_sha,
                simulations=simulations,
                clock=clock,
            )
        except Exception as exc:
            blocked.append({"game_pk": int(snapshot.game_pk), "reason": str(exc)})
            continue
        record["prediction_minutes_before_start"] = round(minutes_before, 4)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(record, handle, indent=2, sort_keys=True)
                handle.write("\n")
        except FileExistsError:
            existing.append(str(path))
            continue
        written.append(str(path))

    if blocked:
        raise MLBMoneylineForwardPredictionBlocked(
            "BLOCKED_DUE_MODEL_P",
            {"blocked": blocked, "written_before_block": written, "already_present": existing},
        )
    return {
        "status": "RETAINED" if written else "ALREADY_CAPTURED",
        "evidence_disposition": EVIDENCE_DISPOSITION,
        "promotion_authority": False,
        "games_due": len(due),
        "predictions_retained": len(written),
        "already_present": existing,
        "paths": written,
    }
