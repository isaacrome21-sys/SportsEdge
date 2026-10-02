"""Outcome-blind materialization of SportsDataverse-native CFB candidate inputs.

Emits the full dual-snapshot row contract required by all four candidate families:
  home_metrics / away_metrics               -- authoritative pregame snapshot
  home_prior_metrics / away_prior_metrics   -- prior-season final snapshot (always present)
  home_current_metrics / away_current_metrics -- in-season through_week W-1,
                                                  or same as prior for week-1 rows

Fail-closed policy:
  Week 0/1, season 2015: row skipped (no 2014 data in frozen window).
  Week 0/1, season 2016+: prior-season snapshot REQUIRED; raises on missing.
  Week 2+: BOTH current-season W-1 AND prior-season snapshot REQUIRED;
            raises on either missing. Silent substitution is prohibited because
            it would silently alter the registered model definition for the three
            advanced candidate families.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .sportsdataverse_history import TeamSnapshot, SOURCE_CONTRACT
from .sportsdataverse_manifest import build_manifest

FEATURES = (
    "off_ppa_rush", "off_ppa_dropback",
    "def_ppa_rush_allowed", "def_ppa_dropback_allowed",
    "off_success_rate", "def_success_rate_allowed",
    "standard_down_ppa", "passing_down_success_rate",
    "explosive_rate", "net_field_position",
)


class SDVMaterializationError(ValueError):
    pass


def _snapshot_to_metrics(snap: TeamSnapshot, sample_source: str) -> dict[str, Any]:
    """Convert a TeamSnapshot to the metrics dict the candidate families expect.

    Embeds identity fields (season, through_week, sample_source, games_in_sample)
    alongside the 10 numeric metric keys so each family can validate the snapshot
    is the correct temporal slice without re-reading raw rows.
    """
    out: dict[str, Any] = {
        "season": snap.season,
        "through_week": snap.through_week,
        "sample_source": sample_source,
        "games_in_sample": snap.games_in_sample,
    }
    for key in FEATURES:
        out[key] = getattr(snap, key)
    return out


def _early_current_metrics(snap: TeamSnapshot, *, season: int, week: int) -> dict[str, Any]:
    """Represent an empty current-season sample without inventing metric values.

    The metric values are carried from the prior-season fallback so blend/switch
    families have numeric inputs, while games_in_sample is exactly zero. Families
    that key on sample size therefore fall back to prior values deterministically.
    """
    out = _snapshot_to_metrics(snap, "CURRENT_SEASON_EMPTY_PRIOR_VALUES")
    out["season"] = int(season)
    out["through_week"] = int(week) - 1
    out["games_in_sample"] = 0
    return out


def materialize_native_candidate_inputs(
    *,
    games: Sequence[Mapping[str, Any]],
    snapshots: Sequence[TeamSnapshot],
    prior_season_snapshots: Sequence[TeamSnapshot] = (),
) -> list[dict[str, Any]]:
    """Attach only pre-game snapshots. Scores/outcomes are deliberately ignored.

    Week 0/1 (season >= 2016): uses prior-season final snapshot as the authoritative
    pregame state (sample_source=PRIOR_SEASON_FALLBACK). Missing prior snapshot raises.

    Week 0/1 (season == 2015): skipped -- no 2014 data in frozen acquisition window.

    Week 2+: authoritative snapshot is current-season through_week W-1
    (sample_source=CURRENT_SEASON_PRIOR_WEEKS). BOTH the current snapshot AND the
    prior-season snapshot MUST be present. Missing either raises -- silent substitution
    is prohibited because it would silently alter the registered model definition for
    the three advanced candidate families that blend or switch between the two.

    All four candidate families receive:
      home_metrics / away_metrics               -- authoritative pregame snapshot
      home_prior_metrics / away_prior_metrics   -- prior-season final snapshot
      home_current_metrics / away_current_metrics -- in-season W-1; Week 0/1 carries
                                                      prior values with games_in_sample=0
    """
    # Index current-season snapshots: (team_id, season, through_week) -> TeamSnapshot
    idx: dict[tuple[int, int, int], TeamSnapshot] = {
        (s.team_id, s.season, s.through_week): s for s in snapshots
    }

    # Index prior-season snapshots: (team_id, prior_season) -> best (highest through_week)
    prior_idx: dict[tuple[int, int], TeamSnapshot] = {}
    for s in prior_season_snapshots:
        key = (s.team_id, s.season)
        existing = prior_idx.get(key)
        if existing is None or s.through_week > existing.through_week:
            prior_idx[key] = s

    out: list[dict[str, Any]] = []
    for raw in sorted(
        games, key=lambda r: (int(r["season"]), int(r["week"]), int(r["game_id"]))
    ):
        season, week = int(raw["season"]), int(raw["week"])
        if season >= 2026:
            raise SDVMaterializationError("CFB_SDV_2026_OUTCOMES_PROHIBITED")
        if week < 0:
            raise SDVMaterializationError("CFB_SDV_WEEK_INVALID")
        try:
            home_id, away_id = int(raw["home_id"]), int(raw["away_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SDVMaterializationError("CFB_SDV_GAME_IDENTITY_INVALID") from exc
        neutral_raw = raw.get("neutral_site")
        if type(neutral_raw) is bool:
            neutral_site = neutral_raw
        else:
            token = str(neutral_raw or "").strip().lower()
            if token in {"true", "1", "t"}:
                neutral_site = True
            elif token in {"false", "0", "f"}:
                neutral_site = False
            else:
                raise SDVMaterializationError(
                    f"CFB_SDV_NEUTRAL_SITE_REQUIRED:{raw.get('game_id')}"
                )

        if week <= 1:
            if season == 2015:
                # Frozen acquisition starts in 2015; no prior-season (2014) data.
                # This boundary condition has no admissible predictive state.
                continue

            # Week 0/1, season >= 2016: prior-season snapshot required.
            home_prior_snap = prior_idx.get((home_id, season - 1))
            away_prior_snap = prior_idx.get((away_id, season - 1))
            if home_prior_snap is None or away_prior_snap is None:
                raise SDVMaterializationError(
                    f"CFB_SDV_PRIOR_SEASON_SNAPSHOT_REQUIRED:{raw.get('game_id')}"
                )

            if home_prior_snap.source_contract != SOURCE_CONTRACT or \
               away_prior_snap.source_contract != SOURCE_CONTRACT:
                raise SDVMaterializationError("CFB_SDV_SOURCE_CONTRACT_MISMATCH")

            # Week 0/1: authoritative snapshot IS the prior-season fallback.
            # No in-season sample exists yet. Current-value placeholders use\n            # prior values, but their sample size is explicitly zero below.
            home_snap = home_prior_snap
            away_snap = away_prior_snap
            home_current_snap = home_prior_snap
            away_current_snap = away_prior_snap
            home_sample_source = "PRIOR_SEASON_FALLBACK"
            away_sample_source = "PRIOR_SEASON_FALLBACK"

        else:
            # Week 2+: BOTH current-season W-1 AND prior-season snapshots required.
            # Missing either is a hard error -- no silent substitution.
            home_snap = idx.get((home_id, season, week - 1))
            away_snap = idx.get((away_id, season, week - 1))
            if home_snap is None or away_snap is None:
                raise SDVMaterializationError(
                    f"CFB_SDV_PREGAME_SNAPSHOT_MISSING:{raw.get('game_id')}"
                )

            home_prior_snap = prior_idx.get((home_id, season - 1))
            away_prior_snap = prior_idx.get((away_id, season - 1))
            if home_prior_snap is None or away_prior_snap is None:
                # Fail closed: silent substitution would alter the registered
                # model definition for the three advanced candidate families.
                raise SDVMaterializationError(
                    f"CFB_SDV_PRIOR_SEASON_SNAPSHOT_REQUIRED_WEEK2:{raw.get('game_id')}"
                )

            if home_snap.source_contract != SOURCE_CONTRACT or \
               away_snap.source_contract != SOURCE_CONTRACT:
                raise SDVMaterializationError("CFB_SDV_SOURCE_CONTRACT_MISMATCH")

            home_current_snap = home_snap
            away_current_snap = away_snap
            home_sample_source = "CURRENT_SEASON_PRIOR_WEEKS"
            away_sample_source = "CURRENT_SEASON_PRIOR_WEEKS"

        # Build identity-enriched metric dicts for all four families
        home_metrics = _snapshot_to_metrics(home_snap, home_sample_source)
        away_metrics = _snapshot_to_metrics(away_snap, away_sample_source)
        home_prior_metrics = _snapshot_to_metrics(home_prior_snap, "PRIOR_SEASON_FALLBACK")
        away_prior_metrics = _snapshot_to_metrics(away_prior_snap, "PRIOR_SEASON_FALLBACK")
        if week <= 1:
            home_current_metrics = _early_current_metrics(home_prior_snap, season=season, week=week)
            away_current_metrics = _early_current_metrics(away_prior_snap, season=season, week=week)
        else:
            home_current_metrics = _snapshot_to_metrics(home_current_snap, home_sample_source)
            away_current_metrics = _snapshot_to_metrics(away_current_snap, away_sample_source)

        out.append({
            "game_id": str(raw["game_id"]),
            "season": season,
            "week": week,
            "home_id": home_id,
            "away_id": away_id,
            "neutral_site": neutral_site,
            # Authoritative pregame snapshot (all four families read this)
            "home_metrics": home_metrics,
            "away_metrics": away_metrics,
            # Dual-snapshot fields (three advanced families read these)
            "home_prior_metrics": home_prior_metrics,
            "away_prior_metrics": away_prior_metrics,
            "home_current_metrics": home_current_metrics,
            "away_current_metrics": away_current_metrics,
            # Convenience pass-through for GAMES_IN_SAMPLE_FEATURE family
            "home_games_in_sample": 0 if week <= 1 else home_snap.games_in_sample,
            "away_games_in_sample": 0 if week <= 1 else away_snap.games_in_sample,
            "source_contract": SOURCE_CONTRACT,
            "provenance_class": "RECONSTRUCTED_HISTORICAL_NOT_PIT",
        })
    return out


def manifest_native_inputs(
    *, rows: Any, source_datasets: Any, season: int, target_week: int
) -> Any:
    return build_manifest(
        season=season,
        target_week=target_week,
        datasets=source_datasets,
        feature_names=FEATURES,
    )
