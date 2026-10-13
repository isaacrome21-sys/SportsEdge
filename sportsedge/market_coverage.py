"""Phase 7 market-coverage extensions: MLB 3-way, NFL/CFB quarter markets, margin bands.

Every pricer here derives from the same verified ``artifacts.free_models``
context pipeline (``PublicContext`` + ``context_for``) and the same declared
distribution families (Poisson for MLB, normal for football) as the existing
game ML/spread/total engine. Base means retain the same active terms
(team-strength, static home-field, verified injuries and weather). The Oct 13
owner ruling disables unvalidated ERA-based starting pitcher, recent form and
rest adjustments across canonical and derivative game pricing; values remain
in context for research, with an exactly zero priced contribution. Never
drop verified injury/participation context (see 2026-10-11 incident:
a participation-blind 1H price manufactured a fake edge on Lamar-out news).

New declared (unfitted, unvalidated) assumptions, all constants below:
- QUARTER_FRACTION = 0.25 of each full-game mean per quarter.
- Quarter total/margin sds = full-game sds / 2 (iid-quarter variance scaling).
- Quarter team-total sd = quarter total sd / sqrt(2) (independent equal-variance
  team scores -- the same structural assumption the base model already makes).
- MLB 3-way 9-inning result assumes both clubs complete nine offensive
  half-innings; the home bottom-9th truncation (home does not bat when leading
  after the top of the 9th) is NOT modeled.
- Margin bands discretize the normal margin with +/-0.5 continuity correction;
  the tie mass uses the normal density at 0 (declared approximation).

Research only. No Model_P, no Truth Gate, no staking. Harness verdicts for
each market are recorded in docs/market_coverage_phase7.md; nothing here is
validated vs closes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import exp, pi, sqrt
from typing import Any, Mapping

from artifacts.free_models import (
    PRIORS,
    PublicContext,
    bounded,
    cdf,
    context_for,
    dt,
    numeric,
    odds_decimal,
    poisson,
)

COVERAGE_VERSION = "market_coverage_v1_20261011"

QUARTER_FRACTION = 0.25

# Markets whose pricers are implemented and unit-tested but FAILED harness
# validation vs the naive baseline (2026-10-11, chronological out-of-sample).
# They are recognized for routing but always fail closed until a verifying
# model exists. This is the correct outcome, not a failure to report.
FAILED_VALIDATION_MARKETS = frozenset({
    "TOTAL_1Q", "TOTAL_2Q", "TOTAL_3Q", "TOTAL_4Q",
    "TEAM_TOTAL_1Q", "TEAM_TOTAL_2Q", "TEAM_TOTAL_3Q", "TEAM_TOTAL_4Q",
    "ML_3WAY",
})

COVERAGE_MARKETS = frozenset({
    "ML_3WAY",
    "SPREAD_1Q", "SPREAD_2Q", "SPREAD_3Q", "SPREAD_4Q",
    "TOTAL_1Q", "TOTAL_2Q", "TOTAL_3Q", "TOTAL_4Q",
    "ML_1Q", "ML_2Q", "ML_3Q", "ML_4Q",
    "TEAM_TOTAL_1Q", "TEAM_TOTAL_2Q", "TEAM_TOTAL_3Q", "TEAM_TOTAL_4Q",
    "MARGIN_BAND",
})

COVERAGE_ALIASES = {
    "MLB_3WAY": "ML_3WAY",
    "3WAY_ML": "ML_3WAY",
    "MONEYLINE_3WAY": "ML_3WAY",
    "THREE_WAY_MONEYLINE": "ML_3WAY",
    "FIRST_QUARTER_SPREAD": "SPREAD_1Q",
    "SECOND_QUARTER_SPREAD": "SPREAD_2Q",
    "THIRD_QUARTER_SPREAD": "SPREAD_3Q",
    "FOURTH_QUARTER_SPREAD": "SPREAD_4Q",
    "FIRST_QUARTER_TOTAL": "TOTAL_1Q",
    "SECOND_QUARTER_TOTAL": "TOTAL_2Q",
    "THIRD_QUARTER_TOTAL": "TOTAL_3Q",
    "FOURTH_QUARTER_TOTAL": "TOTAL_4Q",
    "FIRST_QUARTER_MONEYLINE": "ML_1Q",
    "SECOND_QUARTER_MONEYLINE": "ML_2Q",
    "THIRD_QUARTER_MONEYLINE": "ML_3Q",
    "FOURTH_QUARTER_MONEYLINE": "ML_4Q",
    "WINNING_MARGIN": "MARGIN_BAND",
    "MARGIN_OF_VICTORY": "MARGIN_BAND",
}

COVERAGE_SPORTS = frozenset({"MLB", "NFL", "CFB"})
QUARTER_SPORTS = frozenset({"NFL", "CFB"})

MARGIN_BANDS = (
    ("HOME_1_6", "HOME", 1, 6),
    ("HOME_7_12", "HOME", 7, 12),
    ("HOME_13_18", "HOME", 13, 18),
    ("HOME_19_24", "HOME", 19, 24),
    ("HOME_25_PLUS", "HOME", 25, None),
    ("AWAY_1_6", "AWAY", 1, 6),
    ("AWAY_7_12", "AWAY", 7, 12),
    ("AWAY_13_18", "AWAY", 13, 18),
    ("AWAY_19_24", "AWAY", 19, 24),
    ("AWAY_25_PLUS", "AWAY", 25, None),
)
_MARGIN_BAND_SET = frozenset(b[0] for b in MARGIN_BANDS)


class MarketCoverageError(ValueError):
    pass


def normalize_coverage_market(market: Any) -> str | None:
    """Return the canonical coverage market id, or None when not a coverage market."""
    if not isinstance(market, str):
        return None
    m = market.strip().upper().replace(" ", "_").replace("-", "_")
    m = COVERAGE_ALIASES.get(m, m)
    return m if m in COVERAGE_MARKETS else None


def quarter_of(market: str) -> int | None:
    if market.rsplit("_", 1)[-1] in {"1Q", "2Q", "3Q", "4Q"}:
        return int(market[-2])
    return None


def blocked(row: Mapping[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    out = {
        "status": "NO_MODEL_OR_MARKET",
        "reason": str(reason)[:180],
        "sport": str(row.get("sport") or "").upper(),
        "market": str(row.get("market") or "").upper(),
        "selection": row.get("side") or row.get("selection"),
        "research_only": True,
        "official_authority": False,
        "model_p_authority": False,
        "staking_authority": False,
    }
    out.update(extra)
    return out


def _norm_key(value: Any) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in str(value)).split())


def _resolve_side_token(row: Mapping[str, Any], home: str, away: str) -> str | None:
    raw = str(row.get("side") or row.get("selection") or "").strip().upper()
    token = raw.replace(" ", "_").replace("-", "_").replace("+", "_PLUS")
    if token in {"HOME", "AWAY", "TIE", "OVER", "UNDER"} or token in _MARGIN_BAND_SET:
        return token
    key = _norm_key(raw)
    if key and key == _norm_key(home):
        return "HOME"
    if key and key == _norm_key(away):
        return "AWAY"
    # TEAM_TOTAL quarter sides: HOME_OVER / AWAY_UNDER style.
    if token in {"HOME_OVER", "HOME_UNDER", "AWAY_OVER", "AWAY_UNDER"}:
        return token
    return None


def _base_means(row: Mapping[str, Any], *, now: datetime,
                getter=None, auto_context: bool = True,
                provider: PublicContext | None = None) -> dict[str, Any]:
    """Mirror canonical *active-factor* means (disabled adjustments stay zero).

    Returns {"home_mean", "away_mean", "context", "context_notes", "kickoff"}.
    The unvalidated ERA pitcher, recent form and rest heuristics may be
    retained in the context, but cannot alter the projection or price.
    Raises MarketCoverageError with a BLOCKED_*/NO_* reason when the base game
    cannot be verified -- coverage markets never price without verified means.
    """
    sport = str(row.get("sport") or "").upper().strip()
    if sport not in COVERAGE_SPORTS:
        raise MarketCoverageError("COVERAGE_SPORT_UNSUPPORTED:" + sport)
    away = str(row.get("away") or "").strip()
    home = str(row.get("home") or "").strip()
    if not home or not away or home == away:
        game = str(row.get("game") or "")
        if " @ " in game:
            away, home = (s.strip() for s in game.split(" @ ", 1))
    if not away or not home or away == home:
        raise MarketCoverageError("AWAY_HOME_REQUIRED")
    original_start = dt(row.get("commence_time") or row.get("kickoff"))
    if row.get("commence_time") or row.get("kickoff"):
        if original_start is None:
            raise MarketCoverageError("KICKOFF_TIMESTAMP_INVALID")
    if original_start is not None and original_start <= now:
        raise MarketCoverageError("BLOCKED_STARTED")
    provider = provider if provider is not None else PublicContext(now, getter=getter)
    context = {k: 0.0 for k in
               {"NFL": ("home_rating", "away_rating", "home_injury_pts",
                        "away_injury_pts", "home_form", "away_form", "weather_total_adj"),
                "CFB": ("home_rating", "away_rating", "home_injury_pts",
                        "away_injury_pts", "home_form", "away_form", "weather_total_adj"),
                "MLB": ("home_rating", "away_rating", "home_pitcher_adj",
                        "away_pitcher_adj", "weather_total_adj")}[sport]}
    notes: list[str] = [] if auto_context else ["NO_FETCH_MANUAL_MODE_NO_PUBLIC_CONTEXT"]
    kickoff = original_start
    if auto_context:
        inferred, verified_start, notes = context_for(
            sport, away, home, original_start, provider, row)
        context.update(inferred)
        if verified_start is not None:
            kickoff = verified_start
        elif original_start is not None:
            raise MarketCoverageError(
                "BLOCKED_CONTEXT_UNVERIFIED:" + ",".join(notes))
    overrides = row.get("context") or {}
    for key in context:
        val = overrides.get(key, row.get(key))
        if val is not None:
            n = numeric(val, key)
            if abs(n) > 15:
                raise MarketCoverageError("CONTEXT_ADJUSTMENT_UNBOUNDED:" + key)
            context[key] = n
    if kickoff is None or kickoff <= now:
        raise MarketCoverageError("BLOCKED_KICKOFF_UNVERIFIED")
    base, _, _, hfa = PRIORS[sport]
    home_mean = base + hfa / 2 + context["home_rating"]
    away_mean = base - hfa / 2 + context["away_rating"]
    if sport == "MLB":
        # Owner Oct 13 disable ruling: ERA starting-pitcher heuristics are
        # observed research values, but have exactly ZERO pricing authority.
        # Unlike an absent feature this is a deliberate execution gate.
        notes.append("PITCHER_ADJ_DISABLED_PENDING_INCREMENTAL_VALUE")
    else:
        # Injury/participation stays ACTIVE; unvalidated recent form does
        # not. Do not regress into the participation-blind simplified path.
        home_mean += context["home_injury_pts"]
        away_mean += context["away_injury_pts"]
        notes.append("RECENT_FORM_DISABLED_PENDING_INCREMENTAL_VALUE")
    if "weather_total_adj" in context:
        home_mean += context["weather_total_adj"] / 2
        away_mean += context["weather_total_adj"] / 2
    if min(home_mean, away_mean) < 0.2:
        raise MarketCoverageError("IMPLAUSIBLE_SCORE_MEAN")
    return {"home_mean": home_mean, "away_mean": away_mean,
            "context": context, "context_notes": notes,
            "kickoff": kickoff, "receipts": provider.receipts}


def _normal_win_push(market: str, side: str, line: float | None,
                     home_mean: float, away_mean: float,
                     sd_total: float, sd_margin: float) -> tuple[float, float]:
    """Mirror free_models.model_probability's normal branch with explicit sds."""
    if market == "TOTAL":
        mean = home_mean + away_mean
        sd = sd_total
        sign = 1 if side == "OVER" else -1
        decision = line
    else:
        mean = home_mean - away_mean if side == "HOME" else away_mean - home_mean
        sd = sd_margin
        sign = 1
        decision = -line if market == "SPREAD" else 0
    whole = market != "ML" and line is not None and float(line).is_integer()
    push = cdf(decision + 0.5, mean, sd) - cdf(decision - 0.5, mean, sd) if whole else 0.0
    cut = decision + (0.5 if whole else 0)
    win = (1 - cdf(cut, mean, sd)) if sign > 0 else cdf(decision - (0.5 if whole else 0), mean, sd)
    return bounded(win, 0, 1), bounded(push, 0, 1)


