"""Manual sharp-close observation fallback for EV_TRACKER_POLICY_V2.

This path exists for provider outages/quota exhaustion. It records a user-observed,
paired sharp quote before start and computes the same MARKET_FAIR_P/CLV math as the
automated tracker. Manual observations are explicitly NOT staging/promotion evidence:
they never write ledger/ev_close_attempts or ledger/ev_closes.

Usage from GitHub Actions issue event:
    python scripts/ev_tracker_manual_close.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYS_DIR = ROOT / "ledger" / "ev_plays"
MANUAL_DIR = ROOT / "ledger" / "ev_manual_close_observations"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


ev = _load("ev_math_manual_close", "sports/common/ev_math.py")
tracker = _load("ev_tracker_shared", "scripts/ev_tracker.py")
EVError = ev.EVError


def _num(text, code: str) -> float:
    try:
        return float(str(text).replace("+", "").strip())
    except (TypeError, ValueError):
        raise EVError(code, str(text)) from None


def _accepted_at(issue: dict, action: str):
    stamp = issue.get("updated_at") if action == "edited" else issue.get("created_at")
    if not stamp:
        raise EVError("MANUAL_CLOSE_TIMESTAMP_MISSING")
    return ev.parse_utc(stamp)


def _other_name(play: dict) -> str:
    if play["market"] == "totals":
        return "Under" if play["pick"] == "Over" else "Over"
    return play["home_team"] if play["pick"] == play["away_team"] else play["away_team"]


def _book_outcomes(play: dict, pick_price_am: float, other_price_am: float, line_text: str):
    pick_dec = ev.american_to_decimal(pick_price_am)
    other_dec = ev.american_to_decimal(other_price_am)
    market = play["market"]
    if market == "h2h":
        if str(line_text or "").strip():
            raise EVError("MANUAL_CLOSE_LINE_INVALID", "moneyline close must leave line blank")
        return [
            {"name": play["pick"], "price": pick_dec},
            {"name": _other_name(play), "price": other_dec},
        ]

    line = _num(line_text, "MANUAL_CLOSE_LINE_INVALID")
    if market == "spreads":
        return [
            {"name": play["pick"], "price": pick_dec, "point": line},
            {"name": _other_name(play), "price": other_dec, "point": -line},
        ]
    if market == "totals":
        if line <= 0:
            raise EVError("MANUAL_CLOSE_LINE_INVALID", str(line))
        return [
            {"name": play["pick"], "price": pick_dec, "point": line},
            {"name": _other_name(play), "price": other_dec, "point": line},
        ]
    raise EVError("MARKET_UNSUPPORTED", market)


def build_manual_observation(payload: dict, play: dict, policy: dict, env=None) -> dict:
    issue = payload.get("issue") or {}
    action = payload.get("action", "opened")
    accepted = _accepted_at(issue, action)
    start = ev.parse_utc(play["commence_time"])
    if accepted >= start:
        raise EVError("MANUAL_CLOSE_AFTER_START")

    fields = tracker.parse_issue_body(issue.get("body", ""))
    evidence_ref = (fields.get("Evidence reference") or "").strip()
    if not evidence_ref:
        raise EVError("MANUAL_CLOSE_EVIDENCE_REQUIRED")

    books = []
    configured = (("Pinnacle", "pinnacle"), ("Novig", "novig"), ("ProphetX", "prophetx"))
    for label, key in configured:
        pick_raw = (fields.get(f"{label} pick price") or "").strip()
        other_raw = (fields.get(f"{label} opposite price") or "").strip()
        line_raw = (fields.get(f"{label} line") or "").strip()
        supplied = bool(pick_raw or other_raw or line_raw)
        if not supplied:
            continue
        if not pick_raw or not other_raw:
            raise EVError("MANUAL_CLOSE_QUOTE_INCOMPLETE", label)
        outcomes = _book_outcomes(
            play,
            _num(pick_raw, "MANUAL_CLOSE_PRICE_INVALID"),
            _num(other_raw, "MANUAL_CLOSE_PRICE_INVALID"),
            line_raw,
        )
        books.append({
            "key": key,
            "last_update": tracker.iso(accepted),
            "markets": [{"key": play["market"], "last_update": tracker.iso(accepted), "outcomes": outcomes}],
        })

    if not books:
        raise EVError("MANUAL_CLOSE_NO_SHARP_QUOTES")

    synthetic = {"bookmakers": books}
    grade = ev.grade_attempt(synthetic, play, policy, accepted)
    return dict(
        tracker.provenance(env),
        record_type="MANUAL_CLOSE_OBSERVATION",
        play_id=play["play_id"],
        source_issue_number=issue.get("number"),
        policy_id=policy["policy_id"],
        policy_sha256=policy.get("_sha256"),
        captured_at=tracker.iso(accepted),
        evidence_reference=evidence_ref,
        evidence_method="MANUAL_USER_OBSERVED_PAIRED_SHARP_QUOTES",
        staging_eligible=False,
        staging_exclusion_reason="MANUAL_CLOSE_NOT_AUTOMATED_PROVIDER_EVIDENCE",
        observation=grade,
    )


def _already_answered(gh, issue: dict) -> bool:
    if not issue.get("comments"):
        return False
    marker = tracker.body_marker(issue)
    return any(
        (c.get("user") or {}).get("login") == gh.BOT_LOGIN and marker in (c.get("body") or "")
        for c in gh.issue_comments(issue["number"])
    )


def run(payload: dict, policy: dict, gh, owner: str, env=None) -> str:
    issue = payload.get("issue") or {}
    if not issue.get("title", "").startswith("[CLOSE]"):
        return "SKIP_NOT_CLOSE"
    if (issue.get("user") or {}).get("login") != owner:
        return "SKIP_NOT_OWNER"
    if _already_answered(gh, issue):
        return "SKIP_ALREADY_ANSWERED"

    fields = tracker.parse_issue_body(issue.get("body", ""))
    try:
        bet_issue = int((fields.get("Bet issue number") or "").strip().lstrip("#"))
    except ValueError:
        bet_issue = -1
    play_path = PLAYS_DIR / f"issue-{bet_issue}.json"
    marker = tracker.body_marker(issue)
    if bet_issue < 1 or not play_path.exists():
        gh.comment(issue["number"], f"Not recorded: `MANUAL_CLOSE_PLAY_NOT_FOUND`. Use the original logged bet issue number.\n{marker}")
        return "REJECTED_MANUAL_CLOSE_PLAY_NOT_FOUND"

    play = json.loads(play_path.read_text())
    if not ev.verify_seal(play):
        gh.comment(issue["number"], f"Not recorded: `MANUAL_CLOSE_PLAY_LEDGER_INVALID`.\n{marker}")
        return "REJECTED_MANUAL_CLOSE_PLAY_LEDGER_INVALID"

    name = f"close-issue-{issue['number']}"
    if (MANUAL_DIR / f"{name}.json").exists():
        gh.close(issue["number"])
        return "SKIP_ALREADY_RECORDED"

    try:
        record = build_manual_observation(payload, play, policy, env)
        sealed = tracker.write_new(MANUAL_DIR, name, record)
    except EVError as exc:
        gh.comment(issue["number"], f"Not recorded: `{exc}`. Edit this issue to correct it.\n{marker}")
        return f"REJECTED_{exc.code}"

    obs = sealed["observation"]
    clv = obs.get("prob_clv_pp")
    clv_text = "unavailable" if clv is None else f"{float(clv):+.2f}pp"
    gh.comment(
        issue["number"],
        f"Recorded manual sharp-close observation for **{tracker.bet_label(play)}**: "
        f"`{obs.get('status')}`, CLV {clv_text}. This is useful for review but is **not staging/promotion evidence**.\n{marker}",
    )
    gh.close(issue["number"])
    return "RECORDED"


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    owner = (repo or "/").split("/", 1)[0]
    if not event_path or not repo or not token or not owner:
        print("MANUAL_CLOSE_ENV_MISSING", file=sys.stderr)
        return 2
    payload = json.loads(Path(event_path).read_text())
    policy = ev.load_active_policy(ROOT)
    gh = tracker.GitHub(token, repo)
    result = run(payload, policy, gh, owner)
    print(result)
    return 0 if result.startswith(("RECORDED", "SKIP_")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
