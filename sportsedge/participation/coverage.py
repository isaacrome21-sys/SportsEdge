"""Measured coverage for the participation foundation.

Computes, per signal x season, the coverage table the foundation doc
section 5 requires and the preregistration section 8 gates consume --
MEASURED from the actual nflverse source files, never estimated:

- the eligible-game DENOMINATOR (regular-season team-games from the
  schedule), not downloaded record counts;
- verified coverage against that denominator;
- fail-closed rejection reasons with counts (schema.reason taxonomy);
- the four-way availability classification (owner, 2026-10-12):
  AVAILABLE_HISTORICALLY / AVAILABLE_ONLY_RETROSPECTIVELY /
  FORWARD_CAPTURE_ONLY / UNAVAILABLE_OR_AMBIGUOUS;
- actual observation-lag evidence as carried by the source (roster
  effective-week granularity, injury-report cadence, the source's own
  bookkeeping timestamp distribution -- labelled untrusted where the
  foundation doc says it is untrusted);
- per-signal feasibility verdicts for the V2 model's proposed inputs.

Methodological notes (conservative readings, flagged per the brief):
- The primary QB entering a game is the starter of the team's most recent
  prior game (preregistration section 2), derived from snap counts
  (S1). Where snaps cannot determine it, dependent signals count the
  team-game as uncovered with reason PRIMARY_QB_UNDETERMINED.
- A primary QB's designation is DETERMINABLE when an injury-report row
  exists for him that week (any status, null = no designation) OR his
  team-week is present in the injuries file at all (he was not reported,
  which under the final-report process means no designation). The STRICT
  variant (a row carrying an explicit O/D/Q status) is reported
  alongside; conflating the two would misstate how injury reports work.
- Roster/depth availability uses the prior-week lag rule strictly,
  including for Week 1 (no in-season prior snapshot -> uncovered).
"""

from __future__ import annotations

import io
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

import pandas as pd

from .collectors import Schedule, build_pfr_gsis_bridge, norm_team, practice_class
from .schema import (
    AVAIL_FORWARD_ONLY,
    AVAIL_HISTORICAL,
    AVAIL_RETROSPECTIVE,
    AVAIL_UNAVAILABLE,
    REJ_GAME_BINDING_UNRESOLVED,
    REJ_MISSING_GSIS_ID,
    REJ_SOURCE_FILE_EMPTY,
    REJ_STARTER_AMBIGUOUS,
)
from .timing import week_snapshot_bound_utc

PRIMARY_FITTING_SEASONS = list(range(2019, 2025))   # foundation doc section 5
EXTENDED_SEASONS = list(range(2012, 2019))          # usable to enlarge samples
ALL_MEASURED_SEASONS = EXTENDED_SEASONS + PRIMARY_FITTING_SEASONS

REJ_PRIMARY_UNDETERMINED = "PRIMARY_QB_UNDETERMINED"
REJ_QB_IDENTITY = "QB_IDENTITY_UNRESOLVED_NO_GSIS_BRIDGE"


# ---------------------------------------------------------------------------
def _load(raw: bytes | None) -> pd.DataFrame | None:
    if raw is None or len(raw.strip()) == 0:
        return None
    df = pd.read_csv(io.BytesIO(raw), low_memory=False, dtype={"gsis_id": str})
    return df if len(df) else None


def _pct(n: int, d: int) -> float | None:
    return None if d == 0 else round(100.0 * n / d, 2)


