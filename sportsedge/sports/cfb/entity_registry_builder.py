"""Build the authoritative CFB entity registry from CFBD season records.

CFBD numeric team IDs are used as stable external identities. Division/conference are
stored by season so realignment or FCS/FBS transitions do not rewrite history. Alias
expansion from the current FBS team catalog is optional; unresolved/ambiguous aliases
still fail closed in ``CFBEntityRegistry``.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .entity_registry import CFBEntity, CFBEntityRegistry, CFBEntityResolutionError
from .source import _auth, _cfbd_url, _json_get


class CFBEntityRegistryBuildError(ValueError):
    pass


def _supported_classification(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text if text in {"FBS", "FCS"} else None


def fetch_cfbd_team_season_rows(
    *,
    seasons: Iterable[int],
    cfbd_api_key: str,
    opener: Callable = urlopen,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for season in sorted({int(x) for x in seasons}):
        payload = _json_get(
            _cfbd_url("/records", {"year": season}),
            headers=_auth(cfbd_api_key),
            opener=opener,
        )
        if not isinstance(payload, list):
            raise CFBEntityRegistryBuildError(f"CFBD_RECORDS_NOT_LIST:{season}")
        for row in payload:
            if not isinstance(row, Mapping):
                continue
            classification = _supported_classification(row.get("classification"))
            if classification is None:
                continue
            team_id = row.get("teamId")
            name = str(row.get("team") or "").strip()
            if team_id is None or not name:
                raise CFBEntityRegistryBuildError(f"CFBD_RECORD_IDENTITY_MISSING:{season}")
            out.append({
                "team_id": f"cfbd:{int(team_id)}",
                "season": season,
                "name": name,
                "classification": classification,
                "conference": str(row.get("conference") or "").strip() or None,
            })
    if not out:
        raise CFBEntityRegistryBuildError("CFBD_ENTITY_SEASON_ROWS_EMPTY")
    return out


def fetch_cfbd_fbs_aliases(
    *,
    season: int,
    cfbd_api_key: str,
    opener: Callable = urlopen,
) -> dict[str, set[str]]:
    payload = _json_get(
        _cfbd_url("/teams/fbs", {"year": int(season)}),
        headers=_auth(cfbd_api_key),
        opener=opener,
    )
    if not isinstance(payload, list):
        raise CFBEntityRegistryBuildError("CFBD_FBS_TEAM_CATALOG_NOT_LIST")
    out: dict[str, set[str]] = defaultdict(set)
    for row in payload:
        if not isinstance(row, Mapping) or row.get("id") is None:
            continue
        team_id = f"cfbd:{int(row['id'])}"
        for value in (
            row.get("school"), row.get("abbreviation"),
            f"{row.get('school')} {row.get('mascot')}" if row.get("school") and row.get("mascot") else None,
        ):
            text = str(value or "").strip()
            if text:
                out[team_id].add(text)
        alternates = row.get("alternateNames")
        if isinstance(alternates, list):
            out[team_id].update(str(x).strip() for x in alternates if str(x).strip())
    return out


def build_entity_registry(
    rows: Iterable[Mapping[str, Any]],
    *,
    version: str,
    aliases_by_team_id: Mapping[str, Iterable[str]] | None = None,
) -> CFBEntityRegistry:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in rows:
        row = dict(source)
        team_id = str(row.get("team_id") or "").strip()
        name = str(row.get("name") or "").strip()
        classification = _supported_classification(row.get("classification"))
        if not team_id or not name or classification is None:
            raise CFBEntityRegistryBuildError("ENTITY_SEASON_ROW_INVALID")
        grouped[team_id].append({
            "season": int(row["season"]),
            "name": name,
            "classification": classification,
            "conference": str(row.get("conference") or "").strip() or None,
        })
    entities: list[CFBEntity] = []
    for team_id, history in sorted(grouped.items()):
        seen_seasons: set[int] = set()
        for row in history:
            if row["season"] in seen_seasons:
                raise CFBEntityRegistryBuildError(f"ENTITY_DUPLICATE_TEAM_SEASON:{team_id}:{row['season']}")
            seen_seasons.add(row["season"])
        # Most recent season's name is canonical; historical names remain aliases.
        latest_season = max(row["season"] for row in history)
        latest_names = sorted(row["name"] for row in history if row["season"] == latest_season)
        canonical = latest_names[0]
        aliases = {row["name"] for row in history if row["name"] != canonical}
        aliases.update(str(x).strip() for x in (aliases_by_team_id or {}).get(team_id, ()) if str(x).strip())
        aliases.discard(canonical)
        entities.append(CFBEntity(
            sportsedge_team_id=team_id,
            canonical_name=canonical,
            aliases=tuple(sorted(aliases)),
            classification_by_season=tuple(sorted((row["season"], row["classification"]) for row in history)),
            conference_by_season=tuple(sorted((row["season"], row["conference"]) for row in history)),
        ))
    try:
        return CFBEntityRegistry(version=version, entities=entities)
    except CFBEntityResolutionError as exc:
        raise CFBEntityRegistryBuildError(str(exc)) from exc


def build_cfbd_entity_registry(
    *,
    seasons: Iterable[int],
    cfbd_api_key: str,
    version: str,
    opener: Callable = urlopen,
) -> CFBEntityRegistry:
    season_list = sorted({int(x) for x in seasons})
    if not season_list:
        raise CFBEntityRegistryBuildError("ENTITY_REGISTRY_SEASONS_REQUIRED")
    rows = fetch_cfbd_team_season_rows(seasons=season_list, cfbd_api_key=cfbd_api_key, opener=opener)
    aliases = fetch_cfbd_fbs_aliases(season=max(season_list), cfbd_api_key=cfbd_api_key, opener=opener)
    return build_entity_registry(rows, version=version, aliases_by_team_id=aliases)
