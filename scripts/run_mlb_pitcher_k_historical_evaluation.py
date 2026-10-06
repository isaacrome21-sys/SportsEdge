#!/usr/bin/env python3
"""One-shot historical materialization/evaluation for the frozen MLB pitcher-K candidate.

Research only. The date sample is frozen in
config/research/mlb_pitcher_k_historical_eval_plan_v1.json before this runner
may consume the candidate-specific 2025 test.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any, Mapping
from urllib.request import urlopen

from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource
from sportsedge.mlb_pitcher_k_composite_candidate import build_composite_candidate
from sportsedge.mlb_pitcher_k_historical_row import (
    EVALUATION_USE,
    PROVENANCE_SCHEMA,
    bind_historical_statcast_skill,
    build_historical_evaluation_row,
)
from sportsedge.mlb_pitcher_k_probability_evaluator import evaluate_pitcher_k_candidate
from sportsedge.mlb_pitcher_k_workload_source import build_from_history_source
from sportsedge.mlb_source import fetch_boxscore, fetch_schedule
from sportsedge.statcast_daily_source import SOURCE as STATCAST_SOURCE, fetch_daily_statcast


PLAN_SCHEMA = "MLB_PITCHER_K_HISTORICAL_EVAL_PLAN_V1"
OUTPUT_SCHEMA = "MLB_PITCHER_K_HISTORICAL_EVAL_RUN_V1"


class HistoricalEvalError(RuntimeError):
    pass


class _BytesResponse:
    def __init__(self, raw: bytes):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._raw


class HistoricalTransportCache:
    """Cache immutable historical StatsAPI bytes by URL.

    This is transport-only. Analytical PIT cutoffs remain inside the existing
    feature builders, which filter every history against each target date.
    """

    def __init__(self, root: Path, *, opener=urlopen, attempts: int = 3):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.opener = opener
        self.attempts = int(attempts)
        self.memory: dict[str, bytes] = {}

    @staticmethod
    def _url(req) -> str:
        return req if isinstance(req, str) else str(req.full_url)

    def __call__(self, req, timeout=30):
        url = self._url(req)
        cacheable = "statsapi.mlb.com/" in url
        key = sha256(url.encode("utf-8")).hexdigest()
        if cacheable and key in self.memory:
            return _BytesResponse(self.memory[key])
        path = self.root / f"{key}.json"
        if cacheable and path.exists():
            raw = path.read_bytes()
            json.loads(raw.decode("utf-8"))
            self.memory[key] = raw
            return _BytesResponse(raw)

        last = None
        for attempt in range(self.attempts):
            try:
                with self.opener(req, timeout=timeout) as response:
                    raw = response.read()
                if cacheable:
                    value = json.loads(raw.decode("utf-8"))
                    if not isinstance(value, (dict, list)):
                        raise HistoricalEvalError("StatsAPI response must be JSON object/list")
                    tmp = path.with_suffix(".tmp")
                    tmp.write_bytes(raw)
                    tmp.replace(path)
                    self.memory[key] = raw
                return _BytesResponse(raw)
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt + 1 < self.attempts:
                    time.sleep(1.5 * (attempt + 1))
        raise HistoricalEvalError(f"SOURCE_FETCH_FAILED:{type(last).__name__}") from last


def _canonical_sha(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def load_plan(path: Path) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("schema") != PLAN_SCHEMA:
        raise HistoricalEvalError("unexpected historical evaluation plan schema")
    if plan.get("status") != "FROZEN_BEFORE_FIRST_HISTORICAL_ROW_MATERIALIZATION":
        raise HistoricalEvalError("historical evaluation plan is not frozen")
    seasons = plan.get("seasons") or {}
    if seasons != {"training": 2023, "validation": 2024, "candidate_test": 2025}:
        raise HistoricalEvalError("frozen season split changed")
    if (plan.get("authority") or {}).get("model_p") is not False:
        raise HistoricalEvalError("plan cannot grant Model_P authority")
    if (plan.get("evaluation") or {}).get("candidate_test_one_look") is not True:
        raise HistoricalEvalError("candidate-test one-look flag required")
    return plan


def sample_dates(plan: Mapping[str, Any]) -> list[date]:
    sampling = plan.get("sampling") or {}
    months = [int(v) for v in sampling.get("months") or []]
    days = [int(v) for v in sampling.get("days_of_month") or []]
    seasons = plan.get("seasons") or {}
    years = [int(seasons[k]) for k in ("training", "validation", "candidate_test")]
    out = []
    for year in years:
        for month in months:
            for day in days:
                out.append(date(year, month, day))
    if len(out) != len(set(out)) or not out:
        raise HistoricalEvalError("sample date grid invalid")
    return sorted(out)


def _statcast_cache_path(root: Path, target_date: date) -> Path:
    return root / f"statcast_{target_date.isoformat()}.json"


def statcast_snapshot(target_date: date, root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    path = _statcast_cache_path(root, target_date)
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("window_end") != target_date.isoformat():
            raise HistoricalEvalError("cached Statcast target-date identity mismatch")
        return value

    last = None
    for attempt in range(3):
        try:
            snap = fetch_daily_statcast(end_date=target_date, days=30)
            value = {
                "source": snap.source,
                "window_start": snap.start_date,
                "window_end": snap.end_date,
                "retrieved_at": snap.retrieved_at,
                "raw_pitch_rows": int(snap.raw_pitch_rows),
                "pitcher_rows": list(snap.pitcher_rows),
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
            return value
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < 2:
                time.sleep(3.0 * (attempt + 1))
    raise HistoricalEvalError(
        f"STATCAST_DATE_FAILED:{target_date.isoformat()}:{type(last).__name__}"
    ) from last


def statcast_context(
    snapshot: Mapping[str, Any],
    *,
    pitcher_id: int,
    target_date: date,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if snapshot.get("window_end") != target_date.isoformat():
        raise HistoricalEvalError("Statcast window must end at target date exclusive")
    row = next(
        (
            r for r in snapshot.get("pitcher_rows") or []
            if isinstance(r, Mapping) and str(r.get("entity_id")) == str(int(pitcher_id))
        ),
        None,
    )
    if not isinstance(row, Mapping):
        raise HistoricalEvalError("STATCAST_PITCHER_MISSING")
    context = {
        "entity_id": str(int(pitcher_id)),
        "swings": row.get("swings"),
        "whiffs": row.get("whiffs"),
        "whiff_rate": row.get("whiff_rate"),
        "out_of_zone_pitches": row.get("out_of_zone_pitches"),
        "chases": row.get("chases"),
        "chase_rate": row.get("chase_rate"),
        "pitcher_hand": row.get("pitcher_hand"),
        "window_start": snapshot.get("window_start"),
        "window_end": snapshot.get("window_end"),
    }
    receipt = {
        "schema": PROVENANCE_SCHEMA,
        "source": snapshot.get("source") or STATCAST_SOURCE,
        "mode": "HISTORICAL_RECONSTRUCTION",
        "target_date": target_date.isoformat(),
        "window_start": snapshot.get("window_start"),
        "query_end_exclusive": target_date.isoformat(),
        "retrieved_at": snapshot.get("retrieved_at"),
        "raw_pitch_rows": int(snapshot.get("raw_pitch_rows") or 0),
        "same_day_rows_included": False,
        "future_rows_included": False,
        "historical_reconstruction": True,
        "backfill": True,
        "forward_evidence_eligible": False,
        "promotion_authority": False,
        "evaluation_use": EVALUATION_USE,
    }
    return context, receipt


def _starter(boxscore: Mapping[str, Any], side: str) -> tuple[int, int, int] | None:
    team = ((boxscore.get("teams") or {}).get(side) or {})
    pitchers = team.get("pitchers") or []
    if not pitchers:
        return None
    try:
        pitcher_id = int(pitchers[0])
    except (TypeError, ValueError):
        return None
    player = (team.get("players") or {}).get(f"ID{pitcher_id}") or {}
    pitching = ((player.get("stats") or {}).get("pitching") or {})
    if not isinstance(pitching, Mapping):
        return None
    try:
        strikeouts = int(pitching.get("strikeOuts"))
        batters_faced = int(pitching.get("battersFaced"))
    except (TypeError, ValueError):
        return None
    if strikeouts < 0 or batters_faced <= 0 or strikeouts > batters_faced:
        return None
    return pitcher_id, strikeouts, batters_faced


def _candidate_for_starter(
    *,
    source: MLBAllMarketHistorySource,
    snapshot: Mapping[str, Any],
    target_date: date,
    game_pk: int,
    away_team_id: int,
    home_team_id: int,
    pitcher_id: int,
    team_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    workload = build_from_history_source(source, player_id=pitcher_id, target_date=target_date)
    feature = source.feature_row(
        game_pk=game_pk,
        market="PITCHER_K",
        entity_id=str(pitcher_id),
        target_date=target_date,
        away_team_id=away_team_id,
        home_team_id=home_team_id,
        player_id=pitcher_id,
        team_id=team_id,
    )
    features = feature.get("features") or {}
    history_pool = features.get("history_pool")
    adjustment = features.get("opp_k_adjustment")
    if not isinstance(history_pool, list) or not isinstance(adjustment, Mapping):
        raise HistoricalEvalError("PITCHER_K_VALIDATED_OPPONENT_COMPONENT_MISSING")
    opponent = dict(adjustment)
    lineup = opponent.pop("lineup_k_adjustment", None)
    candidate = build_composite_candidate(
        workload=workload,
        opp_k_adjustment=opponent,
        lineup_k_adjustment=lineup,
    )
    context, receipt = statcast_context(
        snapshot,
        pitcher_id=pitcher_id,
        target_date=target_date,
    )
    candidate = bind_historical_statcast_skill(
        candidate,
        pitcher_context=context,
        provenance=receipt,
        target_date=target_date,
    )
    return candidate, history_pool


def materialize_rows(
    plan: Mapping[str, Any],
    *,
    cache_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    transport = HistoricalTransportCache(cache_dir / "statsapi")
    statcast_root = cache_dir / "statcast"
    rows: list[dict[str, Any]] = []
    drops: Counter[str] = Counter()
    attempted: Counter[str] = Counter()
    run_time = datetime.now(timezone.utc)

    for target_date in sample_dates(plan):
        snapshot = statcast_snapshot(target_date, statcast_root)
        schedule = fetch_schedule(
            target_date.isoformat(),
            opener=transport,
            now=run_time,
        )
        source = MLBAllMarketHistorySource(opener=transport, retrieved_at=run_time)
        games = sorted(
            [g for g in schedule if str(g.status).lower() == "final"],
            key=lambda g: int(g.game_pk),
        )
        for game in games:
            try:
                box = fetch_boxscore(int(game.game_pk), opener=transport)
            except Exception as exc:  # noqa: BLE001
                raise HistoricalEvalError(
                    f"BOXSCORE_FETCH_FAILED:{game.game_pk}:{type(exc).__name__}"
                ) from exc
            # Prime the source's immutable boxscore cache so current/historical
            # lineup reconstruction is byte-identical to the target boxscore used here.
            try:
                from sportsedge.mlb_lineup_k_context_research import parse_boxscore
                source.__dict__.setdefault("_lineup_boxscore_cache", {})[int(game.game_pk)] = parse_boxscore(box)
            except Exception as exc:  # noqa: BLE001
                raise HistoricalEvalError(
                    f"BOXSCORE_LINEUP_PARSE_FAILED:{game.game_pk}:{type(exc).__name__}"
                ) from exc

            for side, team_id in (("away", int(game.away_id)), ("home", int(game.home_id))):
                attempted[str(target_date.year)] += 1
                starter = _starter(box, side)
                if starter is None:
                    drops["STARTER_OR_OUTCOME_UNAVAILABLE"] += 1
                    continue
                pitcher_id, realized_k, realized_bf = starter
                try:
                    candidate, history_pool = _candidate_for_starter(
                        source=source,
                        snapshot=snapshot,
                        target_date=target_date,
                        game_pk=int(game.game_pk),
                        away_team_id=int(game.away_id),
                        home_team_id=int(game.home_id),
                        pitcher_id=pitcher_id,
                        team_id=team_id,
                    )
                    row = build_historical_evaluation_row(
                        season=target_date.year,
                        target_date=target_date,
                        game_id=int(game.game_pk),
                        pitcher_id=pitcher_id,
                        candidate=candidate,
                        history_pool=history_pool,
                        realized_strikeouts=realized_k,
                        realized_batters_faced=realized_bf,
                    )
                except Exception as exc:  # noqa: BLE001
                    drops[type(exc).__name__ + ":" + str(exc).split(":", 1)[0][:80]] += 1
                    continue
                rows.append(row)

    rows.sort(key=lambda r: (int(r["season"]), str(r["target_date"]), int(r["game_id"]), int(r["pitcher_id"])))
    counts = Counter(str(row["season"]) for row in rows)
    return rows, dict(sorted(drops.items())), dict(sorted({**attempted, **{f"eligible_{k}": v for k, v in counts.items()}}.items()))


def render_report(payload: Mapping[str, Any]) -> str:
    ev = payload["evaluation"]
    split = ev["split"]
    metrics = ev["metrics"]
    ci = metrics["candidate_minus_incumbent_rps_ci"]
    lines = [
        "## MLB pitcher-K historical candidate evaluation v1",
        "",
        f"Plan SHA-256: `{payload['plan_sha256']}`.",
        f"Rows: 2023={split['training_rows']}, 2024={split['validation_rows']}, 2025={split['candidate_test_rows']}.",
        "",
        "| metric | candidate | incumbent / comparison |",
        "|---|---:|---:|",
        f"| mean RPS | {metrics['candidate_mean_rps']:.6f} | {metrics['incumbent_mean_rps']:.6f} |",
        f"| typical-line log loss | {metrics['candidate_typical_line_log_loss']:.6f} | {metrics['incumbent_typical_line_log_loss']:.6f} |",
        f"| typical-line ECE | {metrics['candidate_typical_line_ece']:.6f} | {metrics['incumbent_typical_line_ece']:.6f} |",
        f"| candidate - incumbent RPS | {ci['value']:.6f} | 95% CI [{ci['lo']:.6f}, {ci['hi']:.6f}] |",
        f"| count MAE | {metrics['candidate_count_mae']:.4f} | — |",
        "",
        f"Selected ridge alpha: **{ev['selection']['ridge_alpha']}**; beta-binomial concentration: **{ev['selection']['concentration']}**.",
        f"Development gate: **{'PASS' if ev['passes_development_gate'] else 'FAIL'}**.",
    ]
    if ev.get("blockers"):
        lines.append("Blockers: " + "; ".join(map(str, ev["blockers"])) + ".")
    drops = payload.get("drops") or {}
    if drops:
        lines += ["", "Drop counts: " + ", ".join(f"{k}={v}" for k, v in sorted(drops.items())) + "."]
    lines += [
        "",
        "Research-only readout. This candidate-test result does not create Model_P, ACTIONABLE, staking, OFFICIAL, or broader pitcher-prop promotion authority.",
    ]
    return "\n".join(lines) + "\n"


def run(plan_path: Path, *, cache_dir: Path, out_dir: Path, consume_candidate_test: bool) -> dict[str, Any]:
    if not consume_candidate_test:
        raise HistoricalEvalError("explicit --consume-candidate-test required")
    plan = load_plan(plan_path)
    plan_sha = _canonical_sha(plan_path)
    rows, drops, counts = materialize_rows(plan, cache_dir=cache_dir)
    evaluation = evaluate_pitcher_k_candidate(rows)
    payload = {
        "schema": OUTPUT_SCHEMA,
        "plan_sha256": plan_sha,
        "candidate_test_consumed": True,
        "historical_reconstruction": True,
        "forward_evidence_eligible": False,
        "promotion_authority": False,
        "rows": rows,
        "counts": counts,
        "drops": drops,
        "evaluation": evaluation,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "materialized_rows.json").write_text(
        json.dumps({"schema": OUTPUT_SCHEMA, "plan_sha256": plan_sha, "rows": rows, "counts": counts, "drops": drops}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out_dir / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path("config/research/mlb_pitcher_k_historical_eval_plan_v1.json"),
    )
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/mlb-pitcher-k-historical"))
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_pitcher_k_historical_eval"))
    parser.add_argument("--consume-candidate-test", action="store_true")
    args = parser.parse_args()
    run(
        args.plan,
        cache_dir=args.cache_dir,
        out_dir=args.out_dir,
        consume_candidate_test=args.consume_candidate_test,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
