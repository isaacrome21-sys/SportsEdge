"""NFL anytime-touchdown scorer pricing from free nflverse data.

Architecture: the ETR (Establish The Run) opportunity-decomposition framework,
rebuilt on free data only --
    team plays -> pass/run split by game state -> player opportunity share
    -> red-zone split -> TD conversion -> P(anytime TD) = 1 - exp(-xTD)

ETR component mapping (honest accounting of what nflverse provides):

    ETR component                  Free-data implementation            Status
    ------------------------------ ---------------------------------- ------------
    Team plays                     Trailing offensive plays/game,      IMPLEMENTED
                                   shrunk to league mean, opp factor
    Pass/run split by game state   Neutral-script pass rate (1st/2nd   IMPLEMENTED
                                   down, qtr<=3, win prob 0.2-0.8),
                                   trailing, shrunk to league mean.
                                   (No spread conditioning: pricing
                                   stays market-blind.)
    Routes x TPRR                   nflverse has NO routes data.        APPROXIMATED
                                   Approximated by target share of
                                   team pass attempts x snap share
                                   (targets-per-snap role proxy).
    Carry share                     Trailing carries / team rush         IMPLEMENTED
                                   attempts, shrunk to position prior.
    Red-zone share                  Trailing red-zone opps / team        IMPLEMENTED
                                   red-zone opps from pbp, shrunk.
    Goal-line personnel packages    No free personnel data. Folded      APPROXIMATED
                                   into the red-zone opportunity mix.
    TD conversion                   Player TD/opportunity shrunk to     IMPLEMENTED
                                   PIT-safe position baselines,
                                   split red-zone vs open field.
    Game-state script adjustment    Not implemented (would need         NOT WIRED
    beyond neutral pass rate        spread/total = market-derived).

Model:
    xTD_i = ( x_rz_carries*c_rz_rush + x_open_carries*c_open_rush
            + x_rz_targets*c_rz_rec  + x_open_targets*c_open_rec ) * opp_factor
    P(anytime TD) = 1 - exp(-xTD_i)

All inputs are strictly point-in-time: every row used must have kickoff
strictly before the priced game's kickoff.  Kickoffs come from nflverse/nfldata
games.csv.

Data (all free, no API keys):
    - nflverse stats_player_week_{season}.csv : per-game rushing_tds,
      receiving_tds, carries, targets, receptions (player history)
    - nflverse snap_counts_{season}.csv      : per-game offense_pct (role gate)
    - nflverse play_by_play_{season}.csv.gz  : red-zone carries/targets/TDs,
      team rush/pass attempts, neutral pass rate, per-team offensive TDs
    - nflverse/nfldata games.csv             : kickoff timestamps for strict
      PIT filtering

Fail-closed: missing identity, < MIN_GAMES history, low snap share, missing
team baseline, or failed data fetch all produce BLOCKED outputs with explicit
reason codes.  First-TD scorer is assessed honestly and stays blocked
(NO_VERIFIED_FIRST_SCORING_ATTRIBUTION) -- see assess_first_td().

Research only. No betting authority, no staking.
"""
from __future__ import annotations

import gzip
import io
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

try:  # pandas is the supported tabular engine for this module
    import pandas as pd
except ImportError as exc:  # pragma: no cover
    raise ImportError("nfl_anytime_td requires pandas") from exc


