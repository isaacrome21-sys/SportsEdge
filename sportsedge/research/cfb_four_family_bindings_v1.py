"""CFB four-family evaluation — REAL DATA BINDINGS. RESEARCH ONLY.

This module binds the three things the evaluation harness
(``sportsedge/research/cfb_four_family_evaluation_v1.py``) deliberately
left unbound:

1. the frozen production CFB engine, presented through the harness's
   ``ProbabilityProducer`` interface in the declared injury-neutral
   CAND-2 evaluation configuration (:class:`FrozenEngineProducer`);
2. content-addressed data snapshots — historical results, CFBD closing
   lines (descriptive only, labeled at ingest), and the team directory
   with season-effective FBS membership;
3. a dry-run manifest builder that enumerates exactly what a verdict
   run WOULD consume under the ruled configuration, without computing
   a single probability.

Machinery only. Building these bindings performs NO evaluation, scores
NO real game, emits NO verdict, and consumes NO attempt. The harness's
shipped configuration stays UNRULED with ``freeze_sha: null`` on this
branch; the owner's rulings (recorded in
``config/research/cfb_four_family_bindings_v1.json`` after Isaac
delegated the section-10 decisions on 2026-10-13) are carried by the
bindings layer and applied to the harness config only at freeze time.
Execution remains separately gated by an owner ruling.

Provenance discipline:

* Every snapshot is content-addressed: ``snapshot_id`` is the SHA-256
  of the canonical payload, verified on every load. A snapshot whose
  bytes do not match its id is refused, never repaired.
* Sources are pinned by hash in the bindings config (release digests
  and in-repo data-branch manifests for schedules; the
  CFB_HISTORICAL_MARKET_SOURCE_V1 pin for the lines archive; a git blob
  SHA-1 for the team directory table). The ingest CLI verifies every
  pin before a snapshot is built.
* The lines corpus is a retrospective archive with NO per-row
  timestamps (``per_row_pit_certified: false`` in its own source
  contract). Every market record this module emits carries
  ``DESCRIPTIVE_MARKET_COMPARISON_NOT_A_VERDICT``, and the loader
  refuses any record that does not — an unlabeled market record cannot
  leave this layer.
* Results records carry no per-record timestamps either (release-level
  retrieval only). Point-in-time honesty for results comes from the
  harness's walk-forward chronology, not from record timestamps; the
  bindings state this instead of inventing capture times.

This module performs no network access and no subprocess work. File
bytes arrive from the ingest CLI (``scripts/build_cfb_eval_snapshots.py``)
and results leave as in-memory records or canonical JSON bytes.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

from sportsedge.research import cfb_four_family_evaluation_v1 as harness
from sportsedge.research.cfb_four_family_evaluation_v1 import (
    DESCRIPTIVE_LABEL,
    CandidateGameInput,
    EvalConfig,
    FamilyProbabilities,
    GameLines,
    GameRecord,
    NonNeutralInputError,
    OwnerRulings,
    ResolvedConfig,
    build_candidate_input,
    classify_population,
    resolve_config,
)

RESULTS_SCHEMA = "SPORTSEDGE_CFB_RESULTS_SNAPSHOT_V1"
LINES_SCHEMA = "SPORTSEDGE_CFB_LINES_SNAPSHOT_V1"
DIRECTORY_SCHEMA = "SPORTSEDGE_CFB_DIRECTORY_SNAPSHOT_V1"

ENGINE_FILES = ("artifacts/free_models.py", "sportsedge/team_half_pricing.py")

#: Quarantine / flag vocabulary for the lines binding.
Q_ML_SPREAD_SIGN_INCONSISTENT = "ML_SPREAD_SIGN_INCONSISTENT"
Q_ML_CROSSCHECK_UNAVAILABLE = "ML_CROSSCHECK_UNAVAILABLE"
Q_SPREAD_ROWS_NOT_MIRRORED = "SPREAD_ROWS_NOT_MIRRORED"
Q_SPREAD_SIDE_MISSING = "SPREAD_SIDE_MISSING"
Q_TOTAL_ROWS_DISAGREE = "TOTAL_ROWS_DISAGREE"
Q_DUPLICATE_CONFLICTING_ROWS = "DUPLICATE_CONFLICTING_ROWS"
Q_MULTIPLE_KICKOFF_TIMESTAMPS = "MULTIPLE_KICKOFF_TIMESTAMPS"
FLAG_POST_KICKOFF_LINE_TIMESTAMP = "POST_KICKOFF_LINE_TIMESTAMP"
FLAG_TEAM_ID_MISMATCH = "TEAM_ID_MISMATCH_VS_RESULTS"
FLAG_ORPHAN_LINE_RECORD = "LINE_RECORD_WITHOUT_RESULTS_GAME"


class BindingError(Exception):
    """A binding cannot be established honestly. Fail closed."""


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _parse_kickoff(raw: str) -> datetime:
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise BindingError("kickoff timestamp without timezone: %r" % (raw,))
    return parsed.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Frozen-engine producer binding
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineIdentity:
    """The exact code identity of the bound engine: the commit the
    files were read from and the SHA-256 of every engine file whose
    constructions the producer uses. Recorded into every run manifest
    the binding produces."""

    source_commit: str
    file_sha256: Mapping[str, str]

    @classmethod
    def from_file_bytes(
        cls, files: Mapping[str, bytes], *, source_commit: str
    ) -> "EngineIdentity":
        if not source_commit:
            raise BindingError("ENGINE_IDENTITY_SOURCE_COMMIT_MISSING")
        missing = [path for path in ENGINE_FILES if path not in files]
        if missing:
            raise BindingError(
                "ENGINE_IDENTITY_FILES_MISSING: " + ",".join(sorted(missing))
            )
        return cls(
            source_commit=str(source_commit),
            file_sha256={path: _sha256(files[path]) for path in ENGINE_FILES},
        )

    def manifest_fragment(self) -> dict:
        return {
            "engine_source_commit": self.source_commit,
            "engine_file_sha256": dict(sorted(self.file_sha256.items())),
        }


def _decisive(win: float, push: float) -> float:
    """Condition an engine (win, push) pair on a decisive outcome — the
    conditioning the harness applies to every producer (BASE-1 uses the
    same renormalization for integer-line push mass)."""
    loss = 1.0 - win - push
    decisive = win + loss
    if decisive <= 0.0:
        raise BindingError("ENGINE_PROBABILITY_MASS_DEGENERATE")
    return win / decisive


class FrozenEngineProducer:
    """The production CFB engine, bound to the harness producer
    interface in the declared injury-neutral configuration (CAND-2).

    Probability constructions are the production ones, not
    reimplementations:

    * score means — ``artifacts.free_models.score_means`` (the helper
      kept in parity with ``calculate()``'s Lane A base model);
    * moneyline / spread / total — ``free_models.model_probability``
      on those means, exactly as ``calculate()`` Lane A invokes it;
    * team totals — the production full-game team-total construction
      in ``sportsedge.team_half_pricing`` (scale 1.0): the team's own
      score mean with sigma ``sqrt(sd_total^2 + sd_margin^2) / 2``
      through that module's ``_normal_outcome`` (imported private
      helper — the same wart the Form 2 adapter carries; flagged here
      rather than quietly reimplemented, because a reimplementation
      could silently diverge from production).

    Engine (win, push) pairs are conditioned on decisive outcomes
    before reaching the harness, matching BASE-1's construction.

    The adapter never fetches context and never sees a raw production
    context: it consumes only the harness's ``CandidateGameInput``,
    re-validated for neutrality on every call.
    """

    name = "FROZEN_PRODUCTION_CFB_ENGINE_CAND2_INJURY_NEUTRAL"

    def __init__(self, *, identity: EngineIdentity, config: EvalConfig):
        from artifacts import free_models as engine
        from sportsedge import team_half_pricing

        self._engine = engine
        self._team_half = team_half_pricing
        self._identity = identity
        self._config = config
        base, sd_total, sd_margin, hfa = engine.PRIORS["CFB"]
        if float(config.home_advantage_points) != float(hfa):
            raise BindingError(
                "ENGINE_HFA_MISMATCH: harness config home_advantage_points "
                "%r != production PRIORS CFB home advantage %r; the frozen "
                "engine applies its own constant, so a divergent config "
                "would misdescribe the evaluated object"
                % (config.home_advantage_points, hfa)
            )
        self._priors = {
            "base_points_per_team": base,
            "sd_total": sd_total,
            "sd_margin": sd_margin,
            "home_advantage_points": hfa,
        }
        # Full-game team-total sigma, production derivation
        # (team_half_pricing._estimate at scale 1.0).
        self._team_total_sigma = math.sqrt(sd_total**2 + sd_margin**2) / 2.0

    @classmethod
    def bind(
        cls, *, identity: EngineIdentity, config: EvalConfig
    ) -> "FrozenEngineProducer":
        """Bind, proving at bind time that the harness neutrality guard
        bites in both directions: a poisoned production-shaped context
        is neutralized by construction, and a non-neutral input handed
        straight to the producer is refused."""
        producer = cls(identity=identity, config=config)
        producer._neutrality_self_check()
        return producer

    def _neutrality_self_check(self) -> None:
        game = GameRecord(
            game_id="BIND_SELF_CHECK",
            season=2025,
            week=1,
            kickoff_utc=datetime(2025, 9, 1, tzinfo=timezone.utc),
            home_team_id="1",
            away_team_id="2",
            home_fbs=True,
            away_fbs=True,
            home_score=None,
            away_score=None,
        )
        poisoned = {
            "home_injury_pts": 4.5,
            "away_injury_pts": -2.0,
            "home_form": 1.2,
            "away_form": -0.7,
            "weather_total_adj": -3.0,
            "rest_diff_adj": 0.8,
            "starting_qb": 1.0,
        }
        neutral = build_candidate_input(
            game,
            home_rating=0.3,
            away_rating=-0.2,
            home_advantage_points=self._config.home_advantage_points,
            raw_context=poisoned,
        )
        try:
            neutral.validate_neutral()
        except NonNeutralInputError as exc:
            raise BindingError(
                "NEUTRALITY_SELF_CHECK_FAILED: harness construction did "
                "not neutralize a poisoned context: %s" % (exc,)
            ) from exc
        if "starting_qb" not in neutral.omitted_fields:
            raise BindingError(
                "NEUTRALITY_SELF_CHECK_FAILED: QB key was not recorded "
                "as omitted from the evaluation input"
            )
        if "home_injury_pts" not in neutral.neutralized_fields:
            raise BindingError(
                "NEUTRALITY_SELF_CHECK_FAILED: injury points were not "
                "recorded as neutralized in the evaluation input"
            )
        lines = GameLines(spread_home=-3.5, total=51.5,
                          team_total_home=27.5, team_total_away=24.0,
                          home_moneyline=-160, away_moneyline=140)
        via_neutral = self.family_probabilities(neutral, lines)
        clean = build_candidate_input(
            game,
            home_rating=0.3,
            away_rating=-0.2,
            home_advantage_points=self._config.home_advantage_points,
        )
        via_clean = self.family_probabilities(clean, lines)
        if via_neutral != via_clean:
            raise BindingError(
                "NEUTRALITY_SELF_CHECK_FAILED: neutralized poisoned "
                "context changed the probabilities; neutralization is "
                "labeled but not effective"
            )
        for bad_context in (
            {"home_rating": 0.0, "away_rating": 0.0, "starting_qb": 1.0},
            {"home_rating": 0.0, "away_rating": 0.0, "home_injury_pts": 0.5},
        ):
            bad = CandidateGameInput(game_id="BIND_SELF_CHECK", context=bad_context)
            try:
                self.family_probabilities(bad, lines)
            except NonNeutralInputError:
                continue
            raise BindingError(
                "NEUTRALITY_SELF_CHECK_FAILED: producer accepted a "
                "non-neutral input %r" % (bad_context,)
            )

    def family_probabilities(
        self, inp: CandidateGameInput, lines: GameLines
    ) -> FamilyProbabilities:
        inp.validate_neutral()
        engine = self._engine
        context = {
            key: float(inp.context.get(key, 0.0))
            for key in engine.CONTEXT_KEYS["CFB"]
        }
        home_mean, away_mean = engine.score_means("CFB", context)
        win, push = engine.model_probability(
            "CFB", "ML", "HOME", None, home_mean, away_mean
        )
        moneyline = _decisive(win, push)
        spread = None
        if lines.spread_home is not None:
            win, push = engine.model_probability(
                "CFB", "SPREAD", "HOME", float(lines.spread_home),
                home_mean, away_mean,
            )
            spread = _decisive(win, push)
        total = None
        if lines.total is not None:
            win, push = engine.model_probability(
                "CFB", "TOTAL", "OVER", float(lines.total),
                home_mean, away_mean,
            )
            total = _decisive(win, push)
        tt_home = None
        if lines.team_total_home is not None:
            win, push = self._team_half._normal_outcome(
                home_mean, self._team_total_sigma, "OVER",
                float(lines.team_total_home),
            )
            tt_home = _decisive(win, push)
        tt_away = None
        if lines.team_total_away is not None:
            win, push = self._team_half._normal_outcome(
                away_mean, self._team_total_sigma, "OVER",
                float(lines.team_total_away),
            )
            tt_away = _decisive(win, push)
        return FamilyProbabilities(
            moneyline_home_win=moneyline,
            spread_home_cover=spread,
            total_over=total,
            team_total_home_over=tt_home,
            team_total_away_over=tt_away,
        )

    def run_manifest_fragment(self) -> dict:
        fragment = self._identity.manifest_fragment()
        fragment.update(
            {
                "producer_name": self.name,
                "evaluated_object": harness.EVALUATED_OBJECT_INJURY_NEUTRAL,
                "engine_priors_cfb": dict(self._priors),
                "team_total_sigma_production_derivation": self._team_total_sigma,
                "probability_constructions": {
                    "moneyline": "free_models.model_probability(ML) on "
                                 "free_models.score_means",
                    "spread": "free_models.model_probability(SPREAD) on "
                              "free_models.score_means",
                    "total": "free_models.model_probability(TOTAL) on "
                             "free_models.score_means",
                    "team_total": "team_half_pricing._normal_outcome at "
                                  "scale 1.0, sigma sqrt(sd_total^2 + "
                                  "sd_margin^2)/2",
                    "conditioning": "engine (win, push) pairs conditioned "
                                    "on decisive outcomes, as BASE-1",
                },
                "neutral_configuration": {
                    "copied_keys": sorted(harness.ALLOWED_CONTEXT_KEYS),
                    "force_zero_keys": sorted(
                        k for k in harness.FORCE_ZERO_CONTEXT_KEYS
                        if k not in ("rest", "rest_adj")
                    ),
                    "forbidden_key_policy": "QB/availability keys ABSENT, "
                                            "guard-enforced per call",
                },
            }
        )
        return fragment


# --------------------------------------------------------------------------
# Team directory snapshot (binding c)
# --------------------------------------------------------------------------


def build_directory_snapshot(
    team_rows: Sequence[Mapping],
    *,
    provenance: Mapping,
    overrides: Mapping,
) -> dict:
    """Build the directory snapshot payload from parsed team-table
    rows. ``team_rows`` arrive from the ingest CLI (the upstream table
    is parquet; parsing it is an IO concern, not a bindings concern)."""
    teams: dict[str, dict] = {}
    for row in team_rows:
        team_id = str(row.get("team_id") or "").strip()
        if not team_id:
            raise BindingError("DIRECTORY_TEAM_ROW_WITHOUT_ID")
        if team_id in teams:
            raise BindingError("DIRECTORY_DUPLICATE_TEAM_ID: " + team_id)
        teams[team_id] = {
            "school": str(row.get("school") or ""),
            "abbreviation": str(row.get("abbreviation") or ""),
            "conference": str(row.get("conference") or ""),
            "classification": str(row.get("classification") or "").strip().lower(),
        }
    if not teams:
        raise BindingError("DIRECTORY_EMPTY")
    override_teams = {}
    for entry in overrides.get("teams", ()):  # bindings-config shape
        override_teams[str(entry["team_id"])] = {
            "school": entry["school"],
            "table_classification": entry["table_classification"],
            "fcs_seasons": [int(s) for s in entry.get("fcs_seasons", ())],
            "fbs_seasons": [int(s) for s in entry.get("fbs_seasons", ())],
        }
        team_id = str(entry["team_id"])
        if team_id not in teams:
            raise BindingError(
                "DIRECTORY_OVERRIDE_TEAM_NOT_IN_TABLE: " + team_id
            )
        if teams[team_id]["classification"] != entry["table_classification"]:
            raise BindingError(
                "DIRECTORY_OVERRIDE_BASE_MISMATCH: team %s table "
                "classification %r != override basis %r"
                % (team_id, teams[team_id]["classification"],
                   entry["table_classification"])
            )
    payload = {
        "schema": DIRECTORY_SCHEMA,
        "source": dict(provenance),
        "classification_basis": (
            "CURRENT_STATE_TABLE_PLUS_SEASON_EFFECTIVE_OVERRIDES"
        ),
        "overrides_version": overrides.get("version"),
        "overrides_status": overrides.get("status"),
        "teams": teams,
        "overrides": override_teams,
        "team_count": len(teams),
    }
    return {"snapshot_id": _sha256(_canonical(payload)), "payload": payload}


class DirectorySnapshot:
    """The bound team directory: identity for every team id in the
    source table, current-state classification, and season-effective
    FBS membership after the declared overrides."""

    def __init__(self, snapshot: Mapping):
        payload = snapshot.get("payload") or {}
        if payload.get("schema") != DIRECTORY_SCHEMA:
            raise BindingError("DIRECTORY_SNAPSHOT_SCHEMA_MISMATCH")
        if snapshot.get("snapshot_id") != _sha256(_canonical(payload)):
            raise BindingError("DIRECTORY_SNAPSHOT_HASH_MISMATCH")
        self._payload = payload
        self._teams: Mapping[str, Mapping] = payload["teams"]
        self._overrides: Mapping[str, Mapping] = payload.get("overrides") or {}

    @property
    def snapshot_id(self) -> str:
        return _sha256(_canonical(self._payload))

    @property
    def payload(self) -> Mapping:
        return self._payload

    def known_team_ids(self) -> frozenset:
        return frozenset(self._teams)

    def school(self, team_id: str) -> Optional[str]:
        row = self._teams.get(str(team_id))
        return row["school"] if row else None

    def classification_for(self, season: int, team_id: str) -> Optional[str]:
        team_id = str(team_id)
        row = self._teams.get(team_id)
        if row is None:
            return None
        override = self._overrides.get(team_id)
        if override:
            if int(season) in override.get("fbs_seasons", ()):
                return "fbs"
            if int(season) in override.get("fcs_seasons", ()):
                return "fcs"
        return row["classification"] or None

    def is_fbs(self, season: int, team_id: str) -> bool:
        return self.classification_for(season, team_id) == "fbs"


# --------------------------------------------------------------------------
# Results / fixture snapshot (binding a)
# --------------------------------------------------------------------------

_SCHEDULE_REQUIRED_COLUMNS = frozenset(
    {
        "game_id", "season", "week", "game_date", "home_id", "away_id",
        "home_team", "away_team", "home_score", "away_score", "status",
    }
)


def _schedule_rows(data: bytes, season: int) -> list[dict]:
    try:
        text = gzip.decompress(data).decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BindingError(
            "SCHEDULE_FILE_UNREADABLE season %s: %s" % (season, exc)
        ) from exc
    reader = csv.DictReader(io.StringIO(text))
    missing = _SCHEDULE_REQUIRED_COLUMNS - frozenset(reader.fieldnames or ())
    if missing:
        raise BindingError(
            "SCHEDULE_SCHEMA_MISSING_COLUMNS season %s: %s"
            % (season, ",".join(sorted(missing)))
        )
    return list(reader)


def _score_or_none(raw) -> Optional[int]:
    text = str(raw or "").strip()
    if not text:
        return None
    value = float(text)
    if not value.is_integer():
        raise BindingError("SCHEDULE_SCORE_NOT_INTEGRAL: %r" % (raw,))
    return int(value)


def build_results_snapshot(
    season_files: Mapping[int, bytes],
    directory: DirectorySnapshot,
    *,
    source_records: Mapping,
) -> dict:
    """Ingest the pinned schedule files into the results snapshot.

    FBS flags are stamped per game from the directory's
    season-effective classification. Records carry no per-record
    timestamps — the source has none — and the payload says so.
    """
    games: list[dict] = []
    seen: set[str] = set()
    per_season: dict[str, dict] = {}
    unresolved_teams: set[str] = set()
    for season in sorted(season_files):
        rows = _schedule_rows(season_files[season], int(season))
        decided = 0
        for row in rows:
            game_id = str(row["game_id"]).strip()
            if not game_id:
                raise BindingError(
                    "SCHEDULE_ROW_WITHOUT_GAME_ID season %s" % (season,)
                )
            if game_id in seen:
                raise BindingError("RESULTS_DUPLICATE_GAME_ID: " + game_id)
            seen.add(game_id)
            if int(float(row["season"])) != int(season):
                raise BindingError(
                    "SCHEDULE_SEASON_MISMATCH file %s row game %s"
                    % (season, game_id)
                )
            kickoff = _parse_kickoff(row["game_date"])
            home_id = str(row["home_id"]).strip()
            away_id = str(row["away_id"]).strip()
            home_class = directory.classification_for(int(season), home_id)
            away_class = directory.classification_for(int(season), away_id)
            if home_class is None:
                unresolved_teams.add(home_id)
            if away_class is None:
                unresolved_teams.add(away_id)
            home_score = _score_or_none(row.get("home_score"))
            away_score = _score_or_none(row.get("away_score"))
            if home_score is not None and away_score is not None:
                decided += 1
            games.append(
                {
                    "game_id": game_id,
                    "season": int(season),
                    "week": int(float(row["week"])),
                    "kickoff_utc": _iso(kickoff),
                    "home_team_id": home_id,
                    "away_team_id": away_id,
                    "home_team_name": str(row.get("home_team") or ""),
                    "away_team_name": str(row.get("away_team") or ""),
                    "home_classification": home_class,
                    "away_classification": away_class,
                    "home_fbs": home_class == "fbs",
                    "away_fbs": away_class == "fbs",
                    "home_score": home_score,
                    "away_score": away_score,
                    "status": str(row.get("status") or ""),
                    "season_type": str(row.get("season_type") or ""),
                    "neutral_site": str(row.get("neutral_site") or "").lower()
                    in ("true", "1"),
                }
            )
        per_season[str(season)] = {"rows": len(rows), "decided": decided}
    games.sort(key=lambda g: (g["kickoff_utc"], g["game_id"]))
    payload = {
        "schema": RESULTS_SCHEMA,
        "source": dict(source_records),
        "per_record_timestamps": (
            "ABSENT — the source release carries retrieval timestamps "
            "per file, never per game; PIT discipline for results is "
            "the harness walk-forward chronology over kickoff_utc"
        ),
        "per_season": per_season,
        "game_count": len(games),
        "unresolved_team_ids": sorted(unresolved_teams),
        "games": games,
    }
    return {"snapshot_id": _sha256(_canonical(payload)), "payload": payload}


def load_results_snapshot(data: bytes) -> tuple[dict, list[GameRecord]]:
    """Verify and load a results snapshot into harness GameRecords."""
    snapshot = json.loads(data.decode("utf-8"))
    payload = snapshot.get("payload") or {}
    if payload.get("schema") != RESULTS_SCHEMA:
        raise BindingError("RESULTS_SNAPSHOT_SCHEMA_MISMATCH")
    if snapshot.get("snapshot_id") != _sha256(_canonical(payload)):
        raise BindingError("RESULTS_SNAPSHOT_HASH_MISMATCH")
    games: list[GameRecord] = []
    previous: Optional[tuple] = None
    for record in payload["games"]:
        key = (record["kickoff_utc"], record["game_id"])
        if previous is not None and key < previous:
            raise BindingError("RESULTS_SNAPSHOT_NOT_CHRONOLOGICALLY_SORTED")
        previous = key
        games.append(
            GameRecord(
                game_id=record["game_id"],
                season=int(record["season"]),
                week=int(record["week"]),
                kickoff_utc=_parse_kickoff(record["kickoff_utc"]),
                home_team_id=record["home_team_id"],
                away_team_id=record["away_team_id"],
                home_fbs=bool(record["home_fbs"]),
                away_fbs=bool(record["away_fbs"]),
                home_score=record["home_score"],
                away_score=record["away_score"],
                no_contest=record["home_score"] is None
                or record["away_score"] is None,
            )
        )
    return payload, games


# --------------------------------------------------------------------------
# CFBD closing-lines snapshot (binding b) — descriptive only
# --------------------------------------------------------------------------


def _american_or_none(raw) -> Optional[int]:
    text = str(raw or "").strip()
    if not text:
        return None
    value = float(text)
    if not value.is_integer() or value == 0:
        return None
    return int(value)


def _line_or_none(raw) -> Optional[float]:
    text = str(raw or "").strip()
    if not text:
        return None
    return float(text)


def _game_schools(game_desc: str) -> Optional[tuple[str, str]]:
    if "@" not in game_desc:
        return None
    away, home = game_desc.split("@", 1)
    away, home = away.strip(), home.strip()
    if not away or not home:
        return None
    return away, home


def build_lines_snapshot(
    archive_csv_gz: bytes,
    *,
    designated_provider: str,
    seasons: Sequence[int],
    source_record: Mapping,
) -> dict:
    """Ingest the pinned CFBD-era lines archive into the descriptive
    lines snapshot.

    Structural rules enforced at ingest:

    * every emitted record carries the descriptive label — there is no
      code path that builds a market record without it;
    * moneyline sides are assigned by school identity (``abbr`` vs the
      ``game_desc`` schools, both CFBD names) and cross-checked against
      the spread favorite's sign; a contradiction quarantines the
      game's moneyline for that provider — the pair is never silently
      swapped, and the spread/total are retained (their attribution
      was verified independently against schedule team ids);
    * spread rows must mirror exactly and total rows must agree, or
      that market is quarantined for the game;
    * team totals are never emitted: the corpus carries no team-total
      lines, and deriving them from spread/total is a construction
      that requires its own preregistration ruling.
    """
    season_set = {int(s) for s in seasons}
    try:
        text = gzip.decompress(archive_csv_gz).decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BindingError("LINES_ARCHIVE_UNREADABLE: %s" % (exc,)) from exc
    grouped: dict[tuple[str, str], dict] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        try:
            season = int(float(row["season"]))
        except (TypeError, ValueError):
            continue
        if season not in season_set:
            continue
        book = str(row.get("book") or "").strip()
        game_id = str(row.get("game_id") or "").strip()
        if game_id.endswith(".0"):
            game_id = game_id[:-2]
        if not book or not game_id:
            continue
        bucket = grouped.setdefault(
            (book, game_id),
            {
                "season": season,
                "game_desc": str(row.get("game_desc") or ""),
                "date_time": str(row.get("date_time") or ""),
                "date_times": set(),
                "home_team_id": str(row.get("home_team_id") or "").strip(),
                "away_team_id": str(row.get("away_team_id") or "").strip(),
                "markets": {},
            },
        )
        bucket["date_times"].add(str(row.get("date_time") or ""))
        market = str(row.get("market_type") or "").strip()
        abbr = str(row.get("abbr") or "").strip()
        bucket["markets"].setdefault(market, {}).setdefault(abbr, []).append(row)

    coverage: dict[str, dict] = {}
    quarantine: list[dict] = []
    records: dict[str, dict] = {}

    def note(book: str, kind: str) -> None:
        coverage.setdefault(
            book,
            {
                "games_with_any_market": 0,
                "moneyline_ok": 0,
                "moneyline_quarantined": 0,
                "spread_ok": 0,
                "spread_quarantined": 0,
                "total_ok": 0,
                "total_quarantined": 0,
            },
        )[kind] += 1

    for (book, game_id), bucket in sorted(grouped.items()):
        schools = _game_schools(bucket["game_desc"])
        markets = bucket["markets"]
        quarantined: list[dict] = []

        def quarantine_market(market: str, reason: str) -> None:
            quarantined.append({"market": market, "reason": reason})
            if book == designated_provider:
                quarantine.append(
                    {"game_id": game_id, "provider": book,
                     "market": market, "reason": reason}
                )
            note(book, "%s_quarantined" % ("moneyline" if market == "money_line" else market))

        note(book, "games_with_any_market")
        spread_home: Optional[float] = None
        total: Optional[float] = None
        home_ml: Optional[int] = None
        away_ml: Optional[int] = None
        ml_crosscheck = "NOT_AVAILABLE"

        if schools is not None and "spread" in markets:
            rows = markets["spread"]
            home_rows = rows.get(schools[1], [])
            away_rows = rows.get(schools[0], [])
            home_vals = {_line_or_none(r.get("lines")) for r in home_rows}
            away_vals = {_line_or_none(r.get("lines")) for r in away_rows}
            home_vals.discard(None)
            away_vals.discard(None)
            if len(home_vals) > 1 or len(away_vals) > 1:
                quarantine_market("spread", Q_DUPLICATE_CONFLICTING_ROWS)
            elif not home_vals or not away_vals:
                quarantine_market("spread", Q_SPREAD_SIDE_MISSING)
            elif abs(next(iter(home_vals)) + next(iter(away_vals))) > 1e-9:
                quarantine_market("spread", Q_SPREAD_ROWS_NOT_MIRRORED)
            else:
                spread_home = next(iter(home_vals))
                note(book, "spread_ok")
        if schools is not None and "total" in markets:
            rows = markets["total"]
            values = set()
            for abbr in ("over", "under", "Over", "Under"):
                for r in rows.get(abbr, []):
                    value = _line_or_none(r.get("lines"))
                    if value is not None:
                        values.add(value)
            if len(values) > 1:
                quarantine_market("total", Q_DUPLICATE_CONFLICTING_ROWS)
            elif not values:
                quarantine_market("total", Q_TOTAL_ROWS_DISAGREE)
            else:
                total = next(iter(values))
                note(book, "total_ok")
        if schools is not None and "money_line" in markets:
            rows = markets["money_line"]
            home_vals = {
                _american_or_none(r.get("odds")) for r in rows.get(schools[1], [])
            }
            away_vals = {
                _american_or_none(r.get("odds")) for r in rows.get(schools[0], [])
            }
            home_vals.discard(None)
            away_vals.discard(None)
            if len(home_vals) > 1 or len(away_vals) > 1:
                quarantine_market("money_line", Q_DUPLICATE_CONFLICTING_ROWS)
            elif home_vals and away_vals:
                candidate_home = next(iter(home_vals))
                candidate_away = next(iter(away_vals))
                if spread_home is None or spread_home == 0:
                    # The attribution defect this cross-check catches
                    # is undetectable without a non-zero spread: an
                    # unchecked pair is quarantined, never admitted on
                    # trust (a flipped pair would invert the market
                    # probability in the descriptive comparison).
                    quarantine_market(
                        "money_line", Q_ML_CROSSCHECK_UNAVAILABLE
                    )
                else:
                    favorite_ml = (
                        candidate_home if spread_home < 0 else candidate_away
                    )
                    dog_ml = (
                        candidate_away if spread_home < 0 else candidate_home
                    )
                    if favorite_ml < 0 < dog_ml:
                        ml_crosscheck = "PASS"
                        home_ml, away_ml = candidate_home, candidate_away
                        note(book, "moneyline_ok")
                    else:
                        quarantine_market(
                            "money_line", Q_ML_SPREAD_SIGN_INCONSISTENT
                        )
        if book != designated_provider:
            continue
        if len(bucket["date_times"]) != 1:
            quarantine.append(
                {"game_id": game_id, "provider": book, "market": "ALL",
                 "reason": Q_MULTIPLE_KICKOFF_TIMESTAMPS}
            )
            continue
        if spread_home is None and total is None and home_ml is None:
            continue
        records[game_id] = {
            "label": DESCRIPTIVE_LABEL,
            "provider": book,
            "game_id": game_id,
            "season": bucket["season"],
            "date_time_utc": _iso(_parse_kickoff(bucket["date_time"])),
            "home_team_id": bucket["home_team_id"],
            "away_team_id": bucket["away_team_id"],
            "spread_home": spread_home,
            "total": total,
            "home_moneyline": home_ml,
            "away_moneyline": away_ml,
            "team_total_home": None,
            "team_total_away": None,
            "team_total_status": harness.NO_HISTORICAL_MARKET_COMPARATOR,
            "ml_crosscheck": ml_crosscheck,
            "markets_quarantined": quarantined,
        }
    payload = {
        "schema": LINES_SCHEMA,
        "label": DESCRIPTIVE_LABEL,
        "limitation": harness.DESCRIPTIVE_LIMITATION_TEXT,
        "source": dict(source_record),
        "designated_provider": designated_provider,
        "provider_coverage": coverage,
        "quarantine": sorted(
            quarantine, key=lambda q: (q["game_id"], q["market"])
        ),
        "team_total_availability": (
            "NONE_IN_CORPUS — no team-total lines exist in the CFBD-era "
            "archive; implied team totals derived from spread/total are "
            "NOT emitted (a construction requiring its own ruling)"
        ),
        "games": records,
        "game_count": len(records),
    }
    return {"snapshot_id": _sha256(_canonical(payload)), "payload": payload}


@dataclass
class LinesLoad:
    payload: dict
    lines_by_game: dict
    flags: list


def load_lines_snapshot(
    data: bytes, *, results_index: Mapping[str, Mapping]
) -> LinesLoad:
    """Verify and load the lines snapshot. Any record missing the
    descriptive label — or disagreeing with the results snapshot on
    fixture identity or kickoff — is refused a place in the emitted
    lines and surfaced as a flag. Nothing unlabeled, orphaned, or
    timestamped after its fixture's kickoff is ever emitted."""
    snapshot = json.loads(data.decode("utf-8"))
    payload = snapshot.get("payload") or {}
    if payload.get("schema") != LINES_SCHEMA:
        raise BindingError("LINES_SNAPSHOT_SCHEMA_MISMATCH")
    if snapshot.get("snapshot_id") != _sha256(_canonical(payload)):
        raise BindingError("LINES_SNAPSHOT_HASH_MISMATCH")
    if payload.get("label") != DESCRIPTIVE_LABEL:
        raise BindingError("LINES_SNAPSHOT_UNLABELED")
    lines_by_game: dict[str, GameLines] = {}
    flags: list[dict] = []
    for game_id, record in sorted((payload.get("games") or {}).items()):
        if record.get("label") != DESCRIPTIVE_LABEL:
            raise BindingError(
                "UNLABELED_MARKET_RECORD_REFUSED: game %s" % (game_id,)
            )
        result = results_index.get(game_id)
        if result is None:
            flags.append({"game_id": game_id, "flag": FLAG_ORPHAN_LINE_RECORD})
            continue
        if (
            record.get("home_team_id") != result["home_team_id"]
            or record.get("away_team_id") != result["away_team_id"]
        ):
            flags.append({"game_id": game_id, "flag": FLAG_TEAM_ID_MISMATCH})
            continue
        kickoff = _parse_kickoff(result["kickoff_utc"])
        stamped = _parse_kickoff(record["date_time_utc"])
        if stamped > kickoff:
            flags.append(
                {"game_id": game_id, "flag": FLAG_POST_KICKOFF_LINE_TIMESTAMP}
            )
            continue
        lines_by_game[game_id] = GameLines(
            spread_home=record["spread_home"],
            total=record["total"],
            team_total_home=record["team_total_home"],
            team_total_away=record["team_total_away"],
            home_moneyline=record["home_moneyline"],
            away_moneyline=record["away_moneyline"],
        )
    return LinesLoad(payload=payload, lines_by_game=lines_by_game, flags=flags)


