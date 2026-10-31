"""Tests for the PGA H2H Leg 1 screen executor
(research/pga_h2h_executor_20261028/).

Covers: reference (b′) Bradley–Terry math and α fitting (Amendment 1
§3.2), the PIT discipline (design §5 — strictly-prior windows, composite
keys), the 40-round pricing floor, the dg_pts exclusion, the scoring
machinery, simulation determinism, and — above all — the verdict
path's refusals: no artifact that exists today may produce a verdict.
Synthetic corpora only; no workspace store is required.
"""
import hashlib
import importlib.util
import json
import math
import os
import random
import sys
from datetime import date

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKT = os.path.join(REPO, "research", "pga_h2h_executor_20261028")


def _load():
    spec = importlib.util.spec_from_file_location(
        "pga_h2h_executor", os.path.join(PKT, "pga_h2h_executor.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass processing needs the module registered
    spec.loader.exec_module(mod)
    return mod


ex = _load()


# ---------------------------------------------------------------- helpers


def _row(dg_id, fin="1", sg_rounds=(), scores=(), owgr_rank=-9999, close=-9999.0):
    rounds = []
    for i, (sg, sc) in enumerate(zip(sg_rounds, scores)):
        rounds.append({"r": i + 1, "score": sc, "par": 72, "sg": sg})
    return ex.PlayerRow(
        dg_id=dg_id, player_name=f"P{dg_id}", fin=fin, total=-5,
        rounds=rounds, open=close, close=close, owgr_rank=owgr_rank,
    )


def _event(event_id, year, season, day, rows):
    return ex.Event(
        event_id=event_id, calendar_year=year, season=season,
        day=day, name=f"E{event_id}/{year}", rows=rows,
    )


def _history_event(event_id, year, day, sg_by_player, season=None):
    rows = [
        _row(dg, sg_rounds=[sg] * 4, scores=[70] * 4)
        for dg, sg in sg_by_player.items()
    ]
    return _event(event_id, year, season or year, day, rows)


PLUMBING = ex.ExecutorConfig(
    shrinkage_prior_rounds=20.0, cut_size=65, day_draw_sd=0.0,
    n_sims=50, design_sim_count=50, seed=7,
)


# ---------------------------------------------------------------- (b′) math


def test_bt_prob_equal_ranks_is_half():
    assert ex.bt_prob(10, 10, 0.7) == 0.5


def test_bt_prob_matches_amendment_illustration():
    # Amendment 1 §3.2 step 3: McIlroy rank 2 vs Rose rank 39 at α=0.5.
    p = ex.bt_prob(2, 39, 0.5)
    assert abs(p - 0.815) < 0.001
    assert abs(p + ex.bt_prob(39, 2, 0.5) - 1.0) < 1e-12


def test_bt_prob_monotone_in_rank_gap_and_alpha():
    assert ex.bt_prob(1, 50, 0.5) > ex.bt_prob(1, 5, 0.5) > 0.5
    assert ex.bt_prob(1, 50, 1.5) > ex.bt_prob(1, 50, 0.5)


def test_valid_rank_rule():
    assert ex.valid_rank(1) and ex.valid_rank(1566)
    assert not ex.valid_rank(-9999) and not ex.valid_rank(-9998)
    assert not ex.valid_rank(None) and not ex.valid_rank(True) and not ex.valid_rank(2.5)


def test_fit_alpha_recovers_known_scale():
    rng = random.Random(11)
    pairs = []
    ranks = list(range(1, 61))
    true_alpha = 0.9
    for _ in range(4000):
        i, j = rng.sample(ranks, 2)
        p = ex.bt_prob(i, j, true_alpha)
        if rng.random() < p:
            pairs.append((i, j))
        else:
            pairs.append((j, i))
    fitted = ex.fit_alpha(pairs)
    assert abs(fitted - true_alpha) < 0.15


def test_fit_alpha_deterministic_and_bounded():
    pairs = [(1, 10)] * 30 + [(10, 1)] * 5 + [(3, 7)] * 12 + [(7, 3)] * 4
    a1 = ex.fit_alpha(pairs)
    a2 = ex.fit_alpha(list(pairs))
    assert a1 == a2
    assert 0.01 <= a1 <= 2.00


def test_fit_alpha_empty_pairs_refuses():
    with pytest.raises(ValueError):
        ex.fit_alpha([])


# ---------------------------------------------------------------- outcomes/scoring


def test_parse_finish_groups():
    assert ex.parse_finish("1") == (0, 1)
    assert ex.parse_finish("T3") == (0, 3)
    assert ex.parse_finish("MDF") == (1, None)
    assert ex.parse_finish("CUT") == (2, None)
    assert ex.parse_finish("WD") == (3, None)
    assert ex.parse_finish("DQ") == (3, None)
    assert ex.parse_finish(None) == (3, None)


def test_decided_pair_rules():
    assert ex.decided_pair("1", "2") == 1
    assert ex.decided_pair("2", "1") == -1
    assert ex.decided_pair("T3", "3") == 0  # same standing: tie
    assert ex.decided_pair("5", "CUT") == 1  # finisher ahead of missed cut
    assert ex.decided_pair("CUT", "CUT") == 0
    assert ex.decided_pair("MDF", "CUT") == 1
    assert ex.decided_pair("WD", "1") is None  # no standing: undecided
    assert ex.decided_pair("1", "DQ") is None


def test_log_loss_and_calibration():
    assert abs(ex.log_loss(0.8, 1) - (-math.log(0.8))) < 1e-12
    assert abs(ex.log_loss(0.8, 0) - (-math.log(0.2))) < 1e-12
    scored = [(0.95, 1)] * 10 + [(0.05, 0)] * 10
    cal, table = ex.calibration_error(scored)
    assert cal == pytest.approx(0.05, abs=1e-9)
    assert sum(b["n"] for b in table) == 20


def test_score_event_pairs_excludes_ties_and_undecided():
    ev = _event("9", 2025, 2025, date(2025, 5, 5), [
        _row(1, fin="1"), _row(2, fin="1"), _row(3, fin="CUT"), _row(4, fin="WD"),
    ])
    probs = {(1, 2): 0.6, (1, 3): 0.7, (1, 4): 0.9, (3, 4): 0.5}
    scored, ties, undecided = ex.score_event_pairs(probs, ev)
    assert scored == [(0.7, 1)]  # only the decided pair
    assert ties == 1 and undecided == 2


# ---------------------------------------------------------------- reference (a)


def test_ref_a_field_normalized_pairs():
    ev = _event("9", 2025, 2025, date(2025, 5, 5), [
        _row(1, close=2.0), _row(2, close=4.0), _row(3, close=-9999.0),
    ])
    probs = ex.ref_a_probs(ev)
    assert probs[1] == pytest.approx(2 / 3)
    assert probs[2] == pytest.approx(1 / 3)
    assert 3 not in probs  # sentinel close excluded
    assert ex.ref_a_pair(probs, 1, 2) == pytest.approx(2 / 3)
    assert ex.ref_a_pair(probs, 1, 3) is None


# ---------------------------------------------------------------- PIT discipline


def _pit_corpus(with_future):
    prior = _history_event("5", 2024, date(2024, 5, 1), {1: 1.0, 2: 0.0})
    target = _event("6", 2024, 2024, date(2024, 6, 1), [_row(1), _row(2)])
    events = [prior, target]
    if with_future:
        future = _history_event("7", 2024, date(2024, 7, 1), {1: 99.0, 2: -99.0})
        events.append(future)
    return ex.Corpus(events=events, corpus_sha256="x", manifest_status="DRAFT"), target


def test_future_event_cannot_enter_window():
    corpus_a, target_a = _pit_corpus(with_future=False)
    corpus_b, target_b = _pit_corpus(with_future=True)
    idx_a = ex.FeatureWindow(corpus_a, target_a).round_records()
    idx_b = ex.FeatureWindow(corpus_b, target_b).round_records()
    assert idx_a["per_player"][1] == idx_b["per_player"][1]
    assert idx_a["field_mean_sg"] == idx_b["field_mean_sg"]


def test_window_get_event_raises_on_future_and_target():
    corpus, target = _pit_corpus(with_future=True)
    window = ex.FeatureWindow(corpus, target)
    future = corpus.events[-1]
    with pytest.raises(ex.PITViolation):
        window.get_event(future)
    with pytest.raises(ex.PITViolation):
        window.get_event(target)


def test_composite_key_distinguishes_editions():
    a = _event("14", 2024, 2024, date(2024, 4, 14), [])
    b = _event("14", 2025, 2025, date(2025, 4, 13), [])
    assert a.key != b.key and a.key[0] == b.key[0] == "14"


def test_fit_alpha_uses_only_supplied_pairs():
    # α for a season is fitted from the fit-window pair list alone;
    # decided pairs from later events are structurally excluded by the
    # caller, and collect/fit never reach across the supplied set.
    fit_pairs = [(1, 20)] * 20 + [(20, 1)] * 2
    alpha_before = ex.fit_alpha(fit_pairs)
    later_pairs = [(1, 2)] * 500  # would drag α up if leaked in
    assert ex.fit_alpha(fit_pairs) == alpha_before
    assert ex.fit_alpha(fit_pairs + later_pairs) != alpha_before  # sanity: the sets differ


# ---------------------------------------------------------------- pricing floor + dg_pts


def _pricing_corpus(n_rounds_by_player):
    # 12 prior events x 4 rounds each = up to 48 SG rounds per player.
    events = []
    for k in range(12):
        sg = {}
        for dg, total_rounds in n_rounds_by_player.items():
            done = min(4, max(0, total_rounds - 4 * k))
            if done:
                sg[dg] = 1.0
        rows = [
            _row(dg, sg_rounds=[1.0] * done, scores=[70] * done)
            for dg, done in ((dg, min(4, max(0, t - 4 * k))) for dg, t in n_rounds_by_player.items())
            if done
        ]
        events.append(_event("5", 2023, 2023, date(2023, 3, 1 + k), rows))
    target = _event(
        "6", 2024, 2024, date(2024, 6, 1),
        [_row(dg) for dg in n_rounds_by_player],
    )
    events.append(target)
    return ex.Corpus(events=events, corpus_sha256="x", manifest_status="DRAFT"), target


def test_pricing_floor_40_rounds():
    corpus, target = _pricing_corpus({1: 48, 2: 40, 3: 39})
    prices = ex.price_field(ex.FeatureWindow(corpus, target), PLUMBING)
    assert 1 in prices and 2 in prices  # >= 40 measured rounds: priced
    assert 3 not in prices  # 39 rounds: UNPRICED, no silent prior


def test_excluded_fields_never_consumed():
    assert "dg_pts" not in ex.CONSUMED_ROW_FIELDS
    assert "dg_rank" not in ex.CONSUMED_ROW_FIELDS
    fields = set(ex.PlayerRow.__dataclass_fields__)
    assert "dg_pts" not in fields and "dg_rank" not in fields


# ---------------------------------------------------------------- simulation


def test_simulation_deterministic_and_counts_complete():
    prices = {
        dg: ex.PlayerPrice(dg_id=dg, skill=mu, course_adj=0.0, sd=1.5, n_rounds=50)
        for dg, mu in ((1, 0.8), (2, 0.0), (3, -0.8))
    }
    cfg = ex.ExecutorConfig(shrinkage_prior_rounds=20.0, cut_size=65,
                            day_draw_sd=0.3, n_sims=400, design_sim_count=400, seed=42)
    c1 = ex.simulate_event(prices, cfg, random.Random(42))
    c2 = ex.simulate_event(prices, cfg, random.Random(42))
    assert c1 == c2
    for pair, (a, b, t) in c1.items():
        assert a + b + t == 400
    probs = ex.conditional_probs(c1)
    assert probs[(1, 3)] > 0.9  # the widest skill gap prices highest
    assert probs[(1, 3)] > probs[(1, 2)]
    assert probs[(1, 2)] > 0.5 and probs[(2, 3)] > 0.5


# ---------------------------------------------------------------- refusals


def _draft_corpus():
    ev = _event("6", 2025, 2025, date(2025, 6, 1), [_row(1)])
    return ex.Corpus(events=[ev], corpus_sha256="x", manifest_status="DRAFT — NOT ADMITTED")


def test_verdict_refused_without_adoption_and_admission():
    with pytest.raises(ex.ScreenRefusal) as ei:
        ex.run_leg1(_draft_corpus(), PLUMBING, ex.Gates())
    r = ei.value
    assert r.verdict == "NOT_EXECUTABLE"
    assert r.stamps == ["PRE_ADOPTION_CHECK"]
    assert "AMENDMENT_1_NOT_ADOPTED" in r.reasons
    assert "CONTENT_PIN_NOT_ADMITTED" in r.reasons


def test_verdict_refused_on_draft_manifest_even_with_attested_gates():
    with pytest.raises(ex.ScreenRefusal) as ei:
        ex.run_leg1(_draft_corpus(), PLUMBING, ex.Gates(amendment_adopted=True, pin_admitted=True))
    assert ei.value.reasons == ["CONTENT_PIN_NOT_ADMITTED"]


def test_verdict_refused_on_unpinned_parameters():
    corpus = ex.Corpus(events=_draft_corpus().events, corpus_sha256="x",
                       manifest_status="ADMITTED (test fixture)")
    bare = ex.ExecutorConfig()  # nothing pinned
    with pytest.raises(ex.ScreenRefusal) as ei:
        ex.run_leg1(corpus, bare, ex.Gates(amendment_adopted=True, pin_admitted=True))
    reasons = ei.value.reasons
    assert "UNPINNED_DESIGN_PARAMETER:shrinkage_prior_rounds" in reasons
    assert "UNPINNED_DESIGN_PARAMETER:cut_size" in reasons
    assert "UNPINNED_DESIGN_PARAMETER:day_draw_sd" in reasons


def test_price_field_refuses_without_shrinkage():
    corpus, target = _pricing_corpus({1: 48})
    bare = ex.ExecutorConfig()
    with pytest.raises(ex.ScreenRefusal):
        ex.price_field(ex.FeatureWindow(corpus, target), bare)


# ---------------------------------------------------------------- corpus loader


def test_load_corpus_verifies_pins(tmp_path):
    content = {
        "event_id": "6", "calendar_year": 2025, "season": 2025,
        "date": "2025-06-01", "name": "Synthetic", "tour": "pga",
        "num_rounds": 4, "source_pages": [],
        "rows": [{
            "dg_id": 1, "player_name": "P1", "fin": "1", "total": -5,
            "rounds": [{"r": 1, "score": 68, "par": 72, "sg": 2.0}],
            "open": 10.0, "close": 9.0, "owgr_rank": 3,
            "excluded": {"dg_pts": 28.0, "dg_rank": 2},
        }],
    }
    body = (json.dumps(content, sort_keys=True) + "\n").encode()
    digest = hashlib.sha256(body).hexdigest()
    fname = "6_2025-06-01.json"
    (tmp_path / fname).write_bytes(body)
    entry = {"event_id": "6", "date": "2025-06-01", "content_file": fname,
             "content_sha256": digest}
    lines = f"6|2025-06-01|{digest}"
    corpus_hash = hashlib.sha256((lines + "\n").encode()).hexdigest()
    manifest = {"status": "DRAFT — NOT ADMITTED", "corpus_sha256": corpus_hash,
                "events": [entry]}
    corpus = ex.load_corpus(str(tmp_path), manifest)
    assert len(corpus.events) == 1
    assert corpus.events[0].rows[0].owgr_rank == 3
    # tampered bytes fail the pin
    (tmp_path / fname).write_bytes(body + b" ")
    with pytest.raises(ValueError):
        ex.load_corpus(str(tmp_path), manifest)
