"""Unit tests for src/check_phrases.py, with a stub extractor (no model).

    .venv/Scripts/python -m unittest discover -s tests -p "test_check_phrases.py" -v
"""
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import check_phrases as cp  # noqa: E402
import protocol as protocol_mod  # noqa: E402

PROTOCOL = protocol_mod.load(allow_unreviewed=True)


def stub(field, value):
    """Extracts `value` for `field`, quoting the patient's first reply that is
    not "I'm not sure." -- i.e. the phrase; every other field null."""
    def llm(messages, schema):
        said = [m["content"] for m in messages[1:-1] if m["role"] == "user" and m["content"] != cp.NOT_SURE]
        out = {f: {"value": None, "quote": None} for f in schema["required"]}
        if said:
            out[field] = {"value": value, "quote": said[0]}
        return json.dumps(out)
    return llm


class RunPhrase(unittest.TestCase):
    def test_severity_phrase_answers_q11_only(self):
        case = {"id": "X", "severe": True, "text": "It stops me sleeping at night."}
        r = cp.run_phrase(case, "stub", PROTOCOL, stub("pain_severity", "severe"))
        self.assertEqual(r["got"], "severe")
        self.assertIn("Q11", r["asked"])
        self.assertTrue(cp.score(case, r["got"]))

    def test_relief_phrase_answers_q10(self):
        case = {"id": "R", "expected": "not_tried", "text": "I have not taken anything for it."}
        r = cp.run_phrase(case, "stub", PROTOCOL, stub("pain_relief_effect", "not_tried"))
        self.assertEqual(r["got"], "not_tried")
        self.assertEqual(r["asked"][0], "Q10")
        self.assertTrue(cp.score(case, r["got"]))

    def test_nothing_extracted_is_null_and_re_asked(self):
        case = {"id": "R", "expected": "not_tried", "text": "I have not taken anything for it."}
        r = cp.run_phrase(case, "stub", PROTOCOL, stub("pain_relief_effect", None))
        self.assertIsNone(r["got"])
        self.assertTrue(r["reasked"])
        self.assertFalse(cp.score(case, r["got"]))          # the check can fail
        self.assertTrue(cp.score({"expected": None}, None))  # null expected, null got

    def test_severity_scoring_directions(self):
        self.assertFalse(cp.score({"severe": True}, None))          # a drop
        self.assertFalse(cp.score({"severe": True}, "moderate"))
        self.assertFalse(cp.score({"severe": False}, "severe"))     # a false keep
        self.assertTrue(cp.score({"severe": False}, None))

    def test_summary_splits_tuned_and_directions(self):
        rows = [{"id": "A", "tuned": False, "ok": True, "severe": True},
                {"id": "B", "tuned": False, "ok": False, "severe": True},
                {"id": "C", "tuned": True, "ok": False, "severe": False}]
        s = cp.summarise(rows)
        self.assertEqual(s["independent"], {"n": 2, "correct": 1, "wrong_ids": ["B"]})
        self.assertEqual(s["tuned"], {"n": 1, "correct": 0, "wrong_ids": ["C"]})
        self.assertEqual((s["false_drops"], s["false_keeps"]), ({"n": 2, "k": 1}, {"n": 1, "k": 1}))


if __name__ == "__main__":
    unittest.main()
