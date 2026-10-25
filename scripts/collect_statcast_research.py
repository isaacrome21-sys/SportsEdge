#!/usr/bin/env python3
"""Scoped Baseball Savant Statcast CSV intake for research archiving.

REGISTERED RESEARCH SOURCE (see docs/statcast_research_20261024.md):
Baseball Savant pitch-level data (exit velo, spin, whiff, xwOBA) archived
raw with provenance, as the quality layer under the MLB pitcher-K family.
Research/archive only: no pricing-path import, no model probability,
no PLAY authorization, no staking or forward-clock authority.

This is the scoped, stdlib-only sibling of scripts/refresh_statcast_daily.py
(which aggregates via pybaseball into daily snapshots). This collector pulls
a deliberately small window (default one day, hard cap MAX_WINDOW_DAYS),
caches the UNCHANGED provider CSV plus a normalized per-pitch CSV and a
manifest (window, rows, sha256), and applies any player/game filters
client-side because the provider's player_id parameter is not reliable
(verified 2026-10-24: a pull scoped to one pitcher returned the full game).

Cross-check semantics verified against MLB StatsAPI for WS G1 2026
(game_pk 849805, all nine pitchers): Statcast strikeout events are
{"strikeout", "strikeout_double_play"} (the double-play form is a real
strikeout in the box score), and rows with description "automatic_ball" /
"automatic_strike" are pitch-clock violations that StatsAPI does NOT count
in numberOfPitches -- hence the is_thrown_pitch flag below, which makes
thrown-pitch counts reconcile exactly with the box score.

Live calls are explicit: with no --live flag the command performs zero
network requests and only prints the URL it would fetch.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

SAVANT_CSV = "https://baseballsavant.mlb.com/statcast_search/csv"
USER_AGENT = "SportsEdge-StatcastResearch/1.0 (research archive; stdlib)"
MAX_WINDOW_DAYS = 3
PROVIDER_ROW_CAP = 25000  # verified 2026-10-24: unscoped pulls stop here
DEFAULT_OUT_DIR = "research/statcast_archive"
SOURCE_LABEL = "BASEBALL_SAVANT_STATCAST_CSV"
STRIKEOUT_EVENTS = frozenset({"strikeout", "strikeout_double_play"})
NON_THROWN_DESCRIPTIONS = frozenset({"automatic_ball", "automatic_strike"})
SWINGING_STRIKE_DESCRIPTIONS = frozenset(
    {"swinging_strike", "swinging_strike_blocked", "foul_tip"}
)
REQUIRED_COLUMNS = frozenset(
    {
        "game_pk",
        "game_date",
        "pitcher",
        "batter",
        "description",
        "events",
        "pitch_type",
        "at_bat_number",
        "pitch_number",
    }
)


class IntakeRefusal(ValueError):
    """Expected fail-closed provider, window, or payload refusal."""


def build_search_url(start: date, end: date) -> str:
    """Provider CSV URL for the inclusive window; refuses oversized windows."""
    if end < start:
        raise IntakeRefusal("WINDOW_END_BEFORE_START")
    if (end - start).days + 1 > MAX_WINDOW_DAYS:
        raise IntakeRefusal(
            f"WINDOW_TOO_WIDE: {(end - start).days + 1} days > cap {MAX_WINDOW_DAYS}"
        )
    params = {
        "all": "true",
        "hfGT": "R|PO|S|",
        "hfSea": f"{start.year}|",
        "player_type": "pitcher",
        "game_date_gt": start.isoformat(),
        "game_date_lt": end.isoformat(),
        "min_pitches": "0",
        "min_results": "0",
        "group_by": "name",
        "sort_pitches": "0",
        "player_event_sort": "api_p_release_speed",
        "sort_x": "-1",
        "sort_y": "-1",
        "type": "details",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{SAVANT_CSV}?{query}"


def fetch_csv(url: str, opener=None) -> bytes:
    """One explicit live GET. Tests inject an offline opener."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    if opener is None:
        with urlopen(request, timeout=300) as response:
            return response.read()
    return opener(request)


