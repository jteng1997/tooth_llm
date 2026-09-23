"""Unit tests for the explanation guardrails in src/explain.py (no GPU, no Ollama).

    .venv/Scripts/python -m unittest discover -s tests -v
"""
import copy
import json
import unittest

import fixtures  # noqa: F401  (sys.path)

import explain as guardrail_module  # noqa: E402
import explain  # noqa: E402
from explain import Explanation, fallback_text, guardrail_violations  # noqa: E402

GOOD = {"image_quality": {"upper": {"usable": True, "reasons": []},
                          "lower": {"usable": True, "reasons": []}},
        "arches": {"upper": {"present": True, "teeth_detected": 14},
                   "lower": {"present": True, "teeth_detected": 14}},
        "teeth": {"16": {"present": True, "detections": [{"type": "caries", "confidence": 0.81}]}}}

ASSESSMENT = {
    "schema_version": "2.0", "urgency": "SOON", "urgency_rank": 3,
    "headline": "See a dentist within 7 days", "flagged_teeth": ["16"],
    "retake_required": False,
    "limitations": ["Occlusal photos cannot show surfaces between teeth.",
                    "This is a screening aid, not a diagnosis."],
    "safety_net": "x", "emergency_route": None, "decided_by": "llm",
    "reasons": [{"criterion_id": "P1", "statement": "Possible cavity flagged in the photo",
                 "evidence": []}],
    "triage": {}, "rules_baseline": {},
}
GOOD_TEXT = ("Based on the image, there is an indication of tooth decay on tooth 16 "
             "(upper right first molar). See a dentist within 7 days.")


class Patterns(unittest.TestCase):
    def test_clean_text_passes(self):
        self.assertEqual(guardrail_violations(GOOD_TEXT, ["16"]), [])
        self.assertEqual(guardrail_violations(
            "You should definitely see a dentist soon. Pain relief from a pharmacy, used as "
            "the packet says, can help until then.", []), [])

    def test_each_rule_fires(self):
        cases = {
            "names a medicine": ["Take ibuprofen for the pain.", "You may need antibiotics.",
                                 "Amoxicillin is often used."],
            "gives a dose": ["Take 400 mg now.", "Use it three times a day.",
                             "Every 6 hours is fine."],
            "sounds like a diagnosis": ["You have a cavity on tooth 16.",
                                        "This is definitely decay.", "This is a cavity."],
            "suggests a home procedure": ["You could drain it yourself.",
                                          "Try to pull the loose tooth at home."],
        }
        for rule, texts in cases.items():
            for text in texts:
                with self.subTest(text=text):
                    self.assertIn(rule, guardrail_violations(text))

    def test_garbled_medicine_names_are_caught_by_shape(self):
        # research-pm's P9 audit: 8 of 15 medicine leaks in "clean" ChatDoctor
        # answers were names mangled by that dataset's spelling correction. A
        # word list cannot match them, but the prescription shape survives.
        for text in ("Use petrol DT for a few days.", "Try erosion forte.",
                     "Apply stolen gum paint to the area.", "Choral forte helps.",
                     "President 5000 plus is good.", "Humor HP 75 works well.",
                     "Tab Diploma twice daily.", "For can 150 mg."):
            with self.subTest(text=text):
                self.assertTrue(guardrail_violations(text), text)

    def test_general_pain_relief_wording_is_allowed(self):
        # The brief allows a general mention of over-the-counter relief.
        for text in ("You can take an anti-inflammatory if you need to.",
                     "Pain relief from a pharmacy, used as the packet says, can help.",
                     "An ordinary painkiller may take the edge off until then."):
            with self.subTest(text=text):
                self.assertEqual(guardrail_violations(text), [])

    def test_phrase_matches_the_protocol(self):
        # The page shows the protocol's full phrase; the guardrail only
        # requires its opening words. They must not drift apart.
        import protocol
        phrase = protocol.load(allow_unreviewed=True).fixed_text["photo_finding_phrase"]
        self.assertTrue(phrase.lower().startswith(guardrail_module.FINDING_PHRASE), phrase)

    def test_required_finding_phrase(self):
        text = "There may be a cavity on tooth 16 (upper right first molar)."
        self.assertTrue(any("Based on the image" in v for v in guardrail_violations(text, ["16"])))
        self.assertEqual(guardrail_violations(text, []), [])  # no flagged tooth, no phrase needed

    def test_fallback_text_is_itself_clean(self):
        for a in (ASSESSMENT,
                  {**ASSESSMENT, "flagged_teeth": [], "urgency": "ROUTINE",
                   "headline": "No urgent action"},
                  {**ASSESSMENT, "retake_required": True, "urgency": "RETAKE",
                   "headline": "Please retake the photos"}):
            text = fallback_text(a)
            with self.subTest(urgency=a["urgency"]):
                self.assertEqual(guardrail_violations(text, a["flagged_teeth"]
                                                      if a["urgency"] != "RETAKE" else []), [])
                self.assertIn(a["headline"], text)


