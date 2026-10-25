"""QB_IDENTITY_EVIDENCE Form 2 MULTI (MULTI_SOURCE_CORROBORATION) tests.

Owner ruling (Isaac, Oct 23, 2026, "Add all"): a second QB identity
evidence path alongside the frozen DEPTH_ROSTER_COMPOSITE. A team's
QB1 is established when a primary chart source (OurLads or CFBDepth)
shows a QB1 under a stamp postdating the previous-game kickoff AND
an independent non-social source corroborates the same QB1 with
current data. Conflicts among current sources refuse; a lone source
refuses; unreachable sources are recorded, never dropped.

Fixture pages are modeled on the Oct 23, 2026 live probe shapes
(Who's Starting team page, TheTwoDeep QB index, a 247Sports chart
article, the OurLads HTML table the frozen normalizer reads) for the
Oct 24 BYU @ UCF fixture. No network is touched.
"""
import hashlib
import json
from datetime import datetime, timezone

import pytest

from sportsedge.prepricing import qb_evidence_archive as archive
from sportsedge.prepricing import qb_identity_evidence as frozen
from sportsedge.prepricing import qb_identity_multi as multi

BYU_ID, UCF_ID = "252", "2116"
EVENT_ID = "401856955"
KICKOFF = datetime(2026, 10, 24, 19, 30, tzinfo=timezone.utc)
KICKOFF_ISO = "2026-10-24T19:30:00Z"
PREV_ISO = "2026-10-17T23:00:00Z"
CAPTURED = datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)

URLS = {
    "OURLADS": "https://www.ourlads.com/ncaa-football-depth-charts/depth-chart/brigham-young/90222",
    "CFBDEPTH": "https://cfbdepth.com/team/brigham-young",
    "WHOSSTARTING": "https://whosstarting.com/team/brigham-young/",
    "TWODEEP": "https://www.thetwodeep.com/college/depth-charts/position/qb",
    "SPORTS247": "https://247sports.com/college/byu/article/byu-depth-chart-000000001/",
    "BEAT_SOCIAL": "https://x.com/byubeat/status/0000000000000000000",
}

OURLADS_HTML = """<html><body>
<p>Updated: 10/23/2026 7:02PM ET</p>
<table>
<tr><td>QB</td><td>47</td><td>Bachmeier, Bear SO</td><td>10</td><td>Bourguet, Treyson RS SR</td></tr>
<tr><td>RB</td><td>12</td><td>Rex, Preston RS SR</td><td>20</td><td>Tonga, Journee FR</td></tr>
</table>
</body></html>"""

OURLADS_STALE_HTML = OURLADS_HTML.replace("10/23/2026 7:02PM", "10/16/2026 7:02PM")

CFBDEPTH_TEXT = (
    "Updated: 10/23/2026 6:15PM ET\n"
    "1. Bachmeier, Bear — SO #47\n"
    "2. Bourguet, Treyson — RS SR #10\n")

CFBDEPTH_TEXT_OTHER_QB1 = (
    "Updated: 10/23/2026 6:15PM ET\n"
    "1. Bourguet, Treyson — RS SR #10\n"
    "2. Bachmeier, Bear — SO #47\n")

WHOSSTARTING_HTML = """<html><body>
<h2>Starters</h2>
<ol><li>1. QB Bear Bachmeier</li><li>2. RB Preston Rex</li></ol>
<p>Depth Chart · Updated Oct 23, 2026 · Two-deep · Public sources</p>
<p>Bear Bachmeier is the projected starting quarterback for BYU as of
October 23, 2026. Treyson Bourguet is listed second.</p>
<p>QB: Bear Bachmeier, Treyson Bourguet, Enoch Watson</p>
</body></html>"""

WHOSSTARTING_CONFLICT_HTML = WHOSSTARTING_HTML.replace(
    "Bear Bachmeier is the projected starting quarterback",
    "Treyson Bourguet is the projected starting quarterback").replace(
    "QB: Bear Bachmeier, Treyson Bourguet, Enoch Watson",
    "QB: Treyson Bourguet, Bear Bachmeier, Enoch Watson")

