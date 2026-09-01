"""Strict MLB promotion replay bridge bound to MLB_REPLAY_POLICY_V1.

Existing PIT observations prove model/history/identity/settlement provenance. This
layer attaches the exact paired decision/close sportsbook benchmark required for
promotion. It never changes Model_P, Truth Gate floors, or deployment eligibility.
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
_TEAM_SIDE_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "F5_MONEYLINE", "F5_RUN_LINE"})


class MLBPromotionReplayError(ValueError):
    pass


def _dt(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise MLBPromotionReplayError(f"{field}_REQUIRED")
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise MLBPromotionReplayError(f"{field}_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBPromotionReplayError(f"{field}_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _num(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise MLBPromotionReplayError(f"{field}_NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBPromotionReplayError(f"{field}_NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise MLBPromotionReplayError(f"{field}_FINITE_REQUIRED")
    return out


def _prob(value: Any, field: str) -> float:
    out = _num(value, field)
    if not 0.0 <= out <= 1.0:
        raise MLBPromotionReplayError(f"{field}_PROBABILITY_RANGE")
    return out


def _implied(odds: Any) -> float:
    x = _num(odds, "american_odds")
    if x == 0.0 or -100.0 < x < 100.0:
        raise MLBPromotionReplayError("AMERICAN_ODDS_INVALID")
    return 100.0 / (x + 100.0) if x > 0 else (-x) / ((-x) + 100.0)


def _profit(odds: Any) -> float:
    x = _num(odds, "american_odds")
    return x / 100.0 if x > 0 else 100.0 / (-x)


def _family(market: str, side: Any) -> str:
    s = str(side or "").strip().upper()
    if s in {"HOME", "HOME_ML", "HOME_RL"}: return "HOME"
    if s in {"AWAY", "AWAY_ML", "AWAY_RL"}: return "AWAY"
    if s == "OVER": return "OVER"
    if s == "UNDER": return "UNDER"
    if s in {"YES", "NRFI", "YRFI"}: return "YES"
    if s == "NO": return "NO"
    raise MLBPromotionReplayError(f"REPLAY_SIDE_UNSUPPORTED:{market}:{s}")


def _is_complement(a: str, b: str) -> bool:
    return frozenset((a, b)) in {
        frozenset(("HOME", "AWAY")), frozenset(("OVER", "UNDER")), frozenset(("YES", "NO")),
    }


def _pair_valid(market: str, a: Mapping[str, Any], b: Mapping[str, Any], target_entity: str) -> bool:
    sa, sb = str(a["side_family"]), str(b["side_family"])
    if not _is_complement(sa, sb): return False
    ea, eb = str(a["entity_id"]), str(b["entity_id"])
    if market in _TEAM_SIDE_MARKETS:
        if {sa, sb} != {"HOME", "AWAY"} or not ea or not eb or ea == eb: return False
        target_matches = [q for q in (a, b) if q["entity_id"] == target_entity]
        if len(target_matches) != 1: return False
    elif ea != target_entity or eb != target_entity:
        return False
    x, y = float(a["line"]), float(b["line"])
    if market in {"RUN_LINE", "F5_RUN_LINE"}:
        return abs(x + y) <= _EPS
    return abs(x - y) <= _EPS


def _normalize_quotes(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for raw in rows:
        q = validate_canonical_quote(raw, default_ttl_seconds=180)
        q["retrieved_at"] = _dt(q["retrieved_at"], "quote.retrieved_at")
        q["book_key"] = str(q["book_key"]).strip().lower()
        q["side_family"] = _family(q["market"], q["side"])
        key = (q["game_id"], q["period"], q["market"], q["entity_id"], q["book_key"], q["is_alternate"], q["side_family"], float(q["line"]), q["retrieved_at"], int(q["american_odds"]))
        if key in seen: raise MLBPromotionReplayError("REPLAY_QUOTE_DUPLICATE")
        seen.add(key); out.append(q)
    return out


def enrich_joined_pit_observations(*, join_payload: Mapping[str, Any], archive_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Restore exact period/alternate metadata from the immutable source quote."""
    ah = str(archive_payload.get("payload_sha256") or "").strip().lower()
    if not ah or str(join_payload.get("archive_payload_sha256") or "").strip().lower() != ah:
        raise MLBPromotionReplayError("REPLAY_JOIN_ARCHIVE_HASH_MISMATCH")
    quotes, observations = archive_payload.get("quotes"), join_payload.get("observations")
    if not isinstance(quotes, list) or not isinstance(observations, list):
        raise MLBPromotionReplayError("REPLAY_JOIN_OR_ARCHIVE_ROWS_REQUIRED")
    out = []
    for raw in observations:
        if not isinstance(raw, Mapping): raise MLBPromotionReplayError("REPLAY_JOIN_OBSERVATION_INVALID")
        try: idx = int(raw.get("source_index"))
        except (TypeError, ValueError) as exc: raise MLBPromotionReplayError("REPLAY_SOURCE_INDEX_INVALID") from exc
        if idx < 0 or idx >= len(quotes) or not isinstance(quotes[idx], Mapping): raise MLBPromotionReplayError("REPLAY_SOURCE_INDEX_OUT_OF_RANGE")
        q = quotes[idx]
        checks = (
            str(raw.get("market") or "").upper() == str(q.get("market") or "").upper(),
            str(raw.get("side") or "").upper() == str(q.get("side") or "").upper(),
            abs(_num(raw.get("line"), "joined.line") - _num(q.get("line"), "archive.line")) <= _EPS,
            str(raw.get("book_key") or "").strip().lower() == str(q.get("book_key") or "").strip().lower(),
            _dt(raw.get("quote_ts"), "joined.quote_ts") == _dt(q.get("quote_retrieved_at") or q.get("retrieved_at"), "archive.quote_ts"),
        )
        if not all(checks): raise MLBPromotionReplayError("REPLAY_JOIN_SOURCE_IDENTITY_MISMATCH")
        period, alt = str(q.get("period") or "").strip().upper(), q.get("is_alternate")
        if not period or type(alt) is not bool: raise MLBPromotionReplayError("REPLAY_SOURCE_PERIOD_ALTERNATE_REQUIRED")
        out.append({**dict(raw), "period": period, "is_alternate": alt})
    return out


