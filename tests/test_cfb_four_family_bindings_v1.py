"""Synthetic-fixture battery for the CFB four-family data bindings.

Every fixture in this file is synthetic and generated in-memory. The
battery proves the bindings machinery of
``sportsedge/research/cfb_four_family_bindings_v1.py``:

* the frozen-engine producer reproduces the production ``calculate()``
  Lane A probabilities on synthetic rows (and the production
  team-total construction), in the injury-neutral configuration;
* bind-time refusals fire (HFA divergence, incomplete engine
  identity) and the harness neutrality guard bites through the
  producer on every call;
* snapshots are content-addressed: tampered payloads are refused,
  round-trips are exact, and the directory applies season-effective
  FBS overrides;
* the lines binding cannot emit an unlabeled market record, assigns
  moneyline sides by identity with a spread cross-check, quarantines
  contradictory or uncheckable moneylines, and flags records
  timestamped after their fixture's kickoff;
* the dry-run manifest enumerates a ruled configuration's population
  and coverage with run state NOT_RUN and no probabilities.

No real game, line, or CFBD record is touched, and nothing here
authorizes or performs an evaluation run.
"""

from __future__ import annotations

import ast
import csv
import gzip
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsedge.research import cfb_four_family_bindings_v1 as bindings
from sportsedge.research import cfb_four_family_evaluation_v1 as harness
from sportsedge.research.cfb_four_family_bindings_v1 import (
    BindingError,
    DirectorySnapshot,
    EngineIdentity,
    FrozenEngineProducer,
)
from sportsedge.research.cfb_four_family_evaluation_v1 import (
    CandidateGameInput,
    EvalConfig,
    GameLines,
    GameRecord,
    NonNeutralInputError,
    build_candidate_input,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _engine_identity() -> EngineIdentity:
    files = {
        rel: (REPO_ROOT / rel).read_bytes() for rel in bindings.ENGINE_FILES
    }
    return EngineIdentity.from_file_bytes(files, source_commit="b68114e0f")


def _producer() -> FrozenEngineProducer:
    return FrozenEngineProducer.bind(identity=_engine_identity(), config=EvalConfig())


def _game(game_id="SYN1", season=2025, home="100", away="200") -> GameRecord:
    return GameRecord(
        game_id=game_id,
        season=season,
        week=1,
        kickoff_utc=datetime(2025, 9, 6, 17, 0, tzinfo=UTC),
        home_team_id=home,
        away_team_id=away,
        home_fbs=True,
        away_fbs=True,
        home_score=None,
        away_score=None,
    )


# ----------------------------------------------------------------------
# Frozen-engine producer
# ----------------------------------------------------------------------


def test_producer_parity_with_calculate_lane_a():
    from artifacts import free_models as engine

    producer = _producer()
    now = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    kickoff = now + timedelta(days=2)
    context = {"home_rating": 0.9, "away_rating": -0.4}
    base_row = {
        "sport": "CFB",
        "away": "Alpha",
        "home": "Beta",
        "kickoff": kickoff.isoformat(),
        "quote_captured_at": now.isoformat(),
        "odds": -110,
        "context": dict(context),
    }
    inp = build_candidate_input(
        _game(), home_rating=0.9, away_rating=-0.4, home_advantage_points=2.5
    )
    lines = GameLines(
        spread_home=-3.5, total=51.5, home_moneyline=-160, away_moneyline=140
    )
    probs = producer.family_probabilities(inp, lines)
    checks = [
        ("ML", "HOME", None, probs.moneyline_home_win),
        ("SPREAD", "HOME", -3.5, probs.spread_home_cover),
        ("TOTAL", "OVER", 51.5, probs.total_over),
    ]
    for market, side, line, adapter_p in checks:
        row = dict(base_row, market=market, side=side)
        if line is not None:
            row["line"] = line
        result = engine.calculate(
            row, None, now, auto_context=False, allow_manual_context=True
        )
        engine_p = result["pricing_lanes"]["lane_a_independent"]["estimate_p"]
        # Half-point lines carry no push mass, so the engine's raw win
        # probability and the adapter's decisive-conditioned value agree
        # to the card view's 6dp rounding.
        assert adapter_p == pytest.approx(engine_p, abs=2e-6), market


def test_producer_integer_line_decisive_conditioning():
    from artifacts import free_models as engine

    producer = _producer()
    inp = build_candidate_input(
        _game(), home_rating=0.9, away_rating=-0.4, home_advantage_points=2.5
    )
    probs = producer.family_probabilities(inp, GameLines(spread_home=-3.0))
    home_mean, away_mean = engine.score_means(
        "CFB",
        {
            "home_rating": 0.9,
            "away_rating": -0.4,
            "home_injury_pts": 0.0,
            "away_injury_pts": 0.0,
            "home_form": 0.0,
            "away_form": 0.0,
            "weather_total_adj": 0.0,
            "rest_diff_adj": 0.0,
        },
    )
    win, push = engine.model_probability(
        "CFB", "SPREAD", "HOME", -3.0, home_mean, away_mean
    )
    assert push > 0.0  # the integer line really carries push mass
    assert probs.spread_home_cover == pytest.approx(
        win / (win + (1.0 - win - push)), abs=1e-12
    )


def test_producer_team_total_matches_production_construction():
    import math

    from artifacts import free_models as engine
    from sportsedge import team_half_pricing

    producer = _producer()
    inp = build_candidate_input(
        _game(), home_rating=0.9, away_rating=-0.4, home_advantage_points=2.5
    )
    lines = GameLines(team_total_home=27.5, team_total_away=24.0)
    probs = producer.family_probabilities(inp, lines)
    context = {key: 0.0 for key in engine.CONTEXT_KEYS["CFB"]}
    context.update({"home_rating": 0.9, "away_rating": -0.4})
    home_mean, away_mean = engine.score_means("CFB", context)
    _, sd_total, sd_margin, _ = engine.PRIORS["CFB"]
    sigma = math.sqrt(sd_total**2 + sd_margin**2) / 2.0
    for mean, line, adapter_p in (
        (home_mean, 27.5, probs.team_total_home_over),
        (away_mean, 24.0, probs.team_total_away_over),
    ):
        win, push = team_half_pricing._normal_outcome(mean, sigma, "OVER", line)
        expected = win / (win + (1.0 - win - push))
        assert adapter_p == pytest.approx(expected, abs=1e-12)


def test_bind_refuses_hfa_divergence_and_incomplete_identity():
    with pytest.raises(BindingError, match="ENGINE_HFA_MISMATCH"):
        FrozenEngineProducer.bind(
            identity=_engine_identity(),
            config=EvalConfig(home_advantage_points=3.0),
        )
    with pytest.raises(BindingError, match="ENGINE_IDENTITY"):
        EngineIdentity.from_file_bytes({}, source_commit="b68114e0f")
    with pytest.raises(BindingError, match="ENGINE_IDENTITY"):
        EngineIdentity.from_file_bytes(
            {rel: b"x" for rel in bindings.ENGINE_FILES}, source_commit=""
        )


def test_producer_refuses_non_neutral_inputs():
    producer = _producer()
    lines = GameLines(spread_home=-3.5)
    for context in (
        {"home_rating": 0.0, "away_rating": 0.0, "starting_qb": 1.0},
        {"home_rating": 0.0, "away_rating": 0.0, "home_injury_pts": 0.5},
        {"home_rating": 0.0, "away_rating": 0.0, "unlisted_key": 1.0},
    ):
        bad = CandidateGameInput(game_id="SYN", context=context)
        with pytest.raises(NonNeutralInputError):
            producer.family_probabilities(bad, lines)


def test_engine_identity_fragment_records_both_files():
    fragment = _producer().run_manifest_fragment()
    assert set(fragment["engine_file_sha256"]) == set(bindings.ENGINE_FILES)
    assert fragment["producer_name"] == FrozenEngineProducer.name
    assert fragment["engine_source_commit"] == "b68114e0f"


# ----------------------------------------------------------------------
# Directory snapshot
# ----------------------------------------------------------------------

_TEAM_ROWS = [
    {"team_id": 100, "school": "Alpha", "abbreviation": "ALP",
     "conference": "Test A", "classification": "fbs"},
    {"team_id": 200, "school": "Beta", "abbreviation": "BET",
     "conference": "Test A", "classification": "fbs"},
    {"team_id": 256, "school": "James Madison", "abbreviation": "JMU",
     "conference": "Sun Belt", "classification": "fbs"},
    {"team_id": 300, "school": "Gamma State", "abbreviation": "GAM",
     "conference": "Test C", "classification": "fcs"},
    {"team_id": 356, "school": "Illinois", "abbreviation": "ILL",
     "conference": "Big Ten", "classification": "fbs"},
]

_OVERRIDES = {
    "version": "TEST_OVERRIDES",
    "status": "BINDINGS_DECLARED_NOT_OWNER_RULED",
    "teams": [
        {"team_id": "256", "school": "James Madison",
         "table_classification": "fbs", "fcs_seasons": [2021]},
    ],
}


def _directory() -> DirectorySnapshot:
    snapshot = bindings.build_directory_snapshot(
        _TEAM_ROWS, provenance={"fixture": True}, overrides=_OVERRIDES
    )
    return DirectorySnapshot(snapshot)


def test_directory_season_effective_classification():
    directory = _directory()
    assert directory.classification_for(2021, "256") == "fcs"
    assert directory.classification_for(2022, "256") == "fbs"
    assert directory.is_fbs(2025, "100")
    assert not directory.is_fbs(2025, "300")
    assert directory.classification_for(2025, "999") is None
    assert "356" in directory.known_team_ids()


def test_directory_refusals():
    with pytest.raises(BindingError, match="DIRECTORY_DUPLICATE_TEAM_ID"):
        bindings.build_directory_snapshot(
            _TEAM_ROWS + [_TEAM_ROWS[0]],
            provenance={},
            overrides=_OVERRIDES,
        )
    bad_overrides = {
        "version": "T",
        "status": "BINDINGS_DECLARED_NOT_OWNER_RULED",
        "teams": [
            {"team_id": "256", "school": "James Madison",
             "table_classification": "fcs", "fcs_seasons": [2021]},
        ],
    }
    with pytest.raises(BindingError, match="DIRECTORY_OVERRIDE_BASE_MISMATCH"):
        bindings.build_directory_snapshot(
            _TEAM_ROWS, provenance={}, overrides=bad_overrides
        )
    snapshot = bindings.build_directory_snapshot(
        _TEAM_ROWS, provenance={}, overrides=_OVERRIDES
    )
    snapshot["payload"]["teams"]["100"]["classification"] = "fcs"
    with pytest.raises(BindingError, match="DIRECTORY_SNAPSHOT_HASH_MISMATCH"):
        DirectorySnapshot(snapshot)


# ----------------------------------------------------------------------
# Results snapshot
# ----------------------------------------------------------------------

_SCHEDULE_COLUMNS = [
    "game_id", "season", "week", "season_type", "game_date", "neutral_site",
    "conference_competition", "home_id", "away_id", "home_team", "away_team",
    "home_abbreviation", "away_abbreviation", "home_score", "away_score",
    "home_winner", "away_winner", "venue", "attendance", "status",
]


def _schedule_csv(rows) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_SCHEDULE_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return gzip.compress(buffer.getvalue().encode("utf-8"))


def _schedule_row(game_id, season, home_id, away_id, home_score, away_score,
                  date="2021-09-04T17:00Z", status="STATUS_FINAL"):
    return {
        "game_id": game_id, "season": season, "week": 1, "season_type": 2,
        "game_date": date, "neutral_site": "False",
        "conference_competition": "False", "home_id": home_id,
        "away_id": away_id, "home_team": "Home", "away_team": "Away",
        "home_abbreviation": "H", "away_abbreviation": "A",
        "home_score": home_score, "away_score": away_score,
        "home_winner": "", "away_winner": "", "venue": "", "attendance": "",
        "status": status,
    }


def _results_snapshot() -> dict:
    rows_2021 = [
        _schedule_row("G1", 2021, 100, 200, 31, 24),
        _schedule_row("G2", 2021, 100, 300, 45, 10, date="2021-09-11T17:00Z"),
        _schedule_row("G3", 2021, 356, 200, 20, 27, date="2021-09-18T17:00Z"),
        _schedule_row("G4", 2021, 100, 200, "", "", date="2021-09-25T17:00Z",
                      status="STATUS_CANCELED"),
    ]
    return bindings.build_results_snapshot(
        {2021: _schedule_csv(rows_2021)},
        _directory(),
        source_records={"fixture": True},
    )


def test_results_snapshot_round_trip():
    snapshot = _results_snapshot()
    payload, games = bindings.load_results_snapshot(
        json.dumps(snapshot).encode("utf-8")
    )
    assert payload["game_count"] == 4
    by_id = {g.game_id: g for g in games}
    assert by_id["G1"].home_fbs and by_id["G1"].away_fbs
    assert by_id["G2"].home_fbs and not by_id["G2"].away_fbs
    assert by_id["G4"].no_contest and not by_id["G4"].decided
    assert [g.game_id for g in games] == ["G1", "G2", "G3", "G4"]


def test_results_snapshot_refusals():
    rows = [
        _schedule_row("G1", 2021, 100, 200, 31, 24),
        _schedule_row("G1", 2021, 100, 200, 31, 24),
    ]
    with pytest.raises(BindingError, match="RESULTS_DUPLICATE_GAME_ID"):
        bindings.build_results_snapshot(
            {2021: _schedule_csv(rows)}, _directory(), source_records={}
        )
    snapshot = _results_snapshot()
    snapshot["payload"]["games"][0]["home_score"] = 99
    with pytest.raises(BindingError, match="RESULTS_SNAPSHOT_HASH_MISMATCH"):
        bindings.load_results_snapshot(json.dumps(snapshot).encode("utf-8"))


# ----------------------------------------------------------------------
# Lines snapshot
# ----------------------------------------------------------------------

_LINE_COLUMNS = [
    "id", "game_id", "season", "game_desc", "date_time", "market_type",
    "abbr", "lines", "odds", "opening_lines", "opening_odds", "book",
    "season_type", "week", "home_team_id", "away_team_id",
]


def _line_row(game_id, market, abbr, lines="", odds="", book="Bovada",
              desc="Beta@Alpha", date_time="2021-09-04T17:00:00.000Z",
              home_id="100", away_id="200", season="2021.0"):
    return {
        "id": "1.0", "game_id": game_id, "season": season, "game_desc": desc,
        "date_time": date_time, "market_type": market, "abbr": abbr,
        "lines": lines, "odds": odds, "opening_lines": "",
        "opening_odds": "", "book": book, "season_type": "regular",
        "week": "1", "home_team_id": home_id, "away_team_id": away_id,
    }


def _lines_archive(rows) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_LINE_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return gzip.compress(buffer.getvalue().encode("utf-8"))


def _clean_game_rows(game_id="L1", home_ml="-160", away_ml="140"):
    # Alpha (id 100) is home per game_desc 'Beta@Alpha'; Alpha -3.5.
    return [
        _line_row(game_id, "spread", "Alpha", lines="-3.5"),
        _line_row(game_id, "spread", "Beta", lines="3.5"),
        _line_row(game_id, "total", "over", lines="51.5"),
        _line_row(game_id, "total", "under", lines="51.5"),
        _line_row(game_id, "money_line", "Alpha", odds=home_ml),
        _line_row(game_id, "money_line", "Beta", odds=away_ml),
    ]


def _build_lines(rows) -> dict:
    return bindings.build_lines_snapshot(
        _lines_archive(rows),
        designated_provider="Bovada",
        seasons=[2021],
        source_record={"fixture": True},
    )


_RESULTS_INDEX = {
    "L1": {"kickoff_utc": "2021-09-04T17:00:00+00:00",
           "home_team_id": "100", "away_team_id": "200"},
    "L2": {"kickoff_utc": "2021-09-04T17:00:00+00:00",
           "home_team_id": "100", "away_team_id": "200"},
}


def test_lines_snapshot_clean_game_round_trip():
    snapshot = _build_lines(_clean_game_rows())
    payload = snapshot["payload"]
    record = payload["games"]["L1"]
    assert record["label"] == harness.DESCRIPTIVE_LABEL
    assert record["spread_home"] == -3.5
    assert record["total"] == 51.5
    assert record["home_moneyline"] == -160
    assert record["away_moneyline"] == 140
    assert record["ml_crosscheck"] == "PASS"
    assert record["team_total_home"] is None
    assert record["team_total_status"] == harness.NO_HISTORICAL_MARKET_COMPARATOR
    load = bindings.load_lines_snapshot(
        json.dumps(snapshot).encode("utf-8"), results_index=_RESULTS_INDEX
    )
    assert load.flags == []
    lines = load.lines_by_game["L1"]
    assert lines.spread_home == -3.5 and lines.home_moneyline == -160


def test_lines_snapshot_flipped_moneyline_quarantined():
    snapshot = _build_lines(_clean_game_rows(home_ml="140", away_ml="-160"))
    record = snapshot["payload"]["games"]["L1"]
    assert record["home_moneyline"] is None
    assert record["away_moneyline"] is None
    assert record["spread_home"] == -3.5  # spread attribution unaffected
    quarantine = snapshot["payload"]["quarantine"]
    assert any(
        q["reason"] == bindings.Q_ML_SPREAD_SIGN_INCONSISTENT
        for q in quarantine
    )


def test_lines_snapshot_uncheckable_moneyline_quarantined():
    rows = [r for r in _clean_game_rows() if r["market_type"] != "spread"]
    snapshot = _build_lines(rows)
    record = snapshot["payload"]["games"]["L1"]
    assert record["home_moneyline"] is None
    assert any(
        q["reason"] == bindings.Q_ML_CROSSCHECK_UNAVAILABLE
        for q in snapshot["payload"]["quarantine"]
    )


def test_lines_loader_refuses_unlabeled_record_even_when_resigned():
    snapshot = _build_lines(_clean_game_rows())
    snapshot["payload"]["games"]["L1"].pop("label")
    snapshot["snapshot_id"] = bindings._sha256(
        bindings._canonical(snapshot["payload"])
    )
    with pytest.raises(BindingError, match="UNLABELED_MARKET_RECORD_REFUSED"):
        bindings.load_lines_snapshot(
            json.dumps(snapshot).encode("utf-8"), results_index=_RESULTS_INDEX
        )


def test_lines_loader_pit_canary_and_identity_flags():
    rows = _clean_game_rows(game_id="L2")
    for row in rows:
        row["date_time"] = "2021-09-04T19:00:00.000Z"  # after kickoff
    snapshot = _build_lines(rows)
    load = bindings.load_lines_snapshot(
        json.dumps(snapshot).encode("utf-8"), results_index=_RESULTS_INDEX
    )
    assert "L2" not in load.lines_by_game
    assert any(
        f["flag"] == bindings.FLAG_POST_KICKOFF_LINE_TIMESTAMP
        for f in load.flags
    )
    # Orphan: no results game at all.
    load = bindings.load_lines_snapshot(
        json.dumps(_build_lines(_clean_game_rows())).encode("utf-8"),
        results_index={},
    )
    assert load.lines_by_game == {}
    assert any(
        f["flag"] == bindings.FLAG_ORPHAN_LINE_RECORD for f in load.flags
    )
    # Team identity mismatch vs the results snapshot.
    load = bindings.load_lines_snapshot(
        json.dumps(_build_lines(_clean_game_rows())).encode("utf-8"),
        results_index={
            "L1": {"kickoff_utc": "2021-09-04T17:00:00+00:00",
                   "home_team_id": "200", "away_team_id": "100"}
        },
    )
    assert load.lines_by_game == {}
    assert any(
        f["flag"] == bindings.FLAG_TEAM_ID_MISMATCH for f in load.flags
    )


# ----------------------------------------------------------------------
# Ruled config + dry-run manifest
# ----------------------------------------------------------------------


def _bindings_cfg() -> dict:
    return json.loads(
        (REPO_ROOT / "config/research/cfb_four_family_bindings_v1.json")
        .read_text(encoding="utf-8")
    )


def test_ruled_config_applies_owner_rulings_and_keeps_freeze_null():
    resolved = bindings.ruled_config(_bindings_cfg())
    assert resolved.candidate_mode == "CAND_2_INJURY_NEUTRAL"
    assert resolved.cfbd_role == "DESCRIPTIVE_ONLY"
    assert resolved.evaluation_seasons == (2021, 2022, 2023, 2024, 2025)
    assert resolved.burn_in_seasons == tuple(range(2013, 2021))
    assert not resolved.include_fcs_opponents


def test_ruled_config_refuses_freeze_or_unruled_records():
    cfg = _bindings_cfg()
    cfg["rulings"]["freeze_sha"] = "deadbeef"
    with pytest.raises(BindingError, match="BINDINGS_CARRY_A_FREEZE_SHA"):
        bindings.ruled_config(cfg)
    cfg = _bindings_cfg()
    cfg["rulings"]["status"] = "UNRULED"
    with pytest.raises(BindingError, match="BINDINGS_RULINGS_NOT_RECORDED_AS_RULED"):
        bindings.ruled_config(cfg)


def test_dry_run_manifest_counts_reconcile_and_stays_not_run():
    results = _results_snapshot()
    payload, games = bindings.load_results_snapshot(
        json.dumps(results).encode("utf-8")
    )
    lines_snapshot = _build_lines(_clean_game_rows(game_id="G1"))
    index = {
        record["game_id"]: record for record in payload["games"]
    }
    load = bindings.load_lines_snapshot(
        json.dumps(lines_snapshot).encode("utf-8"), results_index=index
    )
    manifest = bindings.build_dry_run_manifest(
        bindings_cfg=_bindings_cfg(),
        results_snapshot_id=results["snapshot_id"],
        lines_snapshot_id=lines_snapshot["snapshot_id"],
        games=games,
        lines_load=load,
        directory=_directory(),
    )
    assert manifest["run_state"] == "NOT_RUN"
    assert manifest["freeze_sha"] is None
    assert manifest["probabilities_computed"] is False
    assert manifest["attempts_consumed"] == 0
    population = manifest["population"]
    assert (
        population["population_games"] + population["excluded_games"]
        == population["total_games_in_results_snapshot"]
        == 4
    )
    # G1 (both FBS) is the population; G2 FCS opponent, G3 Illinois,
    # G4 no-contest are the three exclusions.
    assert population["population_games"] == 1
    assert population["exclusion_counts"] == {
        harness.EXCL_IL_COLLEGE: 1,
        harness.EXCL_NON_FBS_OPPONENT: 1,
        harness.EXCL_NO_CONTEST: 1,
    }
    assert manifest["folds"]["2021"]["families"]["spread"]["matched_games"] == 1
    assert manifest["folds"]["2021"]["families"]["team_total"]["matched_games"] == 0
    market = manifest["market_data_descriptive_only"]
    assert market["label"] == harness.DESCRIPTIVE_LABEL


def test_bindings_module_has_no_network_or_subprocess_imports():
    tree = ast.parse(
        (REPO_ROOT / "sportsedge/research/cfb_four_family_bindings_v1.py")
        .read_text(encoding="utf-8")
    )
    banned = {"urllib", "socket", "subprocess", "requests", "http"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & banned)