# ---------------------------------------------------------------------------
class SeasonData:
    def __init__(self, season: int, files: dict[str, bytes | None]):
        self.season = season
        self.injuries = _load(files.get("injuries"))
        self.snaps = _load(files.get("snap_counts"))
        self.rosters = _load(files.get("weekly_rosters"))
        self.depth = _load(files.get("depth_charts"))
        self.bridge = (
            build_pfr_gsis_bridge(files["weekly_rosters"], season)
            if files.get("weekly_rosters")
            else {}
        )
        # starters: (game_id, team) -> dict(pfr_id, gsis, name, snaps) | "AMBIGUOUS"
        self.starters: dict[tuple[str, str], dict | str] = {}
        # snap completeness: (game_id, team) -> bool
        self.snap_complete: dict[tuple[str, str], bool] = {}
        if self.snaps is not None:
            self._derive_snaps()

    def _derive_snaps(self):
        snaps = self.snaps
        grp = snaps.groupby(["game_id", "team"])
        stats = grp.agg(n_players=("player", "count"),
                        max_off=("offense_snaps", "max")).reset_index()
        pct_ok = (
            snaps.assign(ok=snaps[["offense_pct", "defense_pct", "st_pct"]]
                         .apply(lambda s: s.isna() | ((s >= 0) & (s <= 1))).all(axis=1))
            .groupby(["game_id", "team"])["ok"].all().reset_index()
        )
        merged = stats.merge(pct_ok, on=["game_id", "team"])
        for row in merged.itertuples(index=False):
            team = norm_team(row.team)
            self.snap_complete[(str(row.game_id), team)] = bool(
                row.n_players >= 35 and 30 <= int(row.max_off) <= 120 and bool(row.ok)
            )
        qbs = snaps[snaps["position"] == "QB"]
        for (game_id, team), g in qbs.groupby(["game_id", "team"]):
            g = g.sort_values("offense_snaps", ascending=False)
            top = g.iloc[0]
            team_n = norm_team(team)
            if len(g) > 1 and int(g.iloc[1]["offense_snaps"]) == int(top["offense_snaps"]):
                self.starters[(str(game_id), team_n)] = "AMBIGUOUS"
                continue
            pfr = str(top["pfr_player_id"])
            self.starters[(str(game_id), team_n)] = {
                "pfr_id": pfr,
                "gsis_id": self.bridge.get((self.season, pfr)),
                "name": str(top["player"]),
                "offense_snaps": int(top["offense_snaps"]),
            }


