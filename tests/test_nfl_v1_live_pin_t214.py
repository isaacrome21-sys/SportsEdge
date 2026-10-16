"""t214u Option A: external NFL V1 freeze/source pin, fail-closed live entry."""
from __future__ import annotations

import ast
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sportsedge.sports.nfl import v1_live_pin as pin
from sportsedge.sports.nfl.discrete_v2 import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / pin.MANIFEST_RELPATH
LOCK = ROOT / "config/research/nfl_market_context_prop_v1_2026_forward_lock.json"
FREEZE_REL = "config/nfl_discrete_v2_freeze.json"
V1_PATHS = [c["path"] for c in json.loads(LOCK.read_text())["candidate_identity"]["code_surface"]]


def _blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@pytest.fixture()
def root(tmp_path):
    m = json.loads(MANIFEST.read_text())
    rels = [pin.MANIFEST_RELPATH, m["freeze_file"]["path"],
            *[e["path"] for e in m["locked_v1_files"]],
            *[e["path"] for e in m.get("grid_dependencies") or []]]
    for rel in rels:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dst)
    return tmp_path


def test_real_repo_pins_verify():
    receipt = pin.verify_v1_live_pins()
    assert receipt["status"] == "NFL_V1_LIVE_PINS_VERIFIED"
    assert sorted(receipt["locked_v1_files"]) == sorted(V1_PATHS)
    assert receipt["play_authority"] is False


def test_manifest_matches_original_forward_lock_blobs_and_is_external():
    m = json.loads(MANIFEST.read_text())
    lock = {c["path"]: c["git_blob_sha1"]
            for c in json.loads(LOCK.read_text())["candidate_identity"]["code_surface"]}
    assert {e["path"]: e["git_blob_sha1"] for e in m["locked_v1_files"]} == lock
    for path, blob in lock.items():
        assert _blob((ROOT / path).read_bytes()) == blob  # V1 byte-identical
    # The pin is not stored inside any file it protects.
    for rel in [FREEZE_REL, *V1_PATHS]:
        text = (ROOT / rel).read_text()
        assert pin.PINNED_MANIFEST_SHA256 not in text
        assert m["freeze_file"]["sha256"] not in text
    assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest() == pin.PINNED_MANIFEST_SHA256


def test_tamper_freeze_with_recomputed_internal_sha_refused(root):
    path = root / FREEZE_REL
    art = json.loads(path.read_text())
    art["shape"]["margin_lifts"]["abs_3"] = 9.0
    payload = dict(art)
    payload.pop("artifact_sha256")
    art["artifact_sha256"] = canonical_sha256(payload)
    path.write_text(json.dumps(art, indent=2))
    from sportsedge.sports.nfl.discrete_v2 import load_freeze
    load_freeze(path)  # internal self-check is fooled
    with pytest.raises(pin.V1LivePinError, match="SHA256_MISMATCH"):
        pin.verify_v1_live_pins(root)


@pytest.mark.parametrize("rel", V1_PATHS)
def test_one_v1_source_byte_changed_refused(root, rel):
    path = root / rel
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))
    with pytest.raises(pin.V1LivePinError, match="NFL_V1_PINNED_FILE"):
        pin.verify_v1_live_pins(root)


def test_v1_source_missing_refused(root):
    (root / V1_PATHS[2]).unlink()
    with pytest.raises(pin.V1LivePinError, match="MISSING"):
        pin.verify_v1_live_pins(root)


def test_manifest_missing_refused(root):
    (root / pin.MANIFEST_RELPATH).unlink()
    with pytest.raises(pin.V1LivePinError, match="NFL_V1_PIN_MANIFEST_MISSING"):
        pin.verify_v1_live_pins(root)


def test_manifest_edited_to_match_tampered_freeze_refused(root):
    path = root / FREEZE_REL
    path.write_bytes(path.read_bytes() + b" ")
    m = json.loads((root / pin.MANIFEST_RELPATH).read_text())
    m["freeze_file"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / pin.MANIFEST_RELPATH).write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    with pytest.raises(pin.V1LivePinError, match="NFL_V1_PIN_MANIFEST_HASH_MISMATCH"):
        pin.verify_v1_live_pins(root)


