"""MLB moneyline forward lane: scheduled capture via the DK RENDERED-PAGE fetcher (t269).

The active-window guard requires the acquisition workflow to keep its schedule and
workflow_run triggers. The DK-API guard forbids any scheduled workflow from reaching a DK API
URL builder. Both hold only if the scheduled capture uses the rendered-page fetcher.
SCREEN / NOT_VALIDATED. No network: the fetcher is injected.
"""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "mlb-moneyline-forward-evidence.yml"
SCRIPT = ROOT / "scripts" / "capture_mlb_rendered_paired_ml.py"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
import test_dk_api_scheduled_workflow_guard_20261023 as dkguard  # noqa: E402
import check_active_evidence_windows as aew  # noqa: E402

URL = "https://sportsbook.draftkings.com/leagues/baseball/mlb"
NOW = datetime(2026, 9, 16, 18, 0, 0, tzinfo=timezone.utc)
ART = "a" * 64


def _cap():
    spec = importlib.util.spec_from_file_location("capture_mlb_rendered_paired_ml", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------- workflow / guard contract ----------------

def _wf():
    return WF.read_text(encoding="utf-8")


def test_workflow_restores_schedule_and_workflow_run():
    trig = dkguard.on_triggers(_wf())
    assert "schedule" in trig and "workflow_run" in trig, trig
    assert dkguard.scheduled(_wf())
    assert "mlb-game-context-refresh" in _wf()


def test_scheduled_workflow_reaches_no_dk_api_builder():
    assert dkguard.report_one(_wf()) == []


def test_workflow_uses_rendered_capture_not_direct_api_capture():
    body = "\n".join(l for l in _wf().splitlines() if not l.lstrip().startswith("#"))
    assert "scripts/capture_mlb_rendered_paired_ml.py" in body
    assert "capture_mlb_direct_paired_ml" not in _wf()


def test_workflow_no_identity_spoofing_or_headless():
    low = _wf().lower()
    for bad in ("user-agent", "user_agent", "useragent", "--headless", "headless=true", "stealth"):
        assert bad not in low, bad
    assert "xvfb-run" in low  # headed Chrome on a virtual display


def test_active_window_mutation_guard_passes():
    failures = aew.mutation_failures(ROOT, ROOT / "config" / "active_evidence_windows_v1.json")
    assert failures == [], failures


def test_registry_names_rendered_capture_and_keeps_contract_strength():
    reg = json.loads((ROOT / "config" / "active_evidence_windows_v1.json").read_text())
    w = next(x for x in reg["windows"] if x["id"] == "MLB_MONEYLINE_V2_FORWARD")
    lits = w["required_authority_literals"]
    for need in ("schedule:", "workflow_run:", "mlb-game-context-refresh",
                 "scripts/capture_mlb_moneyline_model_p.py", "scripts/capture_mlb_rendered_paired_ml.py",
                 "scripts/capture_mlb_moneyline_paper_decisions.py", "data/mlb_forward_decisions"):
        assert need in lits, need
    assert len(lits) == 7
    assert w["status"] == "ACTIVE" and w["no_backfill"] is True
    assert "RENDERED_PAGE" in w["provider_dependency"]


def test_capture_script_module_closure_has_no_dk_api_builder():
    assert dkguard.report_one("python scripts/capture_mlb_rendered_paired_ml.py\n") == []


# ---------------- capture behaviour ----------------

def _team(name, sub=""):
    s = f'<span class="cb-market__label-sub-label">{sub}</span>' if sub else ""
    return ('<a data-testid="lp-nav-link" href="/event/x/1"><div>'
            f'<span class="cb-market__label-inner">{name}</span>{s}</div></a>')


def _card(eid, away, home, ap, hp):
    return (f'<div data-testid="market-mapping-template-210">{_team(away, "P1")}{_team(home, "P2")}'
            f'<button data-testid="component-builder-market-button-{eid}-0ML1_3">'
            f'<span data-testid="button-odds-market-board">{ap}</span></button>'
            f'<button data-testid="component-builder-market-button-{eid}-0ML1_1">'
            f'<span data-testid="button-odds-market-board">{hp}</span></button></div>')


def _fetch(cards, observed=NOW):
    from sportsedge.dk_rendered_page_fetcher import parse_rendered_board
    html = "<html><body>" + "".join(cards) + "</body></html>"

    def f(url, sport_key):
        assert url == URL and sport_key == "baseball_mlb"
        return parse_rendered_board(html, page_url=url, observed_at=observed, sport_key=sport_key,
                                    final_url=url, browser={"headless": False})
    return f


def _pred(root, game_pk=7001, minutes=32, away=("Tampa Bay Rays", 139), home=("Milwaukee Brewers", 158)):
    start = NOW + timedelta(minutes=minutes)
    p = Path(root) / start.date().isoformat() / f"game_{game_pk}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"market": "MONEYLINE", "game_pk": game_pk, "away_team": away[0], "away_team_id": away[1],
                             "home_team": home[0], "home_team_id": home[1], "event_start_ts": start.isoformat(),
                             "model_artifact_sha256": ART, "promotion_authority": False}))
    return start


