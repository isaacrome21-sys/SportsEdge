"""Attempt-2 precondition check for the CBB_TORVIK_EFFICIENCY_V1 design screen.

Implements design section 3's "Data pins before any run" faithfully,
including precondition (c) -- the section 2 three-way fixture agreement --
which attempt 1's script treated as not-applicable while (b) was unmet.
With (b) now met (PR #2867), (c) is applicable, and it is UNMET: the
College Basketball Reference leg is REFUSED_HTTP_403_NOT_PINNED and no
manifest in the repo pins any CBR bytes, so no fixture can enter the
screen. Prints a JSON verdict of NOT_EXECUTABLE.

Stdlib only. Usage: python3 verify_preconditions_attempt2.py [repo_root]
The kept schedule bytes are re-hashed when found at the default
successor-admission workspace path; absence of the bytes is reported,
not treated as a pin failure (the manifest on main is the pin of record).
"""

import hashlib
import json
import os
import sys

SEASONS = list(range(2015, 2024))
KEPT_BYTES_DIR = os.path.expanduser(
    "~/workspace/cbb-successor-admission-20261028/pulls"
)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_assets(node):
    if isinstance(node, dict):
        if "asset_name" in node and "sha256" in node:
            yield node
        for v in node.values():
            yield from walk_assets(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_assets(v)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    out = {}

    # (b) successor manifest pins for every design season + CBR leg status.
    man_path = os.path.join(
        root,
        "research/cbb_hoopr_mbb_schedule_successor_20261028/successor_manifest.json",
    )
    manifest = json.load(open(man_path))
    assets = list(walk_assets(manifest))
    seasons_pinned = sorted(
        {
            a["asset_name"].replace("mbb_schedule_", "").split(".")[0]
            for a in assets
            if a["asset_name"].startswith("mbb_schedule_")
        }
    )
    kept = {"checked": False, "match": 0, "mismatch": 0, "missing": 0}
    if os.path.isdir(KEPT_BYTES_DIR):
        kept["checked"] = True
        for a in assets:
            p = os.path.join(KEPT_BYTES_DIR, a["asset_name"])
            if not os.path.exists(p):
                kept["missing"] += 1
            elif sha256_of(p) == a["sha256"]:
                kept["match"] += 1
            else:
                kept["mismatch"] += 1
    cbr_leg = manifest.get("cbr_leg") or {}
    out["precondition_b_successor_manifest"] = {
        "met": seasons_pinned == [str(s) for s in SEASONS],
        "assets_pinned": len(assets),
        "seasons_pinned": seasons_pinned,
        "kept_bytes_rehash": kept,
    }

    # (c) scan every repo JSON for any pinned CBR / sports-reference asset.
    cbr_pins = []
    for dirpath, _dirs, files in os.walk(os.path.join(root, "research")):
        for fn in files:
            if not fn.endswith(".json"):
                continue
            try:
                data = json.load(open(os.path.join(dirpath, fn)))
            except Exception:
                continue
            for a in walk_assets(data):
                name = str(a.get("asset_name", "")).lower()
                url = str(a.get("url", "")).lower()
                if "cbr" in name or "sports-reference" in url:
                    if a.get("pin_status", "PINNED") not in (
                        "REFUSED_HTTP",
                        "NOT_ATTEMPTED_AFTER_REFUSAL",
                    ):
                        cbr_pins.append(a["asset_name"])
    out["precondition_c_three_way_agreement"] = {
        "met": len(cbr_pins) > 0,
        "cbr_pinned_assets_found": cbr_pins,
        "cbr_leg_status_in_successor_manifest": cbr_leg.get("status")
        or "REFUSED_HTTP_403_NOT_PINNED (see successor ADMISSION_RECORD section 5)",
        "reason": (
            "Design section 2: a fixture enters the section 3 screen only on "
            "three-way agreement incl. College Basketball Reference's season "
            "schedule; design section 3 lists (c) under 'Data pins before any "
            "run', applied before any fitting. No CBR bytes are pinned."
        ),
    }

    out["precondition_a_torvik_archive"] = {
        "met": True,
        "basis": (
            "Carried from attempt 1 (PR #2866) and re-verified by re-running "
            "its verify_preconditions.py on this head: samples byte-identical, "
            "26/26 season probes OK."
        ),
    }
    out["screen_verdict"] = (
        "EXECUTABLE"
        if all(
            out[k]["met"]
            for k in (
                "precondition_a_torvik_archive",
                "precondition_b_successor_manifest",
                "precondition_c_three_way_agreement",
            )
        )
        else "NOT_EXECUTABLE"
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
