"""Owner invariant: DraftKings data comes from rendered pages only.

Fails if any *scheduled* workflow (an active, uncommented `- cron:` line) imports or runs
a repo module -- transitively, via AST imports, `python -m`, `python path.py`, inline
`python - <<PY` heredocs and `unittest` targets -- whose source builds a DraftKings API URL
(`/sites/US-SB/api`, `sportsbook-nash.draftkings.com/api`, `api.draftkings.com`).

Proposal branch grok/t250: cron is disabled (commented, workflow_dispatch kept) only on
the three workflows the owner named. Four further scheduled workflows also reach a DK API
module; they are listed in OWNER_DECISION_PENDING as strict xfails so the gap stays
visible and the marker must be removed once they are resolved. No source module deleted.
"""
import pytest
from pathlib import Path

import ast
import re
import textwrap
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PAT = re.compile(r"sites/US-SB/api|sportsbook-nash\.draftkings\.com/api|api\.draftkings\.com")

def scheduled(text):
    return bool(re.search(r"^\s*-\s*cron\s*:", "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#")), re.M))

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



DISABLED_BY_T250 = ("draftkings-prop-provider-probe.yml", "mlb-prop-pit-archive.yml",
                    "nfl-market-maker-radar-capture.yml")
OWNER_DECISION_PENDING = ("mlb-moneyline-forward-evidence.yml", "nfl-2026-line-capture.yml",
                          "nfl-dk-direct-confirmation-capture.yml",
                          "sportsedge-auto-dk-four-sports.yml")
WF = ROOT / ".github" / "workflows"


def _scheduled_workflows():
    return sorted(p.name for p in WF.glob("*.y*ml") if scheduled(p.read_text(encoding="utf-8")))


def _params():
    out = []
    for name in _scheduled_workflows():
        marks = []
        if name in OWNER_DECISION_PENDING:
            marks.append(pytest.mark.xfail(strict=True, reason="OWNER_DECISION_PENDING: scheduled "
                                           "workflow reaches a DK API module; not in t250 scope"))
        out.append(pytest.param(name, marks=marks, id=name))
    return out


@pytest.mark.parametrize("name", _params())
def test_scheduled_workflow_reaches_no_dk_api_module(name):
    assert report().get(name) == [], report().get(name)


@pytest.mark.parametrize("name", DISABLED_BY_T250)
def test_named_workflows_have_no_active_cron_but_keep_dispatch(name):
    text = (WF / name).read_text(encoding="utf-8")
    assert not scheduled(text)
    assert "\n  workflow_dispatch:" in text


def test_detector_positive_control(tmp_path):
    text = (WF / "draftkings-prop-provider-probe.yml").read_text(encoding="utf-8")
    live = re.sub(r"#\s*- cron:", "- cron:", text)
    assert scheduled(live)
    seeds = set()
    for kind, v in entries(live):
        if kind == "inline":
            seeds |= imports(None, v)
    seen, _ = closure(seeds)
    assert ROOT / "sportsedge" / "draftkings_prop_source.py" in seen


def test_commented_cron_is_not_scheduled():
    assert not scheduled("on:\n  schedule:\n    # - cron: '1 * * * *'\n")
    assert scheduled("on:\n  schedule:\n    - cron: '1 * * * *'\n")


@pytest.mark.parametrize("mod", ["sportsedge/draftkings_prop_source.py",
                                 "sportsedge/draftkings_game_market_source.py",
                                 "sportsedge/dfs/draftkings.py", "sportsedge/dfs/dk_contest.py",
                                 "scripts/probe_dk_game_lines_categories.py"])
def test_no_dk_source_module_deleted(mod):
    assert (ROOT / mod).is_file()
