#!/usr/bin/env python3
"""One offline RUN IT command over previously captured, paired DK snapshots.

Canonical research pricing only. No sportsbook requests, no admission,
no wagering, no historical backfill. A ranked screen is NOT a verified PLAY.
The market-family audit is required even when all priced rows succeed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.audit_auto_dk_market_census import audit as market_census
from scripts.run_auto_dk_live_value_card import run_capture_directory


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _short(value, limit=65):
    s = " ".join(str(value or "MISSING").split())
    return s if len(s) <= limit else s[:limit - 1] + "…"


def render_png(summary, rows, path: Path):
    """A visual *research* summary, using the same ranked fresh screens."""
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (1440, 1536), "#09111e")
    draw = ImageDraw.Draw(im)
    def face(size, bold=False):
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            return ImageFont.load_default()

    white, cyan, muted, yellow = "#f1f8ff", "#3fe1fa", "#adbed1", "#ffbb54"
    draw.rectangle((0, 0, 1440, 12), fill=cyan)
    draw.text((60, 45), "SPORTSEDGE  /  RUN IT", font=face(53, True), fill=white)
    draw.text((60, 126), "ONE RANKED RESEARCH CARD  ·  0 VERIFIED PLAYS",
              font=face(25, True), fill=yellow)
    coverage = summary["market_coverage"]
    draw.text((60, 183),
              f"Auto requested: {coverage['families_requested_but_unverified']}/"
              f"{coverage['required_family_count']} sport/market families",
              font=face(25), fill=muted)
    draw.text((60, 222),
              "Requested does not mean captured; NHL and many props absent.",
              font=face(23), fill=muted)
    draw.line((60, 283, 1380, 283), fill="#315066", width=3)
    draw.text((60, 314), "CURRENT PREGAME VALUE SCREENS (UNVALIDATED)",
              font=face(28, True), fill=cyan)
    if not rows:
        draw.text((65, 425), "NO FRESH QUALIFYING RESEARCH SCREENS",
                  font=face(30, True), fill=white)
        draw.text((65, 480), _short(summary["status"], 75),
                  font=face(23), fill=muted)
    else:
        for index, entry in enumerate(rows[:7]):
            top = 385 + index * 144
            draw.rounded_rectangle((56, top, 1384, top + 130),
                                   radius=16, fill="#132338", outline="#294760", width=2)
            game = _short(entry.get("game"), 50)
            sport = _short(entry.get("sport"), 8)
            draw.text((79, top + 13), f"{index + 1}. {sport}  {game}",
                      font=face(24, True), fill=white)
            market = _short(" ".join(str(entry.get(k) or "") for k in
                                      ("player_name", "market", "selection", "line")), 66)
            draw.text((79, top + 51), market, font=face(22), fill=muted)
            odds = entry.get("odds")
            odds_text = f"+{odds}" if isinstance(odds, (int, float)) and odds > 0 else str(odds)
            ev = entry.get("rank_ev")
            ev_text = f"{100 * ev:+.1f}%" if isinstance(ev, (int, float)) else "MISSING"
            draw.text((1035, top + 17), f"DK {odds_text}", font=face(22, True), fill=yellow)
            draw.text((1035, top + 53), f"EV {ev_text}", font=face(25, True), fill=cyan)
            draw.text((79, top + 91), "MODEL " + _short(entry.get("model_version"), 72),
                      font=face(17), fill=muted)
    draw.line((60, 1430, 1380, 1430), fill="#315066", width=3)
    draw.text((60, 1450), "RESEARCH ONLY  ·  Not a wager or a validated edge",
              font=face(22, True), fill=yellow)
    draw.text((60, 1483), "Quotes expire after 180 seconds. Refresh before any decision.",
              font=face(19), fill=muted)
    im.save(path, "PNG")
    return str(path)


def create_bundle(input_dir: Path, out_dir: Path, *, now=None,
                  max_games=None, adapter=None, screen_builder=None,
                  png_writer=None, final_now=None):
    """Bundle one canonical run; dependencies injectable for offline tests."""
    instant = _utc_now() if now is None else now
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("RUN_IT_CLOCK_REQUIRES_TIMEZONE")
    adapter = run_capture_directory if adapter is None else adapter
    if screen_builder is None:
        from sportsedge.phone_display import build_current_value_screens
        screen_builder = build_current_value_screens
    png_writer = render_png if png_writer is None else png_writer

    audit, card, markdown = adapter(input_dir, now=instant, max_games=max_games)
    # This clock MUST be read after the potentially slow canonical run.
    actual_final = _utc_now() if final_now is None else final_now
    if actual_final.tzinfo is None or actual_final.utcoffset() is None:
        raise ValueError("RUN_IT_FINAL_CLOCK_REQUIRES_TIMEZONE")
    if not isinstance(audit, dict) or card is not None and not isinstance(card, dict):
        raise ValueError("CANONICAL_BUNDLE_SCHEMA_INVALID")
    screen = {"unverified_model_value_screens": [], "total_positive_screens": 0}
    status = "NO_FRESH_PAIRED_QUOTES" if card is None else "RESEARCH_SCREEN_ONLY"
    if card is not None:
        try:
            # Re-check freshness at the PNG's own finalization clock.
            screen = screen_builder(card, now=actual_final)
            if not isinstance(screen, dict) or not isinstance(
                    screen.get("unverified_model_value_screens"), list):
                raise ValueError("SCREEN_SCHEMA_INVALID")
        except (ValueError, TypeError, KeyError):
            status = "SCREEN_RENDER_REFUSED"
            screen = {"unverified_model_value_screens": [], "total_positive_screens": 0}
            markdown = ("## SportsEdge · RUN IT\n\n"
                        "Final screen verification failed. No selections released.\n")
    rows = screen["unverified_model_value_screens"]
    coverage = market_census()
    summary = {
        "schema": "SPORTSEDGE_ONE_COMMAND_OFFLINE_RUN_IT_V1",
        "status": status, "new_paid_odds_calls": 0,
        "canonical_audit": audit, "market_coverage": coverage,
        "ranked_research_screens": len(rows), "verified_plays": 0,
        "play_authority": False, "full_board_scanned": False,
        "capture_files_are_preexisting": True,
        "rendered_at_utc": actual_final.astimezone(timezone.utc).isoformat(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run_it_audit.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "run_it_card.md").write_text(
        markdown + "\n\nMarket-family coverage is INCOMPLETE; "
        "requested markets are not proof of received prices. "
        "No verified PLAYs or sportsbook calls.\n", encoding="utf-8")
    if card is not None:
        (out_dir / "run_it_card.json").write_text(
            json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        png_writer(summary, rows, out_dir / "run_it_card.png")
    except (OSError, ValueError, ImportError):
        summary["status"] = "PNG_RENDER_FAILED"
        (out_dir / "run_it_audit.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-dir", type=Path, default=Path("artifacts/auto_dk"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/run_it_auto"))
    ap.add_argument("--max-games", type=int, default=None)
    args = ap.parse_args(argv)
    try:
        result = create_bundle(args.input_dir, args.out_dir, max_games=args.max_games)
    except (ValueError, TypeError, OSError, KeyError) as exc:
        # Never leak URL-bearing exception messages or create a fictitious card.
        print(json.dumps({"status": "RUN_IT_FAILED_CLOSED",
                          "reason_type": type(exc).__name__, "verified_plays": 0}))
        return 2
    print(json.dumps({"status": result["status"], "verified_plays": 0,
                      "research_screens": result["ranked_research_screens"],
                      "out_dir": str(args.out_dir)}))
    return 2 if result["status"] in {"PNG_RENDER_FAILED", "SCREEN_RENDER_REFUSED"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
