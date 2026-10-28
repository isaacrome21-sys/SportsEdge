"""CBB Nov-1 board census contract, strictly research-only (no quote admission)."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Mapping

SCHEMA = "SPORTSEDGE_CBB_CAPTURE_SCOPE_V1"
DEFAULT_SECTIONS = (
    "MONEYLINE", "SPREAD", "TOTAL", "TEAM_TOTAL_AWAY", "TEAM_TOTAL_HOME",
    "FIRST_HALF_SPREAD", "FIRST_HALF_TOTAL",
)
OPTIONAL_PROPS = frozenset((
    "PLAYER_POINTS", "PLAYER_REBOUNDS", "PLAYER_ASSISTS", "PLAYER_THREES",
    "PLAYER_PRA", "PLAYER_POINTS_REBOUNDS", "PLAYER_POINTS_ASSISTS",
    "PLAYER_REBOUNDS_ASSISTS",
))
SECTION_STATES = frozenset(("CAPTURED", "NOT_OFFERED", "MISSING"))
US_STATES = frozenset("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_POSITIVE_ID = re.compile(r"[1-9][0-9]*\Z")
_STATE = re.compile(r"[A-Z]{2}\Z")
_F = chr(96) * 3
_FENCE = re.compile(r"^" + re.escape(_F + "json") + r"\s*\n(.*?)\n" +
                    re.escape(_F) + r"\s*\Z", re.DOTALL)


class CbbCaptureScopeError(ValueError):
    pass


def _fail(reason: str) -> None:
    raise CbbCaptureScopeError("CBB_SCOPE_" + reason)


def _required_string(obj: Mapping, field: str) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _fail("FIELD_INVALID:" + field)
    return value


def _stamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or "T" not in value.upper():
        _fail("TIME_INVALID:" + field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail("TIME_INVALID:" + field)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("TIMEZONE_REQUIRED:" + field)
    return parsed.astimezone(timezone.utc)


def _id(obj: Mapping, field: str) -> str:
    value = _required_string(obj, field)
    if not _POSITIVE_ID.fullmatch(value):
        _fail("ID_INVALID:" + field)
    return value


def _digest(obj: Mapping, field: str) -> str:
    value = _required_string(obj, field)
    if not _SHA.fullmatch(value):
        _fail("SHA256_INVALID:" + field)
    return value


def _mapping(value: object, field: str) -> Mapping:
    if not isinstance(value, dict):
        _fail("OBJECT_REQUIRED:" + field)
    return value


def _team(raw: object, role: str) -> str:
    obj = _mapping(raw, role)
    if obj.get("role") != role or obj.get("is_college") is not True:
        _fail("COLLEGE_TEAM_IDENTITY_REQUIRED:" + role)
    espn_id = _id(obj, "espn_team_id")
    _required_string(obj, "dk_name")
    state = _required_string(obj, "institution_state")
    if not _STATE.fullmatch(state) or state not in US_STATES:
        _fail("INSTITUTION_STATE_INVALID:" + role)
    if state == "IL":
        _fail("ILLINOIS_COLLEGE_EXCLUDED:" + role)
    if type(obj.get("crosswalk_season")) is not int or obj["crosswalk_season"] != 2027:
        _fail("2027_CROSSWALK_REQUIRED:" + role)
    _digest(obj, "crosswalk_sha256")
    if obj.get("crosswalk_status") != "INDEPENDENTLY_VERIFIED":
        _fail("CROSSWALK_UNVERIFIED:" + role)
    return espn_id


def validate_cbb_capture_scope(data: object, *, received_at_utc: str) -> dict:
    """Validate a no-authority market-scope report. Never produce priced rows."""
    obj = _mapping(data, "manifest")
    if obj.get("schema") != SCHEMA or obj.get("sport") != "CBB":
        _fail("SCHEMA_OR_SPORT_INVALID")
    if type(obj.get("season")) is not int or obj["season"] != 2027:
        _fail("2027_SEASON_REQUIRED")
    if obj.get("league") != "NCAA_MEN_D1":
        _fail("LEAGUE_INVALID")
    if obj.get("source") != "DRAFTKINGS_RENDERED":
        _fail("RENDERED_SOURCE_REQUIRED")
    _id(obj, "espn_event_id")
    _id(obj, "dk_event_id")
    _digest(obj, "raw_sha256")
    _required_string(obj, "raw_locator")
    tip = _stamp(obj.get("scheduled_tip_utc"), "scheduled_tip_utc")
    captured = _stamp(obj.get("captured_at_utc"), "captured_at_utc")
    received = _stamp(received_at_utc, "received_at_utc")
    if not captured < tip:
        _fail("POST_TIP_CAPTURE")
    if captured > received:
        _fail("CAPTURE_AFTER_RECEIPT")
    away = _team(obj.get("away"), "AWAY")
    home = _team(obj.get("home"), "HOME")
    if away == home:
        _fail("DUPLICATE_TEAM_ID")
    sections = _mapping(obj.get("sections"), "sections")
    if set(sections) != set(DEFAULT_SECTIONS):
        _fail("DEFAULT_SECTION_SET_MISMATCH")
    missing = []
    for key in DEFAULT_SECTIONS:
        item = _mapping(sections[key], key)
        state = item.get("status")
        if state not in SECTION_STATES:
            _fail("SECTION_STATUS_INVALID:" + key)
        _required_string(item, "evidence_locator")
        if state == "MISSING":
            missing.append(key)
    props = _mapping(obj.get("props"), "props")
    if props.get("menu_examined") is not True:
        _fail("PROP_MENU_NOT_EXAMINED")
    _required_string(props, "menu_evidence_locator")
    offered = props.get("offered")
    captured_props = props.get("captured")
    if not isinstance(offered, list) or not isinstance(captured_props, list):
        _fail("PROP_LISTS_REQUIRED")
    if (any(not isinstance(x, str) for x in offered + captured_props)
            or len(offered) != len(set(offered))
            or len(captured_props) != len(set(captured_props))
            or not set(offered).issubset(OPTIONAL_PROPS)
            or not set(captured_props).issubset(set(offered))):
        _fail("PROP_SET_INVALID")
    missing += sorted(set(offered) - set(captured_props))
    return {
        "schema": SCHEMA, "sport": "CBB", "espn_event_id": obj["espn_event_id"],
        "dk_event_id": obj["dk_event_id"],
        "scope_state": "INCOMPLETE_RESEARCH_ONLY" if missing else "SCOPE_RECORDED_RESEARCH_ONLY",
        "missing_sections": missing, "source_claim_sha256": obj["raw_sha256"],
        "source_claim_locator": obj["raw_locator"],
        "delivery_verified": False, "quote_authenticated": False,
        "counted": False, "official": False, "staking_authority": False,
    }


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            _fail("DUPLICATE_JSON_KEY:" + key)
        out[key] = value
    return out


def parse_cbb_scope_issue(body: str, *, received_at_utc: str) -> dict:
    """Exact grammar: one CBB_CAPTURE_V1 header and one JSON code fence."""
    if not isinstance(body, str) or body.count("### CBB_CAPTURE_V1") != 1:
        _fail("ISSUE_HEADER_INVALID")
    tail = body.split("### CBB_CAPTURE_V1", 1)[1].strip()
    match = _FENCE.fullmatch(tail)
    if not match:
        _fail("ISSUE_FENCE_INVALID")
    try:
        manifest = json.loads(
            match.group(1), object_pairs_hook=_no_duplicate_keys,
            parse_constant=lambda _: _fail("JSON_NONFINITE"),
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise CbbCaptureScopeError("CBB_SCOPE_JSON_INVALID") from exc
    return validate_cbb_capture_scope(manifest, received_at_utc=received_at_utc)
