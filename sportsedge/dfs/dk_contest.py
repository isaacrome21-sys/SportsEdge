from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from .contest import ContestStructure
from .draftkings import DraftKingsError, _http_json

CONTEST_DETAIL_URL = "https://api.draftkings.com/contests/v1/contests/{contest_id}?format=json"


@dataclass(frozen=True)
class DKContestDetail:
    contest_id: int
    name: str
    entries: int | None
    maximum_entries: int
    maximum_entries_per_user: int | None
    entry_fee: float
    total_payouts: float | None
    is_guaranteed: bool | None
    start_time: str
    structure: ContestStructure
    raw: dict[str, Any]

    @property
    def is_single_entry(self) -> bool:
        return self.maximum_entries_per_user == 1


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cash(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_contest_detail(contest_id: int, payload: dict[str, Any]) -> DKContestDetail:
    detail = payload.get("contestDetail") or payload.get("ContestDetail")
    if not isinstance(detail, dict):
        raise DraftKingsError("DK_CONTEST_DETAIL_SHAPE_INVALID")
    maximum_entries = _int(detail.get("maximumEntries"))
    entries = _int(detail.get("entries"))
    field_size = maximum_entries or entries
    if field_size is None or field_size < 2:
        raise DraftKingsError("DK_CONTEST_FIELD_SIZE_INVALID")
    entry_fee = _float(detail.get("entryFee"))
    if entry_fee is None or entry_fee < 0:
        raise DraftKingsError("DK_CONTEST_ENTRY_FEE_INVALID")

    tiers = detail.get("payoutSummary") or []
    if not isinstance(tiers, list) or not tiers:
        raise DraftKingsError("DK_CONTEST_PAYOUT_SUMMARY_MISSING")
    payout_by_rank: dict[int, float] = {}
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        low = _int(tier.get("minPosition"))
        high = _int(tier.get("maxPosition"))
        descriptions = tier.get("tierPayoutDescriptions")
        amount = None
        if isinstance(descriptions, dict):
            amount = _cash(descriptions.get("Cash"))
            if amount is None:
                for value in descriptions.values():
                    amount = _cash(value)
                    if amount is not None:
                        break
        if amount is None:
            amount = _cash(tier.get("payout") or tier.get("amount"))
        if low is None or high is None or low < 1 or high < low or amount is None or amount < 0:
            raise DraftKingsError("DK_CONTEST_PAYOUT_TIER_INVALID")
        if high > field_size:
            raise DraftKingsError("DK_CONTEST_PAYOUT_TIER_EXCEEDS_FIELD")
        for rank in range(low, high + 1):
            if rank in payout_by_rank:
                raise DraftKingsError("DK_CONTEST_PAYOUT_TIER_OVERLAP")
            payout_by_rank[rank] = amount
    last_paid = max(payout_by_rank, default=0)
    if last_paid == 0:
        raise DraftKingsError("DK_CONTEST_PAYOUTS_EMPTY")
    payouts = tuple(payout_by_rank.get(rank, 0.0) for rank in range(1, last_paid + 1))
    structure = ContestStructure(
        field_size=field_size,
        entry_fee=entry_fee,
        payouts=payouts,
        name=str(detail.get("name") or ""),
        version="DK_CONTEST_DETAIL_V1",
    )
    structure.validate()
    total = _float(detail.get("totalPayouts"))
    computed_total = sum(payouts)
    if total is not None and total > 0:
        tolerance = max(1.0, total * 0.002)
        if abs(computed_total - total) > tolerance:
            raise DraftKingsError(
                f"DK_CONTEST_PAYOUT_TOTAL_MISMATCH:{computed_total:.2f}:{total:.2f}"
            )
    guaranteed = detail.get("isGuaranteed")
    return DKContestDetail(
        contest_id=int(contest_id),
        name=str(detail.get("name") or ""),
        entries=entries,
        maximum_entries=field_size,
        maximum_entries_per_user=_int(detail.get("maximumEntriesPerUser")),
        entry_fee=entry_fee,
        total_payouts=total,
        is_guaranteed=bool(guaranteed) if guaranteed is not None else None,
        start_time=str(detail.get("contestStartTime") or ""),
        structure=structure,
        raw=detail,
    )


class DraftKingsContestClient:
    def __init__(self, getter: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._getter = getter or _http_json

    def fetch(self, contest_id: int) -> DKContestDetail:
        payload = self._getter(CONTEST_DETAIL_URL.format(contest_id=int(contest_id)))
        return parse_contest_detail(int(contest_id), payload)

    def find_single_entry(
        self,
        *,
        draft_group_id: int,
        lobby_payload: dict[str, Any],
        lookup_limit: int = 18,
    ) -> DKContestDetail:
        contests = lobby_payload.get("Contests") or lobby_payload.get("contests") or []
        candidates: list[tuple[float, int, str]] = []
        for row in contests if isinstance(contests, list) else []:
            if not isinstance(row, dict):
                continue
            group = row.get("dg") or row.get("draftGroupId") or row.get("DraftGroupId")
            try:
                group_i = int(group)
            except (TypeError, ValueError):
                continue
            if group_i != int(draft_group_id):
                continue
            cid = row.get("id") or row.get("contestId") or row.get("ContestId")
            try:
                cid_i = int(cid)
            except (TypeError, ValueError):
                continue
            payout = _float(row.get("po") or row.get("totalPayouts") or row.get("TotalPayouts")) or 0.0
            name = str(row.get("n") or row.get("name") or row.get("Name") or "")
            candidates.append((payout, cid_i, name))
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if not candidates:
            raise DraftKingsError(f"DK_NO_CONTESTS_FOR_DRAFT_GROUP:{draft_group_id}")

        errors: list[str] = []
        for _, contest_id, _ in candidates[:lookup_limit]:
            try:
                detail = self.fetch(contest_id)
            except Exception as exc:
                errors.append(f"{contest_id}:{type(exc).__name__}")
                continue
            if detail.is_single_entry:
                return detail
        suffix = ",".join(errors[:5])
        raise DraftKingsError(
            f"DK_SINGLE_ENTRY_CONTEST_NOT_FOUND:{draft_group_id}"
            + (f":DETAIL_ERRORS={suffix}" if suffix else "")
        )