WHOSSTARTING_STALE_HTML = WHOSSTARTING_HTML.replace(
    "Updated Oct 23, 2026", "Updated Sep 30, 2026").replace(
    "Bear Bachmeier is the projected starting quarterback",
    "Treyson Bourguet is the projected starting quarterback")

TWODEEP_HTML = """<html><body>
<h1>2026 College Football Quarterback Depth Charts</h1>
<p>138 teams · Updated Oct 24</p>
<h3>Brigham Young Cougars</h3>
<p>STARTER #47 Bear Bachmeier 95% snaps '26 · SO</p>
<p>2ND #10 Treyson Bourguet</p>
<h3>UCF Knights</h3>
<p>STARTER #7 Alonza Barnett III 88% snaps '26 · RS SR</p>
<p>2ND #11 Kaleb Annett</p>
</body></html>"""

SPORTS247_HTML = """<html><head>
<script type="application/ld+json">
{"datePublished": "2026-10-19T16:49:00Z", "headline": "BYU depth chart"}
</script></head><body>
<p>Offense, QB, 47 Bear Bachmeier, 10 Treyson Bourguet, RB, 12 Preston Rex</p>
</body></html>"""

BEAT_SOCIAL_TEXT = (
    "Last updated: October 22, 2026 — Bear Bachmeier is the starting "
    "quarterback for BYU again this week, per the beat.")

UCF_OURLADS_TEXT = (
    "Updated: 10/23/2026 7:05PM ET\n"
    "1. Barnett III, Alonza — RS SR #7\n"
    "2. Annett, Kaleb — RS SO #11\n")

UCF_WHOSSTARTING_HTML = """<html><body>
<p>Depth Chart · Updated Oct 23, 2026 · Two-deep · Public sources</p>
<p>Alonza Barnett III is the projected starting quarterback for UCF as
of October 23, 2026.</p>
<p>QB: Alonza Barnett III, Kaleb Annett</p>
</body></html>"""


def _clock():
    return CAPTURED


def _fetch_from(contents, failing=()):
    def fetch(url):
        if url in failing:
            raise RuntimeError("boom")
        return contents[url]
    return fetch


def _collect(contents_by_source, failing_sources=(), team_lookups=None):
    contents = {URLS[k]: v for k, v in contents_by_source.items()}
    failing = {URLS[k] for k in failing_sources}
    source_urls = {k: URLS[k] for k in contents_by_source}
    return multi.collect_multi_reads(
        source_urls, team_lookup_by_source=team_lookups or {"TWODEEP": "Brigham Young"},
        fetch_text=_fetch_from(contents, failing), clock=_clock)


def _bundle(reads, team_id=BYU_ID, opponent_id=UCF_ID):
    return multi.build_multi_bundle(
        team_id=team_id, team_name="BYU", event_id=EVENT_ID,
        opponent_id=opponent_id, kickoff_utc=KICKOFF_ISO,
        previous_game_kickoff_utc=PREV_ISO, source_reads=reads)


def _evaluate(bundle, **overrides):
    kwargs = dict(team_id=BYU_ID, kickoff=KICKOFF, event_id=EVENT_ID,
                  home_team_id=UCF_ID, away_team_id=BYU_ID, now=CAPTURED)
    kwargs.update(overrides)
    return multi.evaluate_multi_bundle(bundle, **kwargs)


def _byu_reads(**overrides):
    contents = {"OURLADS": OURLADS_HTML, "WHOSSTARTING": WHOSSTARTING_HTML}
    contents.update(overrides)
    return _collect(contents)


# ---------------------------------------------------------------------------
# Admission rule
# ---------------------------------------------------------------------------
def test_primary_plus_corroborator_admits():
    result = _evaluate(_bundle(_byu_reads()))
    assert result["ok"] is True
    assert result["status"] == "QB_IDENTITY_SATISFIED_FORM2_MULTI_V1"
    assert result["status"] != frozen.STATUS_SATISFIED
    assert result["resolved_qb1_name"] == "Bachmeier, Bear"
    assert result["availability_status"] == frozen.AVAILABILITY_UNVERIFIED
    assert result["injury_points"] == 0.0
    receipt = result["receipt"]
    assert receipt["primary_source"] == "OURLADS"
    assert receipt["corroborating_sources"] == ["WHOSSTARTING"]
    assert receipt["receipt_sha256"]


