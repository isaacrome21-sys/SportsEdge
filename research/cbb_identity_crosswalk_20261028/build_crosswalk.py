#!/usr/bin/env python3
"""Build the CBB team identity crosswalk (CBB_TEAM_IDENTITY_CROSSWALK_V1).

Purpose: close the identity-crosswalk gate named OPEN in the CBR mirror
successor manifest (PR #2871) and required by section 5 of the
CBB_TORVIK_EFFICIENCY_V1 / CBB team-totals designs before either
DESIGN_PASS construction (PRs #2891 / #2892) can be considered for a
freeze. This is an IDENTITY artifact: it admits no new source, edits no
criterion or design text, and confers no validation, clock or play
credit. It proves that the same team is the same team across the four
already-admitted / already-used representations:

  * Torvik  - the admitted live route (PR #2841): the 2026-10-28
              morning-pull vintage of 2027_team_results.csv (365 teams)
              is the canonical SPINE; archive-route team names from the
              PR #2832 pinned commit are mapped as a second surface set.
  * CBR     - the pinned mirror bytes (PR #2871 successor manifest);
              each school's slug is read from the row's own
              /cbb/schools/<slug>/ URL (source-native identity).
  * hoopR   - the pinned schedule CSVs (PR #2867 successor manifest);
              rows carry ESPN team ids natively (home_id / away_id).
  * ESPN    - a build-time reference pull of the public ESPN site API
              (teams list + four event summaries), hash-pinned in the
              artifact. NOT an admission: the pull is used only to bind
              ESPN team ids and event team names into the crosswalk.
              ESPN event ids are the same id space hoopR carries.

Canonical id: the CBR school slug where the school appears in the
pinned CBR bytes (continuity with the screens' audited name-join, whose
canonical keys are CBR slugs); otherwise a minted slug from the Torvik
spine name by the documented rule in mint_slug(). Canonical entries not
in the 365-team spine are historical-only (schools present in the
2015-2023 sources but not in the 2026-27 Torvik universe).

Matching discipline (no exceptions): exact matches and table-driven
overrides ONLY. No fuzzy matching, no string-similarity scoring, no
transformation rules at resolve time. Resolution order:
  1. OVERRIDE            - the published table (PR #2871's 41 entries
                           verbatim + named CROSSWALK_EXTENSION entries)
  2. CBR_URL_NATIVE      - CBR Team/TeamFull surfaces: the slug in the
                           row's own school URL
  3. CBR_SURFACE         - surface exactly equals a harvested CBR Team
                           or TeamFull surface (harvest verified
                           unambiguous: every such surface binds exactly
                           one slug in the pinned bytes)
  4. TORVIK_SPINE_NAME   - surface exactly equals a Torvik spine name
  5. ID binding          - ESPN/hoopR team ids, bound only where every
                           co-occurring location surface resolves to
                           one canonical id (conflicts are published,
                           never silently bound)
Anything unresolved is published in the artifact's UNRESOLVED lists
with occurrence counts. Non-D1 opponents dominate those lists by
design: the crosswalk is a Division I identity artifact.

Illinois: canonical entries whose ESPN id is in the downstream capture
denylist (sportsedge/cbb_capture_scope.py
_ILLINOIS_ESPN_MBB_2027_DENYLIST, 13 ids) are flagged
capture_excluded_illinois. Identity is not capture: flagged teams stay
in the crosswalk; the exclusion applies downstream, unchanged.

Pin discipline: every input byte stream is verified against its pin
before use (manifest sha256 for CBR / hoopR / Torvik morning vintage;
the pinned git commit + recorded sha256 for Torvik archive files;
recorded sha256 for the ESPN reference pulls). Any drift is a refusal
(exit 2), never silent acceptance.

Stdlib only. Exit codes: 0 built, 2 an input pin refused,
3 an internal consistency gate failed (see CROSSWALK_RECORD.md).
"""

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

PACKET = Path(__file__).resolve().parent
REPO_ROOT = PACKET.parents[1]
CBR_MANIFEST_PATH = (REPO_ROOT / "research" /
                     "cbb_cbr_schedule_mirror_successor_20261028" /
                     "successor_manifest.json")
HOOPR_MANIFEST_PATH = (REPO_ROOT / "research" /
                       "cbb_hoopr_mbb_schedule_successor_20261028" /
                       "successor_manifest.json")
TORVIK_PINNED_COMMIT = "46d1036443ca452fdd1c6cf25cf5dff50de68337"
TORVIK_ARCHIVE_URL = ("https://raw.githubusercontent.com/andreweatherman/"
                      "toRvik-data/" + TORVIK_PINNED_COMMIT +
                      "/ratings/archive/by_date/ratings_archive_{date}.csv")
# The 27 Torvik archive dates the PR #2871 proof itself used (early /
# mid probes, championships, the 2020 late probe substitute).
TORVIK_ARCHIVE_DATES = [
    "20141115", "20150115", "20150406", "20151114", "20160115",
    "20160404", "20161112", "20170115", "20170403", "20171111",
    "20180114", "20180402", "20181110", "20190113", "20190408",
    "20191109", "20200112", "20200308", "20201128", "20210117",
    "20210405", "20211113", "20220116", "20220404", "20221112",
    "20230115", "20230403",
]
# logs1520.csv is admitted for the 2014-15 -> 2017-18 seasons ONLY
# (PR #2871 successor manifest); harvest is restricted to that scope.
LOGS1520_ADMITTED_SEASONS = {"2014-2015", "2015-2016", "2016-2017",
                             "2017-2018"}
PER_SEASON_FILES = ["logs19.csv", "logs20.csv", "logs21.csv",
                    "logs22.csv", "logs23.csv"]
ESPN_EVENT_FILES = {  # event id -> fixture role in the proof section
    "401522202": "CHAMPIONSHIP_2023",
    "401408636": "CHAMPIONSHIP_2022",
    "400788981": "CHAMPIONSHIP_2015",
    "401920982": "FORWARD_ROME_GAME_2026-11-01",
}
CHAMPIONSHIP_DATES = {  # CBR local date -> (slug, slug), from PR #2871
    "2015-04-06": ("duke", "wisconsin"),
    "2022-04-04": ("kansas", "north-carolina"),
    "2023-04-03": ("connecticut", "san-diego-state"),
}
# Downstream capture denylist (sportsedge/cbb_capture_scope.py),
# reconciled there against the NCAA 2026-27 D1 Illinois directory.
ILLINOIS_ESPN_DENYLIST = frozenset({
    "71", "77", "79", "82", "305", "356", "2130", "2197", "2287",
    "2350", "2459", "2565", "2710",
})

