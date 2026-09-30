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

from sportsedge.mlb_card_blocked import blocked_notes  # noqa: E402
from sportsedge.mlb_context_card import context_section  # noqa: E402
from sportsedge.mlb_myspari_own_model import MYSPARI_OWN_MODEL_VERSION, myspari_rows, render_markdown  # noqa: E402
from sportsedge.mlb_quote_move_guard import apply_quote_move_guard  # noqa: E402


PRE_CONTEXT_STATUS = "PRE-CONTEXT · NOT FINAL"


def _observed_at(payload: dict) -> datetime | None:
    stamps = [payload.get("observed_at_utc")] + [g.get("observed_at_utc") for g in payload.get("games") or []]
    parsed = []
    for s in stamps:
        if isinstance(s, str) and s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                parsed.append(dt)
    return min(parsed) if parsed else None


def _load_context_bundles(context_dir: str | None) -> tuple[list[dict], list[dict], dict[str, str]]:
    if not context_dir:
        return [], [], {}
    ctx = Path(context_dir)
    bundles = [json.loads(p.read_text()) for p in sorted(ctx.glob("*.json")) if p.name != "failures.json"]
    failures = json.loads((ctx / "failures.json").read_text()) if (ctx / "failures.json").is_file() else []
    team_sides: dict[str, str] = {}
    for bundle in bundles:
        probable = ((bundle.get("starters") or {}).get("probable_pitchers") or {})
        for side in ("away", "home"):
            pitcher = probable.get(side) or {}
            player_id = pitcher.get("player_id")
            if player_id not in {None, ""}:
                team_sides[str(player_id)] = side.upper()
    return bundles, failures, team_sides


def _prior_rows(snapshot_path: str | None, extra: str | None) -> list[dict]:
    paths: list[Path] = []
    if extra:
        paths.append(Path(extra))
    if snapshot_path:
        current = Path(snapshot_path)
        if current.parent.is_dir():
            paths.extend(sorted(p for p in current.parent.glob("*.json") if p.resolve() != current.resolve()))
    rows: list[dict] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file() or str(path) in seen:
            continue
        seen.add(str(path))
        raw = json.loads(path.read_text())
        chunk = raw.get("rows") if isinstance(raw, dict) else raw
        if isinstance(chunk, list):
            rows.extend(item for item in chunk if isinstance(item, dict))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-output", default="artifacts/manual_mlb_snapshot_card.json")
    ap.add_argument("--snapshot", help="input snapshot JSON (for subject_name labels)")
    ap.add_argument("--prior-snapshot", help="earlier same-game board used only for NEEDS_CONFIRM")
    ap.add_argument("--out-dir", default="artifacts/mlb_myspari")
    ap.add_argument("--as-of", help="override now (tests)")
    ap.add_argument("--context-dir", help="dir of pregame context bundles retrieved this run")
    ap.add_argument(
        "--pre-context",
        action="store_true",
        help="mark this render as PRE-CONTEXT · NOT FINAL; only the context-bound render is the card",
    )
    args = ap.parse_args()

    if args.pre_context and args.context_dir:
        raise SystemExit("--pre-context cannot be combined with --context-dir")

    payload = json.loads(Path(args.engine_output).read_text())
    names: dict[str, str] = {}
    snap_rows = []
    if args.snapshot and Path(args.snapshot).is_file():
        snap = json.loads(Path(args.snapshot).read_text())
        snap_rows = snap.get("rows") if isinstance(snap, dict) else snap
        for row in snap_rows or []:
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

    bundles, failures, team_sides = _load_context_bundles(args.context_dir)
    for res in resolutions:
        if not isinstance(res, dict):
            continue
        side = str(res.get("team_side") or "").upper()
        entity_id = res.get("entity_id")
        if side in {"AWAY", "HOME"} and entity_id not in {None, ""}:
            team_sides.setdefault(str(entity_id), side)

    rows = myspari_rows(payload, quote_age_seconds=age, names=names, team_sides=team_sides)
    rows = apply_quote_move_guard(rows, _prior_rows(args.snapshot, args.prior_snapshot))
    games = payload.get("games") or ([{"resolved_game": payload.get("resolved_game")}] if payload.get("resolved_game") else [])
    notes = []
    for g in games:
        rg = g.get("resolved_game") or {}
        if rg:
            notes.append(f"{rg.get('game_pk')}: {rg.get('away_team')} @ {rg.get('home_team')}, first pitch {rg.get('scheduled_start_utc')}")
    notes.extend(blocked_notes(payload))
    notes.append(f"Lines observed {observed.isoformat() if observed else 'unknown'}; card built {now.isoformat(timespec='seconds')}.")
    if args.snapshot and Path(args.snapshot).is_file():
        raw = Path(args.snapshot).read_bytes()
        notes.append(f"Input board: {args.snapshot} ({len(snap_rows or [])} rows, sha256 {hashlib.sha256(raw).hexdigest()[:12]}); "
                     f"engine returned {len(payload.get('results') or [])} quote results.")
        timestamp_sources = sorted({
            str(row.get("timestamp_source"))
            for row in (snap_rows or [])
            if isinstance(row, dict) and row.get("timestamp_source")
        })
        if timestamp_sources == ["INTAKE_STAMPED"]:
            notes.append("Timestamp provenance: INTAKE_STAMPED at GitHub issue intake/edit time; not a sportsbook timestamp.")
        elif timestamp_sources:
            notes.append(f"Timestamp provenance: {', '.join(timestamp_sources)}.")
    notes.append("Probabilities are the SportsEdge engines' own model_p (engine_registry); this card only pairs, scores and ranks them.")
    notes.append("NOT Truth Gate / NOT OFFICIAL. Unpriceable = NO_MODEL.")
    if any("QUOTE_MOVE_NEEDS_CONFIRM" in (r.get("presentation_reason_codes") or ()) for r in rows):
        notes.append("NEEDS_CONFIRM: a price moved past the frozen screenshot-misread thresholds vs an earlier same-game board. Look twice. Model_p is unchanged.")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if args.pre_context:
        display_rows = [dict(row, scored_status=PRE_CONTEXT_STATUS) for row in rows]
        header = f"SportsEdge MLB {PRE_CONTEXT_STATUS} ({MYSPARI_OWN_MODEL_VERSION})"
        phase = "PRE_CONTEXT_NOT_FINAL"
    else:
        display_rows = rows
        header = f"SportsEdge MLB card ({MYSPARI_OWN_MODEL_VERSION})"
        phase = "CONTEXT_BOUND_CARD" if args.context_dir else "CARD"

    text = render_markdown(display_rows, header=header, notes=notes)
    if args.context_dir:
        text += "\n".join(context_section(bundles, failures=failures)) + "\n"
    (out / "card.md").write_text(text)
    (out / "card.json").write_text(json.dumps({"version": MYSPARI_OWN_MODEL_VERSION, "phase": phase, "rows": rows}, indent=2, default=str))
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