class PainLocation(unittest.TestCase):
    """The patient's pain is only where symptoms.location says."""

    def test_side_or_tooth_invented_for_the_pain_is_caught(self):
        for text in ("Your toothache is on the upper right side, in the back, on your upper "
                     "right first molar (tooth 16).",
                     "Your toothache is on the upper right, upper left, lower left, and lower "
                     "right sides of your mouth.",
                     "Yes, the pain when biting could be coming from the tooth we found "
                     "(tooth 16, your upper right first molar).",
                     "The pain is probably from tooth 36.",
                     "Your pain comes from the tooth we found."):
            with self.subTest(text=text):
                self.assertTrue(explain.places_pain(text, None))

    def test_a_hedged_or_denied_link_to_a_found_tooth_passes(self):
        for text in ("The pain when biting may be related to the tooth we found, but only a "
                     "dentist can confirm this.",
                     "No, the pain when biting is not coming from a tooth we found.",
                     "We cannot say whether the pain comes from tooth 16."):
            with self.subTest(text=text):
                self.assertFalse(explain.places_pain(text, None))

    def test_the_patients_own_location_may_be_repeated(self):
        self.assertFalse(explain.places_pain("You said the pain is on the lower left.",
                                             "lower_left"))
        self.assertTrue(explain.places_pain("You said the pain is on the lower right.",
                                            "lower_left"))
        self.assertTrue(explain.places_pain("The pain on your lower left is from tooth 36.",
                                            "lower_left"))

    def test_ordinary_explanations_pass(self):
        for text in (GOOD_TEXT,
                     "We looked at the upper and lower teeth in your mouth. Pain when biting "
                     "can mean the problem has reached the tissues around the root tip.",
                     "You did not tell us where it hurts, so a dentist will check.",
                     "Until then, pain relief from a pharmacy can help with tooth 16.",
                     "Please see a dentist right away if the pain gets worse."):
            with self.subTest(text=text):
                self.assertFalse(explain.places_pain(text, None))


MISSING = {**GOOD, "teeth": {"17": {"present": False, "detections": []}}}
MISSING_ASSESSMENT = {**ASSESSMENT, "flagged_teeth": ["17"],
                      "reasons": [{"criterion_id": "R8", "statement": "missing", "evidence": []}]}
MISSING_TEXT = ("We looked at your photos. Based on the image, tooth 17 (upper right second molar) "
                "appears to be missing. See a dentist within 7 days.")


class MissingTooth(unittest.TestCase):
    """rules.py R8 flags an absent tooth; it must never be called decay."""

    def test_flagged_teeth_split_into_decay_and_missing(self):
        both = {**GOOD, "teeth": {**GOOD["teeth"], **MISSING["teeth"]}}
        self.assertEqual(explain.split_flagged({"flagged_teeth": ["16", "17"]}, both),
                         (["16"], ["17"]))
        self.assertEqual(explain.split_flagged(ASSESSMENT, GOOD), (["16"], []))

    def test_fallback_says_missing_not_decay(self):
        text = fallback_text(MISSING_ASSESSMENT, MISSING)
        self.assertIn("tooth 17 (upper right second molar) appears to be missing", text)
        self.assertNotIn("decay", text.lower())
        self.assertEqual(explain.calls_missing_decay(text, ["17"]), [])

    def test_decay_wording_on_a_missing_tooth_is_caught(self):
        self.assertEqual(explain.calls_missing_decay(
            "Based on the image, there is an indication of tooth decay on tooth 17.", ["17"]),
            ["17"])
        self.assertEqual(explain.calls_missing_decay(MISSING_TEXT, ["17"]), [])