def test_cfbdepth_primary_plus_twodeep_admits():
    reads = _collect({"CFBDEPTH": CFBDEPTH_TEXT, "TWODEEP": TWODEEP_HTML})
    result = _evaluate(_bundle(reads))
    assert result["ok"] is True
    assert result["receipt"]["primary_source"] == "CFBDEPTH"
    assert result["receipt"]["corroborating_sources"] == ["TWODEEP"]


def test_247_corroborates_primary():
    reads = _collect({"OURLADS": OURLADS_HTML, "SPORTS247": SPORTS247_HTML})
    result = _evaluate(_bundle(reads))
    assert result["ok"] is True
    assert result["receipt"]["corroborating_sources"] == ["SPORTS247"]


def test_conflicting_current_corroborator_refuses():
    reads = _byu_reads(WHOSSTARTING=WHOSSTARTING_CONFLICT_HTML)
    result = _evaluate(_bundle(reads))
    assert result["ok"] is False
    assert result["status"] == "QB_IDENTITY_SOURCE_CONFLICT"


def test_two_primaries_disagree_refuses_conflict():
    reads = _collect({"OURLADS": OURLADS_HTML,
                      "CFBDEPTH": CFBDEPTH_TEXT_OTHER_QB1,
                      "WHOSSTARTING": WHOSSTARTING_HTML})
    result = _evaluate(_bundle(reads))
    assert result["ok"] is False
    assert result["status"] == "QB_IDENTITY_SOURCE_CONFLICT"
    assert result["detail"] == "PRIMARY_SOURCES_DISAGREE"


def test_stale_primary_refuses():
    reads = _byu_reads(OURLADS=OURLADS_STALE_HTML)
    result = _evaluate(_bundle(reads))
    assert result["ok"] is False
    assert result["status"] == "QB_MULTI_PRIMARY_STALE"


def test_single_source_refuses():
    reads = _collect({"OURLADS": OURLADS_HTML})
    result = _evaluate(_bundle(reads))
    assert result["ok"] is False
    assert result["status"] == "QB_MULTI_SINGLE_SOURCE"
    assert result["detail"] == "NO_INDEPENDENT_CORROBORATOR"


def test_stale_corroborator_neither_corroborates_nor_conflicts():
    # The stale Who's Starting page names a DIFFERENT QB1; being
    # stale, it must not create a conflict, and it cannot corroborate.
    reads = _byu_reads(WHOSSTARTING=WHOSSTARTING_STALE_HTML)
    result = _evaluate(_bundle(reads))
    assert result["ok"] is False
    assert result["status"] == "QB_MULTI_SINGLE_SOURCE"
    assert result["detail"] == "CORROBORATOR_STALE_ONLY"


def test_social_only_corroboration_refuses():
    reads = _collect({"OURLADS": OURLADS_HTML,
                      "BEAT_SOCIAL": BEAT_SOCIAL_TEXT})
    result = _evaluate(_bundle(reads))
    assert result["ok"] is False
    assert result["status"] == "QB_MULTI_SINGLE_SOURCE"
    assert result["detail"] == "SOCIAL_CORROBORATION_ONLY"


def test_capture_at_or_after_kickoff_read_is_not_evidence():
    late = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)
    contents = {URLS["OURLADS"]: OURLADS_HTML,
                URLS["WHOSSTARTING"]: WHOSSTARTING_HTML}
    reads = multi.collect_multi_reads(
        {"OURLADS": URLS["OURLADS"], "WHOSSTARTING": URLS["WHOSSTARTING"]},
        fetch_text=_fetch_from(contents), clock=lambda: late)
    result = _evaluate(_bundle(reads), now=late)
    assert result["ok"] is False
    assert result["status"] == "QB_MULTI_EVIDENCE_MISSING"


