"""Unit tests for src/filter_dental_qa.py — each filter must also be seen to fail.

    .venv/Scripts/python -m unittest tests.test_filter_dental_qa -v

No data files needed. Every positive case has a near-miss negative, because a
filter that accepts everything (or nothing) passes half of any one-sided test.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from filter_dental_qa import DROPPING_FLAGS, answer_flags, is_english, topic  # noqa: E402


def drops(text):
    """The flags that actually remove a row (generic_product does not)."""
    return [f for f in answer_flags(text) if f in DROPPING_FLAGS]


class English(unittest.TestCase):
    def test_english_passes(self):
        for text in ["Hi doctor, my tooth hurts when I drink cold water and it lasts a while.",
                     "toothache",
                     "Hello, I had a filling done two days ago and now my gum is swollen.",
                     # terse English: few function words, but English (real row shapes)
                     "semen analysis volume 3.0ml, colour white, alkaline, sperm count 115million/ml",
                     "thankz doc vel i hav an allergy from last five years ma lyf z like hell",
                     "SGOT (AST) 29.00 U/L SGPT (ALT) 39.00 U/L GGTP 50.00 U/L"]:
            with self.subTest(text=text):
                self.assertTrue(is_english(text)[0], text)

    def test_non_english_fails(self):
        cases = {
            "我的牙齿很痛，已经三天了，晚上睡不着": "non_latin_script",
            "Мой зуб болит уже три дня и ночью я не сплю": "non_latin_script",
            "dokter saya sakit gigi sudah tiga hari dan gusi saya bengkak sekali": "romanised_non_english",
            "doctor mere daant mein bahut dard hai aur masoode sooj gaye hain kya karu": "romanised_non_english",
            "Hola doctor tengo mucho dolor en la muela y no puedo dormir por la noche": "romanised_non_english",
            "I have had pain in my back tooth for a long time and the dentist said it is fine "
            "but it is not, mujhe lagta hai kuch problem hai aur dard ho raha": "code_switched",
            "": "empty",
            "12345 ???": "empty",
        }
        for text, reason in cases.items():
            with self.subTest(text=text):
                self.assertEqual(is_english(text), (False, reason))


class Topic(unittest.TestCase):
    def test_dental_passes(self):
        for text in ["My tooth hurts", "bleeding gums when brushing", "wisdom teeth coming in",
                     "pain in my jaw when chewing", "I have a mouth ulcer",
                     "root canal done last week", "my denture is loose", "TMJ clicking",
                     "the cavity in my back molar", "abscess near my tooth",
                     "a filling fell out of my tooth", "my crown on the molar broke",
                     "gingivitis diagnosed by hygienist"]:
            with self.subTest(text=text):
                self.assertTrue(topic(text)["dental"], text)

    def test_near_misses_fail(self):
        for text in ["I swallowed chewing gum", "nicotine gum makes me dizzy",
                     "fluid in the nasal cavity", "abdominal cavity pain after surgery",
                     "I have jaundice and yellow eyes",         # 'jaw' must not match 'jaundice'
                     "an abscess on my back",                   # abscess needs a tooth word
                     "a cavity was found in my lung on x-ray",
                     "filling out forms makes me anxious",
                     "the crown of my head is itchy",
                     "knee braces after ACL surgery",
                     "extraction of a cataract",
                     "gum arabic allergy",
                     "the canine bit me"]:                      # dog, not tooth
            with self.subTest(text=text):
                self.assertFalse(topic(text)["dental"], text)

    def test_context_word_needs_a_tooth_within_ten_words(self):
        self.assertTrue(topic("had an extraction and now the tooth socket hurts")["dental"])
        far = "had an extraction " + "blah " * 15 + "tooth"
        self.assertFalse(topic(far.replace("tooth", "toe"))["dental"])

    def test_oral_soft_tissue_terms_are_included_and_tagged(self):
        # P9 recall audit, 2026-09-23: most misses were tongue/palate/lip/mouth
        for text in ["a sore spot on my tongue", "white patch on my palate",
                     "my lower lip is swollen", "an ulcer inside my mouth",
                     "a lump in my mouth", "canker sores keep coming back",
                     "burning on the roof of my mouth"]:
            with self.subTest(text=text):
                t = topic(text)
                self.assertTrue(t["dental"], text)
                self.assertIn("oral_soft_tissue", t["tags"])

    def test_soft_tissue_near_misses_still_fail(self):
        for text in ["lipid profile came back high", "I use lip balm for dry skin",
                     "my mother tongue is Tamil", "tongue of the shoe rubs my foot"]:
            with self.subTest(text=text):
                self.assertFalse(topic(text)["dental"], text)

    def test_strong_terms_are_not_tagged_soft_tissue(self):
        self.assertNotIn("oral_soft_tissue", topic("my tooth hurts")["tags"])

    def test_loose_term_with_mouth_now_counts(self):
        # "a few fillings on the left side of my mouth" (research-pm's A2 example)
        self.assertTrue(topic("I have a few fillings on the left side of my mouth")["dental"])

    def test_jaw_with_chest_pain_is_kept_and_tagged(self):
        t = topic("pain in my jaw and chest pain when I walk")
        self.assertTrue(t["dental"])
        self.assertIn("jaw_with_cardiac_symptoms", t["tags"])
        self.assertNotIn("jaw_with_cardiac_symptoms", topic("pain in my jaw")["tags"])


class Answer(unittest.TestCase):
    def test_clean_answers_pass(self):
        for text in ["Please see a dentist so they can examine the tooth.",
                     "Keep the area clean and see your dentist within a week.",
                     "You have to visit a dentist for an examination.",   # not a diagnosis
                     "It is important that a dentist checks this soon.",
                     "Your dentist can take an x-ray to find the cause."]:
            with self.subTest(text=text):
                self.assertEqual(answer_flags(text), [], text)

    def test_drug_names(self):
        for text in ["Take amoxicillin and see your dentist", "Use AUGMENTIN for 5 days",
                     "rinse with chlorhexidine", "a tab of Paracetamol", "ibuprofen helps"]:
            with self.subTest(text=text):
                self.assertIn("drug_name", answer_flags(text))

    def test_drug_names_need_word_boundaries(self):
        # 'amox' inside another word, 'candid' as an adjective is a known false hit
        self.assertNotIn("drug_name", answer_flags("the flagyllic tone"))

    def test_drug_classes(self):
        # Prescription-only classes drop the row; generic OTC wording does not
        # (2026-09-23, after research-pm's over-removal audit).
        for text in ["You may need antibiotics", "a course of antifungals", "steroids help"]:
            with self.subTest(text=text):
                self.assertIn("drug_class", drops(text))
        for text in ["take a painkiller", "use a mouthwash", "an anti-inflammatory will help"]:
            with self.subTest(text=text):
                self.assertEqual(drops(text), [])
                self.assertIn("generic_product", answer_flags(text))

    def test_doses(self):
        for text in ["500 mg", "500mg", "0.5 ml", "take it twice daily", "3 times a day",
                     "every 6 hours", "every 4-6 hours", "two tablets", "tab. zerodol",
                     "1 tsp at night", "take it TDS"]:
            with self.subTest(text=text):
                self.assertIn("dose", answer_flags(text), text)

    def test_dose_near_misses(self):
        for text in ["see a dentist in 2 days", "the tooth 42 is sensitive",
                     "it happened 3 times", "tooth number 0.42 on the chart", "tooth 42.",
                     "the cap on my tooth came off", "a tab on the form"]:
            with self.subTest(text=text):
                self.assertNotIn("dose", answer_flags(text), text)

    def test_self_care_frequencies_are_not_doses(self):
        # P9 over-removal audit, 2026-09-23
        for text in ["Rinse with warm salt water two to three times a day.",
                     "Use 1/2 teaspoon of salt in a glass of warm water.",
                     "Brush twice a day and floss once a day.",
                     "Gargle with lukewarm water 3 times a day."]:
            with self.subTest(text=text):
                self.assertNotIn("dose", drops(text), text)

    def test_real_doses_still_drop_even_near_a_rinse(self):
        for text in ["Rinse with chlorhexidine and take 500 mg twice a day.",
                     "Take two tablets after food.", "one capsule every 8 hours"]:
            with self.subTest(text=text):
                self.assertIn("dose", drops(text), text)

    def test_generic_products_do_not_drop_the_row(self):
        for text in ["You can use a mouthwash.", "An anti-inflammatory may help.",
                     "A painkiller from the pharmacy is fine.", "Apply a gel to the gum."]:
            with self.subTest(text=text):
                self.assertEqual(drops(text), [], text)
                self.assertIn("generic_product", answer_flags(text))

    def test_prescription_classes_still_drop(self):
        for text in ["You may need antibiotics.", "A course of steroids is required.",
                     "NSAIDs will settle it.", "prescription-strength rinse"]:
            with self.subTest(text=text):
                self.assertIn("drug_class", drops(text), text)

    def test_medicine_named_as_a_cause_is_not_advice(self):
        for text in ["The grey stains are from tetracycline taken in childhood.",
                     "This can be due to antibiotics used as a child.",
                     "A metallic taste is a side effect of metronidazole.",
                     "She is allergic to penicillin."]:
            with self.subTest(text=text):
                self.assertEqual(drops(text), [], text)

    def test_medicine_as_advice_still_drops_even_with_a_cause_word(self):
        for text in ["Because of the infection, take amoxicillin.",
                     "The pain is due to decay, so I advise antibiotics.",
                     "Rinse with chlorhexidine."]:
            with self.subTest(text=text):
                self.assertTrue(drops(text), text)

    def test_blood_results_are_not_drugs(self):
        for text in ["Your calcium level is low.", "Take a vitamin rich diet.",
                     "His vitamin D was 12."]:
            with self.subTest(text=text):
                self.assertEqual(drops(text), [], text)

    def test_definitive_diagnoses(self):
        for text in ["You have a tooth infection.", "you have an abscess",
                     "You have caries in the molar", "You are suffering from pulpitis",
                     "This is definitely decay", "this is a dry socket",
                     "It is a periapical abscess", "you were diagnosed with gingivitis",
                     "The x-ray confirms it", "most likely it is an abscess",
                     "probably pericoronitis"]:
            with self.subTest(text=text):
                self.assertIn("definitive_diagnosis", answer_flags(text), text)


if __name__ == "__main__":
    unittest.main()
