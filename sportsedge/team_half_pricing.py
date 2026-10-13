"""Team totals and first-half markets from the same verified free_models means.

Uses the existing PublicContext + independent home/away score means already
computed for game ML/spread/total. No new league priors. Research only.
First-half is a declared 0.50 scale of the full-game mean with inflated
variance; it is not a fitted half model.

MATCHUP-ADJUSTMENT AUDIT (fail-closed, 2026-10-11)
-------------------------------------------------
Every team-strength mean priced here must carry a matchup-adjustment audit.
The pricer verifies the key participants the price depends on and records
which matchup inputs were verified and applied. A market whose key matchup
input is missing is REFUSED with an explicit reason code -- it is never
priced silently on the healthy-roster/default assumption.

- NFL / CFB: free_models.injury_points is wired into the means (the same call
  free_models.calculate uses for full-game ML/SPREAD/TOTAL), plus an explicit
  starting-QB scan of the verified ESPN injury feed. A verified out/doubtful
  starting QB applies a declared backup-replacement penalty (NOT calibrated).
  Unverifiable QB participation -> QB_PARTICIPATION_UNVERIFIED (refuse).
- NBA: injury_points wired; unverifiable participation ->
  PARTICIPATION_UNVERIFIED (refuse).
- MLB: starting-pitcher adjustment is REQUIRED (538-adapted; see
  sportsedge/mlb_sp_rgs.py). Probable pitchers are verified from the free
  MLB StatsAPI schedule (hydrate=probablePitcher), exactly as before. Each
  starter's trailing 20-start rolling game score is verified from the free
  season gameLog (/people/{id}/stats?stats=gameLog&group=pitching, starts
  only, strictly before the game date):

      gameScore = 47.4 + K + 1.5*outs - 2*BB - 2*H - 3*R - 4*HR   (538's
      Tangotiger-modified Bill James score, read from the archived
      methodology page)
      opp_total_adj = 0.014 - 0.0699 * (pitcher_rGS - 51.54)

  applied to the OPPOSING team's total, capped at +-2.0 runs. The gamma
  (-0.0699) and league mean (51.54) are FIT, not borrowed: 2021-2022 fit,
  2023-2024 out-of-sample eval beat both no-adjustment and the old
  ERA-vs-staff formula (scripts/study_sp_ablation.py). Missing/unverifiable
  probable pitcher, opener/bullpen-game shape (<5 starts or <4.0 IP/start),
  or unverifiable gameLog -> PROBABLE_PITCHER_UNVERIFIED (refuse).

Source hierarchy for participation (VERIFIED sources only):
  1. Official inactive lists (e.g. NFL game-day inactives) -- highest
     authority. Not yet wired as a direct feed; when available they override
     the injury feed below.
  2. ESPN team injury feed, out/doubtful rows, structure-verified -- what the
     QB scan uses. Documented limitation: this is the weekly injury report,
     NOT final game-day inactives (see sportsedge/nfl_card_game_info.py).
  3. nflverse weekly injury CSVs (near-official fallback) -- documented for
     future wiring, not used here.
  Never: beat-writer speculation, rumors, social media.

LIMITS (declared vs calibrated):
- NFL QB adjustment is now EMPIRICALLY CALIBRATED (fit 2015-2020, validated
  out-of-sample 2021-2024; see sportsedge/qb_value.py and
  scripts/study_qb_adjustment.py), not a declared constant. The old declared
  -3.0 total (-1.5 injury_points + -1.5 extra) was shown out-of-sample to be
  WORSE than no adjustment; the per-QB 538-adapted VALUE version wins.
  Tier 2 (backup unverifiable) uses the empirical mean backup-start effect
  (-0.582 total). Doubtful = 50% of the OUT extra remains a DECLARED
  play-probability weight (538's published data has no doubtful cases).
- CFB QB penalties (-1.5/-0.75) remain DECLARED and audit-flagged
  UNCALIBRATED: no 538 analog for college, no free college QB history wired.
- Pitcher suppression is expressed vs the starter's OWN club staff ERA, which
  understates aces on elite staffs and flatters weak starters on weak staffs.
  Bullpen quality, park, and platoon effects are NOT modeled.
  (Refinement to 538-style rolling game scores: see sportsedge/mlb_sp_rgs.py
  once the calibration study lands.)
- Doubleheader dates (two same-team games on one date) block: the schedule
  match must be unique.
- Early-season MLB (fewer than 5 starts) blocks until the sample gate passes.
"""
from __future__ import annotations

