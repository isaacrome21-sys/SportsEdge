from sportsedge.canonical_manual_mlb import CanonicalManualMLBError, _resolve_subject, run_canonical_manual_mlb
from sportsedge.engine_registry import resolve_manual_market_type
from sportsedge.mlb_lines_intake import LinesIntakeError, parse_lines
from sportsedge.mlb_pitcher_subject import resolve_pitcher_subject
from sportsedge.mlb_resolve import build_bound_input
from sportsedge.mlb_source import GameSnapshot
from sportsedge.manual_quote import validate_manual_quote
import pytest


def _game() -> GameSnapshot:
    return GameSnapshot(
        game_pk=849841,
        game_date="2026-09-30T18:00:00+00:00",
        status="Scheduled",
        away_id=143,
        away_name="Philadelphia Phillies",
        home_id=144,
        home_name="Atlanta Braves",
        away_probable_pitcher_id=661563,
        away_probable_pitcher_name="Cristopher Sánchez",
        home_probable_pitcher_id=641835,
        home_probable_pitcher_name="Tyler Mahle",
        retrieved_at="2026-09-30T10:47:51+00:00",
        official_date="2026-09-30",
    )


def _quote(market_type: str, name: str, line: float, price: int, paired_price: int) -> dict:
    return {
        "game_id": "Philadelphia Phillies@Atlanta Braves",
        "market_type": market_type,
        "side": "OVER",
        "line": line,
        "price": price,
        "paired_side": "UNDER",
        "paired_price": paired_price,
        "book": "draftkings",
        "observed_at": "2026-09-30T10:47:51+00:00",
        "first_pitch_at": "2026-09-30T18:00:00+00:00",
        "source": "MANUAL",
        "subject_name": name,
    }


def test_outs_and_k_names_survive_bind() -> None:
    text = """Phillies @ Braves
Cristopher Sanchez outs 17.5 -174 +130
Tyler Mahle k 5.5 -110 -110
"""
    bound = build_bound_input(
        text,
        observed_at="2026-09-30T10:47:51+00:00",
        schedule=[_game()],
    )
    outs = next(r for r in bound["rows"] if resolve_manual_market_type(r["market_type"]) == "PITCHER_OUTS")
    ks = next(r for r in bound["rows"] if resolve_manual_market_type(r["market_type"]) == "PITCHER_K")
    assert outs["subject_name"] == "Cristopher Sanchez"
    assert ks["subject_name"] == "Tyler Mahle"
    assert outs["paired_side"] == "UNDER" and ks["paired_side"] == "UNDER"
    parsed = parse_lines(text)
    assert {resolve_manual_market_type(r.market_type) for r in parsed} == {"PITCHER_OUTS", "PITCHER_K"}


def test_two_sided_prop_still_parses() -> None:
    rows = parse_lines("Phillies @ Braves\nCristopher Sanchez outs 17.5 -174 +130\n")
    assert len(rows) == 1
    assert rows[0].price == -174 and rows[0].paired_price == 130
    assert rows[0].paired_side == "UNDER"


def test_probable_starter_resolves_to_id() -> None:
    row = validate_manual_quote(_quote("PITCHER_OUTS", "Cristopher Sanchez", 17.5, -174, 130))
    person_id, team_id = resolve_pitcher_subject(row, _game())
    assert person_id == "661563"
    assert team_id == 143


def test_non_starter_is_subject_unresolved() -> None:
    row = validate_manual_quote(_quote("PITCHER_K", "Zack Wheeler", 5.5, -110, -110))
    with pytest.raises(ValueError, match="SUBJECT_UNRESOLVED"):
        resolve_pitcher_subject(row, _game())


def test_canonical_hook_does_not_people_lookup_a_non_starter() -> None:
    row = validate_manual_quote(_quote("PITCHER_OUTS", "Zack Wheeler", 17.5, -174, 130))

    def boom(*_a, **_k):
        raise AssertionError("People API must not run for pitcher props")

    with pytest.raises(CanonicalManualMLBError, match="SUBJECT_UNRESOLVED"):
        _resolve_subject(row, opener=boom, game=_game())


def test_one_sided_prop_is_blocked_pricing_method() -> None:
    with pytest.raises(LinesIntakeError, match="BLOCKED_PRICING_METHOD"):
        parse_lines("Phillies @ Braves\nCristopher Sanchez outs 17.5 -174\n")


def test_outs_and_k_names_survive_to_pricer(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_card(**kwargs):
        seen["quotes"] = list(kwargs["quotes"])
        seen["features"] = list(kwargs["feature_rows"])
        return []

    monkeypatch.setattr("sportsedge.canonical_manual_mlb.run_generic_card", fake_card)
    monkeypatch.setattr(
        "sportsedge.canonical_manual_mlb.MLBAllMarketHistorySource.feature_row",
        lambda self, **kw: {
            "market": kw["market"],
            "entity_id": kw["entity_id"],
            "source": "TEST",
            "source_subset_hash": "x",
        },
    )
    payload = run_canonical_manual_mlb(
        [
            _quote("PITCHER_OUTS", "Cristopher Sanchez", 17.5, -174, 130),
            _quote("PITCHER_K", "Tyler Mahle", 5.5, -110, -110),
        ],
        schedule=[_game()],
        opener=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no network")),
    )
    names = {item["subject_name"]: item for item in payload["market_resolution"]}
    assert names["Cristopher Sanchez"]["subject_id"] == "661563"
    assert names["Cristopher Sanchez"]["engine_market"] == "PITCHER_OUTS"
    assert names["Tyler Mahle"]["subject_id"] == "641835"
    assert names["Tyler Mahle"]["engine_market"] == "PITCHER_K"
    entities = {q["entity_id"] for q in seen["quotes"]}
    assert entities == {"661563", "641835"}
    assert all(q.get("entity_id") for q in seen["quotes"])


def test_unresolved_starter_is_blocked_not_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sportsedge.canonical_manual_mlb.run_generic_card", lambda **_k: [])
    monkeypatch.setattr(
        "sportsedge.canonical_manual_mlb.MLBAllMarketHistorySource.feature_row",
        lambda self, **kw: {"market": kw["market"], "entity_id": kw["entity_id"]},
    )
    payload = run_canonical_manual_mlb(
        [_quote("PITCHER_OUTS", "Zack Wheeler", 17.5, -174, 130)],
        schedule=[_game()],
        opener=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no network")),
    )
    blocked = payload["results"]
    assert blocked
    assert all(row["bet_status"] == "BLOCKED" for row in blocked)
    assert all("SUBJECT_UNRESOLVED" in str(row["reason"]) for row in blocked)
    assert all(row.get("model_p") is None for row in blocked)
    assert payload["market_resolution"][0]["subject_name"] == "Zack Wheeler"
    assert payload["market_resolution"][0]["resolution_status"] == "BLOCKED"
    assert "NO_MODEL" not in payload["market_resolution"][0]["reason"]