class FakeKnowledge:
    def search(self, query):
        return []


class CheckedTurn(unittest.TestCase):
    def setUp(self):
        self.replies = []
        self.calls = 0
        self.real_chat = explain.chat

        def fake_chat(messages, model=None, **kwargs):
            self.calls += 1
            return self.replies.pop(0)
        explain.chat = fake_chat

    def tearDown(self):
        explain.chat = self.real_chat

    def session(self):
        return Explanation(GOOD, {}, knowledge=FakeKnowledge(),
                           assessment=copy.deepcopy(ASSESSMENT))

    def test_clean_reply_is_used_as_is(self):
        self.replies = [GOOD_TEXT]
        s = self.session()
        self.assertEqual(s.first_response(), GOOD_TEXT)
        self.assertEqual((self.calls, s.guardrail_log), (1, []))

    def test_bad_reply_is_rewritten_once(self):
        self.replies = ["You have a cavity. Take ibuprofen.", GOOD_TEXT]
        s = self.session()
        self.assertEqual(s.first_response(), GOOD_TEXT)
        self.assertEqual(self.calls, 2)
        self.assertEqual(s.guardrail_log[0]["after_retry"], [])

    def test_still_bad_after_rewrite_gives_fixed_text(self):
        self.replies = ["You have a cavity.", "Take 400 mg of ibuprofen."]
        s = self.session()
        text = s.first_response()
        self.assertEqual(text, fallback_text(ASSESSMENT))
        self.assertEqual(s.messages[-1]["content"], text)  # history holds what the user saw

    def test_follow_up_answers_are_checked_too(self):
        self.replies = [GOOD_TEXT, "Amoxicillin 500 mg.", "Amoxicillin."]
        s = self.session()
        s.first_response()
        self.assertIn("ask a dentist or pharmacist", s.ask("what antibiotic should I take?"))

    def test_follow_up_that_invents_a_pain_side_is_rewritten(self):
        clean = "You did not tell us where it hurts. A dentist can check which tooth it is."
        self.replies = [GOOD_TEXT, "Your toothache is on the upper right side (tooth 16).", clean]
        s = self.session()                                # symptoms {}: location unknown
        s.first_response()
        self.assertEqual(s.ask("which side is my toothache on?"), clean)
        self.assertIn("pain", s.guardrail_log[-1]["first"][0])

    def test_follow_up_that_repeats_the_first_response_is_rewritten(self):
        first = ("We looked at your two photos. " + GOOD_TEXT
                 + " Occlusal photos cannot show surfaces between teeth.")
        answer = "A cavity is a small hole in the hard outer layer of a tooth."
        self.replies = [first, "Good question. " + first, answer]
        s = self.session()
        s.first_response()
        self.assertEqual(s.ask("what is a cavity?"), answer)
        self.assertEqual(self.calls, 3)
        self.assertIn("follow-up question", s.messages[-2]["content"])
        self.assertEqual(s.messages[-1]["content"], answer)

    def test_a_follow_up_still_echoing_is_kept_not_replaced_by_the_fallback(self):
        first = "We looked at your two photos. " + GOOD_TEXT
        self.replies = [first, first, first]
        s = self.session()
        s.first_response()
        self.assertEqual(s.ask("what is a cavity?"), first)
        self.assertEqual(s.guardrail_log[-1]["after_retry"], ["repeats the first response"])

    def test_a_short_overlap_is_not_an_echo(self):
        first = ("We looked at your two photos. " + GOOD_TEXT
                 + " Occlusal photos cannot show surfaces between teeth.")
        self.assertFalse(explain.echoes("See a dentist within 7 days. That is the advice.", first))
        self.assertTrue(explain.echoes("Sure. " + first, first))

    def missing_session(self):
        return Explanation(MISSING, {}, knowledge=FakeKnowledge(),
                           assessment=copy.deepcopy(MISSING_ASSESSMENT))

    def test_missing_tooth_needs_no_decay_phrase(self):
        self.replies = [MISSING_TEXT]
        s = self.missing_session()
        self.assertEqual(s.first_response(), MISSING_TEXT)
        self.assertEqual((self.calls, s.guardrail_log), (1, []))
        self.assertIn("appears to be missing: 17", s.messages[1]["content"])

    def test_missing_tooth_called_decay_ends_in_the_missing_fallback(self):
        bad = "Based on the image, there is an indication of tooth decay on tooth 17."
        self.replies = [bad, bad]
        s = self.missing_session()
        text = s.first_response()
        self.assertEqual(text, fallback_text(MISSING_ASSESSMENT, MISSING))
        self.assertNotIn("decay", text.lower())

    def test_assessment_passed_in_is_the_one_explained(self):
        self.replies = [GOOD_TEXT]
        s = self.session()
        s.first_response()
        self.assertEqual(s.assessment["headline"], "See a dentist within 7 days")
        self.assertIn('"schema_version": "2.0"', s.messages[1]["content"])


