"""2025 CFB holdout against CFBD last-stored closes.

Grades a market-blind joint score model after the fact. Closes are last stored
CFBD lines, not timestamped snapshots. This module never trains on lines, never
emits Model_P, and never grants promotion, staking, or OFFICIAL authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import exp, isfinite
from typing import Any, Iterable, Mapping, Sequence

CFB_2025_HOLDOUT_CONTRACT = "CFB_2025_LAST_STORED_CLOSE_HOLDOUT_V1"
CLOSE_SEMANTICS = "LAST_STORED_CLOSE_NOT_TIMESTAMPED_SNAPSHOT"
PHONE_NO_MODEL_PENDING = "NO_MODEL:CFB_2025_HOLDOUT_INCOMPLETE"
PHONE_NO_MODEL_FAIL = "NO_MODEL:CFB_2025_HOLDOUT_FAILED"
PHONE_NO_MODEL_PASS_UNPROMOTED = "NO_MODEL:CFB_PROMOTION_NOT_GRANTED"

_BANNED_SCORE_KEYS = frozenset({
    "spread", "spread_line", "total", "total_line", "line", "price", "american_odds",
    "decimal_odds", "implied_probability", "implied_prob", "market_probability",
    "novig_prob", "no_vig_prob", "book", "sportsbook", "closing_line", "closing_price",
    "home_moneyline", "away_moneyline", "odds", "sp+", "spplus", "sp_plus",
    "espn_fpi", "fpi", "outside_projection", "consensus", "confidence_0_100",
})


class CFB2025HoldoutError(ValueError):
    pass


def _num(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFB2025HoldoutError(f"CFB_HOLDOUT_NUMERIC_REQUIRED:{name}") from exc
    if not isfinite(out):
        raise CFB2025HoldoutError(f"CFB_HOLDOUT_NONFINITE:{name}")
    return out


def _assert_score_clean(score: Mapping[str, Any]) -> None:
    for key in score:
        name = str(key).strip().lower().replace(" ", "_")
        if name in _BANNED_SCORE_KEYS or "implied_prob" in name or "no_vig" in name:
            raise CFB2025HoldoutError(f"CFB_HOLDOUT_SCORE_CONTAMINATED:{key}")


def cover_probability_from_means(
    pred_home: float, pred_away: float, home_spread_close: float, *, sigma: float = 16.0
) -> float:
    """Normal-margin approximation used only to bucket confidence after means exist."""
    if sigma <= 0:
        raise CFB2025HoldoutError("CFB_HOLDOUT_SIGMA_INVALID")
    margin = pred_home - pred_away
    # Home covers when realized margin + home_spread > 0.
    z = (margin + home_spread_close) / sigma
    return 1.0 / (1.0 + exp(-1.702 * z))


def _result(diff: float) -> str:
    if abs(diff) < 1e-12:
        return "PUSH"
    return "WIN" if diff > 0 else "LOSS"


@dataclass(frozen=True)
class CFBHoldoutRowGrade:
    game_id: str
    market: str
    model_side: str
    result: str
    edge: float
    high_confidence: bool


@dataclass(frozen=True)
class CFBHoldoutMarketReport:
    market: str
    n_graded: int
    n_win: int
    n_loss: int
    n_push: int
    hit_rate: float | None
    n_high: int
    high_hit_rate: float | None


@dataclass(frozen=True)
class CFBHoldoutReport:
    contract: str
    close_semantics: str
    status: str
    phone_card_status: str
    saturday_pricing_allowed: bool
    promotion_authority: bool
    contamination: bool
    markets: dict[str, CFBHoldoutMarketReport]
    blocker: str | None
    n_rows: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["markets"] = {k: asdict(v) for k, v in self.markets.items()}
        return payload


def saturday_card_status(lock: Mapping[str, Any]) -> str:
    """Phone/Saturday status. Pricing is never implied by this helper."""
    if bool(lock.get("saturday_pricing_allowed")):
        raise CFB2025HoldoutError("CFB_HOLDOUT_SATURDAY_PRICING_FLAG_FORBIDDEN")
    if bool(lock.get("promotion_authority")) or bool(lock.get("model_p_authority")):
        raise CFB2025HoldoutError("CFB_HOLDOUT_LOCK_MUST_DENY_PROMOTION")
    status = str(lock.get("status") or "").strip().upper()
    if status == "HOLD_FAIL":
        return PHONE_NO_MODEL_FAIL
    if status == "HOLD_PASS":
        return PHONE_NO_MODEL_PASS_UNPROMOTED
    return PHONE_NO_MODEL_PENDING


def _summarize(grades: Sequence[CFBHoldoutRowGrade], market: str) -> CFBHoldoutMarketReport:
    rows = [g for g in grades if g.market == market]
    decided = [g for g in rows if g.result != "PUSH"]
    wins = [g for g in decided if g.result == "WIN"]
    high = [g for g in decided if g.high_confidence]
    high_wins = [g for g in high if g.result == "WIN"]
    return CFBHoldoutMarketReport(
        market=market,
        n_graded=len(decided),
        n_win=len(wins),
        n_loss=len(decided) - len(wins),
        n_push=sum(1 for g in rows if g.result == "PUSH"),
        hit_rate=(len(wins) / len(decided)) if decided else None,
        n_high=len(high),
        high_hit_rate=(len(high_wins) / len(high)) if high else None,
    )


def grade_cfb_2025_holdout(
    rows: Iterable[Mapping[str, Any]],
    *,
    lock: Mapping[str, Any],
    edge_floor: float | None = None,
    min_ats_graded: int | None = None,
    min_high_ats: int | None = None,
    high_hit_min: float | None = None,
) -> CFBHoldoutReport:
    rules = lock.get("pass_rule") if isinstance(lock.get("pass_rule"), Mapping) else {}
    edge_floor = float(edge_floor if edge_floor is not None else rules.get("high_confidence_edge_floor") or 0.08)
    min_ats_graded = int(min_ats_graded if min_ats_graded is not None else rules.get("min_ats_graded") or 200)
    min_high_ats = int(min_high_ats if min_high_ats is not None else rules.get("min_high_confidence_ats") or 40)
    high_hit_min = float(high_hit_min if high_hit_min is not None else rules.get("high_confidence_ats_min_hit") or 0.52)

    saturday_card_status(lock)

    data = [dict(row) for row in rows]
    grades: list[CFBHoldoutRowGrade] = []
    for row in data:
        score = row.get("score")
        if not isinstance(score, Mapping):
            raise CFB2025HoldoutError("CFB_HOLDOUT_SCORE_REQUIRED")
        _assert_score_clean(score)
        game_id = str(row.get("game_id") or "").strip() or "UNKNOWN"
        pred_home = _num(score.get("pred_home"), "pred_home")
        pred_away = _num(score.get("pred_away"), "pred_away")
        home = _num(row.get("home_score"), "home_score")
        away = _num(row.get("away_score"), "away_score")
        close = row.get("cfbd_last_stored_close")
        if not isinstance(close, Mapping):
            raise CFB2025HoldoutError("CFB_HOLDOUT_CLOSE_REQUIRED")
        if str(close.get("semantics") or "") != CLOSE_SEMANTICS:
            raise CFB2025HoldoutError("CFB_HOLDOUT_CLOSE_SEMANTICS_INVALID")

        if close.get("home_spread") is not None:
            spread = _num(close.get("home_spread"), "home_spread")
            p_cover = cover_probability_from_means(pred_home, pred_away, spread)
            edge = abs(p_cover - 0.5)
            pred_cover = (pred_home - pred_away) + spread
            real_cover = (home - away) + spread
            model_side = "HOME" if pred_cover > 0 else ("AWAY" if pred_cover < 0 else "PUSH")
            if model_side == "PUSH":
                result = "PUSH"
            else:
                result = _result(real_cover if model_side == "HOME" else -real_cover)
            grades.append(CFBHoldoutRowGrade(game_id, "ATS", model_side, result, edge, edge >= edge_floor and result != "PUSH"))

        if close.get("total") is not None:
            total = _num(close.get("total"), "total")
            pred_total = pred_home + pred_away
            real_total = home + away
            model_side = "OVER" if pred_total > total else ("UNDER" if pred_total < total else "PUSH")
            real_diff = real_total - total
            if model_side == "PUSH":
                result = "PUSH"
                edge = 0.0
            else:
                result = _result(real_diff if model_side == "OVER" else -real_diff)
                edge = abs(pred_total - total) / 14.0
            grades.append(CFBHoldoutRowGrade(game_id, "TOTAL", model_side, result, edge, edge >= edge_floor and result != "PUSH"))

        if close.get("home_moneyline") is not None:
            pred_margin = pred_home - pred_away
            real_margin = home - away
            model_side = "HOME" if pred_margin > 0 else ("AWAY" if pred_margin < 0 else "PUSH")
            if model_side == "PUSH" or real_margin == 0:
                result = "PUSH"
                edge = 0.0
            else:
                result = _result(real_margin if model_side == "HOME" else -real_margin)
                p_home = cover_probability_from_means(pred_home, pred_away, 0.0)
                edge = abs(p_home - 0.5)
            grades.append(CFBHoldoutRowGrade(game_id, "ML", model_side, result, edge, edge >= edge_floor and result != "PUSH"))

    markets = {
        name: _summarize(grades, name) for name in ("ATS", "TOTAL", "ML")
    }
    ats = markets["ATS"]
    if not data:
        status = "HOLD_PENDING"
        blocker = "CFB_2025_HOLDOUT_BUNDLE_NOT_MATERIALIZED"
    elif ats.n_graded < min_ats_graded or ats.n_high < min_high_ats:
        status = "HOLD_PENDING"
        blocker = "CFB_2025_HOLDOUT_SAMPLE_INSUFFICIENT"
    elif ats.high_hit_rate is None or ats.high_hit_rate < high_hit_min:
        status = "HOLD_FAIL"
        blocker = "CFB_2025_HOLDOUT_HIGH_CONFIDENCE_ATS_FAILED"
    else:
        status = "HOLD_PASS"
        blocker = None

    phone = {
        "HOLD_PENDING": PHONE_NO_MODEL_PENDING,
        "HOLD_FAIL": PHONE_NO_MODEL_FAIL,
        "HOLD_PASS": PHONE_NO_MODEL_PASS_UNPROMOTED,
    }[status]

    return CFBHoldoutReport(
        contract=CFB_2025_HOLDOUT_CONTRACT,
        close_semantics=CLOSE_SEMANTICS,
        status=status,
        phone_card_status=phone,
        saturday_pricing_allowed=False,
        promotion_authority=False,
        contamination=False,
        markets=markets,
        blocker=blocker,
        n_rows=len(data),
    )


__all__ = [
    "CFB_2025_HOLDOUT_CONTRACT",
    "CLOSE_SEMANTICS",
    "CFB2025HoldoutError",
    "CFBHoldoutReport",
    "cover_probability_from_means",
    "grade_cfb_2025_holdout",
    "saturday_card_status",
]