def _mlb_3way(home_mean: float, away_mean: float) -> tuple[float, float, float]:
    """P(home wins in 9), P(away wins in 9), P(tied after 9) from Poisson marginals."""
    a, b = poisson(home_mean), poisson(away_mean)
    ph = pa = pt = 0.0
    for h, p_h in enumerate(a):
        for aw, p_a in enumerate(b):
            mass = p_h * p_a
            if h > aw:
                ph += mass
            elif aw > h:
                pa += mass
            else:
                pt += mass
    return ph, pa, pt


def _quarter_params(sport: str, home_mean: float, away_mean: float):
    _, sd_total, sd_margin, _ = PRIORS[sport]
    return (home_mean * QUARTER_FRACTION, away_mean * QUARTER_FRACTION,
            sd_total / 2.0, sd_margin / 2.0)


def _margin_band_prob(home_mean: float, away_mean: float, sd_margin: float,
                      band_side: str, lo: int, hi: int | None) -> tuple[float, float]:
    """P(margin in [lo, hi]) for the selected team + declared tie mass."""
    mean = home_mean - away_mean if band_side == "HOME" else away_mean - home_mean
    top = cdf(hi + 0.5, mean, sd_margin) if hi is not None else 1.0
    prob = top - cdf(lo - 0.5, mean, sd_margin)
    # Declared tie approximation: normal density at 0. NFL ties are rare but real.
    tie = exp(-0.5 * (mean / sd_margin) ** 2) / (sd_margin * sqrt(2 * pi))
    return bounded(prob, 0, 1), bounded(tie, 0, 1)


