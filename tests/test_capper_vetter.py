from sportsedge.capper_vetter import clv_pct, grade_account, implied, load_config, rank


def _pick(acct, result="win", price=-110, close=-130, other=110, posted="2026-11-01T18:00:00Z"):
    return {"account": acct, "posted_at": posted, "tip_utc": "2026-11-01T23:00:00Z",
            "sport": "NCAAB", "market": "Total", "selection": "Under", "line": 155.5,
            "price": price, "close_price": close, "close_other_price": other, "result": result}


def test_implied():
    assert abs(implied(-110) - 0.5238) < 1e-3
    assert abs(implied(150) - 0.4) < 1e-9


def test_clv_positive_when_line_moves_our_way():
    assert clv_pct(_pick("a"), 0.045) > 0
    assert clv_pct(_pick("a", close=110, other=-130), 0.045) < 0


def test_small_samples_shrink_toward_prior():
    cfg = load_config()
    r = grade_account([_pick("a")] * 3, cfg)
    assert r["roi"] > 0.8 and r["adj_roi"] < 0.05


def test_posted_after_tip_flagged_and_excluded():
    cfg = load_config()
    r = grade_account([_pick("a"), _pick("a", posted="2026-11-02T01:00:00Z")], cfg)
    assert any(f.startswith("POSTED_AFTER_TIP") for f in r["flags"])
    assert r["picks_graded"] == 1


def test_hides_losses_auto_fails():
    cfg = load_config()
    p = _pick("a")
    p["shows_losses"] = False
    assert grade_account([p] * 40, cfg)["score"] == 0.0


def test_rank_orders_by_score():
    good = [_pick("good")] * 80
    bad = [_pick("bad", result="loss", close=110, other=-130)] * 80
    out = rank(good + bad, load_config())
    assert [r["account"] for r in out] == ["good", "bad"]
