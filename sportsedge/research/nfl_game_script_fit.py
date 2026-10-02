"""Frozen NFL game-script V1 research fitter.

Learns pass/rush workload multipliers from historical nflverse play-by-play.
The fit is market blind: raw PBP rows are projected through an explicit
whitelist before any aggregation. The resulting artifact is research-only and
cannot alter the unified NFL engine without a separate integration PR.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

PRELOCK_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "research"
    / "nfl_game_script_v1_prelock.json"
)

SCHEMA = "SPORTSEDGE_NFL_GAME_SCRIPT_V1_ARTIFACT"
STATUS = "FITTED_RESEARCH_ONLY_NOT_VALIDATED"
DEVELOPMENT_SEASONS = tuple(range(2016, 2025))
MIN_TEAM_SEASON_GAMES = 8
MIN_BUCKET_TEAM_GAMES = 100
MULTIPLIER_MIN = 0.40
MULTIPLIER_MAX = 1.80
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

MODEL_FIELDS = (
    "season",
    "season_type",
    "game_id",
    "posteam",
    "posteam_type",
    "home_score",
    "away_score",
    "pass_attempt",
    "rush_attempt",
    "qb_scramble",
    "qb_kneel",
)

BUCKETS = (
    ("LE_NEG15", None, -15),
    ("NEG14_NEG8", -14, -8),
    ("NEG7_NEG1", -7, -1),
    ("TIE", 0, 0),
    ("POS1_POS7", 1, 7),
    ("POS8_POS14", 8, 14),
    ("GE15", 15, None),
)


class NflGameScriptFitError(ValueError):
    pass


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def load_prelock(path: Path | None = None) -> dict[str, Any]:
    artifact = json.loads((path or PRELOCK_PATH).read_text())
    if artifact.get("schema") != "SPORTSEDGE_NFL_GAME_SCRIPT_V1_PRELOCK":
        raise NflGameScriptFitError("GAME_SCRIPT_PRELOCK_SCHEMA_INVALID")
    if artifact.get("status") != "FROZEN_BEFORE_SCORING":
        raise NflGameScriptFitError("GAME_SCRIPT_PRELOCK_STATUS_INVALID")
    seasons = tuple(int(x) for x in artifact["fit_window"]["seasons"])
    if seasons != DEVELOPMENT_SEASONS:
        raise NflGameScriptFitError("GAME_SCRIPT_PRELOCK_FIT_WINDOW_DRIFT")
    return artifact


def expected_pbp_uri(season: int) -> str:
    return (
        "https://github.com/nflverse/nflverse-data/releases/download/pbp/"
        f"play_by_play_{int(season)}.csv"
    )


def _number(value: Any, field: str) -> float:
    if value in (None, "") or isinstance(value, bool):
        raise NflGameScriptFitError(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NflGameScriptFitError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise NflGameScriptFitError(f"{field}:NONFINITE")
    return out


def _integer(value: Any, field: str) -> int:
    out = _number(value, field)
    if out != int(out):
        raise NflGameScriptFitError(f"{field}:INTEGER_REQUIRED")
    return int(out)


def _binary(value: Any, field: str) -> int:
    if value in (None, ""):
        return 0
    out = _integer(value, field)
    if out not in (0, 1):
        raise NflGameScriptFitError(f"{field}:BINARY_REQUIRED")
    return out


def _season(value: Any) -> int:
    season = _integer(value, "season")
    if season not in DEVELOPMENT_SEASONS:
        raise NflGameScriptFitError(f"FIT_ROW_OUTSIDE_DEVELOPMENT_WINDOW:{season}")
    return season


def project_model_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Whitelist only fields declared in the frozen pre-lock.

    nflverse PBP also ships historical spread/total/vegas-WP columns. They are
    deliberately ignored here rather than available to the estimator.
    """
    if not isinstance(raw, Mapping):
        raise NflGameScriptFitError("PBP_ROW_OBJECT_REQUIRED")
    return {field: raw.get(field) for field in MODEL_FIELDS}