# ---------------------------------------------------------------------
# The override table. Layer 1: PR #2871's NORMALIZATION_OVERRIDES,
# verbatim (41 entries). The verifier and the tests pin these pairs:
# an edit here that changes or drops one is a named, reviewed act,
# never a silent divergence.
OVERRIDES_2871 = {
    "Albany": "albany-ny",
    "American University": "american",
    "BYU": "brigham-young",
    "Central Connecticut": "central-connecticut-state",
    "Cleveland St.": "cleveland-state",
    "Detroit": "detroit-mercy",
    "ETSU": "east-tennessee-state",
    "Fort Wayne": "ipfw",
    "Fort Wayne Mastodons": "ipfw",
    "LIU": "long-island-university",
    "LIU-Brooklyn": "long-island-university",
    "LIU-Brooklyn Blackbirds": "long-island-university",
    "LSU": "louisiana-state",
    "Nebraska Omaha": "nebraska-omaha",
    "Ole Miss": "mississippi",
    "Oregon St.": "oregon-state",
    "Penn": "pennsylvania",
    "Pitt": "pittsburgh",
    "Saint Mary's": "saint-marys-ca",
    "San Diego St.": "san-diego-state",
    "SIU-Edwardsville": "southern-illinois-edwardsville",
    "SMU": "southern-methodist",
    "Southern Miss": "southern-mississippi",
    "St. Joseph's": "saint-josephs",
    "St. Peter's": "saint-peters",
    "Texas St.": "texas-state",
    "UAlbany": "albany-ny",
    "UConn": "connecticut",
    "UIC": "illinois-chicago",
    "UMass": "massachusetts",
    "UMass-Lowell": "massachusetts-lowell",
    "UMBC": "maryland-baltimore-county",
    "UMKC": "missouri-kansas-city",
    "UNC": "north-carolina",
    "UNLV": "nevada-las-vegas",
    "USC": "southern-california",
    "USC Upstate": "south-carolina-upstate",
    "UCSB": "california-santa-barbara",
    "UT-Martin": "tennessee-martin",
    "VCU": "virginia-commonwealth",
    "Youngstown St.": "youngstown-state",
}

