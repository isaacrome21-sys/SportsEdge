"""Structural completion-gap ledger over the cross-sport readiness inventory.

Lists each canonical market that lacks a priced path or forward-test config,
the score area it affects and whether it is buildable now or blocked. It is
structural only: it awards no score points, confers no validation and grants
no play authority. Validation gaps are never buildable.
"""
from __future__ import annotations

import argparse
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


def _github_resolver(branch: str, sha: str) -> str:
    """'on_branch' if sha is the head of, or an ancestor of, the remote branch."""
    import urllib.error
    import urllib.parse
    import urllib.request
    url = (f"https://api.github.com/repos/{REMOTE_REPO}/compare/"
           f"{sha}...{urllib.parse.quote(branch, safe='/')}")
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status = json.load(r).get("status")
    except urllib.error.HTTPError as e:
        if e.code in (404, 422):
            return "missing"
        raise LedgerRefusal(f"REMOTE_CHECK_UNAVAILABLE:{e.code}") from None
    except OSError:
        raise LedgerRefusal("REMOTE_CHECK_UNAVAILABLE") from None
    return "on_branch" if status in ("identical", "ahead") else "missing"


def verify_branch_shas(policy: dict, *, resolver=None) -> list:
    """Check every grok_branch_engines SHA is a real commit on its remote branch."""
    resolver = resolver or _github_resolver
    pairs = set()
    for sport, entries in policy.get("grok_branch_engines", {}).items():
        for market, e in entries.items():
            branch, sha = e.get("branch"), e.get("sha")
            if not isinstance(branch, str) or not branch.startswith("grok/"):
                raise LedgerRefusal(f"GROK_BRANCH_REQUIRED:{market}")
            if not isinstance(sha, str) or len(sha) != 40 or not set(sha) <= _HEX:
                raise LedgerRefusal(f"GROK_BRANCH_SHA_MALFORMED:{market}")
            pairs.add((branch, sha))
    for branch, sha in sorted(pairs):
        if resolver(branch, sha) != "on_branch":
            raise LedgerRefusal(f"GROK_BRANCH_SHA_NOT_ON_REMOTE:{branch}@{sha}")
    return sorted(pairs)


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


def _engine(row: dict, policy: dict):
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
        return "ENGINE_ON_GROK_BRANCH_NOT_MERGED", dict(branch)
    return "BUILDABLE", None


def classify(row: dict, policy: dict) -> dict | None:
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
            status, engine_ref = _engine(row, policy)
    else:
        raise LedgerRefusal(f"UNKNOWN_BLOCKER:{blocker}")
    record = None
    paused = _cited(policy, "paused_markets", row["sport"], row["market"])
    held = _cited(policy, "owner_held_markets", row["sport"], row["market"])
    if paused and area != "VALIDATION":
        status, record = "BLOCKED_RULING_6_FOCUS_PAUSE", paused
    elif held and area != "VALIDATION":
        status, record = "BLOCKED_OWNER_HOLD", held
    return {"sport": row["sport"], "market": row["market"], "blocker": blocker,
            "readiness": readiness, "score_area": area, "status": status,
            "engine_ref": engine_ref, "record": record}


def gap_ledger(*, root: Path = ROOT) -> dict:
    policy = json.loads((root / "config" / "completion_gap_policy_v1.json").read_text(encoding="utf-8"))
    if policy.get("schema") != "SPORTSEDGE_COMPLETION_GAP_POLICY_V2":
        raise LedgerRefusal("POLICY_SCHEMA")
    report = accuracy_readiness(root=root)
    if report.get("validated_families_conferred") != 0 or report.get("play_authority_conferred") is not False:
        raise LedgerRefusal("UPSTREAM_CONFERS_AUTHORITY")
    gaps = [g for g in (classify(r, policy) for r in report["canonical_markets"]) if g]
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
    }


def render(ledger: dict) -> str:
    return json.dumps(ledger, indent=2, sort_keys=True) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path)
    p.add_argument("--verify-remote", action="store_true",
                   help="check grok-branch engine SHAs against the real remote first")
    a = p.parse_args()
    if a.verify_remote:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        verify_branch_shas(policy)
    text = render(gap_ledger())
    if a.out:
        a.out.write_bytes(text.encode("utf-8"))
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
