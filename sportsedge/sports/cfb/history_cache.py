"""Executable, checksum-bound cache layer for SportsDataverse CFB history."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen

from .market_archive_contract import (
    load_contract, require_use, restriction_fields, digest as contract_digest,
)

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
MARKET_ARCHIVE_SOURCE_ID = "CFB_HISTORICAL_MARKET_SOURCE_V1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


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


def _load_market_archive_contract(path: str | Path) -> dict[str, Any]:
    payload = load_contract(path)
    upstream = payload.get("upstream") or {}
    digest = str(upstream.get("expected_sha256") or "").lower()
    if not _HEX64.fullmatch(digest):
        raise CFBHistoryCacheError("CFB_MARKET_ARCHIVE_SHA256_REQUIRED")
    try:
        size = int(upstream["expected_size_bytes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBHistoryCacheError("CFB_MARKET_ARCHIVE_SIZE_REQUIRED") from exc
    if size <= 0 or not str(upstream.get("raw_url") or "").startswith("https://"):
        raise CFBHistoryCacheError("CFB_MARKET_ARCHIVE_UPSTREAM_INVALID")
    return payload


def _verify_market_archive_file(path: Path, *, expected_size: int, expected_sha256: str) -> None:
    if not path.is_file() or path.stat().st_size != expected_size:
        raise CFBHistoryCacheError("CFB_MARKET_ARCHIVE_CACHE_SIZE_MISMATCH")
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise CFBHistoryCacheError("CFB_MARKET_ARCHIVE_CACHE_SHA256_MISMATCH")


def cache_market_archive(
    *,
    contract_path: str | Path,
    cache_root: str | Path,
    use: str,
    allow_benchmark: bool = False,
    opener: Callable[..., Any] = urlopen,
    retrieved_at: datetime | None = None,
) -> dict[str, Any]:
    """Cache the exact multi-season market archive behind an explicit benchmark gate."""
    if not allow_benchmark:
        raise CFBHistoricalReleaseError("CFB_MARKET_DATA_PROHIBITED:historical_market_archive")
    contract = _load_market_archive_contract(contract_path)
    require_use(contract, use)
    upstream = contract["upstream"]
    expected_size = int(upstream["expected_size_bytes"])
    expected_sha = str(upstream["expected_sha256"]).lower()
    target = (Path(cache_root) / "betting_archive" / contract["restriction_sha256"]
              / expected_sha / Path(str(upstream["path"])).name)
    reused = False
    if target.is_file():
        _verify_market_manifest(target, contract)
        try:
            _verify_market_archive_file(
                target, expected_size=expected_size, expected_sha256=expected_sha
            )
            reused = True
        except CFBHistoryCacheError:
            reused = False

    if not reused:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        digest = sha256()
        size = 0
        try:
            with _open(opener, str(upstream["raw_url"])) as response, partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise CFBHistoryCacheError("CFB_MARKET_ARCHIVE_STREAM_BYTES_REQUIRED")
                    data = bytes(chunk)
                    digest.update(data)
                    size += len(data)
                    handle.write(data)
            if size != expected_size:
                raise CFBHistoryCacheError("CFB_MARKET_ARCHIVE_SIZE_MISMATCH")
            if digest.hexdigest() != expected_sha:
                raise CFBHistoryCacheError("CFB_MARKET_ARCHIVE_SHA256_MISMATCH")
            partial.replace(target)
        except Exception:
            try:
                partial.unlink()
            except FileNotFoundError:
                pass
            raise

    _verify_market_archive_file(target, expected_size=expected_size, expected_sha256=expected_sha)
    if reused:
        manifest_path = target.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        return {"dataset": "historical_market_archive", "usage": "BENCHMARK_ONLY",
                "cache_file": str(target), "manifest_file": str(manifest_path),
                "content_sha256": expected_sha, "manifest_sha256": manifest["manifest_sha256"],
                "restriction_sha256": contract["restriction_sha256"],
                "row_count": manifest["row_count"], "cache_reused": True}
    retrieved = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    profile = contract.get("verified_profile") or {}
    manifest: dict[str, Any] = {
        "contract": "CFB_HISTORICAL_MARKET_ARCHIVE_CACHE_V2",
        **restriction_fields(contract),
        "source_contract_sha256": contract_digest(contract),
        "source_id": contract["source_id"],
        "usage": "BENCHMARK_ONLY",
        "retrieved_at": retrieved,
        "content_sha256": expected_sha,
        "content_size_bytes": expected_size,
        "upstream_repository": upstream["repository"],
        "upstream_commit": upstream["commit"],
        "upstream_path": upstream["path"],
        "cache_relative_path": str(target.relative_to(Path(cache_root))),
        "cache_reused": reused,
        "row_count": int(profile.get("row_count", 0)),
        "season_start": profile.get("season_start"),
        "season_end": profile.get("season_end"),
        "pit_certified": False,
        "clv_authority": False,
        "promotion_authority": False,
    }
    manifest_sha = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    manifest["manifest_sha256"] = manifest_sha
    manifest_path = target.parent / "manifest.json"
    _atomic_json(manifest_path, manifest)
    return {
        "dataset": "historical_market_archive",
        "usage": "BENCHMARK_ONLY",
        "cache_file": str(target),
        "manifest_file": str(manifest_path),
        "content_sha256": expected_sha,
        "manifest_sha256": manifest_sha,
        "restriction_sha256": contract["restriction_sha256"],
        "row_count": manifest["row_count"],
        "cache_reused": reused,
    }


def _iter_market_archive(*, contract_path: str | Path, cache_file: str | Path, use: str):
    """Stream checksum-verified historical market rows for benchmark/research use."""
    contract = _load_market_archive_contract(contract_path)
    require_use(contract, use)
    upstream = contract["upstream"]
    path = Path(cache_file)
    _verify_market_manifest(path, contract)
    _verify_market_archive_file(
        path,
        expected_size=int(upstream["expected_size_bytes"]),
        expected_sha256=str(upstream["expected_sha256"]).lower(),
    )
    required = list(contract.get("required_columns") or [])
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or any(name not in reader.fieldnames for name in required):
            raise CFBHistoryCacheError("CFB_MARKET_ARCHIVE_HEADER_INVALID")
        found = False
        for row in reader:
            found = True
            yield {str(k): "" if v is None else str(v) for k, v in row.items()}
        if not found:
            raise CFBHistoryCacheError("CFB_MARKET_ARCHIVE_EMPTY")


def _verify_market_manifest(path: Path, contract: dict) -> None:
    """Never bless legacy bytes in place; require write-time V2 provenance."""
    if (path.parent.name != contract["upstream"]["expected_sha256"]
            or path.parent.parent.name != contract["restriction_sha256"]
            or path.parent.parent.parent.name != "betting_archive"):
        raise CFBHistoryCacheError("CFB_MARKET_CACHE_NAMESPACE_MISMATCH")
    try:
        manifest = json.loads((path.parent / "manifest.json").read_text())
    except (OSError, ValueError) as exc:
        raise CFBHistoryCacheError("CFB_MARKET_CACHE_MANIFEST_REQUIRED") from exc
    expected = restriction_fields(contract)
    for key, value in expected.items():
        if contract_digest(manifest.get(key)) != contract_digest(value):
            raise CFBHistoryCacheError("CFB_MARKET_CACHE_RESTRICTION_MISMATCH:" + key)
    if (manifest.get("contract") != "CFB_HISTORICAL_MARKET_ARCHIVE_CACHE_V2"
            or manifest.get("source_contract_sha256") != contract_digest(contract)
            or manifest.get("content_sha256") != contract["upstream"]["expected_sha256"]
            or manifest.get("content_size_bytes") != contract["upstream"]["expected_size_bytes"]
            or manifest.get("source_id") != contract["source_id"]):
        raise CFBHistoryCacheError("CFB_MARKET_CACHE_SOURCE_MISMATCH")
    claimed = manifest.pop("manifest_sha256", None)
    if claimed != contract_digest(manifest):
        raise CFBHistoryCacheError("CFB_MARKET_CACHE_MANIFEST_HASH_MISMATCH")
