"""Forward-only CFB CLV/ROI tracker (research-only, no historical backfill).

A record is accepted only if created within MAX_REGISTRATION_LAG_SECONDS of
the tracker's wall clock, its quote capture is at/after its own creation and
strictly before kickoff. Closing prices may be attached only after kickoff;
settlement only after a close. Summaries never set play_allowed.
"""
from __future__ import annotations

import math
from types import MappingProxyType
from datetime import datetime, timezone
from typing import Any, Mapping

MAX_REGISTRATION_LAG_SECONDS = 300


class TrackerError(ValueError):
    pass


def _ts(v: Any, name: str) -> datetime:
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str) and v.strip():
        try:
            dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise TrackerError(f"{name}_INVALID") from exc
    else:
        raise TrackerError(f"{name}_MISSING")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise TrackerError(f"{name}_NAIVE")
    return dt.astimezone(timezone.utc)


def _odds(v: Any, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or -100 < v < 100:
        raise TrackerError(f"{name}_INVALID")
    return float(v)


def _implied(o: float) -> float:
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def _profit(o: float) -> float:
    return o / 100 if o > 0 else 100 / -o


class ForwardTracker:
    def __init__(self) -> None:
        self._records: dict[str, dict] = {}
        self._audit: list[dict] = []

    @property
    def records(self) -> Mapping[str, Mapping[str, Any]]:
        """Read-only view; mutate only through add/close/settle/correct_settlement."""
        return MappingProxyType({k: MappingProxyType(dict(v)) for k, v in self._records.items()})

    @property
    def audit_history(self) -> tuple:
        """Append-only audit log; returned as an immutable view."""
        return tuple(MappingProxyType(dict(e)) for e in self._audit)

    def _log(self, event: str, rid: str, at: datetime, **extra: Any) -> dict:
        seq = len(self._audit)
        entry = {"seq": seq, "event_id": f"{rid}:{seq}", "event": event, "record_id": rid, "at": at, **extra}
        self._audit.append(entry)
        return entry

    def add(self, rec: Mapping[str, Any], *, now: datetime) -> None:
        now = _ts(now, "NOW")
        rid = rec.get("record_id")
        if not isinstance(rid, str) or not rid:
            raise TrackerError("RECORD_ID_MISSING")
        if rid in self._records:
            raise TrackerError("RECORD_ID_DUPLICATE")
        created, cap, ko = _ts(rec.get("created_at"), "CREATED_AT"), _ts(rec.get("captured_at"), "CAPTURED_AT"), _ts(rec.get("kickoff"), "KICKOFF")
        if created > now:
            raise TrackerError("CREATED_IN_FUTURE")
        if (now - created).total_seconds() > MAX_REGISTRATION_LAG_SECONDS:
            raise TrackerError("HISTORICAL_BACKFILL_REJECTED")
        if cap < created:
            raise TrackerError("CAPTURE_BEFORE_CREATION")
        if cap >= ko:
            raise TrackerError("CAPTURE_AT_OR_AFTER_KICKOFF")
        if now >= ko:
            raise TrackerError("REGISTERED_AFTER_KICKOFF")
        self._records[rid] = {**dict(rec), "odds": _odds(rec.get("odds"), "ODDS"), "_kickoff": ko,
                             "closing_odds": None, "closed_at": None, "result": None,
                             "settled_at": None, "settle_seq": None}
        self._log("ADD", rid, now, odds=self._records[rid]["odds"])

    def close(self, rid: str, *, closing_odds: Any, closing_line: Any, now: datetime) -> None:
        r = self._records.get(rid)
        if r is None:
            raise TrackerError("UNKNOWN_RECORD")
        now = _ts(now, "NOW")
        if now < r["_kickoff"]:
            raise TrackerError("CLOSE_BEFORE_KICKOFF")
        if r["closing_odds"] is not None:
            raise TrackerError("ALREADY_CLOSED")
        if closing_line != r.get("line"):
            raise TrackerError("CLOSING_LINE_MISMATCH")
        r["closing_odds"] = _odds(closing_odds, "CLOSING_ODDS")
        r["closed_at"] = now
        self._log("CLOSE", rid, now, closing_odds=r["closing_odds"])

    def settle(self, rid: str, *, result: str, now: datetime) -> None:
        r = self._records.get(rid)
        if r is None or r["closing_odds"] is None:
            raise TrackerError("SETTLE_REQUIRES_CLOSE")
        if r["result"] is not None:
            raise TrackerError("ALREADY_SETTLED")
        closed_at = r.get("closed_at")
        if not isinstance(closed_at, datetime) or closed_at.tzinfo is None or closed_at < r["_kickoff"]:
            raise TrackerError("CLOSE_TIME_BEFORE_KICKOFF")
        if result not in ("WIN", "LOSS", "PUSH"):
            raise TrackerError("RESULT_INVALID")
        now = _ts(now, "NOW")
        if now < r["_kickoff"]:
            raise TrackerError("SETTLE_BEFORE_KICKOFF")
        entry = self._log("SETTLE", rid, now, result=result)
        r["result"], r["settled_at"], r["settle_seq"] = result, now, entry["seq"]

    def correct_settlement(self, rid: str, *, supersedes_event_id: Any, result: str, reason: Any,
                           actor: Any, now: Any) -> None:
        """Traceable correction: appends a CORRECT_SETTLEMENT entry referencing the
        entry it supersedes; never edits or removes earlier audit entries."""
        r = self._records.get(rid)
        if r is None or r["result"] is None:
            raise TrackerError("CORRECTION_REQUIRES_SETTLEMENT")
        current = self._audit[r["settle_seq"]]
        if not isinstance(supersedes_event_id, str) or supersedes_event_id != current["event_id"]:
            raise TrackerError("CORRECTION_REFERENCE_INVALID")
        if not isinstance(reason, str) or not reason.strip():
            raise TrackerError("CORRECTION_REASON_REQUIRED")
        if not isinstance(actor, str) or not actor.strip():
            raise TrackerError("CORRECTION_ACTOR_REQUIRED")
        now = _ts(now, "NOW")
        if result not in ("WIN", "LOSS", "PUSH"):
            raise TrackerError("RESULT_INVALID")
        if result == r["result"]:
            raise TrackerError("CORRECTION_NO_CHANGE")
        last = self._audit[r["settle_seq"]]["at"]
        if now <= last:
            raise TrackerError("CORRECTION_TIME_NOT_AFTER_SETTLEMENT")
        entry = self._log("CORRECT_SETTLEMENT", rid, now, result=result, previous_result=r["result"],
                          supersedes_event_id=current["event_id"], reason=reason.strip(), actor=actor.strip())
        r["result"], r["settle_seq"] = result, entry["seq"]

    def _replay(self) -> dict[str, dict]:
        """Rebuild ledger state solely from the append-only audit log."""
        st: dict[str, dict] = {}
        for e in self._audit:
            rid = e["record_id"]
            if e["event"] == "ADD":
                st[rid] = {"odds": e["odds"], "closing_odds": None, "result": None}
            elif e["event"] == "CLOSE":
                st[rid]["closing_odds"] = e["closing_odds"]
            elif e["event"] in ("SETTLE", "CORRECT_SETTLEMENT"):
                st[rid]["result"] = e["result"]
        return st

    def summary(self) -> dict:
        state = self._replay()
        consistent = set(state) == set(self._records) and all(
            self._records[k][f] == v[f] for k, v in state.items() for f in ("odds", "closing_odds", "result"))
        settled = [r for r in state.values() if r["result"]]
        closed = [r for r in state.values() if r["closing_odds"] is not None]
        units = sum(_profit(r["odds"]) if r["result"] == "WIN" else (-1.0 if r["result"] == "LOSS" else 0.0) for r in settled)
        clv = [_implied(r["closing_odds"]) - _implied(r["odds"]) for r in closed]
        return {"n_records": len(state), "n_closed": len(closed), "n_settled": len(settled),
                "roi_units": units, "roi_per_bet": units / len(settled) if settled else None,
                "mean_clv_implied_prob": sum(clv) / len(clv) if clv else None,
                "audit_consistent": consistent, "derived_from": "AUDIT_LOG",
                "status_label": "SCREEN/NOT_VALIDATED", "play_allowed": False, "forward_only": True}
