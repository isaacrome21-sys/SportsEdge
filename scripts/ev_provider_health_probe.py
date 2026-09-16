#!/usr/bin/env python3
"""Independent zero-authority Pinnacle health observation for EXTERNAL_EV."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "external_ev_provider_health_policy_v1.json"
_spec = importlib.util.spec_from_file_location("ev_tracker_probe_dep", ROOT / "scripts" / "ev_tracker.py")
_ev = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_ev)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def observe(policy: dict, api_key: str, client_factory=_ev.OddsApiClient) -> dict:
    base = {
        "schema_version": "SPORTSEDGE_EXTERNAL_EV_PROVIDER_HEALTH_OBSERVATION_V1",
        "policy_id": policy["policy_id"],
        "mode": policy["mode"],
        "provider": policy["provider"],
        "captured_at_utc": now_iso(),
        "transport_ok": False,
        "pinnacle_present": False,
        "representative_sport": None,
        "representative_event_id": None,
        "offered_market_keys": [],
        "latency_ms": None,
        "failure_class": None,
        "threshold_status": policy["threshold"]["status"],
        "suspension_authority": False,
        "evidence_authority": False,
        "model_p_authority": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "official_authority": False,
    }
    if not api_key:
        base["failure_class"] = "ODDS_API_KEY_MISSING"
        return base
    started = time.monotonic()
    client = client_factory(api_key, reserve=0)
    try:
        for sport in policy["probe"]["representative_sports"]:
            events = client.events(sport)
            if not events:
                continue
            event = sorted(events, key=lambda row: row["commence_time"])[0]
            base["representative_sport"] = sport
            base["representative_event_id"] = event["id"]
            odds = client.event_odds(
                sport,
                event["id"],
                policy["probe"]["representative_markets"],
                [policy["provider"]],
            )
            books = [b for b in odds.get("bookmakers", []) if isinstance(b, dict)]
            pinn = next((b for b in books if str(b.get("key", "")).lower() == policy["provider"]), None)
            base["transport_ok"] = True
            if pinn is not None:
                base["pinnacle_present"] = True
                base["offered_market_keys"] = sorted({str(m.get("key")) for m in pinn.get("markets", []) if isinstance(m, dict) and m.get("key")})
            else:
                base["failure_class"] = "PINNACLE_NOT_PRESENT_IN_PAYLOAD"
            break
        else:
            base["transport_ok"] = True
            base["failure_class"] = "NO_REPRESENTATIVE_EVENTS"
    except _ev.EVError as exc:
        base["failure_class"] = exc.code
    except Exception as exc:  # operationally recorded; probe itself remains evidence-only
        base["failure_class"] = f"UNEXPECTED_{type(exc).__name__}"
    finally:
        base["latency_ms"] = round((time.monotonic() - started) * 1000.0, 3)
    return base


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=POLICY_PATH)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if policy.get("mode") != "OBSERVE_ONLY" or policy.get("threshold", {}).get("status") != "UNFROZEN":
        raise SystemExit("PROVIDER_HEALTH_POLICY_NOT_OBSERVE_ONLY_UNFROZEN")
    result = observe(policy, os.environ.get("ODDS_API_KEY", ""))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
