"""NFL longest-play + first-reception probability engine (research):
QB longest completion, longest reception, longest rush, and first
reception yardage -- from free nflverse play-by-play.

Markets (matrix N25/N30/N31/N36): LONGEST_COMPLETION (O/U + ladder),
LONGEST_RECEPTION (O/U + ladder), LONGEST_RUSH (O/U + ladder),
FIRST_RECEPTION (yardage O/U on a receiver's first reception).

Identity basis: unlike the N17-N36 volume props, these engines are
built ONLY from the player's own recorded plays in nflverse
play-by-play. No participation/role basis is consumed, asserted, or
modified -- the held #2274 re-audit basis is untouched, and nothing
here depends on it. What play-by-play alone cannot identify is a
game the player appeared in but recorded zero opportunities of the
role (that identification is precisely what a participation basis
would add), so every distribution below is CONDITIONAL on the
player recording at least one opportunity of the role in the priced
game; the readout carries that conditioning explicitly and the
engine makes no participation claim.

Architecture (empirical, strictly point-in-time; every record used
has kickoff strictly before the priced game's kickoff):

    Opportunities/game  trailing per-game opportunity counts for
                        the player (completions / receptions / rush
                        attempts), shrunk toward the league count
                        distribution computed from the same
                        strictly-prior pool (counts + M * league) /
                        (n + M).
    Per-play yardage    the player's trailing per-play yardages,
                        shrunk toward the league per-play yardage
                        distribution from the same pool:
                        F(x) = (#{player plays <= x} + S * F_L(x))
                        / (N + S).
    Longest play        the max-statistic over a random count:
                        P(longest <= x) = sum_n P(N = n) * F(x)^n,
                        differenced over the integer yardage grid.
    First reception     empirical distribution of the player's
                        trailing first-reception yardages (first
                        reception in play order per game), shrunk
                        toward the league first-reception
                        distribution from the same pool.

League aggregates are computed from the supplied pool itself (all
players, same role, strictly-prior games) rather than declared
constants, so no league number is asserted a priori; the pool is
the evidence.

Declared approximations (honest accounting, harness decides):
- Within a game, play yardages are treated as independent draws
  from the shrunk per-play distribution; game script, opponent, and
  within-game correlation are NOT modeled in v1.
- Opportunity counts condition on games with >= 1 recorded
  opportunity (see above); a zero-opportunity game is invisible to
  play-by-play alone.
- Rush attempts include every recorded rush attempt (QB kneels
  included as recorded); completion/reception yardage is the
  play's total yards_gained (including yards after catch), which
  is the quantity the books settle longest completion/reception on.

Fail-closed: missing player identity, invalid role, missing or
naive kickoffs, fewer than MIN_GAMES strictly-prior player games,
zero trailing plays, or an empty league pool all raise
NflLongestPlaysError with a reason code.

GOVERNANCE: this engine is research only. The canonical path still
terminates NFL props at GOVERNANCE_NO_ENGINE
(config/football_prop_engine_surface.json declares NO_ENGINE for
NFL props until an independently validated probability engine is
promoted); nothing here changes that surface or any card row.
Research only. No betting authority, no staking.
"""
from __future__ import annotations

import bisect
import gzip
import io
import math
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.request import Request, urlopen

ENGINE_ID = "NFL_LONGEST_PLAYS_EMPIRICAL"
ENGINE_VERSION = "nfl_longest_plays_empirical_v1_20261015"

NFLVERSE_RELEASE = "https://github.com/nflverse/nflverse-data/releases/download"
NFLVERSE_GAMES_CSV = (
    "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
)
USER_AGENT = "SportsEdge/1.0"

SOURCE_URLS = {
    "pbp": NFLVERSE_RELEASE + "/pbp/play_by_play_{season}.csv.gz",
    "games": NFLVERSE_GAMES_CSV,
}

# Model gates / hyper-parameters (documented a priori).
MIN_GAMES = 5             # minimum strictly-prior player games
TRAILING_GAMES_K = 16     # trailing window (player games)
COUNT_SHRINK_M = 8.0      # pseudo-games of league count distribution
PLAY_SHRINK_PLAYS = 25.0  # pseudo-plays of league per-play distribution
FIRST_REC_SHRINK = 10.0   # pseudo-games of league first-reception dist

