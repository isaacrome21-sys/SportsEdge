#!/usr/bin/env python3
"""Append an immutable snapshot of a [<SPORT> LINES] issue run to the store.

Called by each sport's lines-issue workflow after the card is rendered:

    python scripts/record_line_snapshot.py --sport mlb --issue "$ISSUE" \
        --body-file issue_body.txt --title "$TITLE" --card-md artifacts/.../card.md \
        [--picks-json picks.json] [--game-start ISO] [--game-json game.json]

Picks come from --picks-json (list of {pick, price, status, ...}) or, for the
MLB card format, are parsed from --card-md. The board is the parsed DK board
for MLB (ParsedRow dicts) and the raw lines for other sports. Exit 0 also when
the snapshot already exists (idempotent rerun). Exit 2 when the body has no
offset-aware Captured line (fail closed; nothing written).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.line_snapshots import (  # noqa: E402
    SNAPSHOT_ROOT,
    SnapshotError,
    append_snapshot,
    build_snapshot,
)


def mlb_board(body: str, title: str | None) -> list[dict]:
    from sportsedge.mlb_issue_body import IssueLinesError, extract_issue_lines
    from sportsedge.mlb_lines_intake import LinesIntakeError, parse_lines_with_warnings

    try:
        rows = parse_lines_with_warnings(extract_issue_lines(body), title=title)[0]
    except (IssueLinesError, LinesIntakeError, TypeError):
        return []
    return [asdict(r) for r in rows]


def raw_board(body: str) -> list[dict]:
    return [{"raw": line.strip()} for line in body.splitlines()[2:] if line.strip()]


def mlb_card_picks(card_md: str) -> list[dict]:
    from scripts.grade_mlb_card import parse_card_rows

    try:
        rows = parse_card_rows(card_md)
    except ValueError:
        return []
    return [{"game_pk": r.game_pk, "pick": r.pick, "price": r.price, "status": r.status} for r in rows]


def verify_mlb_card_quotes(body: str, title: str | None, picks: list[dict]) -> None:
    """Refuse a card-pick snapshot if any price lacks its exact paired issue quote.

    Record price and source quote must agree on the selected side, market,
    handicap and matchup. One game per issue; ambiguous boards cannot supply a
    trustworthy pick/price association. Still allow an empty PAPER pick set.
    """
    from scripts.mlb_card_clv import find_quote, issue_quotes, pick_key

    rows = issue_quotes(body, title)
    if not rows:
        raise SnapshotError("MLB_SNAPSHOT_NO_PARSEABLE_PAIR")
    games = {(r.away, r.home) for r in rows}
    if len(games) != 1:
        raise SnapshotError("MLB_SNAPSHOT_GAME_AMBIGUOUS")
    away, home = next(iter(games))
    names = {"away": away, "home": home}
    for pick in picks:
        label, price = pick.get("pick"), pick.get("price")
        if type(price) is not int:
            raise SnapshotError(f"MLB_SNAPSHOT_CARD_PRICE_INVALID:{label}")
        key = pick_key(str(label or ""), names)
        quote = find_quote(rows, key, names) if key is not None else None
        if quote is None or type(quote[0]) is not int or quote[0] != price:
            raise SnapshotError(f"MLB_SNAPSHOT_CARD_PRICE_UNPAIRED:{label}")


def verify_mlb_game_binding(
    bound: dict, picks: list[dict], captured_at: str, recorded_at: str,
) -> dict:
    """Only a uniquely schedule-bound MLB game may carry a graded card receipt."""
    if not isinstance(bound, dict) or not isinstance(bound.get("rows"), list) or not bound["rows"]:
        raise SnapshotError("MLB_SNAPSHOT_BOUND_GAME_MISSING")
    rows = bound["rows"]
    if (any(not isinstance(r, dict) or type(r.get("game_pk")) is not int
            or r.get("book") != "draftkings" for r in rows)
            or len({r["game_pk"] for r in rows}) != 1):
        raise SnapshotError("MLB_SNAPSHOT_BOUND_GAME_AMBIGUOUS")
    game_pk = rows[0]["game_pk"]
    if game_pk <= 0 or any(type(p.get("game_pk")) is not int or p["game_pk"] != game_pk
                           for p in picks):
        raise SnapshotError("MLB_SNAPSHOT_CARD_GAME_PK_MISMATCH")
    starts = {r.get("first_pitch_at") for r in rows}
    if len(starts) != 1 or not next(iter(starts)):
        raise SnapshotError("MLB_SNAPSHOT_FIRST_PITCH_MISSING")
    start_raw = next(iter(starts))
    try:
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        recorded = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        source_capture = datetime.fromisoformat(str(bound["captured_at"]).replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError) as exc:
        raise SnapshotError("MLB_SNAPSHOT_GAME_CLOCK_INVALID") from exc
    if any(x.tzinfo is None or x.utcoffset() is None for x in (start, captured, recorded, source_capture)):
        raise SnapshotError("MLB_SNAPSHOT_GAME_CLOCK_OFFSET_REQUIRED")
    if source_capture != captured or not (captured < start and recorded < start):
        raise SnapshotError("MLB_SNAPSHOT_START_OR_CAPTURE_MISMATCH")
    return {"game_pk": game_pk, "first_pitch_at": start.isoformat()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", required=True)
    ap.add_argument("--issue", required=True, type=int)
    ap.add_argument("--body-file", required=True, type=Path)
    ap.add_argument("--title", default=None)
    ap.add_argument("--card-md", type=Path, default=None)
    ap.add_argument("--picks-json", type=Path, default=None)
    ap.add_argument("--game-json", type=Path, default=None)
    ap.add_argument("--game-start", default=None)
    ap.add_argument("--bound-input-json", type=Path, default=None,
                    help="MLB: same-run MLB schedule-bounded intake JSON, unique game_pk and first-pitch required")
    ap.add_argument("--require-card-quote-match", action="store_true",
                    help="MLB: refuse any saved pick whose price disagrees with its captured two-sided issue line")
    ap.add_argument("--root", type=Path, default=SNAPSHOT_ROOT)
    args = ap.parse_args(argv)

    sport = args.sport.lower()
    body = args.body_file.read_text(encoding="utf-8")
    if args.picks_json and args.picks_json.exists():
        picks = json.loads(args.picks_json.read_text(encoding="utf-8"))
    elif sport == "mlb" and args.card_md and args.card_md.exists():
        picks = mlb_card_picks(args.card_md.read_text(encoding="utf-8"))
    else:
        picks = []
    game = json.loads(args.game_json.read_text(encoding="utf-8")) if args.game_json else {}
    game.setdefault("title", args.title)
    game.setdefault("matchup", (body.splitlines() or [""])[0].strip())
    if args.game_start:
        game["start"] = args.game_start
    board = mlb_board(body, args.title) if sport == "mlb" else raw_board(body)
    try:
        if sport == "mlb" and args.require_card_quote_match:
            verify_mlb_card_quotes(body, args.title, picks)
        recorded_at = datetime.now(timezone.utc).isoformat()
        if args.bound_input_json:
            if sport != "mlb":
                raise SnapshotError("BOUND_INPUT_MLB_ONLY")
            bound = json.loads(args.bound_input_json.read_text(encoding="utf-8"))
            from sportsedge.line_snapshots import parse_captured_at
            captured = parse_captured_at(body)
            if captured is None:
                raise SnapshotError("MLB_SNAPSHOT_CAPTURE_MISSING")
            game.update(verify_mlb_game_binding(bound, picks, captured.isoformat(), recorded_at))
        record = build_snapshot(
            sport=sport, issue_number=args.issue, body=body, title=args.title, game=game,
            board=board, picks=picks, recorded_at=recorded_at,
        )
    except SnapshotError as exc:
        print(f"SNAPSHOT_REFUSED: {exc}", file=sys.stderr)
        return 2
    wrote = append_snapshot(record, args.root)
    print("SNAPSHOT_APPENDED" if wrote else "SNAPSHOT_DUPLICATE_SKIPPED", record["captured_at"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
