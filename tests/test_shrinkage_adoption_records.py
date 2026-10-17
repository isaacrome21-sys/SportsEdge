"""Verification for the published shrinkage adoption records package.

Package under test: ``research/shrinkage_adoption_records/`` — the
identifiable records for the 10/3/1 shrinkage challengers (batter x10,
pitcher x3, CFB QB x1) adopted by owner ruling (Oct 15, 2026) as
RESEARCH challengers only, with adoption/promotion HELD pending owner
certification from these records.

This test makes the package's claims executable rather than prose:

* every preregistration hash in ``specs/`` is recomputed from the
  shipped file bytes and compared against ``specs/SPEC_HASHES.txt``;
* the batter family routes through its amendment chain instead (D1):
  the shipped lock token is a defective 55-character string, and the
  true hash in ``AMENDMENT_BATTER_HASH.md`` must govern;
* every number ``RECORDS.md`` claims for all 14 challengers (arm
  scores, paired deltas and CIs vs FROZEN/B1/B2, sample sizes, gate
  verdicts) is cross-checked against the ``results/`` JSONs;
* the D2 reconciliation state is asserted (2.1705 stands; 2.0267 is
  unattributable);
* the label discipline is asserted (nothing in the package is a
  market verdict, production model, or promotion input).

Pure stdlib; no fixtures beyond the package itself.
"""

import hashlib
import json
import py_compile
import re
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "research" / "shrinkage_adoption_records"
SPECS = PKG / "specs"
RESULTS = PKG / "results"
SCRIPTS = PKG / "scripts"

TOL4 = 6e-5   # RECORDS.md quotes batter/pitcher numbers at 4 dp
TOL3 = 6e-4   # RECORDS.md quotes CFB numbers at 3 dp

BATTER_RESULTS = RESULTS / "challenger_batter_props_results.json"
PITCHER_RESULTS = RESULTS / "challenger_pitcher_undercard_results.json"
CFB_RESULTS = RESULTS / "challenger_cfb_qb_results.json"

# RECORDS.md summary-table display name -> (family, results-JSON key)
TABLE_MAP = {
    "Batter Hits": ("batter", "BATTER_HITS"),
    "Batter Total Bases": ("batter", "BATTER_TOTAL_BASES"),
    "Batter Runs": ("batter", "BATTER_RUNS"),
    "Batter Hits+Runs+RBIs": ("batter", "HITS_RUNS_RBIS"),
    "Batter Singles": ("batter", "BATTER_SINGLES"),
    "Batter Walks": ("batter", "BATTER_WALKS"),
    "Batter Home Runs": ("batter", "BATTER_HOME_RUNS"),
    "Batter Extra-Base Hits": ("batter", "BATTER_EXTRA_BASE_HITS"),
    "Batter Strikeouts": ("batter", "BATTER_STRIKEOUTS"),
    "Batter Runs+RBIs": ("batter", "BATTER_RUNS_RBIS"),
    "Pitcher Outs": ("pitcher", "OUTS"),
    "Pitcher Hits Allowed": ("pitcher", "HITS_ALLOWED"),
    "Pitcher Walks (BB)": ("pitcher", "BB"),
    "CFB QB passing yards": ("cfb", None),
}

# RECORDS.md numbered section -> (family, results-JSON key), in order
SECTION_MAP = {
    1: ("batter", "BATTER_HITS"),
    2: ("batter", "BATTER_TOTAL_BASES"),
    3: ("batter", "BATTER_RUNS"),
    4: ("batter", "HITS_RUNS_RBIS"),
    5: ("batter", "BATTER_SINGLES"),
    6: ("batter", "BATTER_WALKS"),
    7: ("batter", "BATTER_HOME_RUNS"),
    8: ("batter", "BATTER_EXTRA_BASE_HITS"),
    9: ("batter", "BATTER_STRIKEOUTS"),
    10: ("batter", "BATTER_RUNS_RBIS"),
    11: ("pitcher", "OUTS"),
    12: ("pitcher", "HITS_ALLOWED"),
    13: ("pitcher", "BB"),
    14: ("cfb", None),
}

