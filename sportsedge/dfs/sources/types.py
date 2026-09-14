from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any


@dataclass(frozen=True)
class PlayerAvailability:
    name: str
    team: str
    status: str
    source: str
    updated_at: datetime
    detail: str = ""
    player_id: str = ""

    @property
    def unavailable(self) -> bool:
        text = f"{self.status} {self.detail}".casefold()
        if any(phrase in text for phrase in ("injured reserve", "reserve/injured", "physically unable to perform")):
            return True
        return bool(re.search(r"\b(out|inactive|suspended|ir)\b", text))


@dataclass(frozen=True)
class DfsContextEvidence:
    sport: str
    source: str
    retrieved_at: datetime
    games: tuple[dict[str, Any], ...] = ()
    availability: tuple[PlayerAvailability, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def diagnostic_summary(self) -> dict[str, Any]:
        return {
            "sport": self.sport,
            "source": self.source,
            "retrieved_at": self.retrieved_at.isoformat(),
            "game_count": len(self.games),
            "availability_count": len(self.availability),
            **self.metadata,
        }
