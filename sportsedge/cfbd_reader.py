"""Runner-side reader for the CFBD advanced-stats archive.

The phone runner NEVER calls the CFBD API and NEVER reads an API key. It
reads the data-branch archive written by scripts/archive_cfbd_advanced.py
(Actions-side, keyed) from a local checkout:

  {data_dir}/archive/cfb-advanced/seasons/{year}/season_advanced.json
  {data_dir}/archive/cfb-advanced/weeks/{year}/week_{NN}.json

Raw CFBD stats are performance data and are legitimate MODEL inputs, but
per Isaac's standing bar they are harness-gated like everything else: no
factor derived from this archive enters production pricing until the
backtest harness proves chronological out-of-sample improvement vs both
the existing model and the market baseline.

Opponent adjustment (our own — CFBD's opponent-adjusted metrics are a
paid-tier product and are NEVER used):
  Two-way fixed-effects least-squares model over completed FBS-vs-FBS
  games (garbage time excluded at pull time). For each team-game:
      off_epa[i,g]        = O[i] + D[opp(g)] + noise
      def_epa_allowed[i,g] = D[i] + O[opp(g)] + noise
  where O[i] is team i's offensive strength and D[i] its defensive
  weakness (positive D = allows more EPA). Solved with numpy lstsq
  (deterministic). The model has one gauge degree of freedom (add c to
  all O, subtract c from all D); it is pinned so the mean adjusted
  margin equals the mean raw margin — schedule adjustment is zero-sum
  by construction: one team's schedule advantage is another's
  disadvantage. Adjusted EPA margin for team i = O[i] - D[i].
  (An earlier Jacobi-iteration formulation was replaced: the iteration
  matrix has spectral radius exactly 1 — a row-stochastic opponent
  graph — so it oscillates instead of converging. Least squares is the
  correct solver for this system.)
  Chronology: the adjustment is computed strictly on games completed before
  the target week (as-of). The reader computes it on demand from the
  archived week files; results are deterministic given the archive.
  FCS opponents: games vs non-FBS opponents are excluded from the
  system (they are not in the FBS graph) and counted in the coverage
  audit. Home-field is NOT removed inside the adjustment — HFA is a
  separate factor constant, itself harness-gated.

No network. No secrets. Importing this module performs no I/O.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SCHEMA_VERSION = "CFBD_ARCHIVE_V1"
ARCHIVE_SUBDIR = Path("archive") / "cfb-advanced"


class CFBDReaderError(ValueError):
    """Fail-closed read error."""


@dataclass
class AdjustmentResult:
    """Per-team schedule-adjusted EPA margins, as-of a given week."""
    year: int
    through_week: int
    teams: dict = field(default_factory=dict)  # team -> metrics dict
    coverage: dict = field(default_factory=dict)


def _num(value) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def _norm_team(name) -> str:
    return " ".join(str(name or "").split())


def _epa_of(row: dict, unit: str) -> float | None:
    """Raw EPA/play for the "offense"/"defense" unit of a team-game row.

    Accepts the field spellings CFBD has used across API versions
    (epaPerPlay / epa / ppa); the first present finite value wins. Any
    row without a usable value is skipped upstream (never zero-filled).
    """
    unit_block = row.get(unit)
    if not isinstance(unit_block, dict):
        return None
    for key in ("epaPerPlay", "epa", "ppa"):
        val = _num(unit_block.get(key))
        if val is not None:
            return val
    return None


def _connected_components(teams: list[str],
                          games: list[dict]) -> list[set[str]]:
    """Connected components of the team game-graph (union-find).

    Margins are only comparable within a component; a full season is one
    component, early-season samples may not be.
    """
    parent = {t: t for t in teams}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for g in games:
        rh, ra = find(g["home"]), find(g["away"])
        if rh != ra:
            parent[rh] = ra
    groups: dict[str, set[str]] = {}
    for t in teams:
        groups.setdefault(find(t), set()).add(t)
    return list(groups.values())


class CFBDArchiveReader:
    """Reads the CFBD archive from a data-branch checkout directory."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / ARCHIVE_SUBDIR

    # -- raw reads ------------------------------------------------------
    def _read_json(self, path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CFBDReaderError("CFBD_ARCHIVE_UNREADABLE:%s" % path) from exc
        if not isinstance(payload, dict):
            raise CFBDReaderError("CFBD_ARCHIVE_MALFORMED:%s" % path)
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise CFBDReaderError(
                "CFBD_ARCHIVE_SCHEMA_UNKNOWN:%s:%r"
                % (path, payload.get("schema_version")))
        if payload.get("status") != "ARCHIVED":
            raise CFBDReaderError("CFBD_ARCHIVE_NOT_ARCHIVED:%s" % path)
        return payload

    def load_season_advanced(self, year: int) -> list[dict]:
        """Raw per-team season advanced stats (EPA, success, havoc, PPA)."""
        payload = self._read_json(
            self.root / "seasons" / str(year) / "season_advanced.json")
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise CFBDReaderError(
                "CFBD_ARCHIVE_ROWS_MALFORMED:season:%d" % year)
        return rows

    def load_week(self, year: int, week: int) -> dict:
        """Raw per-game advanced stats + PPA for one week."""
        return self._read_json(
            self.root / "weeks" / str(year) / ("week_%02d.json" % week))

    def archived_weeks(self, year: int) -> list[int]:
        weeks_dir = self.root / "weeks" / str(year)
        if not weeks_dir.is_dir():
            return []
        weeks = []
        for path in weeks_dir.glob("week_*.json"):
            try:
                week = int(path.stem.split("_")[1])
            except (IndexError, ValueError):
                continue
            try:
                self._read_json(path)
            except CFBDReaderError:
                continue
            weeks.append(week)
        return sorted(weeks)

    def fbs_teams(self, year: int) -> set[str]:
        """Team names present in the season file (FBS graph membership)."""
        return {_norm_team(r.get("team") or r.get("school"))
                for r in self.load_season_advanced(year)
                if r.get("team") or r.get("school")}

    # -- game pairing ---------------------------------------------------
    def _pair_games(self, year: int, week: int, payload: dict,
                   fbs: set[str]) -> tuple[list[dict], dict]:
        """Pair the two team-rows of each game into one game record.

        Returns (games, skipped) where each game is a dict with home/away
        team names, their raw offensive EPA/play and defensive EPA/play
        allowed. Rows that cannot be paired or lack a usable EPA value are
        skipped and counted — never zero-filled.
        """
        rows = payload.get("game_advanced") or []
        by_game: dict[object, list[dict]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            gid = row.get("id") if row.get("id") is not None else row.get("gameId")
            by_game.setdefault(gid, []).append(row)
        games: list[dict] = []
        skipped = {"unpaired_rows": 0, "non_fbs_opponent": 0, "missing_epa": 0}
        for gid, team_rows in by_game.items():
            if len(team_rows) != 2:
                skipped["unpaired_rows"] += len(team_rows)
                continue
            names = [_norm_team(r.get("team") or r.get("school"))
                     for r in team_rows]
            # Identify the home row: CFBD marks it via homeTeam == team.
            home_row = None
            for r, name in zip(team_rows, names):
                if _norm_team(r.get("homeTeam") or r.get("home_team")) == name and name:
                    home_row = r
                    break
            if home_row is None:
                skipped["unpaired_rows"] += 2
                continue
            away_row = next(r for r in team_rows if r is not home_row)
            home = _norm_team(home_row.get("team") or home_row.get("school"))
            away = _norm_team(away_row.get("team") or away_row.get("school"))
            if not home or not away:
                skipped["unpaired_rows"] += 2
                continue
            if home not in fbs or away not in fbs:
                skipped["non_fbs_opponent"] += 1
                continue
            ho, ao = _epa_of(home_row, "offense"), _epa_of(away_row, "offense")
            hd, ad = _epa_of(home_row, "defense"), _epa_of(away_row, "defense")
            if ho is None or ao is None or hd is None or ad is None:
                skipped["missing_epa"] += 1
                continue
            games.append({
                "game_id": gid, "week": week, "home": home, "away": away,
                "home_off": ho, "away_off": ao,
                "home_def_allowed": hd, "away_def_allowed": ad,
            })
        return games, skipped

    # -- our own opponent adjustment ------------------------------------
    def opponent_adjusted(self, year: int, through_week: int) -> AdjustmentResult:
        """Schedule-adjusted EPA strengths from games with week < through_week.

        Two-way fixed-effects least squares (see module docstring).
        Deterministic given the archive. Fails closed when no usable games
        exist: the result carries zero teams and the reason in coverage —
        never zeros masquerading as data.
        """
        fbs = self.fbs_teams(year)
        games: list[dict] = []
        skipped = {"unpaired_rows": 0, "non_fbs_opponent": 0, "missing_epa": 0}
        for week in self.archived_weeks(year):
            if week >= through_week:
                continue  # as-of: strictly before the target week
            payload = self.load_week(year, week)
            paired, skip = self._pair_games(year, week, payload, fbs)
            games.extend(paired)
            for key in skipped:
                skipped[key] += skip.get(key, 0)
        coverage = {
            "games_used": len(games),
            "weeks_used": sorted({g["week"] for g in games}),
            "skipped": skipped,
            "fbs_teams": len(fbs),
            "method": "two-way fixed-effects least squares (own; "
                      "paid CFBD adjusted metrics never used)",
        }
        result = AdjustmentResult(year=year, through_week=through_week,
                                  coverage=coverage)
        if not games:
            coverage["reason"] = "CFBD_ADJUST_NO_GAMES"
            return result
        teams = sorted({g["home"] for g in games} | {g["away"] for g in games})
        index = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        # Observations: for each team-game, one offensive row and one
        # defensive row. Columns: [O_0..O_{n-1}, D_0..D_{n-1}].
        #   off[i,g] = O[i] + D[opp] ; def[i,g] = D[i] + O[opp].
        rows: list[list[float]] = []
        targets: list[float] = []
        raw_off: dict[str, list[float]] = {t: [] for t in teams}
        raw_def: dict[str, list[float]] = {t: [] for t in teams}
        for g in games:
            for team, opp, off, deff in (
                    (g["home"], g["away"], g["home_off"], g["home_def_allowed"]),
                    (g["away"], g["home"], g["away_off"], g["away_def_allowed"])):
                ti, oi = index[team], index[opp]
                off_row = [0.0] * (2 * n)
                off_row[ti] = 1.0
                off_row[n + oi] = 1.0
                rows.append(off_row)
                targets.append(off)
                def_row = [0.0] * (2 * n)
                def_row[n + ti] = 1.0
                def_row[oi] = 1.0
                rows.append(def_row)
                targets.append(deff)
                raw_off[team].append(off)
                raw_def[team].append(deff)
        solution, residuals, rank, _ = np.linalg.lstsq(
            np.array(rows), np.array(targets), rcond=None)
        off_strength = solution[:n]
        def_weakness = solution[n:]
        # Pin the gauge degree of freedom: mean adjusted margin equals the
        # mean raw margin (schedule adjustment is zero-sum by construction).
        # This preserves every fitted game prediction: shifting O by +c and
        # D by -c leaves O[i]+D[opp] and D[i]+O[opp] unchanged.
        raw_margins = [sum(raw_off[t]) / len(raw_off[t])
                       - sum(raw_def[t]) / len(raw_def[t]) for t in teams]
        target_mean = float(np.mean(raw_margins))
        current_mean = float(np.mean(off_strength - def_weakness))
        shift = (target_mean - current_mean) / 2.0
        off_strength = off_strength + shift
        def_weakness = def_weakness - shift
        # Identification audit. The two-way split has one gauge freedom
        # (rank 2n-1) when the team game-graph is non-bipartite; when a
        # sample's game graph is bipartite, rank drops and only MARGINS
        # (identified up to one global constant, which we pin) are
        # meaningful — the O/D split then carries gauge freedom.
        # Separately, margins are only comparable within a connected
        # component of the team game graph.
        components = _connected_components(teams, games)
        split_identified = (int(rank) == 2 * n - 1)
        coverage["game_graph_components"] = len(components)
        coverage["offense_defense_split_identified"] = split_identified
        if len(components) > 1:
            coverage["warning"] = (
                "CFBD_ADJUST_DISCONNECTED_GRAPH:components=%d — "
                "margins not comparable across components" % len(components))
        if not split_identified:
            coverage["warning"] = (
                coverage.get("warning", "")
                + ("; " if coverage.get("warning") else "")
                + "CFBD_ADJUST_SPLIT_GAUGE_FREEDOM: consume "
                  "adj_margin_epa only, not the O/D split")
        for t in teams:
            i = index[t]
            result.teams[t] = {
                "games": len(raw_off[t]),
                "raw_off_epa": float(np.mean(raw_off[t])),
                "raw_def_epa_allowed": float(np.mean(raw_def[t])),
                "adj_off_epa": float(off_strength[i]),
                "adj_def_epa_allowed": float(def_weakness[i]),
                "adj_margin_epa": float(off_strength[i] - def_weakness[i]),
            }
        coverage["solver_rank"] = int(rank)
        coverage["solver_residuals"] = [float(r) for r in residuals]
        return result

    # -- factor-coverage audit for research cards -----------------------
    def factor_coverage_audit(self, year: int, through_week: int) -> dict:
        """Per-game factor-coverage audit: what the archive can/can't feed.

        Every research card that consumes CFBD factors must carry this:
        verified-used vs missing, with missing critical factors blocking
        pricing (never silently priced).
        """
        audit: dict = {"year": year, "through_week": through_week,
                       "factors": {}}
        try:
            weeks = self.archived_weeks(year)
            usable = [w for w in weeks if w < through_week]
            result = self.opponent_adjusted(year, through_week)
        except CFBDReaderError as exc:
            audit["archive_status"] = "UNAVAILABLE:%s" % exc
            audit["factors"]["cfbd_raw_epa"] = {"status": "MISSING"}
            audit["factors"]["cfbd_opponent_adjusted_epa"] = {
                "status": "MISSING"}
            audit["factors"]["cfbd_sp_plus"] = {
                "status": "NOT_WIRED",
                "reason": "paid-tier product; our own adjustment used instead",
            }
            return audit
        audit["factors"]["cfbd_raw_epa"] = {
            "status": "VERIFIED_USED" if usable else "MISSING",
            "weeks_archived": usable,
            "note": "raw EPA/success/havoc/PPA, garbage time excluded",
        }
        audit["factors"]["cfbd_opponent_adjusted_epa"] = {
            "status": ("VERIFIED_USED" if result.teams else "MISSING"),
            "teams": len(result.teams),
            "games_used": result.coverage.get("games_used", 0),
            "method": "own two-way fixed-effects least squares "
                      "(paid CFBD adjusted metrics never used)",
        }
        audit["factors"]["cfbd_sp_plus"] = {
            "status": "NOT_WIRED",
            "reason": "paid-tier product; our own adjustment used instead",
        }
        audit["archive_status"] = "OK" if usable else "MISSING"
        return audit
