"""Unit tests for src/silver_labels.py (plan §3.2) — no GPU, no Ollama.

    .venv/Scripts/python -m unittest discover -s tests -p "test_silver_labels.py" -v

The four phrases research-pm singled out as deciding whether kappa clears the
bar each have a test here, written from their hand reading, not from what the
script happened to do.
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import silver_labels as sl  # noqa: E402


def label(text):
    return sl.label_answer(text)["silver_label"]


class Basics(unittest.TestCase):
    def test_each_label_fires(self):
        cases = {
            "Please go to the nearest hospital emergency department now.": "EMERGENCY",
            "See a dentist as soon as possible.": "URGENT",
            "Visit a dentist within a week for a filling.": "SOON",
            "There is nothing to worry about; mention it at your next check-up.": "ROUTINE",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(label(text), want)

    def test_bare_consult_is_unspecified(self):
        for text in ["Please consult a dentist for an examination.",
                     "You should see a dentist and get an x-ray taken.",
                     "Visit your dentist for evaluation and treatment.",
                     "Thank you for your query. I have gone through your question."]:
            with self.subTest(text=text):
                self.assertEqual(label(text), "UNSPECIFIED")

    def test_most_urgent_wins_and_is_marked_conflicted(self):
        out = sl.label_answer("See a dentist within a week, but if swelling spreads "
                              "go to the emergency department.")
        self.assertEqual(out["silver_label"], "EMERGENCY")
        self.assertTrue(out["conflicted"])
        self.assertEqual(out["labels_found"], ["EMERGENCY", "SOON"])

    def test_single_label_is_not_conflicted(self):
        self.assertFalse(sl.label_answer("See a dentist as soon as possible.")["conflicted"])

    def test_er_is_case_sensitive(self):
        self.assertEqual(label("Go to the ER now for this."), "EMERGENCY")
        # lower-case "er" inside ordinary words must not fire
        self.assertEqual(label("Consider a filling; the tooth is weaker than the other."),
                         "UNSPECIFIED")


class Negation(unittest.TestCase):
    def test_negated_phrase_does_not_count(self):
        self.assertNotEqual(label("This is not an emergency, just book a check-up."), "EMERGENCY")
        self.assertEqual(label("There is no need to worry about this."), "ROUTINE")

    def test_negation_only_reaches_three_words_back(self):
        # the denial is about something else, far from the instruction
        self.assertEqual(label("There is no fever and the gum looks fine overall, but the "
                               "tooth is broken, so go to the emergency department."), "EMERGENCY")


class PhrasesResearchPmFlagged(unittest.TestCase):
    """The four answers research-pm said would decide kappa (2026-09-23)."""

    def test_not_an_emergency_but_demands_immediate_care(self):
        out = sl.label_answer("Though not an emergency, this demands immediate and complete "
                              "dental care.")
        self.assertEqual(out["silver_label"], "URGENT")       # their hand label (cd053260)
        self.assertIn("denied_emergency", out["capped"])

    def test_er_only_to_obtain_a_painkiller(self):
        out = sl.label_answer("You can take her to ER where they will give her a painkiller "
                              "injection, then see a dentist.")
        self.assertEqual(out["silver_label"], "URGENT")
        self.assertIn("emergency_room_for_medication", out["capped"])

    def test_no_emergency_but_er_if_troubled(self):
        out = sl.label_answer("There is no emergency, if she is troubled take her to ER.")
        self.assertEqual(out["silver_label"], "URGENT")
        self.assertIn("denied_emergency", out["capped"])

    def test_the_earlier_the_better_has_no_window(self):
        # "the earlier you visit, the better" gives no time frame at all
        self.assertEqual(label("The earlier you visit a dentist, the better it is for you."),
                         "UNSPECIFIED")

    def test_at_the_earliest_is_still_urgent(self):
        self.assertEqual(label("Please visit a dentist at the earliest."), "URGENT")


class Corpus(unittest.TestCase):
    def test_source_fault_row_is_skipped_not_labelled(self):
        rows = [{"id": "cd011595", "answer": "anything at all", "question": "q"},
                {"id": "cd000001", "answer": "See a dentist as soon as possible.", "question": "q"}]
        out = sl.label_rows(rows)
        self.assertTrue(out[0]["source_fault"])
        self.assertIsNone(out[0]["silver_label"])
        self.assertEqual(out[1]["silver_label"], "URGENT")
        self.assertEqual(sl.summarise(out)["source_faults"], 1)

    def test_coverage_excludes_unspecified(self):
        rows = [{"id": f"x{i}", "question": "q", "answer": a} for i, a in enumerate(
            ["See a dentist.", "Go to hospital immediately.", "Nothing to worry about.",
             "Consult a dentist please."])]
        summary = sl.summarise(sl.label_rows(rows))
        self.assertAlmostEqual(summary["coverage"], 0.5)
        self.assertEqual(summary["label_counts"]["UNSPECIFIED"], 2)

    def test_agreement_scoring(self):
        labelled = sl.label_rows([
            {"id": "a", "question": "q", "answer": "Go to hospital immediately."},
            {"id": "b", "question": "q", "answer": "See a dentist as soon as possible."},
            {"id": "c", "question": "q", "answer": "Consult a dentist."},
        ])
        perfect = sl.evaluate(labelled, {"a": "EMERGENCY", "b": "URGENT", "c": "UNSPECIFIED"})
        self.assertEqual(perfect["agreement"], 1.0)
        self.assertEqual(perfect["kappa"], 1.0)
        # a checker that cannot disagree proves nothing: flip one
        worse = sl.evaluate(labelled, {"a": "ROUTINE", "b": "URGENT", "c": "UNSPECIFIED"})
        self.assertLess(worse["agreement"], 1.0)
        self.assertLess(worse["kappa"], 1.0)
        self.assertEqual(worse["script_less_urgent_than_hand"], 0)   # script was MORE urgent

    def test_under_triage_proxy_counts_the_right_direction(self):
        labelled = sl.label_rows([{"id": "a", "question": "q",
                                   "answer": "See a dentist within a week."}])
        out = sl.evaluate(labelled, {"a": "EMERGENCY"})   # hand more urgent than script
        self.assertEqual(out["script_less_urgent_than_hand"], 1)

    def test_calibration_batch_is_balanced_and_hides_nothing_needed(self):
        rows = [{"id": f"e{i}", "question": "q", "answer": "Go to hospital immediately."}
                for i in range(50)]
        rows += [{"id": f"o{i}", "question": "q", "answer": "Consult a dentist."} for i in range(50)]
        batch = sl.calibration_batch(sl.label_rows(rows), 40)
        self.assertEqual(len(batch), 80)
        self.assertEqual(sum(r["silver_label"] == "EMERGENCY" for r in batch), 40)


if __name__ == "__main__":
    unittest.main()
