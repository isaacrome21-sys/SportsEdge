from pathlib import Path
import re

USES = re.compile(r"\buses:\s*([^\s#]+)")
IMMUTABLE = re.compile(r"^[^/@\s]+/[^@\s]+@[0-9a-fA-F]{40}$")


def test_all_marketplace_actions_are_pinned_to_immutable_commit_sha():
    failures = []
    for path in sorted(Path(".github/workflows").glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        for ref in USES.findall(text):
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            if not IMMUTABLE.fullmatch(ref):
                failures.append(f"{path}:{ref}")
    assert failures == [], "MUTABLE_ACTION_REFERENCES:" + ",".join(failures)
