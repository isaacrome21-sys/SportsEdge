#!/usr/bin/env python3
"""Audit/execute declared lanes or evaluate supplied multi-sport lines."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

# Running this file as `python scripts/run_it_all.py` puts only `scripts/` on
# sys.path. Add the repository root explicitly so the canonical `sportsedge`
# package resolves identically in local shells and GitHub Actions.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.run_it_control import audit_surface, execute_surface, scope_from_request


SUPPLIED_LINE_SPORTS = frozenset({"MLB", "NBA", "CFB", "NFL"})
RESEARCH_STATUSES = frozenset({
    "RESEARCH_POSITIVE_EV_UNVALIDATED", "RESEARCH_CANDIDATE_NOT_VALIDATED",
    "RESEARCH_EDGE", "PRICED_RESEARCH",
})


def _has_probability(row: dict) -> bool:
    def valid(value):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and 0 <= value <= 1)

    if any(valid(row.get(key)) for key in ("estimate_p", "model_probability")):
        return True
    probs = row.get("model_probabilities")
    return isinstance(probs, dict) and any(valid(value) for value in probs.values())


def _supplied_line_run(
    lines_path: Path, *, requested_scope: tuple[str, ...] | None,
    no_fetch: bool, as_of: str | None, card_output: Path,
) -> dict:
    """Evaluate all supplied sports with the canonical *research* runner.

    This is intentionally NOT a shortcut to the official admission lane. The
    canonical free-research runner has no evidence/promotion authority. A
    positive EV or pricing-provenance ``play_eligible`` flag is not a PLAY.
    """
    try:
        payload = json.loads(lines_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit("RUN_IT_LINES_FILE_INVALID_OR_MISSING") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("lines"), list):
        raise SystemExit("RUN_IT_LINES_STRUCTURE_INVALID")

    rows = payload["lines"]
    fallback_sport = str(payload.get("sport") or "").upper().strip()
    sports = []
    for row in rows:
        if not isinstance(row, dict):
            raise SystemExit("RUN_IT_LINES_ROW_INVALID")
        sport = str(row.get("sport") or fallback_sport).upper().strip()
        if sport not in SUPPLIED_LINE_SPORTS:
            raise SystemExit("RUN_IT_LINES_SPORT_UNSUPPORTED:" + (sport or "MISSING"))
        sports.append(sport)
    selected = set(requested_scope) if requested_scope is not None else set(sports)
    if not selected or selected.difference(SUPPLIED_LINE_SPORTS):
        raise SystemExit("RUN_IT_LINES_SCOPE_INVALID")
    if set(sports).difference(selected):
        raise SystemExit("RUN_IT_LINES_OUTSIDE_SCOPE")
    if as_of:
        try:
            instant = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except (ValueError, TypeError) as exc:
            raise SystemExit("RUN_IT_AS_OF_INVALID") from exc
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise SystemExit("RUN_IT_AS_OF_REQUIRES_TIMEZONE")

    # Import lazily: audits and the autonomous control plane need not load the
    # entire research/pricing stack.
    from artifacts.run_it_full import run_full

    card = run_full(payload, auto_context=not no_fetch, as_of=as_of)
    evaluated = card.get("evaluated_rows")
    if (not isinstance(evaluated, list) or len(evaluated) != len(rows)
            or any(not isinstance(row, dict) for row in evaluated)):
        raise SystemExit("RUN_IT_CANONICAL_EVALUATION_INCOMPLETE")

    results = []
    for sport in sorted(selected):
        matched = [result for source_sport, result in zip(sports, evaluated)
                   if source_sport == sport]
        counts = Counter(str(row.get("status") or "MISSING_STATUS")
                         for row in matched)
        modeled = sum(_has_probability(row) for row in matched)
        research = sum(str(row.get("status")) in RESEARCH_STATUSES
                       for row in matched)
        blockers = Counter(str(row.get("blocker") or row.get("reason") or
                               row.get("status") or "UNKNOWN")
                           for row in matched if not _has_probability(row))
        blocker = ("NO_SUPPLIED_LINES_FOR_SPORT" if not matched else
                   "NO_CANONICAL_MODEL_RESULT" if not modeled else
                   "RESEARCH_MODEL_NOT_ADMITTED_FOR_PLAY")
        results.append({
            "sport": sport, "lane": "CANONICAL_SUPPLIED_LINE_RESEARCH",
            "status": "PARTIAL" if modeled else "BLOCKED",
            "execution_status": "COMPLETED", "input_rows": len(matched),
            "model_rows": modeled, "research_candidates": research,
            "official_bets": 0, "verified_plays": [],
            "blocker": blocker, "status_counts": dict(sorted(counts.items())),
            "unpriced_reason_counts": dict(sorted(blockers.items())),
        })

    card_output.parent.mkdir(parents=True, exist_ok=True)
    card_output.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    return {
        "schema_version": "RUN_IT_SUPPLIED_LINES_V1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "CANONICAL_RESEARCH_NOT_OFFICIAL_BET_RELEASE",
        "scope": sorted(selected),
        "overall_status": ("PARTIAL" if any(r["model_rows"] for r in results)
                           else "BLOCKED"),
        "verified_bets": 0,
        "verification_blocker": "CANONICAL_RESEARCH_RUNNER_HAS_NO_PROMOTION_AUTHORITY",
        "governance": {"model_p_changed": False, "promotion_changed": False,
                       "unverified_estimates_may_be_play": False,
                       "source_quote_age_inferred": False,
                       "silent_skip_allowed": False},
        "canonical_card_path": str(card_output),
        "results": results,
    }


def _request(path: str | None):
    if not path:
        return None
    target = Path(path)
    if not target.exists():
        raise SystemExit("RUN_IT_REQUEST_FILE_MISSING")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit("RUN_IT_REQUEST_FILE_INVALID") from exc
    if not isinstance(payload, dict):
        raise SystemExit("RUN_IT_REQUEST_FILE_INVALID")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true")
    mode.add_argument("--execute", action="store_true")
    ap.add_argument("--scope", default="ALL")
    ap.add_argument("--request")
    ap.add_argument("--output", default="artifacts/run_it/control_plane.json")
    ap.add_argument("--timeout-seconds", type=int, default=900)
    ap.add_argument("--lines", type=Path,
                    help="Input JSON for canonical multi-sport research evaluation")
    ap.add_argument("--card-output", type=Path,
                    help="Full canonical per-selection research card output")
    ap.add_argument("--no-fetch", action="store_true",
                    help="Disable live context fetch on --lines route")
    ap.add_argument("--as-of", help="Timezone-aware ISO-8601 as-of instant")
    args = ap.parse_args()

    if args.lines is not None and (not args.execute or args.request):
        ap.error("--lines requires --execute without --request")
    if args.lines is None and (args.no_fetch or args.as_of or args.card_output):
        ap.error("--no-fetch/--as-of/--card-output require --lines")

    request = _request(args.request)
    if request is not None:
        action = str(request.get("action", "RUN")).strip().upper()
        if action != "RUN":
            raise SystemExit("RUN_IT_REQUEST_ACTION_INVALID")
        scope = scope_from_request(request)
    elif str(args.scope).strip().upper() == "ALL":
        scope = None
    else:
        scope = tuple(x.strip().upper() for x in args.scope.split(",") if x.strip())

    if args.lines is not None:
        output = Path(args.output)
        card_output = args.card_output or output.with_name("canonical_card.json")
        if card_output.resolve() == output.resolve():
            ap.error("--card-output must differ from --output")
        payload = _supplied_line_run(
            args.lines, requested_scope=scope,
            no_fetch=args.no_fetch, as_of=args.as_of,
            card_output=card_output)
    else:
        payload = (audit_surface() if args.audit else
                   execute_surface(scope=scope,
                                   timeout_seconds=args.timeout_seconds))
    if request is not None:
        payload["request"] = {
            "request_id": request.get("request_id"),
            "requested_at_utc": request.get("requested_at_utc"),
            "scope": request.get("scope", "ALL"),
        }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))

    if args.audit:
        return 0 if payload.get("status") == "PASS" else 2
    # PARTIAL is an honest governed result: some lanes can execute while other
    # declared lanes remain explicit blockers. BROKEN executable lanes return 2.
    broken = any(
        row.get("status") == "BROKEN" for row in payload.get("results", [])
    )
    return 2 if broken or payload.get("overall_status") == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