EXPECTED_FILES = [
    "README.md",
    "RECORDS.md",
    "REPORT.md",
    "AMENDMENT_BATTER_HASH.md",
    "D2_RECONCILIATION.md",
    "specs/SPEC_HASHES.txt",
    "specs/PREREG_BATTER_PROPS.md",
    "specs/PREREG_PITCHER_UNDERCARD.md",
    "specs/PREREG_CFB_QB.md",
    "specs/PREREG_F5.md",
    "specs/PREREG_FIRST_INNING.md",
    "specs/AMENDMENT_BATTER_PROPS_SPEC_HASH_RECORD.md",
    "specs/AMENDMENT_F5_STRENGTH_MECHANISM.md",
    "results/challenger_batter_props_results.json",
    "results/challenger_batter_props_parity.json",
    "results/challenger_batter_props_verification.json",
    "results/challenger_pitcher_undercard_results.json",
    "results/challenger_pitcher_undercard_verification.json",
    "results/challenger_cfb_qb_results.json",
    "results/challenger_boxscore_fetch_summary.json",
    "scripts/eval_challenger_batter_props.py",
    "scripts/eval_challenger_pitcher_undercard.py",
    "scripts/eval_challenger_cfb_qb.py",
    "scripts/acquire_2026_statsapi.py",
    "scripts/acquire_model_fix.py",
    "scripts/derive_fbs_teams_2024.py",
]


