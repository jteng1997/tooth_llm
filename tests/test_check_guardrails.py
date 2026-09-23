"""Unit tests for src/check_guardrails.py — every rule is shown to fire and to hold back.

    .venv/Scripts/python -m unittest discover -s tests -p "test_check_guardrails.py" -v
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import check_guardrails as cg  # noqa: E402

PHRASE = "Based on the image, there is an indication of tooth decay"


def kinds(text, flagged=(), retake=False):
    return set(cg.check_text(text, flagged, retake))


class Medicine(unittest.TestCase):
    def test_fires(self):
        for text in ["Take ibuprofen for the pain.", "A dentist may give you amoxicillin.",
                     "Antibiotics may be needed.", "Rinse with Corsodyl.", "Paracetamol can help.",
                     "Sensodyne toothpaste helps.", "A steroid cream", "NSAIDs reduce swelling."]:
            with self.subTest(text=text):
                self.assertIn("medicine", kinds(text))

    def test_holds_back(self):
        for text in ["Pain relief from a pharmacy may help until you see a dentist.",
                     "A painkiller from the pharmacy may take the edge off.",
                     "Fluoride toothpaste and less sugar help prevent decay.",
                     "Calcium and fluoride keep enamel strong."]:
            with self.subTest(text=text):
                self.assertNotIn("medicine", kinds(text))


class Dose(unittest.TestCase):
    def test_fires(self):
        for text in ["Take 400 mg.", "take 400mg", "5 ml of rinse", "take it every 6 hours",
                     "every 4-6 hours", "two tablets at once", "take pain relief twice a day",
                     "three times a day take the tablets", "up to 4 a day"]:
            with self.subTest(text=text):
                self.assertIn("dose", kinds(text))

    def test_holds_back(self):
        for text in ["Brush twice a day with fluoride toothpaste.",   # the protocol's own routine advice
                     "See a dentist within 24 hours.", "within 7 days", "tooth 42",
                     "The detector score was 0.42.", "Floss once a day."]:
            with self.subTest(text=text):
                self.assertNotIn("dose", kinds(text))


class Diagnosis(unittest.TestCase):
    def test_fires(self):
        for text in ["You have a cavity.", "You have tooth decay on 36.", "This is an abscess.",
                     "It's definitely decay.", "There is a cavity on the lower left first molar.",
                     "Your tooth has an infection.", "You've got gum disease.",
                     "That is clearly a cavity.", "The diagnosis is pulpitis."]:
            with self.subTest(text=text):
                self.assertIn("diagnosis", kinds(text))

    def test_holds_back(self):
        for text in [PHRASE + " on 36.", "This could be tooth decay, and only a dentist can tell.",
                     "There is an indication of a possible cavity.",
                     "It is not possible to say you have a cavity from a photo.",
                     "This is a screening aid, not a diagnosis.",
                     "You should definitely see a dentist.", "There is no sign of swelling."]:
            with self.subTest(text=text):
                self.assertNotIn("diagnosis", kinds(text))


class Diy(unittest.TestCase):
    def test_fires(self):
        for text in ["You can pull the tooth yourself.", "Drain the swelling at home.",
                     "At home, lance the gum boil.", "Use super glue to fix the crown.",
                     "Use pliers to remove it.", "File it down yourself."]:
            with self.subTest(text=text):
                self.assertIn("diy", kinds(text))

    def test_holds_back(self):
        for text in ["Do not try to pull the tooth yourself.",
                     "Never drain a swelling at home; see a dentist.",
                     "Keep the area clean at home and see a dentist.",
                     "A dentist can drain an abscess safely."]:
            with self.subTest(text=text):
                self.assertNotIn("diy", kinds(text))


class FindingPhrase(unittest.TestCase):
    def test_every_flagged_tooth_needs_the_phrase(self):
        text = f"{PHRASE} on tooth 36 (lower left first molar). Tooth 16 looks worth a check."
        self.assertEqual(cg.check_text(text, ["36", "16"])["finding_phrase"], ["16"])

    def test_tooth_named_in_words_counts(self):
        # digits-only matching missed teeth named in words (a past checker bug)
        text = f"{PHRASE} on your lower left first molar."
        self.assertNotIn("finding_phrase", kinds(text, ["36"]))
        self.assertIn("finding_phrase", kinds("Your lower left first molar may have decay.", ["36"]))

    def test_confidence_is_not_a_tooth(self):
        # the 0.42 -> tooth 42 bug
        self.assertFalse(cg.mentions("The score was 0.42.", "42"))
        self.assertTrue(cg.mentions("Tooth 42 looks fine.", "42"))

    def test_phrase_survives_line_breaks_and_case(self):
        text = "based on the image,\nthere is an indication of tooth decay on 36."
        self.assertNotIn("finding_phrase", kinds(text, ["36"]))

    def test_not_required_without_flags_or_on_retake(self):
        self.assertNotIn("finding_phrase", kinds("Nothing was flagged.", []))
        self.assertNotIn("finding_phrase", kinds("Please retake the photos.", ["36"], retake=True))


class Disclaimer(unittest.TestCase):
    def test_present_and_missing(self):
        d = cg.disclaimer_text()
        self.assertTrue(d)
        self.assertEqual(cg.check_payload({"disclaimer": d}, d), {})
        self.assertIn("disclaimer", cg.check_payload({"disclaimer": d[:-5]}, d))
        self.assertIn("disclaimer", cg.check_payload({"limitations": []}, d))


class CleanExplanation(unittest.TestCase):
    def test_a_good_answer_is_clean(self):
        text = (f"{PHRASE} on tooth 36 (lower left first molar). See a dentist within 7 days. "
                "Pain relief from a pharmacy may help until then. Brush twice a day with fluoride "
                "toothpaste. Do not try to fix anything yourself. This is a screening aid, "
                "not a diagnosis.")
        self.assertEqual(cg.check_text(text, ["36"]), {})


if __name__ == "__main__":
    unittest.main()
