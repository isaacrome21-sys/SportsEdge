"""NBA player-prop empirical engine — the Oct 17/18 calibration construction.

This module IS the construction scored by the backtest programs, not a
new model:

* Oct 17 program (B5/B6/B7), spec
  ``backtest_program_20261017/lanes/nba/specs/nba_props_calibration_spec_v1.md``
  (SHA-256 47dc1314b608d8a1ae64f869ca8ff48d6add35fcc8ffd2c6ff292d515e1710c2,
  hashed before scoring): player Points / Rebounds / Assists —
  CALIBRATION BEATS_BASELINE vs both league climatology baselines,
  n=16,818 player-games, 2024-25.
* Oct 18 extension (B8), spec
  ``backtest_everything_20261018/specs/SPEC_NBA_EXTENSION_V1.md``
  (SHA-256 d5f794bd470f06a7d5094137415e8f210e5c3372fee168d4d0fce27e26822938):
  PRA (per-game points+rebounds+assists, modeled as the summed game's
  own distribution — never an independence assumption across the three
  stats) — CALIBRATION BEATS_BASELINE, same snapshot, same population.

Construction (verbatim from the specs): the predictive distribution
for a player's stat in his next game is the mixture

    weight n/(n+5)  on the player's empirical distribution over his
                    prior same-season games (n = number of prior
                    games, minutes > 0), and
    weight 5/(n+5)  on the per-position-group (G/F/C) league expanding
                    empirical distribution (B1),

where every pool contains only games with gameDate strictly before
the target date (strict point-in-time at date granularity). If the
position pool holds fewer than 30 games at the target date, B1 falls
back to the league-overall expanding distribution (B2), exactly as
specced. Rows with minutes == 0 are did-not-play and are excluded
everywhere. A player with no verified position group is outside the
construction's universe and cannot be priced.

Sufficiency gate: the program's point-in-time minimum-history
requirement — at least 10 prior same-season games (minutes > 0)
strictly before the target date — is the engine's gate. The program's
scored population additionally required >= 20 total games in the
season; that is a scoring-population criterion that conditions on the
future and therefore cannot gate live pricing point-in-time, so it is
NOT applied here (the first player-games the program scored had
exactly 10 priors). Below 10 priors the engine refuses fail-closed.

Stated limitation, carried in every priced result's metadata: there
is NO participation / minutes / availability feed wired to this
engine. Probabilities are over the player's realized per-game
outcomes (which embed his historical playing time); whether he plays
tonight, and how much, is not modeled.

Calibration is not validation: the construction beat climatology
baselines on realized outcomes. No market leg exists (no historical
DK prop lines), and the families are REGISTERED_RESEARCH_ONLY /
NOT_VALIDATED. This module grants no PLAY, staking or official
authority.

The CRPS implementation below is the programs' exact form
(CRPS(F, y) = E|X-y| - 1/2 * E|X-X'| with the mixture's expectations
expanded linearly over its two components, cross term included), so
the parity reproduction in
``research/nba_props_forward_20261020/parity_reproduction.py`` scores
the frozen Oct 17 snapshot with this module's own code.
"""
from __future__ import annotations

import bisect
import math
from datetime import date, datetime

ENGINE_ID = "NBA_PROP_EMPIRICAL_V1"
CONSTRUCTION_SPEC_SHA256 = (
    "47dc1314b608d8a1ae64f869ca8ff48d6add35fcc8ffd2c6ff292d515e1710c2")
EXTENSION_SPEC_SHA256 = (
    "d5f794bd470f06a7d5094137415e8f210e5c3372fee168d4d0fce27e26822938")
K_SMOOTH = 5.0
MIN_PRIOR_GAMES = 10
B1_MIN_POOL = 30
STATS = ("points", "rebounds", "assists", "pra")
POSITION_GROUPS = ("Guard", "Forward", "Center")
_GROUP_BY_FIRST_CHAR = {"G": "Guard", "F": "Forward", "C": "Center"}

