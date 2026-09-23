"""Unit tests for the scoring in src/check_faithfulness.py (Test 2). No model.

    .venv/Scripts/python -m unittest discover -s tests -p "test_check_faithfulness.py" -v
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import check_faithfulness as cf  # noqa: E402

FINDINGS = {"teeth": {"17": {"present": False, "detections": []},
                      "36": {"present": True, "detections": [{"type": "caries", "confidence": 0.9}]}}}


class Misstated(unittest.TestCase):
    def test_decay_on_a_missing_tooth_is_caught(self):
        text = ("We looked at your photos. Based on the image, there is an indication of tooth "
                "decay on tooth 17 (upper right second molar).")
        self.assertEqual(cf.misstated(text, FINDINGS), ["17"])

    def test_plain_word_name_counts(self):
        self.assertEqual(cf.misstated("A cavity on the upper right second molar.", FINDINGS), ["17"])

    def test_saying_it_is_missing_is_fine(self):
        self.assertEqual(cf.misstated("Tooth 17 (upper right second molar) may be missing.", FINDINGS), [])
        self.assertEqual(cf.misstated("There is an indication of something unusual on tooth 17.",
                                      FINDINGS), [])

    def test_decay_on_a_present_tooth_is_not_this_error(self):
        self.assertEqual(cf.misstated("Possible decay on tooth 36. Tooth 17 is missing.", FINDINGS), [])


if __name__ == "__main__":
    unittest.main()