import os
from math import erf, isfinite, sqrt
from typing import Any, Mapping
from urllib.parse import urlencode

from artifacts.free_models import (
    PRIORS, model_probability, PublicContext, numeric, bounded, dt, odds_decimal,
    ESPN, LEAGUES,
)
from sportsedge import qb_value as _qb_value
from sportsedge import mlb_sp_rgs as _sp_rgs

# Bound at import so tests can monkeypatch the PublicContext *constructor*
# without breaking the stateless helpers below.
_TEAM_MATCHES = PublicContext.team_matches
_INJURY_GROUP_ID = PublicContext._injury_group_id

# Declared, uncalibrated heuristics. See module docstring.
# NOTE (2026-10-11, qb-sp-adjustment): the NFL QB extras below were REPLACED
# by the empirically calibrated two-tier scheme in sportsedge/qb_value.py
# (538-adapted VALUE; fit 2015-2020, validated out-of-sample 2021-2024; see
# scripts/study_qb_adjustment.py and MATCHUP_VALIDATION.md). The CFB values
# remain declared: no 538 analog exists for college and no free college
# QB box-score history is wired, so they are audit-flagged UNCALIBRATED.
_QB_OUT_EXTRA_CFB = -1.5
_QB_DOUBTFUL_EXTRA_CFB = -0.75
_STATSAPI = "https://statsapi.mlb.com/api/v1"


class _MatchupUnverified(Exception):
    """Raised when a required matchup input cannot be verified.

    Carries the explicit reason code the market is refused with, plus the
    partial matchup audit built before the failure.
    """

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail
        self.audit: dict[str, Any] = {
            "home": {}, "away": {},
            "coverage": {"verified_applied": [], "missing": []},
        }


def _cdf(x, mean, sd):
    return (1 + erf((x - mean) / (sd * sqrt(2)))) / 2


