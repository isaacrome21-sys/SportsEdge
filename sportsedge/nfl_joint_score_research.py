"""NFL joint-score RESEARCH factory: frozen PIT profiles -> simulator rows.

Owner ruling (Oct 15, 2026): NFL joint scores are ENABLED for explicitly
labeled RESEARCH cards after review; ordinary production eligibility stays
OFF and the probabilities are UNVALIDATED.  This module is the research
factory behind that ruling.  It is NOT wired into the production card path
(``artifacts/run_it_full.py`` never imports it), it never modifies the
canonical analytic engine (``artifacts/free_models``), and it consumes no
sealed evaluation attempt and touches no G2 material.

Why this exists: the canonical derivative stage
(``sportsedge.nfl_phone_derivative_pricing.phone_nfl_derivative_rows``)
prices team totals / periods / alternates ONLY from an independent joint
score distribution, and the analytic game engine emits none, so those rows
fail closed today (``NFL_TEAM_TOTAL_SCORE_DISTRIBUTION_EMPTY`` /
``SIMULATION_ROWS_EMPTY`` under ``NO_ENGINE``).  This factory supplies the
missing distribution from the integrated Engine A+C regulation simulator
(``sportsedge.core.simulate.regulation_simulator``), whose resolved path
emits a full market row (final + per-period scores) per simulated game.

Profile provenance / PIT discipline: team drive and special-teams profiles
come from the FROZEN fitted artifact
``artifacts/football/nfl_prop_artifact_bundle_v1.json`` (artifact version
``NFL_PROP_SHARED_PATH_2022_2025_V1``, fit scope REG seasons 2022-2025,
pinned by ``config/nfl_prop_model_freeze.json``).  The factory verifies the
freeze chain (bundle part hashes, payload canonical hash, source-manifest
hash) before trusting a single rate, and refuses to build profiles for any
game whose season is not strictly after the fit window -- a 2022-2025 fit
may never "predict" a game inside its own window.  No market data is read
anywhere in this module: profile payloads carrying market keys are refused
outright.  Lines enter only as pricer predicates in the harness layer,
after the distribution exists, exactly as the pricers require.

Known honesty limits (carried into every report this factory feeds):
* Field-position profiles have no frozen per-team fit in the repo; the
  frozen structural defaults of ``NFLFieldPositionProfile`` are used and
  their provenance is recorded as such.
* Special-teams rates are team-aggregate fit rates.  The simulator's
  kicker slot is labeled ``FROZEN_FIT_AGGREGATE:<TEAM>``; no named
  individual's participation or status is claimed or implied.
* The integrated simulator's own module declares its numerical inputs
  structural candidates with explicit validation blockers; the joint
  distribution's scoring level is NOT calibrated to real NFL scoring
  (see the factory REPORT).  Every output is therefore labeled
  research-only / NOT_VALIDATED, with all authority flags False.
"""
from __future__ import annotations

import base64
import gzip
import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from sportsedge.core.simulate.drive_play import TeamDriveProfile
from sportsedge.core.simulate.field_position import NFLFieldPositionProfile
from sportsedge.core.simulate.regulation_simulator import (
    NFLIntegratedRegulationSimulator,
)
from sportsedge.core.simulate.special_teams import SpecialTeamsProfile
from sportsedge.football_prop_run_machine import canonical_hash

RESEARCH_FAMILY = "NFL_JOINT_SCORE_RESEARCH_V1"
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_PATH = _REPO_ROOT / "artifacts" / "football" / "nfl_prop_artifact_bundle_v1.json"
DEFAULT_FREEZE_PATH = _REPO_ROOT / "config" / "nfl_prop_model_freeze.json"

RESEARCH_LABELS: dict[str, Any] = {
    "research_only": True,
    "validated": False,
    "validation_state": "NOT_VALIDATED",
    "official_authority": False,
    "model_p_authority": False,
    "staking_authority": False,
    "production_card_path": False,
    "distribution_family": RESEARCH_FAMILY,
}

# Market keys must never appear inside a profile payload: profiles are
# built from play data only (mirrors the V2K drive-source discipline).
_FORBIDDEN_MARKET_KEYS = frozenset({
    "spread", "closing_spread", "total", "closing_total", "moneyline",
    "home_odds", "away_odds", "odds", "price", "implied_probability",
    "market_probability", "line",
})

