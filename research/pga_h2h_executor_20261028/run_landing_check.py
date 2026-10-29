#!/usr/bin/env python3
"""Landing check for the PGA H2H Leg 1 executor — WIRING ONLY.

Exercises the executor end-to-end on the G-PGA-2 extracted corpus and
records what the plumbing does. It produces NO screen verdict and NO
criterion results: probabilities computed by the wiring simulation are
discarded, and the verdict path is invoked only to record its refusal.

What it verifies:
  * corpus pins (per-event content hashes + corpus hash) via the
    executor's own loader;
  * the Amendment 1 §3.2 headroom counts reproduce from the pinned
    corpus: unordered both-valid-rank pairs per test season
    (161,012 / 170,476 / 167,977 as measured by the amendment), plus
    the decided subset and the §3.2-step-4 fit-window pair counts;
  * the §4 pricing pipeline runs on every test-season event under
    explicitly labeled PLUMBING_ONLY parameter values, and the
    criterion-4-shaped volume count (priced pairs per season) is
    computed by the machinery;
  * the simulation wiring executes on one named event at a plumbing
    sim count (probabilities discarded);
  * the verdict path refuses, with its stamps and reasons recorded.

Output: landing_check_result.json beside this script (or --out).
Stdlib only. Exit 0 = wiring check completed (refusal recorded);
1 = a plumbing failure (pin mismatch, count drift, wiring error).
"""
import argparse
import itertools
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pga_h2h_executor as ex  # noqa: E402

# Plumbing-only parameter values: NOT design values. The design does
# not pin these constants; they exist so the wiring can execute, and
# they are labeled in every record they touch.
PLUMBING_CONFIG = ex.ExecutorConfig(
    shrinkage_prior_rounds=20.0,
    cut_size=65,
    day_draw_sd=0.35,
    n_sims=200,
    design_sim_count=200,
    seed=20261028,
)

AMENDMENT_HEADROOM = {2023: 161012, 2024: 170476, 2025: 167977}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extracted", default=os.path.expanduser("~/workspace/pga_screen_20261028/extracted_content"))
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "landing_check_result.json"))
    args = ap.parse_args()

    manifest_path = args.manifest or os.path.join(args.extracted, "content_manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)

    corpus = ex.load_corpus(args.extracted, manifest)
    record = {
        "executor_version": ex.EXECUTOR_VERSION,
        "check": "LANDING_CHECK_WIRING_ONLY",
        "stamps": ["PRE_ADOPTION_CHECK"],
        "screen_verdict": "NOT_EXECUTABLE",
        "verdict": None,
        "criteria": "NOT RUN — no verdict is produced by a landing check",
        "corpus": {
            "events": len(corpus.events),
            "rows": sum(len(e.rows) for e in corpus.events),
            "corpus_sha256": corpus.corpus_sha256,
            "pins_verified_by_loader": True,
            "manifest_status": corpus.manifest_status,
        },
        "plumbing_config": {
            "label": "PLUMBING_ONLY — not design values",
            "shrinkage_prior_rounds": PLUMBING_CONFIG.shrinkage_prior_rounds,
            "cut_size": PLUMBING_CONFIG.cut_size,
            "day_draw_sd": PLUMBING_CONFIG.day_draw_sd,
            "n_sims": PLUMBING_CONFIG.n_sims,
            "seed": PLUMBING_CONFIG.seed,
        },
    }

    # (b′) accumulation counts: amendment headroom reproduction.
    ref_b = {}
    for season in ex.TEST_SEASONS:
        test_events = [e for e in corpus.events if e.season == season]
        fit_events = [
            e for e in corpus.events if e.season <= ex.FIT_WINDOW_MAX_SEASON[season]
        ]
        both_valid = 0
        for ev in test_events:
            ranked = [r for r in ev.rows if ex.valid_rank(r.owgr_rank)]
            both_valid += len(ranked) * (len(ranked) - 1) // 2
        ref_b[str(season)] = {
            "test_event_both_valid_rank_pairs": both_valid,
            "amendment_headroom": AMENDMENT_HEADROOM[season],
            "headroom_reproduced": both_valid == AMENDMENT_HEADROOM[season],
            "fit_window_decided_pairs": len(ex.collect_bt_pairs(fit_events)),
            "test_event_decided_pairs_both_valid": len(ex.collect_bt_pairs(test_events)),
        }
    record["ref_b_prime_accumulation"] = ref_b
    if not all(v["headroom_reproduced"] for v in ref_b.values()):
        print("LANDING CHECK FAILED: amendment headroom counts did not reproduce")
        return 1

    # §4 pricing wiring over every test-season event + volume count.
    pricing = {}
    for season in ex.TEST_SEASONS:
        test_events = [e for e in corpus.events if e.season == season]
        total_pairs = 0
        total_priced = 0
        for ev in test_events:
            window = ex.FeatureWindow(corpus, ev)
            prices = ex.price_field(window, PLUMBING_CONFIG)
            total_priced += len(prices)
            total_pairs += len(prices) * (len(prices) - 1) // 2
        pricing[str(season)] = {
            "events": len(test_events),
            "priced_player_events": total_priced,
            "priced_pairs_criterion4_shaped": total_pairs,
            "volume_floor": ex.VOLUME_FLOOR_PER_SEASON,
            "floor_met_by_wiring_count": total_pairs >= ex.VOLUME_FLOOR_PER_SEASON,
        }
    record["pricing_wiring"] = pricing

    # Simulation wiring on one named event; probabilities discarded.
    masters = next(
        e for e in corpus.events if e.event_id == "14" and e.calendar_year == 2025
    )
    window = ex.FeatureWindow(corpus, masters)
    prices = ex.price_field(window, PLUMBING_CONFIG)
    counts = ex.simulate_event(prices, PLUMBING_CONFIG, random.Random(PLUMBING_CONFIG.seed))
    probs = ex.conditional_probs(counts)
    record["simulation_wiring"] = {
        "event": "14_2025-04-13 (Masters Tournament)",
        "field_rows": len(masters.rows),
        "priced_players": len(prices),
        "n_sims": PLUMBING_CONFIG.n_sims,
        "pairs_with_decided_simulations": len(probs),
        "probabilities": "computed and discarded — wiring only, not a screen result",
    }

    # Verdict path: record the refusal.
    try:
        ex.run_leg1(corpus, PLUMBING_CONFIG, ex.Gates())
        print("LANDING CHECK FAILED: verdict path did not refuse")
        return 1
    except ex.ScreenRefusal as r:
        record["verdict_path_refusal"] = {
            "verdict": r.verdict,
            "stamps": r.stamps,
            "reasons": r.reasons,
        }

    with open(args.out, "w") as f:
        json.dump(record, f, indent=1, sort_keys=True)
    print(f"corpus: {record['corpus']['events']} events, {record['corpus']['rows']} rows, pins verified")
    for s, v in ref_b.items():
        print(f"(b') {s}: headroom {v['test_event_both_valid_rank_pairs']} reproduced={v['headroom_reproduced']}; fit pairs {v['fit_window_decided_pairs']}")
    for s, v in pricing.items():
        print(f"pricing {s}: {v['priced_pairs_criterion4_shaped']} priced pairs over {v['events']} events")
    print(f"simulation wiring: {record['simulation_wiring']['pairs_with_decided_simulations']} pairs on the 2025 Masters at {PLUMBING_CONFIG.n_sims} sims (discarded)")
    print(f"verdict path refusal: {record['verdict_path_refusal']['reasons']}")
    print("LANDING CHECK COMPLETE — wiring only; screen verdict NOT_EXECUTABLE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