# ---------------------------------------------------------------------------
def measure_season(season: int, schedule: Schedule, files: dict[str, bytes | None],
                   prior_season_data: SeasonData | None,
                   season_data: SeasonData | None = None) -> dict:
    """Measure one season. ``season_data`` may be injected (e.g. by a
    sensitivity analysis with an amended identity bridge); by default the
    strict source data is built from ``files``."""
    data = season_data if season_data is not None else SeasonData(season, files)
    team_games = schedule.reg_team_games(season)  # [(team, game)]
    denom = len(team_games)

    # prior game per (team, game_id) across the full schedule sequence
    seq = sorted(schedule.by_id.values(), key=lambda g: (g["kickoff_utc"], g["game_id"]))
    last_game_for_team: dict[str, dict] = {}
    prior_of: dict[tuple[str, str], dict | None] = {}
    season_of_game = {}
    for g in seq:
        season_of_game[g["game_id"]] = g
        for t in (g["away_team"], g["home_team"]):
            prior_of[(t, g["game_id"])] = last_game_for_team.get(t)
            last_game_for_team[t] = g

    def starter_of(game, team):
        """Starter record for a team-game, looking across season datasets."""
        src = data if game["season"] == season else prior_season_data
        if src is None:
            return None
        return src.starters.get((game["game_id"], team))

    def snap_complete_of(game, team):
        src = data if game["season"] == season else prior_season_data
        if src is None:
            return None
        return src.snap_complete.get((game["game_id"], team))

    # --- injuries lookups ---------------------------------------------------
    inj = data.injuries
    inj_reg = None
    inj_team_weeks: set[tuple[str, int]] = set()
    inj_rows_missing_gsis = 0
    if inj is not None:
        inj_reg = inj[inj["game_type"] == "REG"]
        inj_team_weeks = {
            (norm_team(t), int(w)) for t, w in zip(inj_reg["team"], inj_reg["week"])
        }
        inj_rows_missing_gsis = int(inj_reg["gsis_id"].isna().sum())
    inj_by_key: dict[tuple[int, str], object] = {}
    if inj_reg is not None:
        for row in inj_reg.itertuples(index=False):
            if isinstance(row.gsis_id, str):
                inj_by_key[(int(row.week), row.gsis_id)] = row.report_status

    # --- roster lookups -------------------------------------------------------
    def _roster_index(df):
        team_weeks: set[tuple[str, int]] = set()
        by_key: dict[tuple[int, str], str] = {}
        if df is not None:
            reg = df[df["game_type"] == "REG"]
            team_weeks = {
                (norm_team(t), int(w)) for t, w in zip(reg["team"], reg["week"])
            }
            for row in reg.itertuples(index=False):
                if isinstance(row.gsis_id, str):
                    # First occurrence wins -- identical rule to the
                    # collector; conflicting duplicates are counted there,
                    # never silently overwritten here.
                    by_key.setdefault(
                        (int(row.week), row.gsis_id),
                        None if pd.isna(row.status) else str(row.status))
        return team_weeks, by_key

    ros = data.rosters
    ros_team_weeks, ros_by_key = _roster_index(ros)
    prior_ros_team_weeks, prior_ros_by_key = (
        _roster_index(prior_season_data.rosters)
        if prior_season_data is not None else (set(), {})
    )

    # --- depth lookups --------------------------------------------------------
    dep = data.depth
    qb2_by_team_week: dict[tuple[str, int], str] = {}
    if dep is not None:
        qb = dep[(dep["depth_position"] == "QB") & (dep["game_type"] == "REG")]
        for row in qb.itertuples(index=False):
            try:
                rank = int(float(row.depth_team))
            except (TypeError, ValueError):
                continue
            if rank == 2 and isinstance(row.gsis_id, str):
                qb2_by_team_week[(norm_team(row.club_code), int(row.week))] = row.gsis_id

    # --- per team-game accounting ---------------------------------------------
    s1 = Counter(); s2 = Counter(); s3 = Counter(); s5 = Counter(); s6 = Counter()
    designations_seen = Counter()
    questionable_cases = 0
    backup_starts = 0
    lag_inj_hours: list[float] = []
    lag_roster_days: list[float] = []
    inj_modified_after_kickoff = 0
    inj_modified_rows = 0
    combined_covered = 0

    inj_mod_by_key: dict[tuple[int, str], object] = {}
    if inj_reg is not None:
        for row in inj_reg.itertuples(index=False):
            if isinstance(row.gsis_id, str):
                inj_mod_by_key[(int(row.week), row.gsis_id)] = row.date_modified

    for team, game in team_games:
        week = game["week"]
        # S1: starter of THIS game identifiable
        st = data.starters.get((game["game_id"], team))
        if data.snaps is None:
            s1[REJ_SOURCE_FILE_EMPTY] += 1
        elif st == "AMBIGUOUS":
            s1[REJ_STARTER_AMBIGUOUS] += 1
        elif st is None:
            s1[REJ_GAME_BINDING_UNRESOLVED] += 1
        else:
            s1["STARTER_IDENTIFIED"] += 1
            if st.get("gsis_id") is None:
                # Strict pfr->gsis bridge failed (roster file's pfr_id is
                # blank for this player). Count how many are recoverable by
                # schedule-QB name corroboration -- reported, NOT used to
                # promote the headline metrics (owner decision at lock).
                sched_name = (game["home_qb_name"] if team == game["home_team"]
                              else game["away_qb_name"])
                if isinstance(sched_name, str) and sched_name == st.get("name"):
                    s1["STARTER_IDENTITY_SCHEDULE_CORROBORATED"] += 1
                else:
                    s1["STARTER_IDENTITY_UNRESOLVED"] += 1

        # S2: prior game snap completeness (this team's prior game)
        prior = prior_of.get((team, game["game_id"]))
        if prior is None:
            s2["NO_PRIOR_GAME_IN_SEQUENCE"] += 1
        else:
            complete = snap_complete_of(prior, team)
            if complete is None:
                s2[REJ_SOURCE_FILE_EMPTY if (prior["season"] == 2012 or data.snaps is None)
                   else REJ_GAME_BINDING_UNRESOLVED] += 1
            elif complete:
                s2["PRIOR_GAME_SNAPS_COMPLETE"] += 1
            else:
                s2["PRIOR_GAME_SNAPS_INCOMPLETE"] += 1

        # primary QB entering this game (S1-derived)
        primary = starter_of(prior, team) if prior is not None else None
        primary_gsis = None
        if isinstance(primary, dict):
            primary_gsis = primary.get("gsis_id")
            # backup-start accounting (compare by pfr, bridge-independent)
            if isinstance(st, dict) and st["pfr_id"] != primary["pfr_id"]:
                backup_starts += 1

        # S3: designation determinability for the primary QB
        det_ok = False
        if primary is None or primary == "AMBIGUOUS":
            s3[REJ_PRIMARY_UNDETERMINED] += 1
        elif primary_gsis is None:
            s3[REJ_QB_IDENTITY] += 1
        else:
            key = (week, primary_gsis)
            if key in inj_by_key:
                s3["QB_ROW_PRESENT"] += 1
                det_ok = True
                status = inj_by_key[key]
                label = "NONE_ON_REPORT" if pd.isna(status) else str(status)
                designations_seen[label] += 1
                if label == "Questionable":
                    questionable_cases += 1
                mod = inj_mod_by_key.get(key)
                if isinstance(mod, str):
                    inj_modified_rows += 1
                    try:
                        mts = datetime.fromisoformat(mod.replace("Z", "+00:00"))
                        delta_h = (game["kickoff_utc"] - mts).total_seconds() / 3600.0
                        lag_inj_hours.append(delta_h)
                        if delta_h < 0:
                            inj_modified_after_kickoff += 1
                    except ValueError:
                        pass
            elif (team, week) in inj_team_weeks:
                s3["QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT"] += 1
                det_ok = True
                designations_seen["NONE_NOT_REPORTED"] += 1
            else:
                s3["TEAM_WEEK_ABSENT_FROM_SOURCE"] += 1

        # S5: reserve determinability under prior-week lag rule
        res_ok = False
        if primary is None or primary == "AMBIGUOUS":
            s5[REJ_PRIMARY_UNDETERMINED] += 1
        elif primary_gsis is None:
            s5[REJ_QB_IDENTITY] += 1
        else:
            found_week = None
            found_season = season
            saw_inseason_snapshot = False
            for w in range(week - 1, 0, -1):
                if (team, w) in ros_team_weeks:
                    saw_inseason_snapshot = True
                if (w, primary_gsis) in ros_by_key:
                    found_week = w
                    break
                if (team, w) in ros_team_weeks:
                    # The team's most recent snapshot does not list him:
                    # absence governs (he was not on this roster then).
                    break
            if found_week is None and not saw_inseason_snapshot and prior_ros_by_key:
                # Cross-season fallback (same lag rule, season boundary):
                # the prior season's final snapshots are genuinely prior.
                # Counted separately so the split is visible.
                for w in sorted({wk for (wk, _g) in prior_ros_by_key}, reverse=True):
                    if (w, primary_gsis) in prior_ros_by_key:
                        found_week = w
                        found_season = season - 1
                        break
                    if (team, w) in prior_ros_team_weeks:
                        break
            if found_week is not None:
                if found_season == season:
                    s5["QB_FOUND_IN_PRIOR_SNAPSHOT"] += 1
                    status = ros_by_key[(found_week, primary_gsis)]
                else:
                    s5["QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT"] += 1
                    status = prior_ros_by_key[(found_week, primary_gsis)]
                res_ok = True
                if status in ("RES", "PUP"):
                    s5["QB_ON_RESERVE_IN_PRIOR_SNAPSHOT"] += 1
                # lag evidence: kickoff minus that snapshot's bound
                last_day = schedule.week_last_gameday.get((found_season, found_week))
                if last_day is not None:
                    bound = week_snapshot_bound_utc(last_day)
                    lag_roster_days.append(
                        (game["kickoff_utc"] - bound).total_seconds() / 86400.0
                    )
            else:
                s5["QB_NOT_IN_ANY_PRIOR_SNAPSHOT"] += 1

        if det_ok and res_ok:
            combined_covered += 1

        # S6: prior-week QB2 on depth chart
        if (team, week - 1) in qb2_by_team_week:
            s6["QB2_IDENTIFIED_PRIOR_WEEK"] += 1
        else:
            s6["QB2_NOT_IDENTIFIED"] += 1

    # --- S4: practice status presence among designation rows ------------------
    s4 = Counter()
    if inj_reg is not None:
        with_row = inj_reg[inj_reg["gsis_id"].notna()]
        s4["ROWS_WITH_PRACTICE_STATUS"] = int(with_row["practice_status"].notna().sum())
        s4["ROWS_TOTAL"] = int(len(with_row))
        for v in with_row["practice_status"].dropna():
            cls = practice_class(v)
            if cls:
                s4[f"CLASS_{cls}"] += 1

    # --- S3 x S5 cross-check (same week; data-consistency audit) --------------
    cross = _cross_check(data, schedule)

    def lag_stats(values):
        if not values:
            return None
        s = pd.Series(values)
        return {"n": int(len(s)), "min": round(float(s.min()), 2),
                "p10": round(float(s.quantile(0.10)), 2),
                "median": round(float(s.median()), 2),
                "p90": round(float(s.quantile(0.90)), 2),
                "max": round(float(s.max()), 2)}

    snaps_class = AVAIL_UNAVAILABLE if data.snaps is None else AVAIL_RETROSPECTIVE
    return {
        "season": season,
        "denominator_team_games_reg": denom,
        "signals": {
            "S1_STARTER_ACTUAL": {
                "availability_class": snaps_class,
                "timing_evidence": "NONE",
                "counts": dict(s1),
                "starter_identified_pct": _pct(s1["STARTER_IDENTIFIED"], denom),
                "backup_start_games": backup_starts,
                "cell_notes": "Starter = QB with most offensive snaps (ties fail "
                "closed). Post-game actual: retrospective by construction; prior "
                "games' starters are legitimate inputs for later games under "
                "the completion-window safeguard.",
            },
            "S2_SNAP_COUNTS": {
                "availability_class": snaps_class,
                "timing_evidence": "NONE",
                "counts": dict(s2),
                "prior_game_complete_pct": _pct(s2["PRIOR_GAME_SNAPS_COMPLETE"],
                                                denom - s2["NO_PRIOR_GAME_IN_SEQUENCE"]),
                "cell_notes": "Source carries NO timestamps; publication lag is "
                "documented (~1 day, PFR) but NOT measured from this source. "
                "Classified retrospectively per owner rule.",
            },
            "S3_INJURY_DESIGNATIONS": {
                "availability_class": AVAIL_HISTORICAL if inj is not None else AVAIL_UNAVAILABLE,
                "timing_evidence": "CADENCE_INFERRED",
                "counts": dict(s3),
                "qb_designation_determinable_pct": _pct(
                    s3["QB_ROW_PRESENT"] + s3["QB_NOT_ON_REPORT_TEAM_WEEK_PRESENT"], denom),
                "qb_designation_strict_row_pct": _pct(s3["QB_ROW_PRESENT"], denom),
                "primary_qb_designations": dict(designations_seen),
                "questionable_qb_cases": questionable_cases,
                "rows_missing_gsis": inj_rows_missing_gsis,
                "observation_lag_evidence": {
                    "basis": "date_modified bookkeeping timestamp vs kickoff "
                             "(UNTRUSTED as publication proof -- foundation S3 "
                             "risk 2; classification rests on cadence)",
                    "hours_before_kickoff": lag_stats(lag_inj_hours),
                    "rows_with_modified_ts": inj_modified_rows,
                    "rows_modified_after_kickoff": inj_modified_after_kickoff,
                },
                "cell_notes": "Final-report rule: designations are public pre-"
                "kickoff by league cadence (24-48h). No revision history exists; "
                "date_modified is the feed's bookkeeping, not a publication "
                "receipt.",
            },
            "S4_PRACTICE_STATUS": {
                "availability_class": AVAIL_HISTORICAL if inj is not None else AVAIL_UNAVAILABLE,
                "timing_evidence": "CADENCE_INFERRED",
                "counts": dict(s4),
                "rows_with_practice_status_pct": _pct(
                    s4["ROWS_WITH_PRACTICE_STATUS"], max(s4["ROWS_TOTAL"], 1)),
                "cell_notes": "Weekly snapshot only; per-day progression is NOT "
                "reconstructible (forward-capture class). Restricted use.",
            },
            "S5_ROSTER_RESERVE": {
                "availability_class": AVAIL_HISTORICAL if ros is not None else AVAIL_UNAVAILABLE,
                "timing_evidence": "CADENCE_INFERRED",
                "counts": dict(s5),
                "qb_reserve_determinable_pct": _pct(
                    s5["QB_FOUND_IN_PRIOR_SNAPSHOT"]
                    + s5["QB_FOUND_IN_PRIOR_SEASON_SNAPSHOT"], denom),
                "observation_lag_evidence": {
                    "basis": "weekly snapshot granularity under prior-week lag "
                             "rule; lag = kickoff minus snapshot week-conclusion "
                             "bound, in days",
                    "days": lag_stats(lag_roster_days),
                },
                "cell_notes": "Status codes are a coarse bucket (RES/PUP/...); "
                "reserve SUBTYPE rides on opaque status_description_abbr codes "
                "with no in-file codebook and is unresolved. Snapshot "
                "compilation time inside the week is unknown -- prior-week "
                "rule is the conservative consequence (Week 1 uncovered).",
            },
            "S6_DEPTH_CHARTS": {
                "availability_class": AVAIL_HISTORICAL if dep is not None else AVAIL_UNAVAILABLE,
                "timing_evidence": "CADENCE_INFERRED",
                "counts": dict(s6),
                "qb2_prior_week_pct": _pct(s6["QB2_IDENTIFIED_PRIOR_WEEK"], denom),
                "cell_notes": "Backup identity only; prior-week chart under lag "
                "rule. Snap evidence outranks chart evidence where they differ.",
            },
            "S7_GAME_DAY_INACTIVES": {
                "availability_class": AVAIL_FORWARD_ONLY,
                "counts": {},
                "cell_notes": "No trustworthy timestamped historical archive "
                "exists. Schema support built; zero historical records, by "
                "design. Excluded from any historical feature set.",
            },
            "S8_REPORT_REVISIONS": {
                "availability_class": AVAIL_FORWARD_ONLY,
                "counts": {},
                "cell_notes": "No structured timestamped historical archive "
                "exists. Schema support built; zero historical records, by "
                "design.",
            },
        },
        "combined_s3_s5_qb_coverage_pct": _pct(combined_covered, denom),
        "cross_check_s3_s5": cross,
    }