class FollowUpRedFlag(unittest.TestCase):
    """Design §1.6: a red flag reported after the result still reaches EMERGENCY."""

    def setUp(self):
        self.replies = []
        self.extractions = []
        self.real_chat = explain.chat

        def fake_chat(messages, model=None, schema=None, **kwargs):
            if schema is not None:                     # the red-flag extraction call
                self.extractions.append(messages)
                return self.extractions_out.pop(0)
            return self.replies.pop(0)
        self.extractions_out = []
        explain.chat = fake_chat

    def tearDown(self):
        explain.chat = self.real_chat

    def extraction(self, **fields):
        out = {f: {"value": None, "quote": None} for f in explain.rules.RED_FLAG_FIELDS}
        out.update({f: {"value": v, "quote": q} for f, (v, q) in fields.items()})
        out["notes"] = {"value": None, "quote": None}
        return json.dumps(out)

    def session(self):
        return Explanation(GOOD, {"pain_present": True}, knowledge=FakeKnowledge(),
                           allow_unreviewed=True, assessment=copy.deepcopy(ASSESSMENT))

    def test_swelling_reported_after_the_result_escalates(self):
        s = self.session()
        self.extractions_out = [self.extraction(swelling=(True, "my face is swelling now"))]
        answer = s.ask("my face is swelling now, is that bad?")
        self.assertEqual(s.assessment["urgency"], "EMERGENCY")
        self.assertEqual(s.assessment["decided_by"], "red_flag_floor")
        self.assertIn("hospital", answer.lower())
        self.assertIs(s.symptoms["swelling"], True)
        self.assertEqual(self.replies, [])          # no prose call was made

    def test_ordinary_question_costs_no_extra_call(self):
        s = self.session()
        self.replies = ["A cavity is a hole in the tooth surface."]
        s.ask("what is a cavity?")
        self.assertEqual(self.extractions, [])      # keywords didn't fire
        self.assertEqual(s.assessment["urgency"], "SOON")

    def test_keyword_hit_without_the_patient_saying_it_does_not_escalate(self):
        # "swelling" appears, but as a question about the word, and the
        # extraction finds nothing the patient reported.
        s = self.session()
        self.extractions_out = [self.extraction()]
        self.replies = ["Swelling means the area puffs up."]
        s.ask("what does swelling mean?")
        self.assertEqual(len(self.extractions), 1)  # checked
        self.assertEqual(s.assessment["urgency"], "SOON")   # not escalated

    def test_an_invented_quote_does_not_escalate(self):
        s = self.session()
        self.extractions_out = [self.extraction(fever=(True, "I have a fever of 39"))]
        self.replies = ["I can only go on what you have told me."]
        s.ask("does a fever matter here?")
        self.assertEqual(s.assessment["urgency"], "SOON")
        self.assertIsNone(s.symptoms.get("fever"))


if __name__ == "__main__":
    unittest.main()
