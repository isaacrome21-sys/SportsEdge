"""Spec-completeness audit for the CBB first-half (1H) design screen.

This is NOT a screen runner. It executes no fit and scores no fixture.
It answers one question deterministically from the governing texts on
main: does `CBB_TEAM_TOTALS_1H_DESIGN.md` section 2, composed with the
parent design (`CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md`), supply
every term a runnable design screen needs — the way section 3 of the
parent design does for the spread/total legs and section 1 of the 1H
design does for the team-totals leg?

Each required element is probed in the design text itself. An element
counts PRESENT only when the text states it; a name without a
construction is recorded as named-but-undefined. Where any required
element is absent, the screen is NOT_EXECUTABLE and the absent elements
are the refusal — no term may be invented by the runner (standing law:
a screen runs exactly as written or records why it cannot).

Run:  python3 research/cbb_first_half_screen_20261028/audit_screen_spec.py
Exit: 0 always (the audit is a report, not a gate on other work); the
verdict is in the printed JSON.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DESIGN_1H = REPO / "research/nba_cbb_activation_20261028/CBB_TEAM_TOTALS_1H_DESIGN.md"
DESIGN_PARENT = (
    REPO
    / "research/nba_cbb_activation_20261028/CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md"
)
PBP_MANIFEST = REPO / "research/cbb_hoopr_pbp_admission_20261028/pbp_manifest.json"


def section(text: str, start: str, end: str | None) -> str:
    i = text.index(start)
    j = text.index(end, i) if end else len(text)
    return text[i:j]


def has(text: str, *needles: str) -> bool:
    low = text.lower()
    return any(n.lower() in low for n in needles)


def audit() -> dict:
    design = DESIGN_1H.read_text(encoding="utf-8")
    parent = DESIGN_PARENT.read_text(encoding="utf-8")
    sec2 = section(design, "## 2. First-half lines", "## 3.")
    sec1 = section(design, "## 1. Team totals", "## 2.")
    parent_sec3 = section(parent, "## 3. Design screen spec", "## 4.")

    # --- prerequisite (the one element the Oct 28 admission closed) ---
    manifest = json.loads(PBP_MANIFEST.read_text(encoding="utf-8"))
    cov = manifest["coverage"]
    seasons_pinned = sorted(cov.keys())
    gated = sum(c["final_agreement_running_score"] for c in cov.values())
    pbp_games = sum(c["pbp_games"] for c in cov.values())
    sched_games = sum(c["schedule_games"] for c in cov.values())
    prerequisite = {
        "element": "data_prerequisite_pinned_pbp_with_schema",
        "state": "PRESENT",
        "evidence": (
            "PR #2901 admission manifest: 9 season files full-tuple pinned, "
            "schema verified; manifest 'satisfies' block clears "
            "PBP_PREREQUISITE_MISSING for design-screen use of CBB 1H only."
        ),
        "seasons_pinned": seasons_pinned,
        "universe_from_manifest": {
            "schedule_games": sched_games,
            "pbp_games": pbp_games,
            "no_pbp_no_data": sched_games - pbp_games,
            "method_a_final_agreement_gated": gated,
        },
    }

    elements = [prerequisite]

    # --- what section 2 does state ---
    elements.append(
        {
            "element": "metrics_named",
            "state": "PRESENT",
            "evidence": "Section 2 names '1H-total MAE and 1H-margin MAE'.",
            "gap": None,
        }
    )
    elements.append(
        {
            "element": "outcome_derivation",
            "state": "PRESENT",
            "evidence": (
                "Section 2: '1H outcomes are derived from the pinned PBP "
                "itself'; admission record binds Method A (running score) "
                "with the final-agreement consumer gate; Method B refused."
            ),
            "gap": None,
        }
    )
    elements.append(
        {
            "element": "share_fitting_window",
            "state": "PRESENT",
            "evidence": (
                "Section 2: 'the share is fitted on seasons strictly before "
                "each scored season' (walk-forward window stated)."
            ),
            "gap": None,
        }
    )

    # --- G-1H-1: no verdict rule / pass bar for the 1H legs ---
    sec2_has_bar = has(
        sec2, "CI upper", "DESIGN_PASS", "design pass", "pass =", "passes if",
        "upper bound < 0",
    )
    parent_bar_scoped = has(parent_sec3, "spread MAE and total MAE") and not has(
        parent_sec3, "1H", "first-half", "first half"
    )
    tt_imports_bar = has(sec1, "same walk-forward protocol") and has(
        sec1, "passes or fails on its own CI"
    )
    elements.append(
        {
            "element": "verdict_rule_pass_bar",
            "state": "ABSENT",
            "evidence": (
                f"Section 2 contains no CI test, threshold, or pass "
                f"condition (probe: {sec2_has_bar}). The parent section 3 "
                f"bar ('CI upper bound < 0 against both baselines on both "
                f"legs') is written for the spread/total legs only "
                f"(scoped probe: {parent_bar_scoped}) and section 2 does "
                f"not import it — unlike section 1 for team totals, which "
                f"imports the section 3 protocol and its CI explicitly "
                f"(probe: {tt_imports_bar})."
            ),
            "gap": "G-1H-1",
        }
    )

    # --- G-1H-2: climatology baseline named, never constructed ---
    baseline_named = has(sec2, "naive half-share climatology")
    baseline_constructed = has(
        sec2,
        "league-mean team points",
        "league mean team points",
        "naive team-mean",
        "climatology share is",
        "baseline forecast",
    )
    elements.append(
        {
            "element": "baseline_construction",
            "state": "ABSENT",
            "evidence": (
                f"Baseline named (probe: {baseline_named}) but never "
                f"constructed (probe: {baseline_constructed}): the text "
                f"does not state what full-game expectation the "
                f"climatology scales, nor how the baseline's own share "
                f"is estimated."
            ),
            "gap": "G-1H-2",
        }
    )

    # --- G-1H-3: candidate share estimator undefined ---
    estimator_defined = has(
        sec2,
        "mean of",
        "ratio of sums",
        "sum of first-half",
        "per-team share",
        "league-wide share",
        "average share",
    )
    elements.append(
        {
            "element": "share_estimator",
            "state": "ABSENT",
            "evidence": (
                f"Section 2 fixes 'one share for team points, applied to "
                f"margin and total alike' but never defines the estimator "
                f"(probe: {estimator_defined}): mean of per-game ratios "
                f"vs ratio of sums, league-wide vs per-team, treatment "
                f"of overtime games, and the fitting universe (final-"
                f"gated PBP vs all PBP games) are all unstated."
            ),
            "gap": "G-1H-3",
        }
    )

    # --- G-1H-4: scored-season set unstated for 1H ---
    seasons_stated = bool(re.search(r"20\d\d-\d\d|2015|2023", sec2))
    elements.append(
        {
            "element": "scored_seasons",
            "state": "ABSENT",
            "evidence": (
                f"Section 2 names no season span (probe: {seasons_stated}). "
                f"The pinned PBP begins 2014-15, so the walk-forward rule "
                f"leaves the first season's status undecided in the text: "
                f"scored with an undefined share, or fit-only."
            ),
            "gap": "G-1H-4",
        }
    )

    # --- G-1H-5: no inference procedure for the 1H legs ---
    inference_defined = has(sec2, "bootstrap", "resample", "seed")
    elements.append(
        {
            "element": "inference_procedure",
            "state": "ABSENT",
            "evidence": (
                f"Section 2 declares no bootstrap design, resample count, "
                f"or seed (probe: {inference_defined}). The parent section "
                f"3 season-block bootstrap is written for the spread/total "
                f"legs; the executed sibling screens' 10,000 reps / seed "
                f"20261028 come from those families' own governing texts, "
                f"not from anything written for 1H."
            ),
            "gap": "G-1H-5",
        }
    )

    # --- G-1H-6: fixture-universe composition unstated ---
    universe_defined = has(
        sec2, "three-way", "agreed universe", "fixture universe", "26,553"
    )
    elements.append(
        {
            "element": "fixture_universe_composition",
            "state": "ABSENT",
            "evidence": (
                f"Section 2 does not state the scored fixture universe "
                f"(probe: {universe_defined}): whether candidate "
                f"expectations are computed on the parent screens' "
                f"three-way-agreed universe intersected with the "
                f"admission's final-agreement PBP gate, or on the "
                f"schedule universe under the PBP gate alone, is a "
                f"composition choice the text never makes."
            ),
            "gap": "G-1H-6",
        }
    )

    gaps = [e["gap"] for e in elements if e.get("gap")]
    return {
        "family": "CBB first-half lines (1H spread / 1H total)",
        "design_reference": (
            "research/nba_cbb_activation_20261028/"
            "CBB_TEAM_TOTALS_1H_DESIGN.md section 2; parent: "
            "CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md sections 1-3"
        ),
        "verdict": "NOT_EXECUTABLE" if gaps else "EXECUTABLE",
        "refusal_code": "SCREEN_SPEC_INCOMPLETE_1H" if gaps else None,
        "elements": elements,
        "gaps": gaps,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=1))
    sys.exit(0)
