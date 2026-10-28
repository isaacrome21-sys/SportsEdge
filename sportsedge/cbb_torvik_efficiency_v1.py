"""CBB_TORVIK_EFFICIENCY_V1 — shared forward construction and inputs.

This module is the shared core for the two DESIGN_PASS CBB families
built on the Torvik efficiency construction:

  * CBB_TORVIK_EFFICIENCY_V1 (spread/total; runner:
    ``sportsedge.cbb_efficiency_forward``), and
  * its team-totals readout (runner:
    ``sportsedge.cbb_team_total_forward``), whose expected team points
    ARE this construction's expected team points — no second model.

It carries, with no I/O beyond the two pinned input readers:

  * the construction arithmetic of record, identical in operation
    order to the screen of record
    (``research/cbb_torvik_efficiency_screen_20261028/``
    ``run_screen_attempt4.py`` sha256 75479ea1... and
    ``research/cbb_team_totals_screen_20261028/cbb_team_totals.py``
    sha256 ac01327a...);
  * the forward home-court constants, fitted at build time by the
    design's own walk-forward protocol (see the provenance constants
    below and each family's BUILD_RECORD.md);
  * the FORWARD input reader (reading R-1 of the freeze packages):
    the live route's morning-of Torvik vintage from the daily pull
    store, ``<store>/<YYYY-MM-DD>.csv`` with its ``.json`` manifest.
    The Amendment 1 prior-snapshot (D-1) convention governed the
    SCREEN only and is NOT extended to the forward path;
  * the identity resolver over the admitted crosswalk (PR #2898),
    with the Illinois-college exclusion applied exactly as
    ``sportsedge.cbb_capture_scope`` applies it (fail-closed ESPN-ID
    denylist, plus the crosswalk's own exclusion flag).

NOTHING in this module counts. The families are NOT FROZEN; the
runners refuse every counted entry point with a named NOT_FROZEN
code, and every record they write carries counted=False.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ENGINE_ID = "CBB_TORVIK_EFFICIENCY_V1"
SCHEMA_VINTAGE = "SPORTSEDGE_TORVIK_MORNING_VINTAGE_V1"

SEED = 20261028

# ------------------------------------------------------------------
# Fitted forward constants (build-time fit, 2026-10-28).
#
# Protocol (design section 3, unchanged from the screen): the
# candidate home-court term for a scored season is the mean of
# (actual margin - neutral-site candidate margin) over the agreed
# fixtures of STRICTLY PRIOR seasons; the simple baseline's constant
# is the SAME estimator over the 2014-15 fixture window, measured
# once on the first window and carried forward.
#
# The forward test's scored season is 2026-27, so the candidate term
# is fitted on ALL admitted archive seasons (2014-15 .. 2022-23,
# 26,553 agreed fixtures, of which the non-neutral subset enters the
# mean). The fit was executed at build time by driving the screen
# runner's own universe machinery over the pinned legs; the two
# cross-checks against the published screen result reproduced its
# constants EXACTLY (2014-15 fixed constant 3.3756023216238145 and
# the 2022-23 candidate term 3.2501022398177666 — see BUILD_RECORD).
# The freeze act re-pins these constants; any refit is a new build.
HOME_COURT_CANDIDATE_FORWARD = 3.260655725219634
HOME_COURT_BASELINE_FIXED = 3.3756023216238145
HOME_COURT_FIT_PROVENANCE = (
    "walk-forward mean of (actual margin - neutral candidate margin) "
    "over the agreed non-neutral fixtures of all admitted archive "
    "seasons 2014-15..2022-23 (26,553 agreed fixtures); candidate "
    "term fit on strictly-prior seasons per design section 3; "
    "baseline constant is the same estimator over the 2014-15 window "
    "only, carried forward unchanged from the screen of record"
)


class CbbForwardError(ValueError):
    """Named, fail-closed refusal (the reason code is stable)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(reason if not detail else f"{reason}: {detail}")