# Named fail-closed refusals.
REFUSAL_STAT_UNSUPPORTED = "NBA_PROP_STAT_UNSUPPORTED"
REFUSAL_PLAYER_NOT_IN_STORE = "NBA_PROP_PLAYER_NOT_IN_STORE"
REFUSAL_POSITION_UNVERIFIED = "NBA_PROP_POSITION_GROUP_UNVERIFIED"
REFUSAL_INSUFFICIENT_PRIORS = "NBA_PROP_INSUFFICIENT_PRIOR_GAMES"
REFUSAL_POOL_UNAVAILABLE = "NBA_PROP_POOL_UNAVAILABLE"
REFUSAL_LINE_INVALID = "NBA_PROP_LINE_INVALID"


def position_group(raw) -> str | None:
    """Position group from a roster abbreviation or full name.

    Mirrors the programs: group = first character of the roster
    position abbreviation (``G-F`` -> Guard, ``F-C`` -> Forward); the
    full group names are also accepted. Anything else is unverified.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    if text in POSITION_GROUPS:
        return text
    return _GROUP_BY_FIRST_CHAR.get(text[:1].upper())


def stat_value(record, stat: str) -> float:
    """One game's value of a stat; PRA is the same game's own sum."""
    if stat == "pra":
        return (float(record["points"]) + float(record["rebounds"])
                + float(record["assists"]))
    return float(record[stat])


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(
                value.strip().replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value.strip()[:10])
            except ValueError:
                return None
    return None


# ---------- exact CRPS pieces (the programs' implementation) ---------------

def _sorted_prefix(vals):
    svals = sorted(float(v) for v in vals)
    prefix = [0.0]
    for v in svals:
        prefix.append(prefix[-1] + v)
    return svals, prefix


def pool_ex_abs(sorted_vals, prefix, y: float):
    """E|X - y| for the empirical distribution of sorted_vals."""
    m = len(sorted_vals)
    if m == 0:
        return None
    k = bisect.bisect_right(sorted_vals, y)  # number of vals <= y
    left_sum = prefix[k]
    total = prefix[m]
    return (y * k - left_sum + (total - left_sum) - y * (m - k)) / m


def pool_exx(sorted_vals, prefix):
    """E|X - X'| for the empirical distribution of sorted_vals."""
    m = len(sorted_vals)
    if m == 0:
        return None
    total = 0.0
    for i, x in enumerate(sorted_vals):
        total += (x * i - prefix[i]
                  + (prefix[m] - prefix[i + 1]) - x * (m - i - 1))
    return total / (m * m)


def empirical_crps(sorted_vals, prefix, y: float):
    """CRPS of a single empirical distribution against realized y."""
    exx = pool_exx(sorted_vals, prefix)
    if exx is None:
        return None
    return pool_ex_abs(sorted_vals, prefix, y) - 0.5 * exx


