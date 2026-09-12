"""Prospective, checksum-bound CFB player-participation source capture.

These snapshots establish availability only from retrieval time forward. They do
not backfill point-in-time history, create Model_P, or grant promotion authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from .historical_release import (
    CFBHistoricalReleaseError,
    CFBReleaseAsset,
    cache_asset_to_file,
    iter_cached_csv,
    manifest_dict,
)

SPORTSDATAVERSE_REPO = "sportsdataverse/sportsdataverse-data"
PARTICIPATION_CAPTURE_CONTRACT = "CFB_PARTICIPATION_SOURCE_CAPTURE_V1"
PARTICIPATION_DATASETS = {
    "play_by_play": ("espn_cfb_pbp", "play_by_play"),
    "play_participants": ("espn_cfb_play_participants", "play_participants"),
    "player_box": ("espn_cfb_player_box", "player_box"),
    "game_rosters": ("espn_cfb_game_rosters", "game_rosters"),
}
ASSET_FORMAT_PREFERENCE = (".csv.gz", ".csv")
USER_AGENT = "SportsEdge-CFB-Participation/1"


class CFBParticipationSourceError(ValueError):
    pass


def _dataset(value: Any) -> str:
    name = str(value or "").strip().lower()
    if name not in PARTICIPATION_DATASETS:
        raise CFBParticipationSourceError(
            f"CFB_PARTICIPATION_DATASET_UNSUPPORTED:{name or 'MISSING'}"
        )
    return name


def _season(value: Any) -> int:
    if isinstance(value, bool):
        raise CFBParticipationSourceError("CFB_PARTICIPATION_SEASON_INVALID")
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise CFBParticipationSourceError("CFB_PARTICIPATION_SEASON_INVALID") from exc
    if year < 2000 or year > 2100:
        raise CFBParticipationSourceError("CFB_PARTICIPATION_SEASON_INVALID")
    return year


def release_api_url(dataset: str) -> str:
    name = _dataset(dataset)
    tag, _ = PARTICIPATION_DATASETS[name]
    return (
        f"https://api.github.com/repos/{SPORTSDATAVERSE_REPO}/releases/tags/{tag}"
    )


def _open(opener: Callable[..., Any], url: str):
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    return opener(request, timeout=60)


def fetch_release_payload(
    dataset: str, *, opener: Callable[..., Any] = urlopen
) -> Mapping[str, Any]:
    try:
        with _open(opener, release_api_url(dataset)) as response:
            raw = response.read()
    except Exception as exc:
        raise CFBParticipationSourceError(
            f"CFB_PARTICIPATION_RELEASE_FETCH_FAILED:{type(exc).__name__}:{exc}"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBParticipationSourceError(
            "CFB_PARTICIPATION_RELEASE_JSON_INVALID"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CFBParticipationSourceError("CFB_PARTICIPATION_RELEASE_NOT_OBJECT")
    return payload


def _digest(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBParticipationSourceError(
            "CFB_PARTICIPATION_ASSET_SHA256_REQUIRED"
        )
    return text


def select_participation_asset(
    release_payload: Mapping[str, Any], *, dataset: str, season: int
) -> CFBReleaseAsset:
    name = _dataset(dataset)
    year = _season(season)
    tag, prefix = PARTICIPATION_DATASETS[name]
    if str(release_payload.get("tag_name") or "").strip() != tag:
        raise CFBParticipationSourceError("CFB_PARTICIPATION_RELEASE_TAG_MISMATCH")
    if release_payload.get("draft") is True or release_payload.get("prerelease") is True:
        raise CFBParticipationSourceError("CFB_PARTICIPATION_RELEASE_NOT_FINAL")
    updated = str(release_payload.get("updated_at") or "").strip()
    if not updated:
        raise CFBParticipationSourceError(
            "CFB_PARTICIPATION_RELEASE_UPDATED_AT_REQUIRED"
        )
    try:
        release_id = int(release_payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBParticipationSourceError(
            "CFB_PARTICIPATION_RELEASE_ID_REQUIRED"
        ) from exc
    assets = release_payload.get("assets")
    if not isinstance(assets, list):
        raise CFBParticipationSourceError("CFB_PARTICIPATION_ASSETS_NOT_LIST")

    raw: Mapping[str, Any] | None = None
    for suffix in ASSET_FORMAT_PREFERENCE:
        wanted = f"{prefix}_{year}{suffix}"
        candidates = [
            item
            for item in assets
            if isinstance(item, Mapping) and str(item.get("name") or "") == wanted
        ]
        if len(candidates) > 1:
            raise CFBParticipationSourceError(
                f"CFB_PARTICIPATION_ASSET_AMBIGUOUS:{name}:{year}:{suffix}"
            )
        if candidates:
            raw = candidates[0]
            break
    if raw is None:
        raise CFBParticipationSourceError(
            f"CFB_PARTICIPATION_ASSET_MISSING:{name}:{year}"
        )
    state = str(raw.get("state") or "").strip().lower()
    if state and state != "uploaded":
        raise CFBParticipationSourceError("CFB_PARTICIPATION_ASSET_NOT_UPLOADED")
    url = str(raw.get("browser_download_url") or "").strip()
    expected_prefix = (
        f"https://github.com/{SPORTSDATAVERSE_REPO}/releases/download/{tag}/"
    )
    if not url.startswith(expected_prefix):
        raise CFBParticipationSourceError("CFB_PARTICIPATION_ASSET_URL_INVALID")
    try:
        asset_id = int(raw["id"])
        size = int(raw["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBParticipationSourceError(
            "CFB_PARTICIPATION_ASSET_METADATA_INVALID"
        ) from exc
    if asset_id <= 0 or size <= 0:
        raise CFBParticipationSourceError("CFB_PARTICIPATION_ASSET_METADATA_INVALID")
    return CFBReleaseAsset(
        dataset=name,
        season=year,
        release_tag=tag,
        release_id=release_id,
        release_updated_at=updated,
        asset_id=asset_id,
        asset_name=str(raw["name"]),
        browser_download_url=url,
        sha256=_digest(raw.get("digest")),
        size=size,
        usage="PREDICTIVE_PARTICIPATION_INPUT",
    )


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def cache_participation_source(
    *,
    dataset: str,
    season: int,
    cache_root: str | Path,
    opener: Callable[..., Any] = urlopen,
    retrieved_at: datetime | None = None,
) -> dict[str, Any]:
    name = _dataset(dataset)
    year = _season(season)
    payload = fetch_release_payload(name, opener=opener)
    asset = select_participation_asset(payload, dataset=name, season=year)
    root = Path(cache_root)
    target = root / name / str(year) / asset.asset_name

    reused = False
    row_count: int | None = None
    if target.is_file():
        try:
            row_count = sum(1 for _ in iter_cached_csv(asset, str(target)))
            reused = True
        except CFBHistoricalReleaseError:
            reused = False
    if not reused:
        asset_opener = lambda url: _open(opener, url)
        cache_asset_to_file(asset, str(target), opener=asset_opener)
        row_count = sum(1 for _ in iter_cached_csv(asset, str(target)))
    assert row_count is not None

    retrieved = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    manifest = manifest_dict(
        asset,
        retrieved_at=retrieved.isoformat(),
        content_sha256=asset.sha256,
        row_count=row_count,
    )
    manifest.update(
        {
            "contract": PARTICIPATION_CAPTURE_CONTRACT,
            "cache_relative_path": str(Path(name) / str(year) / asset.asset_name),
            "cache_reused": reused,
            "market_data": False,
            "point_in_time_from_retrieval_forward": True,
            "retroactive_point_in_time_claim": False,
            "model_p_created": False,
            "promotion_authority": False,
        }
    )
    unsigned = dict(manifest)
    manifest_sha = sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    manifest["manifest_sha256"] = manifest_sha
    manifest_path = target.parent / "manifest.json"
    _atomic_json(manifest_path, manifest)
    return {
        "dataset": name,
        "season": year,
        "usage": asset.usage,
        "cache_file": str(target),
        "manifest_file": str(manifest_path),
        "content_sha256": asset.sha256,
        "manifest_sha256": manifest_sha,
        "row_count": row_count,
        "cache_reused": reused,
        "retrieved_at": retrieved.isoformat(),
    }


def cache_participation_bundle(
    *,
    season: int,
    cache_root: str | Path,
    opener: Callable[..., Any] = urlopen,
) -> tuple[dict[str, Any], ...]:
    year = _season(season)
    return tuple(
        cache_participation_source(
            dataset=name,
            season=year,
            cache_root=cache_root,
            opener=opener,
        )
        for name in PARTICIPATION_DATASETS
    )


__all__ = [
    "ASSET_FORMAT_PREFERENCE",
    "CFBParticipationSourceError",
    "PARTICIPATION_CAPTURE_CONTRACT",
    "PARTICIPATION_DATASETS",
    "cache_participation_bundle",
    "cache_participation_source",
    "fetch_release_payload",
    "release_api_url",
    "select_participation_asset",
]
