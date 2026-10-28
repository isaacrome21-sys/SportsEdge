"""Owner ruling Oct 24 2026: CFB cards rank by #2539 blended EV, label the
projection model version, and never surface raw model EV as the price."""
from sportsedge.phone_display import build_phone_card, render_phone_card


def cfb(selection, raw_ev, blended_ev=None, notes=("CFB_OPPONENT_ADJUSTED_V1",)):
    row = {"status": "RESEARCH_CANDIDATE_NOT_VALIDATED", "sport": "CFB",
           "game": "A @ B", "market": "MONEYLINE", "selection": selection,
           "dk_odds": 120, "model_probability": .7, "ev_per_dollar": raw_ev,
           "quote_status": "STALE_QUOTE", "context_notes": list(notes)}
    if blended_ev is not None:
        row["pricing_lanes"] = {"lane_b_anchored": {
            "estimate_p": .47, "ev_per_dollar": blended_ev,
            "fair_american": 113, "anchor": {"weight": .15}}}
    return row


def card(*rows):
    return {"evaluated_rows": list(rows), "summary": {"rows": len(rows)},
            "min_ev": .02, "as_of_utc": "2026-10-24T19:00:00Z"}


def test_cfb_ranks_by_blended_ev_not_raw_model_ev():
    big_raw = cfb("Tulane", raw_ev=.35, blended_ev=.01)
    small_raw = cfb("UCF", raw_ev=.10, blended_ev=.04)
    text = render_phone_card(card(big_raw, small_raw))
    ranked = text.split("re-check line before betting", 1)[1].split("### CFB", 1)[0]
    assert ranked.index("UCF") < ranked.index("Tulane")
    assert "+35.0%" not in ranked


def test_cfb_without_blend_is_not_ranked_on_raw_ev():
    text = render_phone_card(card(cfb("Sac State", raw_ev=.58)))
    assert "re-check line before betting" not in text
    row = [ln for ln in text.splitlines() if "Sac State" in ln][0]
    assert row.split("|")[6].strip() == "—"     # Est. EV withheld
    assert row.split("|")[7].strip() == "—"       # quarantined, not a research value screen
    assert "| QUARANTINED |" in row
    assert card(cfb("Sac State", raw_ev=.58))["evaluated_rows"][0]["ev_per_dollar"] == .58


def test_model_version_is_labeled():
    view = build_phone_card(card(cfb("X", .2, .02),
                                 cfb("Y", .2, .02, notes=())))
    versions = [s["model_version"] for s in view["selections"]]
    assert versions == ["CFB_OPPONENT_ADJUSTED_V1", "CFB_PRE_OCT24_BASELINE"]
    assert "CFB_OPPONENT_ADJUSTED_V1" in render_phone_card(card(cfb("X", .2, .02)))


def test_nfl_ranks_by_blended_ev_and_is_labeled():
    big = {**cfb("Giants ML", raw_ev=.35, blended_ev=.01), "sport": "NFL", "context_notes": []}
    small = {**cfb("Ravens +2.5", raw_ev=.10, blended_ev=.03), "sport": "NFL", "context_notes": []}
    text = render_phone_card(card(big, small))
    ranked = text.split("re-check line before betting", 1)[1].split("### NFL", 1)[0]
    assert ranked.index("Ravens") < ranked.index("Giants")
    assert "+35.0%" not in ranked
    assert "NFL_SIDES_PRIOR_COMPRESSED_2384" in ranked


def test_nfl_without_blend_is_not_ranked():
    row = {**cfb("Giants ML", raw_ev=1.13), "sport": "NFL", "context_notes": []}
    assert "re-check line before betting" not in render_phone_card(card(row))
