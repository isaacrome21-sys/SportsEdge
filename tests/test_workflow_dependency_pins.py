from pathlib import Path
import re
import shlex

WORKFLOWS = Path(".github/workflows")
INSTALL_RE = re.compile(r"python\s+-m\s+pip\s+install\s+--disable-pip-version-check\s+([^\n]+)")
PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+==[^=<>!~\s]+$")


def _packages(spec: str, root: Path = Path("."), seen=frozenset()):
    tokens = iter(shlex.split(spec))
    packages = []
    for token in tokens:
        if token in {"-r", "--requirement"}:
            name = next(tokens, "")
            path = (root / name).resolve()
            if not name or path in seen or not path.is_file():
                raise ValueError("REQUIREMENTS_FILE_INVALID:" + name)
            for line in path.read_text().splitlines():
                line = line.partition("#")[0].strip()
                if line:
                    packages.extend(_packages(line, path.parent, seen | {path}))
        elif not token.startswith("-"):
            packages.append(token)
    return packages


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


def test_requirements_file_contents_are_checked(tmp_path):
    (tmp_path / "requirements.txt").write_text("pytest==9.1.1\nnumpy\n")
    packages = _packages("-r requirements.txt", tmp_path)
    assert packages == ["pytest==9.1.1", "numpy"]
    assert [p for p in packages if not PACKAGE_RE.match(p)] == ["numpy"]
