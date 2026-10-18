"""Offline, forward-only parser for official NBA injury-report PDFs (research only).

Input is ``pdftotext -layout`` text plus a separately recorded PDF sha256 and source
receipt time. Effective time comes from the report header only (never the filename).
Team and player identity are mapped fail-closed. Listed AVAILABLE does not mean the
player participated: every record carries participation=UNKNOWN. No scheduler,
network or activation here, and no use for retrospective evaluation backfill.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Mapping
from zoneinfo import ZoneInfo

SCHEMA = "NBA_OFFICIAL_INJURY_REPORT_PARSE_V1"
ET = ZoneInfo("America/New_York")
STATUSES = {"Out": "OUT", "Doubtful": "DOUBTFUL", "Questionable": "QUESTIONABLE",
            "Probable": "PROBABLE", "Available": "AVAILABLE"}
TEAMS = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR", "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}
HEADER = re.compile(r"Injury Report:\s+(\d\d/\d\d/\d\d)\s+(\d\d:\d\d\s+[AP]M)")
STATUS_RE = re.compile(r"\s{2,}(Out|Doubtful|Questionable|Probable|Available)(?=\s{2,}|\s*$)")
WORD_RE = re.compile(r"\b(Out|Doubtful|Questionable|Probable|Available)\b")
NYS = "NOT YET SUBMITTED"
NAME_RE = re.compile(r"^[A-Z][A-Za-z'.\- ]*(?: (?:Jr|Sr|II|III|IV)\.?)?, [A-Z][A-Za-z'.\- ]*$")
DATE_RE = re.compile(r"^\d\d/\d\d/\d{4}$")
TIME_RE = re.compile(r"^\d\d:\d\d \(ET\)$")
MATCH_RE = re.compile(r"^([A-Z]{3})@([A-Z]{3})$")


class InjuryReportError(ValueError):
    pass


def _utc(v) -> datetime:
    t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise InjuryReportError("RECEIPT_TIMEZONE_REQUIRED")
    return t.astimezone(timezone.utc)


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z, ]", "", s.lower())).strip()


def effective_time(text: str) -> datetime:
    stamps = {m.groups() for m in HEADER.finditer(text)}
    if not stamps:
        raise InjuryReportError("HEADER_MISSING")
    if len(stamps) > 1:
        raise InjuryReportError("PAGE_HEADER_MISMATCH")
    d, t = stamps.pop()
    return datetime.strptime(f"{d} {t}", "%m/%d/%y %I:%M %p").replace(tzinfo=ET).astimezone(timezone.utc)


def _map_player(directory, tri, name):
    if directory is None:
        return None, "UNMAPPED"
    hits = directory.get((tri, norm_name(name)))
    if isinstance(hits, (list, tuple, set)):
        hits = list(hits)
        return (hits[0], "MAPPED") if len(hits) == 1 else (None, "UNMAPPED")
    return (hits, "MAPPED") if hits is not None else (None, "UNMAPPED")


def parse_report(text: str, *, pdf_sha256: str, received_at, extractor: str,
                 player_directory: Mapping | None = None) -> dict:
    eff = effective_time(text)
    rec = _utc(received_at)
    if rec < eff:
        raise InjuryReportError("RECEIPT_BEFORE_EFFECTIVE_TIME")
    if not re.fullmatch(r"[0-9a-f]{64}", pdf_sha256 or ""):
        raise InjuryReportError("PDF_SHA256_REQUIRED")
    ctx = {"date": None, "time": None, "matchup": None, "team": None}
    rows, orphans, prev_orphan = [], 0, False
    for line in text.splitlines():
        s = line.strip()
        if not s or HEADER.search(s) or s.startswith("Game Date") or re.fullmatch(r"Page \d+ of \d+", s):
            continue
        m = STATUS_RE.search(line)
        nys = NYS in line
        if not m and not nys:
            if WORD_RE.search(s) and len(re.split(r"\s{2,}", s)) > 1:
                raise InjuryReportError(f"UNPARSEABLE_LINE:{s[:60]}")
            if any(NAME_RE.match(f) or f in TEAMS or MATCH_RE.match(f) for f in re.split(r"\s{2,}", s)):
                raise InjuryReportError(f"STATUS_UNKNOWN_OR_UNPARSEABLE:{s[:60]}")
            orphans += 1  # wrapped reason text: mark the neighbouring rows incomplete
            prev_orphan = True
            if rows and rows[-1].get("player_name"):
                rows[-1]["reason_complete"] = False
            continue
        left = line[: m.start()] if m else line[: line.index(NYS)]
        reason = line[m.end():].strip() if m else ""
        player = None
        for f in [x for x in re.split(r"\s{2,}", left.strip()) if x]:
            if DATE_RE.match(f):
                ctx.update(date=f, matchup=None, team=None)
            elif TIME_RE.match(f):
                ctx.update(time=f, matchup=None, team=None)
            elif MATCH_RE.match(f):
                ctx.update(matchup=f, team=None)
            elif f in TEAMS:
                ctx["team"] = f
            elif "," in f and player is None:
                player = f
            else:
                raise InjuryReportError(f"UNKNOWN_FIELD:{f}")
        if None in ctx.values():
            raise InjuryReportError("ROW_CONTEXT_MISSING")
        tri = TEAMS[ctx["team"]]
        a, h = MATCH_RE.match(ctx["matchup"]).groups()
        if tri not in (a, h):
            raise InjuryReportError("TEAM_NOT_IN_MATCHUP")
        base = {"game_date": ctx["date"], "game_time_et": ctx["time"], "matchup": ctx["matchup"],
                "team": tri, "participation": "UNKNOWN"}
        if nys:
            if player is not None:
                raise InjuryReportError("NOT_YET_SUBMITTED_WITH_PLAYER")
            rows.append({**base, "status": "NOT_YET_SUBMITTED", "player_name": None, "player_id": None,
                         "mapping": "TEAM_LEVEL"})
            prev_orphan = False
            continue
        if player is None:
            raise InjuryReportError("PLAYER_MISSING")
        pid, mapping = _map_player(player_directory, tri, player)
        rows.append({**base, "status": STATUSES[m.group(1)], "player_name": player, "player_id": pid,
                     "mapping": mapping, "availability": STATUSES[m.group(1)] if pid else "UNKNOWN",
                     "reason": reason, "reason_complete": bool(reason) and not prev_orphan})
        prev_orphan = False
    return {"schema": SCHEMA, "effective_at_utc": eff.isoformat(), "effective_source": "REPORT_HEADER",
            "received_at_utc": rec.isoformat(), "pdf_sha256": pdf_sha256, "extractor": extractor,
            "rows": rows, "wrapped_reason_lines": orphans, "research_only": True,
            "forward_only": True, "play_authority": False}