def _play_kind(row: Mapping[str, Any]) -> str | None:
    if _binary(row.get("qb_kneel"), "qb_kneel"):
        return None
    if _binary(row.get("qb_scramble"), "qb_scramble"):
        return "RUSH"
    if _binary(row.get("pass_attempt"), "pass_attempt"):
        return "PASS"
    if _binary(row.get("rush_attempt"), "rush_attempt"):
        return "RUSH"
    return None


def _team_margin(row: Mapping[str, Any]) -> int:
    home = _integer(row.get("home_score"), "home_score")
    away = _integer(row.get("away_score"), "away_score")
    side = str(row.get("posteam_type") or "").strip().lower()
    if side == "home":
        return home - away
    if side == "away":
        return away - home
    raise NflGameScriptFitError("POSTEAM_TYPE_HOME_AWAY_REQUIRED")


def build_team_game_rows(
    pbp_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate raw PBP to one market-blind workload row per offense/team/game."""
    grouped: dict[tuple[int, str, str], dict[str, Any]] = {}
    for raw in pbp_rows:
        row = project_model_fields(raw)
        if str(row.get("season_type") or "").strip().upper() != "REG":
            continue
        season = _season(row.get("season"))
        game_id = str(row.get("game_id") or "").strip()
        team = str(row.get("posteam") or "").strip().upper()
        if not game_id or not team:
            continue

        kind = _play_kind(row)
        if kind is None:
            continue
        margin = _team_margin(row)
        key = (season, game_id, team)
        current = grouped.setdefault(
            key,
            {
                "season": season,
                "game_id": game_id,
                "team": team,
                "final_margin": margin,
                "pass_plays": 0,
                "rush_plays": 0,
            },
        )
        if current["final_margin"] != margin:
            raise NflGameScriptFitError(f"GAME_FINAL_MARGIN_INCONSISTENT:{game_id}:{team}")
        if kind == "PASS":
            current["pass_plays"] += 1
        else:
            current["rush_plays"] += 1

    rows = sorted(grouped.values(), key=lambda r: (r["season"], r["game_id"], r["team"]))
    if not rows:
        raise NflGameScriptFitError("TEAM_GAME_ROWS_EMPTY")
    for row in rows:
        if row["pass_plays"] <= 0 or row["rush_plays"] <= 0:
            raise NflGameScriptFitError(
                f"TEAM_GAME_WORKLOAD_NONPOSITIVE:{row['game_id']}:{row['team']}"
            )
    return rows


def _bucket_id(margin: int) -> str:
    for name, lo, hi in BUCKETS:
        if (lo is None or margin >= lo) and (hi is None or margin <= hi):
            return name
    raise NflGameScriptFitError(f"MARGIN_BUCKET_MISSING:{margin}")


def _validate_receipts(receipts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_season: dict[int, dict[str, Any]] = {}
    for raw in receipts:
        if not isinstance(raw, Mapping):
            raise NflGameScriptFitError("SOURCE_RECEIPT_OBJECT_REQUIRED")
        season = _integer(raw.get("season"), "receipt.season")
        if season not in DEVELOPMENT_SEASONS:
            raise NflGameScriptFitError(f"SOURCE_RECEIPT_OUTSIDE_FIT_WINDOW:{season}")
        uri = str(raw.get("source_uri") or "").strip()
        if uri != expected_pbp_uri(season):
            raise NflGameScriptFitError(f"SOURCE_URI_INVALID:{season}")
        digest = str(raw.get("raw_sha256") or "").strip().lower()
        if not _SHA256.fullmatch(digest):
            raise NflGameScriptFitError(f"SOURCE_SHA256_INVALID:{season}")
        stamp = str(raw.get("retrieved_at") or "").strip()
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise NflGameScriptFitError(f"SOURCE_RETRIEVED_AT_INVALID:{season}") from exc
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise NflGameScriptFitError(f"SOURCE_RETRIEVED_AT_TIMEZONE_REQUIRED:{season}")
        if season in by_season:
            raise NflGameScriptFitError(f"SOURCE_RECEIPT_DUPLICATE:{season}")
        by_season[season] = {
            "season": season,
            "source_uri": uri,
            "raw_sha256": digest,
            "retrieved_at": dt.isoformat(),
        }

    missing = sorted(set(DEVELOPMENT_SEASONS) - set(by_season))
    if missing:
        raise NflGameScriptFitError(
            "SOURCE_RECEIPTS_MISSING:" + ",".join(str(x) for x in missing)
        )
    return [by_season[season] for season in DEVELOPMENT_SEASONS]


def _normalized_games(
    team_games: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    normalized_input: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()

    for raw in team_games:
        season = _season(raw.get("season"))
        game_id = str(raw.get("game_id") or "").strip()
        team = str(raw.get("team") or "").strip().upper()
        if not game_id or not team:
            raise NflGameScriptFitError("TEAM_GAME_IDENTITY_REQUIRED")
        key = (season, game_id, team)
        if key in seen:
            raise NflGameScriptFitError(f"TEAM_GAME_DUPLICATE:{season}:{game_id}:{team}")
        seen.add(key)
        margin = _integer(raw.get("final_margin"), "final_margin")
        passes = _integer(raw.get("pass_plays"), "pass_plays")
        rushes = _integer(raw.get("rush_plays"), "rush_plays")
        if passes <= 0 or rushes <= 0:
            raise NflGameScriptFitError("TEAM_GAME_WORKLOAD_POSITIVE_REQUIRED")
        row = {
            "season": season,
            "game_id": game_id,
            "team": team,
            "final_margin": margin,
            "pass_plays": passes,
            "rush_plays": rushes,
        }
        normalized_input.append(row)
        grouped[(season, team)].append(row)

    out: list[dict[str, Any]] = []
    for (season, team), rows in sorted(grouped.items()):
        if len(rows) < MIN_TEAM_SEASON_GAMES:
            continue
        pass_sum = sum(row["pass_plays"] for row in rows)
        rush_sum = sum(row["rush_plays"] for row in rows)
        n_other = len(rows) - 1
        for row in rows:
            pass_base = (pass_sum - row["pass_plays"]) / n_other
            rush_base = (rush_sum - row["rush_plays"]) / n_other
            if pass_base <= 0 or rush_base <= 0:
                raise NflGameScriptFitError(
                    f"LEAVE_ONE_OUT_BASELINE_NONPOSITIVE:{season}:{team}"
                )
            out.append(
                {
                    **row,
                    "bucket": _bucket_id(row["final_margin"]),
                    "pass_ratio": row["pass_plays"] / pass_base,
                    "rush_ratio": row["rush_plays"] / rush_base,
                }
            )
    if not out:
        raise NflGameScriptFitError("NO_TEAM_SEASONS_MEET_MINIMUM_GAMES")
    return sorted(out, key=lambda r: (r["season"], r["game_id"], r["team"]))


def fit_game_script_v1(
    team_games: Sequence[Mapping[str, Any]],
    *,
    source_receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Fit the pre-registered V1 surface without touching validation data."""
    prelock = load_prelock()
    receipts = _validate_receipts(source_receipts)
    rows = _normalized_games(team_games)

    buckets: list[dict[str, Any]] = []
    for name, lo, hi in BUCKETS:
        members = [row for row in rows if row["bucket"] == name]
        if len(members) < MIN_BUCKET_TEAM_GAMES:
            raise NflGameScriptFitError(
                f"MARGIN_BUCKET_INSUFFICIENT:{name}:{len(members)}<{MIN_BUCKET_TEAM_GAMES}"
            )
        pass_multiplier = sum(row["pass_ratio"] for row in members) / len(members)
        rush_multiplier = sum(row["rush_ratio"] for row in members) / len(members)
        for metric, value in (
            ("pass_multiplier", pass_multiplier),
            ("rush_multiplier", rush_multiplier),
        ):
            if not MULTIPLIER_MIN <= value <= MULTIPLIER_MAX:
                raise NflGameScriptFitError(
                    f"FITTED_MULTIPLIER_OUT_OF_RANGE:{name}:{metric}:{value}"
                )
        buckets.append(
            {
                "id": name,
                "min_margin": lo,
                "max_margin": hi,
                "n_team_games": len(members),
                "pass_multiplier": pass_multiplier,
                "rush_multiplier": rush_multiplier,
                "mean_pass_ratio": pass_multiplier,
                "mean_rush_ratio": rush_multiplier,
            }
        )

    normalized_for_hash = [
        {
            key: row[key]
            for key in (
                "season",
                "game_id",
                "team",
                "final_margin",
                "pass_plays",
                "rush_plays",
            )
        }
        for row in rows
    ]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": STATUS,
        "prelock_sha256": canonical_sha256(prelock),
        "fit_window": {
            "seasons": list(DEVELOPMENT_SEASONS),
            "season_type": "REG",
        },
        "source_receipts": receipts,
        "team_game_rows_sha256": canonical_sha256(normalized_for_hash),
        "n_team_games": len(rows),
        "normalization": {
            "reference": "LEAVE_ONE_OUT_TEAM_SEASON_MEAN",
            "minimum_team_season_games": MIN_TEAM_SEASON_GAMES,
        },
        "estimator": {
            "minimum_team_games_per_bucket": MIN_BUCKET_TEAM_GAMES,
            "shrinkage": "NONE",
            "post_fit_clipping": False,
        },
        "buckets": buckets,
        "authority": {
            "research_only": True,
            "validated_2025": False,
            "changes_attempt9_owner": False,
            "creates_model_p": False,
            "truth_gate_authority": False,
            "official_authority": False,
            "promotion_authority": False,
            "staking_authority": False,
        },
    }
    payload["artifact_sha256"] = canonical_sha256(payload)
    return payload


