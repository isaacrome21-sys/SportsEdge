"""Offline contracts for the strict forward-capture archive.

These tests prove record shape, immutability, settlement append
semantics, and evaluator assembly. They do not test forecasting skill
and never touch the network: probabilities here are fixtures handed to
the archive layer, exactly as the live capture CLI hands it production
output at capture time.
"""
import json

import pytest

from sportsedge.backtest import forward_capture as fc
from sportsedge.backtest.strict_paired_oos import REQUIRED, evaluate


KICK = "2026-10-13T00:00:00Z"


def make_record(**overrides):
    spec = dict(
        away="Cleveland Guardians", home="Tampa Bay Rays",
        kickoff_utc=KICK, series_id="2026-ALCS-CLE-TB",
        market="ML", selection="HOME", line="ML", book="draftkings",
        selection_american=-171,
        selection_captured_at_utc="2026-10-12T23:45:00Z",
        opposite_american=141,
        opposite_captured_at_utc="2026-10-12T23:45:00Z",
        candidate_p=0.61, existing_p=0.55,
        model_source_sha="b" * 40,
        as_of_utc="2026-10-12T23:46:00Z",
        feature_max_available_at_utc="2026-10-12T23:46:00Z",
        train_last_final_at_utc="2026-10-11T23:00:00Z",
        provenance={"quote_source": "test fixture"},
    )
    spec.update(overrides)
    return fc.build_capture_record(**spec)


def settle(archive, outcome=1, outcome_state=None, **overrides):
    if outcome_state is None:
        outcome_state = ("PUSH" if outcome is None
                         else "WIN" if outcome == 1 else "LOSS")
    entry = {
        "fixture_id": "mlb:2026-10-12:Cleveland Guardians:Tampa Bay Rays",
        "market": "ML", "selection": "HOME", "line": "ML",
        "outcome": outcome, "outcome_state": outcome_state,
        "outcome_grade": 0.5 if outcome is None else float(outcome),
        "home_score": 5, "away_score": 2, "game_pk": "1",
        "source": "MLB_STATSAPI_FINAL",
        "settled_at_utc": "2026-10-13T04:00:00Z", "correction": False,
    }
    entry.update(overrides)
    return fc.append_settlement(archive, entry)


def test_record_carries_every_evaluator_field_except_outcome():
    record = make_record()
    for field in REQUIRED:
        if field == "outcome":
            assert field not in record
        else:
            assert record[field] not in (None, "")
    assert record["market_blind"] is True
    assert record["opposite_selection"] == "AWAY"
    assert record["compliance_warnings"] == []
    # League-local date: 2026-10-13T00:00Z is Oct 12 in America/New_York.
    assert record["fixture_id"].startswith("mlb:2026-10-12:")


def test_compliant_window_has_no_warnings_and_late_close_warns():
    assert make_record()["compliance_warnings"] == []
    late = make_record(selection_captured_at_utc="2026-10-12T22:00:00Z",
                       opposite_captured_at_utc="2026-10-12T22:00:00Z")
    assert "MARKET_NOT_VERIFIED_CLOSE_RISK" in late["compliance_warnings"]


def test_async_pair_and_post_pitch_capture_warn():
    async_rec = make_record(
        opposite_captured_at_utc="2026-10-12T23:40:00Z")
    assert "MARKET_PAIR_ASYNCHRONOUS_RISK" in async_rec["compliance_warnings"]
    post = make_record(selection_captured_at_utc="2026-10-13T00:05:00Z",
                       opposite_captured_at_utc="2026-10-13T00:05:00Z")
    assert "MARKET_QUOTE_NOT_PREGAME_RISK" in post["compliance_warnings"]


def test_invalid_odds_and_probabilities_fail_closed():
    with pytest.raises(fc.CaptureError):
        make_record(selection_american=-100)  # evaluator rejects -100 too
    with pytest.raises(fc.CaptureError):
        make_record(selection_american=0)
    with pytest.raises(fc.CaptureError):
        make_record(candidate_p=1.0)
    with pytest.raises(fc.CaptureError):
        make_record(market="ML", line=1.5)
    with pytest.raises(fc.CaptureError):
        make_record(model_source_sha="")


def test_capture_is_write_once(tmp_path):
    archive = tmp_path / "archive"
    record = make_record()
    path = fc.write_capture(archive, record)
    before = path.read_bytes()
    with pytest.raises(fc.CaptureError):
        fc.write_capture(archive, record)
    assert path.read_bytes() == before


