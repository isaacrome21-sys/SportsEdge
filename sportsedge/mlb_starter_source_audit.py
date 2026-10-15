"""Research-only MLB probable-starter source audit; never authorizes PLAY."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
import re

KINDS = {"OFFICIAL_LEAGUE", "OFFICIAL_TEAM", "VERIFIED_REPORTER", "X_UNVERIFIED", "OTHER"}
OFFICIAL = {"OFFICIAL_LEAGUE", "OFFICIAL_TEAM"}


def _time(value):
    if not isinstance(value, str):
        raise ValueError("INVALID_TIMESTAMP")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_TIMESTAMP") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return dt.astimezone(timezone.utc)


def _source_url(url, kind):
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        if p.scheme != "https" or not host or p.username or p.password:
            return False
        if kind in OFFICIAL:
            return host == "mlb.com" or host.endswith(".mlb.com")
        if kind == "X_UNVERIFIED":
            return host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
        return True
    except (ValueError, TypeError):
        return False


def audit_starter_sources(rows, *, game_id, team_id, cutoff, first_pitch, max_age_hours=24):
    """Inspect source claims without authenticating timestamps, URLs or receipts."""
    if not isinstance(rows, list) or not isinstance(game_id, str) or not game_id:
        raise ValueError("INVALID_INPUT")
    if type(team_id) is not int or team_id <= 0 or type(max_age_hours) not in (int, float) or not 0 < max_age_hours <= 168:
        raise ValueError("INVALID_INPUT")
    cutoff_dt, pitch_dt = _time(cutoff), _time(first_pitch)
    if cutoff_dt >= pitch_dt:
        raise ValueError("CUTOFF_NOT_PREGAME")
    accepted, rejected = [], []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            rejected.append((index, "INVALID_RECORD"))
            continue
        kind, assertion, pitcher = row.get("source_kind"), row.get("assertion"), row.get("pitcher_id")
        sha = row.get("source_snapshot_sha256")
        if row.get("game_id") != game_id or type(row.get("team_id")) is not int or row["team_id"] != team_id:
            reason = "IDENTITY_MISMATCH"
        elif (kind not in KINDS or assertion not in {"NAMED", "SCRATCHED"}
              or (assertion == "NAMED" and (type(pitcher) is not int or pitcher <= 0))
              or (assertion == "SCRATCHED" and pitcher is not None and (type(pitcher) is not int or pitcher <= 0))
              or not _source_url(row.get("source_url"), kind)
              or not isinstance(sha, str) or not re.fullmatch("[0-9a-fA-F]{64}", sha)):
            reason = "INVALID_SOURCE_CLAIM"
        else:
            try:
                pub, obs = _time(row.get("published_at")), _time(row.get("observed_at"))
                if pub > obs:
                    reason = "OBSERVED_BEFORE_PUBLICATION"
                elif obs > cutoff_dt:
                    reason = "AFTER_CUTOFF"
                elif cutoff_dt - pub > timedelta(hours=max_age_hours):
                    reason = "STALE_SOURCE"
                else:
                    reason = None
            except ValueError:
                reason = "INVALID_SOURCE_TIME"
        if reason:
            rejected.append((index, reason))
        else:
            accepted.append(dict(row))
    names = {r["pitcher_id"] for r in accepted if r["assertion"] == "NAMED"}
    scratch = any(r["assertion"] == "SCRATCHED" for r in accepted)
    official = any(r["source_kind"] in OFFICIAL for r in accepted)
    reporter = any(r["source_kind"] == "VERIFIED_REPORTER" for r in accepted)
    invalid = {"INVALID_RECORD", "IDENTITY_MISMATCH", "INVALID_SOURCE_CLAIM",
               "INVALID_SOURCE_TIME", "OBSERVED_BEFORE_PUBLICATION"}
    if any(reason in invalid for _, reason in rejected):
        status = "INVALID_EVIDENCE"
    elif len(names) > 1 or (names and scratch):
        status = "CONFLICT"
    elif official:
        status = "PROVISIONAL_NAMED" if names else "PROVISIONAL_SCRATCH"
    elif reporter:
        status = "REPORTED_UNCONFIRMED"
    elif accepted:
        status = "RUMOR_OR_OTHER_ONLY"
    elif rejected and all(reason == "AFTER_CUTOFF" for _, reason in rejected):
        status = "AFTER_CUTOFF"
    elif rejected and all(reason == "STALE_SOURCE" for _, reason in rejected):
        status = "STALE"
    else:
        status = "MISSING"
    return {"status": status, "game_id": game_id, "team_id": team_id,
            "cutoff": cutoff_dt.isoformat(), "accepted_sources": accepted,
            "rejected_sources": [{"index": i, "reason": why} for i, why in rejected],
            "candidate_pitcher_id": next(iter(names)) if status == "PROVISIONAL_NAMED" and len(names) == 1 else None,
            "source_authenticity_verified": False, "starter_binding_eligible": False,
            "market_probability_verified": False, "play_authorized": False,
            "research_only": True, "blocker": "EXTERNAL_SOURCE_AUTHENTICITY_UNVERIFIED"}
