"""Unit tests for the scoring in src/check_symptoms.py (Test 3). No model.

    .venv/Scripts/python -m unittest discover -s tests -p "test_check_symptoms.py" -v
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import check_symptoms as cs  # noqa: E402


class InventedItems(unittest.TestCase):
    def test_extra_item_next_to_a_right_one(self):
        self.assertEqual(cs.invented_items({"pain_triggers": ["unknown"]},
                                           {"pain_triggers": ["unknown", "spontaneous"]}),
                         {"pain_triggers": ["spontaneous"]})

    def test_order_and_exact_match_are_not_inventions(self):
        self.assertEqual(cs.invented_items({"pain_triggers": ["cold", "sweet"]},
                                           {"pain_triggers": ["sweet", "cold"]}), {})

    def test_null_key_is_the_guessed_count_not_this_one(self):
        self.assertEqual(cs.invented_items({"pain_triggers": None}, {"pain_triggers": ["cold"]}), {})

    def test_missing_item_is_not_an_invention(self):
        self.assertEqual(cs.invented_items({"pain_triggers": ["cold", "hot"]},
                                           {"pain_triggers": ["cold"]}), {})


class Reporting(unittest.TestCase):
    def test_exact_ci_known_value(self):
        lo, hi = cs.clopper_pearson(5, 20)
        self.assertAlmostEqual(lo, 0.0866, places=4)
        self.assertAlmostEqual(hi, 0.4910, places=4)

    def test_configuration_hashes_the_dialogue_file(self):
        cfg = cs.configuration("stub", cs.DIALOGUES)
        self.assertEqual(len(cfg["dialogues_sha256"]), 64)
        self.assertEqual(cfg["model"], "stub")

    def test_answer_lists_are_used_in_order_on_a_reask(self):
        # a re-asked question gets the next scripted answer, not the canned one
        case = {"script": {"Q10": ["hmm", "I took nothing at all."]}, "checklist": {}}
        calls = []

        class FakeInterview:
            def __init__(self, *a, **kw):
                self.symptoms, self.steps = {}, iter([{"type": "question", "id": "Q10"},
                                                      {"type": "question", "id": "Q10"},
                                                      {"type": "done"}])

            def start(self):
                return next(self.steps)

            def reply(self, answer):
                calls.append(answer)
                return next(self.steps)
        original = cs.Interview
        cs.Interview = FakeInterview
        try:
            played = cs.run_case(case, "stub", protocol=None)
        finally:
            cs.Interview = original
        self.assertEqual(calls, ["hmm", "I took nothing at all."])
        self.assertEqual(played["unscripted"], [])


if __name__ == "__main__":
    unittest.main()
