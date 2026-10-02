#!/usr/bin/env python3
"""Audit official NFL 2025 REG gamebooks for explicit inactive-list evidence.

Source-only: discovers official gameBookUrl values from api.nfl.com's anonymous
web-client feed, downloads the PDFs, hashes exact bytes, and checks extracted
text for explicit INACTIVE sections. It never loads outcomes or model code.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import uuid

from pypdf import PdfReader
import requests

API_HOST = "https://api.nfl.com"
CLIENT_KEY = "4cFUW6DmwJpzT9L7LrG3qRAcABG5s04g"
CLIENT_SECRET = "CZuvCL49d9OwfGsR"
DEVICE_INFO = (
    "eyJtb2RlbCI6ImRlc2t0b3AiLCJvc05hbWUiOiJXaW5kb3dzIiwib3NWZXJzaW9uIjoiMTAiLCJ2ZXJzaW9uIjoiQ2hyb21lIn0="
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
INACTIVE_RE = re.compile(r"\bINACTIVE(?:S)?\b", re.IGNORECASE)


class GamebookAuditError(ValueError):
    pass


def _token() -> str:
    response = requests.post(
        API_HOST + "/identity/v3/token",
        data={
            "clientKey": CLIENT_KEY,
            "clientSecret": CLIENT_SECRET,
            "deviceId": str(uuid.uuid4()),
            "deviceInfo": DEVICE_INFO,
            "networkType": "other",
        },
        headers={"User-Agent": UA, "X-Domain-Id": "100"},
        timeout=30,
    )
    response.raise_for_status()
    token = str(response.json().get("accessToken") or "").strip()
    if not token:
        raise GamebookAuditError("NFL_ANON_TOKEN_MISSING")
    return token


def _headers(token: str) -> dict[str, str]:
    return {
        "User-Agent": UA,
        "Accept": "application/json",
        "Referer": "https://www.nfl.com/",
        "Origin": "https://www.nfl.com",
        "Authorization": f"Bearer {token}",
        "X-Domain-Id": "100",
    }


def _weekly_details(token: str, week: int) -> tuple[bytes, list[dict]]:
    url = API_HOST + "/football/v2/experience/weekly-game-details"
    response = requests.get(
        url,
        params={
            "season": 2025,
            "type": "REG",
            "week": int(week),
            "includeDriveChart": "false",
            "includeReplays": "false",
            "includeStandings": "false",
            "includeTaggedVideos": "false",
        },
        headers=_headers(token),
        timeout=30,
    )
    response.raise_for_status()
    raw = response.content
    body = response.json()
    if not isinstance(body, list):
        raise GamebookAuditError(f"NFL_WEEK_DETAILS_NOT_LIST:{week}")
    return raw, body


def _game_identity(row: dict, week: int) -> dict[str, object]:
    home = row.get("homeTeam") or {}
    away = row.get("awayTeam") or {}
    summary = row.get("summary") or {}
    return {
        "week": int(week),
        "game_id": str(row.get("id") or summary.get("gameId") or ""),
        "date": row.get("date"),
        "kickoff": row.get("time") or summary.get("startTime"),
        "home": home.get("abbreviation") or home.get("fullName"),
        "away": away.get("abbreviation") or away.get("fullName"),
        "status": row.get("status"),
        "gamebook_url": summary.get("gameBookUrl"),
    }


def _download_pdf(url: str) -> tuple[bytes, str]:
    response = requests.get(
        url,
        headers={"User-Agent": UA, "Accept": "application/pdf"},
        timeout=60,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise GamebookAuditError("GAMEBOOK_NOT_PDF")
    return raw, sha256(raw).hexdigest()


def _extract_inactive_evidence(raw: bytes, temp: Path) -> dict[str, object]:
    path = temp / "gamebook.pdf"
    path.write_bytes(raw)
    reader = PdfReader(str(path))
    pages_with_not_active: list[int] = []
    contexts: list[str] = []
    total_matches = 0
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        matches = list(INACTIVE_RE.finditer(text))
        if not matches:
            continue
        pages_with_not_active.append(index + 1)
        total_matches += len(matches)
        for match in matches[:3]:
            start = max(0, match.start() - 160)
            end = min(len(text), match.end() + 400)
            context = " ".join(text[start:end].split())
            if context and context not in contexts:
                contexts.append(context[:700])
        if len(contexts) >= 6:
            break
    return {
        "page_count": len(reader.pages),
        "not_active_token_count": int(total_matches),
        "pages_with_not_active": pages_with_not_active,
        "sample_contexts": contexts[:6],
        "explicit_not_active_section": bool(total_matches),
    }


def run(out_path: Path) -> dict[str, object]:
    token = _token()
    weekly_receipts = []
    games: list[dict[str, object]] = []
    for week in range(1, 19):
        raw, rows = _weekly_details(token, week)
        weekly_receipts.append(
            {
                "week": week,
                "bytes": len(raw),
                "sha256": sha256(raw).hexdigest(),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "rows": len(rows),
            }
        )
        games.extend(_game_identity(row, week) for row in rows)

    if not games:
        raise GamebookAuditError("NFL_2025_REG_GAMES_EMPTY")
    unique_ids = {str(g["game_id"]) for g in games}
    if len(unique_ids) != len(games):
        raise GamebookAuditError("NFL_GAME_ID_DUPLICATE")

    with __import__("tempfile").TemporaryDirectory(prefix="sportsedge-gamebook-audit-") as tmp:
        temp = Path(tmp)
        audits = []
        for game in games:
            url = str(game.get("gamebook_url") or "").strip()
            entry = dict(game)
            if not url:
                entry.update(
                    {
                        "status_code": "MISSING_GAMEBOOK_URL",
                        "pdf_sha256": None,
                        "pdf_bytes": 0,
                        "explicit_not_active_section": False,
                        "not_active_token_count": 0,
                        "pages_with_not_active": [],
                        "sample_contexts": [],
                    }
                )
                audits.append(entry)
                continue
            try:
                raw, digest = _download_pdf(url)
                evidence = _extract_inactive_evidence(raw, temp)
                entry.update(
                    {
                        "status_code": "OK",
                        "pdf_sha256": digest,
                        "pdf_bytes": len(raw),
                        **evidence,
                    }
                )
            except Exception as exc:
                entry.update(
                    {
                        "status_code": f"ERROR:{type(exc).__name__}",
                        "error": str(exc),
                        "pdf_sha256": None,
                        "pdf_bytes": 0,
                        "explicit_not_active_section": False,
                        "not_active_token_count": 0,
                        "pages_with_not_active": [],
                        "sample_contexts": [],
                    }
                )
            audits.append(entry)

    available = [g for g in audits if g["status_code"] == "OK"]
    explicit = [g for g in available if g["explicit_not_active_section"]]
    report = {
        "schema": "SPORTSEDGE_NFL_2025_GAMEBOOK_INACTIVE_AUDIT_V1",
        "status": "SOURCE_AUDIT_ONLY_NO_PROP_SCORING",
        "season": 2025,
        "season_type": "REG",
        "weeks": list(range(1, 19)),
        "weekly_detail_receipts": weekly_receipts,
        "n_games": len(audits),
        "n_gamebook_urls": sum(bool(g.get("gamebook_url")) for g in audits),
        "n_gamebooks_downloaded": len(available),
        "n_explicit_not_active_sections": len(explicit),
        "coverage_fraction": (len(explicit) / len(audits)) if audits else 0.0,
        "all_games_have_explicit_not_active_section": bool(audits)
        and len(explicit) == len(audits),
        "games": audits,
        "interpretation": {
            "official_nfl_gamebook": True,
            "list_is_pregame_fact_recorded_in_final_gamebook": True,
            "retrieval_is_historical_not_forward_capture": True,
            "may_be_used_only_as_research_validation_eligibility_ground_truth": True,
            "may_not_claim_forward_timestamped_inactive_capture": True,
        },
        "authority": {
            "source_audit_only": True,
            "model_scoring": False,
            "validation_window_spent": False,
            "model_p": False,
            "promotion": False,
            "official": False,
            "staking": False,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        "NFL_2025_GAMEBOOK_INACTIVE_AUDIT="
        + json.dumps(
            {
                "n_games": report["n_games"],
                "n_gamebook_urls": report["n_gamebook_urls"],
                "n_gamebooks_downloaded": report["n_gamebooks_downloaded"],
                "n_explicit_not_active_sections": report["n_explicit_not_active_sections"],
                "coverage_fraction": report["coverage_fraction"],
                "all_games_have_explicit_not_active_section": report[
                    "all_games_have_explicit_not_active_section"
                ],
                "failures": [
                    {
                        "week": g["week"],
                        "away": g["away"],
                        "home": g["home"],
                        "status_code": g["status_code"],
                    }
                    for g in audits
                    if not g["explicit_not_active_section"]
                ][:30],
                "sample_contexts": [
                    {
                        "week": g["week"],
                        "away": g["away"],
                        "home": g["home"],
                        "contexts": g["sample_contexts"][:2],
                    }
                    for g in explicit[:3]
                ],
            },
            sort_keys=True,
        )
    )
    return report


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="artifacts/nfl_prop_v1_source_audit/gamebook_inactive_audit.json",
    )
    args = parser.parse_args()
    run(Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
