"""SportsEdge UFC production runtime.

Combines sportsbook-independent model probability with optional trained logistic
artifact, then evaluates live prices. Market prices are used only after the model
probability is produced. Model-level promotion is a separate hard gate: an
unpromoted model may generate diagnostics but may not populate official bets.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .ufc_engine import FighterSnapshot, FightContext, FightProjection, project_fight, monte_carlo, no_vig_two_way, truth_gate
from .ufc_source import OddsQuote, normalize_name, pair_h2h_quotes
from .ufc_training import LogisticArtifact


@dataclass(frozen=True)
class UFCCandidate:
    event_id: str
    fighter: str
    opponent: str
    bookmaker: str
    odds: int
    model_probability: float
    baseline_probability: float
    trained_probability: float | None
    market_no_vig: float
    edge: float
    ev: float
    fair_odds: int
    uncertainty: float
    passed: bool
    monte_carlo_probability: float
    reason: str


def snapshot_features(a: FighterSnapshot, b: FighterSnapshot) -> dict[str, float]:
    return {
        "elo_diff": a.elo - b.elo,
        "age_diff": a.age - b.age,
        "reach_diff": a.reach_in - b.reach_in,
        "height_diff": a.height_in - b.height_in,
        "slpm_diff": a.sig_strikes_landed_pm - b.sig_strikes_landed_pm,
        "sapm_diff": a.sig_strikes_absorbed_pm - b.sig_strikes_absorbed_pm,
        "str_acc_diff": a.sig_strike_accuracy - b.sig_strike_accuracy,
        "str_def_diff": a.sig_strike_defense - b.sig_strike_defense,
        "td_avg_diff": a.takedowns_per_15 - b.takedowns_per_15,
        "td_acc_diff": a.takedown_accuracy - b.takedown_accuracy,
        "td_def_diff": a.takedown_defense - b.takedown_defense,
        "sub_avg_diff": a.submissions_per_15 - b.submissions_per_15,
        "recent_win_rate_diff": a.recent_win_rate - b.recent_win_rate,
        "sos_diff": a.strength_of_schedule - b.strength_of_schedule,
        "rest_days_diff": a.days_since_last_fight - b.days_since_last_fight,
        "late_replacement_diff": float(a.late_replacement) - float(b.late_replacement),
        "experience_diff": (a.wins + a.losses) - (b.wins + b.losses),
    }


def ensemble_probability(a: FighterSnapshot, b: FighterSnapshot, ctx: FightContext,
                         artifact: LogisticArtifact | None = None,
                         baseline_weight: float = 0.35) -> tuple[float, float, float | None, float]:
    baseline = project_fight(a, b, ctx)
    trained = artifact.probability(snapshot_features(a, b)) if artifact else None
    if trained is None:
        p = baseline.p_a_win
        uncertainty = max(baseline.uncertainty, 0.16)
    else:
        bw = min(0.8, max(0.0, baseline_weight))
        p = bw * baseline.p_a_win + (1.0 - bw) * trained
        disagreement = abs(baseline.p_a_win - trained)
        uncertainty = min(0.35, baseline.uncertainty + 0.35 * disagreement)
    return p, baseline.p_a_win, trained, uncertainty


def _lookup_snapshots(fighters: Iterable[FighterSnapshot]) -> dict[str, FighterSnapshot]:
    out = {}
    for f in fighters:
        key = normalize_name(f.name)
        if key in out:
            raise ValueError(f"UFC_DUPLICATE_FIGHTER {f.name}")
        out[key] = f
    return out


def _recenter_projection(proj: FightProjection, p_a_win: float) -> FightProjection:
    """Reconcile method distribution to the ensemble ML probability."""
    p_a = min(1.0, max(0.0, float(p_a_win)))
    p_b = 1.0 - p_a
    a = [proj.p_a_ko, proj.p_a_sub, proj.p_a_dec]
    b = [proj.p_b_ko, proj.p_b_sub, proj.p_b_dec]
    a_total = sum(a)
    b_total = sum(b)
    if a_total <= 0.0:
        a = [0.0, 0.0, 1.0]
        a_total = 1.0
    if b_total <= 0.0:
        b = [0.0, 0.0, 1.0]
        b_total = 1.0
    a_ko, a_sub, a_dec = [p_a * x / a_total for x in a]
    b_ko, b_sub, b_dec = [p_b * x / b_total for x in b]
    p_gtd = a_dec + b_dec
    return replace(
        proj,
        p_a_win=p_a,
        p_b_win=p_b,
        p_a_ko=a_ko,
        p_a_sub=a_sub,
        p_a_dec=a_dec,
        p_b_ko=b_ko,
        p_b_sub=b_sub,
        p_b_dec=b_dec,
        p_goes_distance=p_gtd,
        p_inside_distance=1.0 - p_gtd,
    )


def _stable_seed(*parts: str) -> int:
    payload = "\x1f".join(parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def evaluate_h2h(*, fighters: Iterable[FighterSnapshot], quotes: Iterable[OddsQuote],
                 contexts: Mapping[frozenset[str], FightContext] | None = None,
                 artifact: LogisticArtifact | None = None,
                 min_edge: float = 0.025, min_ev: float = 0.03,
                 max_uncertainty: float = 0.20, n_sims: int = 250_000) -> list[UFCCandidate]:
    idx = _lookup_snapshots(fighters)
    contexts = contexts or {}
    out: list[UFCCandidate] = []
    for q1, q2 in pair_h2h_quotes(quotes):
        n1, n2 = normalize_name(q1.selection), normalize_name(q2.selection)
        a, b = idx.get(n1), idx.get(n2)
        if not a or not b:
            continue
        ctx = contexts.get(frozenset((n1, n2)), FightContext(rounds=5 if "title" in (a.weight_class + b.weight_class).lower() else 3))
        p1, base, trained, uncertainty = ensemble_probability(a, b, ctx, artifact)
        m1, m2 = no_vig_two_way(q1.price, q2.price)
        gate1 = truth_gate(prob=p1, odds=q1.price, market_novig=m1, uncertainty=uncertainty,
                           min_edge=min_edge, min_ev=min_ev, max_uncertainty=max_uncertainty)
        proj = _recenter_projection(project_fight(a, b, ctx), p1)
        seed = _stable_seed(q1.event_id, n1, n2, q1.bookmaker)
        sim = monte_carlo(proj, n=n_sims, seed=seed)
        sim_p1 = sim["a_win"]
        reason1 = "PASS" if gate1["pass"] else "TRUTH_GATE"
        out.append(UFCCandidate(q1.event_id, q1.selection, q2.selection, q1.bookmaker, q1.price,
                                p1, base, trained, m1, float(gate1["edge"]), float(gate1["ev"]),
                                int(gate1["fair_odds"]), uncertainty, bool(gate1["pass"]), sim_p1, reason1))
        p2 = 1.0 - p1
        gate2 = truth_gate(prob=p2, odds=q2.price, market_novig=m2, uncertainty=uncertainty,
                           min_edge=min_edge, min_ev=min_ev, max_uncertainty=max_uncertainty)
        out.append(UFCCandidate(q2.event_id, q2.selection, q1.selection, q2.bookmaker, q2.price,
                                p2, 1.0-base, None if trained is None else 1.0-trained, m2,
                                float(gate2["edge"]), float(gate2["ev"]), int(gate2["fair_odds"]),
                                uncertainty, bool(gate2["pass"]), 1.0-sim_p1,
                                "PASS" if gate2["pass"] else "TRUTH_GATE"))
    return sorted(out, key=lambda x: (x.passed, x.ev, x.edge), reverse=True)


def load_artifact(path: str | Path) -> LogisticArtifact:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return LogisticArtifact.from_dict(value)


def load_promotion_evidence(path: str | Path | None) -> Mapping[str, object]:
    if not path:
        return {"promoted": False, "status": "UNVERIFIED", "blockers": ["PROMOTION_EVIDENCE_MISSING"]}
    p = Path(path)
    if not p.exists():
        return {"promoted": False, "status": "UNVERIFIED", "blockers": ["PROMOTION_EVIDENCE_MISSING"]}
    value = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        return {"promoted": False, "status": "UNVERIFIED", "blockers": ["PROMOTION_EVIDENCE_INVALID"]}
    return value


def enforce_model_promotion(candidates: Sequence[UFCCandidate], evidence: Mapping[str, object]) -> list[UFCCandidate]:
    promoted = bool(evidence.get("promoted")) and str(evidence.get("status") or "").upper() == "PROMOTED"
    if promoted:
        return list(candidates)
    blockers = [str(x) for x in (evidence.get("blockers") or [])]
    suffix = "MODEL_UNPROMOTED" + ((":" + ",".join(blockers)) if blockers else "")
    return [replace(c, passed=False, reason=f"{c.reason}|{suffix}") for c in candidates]


def write_card(path: str | Path, candidates: Sequence[UFCCandidate], *, source: str = "SportsEdge UFC",
               promotion_evidence: Mapping[str, object] | None = None) -> None:
    promotion_evidence = promotion_evidence or {
        "promoted": False, "status": "UNVERIFIED", "blockers": ["PROMOTION_EVIDENCE_MISSING"]
    }
    payload = {
        "meta": {
            "sport": "UFC",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "sportsbook_independent_model": True,
            "model_promoted": bool(promotion_evidence.get("promoted")),
            "promotion_status": str(promotion_evidence.get("status") or "UNVERIFIED"),
            "promotion_blockers": [str(x) for x in (promotion_evidence.get("blockers") or [])],
        },
        "bets": [asdict(x) for x in candidates if x.passed],
        "candidates": [asdict(x) for x in candidates],
    }
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
