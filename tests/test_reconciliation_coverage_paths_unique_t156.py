"""t156: every bundle_extensions coverage_paths list must be duplicate-free."""
import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "reconciliation_coverage_v1.json"


def test_bundle_coverage_paths_unique():
    data = json.loads(CONFIG.read_text())
    bundles = data["bundle_extensions"]
    assert "GLOBAL_PROMOTION_EVIDENCE_FREEZE_V2" in bundles
    for name, bundle in bundles.items():
        paths = bundle.get("coverage_paths") if isinstance(bundle, dict) else None
        if paths is None:
            continue
        dups = sorted({p for p in paths if paths.count(p) > 1})
        assert not dups, f"{name} duplicate coverage_paths: {dups}"
