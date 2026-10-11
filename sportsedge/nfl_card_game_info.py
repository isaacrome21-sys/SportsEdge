"""Game info and line movement for the NFL phone card.

Everything here is display-only. Nothing feeds Attempt 9, the lean gate or any
bet label. Every block is printed only when it was actually retrieved:

- ESPN public scoreboard/summary: kickoff, venue, TV, records, weather and the
  ESPN injury report (Out / Doubtful / Questionable). Not final inactives.
- nflverse games (already loaded by the card): this season's points for/against.
- Line movement: the first card posted on the same issue vs this run's lines.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import re
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
EASTERN = ZoneInfo("America/New_York")
CENTRAL = ZoneInfo("America/Chicago")
ESPN_TEAM_ALIASES = {"WSH": "WAS", "LA": "LAR", "JAC": "JAX"}
SHOWN_STATUSES = ("Out", "Doubtful", "Questionable")
MAX_INJURIES_PER_TEAM = 6
CARD_LINES_MARKER = "nfl-card-lines"
CARD_HEADER = "**NFL card**"

Getter = Callable[[str], dict]


def _espn_team(code: object) -> str:
    text = str(code or "").upper().strip()
    return ESPN_TEAM_ALIASES.get(text, text)


def _default_getter(url: str) -> dict:
    from sportsedge.dfs.sources.common import public_json

    return public_json(url, user_agent="SportsEdge-NFL-card/1.0", timeout=10)


def _competition(event: dict) -> dict:
    comps = event.get("competitions") if isinstance(event.get("competitions"), list) else []
    return comps[0] if comps and isinstance(comps[0], dict) else {}


def _sides(comp: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in comp.get("competitors") or []:
        if isinstance(c, dict) and c.get("homeAway") in ("home", "away"):
            out[c["homeAway"]] = c
    return out


def _record(competitor: dict) -> str | None:
    for rec in competitor.get("records") or []:
        if isinstance(rec, dict) and rec.get("summary") and str(rec.get("type") or "total") in ("total", "overall", ""):
            return str(rec["summary"])
    recs = competitor.get("records") or []
    if recs and isinstance(recs[0], dict) and recs[0].get("summary"):
        return str(recs[0]["summary"])
    return None


def _kickoff_text(iso: str) -> str | None:
    try:
        when = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(EASTERN)
    except ValueError:
        return None
    hour = when.strftime("%I").lstrip("0")
    return f"{when.strftime('%a %b')} {when.day}, {hour}:{when.strftime('%M %p')} ET"


def _weather(comp: dict) -> str | None:
    venue = comp.get("venue") if isinstance(comp.get("venue"), dict) else {}
    if venue.get("indoor") is True:
        return "Indoors"
    w = comp.get("weather") if isinstance(comp.get("weather"), dict) else {}
    if not w:
        return None
    parts = []
    if w.get("displayValue"):
        parts.append(str(w["displayValue"]))
    temp = w.get("temperature", w.get("highTemperature"))
    if temp not in (None, ""):
        parts.append(f"{temp}°F")
    return ", ".join(parts) or None


def _injuries(summary: dict, abbr_by_id: dict[str, str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for group in summary.get("injuries") or []:
        if not isinstance(group, dict):
            continue
        gteam = group.get("team") if isinstance(group.get("team"), dict) else {}
        team = _espn_team(gteam.get("abbreviation") or abbr_by_id.get(str(gteam.get("id") or ""), ""))
        for item in group.get("injuries") or []:
            if not isinstance(item, dict):
                continue
            athlete = item.get("athlete") if isinstance(item.get("athlete"), dict) else {}
            name = str(athlete.get("displayName") or athlete.get("fullName") or "").strip()
            status_obj = item.get("status")
            status = str(status_obj.get("name") or status_obj.get("description") or "") if isinstance(status_obj, dict) else str(status_obj or "")
            status = status.strip().title()
            if not name or status not in SHOWN_STATUSES or not team:
                continue
            pos = athlete.get("position") if isinstance(athlete.get("position"), dict) else {}
            out.setdefault(team, []).append({"name": name, "pos": str(pos.get("abbreviation") or ""), "status": status})
    order = {s: i for i, s in enumerate(SHOWN_STATUSES)}
    for team, rows in out.items():
        rows.sort(key=lambda r: (r["pos"] != "QB", order.get(r["status"], 9), r["name"]))
    return out


def fetch_espn_game_info(games: Iterable[dict], slate: date, getter: Getter | None = None, days: int = 6) -> dict:
    """Map 'AWAY@HOME' -> game info for every card game ESPN lists. Fails soft per call."""
    get = getter or _default_getter
    wanted = {f"{g['away']}@{g['home']}" for g in games}
    events: dict[str, tuple[dict, dict]] = {}
    errors: list[str] = []
    for offset in range(-1, days + 1):
        if wanted <= set(events):
            break
        day = slate + timedelta(days=offset)
        try:
            board = get(f"{ESPN_BASE}/scoreboard?dates={day.strftime('%Y%m%d')}")
        except Exception as exc:  # noqa: BLE001 - display-only source
            errors.append(f"scoreboard {day}: {type(exc).__name__}")
            continue
        for event in board.get("events") or []:
            comp = _competition(event)
            sides = _sides(comp)
            if set(sides) != {"home", "away"}:
                continue
            key = f"{_espn_team(sides['away'].get('team', {}).get('abbreviation'))}@{_espn_team(sides['home'].get('team', {}).get('abbreviation'))}"
            if key in wanted and key not in events:
                events[key] = (event, comp)
    info: dict[str, dict] = {}
    for key, (event, comp) in events.items():
        sides = _sides(comp)
        away, home = key.split("@")
        venue = comp.get("venue") if isinstance(comp.get("venue"), dict) else {}
        tv = []
        for b in comp.get("broadcasts") or []:
            if isinstance(b, dict):
                tv.extend(str(n) for n in b.get("names") or [] if n)
        row: dict[str, Any] = {
            "kickoff": _kickoff_text(str(event.get("date") or comp.get("date") or "")),
            "venue": venue.get("fullName"),
            "tv": ", ".join(dict.fromkeys(tv)) or None,
            "records": {away: _record(sides["away"]), home: _record(sides["home"])},
            "weather": _weather(comp),
        }
        abbr_by_id = {
            str(c.get("team", {}).get("id") or ""): _espn_team(c.get("team", {}).get("abbreviation"))
            for c in sides.values()
        }
        try:
            summary = get(f"{ESPN_BASE}/summary?event={event.get('id')}")
            row["injuries"] = _injuries(summary, abbr_by_id)
        except Exception as exc:  # noqa: BLE001
            row["injuries"] = None
            errors.append(f"summary {key}: {type(exc).__name__}")
        info[key] = row
    return {"source": "ESPN", "games": info, "errors": errors}


def season_stats(history: list, team: str, season: int, asof: date) -> dict | None:
    """This season's record and points per game from nflverse, strictly before `asof`."""
    w = l = t = pf = pa = n = 0
    for g in history:
        if not isinstance(g, dict) or g.get("season") != season or str(g.get("date") or "")[:10] >= asof.isoformat():
            continue
        if g.get("home") == team:
            mine, theirs = g.get("hs"), g.get("as")
        elif g.get("away") == team:
            mine, theirs = g.get("as"), g.get("hs")
        else:
            continue
        if mine is None or theirs is None:
            continue
        n += 1
        pf += mine
        pa += theirs
        w += mine > theirs
        l += mine < theirs
        t += mine == theirs
    if not n:
        return None
    rec = f"{w}-{l}" + (f"-{t}" if t else "")
    return {"games": n, "record": rec, "ppg": round(pf / n, 1), "papg": round(pa / n, 1)}


