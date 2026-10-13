"""NFL QB-absence adjustment adapted from FiveThirtyEight's published NFL
QB-adjustment methodology, calibrated on free nflverse data.

538's published approach (corroborated from the archived methodology text
and the fivethirtyeight/data nfl-elo README):
  per-QB-game VALUE = -2.2*Att + 3.7*Cmp + Yds/5 + 11.3*PTD - 14.1*INT
                     - 8*Sacks - 1.1*RushAtt + 0.6*RushYds + 15.9*RushTD
  defense adjustment: rolling team VALUE-allowed minus rolling league avg,
  applied to the raw game score;
  rating updates in blocks of 10: Rating_new = 0.9*old + 0.1*mean(block),
  initialized at 0 (undrafted-rookie replacement level);
  VALUE * 3.3 = Elo points vs replacement.

Empirical calibration (scripts/study_qb_adjustment.py; nflverse weekly box
scores 2015-2024, point-in-time clean; fit on clean backup-start games
2015-2020, n=599):
  total_QB_effect = QB_INTERCEPT + QB_PER_VALUE_SLOPE * (backup_rating -
                                                        starter_rating)
  = -0.014 + 0.1176 * gap
  (sanity: 0.1176 own-team pts/VALUE-pt vs 538's implied 3.3/25 = 0.132).

Out-of-sample 2021-2024 MSE (own-team points residual):
  no adjustment 90.48 | declared -3.0 96.26 (WORSE than nothing) |
  calibrated constant 90.20 | per-QB VALUE 87.45.  VERDICT: PASS.

Tier 1: backup identifiable (nflverse depth chart gsis_id) with >=10
rated games -> per-QB adjustment above.
Tier 2 (fail-closed): OUT verified but backup rating unavailable ->
constant calibrated mean total effect of backup starts (TIER2_TOTAL_EFFECT).
Doubtful stays declared 50% (DECLARED, not calibrated).

The live path uses nflverse weekly box-score CSVs for every needed season
(the stats_player release carries weekly files for the current season), so
no play-by-play download is required. Missing data -> Tier-2 or blocked;
never a silent zero.
"""
import csv
import math
import os
from collections import defaultdict
from typing import Sequence

_NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"

# --- Fitted constants (pinned; see study_qb_adjustment.py) ---
QB_INTERCEPT = -0.014        # total-point effect at zero rating gap
QB_PER_VALUE_SLOPE = 0.1176  # total points per VALUE point of QB gap
TIER2_TOTAL_EFFECT = -0.582  # empirical mean total effect of backup starts
MIN_RATED_GAMES = 10         # games needed before a rating is trusted
QB_PROVENANCE = "538-adapted-VALUE/nflverse-weekly"


def game_value(s: dict) -> float:
    """538's published per-QB-game VALUE from box-score counting stats."""
    att = _f(s.get("attempts"))
    cmp_ = _f(s.get("completions"))
    yds = _f(s.get("passing_yards"))
    ptd = _f(s.get("passing_tds"))
    inter = _f(s.get("interceptions"))
    sacks = _f(s.get("sacks"))
    ratt = _f(s.get("carries"))
    ryds = _f(s.get("rushing_yards"))
    rtd = _f(s.get("rushing_tds"))
    return (-2.2 * att + 3.7 * cmp_ + yds / 5.0 + 11.3 * ptd
            - 14.1 * inter - 8.0 * sacks - 1.1 * ratt
            + 0.6 * ryds + 15.9 * rtd)


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def _r4(x):
    return round(x, 4) if isinstance(x, (int, float)) else x


def _ensure(path: str, url: str) -> str:
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "sportsedge/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    if os.path.getsize(path) == 0:
        raise OSError(f"empty download: {url}")
    return path


