import json
from pathlib import Path

from scripts.audit_null_defaults import scan_repo


def test_null_default_inventory_executes_repo_wide(capsys):
    hits = scan_repo(Path(".").resolve())
    print("NULL_DEFAULT_AUDIT_JSON=" + json.dumps(hits, sort_keys=True))
    assert isinstance(hits, list)
    assert all(hit.get("verdict") == "REVIEW_REQUIRED" for hit in hits)