# ---------------------------------------------------------------- line movement

def lines_snapshot(engine: dict) -> dict:
    """Compact per-game spread/total/ML lines for the hidden marker in the card."""
    out: dict[str, dict] = {}
    for g in engine.get("games") or []:
        key = f"{g.get('away')}@{g.get('home')}"
        for m in g.get("markets") or []:
            market = str(m.get("market") or "")
            if market not in ("spread", "total", "moneyline") or m.get("player"):
                continue
            out.setdefault(key, {})[market] = [m.get("line"), m.get("away_or_over_price"), m.get("home_or_under_price")]
    return out


def snapshot_marker(engine: dict, observed_at: str | None) -> str:
    payload = {"observed_at": observed_at, "lines": lines_snapshot(engine)}
    return f"<!-- {CARD_LINES_MARKER} {json.dumps(payload, separators=(',', ':'))} -->"


_LABEL_RES = {
    "spread": re.compile(r"^- (?:\*\*\w+\*\* )?Spread (\S+) ([+-]?\d+(?:\.\d+)?) ([+-]\d+) / (\S+) [+-]?\d+(?:\.\d+)? ([+-]\d+)"),
    "total": re.compile(r"^- (?:\*\*\w+\*\* )?Total (\d+(?:\.\d+)?) o([+-]\d+) / u([+-]\d+)"),
    "moneyline": re.compile(r"^- (?:\*\*\w+\*\* )?ML (\S+) ([+-]\d+) / (\S+) ([+-]\d+)"),
}


