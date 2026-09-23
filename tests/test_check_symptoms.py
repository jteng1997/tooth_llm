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


if __name__ == "__main__":
    unittest.main()
