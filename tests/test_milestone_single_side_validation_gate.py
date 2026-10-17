"""Single-side milestone binding gate (owner policy, FORM_GATE_DEFECT fix).

The three-sport research bridge historically refused every one-sided quote
set with EXACT_PAIRED_DK_QUOTE_REQUIRED -- a quote-cardinality test that
never read validation state. Owner policy permits one-sided EV against an
independently validated model. These tests pin the new binding stage:

* one-sided prop quote + family NOT validated in the canonical coverage
  authority -> refusal naming the validation state, never the quote form;
* one-sided prop quote + authority-VALIDATED family (fixture resolver) ->
  priced, EV labeled single-side, NO de-vig fields emitted;
* a model row asserting its own validation is still refused
  (RESEARCH_AUTHORITY_ONLY) even when the authority validates the family --
  validation is pronounced by the authority, never self-declared;
* two-sided pairs are byte-identical to the pre-change bridge (golden);
* non-one-sided shapes (duplicates, missing own side, incoherent pair,
  one-sided GAME market) keep the legacy paired refusal;
* PLAY can never surface: a model record asserting PLAY/eligibility is
  refused or demoted to research-only, and no envelope row carries PLAY.
"""
from sportsedge.research_three_sport_bridge import price_three_sport_research

ASOF = "2026-10-11T20:30:00Z"
FUTURE = "2026-10-12T03:00:00Z"


def model(sport="MLB", market="BATTER_HITS", line=0.5, player="456",
          selection="OVER", **other):
    row = {"sport": sport, "game_id": "test-game", "market": market,
           "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
           "player_id": player, "line": line, "selection": selection,
           "estimate_p": .61, "push_p": 0,
           "status": "PRICED_RESEARCH", "model_source": "TEST_INDEPENDENT_SOURCE",
           "market_blind": True, "as_of_utc": "2026-10-11T20:29:00Z",
           "kickoff_utc": FUTURE}
    row.update(other)
    return row


def quote(sport="MLB", market="BATTER_HITS", line=0.5, player="456",
          selection="OVER", odds=-110, captured="2026-10-11T20:29:30Z", **other):
    row = {"sport": sport, "game_id": "test-game", "market": market,
           "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
           "player_id": player, "line": line, "selection": selection,
           "odds": odds, "book": "draftkings", "quote_captured_at": captured}
    row.update(other)
    return row


def validated_resolver(sport, market):
    return {"sport": sport, "market": market, "state": "PRICED_PATH",
            "validation_status": "VALIDATED"}


def one(models, quotes, **kwargs):
    return price_three_sport_research(models, quotes, as_of=ASOF, **kwargs)["rows"][0]


# --- (a) one-sided + unvalidated: refusal names the validation state --------

def test_one_sided_mlb_batter_hits_refuses_naming_validation_state():
    row = one([model()], [quote()])
    assert row["status"] == "NO_MODEL_OR_MARKET"
    # MLB HITS family state in the canonical coverage authority today.
    assert row["reason"] == "MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:NOT_RUN"
    assert "EXACT_PAIRED" not in row["reason"]


def test_one_sided_cfb_yardage_refuses_naming_unvalidated_state():
    row = one([model(sport="CFB", market="PLAYER_PASSING_YARDS", line=200.5,
                     player="qb-1")],
              [quote(sport="CFB", market="PLAYER_PASSING_YARDS", line=200.5,
                     player="qb-1")])
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:UNVALIDATED"


def test_one_sided_nfl_yardage_refuses_naming_validation_state():
    row = one([model(sport="NFL", market="PLAYER_PASSING_YARDS", line=250.5,
                     player="qb-9")],
              [quote(sport="NFL", market="PLAYER_PASSING_YARDS", line=250.5,
                     player="qb-9")])
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:NOT_VALIDATED"


def test_one_sided_under_milestone_also_gated_on_validation():
    row = one([model(selection="UNDER")], [quote(selection="UNDER")])
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:NOT_RUN"


# --- (b) one-sided + authority-validated family: priced, single-side EV -----

