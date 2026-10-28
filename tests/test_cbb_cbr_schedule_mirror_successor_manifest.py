"""Offline guards for the CBR schedule-mirror successor-manifest packet.

These tests never touch the network. They pin the admission invariants:
DESIGN-only status, the six mirror files pinned by the full tuple
(repo + commit SHA + path + git blob SHA + size + SHA-256) at the
hunt-verified values, logs1520.csv admitted for 2014-15 -> 2017-18
ONLY with its later rows explicitly excluded, the merged cbblogs
composites rejected, the provenance chain and authorization posture
stated in the record, precondition (c) recorded satisfiable, the
three-way proof result (27/27 AGREE, championships for the eight
seasons that have one), the crosswalk still OPEN, and the
non-admission of KenPom.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "cbb_cbr_schedule_mirror_successor_20261028"
MANIFEST = json.loads((PACKET / "successor_manifest.json").read_text(encoding="utf-8"))
# Whitespace-normalized: Markdown line wraps must not break phrase checks.
RECORD = re.sub(r"\s+", " ", (PACKET / "ADMISSION_RECORD.md").read_text(encoding="utf-8"))
PROOF = json.loads((PACKET / "three_way_proof_result.json").read_text(encoding="utf-8"))
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COMMIT = "48e22e1c5f39b47425aa64f8fc98112974b5a8c0"

# The hunt-verified pin values (source hunt, re-verified 6/6 by this
# admission's own pulls — see ADMISSION_RECORD.md section 4).
EXPECTED_PINS = {
    "logs1520.csv": ("97bffa2570c18163488bde0306acfa737210befe", 12681623,
                     "17d2e61d32880005238c55bdd6dfcf3807950195844f25bb094d2872d302b3f9"),
    "logs19.csv": ("ba46cdd5c3c38ca793f8413dc6d6f387128af8ca", 2914156,
                   "d5035f37789d4a0b556cdb6824efa344db296ebc0e1248936ebf5cc5010ca4ff"),
    "logs20.csv": ("66bf0d6bf2dfdf71117a793d52bcb8f2649e7a84", 2770086,
                   "42ae4ab716aff6e04279c4b6f9ba9fba6fc681fa65694f6c8b1ce7868bfba4ff"),
    "logs21.csv": ("38adba0fa6980b03c46600d8a88d844357a0e691", 2031033,
                   "5cf27d1db16aa35d5ab42e268ebe3c6ec3610ae8970fa42e7d096c24724321d0"),
    "logs22.csv": ("200094f671d73a4d393803cd2fd6147018ecdc66", 2854222,
                   "1117fe9f97989e9c7012edc9083bdfa1746f94f63f29437e1c095768010c8108"),
    "logs23.csv": ("a3e25cecb6726b5c9422f7b35ccef808eb2cb682", 3008747,
                   "eb1d2cac051d21b52068441313ddc6506135c6086e57079b95132f2b7f141aa6"),
}


def test_manifest_is_design_only():
    assert MANIFEST["design_only"] is True
    assert MANIFEST["validation_credit"] is False
    assert MANIFEST["forward_clock_credit"] is False
    assert MANIFEST["play_eligible"] is False
    assert MANIFEST["sport"] == "CBB"
    assert MANIFEST["source_id"] == "CBR_SCHEDULE_MIRROR_MATTWAITE_V1"


def test_exactly_the_six_hunt_files_are_pinned():
    names = {s["file_name"] for s in MANIFEST["samples"]}
    assert names == set(EXPECTED_PINS)
    assert len(MANIFEST["samples"]) == 6


def test_every_sample_carries_the_full_tuple_at_the_hunt_values():
    for sample in MANIFEST["samples"]:
        blob, size, sha = EXPECTED_PINS[sample["file_name"]]
        assert sample["repo"] == "mattwaite/mattwaite.github.io"
        assert sample["commit_sha"] == COMMIT
        assert GIT_SHA_RE.match(sample["commit_sha"])
        assert sample["path"] == f"sportsdatafiles/{sample['file_name']}"
        assert sample["git_blob_sha"] == blob
        assert GIT_SHA_RE.match(sample["git_blob_sha"])
        assert sample["bytes"] == size
        assert sample["sha256"] == sha
        assert SHA256_RE.match(sample["sha256"])
        assert sample["commit_sha"] in sample["url"]
        assert sample["path"] in sample["url"]
        assert sample["pin_status"] == "PINNED"


def test_logs1520_scope_is_restricted_and_exclusions_explicit():
    sample = next(s for s in MANIFEST["samples"]
                  if s["file_name"] == "logs1520.csv")
    assert sample["admitted_seasons"] == [2015, 2016, 2017, 2018]
    rows = sample["team_rows_by_season"]
    assert [rows[k]["team_rows"] for k in
            ("2014-2015", "2015-2016", "2016-2017", "2017-2018")] == \
        [11431, 11468, 11511, 11544]
    excluded = sample["excluded_rows_in_file"]
    assert excluded["2018-2019"]["team_rows"] == 11566
    assert excluded["2018-2019"]["date_max"] == "2019-03-24"
    assert excluded["2019-2020"]["team_rows"] == 11097
    assert "off-pin" in excluded["exclusion_reason"]


def test_per_season_files_cover_the_remaining_seasons():
    admitted = {}
    for sample in MANIFEST["samples"]:
        for season in sample["admitted_seasons"]:
            admitted[season] = sample["file_name"]
    assert admitted == {2015: "logs1520.csv", 2016: "logs1520.csv",
                        2017: "logs1520.csv", 2018: "logs1520.csv",
                        2019: "logs19.csv", 2020: "logs20.csv",
                        2021: "logs21.csv", 2022: "logs22.csv",
                        2023: "logs23.csv"}
    by_file = {s["file_name"]: s for s in MANIFEST["samples"]}
    assert by_file["logs20.csv"]["team_rows_by_season"]["2019-2020"]["date_max"] == "2020-03-11"
    assert by_file["logs21.csv"]["team_rows_by_season"]["2020-2021"]["team_rows"] == 8229
    assert by_file["logs23.csv"]["team_rows_by_season"]["2022-2023"]["team_rows"] == 11995


def test_merged_cbblogs_composites_are_rejected():
    rejected = {r["file_name"]: r for r in MANIFEST["rejected_sources"]}
    merged = next(v for k, v in rejected.items() if "cbblogs" in k)
    assert merged["status"] == "NOT_ADMITTED"
    direct = next(v for k, v in rejected.items() if "sports-reference" in k)
    assert direct["status"] == "REFUSED_HTTP_403_NOT_PINNED"


def test_precondition_c_is_recorded_satisfiable():
    sat = MANIFEST["satisfies"]
    assert sat["pr_2866_precondition_c_cbr_leg"].startswith("YES")
    assert "CBR_SCHEDULE_MIRROR_MATTWAITE_V1" in \
        sat["pr_2866_precondition_c_cbr_leg"]
    assert "48,155 fixtures" in sat["three_way_proof"]


def test_proof_result_is_27_of_27_with_championships():
    assert PROOF["summary"] == {"fixtures_sampled": 27, "agree": 27,
                                "schedule_discrepancy": 0}
    champs = [r for r in PROOF["sample"] if r["slot"] == "CHAMPIONSHIP"]
    assert len(champs) == 8
    assert all(r["verdict"] == "AGREE" for r in champs)
    covid = [r for r in PROOF["sample"]
             if "NO_CHAMPIONSHIP_COVID" in r["slot"]]
    assert len(covid) == 1 and covid[0]["season"] == "2019-2020"
    seasons = {r["season"] for r in PROOF["sample"]}
    assert len(seasons) == 9
    for stats in PROOF["derivation_by_season"].values():
        assert stats["mirror_inconsistent_pairs"] == 0
        assert stats["fixtures_derived"] > 3000
    assert len(PROOF["normalization_overrides"]) >= 40


def test_crosswalk_remains_open_and_not_admitted():
    assert MANIFEST["crosswalk_status"] == "OPEN_NOT_ADMITTED"
    lowered = RECORD.lower()
    assert "open — not admitted" in lowered
    assert "name-only joins are refused" in lowered


def test_record_states_the_binding_rules():
    lowered = RECORD.lower()
    assert "cbr → scraper → committed mirror" in lowered
    assert "no license" in lowered
    assert "no sports reference authorization" in lowered
    assert "factual game data" in lowered
    assert "internal verification only" in lowered
    assert "never redistributed" in lowered
    assert "commit-anchored" in lowered
    assert "source_changed_after_snapshot" in lowered
    assert "admitted for 2014-15 → 2017-18 only" in lowered
    assert "not admitted (documented rejection)" in lowered
    assert "27/27 agree" in lowered
    assert "satisfiable by this" in lowered
    assert "may run exactly as designed" in lowered
    assert "does **not** run" in RECORD
    assert "illinois college" in lowered
    assert "kenpom is not admitted" in lowered
    assert "design only" in lowered
    assert "no request to sports-reference.com was" in lowered


def test_scripts_compile_and_use_manifest():
    for name in ("pull_cbr_schedule_mirror.py", "derive_three_way_proof.py"):
        script = (PACKET / name).read_text(encoding="utf-8")
        assert "successor_manifest.json" in script
        compile(script, name, "exec")
    pull = (PACKET / "pull_cbr_schedule_mirror.py").read_text(encoding="utf-8")
    assert "SOURCE_CHANGED_AFTER_SNAPSHOT" in pull
    assert "sports-reference.com was made" not in pull  # no direct CBR pull
    derive = (PACKET / "derive_three_way_proof.py").read_text(encoding="utf-8")
    assert "SCHEDULE_DISCREPANCY" in derive
    assert "NORMALIZATION_OVERRIDES" in derive
