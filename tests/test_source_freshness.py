from datetime import datetime, timedelta, timezone
import json

from sportsedge.source_freshness import evaluate_source_freshness


def _contract(tmp_path):
    path = tmp_path / "freshness.json"
    path.write_text(json.dumps({
        "sources": {
            "lineup": {"max_age_seconds": 1200, "freshness_clock": "last_verified_at", "absence_policy": "DEGRADE", "stale_policy": "BLOCK", "provider_tier": "PRIMARY"},
            "statcast": {"max_age_seconds": 172800, "freshness_clock": "retrieved_at", "absence_policy": "BLOCK", "stale_policy": "BLOCK", "provider_tier": "PRIMARY_STATS"},
            "park": {"max_age_seconds": None, "freshness_clock": "artifact_hash", "absence_policy": "BLOCK", "stale_policy": "NA", "provider_tier": "VALIDATED_STATIC_ARTIFACT"}
        }
    }))
    return path


def test_absent_is_not_stale(tmp_path):
    now = datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)
    result = evaluate_source_freshness("lineup", None, now=now, contract_path=_contract(tmp_path))
    assert result.state == "ABSENT"
    assert result.policy == "DEGRADE"


def test_lineup_stales_on_short_ttl(tmp_path):
    now = datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)
    result = evaluate_source_freshness("lineup", {"last_verified_at": (now - timedelta(minutes=21)).isoformat()}, now=now, contract_path=_contract(tmp_path))
    assert result.state == "STALE"
    assert result.policy == "BLOCK"


def test_statcast_can_be_one_day_old_and_remain_fresh(tmp_path):
    now = datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)
    result = evaluate_source_freshness("statcast", {"retrieved_at": (now - timedelta(hours=30)).isoformat()}, now=now, contract_path=_contract(tmp_path))
    assert result.state == "FRESH"


def test_statcast_over_two_days_is_stale(tmp_path):
    now = datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)
    result = evaluate_source_freshness("statcast", {"retrieved_at": (now - timedelta(hours=49)).isoformat()}, now=now, contract_path=_contract(tmp_path))
    assert result.state == "STALE"


def test_immutable_park_requires_verified_hash(tmp_path):
    now = datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)
    bad = evaluate_source_freshness("park", {"artifact_hash": "abc"}, now=now, contract_path=_contract(tmp_path))
    good = evaluate_source_freshness("park", {"artifact_hash": "abc", "hash_verified": True}, now=now, contract_path=_contract(tmp_path))
    assert bad.state == "INVALID"
    assert good.state == "FRESH"