def test_one_sided_validated_family_prices_without_devig_fields():
    row = one([model()], [quote()], validation_resolver=validated_resolver)
    assert row["status"] == "RESEARCH_CANDIDATE_SINGLE_SIDE_VALIDATED"
    assert row["dk_odds"] == -110
    # EV = win * (dec - 1) - loss, dec = 1 + 100/110, p = .61, push = 0.
    assert row["ev_per_dollar"] == round(.61 * (100 / 110) - .39, 6)
    # No de-vig benchmark exists for a single side: fields must be absent.
    assert "dk_no_vig_p" not in row
    assert "edge_pp" not in row
    assert "paired_quote_skew_seconds" not in row
    assert "paired_quote_captured_at" not in row
    # The EV basis is labeled as model-vs-single-price only.
    assert row["quote_form"] == "SINGLE_SIDE"
    assert row["ev_basis"] == "MODEL_PROBABILITY_VS_SINGLE_QUOTED_PRICE_NO_DEVIG"
    assert row["family_validation_status"] == "VALIDATED"
    assert row["validation_authority"] == "SPORTSEDGE_CANONICAL_COVERAGE"
    # The research bridge still grants no authority of any kind.
    assert row["research_only"] is True
    assert row["official_authority"] is False
    assert row["staking_authority"] is False


