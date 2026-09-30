"""Map phone team names onto nflverse abbreviations. Fail closed if not unique."""
from __future__ import annotations

NFL_TEAMS = {
    "ARI": ("Arizona Cardinals", "Cardinals", "Arizona"),
    "ATL": ("Atlanta Falcons", "Falcons", "Atlanta"),
    "BAL": ("Baltimore Ravens", "Ravens", "Baltimore"),
    "BUF": ("Buffalo Bills", "Bills", "Buffalo"),
    "CAR": ("Carolina Panthers", "Panthers", "Carolina"),
    "CHI": ("Chicago Bears", "Bears", "Chicago"),
    "CIN": ("Cincinnati Bengals", "Bengals", "Cincinnati"),
    "CLE": ("Cleveland Browns", "Browns", "Cleveland"),
    "DAL": ("Dallas Cowboys", "Cowboys", "Dallas"),
    "DEN": ("Denver Broncos", "Broncos", "Denver"),
    "DET": ("Detroit Lions", "Lions", "Detroit"),
    "GB": ("Green Bay Packers", "Packers", "Green Bay"),
    "HOU": ("Houston Texans", "Texans", "Houston"),
    "IND": ("Indianapolis Colts", "Colts", "Indianapolis"),
    "JAX": ("Jacksonville Jaguars", "Jaguars", "Jacksonville", "JAC"),
    "KC": ("Kansas City Chiefs", "Chiefs", "Kansas City"),
    "LAC": ("Los Angeles Chargers", "Chargers", "LA Chargers"),
    "LAR": ("Los Angeles Rams", "Rams", "LA Rams", "LA"),
    "LV": ("Las Vegas Raiders", "Raiders", "Las Vegas", "Oakland"),
    "MIA": ("Miami Dolphins", "Dolphins", "Miami"),
    "MIN": ("Minnesota Vikings", "Vikings", "Minnesota"),
    "NE": ("New England Patriots", "Patriots", "New England"),
    "NO": ("New Orleans Saints", "Saints", "New Orleans"),
    "NYG": ("New York Giants", "Giants"),
    "NYJ": ("New York Jets", "Jets"),
    "PHI": ("Philadelphia Eagles", "Eagles", "Philadelphia"),
    "PIT": ("Pittsburgh Steelers", "Steelers", "Pittsburgh"),
    "SEA": ("Seattle Seahawks", "Seahawks", "Seattle"),
    "SF": ("San Francisco 49ers", "49ers", "San Francisco", "Niners"),
    "TB": ("Tampa Bay Buccaneers", "Buccaneers", "Bucs", "Tampa Bay"),
    "TEN": ("Tennessee Titans", "Titans", "Tennessee"),
    "WAS": ("Washington Commanders", "Commanders", "Washington"),
}


class NflTeamAliasError(ValueError):
    pass


def resolve_team(text: str) -> str:
    needle = " ".join(str(text).strip().lower().split())
    if not needle:
        raise NflTeamAliasError("NFL_TEAM_BLANK")
    hits = []
    for abbr, names in NFL_TEAMS.items():
        aliases = {abbr.lower(), *(n.lower() for n in names)}
        if needle in aliases:
            hits.append(abbr)
    if needle == "la":
        raise NflTeamAliasError("NFL_TEAM_AMBIGUOUS:LA")
    if len(hits) != 1:
        raise NflTeamAliasError(f"NFL_TEAM_UNRESOLVED:{text}")
    return hits[0]
