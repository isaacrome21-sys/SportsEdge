"""Market-context sidecars that must never enter predictive model features."""

from .myspariedge_props import (
    CONTEXT_LANE as MYSPARIEDGE_CONTEXT_LANE,
    MYSPARIEDGE_PROP_CONTRACT,
    ModelTrendDiagnostic,
    MySpariEdgeContextError,
    MySpariEdgePropObservation,
    MySpariEdgeSnapshot,
    PropTrendMatch,
    TrendWindow,
    compare_to_model as compare_myspariedge_to_model,
    find_prop_context as find_myspariedge_prop_context,
    parse_myspariedge_records,
    research_sidecar as myspariedge_research_sidecar,
)
from .public_splits import (
    PublicSplitObservation,
    PublicSplitSnapshot,
    PublicSplitsError,
    capture_vsin_cfb,
    compare_snapshots,
    diagnostics,
    parse_vsin_html,
)

__all__ = [
    "MYSPARIEDGE_CONTEXT_LANE",
    "MYSPARIEDGE_PROP_CONTRACT",
    "ModelTrendDiagnostic",
    "MySpariEdgeContextError",
    "MySpariEdgePropObservation",
    "MySpariEdgeSnapshot",
    "PropTrendMatch",
    "TrendWindow",
    "compare_myspariedge_to_model",
    "find_myspariedge_prop_context",
    "myspariedge_research_sidecar",
    "parse_myspariedge_records",
    "PublicSplitObservation",
    "PublicSplitSnapshot",
    "PublicSplitsError",
    "capture_vsin_cfb",
    "compare_snapshots",
    "diagnostics",
    "parse_vsin_html",
]
