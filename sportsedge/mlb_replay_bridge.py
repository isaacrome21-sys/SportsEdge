"""Promotion-grade MLB replay bridge for frozen PIT model observations and quotes.

This layer is deliberately separate from the older PIT observation contract.  It
never changes Model_P or deployment eligibility.  It attaches the exact paired
sportsbook benchmark required by MLB_REPLAY_POLICY_V1 to already-proven PIT model
and settlement observations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from sportsedge.quote_bridge import validate_canonical_quote
from sportsedge.sports.mlb.replay_policy import validate_replay_policy

_CT = ZoneInfo("America/Chicago")
_EPS = 1e-12


class MLBReplayBridgeError(ValueError):
    pass


def _dt(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        raw = str(value or "").strip().replace("Z", "+00:00")
        if not raw:
            raise MLBReplayBridgeError(f"{field}_REQUIRED")
        try:
            out = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise MLBReplayBridgeError(f"{field}_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBReplayBridgeError(f"{field}_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _num(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise MLBReplayBridgeError(f"{field}_NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBReplayBridgeError(f"{field}_NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise MLBReplayBridgeError(f"{field}_FINITE_REQUIRED")
    return out


def _prob(value: Any, field: str) -> float:
    out = _num(value, field)
    if not 0.0 <= out <= 1.0:
        raise MLBReplayBridgeError(f"{field}_PROBABILITY_RANGE")
    return out


def _american_implied(value: Any) -> float:
    odds = _num(value, "american_odds")
    if odds == 0.0 or -100.0 < odds < 100.0:
        raise MLBReplayBridgeError("AMERICAN_ODDS_INVALID")
    return 100.0 / (odds + 100.0) if odds > 0 else (-odds) / ((-odds) + 100.0)


def _american_profit_per_dollar(value: Any) -> float:
    odds = _num(value, "american_odds")
    return odds / 100.0 if odds > 0 else 100.0 / (-odds)


def _side_family(market: str, side: str) -> str:
    s = str(side or "").strip().upper()
    if s in {"HOME", "HOME_ML", "HOME_RL"}:
        return "HOME"
    if s in {"AWAY", "AWAY_ML", "AWAY_RL"}:
        return "AWAY"
    if s == "OVER":
        return "OVER"
    if s == "UNDER":
        return "UNDER"
    if s in {"YES", "NRFI", "YRFI"}:
        return "YES"
    if s == "NO":
        return "NO"
    raise MLBReplayBridgeError(f"REPLAY_SIDE_UNSUPPORTED:{market}:{s}")


def _complement(a: str, b: str) -> bool:
    return frozenset((a, b)) in {
        frozenset(("HOME", "AWAY")),
        frozenset(("OVER", "UNDER")),
        frozenset(("YES", "NO")),
    }


def _threshold_pair_valid(market: str, left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    a = float(left["line"]); b = float(right["line"])
    sa = _side_family(market, str(left["side"])); sb = _side_family(market, str(right["side"]))
    if not _complement(sa, sb):
        return False
    if {sa, sb} == {"HOME", "AWAY"} and market in {"RUN_LINE", "F5_RUN_LINE"}:
        return abs(a + b) <= _EPS
    return abs(a - b) <= _EPS


def _same_identity(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return all(
        a[key] == b[key]
        for key in ("game_id", "period", "market", "entity_id", "book_key", "is_alternate")
    )


def _normalize_quotes(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for raw in rows:
        q = validate_canonical_quote(raw, default_ttl_seconds=180)
        q["retrieved_at"] = _dt(q["retrieved_at"], "quote.retrieved_at")
        q["side_family"] = _side_family(q["market"], q["side"])
        key = (
            q["game_id"], q["period"], q["market"], q["entity_id"], q["book_key"],
            q["is_alternate"], q["side_family"], float(q["line"]), q["retrieved_at"], int(q["american_odds"]),
        )
        if key in seen:
            raise MLBReplayBridgeError("REPLAY_QUOTE_DUPLICATE")
        seen.add(key); out.append(q)
    return out


def _candidate_pairs(
    quotes: Sequence[Mapping[str, Any]], *,
    game_id: str, period: str, market: str, entity_id: str, book_key: str,
    is_alternate: bool, not_after: datetime, after: datetime | None,
    max_age_seconds: int | None, max_skew_seconds: int,
    exact_side: str | None = None, exact_line: float | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pool = [
        dict(q) for q in quotes
        if q["game_id"] == game_id and q["period"] == period and q["market"] == market
        and q["entity_id"] == entity_id and q["book_key"] == book_key
        and q["is_alternate"] is is_alternate and q["retrieved_at"] <= not_after
        and (after is None or q["retrieved_at"] > after)
    ]
    if max_age_seconds is not None:
        pool = [q for q in pool if 0.0 <= (not_after - q["retrieved_at"]).total_seconds() <= max_age_seconds]
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for i, left in enumerate(pool):
        for right in pool[i + 1:]:
            if not _same_identity(left, right):
                continue
            if not _threshold_pair_valid(market, left, right):
                continue
            if abs((left["retrieved_at"] - right["retrieved_at"]).total_seconds()) > max_skew_seconds:
                continue
            if exact_side is not None and exact_line is not None:
                selected = [q for q in (left, right) if q["side_family"] == exact_side]
                if len(selected) != 1 or abs(float(selected[0]["line"]) - exact_line) > _EPS:
                    continue
            pairs.append((left, right))
    return pairs


def _select_latest_pair(pairs: Sequence[tuple[dict[str, Any], dict[str, Any]]]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not pairs:
        return None
    ranked = sorted(pairs, key=lambda pair: max(pair[0]["retrieved_at"], pair[1]["retrieved_at"]), reverse=True)
    latest_ts = max(ranked[0][0]["retrieved_at"], ranked[0][1]["retrieved_at"])
    ties = [pair for pair in ranked if max(pair[0]["retrieved_at"], pair[1]["retrieved_at"]) == latest_ts]
    if len(ties) != 1:
        raise MLBReplayBridgeError("REPLAY_PAIR_AMBIGUOUS")
    return ties[0]


def _devig_pair(pair: tuple[Mapping[str, Any], Mapping[str, Any]]) -> dict[str, float]:
    left, right = pair
    raw_left = _american_implied(left["american_odds"]); raw_right = _american_implied(right["american_odds"])
    denom = raw_left + raw_right
    if denom <= 0.0:
        raise MLBReplayBridgeError("REPLAY_DEVIG_DENOMINATOR_INVALID")
    return {str(left["side_family"]): raw_left / denom, str(right["side_family"]): raw_right / denom}


def _policy_tier(policy: Mapping[str, Any], market: str) -> tuple[str, tuple[str, ...]]:
    tiers = ((policy.get("benchmark") or {}).get("market_tiers") or {})
    for tier_name, raw in tiers.items():
        if market in (raw.get("markets") or []):
            if tier_name == "N_WAY_UNAUTHORIZED_V1":
                raise MLBReplayBridgeError(f"REPLAY_MARKET_NWAY_UNAUTHORIZED:{market}")
            books = tuple(str(x) for x in raw.get("book_hierarchy") or [])
            if not books:
                raise MLBReplayBridgeError(f"REPLAY_BOOK_HIERARCHY_EMPTY:{market}")
            return str(tier_name), books
    raise MLBReplayBridgeError(f"REPLAY_MARKET_NOT_IN_POLICY:{market}")


def _fold_name(policy: Mapping[str, Any], slate_date: date) -> str:
    walk = policy["walk_forward"]
    for raw in walk["folds"]:
        if date.fromisoformat(raw["validation_start"]) <= slate_date <= date.fromisoformat(raw["validation_end"]):
            return str(raw["name"])
    hold = walk["untouched_forward_holdout"]
    if date.fromisoformat(hold["start"]) <= slate_date <= date.fromisoformat(hold["end"]):
        return "untouched_forward_holdout"
    raise MLBReplayBridgeError(f"REPLAY_SLATE_DATE_OUTSIDE_POLICY:{slate_date.isoformat()}")


@dataclass(frozen=True)
class MLBReplayEvidenceRow:
    observation_key: str
    game_id: str
    market: str
    entity_id: str
    side: str
    period: str
    line: float
    is_alternate: bool
    decision_ts: str
    first_pitch_ts: str
    slate_date_ct: str
    fold_name: str
    book_tier: str
    book_key: str
    sportsbook: str | None
    decision_pair_max_ts: str
    decision_side_odds: int
    decision_no_vig_p: float
    close_pair_max_ts: str | None
    close_side_odds: int | None
    close_no_vig_p: float | None
    clv_probability: float | None
    model_p: float
    edge_vs_decision: float
    settlement_state: str
    settled_outcome: str | None
    roi_per_dollar: float | None
    replay_policy_id: str
    replay_policy_sha256: str


def build_mlb_replay_rows(
    *,
    pit_observations: Iterable[Mapping[str, Any]],
    quote_rows: Iterable[Mapping[str, Any]],
    replay_policy: Mapping[str, Any],
    replay_policy_raw_bytes: bytes,
    generated_at: datetime,
) -> dict[str, Any]:
    identity = validate_replay_policy(replay_policy, raw_bytes=replay_policy_raw_bytes)
    generated = _dt(generated_at, "generated_at")
    effective = date.fromisoformat(str(replay_policy["effective_date"]))
    if generated.date() < effective:
        raise MLBReplayBridgeError("REPLAY_GENERATED_BEFORE_POLICY_FREEZE")
    benchmark = replay_policy["benchmark"]
    max_age = int(benchmark["quote_max_age_seconds"])
    max_skew = int(benchmark["paired_side_max_timestamp_skew_seconds"])
    quotes = _normalize_quotes(quote_rows)

    evidence: list[MLBReplayEvidenceRow] = []
    exclusions: list[dict[str, Any]] = []
    seen_observations: set[str] = set()
    for index, raw_obs in enumerate(pit_observations):
        try:
            obs = dict(raw_obs)
            observation_key = str(obs.get("observation_key") or "").strip()
            if not observation_key or observation_key in seen_observations:
                raise MLBReplayBridgeError("REPLAY_OBSERVATION_KEY_MISSING_OR_DUPLICATE")
            seen_observations.add(observation_key)
            if obs.get("source_evidence_class") != "LIVE_PROVIDER_QUOTE_ARCHIVE" or obs.get("model_evidence_class") != "LIVE_PIT_MODEL":
                raise MLBReplayBridgeError("REPLAY_DURABLE_PIT_MODEL_EVIDENCE_REQUIRED")
            market = str(obs.get("market") or "").upper(); game_id = str(obs.get("game_id") or "").strip()
            entity_id = str(obs.get("entity_id") or "").strip(); period = str(obs.get("period") or "FG").upper()
            side = _side_family(market, str(obs.get("side") or "")); line = _num(obs.get("line"), "observation.line")
            alternate = bool(obs.get("is_alternate", False))
            decision_ts = _dt(obs.get("quote_ts") or obs.get("decision_ts"), "decision_ts")
            first_pitch = _dt(obs.get("first_pitch_ts"), "first_pitch_ts")
            if not decision_ts < first_pitch:
                raise MLBReplayBridgeError("REPLAY_DECISION_NOT_PREGAME")
            model_p = _prob(obs.get("candidate_p"), "candidate_p")
            tier, hierarchy = _policy_tier(replay_policy, market)

            decision_pair = None; selected_book = None
            for book in hierarchy:
                pairs = _candidate_pairs(
                    quotes, game_id=game_id, period=period, market=market, entity_id=entity_id,
                    book_key=book, is_alternate=alternate, not_after=decision_ts, after=None,
                    max_age_seconds=max_age, max_skew_seconds=max_skew,
                )
                picked = _select_latest_pair(pairs)
                if picked is not None:
                    decision_pair = picked; selected_book = book; break
            if decision_pair is None or selected_book is None:
                raise MLBReplayBridgeError("REPLAY_DECISION_PAIR_UNAVAILABLE")
            decision_probs = _devig_pair(decision_pair)
            if side not in decision_probs:
                raise MLBReplayBridgeError("REPLAY_DECISION_SIDE_NOT_IN_PAIR")
            decision_p = decision_probs[side]
            decision_side_quote = next(q for q in decision_pair if q["side_family"] == side)
            decision_pair_max = max(q["retrieved_at"] for q in decision_pair)

            close_pairs = _candidate_pairs(
                quotes, game_id=game_id, period=period, market=market, entity_id=entity_id,
                book_key=selected_book, is_alternate=alternate, not_after=first_pitch,
                after=decision_ts, max_age_seconds=None, max_skew_seconds=max_skew,
                exact_side=side, exact_line=float(decision_side_quote["line"]),
            )
            close_pair = _select_latest_pair(close_pairs)
            close_p = None; close_odds = None; close_pair_max = None
            if close_pair is not None:
                close_probs = _devig_pair(close_pair)
                close_p = close_probs.get(side)
                close_side_quote = next(q for q in close_pair if q["side_family"] == side)
                close_odds = int(close_side_quote["american_odds"])
                close_pair_max = max(q["retrieved_at"] for q in close_pair)
                if not close_pair_max < first_pitch:
                    raise MLBReplayBridgeError("REPLAY_CLOSE_NOT_BEFORE_FIRST_PITCH")

            slate_date = first_pitch.astimezone(_CT).date()
            fold = _fold_name(replay_policy, slate_date)
            settlement_state = str(obs.get("settlement_state") or "").upper()
            outcome_raw = obs.get("settled_outcome")
            outcome = None if outcome_raw in (None, "") else str(outcome_raw).upper()
            roi = None
            if settlement_state == "SETTLEMENT_ELIGIBLE" and outcome in {"WIN", "LOSS", "PUSH"}:
                if outcome == "WIN":
                    roi = _american_profit_per_dollar(decision_side_quote["american_odds"])
                elif outcome == "LOSS":
                    roi = -1.0
                else:
                    roi = 0.0

            evidence.append(MLBReplayEvidenceRow(
                observation_key=observation_key, game_id=game_id, market=market, entity_id=entity_id,
                side=side, period=period, line=float(decision_side_quote["line"]), is_alternate=alternate,
                decision_ts=decision_ts.isoformat(), first_pitch_ts=first_pitch.isoformat(),
                slate_date_ct=slate_date.isoformat(), fold_name=fold, book_tier=tier,
                book_key=selected_book, sportsbook=decision_side_quote.get("sportsbook"),
                decision_pair_max_ts=decision_pair_max.isoformat(), decision_side_odds=int(decision_side_quote["american_odds"]),
                decision_no_vig_p=decision_p, close_pair_max_ts=None if close_pair_max is None else close_pair_max.isoformat(),
                close_side_odds=close_odds, close_no_vig_p=close_p,
                clv_probability=None if close_p is None else close_p - decision_p,
                model_p=model_p, edge_vs_decision=model_p - decision_p,
                settlement_state=settlement_state, settled_outcome=outcome, roi_per_dollar=roi,
                replay_policy_id=identity["policy_id"], replay_policy_sha256=identity["policy_sha256"],
            ))
        except Exception as exc:
            exclusions.append({"source_index": index, "observation_key": raw_obs.get("observation_key") if isinstance(raw_obs, Mapping) else None, "reason": f"{type(exc).__name__}:{exc}"})

    return {
        "schema_version": "MLB_PROMOTION_REPLAY_ROWS_V1",
        "generated_at_utc": generated.isoformat(),
        "replay_policy": identity,
        "source_observation_count": len(list(pit_observations)) if isinstance(pit_observations, Sequence) else len(evidence) + len(exclusions),
        "eligible_row_count": len(evidence),
        "exclusion_count": len(exclusions),
        "rows": [asdict(row) for row in evidence],
        "exclusions": exclusions,
        "promotion_changed": False,
    }
