"""Public Open-Meteo venue-city geocoding: exact identity, safe tie-breaking and fallback."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from urllib.parse import urlparse, parse_qs

MOD=Path(__file__).resolve().parents[1] / "artifacts" / "free_models.py"
spec=importlib.util.spec_from_file_location("free_weather_geocode_branch", MOD)
model=importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
NOW=datetime(2026, 10, 11, 18, 0, tzinfo=timezone.utc)
KICKOFF=model.dt("2026-10-11T20:25:00Z")


def venue(city="Phoenix", state="Arizona", full="Example Stadium"):
    return {"venue":{"indoor":False,"fullName":full,
                      "address":{"city":city,"state":state}}}


def run_with(geocodes, *, city="Phoenix", state="Arizona", full="Example Stadium"):
    calls=[]
    def getter(url):
        calls.append(url)
        if "geocoding-api.open-meteo.com" in url:
            name=parse_qs(urlparse(url).query)["name"][0]
            return {"results":geocodes.get(name, [])}
        if urlparse(u).hostname == "api.open-meteo.com"rl:
            return {"hourly":{"time":["2026-10-11T20:00"],
                              "wind_speed_10m":[19],
                              "precipitation_probability":[10]}}
        raise AssertionError("Unexpected URL: " + url)
    provider=model.PublicContext(NOW,getter=getter)
    value,status=provider.weather("NFL",venue(city,state,full),KICKOFF)
    return value,status,calls


def result(name, state, population, latitude, longitude=-112.07, country="US"):
    return {"name":name,"admin1":state,"country_code":country,
            "population":population,"latitude":latitude,"longitude":longitude}


def test_exact_city_state_prefers_unique_largest_population():
    a=result("Phoenix","Arizona",1000,33.4)
    b=result("Phoenix","Arizona",2000000,33.5)
    c=result("Phoenix","New York",999999999,40.0)
    value,status,calls=run_with({"Phoenix, Arizona":[a,b,c]})
    assert value==-0.8 and status=="HEURISTIC_FORECAST_NOT_CALIBRATED"
    forecasts=[u for u in calls if urlparse(u).hostname == "api.open-meteo.com"]
    assert len(forecasts)==1
    assert parse_qs(urlparse(forecasts[0]).query)["latitude"]==["33.5"]


def test_espn_two_letter_state_resolves_geocoder_full_name():
    value,status,calls=run_with({"Phoenix, Arizona":[result("Phoenix","Arizona",1400000,33.6)]}, state="AZ")
    assert value==-0.8
    assert status.startswith("HEURISTIC_FORECAST")
    assert "Phoenix%2C+Arizona" in calls[0]


def test_wrong_state_higher_population_never_overrides_verified_state():
    value,status,calls=run_with({"Phoenix, Arizona":[
        result("Phoenix","Texas",999999999,29.0),result("Phoenix","Arizona",5000,33.3)]})
    assert value==-0.8
    forecasts=[u for u in calls if urlparse(u).hostname == "api.open-meteo.com"]
    assert parse_qs(urlparse(forecasts[0]).query)["latitude"]==["33.3"]


def test_missing_initial_result_uses_city_only_but_checks_state():
    value,status,calls=run_with({
        "Phoenix, Arizona":[],
        "Phoenix":[result("Phoenix","Ohio",99999999,40.0),
                   result("Phoenix","Arizona",1000,33.7)]})
    assert value==-0.8
    assert status.startswith("HEURISTIC")
    assert any("name=Phoenix&" in u for u in calls)


def test_population_tie_retries_exact_stadium_name_with_valid_state():
    a=result("Phoenix","Arizona",1000,33.1)
    b=result("Phoenix","Arizona",1000,33.2)
    stadium=result("Example Stadium","Arizona",None,33.8)
    value,status,calls=run_with({
        "Phoenix, Arizona":[a,b],"Phoenix":[a,b],"Example Stadium":[stadium]})
    assert value==-0.8
    assert status.startswith("HEURISTIC")
    forecasts=[u for u in calls if urlparse(u).hostname == "api.open-meteo.com"]
    assert parse_qs(urlparse(forecasts[0]).query)["latitude"]==["33.8"]


def test_stadium_name_fallback_never_matches_unrelated_city_or_state():
    a=result("Phoenix","Arizona",1000,33.1)
    b=result("Phoenix","Arizona",1000,33.2)
    value,status,calls=run_with({
        "Phoenix, Arizona":[a,b],"Phoenix":[a,b],
        "Example Stadium":[result("Example Stadium","Texas",1000000,30.0),
                           result("Elsewhere","Arizona",2000000,33.9)]})
    assert value==0.0
    assert status=="VENUE_GEOCODE_AMBIGUOUS"
    assert not any(urlparse(u).hostname == "api.open-meteo.com" for u in calls)


def test_unknown_population_leaves_multiple_exact_places_ambiguous():
    a=result("Phoenix","Arizona",None,33.1)
    b=result("Phoenix","Arizona",5000,33.2)
    value,status,calls=run_with({
        "Phoenix, Arizona":[a,b],"Phoenix":[a,b],"Example Stadium":[]})
    assert value==0.0 and status=="VENUE_GEOCODE_AMBIGUOUS"
    assert not any(urlparse(u).hostname == "api.open-meteo.com" for u in calls)


def test_indoor_and_unsafe_roof_status_never_geocode_or_apply_wind():
    provider=model.PublicContext(NOW, getter=lambda _: (_ for _ in ()).throw(AssertionError("Network called")))
    assert provider.weather("NFL",{"venue":{"indoor":True}},KICKOFF)==(0.0,"INDOOR_VERIFIED")
    assert provider.weather("NFL",{"venue":{"indoor":None}},KICKOFF)==(0.0,"ROOF_STATUS_UNVERIFIED")


def test_forecast_missing_keeps_explicit_weather_failure():
    def getter(url):
        if "geocoding-api" in url:
            return {"results":[result("Phoenix","Arizona",500000,33.4)]}
        return {"hourly":{"time":[]}}
    provider=model.PublicContext(NOW,getter=getter)
    assert provider.weather("NFL",venue(),KICKOFF)==(0.0,"FORECAST_UNAVAILABLE")


def test_unknown_espn_state_never_chooses_highest_population_in_another_state():
    value,status,calls=run_with({"Phoenix":[
        result("Phoenix","Arizona",3000000,33.4),
        result("Phoenix","Oregon",5000000,42.0)]},state=None,full="")
    assert value==0.0 and status=="VENUE_GEOCODE_AMBIGUOUS"
    assert not any(urlparse(u).hostname == "api.open-meteo.com" for u in calls)
