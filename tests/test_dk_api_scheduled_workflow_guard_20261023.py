"""Owner invariant: DraftKings data comes from rendered pages only.

Fails if any *scheduled* workflow (an active, uncommented `- cron:` line) imports or runs
a repo module -- transitively, via AST imports, `python -m`, `python path.py`, inline
`python - <<PY` heredocs and `unittest` targets -- whose source builds a DraftKings API URL
(`/sites/US-SB/api`, `sportsbook-nash.draftkings.com/api`, `api.draftkings.com`).

Grok ruling 2026-10-23 (under t234u): the DK-API workflows are manual-only
(workflow_dispatch); cron, push, pull_request and workflow_run triggers are removed.
Exception (ruling 2026-10-23c): the frozen nfl-2026-line-capture lane is untouched and
listed as FROZEN_LANE_EXCEPTION_OWNER_DECISION (reported, not failed).
No source module deleted; no collector run.
"""
import pytest
from pathlib import Path

import ast
import re
import textwrap
ROOT = Path(__file__).resolve().parents[1]
PAT = re.compile(r"sites/US-SB/api|sportsbook-nash\.draftkings\.com/api|api\.draftkings\.com")

def scheduled(text):
    return bool(re.search(r"^\s*-\s*cron\s*:", "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#")), re.M))

def on_triggers(text):
    """Top-level keys of the workflow `on:` block (comments ignored)."""
    keys, inside = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("#") or not line.strip():
            continue
        if re.match(r"^(on|\"on\"|'on'|true)\s*:", line):
            inside = True
            continue
        if inside:
            if not line.startswith(" "):
                break
            m = re.match(r"^  ([A-Za-z_][\w-]*)\s*:", line)
            if m:
                keys.append(m.group(1))
    return keys


def auto_triggered(text):
    return scheduled(text) or any(k != "workflow_dispatch" for k in on_triggers(text))


def entries(text):
    lines = [l for l in text.splitlines() if not l.lstrip().startswith("#")]
    body = "\n".join(lines)
    out = []
    # heredoc python
    for m in re.finditer(r"python3?\s+-\s+<<-?\s*['\"]?(\w+)['\"]?\s*\n(.*?)\n\s*\1\s*$", body, re.S | re.M):
        out.append(("inline", textwrap.dedent(m.group(2))))
    body2 = re.sub(r"\\\n", " ", body)
    for m in re.finditer(r"python3?\s+-m\s+([\w.]+)([^\n]*)", body2):
        mod, rest = m.group(1), m.group(2)
        if mod == "unittest":
            for t in re.findall(r"\b(tests\.[\w.]+)", rest):
                out.append(("module", t))
            d = re.search(r"-s\s+(\S+)", rest); p = re.search(r"-p\s+['\"]?([\w*.]+)", rest)
            if d and p:
                for f in sorted((ROOT / d.group(1)).glob(p.group(1))):
                    out.append(("file", str(f.relative_to(ROOT))))
        elif mod in ("pip", "py_compile", "pytest"):
            continue
        else:
            out.append(("module", mod))
    for m in re.finditer(r"python3?\s+((?:[\w.-]+/)*[\w.-]+\.py)\b", body2):
        out.append(("file", m.group(1)))
    return out

def mod_file(name):
    p = ROOT / Path(*name.split("."))
    for c in (p.with_suffix(".py"), p / "__init__.py"):
        if c.is_file():
            return c
    return None

def imports(path, src=None):
    src = src if src is not None else path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    pkg = None
    if path is not None:
        rel = path.relative_to(ROOT).with_suffix("")
        parts = list(rel.parts)
        pkg = parts[:-1] if parts[-1] != "__init__" else parts[:-1]
    names = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            if n.level and pkg is not None:
                base = pkg[:len(pkg) - (n.level - 1)] if n.level > 1 else pkg
                mod = ".".join(base + ([n.module] if n.module else []))
            else:
                mod = n.module or ""
            names.append(mod)
            names += [f"{mod}.{a.name}" for a in n.names]
    files = set()
    for nm in names:
        parts = nm.split(".")
        for i in range(1, len(parts) + 1):
            f = mod_file(".".join(parts[:i]))
            if f:
                files.add(f)
    return files

def closure(seeds):
    seen, stack, edges = set(), list(seeds), {}
    while stack:
        f = stack.pop()
        if f in seen:
            continue
        seen.add(f)
        for g in imports(f):
            edges.setdefault(g, f)
            stack.append(g)
    return seen, edges

def report_one(text):
    seeds = set()
    for kind, v in entries(text):
        if kind == "inline":
            seeds |= imports(None, v)
        elif kind == "module":
            f = mod_file(v); f and seeds.add(f)
        else:
            f = ROOT / v; f.is_file() and seeds.add(f)
    seen, _ = closure(seeds)
    return sorted(str(f.relative_to(ROOT)) for f in seen
                  if PAT.search(f.read_text(encoding="utf-8", errors="ignore")))


def report(root=None):
    res = {}
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
        text = wf.read_text(encoding="utf-8")
        if not scheduled(text):
            continue
        seeds, inline_imps = set(), set()
        for kind, v in entries(text):
            if kind == "inline":
                inline_imps |= imports(None, v)
            elif kind == "module":
                f = mod_file(v); f and seeds.add(f)
            else:
                f = ROOT / v; f.is_file() and seeds.add(f)
        seen, _ = closure(seeds | inline_imps)
        hits = sorted(str(f.relative_to(ROOT)) for f in seen if PAT.search(f.read_text(encoding="utf-8", errors="ignore")))
        res[wf.name] = hits
    return res