def _tier(policy: Mapping[str, Any], market: str) -> tuple[str, tuple[str, ...]]:
    for name, raw in (((policy.get("benchmark") or {}).get("market_tiers") or {}).items()):
        if market not in (raw.get("markets") or []): continue
        if name == "N_WAY_UNAUTHORIZED_V1": raise MLBPromotionReplayError(f"REPLAY_MARKET_NWAY_UNAUTHORIZED:{market}")
        books = tuple(str(x).strip().lower() for x in (raw.get("book_hierarchy") or []) if str(x).strip())
        if not books: raise MLBPromotionReplayError(f"REPLAY_BOOK_HIERARCHY_EMPTY:{market}")
        return str(name), books
    raise MLBPromotionReplayError(f"REPLAY_MARKET_NOT_IN_POLICY:{market}")


def _pairs(quotes: Sequence[Mapping[str, Any]], *, game_id: str, period: str, market: str, entity_id: str, book: str, alt: bool, boundary: datetime, strict_before: bool, after: datetime | None, max_age: int | None, max_skew: int, exact_side: str | None = None, exact_line: float | None = None) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pool = []
    for q0 in quotes:
        q = dict(q0)
        if not (q["game_id"] == game_id and q["period"] == period and q["market"] == market and q["book_key"] == book and q["is_alternate"] is alt): continue
        if strict_before:
            if not q["retrieved_at"] < boundary: continue
        elif q["retrieved_at"] > boundary: continue
        if after is not None and not q["retrieved_at"] > after: continue
        if max_age is not None and not 0 <= (boundary - q["retrieved_at"]).total_seconds() <= max_age: continue
        pool.append(q)
    out = []
    for i, a in enumerate(pool):
        for b in pool[i + 1:]:
            if not _pair_valid(market, a, b, entity_id): continue
            if abs((a["retrieved_at"] - b["retrieved_at"]).total_seconds()) > max_skew: continue
            if exact_side is not None and exact_line is not None:
                chosen = [q for q in (a, b) if q["side_family"] == exact_side and q["entity_id"] == entity_id]
                if len(chosen) != 1 or abs(float(chosen[0]["line"]) - exact_line) > _EPS: continue
            out.append((a, b))
    return out