def test_manifest_whitespace_edit_refused(root):
    p = root / pin.MANIFEST_RELPATH
    p.write_bytes(p.read_bytes() + b"\n")
    with pytest.raises(pin.V1LivePinError, match="HASH_MISMATCH"):
        pin.verify_v1_live_pins(root)


def test_manifest_dropping_a_file_refused_even_if_repinned(root):
    p = root / pin.MANIFEST_RELPATH
    m = json.loads(p.read_text())
    m["locked_v1_files"] = m["locked_v1_files"][:6]
    raw = (json.dumps(m) + "\n").encode()
    p.write_bytes(raw)
    with pytest.raises(pin.V1LivePinError, match="SEVEN_FILES"):
        pin.verify_v1_live_pins(root, pinned_sha256=hashlib.sha256(raw).hexdigest())


def _good_grid(n=4):
    return [[1.0 / (n * n)] * n for _ in range(n)]


@pytest.mark.parametrize("grid,code", [
    ([], "EMPTY"),
    ([[0.5, 0.25], [0.25]], "RAGGED"),
    ([[0.25, 0.25, 0.0], [0.25, 0.25]], "RAGGED"),
    ([[0.5, 0.5]], "NOT_SQUARE"),
    ([[0.25, 0.25], [0.25, 0.2]], "MASS"),
    ([[0.3, 0.3], [0.3, 0.3]], "MASS"),
    ([[float("nan"), 0.5], [0.25, 0.25]], "CELL"),
    ([[float("inf"), 0.0], [0.0, 0.0]], "CELL"),
    ([[-0.25, 0.75], [0.25, 0.25]], "CELL"),
    ([[True, 0.0], [0.0, 0.0]], "CELL"),
    ([["x", 0.5], [0.25, 0.25]], "CELL"),
])
def test_malformed_grid_refused_without_renormalization(grid, code):
    snapshot = json.dumps(grid)
    with pytest.raises(pin.V1LivePinError, match=code):
        pin.validate_score_grid(grid)
    assert json.dumps(grid) == snapshot  # never renormalized in place


def test_guarded_generator_and_sampler_refuse_bad_grid():
    bad = [[0.3, 0.3], [0.3, 0.3]]
    called = []
    gen = pin.guard_score_grid(lambda *a, **k: bad)
    samp = pin.guard_sampler(lambda g, **k: called.append(g))
    with pytest.raises(pin.V1LivePinError):
        gen(1, 2)
    with pytest.raises(pin.V1LivePinError):
        samp(bad, n_sims=10, seed=1)
    assert called == []
    samp(_good_grid(), n_sims=10, seed=1)
    assert len(called) == 1


def test_require_installs_runtime_mass_guard_on_v1_namespaces():
    from sportsedge.sports.nfl import unified_market_engine as ume, unified_run_it as uri
    pin.require_verified_v1_live()
    for mod in (ume, uri):
        assert getattr(mod.score_grid, "_nfl_v1_mass_guarded", False)
        assert getattr(mod.sample_score_paths, "_nfl_v1_mass_guarded", False)
    with pytest.raises(pin.V1LivePinError):
        ume.sample_score_paths([[0.3, 0.3], [0.3, 0.3]], n_sims=10, seed=1)
    # real frozen grid still passes
    g = ume.score_grid(23.4, 21.4, None)
    assert math.isclose(sum(map(sum, g)), 1.0, abs_tol=1e-9)


def test_live_card_script_refuses_on_tampered_manifest(monkeypatch, tmp_path):
    import scripts.run_nfl_unified_lines_card as card
    monkeypatch.setattr(pin, "PINNED_MANIFEST_SHA256", "0" * 64)
    reached = []
    monkeypatch.setattr(card, "discover_nfl_auto_games", lambda **k: reached.append(1))
    monkeypatch.setattr(card, "build_unified_phone_card", lambda *a, **k: reached.append(2))
    t = tmp_path / "t.json"; t.write_text(json.dumps({"observed_at": "2026-10-16T12:00:00Z", "games": []}))
    monkeypatch.setattr(sys, "argv", ["x", "--input", str(t), "--history", str(t), "--output", str(tmp_path / "o.json")])
    with pytest.raises(SystemExit) as exc:
        card.main()
    assert "NFL_V1_LIVE_PIN_REFUSED" in str(exc.value)
    assert reached == []
    assert not (tmp_path / "o.json").exists()


