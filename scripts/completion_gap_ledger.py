"""Structural completion-gap ledger over the cross-sport readiness inventory.

Lists each canonical market that lacks a priced path or forward-test config,
the score area it affects and whether it is buildable now or blocked. It is
structural only: it awards no score points, confers no validation and grants
no play authority. Validation gaps are never buildable.
"""
from __future__ import annotations

import argparse
import sys
import json
from collections import Counter
from pathlib import Path

from scripts.audit_cross_sport_accuracy_readiness import accuracy_readiness
from sportsedge.canonical_coverage import MARKET_RESOLUTIONS

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "completion_gap_policy_v1.json"
SCHEMA = "SPORTSEDGE_COMPLETION_GAP_LEDGER_V1"

_BLOCKERS = {
    "NO_ENGINE": ("ENGINES", "BUILDABLE"),
    "NO_VALIDATION": ("VALIDATION", "BLOCKED_FORWARD_VERDICT_REQUIRED"),
    "NO_DATA": ("ENGINES", "BLOCKED_MISSING_DATA"),
    "NO_QUOTE": ("INFRASTRUCTURE", "BLOCKED_MISSING_QUOTE"),
}


class LedgerRefusal(ValueError):
    pass


REMOTE_REPO = "isaacrome21-sys/sportsedge"
_HEX = frozenset("0123456789abcdef")


REMOTE_ATTEMPTS = 4
REMOTE_BACKOFF_S = 2.0


