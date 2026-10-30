"""MLB StatsAPI historical acquisition — transport, bundling, completeness.

Free public endpoints only (https://statsapi.mlb.com/api/v1). No keys and
no paid credits. Used by `.github/workflows/mlb-statsapi-history.yml` to
build reproducible research datasets on a staging data branch.

PROVENANCE CONTRACT (owner ruling 9, Oct 17 2026):
* Every payload is labeled ACQUIRED_POSTHOC_FROM_PUBLIC_STATSAPI with the
  real retrieval time. It is NOT a pregame snapshot and NOT a recovered
  original under the #2344 data-loss incident. Nothing here may be
  presented as either.
* Payload bytes are stored verbatim (gzip JSONL), each with its own
  SHA-256, the request URL, and the retrieval timestamp.
* A season bundle is COMPLETE only if (a) every requested URL succeeded,
  and (b) every Final regular-season game in the schedule has exactly two
  starting-pitcher rows (gamesStarted == 1) across the pitching game logs,
  and (c) every such game has a boxscore payload. Hitting game logs for
  every non-pitcher listed player are also bundled (#2368 batter families).
  Anything else is INCOMPLETE, with the exact gaps listed. It is never
  rounded up.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping, Sequence

ROOT = "https://statsapi.mlb.com/api/v1"
SCHEMA = "SPORTSEDGE_STATSAPI_HISTORY_BUNDLE_V1"
PROVENANCE_LABEL = "ACQUIRED_POSTHOC_FROM_PUBLIC_STATSAPI"
NOT_A = ("PREGAME_SNAPSHOT", "ISSUE_2344_RECOVERED_ORIGINAL")
NOT_PLAYED_STATES = frozenset({"Postponed", "Cancelled"})
MIN_INTERVAL_SECONDS = 0.25  # polite client-side rate limit (<= 4 req/s)

Fetcher = Callable[[str], bytes]


def players_url(season: int) -> str:
    return f"{ROOT}/sports/1/players?season={season}"


def pitching_log_url(player_id: int, season: int) -> str:
    return (f"{ROOT}/people/{player_id}/stats?stats=gameLog"
            f"&group=pitching&season={season}&gameType=R")


def hitting_log_url(player_id: int, season: int) -> str:
    # Same URL form as the #2368 batter-props evaluator's cache keys.
    return (f"{ROOT}/people/{player_id}/stats?stats=gameLog"
            f"&group=hitting&season={season}")


def boxscore_url(game_pk: int) -> str:
    return f"{ROOT}/game/{game_pk}/boxscore"


def schedule_url(season: int, month: int) -> str:
    start = f"{season}-{month:02d}-01"
    end_month = month + 1 if month < 12 else 1
    end_year = season if month < 12 else season + 1
    end = f"{end_year}-{end_month:02d}-01"
    return (f"{ROOT}/schedule?sportId=1&gameType=R&startDate={start}"
            f"&endDate={end}")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class RateLimitedFetcher:
    """Wrap a raw fetcher with a minimum interval and bounded retries."""

    def __init__(self, raw: Fetcher, min_interval: float = MIN_INTERVAL_SECONDS,
                 retries: int = 3, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.raw, self.min_interval, self.retries = raw, min_interval, retries
        self.sleep, self.clock, self._last = sleep, clock, None

    def __call__(self, url: str) -> bytes:
        err: Exception | None = None
        for attempt in range(self.retries):
            if self._last is not None:
                wait = self.min_interval - (self.clock() - self._last)
                if wait > 0:
                    self.sleep(wait)
            self._last = self.clock()
            try:
                body = self.raw(url)
                json.loads(body)  # must be valid JSON
                return body
            except Exception as exc:  # noqa: BLE001 - recorded, never hidden
                err = exc
                self.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"FETCH_FAILED:{type(err).__name__}:{url}")


def acquire(urls: Sequence[str], fetch: Fetcher,
            now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
    """Fetch every URL. Returns (records, failures). A record carries the
    verbatim body and its provenance; a failure is never dropped."""
    records, failures = [], []
    for url in urls:
        try:
            body = fetch(url)
        except Exception as exc:  # noqa: BLE001
            failures.append({"url": url, "error": str(exc)})
            continue
        records.append({"url": url, "retrieved_at_utc": now().isoformat(),
                        "sha256": sha256_bytes(body),
                        "body": body.decode("utf-8")})
    return records, failures


def write_bundle(path: str, records: Iterable[Mapping]) -> str:
    """Deterministic gzip JSONL (mtime=0, sorted by URL). Returns SHA-256."""
    rows = sorted(records, key=lambda r: r["url"])
    raw = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                  for r in rows).encode("utf-8")
    with open(path, "wb") as fh:
        with gzip.GzipFile(filename="", fileobj=fh, mode="wb", mtime=0) as gz:
            gz.write(raw)
    with open(path, "rb") as fh:
        return sha256_bytes(fh.read())


def read_bundle(path: str) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    for r in rows:
        if sha256_bytes(r["body"].encode("utf-8")) != r["sha256"]:
            raise ValueError(f"PAYLOAD_SHA256_MISMATCH:{r['url']}")
    return rows


def pitcher_ids(players_body: Mapping) -> list[int]:
    out = []
    for p in players_body.get("people", []):
        pos = (p.get("primaryPosition") or {}).get("abbreviation")
        if pos in ("P", "TWP"):
            out.append(int(p["id"]))
    return sorted(set(out))


def hitter_ids(players_body: Mapping) -> list[int]:
    """Every listed player whose primaryPosition.type is not 'Pitcher'
    (two-way players included), as the #2368 batter acquisition did."""
    out = []
    for p in players_body.get("people", []):
        if ((p.get("primaryPosition") or {}).get("type") or "") != "Pitcher":
            out.append(int(p["id"]))
    return sorted(set(out))