def parse_pitches(raw: bytes) -> list[dict]:
    """Decode provider CSV bytes into raw per-pitch row dicts (fail closed)."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IntakeRefusal(f"PAYLOAD_NOT_UTF8: {exc}") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise IntakeRefusal("PAYLOAD_NO_HEADER")
    missing = REQUIRED_COLUMNS - {name.strip() for name in reader.fieldnames if name}
    if missing:
        raise IntakeRefusal(f"PAYLOAD_MISSING_COLUMNS: {sorted(missing)}")
    rows = []
    for row in reader:
        if row.get("game_pk") in (None, ""):
            continue
        rows.append({(k.strip() if k else k): v for k, v in row.items()})
    if not rows:
        raise IntakeRefusal("PAYLOAD_NO_ROWS")
    if len(rows) >= PROVIDER_ROW_CAP:
        raise IntakeRefusal(
            f"PAYLOAD_ROW_CAP_SUSPECT: {len(rows)} rows hits the provider's "
            f"{PROVIDER_ROW_CAP}-row response cap; the window may be "
            "truncated -- narrow the window and re-pull"
        )
    return rows


def is_thrown_pitch(row: dict) -> bool:
    """Pitch-clock violation rows are recorded by Savant but never thrown."""
    return (row.get("description") or "") not in NON_THROWN_DESCRIPTIONS


def is_strikeout_event(row: dict) -> bool:
    """Box-score strikeouts include the strikeout_double_play event form."""
    return (row.get("events") or "") in STRIKEOUT_EVENTS


def apply_filters(rows, pitcher_id=None, batter_id=None, game_pk=None):
    """Client-side scoping; the provider player_id parameter is unreliable."""
    out = rows
    if pitcher_id is not None:
        out = [r for r in out if _as_int(r.get("pitcher")) == pitcher_id]
    if batter_id is not None:
        out = [r for r in out if _as_int(r.get("batter")) == batter_id]
    if game_pk is not None:
        out = [r for r in out if _as_int(r.get("game_pk")) == game_pk]
    return out


def _as_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def pitcher_game_summary(rows) -> list[dict]:
    """Per-(game, pitcher) aggregates that reconcile with the box score."""
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (_as_int(row.get("game_pk")), _as_int(row.get("pitcher")))
        groups.setdefault(key, []).append(row)
    summary = []
    for (game_pk, pitcher), group in sorted(groups.items()):
        velocities = [
            v for v in (_as_float(r.get("release_speed")) for r in group) if v is not None
        ]
        summary.append(
            {
                "game_pk": game_pk,
                "pitcher": pitcher,
                "player_name": group[0].get("player_name"),
                "pitch_rows": len(group),
                "thrown_pitches": sum(1 for r in group if is_thrown_pitch(r)),
                "strikeouts": sum(1 for r in group if is_strikeout_event(r)),
                "swinging_strikes": sum(
                    1
                    for r in group
                    if (r.get("description") or "") in SWINGING_STRIKE_DESCRIPTIONS
                ),
                "mean_release_speed": (
                    round(sum(velocities) / len(velocities), 2) if velocities else None
                ),
                "max_release_speed": max(velocities) if velocities else None,
            }
        )
    return summary


def normalize_rows(rows, source_url: str, fetched_at: datetime) -> list[dict]:
    """Raw per-pitch rows plus provenance and the two cross-check flags."""
    stamp = fetched_at.astimezone(timezone.utc).isoformat()
    out = []
    for row in rows:
        record = dict(row)
        record["source"] = SOURCE_LABEL
        record["source_url"] = source_url
        record["fetched_at_utc"] = stamp
        record["is_thrown_pitch"] = is_thrown_pitch(row)
        record["is_strikeout_event"] = is_strikeout_event(row)
        out.append(record)
    return out


def _write_csv(path: Path, rows: list[dict]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key is not None and key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def archive_pull(raw: bytes, rows: list[dict], *, start: date, end: date,
                 source_url: str, out_dir: Path, fetched_at: datetime,
                 pitcher_id=None, batter_id=None, game_pk=None) -> dict:
    """Cache raw + normalized CSVs and a provenance manifest; return it."""
    kept = apply_filters(rows, pitcher_id=pitcher_id, batter_id=batter_id,
                         game_pk=game_pk)
    if not kept:
        raise IntakeRefusal("FILTER_REMOVED_ALL_ROWS")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = start.isoformat() if start == end else f"{start.isoformat()}_{end.isoformat()}"
    raw_path = out_dir / f"statcast_raw_{tag}.csv"
    normalized_path = out_dir / f"statcast_pitches_{tag}.csv"
    raw_path.write_bytes(raw)
    normalized = normalize_rows(kept, source_url, fetched_at)
    _write_csv(normalized_path, normalized)
    manifest = {
        "schema": "SPORTSEDGE_STATCAST_RESEARCH_ARCHIVE_V1",
        "source": SOURCE_LABEL,
        "source_url": source_url,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "filters": {"pitcher_id": pitcher_id, "batter_id": batter_id,
                    "game_pk": game_pk, "applied": "client_side"},
        "fetched_at_utc": fetched_at.astimezone(timezone.utc).isoformat(),
        "raw": {
            "file": raw_path.name,
            "bytes": len(raw),
            "rows": len(rows),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "normalized": {
            "file": normalized_path.name,
            "rows": len(normalized),
        },
        "pitcher_game_summary": pitcher_game_summary(kept),
        "labels": {
            "research_archive_only": True,
            "pricing_input": False,
            "model_probability": False,
            "play_authorized": False,
            "staking_authorized": False,
            "forward_clock_authority": False,
        },
    }
    manifest_path = out_dir / f"statcast_manifest_{tag}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="single day YYYY-MM-DD (default window)")
    parser.add_argument("--start", help="window start YYYY-MM-DD")
    parser.add_argument("--end", help="window end YYYY-MM-DD")
    parser.add_argument("--pitcher-id", type=int)
    parser.add_argument("--batter-id", type=int)
    parser.add_argument("--game-pk", type=int)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--live", action="store_true",
                        help="actually fetch; without it, print the URL only")
    args = parser.parse_args(argv)
    if args.date:
        start = end = date.fromisoformat(args.date)
    elif args.start and args.end:
        start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    else:
        end = datetime.now(timezone.utc).date() - timedelta(days=1)
        start = end
    url = build_search_url(start, end)
    if not args.live:
        print("DRY_RUN (zero network requests). Would fetch:")
        print(url)
        return 0
    raw = fetch_csv(url)
    rows = parse_pitches(raw)
    manifest = archive_pull(
        raw, rows, start=start, end=end, source_url=url,
        out_dir=Path(args.out_dir), fetched_at=datetime.now(timezone.utc),
        pitcher_id=args.pitcher_id, batter_id=args.batter_id,
        game_pk=args.game_pk,
    )
    print(json.dumps({k: manifest[k] for k in ("window", "raw", "normalized")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