def _github_get(url: str, *, sleep=None):
    """(http_status, json_or_None). 404/422 -> (code, None). Rate-limit 403/429 retried
    a bounded number of times; anything else unavailable fails closed."""
    import time
    import urllib.error
    import urllib.request
    sleep = sleep or time.sleep
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "sportsedge-completion-gap-ledger/1"})
    for attempt in range(REMOTE_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return 200, json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (404, 422):
                return e.code, None
            limited = e.code in (403, 429) and e.headers.get("x-ratelimit-remaining") == "0"
            if not limited or attempt == REMOTE_ATTEMPTS - 1:
                raise LedgerRefusal(f"REMOTE_CHECK_UNAVAILABLE:{e.code}") from None
        except OSError:
            if attempt == REMOTE_ATTEMPTS - 1:
                raise LedgerRefusal("REMOTE_CHECK_UNAVAILABLE") from None
        sleep(REMOTE_BACKOFF_S * (attempt + 1))
    raise LedgerRefusal("REMOTE_CHECK_UNAVAILABLE")


def _github_resolver(branch: str, sha: str, *, sleep=None) -> str:
    """'head' only if sha IS the remote branch HEAD (compare status identical);
    'ancestor' if the branch has moved past it; otherwise 'missing'."""
    import urllib.parse
    code, body = _github_get(f"https://api.github.com/repos/{REMOTE_REPO}/compare/"
                             f"{sha}...{urllib.parse.quote(branch, safe='/')}", sleep=sleep)
    status = (body or {}).get("status") if code == 200 else None
    return {"identical": "head", "ahead": "ancestor"}.get(status, "missing")


def _blob_sha(path: str, ref: str):
    """Git blob SHA of path at ref (contents API), or None if the file is absent."""
    import urllib.parse
    code, body = _github_get(f"https://api.github.com/repos/{REMOTE_REPO}/contents/"
                             f"{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref, safe='')}")
    return (body or {}).get("sha") if code == 200 else None


def _repo_has_file(path: str, ref: str) -> bool:
    return _blob_sha(path, ref) is not None


def _main_merge_state(path: str, cleared_head_sha: str) -> str:
    """Compare the engine blob on main with the blob at the cleared head."""
    head = _blob_sha(path, cleared_head_sha)
    if head is None:
        raise LedgerRefusal(f"ENGINE_FILE_NOT_AT_SHA:{path}@{cleared_head_sha}")
    main = _blob_sha(path, "main")
    if main is None:
        return "NOT_ON_MAIN"
    return "MERGED_SAME_BLOB" if main == head else "ON_MAIN_DIFFERENT_BLOB"


_GROK_KEYS = ("grok_branch_engines", "grok_branch_screen_engines")


def _grok_entries(policy: dict):
    for key in _GROK_KEYS:
        for sport, entries in policy.get(key, {}).items():
            for market, e in entries.items():
                yield key, sport, market, e


def _hex40(v) -> bool:
    return isinstance(v, str) and len(v) == 40 and set(v) <= _HEX


def verify_branch_shas(policy: dict, *, resolver=None, file_resolver=None) -> list:
    """For every grok-branch entry: cleared_head_sha must be exactly the remote branch
    HEAD, the cited engine sha must be on that branch (the head or an ancestor), and the
    engine_file must exist at the cited sha."""
    resolver = resolver or _github_resolver
    heads, shas, files = set(), set(), set()
    for _key, _sport, market, e in _grok_entries(policy):
        branch, sha, head = e.get("branch"), e.get("sha"), e.get("cleared_head_sha")
        if not isinstance(branch, str) or not branch.startswith("grok/"):
            raise LedgerRefusal(f"GROK_BRANCH_REQUIRED:{market}")
        if not _hex40(sha):
            raise LedgerRefusal(f"GROK_BRANCH_SHA_MALFORMED:{market}")
        if not _hex40(head):
            raise LedgerRefusal(f"CLEARED_HEAD_SHA_MALFORMED:{market}")
        f = e.get("engine_file")
        if not isinstance(f, str) or not f.startswith("sportsedge/") or not f.endswith(".py"):
            raise LedgerRefusal(f"ENGINE_FILE_REQUIRED:{market}")
        shas.add((branch, sha)); heads.add((branch, head)); files.add((f, sha))
    for branch, sha in sorted(shas):
        if resolver(branch, sha) not in ("head", "ancestor"):
            raise LedgerRefusal(f"GROK_BRANCH_SHA_NOT_ON_REMOTE:{branch}@{sha}")
    for branch, head in sorted(heads):
        got = resolver(branch, head)
        if got == "ancestor":
            raise LedgerRefusal(f"GROK_BRANCH_SHA_NOT_HEAD:{branch}@{head}")
        if got != "head":
            raise LedgerRefusal(f"GROK_BRANCH_SHA_NOT_ON_REMOTE:{branch}@{head}")
    if file_resolver is not None or resolver is _github_resolver:
        has = file_resolver or _repo_has_file
        for f, sha in sorted(files):
            if not has(f, sha):
                raise LedgerRefusal(f"ENGINE_FILE_NOT_AT_SHA:{f}@{sha}")
    return sorted(shas | heads)


_PRICED_OR_CONFIG = ("RESEARCH_PRICED_NOT_VALIDATED", "NO_FORWARD_TEST_CONFIG")


def _cited(policy: dict, key: str, sport: str, market: str):
    entries = policy.get(key, {}).get(sport, {})
    if not isinstance(entries, dict):
        raise LedgerRefusal(f"RECORD_CITATION_REQUIRED:{key}")
    if market not in entries:
        return None
    rec = entries[market]
    if not isinstance(rec, str) or "#" not in rec or not rec.split("#", 1)[0]:
        raise LedgerRefusal(f"RECORD_CITATION_REQUIRED:{key}:{market}")
    return rec


_SCOPE_SECTIONS = ("Question", "Scope", "Data (fixed now)")


def _repo_file(rel) -> Path:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise LedgerRefusal(f"COVERING_INSTRUMENT_PATH_ESCAPE:{rel}")
    root = ROOT.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise LedgerRefusal(f"COVERING_INSTRUMENT_PATH_ESCAPE:{rel}")
    return path


def _section_of(text: str, needle: str):
    """(H1 title, enclosing H2 heading) of the first occurrence of needle."""
    i = text.find(needle)
    if i < 0:
        return None, None
    title, section = "", None
    for line in text[:i].splitlines():
        if line.startswith("# "):
            title = line[2:]
        elif line.startswith("## "):
            section = line[3:].strip()
    return title, section


def _check_marker(ref: dict, path: Path, market: str) -> None:
    text = path.read_text(encoding="utf-8")
    if ref["needle"] not in text:
        raise LedgerRefusal(f"COVERING_INSTRUMENT_NOT_FOUND:{market}:{ref['path']}")
    if ref["marker"] == "FREEZE":
        try:
            status = json.loads(text).get("status")
        except (ValueError, AttributeError):
            raise LedgerRefusal(f"COVERING_INSTRUMENT_NOT_A_MARKER:{market}:{ref['path']}") from None
        ok = (isinstance(status, str) and status.startswith("FROZEN")
              and ref["needle"] == f'"status": "{status}"' and market in text)
    else:
        title, section = _section_of(text, ref["needle"])
        ok = ("pre-registration" in (title or "").lower() and section in _SCOPE_SECTIONS
              and market in ref["needle"] and "out of scope" not in ref["needle"].lower())
    if not ok:
        raise LedgerRefusal(f"COVERING_INSTRUMENT_NOT_A_MARKER:{market}:{ref['path']}")


def _covering(policy: dict, sport: str, market: str):
    table = policy.get("covered_by_frozen_instrument", {})
    if not isinstance(table, dict) or not isinstance(table.get(sport, {}), dict):
        raise LedgerRefusal("COVERING_INSTRUMENT_CITATION_MALFORMED:TABLE")
    refs = table.get(sport, {}).get(market)
    if refs is None:
        return None
    if not isinstance(refs, list) or not refs:
        raise LedgerRefusal(f"COVERING_INSTRUMENT_CITATION_MALFORMED:{market}")
    out = []
    for ref in refs:
        if (not isinstance(ref, dict) or set(ref) != {"path", "needle", "marker"}
                or not isinstance(ref["needle"], str) or not ref["needle"]
                or not isinstance(ref["path"], str) or ref["marker"] not in ("SCOPE", "FREEZE")):
            raise LedgerRefusal(f"COVERING_INSTRUMENT_CITATION_MALFORMED:{market}")
        path = _repo_file(ref["path"])
        if not path.is_file():
            raise LedgerRefusal(f"COVERING_INSTRUMENT_NOT_FOUND:{market}:{ref['path']}")
        _check_marker(ref, path, market)
        out.append(ref["path"])
    return out


def _engine(row: dict, policy: dict, merged_files=frozenset(), main_differs=frozenset()):
    code = policy.get("existing_engine_code", {}).get(row["sport"], {}).get(row["market"])
    if code is not None:
        text = (ROOT / code["path"]).read_text(encoding="utf-8")
        if code["needle"] not in text:
            raise LedgerRefusal(f"ENGINE_CODE_NOT_FOUND:{row['market']}")
        return "ENGINE_EXISTS_NOT_WIRED", f"{code['path']} {code['needle']}"
    res = MARKET_RESOLUTIONS.get((row["sport"], row["market"])) or {}
    if res.get("engine"):
        return "ENGINE_EXISTS_NOT_WIRED", res["engine"]
    branch = policy.get("grok_branch_engines", {}).get(row["sport"], {}).get(row["market"])
    if branch is not None:
        if branch.get("engine_file") in merged_files:
            return "ENGINE_MERGED_TO_MAIN_NOT_WIRED", dict(branch)
        if branch.get("engine_file") in main_differs:
            return "ENGINE_ON_MAIN_DIFFERS_FROM_CLEARED_HEAD", dict(branch)
        return "ENGINE_ON_GROK_BRANCH_NOT_MERGED", dict(branch)
    return "BUILDABLE", None


def classify(row: dict, policy: dict, *, merged_files=frozenset(), main_differs=frozenset()) -> dict | None:
    if row.get("validated_accuracy_in_this_audit") is not False:
        raise LedgerRefusal("INPUT_CLAIMS_VALIDATION")
    blocker, readiness = row.get("blocker"), row.get("readiness")
    if (blocker is None) != (readiness in _PRICED_OR_CONFIG) or (
            blocker is not None and readiness != "NO_CANONICAL_PRICING_PATH"):
        raise LedgerRefusal(f"BLOCKER_READINESS_CONTRADICTION:{blocker}:{readiness}")
    engine_ref = None
    if blocker is None:
        if readiness == "RESEARCH_PRICED_NOT_VALIDATED":
            return None
        if readiness != "NO_FORWARD_TEST_CONFIG":
            raise LedgerRefusal(f"UNKNOWN_READINESS:{readiness}")
        area, status = "INFRASTRUCTURE", "BUILDABLE_NEEDS_SIBLING_RECONCILIATION"
    elif blocker in _BLOCKERS:
        area, status = _BLOCKERS[blocker]
        if blocker == "NO_ENGINE":
            status, engine_ref = _engine(row, policy, merged_files, main_differs)
    else:
        raise LedgerRefusal(f"UNKNOWN_BLOCKER:{blocker}")
    record = None
    paused = _cited(policy, "paused_markets", row["sport"], row["market"])
    held = _cited(policy, "owner_held_markets", row["sport"], row["market"])
    if paused and area != "VALIDATION":
        status, record = "BLOCKED_RULING_6_FOCUS_PAUSE", paused
    elif held and area != "VALIDATION":
        status, record = "BLOCKED_OWNER_HOLD", held
    elif readiness == "NO_FORWARD_TEST_CONFIG":
        covered = _covering(policy, row["sport"], row["market"])
        if covered:
            status, record = "COVERED_BY_COMMITTED_FROZEN_INSTRUMENT", covered
    out = {"sport": row["sport"], "market": row["market"], "blocker": blocker,
           "readiness": readiness, "score_area": area, "status": status,
           "engine_ref": engine_ref, "record": record}
    screen = policy.get("grok_branch_screen_engines", {}).get(row["sport"], {}).get(row["market"])
    if screen is not None:  # annotation only: never changes status
        out["screen_engine"] = {**screen, "merged_to_main": screen["engine_file"] in merged_files,
                                "main_blob_differs": screen["engine_file"] in main_differs}
    return out


def gap_ledger(*, root: Path = ROOT, offline: bool = False) -> dict:
    """Build the ledger. Verifies grok-branch SHAs against the remote unless
    offline=True is passed explicitly; the output records which happened."""
    if not isinstance(offline, bool):
        raise LedgerRefusal("OFFLINE_FLAG_MUST_BE_BOOL")
    policy = json.loads((root / "config" / "completion_gap_policy_v1.json").read_text(encoding="utf-8"))
    if policy.get("schema") != "SPORTSEDGE_COMPLETION_GAP_POLICY_V2":
        raise LedgerRefusal("POLICY_SCHEMA")
    merged, differs = set(), set()
    if not offline:
        verify_branch_shas(policy)
        for f, head in sorted({(e["engine_file"], e["cleared_head_sha"]) for *_, e in _grok_entries(policy)}):
            state = _main_merge_state(f, head)
            if state == "MERGED_SAME_BLOB":
                merged.add(f)
            elif state == "ON_MAIN_DIFFERENT_BLOB":
                differs.add(f)
    merged, differs = frozenset(merged), frozenset(differs)
    report = accuracy_readiness(root=root)
    if report.get("validated_families_conferred") != 0 or report.get("play_authority_conferred") is not False:
        raise LedgerRefusal("UPSTREAM_CONFERS_AUTHORITY")
    gaps = [g for g in (classify(r, policy, merged_files=merged, main_differs=differs) for r in report["canonical_markets"]) if g]
    gaps.sort(key=lambda g: (g["score_area"], g["status"], g["sport"], g["market"]))
    return {
        "schema": SCHEMA,
        "scope": "CANONICAL_MLB_NFL_MARKETS_ONLY",
        "gaps": gaps,
        "counts_by_status": dict(sorted(Counter(g["status"] for g in gaps).items())),
        "counts_by_area": dict(sorted(Counter(g["score_area"] for g in gaps).items())),
        "score_points_awarded": None,
        "validated_families_conferred": 0,
        "play_authority_conferred": False,
        "remote_shas_verified": not offline,
    }


def render(ledger: dict) -> str:
    return json.dumps(ledger, indent=2, sort_keys=True) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path)
    p.add_argument("--verify-remote", action="store_true",
                   help="(default) check grok-branch engine SHAs against the real remote")
    p.add_argument("--offline", action="store_true",
                   help="explicit opt-out: skip the remote SHA check (output is unverified)")
    a = p.parse_args()
    if a.offline and a.verify_remote:
        raise LedgerRefusal("OFFLINE_AND_VERIFY_REMOTE_CONFLICT")
    if a.offline:
        print("REMOTE_SHAS_NOT_VERIFIED_OFFLINE", file=sys.stderr)
    text = render(gap_ledger(offline=a.offline))
    if a.out:
        a.out.write_bytes(text.encode("utf-8"))
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
