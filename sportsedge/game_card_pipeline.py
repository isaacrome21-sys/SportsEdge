"""Unified card pipeline for canonical MLB game markets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .deployments import deployment_for
from .game_score_live import simulate_game, price_game_quote
from .nrfi_live import price_first_inning_quote
from .price_ttl import double_ttl_gate
from .quote_bridge import validate_canonical_quote
from .truth_gate import decide_bet

GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS", "NRFI", "YRFI"})

@dataclass(frozen=True)
class GameCardResult:
    game_id: str
    market: str
    entity_id: str
    line: Any
    side: str
    american_odds: Any
    model_p: float | None
    bet_status: str
    reason: str
    engine_version: str | None = None
    artifact_version: str | None = None
    monte_carlo_paths: int | None = None
    quote_age_seconds: float | None = None


def _features_by_game(rows: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    out = {}
    for row in rows:
        gid = str(row.get("game_id") or row.get("game_pk") or "").strip()
        if not gid:
            raise ValueError("GAME_FEATURE_IDENTITY_MISSING")
        if gid in out:
            raise ValueError("GAME_FEATURE_IDENTITY_DUPLICATE")
        out[gid] = row
    return out


def run_game_card(*, feature_rows: list[Mapping[str, Any]], quotes: list[Mapping[str, Any]], game_score_artifact: Mapping[str, Any], nrfi_artifact: Mapping[str, Any], ingestion_now: datetime, finalization_now: datetime, registry_path: str = "config/deployments.json", min_edge: float = 0.025, kelly_multiplier: float = 0.25) -> list[GameCardResult]:
    features = _features_by_game(feature_rows)
    sims: dict[str, Mapping[str, Any]] = {}
    out: list[GameCardResult] = []
    for raw in quotes:
        try:
            q = validate_canonical_quote(raw)
            market = q["market"]
            if market not in GAME_MARKETS:
                raise ValueError(f"UNSUPPORTED_GAME_MARKET: {market}")
            gid = q["game_id"]
            row = features.get(gid)
            if row is None:
                raise ValueError("GAME_FEATURES_MISSING")
            age_ingest, age_final = double_ttl_gate(q, ingestion_now, finalization_now)
            if market in {"MONEYLINE", "RUN_LINE", "TOTALS"}:
                run_rows = row.get("run_rows")
                if run_rows is None:
                    raise ValueError("RUN_FEATURES_MISSING")
                sim = sims.get(gid)
                if sim is None:
                    sim = simulate_game(game_score_artifact, run_rows, game_id=int(gid))
                    sims[gid] = sim
                priced = price_game_quote(sim, q)
                engine_version = str(priced.get("engine_version") or sim.get("engine_version") or "") or None
                artifact_version = str(priced.get("artifact_version") or sim.get("artifact_version") or "") or None
                mc_paths = int(priced.get("n_sims") or sim.get("n_sims") or 0) or None
            else:
                fi_row = row.get("fi_row")
                if fi_row is None:
                    raise ValueError("FIRST_INNING_FEATURES_MISSING")
                priced = price_first_inning_quote(nrfi_artifact, fi_row, q)
                engine_version = str(priced.get("engine_version") or "") or None
                artifact_version = str(priced.get("artifact_version") or "") or None
                mc_paths = None
            p = float(priced["model_p"])
            dep = deployment_for(market, registry_path)
            decision = decide_bet(p, q["american_odds"], bound=True, fresh=True, deployed=bool(dep["eligible"]), min_edge=min_edge, kelly_multiplier=kelly_multiplier)
            if decision.bet_status == "BLOCKED":
                reason = f"DEPLOYMENT_BLOCKED: {dep['stage']}: {dep['reason']}"
            elif decision.bet_status == "PASS":
                reason = "PRICE_OR_EDGE_GATE_NOT_MET"
            else:
                reason = "TRUTH_GATE_PASS"
            out.append(GameCardResult(gid, market, q["entity_id"], q["line"], q["side"], q["american_odds"], p, decision.bet_status, reason, engine_version, artifact_version, mc_paths, age_final))
        except Exception as exc:
            try:
                q = validate_canonical_quote(raw)
                ident = (q["game_id"], q["market"], q["entity_id"], q["line"], q["side"], q["american_odds"])
            except Exception:
                ident = ("UNKNOWN", "UNKNOWN", "", None, "UNKNOWN", None)
            out.append(GameCardResult(*ident, None, "BLOCKED", f"{type(exc).__name__}: {exc}"))
    if len(out) != len(quotes):
        raise RuntimeError("game card changed quote cardinality")
    return out