# ---------------------------------------------------------------------------
# Receipt discipline: unreachable recorded, tamper and binding refusals
# ---------------------------------------------------------------------------
def test_unreachable_source_is_recorded_not_dropped():
    reads = _collect({"OURLADS": OURLADS_HTML,
                      "WHOSSTARTING": WHOSSTARTING_HTML,
                      "TWODEEP": TWODEEP_HTML},
                     failing_sources=("TWODEEP",))
    twodeep = [r for r in reads if r["source"] == "TWODEEP"][0]
    assert twodeep["outcome"] == "SOURCE_UNREACHABLE"
    assert twodeep["reason"].startswith("FETCH_FAILED:RuntimeError")
    assert twodeep["qb1_as_listed"] is None
    # The remaining sources still admit, and the failed read is in
    # the sealed bundle and in the evaluation receipt.
    bundle = _bundle(reads)
    result = _evaluate(bundle)
    assert result["ok"] is True
    recorded = {r["source"]: r for r in result["receipt"]["reads"]}
    assert recorded["TWODEEP"]["outcome"] == "SOURCE_UNREACHABLE"


def test_unparseable_source_is_recorded_unreachable():
    reads = _byu_reads(WHOSSTARTING="<html><body>no chart here</body></html>")
    ws = [r for r in reads if r["source"] == "WHOSSTARTING"][0]
    assert ws["outcome"] == "SOURCE_UNREACHABLE"
    assert ws["reason"] == "PARSE_QB1_NOT_FOUND"
    assert ws["content_sha256"]  # bytes were fetched and hashed
    result = _evaluate(_bundle(reads))
    assert result["ok"] is False
    assert result["status"] == "QB_MULTI_SINGLE_SOURCE"


def test_receipt_tamper_refuses():
    bundle = _bundle(_byu_reads())
    bundle["source_reads"][0]["qb1_as_listed"] = "Else, Someone"
    result = _evaluate(bundle)
    assert result["ok"] is False
    assert result["status"] == "QB_MULTI_RECEIPT_HASH_MISMATCH"


def test_fixture_mismatch_refuses():
    bundle = _bundle(_byu_reads())
    result = _evaluate(bundle, event_id="999999999")
    assert result["ok"] is False
    assert result["status"] == "QB_EVIDENCE_FIXTURE_MISMATCH"


def test_unverifiable_fixture_identity_refuses():
    bundle = _bundle(_byu_reads())
    result = multi.evaluate_multi_bundle(
        bundle, team_id=BYU_ID, kickoff=KICKOFF, now=CAPTURED)
    assert result["ok"] is False
    assert result["status"] == "QB_EVIDENCE_FIXTURE_MISMATCH"
    assert result["detail"] == "FIXTURE_IDENTITY_UNVERIFIABLE"


def test_wrong_evidence_form_refuses():
    bundle = _bundle(_byu_reads())
    bundle["evidence_form"] = "DEPTH_ROSTER_COMPOSITE"
    result = _evaluate(bundle)
    assert result["ok"] is False
    assert result["status"] == "QB_MULTI_EVIDENCE_MISSING"


def test_recorded_qb1_must_match_derivation():
    # Hand-forge a read whose recorded QB1 disagrees with its own
    # captured bytes, then re-seal: the chain verifies, but the
    # evaluator re-derives and invalidates the read.
    reads = _byu_reads()
    forged = [dict(r) for r in reads]
    for read in forged:
        if read["source"] == "WHOSSTARTING":
            read["qb1_as_listed"] = "Treyson Bourguet"
    bundle = _bundle(forged)
    result = _evaluate(bundle)
    assert result["ok"] is False
    assert result["status"] == "QB_MULTI_SINGLE_SOURCE"


# ---------------------------------------------------------------------------
# Parsers / stamps (probe-verified shapes)
# ---------------------------------------------------------------------------
def test_stamp_parsing_shapes():
    _, verbatim, stamp_dt, precision = multi.parse_source_read(
        "WHOSSTARTING", WHOSSTARTING_HTML, captured_at=CAPTURED)
    assert verbatim == "Updated Oct 23, 2026"
    assert precision == "date"
    assert stamp_dt == datetime(2026, 10, 23, 4, 0, tzinfo=timezone.utc)
    qb1, verbatim, stamp_dt, precision = multi.parse_source_read(
        "OURLADS", OURLADS_HTML, captured_at=CAPTURED)
    assert qb1 == "Bachmeier, Bear"
    assert verbatim == "Updated: 10/23/2026 7:02PM ET"
    assert precision == "instant"
    assert stamp_dt == datetime(2026, 10, 23, 23, 2, tzinfo=timezone.utc)


