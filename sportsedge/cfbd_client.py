"""CollegeFootballData API client — ACTIONS-SIDE ONLY.

NEVER imported by the phone runner. The runner reads the data-branch archive
via sportsedge.cfbd_reader, which never touches the network and never reads
an API key. This client exists solely for the GitHub Actions archival
workflow (.github/workflows/archive-cfbd-advanced.yml), where the key is
injected from the SPORTSEDGE_CFBD_API_KEY repo secret.

Key handling (hard rules):
- The key is read from the environment ONLY (SPORTSEDGE_CFBD_API_KEY).
- The client raises CFBDKeyMissing when the variable is absent or blank.
- The key value is NEVER logged, printed, embedded in error messages, file
  paths, URLs, or exception reprs. HTTP errors are reported by status code
  and endpoint path only.
- Unit tests must use a fake key value and a stubbed transport (no network,
  no real secrets).

Free-tier contract (documented from CollegeFootballData's published tiers;
the client ALSO reads GET /info at runtime instead of hardcoding limits):
- 1,000 calls/month, calendar-month reset; the call pool is shared across
  CFBD's football and basketball products (we only call football).
- Seven endpoints are feature-gated off the free tier. The opponent-adjusted
  metrics (notably SP+ via /ratings/sp) are a paid-tier product: they are
  NEVER requested by this client. PAID_TIER_GATED raises CFBDNotWired
  before any HTTP request is made. Any 402/403 from any other endpoint is
  mapped to CFBDTierGated with the endpoint path only.
- Raw advanced stats (EPA, success rate, havoc, PPA) ARE free-tier. Those
  are the endpoints this client exposes.

Stdlib only (urllib), mirroring the repo's archival scripts.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

API_ROOT = "https://api.collegefootballdata.com"
KEY_ENV_VAR = "SPORTSEDGE_CFBD_API_KEY"
SCHEMA_VERSION = "CFBD_ARCHIVE_V1"

# Endpoints that are feature-gated off the CFBD free tier. The review of
# Isaac's source list (Oct 11, 2026) established that opponent-adjusted
# metrics live on the paid tier; SP+ is opponent-adjusted by construction.
# NEVER request these on the free tier: the method raises before any call
# is made, so no budget is ever burned probing them.
PAID_TIER_GATED = frozenset({
    "/ratings/sp",          # SP+ — opponent-adjusted (paid tier)
})

# Raw advanced-efficiency endpoints on the free tier. All calls pass
# excludeGarbageTime=true so the archived numbers are garbage-time-free.
FREE_TIER_ENDPOINTS = {
    "season_advanced": "/stats/season/advanced",  # raw EPA / success / havoc / PPA, per season
    "game_advanced": "/stats/game/advanced",      # per-game per-team EPA / success / havoc
    "ppa_games": "/ppa/games",                    # per-game PPA breakdown
    "info": "/info",                              # tier + monthly budget discovery
}


class CFBDError(RuntimeError):
    """Base fail-closed error. Never downgraded to a warning."""


class CFBDKeyMissing(CFBDError):
    """SPORTSEDGE_CFBD_API_KEY is absent or blank."""


class CFBDNotWired(CFBDError):
    """The endpoint is paid-tier-gated; never call it on the free tier."""


class CFBDTierGated(CFBDError):
    """The API answered 402/403: the key's tier cannot reach this endpoint."""


class CFBDBudgetExhausted(CFBDError):
    """Refusing the call would exceed the remaining monthly budget."""