# --------------------------------------------------------------------------
# Ruled configuration + dry-run manifest
# --------------------------------------------------------------------------


def ruled_config(bindings_cfg: Mapping) -> ResolvedConfig:
    """Construct the harness ResolvedConfig from the bindings layer's
    ruling record. The bindings record must show the rulings as RULED
    and must carry ``freeze_sha: null`` — the bindings never name a
    freeze; doing so here would be a preselection violation."""
    rulings_record = bindings_cfg.get("rulings") or {}
    if rulings_record.get("status") != "RULED":
        raise BindingError("BINDINGS_RULINGS_NOT_RECORDED_AS_RULED")
    if rulings_record.get("freeze_sha") is not None:
        raise BindingError(
            "BINDINGS_CARRY_A_FREEZE_SHA: naming the freeze is a "
            "reserved owner act at freeze time"
        )
    if rulings_record.get("execution_authorized"):
        raise BindingError("BINDINGS_MUST_NOT_AUTHORIZE_EXECUTION")
    rulings = OwnerRulings(
        candidate_mode=rulings_record["candidate_mode"],
        cfbd_role=rulings_record["cfbd_role"],
        cfbd_verification_steps_completed=bool(
            rulings_record.get("cfbd_verification_steps_completed", False)
        ),
        population_rule=rulings_record["population_rule"],
        fold_window=rulings_record["fold_window"],
    )
    return resolve_config(EvalConfig(rulings=rulings))