def _run(tmp, cards, **kw):
    cap = _cap()
    return cap, cap.capture(output_dir=str(tmp / "q"), prediction_root=str(tmp / "p"),
                            fetch=_fetch(cards, kw.pop("observed", NOW)), artifact_binder=lambda: ART, **kw)


def test_retains_rendered_pair_bound_to_official_schedule(tmp_path):
    start = _pred(tmp_path / "p")
    cap, r = _run(tmp_path, [_card(999, "TB Rays", "MIL Brewers", "+159", "−193")])
    assert r["status"] == "RETAINED", r
    row = json.loads(Path(r["paths"][0]).read_text())
    assert row["source_class"] == "DRAFTKINGS_RENDERED_PAGE_V1"
    assert row["sportsbook"] == "draftkings" and row["promotion_authority"] is False
    assert row["home_team"] == "Milwaukee Brewers" and row["away_team"] == "Tampa Bay Rays"
    assert row["moneyline"] == {"status": "OK", "home_price_american": -193, "away_price_american": 159}
    assert row["scheduled_start_utc"] == start.isoformat()
    assert row["game_pk"] == 7001 and row["capture_window"] == "T30"
    assert row["observed_at_utc"] == "2026-09-16T18:00:00Z"
    assert row["model_artifact_sha256"] == ART
    assert len(row["raw_sha256"]) == 64
    assert "transport_host" not in row  # no host/IP recorded


def test_record_is_admissible_to_frozen_paper_decision_matcher(tmp_path):
    from sportsedge.mlb_moneyline_paper_decision import _matching_quotes, _norm_team
    start = _pred(tmp_path / "p")
    _, r = _run(tmp_path, [_card(999, "TB Rays", "MIL Brewers", "+159", "−193")])
    row = json.loads(Path(r["paths"][0]).read_text())
    m = _matching_quotes(quotes=[row], home=_norm_team("Milwaukee Brewers"), away=_norm_team("Tampa Bay Rays"),
                         start=start, generated=NOW - timedelta(minutes=10), artifact=ART, freeze_now=NOW)
    assert len(m) == 1


def test_unmapped_label_refused_not_guessed(tmp_path):
    _pred(tmp_path / "p")
    with pytest.raises(Exception) as e:
        _run(tmp_path, [_card(999, "TB Mystery", "MIL Brewers", "+159", "−193")])
    assert getattr(e.value, "reason", "") == "BLOCKED_ONE_SIDED"


def test_in_window_game_without_rendered_pair_blocks(tmp_path):
    _pred(tmp_path / "p")
    _pred(tmp_path / "p", game_pk=7002, away=("Boston Red Sox", 111), home=("New York Yankees", 147))
    with pytest.raises(Exception) as e:
        _run(tmp_path, [_card(999, "TB Rays", "MIL Brewers", "+159", "−193")])
    assert e.value.reason == "BLOCKED_ONE_SIDED"


def test_doubleheader_ambiguity_refused(tmp_path):
    _pred(tmp_path / "p", game_pk=7001)
    _pred(tmp_path / "p", game_pk=7003, minutes=34)
    with pytest.raises(Exception) as e:
        _run(tmp_path, [_card(999, "TB Rays", "MIL Brewers", "+159", "−193")])
    assert e.value.reason == "BLOCKED_ONE_SIDED"


def test_out_of_window_is_no_capture_due(tmp_path):
    _pred(tmp_path / "p", minutes=200)
    _, r = _run(tmp_path, [_card(999, "TB Rays", "MIL Brewers", "+159", "−193")])
    assert r["status"] == "NO_CAPTURE_DUE" and r["events_in_window"] == 0


def test_empty_board_blocks(tmp_path):
    _pred(tmp_path / "p")
    with pytest.raises(Exception) as e:
        _run(tmp_path, [])
    assert e.value.reason == "BLOCKED_EMPTY_BOARD"


def test_started_game_never_captured(tmp_path):
    _pred(tmp_path / "p", minutes=-5)
    _, r = _run(tmp_path, [_card(999, "TB Rays", "MIL Brewers", "+159", "−193")])
    assert r["status"] == "NO_CAPTURE_DUE" and r["paths"] == []


def test_same_observation_dedup_and_repeat_retained(tmp_path):
    _pred(tmp_path / "p")
    c = [_card(999, "TB Rays", "MIL Brewers", "+159", "−193")]
    _, a = _run(tmp_path, c)
    _, b = _run(tmp_path, c)
    _, d = _run(tmp_path, c, observed=NOW + timedelta(minutes=3))
    assert a["status"] == "RETAINED" and b["status"] == "ALREADY_CAPTURED" and d["status"] == "RETAINED"


def test_default_fetch_uses_rendered_fetcher_with_allowlisted_page():
    cap = _cap()
    from sportsedge.dk_rendered_page_fetcher import assert_rendered_page_url
    assert assert_rendered_page_url(cap.DEFAULT_PAGE_URL) == cap.DEFAULT_PAGE_URL
    src = SCRIPT.read_text()
    assert "fetch_rendered_board" in src
    for bad in ("user_agent", "user-agent", "headless=True", "direct_web_capture_source", "draftkings_game_market_source"):
        assert bad not in src, bad