def test_twodeep_team_lookup():
    qb1, verbatim, _, precision = multi.parse_source_read(
        "TWODEEP", TWODEEP_HTML, team_lookup="Brigham Young",
        captured_at=CAPTURED)
    assert qb1 == "Bear Bachmeier"
    assert verbatim == "Updated Oct 24"
    assert precision == "date"
    qb1_ucf, _, _, _ = multi.parse_source_read(
        "TWODEEP", TWODEEP_HTML, team_lookup="UCF", captured_at=CAPTURED)
    assert qb1_ucf == "Alonza Barnett III"


def test_disposition_mirrors_form2_label():
    proceeds, status = multi.multi_disposition()
    assert proceeds is True
    assert status == frozen.AVAILABILITY_UNVERIFIED


# ---------------------------------------------------------------------------
# Archive discipline: frozen writer refuses multi; multi writer works
# ---------------------------------------------------------------------------
def test_frozen_archive_rejects_multi_bundle(tmp_path):
    bundle = _bundle(_byu_reads())
    raw = json.dumps(bundle, sort_keys=True).encode()
    with pytest.raises(archive.EvidenceArchiveError):
        archive.preserve_form2_bundle(
            str(tmp_path), bundle_bytes=raw, team_id=BYU_ID,
            event_id=EVENT_ID, home_team_id=UCF_ID, away_team_id=BYU_ID,
            kickoff=KICKOFF_ISO, previous_game_kickoff=PREV_ISO)


def test_multi_preserve_and_seal_roundtrip(tmp_path):
    root = str(tmp_path)
    byu = multi.preserve_multi_bundle(
        root, bundle=_bundle(_byu_reads()), team_id=BYU_ID,
        event_id=EVENT_ID, home_team_id=UCF_ID, away_team_id=BYU_ID,
        kickoff=KICKOFF_ISO, previous_game_kickoff=PREV_ISO,
        clock=_clock)
    assert byu["identity_evidence"]["status"] == multi.STATUS_SATISFIED_MULTI
    ucf_reads = _collect(
        {"OURLADS": UCF_OURLADS_TEXT, "WHOSSTARTING": UCF_WHOSSTARTING_HTML})
    ucf_bundle = multi.build_multi_bundle(
        team_id=UCF_ID, team_name="UCF", event_id=EVENT_ID,
        opponent_id=BYU_ID, kickoff_utc=KICKOFF_ISO,
        previous_game_kickoff_utc=PREV_ISO, source_reads=ucf_reads)
    ucf = multi.preserve_multi_bundle(
        root, bundle=ucf_bundle, team_id=UCF_ID, event_id=EVENT_ID,
        home_team_id=UCF_ID, away_team_id=BYU_ID, kickoff=KICKOFF_ISO,
        previous_game_kickoff=PREV_ISO, clock=_clock)
    sealed = multi.seal_multi_archive_manifest(
        root, manifest_sha256s=[byu["candidate_manifest_sha256"],
                                ucf["candidate_manifest_sha256"]])
    assert sealed["receipt_count"] == 2
    combined = json.loads(sealed["manifest_bytes"].decode())
    assert combined["schema"] == "CFB_FORM2_MULTI_ARCHIVE_MANIFEST_V1"
    assert (hashlib.sha256(sealed["manifest_bytes"]).hexdigest()
            == sealed["candidate_manifest_sha256"])
    assert {e["team_id"] for e in combined["entries"]} == {BYU_ID, UCF_ID}


def test_multi_preserve_refused_bundle_publishes_no_manifest(tmp_path):
    root = str(tmp_path)
    single = _bundle(_collect({"OURLADS": OURLADS_HTML}))
    with pytest.raises(multi.MultiArchiveError) as excinfo:
        multi.preserve_multi_bundle(
            root, bundle=single, team_id=BYU_ID, event_id=EVENT_ID,
            home_team_id=UCF_ID, away_team_id=BYU_ID, kickoff=KICKOFF_ISO,
            previous_game_kickoff=PREV_ISO, clock=_clock)
    assert "QB_MULTI_SINGLE_SOURCE" in str(excinfo.value)
    files = [p.name for p in tmp_path.iterdir()]
    assert files == [hashlib.sha256(
        multi._canonical_bytes(single)).hexdigest() + ".json"]