def test_settlement_appends_without_touching_capture(tmp_path):
    archive = tmp_path / "archive"
    path = fc.write_capture(archive, make_record())
    before = path.read_bytes()
    settle(archive, outcome=1)
    assert path.read_bytes() == before
    lines = fc.settlements_path(archive).read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["outcome"] == 1


def test_unsettled_capture_is_excluded_not_dropped(tmp_path):
    archive = tmp_path / "archive"
    fc.write_capture(archive, make_record())
    rows, excluded = fc.assemble_rows(archive)
    assert rows == []
    assert excluded[0]["reason"] == "OUTCOME_NOT_SETTLED"
    result = evaluate(rows)
    assert result["status"] == "BLOCKED_EVIDENCE"


def test_settled_archive_flows_to_evaluator_as_insufficient(tmp_path):
    archive = tmp_path / "archive"
    fc.write_capture(archive, make_record())
    settle(archive, outcome=1)
    rows, excluded = fc.assemble_rows(archive)
    assert excluded == []
    assert len(rows) == 1
    assert set(rows[0]) == set(REQUIRED)
    result = evaluate(rows)  # defaults: 300 games / 20 series
    assert result["status"] == "INSUFFICIENT_OOS"
    assert result["n_verified"] == 1


def test_push_settlement_is_excluded_with_reason(tmp_path):
    archive = tmp_path / "archive"
    fc.write_capture(archive, make_record(selection="OVER", market="TOTAL",
                                          line=7.5))
    settle(archive, outcome=None, outcome_grade=0.5, market="TOTAL",
           selection="OVER", line=7.5)
    rows, excluded = fc.assemble_rows(archive)
    assert rows == []
    assert excluded[0]["reason"] == "PUSH_NOT_BINARY_SETTLEABLE"


def test_prediction_section_keeps_lanes_labeled_and_separate():
    prediction = {
        "candidate": {"lane": "LANE_A_INDEPENDENT", "label": "MARKET_BLIND",
                      "win_p": 0.61, "push_p": 0.0, "loss_p": 0.39},
        "market_anchored": {"lane": "LANE_B_ANCHORED",
                            "label": "MARKET_ANCHORED",
                            "win_p": 0.58, "push_p": 0.0, "loss_p": 0.42},
    }
    record = make_record(prediction=prediction)
    assert record["candidate_p"] == 0.61  # Lane A, never the anchored 0.58
    assert record["prediction"]["candidate"]["label"] == "MARKET_BLIND"
    assert record["prediction"]["market_anchored"]["label"] == \
        "MARKET_ANCHORED"
    with pytest.raises(fc.CaptureError):
        make_record(prediction="not-a-dict")


def test_first_settlement_stands_unless_correction(tmp_path):
    archive = tmp_path / "archive"
    fc.write_capture(archive, make_record())
    settle(archive, outcome=0)
    settle(archive, outcome=1)  # not a correction: ignored by assembler
    rows, _ = fc.assemble_rows(archive)
    assert rows[0]["outcome"] == 0
    settle(archive, outcome=1, correction=True)
    rows, _ = fc.assemble_rows(archive)
    assert rows[0]["outcome"] == 1
    # All three lines remain in the append-only file.
    lines = fc.settlements_path(archive).read_text().strip().splitlines()
    assert len(lines) == 3


def test_elo_leg_uses_supported_sport_key(monkeypatch):
    """Regression (Oct 12 audit): the capture CLI built EloRatings("MLB")
    while SPORT_PARAMS keys are lowercase, so the Elo leg would have
    refused with ELO_SPORT_UNSUPPORTED even after the schedule fetch was
    repaired. Exercise elo_existing_probability with the REAL EloRatings
    and a stubbed schedule fetch (offline)."""
    import importlib.util
    from datetime import datetime, timezone
    spec = importlib.util.spec_from_file_location(
        "capture_strict_mlb_record", "scripts/capture_strict_mlb_record.py")
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    fake_dates = [{"date": "2026-10-10", "games": [{
        "gamePk": 824001, "gameDate": "2026-10-10T23:05:00Z", "gameType": "R",
        "status": {"detailedState": "Final"},
        "teams": {"away": {"team": {"name": "Cleveland Guardians"}, "score": 2},
                  "home": {"team": {"name": "Tampa Bay Rays"}, "score": 5}}}]}]
    observed = datetime(2026, 10, 12, 23, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(cap, "_fetch_schedule_with_provenance",
                        _established_fetch(fake_dates, observed))
    p, cutoff, n, p_home, pop, prov = cap.elo_existing_probability(
        "Cleveland Guardians", "Tampa Bay Rays", "HOME",
        datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc))
    assert 0.0 < p < 1.0 and n == 1 and p == p_home
    assert prov["source_observed_at_utc"] == observed.isoformat()
    assert prov["source_origin"] == "HTTP"
    assert prov["consumer_read_at_utc"] == observed.isoformat()
    assert prov["pit_provenance_status"] == "PIT_PROVENANCE_ESTABLISHED"
    assert len(prov["schedule_content_sha256"]) == 64
    assert pop["included_by_game_type"] == {"R": 1}
    assert pop["included_total"] == 1 and pop["excluded_total"] == 0


