"""Pinned full-venue source for SportsDataverse CFB historical weather.

The source is a public, immutable GitHub blob containing a CFBD venue export.
It is context metadata only: no outcomes, markets, or betting data are present.
"""
from __future__ import annotations

import csv
from hashlib import sha1, sha256
import io
from math import isfinite
from typing import Any, Mapping


class SDVVenueSourceError(ValueError):
    pass


REQUIRED_FIELDS = frozenset({"id", "name", "location.x", "location.y", "dome"})


def git_blob_sha1(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return sha1(header + raw).hexdigest()


def _bool(value: object, name: str) -> bool:
    token = str(value or "").strip().lower()
    if token in {"true", "1", "t"}:
        return True
    if token in {"false", "0", "f"}:
        return False
    raise SDVVenueSourceError(f"CFB_SDV_VENUE_BOOL_INVALID:{name}:{token}")


def parse_pinned_venues(
    raw: bytes,
    *,
    expected_sha256: str,
    expected_git_blob_sha1: str,
    expected_row_count: int,
) -> dict[int, dict[str, Any]]:
    if not raw:
        raise SDVVenueSourceError("CFB_SDV_VENUE_SOURCE_EMPTY")
    if sha256(raw).hexdigest() != str(expected_sha256).lower():
        raise SDVVenueSourceError("CFB_SDV_VENUE_SOURCE_SHA256_MISMATCH")
    if git_blob_sha1(raw) != str(expected_git_blob_sha1).lower():
        raise SDVVenueSourceError("CFB_SDV_VENUE_SOURCE_GIT_BLOB_MISMATCH")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SDVVenueSourceError("CFB_SDV_VENUE_SOURCE_UTF8_REQUIRED") from exc

    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = frozenset(reader.fieldnames or ())
    missing = sorted(REQUIRED_FIELDS - fields)
    if missing:
        raise SDVVenueSourceError(
            "CFB_SDV_VENUE_SOURCE_COLUMNS_MISSING:" + ",".join(missing)
        )

    rows = list(reader)
    if len(rows) != int(expected_row_count):
        raise SDVVenueSourceError(
            f"CFB_SDV_VENUE_SOURCE_ROW_COUNT_MISMATCH:{len(rows)}:{int(expected_row_count)}"
        )

    out: dict[int, dict[str, Any]] = {}
    for line_no, row in enumerate(rows, start=2):
        try:
            venue_id = int(str(row.get("id") or "").strip())
        except ValueError as exc:
            raise SDVVenueSourceError(
                f"CFB_SDV_VENUE_ID_INVALID:{line_no}"
            ) from exc
        if venue_id in out:
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_ID_DUPLICATE:{venue_id}")

        lat_raw = str(row.get("location.x") or "").strip()
        lon_raw = str(row.get("location.y") or "").strip()
        if not lat_raw or not lon_raw:
            # Preserve the source gap. A referenced missing venue fails later;
            # unreferenced incomplete rows do not poison the full source parse.
            continue
        try:
            lat, lon = float(lat_raw), float(lon_raw)
        except ValueError as exc:
            raise SDVVenueSourceError(
                f"CFB_SDV_VENUE_COORDINATES_INVALID:{venue_id}"
            ) from exc
        if not isfinite(lat) or not isfinite(lon) or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise SDVVenueSourceError(
                f"CFB_SDV_VENUE_COORDINATES_OUT_OF_RANGE:{venue_id}"
            )
        out[venue_id] = {
            "venue_id": venue_id,
            "name": str(row.get("name") or "").strip() or None,
            "latitude": lat,
            "longitude": lon,
            "game_indoor": _bool(row.get("dome"), f"dome:{venue_id}"),
        }

    if not out:
        raise SDVVenueSourceError("CFB_SDV_VENUE_SOURCE_NO_USABLE_ROWS")
    return out



def apply_pinned_venue_supplements(
    venues: Mapping[int, Mapping[str, Any]],
    supplements: object,
) -> dict[int, dict[str, Any]]:
    """Merge explicit hash-bound venue supplements without overriding pinned rows."""
    out={int(k):dict(v) for k,v in venues.items()}
    if supplements in (None, []):
        return out
    if not isinstance(supplements, list):
        raise SDVVenueSourceError("CFB_SDV_VENUE_SUPPLEMENTS_LIST_REQUIRED")
    seen=set()
    for index,item in enumerate(supplements):
        if not isinstance(item, Mapping):
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_SUPPLEMENT_OBJECT_REQUIRED:{index}")
        try:
            venue_id=int(item.get("venue_id"))
            lat=float(item.get("latitude"))
            lon=float(item.get("longitude"))
        except (TypeError,ValueError) as exc:
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_SUPPLEMENT_VALUE_INVALID:{index}") from exc
        if venue_id in seen:
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_SUPPLEMENT_DUPLICATE:{venue_id}")
        seen.add(venue_id)
        if venue_id in out:
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_SUPPLEMENT_OVERRIDE_FORBIDDEN:{venue_id}")
        if not isfinite(lat) or not isfinite(lon) or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_SUPPLEMENT_COORDINATES_INVALID:{venue_id}")
        indoor=item.get("game_indoor")
        if type(indoor) is not bool:
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_SUPPLEMENT_INDOOR_BOOL_REQUIRED:{venue_id}")
        sources=item.get("source_identities")
        if not isinstance(sources,list) or not sources or any(not str(x).strip() for x in sources):
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_SUPPLEMENT_SOURCES_REQUIRED:{venue_id}")
        out[venue_id]={
            "venue_id":venue_id,
            "name":str(item.get("name") or "").strip() or None,
            "latitude":lat,
            "longitude":lon,
            "game_indoor":indoor,
            "supplement_source_identities":[str(x).strip() for x in sources],
        }
    return out

def apply_pinned_venue_aliases(
    venues: Mapping[int, Mapping[str, Any]],
    aliases: object,
) -> dict[int, dict[str, Any]]:
    """Bind schedule-era venue IDs to an existing pinned physical venue."""
    out={int(k):dict(v) for k,v in venues.items()}
    if aliases in (None, []):
        return out
    if not isinstance(aliases, list):
        raise SDVVenueSourceError("CFB_SDV_VENUE_ALIASES_LIST_REQUIRED")
    seen=set()
    for index,item in enumerate(aliases):
        if not isinstance(item, Mapping):
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_ALIAS_OBJECT_REQUIRED:{index}")
        try:
            venue_id=int(item.get("venue_id"))
            source_venue_id=int(item.get("source_venue_id"))
        except (TypeError,ValueError) as exc:
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_ALIAS_VALUE_INVALID:{index}") from exc
        if venue_id in seen:
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_ALIAS_DUPLICATE:{venue_id}")
        seen.add(venue_id)
        if venue_id in out:
            raise SDVVenueSourceError(f"CFB_SDV_VENUE_ALIAS_OVERRIDE_FORBIDDEN:{venue_id}")
        source=out.get(source_venue_id)
        if not isinstance(source, Mapping):
            raise SDVVenueSourceError(
                f"CFB_SDV_VENUE_ALIAS_SOURCE_MISSING:{venue_id}:{source_venue_id}"
            )
        expected_name=str(item.get("expected_source_name") or "").strip()
        if expected_name and str(source.get("name") or "").strip() != expected_name:
            raise SDVVenueSourceError(
                f"CFB_SDV_VENUE_ALIAS_SOURCE_NAME_MISMATCH:{venue_id}:{source_venue_id}"
            )
        alias=dict(source)
        alias["venue_id"]=venue_id
        alias["name"]=str(item.get("name") or source.get("name") or "").strip() or None
        alias["alias_source_venue_id"]=source_venue_id
        alias["alias_policy"]="PINNED_PHYSICAL_VENUE_ID_REMAP"
        out[venue_id]=alias
    return out


def venue_source_attestation(raw: bytes, *, usable_rows: int) -> dict[str, Any]:
    return {
        "byte_count": len(raw),
        "sha256": sha256(raw).hexdigest(),
        "git_blob_sha1": git_blob_sha1(raw),
        "usable_rows": int(usable_rows),
    }


__all__ = [
    "REQUIRED_FIELDS",
    "SDVVenueSourceError",
    "git_blob_sha1",
    "parse_pinned_venues",
    "apply_pinned_venue_supplements",
    "apply_pinned_venue_aliases",
    "venue_source_attestation",
]
