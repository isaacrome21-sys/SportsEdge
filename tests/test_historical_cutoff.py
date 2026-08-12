import unittest

from sportsedge.historical_cutoff import (
    HistoricalCutoffError,
    canonical_slate_date,
    process_prior_day_batches,
    stable_sha256,
)


def game(pk, official_date, *, utc="2026-08-12T06:30:00Z", status=None, **extra):
    out = {"gamePk": pk, "officialDate": official_date, "gameDate": utc, "status": status or {"abstractGameState": "Final", "detailedState": "Final"}}
    out.update(extra)
    return out


class HistoricalCutoffTests(unittest.TestCase):
    def test_official_date_is_canonical_not_utc_calendar_date(self):
        # 11:30 PM Pacific on Aug 11 is already Aug 12 UTC. The venue-scheduled
        # officialDate must keep this game in the Aug 11 historical batch.
        g = game(1, "2026-08-11", utc="2026-08-12T06:30:00Z")
        self.assertEqual(canonical_slate_date(g).isoformat(), "2026-08-11")

    def test_missing_official_date_fails_closed(self):
        with self.assertRaisesRegex(HistoricalCutoffError, "OFFICIAL_DATE_REQUIRED"):
            canonical_slate_date({"gamePk": 1, "gameDate": "2026-08-12T01:00:00Z"})

    def test_all_same_day_features_use_same_frozen_prior_day_state(self):
        games = [game(2, "2026-08-11"), game(1, "2026-08-11"), game(3, "2026-08-12")]
        initial = {"seen": []}

        def make_feature(state, g):
            # Mutate the copy deliberately. It must not leak to another same-day game.
            prior = tuple(state["seen"])
            state["seen"].append(g["gamePk"])
            return {"pk": g["gamePk"], "prior": prior}

        def apply_result(state, g):
            state["seen"].append(g["gamePk"])

        rows, state, excluded = process_prior_day_batches(
            games=games, initial_state=initial, make_feature=make_feature, apply_result=apply_result
        )
        self.assertEqual(excluded, [])
        by_pk = {g["gamePk"]: f for g, f in rows}
        self.assertEqual(by_pk[1]["prior"], ())
        self.assertEqual(by_pk[2]["prior"], ())
        self.assertEqual(by_pk[3]["prior"], (1, 2))
        self.assertEqual(state["seen"], [1, 2, 3])

    def test_doubleheader_game_one_result_absent_from_game_two_features(self):
        games = [game(1001, "2026-07-04"), game(1002, "2026-07-04")]

        def make_feature(state, g):
            return {"history_game_pks": list(state)}

        def apply_result(state, g):
            state.append(g["gamePk"])

        rows, _, _ = process_prior_day_batches(
            games=games, initial_state=[], make_feature=make_feature, apply_result=apply_result
        )
        by_pk = {g["gamePk"]: f for g, f in rows}
        self.assertNotIn(1001, by_pk[1002]["history_game_pks"])
        self.assertEqual(by_pk[1001]["history_game_pks"], by_pk[1002]["history_game_pks"])

    def test_suspended_and_resumed_games_are_excluded_from_features_and_state(self):
        games = [
            game(1, "2026-06-01"),
            game(2, "2026-06-02", status={"abstractGameState": "Live", "detailedState": "Suspended"}),
            game(3, "2026-06-03", resumeDate="2026-06-03T18:00:00Z"),
            game(4, "2026-06-04"),
        ]

        def make_feature(state, g):
            return list(state)

        def apply_result(state, g):
            state.append(g["gamePk"])

        rows, state, excluded = process_prior_day_batches(
            games=games, initial_state=[], make_feature=make_feature, apply_result=apply_result
        )
        self.assertEqual([g["gamePk"] for g, _ in rows], [1, 4])
        self.assertEqual(state, [1, 4])
        self.assertEqual([(x.game_pk, x.reason_code) for x in excluded], [
            (2, "SUSPENDED_GAME_EXCLUDED"),
            (3, "RESUMED_GAME_EXCLUDED"),
        ])

    def test_entire_pipeline_is_idempotent_and_order_independent(self):
        games_a = [game(2, "2026-08-11"), game(1, "2026-08-11"), game(3, "2026-08-12")]
        games_b = list(reversed(games_a))

        def run(games):
            def make_feature(state, g):
                return {"pk": g["gamePk"], "prior": list(state)}
            def apply_result(state, g):
                state.append(g["gamePk"])
            rows, state, excluded = process_prior_day_batches(
                games=games, initial_state=[], make_feature=make_feature, apply_result=apply_result
            )
            payload = {
                "rows": [{"gamePk": g["gamePk"], "feature": f} for g, f in rows],
                "state": state,
                "excluded": [x.__dict__ for x in excluded],
            }
            return payload

        first = run(games_a)
        second = run(games_b)
        self.assertEqual(first, second)
        self.assertEqual(stable_sha256(first), stable_sha256(second))


if __name__ == "__main__":
    unittest.main()
