import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from scripts.probe_direct_dk_six_sports import probe, SPORTS, selection_linkage

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)

def test_unverified_sports_never_guess_endpoint():
    calls = []
    def fetch(key):
        calls.append(key)
        return SimpleNamespace(sport_key=key, source_uri="https://sportsbook-nash.draftkings.com/test",
                               received_at=NOW, raw=b"synthetic-direct-dk-board", payload={"events": [], "selections": [{"id": 1, "marketId": "A"}, {"id": 2, "marketId": "missing"}], "markets": [{"id": "A", "name": "Total"}, {"id": "B", "name": "Moneyline"}, {"id": "C", "name": "Total"}]})
    result = probe(fetcher=fetch, clock=lambda: NOW)
    assert set(result["sports"]) == set(SPORTS)
    assert result["sports"]["NBA"]["status"] == "UNVERIFIED_MAPPING"
    assert result["sports"]["CBB"]["status"] == "UNVERIFIED_MAPPING"
    assert result["sports"]["NHL"]["status"] == "UNVERIFIED_MAPPING"
    assert result["sports"]["NFL"]["market_catalog"] == ["Moneyline", "Total"]
    assert result["sports"]["NFL"]["quote_jurisdiction"] == "UNVERIFIED"
    assert result["sports"]["NFL"]["playable_in_user_jurisdiction"] is False
    assert result["sports"]["NFL"]["quote_timestamp_status"] == "UNVERIFIED"
    assert result["sports"]["NFL"]["payload_selections"] == 2
    assert result["sports"]["NFL"]["unlinked_selections"] == 1
    assert result["sports"]["NFL"]["linked_selections"] == 1
    assert result["sports"]["NFL"]["duplicate_market_ids"] == 0
    assert result["sports"]["NFL"]["markets_without_event"] == 3
    assert result["sports"]["NFL"]["duplicate_event_ids"] == 0
    assert result["sports"]["NFL"]["payload_markets"] == 3
    assert result["sports"]["NFL"]["market_counts"] == {"Moneyline": 1, "Total": 2}
    assert result["sports"]["NFL"]["raw_size_bytes"] == len(b"synthetic-direct-dk-board")
    assert result["sports"]["NFL"]["raw_sha256"] == hashlib.sha256(b"synthetic-direct-dk-board").hexdigest()
    assert len(calls) == 3
    assert all(result["sports"][s]["status"] == "FETCHED" for s in ("NFL", "CFB", "MLB"))

def test_failure_is_unavailable_not_fake_prices():
    def fail(_):
        raise ValueError("network unavailable")
    result = probe(fetcher=fail, clock=lambda: NOW)
    assert all(result["sports"][s]["status"] == "UNAVAILABLE" for s in ("NFL", "CFB", "MLB"))
    assert all("price" not in str(v).lower() for v in result["sports"].values())

def test_duplicate_market_ids_are_detected():
    payload = {"markets": [{"id": 10}, {"id": "10"}],
               "selections": [{"marketId": 10}, {"marketId": "missing"}, {}]}
    assert selection_linkage(payload) == {
        "markets_without_event": None, "duplicate_event_ids": None,
        "unlinked_selections": 2, "linked_selections": 1, "duplicate_market_ids": 1,
    }
    assert selection_linkage({"markets": None, "selections": []}) is None

def test_duplicate_event_ids_are_detected():
    payload = {"events": [{"id": 42}, {"id": "42"}],
               "markets": [{"id": 1, "eventId": 42}],
               "selections": [{"marketId": 1}]}
    result = selection_linkage(payload)
    assert result["duplicate_event_ids"] == 1
    assert result["markets_without_event"] == 0
    assert result["linked_selections"] == 1

