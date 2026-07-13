#!/usr/bin/env python3
import unittest

from learning_weekly import apply_lifecycle, build_active_rules, build_report


class LearningWeeklyTests(unittest.TestCase):
    def test_report_contains_only_week_changes_and_not_all_confirmed_rules(self):
        evidence = {"rules": {
            "old": {"id": "old", "title": "旧规则", "status": "confirmed", "last_seen": "2026-05-01"},
            "new": {
                "id": "new", "title": "本周确认", "status": "confirmed", "last_seen": "2026-07-10",
                "feedback": [{"created_at": "2026-07-10T12:00:00+08:00", "classified_as": "confirmed"}],
            },
        }}
        report = build_report(evidence, "2026-07-12")
        self.assertEqual([item["id"] for item in report["confirmed_changes"]], ["new"])
        self.assertEqual(build_active_rules(evidence)["count"], 2)

    def test_dictionary_candidates_are_routed_out_of_style_decisions(self):
        evidence = {"rules": {"dict": {
            "id": "dict", "title": "词库候选", "type": "dictionary_candidate",
            "status": "ready_for_review", "last_seen": "2026-07-10", "days": ["2026-07-10"],
        }}}
        report = build_report(evidence, "2026-07-12")
        self.assertEqual(report["decisions"], [])
        self.assertEqual(len(report["dictionary_candidates"]), 1)

    def test_stale_observation_is_archived_without_deleting_evidence(self):
        evidence = {"rules": {"stale": {
            "id": "stale", "title": "旧观察", "status": "pending", "last_seen": "2026-05-28",
            "examples": [{"before": "a", "after": "b"}],
        }}}
        archived = apply_lifecycle(evidence, "2026-07-12")
        self.assertEqual(len(archived), 1)
        self.assertEqual(evidence["rules"]["stale"]["status"], "archived_stale")
        self.assertEqual(evidence["rules"]["stale"]["previous_status"], "pending")
        self.assertEqual(len(evidence["rules"]["stale"]["examples"]), 1)


if __name__ == "__main__":
    unittest.main()