def test_market_context_guarded_wrapper_refuses(monkeypatch):
    monkeypatch.setattr(pin, "PINNED_MANIFEST_SHA256", "0" * 64)
    with pytest.raises(pin.V1LivePinError):
        pin.guarded_run_market_context_props(game_id="x")
    with pytest.raises(pin.V1LivePinError):
        pin.guarded_run_market_context_props_from_nflverse(game_id="x")


def test_auto_dk_runner_preflights_before_nfl_prop_subprocess():
    src = (ROOT / "scripts/run_auto_dk_cards.py").read_text()
    i_guard = src.find("_nfl_v1_live_preflight()")
    i_call = src.find('"scripts/run_nfl_unified_lines_card.py"')
    assert 0 <= i_guard < i_call
    assert "NFL_V1_LIVE_PIN_REFUSED" in src


# ---- bypass scan ---------------------------------------------------------
V1_MODULES = {
    "sportsedge.nfl_unified_phone", "sportsedge.sports.nfl.unified_run_it",
    "sportsedge.sports.nfl.unified_market_engine", "sportsedge.sports.nfl.market_context_props",
}
ENTRYPOINTS = {
    "run_unified_nfl_model", "sample_score_paths", "run_unified_nfl_run_it",
    "run_unified_nfl_run_it_from_nflverse", "build_unified_phone_card",
    "run_market_context_props", "run_market_context_props_from_nflverse",
}
GUARDS = {"require_verified_v1_live", "_nfl_v1_live_preflight"}
SUBPROCESS_TARGET = "scripts/run_nfl_unified_lines_card.py"


def _resolve(mod: str, level: int, path: Path) -> str:
    if not level:
        return mod
    pkg = list(path.relative_to(ROOT).with_suffix("").parts[:-1])
    pkg = pkg[: len(pkg) - (level - 1)] if level > 1 else pkg
    return ".".join(pkg + ([mod] if mod else []))


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _violations() -> list[str]:
    out = []
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.split()
    for rel in files:
        if rel.startswith("tests/") or rel in V1_PATHS:
            continue
        path = ROOT / rel
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        imported, mod_aliases = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                full = _resolve(node.module or "", node.level, path)
                if full in V1_MODULES:
                    imported |= {a.asname or a.name for a in node.names if a.name in ENTRYPOINTS}
                for a in node.names:
                    if f"{full}.{a.name}" in V1_MODULES:
                        mod_aliases.add(a.asname or a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in V1_MODULES:
                        mod_aliases.add(a.asname or a.name)
        if rel == "sportsedge/sports/nfl/v1_live_pin.py":
            continue  # guard module: wrappers call require_verified_v1_live first (tested above)
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module))]:
            body_nodes = list(ast.walk(fn))
            guard_lines = [n.lineno for n in body_nodes if isinstance(n, ast.Call) and _call_name(n) in GUARDS]
            first_guard = min(guard_lines) if guard_lines else math.inf
            for n in body_nodes:
                hit = False
                if isinstance(n, ast.Call):
                    name = _call_name(n)
                    f = n.func
                    if isinstance(f, ast.Name) and name in imported:
                        hit = True
                    elif isinstance(f, ast.Attribute) and name in ENTRYPOINTS:
                        hit = True
                if isinstance(n, ast.Constant) and n.value == SUBPROCESS_TARGET:
                    hit = True
                if hit and n.lineno <= first_guard:
                    out.append(f"{rel}:{n.lineno}")
    return sorted(set(out))


def test_bypass_scan_no_unverified_live_v1_caller():
    assert _violations() == []