# Layer 2: CROSSWALK_EXTENSION entries, added by this build. Each entry
# is (canonical slug, justification). "ST_CLASS" entries name the CBR
# Team surface the Torvik abbreviation abbreviates; the builder asserts
# that surface harvests to the same slug before accepting the entry.
ST_CLASS = {
    # Torvik spine surfaces, "X St." abbreviated forms.
    "Alabama St.": ("alabama-state", "Alabama State"),
    "Alcorn St.": ("alcorn-state", "Alcorn State"),
    "Appalachian St.": ("appalachian-state", "Appalachian State"),
    "Arizona St.": ("arizona-state", "Arizona State"),
    "Arkansas St.": ("arkansas-state", "Arkansas State"),
    "Ball St.": ("ball-state", "Ball State"),
    "Boise St.": ("boise-state", "Boise State"),
    "Cal St. Bakersfield": ("cal-state-bakersfield", "Cal State Bakersfield"),
    "Cal St. Fullerton": ("cal-state-fullerton", "Cal State Fullerton"),
    "Cal St. Northridge": ("cal-state-northridge", "Cal State Northridge"),
    "Colorado St.": ("colorado-state", "Colorado State"),
    "Coppin St.": ("coppin-state", "Coppin State"),
    "Delaware St.": ("delaware-state", "Delaware State"),
    "East Tennessee St.": ("east-tennessee-state", "East Tennessee State"),
    "Florida St.": ("florida-state", "Florida State"),
    "Fresno St.": ("fresno-state", "Fresno State"),
    "Georgia St.": ("georgia-state", "Georgia State"),
    "Idaho St.": ("idaho-state", "Idaho State"),
    "Illinois St.": ("illinois-state", "Illinois State"),
    "Indiana St.": ("indiana-state", "Indiana State"),
    "Iowa St.": ("iowa-state", "Iowa State"),
    "Jackson St.": ("jackson-state", "Jackson State"),
    "Jacksonville St.": ("jacksonville-state", "Jacksonville State"),
    "Kansas St.": ("kansas-state", "Kansas State"),
    "Kennesaw St.": ("kennesaw-state", "Kennesaw State"),
    "Kent St.": ("kent-state", "Kent State"),
    "Long Beach St.": ("long-beach-state", "Long Beach State"),
    "McNeese St.": ("mcneese-state", "McNeese State"),
    "Michigan St.": ("michigan-state", "Michigan State"),
    "Mississippi St.": ("mississippi-state", "Mississippi State"),
    "Mississippi Valley St.": ("mississippi-valley-state", "Mississippi Valley State"),
    "Missouri St.": ("missouri-state", "Missouri State"),
    "Montana St.": ("montana-state", "Montana State"),
    "Morehead St.": ("morehead-state", "Morehead State"),
    "Morgan St.": ("morgan-state", "Morgan State"),
    "Murray St.": ("murray-state", "Murray State"),
    "New Mexico St.": ("new-mexico-state", "New Mexico State"),
    "Nicholls St.": ("nicholls-state", "Nicholls State"),
    "Norfolk St.": ("norfolk-state", "Norfolk State"),
    "North Dakota St.": ("north-dakota-state", "North Dakota State"),
    "Northwestern St.": ("northwestern-state", "Northwestern State"),
    "Ohio St.": ("ohio-state", "Ohio State"),
    "Oklahoma St.": ("oklahoma-state", "Oklahoma State"),
    "Penn St.": ("penn-state", "Penn State"),
    "Portland St.": ("portland-state", "Portland State"),
    "Sacramento St.": ("sacramento-state", "Sacramento State"),
    "Sam Houston St.": ("sam-houston-state", "Sam Houston State"),
    "San Jose St.": ("san-jose-state", "San Jose State"),
    "South Carolina St.": ("south-carolina-state", "South Carolina State"),
    "South Dakota St.": ("south-dakota-state", "South Dakota State"),
    "Southeast Missouri St.": ("southeast-missouri-state", "Southeast Missouri State"),
    "Tarleton St.": ("tarleton-state", "Tarleton State"),
    "Tennessee St.": ("tennessee-state", "Tennessee State"),
    "Utah St.": ("utah-state", "Utah State"),
    "Washington St.": ("washington-state", "Washington State"),
    "Weber St.": ("weber-state", "Weber State"),
    "Wichita St.": ("wichita-state", "Wichita State"),
    "Wright St.": ("wright-state", "Wright State"),
    "Grambling St.": ("grambling", "Grambling"),
    "Chicago St.": ("chicago-state", "Chicago State"),
}
EXTENSION_OVERRIDES = {
    # Renamed schools (identity continuous; CBR slug is the legacy one).
    "IU Indy": ("iupui", "School renamed IUPUI -> IU Indianapolis (2024); CBR slug iupui from the pinned bytes."),
    "East Texas A&M": ("texas-am-commerce", "School renamed Texas A&M-Commerce -> East Texas A&M (2024); CBR slug texas-am-commerce."),
    "UT Rio Grande Valley": ("texas-pan-american", "CBR carries UTRGV under the legacy slug texas-pan-american; its own surfaces there are 'Texas-Rio Grande Valley'."),
    "Houston Christian": ("houston-baptist", "Renamed Houston Baptist -> Houston Christian (2022); also a harvested CBR surface under slug houston-baptist in logs23."),
    # Torvik / hoopR / ESPN school-name forms with no exact CBR surface.
    "Miami FL": ("miami-fl", "Torvik disambiguated form; CBR surface 'Miami (FL)'."),
    "Miami OH": ("miami-oh", "Torvik disambiguated form; CBR surface 'Miami (OH)'."),
    "St. John's": ("st-johns-ny", "Short form used by Torvik and hoopR; CBR surface 'St. John's (NY)'."),
    "N.C. State": ("north-carolina-state", "Torvik punctuated form; CBR surfaces 'NC State' / 'North Carolina State'."),
    "FIU": ("florida-international", "Torvik initialism; CBR surface 'Florida International'."),
    "Charleston": ("college-of-charleston", "Short form used by Torvik and hoopR for the College of Charleston (CBR surface 'College of Charleston'); not Charleston Southern (slug charleston-southern, surfaces distinct)."),
    "Bowling Green": ("bowling-green-state", "Short form used by Torvik and hoopR; CBR surface 'Bowling Green State'."),
    "Illinois Chicago": ("illinois-chicago", "Torvik expanded form of UIC (PR #2871 table carries 'UIC')."),
    "Loyola Chicago": ("loyola-il", "Form used by Torvik, hoopR and ESPN; CBR surface 'Loyola (IL)'."),
    "Loyola MD": ("loyola-md", "Torvik form; CBR surface 'Loyola (MD)'."),
    "Loyola Maryland": ("loyola-md", "hoopR location form; CBR surface 'Loyola (MD)'."),
    "Queens": ("queens-nc", "Torvik short form; CBR surface 'Queens (NC)'."),
    "Queens University": ("queens-nc", "hoopR location form; CBR surface 'Queens (NC)'."),
    "UMass Lowell": ("massachusetts-lowell", "Torvik space form; PR #2871 table carries the hyphen form 'UMass-Lowell'."),
    "Tennessee Martin": ("tennessee-martin", "Expanded form; PR #2871 table carries 'UT-Martin'."),
    "UT Martin": ("tennessee-martin", "hoopR location form of the same school."),
    "UL Monroe": ("louisiana-monroe", "hoopR location form; CBR surface 'Louisiana-Monroe'."),
    "Louisiana Monroe": ("louisiana-monroe", "Torvik expanded form; CBR surface 'Louisiana-Monroe'."),
    "Prairie View A&M": ("prairie-view", "Full form used by Torvik and hoopR; CBR Team surface is 'Prairie View'."),
    "Texas A&M Corpus Chris": ("texas-am-corpus-christi", "Torvik truncated form (sic); CBR surface 'Texas A&M-Corpus Christi'."),
    "Cal Baptist": ("california-baptist", "Torvik short form; CBR surface 'California Baptist'."),
    "Bethune Cookman": ("bethune-cookman", "Torvik unhyphenated form; CBR surface 'Bethune-Cookman'."),
    "Gardner Webb": ("gardner-webb", "Torvik unhyphenated form; CBR surface 'Gardner-Webb'."),
    "Arkansas Pine Bluff": ("arkansas-pine-bluff", "Torvik unhyphenated form; CBR surface 'Arkansas-Pine Bluff'."),
    "Maryland Eastern Shore": ("maryland-eastern-shore", "Torvik unhyphenated form; CBR surface 'Maryland-Eastern Shore'."),
    "San Diego": ("san-diego", "VERIFIED TRAP (PR #2891 attempt-3 record): on Torvik this is the University of San Diego (CBR surface 'San Diego', slug san-diego), NOT San Diego State (slug san-diego-state, Torvik surface 'San Diego St.', PR #2871 table) and NOT UC San Diego (slug california-san-diego, surface 'UC San Diego')."),
    "Hawai'i": ("hawaii", "hoopR location with okina; CBR surface 'Hawaii'."),
    "San José State": ("san-jose-state", "hoopR accented location form; CBR surface 'San Jose State'."),
    "Seattle U": ("seattle", "hoopR location form; CBR surface 'Seattle'."),
    "McNeese": ("mcneese-state", "hoopR short location; CBR surface 'McNeese State'."),
    "Nicholls": ("nicholls-state", "hoopR short location; CBR surface 'Nicholls State'."),
    "Tarleton": ("tarleton-state", "hoopR short location; CBR surface 'Tarleton State'."),
    "SE Louisiana": ("southeastern-louisiana", "hoopR location form; CBR surface 'Southeastern Louisiana'."),
    "St. Thomas - Minnesota": ("st-thomas-mn", "hoopR location form; CBR surface 'St. Thomas' under slug st-thomas-mn (the D1 St. Thomas in St. Paul)."),
    "St. Thomas-Minnesota": ("st-thomas-mn", "hoopR location variant of the same school."),
    "St. Francis Brooklyn": ("st-francis-ny", "hoopR location form; CBR surface 'St. Francis (NY)'. School dropped athletics after 2022-23 (historical-only)."),
    "St. Francis (PA)": ("saint-francis-pa", "hoopR location form; CBR surface 'Saint Francis (PA)'."),
    "Saint Francis (PA)": ("saint-francis-pa", "Spelled-out form; same school as the CBR Team surface of the same string under slug saint-francis-pa."),
    # Torvik archive-era name forms (pinned-commit archive files,
    # 2014-2023 vintages of the same route).
    "Arkansas Little Rock": ("arkansas-little-rock", "Torvik archive-era form; school rebranded Arkansas-Little Rock -> Little Rock; CBR slug arkansas-little-rock, surface 'Little Rock'."),
    "Dixie St.": ("dixie-state", "Torvik archive-era form; school renamed Dixie State -> Utah Tech (2022), CBR kept slug dixie-state."),
    "IPFW": ("ipfw", "Torvik archive-era initialism; CBR slug ipfw (PR #2871 table carries the 'Fort Wayne' forms)."),
    "LIU Brooklyn": ("long-island-university", "Torvik archive-era space form; PR #2871 table carries 'LIU-Brooklyn'."),
    "Louisiana Lafayette": ("louisiana-lafayette", "Torvik archive-era form; school rebranded Louisiana-Lafayette -> Louisiana; CBR slug louisiana-lafayette."),
    "North Carolina St.": ("north-carolina-state", "Torvik archive-era form of the same school as 'N.C. State'."),
    "Savannah St.": ("savannah-state", "Torvik archive-era form; Savannah State was D1 through 2018-19 (historical-only)."),
    "St. Francis NY": ("st-francis-ny", "Torvik archive-era form of St. Francis Brooklyn."),
    "St. Francis PA": ("saint-francis-pa", "Torvik archive-era form of St. Francis (PA)."),
    "Texas A&M Commerce": ("texas-am-commerce", "Torvik archive-era space form; CBR surface 'Texas A&M-Commerce'."),
    # ESPN teams-pull location forms.
    "App State": ("appalachian-state", "ESPN location short form (team id 2026); school is Appalachian State."),
    "IU Indianapolis": ("iupui", "ESPN full location form (team id 85) of the school Torvik calls 'IU Indy'."),
    "LSU New Orleans": ("new-orleans", "ESPN location (team id 2443, 'LSU New Orleans Privateers', abbr NOLA) is the University of New Orleans under its historical LSUNO name; CBR surface 'New Orleans'."),
}