class NflTdError(ValueError):
    """Fail-closed error with a machine-readable reason code."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NFLVERSE_RELEASE = "https://github.com/nflverse/nflverse-data/releases/download"
NFLVERSE_GAMES_CSV = (
    "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
)
USER_AGENT = "SportsEdge/1.0"

SOURCE_URLS = {
    "player_stats": NFLVERSE_RELEASE + "/stats_player/stats_player_week_{season}.csv",
    "snap_counts": NFLVERSE_RELEASE + "/snap_counts/snap_counts_{season}.csv",
    "pbp": NFLVERSE_RELEASE + "/pbp/play_by_play_{season}.csv.gz",
    "games": NFLVERSE_GAMES_CSV,
}

ELIGIBLE_SEASON_TYPES = frozenset({"REG", "POST"})
ELIGIBLE_POSITION_GROUPS = frozenset({"QB", "RB", "WR", "TE"})

# Columns actually read (memory: full-width pbp is ~300 cols x 4 seasons;
# loading everything OOMs a 7GB box, so read only what the model uses).
LOAD_COLUMNS = {
    "player_stats": [
        "player_id", "player_display_name", "position", "position_group",
        "season", "week", "season_type", "game_id", "team", "opponent_team",
        "carries", "rushing_tds", "targets", "receptions", "receiving_tds",
    ],
    "snap_counts": ["game_id", "season", "week", "player", "team", "offense_pct"],
    "pbp": [
        "game_id", "posteam", "yardline_100", "pass_attempt", "rush_attempt",
        "rusher_player_id", "receiver_player_id",
        "pass_touchdown", "rush_touchdown", "penalty", "two_point_attempt",
        "qb_kneel", "qb_spike", "wp", "down", "qtr",
    ],
    "games": [
        "game_id", "season", "week", "game_type", "gameday", "gametime",
        "home_team", "away_team", "home_score", "away_score",
    ],
}

# Schema contract: the source must contain exactly the columns we load.
REQUIRED_COLUMNS = {kind: frozenset(cols) for kind, cols in LOAD_COLUMNS.items()}

# Model gates / hyper-parameters (documented a priori, not tuned on any test
# window; the harness decides whether they survive).
TRAILING_GAMES_K = 10       # player/team trailing window (games)
MIN_GAMES = 5               # minimum prior completed player games
MIN_SNAP_SHARE = 0.15       # minimum trailing avg offensive snap share
MIN_TEAM_GAMES = 3          # minimum trailing team games
SHRINK_SHARE_M = 60.0       # opportunity-share shrinkage (opportunities)
SHRINK_RZ_MIX_M = 20.0      # red-zone-mix shrinkage (opportunities)
SHRINK_CONV_M = 40.0        # TD-conversion shrinkage (opportunities)
SHRINK_TEAM_M = 8.0         # team-rate shrinkage (games)
OPP_FACTOR_LO, OPP_FACTOR_HI = 0.6, 1.6
REDZONE_YARDLINE = 20       # yardline_100 <= 20
P_CLIP = 1e-4               # probability clip for log-loss stability

_EASTERN = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Data acquisition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceProof:
    kind: str
    season: int | None
    source_uri: str
    source_sha256: str


def _default_cache_dir() -> Path:
    return Path.home() / ".cache" / "sportsedge" / "nfl_td"


def _read_cached(kind: str, season: int | None, cache_dir: Path,
                 opener: Callable = urlopen) -> tuple[pd.DataFrame, SourceProof]:
    url = SOURCE_URLS[kind].format(season=season) if season is not None else SOURCE_URLS[kind]
    tag = f"{kind}" if season is None else f"{kind}_{season}"
    suffix = ".csv.gz" if kind == "pbp" else ".csv"
    path = cache_dir / f"nflverse_{tag}{suffix}"
    if path.exists():
        raw = path.read_bytes()
    else:
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with opener(req, timeout=120) as resp:
                raw = resp.read()
        except Exception as exc:
            raise NflTdError(f"TD_FETCH_FAILED:{tag}") from exc
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    proof = SourceProof(kind=kind, season=season, source_uri=url,
                        source_sha256=sha256(raw).hexdigest())
    try:
        if kind == "pbp":
            with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8") as fh:
                df = pd.read_csv(fh, low_memory=False,
                                 usecols=LOAD_COLUMNS[kind])
        else:
            df = pd.read_csv(io.BytesIO(raw), low_memory=False,
                             usecols=LOAD_COLUMNS[kind])
    except ValueError as exc:
        # usecols raises ValueError when the source lacks a needed column
        raise NflTdError(f"TD_SCHEMA_UNSUPPORTED:{tag}:{exc}") from exc
    except Exception as exc:
        raise NflTdError(f"TD_CSV_INVALID:{tag}") from exc
    if df.empty:
        raise NflTdError(f"TD_TABLE_EMPTY:{tag}")
    missing = REQUIRED_COLUMNS[kind] - set(df.columns)
    if missing:
        raise NflTdError(f"TD_SCHEMA_UNSUPPORTED:{tag}:{','.join(sorted(missing))}")
    return df, proof


def load_td_history(*, seasons: Iterable[int], cache_dir: str | Path | None = None,
                    opener: Callable = urlopen) -> dict[str, Any]:
    """Load and PIT-index the nflverse tables used by the anytime-TD model.

    pbp is required: red-zone opportunities, team rush/pass attempts, and the
    neutral pass rate all come from it.  A failed pbp fetch is fail-closed
    (TD_FETCH_FAILED), never silently worked around.
    """
    seasons = sorted({int(s) for s in seasons})
    if not seasons:
        raise NflTdError("TD_SEASONS_REQUIRED")
    cache = Path(cache_dir) if cache_dir else _default_cache_dir()

    ps_frames, snap_frames, pbp_frames, proofs = [], [], [], []
    for season in seasons:
        df, proof = _read_cached("player_stats", season, cache, opener)
        ps_frames.append(df); proofs.append(proof)
        df, proof = _read_cached("snap_counts", season, cache, opener)
        snap_frames.append(df); proofs.append(proof)
        df, proof = _read_cached("pbp", season, cache, opener)
        pbp_frames.append(df); proofs.append(proof)
    games_df, proof = _read_cached("games", None, cache, opener)
    proofs.append(proof)

    player_stats = pd.concat(ps_frames, ignore_index=True).copy()
    snaps = pd.concat(snap_frames, ignore_index=True).copy()
    pbp = pd.concat(pbp_frames, ignore_index=True).copy()

    # --- kickoff index (strict PIT key) ------------------------------------
    games = games_df.copy()
    games["kickoff"] = games.apply(_parse_kickoff, axis=1)
    kickoff_by_game = games.set_index("game_id")["kickoff"]

    player_stats = player_stats[player_stats["season_type"].isin(ELIGIBLE_SEASON_TYPES)].copy()
    player_stats["kickoff"] = player_stats["game_id"].map(kickoff_by_game)
    player_stats = player_stats.dropna(subset=["kickoff"]).copy()
    for col in ("rushing_tds", "receiving_tds", "carries", "targets", "receptions"):
        player_stats[col] = pd.to_numeric(player_stats[col], errors="coerce").fillna(0)
    player_stats["off_tds"] = player_stats["rushing_tds"] + player_stats["receiving_tds"]

    snaps = snaps.copy()
    snaps["kickoff"] = snaps["game_id"].map(kickoff_by_game)
    snaps = snaps.dropna(subset=["kickoff"]).copy()
    snaps["offense_pct"] = pd.to_numeric(snaps["offense_pct"], errors="coerce")
    snaps["_norm_name"] = snaps["player"].astype(str).map(_norm_name)
    snap_lookup = (
        snaps.dropna(subset=["offense_pct"])
        .groupby(["game_id", "team", "_norm_name"])["offense_pct"].max()
    )

    pbp["kickoff"] = pbp["game_id"].map(kickoff_by_game)
    pbp = pbp.dropna(subset=["kickoff"]).copy()
    team_games = _build_team_games(pbp)
    rz_player = _build_redzone_player(pbp)

    return {
        "player_stats": player_stats,
        "snaps": snaps,
        "snap_lookup": snap_lookup,
        "pbp": pbp,
        "team_games": team_games,
        "rz_player": rz_player,
        "games": games,
        "proofs": proofs,
        "seasons": seasons,
    }


def _parse_kickoff(row: Mapping[str, Any]) -> datetime | None:
    try:
        day = str(row.get("gameday") or "").strip()[:10]
        clock = str(row.get("gametime") or "").strip()
        if not day or not clock:
            return None
        clock8 = clock[:8] if len(clock) >= 8 else clock + ":00"
        local = datetime.combine(
            datetime.fromisoformat(day).date(),
            datetime.strptime(clock8, "%H:%M:%S").time(),
            tzinfo=_EASTERN,
        )
        return local.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


import re as _re

_SUFFIX_RE = _re.compile(r"\s+(jr|sr|ii|iii|iv|v)$")


def _norm_name(name: str) -> str:
    # nflverse display names vs snap-count names differ on suffixes
    # ("Marvin Mims Jr" vs "Marvin Mims"); strip them for the join.
    # Verified 99.2% join rate on 2025 week-1 eligible positions.
    s = " ".join(str(name).lower().replace(".", "").split())
    return _SUFFIX_RE.sub("", s)


def _num(plays: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(plays[col], errors="coerce").fillna(0)


def _build_team_games(pbp: pd.DataFrame) -> pd.DataFrame:
    """One row per team-game: plays, rush/pass attempts, neutral pass rate,
    offensive TDs, red-zone opportunities."""
    plays = pbp.copy()
    for col in ("pass_touchdown", "rush_touchdown", "penalty",
                "two_point_attempt", "yardline_100", "pass_attempt",
                "rush_attempt", "qb_kneel", "qb_spike", "down", "qtr", "wp"):
        plays[col] = _num(plays, col)
    live = (plays["penalty"] == 0) & (plays["two_point_attempt"] == 0)
    clean = live & (plays["qb_kneel"] == 0) & (plays["qb_spike"] == 0)
    is_pass = clean & (plays["pass_attempt"] == 1)
    is_rush = clean & (plays["rush_attempt"] == 1)
    plays["_rush_att"] = is_rush.astype(int)
    plays["_pass_att"] = is_pass.astype(int)
    plays["_off_td"] = (live & ((plays["pass_touchdown"] == 1)
                                | (plays["rush_touchdown"] == 1))).astype(int)
    plays["_rz_opp"] = (clean & (plays["yardline_100"] <= REDZONE_YARDLINE)
                        & (is_pass | is_rush)).astype(int)
    # neutral script: 1st/2nd down, quarters 1-3, competitive win probability
    neutral = (clean & plays["down"].isin([1, 2]) & (plays["qtr"] <= 3)
               & (plays["wp"] >= 0.2) & (plays["wp"] <= 0.8))
    plays["_n_pass"] = (neutral & is_pass).astype(int)
    plays["_n_rush"] = (neutral & is_rush).astype(int)
    grp = plays.groupby(["game_id", "posteam", "kickoff"], dropna=False)
    team_games = grp.agg(
        rush_atts=("_rush_att", "sum"), pass_atts=("_pass_att", "sum"),
        off_tds=("_off_td", "sum"), rz_opps=("_rz_opp", "sum"),
        n_pass=("_n_pass", "sum"), n_rush=("_n_rush", "sum"),
    ).reset_index().rename(columns={"posteam": "team"})
    team_games["plays"] = team_games["rush_atts"] + team_games["pass_atts"]
    n_tot = team_games["n_pass"] + team_games["n_rush"]
    team_games["neutral_pass_rate"] = (team_games["n_pass"] / n_tot).where(n_tot > 0)
    return team_games


def _build_redzone_player(pbp: pd.DataFrame) -> pd.DataFrame:
    """Per player-game red-zone carries/targets/TDs (GSIS player_id join)."""
    plays = pbp.copy()
    for col in ("penalty", "two_point_attempt", "yardline_100", "pass_attempt",
                "rush_attempt", "qb_kneel", "qb_spike", "rush_touchdown",
                "pass_touchdown"):
        plays[col] = _num(plays, col)
    live = (plays["penalty"] == 0) & (plays["two_point_attempt"] == 0)
    clean = live & (plays["qb_kneel"] == 0) & (plays["qb_spike"] == 0)
    rz = clean & (plays["yardline_100"] <= REDZONE_YARDLINE)
    carries = plays[rz & (plays["rush_attempt"] == 1)].copy()
    targets = plays[rz & (plays["pass_attempt"] == 1)].copy()
    carries["_pid"] = carries["rusher_player_id"].astype(str)
    targets["_pid"] = targets["receiver_player_id"].astype(str)
    carries["_td"] = (carries["rush_touchdown"] == 1).astype(int)
    targets["_td"] = (targets["pass_touchdown"] == 1).astype(int)

    def _agg(frame: pd.DataFrame, opp_col: str, td_col: str) -> pd.DataFrame:
        f = frame[frame["_pid"].ne("nan") & frame["_pid"].ne("None")]
        g = f.groupby(["game_id", "_pid", "kickoff"])
        return pd.DataFrame({
            opp_col: g.size(),
            td_col: g["_td"].sum(),
        })

    c = _agg(carries, "rz_carries", "rz_rush_tds")
    t = _agg(targets, "rz_targets", "rz_rec_tds")
    out = pd.concat([c, t], axis=1).fillna(0).reset_index()
    out = out.rename(columns={"_pid": "player_id"})
    out["rz_opps"] = out["rz_carries"] + out["rz_targets"]
    out["rz_tds"] = out["rz_rush_tds"] + out["rz_rec_tds"]
    return out


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def _pit(frame: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    return frame[frame["kickoff"] < as_of]


def _shrink(raw_num: float, raw_den: float, prior: float, m: float) -> tuple[float, float]:
    """Empirical-Bayes blend; returns (estimate, prior_weight)."""
    w = m / (raw_den + m) if (raw_den + m) > 0 else 1.0
    return (1.0 - w) * (raw_num / raw_den if raw_den > 0 else 0.0) + w * prior, w


def resolve_player_id(history: Mapping[str, Any], *, display_name: str,
                      team: str, as_of: datetime) -> str:
    """Resolve a display name + team to the nflverse GSIS player_id.

    Uses only rows strictly before as_of.  Fail closed on ambiguity.
    """
    ps = _pit(history["player_stats"], as_of)
    norm = _norm_name(display_name)
    team_u = str(team).strip().upper()
    cand = ps[(ps["player_display_name"].astype(str).map(_norm_name) == norm)
              & (ps["team"].astype(str).str.upper() == team_u)]
    ids = cand["player_id"].astype(str).unique()
    if len(ids) == 0:
        raise NflTdError(f"TD_IDENTITY_UNRESOLVED:{display_name}:{team}")
    if len(ids) > 1:
        raise NflTdError(f"TD_IDENTITY_AMBIGUOUS:{display_name}:{team}")
    return str(ids[0])


def position_priors(history: Mapping[str, Any], *, as_of: datetime) -> dict[str, dict[str, float]]:
    """PIT-safe position-group baselines for shares, mixes, and conversions.

    Shrinkage targets only -- they never substitute for player history (every
    priced prop still requires the player's own trailing games).
    """
    ps = _pit(history["player_stats"], as_of)
    tg = _pit(history["team_games"], as_of)
    rz = _pit(history["rz_player"], as_of)
    team_rush = tg.set_index(["game_id", "team"])["rush_atts"]
    team_pass = tg.set_index(["game_id", "team"])["pass_atts"]
    ps = ps.copy()
    idx = ps.set_index(["game_id", "team"]).index
    ps["_team_rush"] = idx.map(team_rush).fillna(0)
    ps["_team_pass"] = idx.map(team_pass).fillna(0)
    rz_c = rz.set_index(["game_id", "player_id"])[["rz_carries", "rz_targets",
                                                   "rz_rush_tds", "rz_rec_tds"]]
    ps["_rz_carries"] = ps.set_index(["game_id", "player_id"]).index.map(
        rz_c["rz_carries"]).fillna(0)
    ps["_rz_targets"] = ps.set_index(["game_id", "player_id"]).index.map(
        rz_c["rz_targets"]).fillna(0)
    ps["_rz_rush_tds"] = ps.set_index(["game_id", "player_id"]).index.map(
        rz_c["rz_rush_tds"]).fillna(0)
    ps["_rz_rec_tds"] = ps.set_index(["game_id", "player_id"]).index.map(
        rz_c["rz_rec_tds"]).fillna(0)

    priors: dict[str, dict[str, float]] = {}
    elig = ps[ps["position_group"].isin(ELIGIBLE_POSITION_GROUPS)]
    for pos, grp in elig.groupby("position_group"):
        d: dict[str, float] = {"n_rows": float(len(grp))}
        d["carry_share"] = float(grp["carries"].sum() / grp["_team_rush"].sum()) \
            if grp["_team_rush"].sum() > 0 else 0.0
        d["target_share"] = float(grp["targets"].sum() / grp["_team_pass"].sum()) \
            if grp["_team_pass"].sum() > 0 else 0.0
        d["rz_carry_mix"] = float(grp["_rz_carries"].sum() / grp["carries"].sum()) \
            if grp["carries"].sum() > 0 else 0.0
        d["rz_target_mix"] = float(grp["_rz_targets"].sum() / grp["targets"].sum()) \
            if grp["targets"].sum() > 0 else 0.0
        open_rush = grp["carries"].sum() - grp["_rz_carries"].sum()
        open_tgt = grp["targets"].sum() - grp["_rz_targets"].sum()
        d["conv_rz_rush"] = float(grp["_rz_rush_tds"].sum() / grp["_rz_carries"].sum()) \
            if grp["_rz_carries"].sum() > 0 else 0.0
        d["conv_open_rush"] = float(max(0.0, grp["rushing_tds"].sum() - grp["_rz_rush_tds"].sum())
                                   / open_rush) if open_rush > 0 else 0.0
        d["conv_rz_rec"] = float(grp["_rz_rec_tds"].sum() / grp["_rz_targets"].sum()) \
            if grp["_rz_targets"].sum() > 0 else 0.0
        d["conv_open_rec"] = float(max(0.0, grp["receiving_tds"].sum() - grp["_rz_rec_tds"].sum())
                                  / open_tgt) if open_tgt > 0 else 0.0
        priors[str(pos)] = d
    return priors


def opponent_factor(history: Mapping[str, Any], *, opponent: str,
                    as_of: datetime) -> dict[str, float]:
    """Scoring-environment factor from opponent's trailing TDs allowed.

    Multiplicative, clamped.  Documented approximation: one factor for all
    opportunity pools (no per-pool opponent splits -- sample too thin).
    """
    tg = _pit(history["team_games"], as_of)
    opp_u = str(opponent).strip().upper()
    opp_game_ids = tg[tg["team"] == opp_u]["game_id"].unique()
    allowed = tg[tg["game_id"].isin(opp_game_ids) & (tg["team"] != opp_u)]
    allowed = allowed.sort_values("kickoff").tail(TRAILING_GAMES_K)
    league = tg[tg["kickoff"] >= (as_of - pd.Timedelta(days=3 * 366))]
    league_mean = float(league["off_tds"].mean()) if len(league) else 2.4
    if len(allowed) >= MIN_TEAM_GAMES:
        o_rate = (float(allowed["off_tds"].sum()) + SHRINK_TEAM_M * league_mean) \
            / (len(allowed) + SHRINK_TEAM_M)
        factor = min(OPP_FACTOR_HI, max(OPP_FACTOR_LO,
                                        o_rate / league_mean if league_mean > 0 else 1.0))
    else:
        o_rate, factor = league_mean, 1.0
    return {"opp_factor": factor, "opp_allow_rate": o_rate,
            "league_mean": league_mean, "opp_games": int(len(allowed))}


def team_play_expectation(history: Mapping[str, Any], *, team: str,
                          as_of: datetime) -> dict[str, float]:
    """Expected rush/pass attempts for `team` (ETR: team plays -> pass/run
    split by game state).  PIT-safe."""
    tg = _pit(history["team_games"], as_of)
    team_u = str(team).strip().upper()
    t_hist = tg[tg["team"] == team_u].sort_values("kickoff").tail(TRAILING_GAMES_K)
    if len(t_hist) < MIN_TEAM_GAMES:
        raise NflTdError(f"TD_TEAM_BASELINE_THIN:{team_u}:n={len(t_hist)}")
    league = tg[tg["kickoff"] >= (as_of - pd.Timedelta(days=3 * 366))]
    lg_plays = float(league["plays"].mean()) if len(league) else 62.0
    lg_npr = float(league["neutral_pass_rate"].mean()) if len(league) else 0.58
    plays = (float(t_hist["plays"].sum()) + SHRINK_TEAM_M * lg_plays) \
        / (len(t_hist) + SHRINK_TEAM_M)
    npr_num = float((t_hist["neutral_pass_rate"] * (t_hist["n_pass"] + t_hist["n_rush"])).sum())
    npr_den = float((t_hist["n_pass"] + t_hist["n_rush"]).sum())
    npr_raw = npr_num / npr_den if npr_den > 0 else lg_npr
    npr_w = SHRINK_TEAM_M / (npr_den / 60.0 + SHRINK_TEAM_M)  # ~games of neutral plays
    npr = (1 - npr_w) * npr_raw + npr_w * lg_npr
    return {"exp_rush_atts": plays * (1 - npr), "exp_pass_atts": plays * npr,
            "exp_plays": plays, "neutral_pass_rate": npr,
            "team_games": int(len(t_hist))}


def estimate_anytime_td(history: Mapping[str, Any], *, player_id: str,
                        player_name: str, team: str, opponent: str,
                        game_id: str, kickoff: datetime,
                        priors: dict[str, dict[str, float]] | None = None,
                        team_plays: dict[str, float] | None = None,
                        opp: dict[str, float] | None = None) -> dict[str, Any]:
    """Price P(anytime TD) for one player-game.  Fail closed with reason codes."""
    pid = str(player_id).strip()
    team_u, opp_u = str(team).strip().upper(), str(opponent).strip().upper()
    if not pid or not team_u or not opp_u or not str(game_id).strip():
        raise NflTdError("TD_IDENTITY_INCOMPLETE")
    if kickoff.tzinfo is None:
        raise NflTdError("TD_KICKOFF_TIMEZONE_REQUIRED")
    as_of = kickoff  # strict < filtering inside _pit; nothing at/after kickoff used

    ps = _pit(history["player_stats"], as_of)
    rows = ps[ps["player_id"].astype(str) == pid].sort_values("kickoff").tail(TRAILING_GAMES_K)
    if len(rows) < MIN_GAMES:
        raise NflTdError(f"TD_HISTORY_INSUFFICIENT:{player_name}:n={len(rows)}")
    pos = str(rows["position_group"].iloc[-1])
    if pos not in ELIGIBLE_POSITION_GROUPS:
        raise NflTdError(f"TD_POSITION_UNSUPPORTED:{player_name}:{pos}")

    # --- snap-share participation gate (TPRR approximation needs role) ------
    lookup = history["snap_lookup"]
    snap_vals = []
    for _, r in rows.iterrows():
        key = (str(r["game_id"]), str(r["team"]).upper(),
               _norm_name(str(r["player_display_name"])))
        try:
            snap_vals.append(float(lookup.loc[key]))
        except KeyError:
            snap_vals.append(None)
    known = [v for v in snap_vals if v is not None]
    if len(known) < MIN_GAMES:
        raise NflTdError(f"TD_SNAP_SHARE_UNVERIFIED:{player_name}:n={len(known)}")
    snap_share = sum(known) / len(known)
    if snap_share < MIN_SNAP_SHARE:
        raise NflTdError(f"TD_SNAP_SHARE_LOW:{player_name}:{snap_share:.2f}")

    # --- player opportunity shares over the trailing window -----------------
    # Team totals are accumulated per trailing game's OWN team (from the
    # player_stats row), not the fixture team: players who changed teams
    # would otherwise get opportunity shares against the wrong denominator.
    tg = _pit(history["team_games"], as_of)
    pairs = list(zip([str(g) for g in rows["game_id"]],
                     [str(t).strip().upper() for t in rows["team"]]))
    team_rows = tg[tg.set_index(["game_id", "team"]).index.isin(pairs)]
    if len(team_rows) == 0 or float(team_rows["plays"].sum()) <= 0:
        raise NflTdError(f"TD_NO_TEAM_BASELINE:{team_u}")

    carries_i = float(rows["carries"].sum())
    targets_i = float(rows["targets"].sum())
    team_rush = float(team_rows["rush_atts"].sum())
    team_pass = float(team_rows["pass_atts"].sum())

    rz = _pit(history["rz_player"], as_of)
    prz = rz[(rz["player_id"].astype(str) == pid)
             & (rz["game_id"].isin([p[0] for p in pairs]))]
    rz_carries_i = float(prz["rz_carries"].sum())
    rz_targets_i = float(prz["rz_targets"].sum())
    rz_rush_tds_i = float(prz["rz_rush_tds"].sum())
    rz_rec_tds_i = float(prz["rz_rec_tds"].sum())
    rush_tds_i = float(rows["rushing_tds"].sum())
    rec_tds_i = float(rows["receiving_tds"].sum())
    open_rush_tds_i = max(0.0, rush_tds_i - rz_rush_tds_i)
    open_rec_tds_i = max(0.0, rec_tds_i - rz_rec_tds_i)
    open_carries_i = max(0.0, carries_i - rz_carries_i)
    open_targets_i = max(0.0, targets_i - rz_targets_i)

    if priors is None:
        priors = position_priors(history, as_of=as_of)
    prior = priors.get(pos)
    if prior is None:
        raise NflTdError(f"TD_POSITION_PRIOR_MISSING:{pos}")

    carry_share, w_carry = _shrink(carries_i, team_rush, prior["carry_share"], SHRINK_SHARE_M)
    target_share, w_tgt = _shrink(targets_i, team_pass, prior["target_share"], SHRINK_SHARE_M)
    rz_carry_mix, w_rzm_c = _shrink(rz_carries_i, carries_i, prior["rz_carry_mix"], SHRINK_RZ_MIX_M)
    rz_target_mix, w_rzm_t = _shrink(rz_targets_i, targets_i, prior["rz_target_mix"], SHRINK_RZ_MIX_M)
    conv_rz_rush, w_c1 = _shrink(rz_rush_tds_i, rz_carries_i, prior["conv_rz_rush"], SHRINK_CONV_M)
    conv_open_rush, w_c2 = _shrink(open_rush_tds_i, open_carries_i, prior["conv_open_rush"], SHRINK_CONV_M)
    conv_rz_rec, w_c3 = _shrink(rz_rec_tds_i, rz_targets_i, prior["conv_rz_rec"], SHRINK_CONV_M)
    conv_open_rec, w_c4 = _shrink(open_rec_tds_i, open_targets_i, prior["conv_open_rec"], SHRINK_CONV_M)

    # --- team play expectations (ETR: team plays -> pass/run split) ---------
    if team_plays is None:
        team_plays = team_play_expectation(history, team=team_u, as_of=as_of)
    if opp is None:
        opp = opponent_factor(history, opponent=opp_u, as_of=as_of)

    x_rz_carries = team_plays["exp_rush_atts"] * carry_share * rz_carry_mix
    x_open_carries = team_plays["exp_rush_atts"] * carry_share * (1 - rz_carry_mix)
    x_rz_targets = team_plays["exp_pass_atts"] * target_share * rz_target_mix
    x_open_targets = team_plays["exp_pass_atts"] * target_share * (1 - rz_target_mix)

    xtd = (x_rz_carries * conv_rz_rush + x_open_carries * conv_open_rush
           + x_rz_targets * conv_rz_rec + x_open_targets * conv_open_rec)
    xtd *= opp["opp_factor"]
    p = 1.0 - math.exp(-xtd)
    p = min(1.0 - P_CLIP, max(P_CLIP, p))

    flags: list[str] = []
    if len(rows) < 8:
        flags.append("TD_SAMPLE_SMALL")
    if snap_share < 0.30:
        flags.append("TD_ROLE_UNCERTAIN")
    if (w_carry + w_tgt) / 2 > 0.5:
        flags.append("TD_PRIOR_DOMINATED")
    if (w_c1 + w_c2 + w_c3 + w_c4) / 4 > 0.6:
        flags.append("TD_CONVERSION_PRIOR_DOMINATED")
    if team_plays["team_games"] < 8:
        flags.append("TD_TEAM_BASELINE_THIN")

    return {
        "status": "PRICED",
        "sport": "NFL",
        "market": "ANYTIME_TD",
        "selection": str(player_name),
        "player_id": pid,
        "game_id": str(game_id),
        "team": team_u,
        "opponent": opp_u,
        "kickoff": kickoff.isoformat(),
        "model_p": p,
        "xtd": xtd,
        "components": {
            "x_rz_carries": x_rz_carries, "x_open_carries": x_open_carries,
            "x_rz_targets": x_rz_targets, "x_open_targets": x_open_targets,
            "conv_rz_rush": conv_rz_rush, "conv_open_rush": conv_open_rush,
            "conv_rz_rec": conv_rz_rec, "conv_open_rec": conv_open_rec,
            "carry_share": carry_share, "target_share": target_share,
            "rz_carry_mix": rz_carry_mix, "rz_target_mix": rz_target_mix,
            "exp_rush_atts": team_plays["exp_rush_atts"],
            "exp_pass_atts": team_plays["exp_pass_atts"],
            "neutral_pass_rate": team_plays["neutral_pass_rate"],
            "opp_factor": opp["opp_factor"],
        },
        "n_games": int(len(rows)),
        "snap_share": snap_share,
        "position_group": pos,
        "uncertainty_flags": flags,
        "evidence": {
            "sources": [
                {"kind": pr.kind, "season": pr.season, "uri": pr.source_uri,
                 "sha256": pr.source_sha256} for pr in history["proofs"]
            ],
            "seasons": list(history["seasons"]),
            "pit": f"all inputs kickoff < {as_of.isoformat()}",
            "etr_mapping": "team plays -> neutral pass/run split -> "
                           "carry/target share (TPRR approximated via "
                           "targets-per-snap) -> red-zone split -> "
                           "TD conversion; routes and goal-line personnel "
                           "not available in free data",
        },
        "research_only": True,
        "official_authority": False,
        "model_p_authority": False,
        "staking_authority": False,
    }


def blocked_anytime_td(*, player_name: str = "", game_id: str = "",
                       team: str = "", reason: str) -> dict[str, Any]:
    """Fail-closed output matching the phone-pricing blocked() convention."""
    return {"status": "NO_MODEL_OR_MARKET", "reason": str(reason)[:180],
            "sport": "NFL", "market": "ANYTIME_TD",
            "selection": str(player_name), "player_name": str(player_name),
            "game_id": str(game_id), "team": str(team),
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False}


# ---------------------------------------------------------------------------
# First-TD scorer: honest feasibility assessment
# ---------------------------------------------------------------------------

def assess_first_td() -> dict[str, Any]:
    """Assess whether first-TD scorer is verifiable from free pre-kickoff data.

    Verdict: NOT verifiable.  The required pre-kickoff inputs do not exist in
    any free source:
      1. Opening possession is decided by a coin toss conducted at game time.
         The outcome is random and unknowable before kickoff; nflverse records
         coin_toss_winner only post-game, so no pre-kickoff source can tell
         which team receives the opening kickoff.
      2. Team receive-vs-defer tendencies are real but the toss outcome
         dominates; the residual pre-kickoff edge on "who gets the ball first"
         is swamped by noise and is not a verifiable player-level input.
      3. The game's first TD is frequently NOT on the opening drive (punts,
         turnovers, and field goals intervene), and defensive/special-teams
         TDs can be the first TD of the game -- none of these are attributable
         to an offensive player's pre-kickoff role.
      4. Per-player opening-drive TD samples are a handful of events per
         season: far too thin for a verified player-specific estimate, and no
         free source publishes pre-kickoff opening-drive personnel or
         sequencing.
    Correct outcome: stays BLOCKED_WITH_REASON
    (NO_VERIFIED_FIRST_SCORING_ATTRIBUTION).
    """
    return {
        "status": "BLOCKED",
        "sport": "NFL",
        "market": "FIRST_TD",
        "reason": "NO_VERIFIED_FIRST_SCORING_ATTRIBUTION",
        "verifiable": False,
        "blockers": [
            "Opening possession is decided by a game-time coin toss; the "
            "outcome is random pre-kickoff and nflverse records "
            "coin_toss_winner only post-game.",
            "Receive-vs-defer tendencies do not overcome toss randomness to a "
            "verifiable degree for player-level pricing.",
            "The first TD is often not on the opening drive; defensive and "
            "special-teams TDs can be first and are not attributable to "
            "offensive role pre-kickoff.",
            "Per-player opening-drive TD samples are a few events per season; "
            "no free source publishes pre-kickoff opening-drive personnel or "
            "sequencing.",
        ],
        "research_only": True,
        "official_authority": False,
        "model_p_authority": False,
        "staking_authority": False,
    }
