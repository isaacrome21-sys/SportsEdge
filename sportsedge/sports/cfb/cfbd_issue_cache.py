"""Reusable CFBD history cache stored as comments on a GitHub issue.

Why issue comments: the phone-driven CFB workflow can write issues but not
repo contents, and the CFBD free tier rate-limits (HTTP 429). Each cached item
(one table for one season) is one comment whose body is

    CFBCACHE <name> <base64(gzip(json))>

e.g. ``lines_2019``, ``talent_2021``, ``returning_2021``, ``sp_2020``.
Loading reads every comment once via ``gh api``; only missing items are fetched
from CFBD, with a per-run call budget, a pause between calls, and an immediate
stop on the first 429 so the monthly quota is not burned.

Item shapes (all keyed by CFBD names):
  lines_<season>     {game_id: {spread,total,spread_open,total_open,provider,home,away,week,home_pts,away_pts}}
  talent_<season>    {team: 247 talent composite}
  returning_<season> {team: returning production percentPPA}
  sp_<season>        {team: SP+ rating for that season (use season-1 as a preseason prior)}
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
CACHE_ISSUE_FILE = ROOT / "config" / "cfb_history_cache_issue.json"
MARKER = "CFBCACHE"
_ITEM_RE = re.compile(rf"^{MARKER} ([a-z_]+_\d{{4}}) ([A-Za-z0-9+/=]+)\s*$", re.M)
TRUSTED_AUTHORS = {"github-actions[bot]", "isaacrome21-sys"}
PROVIDER_ORDER = ("consensus", "Bovada", "DraftKings", "ESPN Bet", "William Hill (New Jersey)", "teamrankings", "numberfire")


class RateLimited(RuntimeError):
    pass


def encode_item(name: str, data: Any) -> str:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"{MARKER} {name} " + base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode("ascii")


def decode_bodies(bodies) -> dict:
    out: dict = {}
    for body in bodies:
        for m in _ITEM_RE.finditer(body or ""):
            try:
                out[m.group(1)] = json.loads(gzip.decompress(base64.b64decode(m.group(2))).decode("utf-8"))
            except Exception:
                continue
    return out


def cache_issue() -> int | None:
    env = os.environ.get("CFB_HISTORY_CACHE_ISSUE")
    if env:
        return int(env)
    try:
        return int(json.loads(CACHE_ISSUE_FILE.read_text(encoding="utf-8"))["issue"])
    except Exception:
        return None


def _repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY") or "isaacrome21-sys/SportsEdge"


def load_cache(issue: int | None = None, runner: Callable = subprocess.run) -> dict:
    issue = issue or cache_issue()
    if not issue:
        return {}
    try:
        res = runner(["gh", "api", "--paginate", f"repos/{_repo()}/issues/{issue}/comments?per_page=100",
                      "--jq", ".[] | {u: .user.login, b: .body} | @json"], capture_output=True, text=True, timeout=120)
    except Exception as exc:
        print(f"CFB_CACHE_LOAD_FAILED {type(exc).__name__}: {exc}")
        return {}
    if res.returncode != 0:
        print(f"CFB_CACHE_LOAD_FAILED rc={res.returncode} {(res.stderr or '')[:200]}")
        return {}
    bodies = []
    for line in (res.stdout or "").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("u") in TRUSTED_AUTHORS:
            bodies.append(rec.get("b") or "")
    return decode_bodies(bodies)


def save_item(name: str, data: Any, issue: int | None = None, runner: Callable = subprocess.run) -> bool:
    issue = issue or cache_issue()
    if not issue:
        return False
    body = encode_item(name, data)
    if len(body) > 60000:
        print(f"CFB_CACHE_ITEM_TOO_LARGE {name} {len(body)}")
        return False
    res = runner(["gh", "api", f"repos/{_repo()}/issues/{issue}/comments", "-f", f"body={body}"],
                 capture_output=True, text=True, timeout=60)
    ok = res.returncode == 0
    print(f"CFB_CACHE_SAVED {name} {len(body)}B" if ok else f"CFB_CACHE_SAVE_FAILED {name} {(res.stderr or '')[:200]}")
    return ok


# ---------- CFBD fetch + normalisation ----------

def _get(path: str, params: dict, key: str, timeout: int = 60) -> Any:
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from sportsedge.sports.cfb.source import _auth, _cfbd_url
    req = Request(_cfbd_url(path, params), headers=_auth(key))
    try:
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 429:
            raise RateLimited(f"429 on {path} {params}") from exc
        raise


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def normalize_lines(data) -> dict:
    out = {}
    for g in data or []:
        lines = g.get("lines") or []
        by = {str(l.get("provider")): l for l in lines}
        pick = next((by[p] for p in PROVIDER_ORDER if p in by and by[p].get("spread") is not None), None)
        if pick is None:
            pick = next((l for l in lines if l.get("spread") is not None), None)
        if pick is None or _f(pick.get("spread")) is None:
            continue
        out[str(g.get("id"))] = {
            "spread": _f(pick.get("spread")), "total": _f(pick.get("overUnder")),
            "spread_open": _f(pick.get("spreadOpen")), "total_open": _f(pick.get("overUnderOpen")),
            "provider": pick.get("provider"), "home": g.get("homeTeam"), "away": g.get("awayTeam"),
            "week": g.get("week"), "home_pts": _f(g.get("homeScore")), "away_pts": _f(g.get("awayScore")),
        }
    return out


def _table(data, field: str) -> dict:
    out = {}
    for r in data or []:
        team = r.get("team") or r.get("school")
        v = _f(r.get(field))
        if team and v is not None:
            out[team] = v
    return out


SPECS = {
    "lines": ("/lines", lambda s: {"year": s, "seasonType": "regular"}, normalize_lines),
    "talent": ("/talent", lambda s: {"year": s}, lambda d: _table(d, "talent")),
    "returning": ("/player/returning", lambda s: {"year": s}, lambda d: _table(d, "percentPPA")),
    "sp": ("/ratings/sp", lambda s: {"year": s}, lambda d: _table(d, "rating")),
}


def ensure(names, key: str, cache: dict | None = None, *, budget: int = 12, pause: float = 2.5,
           fetch: Callable = _get, save: Callable = save_item, sleep: Callable = time.sleep) -> dict:
    """Return cache with as many of ``names`` as possible; fetch missing within budget, persist each."""
    cache = dict(cache if cache is not None else load_cache())
    calls = 0
    for name in names:
        if name in cache:
            continue
        if calls >= budget:
            print(f"CFB_CACHE_BUDGET_EXHAUSTED next={name}")
            break
        kind, season = name.rsplit("_", 1)
        path, params, norm = SPECS[kind]
        if calls:
            sleep(pause)
        calls += 1
        try:
            data = norm(fetch(path, params(int(season)), key))
        except RateLimited as exc:
            print(f"CFB_CACHE_RATE_LIMITED {name} -- stopping to save quota ({exc})")
            break
        except Exception as exc:
            print(f"CFB_CACHE_FETCH_FAILED {name} {type(exc).__name__}: {str(exc)[:120]}")
            continue
        if not data:
            print(f"CFB_CACHE_EMPTY {name}")
            continue
        cache[name] = data
        save(name, data)
    return cache


def history_names(first: int = 2016, last: int = 2025, current: int = 2026) -> list:
    """Complete seasons in order (lines + preseason tables), then the current season's preseason tables."""
    names = []
    for s in range(first, last + 1):
        names += [f"lines_{s}", f"talent_{s}", f"returning_{s}", f"sp_{s - 1}"]
    names += [f"talent_{current}", f"returning_{current}", f"sp_{current - 1}"]
    return names


def coverage(cache: dict, names) -> str:
    have = [n for n in names if n in cache]
    miss = [n for n in names if n not in cache]
    return f"have {len(have)}/{len(names)}; missing: {', '.join(miss) if miss else 'none'}"


def main(argv=None) -> int:
    key = os.environ.get("CFBD_API_KEY") or os.environ.get("SPORTSEDGE_CFBD_API_KEY") or ""
    if not key:
        raise SystemExit("CFB_SDV_CFBD_API_KEY_REQUIRED")
    budget = int(os.environ.get("CFB_CACHE_BUDGET", "12"))
    names = history_names()
    cache = ensure(names, key, budget=budget)
    print("CFB_SDV_CACHE_SUMMARY " + coverage(cache, names))
    for n in names:
        if n in cache:
            print(f"CFB_SDV_CACHE_ITEM {n} rows={len(cache[n])}")
    return 0
