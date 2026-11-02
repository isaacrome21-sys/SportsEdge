"""Authoritative, timestamped starting-QB check for the legacy NFL phone card.

LEGACY-ROUTE SAFEGUARD. Used only by ``scripts/run_nfl_lines_card.py`` (the
superseded phone path). The canonical RUN IT path (``artifacts/run_it_full.py``)
is untouched. Nothing here changes a projection, a price or a score; it only
decides whether side/total/ML leans may be SHOWN for a game.

Owner rule (relay #2447, Nov 1 2026): block leans when the model's QB differs
from the confirmed starter OR the starter cannot be verified. Never invent a
scoring adjustment.

Starter source (team-bound, timestamped; a PROVISIONAL availability screen,
not proof of the game-day starter -- final inactives are not consumed, and
"CONFIRMED" below means only "passed this screen"; review 5731213002):
  1. ESPN public team depth chart, QB1 (``/teams/{id}/depthcharts``), and
  2. ESPN injury report for the event (``/summary?event=``): a QB1 listed
     Out / Doubtful / Questionable is NOT a confirmed starter.
  or an operator-supplied ``--starters`` JSON with the same shape.

Fail closed: fetch error, unknown shape, an event summary with no valid
``injuries`` section or no group for the team (not a clean report; review
5731270304), more than one distinct QB1 across formations, a single-token (surname-only) name, a missing team, a missing or
stale ``retrieved_at`` -> that team is UNVERIFIED.

DK props are NOT a starter source. They are reported as "prop corroboration"
only, and can only ADD a hold: a prop for a QB who is neither screened
starter, a prop whose team disagrees with the screened starter's team, or a
prop for a passer who is not the model's QB (CHANGE: the board itself shows
the model was built on a different offense, e.g. #3015 McKee vs Hurts);
they can never clear one.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable

from sportsedge.dfs.sources.common import normalize_name

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
SOURCE_ESPN = "ESPN_DEPTH_CHART_QB1+ESPN_INJURY_REPORT"
MAX_STARTER_AGE = timedelta(hours=12)
MAX_CLOCK_SKEW = timedelta(minutes=5)
NOT_CONFIRMED_STATUSES = frozenset({"Out", "Doubtful", "Questionable"})
ESPN_TEAM_ALIASES = {"WSH": "WAS", "LA": "LAR", "JAC": "JAX"}

CONFIRMED = "CONFIRMED"
UNVERIFIED_CODES = (
    "STARTER_SOURCE_UNAVAILABLE",
    "STARTER_TEAM_MISSING",
    "STARTER_NAME_AMBIGUOUS",
    "STARTER_TIMESTAMP_MISSING",
    "STARTER_STALE",
    "STARTER_INJURY_LISTED",
    "MODEL_QB_MISSING",
    "PROP_QB_NOT_A_CONFIRMED_STARTER",
    "PROP_TEAM_CONFLICT",
)

Getter = Callable[[str], dict]


def canonical_qb(name: object) -> str | None:
    """Full canonical name (accents, punctuation, Jr/Sr/II/III/IV/V removed).
    A single-token name (e.g. surname only) is ambiguous -> None."""
    text = str(name or "").replace(".", " ").replace(",", " ")
    tokens = [t for t in text.split() if normalize_name(t)]
    if len(tokens) < 2:
        return None
    key = normalize_name(text)
    return key or None


def _parse_ts(value: object) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else None


def _team(code: object) -> str:
    text = str(code or "").upper().strip()
    return ESPN_TEAM_ALIASES.get(text, text)


# ------------------------------------------------------------------ ESPN fetch
def _default_getter(url: str) -> dict:
    from sportsedge.dfs.sources.common import public_json

    return public_json(url, user_agent="SportsEdge-NFL-card/1.0", timeout=10)


def _qb1(depth: dict) -> list[dict]:
    """Distinct QB1 athletes across every formation in an ESPN depth chart."""
    seen: dict[str, dict] = {}
    for formation in depth.get("depthchart") or depth.get("items") or []:
        if not isinstance(formation, dict):
            continue
        positions = formation.get("positions") or {}
        qb = positions.get("qb") or positions.get("QB") if isinstance(positions, dict) else None
        athletes = (qb or {}).get("athletes") if isinstance(qb, dict) else None
        if not athletes or not isinstance(athletes[0], dict):
            continue
        a = athletes[0]
        name = str(a.get("displayName") or a.get("fullName") or "").strip()
        key = str(a.get("id") or canonical_qb(name) or "")
        if key and name:
            seen.setdefault(key, {"name": name, "athlete_id": str(a.get("id") or "") or None})
    return list(seen.values())


class InjuryReportInvalid(Exception):
    """ESPN injury report absent or not in the expected shape."""


def parse_injury_report(summary: object) -> dict[str, dict[str, str]]:
    """Validate an ESPN event-summary injury report (review 5731270304).

    Returns {"id:<espn team id>"|"abbr:<TEAM>": {athlete_id: status}}. Raises
    InjuryReportInvalid when the report is absent or its shape is not understood, so
    the caller marks the team UNVERIFIED (HOLD) instead of treating a missing
    section as a clean report."""
    if not isinstance(summary, dict) or "injuries" not in summary:
        raise InjuryReportInvalid("INJURY_REPORT_ABSENT")
    groups = summary["injuries"]
    if not isinstance(groups, list):
        raise InjuryReportInvalid("INJURY_REPORT_SCHEMA")
    out: dict[str, dict[str, str]] = {}
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("team"), dict) \
                or not isinstance(group.get("injuries"), list):
            raise InjuryReportInvalid("INJURY_REPORT_SCHEMA")
        team = group["team"]
        keys = [f"id:{team['id']}"] if team.get("id") else []
        if team.get("abbreviation"):
            keys.append(f"abbr:{_team(team['abbreviation'])}")
        if not keys:
            raise InjuryReportInvalid("INJURY_REPORT_TEAM_MISSING")
        rows: dict[str, str] = {}
        for item in group["injuries"]:
            ath = item.get("athlete") if isinstance(item, dict) else None
            if not isinstance(ath, dict) or not ath.get("id"):
                raise InjuryReportInvalid("INJURY_REPORT_ATHLETE_MISSING")
            st = item.get("status")
            st = (st.get("name") or st.get("description")) if isinstance(st, dict) else st
            if not isinstance(st, str) or not st.strip():
                raise InjuryReportInvalid("INJURY_REPORT_STATUS_MISSING")
            rows[str(ath["id"])] = st.strip().title()
        for k in keys:
            if k in out:
                raise InjuryReportInvalid("INJURY_REPORT_DUPLICATE_TEAM")
            out[k] = rows
    return out


def fetch_espn_starters(games: Iterable[dict], slate: date, *, getter: Getter | None = None,
                        now: datetime | None = None, days: int = 6) -> dict:
    """Return a starters document {"source","retrieved_at","teams":{TEAM:{...}},"errors"}.
    Every per-team failure is recorded and leaves that team out (fail closed)."""
    get = getter or _default_getter
    retrieved_at = (now or datetime.now(timezone.utc)).isoformat()
    wanted = {f"{_team(g['away'])}@{_team(g['home'])}" for g in games}
    events: dict[str, dict] = {}
    errors: list[str] = []
    for offset in range(-1, days + 1):
        if wanted <= set(events):
            break
        day = slate + timedelta(days=offset)
        try:
            board = get(f"{ESPN_BASE}/scoreboard?dates={day.strftime('%Y%m%d')}")
        except Exception as exc:  # noqa: BLE001 - fail closed per team
            errors.append(f"scoreboard {day}: {type(exc).__name__}")
            continue
        for event in board.get("events") or []:
            comp = (event.get("competitions") or [{}])[0]
            sides = {c.get("homeAway"): c for c in comp.get("competitors") or [] if isinstance(c, dict)}
            if set(sides) >= {"home", "away"}:
                key = f"{_team(sides['away']['team'].get('abbreviation'))}@{_team(sides['home']['team'].get('abbreviation'))}"
                if key in wanted and key not in events:
                    events[key] = {"event": event, "sides": sides}
    teams: dict[str, dict] = {}
    for key, found in events.items():
        report: dict[str, dict[str, str]] | None
        try:
            report = parse_injury_report(get(f"{ESPN_BASE}/summary?event={found['event'].get('id')}"))
        except Exception as exc:  # noqa: BLE001 - absent/unparseable report -> HOLD
            errors.append(f"injuries {key}: {type(exc).__name__}: {exc}")
            report = None
        for side in ("away", "home"):
            team_obj = found["sides"][side]["team"]
            code = _team(team_obj.get("abbreviation"))
            try:
                qb1 = _qb1(get(f"{ESPN_BASE}/teams/{team_obj.get('id')}/depthcharts"))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"depthchart {code}: {type(exc).__name__}")
                continue
            if not qb1:
                errors.append(f"depthchart {code}: NO_QB1")
                continue
            # The report must carry an explicit group for THIS team (matched by
            # ESPN team id or abbreviation); a missing group is not "no injuries".
            team_rows = None
            if report is not None:
                team_rows = report.get(f"id:{team_obj.get('id')}")
                if team_rows is None:
                    team_rows = report.get(f"abbr:{code}")
                if team_rows is None:
                    errors.append(f"injuries {code}: TEAM_NOT_IN_REPORT")
            entry = {"names": [q["name"] for q in qb1],
                     "athlete_id": qb1[0]["athlete_id"] if len(qb1) == 1 else None,
                     "injury_status": None if team_rows is None else team_rows.get(str(qb1[0]["athlete_id"]), ""),
                     "injury_report_checked": team_rows is not None}
            teams[code] = entry
    return {"source": SOURCE_ESPN, "retrieved_at": retrieved_at, "teams": teams, "errors": errors}


# ------------------------------------------------------------------ decision
def resolve_starter(doc: dict | None, team: str, pricing_as_of: object) -> dict:
    """Team-bound starter verdict: {"status": CONFIRMED|code, "name", "canonical", ...}."""
    if not isinstance(doc, dict):
        return {"status": "STARTER_SOURCE_UNAVAILABLE"}
    retrieved = _parse_ts(doc.get("retrieved_at"))
    clock = _parse_ts(pricing_as_of)
    base = {"source": doc.get("source"), "retrieved_at": doc.get("retrieved_at")}
    if retrieved is None:
        return {**base, "status": "STARTER_TIMESTAMP_MISSING"}
    if clock is None or retrieved > clock + MAX_CLOCK_SKEW or clock - retrieved > MAX_STARTER_AGE:
        return {**base, "status": "STARTER_STALE"}
    entry = (doc.get("teams") or {}).get(team)
    if not isinstance(entry, dict):
        return {**base, "status": "STARTER_TEAM_MISSING"}
    names = entry.get("names") if isinstance(entry.get("names"), list) else [entry.get("name")]
    canon = {canonical_qb(n) for n in names}
    if len(names) != 1 or None in canon:
        return {**base, "status": "STARTER_NAME_AMBIGUOUS", "names": names}
    name = names[0]
    out = {**base, "name": name, "canonical": canonical_qb(name), "athlete_id": entry.get("athlete_id")}
    if entry.get("injury_report_checked") is not True:
        return {**out, "status": "STARTER_SOURCE_UNAVAILABLE"}
    if str(entry.get("injury_status") or "").title() in NOT_CONFIRMED_STATUSES:
        return {**out, "status": "STARTER_INJURY_LISTED", "injury_status": entry.get("injury_status")}
    return {**out, "status": CONFIRMED}


def qb_check(*, away: str, home: str, model_qbs: dict, starters_doc: dict | None,
             pricing_as_of: object, prop_qbs: list[dict]) -> dict:
    """Full per-game verdict.

    model_qbs: {TEAM: {"qb": name}} from the model's own history (nflverse
    last listed starter). prop_qbs: [{"player", "team"|None}] DK QB props.
    Returns {"block": None|"CHANGE"|"UNVERIFIED", "teams": {...},
    "prop_corroboration": {...}}."""
    teams: dict[str, dict] = {}
    for team in (away, home):
        starter = resolve_starter(starters_doc, team, pricing_as_of)
        model = canonical_qb((model_qbs.get(team) or {}).get("qb"))
        row = {"starter": starter, "model_qb": (model_qbs.get(team) or {}).get("qb")}
        if starter["status"] != CONFIRMED:
            row["verdict"] = starter["status"]
        elif model is None:
            row["verdict"] = "MODEL_QB_MISSING"
        elif model != starter["canonical"]:
            row["verdict"] = "QB_CHANGE"
        else:
            row["verdict"] = "MATCH"
        teams[team] = row

    confirmed = {t: r["starter"]["canonical"] for t, r in teams.items() if r["starter"]["status"] == CONFIRMED}
    corroboration: dict[str, object] = {"teams": {}, "conflicts": []}
    for team, canon in confirmed.items():
        corroboration["teams"][team] = any(canonical_qb(p.get("player")) == canon for p in prop_qbs)
    for p in prop_qbs:
        canon = canonical_qb(p.get("player"))
        owner = [t for t, c in confirmed.items() if c == canon]
        if len(confirmed) == 2 and not owner:
            corroboration["conflicts"].append({"player": p.get("player"), "code": "PROP_QB_NOT_A_CONFIRMED_STARTER"})
        elif owner and p.get("team") and _team(p["team"]) != owner[0]:
            corroboration["conflicts"].append({"player": p.get("player"), "code": "PROP_TEAM_CONFLICT"})

    # Board evidence (owner correction, #3015): a posted DK QB prop for a
    # passer who is neither team's model QB means the model was built on a
    # different offense. Props never CONFIRM a starter, but they can show a
    # change -> CHANGE hold.
    model_canon = {canonical_qb((model_qbs.get(t) or {}).get("qb")) for t in (away, home)} - {None}
    if model_canon:
        for p in prop_qbs:
            canon = canonical_qb(p.get("player"))
            if canon and canon not in model_canon:
                corroboration["conflicts"].append({"player": p.get("player"), "code": "PROP_QB_DIFFERS_FROM_MODEL_QB"})

    verdicts = [r["verdict"] for r in teams.values()]
    if "QB_CHANGE" in verdicts or any(
            c["code"] == "PROP_QB_DIFFERS_FROM_MODEL_QB" for c in corroboration["conflicts"]):
        block = "CHANGE"
    elif any(v != "MATCH" for v in verdicts) or corroboration["conflicts"]:
        block = "UNVERIFIED"
    else:
        block = None
    return {"block": block, "teams": teams, "prop_corroboration": corroboration}