def _lines_from_card_text(body: str) -> dict:
    """Fallback for cards posted before the hidden marker existed."""
    out: dict[str, dict] = {}
    key = None
    for line in body.splitlines():
        head = re.match(r"^### (\S+) @ (\S+)\s*$", line)
        if head:
            key = f"{head.group(1)}@{head.group(2)}"
            continue
        if not key:
            continue
        for market, rx in _LABEL_RES.items():
            m = rx.match(line)
            if not m:
                continue
            if market == "spread":
                vals = [float(m.group(2)), int(m.group(3)), int(m.group(5))]
            elif market == "total":
                vals = [float(m.group(1)), int(m.group(2)), int(m.group(3))]
            else:
                vals = [None, int(m.group(2)), int(m.group(4))]
            out.setdefault(key, {}).setdefault(market, vals)
    return out


def first_card_lines(comments: list[dict]) -> dict | None:
    """Earliest card on the issue: {'observed_at', 'lines'} or None."""
    cards = [c for c in comments if str(c.get("body") or "").startswith(CARD_HEADER)]
    cards.sort(key=lambda c: str(c.get("created_at") or ""))
    for c in cards:
        body = str(c["body"])
        m = re.search(rf"<!-- {CARD_LINES_MARKER} (\{{.*?\}}) -->", body)
        if m:
            try:
                payload = json.loads(m.group(1))
                if payload.get("lines"):
                    return {"observed_at": payload.get("observed_at") or c.get("created_at"), "lines": payload["lines"]}
            except ValueError:
                pass
        lines = _lines_from_card_text(body)
        if lines:
            return {"observed_at": c.get("created_at"), "lines": lines}
    return None


def _fmt_price(p: object) -> str:
    try:
        v = int(p)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"
    return f"+{v}" if v > 0 else str(v)


def _fmt_line(x: object, signed: bool) -> str:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"
    return f"{v:+g}" if signed else f"{v:g}"


def movement_lines(first: dict | None, engine: dict, away: str, home: str) -> list[str]:
    """One bullet per market that moved since the first card on this issue."""
    if not first:
        return []
    key = f"{away}@{home}"
    old = (first.get("lines") or {}).get(key) or {}
    now = lines_snapshot(engine).get(key) or {}
    moves: list[str] = []
    for market in ("spread", "total", "moneyline"):
        if market not in old or market not in now:
            continue
        o, n = old[market], now[market]
        if (market == "moneyline" or _same(o[0], n[0])) and _same(o[1], n[1]) and _same(o[2], n[2]):
            continue
        if market == "spread":
            if _same(o[0], n[0]):
                moves.append(f"Spread {away} {_fmt_line(n[0], True)} price {_fmt_price(o[1])} → {_fmt_price(n[1])}")
            else:
                moves.append(
                    f"Spread {away} {_fmt_line(o[0], True)} ({_fmt_price(o[1])}) → {_fmt_line(n[0], True)} ({_fmt_price(n[1])})"
                )
        elif market == "total":
            if _same(o[0], n[0]):
                moves.append(f"Total {_fmt_line(n[0], False)} o{_fmt_price(o[1])}/u{_fmt_price(o[2])} → o{_fmt_price(n[1])}/u{_fmt_price(n[2])}")
            else:
                moves.append(
                    f"Total {_fmt_line(o[0], False)} o{_fmt_price(o[1])}/u{_fmt_price(o[2])} → "
                    f"{_fmt_line(n[0], False)} o{_fmt_price(n[1])}/u{_fmt_price(n[2])}"
                )
        else:
            moves.append(f"ML {away} {_fmt_price(o[1])} → {_fmt_price(n[1])}; {home} {_fmt_price(o[2])} → {_fmt_price(n[2])}")
    since = _since_text(first.get("observed_at"))
    if not moves:
        compared = [m for m in ("spread", "total", "moneyline") if m in old and m in now]
        return [f"- Line move since first card ({since}): no change"] if compared else []
    return [f"- Line move since first card ({since}): " + "; ".join(moves)]