def final_regular_games(schedule_bodies: Iterable[Mapping]) -> set[int]:
    games = set()
    for body in schedule_bodies:
        for d in body.get("dates", []):
            for g in d.get("games", []):
                st = g.get("status") or {}
                # StatsAPI marks never-played games abstractGameState=Final
                # with detailedState Postponed/Cancelled: no starters exist.
                if (g.get("gameType") == "R"
                        and st.get("abstractGameState") == "Final"
                        and st.get("detailedState") not in NOT_PLAYED_STATES):
                    games.add(int(g["gamePk"]))
    return games


def starts_by_game(log_bodies: Iterable[Mapping]) -> Counter:
    c: Counter = Counter()
    for body in log_bodies:
        for block in body.get("stats", []):
            for split in block.get("splits", []):
                stat = split.get("stat") or {}
                game = split.get("game") or {}
                if int(stat.get("gamesStarted", 0) or 0) == 1 and game.get("gamePk"):
                    c[int(game["gamePk"])] += 1
    return c


def completeness(final_games: set[int], starts: Counter,
                 failures: Sequence[Mapping],
                 boxscore_games: set[int] | None = None) -> dict:
    missing = sorted(g for g in final_games if starts.get(g, 0) == 0)
    one = sorted(g for g in final_games if starts.get(g, 0) == 1)
    over = sorted(g for g in final_games if starts.get(g, 0) > 2)
    unknown = sorted(g for g in starts if g not in final_games)
    box_missing = (sorted(g for g in final_games if g not in boxscore_games)
                   if boxscore_games is not None else [])
    ok = not failures and not missing and not one and not over and not box_missing
    return {
        "status": "COMPLETE" if ok else "INCOMPLETE",
        "final_regular_games": len(final_games),
        "games_with_two_starters": sum(1 for g in final_games if starts.get(g) == 2),
        "games_missing_both_starters": missing[:200],
        "games_with_one_starter": one[:200],
        "games_with_more_than_two_starters": over[:200],
        "start_rows_outside_final_schedule": len(unknown),
        "fetch_failures": len(failures),
        "boxscores_checked": boxscore_games is not None,
        "games_missing_boxscore": box_missing[:200],
        "rule": ("COMPLETE iff zero fetch failures and every Final REG game "
                 "has exactly two gamesStarted==1 pitching rows"
                 + (" and a boxscore payload" if boxscore_games is not None else "")),
    }


def manifest(season: int, bundles: Mapping[str, str], counts: Mapping[str, int],
             comp: Mapping, failures: Sequence[Mapping], copyright_text: str | None,
             run: Mapping[str, str]) -> dict:
    return {
        "schema": SCHEMA, "season": season,
        "source": ROOT, "access": "public, unauthenticated, free; no keys",
        "provenance_label": PROVENANCE_LABEL, "is_not": list(NOT_A),
        "license_notice_from_source": copyright_text,
        "license_handling": ("Third-party data; research use; source copyright "
                             "notice recorded verbatim; not redistributed beyond "
                             "this repository's staging data branch."),
        "rate_limit_seconds_min_interval": MIN_INTERVAL_SECONDS,
        "bundles_sha256": dict(bundles), "payload_counts": dict(counts),
        "completeness": dict(comp), "failures": list(failures)[:500],
        "run": dict(run),
    }