def _cross_check(data: SeasonData, schedule: Schedule) -> dict:
    """Same-week consistency audit between roster reserve status (S5) and
    injury designations (S3) + actual participation (S2). A data-consistency
    audit, not a feature: same-week binding is correct here."""
    out = {"population_reserve_player_weeks": 0, "consistent": 0,
           "conflict_designation_q_or_d_while_reserve": 0,
           "conflict_played_snaps_while_reserve": 0,
           "reverse_out_but_active_and_played": 0}
    if data.rosters is None or data.injuries is None:
        return out
    ros = data.rosters[data.rosters["game_type"] == "REG"]
    inj = data.injuries[data.injuries["game_type"] == "REG"]
    inj_status = {}
    for row in inj.itertuples(index=False):
        if isinstance(row.gsis_id, str):
            inj_status[(int(row.week), row.gsis_id)] = (
                None if pd.isna(row.report_status) else str(row.report_status))
    played: dict[tuple[int, str], int] = defaultdict(int)
    if data.snaps is not None:
        snaps_reg = data.snaps[data.snaps["game_type"] == "REG"]
        for row in snaps_reg.itertuples(index=False):
            gsis = data.bridge.get((data.season, str(row.pfr_player_id)))
            if gsis:
                played[(int(row.week), gsis)] += (
                    int(row.offense_snaps or 0) + int(row.defense_snaps or 0)
                    + int(row.st_snaps or 0))
    reserve_weeks = 0
    consistent = 0
    for row in ros.itertuples(index=False):
        if not isinstance(row.gsis_id, str):
            continue
        status = None if pd.isna(row.status) else str(row.status)
        key = (int(row.week), row.gsis_id)
        designation = inj_status.get(key)
        if status in ("RES", "PUP"):
            reserve_weeks += 1
            conflict = False
            if designation in ("Questionable", "Doubtful"):
                out["conflict_designation_q_or_d_while_reserve"] += 1
                conflict = True
            if played.get(key, 0) > 0:
                out["conflict_played_snaps_while_reserve"] += 1
                conflict = True
            if not conflict:
                consistent += 1
        if designation == "Out" and status == "ACT" and played.get(key, 0) > 0:
            out["reverse_out_but_active_and_played"] += 1
    out["population_reserve_player_weeks"] = reserve_weeks
    out["consistent"] = consistent
    out["consistent_pct"] = _pct(consistent, reserve_weeks)
    return out