def test_one_sided_validated_family_status_ladder_mirrors_paired_path():
    stale = one([model()], [quote(captured="2026-10-11T19:00:00Z")],
                validation_resolver=validated_resolver)
    assert stale["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert "dk_no_vig_p" not in stale
    capped = one([model()], [quote(odds=-170)],
                 validation_resolver=validated_resolver)
    assert capped["status"] == "WATCH_PRICE_CAP"
    below = one([model(estimate_p=.40)], [quote()],
                validation_resolver=validated_resolver)
    assert below["status"] == "WATCH_BELOW_EV_FLOOR"


def test_one_sided_validated_family_requires_capture_timestamp():
    row = one([model()], [quote(captured=None)],
              validation_resolver=validated_resolver)
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "SINGLE_SIDE_QUOTE_CAPTURE_TIMESTAMP_REQUIRED"


def test_one_sided_validated_family_started_game_refused():
    row = one([model(kickoff_utc="2026-10-11T19:00:00Z")], [quote()],
              validation_resolver=validated_resolver)
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert "GAME_STARTED" in row["reason"]


# --- (d) self-asserted authority stays refused; the authority decides ------

def test_self_asserted_validation_refused_even_when_authority_validates():
    row = one([model(validated_vs_close=True)], [quote()],
              validation_resolver=validated_resolver)
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "RESEARCH_AUTHORITY_ONLY"


def test_self_asserted_official_authority_refused_on_paired_path_too():
    row = one([model(market="PITCHER_K", line=5.5, player="123",
                     official_authority=True)],
              [quote(market="PITCHER_K", line=5.5, player="123"),
               quote(market="PITCHER_K", line=5.5, player="123",
                     selection="UNDER")])
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "RESEARCH_AUTHORITY_ONLY"


def test_resolver_error_fails_closed_naming_no_resolution():
    def broken_resolver(sport, market):
        raise RuntimeError("authority unavailable")
    row = one([model()], [quote()], validation_resolver=broken_resolver)
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == ("MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:"
                             "NO_COVERAGE_RESOLUTION")


# --- (e) research-only enforcement: PLAY can never surface -----------------
# Owner audit finding (forwarded from the #2359 branch audit): a component
# emitting status="PLAY" for an unvalidated family must be caught. On this
# surface the enforcement is structural -- the bridge requires the model
# status to be exactly PRICED_RESEARCH, refuses self-asserted authority,
# builds rows from a whitelisted identity plus hardcoded research flags --
# and these tests pin it on the milestone/single-side path specifically.

def test_model_asserting_play_status_is_refused_never_priced():
    # A model record whose own status claims PLAY is not a research model
    # record at all: refused before any quote binding, on the single-side
    # path (even with a validating authority) and on the paired path alike.
    row = one([model(status="PLAY")], [quote()],
              validation_resolver=validated_resolver)
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "NO_INDEPENDENT_MODEL_PROBABILITY"
    row = one([model(status="PLAY", market="PITCHER_K", line=5.5,
                     player="123")],
              [quote(market="PITCHER_K", line=5.5, player="123"),
               quote(market="PITCHER_K", line=5.5, player="123",
                     selection="UNDER")],
              validation_resolver=validated_resolver)
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "NO_INDEPENDENT_MODEL_PROBABILITY"


def test_model_asserting_eligibility_is_demoted_to_research_only():
    # Eligibility/staking self-assertions riding on an otherwise valid
    # research model never reach the row: identity is whitelisted and the
    # authority flags are hardcoded False, so even a fixture-VALIDATED
    # single-side price surfaces as research-only, never PLAY.
    row = one([model(eligible=True, play_eligible=True,
                     staking_authority=True, betting_authority=True)],
              [quote()], validation_resolver=validated_resolver)
    assert row["status"] == "RESEARCH_CANDIDATE_SINGLE_SIDE_VALIDATED"
    assert row["status"] != "PLAY"
    assert row["research_only"] is True
    assert row["official_authority"] is False
    assert row["model_p_authority"] is False
    assert row["staking_authority"] is False
    for leaked in ("eligible", "play_eligible", "betting_authority"):
        assert leaked not in row


def test_envelope_never_contains_play_even_with_play_asserting_input():
    result = price_three_sport_research(
        [model(),
         model(player="789", status="PLAY")],
        [quote(), quote(player="789")],
        as_of=ASOF, validation_resolver=validated_resolver)
    assert result["authority"] == {"research_only": True, "official": False,
                                   "model_p": False, "staking": False}
    assert "PLAY" not in result["status_counts"]
    assert set(result["status_counts"]) == {
        "RESEARCH_CANDIDATE_SINGLE_SIDE_VALIDATED", "NO_MODEL_OR_MARKET"}
    assert all(r["status"] != "PLAY" for r in result["rows"])
    assert all(r["research_only"] is True for r in result["rows"])


# --- shapes that are NOT one-sided keep the legacy paired refusal ----------

def test_duplicate_own_side_quotes_keep_paired_refusal():
    row = one([model()], [quote(), quote(odds=-115)])
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "EXACT_PAIRED_DK_QUOTE_REQUIRED"


def test_missing_own_side_keeps_paired_refusal():
    row = one([model()], [quote(selection="UNDER")])
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "EXACT_PAIRED_DK_QUOTE_REQUIRED"


def test_opposite_at_mismatched_line_is_incoherent_pair_not_single_side():
    row = one([model()], [quote(), quote(selection="UNDER", line=1.5)])
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "EXACT_PAIRED_DK_QUOTE_REQUIRED"


def test_one_sided_game_market_keeps_paired_refusal():
    row = one([model(market="MONEYLINE", line=None, player="", selection="HOME")],
              [quote(market="MONEYLINE", line=None, player="", selection="HOME")],
              validation_resolver=validated_resolver)
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "EXACT_PAIRED_DK_QUOTE_REQUIRED"


# --- (c) golden: two-sided behavior byte-identical to the pre-change bridge -

GOLDEN_MODELS = [
    {"sport": "MLB", "game_id": "test-game", "market": "PITCHER_K",
     "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
     "player_id": "123", "line": 5.5, "selection": "OVER",
     "estimate_p": .61, "push_p": 0, "status": "PRICED_RESEARCH",
     "model_source": "TEST_INDEPENDENT_SOURCE", "market_blind": True,
     "as_of_utc": "2026-10-11T20:29:00Z", "kickoff_utc": FUTURE},
    {"sport": "MLB", "game_id": "test-game", "market": "BATTER_HITS",
     "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
     "player_id": "456", "line": 0.5, "selection": "OVER",
     "estimate_p": .61, "push_p": 0, "status": "PRICED_RESEARCH",
     "model_source": "TEST_INDEPENDENT_SOURCE", "market_blind": True,
     "as_of_utc": "2026-10-11T20:29:00Z", "kickoff_utc": FUTURE},
    {"sport": "MLB", "game_id": "test-game", "market": "PITCHER_OUTS",
     "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
     "player_id": "789", "line": 18, "selection": "OVER",
     "estimate_p": .54, "push_p": .08, "status": "PRICED_RESEARCH",
     "model_source": "TEST_INDEPENDENT_SOURCE", "market_blind": True,
     "as_of_utc": "2026-10-11T20:29:00Z", "kickoff_utc": FUTURE},
]

GOLDEN_QUOTES = [
    {"sport": "MLB", "game_id": "test-game", "market": "PITCHER_K",
     "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
     "player_id": "123", "line": 5.5, "selection": "OVER",
     "odds": -110, "book": "draftkings", "quote_captured_at": "2026-10-11T20:29:30Z"},
    {"sport": "MLB", "game_id": "test-game", "market": "PITCHER_K",
     "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
     "player_id": "123", "line": 5.5, "selection": "UNDER",
     "odds": -110, "book": "draftkings", "quote_captured_at": "2026-10-11T20:29:30Z"},
    {"sport": "MLB", "game_id": "test-game", "market": "BATTER_HITS",
     "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
     "player_id": "456", "line": 0.5, "selection": "OVER",
     "odds": -110, "book": "draftkings", "quote_captured_at": "2026-10-11T20:29:30Z"},
    {"sport": "MLB", "game_id": "test-game", "market": "BATTER_HITS",
     "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
     "player_id": "456", "line": 1.5, "selection": "UNDER",
     "odds": -110, "book": "draftkings", "quote_captured_at": "2026-10-11T20:29:30Z"},
    {"sport": "MLB", "game_id": "test-game", "market": "PITCHER_OUTS",
     "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
     "player_id": "789", "line": 18, "selection": "OVER",
     "odds": -110, "book": "draftkings", "quote_captured_at": "2026-10-11T20:29:30Z"},
    {"sport": "MLB", "game_id": "test-game", "market": "PITCHER_OUTS",
     "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
     "player_id": "789", "line": 18, "selection": "UNDER",
     "odds": 100, "book": "draftkings", "quote_captured_at": "2026-10-11T20:29:30Z"},
]

# Captured verbatim from the pre-change bridge (origin/main 1a10b7ffd)
# on this exact input; the change must not alter any byte of it.
GOLDEN_EXPECTED = {
    "as_of_utc": "2026-10-11T20:30:00+00:00",
    "authority": {"model_p": False, "official": False,
                  "research_only": True, "staking": False},
    "ev_floor": 0.02,
    "price_cap": -165,
    "rows": [
        {"dk_no_vig_p": 0.5, "dk_odds": -110, "edge_pp": 11.0,
         "ev_per_dollar": 0.164545, "fair_american": -156,
         "game_id": "test-game", "input_index": 0, "market": "PITCHER_K",
         "model_conditional_p": 0.61, "model_p_authority": False,
         "model_probability": 0.61, "model_push_p": 0.0,
         "model_source": "TEST_INDEPENDENT_SOURCE", "official_authority": False,
         "paired_quote_captured_at": ["2026-10-11T20:29:30+00:00",
                                      "2026-10-11T20:29:30+00:00"],
         "paired_quote_skew_seconds": 0.0, "player_id": "123",
         "quote_status": "RECENT_CAPTURED_QUOTE", "research_only": True,
         "selection": "OVER", "sport": "MLB", "staking_authority": False,
         "status": "RESEARCH_CANDIDATE_NOT_VALIDATED"},
        {"dk_no_vig_p": 0.511628, "dk_odds": -110, "edge_pp": 7.533,
         "ev_per_dollar": 0.110909, "fair_american": -142,
         "game_id": "test-game", "input_index": 2, "market": "PITCHER_OUTS",
         "model_conditional_p": 0.586957, "model_p_authority": False,
         "model_probability": 0.54, "model_push_p": 0.08,
         "model_source": "TEST_INDEPENDENT_SOURCE", "official_authority": False,
         "paired_quote_captured_at": ["2026-10-11T20:29:30+00:00",
                                      "2026-10-11T20:29:30+00:00"],
         "paired_quote_skew_seconds": 0.0, "player_id": "789",
         "quote_status": "RECENT_CAPTURED_QUOTE", "research_only": True,
         "selection": "OVER", "sport": "MLB", "staking_authority": False,
         "status": "RESEARCH_CANDIDATE_NOT_VALIDATED"},
        {"game_id": "test-game", "input_index": 1, "market": "BATTER_HITS",
         "official_authority": False, "player_id": "456",
         "reason": "EXACT_PAIRED_DK_QUOTE_REQUIRED", "research_only": True,
         "selection": "OVER", "sport": "MLB", "staking_authority": False,
         "status": "NO_MODEL_OR_MARKET"},
    ],
    "schema": "SPORTSEDGE_THREE_SPORT_GAMES_PROPS_RESEARCH_V1",
    "sports": ["NFL", "MLB", "CFB"],
    "status_counts": {"NO_MODEL_OR_MARKET": 1,
                      "RESEARCH_CANDIDATE_NOT_VALIDATED": 2},
}


def test_two_sided_pairs_byte_identical_to_pre_change_bridge():
    out = price_three_sport_research(GOLDEN_MODELS, GOLDEN_QUOTES, as_of=ASOF)
    assert out == GOLDEN_EXPECTED


def test_two_sided_pairs_unaffected_by_validation_resolver():
    out = price_three_sport_research(GOLDEN_MODELS, GOLDEN_QUOTES, as_of=ASOF,
                                     validation_resolver=validated_resolver)
    assert out == GOLDEN_EXPECTED