MAX_OPPS = 40   # opportunity-count support; tail folded at 40
Y_MIN = -20     # yardage grid floor; plays below fold to Y_MIN
Y_MAX = 99      # yardage grid cap; plays above fold to Y_MAX

ROLES = ("PASSER", "RECEIVER", "RUSHER")
ROLE_MARKET = {
    "PASSER": "LONGEST_COMPLETION",
    "RECEIVER": "LONGEST_RECEPTION",
    "RUSHER": "LONGEST_RUSH",
}


class NflLongestPlaysError(ValueError):
    """Fail-closed error with a machine-readable reason code."""


# ---------------------------------------------------------------------------
# Distribution helpers
# ---------------------------------------------------------------------------

def _fold_counts(counts: Iterable[int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for c in counts:
        k = min(max(int(c), 0), MAX_OPPS)
        out[k] = out.get(k, 0) + 1
    return out


def _shrunk_count_pmf(player_counts: Sequence[int],
                      league_counts: Sequence[int]) -> dict[int, float]:
    """(observed + M * league_pmf) / (n + M) over 0..MAX_OPPS."""
    n = len(player_counts)
    if n == 0 or not league_counts:
        raise NflLongestPlaysError("LONGEST_COUNT_POOL_EMPTY")
    obs = _fold_counts(player_counts)
    lg = _fold_counts(league_counts)
    nl = len(league_counts)
    pmf: dict[int, float] = {}
    for k in range(MAX_OPPS + 1):
        pmf[k] = (obs.get(k, 0) + COUNT_SHRINK_M * (lg.get(k, 0) / nl)) \
            / (n + COUNT_SHRINK_M)
    total = math.fsum(pmf.values())
    return {k: v / total for k, v in pmf.items()}


def _clamp_yards(y: float) -> int:
    return min(max(int(y), Y_MIN), Y_MAX)


def _max_pmf(count_pmf: Mapping[int, float],
             player_plays: Sequence[int],
             league_plays: Sequence[int]) -> dict[int, float]:
    """PMF of the maximum play yardage over a random opportunity
    count: cdf_max(x) = sum_n P(N=n) * F(x)^n, differenced on the
    integer grid. F is the shrunk per-play CDF; plays are clamped
    to the grid, so F(Y_MAX) = 1 and the PMF telescopes to 1."""
    p_plays = sorted(_clamp_yards(y) for y in player_plays)
    l_plays = sorted(_clamp_yards(y) for y in league_plays)
    pmf: dict[int, float] = {}
    prev = 0.0
    for x in range(Y_MIN, Y_MAX + 1):
        le = bisect.bisect_right(l_plays, x) / len(l_plays)
        pe = bisect.bisect_right(p_plays, x) / len(p_plays)
        f = (len(p_plays) * pe + PLAY_SHRINK_PLAYS * le) \
            / (len(p_plays) + PLAY_SHRINK_PLAYS)
        cdf = math.fsum(p * f ** n for n, p in count_pmf.items())
        pmf[x] = max(cdf - prev, 0.0)
        prev = cdf
    total = math.fsum(pmf.values())
    return {k: v / total for k, v in pmf.items()}


def _shrunk_yardage_pmf(player_obs: Sequence[int],
                        league_obs: Sequence[int],
                        shrink: float) -> dict[int, float]:
    """Shrunk empirical PMF over the yardage grid (first reception):
    (observed + shrink * league_pmf) / (n + shrink), tails folded."""
    n = len(player_obs)
    if n == 0 or not league_obs:
        raise NflLongestPlaysError("LONGEST_FIRST_RECEPTION_POOL_EMPTY")
    obs: dict[int, int] = {}
    for y in player_obs:
        k = _clamp_yards(y)
        obs[k] = obs.get(k, 0) + 1
    lg: dict[int, int] = {}
    for y in league_obs:
        k = _clamp_yards(y)
        lg[k] = lg.get(k, 0) + 1
    nl = len(league_obs)
    pmf = {x: (obs.get(x, 0) + shrink * (lg.get(x, 0) / nl))
           / (n + shrink)
           for x in range(Y_MIN, Y_MAX + 1)}
    total = math.fsum(pmf.values())
    return {k: v / total for k, v in pmf.items()}


def _mean(pmf: Mapping[int, float]) -> float:
    return math.fsum(k * v for k, v in pmf.items())


def prob_over_under(pmf: Mapping[int, float],
                    line: float) -> tuple[float, float, float]:
    """(p_over, p_push, p_under) for an O/U line on the yardage."""
    over = math.fsum(v for k, v in pmf.items() if k > line)
    push = math.fsum(v for k, v in pmf.items() if k == line)
    under = math.fsum(v for k, v in pmf.items() if k < line)
    return over, push, under



def _yard(v: Any) -> int:
    """Measured integral yardage or a named refusal (no coercion)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise NflLongestPlaysError(f"LONGEST_HISTORY_YARDS_INVALID:{v!r}")
    if not math.isfinite(v) or v != int(v):
        raise NflLongestPlaysError(f"LONGEST_HISTORY_YARDS_INVALID:{v!r}")
    return int(v)


def _validated_row(r: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed row check: identity, game id, tz-aware kickoff,
    non-empty measured plays, consistent first reception."""
    pid = str(r.get("player_id") or "").strip()
    if not pid:
        raise NflLongestPlaysError("LONGEST_HISTORY_PLAYER_ID_MISSING")
    gid = str(r.get("game_id") or "").strip()
    if not gid:
        raise NflLongestPlaysError("LONGEST_HISTORY_GAME_ID_MISSING")
    plays = [_yard(y) for y in (r.get("play_yards") or ())]
    if not plays:
        raise NflLongestPlaysError(
            f"LONGEST_HISTORY_PLAYS_EMPTY:LONGEST_NO_PLAYS:{pid}:{gid}")
    fr = r.get("first_reception_yards")
    if fr is not None:
        fr = _yard(fr)
        if fr not in plays:
            raise NflLongestPlaysError(
                f"LONGEST_HISTORY_FIRST_RECEPTION_INCONSISTENT:{pid}:{gid}")
    return {**r, "player_id": pid, "game_id": gid,
            "play_yards": plays, "first_reception_yards": fr}


# ---------------------------------------------------------------------------
# Estimator
# ---------------------------------------------------------------------------

def estimate_longest_plays(records: Iterable[Mapping[str, Any]], *,
                           player_id: str, role: str,
                           kickoff: datetime) -> dict[str, Any]:
    """Research probability distributions for one player-game.

    ``records`` are per-(player, role, game) play records for the
    WHOLE pool (the league aggregates are computed from it):
    {player_id, role, game_id, kickoff (datetime), play_yards:
    [int, ...], first_reception_yards: int | None}. Only rows with
    kickoff strictly before ``kickoff`` are used (strict PIT).
    Distributions condition on the player recording >= 1 opportunity
    of the role (module docstring).
    """
    pid = str(player_id or "").strip()
    if not pid:
        raise NflLongestPlaysError("LONGEST_IDENTITY_REQUIRED")
    role = str(role or "").strip().upper()
    if role not in ROLES:
        raise NflLongestPlaysError(f"LONGEST_ROLE_INVALID:{role}")
    if kickoff.tzinfo is None:
        raise NflLongestPlaysError("LONGEST_KICKOFF_TIMEZONE_REQUIRED")

    player_rows: list[Mapping[str, Any]] = []
    league_counts: list[int] = []
    league_plays: list[int] = []
    league_first_rec: list[int] = []
    seen: set[tuple[str, str]] = set()
    for r in records:
        rk = r.get("kickoff")
        if rk is None:
            raise NflLongestPlaysError("LONGEST_HISTORY_KICKOFF_MISSING")
        if str(r.get("role") or "").strip().upper() != role:
            continue
        if getattr(rk, "tzinfo", None) is None:
            raise NflLongestPlaysError(
                "LONGEST_HISTORY_KICKOFF_TIMEZONE_REQUIRED")
        if not rk < kickoff:
            continue
        r = _validated_row(r)
        key = (r["player_id"], r["game_id"])
        if key in seen:
            raise NflLongestPlaysError(
                f"LONGEST_HISTORY_DUPLICATE_GAME:{key[0]}:{key[1]}")
        seen.add(key)
        plays = r["play_yards"]
        league_counts.append(len(plays))
        league_plays.extend(plays)
        fr = r.get("first_reception_yards")
        if fr is not None:
            league_first_rec.append(fr)
        if r["player_id"] == pid:
            player_rows.append(r)
    player_rows.sort(key=lambda r: r["kickoff"])
    player_rows = player_rows[-TRAILING_GAMES_K:]
    if len(player_rows) < MIN_GAMES:
        raise NflLongestPlaysError(
            f"LONGEST_HISTORY_INSUFFICIENT:{pid}:n={len(player_rows)}")

    player_counts = [len(r.get("play_yards") or ()) for r in player_rows]
    player_plays = [int(y) for r in player_rows
                    for y in (r.get("play_yards") or ())]
    if not player_plays:
        raise NflLongestPlaysError(f"LONGEST_NO_PLAYS:{pid}")
    if not league_plays:
        raise NflLongestPlaysError("LONGEST_LEAGUE_POOL_EMPTY")

    count_pmf = _shrunk_count_pmf(player_counts, league_counts)
    longest_pmf = _max_pmf(count_pmf, player_plays, league_plays)

    # Diagnostic: the trailing raw longest-play distribution
    # (unshrunk), the baseline any challenger must beat.
    raw: dict[int, float] = {}
    for r in player_rows:
        plays = [int(y) for y in (r.get("play_yards") or ())]
        if plays:
            m = _clamp_yards(max(plays))
            raw[m] = raw.get(m, 0.0) + 1.0 / len(player_rows)

    out: dict[str, Any] = {
        "status": "RESEARCH_ONLY",
        "engine": ENGINE_ID,
        "engine_version": ENGINE_VERSION,
        "validation_status": "NOT_VALIDATED",
        "governance": "NOT_ADMITTED_CANONICAL_PATH_GOVERNANCE_NO_ENGINE",
        "player_id": pid,
        "role": role,
        "market": ROLE_MARKET[role],
        "conditioning": "AT_LEAST_ONE_OPPORTUNITY_RECORDED",
        "as_of_kickoff": kickoff.isoformat(),
        "games_used": len(player_rows),
        "plays_used": len(player_plays),
        "opportunities_per_game": {
            "mean": _mean(count_pmf), "pmf": count_pmf},
        "longest": {"mean": _mean(longest_pmf), "pmf": longest_pmf},
        "trailing_raw_longest_pmf_diagnostic": raw,
    }

    if role == "RECEIVER":
        first_obs = [int(r["first_reception_yards"]) for r in player_rows
                     if r.get("first_reception_yards") is not None]
        if not first_obs:
            raise NflLongestPlaysError(
                f"LONGEST_NO_FIRST_RECEPTION_OBSERVATIONS:{pid}")
        fr_pmf = _shrunk_yardage_pmf(first_obs, league_first_rec,
                                     FIRST_REC_SHRINK)
        out["first_reception"] = {
            "market": "FIRST_RECEPTION",
            "mean": _mean(fr_pmf),
            "pmf": fr_pmf,
            "observations": len(first_obs),
            "conditioning": "AT_LEAST_ONE_RECEPTION_RECORDED",
        }
    return out


# ---------------------------------------------------------------------------
# nflverse play-by-play history source
# ---------------------------------------------------------------------------

PBP_COLUMNS = (
    "game_id", "play_id", "posteam",
    "passer_player_id", "receiver_player_id", "rusher_player_id",
    "pass_attempt", "complete_pass", "rush_attempt", "yards_gained",
)
GAMES_COLUMNS = ("game_id", "gameday", "gametime")


def build_longest_play_games(pbp: Any, games: Any) -> list[dict[str, Any]]:
    """Per-(game, player, role) play records from nflverse frames.

    ``pbp`` / ``games`` are pandas DataFrames with at least
    PBP_COLUMNS / GAMES_COLUMNS. Kickoff = gameday + gametime (ET)
    converted to UTC, mirroring the sibling kicking source's PIT
    basis. Plays are taken in (game_id, play_id) order, so a
    receiver's first reception is the first completed pass to him
    in play order. Only plays define a record: a player-game with
    zero opportunities of a role emits no record for that role
    (zero-opportunity games are not identifiable from pbp alone).
    A missing/non-finite yards_gained on a recorded opportunity
    refuses (LONGEST_PBP_YARDS_MISSING); it is never coerced to 0.
    """
    import pandas as pd  # local: core above is dependency-light

    missing = [c for c in PBP_COLUMNS if c not in pbp.columns]
    if missing:
        raise NflLongestPlaysError(f"LONGEST_PBP_SCHEMA_MISSING:{missing}")
    missing = [c for c in GAMES_COLUMNS if c not in games.columns]
    if missing:
        raise NflLongestPlaysError(
            f"LONGEST_GAMES_SCHEMA_MISSING:{missing}")

    g = games.copy()
    g["kickoff"] = pd.to_datetime(
        g["gameday"].astype(str) + " " + g["gametime"].astype(str),
        errors="coerce", format="mixed")
    g = g.dropna(subset=["kickoff"])
    g["kickoff"] = g["kickoff"].dt.tz_localize(
        "America/New_York").dt.tz_convert("UTC")
    kickoff_by_game = dict(zip(g["game_id"].astype(str), g["kickoff"]))

    p = pbp.copy()
    for col in ("pass_attempt", "complete_pass", "rush_attempt",
                "yards_gained"):
        p[col] = pd.to_numeric(p[col], errors="coerce")
    p = p.sort_values(["game_id", "play_id"], kind="stable")

    out: dict[tuple[str, str, str], dict[str, Any]] = {}

    def _rec(gid: str, player: str, team: str,
             role: str) -> dict[str, Any] | None:
        ko = kickoff_by_game.get(gid)
        if ko is None:
            return None
        key = (gid, player, role)
        return out.setdefault(key, {
            "game_id": gid, "kickoff": ko.to_pydatetime(),
            "player_id": player, "team": team,
            "role": role, "play_yards": [],
            "first_reception_yards": None,
        })

    for row in p.itertuples(index=False):
        gid = str(row.game_id)
        yards = row.yards_gained
        is_opp = (int(row.pass_attempt or 0) == 1
                  and int(row.complete_pass or 0) == 1) \
            or int(row.rush_attempt or 0) == 1
        if is_opp and not (yards == yards and math.isfinite(yards)):
            raise NflLongestPlaysError(
                f"LONGEST_PBP_YARDS_MISSING:{gid}:{row.play_id}")
        yards = int(yards) if is_opp else 0
        team = str(row.posteam)
        if int(row.pass_attempt or 0) == 1 \
                and int(row.complete_pass or 0) == 1:
            passer = row.passer_player_id
            if passer == passer and str(passer).strip():
                rec = _rec(gid, str(passer), team, "PASSER")
                if rec is not None:
                    rec["play_yards"].append(yards)
            receiver = row.receiver_player_id
            if receiver == receiver and str(receiver).strip():
                rec = _rec(gid, str(receiver), team, "RECEIVER")
                if rec is not None:
                    rec["play_yards"].append(yards)
                    if rec["first_reception_yards"] is None:
                        rec["first_reception_yards"] = yards
        if int(row.rush_attempt or 0) == 1:
            rusher = row.rusher_player_id
            if rusher == rusher and str(rusher).strip():
                rec = _rec(gid, str(rusher), team, "RUSHER")
                if rec is not None:
                    rec["play_yards"].append(yards)
    return sorted(out.values(), key=lambda r: r["kickoff"])


def _fetch_csv(url: str, *, gzip_encoded: bool = False) -> Any:
    import pandas as pd

    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=120) as resp:  # noqa: S310 (declared source)
        raw = resp.read()
    if gzip_encoded:
        raw = gzip.decompress(raw)
    return pd.read_csv(io.BytesIO(raw), low_memory=False)


class NflLongestPlaysPublicSource:
    """Free nflverse source for longest-play history (no API keys).

    Returns the whole role pool (the estimator's league aggregates
    are computed from the pool), unlike the kicking source's
    per-kicker filter.
    """

    def __init__(self, fetcher: Callable[[str, bool], Any] | None = None):
        self._fetcher = fetcher or (
            lambda url, gz: _fetch_csv(url, gzip_encoded=gz))

    def records_for(self, seasons: Sequence[int], *,
                    role: str) -> list[dict[str, Any]]:
        role = str(role or "").strip().upper()
        if role not in ROLES:
            raise NflLongestPlaysError(f"LONGEST_ROLE_INVALID:{role}")
        games = self._fetcher(SOURCE_URLS["games"], False)
        records: list[dict[str, Any]] = []
        for season in seasons:
            pbp = self._fetcher(
                SOURCE_URLS["pbp"].format(season=season), True)
            records.extend(build_longest_play_games(pbp, games))
        return [r for r in records if r["role"] == role]
