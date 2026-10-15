import base64
import hashlib
import json
import shutil
import subprocess
from email.utils import parsedate_to_datetime
from pathlib import Path

import pytest

from sportsedge.sports.nba import injury_report_parser as p

FX = Path(__file__).parent / "fixtures" / "nba_injury_reports"
MAN = json.loads((FX / "manifest.json").read_text())


def pdf_bytes(slot):  # real PDFs stored base64 (text-only push channel); bytes are hash-checked
    return base64.b64decode((FX / f"Injury-Report_{slot}.pdf.b64").read_text())


def load(slot, **kw):
    m = MAN[slot]
    received = parsedate_to_datetime(m["http_date_at_receipt"])
    return p.parse_report((FX / f"Injury-Report_{slot}.txt").read_text(), pdf_sha256=m["pdf_sha256"],
                          received_at=received, extractor=m["extractor"], **kw)


def test_fixture_pdf_hashes_match_manifest():
    for slot, m in MAN.items():
        assert hashlib.sha256(pdf_bytes(slot)).hexdigest() == m["pdf_sha256"]


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="poppler not installed")
def test_reextraction_matches_saved_text(tmp_path):
    for slot in MAN:
        pdf = tmp_path / f"{slot}.pdf"
        pdf.write_bytes(pdf_bytes(slot))
        out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                             capture_output=True, text=True, check=True).stdout
        assert p.effective_time(out) == p.effective_time((FX / f"Injury-Report_{slot}.txt").read_text())


def test_effective_time_from_header_not_filename_and_dst():
    r = load("2025-01-15_05PM")  # filename says 05PM, header says 05:30 PM EST
    assert r["effective_at_utc"] == "2025-01-15T22:30:00+00:00" and r["effective_source"] == "REPORT_HEADER"
    assert r["received_at_utc"].startswith("2026-10-13") and r["received_at_utc"] != r["effective_at_utc"]
    assert load("2025-03-10_06PM")["effective_at_utc"] == "2025-03-10T22:30:00+00:00"  # 06:30 PM EDT
    assert load("2024-11-20_01PM")["effective_at_utc"] == "2024-11-20T18:30:00+00:00"


def test_hand_checked_rows_and_counts():
    r = load("2025-03-10_06PM")
    assert len(r["rows"]) == 186
    first = r["rows"][0]
    assert (first["matchup"], first["team"], first["player_name"], first["status"]) == \
        ("CHA@MIA", "CHA", "Mann, Tre", "OUT")
    nurk = next(x for x in r["rows"] if x["player_name"] == "Nurkic, Jusuf")
    assert nurk["status"] == "AVAILABLE" and nurk["participation"] == "UNKNOWN"
    br = next(x for x in r["rows"] if x["player_name"] == "Brunson, Jalen")
    assert (br["team"], br["matchup"], br["game_time_et"], br["status"]) == ("NYK", "NYK@SAC", "10:30 (ET)", "OUT")
    assert len(load("2025-01-15_05PM")["rows"]) == 166 and len(load("2024-11-20_01PM")["rows"]) == 87
    nys = [x for x in load("2024-11-20_01PM")["rows"] if x["status"] == "NOT_YET_SUBMITTED"]
    assert len(nys) == 10 and all(x["player_id"] is None for x in nys)


def test_listed_available_never_means_participation_and_no_authority():
    for slot in MAN:
        r = load(slot)
        assert r["forward_only"] and r["research_only"] and r["play_authority"] is False
        assert all(x["participation"] == "UNKNOWN" for x in r["rows"])


def test_player_mapping_fail_closed():
    d = {("CHA", "mann, tre"): 4431823, ("NYK", "brunson, jalen"): [3934672, 999]}
    r = load("2025-03-10_06PM", player_directory=d)
    mann = r["rows"][0]
    assert mann["player_id"] == 4431823 and mann["mapping"] == "MAPPED" and mann["availability"] == "OUT"
    br = next(x for x in r["rows"] if x["player_name"] == "Brunson, Jalen")
    assert br["player_id"] is None and br["mapping"] == "UNMAPPED" and br["availability"] == "UNKNOWN"
    other = next(x for x in r["rows"] if x["player_name"] == "Nurkic, Jusuf")
    assert other["mapping"] == "UNMAPPED" and other["availability"] == "UNKNOWN"


TXT = (FX / "Injury-Report_2025-03-10_06PM.txt").read_text()
KW = dict(pdf_sha256="0" * 64, received_at="2026-10-13T15:00:00Z", extractor="x")


@pytest.mark.parametrize("mutate,err", [
    (lambda t: t.replace("Charlotte Hornets", "Charlotte Bobcats", 1), "UNKNOWN_FIELD"),
    (lambda t: t.replace("CHA@MIA", "BOS@MIA", 1), "TEAM_NOT_IN_MATCHUP"),
    (lambda t: t.replace("Miller, Brandon      Out", "Miller, Brandon      Suspended", 1), "STATUS_UNKNOWN"),
    (lambda t: t.replace("Miller, Brandon      Out", "Miller, Brandon      GTD Out", 1), "UNPARSEABLE_LINE"),
    (lambda t: t.replace("Injury Report: 03/10/25 06:30 PM", "Injury Report: 03/10/25 07:30 PM", 1), "PAGE_HEADER_MISMATCH"),
    (lambda t: t.replace("Injury Report:", "Report:"), "HEADER_MISSING"),
])
def test_fail_closed_mutations(mutate, err):
    with pytest.raises(p.InjuryReportError, match=err):
        p.parse_report(mutate(TXT), **KW)


def test_receipt_before_effective_and_missing_hash_fail():
    with pytest.raises(p.InjuryReportError, match="RECEIPT_BEFORE"):
        p.parse_report(TXT, **{**KW, "received_at": "2025-03-10T22:00:00Z"})
    with pytest.raises(p.InjuryReportError, match="SHA256"):
        p.parse_report(TXT, **{**KW, "pdf_sha256": ""})
    with pytest.raises(p.InjuryReportError, match="TIMEZONE"):
        p.parse_report(TXT, **{**KW, "received_at": "2026-10-13T15:00:00"})
