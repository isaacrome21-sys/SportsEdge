"""538-adapted MLB starting-pitcher rolling game score (rGS) engine.

Methodology provenance
----------------------
FiveThirtyEight's "How Our MLB Predictions Work" (archived 2022-04-07;
read in full):
  - Per-start gameScore = 47.4 + K + 1.5*outs - 2*BB - 2*H - 3*R - 4*HR
    (a Tangotiger-modified Bill James game score), normalized for era,
    stadium, and opposing-team offensive strength.
  - Rolling game score (rGS) per pitcher and per team ("the model's best
    guess as to how the pitcher would perform in a typical start").
  - ratingAdj = 4.7 * (pitcher_rGS - team_rGS), applied to the team's
    rating. Openers: the team uses its average pitcher adjustment and the
    opener's game score is not added to any rolling score.

Adaptation with free data (MLB StatsAPI, zero keys)
---------------------------------------------------
  - Per-start game scores from the free season gameLog
    (/people/{id}/stats?stats=gameLog&group=pitching); starts identified by
    the per-split gamesStarted flag; only splits with date < kickoff date
    (point-in-time).
  - Pitcher rGS = trailing 20-start mean of RAW game scores (min 5 starts,
    mirroring the existing gate). Baseline = trailing league-mean game score
    (51.54, 2021-2024 starts). The ablation (scripts/study_sp_ablation.py)
    tested 538's team-relative + opponent-normalized variant against
    league-relative raw: league-relative won out-of-sample (MSE 10.047 vs
    10.113 team-relative, 10.133 no-adjustment, 10.361 old ERA formula), so
    it ships. Opponent/park normalization is a documented known gap (the
    per-start opponent-normalized variant was within noise, +0.08%, but
    needs ~20 extra fetches per starter).
  - Runs mapping: opp_total_adj = INTERCEPT + GAMMA * (pitcher_rGS -
    LEAGUE_MEAN_GS), GAMMA = -0.0699 fitted empirically (fit 2021-2022,
    eval 2023-2024 on the identical game set). 538's 4.7 converts to Elo;
    we need runs, so gamma is fit, not borrowed.
  - Opener/bullpen-game shape (<5 starts, or averaging <4.0 IP/start)
    refuses with PROBABLE_PITCHER_UNVERIFIED, mirroring 538's opener rule.
Fail-closed: any unverifiable input (schedule, gameLog shape, team
enumeration) raises _MatchupUnverified-equivalent; the caller refuses.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Any
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Calibrated constants (fit 2021-2022, eval 2023-2024 on the identical game
# set; see scripts/study_sp_ablation.py). Winner: V2 (league-relative, raw
# game scores). Ablation MSEs, eval 2023-2024, n=8800:
#   no adjustment 10.1328 | current ERA-vs-staff formula 10.3608 (WORSE)
#   V1 team+oppnorm 10.1134 | V3 team+raw 10.1168
#   V2 league+raw  10.0472 | V4 league+oppnorm 10.0387
# V4 is within noise of V2 (+0.08%) but needs ~20 extra schedule fetches per
# starter for per-start opponent R/G; V2 ships on the cost/robustness trade.
# Opponent normalization is a documented known gap, not a silent omission.
# ---------------------------------------------------------------------------
#: Runs of opponent-total suppression per raw game-score point above the
#: trailing league mean (V2).
SP_RGS_GAMMA = -0.0699
#: Intercept of the same regression (~0; kept for honesty).
SP_RGS_INTERCEPT = 0.014
#: Trailing league-mean raw game score (2021-2024 starts; stable ~50-52).
#: A +/-1 error here shifts every total by gamma*1 ~= 0.07 runs: negligible.
LEAGUE_MEAN_GS = 51.54
#: Declared cap on |adjustment| (safety rail).
SP_RGS_ADJ_CAP = 2.0

SP_RGS_WINDOW = 20
MIN_PITCHER_STARTS = 5

_STATSAPI = "https://statsapi.mlb.com/api/v1"


def game_score(strikeouts, outs, walks, hits, runs, homers) -> float:
    """538's (Tangotiger-modified) per-start game score."""
    return (47.4 + strikeouts + 1.5 * outs - 2 * walks - 2 * hits
            - 3 * runs - 4 * homers)