def validate_artifact(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema") != SCHEMA:
        raise NflGameScriptFitError("GAME_SCRIPT_ARTIFACT_SCHEMA_INVALID")
    if artifact.get("status") != STATUS:
        raise NflGameScriptFitError("GAME_SCRIPT_ARTIFACT_STATUS_INVALID")
    expected = str(artifact.get("artifact_sha256") or "").lower()
    body = dict(artifact)
    body.pop("artifact_sha256", None)
    actual = canonical_sha256(body)
    if expected != actual:
        raise NflGameScriptFitError(f"GAME_SCRIPT_ARTIFACT_SHA_MISMATCH:{actual}")
    rows = artifact.get("buckets")
    if not isinstance(rows, list) or [row.get("id") for row in rows] != [
        name for name, _lo, _hi in BUCKETS
    ]:
        raise NflGameScriptFitError("GAME_SCRIPT_BUCKETS_INVALID")


def script_multipliers(
    artifact: Mapping[str, Any],
    *,
    final_margin: int,
) -> dict[str, Any]:
    """Return learned pass/rush multipliers for one simulated team margin."""
    validate_artifact(artifact)
    bucket = _bucket_id(int(final_margin))
    for row in artifact["buckets"]:
        if row["id"] == bucket:
            return {
                "bucket": bucket,
                "pass_multiplier": float(row["pass_multiplier"]),
                "rush_multiplier": float(row["rush_multiplier"]),
                "script_source": f"{SCHEMA}:{artifact['artifact_sha256']}",
            }
    raise NflGameScriptFitError(f"GAME_SCRIPT_BUCKET_NOT_FOUND:{bucket}")


__all__ = [
    "BUCKETS",
    "DEVELOPMENT_SEASONS",
    "MODEL_FIELDS",
    "NflGameScriptFitError",
    "build_team_game_rows",
    "expected_pbp_uri",
    "fit_game_script_v1",
    "load_prelock",
    "project_model_fields",
    "script_multipliers",
    "validate_artifact",
]
