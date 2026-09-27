#!/usr/bin/env python3
"""Verify CFBD account/quota before reconstructed CFB selection acquisition.

This performs exactly one account-info request and zero historical replay calls.
It deliberately prints only a redacted public report. Exact account/quota values
may be written to a caller-selected private temporary file, but must not be
committed to this public repository.

The selection lane does not require CFBD's paid weather endpoint. Frozen weather
features are reconstructed separately from CFBD venue metadata plus public
Open-Meteo historical reanalysis and remain RECONSTRUCTED_HISTORICAL_NOT_PIT.

No candidate evaluation is performed and no Model_P, Truth Gate, promotion,
eligibility, staking, OFFICIAL, evidence-clock, or backfill authority is created.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/cfb_cfbd_reconstructed_selection_budget_v1.json"
INFO_URL = "https://api.collegefootballdata.com/info"
EXPECTED_WEATHER_CONTRACT = "CFBD_VENUES_OPEN_METEO_ERA5_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE"


class CFBProviderPreflightError(RuntimeError):
    pass


def _zero_authority() -> dict[str, bool]:
    return {
        "attempt_consumed": False,
        "evaluation_performed": False,
        "model_p": False,
        "truth_gate": False,
        "promotion": False,
        "eligibility": False,
        "staking": False,
        "official": False,
        "backfill": False,
    }


def _load_config(path: Path = CONFIG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "CFB_CFBD_RECONSTRUCTED_SELECTION_BUDGET_V1":
        raise CFBProviderPreflightError("CFB_CFBD_PREFLIGHT_CONFIG_INVALID")
    return payload


def fetch_account_info(api_key: str, *, opener: Callable = urlopen) -> dict[str, Any]:
    key = str(api_key or "").strip()
    if not key:
        raise CFBProviderPreflightError("CFBD_API_KEY_MISSING")
    request = Request(
        INFO_URL,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with opener(request, timeout=20) as response:
            raw = response.read()
    except Exception as exc:
        raise CFBProviderPreflightError(f"CFBD_INFO_REQUEST_FAILED:{type(exc).__name__}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBProviderPreflightError("CFBD_INFO_RESPONSE_INVALID_JSON") from exc
    if not isinstance(payload, Mapping):
        raise CFBProviderPreflightError("CFBD_INFO_RESPONSE_NOT_OBJECT")
    return dict(payload)


def _weather_transport(config: Mapping[str, Any]) -> tuple[str, bool]:
    weather = config.get("weather_reconstruction")
    if not isinstance(weather, Mapping):
        return "", False
    contract = str(weather.get("contract") or "").strip()
    ready = (
        contract == EXPECTED_WEATHER_CONTRACT
        and weather.get("venue_endpoint") == "/venues"
        and str(weather.get("archive_endpoint") or "").startswith("https://archive-api.open-meteo.com/")
        and weather.get("archive_model") == "era5"
        and weather.get("provenance_class") == "RECONSTRUCTED_HISTORICAL_NOT_PIT"
        and weather.get("promotion_authority") is False
    )
    return contract, ready


def evaluate_account(info: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    blockers: list[str] = []
    try:
        patron_level = int(info["patronLevel"])
        remaining = int(info["remainingCalls"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBProviderPreflightError("CFBD_INFO_REQUIRED_FIELDS_MISSING") from exc
    if patron_level < 0 or remaining < 0:
        raise CFBProviderPreflightError("CFBD_INFO_REQUIRED_FIELDS_INVALID")

    quotas = config.get("standard_tier_monthly_quotas") or {}
    labels = config.get("tier_labels") or {}
    quota_raw = quotas.get(str(patron_level))
    label = labels.get(str(patron_level))
    if quota_raw is None or label is None:
        blockers.append("CFBD_STANDARD_TIER_MAPPING_UNKNOWN")
        monthly_quota = None
        tier_label = f"PATRON_LEVEL_{patron_level}"
    else:
        monthly_quota = int(quota_raw)
        tier_label = str(label)
        if remaining > monthly_quota:
            blockers.append("CFBD_TIER_QUOTA_MAPPING_INCONSISTENT")

    weather_contract, weather_transport_ready = _weather_transport(config)
    if not weather_transport_ready:
        blockers.append("CFB_RECONSTRUCTED_WEATHER_TRANSPORT_CONTRACT_INVALID")

    plan = config.get("planned_new_calls_upper_bound") or {}
    planned = int(plan.get("total", -1))
    reserve = int(config.get("retry_reserve_calls", -1))
    if planned < 0 or reserve < 0:
        raise CFBProviderPreflightError("CFB_CFBD_PREFLIGHT_BUDGET_INVALID")
    call_plan_fits = remaining >= planned + reserve
    if not call_plan_fits:
        blockers.append("CFBD_REPLAY_PLAN_EXCEEDS_REMAINING_QUOTA")

    ready = not blockers
    private_report = {
        "schema_version": "CFB_CFBD_PROVIDER_PREFLIGHT_V1",
        "status": "VERIFIED_BEFORE_FIRST_REPLAY_CALL" if ready else "BLOCKED_PROVIDER_PREFLIGHT",
        "active_cfbd_tier": tier_label,
        "patron_level": patron_level,
        "monthly_quota": monthly_quota,
        "remaining_quota": remaining,
        "planned_new_calls": planned,
        "retry_reserve_calls": reserve,
        "cfbd_weather_entitled": patron_level >= 1,
        "cfbd_weather_required_for_selection": False,
        "weather_source_contract": weather_contract,
        "weather_transport_ready": weather_transport_ready,
        "verified_cache_reuse": True,
        "resume_from_verified_cache": True,
        "restart_from_2015": False,
        "retry_backoff": True,
        "historical_replay_calls_performed": 0,
        "blockers": blockers,
        "authority": _zero_authority(),
    }
    public_report = {
        "schema_version": "CFB_CFBD_PROVIDER_PREFLIGHT_PUBLIC_V1",
        "status": private_report["status"],
        "account_info_verified": True,
        "standard_tier_mapping_verified": monthly_quota is not None and "CFBD_TIER_QUOTA_MAPPING_INCONSISTENT" not in blockers,
        "cfbd_weather_entitled": private_report["cfbd_weather_entitled"],
        "cfbd_weather_required_for_selection": False,
        "weather_source_contract": weather_contract,
        "weather_transport_ready": weather_transport_ready,
        "call_plan_fits": call_plan_fits,
        "historical_replay_calls_performed": 0,
        "blockers": blockers,
        "authority": _zero_authority(),
    }
    return private_report, public_report


def run(api_key: str, *, config: Mapping[str, Any] | None = None, opener: Callable = urlopen):
    cfg = dict(config or _load_config())
    info = fetch_account_info(api_key, opener=opener)
    return evaluate_account(info, cfg)


def _write_outputs(report: Mapping[str, Any]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"state={report['status']}\n")
        handle.write(f"weather_transport_ready={str(bool(report.get('weather_transport_ready'))).lower()}\n")
        handle.write(f"call_plan_fits={str(bool(report['call_plan_fits'])).lower()}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-out", type=Path)
    parser.add_argument("--public-out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        private, public = run(os.environ.get("CFBD_API_KEY", ""))
    except CFBProviderPreflightError as exc:
        private = None
        public = {
            "schema_version": "CFB_CFBD_PROVIDER_PREFLIGHT_PUBLIC_V1",
            "status": "BLOCKED_PROVIDER_PREFLIGHT",
            "account_info_verified": False,
            "standard_tier_mapping_verified": False,
            "cfbd_weather_entitled": False,
            "cfbd_weather_required_for_selection": False,
            "weather_source_contract": EXPECTED_WEATHER_CONTRACT,
            "weather_transport_ready": False,
            "call_plan_fits": False,
            "historical_replay_calls_performed": 0,
            "blockers": [str(exc)],
            "authority": _zero_authority(),
        }

    args.public_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_out.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.private_out is not None and private is not None:
        args.private_out.parent.mkdir(parents=True, exist_ok=True)
        args.private_out.write_text(json.dumps(private, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(public, sort_keys=True))
    _write_outputs(public)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
