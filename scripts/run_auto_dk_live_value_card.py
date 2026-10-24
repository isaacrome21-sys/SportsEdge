#!/usr/bin/env python3
"""Price an existing DK capture via canonical RUN IT without new odds calls.

All supported game markets and both quoted sides are retained; unavailable
model families stay blocked. The final phone card checks quote age AGAIN at
render, so a slow public-data lookup cannot advertise an expired offer.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.auto_dk_canonical_intake import bind_capture, SUPPORTED_SPORTS


def run_capture_directory(directory: Path, *, now: datetime, runner=None,
                          render=None, max_games: int | None = None,
                          form2_bundles_dir: Path | None = None,
                          form2_manifest_sha256: str | None = None) -> tuple[dict, dict | None, str]:
    """Build one current-value board from already-paid DK snapshot files.

    form2_bundles_dir / form2_manifest_sha256 pass straight through to the
    canonical runner's Form 2 loader. The pin is only ever the caller's
    external value (CLI or runner config); it is never derived from the
    archive or this run, so NO PIN means NO ADMISSION (CFB stays blocked).
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("CURRENT_DK_NOW_TIMEZONE_REQUIRED")
    if max_games is not None and (isinstance(max_games, bool)
                                  or not isinstance(max_games, int) or max_games < 1):
        raise ValueError("LIVE_MAX_GAMES_MUST_BE_POSITIVE_INTEGER")
    if runner is None:
        from artifacts.run_it_full import run_full as runner
    if render is None:
        from sportsedge.phone_display import render_phone_card as render
    lines, receipts = [], []
    sport_counts = {}
    for sport in ("NFL", "CFB", "MLB", "NBA"):
        path = directory / f"{sport.lower()}_odds.json"
        if not path.is_file():
            receipts.append({"sport": sport, "reason": "CAPTURE_FILE_MISSING"})
            sport_counts[sport] = 0
            continue
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict):
                raise ValueError("SNAPSHOT_NOT_OBJECT")
            offers, rejected = bind_capture(snapshot, now=now)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            offers, rejected = [], [{"sport": sport,
                                     "reason": "SNAPSHOT_INVALID:" + type(exc).__name__}]
        lines.extend(offers)
        receipts.extend(rejected)
        sport_counts[sport] = len(offers)
    source_rows = len(lines)
    source_sport_counts = dict(sport_counts)
    if max_games is not None:
        # Price the soonest-to-start complete games first. The slow full-slate
        # audit runs separately; delaying the first current price until it
        # finishes can consume the entire three-minute quote lifetime.
        events = {}
        for line in lines:
            identity = (line["sport"], line["capture_event_id"])
            events.setdefault(identity, line["kickoff"])
        ordered = sorted(events, key=lambda k: (events[k], k))
        selected = set(ordered[:max_games])
        for sport, event in ordered[max_games:]:
            receipts.append({"sport": sport, "capture_event_id": event,
                             "reason": "DEFERRED_BY_FAST_PASS_GAME_CAP"})
        lines = [line for line in lines if
                 (line["sport"], line["capture_event_id"]) in selected]
        sport_counts = {sport: sum(row["sport"] == sport for row in lines)
                        for sport in ("NFL", "CFB", "MLB", "NBA")}
    audit = {"schema": "SPORTSEDGE_AUTO_DK_CANONICAL_V1",
             "generated_at_utc": now.astimezone(timezone.utc).isoformat(),
             "markets_in_source": ["h2h", "spreads", "totals"],
             "sports_in_source": sorted(SUPPORTED_SPORTS),
             "new_sportsbook_calls": 0,
             "source_price_model_probability": None,
             "input_rows": len(lines), "rows_by_sport": sport_counts,
             "source_rows": source_rows, "source_rows_by_sport": source_sport_counts,
             "deferred_rows": source_rows - len(lines),
             "fast_pass_game_cap": max_games,
             "capture_refusals": receipts,
             "status": "READY_FOR_CANONICAL_PRICE" if lines else "NO_FRESH_PAIRED_QUOTES"}
    if not lines:
        return audit, None, ("## SportsEdge · Current value screen\n\n"
                             "No fresh paired DK game-market quotes in the existing capture.\n"
                             "Nothing is inferred or backfilled.\n")
    extra = {}
    if form2_bundles_dir is not None:
        extra = {"form2_bundles_dir": form2_bundles_dir,
                 "form2_manifest_sha256": form2_manifest_sha256}
        audit["form2_bundles_dir_supplied"] = True
        audit["form2_external_pin_supplied"] = form2_manifest_sha256 is not None
    card = runner({"lines": lines}, now=now, as_of=now.isoformat(),
                  auto_context=True, **extra)
    if (not isinstance(card, dict) or
            len(card.get("evaluated_rows") or []) != len(lines)):
        raise ValueError("CANONICAL_VALUE_CARD_ROW_COUNT_INVALID")
    # The quote was fresh at the original capture, but model acquisition may
    # have consumed most/all of the TTL. Enforce the actual render clock.
    final_now = datetime.now(timezone.utc)
    rendered = render(card, now=final_now)
    audit["finished_at_utc"] = final_now.isoformat()
    audit["elapsed_seconds"] = round((final_now - now).total_seconds(), 3)
    return audit, card, rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("artifacts/auto_dk"))
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/auto_dk_cards"))
    parser.add_argument("--max-games", type=int, default=None,
                        help="Process N earliest games first; account for every deferred event")
    parser.add_argument("--form2-bundles-dir", type=Path, default=None)
    parser.add_argument("--form2-manifest-sha256", default=None,
                        help="EXTERNAL pin (owner-supplied); never computed here")
    args = parser.parse_args()
    pin = args.form2_manifest_sha256 or None
    if pin is not None and not (len(pin) == 64 and all(c in "0123456789abcdef" for c in pin)):
        parser.error("form2-manifest-sha256 must be 64 lowercase hex")
    now = datetime.now(timezone.utc)
    try:
        audit, card, markdown = run_capture_directory(
            args.input_dir, now=now, max_games=args.max_games,
            form2_bundles_dir=args.form2_bundles_dir, form2_manifest_sha256=pin)
        result_code = 0
    except Exception as exc:
        # The source capture remains intact. Emit an explicit failure artifact
        # without displaying exception strings that may include provider URLs.
        audit = {"schema": "SPORTSEDGE_AUTO_DK_CANONICAL_V1",
                 "status": "CANONICAL_EXECUTION_FAILED",
                 "generated_at_utc": now.isoformat(),
                 "new_sportsbook_calls": 0,
                 "failure_type": type(exc).__name__,
                 "input_rows": 0, "capture_refusals": []}
        card = None
        markdown = ("## SportsEdge · Current value screen\n\n"
                    "Canonical model execution failed. No priced selections released.\n")
        result_code = 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "current_value_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if card is not None:
        (args.out_dir / "current_value_card.json").write_text(
            json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out_dir / "current_value_card.md").write_text(markdown, encoding="utf-8")
    print(json.dumps({"status": audit["status"],
                      "input_rows": audit["input_rows"],
                      "refusals": len(audit["capture_refusals"]),
                      "new_paid_odds_calls": 0}))
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