def _family_line_present(lines: Optional[GameLines], family: str) -> bool:
    if lines is None:
        return False
    if family == "moneyline":
        return lines.home_moneyline is not None and lines.away_moneyline is not None
    if family == "spread":
        return lines.spread_home is not None
    if family == "total":
        return lines.total is not None
    if family == "team_total":
        return lines.team_total_home is not None or lines.team_total_away is not None
    raise BindingError("unknown family %r" % (family,))


def build_dry_run_manifest(
    *,
    bindings_cfg: Mapping,
    results_snapshot_id: str,
    lines_snapshot_id: str,
    games: Sequence[GameRecord],
    lines_load: LinesLoad,
    directory: DirectorySnapshot,
    engine_fragment: Optional[Mapping] = None,
) -> dict:
    """Enumerate what a verdict run WOULD consume under the ruled
    configuration. Counts and coverage only: this builder accepts no
    producer, computes no probability, and consumes no attempt."""
    resolved = ruled_config(bindings_cfg)
    cfg = resolved.base
    population, exclusions = classify_population(
        games, resolved, known_team_ids=directory.known_team_ids()
    )
    lines_by_game = lines_load.lines_by_game

    exclusion_counts: dict[str, int] = {}
    for exclusion in exclusions:
        exclusion_counts[exclusion.reason] = (
            exclusion_counts.get(exclusion.reason, 0) + 1
        )
    unresolved_team_ids = sorted(
        {
            team_id
            for game in games
            if (
                game.home_team_id not in directory.known_team_ids()
                or game.away_team_id not in directory.known_team_ids()
            )
            for team_id in (game.home_team_id, game.away_team_id)
            if team_id not in directory.known_team_ids()
        }
    )

    folds: dict[str, dict] = {}
    pooled_matched = {family: 0 for family in harness.FAMILIES}
    for season in resolved.evaluation_seasons:
        fold_games = [g for g in population if g.season == season]
        families: dict[str, dict] = {}
        for family in harness.FAMILIES:
            matched = sum(
                1
                for g in fold_games
                if _family_line_present(lines_by_game.get(g.game_id), family)
            )
            pooled_matched[family] += matched
            families[family] = {
                "matched_games": matched,
                "coverage": (matched / len(fold_games)) if fold_games else 0.0,
                "coverage_floor": cfg.coverage_floor,
                "would_pass_coverage_gate": bool(
                    fold_games
                    and matched / len(fold_games) >= cfg.coverage_floor
                ),
                "fold_min_games": cfg.fold_min_games,
                "would_pass_fold_floor": matched >= cfg.fold_min_games,
            }
        folds[str(season)] = {
            "population_games": len(fold_games),
            "with_any_lines_record": sum(
                1 for g in fold_games if g.game_id in lines_by_game
            ),
            "families": families,
        }
    burn_in_population = [g for g in population if g.season in resolved.burn_in_seasons]
    burn_in_teams = {
        team_id
        for g in burn_in_population
        for team_id in (g.home_team_id, g.away_team_id)
    }
    eval_teams = {
        team_id
        for g in population
        if g.season in resolved.evaluation_seasons
        for team_id in (g.home_team_id, g.away_team_id)
    }
    cold_start_teams = sorted(eval_teams - burn_in_teams)
    lines_payload = lines_load.payload
    return {
        "manifest": "CFB_FOUR_FAMILY_DRY_RUN_MANIFEST_V1",
        "run_state": "NOT_RUN",
        "probabilities_computed": False,
        "attempts_consumed": 0,
        "freeze_sha": None,
        "freeze_status": (
            "NOT_ESTABLISHED — naming the freeze SHA is a reserved "
            "owner act at freeze time"
        ),
        "rulings_applied": {
            "candidate_mode": resolved.candidate_mode,
            "population_rule": bindings_cfg["rulings"]["population_rule"],
            "fold_window": bindings_cfg["rulings"]["fold_window"],
            "cfbd_role": resolved.cfbd_role,
            "decided_by": bindings_cfg["rulings"]["decided_by"],
        },
        "snapshots": {
            "results_snapshot_id": results_snapshot_id,
            "lines_snapshot_id": lines_snapshot_id,
            "directory_snapshot_id": directory.snapshot_id,
        },
        "engine_binding": dict(engine_fragment) if engine_fragment else None,
        "population": {
            "total_games_in_results_snapshot": len(games),
            "population_games": len(population),
            "excluded_games": len(exclusions),
            "exclusion_counts": dict(sorted(exclusion_counts.items())),
            "unresolved_team_ids": unresolved_team_ids,
            "burn_in_population_games": len(burn_in_population),
            "burn_in_distinct_teams": len(burn_in_teams),
            "evaluation_distinct_teams": len(eval_teams),
            "evaluation_teams_without_burn_in_evidence": len(cold_start_teams),
            "evaluation_teams_without_burn_in_evidence_sample": cold_start_teams[:25],
        },
        "folds": folds,
        "pooled": {
            family: {
                "matched_games": pooled_matched[family],
                "pooled_min_games": cfg.pooled_min_games,
                "would_pass_pooled_floor": pooled_matched[family]
                >= cfg.pooled_min_games,
            }
            for family in harness.FAMILIES
        },
        "market_data_descriptive_only": {
            "label": DESCRIPTIVE_LABEL,
            "designated_provider": lines_payload.get("designated_provider"),
            "designated_provider_status": (
                bindings_cfg.get("sources", {})
                .get("lines", {})
                .get("designated_provider_status")
            ),
            "provider_coverage": lines_payload.get("provider_coverage"),
            "quarantined_records_designated_provider": len(
                lines_payload.get("quarantine") or ()
            ),
            "load_flags": lines_load.flags,
            "team_total_availability": lines_payload.get(
                "team_total_availability"
            ),
        },
        "remaining_pre_flight": [
            "preregistration filed and frozen with an OWNER-NAMED freeze "
            "SHA (freeze_sha stays null until that moment)",
            "family-level registry adoption for CFB (integration lane)",
            "separate owner execution ruling before any scored run",
            "team_total historical lines: none exist in the CFBD corpus "
            "— the family cannot be scored historically unless a ruled "
            "source or a preregistered implied-line construction is "
            "adopted",
            "provider designation for the descriptive comparison is a "
            "bindings default (Bovada), to be pinned at freeze",
            "FBS membership override table is bindings-declared, to be "
            "ratified or replaced at freeze",
        ],
    }