# ------------------------------------------------------------------
# Construction arithmetic (identical to the construction of record).
# ------------------------------------------------------------------

@dataclass(frozen=True)
class TeamRatings:
    adj_o: float
    adj_d: float
    adj_tempo: float


def expected_team_points(adj_o: float, opp_adj_d: float,
                         league_mean_eff: float,
                         possessions: float) -> float:
    return (adj_o + opp_adj_d - league_mean_eff) / 100.0 * possessions


def candidate_team_points(home: TeamRatings, away: TeamRatings,
                          league_mean_eff: float) -> tuple[float, float]:
    """Expected points (home, away) for the candidate construction.

    Expected possessions are the arithmetic mean of the two teams'
    adjusted tempos (design section 1, as operationalized by the
    screen of record).
    """
    poss = (home.adj_tempo + away.adj_tempo) / 2.0
    return (expected_team_points(home.adj_o, away.adj_d,
                                 league_mean_eff, poss),
            expected_team_points(away.adj_o, home.adj_d,
                                 league_mean_eff, poss))


def baseline_team_points(home: TeamRatings, away: TeamRatings,
                         league_mean_eff: float,
                         league_mean_tempo: float) -> tuple[float, float]:
    """Expected points (home, away) for the section 1 simple ratings
    baseline: each team's own ratings at the league-mean tempo."""
    return (expected_team_points(home.adj_o, away.adj_d,
                                 league_mean_eff, league_mean_tempo),
            expected_team_points(away.adj_o, home.adj_d,
                                 league_mean_eff, league_mean_tempo))


def model_outputs(home: TeamRatings, away: TeamRatings,
                  league_mean_eff: float, league_mean_tempo: float,
                  neutral_site: bool) -> dict:
    """Candidate and baseline outputs for one game.

    Exactly the construction of record: the home-court term enters
    the MARGIN only (design section 1: the margin is the
    expected-points difference plus a home-court term that is zero
    at neutral sites). Expected team points — and therefore the game
    total and the team-totals readout — carry NO home-court term,
    exactly as the screened construction computes them
    (candidate_team_points has no home-court input). The margin is
    formed as (points difference) + term, the screen's own
    expression, so forward outputs are float-identical to the
    construction of record on identical inputs.
    """
    cand_home, cand_away = candidate_team_points(home, away,
                                                 league_mean_eff)
    base_home, base_away = baseline_team_points(
        home, away, league_mean_eff, league_mean_tempo)
    hc_candidate = 0.0 if neutral_site else HOME_COURT_CANDIDATE_FORWARD
    hc_baseline = 0.0 if neutral_site else HOME_COURT_BASELINE_FIXED
    return {
        "expected_points_home_candidate": cand_home,
        "expected_points_away_candidate": cand_away,
        "expected_points_home_baseline_simple": base_home,
        "expected_points_away_baseline_simple": base_away,
        "model_margin_home_candidate": (cand_home - cand_away)
        + hc_candidate,
        "model_total_candidate": cand_home + cand_away,
        "model_margin_home_baseline_simple": (base_home - base_away)
        + hc_baseline,
        "model_total_baseline_simple": base_home + base_away,
        "home_court_term_candidate": hc_candidate,
        "home_court_constant_baseline_simple": hc_baseline,
    }


# ------------------------------------------------------------------
# Identity: the admitted crosswalk (PR #2898) + Illinois exclusion.
# ------------------------------------------------------------------

# Fail-closed ESPN-ID denylist, taken from the capture-scope module
# of record so the runners exclude EXACTLY what the scope module
# excludes. Imported (not copied) so the two can never drift; the
# scope module's sha256 is pinned into every record.
from sportsedge.cbb_capture_scope import (  # noqa: E402
    _ILLINOIS_ESPN_MBB_2027_DENYLIST as ILLINOIS_ESPN_DENYLIST,
)