def _latest(pairs: Sequence[tuple[dict[str, Any], dict[str, Any]]]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not pairs: return None
    ranked = sorted(pairs, key=lambda p: max(p[0]["retrieved_at"], p[1]["retrieved_at"]), reverse=True)
    stamp = max(ranked[0][0]["retrieved_at"], ranked[0][1]["retrieved_at"])
    tied = [p for p in ranked if max(p[0]["retrieved_at"], p[1]["retrieved_at"]) == stamp]
    if len(tied) != 1: raise MLBPromotionReplayError("REPLAY_PAIR_AMBIGUOUS")
    return tied[0]


def _devig(pair: tuple[Mapping[str, Any], Mapping[str, Any]]) -> dict[str, float]:
    a, b = pair; pa, pb = _implied(a["american_odds"]), _implied(b["american_odds"]); total = pa + pb
    if total <= 0: raise MLBPromotionReplayError("REPLAY_DEVIG_DENOMINATOR_INVALID")
    return {str(a["side_family"]): pa / total, str(b["side_family"]): pb / total}


def _fold(policy: Mapping[str, Any], slate: date) -> str:
    for raw in policy["walk_forward"]["folds"]:
        if date.fromisoformat(raw["validation_start"]) <= slate <= date.fromisoformat(raw["validation_end"]): return str(raw["name"])
    hold = policy["walk_forward"]["untouched_forward_holdout"]
    if date.fromisoformat(hold["start"]) <= slate <= date.fromisoformat(hold["end"]): return "untouched_forward_holdout"
    raise MLBPromotionReplayError(f"REPLAY_SLATE_DATE_OUTSIDE_POLICY:{slate.isoformat()}")


@dataclass(frozen=True)
class MLBPromotionReplayRow:
    observation_key: str; game_id: str; market: str; entity_id: str; side: str; period: str
    line: float; is_alternate: bool; slate_date_ct: str; fold_name: str
    decision_ts: str; first_pitch_ts: str; book_tier: str; book_key: str; sportsbook: str | None
    decision_pair_max_ts: str; decision_side_odds: int; decision_no_vig_p: float
    model_p: float; edge_vs_decision: float
    close_pair_max_ts: str | None; close_side_odds: int | None; close_no_vig_p: float | None; clv_probability: float | None
    settlement_book_key: str | None; settlement_compatible: bool; settlement_state: str; settled_outcome: str | None; roi_per_dollar: float | None
    replay_policy_id: str; replay_policy_sha256: str


def build_mlb_promotion_replay(*, pit_observations: Iterable[Mapping[str, Any]], quote_rows: Iterable[Mapping[str, Any]], replay_policy: Mapping[str, Any], replay_policy_raw_bytes: bytes, generated_at: datetime) -> dict[str, Any]:
    identity = validate_replay_policy(replay_policy, raw_bytes=replay_policy_raw_bytes)
    generated = _dt(generated_at, "generated_at")
    if generated.date() < date.fromisoformat(str(replay_policy["effective_date"])): raise MLBPromotionReplayError("REPLAY_GENERATED_BEFORE_POLICY_FREEZE")
    observations = [dict(x) for x in pit_observations if isinstance(x, Mapping)]
    quotes = _normalize_quotes(quote_rows); bench = replay_policy["benchmark"]
    max_age, max_skew = int(bench["quote_max_age_seconds"]), int(bench["paired_side_max_timestamp_skew_seconds"])
    rows, exclusions, seen = [], [], set()
    for index, obs in enumerate(observations):
        try:
            key = str(obs.get("observation_key") or "").strip()
            if not key or key in seen: raise MLBPromotionReplayError("REPLAY_OBSERVATION_KEY_MISSING_OR_DUPLICATE")
            seen.add(key)
            if obs.get("source_evidence_class") != "LIVE_PROVIDER_QUOTE_ARCHIVE" or obs.get("model_evidence_class") != "LIVE_PIT_MODEL": raise MLBPromotionReplayError("REPLAY_DURABLE_PIT_MODEL_EVIDENCE_REQUIRED")
            market, game_id, entity_id = str(obs.get("market") or "").upper(), str(obs.get("game_id") or "").strip(), str(obs.get("entity_id") or "").strip()
            period, alt = str(obs.get("period") or "").strip().upper(), obs.get("is_alternate")
            if not period or type(alt) is not bool: raise MLBPromotionReplayError("REPLAY_PERIOD_ALTERNATE_REQUIRED")
            side = _family(market, obs.get("side")); decision = _dt(obs.get("quote_ts") or obs.get("decision_ts"), "decision_ts"); first_pitch = _dt(obs.get("first_pitch_ts"), "first_pitch_ts")
            if not decision < first_pitch: raise MLBPromotionReplayError("REPLAY_DECISION_NOT_PREGAME")
            model_p = _prob(obs.get("candidate_p"), "candidate_p"); tier, books = _tier(replay_policy, market)
            decision_pair = None; selected_book = None
            for book in books:
                decision_pair = _latest(_pairs(quotes, game_id=game_id, period=period, market=market, entity_id=entity_id, book=book, alt=alt, boundary=decision, strict_before=False, after=None, max_age=max_age, max_skew=max_skew))
                if decision_pair is not None: selected_book = book; break
            if decision_pair is None or selected_book is None: raise MLBPromotionReplayError("REPLAY_DECISION_PAIR_UNAVAILABLE")
            decision_probs = _devig(decision_pair)
            if side not in decision_probs: raise MLBPromotionReplayError("REPLAY_DECISION_SIDE_NOT_IN_PAIR")
            decision_side = [q for q in decision_pair if q["side_family"] == side and q["entity_id"] == entity_id]
            if len(decision_side) != 1: raise MLBPromotionReplayError("REPLAY_DECISION_SELECTED_ENTITY_AMBIGUOUS")
            dq = decision_side[0]; decision_p = decision_probs[side]; decision_max = max(q["retrieved_at"] for q in decision_pair)
            close_pair = _latest(_pairs(quotes, game_id=game_id, period=period, market=market, entity_id=entity_id, book=selected_book, alt=alt, boundary=first_pitch, strict_before=True, after=decision, max_age=None, max_skew=max_skew, exact_side=side, exact_line=float(dq["line"])))
            close_p = close_odds = close_max = None
            if close_pair is not None:
                cp = _devig(close_pair); close_p = cp.get(side)
                cq = [q for q in close_pair if q["side_family"] == side and q["entity_id"] == entity_id]
                if len(cq) != 1: raise MLBPromotionReplayError("REPLAY_CLOSE_SELECTED_ENTITY_AMBIGUOUS")
                close_odds = int(cq[0]["american_odds"]); close_max = max(q["retrieved_at"] for q in close_pair)
            settlement_book = str(obs.get("settlement_book_key") or obs.get("book_key") or "").strip().lower() or None
            compatible = bool(settlement_book == selected_book and obs.get("book_rule_evidence_class") == "LIVE_BOOK_RULE_CAPTURE" and obs.get("official_fact_evidence_class") == "LIVE_OFFICIAL_FACT_PROBE")
            state = str(obs.get("settlement_state") or "").upper(); outcome = None if obs.get("settled_outcome") in (None, "") else str(obs.get("settled_outcome")).upper(); roi = None
            if compatible and state == "SETTLEMENT_ELIGIBLE" and outcome in {"WIN", "LOSS", "PUSH"}: roi = _profit(dq["american_odds"]) if outcome == "WIN" else -1.0 if outcome == "LOSS" else 0.0
            slate = first_pitch.astimezone(_CT).date()
            rows.append(MLBPromotionReplayRow(key, game_id, market, entity_id, side, period, float(dq["line"]), alt, slate.isoformat(), _fold(replay_policy, slate), decision.isoformat(), first_pitch.isoformat(), tier, selected_book, dq.get("sportsbook"), decision_max.isoformat(), int(dq["american_odds"]), decision_p, model_p, model_p - decision_p, None if close_max is None else close_max.isoformat(), close_odds, close_p, None if close_p is None else close_p - decision_p, settlement_book, compatible, state, outcome, roi, identity["policy_id"], identity["policy_sha256"]))
        except Exception as exc:
            exclusions.append({"source_index": index, "observation_key": obs.get("observation_key"), "reason": f"{type(exc).__name__}:{exc}"})
    return {"schema_version": "MLB_PROMOTION_REPLAY_V1", "generated_at_utc": generated.isoformat(), "replay_policy": identity, "source_observation_count": len(observations), "eligible_row_count": len(rows), "exclusion_count": len(exclusions), "rows": [asdict(r) for r in rows], "exclusions": exclusions, "promotion_changed": False}
