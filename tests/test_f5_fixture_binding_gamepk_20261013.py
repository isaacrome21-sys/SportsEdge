"""F5 gate-2.5 fixture binding tests (2026-10-13). Offline fixtures only.

Proves the in-run gamePk resolution seam
(sportsedge.mlb_f5_fixture_resolution.stamp_f5_game_pks, wired into
artifacts/run_it_full.py immediately before the F5 quote-binding
stage):

* a live StatsAPI schedule resolution keyed by the fixture's team
  names + stated first pitch stamps the verified gamePk onto F5 rows
  only, and the stamped rows pass the REAL binder
  (sportsedge.mlb_f5_quote_binding, unmodified) through fixture
  resolution, pairing and settlement basis, stopping only at the
  deployment eligibility gate F5_DEPLOYMENT_NOT_ELIGIBLE;
* a doubleheader is disambiguated by the board's stated first pitch
  (the binder's own 120s tolerance); ambiguity stamps nothing;
* a pre-claimed gamePk is never overwritten -- a wrong-fixture claim
  is refused by the binder's own fixture resolver verbatim;
* a StatsAPI failure stamps nothing, never raises, and leaves the
  run's other markets untouched;
* non-F5 rows pass through as the identical objects, unmutated.

The schedule/history fixtures mirror tests/test_mlb_f5_quote_binding.py
(synthetic strictly-prior linescores for team IDs 101/202).
"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest
import json

from sportsedge.mlb_f5_quote_binding import (
    F5_DEPLOYMENT_NOT_ELIGIBLE, F5_FIXTURE_BINDING_MISMATCH,
    F5_FIXTURE_BINDING_MISSING, bind_f5_quotes,
    make_statsapi_fixture_resolver, phone_f5_binding_rows)
from sportsedge.mlb_f5_fixture_resolution import (
    RESOLUTION_VERSION, stamp_f5_game_pks)

NOW = datetime(2026, 9, 14, 23, 0, tzinfo=timezone.utc)
GAME_PK = 777001
KICKOFF = "2026-09-14T23:10:00Z"
SLATE = "2026-09-14"

FIXTURE = {
    "game_pk": GAME_PK,
    "away_team_id": 101,
    "home_team_id": 202,
    "away_name": "Away Club",
    "home_name": "Home Club",
    "first_pitch_at": datetime(2026, 9, 14, 23, 10, tzinfo=timezone.utc),
    "official_date": "2026-09-14",
}


def _resolver(**_kwargs):
    return dict(FIXTURE)


def _game(game_pk, game_date, *, away_id=101, away_name="Away Club",
          home_id=202, home_name="Home Club", date=SLATE):
    return {
        "gamePk": game_pk, "gameDate": game_date, "officialDate": date,
        "status": {"abstractGameState": "Preview"},
        "teams": {
            "away": {"team": {"id": away_id, "name": away_name}},
            "home": {"team": {"id": home_id, "name": home_name}},
        },
    }


def _schedule(*games, date=SLATE):
    return {"dates": [{"date": date, "games": list(games)}]}


FIXTURE_SCHEDULE = _schedule(_game(GAME_PK, KICKOFF))


def _inning(num, away, home):
    return {"num": num, "away": {"runs": away}, "home": {"runs": home}}


def _history_payload(games=120):
    """Synthetic strictly-prior StatsAPI schedule (the binder battery's
    fixture shape): both fixture teams in every game, complete
    innings 1-5 linescores, all before 2026-09-14."""
    out = []
    for i in range(games):
        day = 1 + (i % 13)
        away_f5, home_f5 = i % 4, (i + 1) % 3
        innings = [_inning(1, away_f5, home_f5)] + [
            _inning(n, 0, 0) for n in range(2, 8)]
        out.append({
            "gamePk": 9000 + i,
            "gameDate": f"2026-09-{day:02d}T23:10:00Z",
            "officialDate": f"2026-09-{day:02d}",
            "status": {"abstractGameState": "Final"},
            "teams": {
                "away": {"team": {"id": 101}, "score": away_f5 + 3},
                "home": {"team": {"id": 202}, "score": home_f5 + 2},
            },
            "linescore": {"innings": innings},
        })
    return {"dates": [{"date": "2026-09-13", "games": out}]}


def _getter(schedule_payload=FIXTURE_SCHEDULE, *, fail_schedule=False):
    """Payload-style getter: the fixture date's schedule request gets
    the fixture slate; every other schedule request gets the history
    slate; anything else has no payload."""
    def getter(url):
        if "schedule" in url:
            if fail_schedule:
                raise OSError("STATSAPI_UNREACHABLE_SIMULATED")
            if f"date={SLATE}" in url:
                return schedule_payload
            return _history_payload()
        return None
    return getter


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _opener(schedule_payload=FIXTURE_SCHEDULE):
    getter = _getter(schedule_payload)

    def opener(url_or_request, timeout=15):
        url = getattr(url_or_request, "full_url", None) or str(url_or_request)
        payload = getter(url)
        if payload is None:
            raise OSError("NO_PAYLOAD")
        return _Response(payload)
    return opener


def _row(**over):
    """Intake-shaped F5 totals row: SOURCE + EVENT_ID stamps from the
    earlier extensions, deliberately NO game_pk."""
    base = {
        "sport": "MLB", "market": "F5_TOTALS", "book": "DraftKings",
        "event_id": "34817298", "away": "Away Club", "home": "Home Club",
        "kickoff": KICKOFF, "side": "OVER", "line": 4.5, "odds": -110,
        "quote_captured_at": "2026-09-14T22:59:00Z",
    }
    base.update(over)
    return base


def _totals_pair(**over):
    return [
        _row(**over),
        _row(side="UNDER", odds=-105,
             quote_captured_at="2026-09-14T22:59:30Z", **over),
    ]


# ------------------------------------------------------- (a) resolution

def test_single_match_stamps_verified_gamepk_with_provenance():
    rows = _totals_pair()
    out, receipts = stamp_f5_game_pks(rows, getter=_getter(), resolved_at=NOW)
    assert [r["game_pk"] for r in out] == [GAME_PK, GAME_PK]
    for stamped in out:
        prov = stamped["game_pk_provenance"]
        assert prov["source"] == "STATSAPI_SCHEDULE"
        assert prov["resolved_at"] == NOW.isoformat()
        assert prov["slate_date"] == SLATE
        assert prov["matched_first_pitch_at"] == "2026-09-14T23:10:00+00:00"
    (receipt,) = receipts
    assert receipt["source"] == RESOLUTION_VERSION
    assert receipt["status"] == "RESOLVED"
    assert receipt["game_pk"] == GAME_PK
    assert receipt["rows_stamped"] == 2
    # Inputs are never mutated.
    assert all("game_pk" not in r for r in rows)


def test_stamped_rows_pass_real_binder_to_bound_pair():
    out, _ = stamp_f5_game_pks(_totals_pair(), getter=_getter(),
                               resolved_at=NOW)
    bound = bind_f5_quotes(out, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    assert bound["pairs"][0]["fixture"]["game_pk"] == GAME_PK
    assert bound["pairs"][0]["settlement_basis"]["status"] == "VERIFIED"


def test_stamped_rows_stop_at_deployment_gate_through_stage():
    out, _ = stamp_f5_game_pks(_totals_pair(), getter=_getter(),
                               resolved_at=NOW)
    results, _ = phone_f5_binding_rows(out, now=NOW, opener=_opener())
    assert len(results) == 2
    for result in results:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["f5_reason"] == F5_DEPLOYMENT_NOT_ELIGIBLE
        assert result["blocker"] == "NO_VALIDATION"
        assert result["f5_deployment"]["stage"] == "F5_STATE_CANDIDATE"
        assert result["f5_deployment"]["eligible"] is False
        assert result["f5_binding"]["fixture"]["game_pk"] == GAME_PK
        assert "model_p" not in result


@pytest.mark.registry_lane_internals
def test_run_full_stamps_and_stops_at_deployment_gate():
    from artifacts.run_it_full import run_full
    card = run_full({"lines": _totals_pair(), "sport": "MLB"},
                    now=NOW, getter=_getter())
    evaluated = card["evaluated_rows"]
    assert len(evaluated) == 2
    for result in evaluated:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["f5_reason"] == F5_DEPLOYMENT_NOT_ELIGIBLE
        assert result["blocker"] == "NO_VALIDATION"
        assert result["f5_binding"]["fixture"]["game_pk"] == GAME_PK
    resolution = [r for r in card["source_receipts"]
                  if r.get("source") == RESOLUTION_VERSION]
    assert len(resolution) == 1
    assert resolution[0]["status"] == "RESOLVED"
    assert resolution[0]["game_pk"] == GAME_PK
    assert resolution[0]["rows_stamped"] == 2


def test_provenance_key_is_tolerated_by_the_binder():
    plain = _totals_pair()
    for r in plain:
        r["game_pk"] = GAME_PK
    stamped, _ = stamp_f5_game_pks(_totals_pair(), getter=_getter(),
                                   resolved_at=NOW)
    bound_plain = bind_f5_quotes(plain, now=NOW, fixture_resolver=_resolver)
    bound_stamped = bind_f5_quotes(stamped, now=NOW,
                                   fixture_resolver=_resolver)
    assert [r["status"] for r in bound_stamped["row_results"]] == \
        [r["status"] for r in bound_plain["row_results"]] == ["BOUND", "BOUND"]
    assert bound_stamped["pairs"][0]["quotes"] == \
        bound_plain["pairs"][0]["quotes"]


def test_all_four_f5_markets_stamp():
    rows = [
        _row(market="F5_MONEYLINE", side="AWAY", odds=100, line=None),
        _row(market="F5_MONEYLINE", side="HOME", odds=-130, line=None,
             quote_captured_at="2026-09-14T22:59:30Z"),
        _row(market="F5_RUN_LINE", side="AWAY", line=1.5, odds=110),
        _row(market="F5_RUN_LINE", side="HOME", line=-1.5, odds=-130,
             quote_captured_at="2026-09-14T22:59:30Z"),
        _row(market="F5_TEAM_TOTALS", team_side="HOME", line=2.5),
        _row(market="F5_TEAM_TOTALS", team_side="HOME", side="UNDER",
             line=2.5, quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    rows += _totals_pair()
    out, receipts = stamp_f5_game_pks(rows, getter=_getter(), resolved_at=NOW)
    assert all(r["game_pk"] == GAME_PK for r in out)
    assert receipts[0]["rows_stamped"] == len(rows)


def test_stamped_run_line_single_rung_reaches_deployment_gate():
    rows = [
        _row(market="F5_RUN_LINE", side="AWAY", line=1.5, odds=110),
        _row(market="F5_RUN_LINE", side="HOME", line=-1.5, odds=-130,
             quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    out, _ = stamp_f5_game_pks(rows, getter=_getter(), resolved_at=NOW)
    results, _ = phone_f5_binding_rows(out, now=NOW, opener=_opener())
    for result in results:
        assert result["f5_reason"] == F5_DEPLOYMENT_NOT_ELIGIBLE
        assert result["blocker"] == "NO_VALIDATION"


def test_run_line_ladder_stops_at_pairing_verbatim():
    """Originally (#2210) a multi-rung ladder was ONE binding group and
    stopped at F5_QUOTE_UNPAIRED. t126 composition with t121 (reviewer
    ruling 2026-10-13: the rung line is part of the pairing identity)
    supersedes that expectation: each rung binds as its own two-sided
    pair. Gate 2.5 stamping is still asserted unchanged."""
    rows = []
    for away_line, home_line in ((1.5, -1.5), (0.5, -0.5),
                                 (-0.5, 0.5), (-1.5, 1.5)):
        rows.append(_row(market="F5_RUN_LINE", side="AWAY",
                         line=away_line, odds=110))
        rows.append(_row(market="F5_RUN_LINE", side="HOME",
                         line=home_line, odds=-130,
                         quote_captured_at="2026-09-14T22:59:30Z"))
    out, _ = stamp_f5_game_pks(rows, getter=_getter(), resolved_at=NOW)
    assert all(r["game_pk"] == GAME_PK for r in out)
    bound = bind_f5_quotes(out, now=NOW, fixture_resolver=_resolver)
    results = bound["row_results"]
    assert [r["status"] for r in results] == ["BOUND"] * 8
    assert all(r.get("reason_code") is None for r in results)
    pair_ids = [r["pair_id"] for r in results]
    assert len(set(pair_ids)) == 4 and len(bound["pairs"]) == 4
    for k in range(0, 8, 2):  # each rung's AWAY/HOME rows share one pair
        assert pair_ids[k] == pair_ids[k + 1]


# --------------------------------------------------- (b) doubleheaders

DH_SCHEDULE = _schedule(
    _game(777101, "2026-09-14T19:10:00Z"),
    _game(777102, KICKOFF),
)


def test_doubleheader_disambiguated_by_stated_first_pitch():
    out, receipts = stamp_f5_game_pks(
        _totals_pair(), getter=_getter(DH_SCHEDULE), resolved_at=NOW)
    assert [r["game_pk"] for r in out] == [777102, 777102]
    assert receipts[0]["status"] == "RESOLVED"
    assert receipts[0]["candidates_matched"] == 2
    assert receipts[0]["basis"] == "FIRST_PITCH_DISAMBIGUATION"


def test_doubleheader_first_game_stamps_first_gamepk():
    early = "2026-09-14T19:10:00Z"
    rows = _totals_pair(kickoff=early)
    rows[0]["quote_captured_at"] = "2026-09-14T18:59:00Z"
    rows[1]["quote_captured_at"] = "2026-09-14T18:59:30Z"
    out, _ = stamp_f5_game_pks(rows, getter=_getter(DH_SCHEDULE),
                                resolved_at=NOW)
    assert [r["game_pk"] for r in out] == [777101, 777101]


def test_doubleheader_neither_pitch_in_tolerance_stamps_nothing():
    rows = _totals_pair(kickoff="2026-09-14T21:10:00Z")
    out, receipts = stamp_f5_game_pks(
        rows, getter=_getter(DH_SCHEDULE), resolved_at=NOW)
    assert all("game_pk" not in r for r in out)
    assert receipts[0]["status"] == "AMBIGUOUS"
    bound = bind_f5_quotes(out, now=NOW, fixture_resolver=_resolver)
    assert [r.get("reason_code") for r in bound["row_results"]] == \
        [F5_FIXTURE_BINDING_MISSING] * 2


def test_doubleheader_equidistant_within_tolerance_stamps_nothing():
    schedule = _schedule(
        _game(777103, "2026-09-14T23:09:00Z"),
        _game(777104, "2026-09-14T23:11:00Z"),
    )
    out, receipts = stamp_f5_game_pks(
        _totals_pair(), getter=_getter(schedule), resolved_at=NOW)
    assert all("game_pk" not in r for r in out)
    assert receipts[0]["status"] == "AMBIGUOUS"


# ------------------------------------------- (c) wrong-gamePk hostiles

def test_preclaimed_gamepk_is_never_overwritten():
    rows = _totals_pair()
    for r in rows:
        r["game_pk"] = GAME_PK
    out, receipts = stamp_f5_game_pks(rows, getter=_getter(), resolved_at=NOW)
    assert out[0] is rows[0] and out[1] is rows[1]
    assert receipts[0]["status"] == "PREEXISTING_GAME_PK"
    assert receipts[0]["rows_stamped"] == 0


def test_wrong_fixture_claim_refused_by_binder_resolver_verbatim():
    other = _game(777555, KICKOFF, away_id=303, away_name="Other Club",
                  home_id=404, home_name="Another Club")
    schedule = _schedule(_game(GAME_PK, KICKOFF), other)
    resolver = make_statsapi_fixture_resolver(opener=_opener(schedule))
    rows = _totals_pair()
    for r in rows:
        r["game_pk"] = 777555  # a real gamePk -- for a different fixture
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=resolver)
    assert [r.get("reason_code") for r in bound["row_results"]] == \
        [F5_FIXTURE_BINDING_MISMATCH] * 2


def test_unknown_claimed_gamepk_refused_by_binder_resolver_verbatim():
    resolver = make_statsapi_fixture_resolver(opener=_opener())
    rows = _totals_pair()
    for r in rows:
        r["game_pk"] = 777999  # not on the official schedule at all
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=resolver)
    assert [r.get("reason_code") for r in bound["row_results"]] == \
        [F5_FIXTURE_BINDING_MISSING] * 2


# ------------------------------------------------------ (d) API failure

def test_statsapi_failure_stamps_nothing_and_never_raises():
    rows = _totals_pair()
    out, receipts = stamp_f5_game_pks(
        rows, getter=_getter(fail_schedule=True), resolved_at=NOW)
    assert out[0] is rows[0] and out[1] is rows[1]
    assert all("game_pk" not in r for r in out)
    assert receipts[0]["status"] == "FETCH_FAILED"
    assert "STATSAPI_UNREACHABLE_SIMULATED" in receipts[0]["detail"]


@pytest.mark.registry_lane_internals
def test_statsapi_failure_run_continues_other_markets_unaffected():
    from artifacts.run_it_full import run_full
    rows = _totals_pair() + [{
        "sport": "MLB", "market": "PITCHER_K", "player_name": "Some Arm",
        "side": "OVER", "line": 6.5, "odds": -110, "kickoff": KICKOFF,
        "quote_captured_at": "2026-09-14T22:59:00Z",
    }]
    card = run_full({"lines": rows, "sport": "MLB"}, now=NOW,
                    getter=_getter(fail_schedule=True))
    evaluated = card["evaluated_rows"]
    assert len(evaluated) == 3
    for result in evaluated[:2]:
        assert result["f5_reason"] == F5_FIXTURE_BINDING_MISSING
    # The non-F5 row resolved through its own stage, not the F5 gate.
    assert evaluated[2].get("f5_reason") is None
    resolution = [r for r in card["source_receipts"]
                  if r.get("source") == RESOLUTION_VERSION]
    assert resolution[0]["status"] == "FETCH_FAILED"


# -------------------------------------------------- (e) scope / no-ops

def test_non_f5_rows_pass_through_identical():
    game_row = {"sport": "MLB", "market": "MONEYLINE", "away": "Away Club",
                "home": "Home Club", "kickoff": KICKOFF, "side": "HOME",
                "odds": -120, "quote_captured_at": "2026-09-14T22:59:00Z"}
    nrfi_row = {"sport": "MLB", "market": "NRFI", "away": "Away Club",
                "home": "Home Club", "kickoff": KICKOFF, "side": "UNDER",
                "line": 0.5, "odds": -135,
                "quote_captured_at": "2026-09-14T22:59:00Z"}
    rows = [game_row] + _totals_pair() + [nrfi_row]
    out, _ = stamp_f5_game_pks(rows, getter=_getter(), resolved_at=NOW)
    assert out[0] is game_row and out[3] is nrfi_row
    assert "game_pk" not in game_row and "game_pk" not in nrfi_row
    assert out[1]["game_pk"] == GAME_PK and out[2]["game_pk"] == GAME_PK


def test_zero_matches_stamps_nothing():
    rows = _totals_pair(away="Nowhere Club", home="Home Club")
    out, receipts = stamp_f5_game_pks(rows, getter=_getter(), resolved_at=NOW)
    assert all("game_pk" not in r for r in out)
    assert receipts[0]["status"] == "NO_MATCH"


def test_missing_fixture_context_stamps_nothing():
    row = _row()
    del row["kickoff"]
    out, receipts = stamp_f5_game_pks([row], getter=_getter(), resolved_at=NOW)
    assert "game_pk" not in out[0]
    assert receipts[0]["status"] == "NO_FIXTURE_CONTEXT"

    row = _row(kickoff="2026-09-14T23:10:00")  # naive: refuses to bind
    out, receipts = stamp_f5_game_pks([row], getter=_getter(), resolved_at=NOW)
    assert "game_pk" not in out[0]
    assert receipts[0]["status"] == "NO_FIXTURE_CONTEXT"


@pytest.mark.registry_lane_internals
def test_no_fetch_mode_equivalence_rows_keep_stopping_at_gate():
    """auto_context off = no resolution attempted = today's behavior:
    run_full's F5 rows carry no gamePk and stop at gate 2.5."""
    from artifacts.run_it_full import run_full
    rows = _totals_pair()  # book + event_id present; no game_pk anywhere
    card = run_full({"lines": rows, "sport": "MLB"}, now=NOW,
                    auto_context=False)
    for result in card["evaluated_rows"]:
        assert result["f5_reason"] == F5_FIXTURE_BINDING_MISSING
    assert not [r for r in card["source_receipts"]
                if r.get("source") == RESOLUTION_VERSION]
