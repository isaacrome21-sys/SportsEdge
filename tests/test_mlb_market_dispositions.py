import json
from sportsedge.mlb_market_dispositions import canonical_mlb_markets, market_dispositions

def test_catalog_has_exactly_38_unique_markets():
    markets=canonical_mlb_markets()
    assert len(markets)==38
    assert len(set(markets))==38

def test_every_market_gets_explicit_disposition():
    rows=[{"market":"MONEYLINE","scored_status":"ACTIONABLE","confidence_score":77}]
    out=market_dispositions(rows)
    assert len(out)==38
    assert {x["market"] for x in out}==set(canonical_mlb_markets())
    ml=next(x for x in out if x["market"]=="MONEYLINE")
    assert ml["status"]=="ACTIONABLE" and ml["best_confidence_score"]==77
    nrfi=next(x for x in out if x["market"]=="NRFI")
    assert nrfi["status"]=="NO_MODEL" and nrfi["reason"]=="MARKET_NOT_SURFACED"