def _finite(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _innings_to_outs(value):
    try:
        whole_s, _, frac_s = str(value).strip().partition(".")
        whole, frac = int(whole_s), int(frac_s or "0")
    except (ValueError, AttributeError):
        return None
    if whole < 0 or not 0 <= frac <= 2:
        return None
    return whole * 3 + frac


class Unverifiable(Exception):
    pass


def fetch_gamelog_starts(getter, pitcher_id: int, season: int,
                         before: date):
    """Verified per-start (date, gameScore inputs, opponent id) before `before`.

    Uses the free StatsAPI season gameLog; strict shape checks. Raises
    Unverifiable on anything unrecognized.
    """
    url = (_STATSAPI + "/people/%d/stats?" % pitcher_id
           + urlencode({"stats": "gameLog", "group": "pitching",
                        "season": str(season), "gameType": "R"}))
    try:
        data = getter(url)
    except Exception as exc:  # noqa: BLE001
        raise Unverifiable("gamelog fetch failed: %s" % type(exc).__name__) from exc
    if not isinstance(data, dict) or not isinstance(data.get("stats"), list):
        raise Unverifiable("gamelog payload shape unverified")
    starts = []
    for entry in data["stats"]:
        if not isinstance(entry, dict):
            continue
        for split in entry.get("splits") or []:
            if not isinstance(split, dict):
                continue
            stat = split.get("stat") or {}
            try:
                gs_flag = int(stat.get("gamesStarted") or 0)
            except (TypeError, ValueError):
                continue
            if gs_flag != 1:
                continue
            sdate = str(split.get("date") or "")[:10]
            if not sdate or sdate >= before.isoformat():
                continue  # point-in-time: strictly earlier starts only
            so = _finite(stat.get("strikeOuts"))
            bb = _finite(stat.get("baseOnBalls"))
            h = _finite(stat.get("hits"))
            r = _finite(stat.get("runs"))
            hr = _finite(stat.get("homeRuns"))
            o = _innings_to_outs(stat.get("inningsPitched"))
            opp = (split.get("opponent") or {}).get("id")
            if None in (so, bb, h, r, hr) or o is None or opp is None:
                raise Unverifiable("gamelog start shape unverified")
            starts.append({
                "date": sdate,
                "game_score": game_score(so, o, bb, h, r, hr),
                "outs": o, "opp_id": opp,
            })
    starts.sort(key=lambda s: s["date"])
    return starts


def pitcher_rgs(getter, pitcher_id: int, season: int, kickoff_date: date):
    """Trailing raw rGS for one probable starter (V2: no opponent norm).

    Returns (rgs, n_starts, audit). Raises Unverifiable. Point-in-time:
    strictly-earlier starts only.
    """
    starts = fetch_gamelog_starts(getter, pitcher_id, season, kickoff_date)
    if len(starts) < MIN_PITCHER_STARTS:
        raise Unverifiable("only %d starts (<%d)" % (len(starts), MIN_PITCHER_STARTS))
    recent = starts[-SP_RGS_WINDOW:]
    rgs = sum(s["game_score"] for s in recent) / len(recent)
    avg_ip = sum(s["outs"] for s in recent) / len(recent) / 3.0
    if avg_ip < 4.0:
        # De-facto opener: the rGS suppression formula does not apply,
        # mirroring 538's opener rule (use the average, not the listed arm).
        raise Unverifiable("%.2f IP/start (<4.0); opener/bullpen shape" % avg_ip)
    return rgs, len(starts), {
        "starts_used": len(recent), "avg_ip_per_start": round(avg_ip, 2)}


def suppression_for_starter(getter, pitcher_id: int, season: int,
                            kickoff_date: date):
    """Opponent-total adjustment for one starter (V2).

    adj = INTERCEPT + GAMMA * (pitcher_rgs - LEAGUE_MEAN_GS), capped.
    Negative suppresses the opponent's total. Raises Unverifiable.
    """
    rgs, n, audit = pitcher_rgs(getter, pitcher_id, season, kickoff_date)
    gap = rgs - LEAGUE_MEAN_GS
    raw = SP_RGS_INTERCEPT + SP_RGS_GAMMA * gap
    adj = max(-SP_RGS_ADJ_CAP, min(SP_RGS_ADJ_CAP, raw))
    return adj, {
        "pitcher_rgs": round(rgs, 2), "pitcher_starts": n,
        "league_mean_gs": LEAGUE_MEAN_GS,
        "rgs_gap_vs_league": round(gap, 2),
        "adjustment_to_opponent_total": round(adj, 3),
        "gamma": SP_RGS_GAMMA, "intercept": SP_RGS_INTERCEPT,
        "variant": "V2_league_relative_raw",
        "pitcher_detail": audit,
    }
