#!/usr/bin/env python3
"""Recover a fixed allowlist of missing 2025 DK MLB openers from ATS.io.

This lane is acquisition-only. It fetches and retains exact source HTML, verifies
identity from a fixed allowlist, parses only the MoneyLine/Open/DraftKings row,
and emits source hashes. It never reads game outcomes, SportsEdge model output,
or any 2025 evaluation artifact.

Only games whose exact DraftKings opening pair was independently identified are
allowed here. Consensus, current odds, another sportsbook, or nearby games are
not accepted substitutes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import time
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/140 Safari/537.36"
)
AMERICAN_RE = re.compile(r"(?<![\w$])([+-]\d{3,5})(?!\w)")


@dataclass(frozen=True)
class Target:
    game_pk: int
    date: str
    away: str
    home: str
    away_abbr: str
    home_abbr: str
    url: str
    expected_open: tuple[int, int]


TARGETS = (
    Target(
        777861,
        "2025-05-21",
        "Cleveland Guardians",
        "Minnesota Twins",
        "CLE",
        "MIN",
        "https://ats.io/mlb/cleveland-guardians-vs-minnesota-twins-pick-5-21-2025/387574/",
        (110, -130),
    ),
    Target(
        778247,
        "2025-04-19",
        "Washington Nationals",
        "Colorado Rockies",
        "WSH",
        "COL",
        "https://ats.io/mlb/washington-nationals-vs-colorado-rockies-pick-4-19-2025/352799/",
        (-130, 110),
    ),
    Target(
        778552,
        "2025-03-27",
        "Chicago Cubs",
        "Arizona Diamondbacks",
        "CHC",
        "ARI",
        "https://ats.io/mlb/chicago-cubs-vs-arizona-diamondbacks-pick-3-27-2025/316720/",
        (110, -130),
    ),
)


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(html.unescape(data).split())
        if value:
            self.parts.append(value)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_bytes(url: str, retries: int = 5) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            with urllib.request.urlopen(request, timeout=35) as response:
                data = response.read()
            if data:
                return data
        except Exception as exc:  # pragma: no cover - hosted network lane
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"SECONDARY_FETCH_FAILED:{url}:{last!r}")


def visible_text(raw_html: bytes) -> str:
    parser = TextExtractor()
    parser.feed(raw_html.decode("utf-8", errors="replace"))
    return "\n".join(parser.parts)


def parse_moneyline_open(text: str, target: Target) -> tuple[int, int]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    low = normalized.lower()

    identity_terms = (
        target.away.lower(),
        target.home.lower(),
        target.date.replace("-", "/"),
    )
    # Date formatting varies by title, so teams are the mandatory identity check.
    if identity_terms[0] not in low or identity_terms[1] not in low:
        raise ValueError(f"SECONDARY_EVENT_IDENTITY_MISMATCH:{target.game_pk}")

    money_idx = low.find("moneyline")
    if money_idx < 0:
        raise ValueError(f"SECONDARY_MONEYLINE_SECTION_MISSING:{target.game_pk}")
    tail = normalized[money_idx:]
    tail_low = tail.lower()
    next_section_candidates = [
        idx for token in ("runline", "run line", "over/under", "over under")
        if (idx := tail_low.find(token, 10)) > 0
    ]
    if next_section_candidates:
        tail = tail[: min(next_section_candidates)]
        tail_low = tail.lower()

    dk_idx = tail_low.find("draftkings")
    if dk_idx < 0:
        raise ValueError(f"SECONDARY_DRAFTKINGS_ROW_MISSING:{target.game_pk}")
    dk_tail = tail[dk_idx:]
    odds = [int(match.group(1)) for match in AMERICAN_RE.finditer(dk_tail)]
    if len(odds) < 2:
        raise ValueError(f"SECONDARY_DRAFTKINGS_OPEN_PAIR_MISSING:{target.game_pk}")

    parsed = (odds[0], odds[1])
    if parsed != target.expected_open:
        raise ValueError(
            f"SECONDARY_DRAFTKINGS_OPEN_REGRESSION:{target.game_pk}:"
            f"{parsed}!={target.expected_open}"
        )
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", required=True)
    args = parser.parse_args()
    outdir = Path(args.outdir)
    raw_dir = outdir / "raw_html"
    raw_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    source_manifest: list[dict[str, Any]] = []
    for target in TARGETS:
        raw = fetch_bytes(target.url)
        raw_path = raw_dir / f"ats_{target.game_pk}.html"
        raw_path.write_bytes(raw)
        text = visible_text(raw)
        away_open, home_open = parse_moneyline_open(text, target)
        raw_sha = sha256_bytes(raw)
        rows.append(
            {
                "gamePk": target.game_pk,
                "date": target.date,
                "away": target.away,
                "home": target.home,
                "awayML_open_DK": away_open,
                "homeML_open_DK": home_open,
                "source": "ATS.io historical odds table",
                "source_url": target.url,
                "source_sha256": raw_sha,
                "binding_mode": "SECONDARY_EXACT_DRAFTKINGS_OPEN",
            }
        )
        source_manifest.append(
            {
                "gamePk": target.game_pk,
                "url": target.url,
                "sha256": raw_sha,
                "bytes": len(raw),
                "parsed_draftkings_open": [away_open, home_open],
            }
        )
        print(
            f"SECONDARY_DK_OPEN_RECOVERED:{target.game_pk}:"
            f"{away_open}:{home_open}:{raw_sha}"
        )

    csv_path = outdir / "secondary_dk_openers_2025.csv"
    fields = [
        "gamePk",
        "date",
        "away",
        "home",
        "awayML_open_DK",
        "homeML_open_DK",
        "source",
        "source_url",
        "source_sha256",
        "binding_mode",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "schema_version": 1,
        "purpose": "EXACT_SECONDARY_DRAFTKINGS_OPENING_RECOVERY_ONLY",
        "target_count": len(TARGETS),
        "recovered_count": len(rows),
        "no_outcomes_read": True,
        "no_model_outputs_read": True,
        "no_consensus_or_other_book_substitution": True,
        "sources": source_manifest,
        "output_csv_sha256": sha256_bytes(csv_path.read_bytes()),
    }
    (outdir / "secondary_source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
