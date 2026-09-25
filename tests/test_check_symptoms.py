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


class SeverityErrors(unittest.TestCase):
    """Pre-declared 2026-09-26: pain_severity errors by the direction they push
    triage. Extra block only; no other number may move."""

    PAIRS = [("A", "mild", "severe"), ("B", "moderate", "severe"), ("C", "moderate", "moderate"),
             ("D", "severe", "moderate"), ("E", "severe", None), ("F", "severe", "severe"),
             ("G", "mild", "moderate")]

    def test_directions_and_ids(self):
        s = cs.severity_errors(self.PAIRS)
        self.assertEqual((s["n"], s["n_key_below_severe"], s["n_key_severe"]), (7, 4, 3))
        self.assertEqual((s["false_severe"], s["false_severe_ids"]), (2, ["A", "B"]))
        self.assertEqual((s["missed_severe"], s["missed_severe_ids"]), (2, ["D", "E"]))
        self.assertEqual(s["false_severe_ci95"], cs.clopper_pearson(2, 7))
        self.assertEqual(s["false_severe_ci95_of_key_below"], cs.clopper_pearson(2, 4))
        self.assertEqual(s["missed_severe_ci95_of_key_severe"], cs.clopper_pearson(2, 3))

    def test_a_correct_run_counts_nothing(self):
        s = cs.severity_errors([(i, v, v) for i, v in (("A", "mild"), ("B", "severe"))])
        self.assertEqual((s["false_severe"], s["missed_severe"]), (0, 0))
        self.assertEqual(s["missed_severe_ci95"][0], 0.0)

    def test_mild_moderate_swaps_are_neither(self):
        s = cs.severity_errors([("A", "mild", "moderate"), ("B", "moderate", "mild"),
                                ("C", "moderate", None)])
        self.assertEqual((s["false_severe"], s["missed_severe"]), (0, 0))

    def test_null_key_is_kept_apart(self):
        s = cs.severity_errors([("A", None, "severe"), ("B", "mild", "mild")])
        self.assertEqual((s["false_severe"], s["severe_where_key_null_ids"]), (0, ["A"]))

    def test_empty_gives_nan_not_a_crash(self):
        s = cs.severity_errors([])
        self.assertNotEqual(s["false_severe_ci95"][0], s["false_severe_ci95"][0])

    def test_evaluate_on_the_dev_dialogues_with_a_stub_extractor(self):
        """The real evaluate() and report on llm/eval/symptom_dialogues.json,
        with run_case stubbed to return the key except for pain_severity."""
        import contextlib
        import io
        import json
        spec = json.loads(cs.DIALOGUES.read_text(encoding="utf-8"))
        cases = [c for c in spec["cases"] if c.get("scope", "headline") == "headline"
                 and c["expected"].get("pain_severity") is not None]
        below = [c["id"] for c in cases if c["expected"]["pain_severity"] != "severe"]
        severe = [c["id"] for c in cases if c["expected"]["pain_severity"] == "severe"]
        self.assertTrue(below and severe, "the dev dialogues need both kinds of key")
        flip = {below[0]: "severe", severe[0]: None}
        by_id = {c["id"]: c for c in spec["cases"]}

        def fake_run_case(case, model, protocol, llm=None):
            got = dict(case["expected"])
            if case["id"] in flip:
                got["pain_severity"] = flip[case["id"]]
            got.update(case.get("expected_clicks_unchanged") or {})
            return {"symptoms": got, "asked": [], "unscripted": [], "unused": {}}
        original = cs.run_case
        cs.run_case = fake_run_case
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                r = cs.evaluate("stub", protocol=object())
        finally:
            cs.run_case = original
        s = r["severity_errors"]
        self.assertEqual(s["n"], len(cases))
        self.assertEqual((s["false_severe_ids"], s["missed_severe_ids"]), ([below[0]], [severe[0]]))
        self.assertIn(f"false severe  (key mild/moderate, got severe; raises urgency)  1/{len(cases)}",
                      buf.getvalue())
        # the existing numbers see exactly two wrong fields, as before
        self.assertEqual(r["fields_scored"] - r["fields_right"], 2)
        self.assertIn(by_id[below[0]]["id"], [c["id"] for c in r["cases"] if c["wrong"]])


if __name__ == "__main__":
    unittest.main()