_DRIVE_FIELDS = (
    "pass_rate", "completion_rate", "success_rate", "explosive_rate",
    "turnover_rate", "sack_rate", "field_goal_attempt_rate",
    "field_goal_skill", "pace_seconds_mean",
)
_ST_FIELDS = (
    "fg_base_skill", "xp_make_rate", "two_point_attempt_rate",
    "two_point_success_rate",
)


class NFLJointScoreResearchError(ValueError):
    """Fail-closed refusal from the research factory."""


def _scan_forbidden_keys(value: Any, *, where: str) -> None:
    if isinstance(value, Mapping):
        for key, sub in value.items():
            if str(key).strip().lower() in _FORBIDDEN_MARKET_KEYS:
                raise NFLJointScoreResearchError(
                    f"NFL_JOINT_PROFILE_MARKET_KEY_FORBIDDEN:{where}:{key}")
            _scan_forbidden_keys(sub, where=where)
    elif isinstance(value, (list, tuple)):
        for sub in value:
            _scan_forbidden_keys(sub, where=where)


@dataclass(frozen=True)
class FrozenProfileSource:
    """A verified frozen fitted artifact usable as a profile source."""

    payload: Mapping[str, Any]
    bundle_path: str
    bundle_file_sha256: str
    artifact_canonical_sha256: str
    artifact_version: str
    source_manifest_sha256: str
    fit_seasons: tuple[int, ...]
    fit_season_type: str

    @property
    def fit_window_end_season(self) -> int:
        return max(self.fit_seasons)

    def provenance(self) -> dict[str, Any]:
        return {
            "source_artifact": self.bundle_path,
            "bundle_file_sha256": self.bundle_file_sha256,
            "artifact_canonical_sha256": self.artifact_canonical_sha256,
            "artifact_version": self.artifact_version,
            "source_manifest_sha256": self.source_manifest_sha256,
            "fit_seasons": list(self.fit_seasons),
            "fit_season_type": self.fit_season_type,
            "training_version": self.payload.get("training_version"),
        }


