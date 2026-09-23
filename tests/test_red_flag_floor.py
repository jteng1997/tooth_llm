"""Unit tests for rules.red_flag_floor() — the deterministic floor under LLM triage.

    .venv/Scripts/python -m unittest discover -s tests -v

No GPU, no Ollama. The floor may only ever raise urgency; that property is
tested where the floor is composed with the LLM level (test_triage.py).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "llm"))

import rules  # noqa: E402

# decisions.md 2026-09-22: the user's four, plus the four added in the
# "Phase 1–2 plan decisions" entry (#3).
EXPECTED_FLAGS = {
    "swelling", "fever", "difficulty_swallowing_or_breathing", "recent_trauma",
    "bleeding_uncontrolled", "chest_pain_or_breathless",
    "exceeded_pain_relief_dose", "systemically_unwell",
}


class RedFlagFloor(unittest.TestCase):
    def test_flag_list_matches_the_decision_log(self):
        self.assertEqual(set(rules.RED_FLAG_FIELDS), EXPECTED_FLAGS)

    def test_each_flag_alone_forces_emergency(self):
        for flag in rules.RED_FLAG_FIELDS:
            with self.subTest(flag=flag):
                floor = rules.red_flag_floor({flag: True})
                self.assertEqual(floor, {"level": "EMERGENCY", "red_flags": [flag]})

    def test_all_flags_are_reported(self):
        floor = rules.red_flag_floor({"swelling": True, "fever": True, "pain_present": True})
        self.assertEqual(floor["level"], "EMERGENCY")
        self.assertEqual(sorted(floor["red_flags"]), ["fever", "swelling"])

    def test_unanswered_is_not_a_red_flag(self):
        # null means "not answered"; the floor must never guess one.
        floor = rules.red_flag_floor({flag: None for flag in rules.RED_FLAG_FIELDS})
        self.assertEqual(floor, {"level": None, "red_flags": []})

    def test_denied_flags_do_not_fire(self):
        floor = rules.red_flag_floor({flag: False for flag in rules.RED_FLAG_FIELDS})
        self.assertEqual(floor, {"level": None, "red_flags": []})

    def test_only_literal_true_counts(self):
        # A stray string or list from a malformed object is not evidence.
        floor = rules.red_flag_floor({"swelling": "yes", "fever": 1, "recent_trauma": ["x"]})
        self.assertEqual(floor["level"], None)

    def test_non_red_flag_symptoms_do_not_fire(self):
        floor = rules.red_flag_floor({"pain_present": True, "pain_severity": "severe",
                                      "pain_relief_effect": "not_helped",
                                      "pain_wakes_at_night": True})
        self.assertEqual(floor["level"], None)

    def test_missing_symptoms(self):
        self.assertEqual(rules.red_flag_floor(None), {"level": None, "red_flags": []})
        self.assertEqual(rules.red_flag_floor({}), {"level": None, "red_flags": []})

    def test_assess_baseline_ignores_new_flags(self):
        # assess() is the unchanged paper baseline: the new floor fields must
        # not leak into it (a bleeding-only case stays ROUTINE under R9).
        good = {"image_quality": {"upper": {"usable": True, "reasons": []},
                                  "lower": {"usable": True, "reasons": []}},
                "arches": {"upper": {"present": True, "teeth_detected": 14},
                           "lower": {"present": True, "teeth_detected": 14}},
                "teeth": {}}
        result = rules.assess(good, {"bleeding_uncontrolled": True})
        self.assertEqual((result["urgency"], result["rule_id"]), ("ROUTINE", "R9"))


if __name__ == "__main__":
    unittest.main()