@dataclass(frozen=True)
class CrosswalkTeam:
    canonical_id: str
    torvik_name: str
    espn_id: str
    capture_excluded_illinois: bool


class Crosswalk:
    def __init__(self, teams: list[CrosswalkTeam]) -> None:
        self.by_espn_id = {t.espn_id: t for t in teams}
        self.by_torvik_name = {t.torvik_name: t for t in teams}

    def for_espn_id(self, espn_id: str) -> CrosswalkTeam | None:
        return self.by_espn_id.get(str(espn_id))


def load_crosswalk(path) -> Crosswalk:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        teams = [CrosswalkTeam(
            canonical_id=str(t["canonical_id"]),
            torvik_name=str(t["torvik_name"]),
            espn_id=str(t["espn_id"]),
            capture_excluded_illinois=bool(
                t.get("capture_excluded_illinois", False)))
            for t in doc["teams"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CbbForwardError(
            "IDENTITY_CROSSWALK_INVALID",
            f"cannot load crosswalk at {path}: {exc}") from exc
    if not teams:
        raise CbbForwardError("IDENTITY_CROSSWALK_INVALID",
                              "crosswalk carries no teams")
    return Crosswalk(teams)


def illinois_excluded(team: CrosswalkTeam | None, espn_id: str,
                      institution_state: str | None = None) -> bool:
    """The scope module's rule, in its fail-closed form: an Illinois
    ESPN ID denies; an Illinois institution state denies; the
    crosswalk's exclusion flag denies."""
    if str(espn_id) in ILLINOIS_ESPN_DENYLIST:
        return True
    if institution_state is not None and str(
            institution_state).strip().upper() == "IL":
        return True
    return bool(team is not None and team.capture_excluded_illinois)


# ------------------------------------------------------------------
# Forward input: the morning-of Torvik vintage (reading R-1).
# ------------------------------------------------------------------

_LIVE_COLUMNS = ("team", "adjoe", "adjde", "adjt", "barthag")


@dataclass(frozen=True)
class TorvikVintage:
    slate_date: str
    sha256: str
    manifest: dict
    by_team: dict  # Torvik team name -> TeamRatings
    league_mean_eff: float
    league_mean_tempo: float
    team_rows: int


def _parse_live_vintage(raw: bytes) -> tuple[dict, float, float, int]:
    try:
        text = raw.decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise CbbForwardError("TORVIK_VINTAGE_SCHEMA_INVALID",
                              f"unreadable csv: {exc}") from exc
    if not rows:
        raise CbbForwardError("TORVIK_VINTAGE_SCHEMA_INVALID",
                              "vintage carries no rows")
    header = rows[0].keys()
    for col in _LIVE_COLUMNS:
        if col not in header:
            raise CbbForwardError(
                "TORVIK_VINTAGE_SCHEMA_INVALID",
                f"missing required column {col!r}")
    by_team: dict[str, TeamRatings] = {}
    effs: list[float] = []
    tempos: list[float] = []
    for row in rows:
        name = (row.get("team") or "").strip()
        try:
            adj_o = float(row["adjoe"])
            adj_d = float(row["adjde"])
            tempo = float(row["adjt"])
            barthag = float(row["barthag"])
        except (TypeError, ValueError) as exc:
            raise CbbForwardError(
                "TORVIK_VINTAGE_SCHEMA_INVALID",
                f"unparseable ratings row for {name!r}") from exc
        if not name or not all(math.isfinite(v) for v in
                               (adj_o, adj_d, tempo, barthag)):
            raise CbbForwardError("TORVIK_VINTAGE_SCHEMA_INVALID",
                                  f"invalid ratings row for {name!r}")
        if not 0.0 < barthag < 1.0:
            raise CbbForwardError(
                "TORVIK_VINTAGE_SCHEMA_INVALID",
                f"barthag out of (0,1) for {name!r}")
        ratings = TeamRatings(adj_o=adj_o, adj_d=adj_d, adj_tempo=tempo)
        if name in by_team and by_team[name] != ratings:
            raise CbbForwardError(
                "TORVIK_VINTAGE_SCHEMA_INVALID",
                f"conflicting duplicate rows for team {name!r}")
        by_team[name] = ratings
        effs.append(adj_o)
        tempos.append(tempo)
    if not 300 <= len(rows) <= 400:
        raise CbbForwardError(
            "TORVIK_VINTAGE_SCHEMA_INVALID",
            f"team row count {len(rows)} outside the D1 envelope")
    league_mean_eff = sum(effs) / len(effs)
    league_mean_tempo = sum(tempos) / len(tempos)
    return by_team, league_mean_eff, league_mean_tempo, len(rows)


def load_vintage(slate_date: str, store_dir) -> TorvikVintage:
    """Load and verify the morning-of vintage for ``slate_date``.

    Reading R-1: the forward input for a game on date D is D's own
    morning-of live-route vintage. A missing vintage, a vintage whose
    manifest date is not the slate date, a hash/byte disagreement, or
    a LATE_PULL-flagged vintage (Amendment 1 section 7: valid for
    later dates only, never as a pre-game snapshot for the flagged
    date) is a named NO_DATA refusal for the whole slate.
    """
    store = Path(store_dir)
    csv_path = store / f"{slate_date}.csv"
    json_path = store / f"{slate_date}.json"
    if not csv_path.is_file() or not json_path.is_file():
        raise CbbForwardError(
            "TORVIK_VINTAGE_MISSING",
            f"no morning-of vintage pair for slate date {slate_date} "
            f"in {store}")
    try:
        manifest = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CbbForwardError("TORVIK_VINTAGE_UNAVAILABLE",
                              f"manifest unreadable: {exc}") from exc
    if manifest.get("refusal"):
        raise CbbForwardError(
            "TORVIK_VINTAGE_UNAVAILABLE",
            f"pull recorded a refusal: {manifest['refusal']}")
    sha = manifest.get("sha256")
    if not sha or manifest.get("evidence_state") != "verified-by-pull":
        raise CbbForwardError(
            "TORVIK_VINTAGE_UNAVAILABLE",
            "manifest does not attest a verified pull")
    if manifest.get("as_of_local_date") != slate_date:
        raise CbbForwardError(
            "TORVIK_VINTAGE_DATE_MISMATCH",
            f"vintage is for {manifest.get('as_of_local_date')}, "
            f"slate date is {slate_date}")
    warning = manifest.get("snapshot_warning")
    if warning:
        raise CbbForwardError(
            "TORVIK_VINTAGE_LATE_PULL",
            f"vintage flagged {warning}; a late pull is never a "
            "pre-game snapshot for its own date")
    raw = csv_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        manifest_bytes = (None if manifest.get("bytes") is None
                          else int(manifest["bytes"]))
        manifest_rows = (None if manifest.get("team_rows") is None
                         else int(manifest["team_rows"]))
    except (TypeError, ValueError) as exc:
        raise CbbForwardError(
            "TORVIK_VINTAGE_UNAVAILABLE",
            f"manifest carries non-integer size fields: {exc}") from exc
    if digest != sha or (manifest_bytes is not None
                         and len(raw) != manifest_bytes):
        raise CbbForwardError(
            "TORVIK_VINTAGE_HASH_MISMATCH",
            "vintage bytes disagree with the pull manifest")
    by_team, mean_eff, mean_tempo, n_rows = _parse_live_vintage(raw)
    if manifest_rows is not None and manifest_rows != n_rows:
        raise CbbForwardError(
            "TORVIK_VINTAGE_SCHEMA_INVALID",
            "parsed row count disagrees with the pull manifest")
    return TorvikVintage(slate_date=slate_date, sha256=digest,
                         manifest=manifest, by_team=by_team,
                         league_mean_eff=mean_eff,
                         league_mean_tempo=mean_tempo,
                         team_rows=n_rows)


# ------------------------------------------------------------------
# Shared runner machinery: quotes, slate games, record writing.
# ------------------------------------------------------------------

def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_ts(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class PairedQuote:
    """One two-sided entry quote from a lane capture.

    ``line`` is the line as captured for side A (for SPREAD, side A is
    the away team and the line is the away spread, matching the
    shared intake parser's convention; for TOTAL and TEAM_TOTAL the
    sides are OVER and UNDER). A side's price or timestamp is None
    when the capture did not carry it; the runners refuse such quotes
    with named codes rather than completing them.
    """

    line: float | None
    side_a_price: int | None
    side_b_price: int | None
    side_a_captured_at: str | None
    side_b_captured_at: str | None
    capture_source: str = "DK_CAPTURE"


@dataclass(frozen=True)
class CbbSlateGame:
    """One slate game with its identity and entry capture quotes.

    Identity is carried by ESPN event/team IDs and resolved through
    the crosswalk; DraftKings display names are never identity.
    ``entry_quotes`` keys are the family's market sections: SPREAD /
    TOTAL for the efficiency family, TEAM_TOTAL_AWAY /
    TEAM_TOTAL_HOME for the team-totals readout (the capture-scope
    module's section names).
    """

    espn_event_id: str
    slate_date: str
    away_espn_id: str
    home_espn_id: str
    neutral_site: bool
    tip_utc: str
    entry_quotes: dict = field(default_factory=dict)
    institution_state_away: str | None = None
    institution_state_home: str | None = None


def price_ok(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(float(value)):
        return False
    return value <= -100 or value >= 100


def line_ok(value, *, positive: bool) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(float(value)):
        return False
    return float(value) > 0.0 if positive else True


def implied_prob(price: float) -> float:
    price = float(price)
    return (-price) / (-price + 100.0) if price < 0 else 100.0 / (
        price + 100.0)


def no_vig_pair(price_a: float, price_b: float) -> tuple[float, float]:
    pa, pb = implied_prob(price_a), implied_prob(price_b)
    total = pa + pb
    return pa / total, pb / total


def quote_refusal(pair: PairedQuote | None, *, positive_line: bool,
                  tip: datetime | None) -> str | None:
    """The named refusal for an unusable entry quote, or None.

    Order mirrors the frozen NFL runner: capture presence, freshness
    (both sides exist and were captured before tip), price validity,
    line validity. The CBB designs carry NO close-validity or
    freshness-window terms (gap G-3); pre-tip presence is the only
    temporal rule the build applies, and it is a capture-integrity
    rule, not a close rule.
    """
    if pair is None:
        return "ENTRY_CAPTURE_MISSING"
    if (pair.side_a_price is None or pair.side_b_price is None
            or pair.side_a_captured_at is None
            or pair.side_b_captured_at is None):
        return "ENTRY_SINGLE_SIDED"
    cap_a, cap_b = parse_ts(pair.side_a_captured_at), parse_ts(
        pair.side_b_captured_at)
    if cap_a is None or cap_b is None:
        return "ENTRY_CAPTURE_TIMESTAMP_INVALID"
    if tip is not None and (cap_a >= tip or cap_b >= tip):
        return "ENTRY_NOT_PRE_EVENT"
    if not price_ok(pair.side_a_price) or not price_ok(pair.side_b_price):
        return "PRICE_INVALID"
    if not line_ok(pair.line, positive=positive_line):
        return "LINE_INVALID"
    return None


def write_entry_records(records: list[dict], out_path) -> Path:
    """Create-only record write (the frozen NFL runner's rule): a run
    writes its records exactly once; an existing file is a refusal,
    never an overwrite."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, sort_keys=True) + "\n"
                      for r in records)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise CbbForwardError(
            "RECORD_FILE_EXISTS",
            f"refusing to overwrite existing records at {path}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(payload)
    return path