def load_frozen_profile_source(
    bundle_path: Path | str = DEFAULT_BUNDLE_PATH,
    freeze_path: Path | str = DEFAULT_FREEZE_PATH,
) -> FrozenProfileSource:
    """Load and verify the frozen NFL prop artifact as a profile source.

    Refuses (fail-closed) on any break in the freeze chain: freeze status,
    bundle hashes, canonical payload hash, or source-manifest hash.
    """
    bundle_file = Path(bundle_path)
    freeze = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN":
        raise NFLJointScoreResearchError("NFL_JOINT_FREEZE_STATUS_NOT_FROZEN")
    if freeze.get("promotion_authority") is not False:
        raise NFLJointScoreResearchError("NFL_JOINT_FREEZE_PROMOTION_AUTHORITY_INVALID")
    if str(freeze.get("sport") or "").upper() != "NFL":
        raise NFLJointScoreResearchError("NFL_JOINT_FREEZE_SPORT_MISMATCH")

    raw_bundle = bundle_file.read_bytes()
    bundle = json.loads(raw_bundle)
    if bundle.get("schema_version") != "FOOTBALL_PROP_ARTIFACT_BUNDLE_V1":
        raise NFLJointScoreResearchError("NFL_JOINT_BUNDLE_SCHEMA_MISMATCH")
    if bundle.get("encoding") != "GZIP_BASE64_CONCAT_V1":
        raise NFLJointScoreResearchError("NFL_JOINT_BUNDLE_ENCODING_MISMATCH")
    if bundle.get("promotion_authority") is not False:
        raise NFLJointScoreResearchError("NFL_JOINT_BUNDLE_PROMOTION_AUTHORITY_INVALID")
    if bundle.get("artifact_canonical_sha256") != freeze.get("artifact_sha256"):
        raise NFLJointScoreResearchError("NFL_JOINT_FREEZE_ARTIFACT_HASH_MISMATCH")

    compressed = b""
    for part in bundle.get("parts") or []:
        part_path = _REPO_ROOT / str(part["path"])
        text = part_path.read_text(encoding="utf-8").strip()
        if sha256(text.encode("utf-8")).hexdigest() != part.get("text_sha256"):
            raise NFLJointScoreResearchError(
                f"NFL_JOINT_BUNDLE_PART_HASH_MISMATCH:{part['path']}")
        compressed += base64.b64decode(text)
    if sha256(compressed).hexdigest() != bundle.get("compressed_sha256"):
        raise NFLJointScoreResearchError("NFL_JOINT_BUNDLE_COMPRESSED_HASH_MISMATCH")

    payload = json.loads(gzip.decompress(compressed))
    if canonical_hash(payload) != bundle["artifact_canonical_sha256"]:
        raise NFLJointScoreResearchError("NFL_JOINT_PAYLOAD_CANONICAL_HASH_MISMATCH")
    if payload.get("schema_version") != "FOOTBALL_PROP_MODEL_ARTIFACT_V1":
        raise NFLJointScoreResearchError("NFL_JOINT_PAYLOAD_SCHEMA_MISMATCH")
    if str(payload.get("sport") or "").upper() != "NFL":
        raise NFLJointScoreResearchError("NFL_JOINT_PAYLOAD_SPORT_MISMATCH")
    if payload.get("source_manifest_sha256") != freeze.get("source_manifest_sha256"):
        raise NFLJointScoreResearchError("NFL_JOINT_SOURCE_MANIFEST_HASH_MISMATCH")
    fit_scope = payload.get("fit_scope") or {}
    fit_seasons = tuple(int(s) for s in fit_scope.get("seasons") or [])
    if not fit_seasons:
        raise NFLJointScoreResearchError("NFL_JOINT_FIT_SEASONS_MISSING")

    return FrozenProfileSource(
        payload=payload,
        bundle_path=str(bundle_file.relative_to(_REPO_ROOT))
        if bundle_file.is_relative_to(_REPO_ROOT) else str(bundle_file),
        bundle_file_sha256=sha256(raw_bundle).hexdigest(),
        artifact_canonical_sha256=str(bundle["artifact_canonical_sha256"]),
        artifact_version=str(payload.get("artifact_version") or ""),
        source_manifest_sha256=str(payload.get("source_manifest_sha256") or ""),
        fit_seasons=fit_seasons,
        fit_season_type=str(fit_scope.get("season_type") or ""),
    )


@dataclass(frozen=True)
class TeamProfileBundle:
    team: str
    drive: TeamDriveProfile
    special_teams: SpecialTeamsProfile
    field_position: NFLFieldPositionProfile
    provenance: dict[str, Any]


@dataclass(frozen=True)
class GameProfileSet:
    home: TeamProfileBundle
    away: TeamProfileBundle
    season: int
    week: int
    pit_rule: str
    labels: dict[str, Any] = field(default_factory=lambda: dict(RESEARCH_LABELS))


def _team_bundle(source: FrozenProfileSource, team: str) -> TeamProfileBundle:
    drive_raw = (source.payload.get("team_drive_profiles") or {}).get(team)
    st_raw = (source.payload.get("team_special_teams_rates") or {}).get(team)
    if not isinstance(drive_raw, Mapping) or not isinstance(st_raw, Mapping):
        raise NFLJointScoreResearchError(f"NFL_JOINT_TEAM_PROFILE_MISSING:{team}")
    _scan_forbidden_keys(drive_raw, where=f"{team}:drive")
    _scan_forbidden_keys(st_raw, where=f"{team}:special_teams")
    missing = [f for f in _DRIVE_FIELDS if f not in drive_raw]
    if missing:
        raise NFLJointScoreResearchError(
            f"NFL_JOINT_DRIVE_FIELD_MISSING:{team}:{','.join(missing)}")
    missing_st = [f for f in _ST_FIELDS if f not in st_raw]
    if missing_st:
        raise NFLJointScoreResearchError(
            f"NFL_JOINT_SPECIAL_TEAMS_FIELD_MISSING:{team}:{','.join(missing_st)}")
    try:
        drive = TeamDriveProfile(**{f: drive_raw[f] for f in _DRIVE_FIELDS})
        special = SpecialTeamsProfile(
            team=team,
            kicker_id=f"FROZEN_FIT_AGGREGATE:{team}",
            kicker_active=True,
            **{f: st_raw[f] for f in _ST_FIELDS},
        )
    except (TypeError, ValueError) as exc:
        raise NFLJointScoreResearchError(
            f"NFL_JOINT_TEAM_PROFILE_INVALID:{team}:{exc}") from exc
    provenance = {
        "team": team,
        **source.provenance(),
        "field_position_provenance": (
            "STRUCTURAL_DEFAULT_FROZEN_CLASS:"
            "sportsedge.core.simulate.field_position.NFLFieldPositionProfile"),
        "kicker_provenance": (
            "AGGREGATE_FIT_TEAM_RATE: kicker slot is the frozen fit's "
            "team-aggregate kicking unit; no named individual's "
            "participation or status is claimed or implied"),
    }
    return TeamProfileBundle(
        team=team, drive=drive, special_teams=special,
        field_position=NFLFieldPositionProfile(team=team),
        provenance=provenance)