DK_API_WORKFLOWS = ("draftkings-prop-provider-probe.yml", "mlb-prop-pit-archive.yml",
                    "nfl-market-maker-radar-capture.yml", "mlb-moneyline-forward-evidence.yml",
                    "nfl-dk-direct-confirmation-capture.yml",
                    "sportsedge-auto-dk-four-sports.yml",
                    # live DK API request in CI (not mocked): dispatch-only (ruling 2026-10-23b)
                    "direct-dk-market-archive-contract.yml", "dk-nba-nhl-category-probe.yml")
# Grok ruling 2026-10-23c: frozen lanes never change mid-clock. nfl-2026-line-capture is a
# frozen confirmation lane (market-provider frozen-exclusion gate) that still reaches a DK
# API builder on cron. It is reported, not failed, until the owner decides.
FROZEN_LANE_EXCEPTION_OWNER_DECISION = ("nfl-2026-line-capture.yml",)
FROZEN_PATHS = ("scripts/nfl_2026_line_capture.py", "config/nfl_2026_capture.json",
                ".github/workflows/nfl-2026-line-capture.yml")
MAIN_BASE = "53a636afdda137f2bc7292282c961c86f1a2d9d4"
WF = ROOT / ".github" / "workflows"


def _scheduled_workflows():
    return sorted(p.name for p in WF.glob("*.y*ml") if scheduled(p.read_text(encoding="utf-8")))


@pytest.mark.parametrize("name", [n for n in _scheduled_workflows()
                                  if n not in FROZEN_LANE_EXCEPTION_OWNER_DECISION])
def test_scheduled_workflow_reaches_no_dk_api_module(name):
    assert report().get(name) == [], report().get(name)


@pytest.mark.parametrize("name", FROZEN_LANE_EXCEPTION_OWNER_DECISION)
def test_frozen_lane_exception_is_reported_not_failed(name):
    """Reported: still scheduled and still reaching a DK API builder (owner decision)."""
    import warnings
    text = (WF / name).read_text(encoding="utf-8")
    hits = report_one(text)
    assert scheduled(text) and hits, "exception no longer needed; remove it from the list"
    warnings.warn(f"FROZEN_LANE_EXCEPTION_OWNER_DECISION:{name}:{hits}")


def _git(*args):
    import subprocess
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    return r.returncode, r.stdout


@pytest.mark.parametrize("path", FROZEN_PATHS)
def test_frozen_lane_paths_byte_identical_to_main_base(path):
    code, blob = _git("show", f"{MAIN_BASE}:{path}")
    if code != 0:
        pytest.skip("main base commit not in this clone's history")
    assert (ROOT / path).read_bytes() == blob, path


def test_market_provider_frozen_exclusion_gate():
    """Same check as market-provider-contract.yml: no frozen path in the branch diff."""
    code, out = _git("diff", "--name-only", f"{MAIN_BASE}...HEAD")
    if code != 0:
        pytest.skip("main base commit not in this clone's history")
    changed = set(out.decode().split())
    assert not changed & set(FROZEN_PATHS), changed & set(FROZEN_PATHS)


@pytest.mark.parametrize("name", DK_API_WORKFLOWS)
def test_dk_api_workflow_is_dispatch_only(name):
    """Grok ruling 2026-10-23 (t234u): manual workflow_dispatch is the only trigger left;
    cron lines are deleted, not commented."""
    text = (WF / name).read_text(encoding="utf-8")
    assert on_triggers(text) == ["workflow_dispatch"], on_triggers(text)
    assert "cron" not in text
    assert not auto_triggered(text)


@pytest.mark.parametrize("name", DK_API_WORKFLOWS)
def test_dk_api_workflow_still_reaches_dk_module_so_it_must_stay_manual(name):
    """Guards against the list going stale: each still imports a DK API builder."""
    text = (WF / name).read_text(encoding="utf-8")
    seeds = set()
    for kind, v in entries(text):
        if kind == "inline":
            seeds |= imports(None, v)
        elif kind == "module":
            f = mod_file(v); f and seeds.add(f)
        else:
            f = ROOT / v; f.is_file() and seeds.add(f)
    seen, _ = closure(seeds)
    assert any(PAT.search(f.read_text(encoding="utf-8", errors="ignore")) for f in seen)


def test_trigger_parser():
    t = "on:\n  workflow_dispatch:\n  # push:\n  push:\n    branches: [main]\njobs:\n  a:\n"
    assert on_triggers(t) == ["workflow_dispatch", "push"]
    assert auto_triggered(t) and not auto_triggered("on:\n  workflow_dispatch:\njobs:\n")


def test_detector_positive_control():
    live = ("on:\n  schedule:\n    - cron: '1 * * * *'\njobs:\n  j:\n    steps:\n      - run: |\n"
            "          python - <<'PY'\n          from sportsedge.draftkings_prop_source import x\n"
            "          PY\n")
    assert scheduled(live)
    assert "sportsedge/draftkings_prop_source.py" in report_one(live)


def test_commented_cron_is_not_scheduled():
    assert not scheduled("on:\n  schedule:\n    # - cron: '1 * * * *'\n")
    assert scheduled("on:\n  schedule:\n    - cron: '1 * * * *'\n")


@pytest.mark.parametrize("mod", ["sportsedge/draftkings_prop_source.py",
                                 "sportsedge/draftkings_game_market_source.py",
                                 "sportsedge/dfs/draftkings.py", "sportsedge/dfs/dk_contest.py",
                                 "scripts/probe_dk_game_lines_categories.py"])
def test_no_dk_source_module_deleted(mod):
    assert (ROOT / mod).is_file()