# ---------------------------------------------------------------------------
def pooled_gates(season_results: list[dict], seasons: list[int]) -> dict:
    """Preregistration section 8 gates, computed from measured values."""
    rows = [r for r in season_results if r["season"] in seasons]
    denom = sum(r["denominator_team_games_reg"] for r in rows)
    combined_num = sum(
        (r["combined_s3_s5_qb_coverage_pct"] or 0) / 100.0
        * r["denominator_team_games_reg"] for r in rows)
    s2_num = sum(r["signals"]["S2_SNAP_COUNTS"]["counts"].get(
        "PRIOR_GAME_SNAPS_COMPLETE", 0) for r in rows)
    s2_den = sum(
        r["denominator_team_games_reg"]
        - r["signals"]["S2_SNAP_COUNTS"]["counts"].get("NO_PRIOR_GAME_IN_SEQUENCE", 0)
        for r in rows)
    backup = sum(r["signals"]["S1_STARTER_ACTUAL"]["backup_start_games"] for r in rows)
    quest = sum(r["signals"]["S3_INJURY_DESIGNATIONS"]["questionable_qb_cases"] for r in rows)
    return {
        "seasons": seasons,
        "team_games": denom,
        "gate_s3_s5_qb_coverage_ge_95pct": {
            "value_pct": _pct(int(round(combined_num)), denom), "threshold_pct": 95.0,
            "pass": (combined_num / denom) >= 0.95 if denom else False},
        "gate_s2_snap_completeness_ge_95pct": {
            "value_pct": _pct(s2_num, s2_den), "threshold_pct": 95.0,
            "pass": (s2_num / s2_den) >= 0.95 if s2_den else False,
            "denominator_note": "team-games with an in-sequence prior game"},
        "gate_backup_start_games_ge_150": {
            "value": backup, "threshold": 150, "pass": backup >= 150},
        "gate_questionable_qb_cases_ge_100": {
            "value": quest, "threshold": 100, "pass": quest >= 100},
    }


