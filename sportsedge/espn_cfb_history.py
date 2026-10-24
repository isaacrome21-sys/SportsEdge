"""ESPN college-football history acquisition (staging data only).

Free public ESPN endpoints, no keys. Built for the #2368 CFB QB family
reproduction (Isaac, Oct 17 2026: "Finish CFB"), on the same contract as
sportsedge/statsapi_history.py:

* Every payload is labeled ACQUIRED_POSTHOC_FROM_PUBLIC_ESPN with its real
  retrieval time. It is NOT a pregame snapshot and NOT a recovered
  original under #2344. Nothing here may be presented as either.
* Payload bytes are stored verbatim (gzip JSONL) with URL + SHA-256.
* A season is COMPLETE only if every requested URL succeeded and every
  completed scoreboard event has a summary payload.
* Raw data is not filtered by team. The Illinois exclusion is applied by
  every consumer at modeling time, as the original lane did.
"""
from __future__ import annotations

import json
from typing import Iterable, Mapping, Sequence

from sportsedge.statsapi_history import (  # noqa: F401 (re-exported transport)
    RateLimitedFetcher, acquire, read_bundle, sha256_bytes, write_bundle,
)

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
WEB = "https://site.web.api.espn.com/apis/common/v3/sports/football/college-football"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
SCHEMA = "SPORTSEDGE_ESPN_CFB_HISTORY_BUNDLE_V1"
PROVENANCE_LABEL = "ACQUIRED_POSTHOC_FROM_PUBLIC_ESPN"
NOT_A = ("PREGAME_SNAPSHOT", "ISSUE_2344_RECOVERED_ORIGINAL")
REG_WEEKS = range(1, 17)


def scoreboard_url(season: int, seasontype: int, week: int) -> str:
    return (f"{SITE}/scoreboard?groups=80&limit=300&dates={season}"
            f"&seasontype={seasontype}&week={week}")


def scoreboard_urls(season: int) -> list[str]:
    return ([scoreboard_url(season, 2, w) for w in REG_WEEKS]
            + [scoreboard_url(season, 3, 1)])


def summary_url(event_id: str) -> str:
    return f"{SITE}/summary?event={event_id}"


def fbs_teams_url(season: int) -> str:
    return f"{CORE}/seasons/{season}/types/2/groups/80/teams?limit=300"


def gamelog_url(athlete_id: int, season: int) -> str:
    return f"{WEB}/athletes/{athlete_id}/gamelog?season={season}"


def completed_events(scoreboards: Iterable[Mapping]) -> set[str]:
    out = set()
    for sb in scoreboards:
        for ev in sb.get("events") or []:
            st = ((ev.get("status") or {}).get("type") or {})
            if st.get("completed") is True:
                out.add(str(ev["id"]))
    return out


def fbs_team_ids(core_body: Mapping) -> list[str]:
    ids = []
    for item in core_body.get("items") or []:
        ref = str(item.get("$ref") or "")
        seg = ref.split("/teams/")[1].split("?")[0] if "/teams/" in ref else ""
        if seg.isdigit():
            ids.append(seg)
    return sorted(set(ids), key=int)


def passer_ids(summary_bodies: Iterable[Mapping]) -> list[int]:
    out = set()
    for d in summary_bodies:
        for tp in (d.get("boxscore") or {}).get("players") or []:
            for cat in tp.get("statistics") or []:
                if cat.get("name") != "passing":
                    continue
                for a in cat.get("athletes") or []:
                    aid = int(((a.get("athlete") or {}).get("id")) or 0)
                    if aid > 0:
                        out.add(aid)
    return sorted(out)


def completeness(events: set[str], summary_events: set[str],
                 failures: Sequence[Mapping], fbs_count: int | None) -> dict:
    missing = sorted(events - summary_events)
    ok = not failures and not missing and (fbs_count is None or fbs_count > 0)
    return {"status": "COMPLETE" if ok else "INCOMPLETE",
            "completed_events": len(events),
            "summaries": len(summary_events & events),
            "events_missing_summary": missing[:200],
            "fbs_team_count": fbs_count,
            "fetch_failures": len(failures),
            "rule": ("COMPLETE iff zero fetch failures, every completed "
                     "scoreboard event has a summary, and the FBS list is non-empty")}


def manifest(season: int, bundles: Mapping[str, str], counts: Mapping[str, int],
             comp: Mapping, failures: Sequence[Mapping], run: Mapping[str, str]) -> dict:
    return {"schema": SCHEMA, "season": season, "source": [SITE, WEB, CORE],
            "access": "public, unauthenticated, free; no keys",
            "provenance_label": PROVENANCE_LABEL, "is_not": list(NOT_A),
            "license_handling": ("Third-party data; research use; not "
                                 "redistributed beyond this repository's "
                                 "staging data branch."),
            "illinois_note": "raw data unfiltered; consumers apply the Illinois exclusion",
            "bundles_sha256": dict(bundles), "payload_counts": dict(counts),
            "completeness": dict(comp), "failures": list(failures)[:500],
            "run": dict(run)}