def _same(a: object, b: object) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return a == b


def _since_text(iso: object) -> str:
    try:
        when = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(CENTRAL)
    except ValueError:
        return "earlier"
    hour = when.strftime("%I").lstrip("0")
    return f"{when.strftime('%b')} {when.day} {hour}:{when.strftime('%M %p')} CT"


def fetch_issue_comments(repo: str, issue: str) -> list[dict]:
    import subprocess

    proc = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{repo}/issues/{issue}/comments?per_page=100"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    text = proc.stdout.strip().replace("][", ",")
    rows = json.loads(text or "[]")
    return [{"body": r.get("body"), "created_at": r.get("created_at")} for r in rows if isinstance(r, dict)]


def game_info_lines(game: dict) -> list[str]:
    """Card bullets for the ESPN block and nflverse season table."""
    away, home = str(game.get("away")), str(game.get("home"))
    ctx = game.get("context") or {}
    info = ctx.get("game_info")
    out: list[str] = []
    if info:
        head = " · ".join(x for x in (info.get("kickoff"), info.get("venue"), info.get("tv")) if x)
        if head:
            out.append(f"- {head}")
        recs = info.get("records") or {}
        if recs.get(away) or recs.get(home):
            out.append(f"- Records: {away} {recs.get(away) or '?'} · {home} {recs.get(home) or '?'}")
        if info.get("weather"):
            out.append(f"- Weather (ESPN forecast): {info['weather']}")
        inj = info.get("injuries")
        if inj is None:
            out.append("- Injuries: ESPN injury report not retrieved this run")
        else:
            for team in (away, home):
                rows = inj.get(team) or []
                if not rows:
                    out.append(f"- {team} injury report: no Out/Doubtful/Questionable listed")
                    continue
                shown = rows[:MAX_INJURIES_PER_TEAM]
                text = "; ".join(f"{r['name']}{' ' + r['pos'] if r['pos'] else ''} **{r['status'].upper()}**" for r in shown)
                more = f" (+{len(rows) - len(shown)} more)" if len(rows) > len(shown) else ""
                out.append(f"- {team} injury report: {text}{more}")
    stats = ctx.get("season_stats") or {}
    if stats.get(away) and stats.get(home):
        a, h = stats[away], stats[home]
        out += [
            "",
            f"| This season (nflverse) | {away} | {home} |",
            "|---|---|---|",
            f"| Record | {a['record']} | {h['record']} |",
            f"| Points/game | {a['ppg']:g} | {h['ppg']:g} |",
            f"| Allowed/game | {a['papg']:g} | {h['papg']:g} |",
            "",
        ]
    return out


HISTORY_TEAM_ALIASES = {"LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV", "WSH": "WAS"}


def load_history(path: str) -> list:
    """nflverse games cache written by scripts/fetch_nflverse_games.py, with intake team codes."""
    try:
        raw = json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return []
    rows = raw.get("games") if isinstance(raw, dict) else raw
    out = []
    for g in rows or []:
        if isinstance(g, dict):
            out.append({**g, "home": HISTORY_TEAM_ALIASES.get(str(g.get("home")), g.get("home")),
                        "away": HISTORY_TEAM_ALIASES.get(str(g.get("away")), g.get("away"))})
    return out


def attach_game_info(games: list, history: list, asof: date, *, fetch_espn: bool, getter: Getter | None = None) -> None:
    """Display-only game info (ESPN) and this season's nflverse stats. Never touches picks or leans."""
    season = asof.year if asof.month >= 3 else asof.year - 1
    for game in games:
        ctx = game.setdefault("context", {})
        stats = {t: season_stats(history, t, season, asof) for t in (str(game["away"]), str(game["home"]))}
        if all(stats.values()):
            ctx["season_stats"] = stats
    if not (fetch_espn or getter) or not games:
        return
    try:
        espn = fetch_espn_game_info(games, asof, getter=getter)
    except Exception as exc:  # noqa: BLE001 - display-only; the card must still post
        espn = {"games": {}, "errors": [type(exc).__name__]}
    for game in games:
        info = espn["games"].get(f"{game['away']}@{game['home']}")
        if info:
            game["context"]["game_info"] = info
            game["context"].setdefault("sources", []).append("ESPN")
