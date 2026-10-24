#!/usr/bin/env python3
"""MLB paired moneyline forward capture from the DraftKings RENDERED PAGE (FORWARD_CAPTURE_PARTIAL).

Replaces the scheduled use of the DK-API direct capture (owner invariant: DK rendered pages
only). The page is rendered by sportsedge.dk_rendered_page_fetcher (headed Chrome, stock
identity, allowlisted public page URL). No API credentials; no DK API URL is built here.

The board card carries no start time, so each rendered event is matched one-to-one to an
already-captured market-blind MLB forward prediction (MLB StatsAPI schedule) by the DK label
nickname -> MLB team id table below and the prediction's home/away team ids. When more than one
scheduled game or rendered card shares the same away/home pair (doubleheaders, World Series G1/G2),
a card is bound to a game only through the card's rendered start label (``cb-start-time-<event>``,
browser-local zone, no year): the label must equal the game's StatsAPI start, and the resulting
card->game binding must be the same under every candidate UTC offset at which any card matches.
Missing/unparseable labels, offset-dependent bindings, unmapped labels and in-window games without
a clean two-sided rendered moneyline block the run (BLOCKED_ONE_SIDED). Nothing is inferred or
filled in; the label is never written as a start time.

Snapshots are immutable and keyed by event, window, observation time and page-HTML hash, as
in the direct capture, so the ledger can select the T30 decision quote and the close.
Grants no promotion authority. SCREEN / NOT_VALIDATED. No backfill: only quotes observed now
for games that have not started are written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

SPORT_KEY = "baseball_mlb"
EVIDENCE_DISPOSITION = "FORWARD_CAPTURE_PARTIAL"
SOURCE_CLASS = "DRAFTKINGS_RENDERED_PAGE_V1"
DEFAULT_OUTPUT_DIR = "data/mlb_forward_capture"
DEFAULT_PREDICTION_ROOT = "data/mlb_forward_predictions"
DEFAULT_PAGE_URL = "https://sportsbook.draftkings.com/leagues/baseball/mlb"
CAPTURE_WINDOWS = (("T60", 45.0, 75.0), ("T30", 20.0, 45.0), ("T10", 0.0, 20.0))
# DK board label nickname (text after the city abbreviation) -> MLB StatsAPI team id.
DK_MLB_NICKNAME_TEAM_ID = {
    "Diamondbacks": 109, "D-backs": 109, "Braves": 144, "Orioles": 110, "Red Sox": 111, "Cubs": 112,
    "White Sox": 145, "Reds": 113, "Guardians": 114, "Rockies": 115, "Tigers": 116, "Astros": 117,
    "Royals": 118, "Angels": 108, "Dodgers": 119, "Marlins": 146, "Brewers": 158, "Twins": 142,
    "Mets": 121, "Yankees": 147, "Athletics": 133, "Phillies": 143, "Pirates": 134, "Padres": 135,
    "Giants": 137, "Mariners": 136, "Cardinals": 138, "Rays": 139, "Rangers": 140, "Blue Jays": 141,
    "Nationals": 120,
}


# Candidate browser UTC offsets (minutes) for the rendered start label; 15-minute grid, -12h..+14h.
LABEL_UTC_OFFSETS_MIN = tuple(range(-12 * 60, 14 * 60 + 1, 15))
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                       "oct", "nov", "dec"), 1)}
_WEEKDAYS = {d: i for i, d in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
_LABEL_RE = re.compile(
    r"^(?:(?P<wd>mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?\s+(?P<mon>[a-z]{3})[a-z]*\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?"
    r"|(?P<rel>today|tomorrow))\s+(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>[ap]m)$", re.I)


class CaptureBlocked(RuntimeError):
    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _parse(value: Any) -> datetime:
    out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return out


def window_for(minutes_before: float):
    for label, low, high in CAPTURE_WINDOWS:
        if low < minutes_before <= high:
            return label
    return None


def label_team_id(label: str) -> int | None:
    parts = str(label or "").split(" ", 1)
    if len(parts) != 2:
        return None
    return DK_MLB_NICKNAME_TEAM_ID.get(parts[1].strip())


def parse_start_label(text: Any) -> dict[str, Any] | None:
    """Parse a DK board start label ('Fri Oct 23rd 7:08 PM', 'Today 7:08 PM'). None if not exact."""
    m = _LABEL_RE.match(" ".join(str(text or "").split()))
    if not m:
        return None
    h, mi = int(m.group("h")), int(m.group("m"))
    if not (1 <= h <= 12 and 0 <= mi <= 59):
        return None
    out: dict[str, Any] = {"hour": h % 12 + (12 if m.group("ap").lower() == "pm" else 0), "minute": mi}
    if m.group("rel"):
        out["rel_days"] = 0 if m.group("rel").lower() == "today" else 1
        return out
    mon = _MONTHS.get(m.group("mon").lower())
    day = int(m.group("day"))
    if mon is None or not 1 <= day <= 31:
        return None
    out.update(weekday=_WEEKDAYS[m.group("wd").lower()[:3]], month=mon, day=day)
    return out


def _label_matches(lab: Mapping[str, Any], start: datetime, observed: datetime, offset_min: int) -> bool:
    tz = timezone(timedelta(minutes=offset_min))
    ls, lo = start.astimezone(tz), observed.astimezone(tz)
    if (ls.hour, ls.minute) != (lab["hour"], lab["minute"]):
        return False
    if "rel_days" in lab:
        return ls.date() == lo.date() + timedelta(days=lab["rel_days"])
    return (ls.month, ls.day, ls.weekday()) == (lab["month"], lab["day"], lab["weekday"])


def bind_by_start_label(preds: list[Mapping[str, Any]], cands: list[Mapping[str, Any]],
                        observed: datetime) -> dict[int, Mapping[str, Any]] | None:
    """Bind same-matchup cards to scheduled games by rendered start label, or None (refuse).

    Every card must carry a parseable label. For each candidate offset, every card may match at
    most one game and no game more than one card; the non-empty binding must be identical under
    every offset at which any card matches. Otherwise the binding is ambiguous and refused.
    """
    labs = [parse_start_label(c.get("start_text")) for c in cands]
    if not cands or any(lab is None for lab in labs):
        return None
    starts = []
    for p in preds:
        try:
            starts.append((int(p["game_pk"]), _parse(p.get("event_start_ts"))))
        except Exception:
            return None
    bindings = set()
    for off in LABEL_UTC_OFFSETS_MIN:
        mapping: dict[int, int] = {}
        for ci, lab in enumerate(labs):
            hits = [pk for pk, st in starts if _label_matches(lab, st, observed, off)]
            if len(hits) > 1 or (hits and hits[0] in mapping):
                return None
            if hits:
                mapping[hits[0]] = ci
        if mapping:
            bindings.add(frozenset(mapping.items()))
    if len(bindings) != 1:
        return None
    return {pk: cands[ci] for pk, ci in next(iter(bindings))}


def _predictions(root: str | Path) -> list[dict[str, Any]]:
    out = []
    base = Path(root)
    if not base.is_dir():
        return out
    for p in sorted(base.rglob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("market") == "MONEYLINE" and rec.get("game_pk") is not None:
            out.append(rec)
    by_pk: dict[int, dict[str, Any]] = {}
    for rec in out:
        by_pk.setdefault(int(rec["game_pk"]), rec)
    return list(by_pk.values())


def _default_fetch(url: str, sport_key: str) -> dict[str, Any]:
    from sportsedge.dk_rendered_page_fetcher import fetch_rendered_board
    return fetch_rendered_board(url, sport_key=sport_key)


def _snapshot_key(game_pk: int, event_id: str, window: str, observed: datetime, raw_sha256: str) -> str:
    raw = str(raw_sha256 or "").lower()
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
        raise CaptureBlocked("BLOCKED_RAW_SHA256", raw_sha256)
    return f"{event_id}__{window}__{observed.strftime('%Y%m%dT%H%M%S%fZ')}__{raw[:16]}"


def _rendered_pairs(board: Mapping[str, Any]) -> dict[tuple[int | None, int | None], list[dict[str, Any]]]:
    by_event: dict[str, list[dict[str, Any]]] = {}
    for r in board.get("rows") or []:
        if r.get("market") == "h2h" and r.get("status") == "OK":
            by_event.setdefault(str(r["provider_event_id"]), []).append(r)
    pairs: dict[tuple[int | None, int | None], list[dict[str, Any]]] = {}
    for eid, rows in by_event.items():
        if len(rows) != 2:
            continue
        away_label, home_label = rows[0]["away_team"], rows[0]["home_team"]
        home = next((r for r in rows if r["outcome"] == home_label), None)
        away = next((r for r in rows if r["outcome"] == away_label), None)
        if home is None or away is None:
            continue
        key = (label_team_id(away_label), label_team_id(home_label))
        texts = {r.get("board_start_time_text") for r in rows}
        pairs.setdefault(key, []).append({"event_id": eid, "home": home, "away": away,
                                          "away_label": away_label, "home_label": home_label,
                                          "start_text": texts.pop() if len(texts) == 1 else None})
    return pairs


def capture(*, output_dir=DEFAULT_OUTPUT_DIR, prediction_root=DEFAULT_PREDICTION_ROOT,
            fetch: Callable[[str, str], Mapping[str, Any]] | None = None, artifact_binder=None,
            page_url: str = DEFAULT_PAGE_URL):
    if artifact_binder is None:
        from sportsedge.mlb_model_artifact import mlb_model_artifact_sha256
        artifact_binder = mlb_model_artifact_sha256
    try:
        artifact_sha = artifact_binder()
    except Exception as exc:
        raise CaptureBlocked("BLOCKED_ARTIFACT", str(exc)) from exc
    try:
        board = (fetch or _default_fetch)(page_url, SPORT_KEY)
    except Exception as exc:
        raise CaptureBlocked("BLOCKED_TRANSPORT", type(exc).__name__ + ":" + str(exc)[:200]) from exc
    raw_sha = board.get("page_html_sha256")
    if board.get("page_status") != "OK" or not board.get("rows") and not board.get("card_refusals"):
        raise CaptureBlocked("BLOCKED_EMPTY_BOARD", {"page_status": board.get("page_status"),
                                                     "raw_sha256": raw_sha, "source_uri": board.get("source_uri")})
    observed = _parse(board["observed_at_utc"])
    pairs = _rendered_pairs(board)
    out_rows, anomalies, in_window = [], [], 0
    for pred in sorted(_predictions(prediction_root), key=lambda r: int(r["game_pk"])):
        try:
            start = _parse(pred.get("event_start_ts"))
        except Exception:
            continue
        if not observed < start:
            continue
        minutes_before = (start - observed).total_seconds() / 60.0
        window = window_for(minutes_before)
        if window is None:
            continue
        in_window += 1
        game_pk = int(pred["game_pk"])
        key = (pred.get("away_team_id"), pred.get("home_team_id"))
        same_matchup = [p for p in _predictions(prediction_root)
                        if (p.get("away_team_id"), p.get("home_team_id")) == key]
        cands = pairs.get(key, [])
        if not cands:
            anomalies.append({"game_pk": game_pk, "capture_window": window, "reason": "NO_TWO_SIDED_RENDERED_MONEYLINE"})
            continue
        if len(same_matchup) == 1 and len(cands) == 1:
            out_rows.append((game_pk, window, minutes_before, start, pred, cands[0], "SOLE_MATCHUP_ON_BOARD_AND_SCHEDULE"))
            continue
        bound = bind_by_start_label(same_matchup, cands, observed)
        if bound is None or game_pk not in bound:
            anomalies.append({"game_pk": game_pk, "capture_window": window,
                              "reason": "AMBIGUOUS_SCHEDULE_MATCH" if len(same_matchup) != 1 else "AMBIGUOUS_RENDERED_MATCH",
                              "board_start_labels": [c.get("start_text") for c in cands]})
            continue
        out_rows.append((game_pk, window, minutes_before, start, pred, bound[game_pk],
                         "BOARD_START_LABEL_UNIQUE_ACROSS_OFFSETS"))
    if anomalies:
        raise CaptureBlocked("BLOCKED_ONE_SIDED", {"anomalies": anomalies,
                                                   "unmapped_labels": sorted({lbl for k, v in pairs.items() if None in k
                                                                              for x in v for lbl in (x["away_label"], x["home_label"])})})
    slate = observed.date().isoformat()
    base = Path(output_dir) / slate
    written, skipped = [], []
    for game_pk, window, minutes_before, start, pred, c, match_basis in out_rows:
        key = _snapshot_key(game_pk, c["event_id"], window, observed, raw_sha)
        path = base / f"{key}.json"
        if path.exists():
            skipped.append(key)
            continue
        record = {
            "evidence_disposition": EVIDENCE_DISPOSITION, "promotion_authority": False,
            "source_class": SOURCE_CLASS, "sportsbook": "draftkings", "provider": board.get("provider"),
            "sport_key": SPORT_KEY, "provider_event_id": c["event_id"], "game_pk": game_pk,
            "home_team": pred["home_team"], "away_team": pred["away_team"],
            "home_team_id": pred.get("home_team_id"), "away_team_id": pred.get("away_team_id"),
            "home_team_label": c["home_label"], "away_team_label": c["away_label"],
            "board_start_time_text": c.get("start_text"), "event_match_basis": match_basis,
            "scheduled_start_utc": start.isoformat(),
            "scheduled_start_source": "MLB_FORWARD_PREDICTION_EVENT_START_TS_STATSAPI",
            "observed_at_utc": board["observed_at_utc"], "capture_window": window,
            "minutes_before_start": round(minutes_before, 2),
            "pit_basis": "OBSERVED_AT_UTC_VS_SCHEDULED_START_UTC", "quote_side_skew_seconds": 0,
            "quote_synchronization": "SINGLE_DOM_SNAPSHOT_BOTH_SIDES",
            "quote_synchronization_note": "Both sides were read from one rendered DOM snapshot. This is NOT two independently timestamped quotes.",
            "book_last_update": None, "provider_quote_timestamp_available": False,
            "moneyline": {"status": "OK", "home_price_american": c["home"]["price_american"],
                          "away_price_american": c["away"]["price_american"]},
            "capture_observation_id": key, "model_artifact_sha256": artifact_sha,
            "model_artifact_grants_promotion": False, "raw_sha256": raw_sha,
            "source_uri": board.get("source_uri"), "final_url": board.get("final_url"),
            "browser": board.get("browser"), "status_label": "SCREEN", "validation": "NOT_VALIDATED",
            "capture_module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "captured_at_utc": board["observed_at_utc"],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, sort_keys=True))
        written.append(str(path))
    summary = {"evidence_disposition": EVIDENCE_DISPOSITION, "slate_date": slate, "already_present": skipped,
               "events_on_board": sum(len(v) for v in pairs.values()), "events_in_window": in_window,
               "paths": written, "raw_sha256": raw_sha, "model_artifact_sha256": artifact_sha,
               "source_class": SOURCE_CLASS}
    if not written:
        return {"status": "ALREADY_CAPTURED" if skipped else "NO_CAPTURE_DUE", "observations_retained": 0, **summary}
    return {"status": "RETAINED", "observations_retained": len(written), **summary}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    ap.add_argument("--prediction-root", default=DEFAULT_PREDICTION_ROOT)
    args = ap.parse_args(argv)
    try:
        result = capture(output_dir=args.output_dir, prediction_root=args.prediction_root)
    except CaptureBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "reason": exc.reason, "detail": exc.detail,
                          "evidence_disposition": EVIDENCE_DISPOSITION, "promotion_authority": False}, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