# Display-name (school + mascot) forms used by hoopR and ESPN. Each was
# verified against the ESPN team-id co-occurrence in the pinned hoopR
# schedules (the surface's rows bind to exactly one canonical id) or,
# for the minted-canonical schools, against the ESPN teams pull itself.
# CBR TeamFull surfaces that already match exactly are NOT repeated
# here; they resolve by the CBR_SURFACE rule.
DISPLAY_NAME_OVERRIDES = {
    "Albany Great Danes": "albany-ny",
    "American University Eagles": "american",
    "App State Mountaineers": "appalachian-state",
    "Bowling Green Falcons": "bowling-green-state",
    "Charleston Cougars": "college-of-charleston",
    "Delaware Blue Hens": "delaware",
    "East Tennessee State Buccaneers": "east-tennessee-state",
    "East Texas A&M Lions": "texas-am-commerce",
    "Grand Canyon Lopes": "grand-canyon",
    "Hawai'i Rainbow Warriors": "hawaii",
    "IU Indianapolis Jaguars": "iupui",
    "LSU New Orleans Privateers": "new-orleans",
    "LSU Tigers": "louisiana-state",
    "Le Moyne Dolphins": "le-moyne",
    "Long Island University Sharks": "long-island-university",
    "Loyola Chicago Ramblers": "loyola-il",
    "Loyola Maryland Greyhounds": "loyola-md",
    "Maryland Eastern Shore Hawks": "maryland-eastern-shore",
    "Massachusetts Minutemen": "massachusetts",
    "McNeese Cowboys": "mcneese-state",
    "Mercyhurst Lakers": "mercyhurst",
    "Miami (OH) Redhawks": "miami-oh",
    "Miami Hurricanes": "miami-fl",
    "New Haven Chargers": "new-haven",
    "Nicholls Colonels": "nicholls-state",
    "North Carolina Tar Heels": "north-carolina",
    "Pennsylvania Quakers": "pennsylvania",
    "Pittsburgh Panthers": "pittsburgh",
    "Prairie View A&M Panthers": "prairie-view",
    "Queens University Royals": "queens-nc",
    "SE Louisiana Lions": "southeastern-louisiana",
    "SIU Edwardsville Cougars": "southern-illinois-edwardsville",
    "Saint Joseph's Hawks": "saint-josephs",
    "Saint Peter's Peacocks": "saint-peters",
    "San José State Spartans": "san-jose-state",
    "Seattle U Redhawks": "seattle",
    "South Carolina Upstate Spartans": "south-carolina-upstate",
    "St. Francis (PA) Red Flash": "saint-francis-pa",
    "St. Francis Brooklyn Terriers": "st-francis-ny",
    "St. John's Red Storm": "st-johns-ny",
    "St. Thomas - Minnesota Tommies": "st-thomas-mn",
    "St. Thomas-Minnesota Tommies": "st-thomas-mn",
    "Tarleton Texans": "tarleton-state",
    "UAlbany Great Danes": "albany-ny",
    "UC Davis Aggies": "california-davis",
    "UC Irvine Anteaters": "california-irvine",
    "UC Riverside Highlanders": "california-riverside",
    "UC San Diego Tritons": "california-san-diego",
    "UC Santa Barbara Gauchos": "california-santa-barbara",
    "UL Monroe Warhawks": "louisiana-monroe",
    "UMass Lowell River Hawks": "massachusetts-lowell",
    "UT Martin Skyhawks": "tennessee-martin",
    "UT Rio Grande Valley Vaqueros": "texas-pan-american",
    "West Florida Argonauts": "west-florida",
    "West Georgia Wolves": "west-georgia",
}
# Surfaces that must NEVER resolve by name alone (two D1 schools share
# the string). The crosswalk binds those schools by team id and by
# their disambiguated surfaces only; a name-only join on these strings
# is exactly the IDENTITY_UNVERIFIED failure the designs forbid.
AMBIGUOUS_SURFACES = {"Miami"}


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def refuse(label, detail):
    print(json.dumps({"refusal": label, "detail": detail}))
    sys.exit(2)


def load_pinned(path, expected_sha, label):
    if not path.exists():
        refuse("INPUT_MISSING", f"{label}: {path}")
    raw = path.read_bytes()
    if sha256(raw) != expected_sha:
        refuse("SOURCE_CHANGED_AFTER_SNAPSHOT",
               f"{label}: {path} sha256 {sha256(raw)} != pin {expected_sha}")
    return raw


