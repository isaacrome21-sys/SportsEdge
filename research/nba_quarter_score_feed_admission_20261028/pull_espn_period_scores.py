"""ESPN summary-API quarter-score puller (NBA period-outcomes feed).

Retrieval skeleton for the admission packet in this directory. Fetches one
completed game's ESPN summary document, validates it fail-closed, derives
the regulation quarter splits (the first four periods — exactly the
``NBAPeriodObservation`` form in
``sportsedge/sports/nba/period_history.py``), the overtime periods, and
the half splits (H1 = Q1+Q2, H2 = Q3+Q4, regulation only), and prints a
manifest entry JSON with the SHA-256 of the exact bytes received.

Refusals (printed as JSON, exit code 2):
  SOURCE_UNAVAILABLE   fetch failed or non-200
  SCHEMA_INVALID       payload shape is not the validated summary shape
  IDENTITY_UNVERIFIED  payload header id != requested ESPN event id
  NOT_FINAL            game is not final — period splits are incomplete
  SCORE_MISMATCH       linescore sums do not equal the payload finals
  SOURCE_CHANGED_AFTER_SNAPSHOT  --expect-sha256 re-pull mismatch

Stdlib only. Usage:
  python3 pull_espn_period_scores.py pull --event 401909877 [--out DIR]
      [--expect-sha256 HEX]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCE = "ESPN_SUMMARY_API"
SOURCE_VERSION = "espn-summary-v1:20261028"
URL_TEMPLATE = ("https://site.api.espn.com/apis/site/v2/sports/basketball/"
                "nba/summary?event={event_id}")
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class Refusal(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def fetch(event_id: str) -> bytes:
    url = URL_TEMPLATE.format(event_id=event_id)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                 "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            if resp.status != 200:
                raise Refusal("SOURCE_UNAVAILABLE", f"HTTP {resp.status}")
            return resp.read()
    except Refusal:
        raise
    except urllib.error.HTTPError as e:
        raise Refusal("SOURCE_UNAVAILABLE", f"HTTP {e.code}") from e
    except Exception as e:
        raise Refusal("SOURCE_UNAVAILABLE",
                      f"{type(e).__name__}: {e}") from e


def _period_value(entry) -> int:
    if not isinstance(entry, dict):
        raise Refusal("SCHEMA_INVALID", f"linescore entry not an object: {entry!r}")
    raw = entry.get("value", entry.get("displayValue"))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise Refusal("SCHEMA_INVALID", f"linescore value not numeric: {raw!r}")
    if value < 0 or value != int(value):
        raise Refusal("SCHEMA_INVALID", f"linescore value not a non-negative int: {raw!r}")
    return int(value)


def parse_sample(body: bytes, event_id: str, pulled_at: datetime) -> dict:
    try:
        doc = json.loads(body)
    except Exception as e:
        raise Refusal("SCHEMA_INVALID", f"payload is not JSON: {e}") from e
    header = doc.get("header") or {}
    if str(header.get("id")) != str(event_id):
        raise Refusal("IDENTITY_UNVERIFIED",
                      f"payload id {header.get('id')!r} != requested {event_id!r}")
    competitions = header.get("competitions") or []
    if len(competitions) != 1:
        raise Refusal("SCHEMA_INVALID", "expected exactly one competition")
    comp = competitions[0]
    status = ((comp.get("status") or {}).get("type") or {})
    if status.get("name") != "STATUS_FINAL" or status.get("state") != "post":
        raise Refusal("NOT_FINAL", f"status is {status.get('name')!r} — "
                                   "period splits are incomplete")
    competitors = comp.get("competitors") or []
    if len(competitors) != 2:
        raise Refusal("SCHEMA_INVALID", "expected exactly two competitors")
    sides: dict[str, dict] = {}
    for c in competitors:
        side = c.get("homeAway")
        if side not in ("home", "away") or side in sides:
            raise Refusal("SCHEMA_INVALID", f"bad homeAway: {side!r}")
        linescores = [_period_value(p) for p in (c.get("linescores") or [])]
        if len(linescores) < 4:
            raise Refusal("SCHEMA_INVALID",
                          f"{side} linescores has {len(linescores)} periods (< 4)")
        try:
            final = int(c.get("score"))
        except (TypeError, ValueError):
            raise Refusal("SCHEMA_INVALID", f"{side} final score not numeric")
        if sum(linescores) != final:
            raise Refusal("SCORE_MISMATCH",
                          f"{side} linescores sum {sum(linescores)} != final {final}")
        sides[side] = {
            "team": (c.get("team") or {}).get("abbreviation"),
            "linescores": linescores,
            "quarters_regulation": linescores[:4],
            "ot_periods": linescores[4:],
            "half_scores": [linescores[0] + linescores[1],
                            linescores[2] + linescores[3]],
            "final": final,
        }
    if len(sides) != 2:
        raise Refusal("SCHEMA_INVALID", "missing a home or away competitor")
    tipoff_raw = comp.get("date")
    try:
        tipoff = datetime.fromisoformat(str(tipoff_raw).replace("Z", "+00:00"))
    except ValueError:
        raise Refusal("SCHEMA_INVALID", f"unparseable tipoff: {tipoff_raw!r}")
    if tipoff.tzinfo is None:
        raise Refusal("SCHEMA_INVALID", "tipoff carries no timezone")
    season = header.get("season") or {}
    home, away = sides["home"], sides["away"]
    observation = {
        "game_id": str(event_id),
        "tipoff": tipoff.isoformat(),
        "observed_at": pulled_at.isoformat(),
        "home_quarters": home["quarters_regulation"],
        "away_quarters": away["quarters_regulation"],
        "source": SOURCE,
        "source_version": SOURCE_VERSION,
    }
    return {
        "espn_event_id": str(event_id),
        "game_id_namespace": "ESPN_EVENT_ID",
        "url": URL_TEMPLATE.format(event_id=event_id),
        "http_status": 200,
        "pulled_at_utc": pulled_at.isoformat(),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "stored_as": f"espn_summary_{event_id}.json",
        "date_utc": str(tipoff_raw),
        "season_year_espn": season.get("year"),
        "engine_season": (int(season["year"]) - 1) if season.get("year") else None,
        "season_type": season.get("type"),
        "home_team": home["team"],
        "away_team": away["team"],
        "home_linescores": home["linescores"],
        "away_linescores": away["linescores"],
        "home_quarters_regulation": home["quarters_regulation"],
        "away_quarters_regulation": away["quarters_regulation"],
        "home_ot_periods": home["ot_periods"],
        "away_ot_periods": away["ot_periods"],
        "home_half_scores": home["half_scores"],
        "away_half_scores": away["half_scores"],
        "home_final": home["final"],
        "away_final": away["final"],
        "checks": {"identity_match": True, "status_final": True,
                   "linescore_sums_match_finals": True},
        "observation": observation,
        "evidence_state": "verified-by-pull",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull")
    p.add_argument("--event", required=True)
    p.add_argument("--out", default=None,
                   help="directory to save the raw payload bytes into")
    p.add_argument("--expect-sha256", default=None,
                   help="refuse SOURCE_CHANGED_AFTER_SNAPSHOT if the "
                        "re-pulled payload hash differs")
    args = ap.parse_args()

    pulled_at = datetime.now(timezone.utc)
    try:
        body = fetch(args.event)
        digest = hashlib.sha256(body).hexdigest()
        if args.expect_sha256 and digest != args.expect_sha256:
            raise Refusal("SOURCE_CHANGED_AFTER_SNAPSHOT",
                          f"re-pull sha256 {digest} != pinned {args.expect_sha256}")
        entry = parse_sample(body, args.event, pulled_at)
    except Refusal as r:
        print(json.dumps({"status": "REFUSED", "reason": r.reason,
                          "detail": r.detail, "event": args.event}, indent=1))
        return 2
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / entry["stored_as"]).write_bytes(body)
    print(json.dumps(entry, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