def _finite_number(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if isfinite(x) else None


def _injury_candidates(ctx, sport, team_id):
    """Return verified injury rows for one team, or None if unverifiable.

    Mirrors the verified-shape logic of PublicContext.injury_points: a flat
    injuries list on the team-scoped URL is accepted; a grouped payload
    requires exactly one group whose team ID matches. Anything else (missing
    keys, unrecognized schema, league payload that cannot be attributed to
    this team) returns None so the caller fails closed.
    """
    target = str(team_id)
    urls = (f"{ESPN}/{LEAGUES[sport]}/teams/{target}/injuries",
            f"{ESPN}/{LEAGUES[sport]}/injuries")
    for index, url in enumerate(urls):
        try:
            data = ctx.fetch(url)
        except Exception:
            continue
        if not isinstance(data, dict) or not isinstance(data.get("injuries"), list):
            continue
        groups = data["injuries"]
        grouped = any(isinstance(g, dict) and isinstance(g.get("injuries"), list)
                      for g in groups)
        if grouped:
            matches = [g for g in groups
                       if _INJURY_GROUP_ID(g) == target]
            if len(matches) == 1:
                return matches[0]["injuries"]
            continue
        if index == 0:
            # Team-scoped payload with a flat injury-row list.
            return groups
        # League payload without attributable grouping: cannot verify rows
        # belong to this team.
        continue
    return None


_QB_RATINGS_CACHE = {}


def _qb_ratings(cache_dir, kickoff):
    """Cached {pid: rating_state} for the trailing seasons.

    Ratings are point-in-time safe: weekly nflverse CSVs only ever contain
    completed weeks, and completed seasons are loaded whole. Keyed by
    (cache_dir, seasons) so a stale process never mixes seasons.
    """
    current = kickoff.year
    seasons = tuple(range(max(2015, current - 11), current + 1))
    key = (cache_dir, seasons)
    if key not in _QB_RATINGS_CACHE:
        _QB_RATINGS_CACHE[key] = _qb_value.build_ratings(
            cache_dir, seasons, current, kickoff)[0]
    return _QB_RATINGS_CACHE[key]


def _qb_value_dir():
    d = os.path.expanduser("~/.cache/sportsedge/qb_value")
    os.makedirs(d, exist_ok=True)
    return d


def _qb_status(ctx, sport, team, kickoff):
    """Verify the starting QB's participation from the ESPN injury feed.

    Returns (status, extra_points, detail, value_audit). Raises
    _MatchupUnverified with QB_PARTICIPATION_UNVERIFIED when the feed cannot
    be verified -- the price must not assume a healthy starting QB in that
    case.

    NFL: the extra is the empirically calibrated 538-adapted adjustment
    (sportsedge/qb_value.py): Tier 1 per-QB VALUE gap when the backup is
    verifiable, else the Tier 2 calibrated constant. Both are TOTAL-effect
    estimates with injury_points' generic QB component (-1.5) compensated
    in the stacking: the published empirical effects are TOTAL effects, so
    the +1.5 compensation below offsets injury_points' generic -1.5 QB term
    (see _apply_matchup_adjustments).
    CFB: declared -1.5/-0.75, audit-flagged UNCALIBRATED (no 538 analog).
    """
    rows = _injury_candidates(ctx, sport, team.get("id"))
    if rows is None:
        raise _MatchupUnverified(
            "QB_PARTICIPATION_UNVERIFIED",
            "ESPN injury feed shape unverifiable for team id "
            + str(team.get("id")) + "; starting-QB status unknown")
    found = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("status") or ""
        if isinstance(raw, dict):
            raw = raw.get("name") or raw.get("description") or ""
        status = str(raw).strip().lower()
        if status not in {"out", "doubtful"}:
            continue
        athlete = row.get("athlete") or {}
        if not isinstance(athlete, dict):
            continue
        position = athlete.get("position") or {}
        position = position.get("abbreviation") if isinstance(position, dict) else position
        if str(position).upper() != "QB":
            continue
        name = str(athlete.get("fullName") or athlete.get("displayName")
                   or athlete.get("id") or "UNKNOWN_QB")
        espn_id = str(athlete.get("id") or "").strip()
        found = (status, name, espn_id)
        break
    if found is None:
        return ("QB_NO_ABSENCE_VERIFIED", 0.0,
                "no QB out/doubtful in the verified injury feed", {})
    status, name, espn_id = found
    doubtful = status == "doubtful"
    if sport == "NFL":
        try:
            cache_dir = _qb_value_dir()
            ratings = _qb_ratings(cache_dir, kickoff)
            vout = _qb_value.qb_absence_extra(
                ratings, starter_name=name,
                team_abbr=str(team.get("abbreviation") or "").upper(),
                cache=cache_dir)
        except Exception as exc:  # noqa: BLE001 - fail closed, never blind
            raise _MatchupUnverified(
                "QB_PARTICIPATION_UNVERIFIED",
                "QB VALUE pipeline failed for verified-%s QB %s: %s"
                % (status.upper(), name, type(exc).__name__)) from exc
        extra = vout["extra_total"]
        if doubtful:
            # Doubtful = 50% of the OUT extra: DECLARED, not calibrated.
            extra = 0.5 * extra
        vaudit = {"tier": vout["variant"], "source": vout["source"],
                  "doubtful_weight": 0.5 if doubtful else 1.0,
                  "provenance": vout["provenance"]}
        vaudit.update(vout["audit"])
        code = "QB_OUT_VERIFIED" if status == "out" else "QB_DOUBTFUL_VERIFIED"
        detail = ("starting QB verified %s: %s; %s adjustment (538-adapted "
                  "VALUE, %s%s)" % (status.upper(), name,
                                  "per-QB" if vout["variant"] ==
                                  "TIER1_PER_QB_VALUE" else "calibrated-constant",
                                  vout["variant"],
                                  ", doubtful halved (DECLARED)" if doubtful else ""))
        return (code, extra, detail, vaudit)
    # CFB: declared, explicitly uncalibrated.
    extra = _QB_OUT_EXTRA_CFB if status == "out" else _QB_DOUBTFUL_EXTRA_CFB
    code = "QB_OUT_VERIFIED" if status == "out" else "QB_DOUBTFUL_VERIFIED"
    return (code, extra, "starting QB verified %s: %s (CFB declared penalty, "
            "UNCALIBRATED -- no 538 analog)" % (status.upper(), name),
            {"tier": "DECLARED_CFB_UNCALIBRATED"})


def _mlb_probable_pitchers(getter, kickoff, home_name, away_name):
    """Verify both probable pitchers from the StatsAPI schedule.

    Endpoint: /api/v1/schedule?sportId=1&date=YYYY-MM-DD&hydrate=probablePitcher
    Field: games[].teams.{home,away}.probablePitcher.{id,fullName}.
    The schedule match must be unique (doubleheader dates refuse).
    """
    date = kickoff.date().isoformat()
    url = (_STATSAPI + "/schedule?"
           + urlencode({"sportId": 1, "date": date, "hydrate": "probablePitcher"}))
    try:
        data = getter(url)
    except Exception as exc:  # noqa: BLE001 - any fetch failure is unverified
        raise _MatchupUnverified("PROBABLE_PITCHER_UNVERIFIED",
                                 "schedule fetch failed: "
                                 + type(exc).__name__) from exc
    if not isinstance(data, dict):
        raise _MatchupUnverified("PROBABLE_PITCHER_UNVERIFIED",
                                 "schedule payload not a JSON object")
    games = [g for day in (data.get("dates") or []) if isinstance(day, dict)
             for g in (day.get("games") or []) if isinstance(g, dict)]
    matches = []
    for game in games:
        teams = game.get("teams") or {}
        sides = {}
        ok = True
        for side, name in (("home", home_name), ("away", away_name)):
            team = (teams.get(side) or {}).get("team") or {}
            if not _TEAM_MATCHES(team, name):
                ok = False
                break
            sides[side] = team
        if ok:
            matches.append((game, sides))
    if len(matches) != 1:
        raise _MatchupUnverified(
            "PROBABLE_PITCHER_UNVERIFIED",
            "unique schedule game not verified for %s @ %s on %s: %d matches"
            % (away_name, home_name, date, len(matches)))
    game, sides = matches[0]
    status = game.get("status") or {}
    detailed = str(status.get("detailedState") or "").strip()
    if detailed and detailed not in {"Scheduled", "Pre-Game"}:
        # Late scratch / stale listing: the feed says this game is no longer
        # pregame, so the probable-pitcher announcement cannot be trusted.
        # (A scratch between our fetch and first pitch is NOT detectable from
        # this endpoint; the audit records the probable identity + schedule
        # date for post-game reconciliation. Known residual risk.)
        raise _MatchupUnverified(
            "PROBABLE_PITCHER_UNVERIFIED",
            "schedule game status %r contradicts a pregame probable listing; "
            "probable pitchers may be stale" % detailed)
    meta = {"schedule_date": date, "game_status": detailed or "UNREPORTED"}
    out = {}
    for side in ("home", "away"):
        probable = ((game.get("teams") or {}).get(side) or {}).get("probablePitcher") or {}
        pid = _finite_number(probable.get("id"))
        name = str(probable.get("fullName") or "").strip()
        if pid is None or int(pid) < 100 or not name:
            raise _MatchupUnverified(
                "PROBABLE_PITCHER_UNVERIFIED",
                side + " probable pitcher id/name unverified on " + date)
        out[side] = {"id": int(pid), "name": name, "team": sides[side]}
    return out, meta


def _mlb_pitcher_adjustment(getter, kickoff, home_name, away_name):
    """Compute the required starting-pitcher adjustment for MLB team totals.

    538-adapted (see sportsedge/mlb_sp_rgs.py): each probable starter's
    trailing 20-start rolling game score (free StatsAPI season gameLog,
    point-in-time) is compared against the trailing league-mean game score;
    the OPPOSING team's total moves by INTERCEPT + GAMMA * gap, capped.
    Returns (home_total_adj, away_total_adj, audit). Raises
    _MatchupUnverified on any unverifiable input.
    """
    probables, meta = _mlb_probable_pitchers(getter, kickoff, home_name, away_name)
    season = kickoff.year
    per_side = {}
    for side in ("home", "away"):
        pitcher = probables[side]
        try:
            adj, audit = _sp_rgs.suppression_for_starter(
                getter, pitcher["id"], season, kickoff.date())
        except _sp_rgs.Unverifiable as exc:
            raise _MatchupUnverified(
                "PROBABLE_PITCHER_UNVERIFIED",
                "%s: %s" % (pitcher["name"], exc)) from exc
        per_side[side] = {
            "adjustment_to_opponent_total": adj,
            "probable_pitcher": pitcher["name"],
            "probable_pitcher_id": pitcher["id"],
            "schedule_date": meta["schedule_date"],
            "game_status": meta["game_status"],
            **audit,
        }
    # The home total is suppressed by the AWAY starter and vice versa.
    home_adj = per_side["away"]["adjustment_to_opponent_total"]
    away_adj = per_side["home"]["adjustment_to_opponent_total"]
    return home_adj, away_adj, per_side


def _build_means(ctx, sport, home, away, home_team, away_team, kickoff,
                 getter=None):
    """Build verified home/away score means with required matchup adjustments.

    Returns (home_mean, away_mean, matchup_audit). Raises _MatchupUnverified
    when a required matchup input cannot be verified.
    """
    base, _, _, hfa = PRIORS[sport]
    # Minimal context: prior-five margin proxy if available.
    home_hist = ctx.schedule(sport, home_team, kickoff)
    away_hist = ctx.schedule(sport, away_team, kickoff)
    def margin_proxy(hist):
        if len(hist) < 3:
            return 0.0
        diffs = [own - opp for _, own, opp in hist]
        return max(-4.0, min(4.0, sum(diffs) / len(diffs) * 0.15))
    home_rating = margin_proxy(home_hist)
    away_rating = margin_proxy(away_hist)
    home_mean = base + hfa / 2 + home_rating
    away_mean = base - hfa / 2 + away_rating

    # Required matchup adjustments with a fail-closed audit. Never price the
    # healthy-roster/default number when a key participant is unverified.
    matchup_audit: dict[str, Any] = {
        "home": {}, "away": {},
        "coverage": {"verified_applied": [], "missing": []},
    }
    try:
        home_mean, away_mean = _apply_matchup_adjustments(
            ctx, sport, home, away, home_team, away_team, kickoff, getter,
            home_mean, away_mean, matchup_audit)
    except _MatchupUnverified as exc:
        exc.audit = matchup_audit
        raise
    return home_mean, away_mean, matchup_audit


def _apply_matchup_adjustments(ctx, sport, home, away, home_team, away_team,
                               kickoff, getter, home_mean, away_mean,
                               matchup_audit):
    """Apply required matchup adjustments; mutate matchup_audit in place.

    Returns (home_mean, away_mean). Raises _MatchupUnverified when a required
    matchup input cannot be verified.
    """
    if sport == "MLB":
        if getter is None:
            raise _MatchupUnverified(
                "PROBABLE_PITCHER_UNVERIFIED",
                "no data getter: probable pitchers cannot be verified")
        home_adj, away_adj, pitcher_audit = _mlb_pitcher_adjustment(
            getter, kickoff, home, away)
        home_mean += home_adj
        away_mean += away_adj
        matchup_audit["home"] = {
            "factor": "opposing_probable_starter",
            "points_applied": home_adj, **pitcher_audit["away"]}
        matchup_audit["away"] = {
            "factor": "opposing_probable_starter",
            "points_applied": away_adj, **pitcher_audit["home"]}
        matchup_audit["coverage"]["verified_applied"].extend([
            "probable_pitcher_home:" + pitcher_audit["home"]["probable_pitcher"],
            "probable_pitcher_away:" + pitcher_audit["away"]["probable_pitcher"],
        ])
    elif sport in {"NFL", "CFB", "NBA"}:
        for prefix, team, is_home in (("home", home_team, True),
                                     ("away", away_team, False)):
            injury_pts, injury_status = ctx.injury_points(sport, team)
            if injury_status == "MISSING_OR_UNRECOGNIZED_SOURCE":
                code = ("PARTICIPATION_UNVERIFIED" if sport == "NBA"
                        else "QB_PARTICIPATION_UNVERIFIED")
                raise _MatchupUnverified(
                    code, prefix + " injury feed unverifiable; "
                    "participation of key players unknown")
            if is_home:
                home_mean += injury_pts
            else:
                away_mean += injury_pts
            entry: dict[str, Any] = {
                "factor": "injury_report",
                "injury_points": injury_pts,
                "injury_status": injury_status,
            }
            if sport in {"NFL", "CFB"}:
                qb_status, qb_pts, qb_detail, qb_vaudit = _qb_status(
                    ctx, sport, team, kickoff)
                if is_home:
                    home_mean += qb_pts
                else:
                    away_mean += qb_pts
                entry.update({"qb_status": qb_status, "qb_points": qb_pts,
                              "qb_detail": qb_detail,
                              "qb_value_audit": qb_vaudit})
                matchup_audit["coverage"]["verified_applied"].append(
                    prefix + "_qb:" + qb_status)
            matchup_audit[prefix] = entry
            matchup_audit["coverage"]["verified_applied"].append(
                prefix + "_injuries:" + injury_status)
    else:
        matchup_audit["coverage"]["missing"].append(
            "no verified matchup-adjustment path for sport " + sport)
    return home_mean, away_mean


def _blocked(reason, detail, sport, market):
    return {"status": "NO_MODEL_OR_MARKET", "reason": reason,
            "detail": detail, "sport": sport, "market": market,
            "research_only": True}


def price_team_or_half(
    row: Mapping[str, Any],
    *,
    now,
    getter=None,
) -> dict[str, Any]:
    """Price TEAM_TOTAL, TEAM_TOTAL_1H, TOTAL_1H, SPREAD_1H, ML_1H from free context."""
    sport = str(row.get("sport") or "").upper()
    market = str(row.get("market") or "").upper()
    side = str(row.get("side") or row.get("selection") or "").upper()
    away = str(row.get("away") or "").strip()
    home = str(row.get("home") or "").strip()
    kickoff = dt(row.get("kickoff") or row.get("commence_time"))
    if sport not in PRIORS or not away or not home or kickoff is None:
        return _blocked("IDENTITY_OR_SPORT_MISSING", "", sport, market)
    if kickoff <= now:
        return {"status": "BLOCKED_STARTED", "reason": "GAME_ALREADY_STARTED",
                "sport": sport, "market": market, "research_only": True}

    ctx = PublicContext(now, getter=getter)
    fixture = ctx.fixture(sport, away, home, kickoff)
    if fixture is None:
        return _blocked("FREE_CONTEXT_FIXTURE_NOT_VERIFIED", "", sport, market)

    # Reuse the same mean construction as free_models.calculate (simplified).
    home_team = ctx.identify(sport, home)
    away_team = ctx.identify(sport, away)
    if not home_team or not away_team:
        return _blocked("TEAM_IDENTITY_UNMATCHED", "", sport, market)

    base, _, _, hfa = PRIORS[sport]
    # Reuse the same mean construction as free_models.calculate (simplified),
    # now with required matchup adjustments and a fail-closed audit.
    try:
        home_mean, away_mean, matchup_audit = _build_means(
            ctx, sport, home, away, home_team, away_team, kickoff, getter=getter)
    except _MatchupUnverified as exc:
        out = _blocked(exc.reason, exc.detail, sport, market)
        out["matchup_audit"] = exc.audit
        return out

    if min(home_mean, away_mean) < 0.2:
        return _blocked("IMPLAUSIBLE_SCORE_MEAN", "", sport, market)

    line = row.get("line")
    try:
        line_f = float(line) if line is not None else None
    except (TypeError, ValueError):
        return _blocked("LINE_UNVERIFIED", "", sport, market)

    # Map to underlying model_probability call.
    if market in {"TEAM_TOTAL", "TEAM_TOTAL_POINTS"}:
        team = str(row.get("team") or "").upper()
        if team in {"HOME", home.upper()}:
            mean = home_mean
        elif team in {"AWAY", away.upper()}:
            mean = away_mean
        else:
            return _blocked("TEAM_TOTAL_TEAM_UNRESOLVED", "", sport, market)
        # Approximate team total as normal with sd from league total / sqrt(2).
        _, sd_total, _, _ = PRIORS[sport]
        sd = (sd_total or 12.0) / 1.4
        whole = line_f is not None and float(line_f).is_integer()
        push = _cdf(line_f + 0.5, mean, sd) - _cdf(line_f - 0.5, mean, sd) if whole else 0.0
        cut = line_f + (0.5 if whole else 0)
        win = (1 - _cdf(cut, mean, sd)) if side == "OVER" else _cdf(line_f - (0.5 if whole else 0), mean, sd)
        model_p, push_p = bounded(win, 0, 1), bounded(push, 0, 1)
    elif market in {"TOTAL_1H", "FIRST_HALF_TOTAL"}:
        # Declared half scale; not fitted.
        half_home, half_away = home_mean * 0.50, away_mean * 0.50
        model_p, push_p = model_probability(
            sport, "TOTAL", side, line_f, half_home, half_away)
    elif market in {"SPREAD_1H", "FIRST_HALF_SPREAD"}:
        half_home, half_away = home_mean * 0.50, away_mean * 0.50
        model_p, push_p = model_probability(
            sport, "SPREAD", side, line_f, half_home, half_away)
    elif market in {"ML_1H", "FIRST_HALF_ML"}:
        half_home, half_away = home_mean * 0.50, away_mean * 0.50
        model_p, push_p = model_probability(
            sport, "ML", side, None, half_home, half_away)
    else:
        return _blocked("UNSUPPORTED_TEAM_HALF_MARKET", "", sport, market)

    try:
        dec = odds_decimal(row.get("odds") or row.get("price"))
    except ValueError:
        dec = None
    loss = bounded(1 - model_p - push_p, 0, 1)
    ev = (model_p * (dec - 1) - loss) if dec else None
    return {
        "status": "PRICED_RESEARCH",
        "sport": sport, "market": market, "selection": side,
        "estimate_p": model_p, "push_p": push_p,
        "ev_per_dollar": ev,
        "model_source": "free_models_means_team_half_v2_matchup_audit",
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
        "home_mean": round(home_mean, 3), "away_mean": round(away_mean, 3),
        "matchup_audit": matchup_audit,
    }
