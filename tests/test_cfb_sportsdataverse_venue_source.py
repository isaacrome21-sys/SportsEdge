from hashlib import sha256

import pytest

from sportsedge.sports.cfb.sportsdataverse_venue_source import (
    SDVVenueSourceError,
    apply_pinned_venue_supplements,
    git_blob_sha1,
    parse_pinned_venues,
)


HEADER="id,name,capacity,grass,city,state,zip,country_code,location.x,location.y,elevation,year_constructed,dome,timezone\n"


def _raw():
    return (
        HEADER
        + "1,Outdoor Stadium,50000,true,City,ST,00000,US,40.0,-88.0,200,2000,false,America/Chicago\n"
        + "2,Dome Stadium,60000,false,City,ST,00000,US,41.0,-89.0,200,2001,true,America/Chicago\n"
    ).encode("utf-8")


def test_pinned_venue_source_verifies_hash_blob_and_dome_coordinates():
    raw=_raw()
    venues=parse_pinned_venues(
        raw,
        expected_sha256=sha256(raw).hexdigest(),
        expected_git_blob_sha1=git_blob_sha1(raw),
        expected_row_count=2,
    )
    assert venues[1]["latitude"]==40.0
    assert venues[1]["game_indoor"] is False
    assert venues[2]["game_indoor"] is True


def test_pinned_venue_hash_mismatch_fails_closed():
    raw=_raw()
    with pytest.raises(SDVVenueSourceError,match="SHA256_MISMATCH"):
        parse_pinned_venues(
            raw,
            expected_sha256="0"*64,
            expected_git_blob_sha1=git_blob_sha1(raw),
            expected_row_count=2,
        )


def test_unreferenced_missing_coordinates_are_preserved_as_source_gap():
    raw=(
        HEADER
        + "1,Good,50000,true,City,ST,00000,US,40.0,-88.0,200,2000,false,America/Chicago\n"
        + "2,Missing,50000,true,City,ST,00000,US,,,,2000,false,America/Chicago\n"
    ).encode("utf-8")
    venues=parse_pinned_venues(
        raw,
        expected_sha256=sha256(raw).hexdigest(),
        expected_git_blob_sha1=git_blob_sha1(raw),
        expected_row_count=2,
    )
    assert set(venues)=={1}


def test_explicit_supplement_adds_missing_venue_without_override():
    base={1:{"venue_id":1,"name":"Pinned","latitude":40.0,"longitude":-88.0,"game_indoor":False}}
    merged=apply_pinned_venue_supplements(base,[{
        "venue_id":5960,
        "name":"Levi's Stadium",
        "latitude":37.4033889,
        "longitude":-121.97,
        "game_indoor":False,
        "source_identities":["WIKIDATA_Q7419343","LEVIS_STADIUM_OPEN_AIR"],
    }])
    assert merged[5960]["game_indoor"] is False
    assert merged[5960]["latitude"]==pytest.approx(37.4033889)
    assert merged[1]["name"]=="Pinned"


def test_explicit_supplement_cannot_override_pinned_venue():
    base={5960:{"venue_id":5960,"name":"Pinned","latitude":1.0,"longitude":2.0,"game_indoor":False}}
    with pytest.raises(SDVVenueSourceError,match="OVERRIDE_FORBIDDEN"):
        apply_pinned_venue_supplements(base,[{
            "venue_id":5960,"name":"Override","latitude":37.4,"longitude":-121.97,
            "game_indoor":False,"source_identities":["TEST"],
        }])