class MixtureDistribution:
    """The specced mixture: player empirical smoothed k=5 toward a pool.

    ``pool_values`` is the B1 position-group pool, or the B2 league
    pool when the caller applied the specced fallback. All values are
    prior games only (strictly before the target date) — PIT filtering
    is the caller's contract and is enforced by ``GameLogStore``.
    """

    def __init__(self, player_values, pool_values, *, k: float = K_SMOOTH):
        self.player_values = [float(v) for v in player_values]
        self.pool_values = [float(v) for v in pool_values]
        n = len(self.player_values)
        self.weight_player = n / (n + k)
        self.weight_pool = k / (n + k)
        self._p_sorted, self._p_prefix = _sorted_prefix(self.player_values)
        self._b_sorted, self._b_prefix = _sorted_prefix(self.pool_values)
        self._b_exx = pool_exx(self._b_sorted, self._b_prefix)

    @classmethod
    def from_precomputed(cls, player_values, sorted_pool, pool_prefix,
                         pool_exx_value, *, k: float = K_SMOOTH):
        """Build with a pool's sorted/prefix/E|X-X'| pieces already
        computed (the programs' per-date pool snapshots), so scoring a
        full season does not re-sort the pool per player-game."""
        obj = cls.__new__(cls)
        obj.player_values = [float(v) for v in player_values]
        obj.pool_values = list(sorted_pool)
        n = len(obj.player_values)
        obj.weight_player = n / (n + k)
        obj.weight_pool = k / (n + k)
        obj._p_sorted, obj._p_prefix = _sorted_prefix(obj.player_values)
        obj._b_sorted, obj._b_prefix = sorted_pool, pool_prefix
        obj._b_exx = pool_exx_value
        return obj

    # -- exceedance probabilities (the pricing read of the mixture) --

    @staticmethod
    def _frac_gt(sorted_vals, line: float) -> float:
        m = len(sorted_vals)
        if m == 0:
            return 0.0
        return (m - bisect.bisect_right(sorted_vals, line)) / m

    @staticmethod
    def _frac_eq(sorted_vals, line: float) -> float:
        m = len(sorted_vals)
        if m == 0:
            return 0.0
        return (bisect.bisect_right(sorted_vals, line)
                - bisect.bisect_left(sorted_vals, line)) / m

    def prob_over(self, line: float) -> float:
        return (self.weight_player * self._frac_gt(self._p_sorted, line)
                + self.weight_pool * self._frac_gt(self._b_sorted, line))

    def prob_push(self, line: float) -> float:
        return (self.weight_player * self._frac_eq(self._p_sorted, line)
                + self.weight_pool * self._frac_eq(self._b_sorted, line))

    def prob_under(self, line: float) -> float:
        return 1.0 - self.prob_over(line) - self.prob_push(line)

    def mean(self) -> float:
        mp = math.fsum(self.player_values) / len(self.player_values)
        mb = math.fsum(self.pool_values) / len(self.pool_values)
        return self.weight_player * mp + self.weight_pool * mb

    # -- exact CRPS (the programs' scoring form; parity + future scoring) --

    def crps(self, y: float) -> float:
        a, b = self.weight_player, self.weight_pool
        pv = self.player_values
        e_emp_y = math.fsum(abs(v - y) for v in pv) / len(pv)
        e_b1_y = pool_ex_abs(self._b_sorted, self._b_prefix, y)
        # E|X-X'| of the player's empirical via the same sorted-prefix
        # form the programs use for pools (identical quantity to the
        # pairwise mean; the parity script's brute-force unit check
        # pins the two forms together).
        e_emp_emp = pool_exx(self._p_sorted, self._p_prefix)
        e_cross = (math.fsum(
            pool_ex_abs(self._b_sorted, self._b_prefix, float(e))
            for e in pv) / len(pv))
        ex_y = a * e_emp_y + b * e_b1_y
        exx = a * a * e_emp_emp + 2 * a * b * e_cross + b * b * self._b_exx
        return ex_y - 0.5 * exx


# ---------- game-log store ---------------------------------------------------

