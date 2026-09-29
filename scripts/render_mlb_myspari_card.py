#!/usr/bin/env python3
"""Render the SportsEdge MLB manual-snapshot output as a MySpariEdge-style card.

Reads artifacts/manual_mlb_snapshot_card.json (SportsEdge engine output) plus the
input snapshot (for optional subject_name labels) and writes card.md / card.json.
"""
from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.mlb_context_card import context_section  # noqa: E402
from sportsedge.mlb_myspari_own_model import MYSPARI_OWN_MODEL_VERSION, myspari_rows, render_markdown  # noqa: E402


def _observed_at(payload: dict) -> datetime | None:
    stamps = [payload.get("observed_at_utc")] + [g.get("observed_at_utc") for g in payload.get("games") or []]
    parsed = []
    for s in stamps:
        if isinstance(s, str) and s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                parsed.append(dt)
    return min(parsed) if parsed else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-output", default="artifacts/manual_mlb_snapshot_card.json")
    ap.add_argument("--snapshot", help="input snapshot JSON (for subject_name labels)")
    ap.add_argument("--out-dir", default="artifacts/mlb_myspari")
    ap.add_argument("--as-of", help="override now (tests)")
    ap.add_argument("--context-dir", help="dir of pregame context bundles retrieved this run")
    args = ap.parse_args()

    payload = json.loads(Path(args.engine_output).read_text())
    names: dict[str, str] = {}
    if args.snapshot and Path(args.snapshot).is_file():
        snap = json.loads(Path(args.snapshot).read_text())
        rows = snap.get("rows") if isinstance(snap, dict) else snap
        for row in rows or []:
            if isinstance(row, dict) and row.get("subject_id") and row.get("subject_name"):
                names[str(row["subject_id"])] = str(row["subject_name"])
    resolutions = list(payload.get("market_resolution") or [])
    for g in payload.get("games") or []:
        resolutions += list(g.get("market_resolution") or [])
    for res in resolutions:
        if isinstance(res, dict) and res.get("subject_id") and res.get("subject_name"):
            names.setdefault(str(res["subject_id"]), str(res["subject_name"]))
    now = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
    observed = _observed_at(payload)
    age = max((now - observed).total_seconds(), 0.0) if observed else 0.0

    rows = myspari_rows(payload, quote_age_seconds=age, names=names)
    games = payload.get("games") or ([{"resolved_game": payload.get("resolved_game")}] if payload.get("resolved_game") else [])
    notes = []
    for g in games:
        rg = g.get("resolved_game") or {}
        if rg:
            notes.append(f"{rg.get('game_pk')}: {rg.get('away_team')} @ {rg.get('home_team')}, first pitch {rg.get('scheduled_start_utc')}")
    notes.append(f"Lines observed {observed.isoformat() if observed else 'unknown'}; card built {now.isoformat(timespec='seconds')}.")
    if args.snapshot and Path(args.snapshot).is_file():
        raw = Path(args.snapshot).read_bytes()
        snap_obj = json.loads(raw)
        snap_rows = snap_obj.get("rows") if isinstance(snap_obj, dict) else snap_obj
        notes.append(f"Input board: {args.snapshot} ({len(snap_rows or [])} rows, sha256 {hashlib.sha256(raw).hexdigest()[:12]}); "
                     f"engine returned {len(payload.get('results') or [])} quote results.")
    notes.append("Probabilities are the SportsEdge engines' own model_p (engine_registry); this card only pairs, scores and ranks them.")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    text = render_markdown(rows, header=f"SportsEdge MLB card ({MYSPARI_OWN_MODEL_VERSION})", notes=notes)
    if args.context_dir:
        ctx = Path(args.context_dir)
        bundles = [json.loads(p.read_text()) for p in sorted(ctx.glob("*.json")) if p.name != "failures.json"]
        failures = json.loads((ctx / "failures.json").read_text()) if (ctx / "failures.json").is_file() else []
        text += "\n".join(context_section(bundles, failures=failures)) + "\n"
    (out / "card.md").write_text(text)
    (out / "card.json").write_text(json.dumps({"version": MYSPARI_OWN_MODEL_VERSION, "rows": rows}, indent=2, default=str))
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
