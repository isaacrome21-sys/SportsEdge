from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from urllib.request import Request, urlopen


def public_json(url: str, *, user_agent: str = "SportsEdge-DFS/1.0", timeout: int = 15) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json,text/plain,*/*"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - intentional public HTTPS source
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("DFS_PUBLIC_JSON_SHAPE_INVALID")
    return payload


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def normalize_team(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())
