#!/usr/bin/env python3
"""
MLB_GAME_STATE_V1 screen - STEP B: first-pitch weather pin record.

Design section 3 input 4 + section 6 step B: weather enters the screen
ONLY as lead-time-labelled past forecasts from the Open-Meteo Previous
Runs API (`previous_day1`: the value forecast one day ahead, available no
later than valid_time - 24h; availability = LEAD_TIME_BOUND, never an
exact issue time). Observed actuals are barred as a leak and are never
pulled here.

Method: one Previous Runs pull per (venue, season) over the season span,
hourly, variables temperature_2m / wind_speed_10m / wind_direction_10m /
precipitation, each as its `_previous_day1` series, timezone UTC, units
mph / degF / inch (the in-tree module sportsedge/open_meteo_previous_runs.py
establishes the access pattern and the availability language; wind
direction comes from the same endpoint). Each pull response is stored
verbatim and hash-pinned in the manifest this script writes: the pin
record for the screen's weather input. Per-game extraction (first-pitch
hour = the game's StatsAPI UTC start floored to the hour) happens in the
screen, from these pinned bytes.

Declared treatments:
  * Retractable-roof parks (Chase, Minute Maid, loanDepot, American
    Family, T-Mobile, Globe Life, Rogers Centre) and the fixed-roof
    Tropicana Field: per-game roof state is not in any admitted source,
    so the weather term is NEUTRAL (features absent) for those games -
    declared here, counted in the screen report.
  * A venue missing from the table below, or an hour missing from the
    pinned series: weather = NO_DATA for that game (term neutral),
    counted. Never substituted with observed weather.
  * Park coordinates and center-field bearings are compiled constants
    from published park references, listed in the pin record.
"""
import argparse
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

ROOT = "https://previous-runs-api.open-meteo.com/v1/forecast"
VARIABLES = ("temperature_2m", "wind_speed_10m", "wind_direction_10m", "precipitation")
LEAD_DAYS = 1

# venue_id (StatsAPI) -> (lat, lon, cf_bearing_deg, roof)
# roof: None = open air; "retractable"/"fixed" = weather term neutral.
VENUES = {
    1: (33.8003, -117.8827, 15, None),        # Angel Stadium
    2: (39.2839, -76.6217, 35, None),         # Oriole Park at Camden Yards
    3: (42.3467, -71.0972, 60, None),         # Fenway Park
    4: (41.8299, -87.6338, 15, None),         # Guaranteed Rate Field
    5: (41.4952, -81.6852, 5, None),          # Progressive Field
    7: (39.0517, -94.4803, 10, None),         # Kauffman Stadium
    10: (37.7516, -122.2005, 55, None),       # Oakland Coliseum
    12: (27.7683, -82.6534, 90, "fixed"),     # Tropicana Field
    14: (43.6414, -79.3894, 5, "retractable"),  # Rogers Centre
    15: (33.4455, -112.0667, 0, "retractable"),  # Chase Field
    17: (41.9484, -87.6553, 30, None),        # Wrigley Field
    19: (39.7560, -105.0340, 5, None),        # Coors Field
    22: (34.0739, -118.2400, 25, None),       # Dodger Stadium
    31: (40.4469, -80.0058, 120, None),       # PNC Park
    32: (43.0280, -87.9710, 30, "retractable"),  # American Family Field
    680: (47.5914, -122.3325, 5, "retractable"),  # T-Mobile Park
    2392: (29.7573, -95.3555, 15, "retractable"),  # Minute Maid Park
    2394: (42.3390, -83.0485, 35, None),      # Comerica Park
    2395: (37.7786, -122.3893, 95, None),     # Oracle Park
    2536: (28.0030, -82.7530, 30, None),      # TD Ballpark (Dunedin)
    2602: (39.0975, -84.5069, 115, None),     # Great American Ball Park
    2680: (32.7073, -117.1566, 5, None),      # Petco Park
    2681: (39.9061, -75.1665, 10, None),      # Citizens Bank Park
    2735: (41.2403, -77.0466, 40, None),      # Bowman Field (Williamsport)
    2756: (42.8803, -78.8747, 55, None),      # Sahlen Field (Buffalo)
    2889: (38.6226, -90.1939, 30, None),      # Busch Stadium
    3289: (40.7571, -73.8458, 25, None),      # Citi Field
    3309: (38.8730, -77.0075, 30, None),      # Nationals Park
    3312: (44.9817, -93.2783, 80, None),      # Target Field
    3313: (40.8296, -73.9262, 70, None),      # Yankee Stadium
    4169: (25.7781, -80.2197, 35, "retractable"),  # loanDepot park
    4705: (33.8908, -84.4678, 55, None),      # Truist Park
    5325: (32.7473, -97.0845, 20, "retractable"),  # Globe Life Field
    5445: (42.4978, -91.0556, 30, None),      # Field of Dreams
}

