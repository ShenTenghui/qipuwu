"""Behavior checks using fictional IDs and synthetic timing/results only.

Core selection cases adapt ideas from the original test_training_schedule_v7.py.
No original project is imported, read, started or contacted by this test suite.
"""
from collections import Counter
from copy import deepcopy
import unittest

from app import training_schedule_v7 as schedule
from app.training_schedule_v6 import _separate_games
from examples.schedule_demo import NOW, make_candidates, priority_examples, run_demo


class ScheduleTests(unittest.TestCase):
    def test_balanced_supply_selects_six_new_four_review(self):
        result = run_demo()
        self.assertEqual((result["summary"]["new"], result["summary"]["review"]), (6, 4))
        self.assertEqual(len({item["id"] for item in result["selected"]}), 10)

    def test_same_inputs_seed_and_reversed_unique_rows_replay_exactly(self):
        rows = make_candidates(20, 20, 12)
        first = schedule.select(rows, seed="replay-check", now=NOW)
        self.assertEqual(first, schedule.select(rows, seed="replay-check", now=NOW))
        self.assertEqual(first, schedule.select(list(reversed(rows)), seed="replay-check", now=NOW))

    def test_inputs_and_nested_outcomes_are_not_mutated(self):
        rows = make_candidates()
        before = deepcopy(rows)
        selected = schedule.select(rows, seed="immutable", now=NOW)
        self.assertEqual(rows, before)
        selected[0]["practice_learning"]["outcomes"].append("blunder")
        self.assertEqual(rows, before)

    def test_shortages_borrow_in_both_directions(self):
        for new, old, expected in ((2, 20, (2, 8)), (20, 2, (8, 2)),
                                   (0, 20, (0, 10)), (20, 0, (10, 0)),
                                   (3, 4, (3, 4)), (0, 0, (0, 0))):
            with self.subTest(new=new, old=old):
                result = run_demo(new, old, 4)
                self.assertEqual((result["summary"]["new"], result["summary"]["review"]), expected)

    def test_invalid_rows_and_duplicate_ids_do_not_fill_batch(self):
        valid = make_candidates(1, 0, 1)[0]
        rows = [valid, deepcopy(valid), None, "not-a-row", {},
                dict(valid, id="", pool="N"), dict(valid, id="bad-pool", pool="pending"),
                dict(valid, id="no-source", source_key=None)]
        selected = schedule.select(rows, now=NOW)
        self.assertEqual([item["id"] for item in selected], [valid["id"]])

    def test_future_due_date_does_not_hard_block_reliable_review(self):
        rows = make_candidates(0, 12, 12)
        for row in rows:
            row["next_due"] = NOW + 30 * schedule.DAY
        self.assertEqual(len(schedule.select(rows, now=NOW)), 10)

    def test_oldest_waiting_opportunity_is_preserved_in_each_pool(self):
        rows = make_candidates(20, 20, 20)
        rows[10]["ticket"] = rows[30]["ticket"] = NOW - 200 * schedule.DAY
        selected = schedule.select(rows, seed="coverage", now=NOW)
        ids = {item["id"] for item in selected}
        self.assertTrue({rows[10]["id"], rows[30]["id"]} <= ids)

    def test_weight_changes_for_waiting_and_failure_not_guaranteed_selection(self):
        recent_pass, old_pass, recent_fail, old_fail = priority_examples()
        self.assertGreater(old_pass["weight"], recent_pass["weight"])
        self.assertGreater(recent_fail["weight"], recent_pass["weight"])
        self.assertGreater(old_fail["weight"], old_pass["weight"])

    def test_source_diversity_when_distinct_supply_is_available(self):
        selected = schedule.select(make_candidates(0, 20, 20), now=NOW)
        self.assertEqual(len({item["source_key"] for item in selected}), 10)

    def test_one_source_still_fills_batch(self):
        result = run_demo(12, 12, 1)
        self.assertEqual(result["summary"]["selected"], 10)
        self.assertEqual(result["summary"]["unique_sources"], 1)
        self.assertEqual(result["summary"]["same_source_neighbors"], 9)

    def test_reordering_separates_sources_preserves_members_and_internal_order(self):
        rows = [dict(id=f"{source}{i}", source_key=source, pool="N")
                for source, count in (("A", 5), ("B", 3), ("C", 2)) for i in range(count)]
        ordered = _separate_games(rows)
        self.assertEqual(Counter(row["id"] for row in ordered), Counter(row["id"] for row in rows))
        self.assertFalse(any(a["source_key"] == b["source_key"] for a, b in zip(ordered, ordered[1:])))
        for source in ("A", "B", "C"):
            self.assertEqual([row["id"] for row in ordered if row["source_key"] == source],
                             [row["id"] for row in rows if row["source_key"] == source])

    def test_batch_size_is_bounded(self):
        rows = make_candidates(20, 20, 10)
        self.assertEqual(len(schedule.select(rows, limit=500, now=NOW)), 10)
        self.assertEqual(schedule.select(rows, limit=0, now=NOW), [])
        self.assertEqual(schedule.select(rows, limit=-10, now=NOW), [])

    def test_example_validation_rejects_unbounded_or_ambiguous_inputs(self):
        for args in ((101, 12, 8), (12, -1, 8), (12, 12, 0), (True, 12, 8)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                run_demo(*args)


if __name__ == "__main__":
    unittest.main()