def _load_capture_cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "capture_strict_mlb_record", "scripts/capture_strict_mlb_record.py")
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    return cap


def _established_fetch(dates, observed):
    """Stub for cap._fetch_schedule_with_provenance returning an
    ESTABLISHED provenance fixture: a fresh HTTP observation stamped
    at `observed`. Provenance mechanics themselves are exercised
    against the real wrapper in the provenance tests below; the
    population/ratings tests stub this seam because their subject is
    the population filter and the ratings, not provenance."""
    def _stub(season_start, end_date):
        fields = {
            "source_observed_at_utc": observed.isoformat(),
            "source_origin": "HTTP",
            "consumer_read_at_utc": observed.isoformat(),
            "cache_provenance_basis": "test fixture: established "
                                      "provenance stub",
        }
        return dates, fields, observed, observed
    return _stub


def _typed_game(pk, date, game_type, away, home, away_score, home_score):
    game = {"gamePk": pk, "gameDate": date,
            "status": {"detailedState": "Final"},
            "teams": {"away": {"team": {"name": away}, "score": away_score},
                      "home": {"team": {"name": home}, "score": home_score}}}
    if game_type is not None:
        game["gameType"] = game_type
    return game


def _mixed_type_dates():
    """Synthetic schedule mixing competitive and non-competitive types.

    The spring-training game is a 20-0 blowout: if it leaked into the
    Elo accumulation it would move the probability, so exact equality
    against the competitive-only fixture proves exclusion.
    """
    cle, tb = "Cleveland Guardians", "Tampa Bay Rays"
    return [{"date": "2026-10-10", "games": [
        _typed_game(1, "2026-10-10T23:05:00Z", "R", cle, tb, 2, 5),
        _typed_game(2, "2026-10-09T23:05:00Z", "D", tb, cle, 3, 1),
        _typed_game(3, "2026-03-10T18:05:00Z", "S", tb, cle, 0, 20),
        _typed_game(4, "2026-03-11T18:05:00Z", "E", cle, tb, 1, 9),
        _typed_game(5, "2026-07-14T23:05:00Z", "A", cle, tb, 4, 6),
        # No gameType at all: excluded fail-closed, counted UNKNOWN.
        _typed_game(6, "2026-10-08T23:05:00Z", None, cle, tb, 7, 0),
        # Not Final: in neither population even though type R.
        {"gamePk": 7, "gameDate": "2026-10-10T20:05:00Z", "gameType": "R",
         "status": {"detailedState": "In Progress"},
         "teams": {"away": {"team": {"name": cle}, "score": 1},
                   "home": {"team": {"name": tb}, "score": 1}}},
    ]}]


def test_elo_training_population_excludes_noncompetitive_types(monkeypatch):
    """Owner data-quality hold (issue #2086): parse_completed_mlb_games
    accepts every Final game and drops gameType, so the capture CLI's
    Elo leg must filter the raw schedule to regular season + postseason
    BEFORE parsing, or spring/exhibition results contaminate the
    market-free baseline (live Oct 2026 population was 471/2,925
    non-competitive games)."""
    from datetime import datetime, timezone
    cap = _load_capture_cli()
    kickoff = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    observed = datetime(2026, 10, 12, 23, 0, tzinfo=timezone.utc)
    dates = _mixed_type_dates()
    monkeypatch.setattr(cap, "_fetch_schedule_with_provenance",
                        _established_fetch(dates, observed))
    p, cutoff, n, p_home, pop, prov = cap.elo_existing_probability(
        "Cleveland Guardians", "Tampa Bay Rays", "HOME", kickoff)
    # (b) The population summary matches the fixture exactly.
    assert pop["included_by_game_type"] == {"R": 1, "D": 1}
    assert pop["included_total"] == 2
    assert pop["excluded_by_game_type"] == {"S": 1, "E": 1, "A": 1,
                                             "UNKNOWN": 1}
    assert pop["excluded_total"] == 4
    assert pop["allowable_game_types"] == ["D", "F", "L", "R", "W"]
    # The games the ratings were built from are exactly the included set.
    assert n == pop["included_total"]
    # (a) The same fixture without the non-competitive games yields the
    # identical probability: the 20-0 spring blowout did not move it.
    competitive_only = [{"date": day["date"], "games": [
        g for g in day["games"]
        if g.get("gameType") in ("R", "D")
        and g["status"]["detailedState"] == "Final"]}
        for day in dates]
    monkeypatch.setattr(cap, "_fetch_schedule_with_provenance",
                        _established_fetch(competitive_only, observed))
    p2, cutoff2, n2, p_home2, pop2, prov2 = cap.elo_existing_probability(
        "Cleveland Guardians", "Tampa Bay Rays", "HOME", kickoff)
    assert p == p2 and p_home == p_home2 and n == n2 and cutoff == cutoff2
    assert pop2["excluded_total"] == 0