class GameLogStore:
    """One season of normalized player game logs, PIT-queryable.

    Records are mappings with keys: ``player_id``, ``player_name``,
    ``position`` (abbreviation or group name), ``game_date`` (date or
    ISO string), ``game_id``, ``minutes``, ``points``, ``rebounds``,
    ``assists``. Mirrors the programs' universe rules: a player with
    no verified position group is excluded from the store and from all
    pools (counted); minutes == 0 rows are did-not-play and excluded
    everywhere (counted); records without a parseable game date cannot
    be point-in-time ordered and are excluded (counted).
    """

    def __init__(self, records, *, season_label: str | None = None):
        self.season_label = season_label
        self.counters = {"records_in": 0, "records_kept": 0,
                         "excluded_no_position": 0,
                         "excluded_dnp_minutes0": 0,
                         "excluded_no_date": 0,
                         "excluded_invalid": 0}
        self._players = {}   # player_id -> {"name", "group", "games": [...]}
        self._league = []    # all kept records (played games only)
        for rec in records or []:
            self.counters["records_in"] += 1
            try:
                pid = str(rec.get("player_id") or "").strip()
                group = position_group(rec.get("position"))
                gdate = _as_date(rec.get("game_date"))
                minutes = float(rec.get("minutes"))
                values = {s: float(rec[s]) for s in
                          ("points", "rebounds", "assists")}
            except (TypeError, ValueError, KeyError, AttributeError):
                self.counters["excluded_invalid"] += 1
                continue
            if not pid:
                self.counters["excluded_invalid"] += 1
                continue
            if group is None:
                self.counters["excluded_no_position"] += 1
                continue
            if gdate is None:
                self.counters["excluded_no_date"] += 1
                continue
            if minutes == 0.0:
                self.counters["excluded_dnp_minutes0"] += 1
                continue
            game = {"player_id": pid, "game_date": gdate,
                    "game_id": str(rec.get("game_id") or ""),
                    "minutes": minutes, **values}
            player = self._players.setdefault(
                pid, {"name": str(rec.get("player_name") or "").strip(),
                      "group": group, "games": []})
            player["games"].append(game)
            self._league.append(game)
            self.counters["records_kept"] += 1
        for player in self._players.values():
            player["games"].sort(key=lambda g: (g["game_date"], g["game_id"]))
        self._league.sort(key=lambda g: (g["game_date"], g["game_id"]))

    # -- identity ------------------------------------------------------

    def player_ids(self):
        return sorted(self._players)

    def player_name(self, player_id):
        player = self._players.get(str(player_id))
        return player["name"] if player else None

    def position_group_of(self, player_id):
        player = self._players.get(str(player_id))
        return player["group"] if player else None

    def player_total_games(self, player_id) -> int:
        player = self._players.get(str(player_id))
        return len(player["games"]) if player else 0

    # -- PIT slices (strictly before the target date) -------------------

    def player_prior_values(self, player_id, stat: str, target_date):
        player = self._players.get(str(player_id))
        if player is None:
            return []
        return [stat_value(g, stat) for g in player["games"]
                if g["game_date"] < target_date]

    def pool_values(self, group: str, stat: str, target_date):
        return [stat_value(g, stat) for g in self._league
                if g["game_date"] < target_date
                and self._players[g["player_id"]]["group"] == group]

    def league_values(self, stat: str, target_date):
        return [stat_value(g, stat) for g in self._league
                if g["game_date"] < target_date]

    # -- the pricer ------------------------------------------------------

    def price(self, player_id, stat: str, line, target_date) -> dict:
        """Price one prop from the store, or refuse fail-closed by name.

        ``target_date`` is the target game's calendar date (a
        ``datetime.date``); only games strictly before it enter any
        distribution. Returns a dict: priced results carry
        ``status == "PRICED"`` with probabilities and audit metadata;
        refusals carry ``status == "REFUSED"`` and a named ``reason``.
        """
        base = {"engine_id": ENGINE_ID, "stat": stat,
                "history_basis": "PIT_GAME_LOGS_ONLY",
                "participation_feed": "NOT_WIRED",
                "limitation": ("No participation/minutes/availability feed "
                               "is wired: probabilities are over the "
                               "player's realized per-game outcomes; "
                               "tonight's playing time is not modeled.")}
        if stat not in STATS:
            return {**base, "status": "REFUSED",
                    "reason": REFUSAL_STAT_UNSUPPORTED}
        try:
            line = float(line)
        except (TypeError, ValueError):
            return {**base, "status": "REFUSED",
                    "reason": REFUSAL_LINE_INVALID}
        if not math.isfinite(line):
            return {**base, "status": "REFUSED",
                    "reason": REFUSAL_LINE_INVALID}
        target = _as_date(target_date)
        if target is None:
            return {**base, "status": "REFUSED",
                    "reason": REFUSAL_LINE_INVALID,
                    "detail": "TARGET_DATE_UNPARSEABLE"}
        player = self._players.get(str(player_id))
        if player is None:
            return {**base, "status": "REFUSED",
                    "reason": REFUSAL_PLAYER_NOT_IN_STORE}
        group = player["group"]
        priors = self.player_prior_values(player_id, stat, target)
        n_prior = len(priors)
        if n_prior < MIN_PRIOR_GAMES:
            return {**base, "status": "REFUSED",
                    "reason": REFUSAL_INSUFFICIENT_PRIORS,
                    "n_prior": n_prior,
                    "min_prior_games": MIN_PRIOR_GAMES}
        pool = self.pool_values(group, stat, target)
        pool_source = "POSITION_GROUP"
        if len(pool) < B1_MIN_POOL:
            pool = self.league_values(stat, target)
            pool_source = "LEAGUE_FALLBACK"
        if not pool:
            return {**base, "status": "REFUSED",
                    "reason": REFUSAL_POOL_UNAVAILABLE,
                    "n_prior": n_prior}
        dist = MixtureDistribution(priors, pool)
        p_over = dist.prob_over(line)
        p_push = dist.prob_push(line)
        p_under = dist.prob_under(line)
        return {**base, "status": "PRICED",
                "player_id": str(player_id),
                "player_name": player["name"],
                "position_group": group,
                "line": line,
                "target_date": target.isoformat(),
                "n_prior": n_prior,
                "pool_n": len(pool),
                "pool_source": pool_source,
                "b1_fallback_to_b2": pool_source == "LEAGUE_FALLBACK",
                "weight_player": dist.weight_player,
                "weight_pool": dist.weight_pool,
                "k_smooth": K_SMOOTH,
                "model_mean": dist.mean(),
                "p_over": p_over, "p_push": p_push, "p_under": p_under,
                "sufficiency_met": True,
                "construction": {
                    "spec_sha256": CONSTRUCTION_SPEC_SHA256,
                    "extension_spec_sha256": EXTENSION_SPEC_SHA256,
                    "kind": "CALIBRATION_ONLY_NO_MARKET_LEG",
                    "validation_status": "NOT_VALIDATED",
                }}


