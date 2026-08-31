from __future__ import annotations

import json

import pytest

from sportsedge.sports.cfb.truth_gate import CFBTruthGate
from sportsedge.sports.mlb.truth_gate import MLBTruthGate
from sportsedge.sports.nfl.truth_gate import NFLTruthGate
from sportsedge.validation.run_truth_gate import (
    TruthGateRunnerError,
    load_evidence,
    main,
    run_one,
)


def passing_evidence(gate, market: str, **changes):
    evidence = dict(
        evidence_market=market,
        evidence_policy_sha256=gate.policy_sha256,
        pit_reproducible=True,
        leakage_violations=0,
        n_forward_seasons=6,
        brier_model=0.20,
        brier_market=0.22,
        logloss_model=0.55,
        logloss_market=0.58,
        season_fold_scoring_win_rate=0.75,
        mean_novig_clv=0.006,
        clv_t_stat=2.5,
        roi_after_vig=0.025,
        calibration_slope=1.0,
        calibration_intercept=0.01,
        ece=0.015,
        n_promoted=800,
        recent_two_season_ok=True,
        live_two_sided_quote=True,
        data_fresh=True,
        exposure_limits_ok=True,
        model_prob=0.55,
        no_vig_prob=0.50,
        coherent_joint=True,
        shared_path_ok=True,
    )
    if isinstance(gate, CFBTruthGate):
        evidence["paired_historical_price_evidence_complete"] = True
    evidence.update(changes)
    return evidence


@pytest.mark.parametrize(
    ("sport", "market", "gate", "method"),
    [
        ("CFB", "MONEYLINE", CFBTruthGate(), "evaluate"),
        ("NFL", "GAME", NFLTruthGate(), "evaluate_surface"),
        ("MLB", "V7_GAME", MLBTruthGate(), "evaluate_family"),
    ],
)
def test_unified_runner_matches_direct_thin_adapter(tmp_path, sport, market, gate, method):
    evidence = passing_evidence(gate, market)
    direct = getattr(gate, method)(market, **evidence)
    out_path, via_runner = run_one(sport, market, evidence, tmp_path)
    assert via_runner == direct
    assert via_runner.content_hash() == direct.content_hash()
    assert via_runner.content_hash() in out_path.name


def test_identical_inputs_write_one_immutable_content_addressed_report(tmp_path):
    gate = CFBTruthGate()
    evidence = passing_evidence(gate, "SPREAD")
    first_path, first = run_one("CFB", "SPREAD", evidence, tmp_path)
    second_path, second = run_one("CFB", "SPREAD", evidence, tmp_path)
    assert first_path == second_path
    assert first.content_hash() == second.content_hash()
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_summary_flag_does_not_change_report_bytes(tmp_path):
    gate = CFBTruthGate()
    evidence = passing_evidence(gate, "SPREAD")
    evidence_path = tmp_path / "spread_evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    out_dir = tmp_path / "reports"

    assert main([
        "--sport", "CFB",
        "--market", "SPREAD",
        "--evidence", str(evidence_path),
        "--out-dir", str(out_dir),
        "--summary",
    ]) == 0
    report_path = next(out_dir.glob("*.json"))
    first = report_path.read_bytes()

    assert main([
        "--sport", "CFB",
        "--market", "SPREAD",
        "--evidence", str(evidence_path),
        "--out-dir", str(out_dir),
    ]) == 0
    assert report_path.read_bytes() == first


def test_fail_on_block_is_nonzero_for_no_bet(tmp_path):
    gate = CFBTruthGate()
    evidence = passing_evidence(
        gate,
        "SPREAD",
        model_prob=0.51,
        no_vig_prob=0.50,
    )
    evidence_path = tmp_path / "spread_evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    assert main([
        "--sport", "CFB",
        "--market", "SPREAD",
        "--evidence", str(evidence_path),
        "--out-dir", str(tmp_path / "reports"),
        "--fail-on-block",
    ]) == 1


def test_fail_on_block_is_zero_only_for_official_bet(tmp_path):
    gate = CFBTruthGate()
    evidence = passing_evidence(gate, "SPREAD")
    evidence_path = tmp_path / "spread_evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    assert main([
        "--sport", "CFB",
        "--market", "SPREAD",
        "--evidence", str(evidence_path),
        "--out-dir", str(tmp_path / "reports"),
        "--fail-on-block",
    ]) == 0


def test_stale_live_input_does_not_change_market_certification(tmp_path):
    gate = CFBTruthGate()
    evidence = passing_evidence(gate, "TOTAL", data_fresh=False)
    _, report = run_one("CFB", "TOTAL", evidence, tmp_path)
    assert report.hard_gate_pass is True
    assert report.market_status == "OFFICIAL"
    assert report.candidate_decision == "BLOCKED"
    assert "DATA_NOT_FRESH" in report.candidate_failures


def test_runner_does_not_inject_missing_evidence_identity(tmp_path):
    gate = CFBTruthGate()
    evidence = passing_evidence(gate, "MONEYLINE")
    evidence.pop("evidence_market")
    _, report = run_one("CFB", "MONEYLINE", evidence, tmp_path)
    assert report.hard_gate_pass is False
    assert "EVIDENCE_MARKET_IDENTITY_MISMATCH" in report.market_failures


def test_tampered_existing_report_fails_immutable(tmp_path):
    gate = CFBTruthGate()
    evidence = passing_evidence(gate, "TOTAL")
    path, _ = run_one("CFB", "TOTAL", evidence, tmp_path)
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(TruthGateRunnerError, match="IMMUTABLE_COLLISION"):
        run_one("CFB", "TOTAL", evidence, tmp_path)


def test_load_evidence_requires_json_object(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(TruthGateRunnerError, match="EVIDENCE_OBJECT_REQUIRED"):
        load_evidence(path)
