#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

# Keep this mapping centralized so the sweep is deterministic and reviewable.
PINS = {
    "actions/checkout@v4": "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
    "actions/checkout@v6": "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803",
    "actions/setup-python@v5": "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
    "actions/setup-python@v6": "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/cache@v4": "actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830",
    "actions/upload-artifact@v4": "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
}
USES = re.compile(r"^[ \t]*(?:-[ \t]+)?uses:[ \t]*(?P<ref>[^\s#]+)", re.MULTILINE)
SHA_REF = re.compile(r"^[^/@\s]+/[^@\s]+@[0-9a-fA-F]{40}$")


def main() -> int:
    changed = []
    failures = []
    for path in sorted(Path(".github/workflows").glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in PINS.items():
            text = text.replace(old, new)
        for match in USES.finditer(text):
            ref = match.group("ref")
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            if not SHA_REF.fullmatch(ref):
                failures.append(f"{path}:{ref}")
        if text != original:
            path.write_text(text, encoding="utf-8")
            changed.append(str(path))
    print("CHANGED_COUNT", len(changed))
    for path in changed:
        print("CHANGED", path)
    if failures:
        for failure in failures:
            print("MUTABLE_OR_UNKNOWN", failure)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