# ---------- sportsdataverse store loader (the verified pull shape) ----------

def records_from_boxscore_rows(rows, game_dates, positions):
    """Normalize pull-shaped box-score rows into store records.

    ``rows`` are mappings in the ``scripts/pull_nba_results.py`` output
    shape (PLAYER_ID / PLAYER_NAME / GAME_ID / MIN / PTS / REB / AST).
    That asset carries no game date and no position, so both join from
    caller-supplied maps: ``game_dates`` {GAME_ID: ISO date} and
    ``positions`` {PLAYER_ID: roster position abbreviation or group}.
    Rows whose GAME_ID has no date cannot be point-in-time ordered and
    are dropped (counted by the store as excluded_no_date); players
    without a position are dropped by the store's universe rule. The
    caller's pipeline owns regular-season filtering of the asset.
    """
    game_dates = game_dates or {}
    positions = positions or {}
    out = []
    for row in rows or []:
        gid = str(row.get("GAME_ID") or "").strip()
        pid = str(row.get("PLAYER_ID") or "").strip()
        out.append({
            "player_id": pid,
            "player_name": str(row.get("PLAYER_NAME") or "").strip(),
            "position": positions.get(pid),
            "game_date": game_dates.get(gid),
            "game_id": gid,
            "minutes": row.get("MIN"),
            "points": row.get("PTS"),
            "rebounds": row.get("REB"),
            "assists": row.get("AST"),
        })
    return out