def test_cli_refuses_spread_and_total_before_any_record(tmp_path,
                                                        monkeypatch, capsys):
    """Owner check #2 (issue #2086): the Elo floor is moneyline-only, so
    its probability must never serve as existing_p for a spread or a
    total. The refusal lives in the capture CLI's main(), immediately
    after schema validation and BEFORE the production pricer, the Elo
    leg, and record assembly — prove it by making both probability legs
    explode if called, and by the archive staying empty."""
    cap = _load_capture_cli()

    def _boom(*args, **kwargs):
        raise AssertionError("probability leg reached for a non-ML market")

    monkeypatch.setattr(cap, "production_probability", _boom)
    monkeypatch.setattr(cap, "elo_existing_probability", _boom)
    base = {
        "schema": "SPORTSEDGE_STRICT_CAPTURE_INPUT_V1",
        "away": "Cleveland Guardians", "home": "Tampa Bay Rays",
        "kickoff_utc": "2027-04-01T23:05:00Z",
        "series_id": "2027-TEST-CLE-TB",
        "book": "draftkings",
        "selection_american": -110,
        "selection_captured_at_utc": "2027-04-01T22:35:00Z",
        "opposite_american": -110,
        "opposite_captured_at_utc": "2027-04-01T22:35:00Z",
        "quote_source": "offline refusal fixture",
    }
    cases = (("SPREAD", "HOME", "-1.5"), ("TOTAL", "OVER", "6.5"))
    for market, selection, line in cases:
        spec_in = dict(base, market=market, selection=selection, line=line)
        input_path = tmp_path / f"input_{market}.json"
        input_path.write_text(json.dumps(spec_in), encoding="utf-8")
        archive = tmp_path / f"archive_{market}"
        rc = cap.main(["--input", str(input_path),
                       "--archive-dir", str(archive)])
        verdict = json.loads(capsys.readouterr().out.strip())
        assert rc == 1
        assert verdict["status"] == "CAPTURE_REFUSED"
        assert verdict["reason"].startswith(
            "EXISTING_MODEL_PROBABILITY_UNAVAILABLE_FOR_MARKET:" + market)
        assert not archive.exists() or not list(archive.rglob("*.json"))