def test_mismatched_source_sport_is_unavailable():
    def wrong_sport(_):
        return SimpleNamespace(sport_key="baseball_mlb", raw=b"{}", payload={},
                               source_uri="https://sportsbook-nash.draftkings.com/test", received_at=NOW)
    result = probe(fetcher=wrong_sport, clock=lambda: NOW)
    assert result["sports"]["NFL"]["status"] == "UNAVAILABLE"
    assert result["sports"]["CFB"]["status"] == "UNAVAILABLE"

def test_naive_receipt_time_is_unavailable():
    def naive(key):
        return SimpleNamespace(sport_key=key, raw=b"{}", payload={},
                               source_uri="https://sportsbook-nash.draftkings.com/test",
                               received_at=datetime(2026, 10, 25))
    result = probe(fetcher=naive, clock=lambda: NOW)
    assert all(result["sports"][sport]["status"] == "UNAVAILABLE"
               for sport in ("NFL", "CFB", "MLB"))

def test_nonmapping_payload_is_unavailable():
    def bad_payload(key):
        return SimpleNamespace(sport_key=key, raw=b"[]", payload=[],
                               source_uri="https://sportsbook-nash.draftkings.com/test", received_at=NOW)
    result = probe(fetcher=bad_payload, clock=lambda: NOW)
    assert all(result["sports"][sport]["status"] == "UNAVAILABLE"
               for sport in ("NFL", "CFB", "MLB"))

def test_missing_arrays_report_unknown_linkage_not_zero():
    def empty(key):
        return SimpleNamespace(sport_key=key, raw=b"{}", payload={},
                               source_uri="https://sportsbook-nash.draftkings.com/test", received_at=NOW)
    result = probe(fetcher=empty, clock=lambda: NOW)
    for sport in ("NFL", "CFB", "MLB"):
        row = result["sports"][sport]
        assert row["status"] == "FETCHED"
        for field in ("unlinked_selections", "linked_selections", "duplicate_market_ids",
                      "duplicate_event_ids", "markets_without_event"):
            assert field in row and row[field] is None

def test_raw_archive_preserves_exact_bytes(tmp_path):
    raw = b'{"events":[],"markets":[],"selections":[]}'
    def fetch(key):
        return SimpleNamespace(sport_key=key, raw=raw, payload={"events": [], "markets": [], "selections": []},
                               source_uri="https://sportsbook-nash.draftkings.com/test", received_at=NOW)
    report = probe(fetcher=fetch, clock=lambda: NOW, archive_dir=tmp_path)
    for sport in ("NFL", "CFB", "MLB"):
        row = report["sports"][sport]
        assert row["status"] == "FETCHED"
        assert (tmp_path / (sport.lower() + "-" + hashlib.sha256(raw).hexdigest() + ".json")).read_bytes() == raw

def test_archive_conflict_fails_closed(tmp_path):
    raw = b'{"events":[]}'
    destination = tmp_path / ("nfl-" + hashlib.sha256(raw).hexdigest() + ".json")
    destination.write_bytes(b"tampered")
    def fetch(key):
        return SimpleNamespace(sport_key=key, raw=raw, payload={"events": []},
                               source_uri="https://sportsbook-nash.draftkings.com/test", received_at=NOW)
    report = probe(fetcher=fetch, clock=lambda: NOW, archive_dir=tmp_path)
    assert report["sports"]["NFL"]["status"] == "UNAVAILABLE"
    assert destination.read_bytes() == b"tampered"

def test_source_url_rejects_prefix_spoof_and_credentials():
    for url in (
        "https://sportsbook-nash.draftkings.com.evil.invalid/board",
        "https://sportsbook-nash.draftkings.com@evil.invalid/board",
        "http://sportsbook-nash.draftkings.com/board",
        "https://user:secret@sportsbook-nash.draftkings.com/board",
    ):
        def fetch(key):
            return SimpleNamespace(sport_key=key, raw=b"{}", payload={},
                                   source_uri=url, received_at=NOW)
        report = probe(fetcher=fetch, clock=lambda: NOW)
        assert all(report["sports"][sport]["status"] == "UNAVAILABLE"
                   for sport in ("NFL", "CFB", "MLB"))