def _quarter_ml(home_mean: float, away_mean: float, sd_margin_q: float,
                side: str) -> tuple[float, float]:
    """Quarter moneyline with discretized tie mass (+/-0.5 continuity correction)."""
    mean = home_mean - away_mean if side == "HOME" else away_mean - home_mean
    win = 1 - cdf(0.5, mean, sd_margin_q)
    tie = cdf(0.5, mean, sd_margin_q) - cdf(-0.5, mean, sd_margin_q)
    return bounded(win, 0, 1), bounded(tie, 0, 1)


def finalize_research_row(*, sport: str, game: str, selection: str, market: str,
                          price: int, dec: float, line: float | None,
                          win: float, push: float,
                          home_mean: float, away_mean: float,
                          kickoff_iso: str, context: Mapping[str, Any],
                          context_notes: list, model_family: str,
                          extra: Mapping[str, Any] | None = None,
                          declared_assumptions: Mapping[str, Any] | None = None,
                          min_ev: float = 0.02) -> dict[str, Any]:
    """Build the standard research row; EV math identical for all game markets."""
    win, push = bounded(win, 0, 1), bounded(push, 0, 1)
    loss = bounded(1 - win - push, 0, 1)
    ev = win * (dec - 1) - loss
    breakeven = (1 - push) / dec
    status = "RESEARCH_EDGE" if ev >= min_ev and price >= -165 else "BELOW_THRESHOLD"
    if price < -165:
        status = "PRICE_CAP"
    row = {
        "schema": "SPORTSEDGE_FREE_RESEARCH_V1",
        "status": status,
        "sport": sport,
        "game": game,
        "selection": selection,
        "market": market,
        "odds_american": int(price),
        "line": line,
        "kickoff_utc": kickoff_iso,
        "estimate_p": round(win, 6),
        "push_p": round(push, 6),
        "loss_p": round(loss, 6),
        "book_break_even_p": round(breakeven, 6),
        "edge_over_break_even_pp": round(100 * (win - breakeven), 3),
        "ev_per_dollar": round(ev, 6),
        "home_mean": round(home_mean, 3),
        "away_mean": round(away_mean, 3),
        "context": dict(context),
        "context_notes": list(context_notes),
        "context_quality": "HEURISTIC_UNVALIDATED",
        "model_family": model_family,
        "model_validation": "NOT_PROVEN_VS_CLOSE",
        "research_only": True,
        "model_p_authority": False,
        "official_authority": False,
        "staking_authority": False,
        "coverage_version": COVERAGE_VERSION,
    }
    if declared_assumptions:
        row["declared_assumptions"] = dict(declared_assumptions)
    if extra:
        row.update(dict(extra))
    return row


