import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import HabitDB


class TestWeeklyReset(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "habit.db")
        self.json_path = os.path.join(self.tmp_dir.name, "data.json")
        initial_data = {
            "score": 520,
            "princessId": "elsa",
            "soundEnabled": True,
            "weekWritingCount": 3,
            "weekJumpCount": 2,
            "hasClaimedWeeklyWriting": False,
            "hasClaimedWeeklyJump": True,
            "todayEarned": 40,
            "lastCheckDate": "Wed Nov 25 2026",
            "history": [{"pts": 40, "reason": "练字", "time": "11/25 18:00"}],
            "prizes": [],
            "customReasons": [],
            "customDeductReasons": [],
        }
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, ensure_ascii=False)
        self.db = HabitDB(self.db_path, self.json_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_period_calculation_boundaries(self):
        sunday_night = datetime(2026, 11, 29, 23, 59, 59)
        monday_before_1am = datetime(2026, 11, 30, 0, 59, 59)
        monday_at_1am = datetime(2026, 11, 30, 1, 0, 0)
        monday_after_1am = datetime(2026, 11, 30, 8, 30, 0)

        p_sun = HabitDB.get_current_reset_period(sunday_night)
        p_mon_0 = HabitDB.get_current_reset_period(monday_before_1am)
        p_mon_1 = HabitDB.get_current_reset_period(monday_at_1am)
        p_mon_8 = HabitDB.get_current_reset_period(monday_after_1am)

        self.assertEqual(p_sun, p_mon_0)
        self.assertNotEqual(p_mon_0, p_mon_1)
        self.assertEqual(p_mon_1, p_mon_8)

    def test_first_deployment_midweek_preserves_counts(self):
        wednesday = datetime(2026, 11, 25, 18, 0, 0)
        did_reset = self.db.check_and_perform_weekly_reset(now=wednesday)
        self.assertFalse(did_reset)
        state = self.db.get_state()
        self.assertEqual(state["weekWritingCount"], 3)
        self.assertEqual(state["weekJumpCount"], 2)
        self.assertTrue(state["hasClaimedWeeklyJump"])
        self.assertEqual(state["score"], 520)

    def test_no_reset_before_monday_1am(self):
        wednesday = datetime(2026, 11, 25, 18, 0, 0)
        self.db.check_and_perform_weekly_reset(now=wednesday)

        monday_00_59 = datetime(2026, 11, 30, 0, 59, 59)
        did_reset = self.db.check_and_perform_weekly_reset(now=monday_00_59)
        self.assertFalse(did_reset)
        state = self.db.get_state()
        self.assertEqual(state["weekWritingCount"], 3)
        self.assertEqual(state["weekJumpCount"], 2)

    def test_resets_at_monday_1am_and_syncs_json(self):
        wednesday = datetime(2026, 11, 25, 18, 0, 0)
        self.db.check_and_perform_weekly_reset(now=wednesday)

        monday_01_00 = datetime(2026, 11, 30, 1, 0, 0)
        did_reset = self.db.check_and_perform_weekly_reset(now=monday_01_00)
        self.assertTrue(did_reset)

        state = self.db.get_state()
        self.assertEqual(state["weekWritingCount"], 0)
        self.assertEqual(state["weekJumpCount"], 0)
        self.assertFalse(state["hasClaimedWeeklyWriting"])
        self.assertFalse(state["hasClaimedWeeklyJump"])
        self.assertEqual(state["score"], 520)
        self.assertEqual(len(state["history"]), 1)

        with open(self.json_path, "r", encoding="utf-8") as f:
            json_state = json.load(f)
        self.assertEqual(json_state["weekWritingCount"], 0)
        self.assertEqual(json_state["weekJumpCount"], 0)
        self.assertFalse(json_state["hasClaimedWeeklyJump"])

    def test_idempotent_after_reset_and_save_state(self):
        wednesday = datetime(2026, 11, 25, 18, 0, 0)
        self.db.check_and_perform_weekly_reset(now=wednesday)

        monday_01_00 = datetime(2026, 11, 30, 1, 0, 0)
        self.assertTrue(self.db.check_and_perform_weekly_reset(now=monday_01_00))

        state = self.db.get_state()
        state["weekWritingCount"] = 1
        self.assertTrue(self.db.save_state(state))

        monday_08_00 = datetime(2026, 11, 30, 8, 0, 0)
        self.assertFalse(self.db.check_and_perform_weekly_reset(now=monday_08_00))
        self.assertEqual(self.db.get_state()["weekWritingCount"], 1)


if __name__ == "__main__":
    unittest.main()
