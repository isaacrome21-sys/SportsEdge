"""Offline per-game probable-starter capture records (MLB). Research only.

There is NO scheduler, no network call and no activation here. A future runner would
call these pure functions. Snapshot slots are keyed to each game's first pitch.
Delivery is best effort: scheduled jobs can be delayed or dropped, so no slot
(including T-5m) is guaranteed. Every slot ends as ON_TIME, LATE or MISSED.
Evidence hashes are anchored outside the editable capture file via
``anchor_digest``. Output never carries probabilities, prices or eligibility.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

SCHEMA = "MLB_PROBABLE_STARTER_CAPTURE_V1"
# slot -> (offset before first pitch, tolerance after due)
SLOTS = {
    "T-24h": (timedelta(hours=24), timedelta(minutes=30)),
    "T-6h": (timedelta(hours=6), timedelta(minutes=15)),
    "T-90m": (timedelta(minutes=90), timedelta(minutes=10)),
    "T-30m": (timedelta(minutes=30), timedelta(minutes=5)),
    "T-5m": (timedelta(minutes=5), timedelta(minutes=2)),
}
# Regular season plus explicit postseason types (F wild card, D division series,
# L league championship, W World Series); spring/exhibition/ASG captured but labeled.
POSTSEASON_TYPES = frozenset({"F", "D", "L", "W"})
GAME_TYPES = frozenset({"R"}) | POSTSEASON_TYPES | frozenset({"S", "E", "A"})
GUARANTEE = "BEST_EFFORT_NO_SLOT_GUARANTEED"


class CaptureError(ValueError):
    pass


def _utc(v: str | datetime) -> datetime:
    t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise CaptureError("TIMEZONE_REQUIRED")
    return t.astimezone(timezone.utc)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def parse_games(response: Mapping[str, Any]) -> list[dict]:
    out = []
    for d in response.get("dates") or []:
        for g in d.get("games") or []:
            gt = g.get("gameType")
            if gt not in GAME_TYPES:
                raise CaptureError(f"GAME_TYPE_UNKNOWN:{gt}")
            pp = {s: ((g["teams"][s].get("probablePitcher") or {}).get("id")) for s in ("away", "home")}
            out.append({"gamePk": int(g["gamePk"]), "gameType": gt, "postseason": gt in POSTSEASON_TYPES,
                        "first_pitch_utc": _utc(g["gameDate"]).isoformat(),
                        "away_team_id": g["teams"]["away"]["team"]["id"],
                        "home_team_id": g["teams"]["home"]["team"]["id"],
                        "away_probable_id": pp["away"], "home_probable_id": pp["home"]})
    return out


def plan_slots(first_pitch: str | datetime) -> dict[str, dict]:
    fp = _utc(first_pitch)
    return {s: {"due_utc": (fp - off).isoformat(), "close_utc": (fp - off + tol).isoformat()}
            for s, (off, tol) in SLOTS.items()}


def record_snapshot(*, raw: bytes, received_at: str | datetime, slot: str, game_pk: int,
                    prior: Mapping[str, Any] | None = None) -> dict:
    """One receipt. received_at is the actual receipt time, never the due time."""
    if slot not in SLOTS:
        raise CaptureError("SLOT_UNKNOWN")
    rec_at = _utc(received_at)
    games = [g for g in parse_games(json.loads(raw)) if g["gamePk"] == int(game_pk)]
    if len(games) != 1:
        raise CaptureError("GAME_NOT_IN_RESPONSE")
    g = games[0]
    plan = plan_slots(g["first_pitch_utc"])[slot]
    due, close = _utc(plan["due_utc"]), _utc(plan["close_utc"])
    if rec_at >= _utc(g["first_pitch_utc"]):
        status = "AFTER_FIRST_PITCH"
    elif rec_at < due:
        status = "EARLY"
    else:
        status = "ON_TIME" if rec_at <= close else "LATE"
    changes = []
    if prior:
        for k in ("away_probable_id", "home_probable_id"):
            if prior.get(k) != g[k]:
                changes.append({"kind": "STARTER_CHANGE", "field": k, "from": prior.get(k), "to": g[k]})
        if prior.get("first_pitch_utc") != g["first_pitch_utc"]:
            changes.append({"kind": "SCHEDULE_CHANGE", "from": prior.get("first_pitch_utc"), "to": g["first_pitch_utc"]})
    return {"schema": SCHEMA, "gamePk": g["gamePk"], "slot": slot, "status": status,
            "received_at_utc": rec_at.isoformat(), "due_utc": plan["due_utc"], **g,
            "response_sha256": sha256_bytes(raw), "changes": changes, "guarantee": GUARANTEE,
            "research_only": True}


def close_slots(records: Iterable[Mapping[str, Any]], *, game_pk: int, first_pitch: str | datetime,
                now: str | datetime) -> list[dict]:
    """MISSED records for slots whose window closed with no ON_TIME/LATE receipt."""
    have = {r["slot"] for r in records if r["gamePk"] == int(game_pk) and r["status"] in {"ON_TIME", "LATE"}}
    fp, n = _utc(first_pitch), _utc(now)
    out = []
    for s, p in plan_slots(fp).items():
        if s not in have and n >= min(fp, _utc(p["close_utc"]) if s != "T-5m" else fp):
            out.append({"schema": SCHEMA, "gamePk": int(game_pk), "slot": s, "status": "MISSED",
                        "due_utc": p["due_utc"], "recorded_at_utc": n.isoformat(), "guarantee": GUARANTEE})
    return out


def _canon(r: Mapping[str, Any]) -> bytes:
    return json.dumps(r, sort_keys=True, separators=(",", ":")).encode()


def anchor_digest(records: Iterable[Mapping[str, Any]]) -> str:
    """Chained digest to store OUTSIDE the capture file (e.g. a separate anchor log)."""
    h = "0" * 64
    for r in records:
        h = sha256_bytes(h.encode() + _canon(r))
    return h


def verify(records: Iterable[Mapping[str, Any]], anchored: str) -> bool:
    return anchor_digest(records) == anchored
