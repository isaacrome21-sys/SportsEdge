"""Direct DraftKings failover must never invent odds or quote timestamps."""
import importlib.util,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("direct_fallback",ROOT/"scripts"/"fallback_nfl_direct_dk.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
NOW=datetime(2026,10,11,15,0,tzinfo=timezone.utc)


def transport(observed=None):
    return {"source_class":m.SOURCE_CLASS,"observed_at_utc":(observed or NOW).isoformat(),
            "raw_sha256":"f"*64,"source_uri":"https://sportsbook-nash.draftkings.com/example"}


def rows():
    return [{"event_id":"direct-123","book":"draftkings",
         "away_team":"Cincinnati Bengals","home_team":"Miami Dolphins",
         "commence_time":"2026-10-11T17:00:00Z",
         "spread":{"status":"OK","away_point":3.5,"home_point":-3.5,
                   "away_price":-110,"home_price":-110},
         "total":{"status":"OK","point":43.5,
                  "over_price":-108,"under_price":-112}}]


def test_convert_only_paired_source_with_intake_stamped_receipt():
    result=m.convert(transport(),rows(),NOW)
    assert len(result)==1
    row=result[0]
    assert row["markets"]["spreads"]["line"]==3.5
    assert row["markets"]["totals"]["under"]==-112
    assert row["markets"]["totals"]["timestamp_source"]=="INTAKE_STAMPED"
    assert row["markets"]["totals"]["book_last_update"] is None
    assert row["reference"]=={}
    assert row["estimate_p"] is None


def test_missing_side_mismatch_started_stale_and_duplicate_fail_closed():
    r=rows()
    r[0]["spread"]["home_point"]=-2.5
    assert m.convert(transport(),r,NOW)==[]
    r=rows()
    r[0]["total"]["status"]="ONE_SIDED"
    assert m.convert(transport(),r,NOW)==[]
    r=rows()
    r[0]["commence_time"]=(NOW-timedelta(minutes=1)).isoformat()
    assert m.convert(transport(),r,NOW)==[]
    with pytest.raises(ValueError,match="STALE"):
        m.convert(transport(NOW-timedelta(minutes=11)),rows(),NOW)
    with pytest.raises(ValueError,match="DUPLICATE"):
        m.convert(transport(),rows()*2,NOW)


def test_api_ready_never_calls_direct_endpoint():
    with TemporaryDirectory() as temp:
        target=Path(temp)/"nfl_odds.json"
        previous={"sport":"NFL","status":"READY","games":[{"event":"good"}]}
        target.write_text(json.dumps(previous))
        def forbidden():
            raise AssertionError("direct lookup used despite available API")
        status=m.fallback(target,NOW,capture=forbidden)
        assert status["status"]=="ODDS_API_ALREADY_READY"
        assert json.loads(target.read_text())==previous


def test_provider_exhaustion_promotes_real_direct_quote_without_model_probabilities():
    with TemporaryDirectory() as temp:
        target=Path(temp)/"nfl_odds.json"
        target.write_text(json.dumps({"sport":"NFL","status":"UNAVAILABLE","reason":"QUOTA","games":[]}))
        outcome=m.fallback(target,NOW,capture=transport,
                           rows_from=lambda t,week_of:rows())
        assert outcome["status"]=="DIRECT_DK_INTAKE_STAMPED"
        item=json.loads(target.read_text())
        assert item["status"]=="READY" and item["source"]==m.SOURCE_CLASS
        assert item["book_quote_timestamp_source"]=="INTAKE_STAMPED"
        assert item["estimate_p"] is None
        assert len(item["games"])==1


def test_ticket_and_phone_metadata_keep_direct_intake_status():
    from scripts.collect_auto_dk_four_sports import nfl_tickets
    from scripts.render_auto_dk_phone_summary import candidates,row_text
    direct=m.convert(transport(),rows(),NOW)
    t=nfl_tickets(direct,NOW,source="DRAFTKINGS_DIRECT_WEB_V1")
    one=t["2026-10-11"]["games"][0]
    assert one["away"]=="CIN" and one["home"]=="MIA"
    assert t["2026-10-11"]["source"]=="DRAFTKINGS_DIRECT_WEB_V1"
    assert all(x["quote_timestamp_source"]=="INTAKE_STAMPED" for x in one["markets"])
    card={"games":[{"away":"CIN","home":"MIA","commence_time":"2026-10-11T17:00:00Z",
          "markets":[{"market":"total",
             "quote_timestamp_source":one["markets"][-1]["quote_timestamp_source"],
             "quote_retrieved_at":one["markets"][-1]["quote_retrieved_at"],
             "lean":{"selection":"Under","line":43.5,"price_american":-112,
                 "estimate_p":.53,"edge_probability_points":.04,
                 "ev_per_dollar":.03}}]}]}
    x=candidates("NFL",card)
    assert len(x)==1
    display=row_text(x[0])
    assert "DK intake stamp" in display
    assert "DK quote" not in display
