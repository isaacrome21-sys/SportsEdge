#!/usr/bin/env python3
"""
SportsEdge Production Foundation v0.1
======================================
The repo-level baseline for when GitHub access returns. Encodes today's
hard-won lessons as enforced mechanisms, not just documentation:

  - canonical identity resolution BEFORE any classification/filtering
    (this is the Athletics bug, made permanently regression-tested)
  - SOURCE_MANIFEST: every input to a run carries explicit provenance
  - referential integrity: every computed value must trace to a real,
    present manifest entry, or it's a MISSING_LINEAGE violation
  - SOURCE_CONFLICT: two providers disagreeing about the same fact is
    surfaced and blocked, never silently resolved by picking one
  - artifact/hash startup checks: registry-declared artifact hashes are
    verified against the actual files on disk at boot, every run
  - MODEL_STATUS vs BET_STATUS: whether a model is validated (research
    question, static) is kept separate from whether a specific candidate
    bet is eligible right now (operational question, per-run)
  - rollback/quarantine: a hash mismatch or conflict quarantines that
    market for this run without crashing the rest of the slate
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

SCHEMA_VERSION = "0.2"

TEAM_ALIASES: Dict[str, str] = {
    "athletics athletics": "ATH", "oakland athletics": "ATH",
    "sacramento athletics": "ATH", "athletics": "ATH", "ath": "ATH",
    "arizona diamondbacks": "ARI", "az": "ARI", "diamondbacks": "ARI",
}
EXPECTED_TEAM_COUNT = 30


def canonical_team_id(raw_name: Optional[str], raw_short: Optional[str] = None) -> Optional[str]:
    if raw_short and raw_short.strip().upper() in {
        "ARI","ATL","BAL","BOS","CHC","CHW","CIN","CLE","COL","DET","HOU",
        "KC","LAA","LAD","MIA","MIL","MIN","NYM","NYY","PHI","PIT","SD",
        "SEA","SF","STL","TB","TEX","TOR","WAS","ATH"
    }:
        return raw_short.strip().upper()
    key = (raw_name or "").strip().lower()
    return TEAM_ALIASES.get(key)


def raw_entity_coverage_check(raw_rows: List[dict], expected: int = EXPECTED_TEAM_COUNT) -> Dict[str, Any]:
    teams: Set[str] = set()
    unresolved: List[str] = []
    for r in raw_rows:
        for prefix in ("away", "home"):
            raw_name = r.get(f"{prefix}_full") or r.get(f"{prefix}_team")
            raw_short = r.get(f"{prefix}_short")
            cid = canonical_team_id(raw_name, raw_short)
            if cid:
                teams.add(cid)
            elif raw_name or raw_short:
                unresolved.append(str(raw_name or raw_short))
    return {
        "checked_on": "RAW rows, before any classification/filter",
        "distinct_canonical_teams": len(teams),
        "expected_teams": expected,
        "pass": len(teams) >= expected,
        "unresolved_names": sorted(set(unresolved)),
        "teams": sorted(teams),
    }

PROVIDER_AUTHORITY = {
    "MLB_OFFICIAL": 100,
    "TEAM_OFFICIAL": 95,
    "MLB_API": 90,
    "BEAT_REPORTER": 80,
    "ESTABLISHED_OUTLET": 70,
    "ODDS_API": 90,
    "SPORTSBOOK": 95,
    "SOCIAL_VERIFIED": 60,
    "SOCIAL_UNVERIFIED": 10,
    "UNKNOWN": 0,
}

BLOCKING_FACT_PREFIXES = (
    "starter:", "opener:", "bulk:", "confirmed_lineup:", "roof:", "dk_price:"
)

DEFAULT_TTL_SECONDS = {
    "dk_price": 120,
    "confirmed_lineup": 900,
    "starter": 1800,
    "opener": 1800,
    "bulk": 1800,
    "roof": 1800,
    "umpire": 3600,
    "injury": 3600,
    "scratch": 900,
    "manager_comment": 7200,
    "bullpen_usage": 21600,
    "pitch_count": 21600,
    "weather": 1800,
}

MAX_EVENT_AGE_SECONDS = {
    "pitch_count": 10 * 86400,
    "bullpen_usage": 4 * 86400,
    "injury": 30 * 86400,
    "manager_comment": 7 * 86400,
}


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except Exception:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _fact_class(fact_key: str) -> str:
    return fact_key.split(":", 1)[0]


@dataclass
class SourceEntry:
    source_id: str
    fact_key: str
    value: Any
    provider: str
    as_of: str
    retrieved_at: str
    payload_hash: Optional[str] = None
    confidence: str = "verified"

    def event_age_seconds(self, now: datetime) -> Optional[float]:
        ts = _parse_ts(self.as_of)
        if ts is None or ts > now:
            return None
        return (now - ts).total_seconds()

    def retrieval_age_seconds(self, now: datetime) -> Optional[float]:
        ts = _parse_ts(self.retrieved_at)
        if ts is None or ts > now:
            return None
        return (now - ts).total_seconds()

    @property
    def authority(self) -> int:
        return PROVIDER_AUTHORITY.get(self.provider.upper(), PROVIDER_AUTHORITY["UNKNOWN"])

    def usable(self, now: datetime, ttl_seconds: Optional[int] = None) -> Tuple[bool, str]:
        if self.confidence.lower() == "unverified" or self.provider.upper() == "SOCIAL_UNVERIFIED":
            return False, "UNVERIFIED_SOURCE"
        r_age = self.retrieval_age_seconds(now)
        if r_age is None:
            return False, "INVALID_OR_FUTURE_RETRIEVAL_TIMESTAMP"
        cls = _fact_class(self.fact_key)
        ttl = ttl_seconds if ttl_seconds is not None else DEFAULT_TTL_SECONDS.get(cls)
        if ttl is not None and r_age > ttl:
            return False, "STALE_RETRIEVAL"
        e_age = self.event_age_seconds(now)
        max_event = MAX_EVENT_AGE_SECONDS.get(cls)
        if max_event is not None and (e_age is None or e_age > max_event):
            return False, "EVENT_TOO_OLD_OR_INVALID"
        return True, "USABLE"


def build_source_manifest(raw_sources: List[dict]) -> Dict[str, SourceEntry]:
    manifest: Dict[str, SourceEntry] = {}
    for s in raw_sources:
        sid = s["source_id"]
        if sid in manifest:
            raise ValueError(f"duplicate source_id: {sid}")
        e = SourceEntry(
            source_id=sid, fact_key=s["fact_key"], value=s.get("value"),
            provider=s.get("provider", "UNKNOWN"), as_of=s.get("as_of", ""),
            retrieved_at=s.get("retrieved_at", ""), payload_hash=s.get("payload_hash"),
            confidence=s.get("confidence", "verified"),
        )
        manifest[e.source_id] = e
    return manifest


def adjudicate_fact(entries: List[SourceEntry], now: datetime, ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
    usable = []
    rejected = []
    for e in entries:
        ok, reason = e.usable(now, ttl_seconds)
        (usable if ok else rejected).append((e, reason))
    if not usable:
        return {"status": "NO_USABLE_SOURCE", "rejected": [
            {"source_id": e.source_id, "reason": r} for e, r in rejected]}
    values = {}
    for e, _ in usable:
        values.setdefault(json.dumps(e.value, sort_keys=True, default=str), []).append(e)
    fact_key = usable[0][0].fact_key
    if len(values) == 1:
        winner = max((e for e, _ in usable), key=lambda x: x.authority)
        return {"status": "RESOLVED", "value": winner.value, "source_id": winner.source_id,
                "authority": winner.authority, "rejected": [
                    {"source_id": e.source_id, "reason": r} for e, r in rejected]}
    flat = [e for group in values.values() for e in group]
    if fact_key.startswith(BLOCKING_FACT_PREFIXES):
        return {"status": "SOURCE_CONFLICT", "fact_key": fact_key,
                "conflicting_sources": [{"source_id": e.source_id, "provider": e.provider,
                                          "authority": e.authority, "value": e.value} for e in flat]}
    ranked = sorted(flat, key=lambda x: x.authority, reverse=True)
    if len(ranked) > 1 and ranked[0].authority > ranked[1].authority:
        return {"status": "RESOLVED_BY_AUTHORITY", "value": ranked[0].value,
                "source_id": ranked[0].source_id, "authority": ranked[0].authority}
    return {"status": "SOURCE_CONFLICT", "fact_key": fact_key,
            "conflicting_sources": [{"source_id": e.source_id, "provider": e.provider,
                                      "authority": e.authority, "value": e.value} for e in flat]}


def detect_source_conflicts(manifest: Dict[str, SourceEntry], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    by_fact: Dict[str, List[SourceEntry]] = {}
    for e in manifest.values():
        by_fact.setdefault(e.fact_key, []).append(e)
    conflicts = []
    for fact_key, entries in by_fact.items():
        result = adjudicate_fact(entries, now)
        if result.get("status") == "SOURCE_CONFLICT":
            conflicts.append(result)
    return conflicts


def check_referential_integrity(claimed_dependencies: List[str], manifest: Dict[str, SourceEntry]) -> List[str]:
    return [d for d in claimed_dependencies if d not in manifest]


def verify_artifact_hashes(registry: Dict[str, Any], base_dir: Path) -> Dict[str, Dict[str, Any]]:
    results = {}
    for market, rec in registry.get("markets", {}).items():
        art = rec.get("artifact")
        if not art:
            continue
        path = base_dir / art["path"]
        if not path.exists():
            results[market] = {"status": "MISSING_ARTIFACT_FILE", "path": str(path)}
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = art["artifact_hash"]
        if actual != expected:
            results[market] = {"status": "HASH_MISMATCH", "expected": expected, "actual": actual}
        else:
            results[market] = {"status": "VERIFIED", "hash": actual}
    return results


def model_status(registry: Dict[str, Any], market: str) -> Dict[str, Any]:
    rec = registry.get("markets", {}).get(market, {
        "status": "UNVALIDATED", "official_eligible": False,
        "reason": "market absent from registry"})
    return {"market": market, "model_status": rec.get("status", "UNVALIDATED"),
            "model_eligible": bool(rec.get("official_eligible", False)),
            "reason": rec.get("reason", "")}


@dataclass
class QuarantineRecord:
    market: str
    cause: str
    detail: Dict[str, Any]
    last_known_good_hash: Optional[str] = None


def bet_status(market: str, registry: Dict[str, Any], base_dir: Path,
               manifest: Dict[str, SourceEntry], now: datetime,
               required_fact_keys: List[str],
               freshness_limits: Dict[str, int],
               claimed_dependencies: List[str]) -> Tuple[str, Dict[str, Any], Optional[QuarantineRecord]]:
    ms = model_status(registry, market)
    if not ms["model_eligible"]:
        return "BLOCKED", {"reason": f"model not eligible: {ms['reason']}"}, None

    hash_results = verify_artifact_hashes(registry, base_dir)
    if market in hash_results and hash_results[market]["status"] != "VERIFIED":
        q = QuarantineRecord(market, "ARTIFACT_HASH_MISMATCH_OR_MISSING",
                             hash_results[market],
                             registry["markets"][market].get("artifact", {}).get("artifact_hash"))
        return "QUARANTINED", {"reason": "artifact failed startup verification",
                               "detail": hash_results[market]}, q

    missing_lineage = check_referential_integrity(claimed_dependencies, manifest)
    if missing_lineage:
        return "BLOCKED", {"reason": "MISSING_LINEAGE", "missing_source_ids": missing_lineage}, None

    conflicts = detect_source_conflicts(manifest, now)
    relevant_conflicts = []
    for c in conflicts:
        dep_ids = {e["source_id"] for e in c.get("conflicting_sources", [])}
        if dep_ids.intersection(claimed_dependencies) or c.get("fact_key") in required_fact_keys:
            relevant_conflicts.append(c)
    if relevant_conflicts:
        return "BLOCKED", {"reason": "SOURCE_CONFLICT", "conflicts": relevant_conflicts}, None

    stale = []
    for fk in required_fact_keys:
        matching = [e for e in manifest.values() if e.fact_key == fk]
        if not matching:
            return "BLOCKED", {"reason": f"no source for required fact_key '{fk}'"}, None
        result = adjudicate_fact(matching, now, freshness_limits.get(fk))
        if result["status"] == "NO_USABLE_SOURCE":
            stale.append({"fact_key": fk, "rejected": result.get("rejected", [])})
        elif result["status"] == "SOURCE_CONFLICT":
            return "BLOCKED", {"reason": "SOURCE_CONFLICT", "conflicts": [result]}, None
    if stale:
        return "STALE", {"reason": "one or more required facts have no usable fresh source", "stale": stale}, None

    return "PASS", {"reason": "model eligible, artifact verified, lineage intact, no conflicts, inputs fresh"}, None


def run_foundation(snapshot: Dict[str, Any], registry: Dict[str, Any],
                   base_dir: Path, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)

    raw_rows = snapshot.get("raw_rows", [])
    coverage = raw_entity_coverage_check(raw_rows) if raw_rows else {
        "pass": False, "checked_on": "RAW rows, before any classification/filter",
        "distinct_canonical_teams": 0,
        "unresolved_names": [], "teams": [],
        "note": "no raw rows supplied"}

    manifest = build_source_manifest(snapshot.get("sources", []))
    hash_results = verify_artifact_hashes(registry, base_dir)
    quarantine: List[QuarantineRecord] = []

    market_results = []
    for m in snapshot.get("candidate_markets", []):
        market = m["market"]
        status, detail, q = bet_status(
            market, registry, base_dir, manifest, now,
            required_fact_keys=m.get("required_fact_keys", []),
            freshness_limits=m.get("freshness_limits", {}),
            claimed_dependencies=m.get("claimed_dependencies", []),
        )
        if q:
            quarantine.append(q)
        market_results.append({
            "market": market,
            "model_status": model_status(registry, market),
            "bet_status": status,
            "detail": detail,
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "run_at_utc": now.isoformat(),
        "raw_entity_coverage": coverage,
        "artifact_hash_check": hash_results,
        "source_conflicts": detect_source_conflicts(manifest, now),
        "quarantine": [asdict(q) for q in quarantine],
        "market_results": market_results,
    }
