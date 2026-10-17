"""2026 StatsAPI acquisition for the Model Fix Lane (transport only).

Mirrors backtest_program_20261014/scripts/acquire_statsapi.py exactly:
same cache dir (~/workspace/tmp/bt_data/statsapi_cache), URL-sha256
keys, tmp+os.replace writes, file-existence skip, shared index.json.

Fetches (per PREREG_BATTER_PROPS section 4 / PREREG_PITCHER_UNDERCARD
section 4):
- sports/1/players?season=2026
- hitting gameLogs 2026 for every non-pure-pitcher
- pitching gameLogs 2026 for every pitcher / two-way
- schedule?sportId=1&gameType=R&hydrate=linescore monthly chunks
  Oct 2025 .. Sep 2026

Boxscores for 2026 regular-season games are fetched by the batter
evaluator's boxscores phase (pattern: fetch_boxscore in Phase 2's
eval_batter_props.py), into ~/workspace/tmp/bt_data/boxscore_cache.

Writes its own summary to
~/workspace/tmp/bt_data/ACQUISITION_2026_DONE.json (the Phase 2
ACQUISITION_DONE.json is left untouched). Zero failures required
before scoring.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

ROOT = "https://statsapi.mlb.com/api/v1"
CACHE = os.path.expanduser("~/workspace/tmp/bt_data/statsapi_cache")
os.makedirs(CACHE, exist_ok=True)
INDEX_PATH = os.path.join(CACHE, "index.json")
DONE_PATH = os.path.expanduser(
    "~/workspace/tmp/bt_data/ACQUISITION_2026_DONE.json")

HEADERS = {"User-Agent": "SportsEdge-free-research/1.0",
           "Accept": "application/json"}


def cache_file(url: str) -> str:
    return os.path.join(
        CACHE, hashlib.sha256(url.encode()).hexdigest() + ".json")


def load_index() -> dict:
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH) as f:
            return json.load(f)
    return {}


def fetch_one(url: str) -> tuple[str, str, int]:
    path = cache_file(url)
    if os.path.exists(path):
        return url, "cached", os.path.getsize(path)
    last_err = None
    for attempt in range(3):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=30) as resp:
                body = resp.read()
            json.loads(body)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, path)
            return url, "ok", len(body)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    return url, f"FAIL:{type(last_err).__name__}", 0


def run(urls: list[str], workers: int = 10) -> dict:
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for url, status, nbytes in pool.map(fetch_one, urls):
            results[url] = {"file": os.path.basename(cache_file(url)),
                            "status": status, "bytes": nbytes}
    return results


def main() -> int:
    index = load_index()
    log = []

    player_urls = [f"{ROOT}/sports/1/players?season=2026"]
    res = run(player_urls)
    index.update(res)
    players: dict[int, dict] = {}
    with open(cache_file(player_urls[0])) as f:
        payload = json.load(f)
    for person in payload.get("people", []):
        players.setdefault(person["id"], person)
    log.append(f"players 2026: {len(players)} unique ids")

    log_urls: list[str] = []
    for pid, person in players.items():
        ptype = ((person.get("primaryPosition") or {}).get("type") or "")
        if ptype != "Pitcher":
            log_urls.append(
                f"{ROOT}/people/{pid}/stats?stats=gameLog&group=hitting"
                f"&season=2026")
        if ptype in ("Pitcher", "Two-Way"):
            log_urls.append(
                f"{ROOT}/people/{pid}/stats?stats=gameLog&group=pitching"
                f"&season=2026")
    log.append(f"gamelog urls: {len(log_urls)}")
    res = run(log_urls)
    index.update(res)
    fails = {u: v for u, v in res.items()
             if v["status"].startswith("FAIL")}
    log.append(f"gamelog failures: {len(fails)}")

    sched_urls: list[str] = []
    year, month = 2025, 10
    while (year, month) <= (2026, 9):
        start = f"{year}-{month:02d}-01"
        if month == 12:
            end = f"{year}-12-31"
            year, month = year + 1, 1
        else:
            end = f"{year}-{month + 1:02d}-01"
            month += 1
        sched_urls.append(
            f"{ROOT}/schedule?sportId=1&startDate={start}&endDate={end}"
            f"&gameType=R&hydrate=linescore")
    log.append(f"schedule urls: {len(sched_urls)}")
    res = run(sched_urls, workers=4)
    index.update(res)
    sfails = {u: v for u, v in res.items()
              if v["status"].startswith("FAIL")}
    log.append(f"schedule failures: {len(sfails)}")

    tmp = INDEX_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(index, f, indent=1, sort_keys=True)
    os.replace(tmp, INDEX_PATH)

    failures = sorted(u for u, v in index.items()
                      if "2026" in u
                      and str(v.get("status", "")).startswith("FAIL"))
    summary = {
        "scope": "2026 acquisition for model_fix_20261014 (transport only)",
        "players_2026": len(players),
        "gamelog_urls": len(log_urls),
        "schedule_urls": len(sched_urls),
        "failures": failures,
        "log": log,
    }
    with open(DONE_PATH, "w") as f:
        json.dump(summary, f, indent=1)
    print("\n".join(log))
    print("failures:", len(failures))
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