def price_coverage_row(row: Mapping[str, Any], *, now: datetime,
                       getter=None, auto_context: bool = True,
                       min_ev: float = 0.02,
                       provider: PublicContext | None = None) -> dict[str, Any]:
    """Price one coverage market row; fail-closed dict on any unverified input."""
    if not isinstance(row, dict):
        return blocked({}, "LINE_MUST_BE_OBJECT")
    market = normalize_coverage_market(row.get("market"))
    if market is None:
        return blocked(row, "NOT_A_COVERAGE_MARKET")
    if market in FAILED_VALIDATION_MARKETS:
        return blocked(row, "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED")
    sport = str(row.get("sport") or "").upper().strip()
    if sport == "MLB" and market != "ML_3WAY":
        return blocked(row, "COVERAGE_MARKET_NOT_OFFERED_FOR_MLB:" + market)
    if sport in QUARTER_SPORTS and market == "ML_3WAY":
        return blocked(row, "THREE_WAY_NOT_OFFERED_FOR_FOOTBALL")
    if market == "MARGIN_BAND" and sport not in QUARTER_SPORTS:
        return blocked(row, "MARGIN_BAND_FOOTBALL_ONLY")
    try:
        base = _base_means(row, now=now, getter=getter, auto_context=auto_context,
                           provider=provider)
    except MarketCoverageError as exc:
        reason = str(exc)
        out = blocked(row, reason)
        out["status"] = reason if reason.startswith("BLOCKED_") else "NO_MODEL_OR_MARKET"
        return out
    home_mean, away_mean = base["home_mean"], base["away_mean"]
    away = str(row.get("away") or "").strip()
    home = str(row.get("home") or "").strip()
    if not home or not away:
        game = str(row.get("game") or "")
        if " @ " in game:
            away, home = (s.strip() for s in game.split(" @ ", 1))
    side = _resolve_side_token(row, home, away)
    line = None
    needs_line = market.startswith(("SPREAD_", "TOTAL_", "TEAM_TOTAL_"))
    if needs_line:
        try:
            line = numeric(row.get("line"), "line")
        except (TypeError, ValueError):
            return blocked(row, "LINE_UNVERIFIED")
        if (market.startswith("TOTAL_") or market.startswith("TEAM_TOTAL_")) \
                and line <= 0:
            return blocked(row, "TOTAL_LINE_INVALID")
    q = quarter_of(market)
    try:
        price = numeric(row.get("odds", row.get("price")), "odds")
        dec = odds_decimal(row.get("odds", row.get("price")))
    except (TypeError, ValueError):
        return blocked(row, "ODDS_INVALID")

    label = ""
    if market == "ML_3WAY":
        if side not in {"HOME", "AWAY", "TIE"}:
            return blocked(row, "SIDE_MUST_BE_HOME_AWAY_TIE")
        ph, pa, pt = _mlb_3way(home_mean, away_mean)
        win = ph if side == "HOME" else pa if side == "AWAY" else pt
        push = 0.0
        label = {"HOME": home + " 9-inning", "AWAY": away + " 9-inning",
                 "TIE": "Tie after 9"}[side]
    elif market == "MARGIN_BAND":
        band = next((b for b in MARGIN_BANDS if b[0] == side), None)
        if band is None:
            return blocked(row, "MARGIN_BAND_SIDE_INVALID")
        _, sd_total, sd_margin, _ = PRIORS[sport]
        win, push = _margin_band_prob(home_mean, away_mean, sd_margin,
                                      band[1], band[2], band[3])
        team = home if band[1] == "HOME" else away
        span = f"{band[2]}-{band[3]}" if band[3] is not None else "25+"
        label = f"{team} wins by {span}"
    elif q is not None:
        hq, aq, sdt_q, sdm_q = _quarter_params(sport, home_mean, away_mean)
        if market.startswith("SPREAD_"):
            if side not in {"HOME", "AWAY"}:
                return blocked(row, "SIDE_MUST_BE_HOME_AWAY")
            win, push = _normal_win_push("SPREAD", side, line, hq, aq, sdt_q, sdm_q)
            label = f"{home if side == 'HOME' else away} Q{q} {line:+g}"
        elif market.startswith("TOTAL_"):
            if side not in {"OVER", "UNDER"}:
                return blocked(row, "SIDE_MUST_BE_OVER_UNDER")
            win, push = _normal_win_push("TOTAL", side, line, hq, aq, sdt_q, sdm_q)
            label = f"Q{q} {'Over' if side == 'OVER' else 'Under'} {line:g}"
        elif market.startswith("ML_"):
            if side not in {"HOME", "AWAY"}:
                return blocked(row, "SIDE_MUST_BE_HOME_AWAY")
            win, push = _quarter_ml(hq, aq, sdm_q, side)
            label = f"{home if side == 'HOME' else away} Q{q} ML"
        else:  # TEAM_TOTAL_nQ
            team_tok = (side or "").rsplit("_", 1)
            if len(team_tok) != 2 or team_tok[0] not in {"HOME", "AWAY"} \
                    or team_tok[1] not in {"OVER", "UNDER"}:
                return blocked(row, "TEAM_TOTAL_SIDE_MUST_BE_HOME_OVER_STYLE")
            team_mean = hq if team_tok[0] == "HOME" else aq
            sd_team = sdt_q / sqrt(2.0)
            over = 1 - cdf(line, team_mean, sd_team)
            under = cdf(line, team_mean, sd_team)
            push = (cdf(line + 0.5, team_mean, sd_team)
                    - cdf(line - 0.5, team_mean, sd_team)) if float(line).is_integer() else 0.0
            win = over if team_tok[1] == "OVER" else under
            label = (f"{home if team_tok[0] == 'HOME' else away} Q{q} "
                     f"{'Over' if team_tok[1] == 'OVER' else 'Under'} {line:g}")
    else:
        return blocked(row, "COVERAGE_MARKET_UNHANDLED")

    win, push = bounded(win, 0, 1), bounded(push, 0, 1)
    win, push = round(win, 6), round(push, 6)
    # Degenerate probabilities fail closed exactly like the research bridge:
    # a REPORTED 0/1 model probability is refused, never priced. The guard
    # runs on rounded values so 5.4e-9 cannot be reported as a clean 0.0.
    if not (0.0 < win < 1.0) or not (0.0 <= push < 1.0) \
            or win + push > 1.0 + 1e-12:
        return blocked(row, "DEGENERATE_PROBABILITY_REFUSED")
    return finalize_research_row(
        sport=sport, game=f"{away} @ {home}", selection=label, market=market,
        price=int(price), dec=dec, line=line, win=win, push=push,
        home_mean=home_mean, away_mean=away_mean,
        kickoff_iso=base["kickoff"].isoformat(),
        context=base["context"], context_notes=base["context_notes"],
        model_family="FREE_COVERAGE_EXTENSION_UNVALIDATED",
        declared_assumptions={
            "quarter_fraction": QUARTER_FRACTION if q is not None else None,
            "quarter_variance_scaling": "SD_HALVED_IID_QUARTERS" if q is not None else None,
            "mlb_3way_note": ("BOTH_CLUBS_COMPLETE_NINE_HALF_INNINGS_ASSUMED;"
                              "HOME_BOTTOM_9TH_TRUNCATION_NOT_MODELED")
            if market == "ML_3WAY" else None,
            "margin_band_note": ("NORMAL_MARGIN_DISCRETIZED_PM_HALF;"
                                 "TIE_MASS_FROM_NORMAL_DENSITY_DECLARED_APPROX")
            if market == "MARGIN_BAND" else None,
        },
        min_ev=min_ev,
    )