def mint_slug(torvik_name):
    """Documented minting rule for spine teams with no CBR slug in the
    pinned scope: lowercase, spaces -> hyphens, drop characters outside
    [a-z0-9-], collapse repeated hyphens."""
    s = torvik_name.lower().replace(" ", "-")
    s = re.sub(r"[^a-z0-9-]", "", s)
    return re.sub(r"-+", "-", s).strip("-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cbr-dir", default=str(
        Path.home() / "workspace/cbb-cbr-successor-admission-20261028/pulls"))
    ap.add_argument("--hoopr-dir", default=str(
        Path.home() / "workspace/cbb-successor-admission-20261028/pulls"))
    ap.add_argument("--torvik-vintage", default=str(
        Path.home() / "workspace/sportsedge/lane_intakes/torvik_morning/2026-10-28.csv"))
    ap.add_argument("--pulls-dir", default=str(
        Path.home() / "workspace/cbb-crosswalk-20261028/pulls"))
    ap.add_argument("--out", default=str(PACKET / "crosswalk.json"))
    ap.add_argument("--worklist", action="store_true",
                    help="print unresolved D1-plausible surfaces and exit")
    args = ap.parse_args()
    cbr_dir, hoopr_dir = Path(args.cbr_dir), Path(args.hoopr_dir)
    pulls_dir = Path(args.pulls_dir)
    inputs = []

    # ---- CBR harvest (pins from the PR #2871 manifest) ----------------
    cbr_manifest = json.loads(CBR_MANIFEST_PATH.read_text(encoding="utf-8"))
    cbr_pins = {s["file_name"]: s["sha256"] for s in cbr_manifest["samples"]}
    team2slug, full2slug = {}, {}
    opponent_counts = Counter()
    cbr_rows_used = 0
    for name in PER_SEASON_FILES:
        raw = load_pinned(cbr_dir / name, cbr_pins[name], name)
        inputs.append({"source": "cbr", "file": name, "sha256": cbr_pins[name],
                       "bytes": len(raw), "pin_basis": "PR #2871 successor_manifest.json"})
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            url = next((v for v in row.values()
                        if isinstance(v, str) and "/cbb/schools/" in v), None)
            if url is None:
                refuse("CBR_ROW_WITHOUT_SCHOOL_URL", f"{name}: {row}")
            slug = url.split("/")[3]
            for table, key in ((team2slug, "Team"), (full2slug, "TeamFull")):
                prev = table.setdefault(row[key], slug)
                if prev != slug:
                    refuse("CBR_SURFACE_AMBIGUOUS",
                           f"{key} surface {row[key]!r} -> {prev} and {slug}")
            opponent_counts[row["Opponent"]] += 1
            cbr_rows_used += 1
    cbr_slugs = sorted(set(team2slug.values()) | set(full2slug.values()))
    surface2slug = dict(team2slug)
    surface2slug.update(full2slug)
    # logs1520.csv has a DIFFERENT schema (the PR #2871 proof harvests
    # around it the same way): no school URL, and its 'Team' column
    # carries the FULL name form. Its rows bind through the per-season
    # TeamFull harvest; a surface the harvest does not know is counted
    # and published, never guessed.
    full1520_2slug, logs1520_unbound = {}, Counter()
    raw = load_pinned(cbr_dir / "logs1520.csv", cbr_pins["logs1520.csv"],
                      "logs1520.csv")
    inputs.append({"source": "cbr", "file": "logs1520.csv",
                   "sha256": cbr_pins["logs1520.csv"], "bytes": len(raw),
                   "pin_basis": "PR #2871 successor_manifest.json (2014-15 -> 2017-18 scope only)"})
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        if row.get("season") not in LOGS1520_ADMITTED_SEASONS:
            continue
        slug = surface2slug.get(row["Team"])
        if slug is None and row["Team"] in OVERRIDES_2871:
            slug = OVERRIDES_2871[row["Team"]]
        if slug is None:
            logs1520_unbound[row["Team"]] += 1
            continue
        full1520_2slug[row["Team"]] = slug
        opponent_counts[row["Opponent"]] += 1
        cbr_rows_used += 1

    # ---- Overrides: validate every entry against the harvest ---------
    overrides = {}
    for surface, slug in OVERRIDES_2871.items():
        overrides[surface] = {"canonical": slug, "origin": "PR2871",
                              "justification": "PR #2871 NORMALIZATION_OVERRIDES, verbatim."}
    for surface, (slug, expanded) in ST_CLASS.items():
        if surface2slug.get(expanded) != slug:
            refuse("ST_CLASS_TARGET_MISMATCH",
                   f"{surface!r}: expanded surface {expanded!r} harvests to "
                   f"{surface2slug.get(expanded)}, not {slug}")
        overrides[surface] = {
            "canonical": slug, "origin": "CROSSWALK_EXTENSION",
            "justification": f"Torvik abbreviated form; CBR Team surface '{expanded}'."}
    deferred_targets = []
    for surface, (slug, why) in EXTENSION_OVERRIDES.items():
        if slug not in cbr_slugs:
            deferred_targets.append((surface, slug))
        overrides[surface] = {"canonical": slug,
                              "origin": "CROSSWALK_EXTENSION",
                              "justification": why}
    for surface, slug in DISPLAY_NAME_OVERRIDES.items():
        if slug not in cbr_slugs:
            deferred_targets.append((surface, slug))
        overrides[surface] = {
            "canonical": slug, "origin": "CROSSWALK_EXTENSION",
            "justification": ("Display-name form (school + mascot) used by "
                              "hoopR/ESPN; verified against the ESPN team-id "
                              "co-occurrence in the pinned schedules / the "
                              "ESPN teams pull (binds to one canonical).")}
    for surface in AMBIGUOUS_SURFACES:
        if surface in overrides:
            refuse("AMBIGUOUS_SURFACE_OVERRIDDEN", surface)
    for surface, entry in overrides.items():
        bound = surface2slug.get(surface)
        if bound is not None and bound != entry["canonical"]:
            refuse("OVERRIDE_CONTRADICTS_CBR_HARVEST",
                   f"{surface!r}: override -> {entry['canonical']}, harvest -> {bound}")
        if surface in OVERRIDES_2871 and entry["canonical"] != OVERRIDES_2871[surface]:
            refuse("OVERRIDE_DIVERGES_FROM_PR2871", surface)

    # ---- Torvik spine --------------------------------------------------
    vintage_path = Path(args.torvik_vintage)
    vintage_meta = json.loads(vintage_path.with_suffix(".json").read_text(encoding="utf-8"))
    raw = load_pinned(vintage_path, vintage_meta["sha256"], "torvik morning vintage")
    spine_rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    if len(spine_rows) != vintage_meta["team_rows"] or len(spine_rows) != 365:
        refuse("TORVIK_SPINE_SIZE", f"{len(spine_rows)} rows")
    inputs.append({"source": "torvik_live_route", "file": vintage_path.name,
                   "sha256": vintage_meta["sha256"], "bytes": len(raw),
                   "rows": len(spine_rows), "url": vintage_meta["url"],
                   "pulled_at_utc": vintage_meta["pulled_at_utc"],
                   "pin_basis": "PR #2841 admitted route; morning-pull manifest"})

    def resolve(surface, native_slug=None):
        """The published chain. Returns (canonical, method) or (None, None)."""
        if surface in overrides:
            return overrides[surface]["canonical"], "OVERRIDE"
        if native_slug is not None:
            return native_slug, "CBR_URL_NATIVE"
        if surface in surface2slug:
            return surface2slug[surface], "CBR_SURFACE"
        if surface in spine_canonical:
            return spine_canonical[surface], "TORVIK_SPINE_NAME"
        return None, None

    spine_canonical, minted = {}, {}
    for row in spine_rows:
        name = row["team"]
        if name in overrides:
            canon = overrides[name]["canonical"]
        elif name in surface2slug:
            canon = surface2slug[name]
        else:
            canon = mint_slug(name)
            minted[name] = canon
        if canon in spine_canonical.values():
            refuse("SPINE_CANONICAL_COLLISION", f"{name} -> {canon}")
        spine_canonical[name] = canon
    # Deferred override-target validation: an extension target must be a
    # CBR slug or one of the minted spine canonicals (display-name forms
    # for the post-2023 entrants target the minted ids).
    for surface, slug in deferred_targets:
        if slug not in minted.values():
            refuse("EXTENSION_TARGET_UNKNOWN", f"{surface!r} -> {slug}")

    # ---- Torvik archive surfaces (pinned commit) -----------------------
    archive_dir = pulls_dir / "torvik_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_surfaces = Counter()
    for date in TORVIK_ARCHIVE_DATES:
        path = archive_dir / f"ratings_archive_{date}.csv"
        if not path.exists():
            req = urllib.request.Request(
                TORVIK_ARCHIVE_URL.format(date=date),
                headers={"User-Agent": "sportsedge-admission-probe"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                path.write_bytes(resp.read())
        raw = path.read_bytes()
        inputs.append({"source": "torvik_archive", "file": path.name,
                       "sha256": sha256(raw), "bytes": len(raw),
                       "pin_basis": f"PR #2832 pinned commit {TORVIK_PINNED_COMMIT}"})
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            archive_surfaces[row["team"]] += 1

    # ---- hoopR surfaces + ESPN id co-occurrence ------------------------
    hoopr_manifest = json.loads(HOOPR_MANIFEST_PATH.read_text(encoding="utf-8"))
    hoopr_pins = {s["asset_name"]: s["sha256"] for s in hoopr_manifest["samples"]}
    loc_counts, disp_counts = Counter(), Counter()
    id_locations = defaultdict(Counter)       # espn id -> location -> games
    hoopr_games = {}                          # game id -> row (proof use)
    for year in range(2015, 2024):
        name = f"mbb_schedule_{year}.csv"
        raw = load_pinned(hoopr_dir / name, hoopr_pins[name], name)
        inputs.append({"source": "hoopr", "file": name, "sha256": hoopr_pins[name],
                       "bytes": len(raw), "pin_basis": "PR #2867 successor_manifest.json"})
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            hoopr_games[row["id"]] = row
            for side in ("home", "away"):
                loc_counts[row[f"{side}_location"]] += 1
                disp_counts[row[f"{side}_display_name"]] += 1
                id_locations[row[f"{side}_id"]][row[f"{side}_location"]] += 1

    # ---- ESPN reference pull -------------------------------------------
    espn_path = pulls_dir / "espn_teams.json"
    espn_raw = espn_path.read_bytes()
    inputs.append({"source": "espn_teams_pull", "file": espn_path.name,
                   "sha256": sha256(espn_raw), "bytes": len(espn_raw),
                   "pin_basis": "build-time reference pull 2026-10-28 (this packet); NOT an admission"})
    espn_teams = [t["team"] for t in
                  json.loads(espn_raw)["sports"][0]["leagues"][0]["teams"]]
    espn_loc_counts = Counter(t["location"] for t in espn_teams)
    espn_disp_counts = Counter(t["displayName"] for t in espn_teams)

    # ---- Resolve every source's surfaces -------------------------------
    def resolve_set(counts, native=None):
        resolved, unresolved = {}, []
        for surface, n in sorted(counts.items()):
            canon, method = resolve(surface, (native or {}).get(surface))
            if canon is None:
                reason = ("AMBIGUOUS_SURFACE_NAME_ONLY_JOIN_FORBIDDEN"
                          if surface in AMBIGUOUS_SURFACES
                          else "NOT_RESOLVED_BY_CHAIN")
                unresolved.append({"surface": surface, "occurrences": n,
                                   "reason": reason})
            else:
                resolved[surface] = {"canonical": canon, "method": method}
        return resolved, unresolved

    sets = {}
    sets["torvik"] = resolve_set(Counter({n: 1 for n in spine_canonical}))
    sets["torvik_archive"] = resolve_set(archive_surfaces)
    sets["cbr_team"] = resolve_set(Counter({s: 1 for s in team2slug}),
                                   native=team2slug)
    full_union = {**full2slug, **full1520_2slug}
    res_f, unres_f = resolve_set(Counter({s: 1 for s in full_union}),
                                 native=full_union)
    for surface, n in sorted(logs1520_unbound.items()):
        unres_f.append({"surface": surface, "occurrences": n,
                        "reason": "LOGS1520_FULLNAME_NOT_IN_PER_SEASON_HARVEST"})
    sets["cbr_teamfull"] = (res_f, unres_f)
    sets["cbr_opponent"] = resolve_set(opponent_counts)
    sets["hoopr_location"] = resolve_set(loc_counts)
    sets["hoopr_display_name"] = resolve_set(disp_counts)
    sets["espn_location"] = resolve_set(espn_loc_counts)
    sets["espn_display_name"] = resolve_set(espn_disp_counts)

    # ---- ESPN id bindings ----------------------------------------------
    id_bindings, id_conflicts, id_unbound = {}, [], []
    for tid, locs in sorted(id_locations.items()):
        resolved = {}
        for loc in locs:
            canon, _ = resolve(loc)
            if canon is not None:
                resolved[loc] = canon
        distinct = set(resolved.values())
        if len(locs) and len(resolved) == len(locs) and len(distinct) == 1:
            id_bindings[tid] = {"canonical": distinct.pop(),
                                "method": "HOOPR_ID_COOCCURRENCE",
                                "locations": sorted(locs)}
        elif len(distinct) > 1 or (resolved and len(resolved) < len(locs)):
            entry = {"espn_id": tid, "locations": sorted(locs),
                     "resolved_locations": resolved}
            (id_conflicts if len(distinct) > 1 else id_unbound).append(entry)
        else:
            id_unbound.append({"espn_id": tid, "locations": sorted(locs),
                               "resolved_locations": {}})
    espn_pull_ids = {}
    for t in espn_teams:
        tid = t["id"]
        if tid in id_bindings:
            espn_pull_ids[tid] = {**id_bindings[tid], "method": "HOOPR_ID_COOCCURRENCE"}
            continue
        canon, _ = resolve(t["location"])
        if canon is None:
            canon, _ = resolve(t["displayName"])
        if canon is not None:
            espn_pull_ids[tid] = {"canonical": canon, "method": "ESPN_SURFACE",
                                  "locations": [t["location"]]}
        else:
            id_unbound.append({"espn_id": tid, "locations": [t["location"]],
                               "resolved_locations": {},
                               "note": "ESPN teams pull; no hoopR co-occurrence, surfaces unresolved"})
    all_id_bindings = {**id_bindings, **espn_pull_ids}
    # An id bound by either pass is not unbound; merge duplicate entries.
    merged_unbound = {}
    for entry in id_unbound:
        if entry["espn_id"] in all_id_bindings:
            continue
        cur = merged_unbound.setdefault(entry["espn_id"], entry)
        if cur is not entry:
            cur["locations"] = sorted(set(cur["locations"]) | set(entry["locations"]))
    id_unbound = sorted(merged_unbound.values(), key=lambda e: e["espn_id"])

    # ---- Teams registry --------------------------------------------------
    espn_by_canonical = {}
    for tid, b in all_id_bindings.items():
        espn_by_canonical.setdefault(b["canonical"], []).append(tid)
    teams, historical = [], []
    spine_slugs = set(spine_canonical.values())
    name_by_slug = {v: k for k, v in spine_canonical.items()}
    for slug in sorted(spine_slugs | set(cbr_slugs)):
        entry = {
            "canonical_id": slug,
            "spine_member": slug in spine_slugs,
            "historical_only": slug not in spine_slugs,
            "canonical_id_origin": ("MINTED_NO_CBR_SLUG_IN_PINNED_SCOPE"
                                    if slug in minted.values() else "CBR_SLUG"),
            "torvik_name": name_by_slug.get(slug),
            "cbr_slug": slug if slug in cbr_slugs else None,
            "espn_id": (sorted(espn_by_canonical.get(slug, []))[0]
                        if espn_by_canonical.get(slug) else None),
            "capture_excluded_illinois": False,
        }
        teams.append(entry)
    for entry in teams:
        if entry["espn_id"] in ILLINOIS_ESPN_DENYLIST:
            entry["capture_excluded_illinois"] = True
    flagged = sorted(e["canonical_id"] for e in teams
                     if e["capture_excluded_illinois"])

    # ---- Fixture proofs ---------------------------------------------------
    proofs = []
    for date, pair in sorted(CHAMPIONSHIP_DATES.items()):
        # CBR leg: mirror rows on the date for both slugs (per-season
        # files bind by URL slug; logs1520 rows bind by full-name surface)
        cbr_scores = {}
        for name in PER_SEASON_FILES + ["logs1520.csv"]:
            raw = load_pinned(cbr_dir / name, cbr_pins[name], name)
            for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
                if row["Date"] != date:
                    continue
                if name == "logs1520.csv":
                    if row.get("season") not in LOGS1520_ADMITTED_SEASONS:
                        continue
                    slug = surface2slug.get(row["Team"])
                else:
                    url = next((v for v in row.values()
                                if isinstance(v, str) and "/cbb/schools/" in v), None)
                    slug = url.split("/")[3] if url else None
                if slug in pair:
                    cbr_scores[slug] = int(row["TeamScore"])
            if len(cbr_scores) == 2:
                break
        # hoopR leg: the proof's declared game (find by date + pair)
        hoopr_leg = None
        for gid, row in hoopr_games.items():
            if row["game_date"] != date:
                continue
            h, _ = resolve(row["home_location"])
            a, _ = resolve(row["away_location"])
            if tuple(sorted((h, a))) == pair:
                hoopr_leg = {"game_id": gid,
                             "scores": {h: int(row["home_score"]),
                                        a: int(row["away_score"])},
                             "espn_ids": {h: row["home_id"], a: row["away_id"]}}
                break
        # Torvik archive leg: both teams present in the D-1... archive file
        arch_raw = (archive_dir / f"ratings_archive_{date.replace('-', '')}.csv").read_bytes()
        arch_names = {r["team"] for r in csv.DictReader(io.StringIO(arch_raw.decode("utf-8")))}
        torvik_leg = {}
        for slug in pair:
            surf = next((s for s, c in spine_canonical.items() if c == slug), None)
            present = [n for n in arch_names if resolve(n)[0] == slug]
            torvik_leg[slug] = {"present": bool(present), "archive_surface": present[:1]}
        # ESPN leg
        espn_leg = None
        for eid, role in ESPN_EVENT_FILES.items():
            if role != f"CHAMPIONSHIP_{date[:4]}":
                continue
            raw = (pulls_dir / f"espn_event_{eid}.json").read_bytes()
            inputs.append({"source": "espn_event_pull", "file": f"espn_event_{eid}.json",
                           "sha256": sha256(raw), "bytes": len(raw),
                           "pin_basis": "build-time reference pull 2026-10-28 (this packet); NOT an admission"})
            comp = json.loads(raw)["header"]["competitions"][0]
            espn_leg = {"event_id": eid, "competitors": []}
            for c in comp["competitors"]:
                t = c["team"]
                espn_leg["competitors"].append({
                    "espn_id": t["id"], "display_name": t["displayName"],
                    "location": t["location"],
                    "canonical": all_id_bindings.get(t["id"], {}).get("canonical"),
                    "score": int(c["score"]) if c.get("score") else None})
        agree = (len(cbr_scores) == 2 and hoopr_leg is not None
                 and hoopr_leg["scores"] == cbr_scores
                 and all(v["present"] for v in torvik_leg.values())
                 and espn_leg is not None
                 and tuple(sorted(c["canonical"] for c in espn_leg["competitors"])) == pair
                 and {c["canonical"]: c["score"] for c in espn_leg["competitors"]} == cbr_scores)
        proofs.append({"fixture": f"NCAA championship {date}", "date": date,
                       "canonical_pair": list(pair), "cbr_scores": cbr_scores,
                       "hoopr": hoopr_leg, "torvik_archive": torvik_leg,
                       "espn": espn_leg, "all_sources_agree": agree})
    # Forward proof: the Nov 1 Rome game through ESPN -> crosswalk -> spine
    raw = (pulls_dir / "espn_event_401920982.json").read_bytes()
    inputs.append({"source": "espn_event_pull", "file": "espn_event_401920982.json",
                   "sha256": sha256(raw), "bytes": len(raw),
                   "pin_basis": "build-time reference pull 2026-10-28 (this packet); NOT an admission"})
    comp = json.loads(raw)["header"]["competitions"][0]
    rome = {"fixture": "Eternal City Tip-Off, Rome — Notre Dame @ Villanova",
            "espn_event_id": "401920982", "date_utc": comp["date"],
            "competitors": []}
    for c in comp["competitors"]:
        t = c["team"]
        canon = all_id_bindings.get(t["id"], {}).get("canonical")
        rome["competitors"].append({
            "home_away": c["homeAway"], "espn_id": t["id"],
            "display_name": t["displayName"], "location": t["location"],
            "canonical": canon,
            "spine_member": canon in spine_slugs})
    rome["forward_path_proven"] = all(
        c["canonical"] and c["spine_member"] for c in rome["competitors"])
    rome["note"] = ("Forward fixture: CBR/hoopR historical legs cannot exist "
                    "for an unplayed game. This proves the Nov 1 pre-check "
                    "path ESPN event -> ESPN id -> canonical -> Torvik spine. "
                    "The DK leg joins at capture time through the same ids.")
    proofs.append(rome)

    # ---- Coverage ---------------------------------------------------------
    coverage = {}
    for source, (resolved, unresolved) in sets.items():
        coverage[source] = {"surfaces_total": len(resolved) + len(unresolved),
                            "resolved": len(resolved),
                            "unresolved": len(unresolved)}
    coverage["espn_team_ids"] = {
        "ids_in_hoopr_schedules": len(id_locations),
        "ids_bound": len(id_bindings),
        "ids_conflicted_unbound": len(id_conflicts),
        "ids_unbound_partial_or_none": len(id_unbound),
        "espn_pull_teams": len(espn_teams),
        "espn_pull_ids_bound": len(espn_pull_ids),
        "spine_teams_with_espn_id": sum(1 for e in teams
                                        if e["spine_member"] and e["espn_id"]),
        "spine_teams_total": len(spine_canonical),
    }

    if args.worklist:
        for source, (resolved, unresolved) in sets.items():
            print(f"== {source}: {len(unresolved)} unresolved ==")
            for u in unresolved:
                print(f"  {u['occurrences']:>6}  {u['surface']!r}")
        print("== id conflicts ==", json.dumps(id_conflicts, indent=1))
        print("== minted ==", minted)
        print("== illinois flagged ==", flagged)
        print("== proofs agree ==", [p.get("all_sources_agree", p.get("forward_path_proven")) for p in proofs])
        return 0

    # Final integrity pass over the COMPLETE override table (all layers
    # assembled): no layer may have overwritten a PR #2871 pair with a
    # different target, and no override may contradict the CBR harvest.
    for surface, entry in overrides.items():
        if surface in OVERRIDES_2871 and entry["canonical"] != OVERRIDES_2871[surface]:
            refuse("OVERRIDE_DIVERGES_FROM_PR2871", surface)
        bound = surface2slug.get(surface)
        if bound is not None and bound != entry["canonical"]:
            refuse("OVERRIDE_CONTRADICTS_CBR_HARVEST",
                   f"{surface!r}: override -> {entry['canonical']}, harvest -> {bound}")

    artifact = {
        "artifact": "CBB_TEAM_IDENTITY_CROSSWALK_V1",
        "status": ("IDENTITY ARTIFACT — closes the identity-crosswalk gate "
                   "named OPEN in PR #2871's successor manifest. Not a "
                   "source admission; edits no design or criterion; "
                   "confers no validation, forward-clock or play credit."),
        "design_only": True, "validation_credit": False,
        "forward_clock_credit": False, "play_eligible": False,
        "sport": "CBB",
        "canonical_rule": ("canonical_id = CBR school slug where the school "
                           "appears in the pinned CBR bytes; otherwise a "
                           "slug minted from the Torvik spine name "
                           "(lowercase, spaces -> hyphens, [a-z0-9-] only)."),
        "matching_discipline": ("exact matches and table-driven overrides "
                                "ONLY; no fuzzy or similarity matching; "
                                "resolution order OVERRIDE > CBR_URL_NATIVE "
                                "> CBR_SURFACE > TORVIK_SPINE_NAME; team "
                                "ids bound only on consistent co-occurrence."),
        "inputs": inputs,
        "overrides": overrides,
        "teams": teams,
        "source_surfaces": {src: res for src, (res, _) in sets.items()},
        "unresolved": {src: un for src, (_, un) in sets.items()},
        "id_bindings": {"espn_team_id": all_id_bindings,
                        "conflicts_withheld": id_conflicts,
                        "unbound": id_unbound},
        "coverage": coverage,
        "fixture_proofs": proofs,
        "illinois_exclusion": {
            "rule": ("Illinois college teams are excluded from capture "
                     "scope by standing law. Identity is not capture: "
                     "flagged teams remain in this crosswalk and the "
                     "exclusion applies downstream, unchanged."),
            "basis": ("espn_id in sportsedge/cbb_capture_scope.py "
                      "_ILLINOIS_ESPN_MBB_2027_DENYLIST (13 ids, reconciled "
                      "there against the NCAA 2026-27 D1 Illinois directory)"),
            "flagged_canonicals": flagged,
        },
        "minted_canonical_ids": minted,
    }
    Path(args.out).write_text(json.dumps(artifact, indent=1, sort_keys=False) + "\n",
                              encoding="utf-8")
    print(json.dumps({"coverage": coverage, "teams": len(teams),
                      "illinois_flagged": flagged,
                      "proofs": [p.get("all_sources_agree",
                                       p.get("forward_path_proven"))
                                 for p in proofs]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