@dataclass
class CFBDClient:
    """Minimal CFBD client. transport is injectable for tests."""

    api_key: str = field(repr=False)
    timeout_seconds: int = 30
    _calls_made: int = field(default=0, init=False, repr=False)

    @classmethod
    def from_env(cls, env: dict | None = None) -> "CFBDClient":
        """Build from the environment only. Fails closed when the key is absent."""
        source = env if env is not None else os.environ
        key = (source.get(KEY_ENV_VAR) or "").strip()
        if not key:
            raise CFBDKeyMissing(
                "CFBD_KEY_MISSING: set %s (GitHub repo secret; "
                "Actions-side archival only)" % KEY_ENV_VAR
            )
        return cls(api_key=key)

    # -- low-level ------------------------------------------------------
    def _request(self, path: str, params: dict | None = None) -> object:
        if path in PAID_TIER_GATED:
            raise CFBDNotWired(
                "CFBD_PAID_TIER_GATED:%s — opponent-adjusted metrics are a "
                "paid-tier product; never request on the free tier" % path
            )
        query = urllib.parse.urlencode(
            {k: v for k, v in (params or {}).items() if v is not None}
        )
        url = API_ROOT + path + ("?" + query if query else "")
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer REDACTED",  # placeholder replaced below
                "Accept": "application/json",
                "User-Agent": "SportsEdge-CFBD-Archiver/1.0",
            },
        )
        # The real key is set on the header object directly so it never
        # appears in any repr/log of the Request construction above.
        request.add_header("Authorization", "Bearer " + self.api_key)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (402, 403):
                raise CFBDTierGated(
                    "CFBD_TIER_GATED:http=%d path=%s" % (exc.code, path)
                ) from exc
            raise CFBDError(
                "CFBD_HTTP_ERROR:http=%d path=%s" % (exc.code, path)
            ) from exc
        except urllib.error.URLError as exc:
            raise CFBDError("CFBD_NETWORK_ERROR:path=%s" % path) from exc
        self._calls_made += 1
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CFBDError("CFBD_BAD_JSON:path=%s" % path) from exc

    @property
    def calls_made(self) -> int:
        return self._calls_made

    # -- tier / budget discovery (1 call; never hardcoded limits) -------
    def get_info(self) -> dict:
        """GET /info: tier name, monthly limit, used/remaining, reset time."""
        payload = self._request(FREE_TIER_ENDPOINTS["info"])
        if not isinstance(payload, dict):
            raise CFBDError("CFBD_INFO_MALFORMED")
        return payload

    # -- free-tier advanced stats ---------------------------------------
    def season_advanced(self, year: int, **kwargs) -> list:
        """Raw season-advanced stats for ALL teams (1 call per season)."""
        params = {"year": year, "excludeGarbageTime": "true", **kwargs}
        payload = self._request(FREE_TIER_ENDPOINTS["season_advanced"], params)
        if not isinstance(payload, list):
            raise CFBDError("CFBD_SEASON_ADVANCED_MALFORMED")
        return payload

    def game_advanced(self, year: int, week: int, **kwargs) -> list:
        """Per-game per-team advanced stats for one week (1 call per week)."""
        params = {
            "year": year, "week": week,
            "excludeGarbageTime": "true", "seasonType": "both", **kwargs,
        }
        payload = self._request(FREE_TIER_ENDPOINTS["game_advanced"], params)
        if not isinstance(payload, list):
            raise CFBDError("CFBD_GAME_ADVANCED_MALFORMED")
        return payload

    def ppa_games(self, year: int, week: int, **kwargs) -> list:
        """Per-game PPA for one week (1 call per week)."""
        params = {
            "year": year, "week": week,
            "excludeGarbageTime": "true", "seasonType": "both", **kwargs,
        }
        payload = self._request(FREE_TIER_ENDPOINTS["ppa_games"], params)
        if not isinstance(payload, list):
            raise CFBDError("CFBD_PPA_GAMES_MALFORMED")
        return payload

    def sp_ratings(self, year: int) -> list:  # noqa: ARG002
        """SP+ — intentionally NOT wired. Paid-tier product; never call."""
        raise CFBDNotWired(
            "CFBD_PAID_TIER_GATED:/ratings/sp — SP+ is opponent-adjusted and "
            "lives on the paid tier. Pair free raw EPA with our own opponent "
            "adjustment (sportsedge.cfbd_reader) instead."
        )
