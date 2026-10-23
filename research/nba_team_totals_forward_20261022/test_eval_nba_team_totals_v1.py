"""RED-first tests for the NBA team totals forward evaluator V1.

Each test cites the frozen prereg section it enforces.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import eval_nba_team_totals_v1 as ev  # noqa: E402

TIP0 = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)


def iso(t):
    return t.isoformat()


def cfg(**kw):
    c = {"k": 9, "seed": 20261022, "first_counted_slate": "2026-11-01",
         "resamples": 400}
    c.update(kw)
    return c


def entry_quotes(game, team, line, *, t, over=-110, under=-110,
                 main=True, span=0, cap="E1", designation="ENTRY"):
    return [
        {"game_id": game, "team": team, "line": line, "side": "OVER",
         "price": over, "captured_at": iso(t), "designation": designation,
         "book": "DraftKings", "is_main": main, "capture_id": cap},
        {"game_id": game, "team": team, "line": line, "side": "UNDER",
         "price": under, "captured_at": iso(t + timedelta(seconds=span)),
         "designation": designation, "book": "DraftKings", "is_main": main,
         "capture_id": cap},
    ]


def close_quotes(game, team, line, *, t, over=-110, under=-110, span=0,
                 cap="C1", sides=("OVER", "UNDER"), main=True):
    out = []
    for s in sides:
        out.append({"game_id": game, "team": team, "line": line, "side": s,
                    "price": over if s == "OVER" else under,
                    "captured_at": iso(t + (timedelta(seconds=span)
                                            if s == "UNDER" else timedelta())),
                    "designation": "CLOSE", "book": "DraftKings",
                    "capture_id": cap, "is_main": main})
    return out


def priced(game, team, mean, *, slate="2026-11-01", tip=TIP0, b1=None,
           b2=None, priced_at=None, entry_t=None, **extra):
    r = {"game_id": game, "team": team, "slate_date": slate,
         "tipoff": iso(tip), "home": team, "away": "OPP" + game,
         "engine": {"engine_id": ev.ENGINE_ID, "status": "PRICED",
                    "sufficiency_met": True, "mean": mean,
                    "b1_team_mean": mean if b1 is None else b1,
                    "b2_league_mean": mean if b2 is None else b2,
                    "priors": {"team_games": 20, "league_team_games": 400}},
         "engine_sha256": ev.PINNED_ENGINE_SHA256,
         "runner_sha256": ev.PINNED_RUNNER_SHA256,
         "history_hash_recorded_before_pricing": True,
         "priced_at": iso(priced_at or (entry_t or tip - timedelta(hours=5))
                          + timedelta(seconds=30))}
    r.update(extra)
    return r


def one_game(game, mean, line, final, *, close_line=None, slate="2026-11-01",
             tip=TIP0, close_dt=timedelta(minutes=30), **kw):
    et = tip - timedelta(hours=5)
    rows = [priced(game, "T" + game, mean, slate=slate, tip=tip, entry_t=et,
                   **kw)]
    ents = entry_quotes(game, "T" + game, line, t=et)
    cl = close_quotes(game, "T" + game, line if close_line is None
                      else close_line, t=tip - close_dt, cap="C" + game)
    res = {game: {"status": "FINAL", "points": {"T" + game: final}}}
    return rows, ents, cl, res


def merge(*parts):
    rows, ents, cls, res = [], [], [], {}
    for r, e, c, s in parts:
        rows += r; ents += e; cls += c; res.update(s)
    return rows, ents, cls, res


def full_slates(dates):
    return {d: {"entry_job_ok": True, "close_job_ok": True,
                "all_games_captured": True} for d in dates}


# §11 / freeze: evaluator is pinned to the frozen document
def test_frozen_doc_hash_pinned():
    assert ev.FROZEN_DOC_SHA256 == (
        "0274e8cd248ed56a43c445c3d23e96e04eb218f4abcafb2ebe4041448ef55504")
    assert ev.verify_frozen_doc() is True


# §5 entry = first ENTRY capture, main line; later captures/alternates ignored
def test_entry_first_capture_main_line_only():
    t = TIP0 - timedelta(hours=6)
    q = (entry_quotes("g1", "Tg1", 112.5, t=t + timedelta(hours=1), cap="E2")
         + entry_quotes("g1", "Tg1", 110.5, t=t, cap="E1")
         + entry_quotes("g1", "Tg1", 99.5, t=t - timedelta(hours=1),
                        main=False, cap="EA"))
    e = ev.select_entry(q, "g1", "Tg1")
    assert e["line"] == 110.5 and e["capture_id"] == "E1"


# §5 pick rule ±2.0
@pytest.mark.parametrize("gap,exp", [(2.0, ("PICKED", "OVER")),
                                     (-2.0, ("PICKED", "UNDER")),
                                     (1.99, ("PASSED", "OVER")),
                                     (-1.5, ("PASSED", "UNDER")),
                                     (0.0, ("PASSED", None))])
def test_pick_rule(gap, exp):
    assert ev.classify(gap) == exp


# §7 runner 120s entry pair -> entry refusal, not CLV-missing
def test_entry_pair_over_120s_is_runner_refusal():
    et = TIP0 - timedelta(hours=5)
    rows = [priced("g1", "Tg1", 115, entry_t=et)]
    ents = entry_quotes("g1", "Tg1", 110.5, t=et, span=121)
    out = ev.evaluate(rows, ents, [], {}, full_slates(["2026-11-01"]),
                      [], cfg())
    assert out["refusals"]["DK_PAIR_CAPTURE_SPAN_EXCEEDED"] == 1
    assert out["clv_missing"] == {}


# §8 the six runner codes are declared and pass through
def test_runner_codes_declared():
    for c in ["DK_PAIR_MISSING_OR_STALE", "TWO_SIDED_OU_REQUIRED",
              "DRAFTKINGS_QUOTE_REQUIRED", "FINITE_DK_ODDS_REQUIRED",
              "NATIVE_TWO_SIDED_QUOTES_REQUIRED",
              "DK_PAIR_CAPTURE_SPAN_EXCEEDED"]:
        assert c in ev.DECLARED_REFUSALS


# §8 undeclared code blocks the verdict
def test_undeclared_code_blocks():
    rows = [priced("g1", "Tg1", 115, runner_refusal="SOMETHING_NEW")]
    out = ev.evaluate(rows, [], [], {}, {}, [], cfg())
    assert out["verdict"] == "UNDECLARED_REFUSAL_CODE"


# §8 malformed row refused alone, slate not aborted
def test_bad_price_refused_alone():
    a = one_game("g1", 115, 110.5, 112)
    b = one_game("g2", 115, 110.5, 112)
    rows, ents, cls, res = merge(a, b)
    for q in ents:
        if q["game_id"] == "g1" and q["side"] == "OVER":
            q["price"] = "abc"
    out = ev.evaluate(rows, ents, cls, res, full_slates(["2026-11-01"]),
                      [], cfg())
    assert out["refusals"]["PRICE_INVALID"] == 1
    assert out["counts"]["engine_priced_rows"] == 1


# §8 freshness 180s
def test_quote_stale_180s():
    et = TIP0 - timedelta(hours=5)
    rows = [priced("g1", "Tg1", 115, entry_t=et,
                   priced_at=et + timedelta(seconds=181))]
    ents = entry_quotes("g1", "Tg1", 110.5, t=et)
    out = ev.evaluate(rows, ents, [], {}, {}, [], cfg())
    assert out["refusals"]["QUOTE_STALE_180S"] == 1


def test_entry_after_tip_refused():
    rows = [priced("g1", "Tg1", 115, entry_t=TIP0)]
    ents = entry_quotes("g1", "Tg1", 110.5, t=TIP0)
    out = ev.evaluate(rows, ents, [], {}, {}, [], cfg())
    assert out["refusals"]["ENTRY_NOT_PRETIP"] == 1


def test_engine_provenance_and_hash():
    r1 = priced("g1", "Tg1", 115); r1["engine"]["engine_id"] = "X"
    r2 = priced("g2", "Tg2", 115); r2["engine_sha256"] = "0" * 64
    r3 = priced("g3", "Tg3", 115)
    r3["history_hash_recorded_before_pricing"] = False
    et = TIP0 - timedelta(hours=5)
    ents = sum([entry_quotes(g, "T" + g, 110.5, t=et)
                for g in ("g1", "g2", "g3")], [])
    out = ev.evaluate([r1, r2, r3], ents, [], {}, {}, [], cfg())
    assert out["refusals"]["ENGINE_PROVENANCE_MISSING"] == 1
    assert out["refusals"]["HISTORY_HASH_MISMATCH"] == 2


# §7 close validity
def _close_reason(cls, tip=TIP0, line=110.5):
    return ev.close_status(cls, "g1", "Tg1", line, tip)["reason"]


def test_close_window():
    t = TIP0
    assert _close_reason([]) == "NO_CLOSE_ROW"
    assert _close_reason(close_quotes("g1", "Tg1", 110.5, t=t)) == \
        "CLOSE_NOT_PRETIP"
    assert _close_reason(close_quotes(
        "g1", "Tg1", 110.5, t=t - timedelta(minutes=60))) is None  # 60:00 ok
    assert _close_reason(close_quotes(
        "g1", "Tg1", 110.5, t=t - timedelta(minutes=60, seconds=1))) == \
        "CLOSE_STALE"
    assert _close_reason(close_quotes(
        "g1", "Tg1", 110.5, t=t - timedelta(minutes=5), sides=("OVER",))) \
        == "CLOSE_SINGLE_SIDED"
    assert _close_reason(close_quotes(
        "g1", "Tg1", 110.5, t=t - timedelta(minutes=5), span=151)) == \
        "PAIR_SPAN_EXCEEDED"
    assert _close_reason(close_quotes(
        "g1", "Tg1", 110.5, t=t - timedelta(minutes=5), span=150)) is None


def test_moved_requires_valid_close():
    t = TIP0 - timedelta(minutes=5)
    st = ev.close_status(close_quotes("g1", "Tg1", 112.5, t=t),
                         "g1", "Tg1", 110.5, TIP0)
    assert st["reason"] is None and st["moved"] and st["close_line"] == 112.5
    # one-sided at new line is a capture failure, not moved
    st = ev.close_status(close_quotes("g1", "Tg1", 112.5, t=t,
                                      sides=("OVER",)),
                         "g1", "Tg1", 110.5, TIP0)
    assert st["reason"] == "CLOSE_SINGLE_SIDED" and not st["moved"]
    # stale moved close is stale
    st = ev.close_status(close_quotes("g1", "Tg1", 112.5,
                                      t=TIP0 - timedelta(minutes=61)),
                         "g1", "Tg1", 110.5, TIP0)
    assert st["reason"] == "CLOSE_STALE"


# §6c moved direction and straddle-adverse
def test_move_direction():
    assert ev.move_direction("OVER", 110.5, [112.5]) == "FAVORABLE"
    assert ev.move_direction("OVER", 110.5, [108.5]) == "ADVERSE"
    assert ev.move_direction("UNDER", 110.5, [108.5]) == "FAVORABLE"
    assert ev.move_direction("OVER", 110.5, [108.5, 112.5]) == "ADVERSE"


# §3 void / result unavailable / push; §8 GAP_ZERO
def test_excluded_and_counted():
    a = one_game("g1", 115, 110.5, 112)
    b = one_game("g2", 115, 110.5, 112)
    c = one_game("g3", 115, 110.0, 110)  # push in 6d
    d = one_game("g4", 110.5, 110.5, 112)  # gap zero
    rows, ents, cls, res = merge(a, b, c, d)
    res["g1"] = {"status": "POSTPONED"}
    del res["g2"]
    out = ev.evaluate(rows, ents, cls, res, full_slates(["2026-11-01"]),
                      [], cfg())
    x = out["excluded"]
    assert x["VOID"] == 1 and x["RESULT_UNAVAILABLE"] == 1
    assert x["GAP_ZERO"] == 1
    assert "PUSH" not in x  # audit minor: PUSH hidden until review


# §3 missing offers reported, never backfilled or counted
def test_missing_offers_reported():
    out = ev.evaluate([], [], [], {}, {}, [{"game_id": "gX",
                                             "slate_date": "2026-11-01",
                                             "capture_id": "E1"}], cfg())
    assert out["missing_offer"]["count"] == 1
    assert out["counts"]["engine_priced_rows"] == 0


# §4/§12: rows before the first counted slate never count; no metrics
# before gates met
def test_precount_and_no_early_metrics():
    a = one_game("g0", 115, 110.5, 112, slate="2026-10-31")
    b = one_game("g1", 115, 110.5, 112)
    rows, ents, cls, res = merge(a, b)
    out = ev.evaluate(rows, ents, cls, res,
                      full_slates(["2026-10-31", "2026-11-01"]), [], cfg())
    assert out["counts"]["historical_not_counted"] == 1
    assert out["verdict"] == "INSUFFICIENT_SAMPLE"
    assert "metrics" not in out


def test_first_counted_slate_required():
    with pytest.raises(ValueError):
        ev.evaluate([], [], [], {}, {}, [], cfg(first_counted_slate=None))


# §4 single review at first slate close where all gates met
def _big(n_slates, games_per, *, mean_fn, final_fn, line=110.5,
         close_line_fn=None, close_over=-110, close_under=-110):
    parts, dates = [], []
    for s in range(n_slates):
        d = (datetime(2026, 11, 1) + timedelta(days=s)).strftime("%Y-%m-%d")
        dates.append(d)
        tip = TIP0 + timedelta(days=s)
        for g in range(games_per):
            gid = f"s{s}g{g}"
            for team in ("H", "A"):
                tm = gid + team
                et = tip - timedelta(hours=5)
                i = s * 1000 + g * 2 + (team == "A")
                r = priced(gid, tm, mean_fn(i), slate=d, tip=tip, entry_t=et,
                           b1=line + 6, b2=line - 6)
                cl = line if close_line_fn is None else close_line_fn(i)
                parts.append(([r], entry_quotes(gid, tm, line, t=et),
                              close_quotes(gid, tm, cl,
                                           t=tip - timedelta(minutes=20),
                                           over=close_over,
                                           under=close_under,
                                           cap="C" + tm),
                              {}))
                parts.append(([], [], [], {gid: None}))
    rows, ents, cls, _ = merge(*parts)
    res = {}
    for r in rows:
        i = int(r["game_id"][1:].split("g")[0]) * 1000 + \
            int(r["game_id"].split("g")[1]) * 2 + r["team"].endswith("A")
        res.setdefault(r["game_id"], {"status": "FINAL", "points": {}})
        res[r["game_id"]]["points"][r["team"]] = final_fn(i)
    return rows, ents, cls, res, dates


def test_review_freezes_at_first_gate_slate():
    rows, ents, cls, res, dates = _big(
        8, 12, mean_fn=lambda i: 113.0 if i % 2 else 108.0,
        final_fn=lambda i: 113.0 if i % 2 else 108.0)
    out = ev.evaluate(rows, ents, cls, res, full_slates(dates), [], cfg())
    # 24 rows/slate, 12 games/slate: games>=40 at slate 4, rows>=150 at 7
    assert out["review_slate"] == dates[6]
    assert out["counts"]["sample_rows"] == 7 * 24
    assert "metrics" in out


def test_partial_slate_not_full():
    rows, ents, cls, res, dates = _big(
        8, 12, mean_fn=lambda i: 113.0, final_fn=lambda i: 113.0)
    sl = full_slates(dates)
    sl[dates[0]]["close_job_ok"] = False
    out = ev.evaluate(rows, ents, cls, res, sl, [], cfg())
    assert out["review_slate"] == dates[6]
    assert out["counts"]["full_slates"] == 6


# §6 moved rules first: adverse sign test -> DOES_NOT_BEAT_MARKET
def test_adverse_sign_test_first():
    # all picks OVER (mean line+4), all closes move down -> adverse
    rows, ents, cls, res, dates = _big(
        12, 12, mean_fn=lambda i: 114.5, final_fn=lambda i: 130.0,
        close_line_fn=lambda i: 108.5 if i % 3 == 0 else 110.5)
    out = ev.evaluate(rows, ents, cls, res, full_slates(dates), [], cfg())
    assert out["verdict"] == "DOES_NOT_BEAT_MARKET"
    assert out["verdict_reason"] == "MOVED_SIGN_TEST_ADVERSE"


def test_majority_moved_insufficient_close():
    # half up half down -> sign test not adverse; >50% moved
    rows, ents, cls, res, dates = _big(
        30, 12, mean_fn=lambda i: 114.5, final_fn=lambda i: 130.0,
        close_line_fn=lambda i: 112.5 if i % 4 in (0, 1) else
        (108.5 if i % 4 == 2 else 110.5))
    out = ev.evaluate(rows, ents, cls, res, full_slates(dates), [], cfg())
    assert out["verdict"] == "INSUFFICIENT_CLOSE_DATA"
    assert out["verdict_reason"] == "PICKED_MOVED_OVER_50PCT"


def test_zero_moved_sign_test_not_run():
    rows, ents, cls, res, dates = _big(
        8, 12, mean_fn=lambda i: 114.5, final_fn=lambda i: 114.5)
    out = ev.evaluate(rows, ents, cls, res, full_slates(dates), [], cfg())
    assert out["metrics"]["moved"]["sign_test_run"] is False


def test_over_20pct_invalid_close():
    rows, ents, cls, res, dates = _big(
        10, 12, mean_fn=lambda i: 114.5, final_fn=lambda i: 114.5)
    drop = {r["team"] for j, r in enumerate(rows) if j % 4 == 0}
    cls = [c for c in cls if c["team"] not in drop]
    out = ev.evaluate(rows, ents, cls, res, full_slates(dates), [], cfg())
    assert out["verdict"] == "INSUFFICIENT_CLOSE_DATA"
    assert out["verdict_reason"] == "INVALID_CLOSE_OVER_20PCT"


# §6a market loses -> DOES_NOT_BEAT_MARKET even if naive baselines lose
def test_market_baseline_governs():
    # engine mean off by 5 alternating; line exact
    rows, ents, cls, res, dates = _big(
        8, 12, mean_fn=lambda i: 115.5 if i % 2 else 105.5,
        final_fn=lambda i: 110.5)
    out = ev.evaluate(rows, ents, cls, res, full_slates(dates), [], cfg())
    assert out["verdict"] == "DOES_NOT_BEAT_MARKET"
    assert out["metrics"]["6a"]["pass"] is False


def test_beats_market_all_four():
    # engine exact; finals differ from line; close shades toward pick
    rows, ents, cls, res, dates = _big(
        8, 12, mean_fn=lambda i: 116.0 + (i % 3),
        final_fn=lambda i: 116.0 + (i % 3),
        close_over=-130, close_under=110)
    out = ev.evaluate(rows, ents, cls, res, full_slates(dates), [], cfg())
    m = out["metrics"]
    assert m["6a"]["pass"] and m["6b"]["pass"] and m["6d"]["pass"]
    # all rows picked -> no passed rows -> 6c ordering cannot be shown
    assert out["verdict"] == "DOES_NOT_BEAT_MARKET"
    assert m["6c"]["reason"] == "NO_PASSED_ROWS"


def test_devig_and_bonferroni_level():
    p = ev.no_vig(-110, -110)
    assert abs(p - 0.5) < 1e-12
    assert abs(ev.ci_level(9) - (1 - 0.05 / 9)) < 1e-12
    assert ev.sign_test_p(0, 0) is None
    assert abs(ev.sign_test_p(5, 5) - 0.5 ** 5) < 1e-12


# §9 frozen settings: only k>=9, seed 20261022, 10,000 resamples are binding
def test_binding_flag():
    o = ev.evaluate([], [], [], {}, {}, [], cfg())
    assert o["binding"] is False  # 400 resamples in tests
    o = ev.evaluate([], [], [], {}, {}, [], {"first_counted_slate": "x",
                                             "clock_ids": CLOCKS9})
    assert o["binding"] is True and o["resamples"] == 10_000
    o = ev.evaluate([], [], [], {}, {}, [], cfg(resamples=10_000, k=8))
    assert o["binding"] is False


# ---------------------------------------------------------------------------
# Audit round 1 fixes (F1-F5 + minors). AMENDMENT_1.md declares new codes.
CLOCKS9 = [f"CLOCK_{i}" for i in range(9)]
AMEND_CODES = {"DUPLICATE_ROW", "ENTRY_QUOTE_CONFLICT", "ROW_MALFORMED",
               "QUOTE_TIMESTAMP_INVALID", "CAPTURE_ID_MISSING",
               "PRICED_BEFORE_QUOTE", "SLATE_DATE_MISMATCH"}
AMEND_CLV = {"CLOSE_QUOTE_CONFLICT", "CLOSE_TIMESTAMP_INVALID",
             "CLOSE_CAPTURE_ID_MISSING", "CLOSE_MAIN_FLAG_MISSING"}


def _ev(rows, ents, cls, res, **kw):
    return ev.evaluate(rows, ents, cls, res, full_slates(["2026-11-01"]),
                       [], cfg(**kw))


def test_amendment_pinned_and_codes_declared():
    import hashlib
    txt = (HERE / "AMENDMENT_1.md").read_bytes()
    assert hashlib.sha256(txt).hexdigest() == ev.AMENDMENT_1_SHA256
    for c in AMEND_CODES | AMEND_CLV:
        assert f"`{c}`".encode() in txt
    assert AMEND_CODES <= ev.DECLARED_REFUSALS
    assert AMEND_CLV <= ev.CLV_MISSING
    assert ev.verify_amendment() is True


# F1 duplicates: every copy refused
def test_f1_duplicate_row_refuses_every_copy():
    rows, ents, cls, res = one_game("g1", 115, 110.5, 112)
    rows = rows + [dict(rows[0])]
    out = _ev(rows, ents, cls, res)
    assert out["refusals"].get("DUPLICATE_ROW") == 2
    assert out["counts"]["engine_priced_rows"] == 0


# F1 conflicting entry quotes within one capture/line/side
def test_f1_entry_quote_conflict():
    rows, ents, cls, res = one_game("g1", 115, 110.5, 112)
    bad = dict(ents[0]); bad["price"] = -150
    out = _ev(rows, ents + [bad], cls, res)
    assert out["refusals"].get("ENTRY_QUOTE_CONFLICT") == 1
    # identical repeat is not a conflict
    out = _ev(rows, ents + [dict(ents[0])], cls, res)
    assert out["counts"]["engine_priced_rows"] == 1


# F1 conflicting close quotes invalidate that pair
def test_f1_close_quote_conflict():
    t = TIP0 - timedelta(minutes=5)
    q = close_quotes("g1", "Tg1", 110.5, t=t)
    bad = dict(q[1]); bad["price"] = +120
    assert _close_reason(q + [bad]) == "CLOSE_QUOTE_CONFLICT"


# F2 evaluate verifies the frozen doc
def test_f2_evaluate_calls_verify(monkeypatch):
    monkeypatch.setattr(ev, "FROZEN_DOC_SHA256", "0" * 64)
    with pytest.raises(RuntimeError):
        ev.evaluate([], [], [], {}, {}, [], cfg())


def test_f2_binding_requires_clock_ids_len_k():
    base = {"first_counted_slate": "x"}
    assert ev.evaluate([], [], [], {}, {}, [], base)["binding"] is False
    o = ev.evaluate([], [], [], {}, {}, [], {**base,
                                             "clock_ids": CLOCKS9[:8]})
    assert o["binding"] is False
    o = ev.evaluate([], [], [], {}, {}, [], {**base, "clock_ids": CLOCKS9})
    assert o["binding"] is True and o["doc_hash_ok"] is True


# F3 malformed timestamp refuses only that row
def test_f3_malformed_row_timestamp_isolated():
    a = one_game("g1", 115, 110.5, 112)
    b = one_game("g2", 115, 110.5, 112)
    rows, ents, cls, res = merge(a, b)
    rows[0]["tipoff"] = "not-a-time"
    out = _ev(rows, ents, cls, res)
    assert out["refusals"].get("ROW_MALFORMED") == 1
    assert out["counts"]["engine_priced_rows"] == 1
    rows[0]["tipoff"] = "2026-11-02T00:00:00"  # zoneless
    out = _ev(rows, ents, cls, res)
    assert out["refusals"].get("ROW_MALFORMED") == 1


def test_f3_bad_quote_timestamps():
    rows, ents, cls, res = one_game("g1", 115, 110.5, 112)
    e2 = [dict(q) for q in ents]; e2[0]["captured_at"] = "garbage"
    out = _ev(rows, e2, cls, res)
    assert out["refusals"].get("QUOTE_TIMESTAMP_INVALID") == 1
    c2 = [dict(q) for q in cls]; c2[1]["captured_at"] = "garbage"
    out = _ev(rows, ents, c2, res)
    assert out["clv_missing"].get("CLOSE_TIMESTAMP_INVALID") == 1


def test_f3_nonfinite_fields():
    rows, ents, cls, res = one_game("g1", 115, 110.5, float("nan"))
    out = _ev(rows, ents, cls, res)
    assert out["excluded"].get("RESULT_UNAVAILABLE") == 1
    for fld in ("b1_team_mean", "b2_league_mean"):
        rows, ents, cls, res = one_game("g1", 115, 110.5, 112)
        rows[0]["engine"][fld] = float("inf")
        assert _ev(rows, ents, cls, res)["refusals"].get(
            "ROW_MALFORMED") == 1
    rows, ents, cls, res = one_game("g1", 115, 110.5, 112)
    for q in ents:
        q["line"] = float("nan")
    assert _ev(rows, ents, cls, res)["refusals"].get("PRICE_INVALID") == 1


# F4 priced_at window and slate date
def test_f4_priced_before_quote():
    et = TIP0 - timedelta(hours=5)
    rows = [priced("g1", "Tg1", 115, priced_at=et - timedelta(seconds=1))]
    out = _ev(rows, entry_quotes("g1", "Tg1", 110.5, t=et), [], {})
    assert out["refusals"].get("PRICED_BEFORE_QUOTE") == 1
    rows = [priced("g1", "Tg1", 115, priced_at=et + timedelta(seconds=181))]
    out = _ev(rows, entry_quotes("g1", "Tg1", 110.5, t=et), [], {})
    assert out["refusals"].get("QUOTE_STALE_180S") == 1
    rows = [priced("g1", "Tg1", 115, priced_at=et + timedelta(seconds=180))]
    out = _ev(rows, entry_quotes("g1", "Tg1", 110.5, t=et), [], {})
    assert out["counts"]["engine_priced_rows"] == 1


def test_f4_slate_date_is_tipoff_ct_date():
    # TIP0 = 2026-11-02 00:00Z = 2026-11-01 18:00 CT
    rows, ents, cls, res = one_game("g1", 115, 110.5, 112,
                                    slate="2026-11-02")
    out = _ev(rows, ents, cls, res)
    assert out["refusals"].get("SLATE_DATE_MISMATCH") == 1


# F5 post-tip capture is the last capture; main-line closes only
def test_f5_post_tip_capture_blocks_close():
    # fully post-tip-only case superseded by AMENDMENT_2 (see test_a2_*)
    q = (close_quotes("g1", "Tg1", 110.5, t=TIP0 - timedelta(minutes=10),
                      cap="C1")
         + close_quotes("g1", "Tg1", 110.5, t=TIP0 - timedelta(seconds=30),
                        span=60, cap="C2"))  # straddles tip
    assert _close_reason(q) == "CLOSE_NOT_PRETIP"


def test_f5_main_line_close_only():
    t = TIP0 - timedelta(minutes=5)
    q = (close_quotes("g1", "Tg1", 110.5, t=t)
         + close_quotes("g1", "Tg1", 112.5, t=t, main=False))
    st = ev.close_status(q, "g1", "Tg1", 110.5, TIP0)
    assert st["reason"] is None and not st["moved"]
    st = ev.close_status(close_quotes("g1", "Tg1", 112.5, t=t, main=False)
                         + close_quotes("g1", "Tg1", 108.5, t=t),
                         "g1", "Tg1", 112.5, TIP0)
    assert st["moved"] and st["close_lines"] == [108.5]
    q = close_quotes("g1", "Tg1", 110.5, t=t)
    del q[0]["is_main"]
    assert _close_reason(q) == "CLOSE_MAIN_FLAG_MISSING"


# Minor: missing capture_id
def test_minor_missing_capture_id():
    rows, ents, cls, res = one_game("g1", 115, 110.5, 112)
    e2 = [dict(q) for q in ents]; del e2[0]["capture_id"]
    assert _ev(rows, e2, cls, res)["refusals"].get("CAPTURE_ID_MISSING") == 1
    c2 = [dict(q) for q in cls]; c2[0]["capture_id"] = None
    assert _ev(rows, ents, c2, res)["clv_missing"].get(
        "CLOSE_CAPTURE_ID_MISSING") == 1


# ---------------------------------------------------------------------------
# Re-audit round 2: AMENDMENT_2.md narrows the post-tip rule to straddling
# captures; fully post-tip captures are ignored (frozen §7).
def test_amendment2_pinned():
    import hashlib
    txt = (HERE / "AMENDMENT_2.md").read_bytes()
    assert hashlib.sha256(txt).hexdigest() == ev.AMENDMENT_2_SHA256
    assert ev.verify_amendment() is True
    assert b"adds no codes" in txt.lower()


def test_a2_fully_post_tip_capture_ignored():
    q = (close_quotes("g1", "Tg1", 110.5, t=TIP0 - timedelta(minutes=10),
                      cap="C1")
         + close_quotes("g1", "Tg1", 110.5, t=TIP0 + timedelta(minutes=1),
                        cap="C2"))
    st = ev.close_status(q, "g1", "Tg1", 110.5, TIP0)
    assert st["reason"] is None and st["close_line"] == 110.5
    only_post = close_quotes("g1", "Tg1", 110.5,
                             t=TIP0 + timedelta(minutes=1), cap="C2")
    assert _close_reason(only_post) == "CLOSE_NOT_PRETIP"


def test_a2_straddling_last_capture_not_rescued():
    q = (close_quotes("g1", "Tg1", 110.5, t=TIP0 - timedelta(minutes=10),
                      cap="C1")
         + close_quotes("g1", "Tg1", 110.5, t=TIP0 - timedelta(seconds=30),
                        span=60, cap="C2")
         + close_quotes("g1", "Tg1", 110.5, t=TIP0 + timedelta(minutes=2),
                        cap="C3"))
    assert _close_reason(q) == "CLOSE_NOT_PRETIP"