def build_game_profiles(
    source: FrozenProfileSource,
    *,
    home_team: str,
    away_team: str,
    season: int,
    week: int,
) -> GameProfileSet:
    """Assemble PIT-clean simulator profiles for one fixture.

    PIT rule: the frozen fit window covers full REG seasons; a fixture is
    eligible only when its season is strictly greater than every fit
    season, so no game inside (or before) the fit window can be priced
    from data that includes its own season.  ``as_of`` for every emitted
    profile is therefore the end of the fit window, recorded in the
    provenance of both team bundles.
    """
    home = str(home_team or "").strip().upper()
    away = str(away_team or "").strip().upper()
    if not home or not away or home == away:
        raise NFLJointScoreResearchError("NFL_JOINT_TEAM_IDENTITY_INVALID")
    if int(season) <= source.fit_window_end_season:
        raise NFLJointScoreResearchError(
            "NFL_JOINT_PROFILE_FIT_WINDOW_NOT_STRICTLY_PRIOR:"
            f"game_season={int(season)} fit_seasons={list(source.fit_seasons)}")
    return GameProfileSet(
        home=_team_bundle(source, home),
        away=_team_bundle(source, away),
        season=int(season), week=int(week),
        pit_rule=(
            "game season must be strictly after every fit season; "
            "profile as_of = end of fit window "
            f"({source.fit_window_end_season} {source.fit_season_type})"),
    )