def test_elo_leg_provenance_gate_and_hash(monkeypatch):
    """Owner requirements (issue #2086): start < kickoff + Final status
    cannot prove a game was final before the cutoff — a game starting
    one minute before it could finish after. What proves finality is
    the payload having been OBSERVED at the source, Final statuses
    included, before the cutoff. UPDATED EXPECTATION (cache-
    provenance fix): a payload observed at/after kickoff no longer
    returns a probability with a visibly-failing stamp — the leg
    REFUSES (ELO_SCHEDULE_PROVENANCE_UNESTABLISHED). The stamp is
    still never backdated; refusal is the honest outcome."""
    import hashlib
    import json

    import pytest
    from datetime import datetime, timezone
    cap = _load_capture_cli()
    kickoff = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    # The owner's edge case exactly: Final game starting 1 minute
    # before the target kickoff.
    fixture = [{"date": "2026-10-12", "games": [{
        "gamePk": 824002, "gameDate": "2026-10-12T23:59:00Z",
        "gameType": "R", "status": {"detailedState": "Final"},
        "teams": {"away": {"team": {"name": "Cleveland Guardians"}, "score": 2},
                  "home": {"team": {"name": "Tampa Bay Rays"}, "score": 5}}}]}]
    # Payload observed at the source 30s before kickoff, the game
    # already Final in it: provenance established, the game trains.
    observed = datetime(2026, 10, 12, 23, 59, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(cap, "_fetch_schedule_with_provenance",
                        _established_fetch(fixture, observed))
    p, cutoff, n, p_home, pop, prov = cap.elo_existing_probability(
        "Cleveland Guardians", "Tampa Bay Rays", "HOME", kickoff)
    assert n == 1  # start-time eligibility includes the 1-minute game
    assert prov["source_observed_at_utc"] == observed.isoformat()
    assert prov["source_origin"] == "HTTP"
    assert prov["consumer_read_at_utc"] == observed.isoformat()
    assert prov["pit_provenance_status"] == "PIT_PROVENANCE_ESTABLISHED"
    # The hash matches an independent canonical recomputation over the
    # structure the leg consumed (single R game: filtered == fixture).
    expected = hashlib.sha256(json.dumps(
        fixture, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert prov["schedule_content_sha256"] == expected
    assert "raw response bytes" in prov["schedule_hash_basis"]
    # Observation AT the kickoff refuses (the rule is at/after), and a
    # retrospective observation after the kickoff refuses: no
    # probability is produced and no stamp is backdated to fake one.
    for bad_observed in (kickoff,
                         datetime(2026, 10, 14, 12, 0,
                                  tzinfo=timezone.utc)):
        monkeypatch.setattr(cap, "_fetch_schedule_with_provenance",
                             _established_fetch(fixture, bad_observed))
        with pytest.raises(cap.fc.CaptureError,
                           match="ELO_SCHEDULE_PROVENANCE_"
                                 "UNESTABLISHED"):
            cap.elo_existing_probability(
                "Cleveland Guardians", "Tampa Bay Rays", "HOME", kickoff)


def test_elo_schedule_hash_binds_training_content(monkeypatch):
    """Changing any training-relevant content changes the hash; the
    hash is deterministic for identical content."""
    from datetime import datetime, timezone
    cap = _load_capture_cli()
    kickoff = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)

    def fixture(home_score):
        return [{"date": "2026-10-10", "games": [{
            "gamePk": 824003, "gameDate": "2026-10-10T23:05:00Z",
            "gameType": "R", "status": {"detailedState": "Final"},
            "teams": {"away": {"team": {"name": "Cleveland Guardians"}, "score": 2},
                      "home": {"team": {"name": "Tampa Bay Rays"}, "score": home_score}}}]}]

    observed = datetime(2026, 10, 12, 23, 0, tzinfo=timezone.utc)
    hashes = []
    for score in (5, 5, 6):
        monkeypatch.setattr(cap, "_fetch_schedule_with_provenance",
                            _established_fetch(fixture(score), observed))
        *_, prov = cap.elo_existing_probability(
            "Cleveland Guardians", "Tampa Bay Rays", "HOME", kickoff)
        hashes.append(prov["schedule_content_sha256"])
    assert hashes[0] == hashes[1]      # deterministic
    assert hashes[0] != hashes[2]      # binds training-relevant content


def _one_game_dates():
    return [{"date": "2026-10-10", "games": [{
        "gamePk": 824001, "gameDate": "2026-10-10T23:05:00Z",
        "gameType": "R", "status": {"detailedState": "Final"},
        "teams": {"away": {"team": {"name": "Cleveland Guardians"},
                           "score": 2},
                  "home": {"team": {"name": "Tampa Bay Rays"},
                           "score": 5}}}]}]


def test_schedule_provenance_fresh_http_then_verified_cache_hit(
        tmp_path, monkeypatch):
    """The real wrapper over the real shared-fetcher cache: a fresh
    HTTP fetch stamps the SOURCE observation instant (distinct from
    the consumer-read instant) and records a manifest entry; a later
    cache hit reuses the ORIGINAL observation instant, verified by
    content-hash match, without touching the network."""
    from datetime import datetime, timezone
    cap = _load_capture_cli()
    monkeypatch.setattr(cap, "SCHEDULE_CACHE_DIR", tmp_path)
    payload = {"dates": _one_game_dates()}
    calls = {"n": 0}

    def getter(url):
        calls["n"] += 1
        return payload

    monkeypatch.setattr(cap, "_default_schedule_getter", getter)
    t1 = datetime(2026, 10, 12, 23, 50, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 12, 23, 55, tzinfo=timezone.utc)
    ticks = iter([t1, t2])  # getter observation, then consumer read
    monkeypatch.setattr(cap, "_utcnow", lambda: next(ticks))
    dates, fields, observed, read = cap._fetch_schedule_with_provenance(
        "2026-01-01", "2026-10-12")
    assert dates == payload["dates"]
    assert fields["source_origin"] == "HTTP"
    assert observed == t1 and read == t2 and observed <= read
    assert fields["source_observed_at_utc"] == t1.isoformat()
    assert fields["consumer_read_at_utc"] == t2.isoformat()
    assert calls["n"] == 1
    manifest = json.loads(
        (tmp_path / cap.SCHEDULE_PROVENANCE_MANIFEST).read_text(
            encoding="utf-8"))
    assert len(manifest) == 1
    entry = next(iter(manifest.values()))
    assert entry["source_observed_at_utc"] == t1.isoformat()

    # Second call: a pure cache hit. The HTTP getter must not run;
    # the original observation instant is recovered from the manifest.
    def _boom(url):
        raise AssertionError("HTTP getter invoked on a cache hit")

    monkeypatch.setattr(cap, "_default_schedule_getter", _boom)
    t3 = datetime(2026, 10, 12, 23, 58, tzinfo=timezone.utc)
    monkeypatch.setattr(cap, "_utcnow", lambda: t3)
    dates2, fields2, observed2, read2 = \
        cap._fetch_schedule_with_provenance("2026-01-01", "2026-10-12")
    assert dates2 == dates
    assert fields2["source_origin"] == "CACHE"
    assert observed2 == t1 and read2 == t3 and observed2 < read2
    assert fields2["source_observed_at_utc"] == t1.isoformat()
    assert fields2["consumer_read_at_utc"] == t3.isoformat()
    assert "manifest" in fields2["cache_provenance_basis"]

    # End to end: the Elo leg on this verified cache hit (observed
    # 23:50, before the 00:00 kickoff) is established and prices.
    kickoff = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    p, cutoff, n, p_home, pop, prov = cap.elo_existing_probability(
        "Cleveland Guardians", "Tampa Bay Rays", "HOME", kickoff)
    assert 0.0 < p < 1.0 and n == 1
    assert prov["source_origin"] == "CACHE"
    assert prov["source_observed_at_utc"] == t1.isoformat()
    assert prov["pit_provenance_status"] == "PIT_PROVENANCE_ESTABLISHED"


def test_schedule_provenance_unverifiable_cache_hit_refuses(
        tmp_path, monkeypatch):
    """A cache populated WITHOUT the provenance wrapper (any other
    consumer of the shared fetcher) carries no manifest entry: the
    original observation instant cannot be established, and the Elo
    leg refuses instead of producing a probability."""
    import pytest
    from datetime import datetime, timezone
    cap = _load_capture_cli()
    monkeypatch.setattr(cap, "SCHEDULE_CACHE_DIR", tmp_path)
    payload = {"dates": _one_game_dates()}
    # Populate the cache through the real shared fetcher directly.
    cap.fetch_mlb_schedule("2026-01-01", "2026-10-12",
                           getter=lambda url: payload,
                           cache_dir=tmp_path)
    assert not (tmp_path / cap.SCHEDULE_PROVENANCE_MANIFEST).exists()
    # The wrapper sees a cache hit with no verifiable observation.
    dates, fields, observed, read = cap._fetch_schedule_with_provenance(
        "2026-01-01", "2026-10-12")
    assert dates == payload["dates"]
    assert fields["source_origin"] == "CACHE"
    assert observed is None
    assert fields["source_observed_at_utc"] is None
    # And the Elo leg fails closed on it.
    kickoff = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(cap.fc.CaptureError,
                       match="ELO_SCHEDULE_PROVENANCE_UNESTABLISHED"):
        cap.elo_existing_probability(
            "Cleveland Guardians", "Tampa Bay Rays", "HOME", kickoff)


def test_schedule_provenance_late_http_observation_refuses(
        tmp_path, monkeypatch):
    """A FRESH HTTP fetch whose observation instant is at/after the
    target kickoff (the retrospective shape) refuses through the real
    wrapper: pre-cutoff availability cannot be established."""
    import pytest
    from datetime import datetime, timezone
    cap = _load_capture_cli()
    monkeypatch.setattr(cap, "SCHEDULE_CACHE_DIR", tmp_path)
    payload = {"dates": _one_game_dates()}
    monkeypatch.setattr(cap, "_default_schedule_getter",
                        lambda url: payload)
    late = datetime(2026, 10, 13, 0, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(cap, "_utcnow", lambda: late)
    kickoff = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(cap.fc.CaptureError,
                       match="ELO_SCHEDULE_PROVENANCE_UNESTABLISHED"):
        cap.elo_existing_probability(
            "Cleveland Guardians", "Tampa Bay Rays", "HOME", kickoff)


def test_schedule_provenance_exports_unfiltered_manifest_lookup_hash(
        tmp_path, monkeypatch):
    """Owner qualification (issue #2086): the provenance manifest is
    keyed by the hash of the UNFILTERED schedule payload, while
    schedule_content_sha256 covers the FILTERED training population.
    When the filter removes games the two differ, and the unfiltered
    lookup hash must be exported so an auditor can verify the
    manifest lookup that a cache hit rests on."""
    import hashlib
    import json
    from datetime import datetime, timezone
    cap = _load_capture_cli()
    monkeypatch.setattr(cap, "SCHEDULE_CACHE_DIR", tmp_path)
    cle, tb = "Cleveland Guardians", "Tampa Bay Rays"
    dates = [{"date": "2026-10-10", "games": [
        _typed_game(1, "2026-10-10T23:05:00Z", "R", cle, tb, 2, 5),
        _typed_game(2, "2026-03-10T18:05:00Z", "S", tb, cle, 0, 20),
    ]}]
    monkeypatch.setattr(cap, "_default_schedule_getter",
                        lambda url: {"dates": dates})
    t_obs = datetime(2026, 10, 12, 23, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(cap, "_utcnow", lambda: t_obs)
    kickoff = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    p, cutoff, n, p_home, pop, prov = cap.elo_existing_probability(
        cle, tb, "HOME", kickoff)
    assert n == 1  # only the R game trains; the S game was filtered

    def _canon(obj):
        return hashlib.sha256(json.dumps(
            obj, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")).hexdigest()

    # Lookup hash = FULL returned schedule (pre-filter); content
    # hash = filtered population only. Filtering removed a game, so
    # they must differ.
    assert prov["schedule_manifest_lookup_sha256"] == _canon(dates)
    filtered = [{"date": "2026-10-10", "games": [dates[0]["games"][0]]}]
    assert prov["schedule_content_sha256"] == _canon(filtered)
    assert (prov["schedule_manifest_lookup_sha256"]
            != prov["schedule_content_sha256"])
    # Age fields on a fresh HTTP observation under a frozen clock.
    assert prov["schedule_age_seconds"] == 0.0
    assert prov["schedule_freshness"] == "WITHIN_BOUND"
    # The manifest on disk is keyed by the exported lookup hash.
    manifest = json.loads(
        (tmp_path / cap.SCHEDULE_PROVENANCE_MANIFEST).read_text(
            encoding="utf-8"))
    assert prov["schedule_manifest_lookup_sha256"] in manifest
    entry = manifest[prov["schedule_manifest_lookup_sha256"]]
    assert entry["source_observed_at_utc"] == t_obs.isoformat()
    # A manifest lookup performed with the exported hash verifies a
    # later cache hit — the network getter must not run.
    def _boom(url):
        raise AssertionError("HTTP getter invoked on a cache hit")

    monkeypatch.setattr(cap, "_default_schedule_getter", _boom)
    dates2, fields2, observed2, read2 = \
        cap._fetch_schedule_with_provenance("2026-01-01", "2026-10-12")
    assert fields2["source_origin"] == "CACHE"
    assert (fields2["schedule_manifest_lookup_sha256"]
            == prov["schedule_manifest_lookup_sha256"])
    assert observed2 == t_obs


def test_schedule_freshness_cache_within_bound_accepted(
        tmp_path, monkeypatch):
    """Freshness policy (issue #2086): a verified cache observation
    within ELO_SCHEDULE_MAX_AGE_SECONDS of the consumer read is
    accepted as CACHE — no refresh is attempted (the network getter
    is rigged to explode) — and the age is exported."""
    from datetime import datetime, timedelta, timezone
    cap = _load_capture_cli()
    monkeypatch.setattr(cap, "SCHEDULE_CACHE_DIR", tmp_path)
    payload = {"dates": _one_game_dates()}
    clock = {"now": datetime(2026, 10, 12, 23, 30,
                             tzinfo=timezone.utc)}
    monkeypatch.setattr(cap, "_utcnow", lambda: clock["now"])
    monkeypatch.setattr(cap, "_default_schedule_getter",
                        lambda url: payload)
    cap._fetch_schedule_with_provenance("2026-01-01", "2026-10-12")
    # 10 minutes later: age 600s <= the 900s bound -> within bound.
    clock["now"] = clock["now"] + timedelta(seconds=600)

    def _boom(url):
        raise AssertionError("network touched for a within-bound "
                             "cache observation")

    monkeypatch.setattr(cap, "_default_schedule_getter", _boom)
    kickoff = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    p, cutoff, n, p_home, pop, prov = cap.elo_existing_probability(
        "Cleveland Guardians", "Tampa Bay Rays", "HOME", kickoff)
    assert 0.0 < p < 1.0 and n == 1
    assert prov["source_origin"] == "CACHE"
    assert prov["schedule_age_seconds"] == 600.0
    assert prov["schedule_freshness"] == "WITHIN_BOUND"
    assert prov["pit_provenance_status"] == "PIT_PROVENANCE_ESTABLISHED"


def test_schedule_freshness_stale_cache_refreshes_over_http(
        tmp_path, monkeypatch):
    """A verified cache observation OLDER than the bound forces one
    fresh HTTP re-observation through the recording getter: the
    probability is priced from the REFRESHED payload (origin HTTP,
    freshness REFRESHED), and the exported lookup hash re-keys to
    the refreshed payload."""
    import hashlib
    import json
    from datetime import datetime, timedelta, timezone
    cap = _load_capture_cli()
    monkeypatch.setattr(cap, "SCHEDULE_CACHE_DIR", tmp_path)
    clock = {"now": datetime(2026, 10, 12, 23, 0,
                             tzinfo=timezone.utc)}
    monkeypatch.setattr(cap, "_utcnow", lambda: clock["now"])
    stale_payload = {"dates": _one_game_dates()}
    monkeypatch.setattr(cap, "_default_schedule_getter",
                        lambda url: stale_payload)
    cap._fetch_schedule_with_provenance("2026-01-01", "2026-10-12")
    # 40 minutes later: age 2400s > the 900s bound -> stale.
    clock["now"] = clock["now"] + timedelta(seconds=2400)
    fresh_dates = _one_game_dates() + [{"date": "2026-10-11",
        "games": [{
            "gamePk": 824004, "gameDate": "2026-10-11T23:05:00Z",
            "gameType": "R", "status": {"detailedState": "Final"},
            "teams": {"away": {"team": {"name": "Tampa Bay Rays"},
                               "score": 1},
                      "home": {"team": {"name":
                                         "Cleveland Guardians"},
                               "score": 4}}}]}]
    calls = {"n": 0}

    def fresh_getter(url):
        calls["n"] += 1
        return {"dates": fresh_dates}

    monkeypatch.setattr(cap, "_default_schedule_getter", fresh_getter)
    kickoff = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    p, cutoff, n, p_home, pop, prov = cap.elo_existing_probability(
        "Cleveland Guardians", "Tampa Bay Rays", "HOME", kickoff)
    # Exactly one network fetch (the refresh); the first look was
    # served by the cache. The refreshed payload (2 games) trained,
    # not the stale one (1 game).
    assert calls["n"] == 1
    assert n == 2
    assert prov["source_origin"] == "HTTP"
    assert prov["schedule_freshness"] == "REFRESHED"
    assert prov["source_observed_at_utc"] == clock["now"].isoformat()
    assert prov["schedule_age_seconds"] == 0.0
    # The exported lookup hash keys the REFRESHED (unfiltered)
    # payload, and the manifest holds an entry under it.
    expected_lookup = hashlib.sha256(json.dumps(
        fresh_dates, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert prov["schedule_manifest_lookup_sha256"] == expected_lookup
    manifest = json.loads(
        (tmp_path / cap.SCHEDULE_PROVENANCE_MANIFEST).read_text(
            encoding="utf-8"))
    assert expected_lookup in manifest
    assert (manifest[expected_lookup]["source_observed_at_utc"]
            == clock["now"].isoformat())


def test_schedule_freshness_stale_cache_refresh_failure_refuses(
        tmp_path, monkeypatch):
    """A stale verified observation whose forced refresh FAILS
    refuses with ELO_SCHEDULE_PROVENANCE_UNESTABLISHED — the stale
    payload is never silently used."""
    import pytest
    from datetime import datetime, timedelta, timezone
    cap = _load_capture_cli()
    monkeypatch.setattr(cap, "SCHEDULE_CACHE_DIR", tmp_path)
    clock = {"now": datetime(2026, 10, 12, 23, 0,
                             tzinfo=timezone.utc)}
    monkeypatch.setattr(cap, "_utcnow", lambda: clock["now"])
    monkeypatch.setattr(cap, "_default_schedule_getter",
                        lambda url: {"dates": _one_game_dates()})
    cap._fetch_schedule_with_provenance("2026-01-01", "2026-10-12")
    # 40 minutes later the observation is stale, and the source is
    # now unavailable: the refresh yields no payload.
    clock["now"] = clock["now"] + timedelta(seconds=2400)
    monkeypatch.setattr(cap, "_default_schedule_getter",
                        lambda url: None)
    kickoff = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(cap.fc.CaptureError,
                       match="ELO_SCHEDULE_PROVENANCE_UNESTABLISHED") \
            as excinfo:
        cap.elo_existing_probability(
            "Cleveland Guardians", "Tampa Bay Rays", "HOME", kickoff)
    assert "stale" in str(excinfo.value)