# Name-keyed fallbacks for one-off venues whose StatsAPI ids vary by pull.
VENUE_NAMES = {
    "London Stadium": (51.5387, -0.0166, 40, None),
    "Estadio Alfredo Harp Helu": (19.4260, -99.0858, 30, None),
    "Estadio Alfredo Harp Helú": (19.4260, -99.0858, 30, None),
    "Rickwood Field": (33.5024, -86.8557, 90, None),
    "Sutter Health Park": (38.5805, -121.5132, 30, None),
    "George M. Steinbrenner Field": (27.9803, -82.5033, 30, None),
    "Bristol Motor Speedway": (36.5160, -82.2570, 30, None),
}


def season_url(lat, lon, season):
    hourly = ",".join(f"{v}_previous_day{LEAD_DAYS}" for v in VARIABLES)
    return ROOT + "?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "hourly": hourly,
        "start_date": f"{season}-03-01", "end_date": f"{season}-11-15",
        "timezone": "UTC", "wind_speed_unit": "mph",
        "temperature_unit": "fahrenheit", "precipitation_unit": "inch"})


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "sportsedge-research/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2.0 * (i + 1))
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--statsapi", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    games = json.load(open(args.statsapi))
    needed = {}
    unmapped = {}
    for g in games:
        if g["season"] < 2022:
            continue
        vid, vname = g["venue_id"], g["venue_name"]
        key = VENUES.get(vid) or VENUE_NAMES.get(vname)
        if key is None:
            unmapped[(vid, vname)] = unmapped.get((vid, vname), 0) + 1
            continue
        needed.setdefault((vid, vname, key), set()).add(g["season"])
    manifest = dict(
        source="Open-Meteo Previous Runs API (free, CC BY 4.0)",
        availability="LEAD_TIME_BOUND", historical_pit=False,
        lead_days=LEAD_DAYS, variables=list(VARIABLES),
        note=("previous_day1 values were available no later than "
              "valid_time - 24h; lead-time label, not an exact issue time. "
              "Observed actuals were never pulled."),
        pulled_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        pulls=[], unmapped_venues={f"{k[0]}|{k[1]}": v for k, v in unmapped.items()})
    for (vid, vname, (lat, lon, bearing, roof)), seasons in sorted(needed.items(), key=lambda x: str(x[0][1])):
        for season in sorted(seasons):
            fname = f"weather_v{vid}_{season}.json"
            fpath = os.path.join(args.out_dir, fname)
            if not os.path.exists(fpath):
                raw = get(season_url(lat, lon, season))
                with open(fpath, "wb") as fh:
                    fh.write(raw)
            else:
                raw = open(fpath, "rb").read()
            payload = json.loads(raw)
            hours = len((payload.get("hourly") or {}).get("time") or [])
            manifest["pulls"].append(dict(
                file=fname, venue_id=vid, venue_name=vname, season=season,
                lat=lat, lon=lon, cf_bearing_deg=bearing, roof=roof,
                bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                hourly_rows=hours))
            print(vname, season, hours, "hours", flush=True)
    with open(os.path.join(args.out_dir, "weather_pin_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    print("unmapped:", manifest["unmapped_venues"])
    print("pulls:", len(manifest["pulls"]))


if __name__ == "__main__":
    main()