def _norm(text):
    """RECORDS.md uses U+2212 minus signs; normalize for parsing."""
    return text.replace("\u2212", "-")


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def records_text():
    return _norm((PKG / "RECORDS.md").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def batter():
    return _load_json(BATTER_RESULTS)


@pytest.fixture(scope="module")
def pitcher():
    return _load_json(PITCHER_RESULTS)


@pytest.fixture(scope="module")
def cfb():
    return _load_json(CFB_RESULTS)


@pytest.fixture(scope="module")
def spec_hash_tokens():
    tokens = {}
    for line in (SPECS / "SPEC_HASHES.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\S+)\s+(PREREG_\w+\.md)\s*$", line)
        if m:
            tokens[m.group(2)] = m.group(1)
    return tokens


# ---------------------------------------------------------------------------
# Package completeness
# ---------------------------------------------------------------------------

def test_package_files_present():
    missing = [rel for rel in EXPECTED_FILES if not (PKG / rel).is_file()]
    assert missing == [], f"package files missing: {missing}"


def test_results_jsons_parse_and_scripts_compile():
    for rel in EXPECTED_FILES:
        if rel.endswith(".json"):
            _load_json(PKG / rel)  # raises on malformed JSON
    with tempfile.TemporaryDirectory() as tmp:
        for rel in EXPECTED_FILES:
            if rel.startswith("scripts/") and rel.endswith(".py"):
                py_compile.compile(str(PKG / rel),
                                   cfile=str(Path(tmp) / "out.pyc"),
                                   doraise=True)


# ---------------------------------------------------------------------------
# Preregistration hashes and the D1 amendment chain
# ---------------------------------------------------------------------------

def test_all_five_preregs_locked_in_spec_hashes(spec_hash_tokens):
    assert set(spec_hash_tokens) == {
        "PREREG_BATTER_PROPS.md",
        "PREREG_PITCHER_UNDERCARD.md",
        "PREREG_CFB_QB.md",
        "PREREG_F5.md",
        "PREREG_FIRST_INNING.md",
    }


def test_non_batter_spec_hashes_verify_directly(spec_hash_tokens):
    for name, token in spec_hash_tokens.items():
        if name == "PREREG_BATTER_PROPS.md":
            continue
        assert len(token) == 64, f"{name}: token is not a full digest"
        assert token == _sha256(SPECS / name), f"{name}: token != file hash"


def test_batter_amendment_chain(spec_hash_tokens, batter):
    token = spec_hash_tokens["PREREG_BATTER_PROPS.md"]
    true_hash = _sha256(SPECS / "PREREG_BATTER_PROPS.md")

    # The lock token is defective exactly as documented: 55 chars, not
    # the file's hash, and related to it by a single 9-char deletion
    # at offset 49 (the deleted segment is d8e08e1d1).
    assert len(token) == 55
    assert token != true_hash
    assert token == true_hash[:49] + true_hash[58:]
    assert true_hash[49:58] == "d8e08e1d1"

    # The formal amendment in this package names the same true hash
    # and the same defective token, and governs verification.
    amendment = (PKG / "AMENDMENT_BATTER_HASH.md").read_text(encoding="utf-8")
    m = re.search(
        r"True SHA-256 of specs/PREREG_BATTER_PROPS\.md "
        r"\(recomputed [^)]*\): `([0-9a-f]{64})`", amendment)
    assert m, "AMENDMENT_BATTER_HASH.md does not state the true hash"
    assert m.group(1) == true_hash
    m = re.search(
        r"Recorded token in specs/SPEC_HASHES\.txt "
        r"\(defective, 55 characters\): `([0-9a-f]{55})`", amendment)
    assert m, "AMENDMENT_BATTER_HASH.md does not state the defective token"
    assert m.group(1) == token

    # The lane's own pre-scoring amendment carries both strings too.
    lane_amendment = (SPECS / "AMENDMENT_BATTER_PROPS_SPEC_HASH_RECORD.md"
                      ).read_text(encoding="utf-8")
    assert true_hash in lane_amendment
    assert token in lane_amendment

    # The results JSON records the chain explicitly and locked on the
    # true hash.
    prereg = batter["prereg"]
    assert prereg["sha256"] == true_hash
    record = prereg["spec_hashes_record"]
    assert record["recorded_token"] == token
    assert record["recorded_token_length"] == 55
    assert record["record_matches_true_sha256"] is False
    assert (SPECS / Path(record["amendment"]).name).is_file()


def test_pitcher_and_cfb_prereg_hashes_match_results_jsons(
        spec_hash_tokens, pitcher, cfb):
    pitcher_hash = _sha256(SPECS / "PREREG_PITCHER_UNDERCARD.md")
    assert pitcher["prereg"]["sha256"] == pitcher_hash
    assert spec_hash_tokens["PREREG_PITCHER_UNDERCARD.md"] == pitcher_hash

    cfb_hash = _sha256(SPECS / "PREREG_CFB_QB.md")
    assert cfb["prereg"]["sha256"] == cfb_hash
    assert cfb["prereg"]["locked_sha256_in_SPEC_HASHES"] == cfb_hash
    assert spec_hash_tokens["PREREG_CFB_QB.md"] == cfb_hash


# ---------------------------------------------------------------------------
# RECORDS.md claims vs results JSONs — the summary table
# ---------------------------------------------------------------------------

def _parse_summary_table(records_text):
    rows = {}
    for line in records_text.splitlines():
        m = re.match(
            r"^\| (\d+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| "
            r"([^|]+) \|$", line)
        if not m:
            continue
        num, name, _form, split_cell, delta_cell, gate_cell = m.groups()
        name = name.strip()
        n_match = re.search(r"n=([\d,]+)", split_cell)
        d_match = re.search(
            r"(Brier|CRPS)(?: CI)?(?: (-?[\d.]+))? "
            r"\[(-?[\d.]+), (-?[\d.]+)\]", delta_cell)
        assert n_match and d_match, f"table row {num} ({name}) unparsable"
        rows[name] = {
            "num": int(num),
            "n": int(n_match.group(1).replace(",", "")),
            "metric": d_match.group(1),
            "point": (float(d_match.group(2))
                      if d_match.group(2) is not None else None),
            "ci": (float(d_match.group(3)), float(d_match.group(4))),
            "gate": gate_cell.strip(),
        }
    return rows


def _json_delta(family, key, data, metric, leg):
    """Return (point, ci_lo, ci_hi, entirely_below_zero) for one gate leg."""
    if family == "batter":
        entry = data["stats"][key]
        if entry["form"] == "OU_0.5":
            d = entry["paired_deltas"][f"d{metric}_ch_vs_{leg}"]
        else:
            assert metric == "CRPS"
            d = entry["paired_deltas"][f"dCRPS_ch_vs_{leg}"]
        return d["delta"], d["ci95"][0], d["ci95"][1], d["entirely_below_zero"]
    if family == "pitcher":
        d = data["markets"][key][f"delta_crps_challenger_vs_{leg}"]
        return (d["mean_delta"], d["ci95_lo"], d["ci95_hi"],
                d["entirely_below_zero"])
    raise AssertionError(family)


def _json_n(family, key, data):
    if family == "batter":
        return data["stats"][key]["metrics"]["n"]
    if family == "pitcher":
        return data["markets"][key]["n"]
    raise AssertionError(family)


def _json_verdict(family, key, data):
    if family == "batter":
        return data["stats"][key]["verdict"]
    if family == "pitcher":
        return data["markets"][key]["verdict"]
    raise AssertionError(family)


def test_summary_table_covers_exactly_the_14(records_text):
    rows = _parse_summary_table(records_text)
    assert set(rows) == set(TABLE_MAP), (
        f"table/ map mismatch: {set(rows) ^ set(TABLE_MAP)}")
    assert sorted(r["num"] for r in rows.values()) == list(range(1, 15))


def test_summary_table_binding_leg_matches_json(records_text, batter,
                                                pitcher, cfb):
    rows = _parse_summary_table(records_text)
    data = {"batter": batter, "pitcher": pitcher}
    for name, (family, key) in TABLE_MAP.items():
        row = rows[name]
        assert row["gate"].startswith("PASS"), f"{name}: table gate"
        if family == "cfb":
            assert row["n"] == cfb["population"]["scored"] == 417
            lo, hi = cfb["ci_challenger_minus_b2"]
            assert abs(row["ci"][0] - lo) <= TOL3, f"{name}: CI lo vs B2"
            assert abs(row["ci"][1] - hi) <= TOL3, f"{name}: CI hi vs B2"
            continue
        assert row["n"] == _json_n(family, key, data[family]), f"{name}: n"
        point, lo, hi, below = _json_delta(
            family, key, data[family], row["metric"], "B2")
        assert below is True, f"{name}: B2 leg not entirely below zero"
        if row["point"] is not None:
            assert abs(row["point"] - point) <= TOL4, f"{name}: delta vs B2"
        assert abs(row["ci"][0] - lo) <= TOL4, f"{name}: CI lo vs B2"
        assert abs(row["ci"][1] - hi) <= TOL4, f"{name}: CI hi vs B2"


def test_all_gate_legs_entirely_below_zero_and_verdicts(batter, pitcher, cfb):
    # Batter: exactly the 10 mapped stats are ADOPT-CANDIDATE, and every
    # preregistered gate leg (both metrics for binary stats, CRPS for
    # ladder stats, vs FROZEN/B1/B2) is entirely below zero in the JSON.
    adopt = {k for k, v in batter["stats"].items()
             if v["verdict"] == "ADOPT-CANDIDATE"}
    assert adopt == {k for f, k in TABLE_MAP.values() if f == "batter"}
    for key in adopt:
        entry = batter["stats"][key]
        metrics = ["Brier", "LogLoss"] if entry["form"] == "OU_0.5" else ["CRPS"]
        for metric in metrics:
            for leg in ("FROZEN", "B1", "B2"):
                *_, below = _json_delta("batter", key, batter, metric, leg)
                assert below is True, f"batter {key} {metric} vs {leg}"
    # The three evaluated non-candidates stay KEEP FROZEN.
    for key in ("BATTER_RBIS", "BATTER_DOUBLES", "BATTER_TRIPLES"):
        assert batter["stats"][key]["verdict"] == "KEEP FROZEN", key

    # Pitcher: exactly OUTS / HITS_ALLOWED / BB are ADOPT-CANDIDATE with
    # all three CRPS legs below zero; Earned Runs stays KEEP FROZEN
    # precisely because its B2 leg is not entirely below zero.
    adopt_p = {k for k, v in pitcher["markets"].items()
               if v["verdict"] == "ADOPT-CANDIDATE"}
    assert adopt_p == {"OUTS", "HITS_ALLOWED", "BB"}
    for key in adopt_p:
        for leg in ("FROZEN", "B1", "B2"):
            *_, below = _json_delta("pitcher", key, pitcher, "CRPS", leg)
            assert below is True, f"pitcher {key} vs {leg}"
    er = pitcher["markets"]["ER"]
    assert er["verdict"] == "KEEP FROZEN"
    assert er["delta_crps_challenger_vs_B2"]["entirely_below_zero"] is False

    # CFB: gate verdict plus all three paired CIs entirely below zero.
    assert cfb["gate_verdict"] == "ADOPT-CANDIDATE"
    for leg in ("frozen", "b1", "b2"):
        lo, hi = cfb[f"ci_challenger_minus_{leg}"]
        assert hi < 0, f"cfb CI vs {leg} not entirely below zero"


def test_d3_total_bases_is_hits_duplicate_form(batter):
    # D3: at the 0.5 line Total Bases is the same event as Hits; the
    # results JSON carries byte-identical metrics and deltas.
    hits = batter["stats"]["BATTER_HITS"]
    tb = batter["stats"]["BATTER_TOTAL_BASES"]
    assert tb["metrics"] == hits["metrics"]
    assert tb["paired_deltas"] == hits["paired_deltas"]
    assert tb["verdict"] == hits["verdict"] == "ADOPT-CANDIDATE"


# ---------------------------------------------------------------------------
# RECORDS.md claims vs results JSONs — the numbered per-challenger sections
# ---------------------------------------------------------------------------

def _split_sections(records_text):
    # First occurrence of each number wins: the later "## 5." / "## 6."
    # top-level headings must not shadow sections 5 and 6.
    heads = []
    seen = set()
    for m in re.finditer(r"^#{2,3} (\d+)\. ", records_text, re.M):
        num = int(m.group(1))
        if num not in seen:
            seen.add(num)
            heads.append((m.start(), num))
    tail = records_text.find("\n## 5. Discrepancies")
    sections = {}
    for i, (start, num) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else tail
        sections[num] = records_text[start:end]
    return sections


def _arm_scores(family, key, data):
    """(FROZEN, CHALLENGER, B1, B2) headline scores from a results JSON."""
    if family == "batter":
        metrics = data["stats"][key]["metrics"]
        if data["stats"][key]["form"] == "OU_0.5":
            return (metrics["brier_eng"], metrics["brier_ch"],
                    metrics["brier_b1"], metrics["brier_b2"])
        return (metrics["crps_eng"], metrics["crps_ch"],
                metrics["crps_b1"], metrics["crps_b2"])
    if family == "pitcher":
        mkt = data["markets"][key]
        return (mkt["crps_engine_mean"], mkt["crps_challenger_mean"],
                mkt["crps_b1_mean"], mkt["crps_b2_mean"])
    raise AssertionError(family)


def _parse_section_delta_chains(section):
    """Parse 'dX vs LEG p [lo, hi]; vs LEG ...' chains in one section.

    Returns {(metric, leg): (point, lo, hi)} with metric in
    {Brier, LogLoss, CRPS} (a bare 'd' label is the CRPS chain).
    """
    token_re = re.compile(
        r"(ΔBrier|ΔLogLoss|ΔCRPS|Δ)\s|"
        r"vs (FROZEN|B1|B2)\s+(-?[\d.]+)\s*\[(-?[\d.]+),\s*(-?[\d.]+)\]")
    chains = {}
    metric = None
    for m in token_re.finditer(section):
        if m.group(1) is not None:
            metric = {"ΔBrier": "Brier", "ΔLogLoss": "LogLoss",
                      "ΔCRPS": "CRPS", "Δ": "CRPS"}[m.group(1)]
        else:
            assert metric is not None, "delta leg with no metric label"
            chains[(metric, m.group(2))] = (
                float(m.group(3)), float(m.group(4)), float(m.group(5)))
    return chains


def test_sections_scores_and_deltas_match_json(records_text, batter, pitcher):
    sections = _split_sections(records_text)
    assert set(sections) == set(SECTION_MAP)
    data = {"batter": batter, "pitcher": pitcher}
    for num, (family, key) in SECTION_MAP.items():
        if family == "cfb":
            continue
        section = sections[num]
        if num == 2:
            # Section 2 (Total Bases) states no numbers of its own: it
            # defers to Hits by the D3 identity, which is asserted
            # against the JSON in test_d3_total_bases_is_hits_duplicate_form.
            assert "byte-identical to Hits" in section
            continue
        m = re.search(
            r"Scores (\d+\.\d+) / (\d+\.\d+) / (\d+\.\d+) / (\d+\.\d+)",
            section)
        assert m, f"section {num}: no Scores line"
        claimed = tuple(float(x) for x in m.groups())
        actual = _arm_scores(family, key, data[family])
        for c, a in zip(claimed, actual):
            assert abs(c - a) <= TOL4, f"section {num} ({key}): scores"

        chains = _parse_section_delta_chains(section)
        expected_metrics = (
            ["Brier", "LogLoss"]
            if family == "batter"
            and batter["stats"][key]["form"] == "OU_0.5" else ["CRPS"])
        for metric in expected_metrics:
            for leg in ("FROZEN", "B1", "B2"):
                assert (metric, leg) in chains, (
                    f"section {num} ({key}): missing {metric} vs {leg}")
                c_point, c_lo, c_hi = chains[(metric, leg)]
                point, lo, hi, _ = _json_delta(
                    family, key, data[family], metric, leg)
                assert abs(c_point - point) <= TOL4, (
                    f"section {num} ({key}): {metric} vs {leg} point")
                assert abs(c_lo - lo) <= TOL4, (
                    f"section {num} ({key}): {metric} vs {leg} CI lo")
                assert abs(c_hi - hi) <= TOL4, (
                    f"section {num} ({key}): {metric} vs {leg} CI hi")


def test_cfb_section_matches_json(records_text, cfb):
    section = _split_sections(records_text)[14]
    m = re.search(
        r"FROZEN (\d+\.\d+)\s*/\s*CHALLENGER (\d+\.\d+)\s*/\s*"
        r"B1 (\d+\.\d+)\s*/\s*B2 (\d+\.\d+)", section)
    assert m, "CFB section: no headline CRPS line"
    claimed = tuple(float(x) for x in m.groups())
    crps = cfb["crps"]
    actual = (crps["frozen"], crps["challenger"], crps["b1"], crps["b2"])
    for c, a in zip(claimed, actual):
        assert abs(c - a) <= TOL3, "CFB headline CRPS"

    # Point deltas in RECORDS.md are computed from the recorded arm
    # means (stated in the record); CIs are the JSON's paired CIs.
    for leg_name, leg_key in (("FROZEN", "frozen"), ("B1", "b1"),
                              ("B2", "b2")):
        m = re.search(
            rf"vs {leg_name} (-?[\d.]+),\s*CI \[(-?[\d.]+), (-?[\d.]+)\]",
            section)
        assert m, f"CFB section: no delta line vs {leg_name}"
        c_point, c_lo, c_hi = (float(x) for x in m.groups())
        assert abs(c_point - (crps["challenger"] - crps[leg_key])) <= TOL3, (
            f"CFB point delta vs {leg_name}")
        lo, hi = cfb[f"ci_challenger_minus_{leg_key}"]
        assert abs(c_lo - lo) <= TOL3, f"CFB CI lo vs {leg_name}"
        assert abs(c_hi - hi) <= TOL3, f"CFB CI hi vs {leg_name}"

    # D4 population caveat is part of the record and matches the JSON.
    pop = cfb["population"]
    assert pop["candidates"] == 1695 and pop["scored"] == 417
    assert pop["exclusions"]["ROLE_NOT_MATERIALIZED"] == 1191
    assert "417 scored of 1,695" in section


# ---------------------------------------------------------------------------
# D2 resolution state
# ---------------------------------------------------------------------------

def test_d2_resolved_in_favor_of_recorded_values(records_text, pitcher):
    d2_start = records_text.find("- **D2")
    assert d2_start != -1
    d2_block = records_text[d2_start:d2_start + 4000]
    assert "RESOLVED" in d2_block
    assert "withdrawn-by-unverifiability" in d2_block

    reconciliation = (PKG / "D2_RECONCILIATION.md").read_text(
        encoding="utf-8")
    assert "2.1705" in reconciliation
    assert "unattributable" in reconciliation

    # The value the verdict stands on is the value in the JSON.
    b2_outs = pitcher["markets"]["OUTS"]["crps_b2_mean"]
    assert abs(b2_outs - 2.1705) <= TOL4


# ---------------------------------------------------------------------------
# Label discipline — research only, never a market verdict
# ---------------------------------------------------------------------------

def test_label_discipline(records_text, batter, pitcher, cfb):
    for data in (batter, pitcher, cfb):
        # The CFB JSON's label phrases it in lowercase; the claim being
        # verified is that the label carries the statement at all.
        assert "not a market verdict" in data["label"].lower()
    assert ("None of the 14 evaluations was ever scored against market"
            in records_text)
    readme = " ".join((PKG / "README.md").read_text(encoding="utf-8").split())
    for phrase in ("RESEARCH challengers", "NOT production",
                   "NOT market-scored", "HELD"):
        assert phrase in readme, f"README missing state phrase: {phrase!r}"
