"""Checksum-bound SportsDataverse CFB historical release ingestion.

This module only authenticates and parses published season assets. It does not
turn betting lines into predictive features. Callers must explicitly request a
dataset, and market-bearing ``betting`` rows are labelled benchmark-only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import gzip
from hashlib import sha256
import io
import json
import re
from typing import Any, Callable, Mapping

SPORTSDATAVERSE_REPO = "sportsdataverse/sportsdataverse-data"
RELEASE_TAG_BY_DATASET = {
    "schedules": "espn_cfb_schedules",
    "adv_team": "espn_cfb_adv_team",
    "adv_situational": "espn_cfb_adv_situational",
    "adv_drives": "espn_cfb_adv_drives",
    "betting": "espn_cfb_betting",
}
ASSET_PREFIX_BY_DATASET = {
    "schedules": "cfb_schedule",
    "adv_team": "adv_team",
    "adv_situational": "adv_situational",
    "adv_drives": "adv_drives",
    "betting": "betting",
}
PREDICTIVE_DATASETS = frozenset({"schedules", "adv_team", "adv_situational", "adv_drives"})
BENCHMARK_ONLY_DATASETS = frozenset({"betting"})
SUPPORTED_DATASETS = frozenset(set(PREDICTIVE_DATASETS) | set(BENCHMARK_ONLY_DATASETS))
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CFBHistoricalReleaseError(ValueError):
    pass


@dataclass(frozen=True)
class CFBReleaseAsset:
    dataset: str
    season: int
    release_tag: str
    release_id: int
    release_updated_at: str
    asset_id: int
    asset_name: str
    browser_download_url: str
    sha256: str
    size: int
    usage: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CFBLoadedSeason:
    asset: CFBReleaseAsset
    retrieved_at: str
    content_sha256: str
    row_count: int
    rows: tuple[dict[str, str], ...]
    manifest_sha256: str


def _dataset(value: Any) -> str:
    name = str(value or "").strip().lower()
    if name not in SUPPORTED_DATASETS:
        raise CFBHistoricalReleaseError(f"CFB_HISTORICAL_DATASET_UNSUPPORTED:{name or 'MISSING'}")
    return name


def _season(value: Any) -> int:
    if isinstance(value, bool):
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_SEASON_INVALID")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_SEASON_INVALID") from exc
    if out < 2000 or out > 2100:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_SEASON_INVALID")
    return out


def release_api_url(dataset: str) -> str:
    name = _dataset(dataset)
    tag = RELEASE_TAG_BY_DATASET[name]
    return f"https://api.github.com/repos/{SPORTSDATAVERSE_REPO}/releases/tags/{tag}"


def _digest(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if not _HEX64.fullmatch(text):
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_ASSET_SHA256_REQUIRED")
    return text


def select_release_asset(
    release_payload: Mapping[str, Any], *, dataset: str, season: int
) -> CFBReleaseAsset:
    name, year = _dataset(dataset), _season(season)
    if not isinstance(release_payload, Mapping):
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_RELEASE_NOT_OBJECT")
    expected_tag = RELEASE_TAG_BY_DATASET[name]
    if str(release_payload.get("tag_name") or "").strip() != expected_tag:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_RELEASE_TAG_MISMATCH")
    if release_payload.get("draft") is True or release_payload.get("prerelease") is True:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_RELEASE_NOT_FINAL")
    updated = str(release_payload.get("updated_at") or "").strip()
    if not updated:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_RELEASE_UPDATED_AT_REQUIRED")
    try:
        release_id = int(release_payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_RELEASE_ID_REQUIRED") from exc

    prefix = ASSET_PREFIX_BY_DATASET[name]
    candidates: list[Mapping[str, Any]] = []
    wanted = {f"{prefix}_{year}.csv", f"{prefix}_{year}.csv.gz"}
    assets = release_payload.get("assets")
    if not isinstance(assets, list):
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_ASSETS_NOT_LIST")
    for raw in assets:
        if isinstance(raw, Mapping) and str(raw.get("name") or "") in wanted:
            candidates.append(raw)
    if len(candidates) != 1:
        if not candidates:
            raise CFBHistoricalReleaseError(f"CFB_HISTORICAL_ASSET_MISSING:{name}:{year}")
        raise CFBHistoricalReleaseError(f"CFB_HISTORICAL_ASSET_AMBIGUOUS:{name}:{year}")
    raw = candidates[0]
    state = str(raw.get("state") or "").strip().lower()
    if state and state != "uploaded":
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_ASSET_NOT_UPLOADED")
    url = str(raw.get("browser_download_url") or "").strip()
    expected_prefix = (
        f"https://github.com/{SPORTSDATAVERSE_REPO}/releases/download/"
        f"{expected_tag}/"
    )
    if not url.startswith(expected_prefix):
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_ASSET_URL_INVALID")
    try:
        asset_id = int(raw["id"])
        size = int(raw["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_ASSET_METADATA_INVALID") from exc
    if asset_id <= 0 or size <= 0:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_ASSET_METADATA_INVALID")

    return CFBReleaseAsset(
        dataset=name,
        season=year,
        release_tag=expected_tag,
        release_id=release_id,
        release_updated_at=updated,
        asset_id=asset_id,
        asset_name=str(raw["name"]),
        browser_download_url=url,
        sha256=_digest(raw.get("digest")),
        size=size,
        usage="PREDICTIVE_INPUT" if name in PREDICTIVE_DATASETS else "BENCHMARK_ONLY",
    )


def verify_asset_bytes(asset: CFBReleaseAsset, raw: bytes) -> None:
    if not isinstance(raw, (bytes, bytearray)):
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_ASSET_BYTES_REQUIRED")
    data = bytes(raw)
    if len(data) != asset.size:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_ASSET_SIZE_MISMATCH")
    actual = sha256(data).hexdigest()
    if actual != asset.sha256:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_ASSET_SHA256_MISMATCH")


def _csv_bytes(asset: CFBReleaseAsset, raw: bytes) -> bytes:
    if asset.asset_name.endswith(".csv.gz"):
        try:
            return gzip.decompress(raw)
        except (OSError, EOFError) as exc:
            raise CFBHistoricalReleaseError("CFB_HISTORICAL_GZIP_INVALID") from exc
    if asset.asset_name.endswith(".csv"):
        return raw
    raise CFBHistoricalReleaseError("CFB_HISTORICAL_ASSET_FORMAT_UNSUPPORTED")


def parse_asset_rows(asset: CFBReleaseAsset, raw: bytes) -> tuple[dict[str, str], ...]:
    verify_asset_bytes(asset, raw)
    csv_raw = _csv_bytes(asset, bytes(raw))
    try:
        text = csv_raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_CSV_UTF8_REQUIRED") from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise CFBHistoricalReleaseError("CFB_HISTORICAL_CSV_HEADER_INVALID")
        rows = tuple(
            {str(k): "" if v is None else str(v) for k, v in row.items()}
            for row in reader
        )
    except csv.Error as exc:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_CSV_INVALID") from exc
    if not rows:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_CSV_EMPTY")
    return rows


def manifest_dict(
    asset: CFBReleaseAsset, *, retrieved_at: str, content_sha256: str, row_count: int
) -> dict[str, Any]:
    retrieved = str(retrieved_at or "").strip()
    if not retrieved:
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_RETRIEVED_AT_REQUIRED")
    if not _HEX64.fullmatch(str(content_sha256 or "").lower()):
        raise CFBHistoricalReleaseError("CFB_HISTORICAL_CONTENT_SHA256_INVALID")
    return {
        "contract": "CFB_SPORTSDATAVERSE_RELEASE_V1",
        "asset": asset.to_dict(),
        "retrieved_at": retrieved,
        "content_sha256": str(content_sha256).lower(),
        "row_count": int(row_count),
        "market_role": asset.usage,
    }


def load_release_season(
    *,
    dataset: str,
    season: int,
    release_fetcher: Callable[[str], Mapping[str, Any]],
    bytes_fetcher: Callable[[str], bytes],
    retrieved_at: str,
) -> CFBLoadedSeason:
    url = release_api_url(dataset)
    payload = release_fetcher(url)
    asset = select_release_asset(payload, dataset=dataset, season=season)
    raw = bytes_fetcher(asset.browser_download_url)
    rows = parse_asset_rows(asset, raw)
    content_hash = sha256(raw).hexdigest()
    manifest = manifest_dict(
        asset, retrieved_at=retrieved_at, content_sha256=content_hash, row_count=len(rows)
    )
    manifest_hash = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return CFBLoadedSeason(
        asset=asset,
        retrieved_at=str(retrieved_at).strip(),
        content_sha256=content_hash,
        row_count=len(rows),
        rows=rows,
        manifest_sha256=manifest_hash,
    )


def assert_predictive_dataset(dataset: str) -> str:
    name = _dataset(dataset)
    if name not in PREDICTIVE_DATASETS:
        raise CFBHistoricalReleaseError(f"CFB_MARKET_DATA_PROHIBITED:{name}")
    return name
