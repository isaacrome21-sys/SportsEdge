"""Universal forward-validation framework (v1).

Config-driven forward-test evaluation for every SportsEdge market family,
generalizing the frozen NFL props Part 2 test. See README.md in this
package for the record contracts, the refusal rules, and how a family is
declared. Nothing in this package prices a market or changes any family's
registration, eligibility, or validation state: it judges priced records
against timestamped DraftKings captures, per the standing validation law.
"""
from .core import (  # noqa: F401
    CLV_MISSING_REASONS,
    VERDICTS,
    FamilyConfig,
    ForwardValidationRefusal,
    config_from_dict,
    evaluate_family,
    load_config,
)
from .nba_props import (  # noqa: F401
    evaluate_nba_props,
    evaluate_nba_props_v2,
    load_nba_config,
    verify_prereg_document,
)

__all__ = [
    "CLV_MISSING_REASONS",
    "VERDICTS",
    "FamilyConfig",
    "ForwardValidationRefusal",
    "config_from_dict",
    "evaluate_family",
    "evaluate_nba_props",
    "evaluate_nba_props_v2",
    "load_config",
    "load_nba_config",
    "verify_prereg_document",
]
