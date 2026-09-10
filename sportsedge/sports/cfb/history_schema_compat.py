"""Audit captured historical-release schemas against frozen CFB model inputs.

This module is descriptive only.  Raw source-column availability is not proof that
a provider field has the exact semantics of the frozen ``CFBTeamMetrics`` field,
and neither source coverage nor semantic compatibility proves point-in-time
availability. Missing or uncertified inputs must not be imputed merely to make the
historical materializer run.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Mapping, Any


CFB_HISTORY_SCHEMA_COMPAT_V1 = "CFB_HISTORY_SCHEMA_COMPAT_V1"

REQUIRED_TEAM_METRICS = (
    "off_ppa_rush",
    "off_ppa_dropback",
    "def_ppa_rush_allowed",
    "def_ppa_dropback_allowed",
    "off_success_rate",
    "def_success_rate_allowed",
    "standard_down_ppa",
    "passing_down_success_rate",
    "eckel_rate",
    "points_per_eckel",
    "points_per_drive",
    "net_field_position",
    "explosive_rate",
)

# Candidate raw-source recipes only.  These establish that potentially relevant
# columns exist; they deliberately do NOT assert semantic equivalence with the
# canonical CFBD fields used by ``normalize_advanced_team_metrics``.
CANDIDATE_SOURCE_RECIPES: dict[str, tuple[tuple[str, str], ...]] = {
    "off_ppa_rush": (("adv_team", "EPA_rushing_per_play"),),
    "off_ppa_dropback": (("adv_team", "EPA_passing_per_play"),),
    "def_ppa_rush_allowed": (("adv_team_opponent_join", "EPA_rushing_per_play"),),
    "def_ppa_dropback_allowed": (("adv_team_opponent_join", "EPA_passing_per_play"),),
    "off_success_rate": (("adv_situational", "EPA_success_rate"),),
    "def_success_rate_allowed": (("adv_situational_opponent_join", "EPA_success_rate"),),
    "standard_down_ppa": (("adv_situational", "EPA_standard_down_per_play"),),
    "passing_down_success_rate": (("adv_situational", "EPA_success_passing_down_rate"),),
    "eckel_rate": (),
    "points_per_eckel": (),
    # Canonical live normalization computes season points / offensive drives.
    # Schedule score + drive rows may support a derivation, but that derivation is
    # not certified here because scoring/drive semantics must be proven first.
    "points_per_drive": (("schedules", "home_score"), ("adv_drives", "drives")),
    # Canonical live normalization is offense.averageStart - defense.averageStart.
    # A single avg_field_position column is therefore only a candidate ingredient.
    "net_field_position": (
        ("adv_drives", "avg_field_position"),
        ("adv_drives_opponent_join", "avg_field_position"),
    ),
    # CFBD canonical feature is offense.explosiveness; ESPN EPA_explosive_rate is
    # potentially related but must not be asserted equivalent without validation.
    "explosive_rate": (("adv_team", "EPA_explosive_rate"),),
}


@dataclass(frozen=True)
class CFBHistorySchemaCompatReport:
    contract: str
    status: str
    required_metrics: tuple[str, ...]
    candidate_source_coverage: tuple[str, ...]
    raw_source_fields_missing: tuple[str, ...]
    semantic_equivalence_proven: tuple[str, ...]
    semantic_equivalence_unproven: tuple[str, ...]
    point_in_time_proven: bool
    promotion_evidence: bool
    model_p_created: bool
    eligibility_changed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_cfb_history_schema_compat(
    *,
    columns_by_dataset: Mapping[str, Iterable[str]],
    semantic_equivalence_proven: Iterable[str] = (),
    point_in_time_proven: bool = False,
) -> CFBHistorySchemaCompatReport:
    """Audit raw field coverage and independently supplied semantic certification."""
    if type(point_in_time_proven) is not bool:
        raise ValueError("CFB_SCHEMA_COMPAT_PIT_BOOL_REQUIRED")

    normalized = {
        str(dataset): frozenset(str(column) for column in columns)
        for dataset, columns in columns_by_dataset.items()
    }
    covered: list[str] = []
    missing: list[str] = []
    for metric in REQUIRED_TEAM_METRICS:
        recipes = CANDIDATE_SOURCE_RECIPES[metric]
        if not recipes:
            missing.append(metric)
            continue
        ok = True
        for dataset, column in recipes:
            base_dataset = dataset.removesuffix("_opponent_join")
            if column not in normalized.get(base_dataset, frozenset()):
                ok = False
                break
        (covered if ok else missing).append(metric)

    certified = tuple(dict.fromkeys(str(x) for x in semantic_equivalence_proven))
    unknown = sorted(set(certified) - set(REQUIRED_TEAM_METRICS))
    if unknown:
        raise ValueError("CFB_SCHEMA_COMPAT_UNKNOWN_SEMANTIC_CERTIFICATION:" + ",".join(unknown))
    falsely_certified = sorted(set(certified) - set(covered))
    if falsely_certified:
        raise ValueError("CFB_SCHEMA_COMPAT_CERTIFICATION_WITHOUT_SOURCE:" + ",".join(falsely_certified))

    unproven = tuple(metric for metric in covered if metric not in set(certified))
    complete = not missing and not unproven
    return CFBHistorySchemaCompatReport(
        contract=CFB_HISTORY_SCHEMA_COMPAT_V1,
        status="SOURCE_SEMANTICS_COMPATIBLE" if complete else "SOURCE_SCHEMA_OR_SEMANTICS_INCOMPLETE",
        required_metrics=REQUIRED_TEAM_METRICS,
        candidate_source_coverage=tuple(covered),
        raw_source_fields_missing=tuple(missing),
        semantic_equivalence_proven=certified,
        semantic_equivalence_unproven=unproven,
        point_in_time_proven=point_in_time_proven,
        promotion_evidence=False,
        model_p_created=False,
        eligibility_changed=False,
    )