def feasibility_verdicts(pooled_primary: dict, season_results: list[dict]) -> dict:
    """Per-V2-input verdicts driven by the measured cells."""
    rows = [r for r in season_results if r["season"] in PRIMARY_FITTING_SEASONS]
    denom = sum(r["denominator_team_games_reg"] for r in rows)

    def pooled_pct(signal, key_counts, mode):
        if mode == "key":
            num = sum(r["signals"][signal]["counts"].get(k, 0)
                      for r in rows for k in key_counts)
            return _pct(num, denom)
        return None

    starter_pct = pooled_pct("S1_STARTER_ACTUAL", ["STARTER_IDENTIFIED"], "key")
    det_pct = None
    num = sum(
        (r["combined_s3_s5_qb_coverage_pct"] or 0) / 100.0
        * r["denominator_team_games_reg"] for r in rows)
    s3_pct = _pct(int(round(sum(
        (r["signals"]["S3_INJURY_DESIGNATIONS"]["qb_designation_determinable_pct"] or 0)
        / 100.0 * r["denominator_team_games_reg"] for r in rows))), denom)
    s5_pct = _pct(int(round(sum(
        (r["signals"]["S5_ROSTER_RESERVE"]["qb_reserve_determinable_pct"] or 0)
        / 100.0 * r["denominator_team_games_reg"] for r in rows))), denom)
    s6_pct = _pct(int(round(sum(
        (r["signals"]["S6_DEPTH_CHARTS"]["qb2_prior_week_pct"] or 0)
        / 100.0 * r["denominator_team_games_reg"] for r in rows))), denom)
    s2_pct = pooled_primary["gate_s2_snap_completeness_ge_95pct"]["value_pct"]

    def verdict(pct, gate=95.0):
        if pct is None:
            return "NOT_FEASIBLE"
        if pct >= gate:
            return "FEASIBLE"
        if pct >= gate - 2.0:
            return "FEASIBLE_WITH_NAMED_RESTRICTIONS"
        return "NOT_FEASIBLE"

    return {
        "primary_qb_id (S1/S2)": {
            "verdict": verdict(starter_pct, 99.0),
            "measured_pct": starter_pct,
            "basis": "starter identification rate, fitting corpora pooled",
            "restrictions": "snap-derived starter (max offensive snaps); ties "
            "fail closed; 2012 unavailable at the named source (header-only "
            "file), so extended corpora effectively start 2013",
        },
        "qb_designation (S3)": {
            "verdict": verdict(s3_pct),
            "measured_pct": s3_pct,
            "basis": "determinable = report row present (any status) or "
            "team-week present in the injuries file",
            "restrictions": "final-report cadence rule (cadence-inferred "
            "timing, no per-record publication receipt); no revision "
            "history; strict explicit-designation rows are a minority of "
            "team-games because healthy QBs carry no designation",
        },
        "qb_reserve (S5)": {
            "verdict": verdict(s5_pct),
            "measured_pct": s5_pct,
            "basis": "primary QB found in a prior-week roster snapshot",
            "restrictions": "prior-week lag rule strictly applied (Week 1 "
            "team-games uncovered); reserve subtype unresolved (opaque "
            "status_description_abbr codes, no codebook)",
        },
        "qb_practice_final (S4)": {
            "verdict": "FEASIBLE_WITH_NAMED_RESTRICTIONS",
            "measured_pct": None,
            "basis": "practice_status presence among injury-report rows "
            "(see per-season S4 counts)",
            "restrictions": "weekly snapshot only; per-day progression not "
            "reconstructible; optional feature -- drop at design freeze if "
            "its value cannot be isolated (foundation S4)",
        },
        "backup_qb_id (S1/S6)": {
            "verdict": verdict(s6_pct, 90.0),
            "measured_pct": s6_pct,
            "basis": "prior-week depth-chart QB2 identified rate; snap "
            "evidence (most recent fill-in starter) outranks the chart",
            "restrictions": "chart snapshot day inside the week is "
            "untimestamped; lag rule mandatory",
        },
        "absent_share_off/def (S2 x S3/S5)": {
            "verdict": verdict(s2_pct),
            "measured_pct": s2_pct,
            "basis": "prior-game snap completeness gate metric",
            "restrictions": "trailing shares from completed games only, "
            "under the completion-window safeguard; same-game snaps never "
            "features",
        },
        "game_day_inactives (S7)": {
            "verdict": "NOT_FEASIBLE",
            "measured_pct": 0.0,
            "basis": "no trustworthy timestamped historical archive exists",
            "restrictions": "forward-capture only; excluded from V2 per the "
            "parity rule and the owner's decision",
        },
        "report_revisions (S8)": {
            "verdict": "NOT_FEASIBLE",
            "measured_pct": 0.0,
            "basis": "no structured timestamped historical archive exists",
            "restrictions": "forward-capture only; excluded from V2",
        },
    }


def compute_all(raw_files: dict[tuple[str, int], bytes | None],
                games_raw: bytes) -> dict:
    """raw_files keyed (signal_name, season) with signal_name in
    {injuries, snap_counts, weekly_rosters, depth_charts}."""
    schedule = Schedule(pd.read_csv(io.BytesIO(games_raw), low_memory=False))
    results = []
    prior_data: SeasonData | None = None
    for season in ALL_MEASURED_SEASONS:
        files = {name: raw_files.get((name, season))
                 for name in ("injuries", "snap_counts", "weekly_rosters", "depth_charts")}
        res = measure_season(season, schedule, files, prior_data)
        results.append(res)
        prior_data = SeasonData(season, files)
    gates_primary = pooled_gates(results, PRIMARY_FITTING_SEASONS)
    gates_extended = pooled_gates(results, EXTENDED_SEASONS)
    gates_all = pooled_gates(results, ALL_MEASURED_SEASONS)
    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "measured from nflverse source files; see coverage.py docstring",
        "seasons": results,
        "gates": {
            "primary_fitting_2019_2024": gates_primary,
            "extended_2012_2018": gates_extended,
            "all_2012_2024": gates_all,
        },
        "feasibility_verdicts": feasibility_verdicts(gates_primary, results),
    }
