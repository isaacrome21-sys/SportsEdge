from datetime import datetime, timezone
import unittest

from sportsedge.validation.temporal_evaluation_contract import (
    EvaluationRow,
    TemporalWindows,
    evaluation_identity,
    event_clusters,
    partition_untouched,
    require_disjoint_event_ids,
)


def ts(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


def row(event: str, day: int, p: float = 0.5, y: int = 1) -> EvaluationRow:
    return EvaluationRow(event, ts(day), p, y)


class TemporalEvaluationContractTests(unittest.TestCase):
    def setUp(self):
        self.windows = TemporalWindows(ts(2), ts(3), ts(4), ts(5))

    def test_chronological_partition_and_identity_are_deterministic(self):
        rows = [row("g5", 5), row("g1", 1), row("g3", 3)]
        parts = partition_untouched(rows, self.windows)
        require_disjoint_event_ids(parts)
        self.assertEqual([r.event_id for r in parts["train"]], ["g1"])
        self.assertEqual([r.event_id for r in parts["calibration"]], ["g3"])
        self.assertEqual([r.event_id for r in parts["test"]], ["g5"])
        self.assertEqual(evaluation_identity(parts), evaluation_identity(partition_untouched(reversed(rows), self.windows)))

    def test_rejects_overlapping_or_reordered_windows(self):
        bad = TemporalWindows(ts(3), ts(3), ts(4), ts(4))
        with self.assertRaisesRegex(ValueError, "TEMPORAL_WINDOW_OVERLAP_OR_REORDER"):
            bad.validate()

    def test_rejects_undeclared_gap_row(self):
        windows = TemporalWindows(ts(1), ts(3), ts(3), ts(5))
        with self.assertRaisesRegex(ValueError, "ROW_IN_UNDECLARED_TEMPORAL_GAP"):
            partition_untouched([row("train", 1), row("gap", 2), row("cal", 3), row("test", 5)], windows)

    def test_same_event_cannot_cross_partitions(self):
        parts = partition_untouched([row("same", 1), row("same", 3), row("test", 5)], self.windows)
        with self.assertRaisesRegex(ValueError, "EVENT_CROSSES_TEMPORAL_PARTITIONS:same"):
            require_disjoint_event_ids(parts)

    def test_event_clusters_keep_repeated_snapshots_together(self):
        clusters = event_clusters([row("b", 5), row("a", 5), row("b", 5, 0.6), row("a", 5, 0.4)])
        self.assertEqual(clusters, ((1, 3), (0, 2)))

    def test_invalid_probability_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "PROBABILITY_OUT_OF_RANGE"):
            event_clusters([row("g", 5, 1.1)])


if __name__ == "__main__":
    unittest.main()
