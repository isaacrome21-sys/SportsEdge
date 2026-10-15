"""CFB QB passing research annex on the canonical RUN IT card (Oct 14 2026).

Covers: the pre-pricing stage's Form 2 verdict pass-through (additive,
behavior-neutral), the card annex's identity discipline (identity only
from the runner's seam state; NOT_ESTABLISHED with the seam's reason
and NO distribution otherwise), the satisfied-identity population path
(Form 2 Collins fixture), preservation of the distribution builder's
own refusals, the registry terminal state staying attached and
unchanged, and the code health of the other registered CFB families'
research pricing paths. Synthetic/recorded fixtures only -- no
network.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.prepricing import factor_ingestion as fi  # noqa: E402
from sportsedge.prepricing.qb_identity_evidence import (  # noqa: E402
    AVAILABILITY_UNVERIFIED, STATUS_SATISFIED)
from sportsedge.registry_gate import PRICING_KEYS  # noqa: E402
from sportsedge.research.cfb_qb_card_annex import (  # noqa: E402
    IDENTITY_ESTABLISHED, IDENTITY_NOT_ESTABLISHED,
    build_cfb_research_projections)

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
NOW = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)
KICKOFF_ISO = "2026-10-13T23:00:00Z"


# ---------------------------------------------------------------------------
# Stage pass-through: the stage records the evaluator verdict it consumed
# ---------------------------------------------------------------------------

class _FakeGetter:
    def __init__(self, mapping):
        self.mapping = dict(mapping)

    def __call__(self, url):
        if url not in self.mapping:
            raise OSError("UNMAPPED_URL:" + url)
        return self.mapping[url]


def _stage_mapping():
    teams = {"sports": [{"leagues": [{"teams": [
        {"team": {"id": "48", "displayName": "Delaware Blue Hens",
                  "name": "Blue Hens", "shortDisplayName": "Delaware",
                  "abbreviation": "DEL", "location": "Delaware"}},
        {"team": {"id": "2393", "displayName": "Middle Tennessee Blue Raiders",
                  "name": "Blue Raiders", "shortDisplayName": "Middle Tennessee",
                  "abbreviation": "MTSU", "location": "Middle Tennessee"}},
    ]}]}]}
    scoreboard = {"events": [{
        "id": "401871067", "date": KICKOFF_ISO,
        "competitions": [{
            "id": "401871067",
            "competitors": [
                {"homeAway": "home",
                 "team": {"id": "2393", "abbreviation": "MTSU",
                          "displayName": "Middle Tennessee Blue Raiders"}},
                {"homeAway": "away",
                 "team": {"id": "48", "abbreviation": "DEL",
                          "displayName": "Delaware Blue Hens"}}],
            "venue": {"indoor": False, "fullName": "Johnny Red Floyd Stadium",
                      "address": {"city": "Murfreesboro", "state": "TN"}},
        }],
    }]}
    league = {"timestamp": "2026-10-13T12:00:41Z", "status": "success",
              "season": {"year": 2026, "type": 2},
              "injuries": [{"id": "57", "displayName": "Florida Gators",
                            "injuries": []}]}
    return {
        f"{ESPN}/football/college-football/teams?limit=500": teams,
        f"{ESPN}/football/college-football/scoreboard?dates=20261012&limit=500": {"events": []},
        f"{ESPN}/football/college-football/scoreboard?dates=20261013&limit=500": scoreboard,
        f"{ESPN}/football/college-football/scoreboard?dates=20261014&limit=500": {"events": []},
        f"{ESPN}/football/college-football/teams/48/injuries": {},
        f"{ESPN}/football/college-football/teams/2393/injuries": {},
        f"{ESPN}/football/college-football/injuries": league,
    }


def _verdict(team_id, athlete_id, name):
    return {"ok": True, "status": STATUS_SATISFIED,
            "detail": "UNIQUE_QB_RESOLUTION",
            "resolved_athlete_id": athlete_id, "resolved_athlete_name": name,
            "availability_status": AVAILABILITY_UNVERIFIED,
            "injury_points": 0.0,
            "receipt": {"team_id": team_id, "event_id": "401871067",
                        "opponent_espn_id": "2393" if team_id == "48" else "48"}}


def test_stage_records_form2_verdicts_by_side(monkeypatch):
    def fake_consult(bundles, provider, sport, team, kickoff, now,
                     receipts, *, event_id=None, home_team_id=None,
                     away_team_id=None):
        tid = str(team.get("id"))
        result = _verdict(tid, "5153846" if tid == "48" else "5194626",
                          "Delaware QB" if tid == "48" else "MTSU QB")
        receipts.append({"source": "QB_IDENTITY_EVIDENCE_FORM2",
                         "status": result["status"], "detail": result["detail"]})
        return result

    monkeypatch.setattr(fi, "_consult_qb_form2", fake_consult)
    row = {"sport": "CFB", "market": "SPREAD", "away": "Delaware Blue Hens",
           "home": "Middle Tennessee Blue Raiders", "side": "HOME",
           "line": -1.5, "odds": -110, "commence_time": KICKOFF_ISO,
           "quote_captured_at": NOW.isoformat()}
    (stage,) = fi.stage_games([row], now=NOW, getter=_FakeGetter(_stage_mapping()),
                              qb_form2_bundles={"48": {}, "2393": {}})
    identities = stage["qb_form2_identities"]
    assert set(identities) == {"HOME", "AWAY"}
    assert identities["AWAY"]["resolved_athlete_id"] == "5153846"
    assert identities["AWAY"]["status"] == STATUS_SATISFIED
    assert identities["AWAY"]["availability_status"] == AVAILABILITY_UNVERIFIED
    assert identities["AWAY"]["event_id"] == "401871067"
    # The gate's own behavior is untouched by the recording.
    assert stage["availability_status"] == AVAILABILITY_UNVERIFIED
    assert stage["adjustments"]["away_injury_pts"] == 0.0


def test_stage_without_bundles_records_no_identities():
    row = {"sport": "CFB", "market": "SPREAD", "away": "Delaware Blue Hens",
           "home": "Middle Tennessee Blue Raiders", "side": "HOME",
           "line": -1.5, "odds": -110, "commence_time": KICKOFF_ISO,
           "quote_captured_at": NOW.isoformat()}
    (stage,) = fi.stage_games([row], now=NOW,
                              getter=_FakeGetter(_stage_mapping()))
    assert stage["qb_form2_identities"] == {}


# ---------------------------------------------------------------------------
# Annex identity discipline
# ---------------------------------------------------------------------------

GATE_ROW = {
    "status": "NO_MODEL_OR_MARKET",
    "reason": "FAMILY_REGISTRY_NOT_VALIDATED: family registry state "
              "BLOCKED, validation UNVALIDATED",
    "blocker": "NO_VALIDATION", "registry_enforced": True,
    "family_decision": {"market": "player_passing_yards", "state": "BLOCKED",
                        "blocker": "NO_VALIDATION",
                        "reason": "FAMILY_REGISTRY_NOT_VALIDATED",
                        "validation_status": "UNVALIDATED",
                        "evaluation_scope": "FORWARD_ONLY"},
}

GAME = {"sport": "CFB", "away": "Kennesaw State", "home": "Missouri State",
        "market": "ML"}
STAGE_KO = "2026-10-14T23:30:00+00:00"


def _ladder_rows(player="Rickie Collins", thresholds=(150, 226, 340)):
    rows, evaluated = [], []
    for t in thresholds:
        rows.append({"sport": "CFB", "away": "Kennesaw State",
                     "home": "Missouri State", "market": "PLAYER_PASSING_YARDS",
                     "player_name": player, "milestone_threshold": t,
                     "side": "OVER", "line": t - 0.5,
                     "kickoff": "2026-10-14T18:30:00-05:00"})
        evaluated.append(dict(GATE_ROW))
    return rows, evaluated


def _collins_records(n=12):
    base = [(34, 24, 293, 35, 30), (24, 15, 129, 34, 30), (34, 22, 189, 35, 32),
            (35, 22, 260, 38, 30), (23, 18, 171, 34, 30), (25, 14, 85, 39, 31),
            (29, 17, 224, 40, 32), (31, 18, 126, 41, 30), (45, 28, 279, 46, 33),
            (37, 23, 229, 39, 31), (8, 5, 34, 39, 30), (6, 4, 65, 37, 32)]
    return [{"event_id": f"E{i}", "game_date_utc": f"2026-0{9 + (i // 6)}-"
             f"{3 + i:02d}T23:00:00+00:00" if i < 6 else f"2025-11-"
             f"{8 - (i - 6):02d}T23:00:00+00:00",
             "qb_team": "Kennesaw State Owls",
             "qb_attempts": float(a), "qb_completions": float(c),
             "qb_passing_yards": float(y), "team_pass_attempts": float(pa),
             "team_rush_attempts": float(ra)}
            for i, (a, c, y, pa, ra) in enumerate(base[:n])]


def _satisfied_stage():
    verdict = {"team_id": "338", "ok": True, "status": STATUS_SATISFIED,
               "detail": "UNIQUE_QB_RESOLUTION",
               "resolved_athlete_id": "4870645",
               "resolved_athlete_name": "Rickie Collins",
               "availability_status": AVAILABILITY_UNVERIFIED,
               "injury_points": 0.0, "event_id": "401871054",
               "opponent_espn_id": "2623"}
    return [{"kickoff_utc": STAGE_KO, "qb_form2_identities": {"AWAY": verdict}}]


def _annex(rows, evaluated, stages, **kw):
    args = {"rows": rows, "evaluated": evaluated, "games": [GAME],
            "stages": stages, "as_of_utc": "2026-10-14T21:06:18Z"}
    args.update(kw)
    return build_cfb_research_projections(**args)


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def test_annex_tonight_state_pin_absent_no_distribution():
    rows, evaluated = _ladder_rows()
    audit = {"pin_status": "ABSENT", "admitted_team_ids": [],
             "entries": [{"disposition": "EXCLUDED",
                          "reason": "ARCHIVE_PIN_REQUIRED",
                          "detail": "NO_EXTERNAL_PIN_SUPPLIED; "
                                    "FORM2_ADMISSION_DISABLED"}]}
    annex = _annex(rows, evaluated,
                   [{"kickoff_utc": STAGE_KO, "qb_form2_identities": {}}],
                   form2_loader_audit=audit)
    (entry,) = annex["projections"]
    assert entry["identity"]["state"] == IDENTITY_NOT_ESTABLISHED
    assert "ARCHIVE_PIN_REQUIRED" in entry["identity"]["detail"]
    assert entry["distribution"] is None
    assert entry["distribution_state"] == "NOT_BUILT_IDENTITY_NOT_ESTABLISHED"
    assert entry["terminal_registry_state"]["blocker"] == "NO_VALIDATION"
    assert entry["terminal_registry_state"]["evaluation_scope"] == "FORWARD_ONLY"
    assert entry["ladder_thresholds"] == [150, 226, 340]
    assert annex["section_label"] == "RESEARCH_ONLY"
    assert not (set(_walk_keys(annex)) & set(PRICING_KEYS))


def test_annex_composite_admitted_but_not_consulted():
    # #2278 shape: pins verified, bundles admitted, but the stage
    # recorded no verdict for the fixture (Form 2 never consulted --
    # e.g. a feed-covered team is Form 1 territory). Admission is not
    # the blocker, and no distribution may appear.
    rows, evaluated = _ladder_rows()
    audit = {"pin_status": "VERIFIED", "directory_status": "OK",
             "admitted_team_ids": ["2623", "338"],
             "manifest_sha256s": ["a" * 64, "b" * 64],
             "entries": [{"disposition": "ADMITTED", "reason": None,
                          "team_id": "338", "manifest_sha256": "a" * 64}]}
    annex = _annex(rows, evaluated,
                   [{"kickoff_utc": STAGE_KO, "qb_form2_identities": {}}],
                   form2_loader_audit=audit)
    (entry,) = annex["projections"]
    assert entry["identity"]["state"] == IDENTITY_NOT_ESTABLISHED
    assert entry["identity"]["detail"] == \
        "FORM2_ADMITTED_BUT_NOT_CONSULTED_FOR_FIXTURE"
    assert entry["distribution"] is None


def test_annex_composite_pin_refusal_surfaces():
    # #2278 all-or-none: one bad pin refuses the whole composite; the
    # annex names the composite refusal, not a generic pin absence.
    rows, evaluated = _ladder_rows()
    audit = {"pin_status": "UNVERIFIED", "directory_status": "OK",
             "admitted_team_ids": [],
             "entries": [{"disposition": "EXCLUDED",
                          "reason": "ARCHIVE_COMPOSITE_PIN_UNVERIFIED",
                          "detail": "ONE_OR_MORE_EXTERNAL_MANIFESTS_FAILED_"
                                    "ADMISSION; ENTIRE_COMPOSITE_REFUSED"}]}
    annex = _annex(rows, evaluated,
                   [{"kickoff_utc": STAGE_KO, "qb_form2_identities": {}}],
                   form2_loader_audit=audit)
    (entry,) = annex["projections"]
    assert entry["identity"]["state"] == IDENTITY_NOT_ESTABLISHED
    assert entry["identity"]["detail"].startswith(
        "ARCHIVE_COMPOSITE_PIN_UNVERIFIED")
    assert entry["distribution"] is None


def test_annex_failed_verdict_named_no_distribution():
    rows, evaluated = _ladder_rows()
    failed = {"team_id": "338", "ok": False, "status": "QB_DEPTH_EVIDENCE_STALE",
              "detail": "STALE", "resolved_athlete_id": None,
              "resolved_athlete_name": None, "availability_status": None,
              "injury_points": 0.0, "event_id": None, "opponent_espn_id": None}
    annex = _annex(rows, evaluated,
                   [{"kickoff_utc": STAGE_KO,
                     "qb_form2_identities": {"AWAY": failed}}])
    (entry,) = annex["projections"]
    assert entry["identity"]["state"] == IDENTITY_NOT_ESTABLISHED
    assert "QB_DEPTH_EVIDENCE_STALE" in entry["identity"]["detail"]
    assert entry["distribution"] is None


def test_annex_resolved_qb_differs_from_ladder_player():
    # The morning WKU shape: the seam resolved Glenn; the ladder named
    # another QB. No distribution may be built for the ladder player.
    rows, evaluated = _ladder_rows(player="Rodney Tisdale")
    annex = _annex(rows, evaluated, _satisfied_stage())
    (entry,) = annex["projections"]
    assert entry["identity"]["state"] == IDENTITY_NOT_ESTABLISHED
    assert entry["identity"]["detail"].startswith(
        "RESOLVED_QB_DIFFERS_FROM_LADDER_PLAYER")
    assert entry["distribution"] is None


def test_annex_satisfied_identity_builds_distribution():
    rows, evaluated = _ladder_rows()
    annex = _annex(rows, evaluated, _satisfied_stage(),
                   prior_games_provider=lambda **kw: (_collins_records(), []))
    (entry,) = annex["projections"]
    assert entry["identity"]["state"] == IDENTITY_ESTABLISHED
    assert entry["identity"]["athlete_id"] == "4870645"
    assert entry["availability_status"] == AVAILABILITY_UNVERIFIED
    assert entry["distribution_state"] == "BUILT"
    dist = entry["distribution"]
    assert dist["prior_game_count"] == 12
    assert 150.0 < dist["mean_yards"] < 200.0
    assert dist["sd_yards"] > 50.0
    assert set(dist["quantiles_yards"]) == {"p5", "p25", "p50", "p75", "p95"}
    assert entry["starter_certainty"]["mixture_status"] == \
        "NOT_CONSTRUCTED_REPLACEMENT_POOL_UNKNOWN"
    assert entry["terminal_registry_state"]["reason"].startswith(
        "FAMILY_REGISTRY_NOT_VALIDATED")
    assert not (set(_walk_keys(annex)) & set(PRICING_KEYS))


def test_annex_builder_refusal_preserved_by_name():
    rows, evaluated = _ladder_rows()
    annex = _annex(rows, evaluated, _satisfied_stage(),
                   prior_games_provider=lambda **kw: (_collins_records(3), []))
    (entry,) = annex["projections"]
    assert entry["identity"]["state"] == IDENTITY_ESTABLISHED
    assert entry["distribution_state"] == "REFUSED"
    assert entry["distribution_refusal"].startswith(
        "QB_DISTRIBUTION_INSUFFICIENT_PIT_HISTORY:3")
    assert entry["distribution"] is None


def test_annex_no_fetch_never_assembles():
    rows, evaluated = _ladder_rows()
    annex = _annex(rows, evaluated, _satisfied_stage(), fetch_enabled=False)
    (entry,) = annex["projections"]
    assert entry["distribution_state"] == "NOT_BUILT"
    assert entry["distribution_refusal"] == \
        "PRIOR_GAME_ASSEMBLY_REQUIRES_FETCH_DISABLED_IN_NO_FETCH_MODE"
    assert entry["distribution"] is None


def test_annex_illinois_fixture_refused_by_builder():
    rows, evaluated = _ladder_rows()
    for r in rows:
        r["home"] = "Illinois Fighting Illini"
    game = dict(GAME, home="Illinois Fighting Illini")
    annex = build_cfb_research_projections(
        rows=rows, evaluated=evaluated, games=[game],
        stages=_satisfied_stage(), as_of_utc="2026-10-14T21:06:18Z",
        prior_games_provider=lambda **kw: (_collins_records(), []))
    (entry,) = annex["projections"]
    assert entry["distribution_state"] == "REFUSED"
    assert entry["distribution_refusal"] == "ILLINOIS_COLLEGE_EXCLUDED"


# ---------------------------------------------------------------------------
# Runner level: the card gains the annex; terminal states unchanged
# ---------------------------------------------------------------------------

def test_runner_card_carries_annex_and_rows_stay_gated():
    from artifacts.run_it_full import run_full
    lines = [
        {"sport": "CFB", "away": "Kennesaw State", "home": "Missouri State",
         "market": "MONEYLINE", "side": "AWAY", "odds": -142,
         "kickoff": "2026-10-14T18:30:00-05:00",
         "quote_captured_at": "2026-10-14T23:01:00Z"},
        {"sport": "CFB", "away": "Kennesaw State", "home": "Missouri State",
         "market": "PLAYER_PASSING_YARDS", "player_name": "Rickie Collins",
         "book": "draftkings", "kickoff": "2026-10-14T18:30:00-05:00",
         "quote_captured_at": "2026-10-14T23:01:00Z",
         "milestone_ladder": {"form": "X_PLUS", "rungs": [
             {"threshold": 150, "odds": -690}, {"threshold": 226, "odds": -117},
             {"threshold": 340, "odds": 1080}]}},
    ]
    card = run_full({"lines": lines}, auto_context=False,
                    as_of="2026-10-14T23:03:00Z")
    annex = card["cfb_research_projections"]
    (entry,) = annex["projections"]
    assert entry["identity"]["state"] == IDENTITY_NOT_ESTABLISHED
    assert entry["identity"]["detail"] == "FORM2_NOT_CONFIGURED_FOR_RUN"
    assert entry["distribution"] is None
    cfb_rows = [r for r in card["evaluated_rows"] if r.get("sport") == "CFB"]
    assert cfb_rows and all(
        r["status"] == "NO_MODEL_OR_MARKET" for r in cfb_rows)
    assert all("FAMILY_REGISTRY_NOT_VALIDATED" in str(r.get("reason"))
               for r in cfb_rows)
    assert card["edges"] == [] and card["prop_candidates"] == []


def test_runner_without_cfb_passing_rows_has_no_annex():
    from artifacts.run_it_full import run_full
    lines = [{"sport": "MLB", "away": "Milwaukee Brewers",
              "home": "Los Angeles Dodgers", "market": "MONEYLINE",
              "side": "AWAY", "odds": 155,
              "kickoff": "2026-10-14T19:00:00-05:00",
              "quote_captured_at": "2026-10-14T23:03:00Z"}]
    card = run_full({"lines": lines}, auto_context=False,
                    as_of="2026-10-14T23:03:00Z")
    assert "cfb_research_projections" not in card


# ---------------------------------------------------------------------------
# Family code health: the other registered families' research paths
# ---------------------------------------------------------------------------

_HEALTHY_STATUSES = {
    "WATCH_BELOW_EV_FLOOR", "WATCH_PLAYER_PARTICIPATION_UNVERIFIED",
    "WATCH_QUOTE_NOT_CURRENT", "WATCH_PRICE_CAP",
    "RESEARCH_CANDIDATE_NOT_VALIDATED",
}

_FAMILY_LINES = {
    "PLAYER_PASSING_YARDS": 199.5, "PLAYER_PASS_TDS": 1.5,
    "PLAYER_PASS_ATTEMPTS": 27.5, "PLAYER_COMPLETIONS": 17.5,
    "PLAYER_PASS_INTERCEPTIONS": 0.5, "PLAYER_RUSHING_YARDS": 29.5,
    "PLAYER_RUSH_ATTEMPTS": 6.5, "PLAYER_RECEIVING_YARDS": 9.5,
    "PLAYER_RECEPTIONS": 1.5, "PLAYER_RUSH_PLUS_REC_YARDS": 39.5,
    "PLAYER_PASS_PLUS_RUSH_YARDS": 229.5,
}

_HISTORY = [
    {"passing_yards": v, "passing_tds": t, "pass_attempts": a,
     "completions": c, "interceptions": i, "rushing_yards": ry,
     "rush_attempts": ra, "receiving_yards": ey, "receptions": rc}
    for v, t, a, c, i, ry, ra, ey, rc in [
        (210, 2, 30, 19, 1, 24, 6, 0, 0), (165, 1, 26, 15, 0, 41, 8, 12, 1),
        (288, 3, 35, 24, 1, 12, 4, 0, 0), (132, 0, 22, 12, 2, 55, 9, 30, 3),
        (244, 2, 31, 20, 0, 18, 5, 8, 1), (190, 1, 28, 17, 1, 33, 7, 22, 2)]]


@pytest.mark.parametrize("market,line", sorted(_FAMILY_LINES.items()))
def test_registered_family_research_path_executes(market, line, monkeypatch):
    import sportsedge.cfb_phone_player_pricing as pricing

    verified = {
        "game_id": "401871054", "player_id": "4870645",
        "player_name": "Test QB", "home_team": "Missouri State",
        "away_team": "Kennesaw State",
        "kickoff_utc": "2026-10-14T23:30:00+00:00",
        "features": {"game_history": _HISTORY},
        "explicit_stat_fields": sorted(_HISTORY[0]),
        "schema_rejected_prior_events": 0,
        "source_endpoint": "STUB", "prior_game_count": len(_HISTORY),
    }

    class _StubSource:
        def __init__(self, *, getter=None):
            pass

        def prior_games(self, **kw):
            return verified

    monkeypatch.setattr(pricing, "CFBPlayerPublicSource", _StubSource)
    now = datetime(2026, 10, 14, 23, 0, tzinfo=timezone.utc)

    def row(side):
        return {"sport": "CFB", "away": "Kennesaw State",
                "home": "Missouri State", "market": market,
                "player_name": "Test QB", "side": side, "line": line,
                "odds": -110, "book": "draftkings",
                "kickoff": "2026-10-14T18:30:00-05:00",
                "quote_captured_at": "2026-10-14T22:59:30+00:00"}

    outputs, _receipts = pricing.phone_cfb_player_rows(
        [row("OVER"), row("UNDER")], now=now, getter=None)
    assert len(outputs) == 2
    for out in outputs:
        assert out["status"] in _HEALTHY_STATUSES, (market, out)
