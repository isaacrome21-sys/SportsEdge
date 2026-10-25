"""Match phone quotes to a timezone-qualified event start."""
from datetime import datetime, timezone


def same_event_start(left, right):
    """Never lend a resolved event ID to a quote for another fixture."""
    def parse(row):
        value = row.get("kickoff") or row.get("commence_time")
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        return stamp.astimezone(timezone.utc)

    first, second = parse(left), parse(right)
    return first is not None and second is not None and first == second
