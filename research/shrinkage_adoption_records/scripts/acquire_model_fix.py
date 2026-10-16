#!/usr/bin/env python3
"""StatsAPI acquisition for the Model Fix lane (first-inning + F5 challengers).

Transport only. Populates ~/workspace/tmp/bt_data/statsapi_cache with
payloads keyed by sha256(url) (tmp + os.replace), skipping any URL
whose hashed file already exists (a sibling lane populates the same
cache concurrently; file existence is checked by hashed name, never
by trusting index.json alone).

Fetches (per PREREG_FIRST_INNING §4 / PREREG_F5 §4):
- schedule?sportId=1&hydrate=linescore, gameType=R, monthly chunks
  Oct 2025 .. Sep 2026 (production first-inning corpus shape)
- unfiltered schedule chunks mirroring acquire_statsapi_extra.py's
  windows for the 2025-09-29..2026-09-30 span (production's F5
  team schedule query carries no gameType filter)
- sports/1/players?season=2026
- pitching gameLogs season=2026 for every Pitcher / Two-Way player
  on the 2026 roster (first-inning actual starters)

Writes its own manifest (url -> file/status) to
model_fix_20261014/scratch/acquisition_manifest.json and also merges
into the cache index.json (read-modify-write at the end).
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
MANIFEST = os.path.expanduser(
    "~/workspace/sportsedge/model_fix_20261014/scratch/acquisition_manifest.json")
INDEX_PATH = os.path.join(CACHE, "index.json")
HEADERS = {"User-Agent": "SportsEdge-free-research/1.0",
           "Accept": "application/json"}


def cache_file(url: str) -> str:
    return os.path.join(CACHE, hashlib.sha256(url.encode()).hexdigest() + ".json")


def fetch_one(url: str) -> tuple[str, str, int]:
    path = cache_file(url)
    if os.path.exists(path):
        return url, "cached", os.path.getsize(path)
    last_err = None
    for attempt in range(3):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=60) as resp:
                body = resp.read()
            json.loads(body)  # validate before persisting
            tmp = path + f".tmp{os.getpid()}"
            with open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, path)
            return url, "ok", len(body)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    return url, f"FAIL:{type(last_err).__name__}", 0


def run(urls: list[str], workers: int = 10) -> dict:
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for url, status, nbytes in pool.map(fetch_one, urls):
            out[url] = {"file": os.path.basename(cache_file(url)),
                        "status": status, "bytes": nbytes}
    return out


def main() -> int:
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    manifest: dict = {}
    log = []

    # ---- schedule chunks -------------------------------------------------
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
    windows = [("2025-09-29", "2025-11-05"), ("2026-02-01", "2026-02-28"),
               ("2026-03-01", "2026-03-31"), ("2026-04-01", "2026-04-30"),
               ("2026-09-29", "2026-10-30")]
    for start, end in windows:
        sched_urls.append(
            f"{ROOT}/schedule?sportId=1&startDate={start}&endDate={end}"
            f"&hydrate=linescore")
    log.append(f"schedule urls: {len(sched_urls)}")
    res = run(sched_urls, workers=4)
    manifest.update(res)
    sfails = [u for u, v in res.items() if v["status"].startswith("FAIL")]
    log.append(f"schedule failures: {len(sfails)} {sfails}")
    log.append("schedule statuses: "
               + json.dumps({s: sum(1 for v in res.values() if v['status'] == s)
                             for s in {v['status'] for v in res.values()}}))

    # ---- players 2026 ----------------------------------------------------
    purl = f"{ROOT}/sports/1/players?season=2026"
    res = run([purl])
    manifest.update(res)
    with open(cache_file(purl)) as f:
        payload = json.load(f)
    pitchers = []
    for person in payload.get("people", []):
        ptype = ((person.get("primaryPosition") or {}).get("type") or "")
        if ptype in ("Pitcher", "Two-Way"):
            pitchers.append(person["id"])
    log.append(f"players 2026: {len(payload.get('people', []))} people; "
               f"pitchers/two-way: {len(pitchers)}")

    # ---- pitching gameLogs 2026 -------------------------------------------
    log_urls = [f"{ROOT}/people/{pid}/stats?stats=gameLog&group=pitching&season=2026"
                for pid in pitchers]
    log.append(f"pitching gamelog urls 2026: {len(log_urls)}")
    res = run(log_urls, workers=10)
    manifest.update(res)
    lfails = [u for u, v in res.items() if v["status"].startswith("FAIL")]
    log.append(f"gamelog failures: {len(lfails)} {lfails[:5]}")
    log.append("gamelog statuses: "
               + json.dumps({s: sum(1 for v in res.values() if v['status'] == s)
                             for s in {v['status'] for v in res.values()}}))

    with open(MANIFEST, "w") as f:
        json.dump({"manifest": manifest, "log": log}, f, indent=1)
    # Merge into the shared index (best-effort; files on disk are canonical).
    try:
        index = {}
        if os.path.exists(INDEX_PATH):
            with open(INDEX_PATH) as f:
                index = json.load(f)
        index.update(manifest)
        tmp = INDEX_PATH + f".tmp{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(index, f, indent=1, sort_keys=True)
        os.replace(tmp, INDEX_PATH)
    except Exception as exc:  # noqa: BLE001
        log.append(f"index merge failed (non-fatal): {exc}")
    print("\n".join(log))
    fails = [u for u, v in manifest.items() if v["status"].startswith("FAIL")]
    print("TOTAL FAILURES:", len(fails))
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())
