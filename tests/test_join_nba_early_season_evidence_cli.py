import csv
import json
import pytest
from scripts.join_nba_early_season_evidence import build,main


def fixture(tmp_path):
    csvfile=tmp_path/"box.csv"
    with csvfile.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=("PLAYER_ID","GAME_ID","TEAM_ABBREVIATION",
                     "SEASON","SEASON_TYPE_ID","MIN","PTS","REB","AST"))
        w.writeheader()
        w.writerow({"PLAYER_ID":"123","GAME_ID":"game123",
                    "TEAM_ABBREVIATION":"CHI","SEASON":"2025-26",
                    "SEASON_TYPE_ID":"2","MIN":"31:22","PTS":"20",
                    "REB":"8","AST":"4"})
    e=tmp_path/"events.json"
    e.write_text(json.dumps({"events":[{"event_id":"game123",
         "tipoff":"2026-01-11T00:30:00Z",
         "result_observed_at":"2026-01-11T04:00:00Z",
         "finalized_at":"2026-01-11T03:50:00Z",
         "event_state":"FINAL","result_state":"FINAL",
         "source_ref":"external-gamelog-receipt"}]}))
    p=tmp_path/"roles.json"
    p.write_text(json.dumps({"roles":[{"player_id":"123",
        "team_abbreviation":"CHI","position":"F",
        "observed_at":"2026-01-10T20:00:00Z",
        "source_ref":"pre-event-roster"}]}))
    return csvfile,e,p


def test_cli_writes_only_joined_unverified_records(tmp_path):
    b,e,p=fixture(tmp_path)
    o=tmp_path/"output.json"
    assert main(["--box-csv",str(b),"--event-manifest",str(e),
                 "--role-manifest",str(p),"--out",str(o)])==0
    row=json.loads(o.read_text())
    assert row["joined"]==1
    assert row["rows"][0]["game_date"]=="2026-01-10"
    assert row["input_byte_sha256"]["boxscore_csv"]
    assert row["digest_semantics"].endswith("NOT_PROVIDER_ATTESTATION")
    assert row["play_authority"] is False


def test_unjoined_game_refuses_with_no_output(tmp_path):
    b,e,p=fixture(tmp_path)
    e.write_text(json.dumps({"events":[]}))
    o=tmp_path/"out.json"
    with pytest.raises(ValueError,match="EVENT_RECEIPT_MISSING"):
        main(["--box-csv",str(b),"--event-manifest",str(e),
              "--role-manifest",str(p),"--out",str(o)])
    assert not o.exists()


def test_empty_or_malformed_manifest_is_not_assumed_verified(tmp_path):
    b,e,p=fixture(tmp_path)
    p.write_text(json.dumps({"other":[]}))
    with pytest.raises(ValueError,match="MANIFEST_ROLES_INVALID"):
        build(box_csv=b,event_manifest=e,role_manifest=p)


def test_raw_byte_digest_changes_without_claiming_provider_authentication(tmp_path):
    b,e,p=fixture(tmp_path)
    first=build(box_csv=b,event_manifest=e,role_manifest=p)
    e.write_text(e.read_text()+"\n")
    second=build(box_csv=b,event_manifest=e,role_manifest=p)
    assert first["rows"]==second["rows"]
    assert first["input_byte_sha256"]["event_manifest"]!=second["input_byte_sha256"]["event_manifest"]
    assert first["receipt_authentication"]==second["receipt_authentication"]=="NOT_ESTABLISHED_BY_CALLER_FIELDS"


def test_cli_explicit_final_receipt_required_and_no_output_on_failure(tmp_path):
    b,e,p=fixture(tmp_path)
    manifest=json.loads(e.read_text())
    del manifest["events"][0]["result_state"]
    e.write_text(json.dumps(manifest))
    output=tmp_path/"unverified.json"
    with pytest.raises(ValueError,match="FINAL_STATE_WITNESS_MISSING"):
        main(["--box-csv",str(b),"--event-manifest",str(e),
              "--role-manifest",str(p),"--out",str(output)])
    assert not output.exists()