def _iter_weekly_qb_games(seasons: Sequence[int], cache: str):
    """Per-QB games from nflverse weekly CSVs (regular season only).

    Schema A ("player_stats", seasons <= 2024): player_stats_{s}.csv with
    columns interceptions / sacks / recent_team.
    Schema B ("stats_player", seasons >= 1999 incl. current): the
    stats_player release file stats_player_week_{s}.csv with columns
    passing_interceptions / sacks_suffered / team. Both use gsis player_id,
    so the backup QB from the nflverse depth chart matches on gsis_id.
    """
    for season in seasons:
        path_a = os.path.join(cache, f"player_stats_{season}.csv")
        if os.path.exists(path_a):
            schema, path = "A", path_a
        else:
            path = _ensure(
                os.path.join(cache, f"stats_player_week_{season}.csv"),
                f"{_NFLVERSE}/stats_player/stats_player_week_{season}.csv")
            schema = "B"
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("position") or "") != "QB":
                    continue
                if (r.get("season_type") or "REG") != "REG":
                    continue
                if int(r["season"]) != season:
                    continue
                try:
                    week = int(r["week"])
                except (TypeError, ValueError):
                    continue
                if week <= 1:
                    # week 1: no prior games for any rating; kept out of the
                    # calibration fits (538 also anchors to a prior here).
                    continue
                if schema == "A":
                    stat = {"attempts": r["attempts"],
                            "completions": r["completions"],
                            "passing_yards": r["passing_yards"],
                            "passing_tds": r["passing_tds"],
                            "interceptions": r["interceptions"],
                            "sacks": r["sacks"],
                            "carries": r["carries"],
                            "rushing_yards": r["rushing_yards"],
                            "rushing_tds": r["rushing_tds"]}
                    team = r["recent_team"]
                else:
                    stat = {"attempts": r["attempts"],
                            "completions": r["completions"],
                            "passing_yards": r["passing_yards"],
                            "passing_tds": r["passing_tds"],
                            "interceptions": r["passing_interceptions"],
                            "sacks": r["sacks_suffered"],
                            "carries": r["carries"],
                            "rushing_yards": r["rushing_yards"],
                            "rushing_tds": r["rushing_tds"]}
                    team = r["team"]
                att = _f(stat["attempts"])
                if att <= 0:
                    continue
                yield {
                    "season": season, "week": week,
                    "pid": r["player_id"], "pname": r["player_name"],
                    "team": team, "opp": r["opponent_team"],
                    "att": att, "raw": game_value(stat),
                }


def collect_qb_games(seasons: Sequence[int], current_season: int,
                     kickoff, cache: str):
    """All per-QB games, chronological by (season, week).

    Weekly nflverse CSVs (schema A for 2015-2024, schema B incl. the current
    season) cover every needed season. current_season / kickoff are kept in
    the signature for the fail-closed contract: the caller must pass them so
    future edits cannot silently ingest post-kickoff games. Completed seasons
    only are requested by callers for calibration; the live path passes the
    current season through _iter_weekly_qb_games as well, which is point-in-
    time safe because the weekly files only ever contain completed weeks.
    """
    _ = (current_season, kickoff)
    games = []
    for season in seasons:
        games.extend(_iter_weekly_qb_games([season], cache))
    # Weekly files carry no game date; chronological by (season, week) is
    # sufficient: ratings only need per-QB chronological order + defense
    # windows indexed by (season, week).
    games.sort(key=lambda g: (g["season"], g["week"], g["pid"]))
    return games


def compute_ratings(qb_games):
    """Point-in-time 538-style rolling ratings.

    Returns {pid: rating_state}. Processes each QB's games in chronological
    order, applying the 10-game block update rule; the defense adjustment
    uses trailing 20-game team VALUE-allowed (min 5) minus the trailing
    league average, all from strictly earlier (season, week).
    """
    # defense-allowed per team per (season, week): sum of opposing QBs' raw.
    allowed = defaultdict(float)
    for g in qb_games:
        allowed[(g["opp"], g["season"], g["week"])] += g["raw"]

    rating = {}
    block = defaultdict(list)
    played = defaultdict(int)
    state = {}

    # Trailing team allowed history, chronological list of (season, week, v).
    team_allowed_hist = defaultdict(list)
    for g in qb_games:
        team_allowed_hist[g["opp"]].append((g["season"], g["week"], g["raw"]))
    for t in team_allowed_hist:
        team_allowed_hist[t].sort()

    for g in qb_games:
        pid = g["pid"]
        played[pid] += 1
        hist = team_allowed_hist[g["opp"]]
        prior = [v for (s, w, v) in hist
                 if (s, w) < (g["season"], g["week"])]
        tail = prior[-20:]
        if len(tail) >= 5:
            # trailing league average over the same window
            lg_vals = []
            for t2, h2 in team_allowed_hist.items():
                lg_vals.extend(v for (s, w, v) in h2
                               if (s, w) < (g["season"], g["week"]))
            lg_tail = lg_vals[-20 * 32:] or [0.0]
            lg_avg = sum(lg_tail) / len(lg_tail)
            adj = g["raw"] - (sum(tail) / len(tail) - lg_avg)
        else:
            adj = g["raw"]
        block[pid].append(adj)
        if len(block[pid]) == 10:
            rating[pid] = 0.9 * rating.get(pid, 0.0) + 0.1 * (
                sum(block[pid]) / 10.0)
            block[pid] = []
        state[pid] = {"rating": rating.get(pid, 0.0),
                      "games": played[pid], "pname": g["pname"]}
    return state


_DEPTH_CACHE = {}


def _read_depth(path):
    if path not in _DEPTH_CACHE:
        with open(path, newline="") as fh:
            _DEPTH_CACHE[path] = list(csv.DictReader(fh))
    return _DEPTH_CACHE[path]


