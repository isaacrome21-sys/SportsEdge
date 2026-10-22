import json
from pathlib import Path
import pytest

from scripts.run_cfb_nhl_research_readout import run_payload,main


def payload():
    return {"as_of":"2026-10-21T17:00:00Z",
        "nhl_games":[{"event_id":"one","away":"Flyers","home":"Sabres",
            "event_start":"2026-10-21T23:00:00Z",
            "fixture_source_ref":"fixture-source"}],
        "cfb_games":[{"event_id":"two","away":"New Mexico State",
            "home":"Sam Houston","event_start":"2026-10-21T23:00:00Z"}]}


def test_mixed_coverage_reports_usable_readout_and_no_plays():
    r=run_payload(payload())
    assert r["count"]==2
    assert r["items"][0]["status"]=="RESEARCH_PROJECTION"
    assert r["items"][1]["status"]=="EVIDENCE_INTAKE_MISSING"
    assert r["model_validation"]=="NONE"
    assert r["play_authority"] is False


def test_cli_records_reproducible_input_digest(tmp_path):
    i=tmp_path/"in.json"
    o=tmp_path/"out.json"
    i.write_text(json.dumps(payload()))
    assert main(["--input",str(i),"--output",str(o)])==0
    r=json.loads(o.read_text())
    assert r["input_sha256"]==run_payload(payload())["input_sha256"]
    assert r["source_provenance"].startswith("CALLER_SUPPLIED")


def test_duplicate_fixture_refused():
    p=payload()
    p["nhl_games"].append(p["nhl_games"][0])
    with pytest.raises(ValueError,match="DUPLICATE"):
        run_payload(p)


def test_empty_dataset_refused():
    with pytest.raises(ValueError,match="NO_GAMES"):
        run_payload({"as_of":"2026-10-21T17:00:00Z"})