def simulate_joint_score_rows(
    profiles: GameProfileSet,
    *,
    game_id: str,
    n_sims: int,
    base_seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the integrated A+C simulator into pricer-shaped joint score rows.

    Deterministic seed scheme: sim ``i`` uses ``base_seed + i`` (recorded
    in the manifest).  Every row is the simulator's own reconciled market
    row, stamped with the research labels and the profile provenance.
    """
    if int(n_sims) <= 0:
        raise NFLJointScoreResearchError("NFL_JOINT_N_SIMS_INVALID")
    if not str(game_id or "").strip():
        raise NFLJointScoreResearchError("NFL_JOINT_GAME_ID_REQUIRED")
    rows: list[dict[str, Any]] = []
    for i in range(int(n_sims)):
        result = NFLIntegratedRegulationSimulator(
            game_id=str(game_id),
            home_team=profiles.home.team,
            away_team=profiles.away.team,
            home_profile=profiles.home.drive,
            away_profile=profiles.away.drive,
            home_special_teams=profiles.home.special_teams,
            away_special_teams=profiles.away.special_teams,
            home_field_position=profiles.home.field_position,
            away_field_position=profiles.away.field_position,
            seed=int(base_seed) + i,
        ).simulate()
        result.assert_reconciliation()
        row = dict(result.resolved_path.to_scoring_path().to_market_row())
        if (row.get("home_score") != result.final_home_score
                or row.get("away_score") != result.final_away_score):
            raise NFLJointScoreResearchError(
                "NFL_JOINT_ROW_FINAL_SCORE_MISMATCH")
        row["simulation_index"] = i
        row["seed"] = int(base_seed) + i
        row.update(RESEARCH_LABELS)
        rows.append(row)
    home_scores = [float(r["home_score"]) for r in rows]
    away_scores = [float(r["away_score"]) for r in rows]
    manifest = {
        **RESEARCH_LABELS,
        "game_id": str(game_id),
        "home_team": profiles.home.team,
        "away_team": profiles.away.team,
        "season": profiles.season,
        "week": profiles.week,
        "n_sims": len(rows),
        "seed_scheme": "base_seed + simulation_index",
        "base_seed": int(base_seed),
        "mean_home_score": sum(home_scores) / len(home_scores),
        "mean_away_score": sum(away_scores) / len(away_scores),
        "mean_total": (sum(home_scores) + sum(away_scores)) / len(rows),
        "pit_rule": profiles.pit_rule,
        "profile_provenance": {
            "home": profiles.home.provenance,
            "away": profiles.away.provenance,
        },
        "calibration_warning": (
            "Joint distribution is NOT calibrated to real NFL scoring "
            "levels and is NOT validated against any baseline or market; "
            "probabilities derived from it are research artifacts only."),
    }
    return rows, manifest


def price_research_derivatives(
    rows: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    *,
    intake_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Price derivative intake rows through the canonical derivative stage.

    The stage (``phone_nfl_derivative_rows``) is called with this factory's
    rows as the fixture distribution -- the exact seam the stage was built
    for.  Its outputs already carry research-only stamps; this wrapper adds
    the family labels and the distribution manifest so provenance
    propagates into every priced output.  Lines on the intake rows are
    pricer predicates only; they never reach the factory or simulator.
    """
    from sportsedge.core.simulate.markets import derive_alternate_markets
    from sportsedge.nfl_phone_derivative_pricing import (
        ALTERNATE_MARKETS,
        fixture_key,
        phone_nfl_derivative_rows,
    )

    key = fixture_key(manifest["away_team"], manifest["home_team"])
    outcomes, receipts = phone_nfl_derivative_rows(
        list(intake_rows), distributions={key: list(rows)})

    # KNOWN STAGE DEFECT (documented, not hidden): the canonical stage
    # passes None for the unused alternate-lines argument, and
    # derive_alternate_markets iterates it, so a single-sided alternate
    # row errors (ALTERNATE_PRICER_ERROR) even with a valid distribution.
    # On the production path this changes nothing today (no distribution
    # is ever supplied there, so the pricer's SIMULATION_ROWS_EMPTY guard
    # fires first).  Here the stage outcomes stand as-is, and each failed
    # alternate row is ALSO priced directly against the pricer the stage
    # wraps, in a labeled supplement, so the research record shows both.
    supplements: list[dict[str, Any]] = []
    for idx, intake in enumerate(intake_rows):
        market = str(intake.get("market") or "").upper()
        if market not in ALTERNATE_MARKETS:
            continue
        outcome = outcomes[idx]
        if not str(outcome.get("reason") or "").startswith(
                "ALTERNATE_PRICER_ERROR"):
            continue
        line = intake.get("line")
        direct = derive_alternate_markets(
            list(rows),
            spread_lines=[line] if market in (
                "ALTERNATE_SPREAD", "ALT_SPREAD") and line is not None else (),
            total_lines=[line] if market in (
                "ALTERNATE_TOTAL", "ALT_TOTAL") and line is not None else ())
        supplements.append({
            **RESEARCH_LABELS,
            "intake_index": idx,
            "market": market,
            "line": line,
            "pricer": "derive_alternate_markets (direct; canonical stage "
                      "defect bypassed, stage outcome preserved above)",
            "model_probabilities": direct,
        })
    return {
        **RESEARCH_LABELS,
        "distribution_manifest": dict(manifest),
        "outcomes": outcomes,
        "receipts": receipts,
        "direct_pricer_supplements": supplements,
        "known_stage_defect": (
            "sportsedge/nfl_phone_derivative_pricing.py passes None for "
            "the unused alternate-lines argument into "
            "derive_alternate_markets, which iterates it: single-sided "
            "alternate rows fail with ALTERNATE_PRICER_ERROR whenever a "
            "distribution IS supplied. Production outcomes are unaffected "
            "today (no distribution is supplied on the canonical path). "
            "Fix belongs to the integration lane: pass () instead of None."
        ) if supplements else None,
    }