def depth_qbs_from_depth_chart(cache: str, team_abbr: str):
    """(qb1_gsis, qb1_name, qb2_gsis, qb2_name) from the nflverse depth chart.

    gsis_ids match the rating states exactly across both weekly schemas;
    names are for the audit trail and the injury-feed cross-check.
    """
    path = _ensure(
        os.path.join(cache, "depth_charts_latest.csv"),
        f"{_NFLVERSE}/rosters/depth_charts.csv")
    out = {}
    for r in _read_depth(path):
        if (r.get("team") or "").upper() != team_abbr.upper():
            continue
        if (r.get("pos_abb") or "") != "QB":
            continue
        try:
            rank = int(r.get("pos_rank") or 0)
        except (TypeError, ValueError):
            continue
        if rank in (1, 2):
            out[rank] = ((r.get("gsis_id") or "").strip(),
                         (r.get("player_name") or "").strip())
    q1 = out.get(1, (None, None))
    q2 = out.get(2, (None, None))
    return q1[0], q1[1], q2[0], q2[1]


def backup_gsis_from_depth_chart(cache: str, team_abbr: str):
    """(gsis_id, display name) of the QB2 -- thin wrapper, kept for tests."""
    _, _, gsis, name = depth_qbs_from_depth_chart(cache, team_abbr)
    return gsis, name


def _tier2_extra(source: str, audit: dict):
    return {"extra_total": TIER2_TOTAL_EFFECT,
            "variant": "TIER2_CALIBRATED_CONSTANT",
            "source": source, "audit": audit,
            "provenance": QB_PROVENANCE}


def _names_match(injury_name: str, depth_name: str) -> bool:
    """Last name + first initial must agree (weekly schemas abbreviate)."""
    def key(n):
        parts = n.replace(".", " ").split()
        return (parts[-1].lower(), parts[0][0].lower()) if parts else ("", "")
    return key(injury_name) == key(depth_name)


def qb_absence_extra(ratings, starter_name: str, team_abbr: str, cache: str):
    """Tier-1/2 extra total-points effect for a verified QB OUT.

    Identity chain (all verifiable, no guessing):
      ESPN injury feed starter name  ~=  depth-chart QB1 name
      depth-chart QB1/QB2 gsis_id    ==  rating-state keys (exact)
    Returns dict with extra_total (signed), variant, source, audit,
    provenance. Any identity break -> Tier-2 calibrated constant, never a
    silent zero and never a mismatched rating.
    """
    q1_gsis, q1_name, q2_gsis, q2_name = depth_qbs_from_depth_chart(
        cache, team_abbr)
    audit_base = {"injury_feed_starter": starter_name,
                  "depth_qb1": q1_name, "depth_qb2": q2_name}
    if not q1_gsis or not q2_gsis or not _names_match(starter_name, q1_name):
        audit = dict(audit_base,
                     variant="tier2_identity_break",
                     reason="injury-feed starter does not match depth-chart "
                            "QB1, or depth chart missing")
        return _tier2_extra("TIER2_IDENTITY_BREAK", audit)
    starter_state = ratings.get(q1_gsis)
    backup_state = ratings.get(q2_gsis)
    if starter_state is None or backup_state is None:
        audit = dict(audit_base, variant="tier2_unknown_identity",
                     reason="QB1/QB2 gsis_id not in rating states")
        return _tier2_extra("TIER2_IDENTITY_UNKNOWN", audit)
    if (starter_state["games"] < MIN_RATED_GAMES
            or backup_state["games"] < MIN_RATED_GAMES):
        audit = dict(audit_base, variant="tier2_insufficient_history",
                     starter_games=starter_state["games"],
                     backup_games=backup_state["games"],
                     reason=f"fewer than {MIN_RATED_GAMES} rated games")
        return _tier2_extra("TIER2_INSUFFICIENT_HISTORY", audit)
    gap = backup_state["rating"] - starter_state["rating"]
    audit = dict(audit_base, variant="tier1_qb_gap",
                 starter_gsis=q1_gsis,
                 starter_rating=_r4(starter_state["rating"]),
                 starter_games=starter_state["games"],
                 backup_gsis=q2_gsis,
                 backup_rating=_r4(backup_state["rating"]),
                 backup_games=backup_state["games"],
                 gap=_r4(gap))
    return {"extra_total": QB_INTERCEPT + QB_PER_VALUE_SLOPE * gap,
            "variant": "TIER1_PER_QB_VALUE",
            "source": "TIER1_VERIFIED_DEPTH_CHART",
            "audit": audit, "provenance": QB_PROVENANCE}


def build_ratings(cache: str, seasons: Sequence[int], current_season: int,
                  kickoff):
    """Convenience: collect games and compute ratings for the given seasons."""
    games = collect_qb_games(seasons, current_season, kickoff, cache)
    return compute_ratings(games), games
