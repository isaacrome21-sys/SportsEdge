from pathlib import Path
import re

WORKFLOWS = Path(".github/workflows")
INSTALL_RE = re.compile(r"python\s+-m\s+pip\s+install\s+--disable-pip-version-check\s+([^\n]+)")
PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+==[^=<>!~\s]+$")


def _packages(spec: str):
    return [x.strip("'\"") for x in spec.split() if not x.startswith("-")]


def test_every_direct_workflow_python_dependency_is_exactly_pinned():
    failures = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        for match in INSTALL_RE.finditer(text):
            for package in _packages(match.group(1)):
                if package.startswith((".", "/")):
                    continue
                if not PACKAGE_RE.match(package):
                    failures.append(f"{path}:{package}")
    assert failures == [], "UNPINNED_WORKFLOW_DEPENDENCIES:" + ",".join(failures)
