from datetime import datetime, timezone
from types import SimpleNamespace
from scripts.probe_direct_dk_six_sports import probe, SPORTS

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)

def test_unverified_sports_never_guess_endpoint():
    calls = []
    def fetch(key):
        calls.append(key)
        return SimpleNamespace(source_uri="https://sportsbook-nash.draftkings.com/test",
                               received_at=NOW, payload={"events": [], "markets": [{"name": "Total"}, {"name": "Moneyline"}, {"name": "Total"}]})
    result = probe(fetcher=fetch, clock=lambda: NOW)
    assert set(result["sports"]) == set(SPORTS)
    assert result["sports"]["NBA"]["status"] == "UNVERIFIED_MAPPING"
    assert result["sports"]["CBB"]["status"] == "UNVERIFIED_MAPPING"
    assert result["sports"]["NHL"]["status"] == "UNVERIFIED_MAPPING"
    assert result["sports"]["NFL"]["market_catalog"] == ["Moneyline", "Total"]
    assert result["sports"]["NFL"]["payload_markets"] == 3
    assert len(calls) == 3
    assert all(result["sports"][s]["status"] == "FETCHED" for s in ("NFL", "CFB", "MLB"))

def test_failure_is_unavailable_not_fake_prices():
    def fail(_):
        raise ValueError("network unavailable")
    result = probe(fetcher=fail, clock=lambda: NOW)
    assert all(result["sports"][s]["status"] == "UNAVAILABLE" for s in ("NFL", "CFB", "MLB"))
    assert all("price" not in str(v).lower() for v in result["sports"].values())