def phone_coverage_rows(rows, *, now=None, getter=None,
                        auto_context: bool = True,
                        min_ev: float = 0.02):
    """Price coverage-market rows; returns (outputs, receipts)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    now = now.astimezone(timezone.utc)
    if not 0 <= min_ev <= 0.15:
        raise ValueError("MIN_EV_OUT_OF_RANGE")
    outputs = []
    receipts: list[dict[str, Any]] = []
    provider = PublicContext(now, getter=getter)
    for row in rows:
        if not isinstance(row, dict):
            outputs.append(blocked({}, "LINE_MUST_BE_OBJECT"))
            continue
        canon = normalize_coverage_market(row.get("market"))
        if canon is None:
            outputs.append(blocked(row, "NOT_A_COVERAGE_MARKET"))
            continue
        bound = dict(row)
        bound["market"] = canon
        try:
            result = price_coverage_row(bound, now=now, getter=getter,
                                        auto_context=auto_context, min_ev=min_ev,
                                        provider=provider)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            result = blocked(bound, "COVERAGE_PRICING_FAILED:" + type(exc).__name__)
        outputs.append(result)
    receipts.extend(provider.receipts)
    if outputs:
        # Lane summary receipts are provenance for work actually performed:
        # like the sibling phone lanes, an invocation that processed no rows
        # must not append a receipt to the card (a rows:0 receipt would
        # fabricate provenance for a source never consulted).
        receipts.append({"source": "sportsedge.market_coverage",
                         "status": "COVERAGE_BASE_MEANS_FROM_VERIFIED_CONTEXT",
                         "version": COVERAGE_VERSION,
                         "rows": len(outputs)})
    return outputs, receipts
