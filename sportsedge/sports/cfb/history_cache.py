"""Executable, checksum-bound cache layer for SportsDataverse CFB history."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen

from .historical_release import (
    BENCHMARK_ONLY_DATASETS,
    PREDICTIVE_DATASETS,
    CFBHistoricalReleaseError,
    assert_predictive_dataset,
    cache_asset_to_file,
    iter_cached_csv,
    manifest_dict,
    release_api_url,
    select_release_asset,
)

USER_AGENT = "SportsEdge-CFB-History/1"


class CFBHistoryCacheError(ValueError):
    pass


def parse_season_spec(specs: Iterable[str]) -> tuple[int, ...]:
    values: list[int] = []
    for raw in specs:
        for token in str(raw or "").split(","):
            token = token.strip()
            if not token:
                continue
            if ":" in token:
                left, right = token.split(":", 1)
                try:
                    start, end = int(left), int(right)
                except ValueError as exc:
                    raise CFBHistoryCacheError("CFB_HISTORY_SEASON_SPEC_INVALID") from exc
                if start > end:
                    raise CFBHistoryCacheError("CFB_HISTORY_SEASON_RANGE_REVERSED")
                values.extend(range(start, end + 1))
            else:
                try:
                    values.append(int(token))
                except ValueError as exc:
                    raise CFBHistoryCacheError("CFB_HISTORY_SEASON_SPEC_INVALID") from exc
    out = tuple(dict.fromkeys(values))
    if not out or any(x < 2000 or x > 2100 for x in out):
        raise CFBHistoryCacheError("CFB_HISTORY_SEASON_SPEC_INVALID")
    return out


def resolve_datasets(specs: Iterable[str], *, allow_benchmark: bool = False) -> tuple[str, ...]:
    values: list[str] = []
    for raw in specs:
        name = str(raw or "").strip().lower()
        if name == "predictive":
            values.extend(sorted(PREDICTIVE_DATASETS))
            continue
        if not name:
            continue
        if name in BENCHMARK_ONLY_DATASETS:
            if not allow_benchmark:
                raise CFBHistoricalReleaseError(f"CFB_MARKET_DATA_PROHIBITED:{name}")
        else:
            assert_predictive_dataset(name)
        values.append(name)
    out = tuple(dict.fromkeys(values))
    if not out:
        raise CFBHistoryCacheError("CFB_HISTORY_DATASET_REQUIRED")
    return out


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
    url = release_api_url(dataset)
    try:
        with _open(opener, url) as response:
            raw = response.read()
    except Exception as exc:
        raise CFBHistoryCacheError(
            f"CFB_HISTORY_RELEASE_FETCH_FAILED:{type(exc).__name__}:{exc}"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBHistoryCacheError("CFB_HISTORY_RELEASE_JSON_INVALID") from exc
    if not isinstance(payload, Mapping):
        raise CFBHistoryCacheError("CFB_HISTORY_RELEASE_JSON_NOT_OBJECT")
    return payload


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def cache_one(
    *,
    dataset: str,
    season: int,
    cache_root: str | Path,
    allow_benchmark: bool = False,
    opener: Callable[..., Any] = urlopen,
    retrieved_at: datetime | None = None,
) -> dict[str, Any]:
    name = resolve_datasets([dataset], allow_benchmark=allow_benchmark)[0]
    year = parse_season_spec([str(season)])[0]
    payload = fetch_release_payload(name, opener=opener)
    asset = select_release_asset(payload, dataset=name, season=year)
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
    retrieved = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    manifest = manifest_dict(
        asset,
        retrieved_at=retrieved,
        content_sha256=asset.sha256,
        row_count=row_count,
    )
    manifest["cache_relative_path"] = str(Path(name) / str(year) / asset.asset_name)
    manifest["cache_reused"] = reused
    manifest_sha = sha256(
        json.dumps(
            manifest,
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
    }


def cache_many(
    *,
    datasets: Iterable[str],
    seasons: Iterable[int],
    cache_root: str | Path,
    allow_benchmark: bool = False,
    opener: Callable[..., Any] = urlopen,
) -> tuple[dict[str, Any], ...]:
    names = resolve_datasets(datasets, allow_benchmark=allow_benchmark)
    years = parse_season_spec([str(x) for x in seasons])
    return tuple(
        cache_one(
            dataset=name,
            season=year,
            cache_root=cache_root,
            allow_benchmark=allow_benchmark,
            opener=opener,
        )
        for year in years
        for name in names
    )
