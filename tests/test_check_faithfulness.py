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


class Quantities(unittest.TestCase):
    """A number that counts hours, days or teeth is not an FDI tooth (#19)."""

    def test_time_and_counts_are_not_teeth(self):
        for text in ("See a dentist within 24 hours.", "Book within the next 24-hour window.",
                     "The photo showed 14 teeth.", "It has hurt for 21 days.",
                     "Within 12 Hours, please.", "for 11 weeks", "about 18 months", "for 13 years"):
            self.assertEqual(cf.mentioned_teeth(text), set(), text)

    def test_real_teeth_still_match(self):
        self.assertEqual(cf.mentioned_teeth("Possible decay on tooth 24."), {"24"})
        self.assertEqual(cf.mentioned_teeth("Tooth 24 (upper left first premolar): see a dentist "
                                            "within 24 hours."), {"24"})
        self.assertEqual(cf.mentioned_teeth("Teeth 14 and 24 may have decay."), {"14", "24"})
        self.assertEqual(cf.mentioned_teeth("A cavity on the upper left first premolar."), {"24"})
        self.assertEqual(cf.mentioned_teeth("Possible decay on 36."), {"36"})

    def test_24_hours_no_longer_hides_an_omitted_tooth_24(self):
        # evaluate() scores omission as flagged - mentioned_teeth(text)
        text = "Nothing we can name. See a dentist within 24 hours. This is a screening aid."
        self.assertEqual({"24"} - cf.mentioned_teeth(text), {"24"})


class Unreported(unittest.TestCase):
    """A tooth told as a finding that the assessment did not flag (#22)."""

    def test_sub_threshold_tooth_told_as_a_finding(self):
        text = ("Based on the image, there is an indication of tooth decay on tooth 36 (lower left "
                "first molar). There is also an indication of a cavity on tooth 21.")
        self.assertEqual(cf.unreported(text, {"36"}), ["21"])
        self.assertEqual(cf.unreported("There is something unusual on tooth 11.", set()), ["11"])
        self.assertEqual(cf.unreported("A possible other issue on tooth 26.", set()), ["26"])
        self.assertEqual(cf.unreported("There is an indication of a filling on tooth 12.", set()), ["12"])

    def test_flagged_teeth_are_fine(self):
        text = "Based on the image, there is an indication of tooth decay on tooth 36 and tooth 46."
        self.assertEqual(cf.unreported(text, {"36", "46"}), [])
        self.assertEqual(cf.unreported("Nothing reached the level we report. See a dentist "
                                       "within 24 hours.", set()), [])

    def test_plain_word_name_counts(self):
        self.assertEqual(cf.unreported("There may be decay on the upper left central incisor.", set()),
                         ["21"])

    def test_retake_and_limitation_sentences_are_not_findings(self):
        text = ("The upper photo could not be used, so please retake it with tooth 16 in view. "
                "These photos show the biting surfaces only, so tooth 26 may look different.")
        self.assertEqual(cf.unreported(text, set()), [])
        # the same tooth in a sentence that does claim a finding is counted
        self.assertEqual(cf.unreported(text + " There is a possible cavity on tooth 26.", set()), ["26"])

    def test_scored_in_evaluate_first_response_and_follow_up(self):
        findings = base_findings()
        findings["teeth"]["21"]["detections"] = [{"type": "caries", "confidence": 0.25}]
        case = {"id": "X8", "note": "t", "findings": findings, "symptoms": symptoms(),
                "follow_ups": ["Is this serious?"]}
        told = Modes.TEXT + " There is also an indication of a cavity on tooth 21."
        import explain
        original = explain.chat
        explain.chat = Scripted(told, retry=told, follow="Tooth 21 may have a small cavity.",
                                follow_retry="Tooth 21 may have a small cavity.")
        try:
            r = cf.evaluate([case], "stub", knowledge=NoKnowledge(), verbose=False,
                            triage_llm=MOCK_TRIAGE)
        finally:
            explain.chat = original
        c = r["cases"][0]
        self.assertEqual(c["flagged"], [])                      # 0.25 is below the threshold
        self.assertEqual(c["hallucinated"], [])                 # the old check passes it
        # A #22 guardrail may replace the text with the fallback; the model's
        # own text, when it is what the patient gets, must be counted.
        fu = c["follow_ups"][0]
        self.assertEqual(c["unreported"], [] if c["fallback"] else ["21"])
        self.assertEqual(fu["unreported"], [] if fu["fallback"] else ["21"])
        self.assertEqual((r["unreported"], r["follow_up"]["unreported"]),
                         (int(not c["fallback"]), int(not fu["fallback"])))
        self.assertEqual(cf.unreported(told, cf.reportable(
            {"urgency": "ROUTINE", "flagged_teeth": [], "reasons": []}, findings)), ["21"])


class NoKnowledge:
    def search(self, query, k=4):
        return []


MOCK_TRIAGE = lambda messages, schema: '{"criteria_met": [], "level": "ROUTINE", "uncertain": false}'  # noqa: E731


def base_findings(missing=(), caries=()):
    teeth = {f"{q}{p}": {"present": True, "detections": []} for q in (1, 2, 3, 4) for p in range(1, 8)}
    for t in missing:
        teeth[t] = {"present": False, "detections": []}
    for t in caries:
        teeth[t]["detections"] = [{"type": "caries", "confidence": 0.9}]
    return {"schema_version": "1.0",
            "image_quality": {a: {"usable": True, "reasons": []} for a in ("upper", "lower")},
            "arches": {a: {"present": True, "teeth_detected": 14} for a in ("upper", "lower")},
            "teeth": teeth, "unassigned_detections": []}


def symptoms(**over):
    import eval_data
    s = {"schema_version": "1.2", **{f: False for f in eval_data.CHECKLIST_A}, "pain_present": False,
         **{f: None for f in eval_data.CHECKLIST_B}, "pain_relief_effect": None, "pain_severity": None,
         "pain_triggers": None, "location": None, "duration_days": None}
    s.update(over)
    return s


class Scripted:
    """explain.chat stand-in: first reply, retry reply and follow-up replies by turn."""

    def __init__(self, first, retry=None, follow=None, follow_retry=None):
        self.first, self.retry, self.follow, self.follow_retry = first, retry, follow, follow_retry

    def __call__(self, messages, model, *a, **kw):
        last = messages[-1]["content"]
        in_follow_up = any("User asks:" in m["content"] for m in messages if m["role"] == "user")
        if last.startswith("Rewrite your reply"):
            return (self.follow_retry if in_follow_up else self.retry) or self.first
        return self.follow if in_follow_up else self.first


class Modes(unittest.TestCase):
    def run_one(self, case, chat, mode="triage"):
        import explain
        original = explain.chat
        explain.chat = chat
        try:
            return cf.evaluate([case], "stub", knowledge=NoKnowledge(), verbose=False, mode=mode,
                               triage_llm=MOCK_TRIAGE)
        finally:
            explain.chat = original

    TEXT = ("We looked at your two photos. Nothing in these photos reached the level we report. "
            "Book a routine check-up. This is a screening aid, not a diagnosis.")

    def test_triage_mode_does_not_flag_a_missing_tooth_legacy_does(self):
        case = {"id": "X1", "note": "t", "findings": base_findings(missing=["17"]),
                "symptoms": symptoms(), "follow_ups": []}
        tri = self.run_one(case, Scripted(self.TEXT), "triage")
        self.assertEqual(tri["cases"][0]["flagged"], [])
        leg = self.run_one({**case, "symptoms": None}, Scripted(self.TEXT), "legacy")
        self.assertEqual(leg["cases"][0]["flagged"], ["17"])     # rules.py R8

    def test_places_pain_fires_on_an_unnamed_side_and_not_on_the_named_one(self):
        wrong = self.TEXT + " The pain on your upper right side is probably from that tooth."
        case = {"id": "X2", "note": "t", "findings": base_findings(),
                "symptoms": symptoms(pain_present=True, location="lower_left"), "follow_ups": []}
        r = self.run_one(case, Scripted(wrong, retry=self.TEXT))
        self.assertEqual((r["places_pain"], r["guardrail_retry"], r["guardrail_fallback"]), (1, 1, 0))
        allowed = self.TEXT + " You said the pain is on the lower left."
        r = self.run_one(case, Scripted(allowed))
        self.assertEqual((r["places_pain"], r["guardrail_retry"]), (0, 0))

    def test_follow_up_echo_is_counted(self):
        case = {"id": "X3", "note": "t", "findings": base_findings(), "symptoms": symptoms(),
                "follow_ups": ["Is this serious?"]}
        r = self.run_one(case, Scripted(self.TEXT, follow=self.TEXT, follow_retry=self.TEXT))
        fu = r["follow_up"]
        self.assertEqual((fu["n"], fu["echo"], fu["echo_retry"], fu["guardrail_fallback"]), (1, 1, 1, 0))
        r = self.run_one(case, Scripted(self.TEXT, follow="It is not an emergency; a check-up will tell."))
        self.assertEqual((r["follow_up"]["echo"], r["follow_up"]["echo_retry"]), (0, 0))

    def test_partial_retake_with_urgent_symptoms_scores_teeth_as_usual(self):
        findings = base_findings(caries=["36"])
        findings["image_quality"]["upper"] = {"usable": False, "reasons": ["no_teeth_detected"]}
        case = {"id": "X6", "note": "t", "findings": findings, "follow_ups": [],
                "symptoms": symptoms(pain_present=True, lingering_pain=True)}
        urgent = lambda messages, schema: ('{"criteria_met": [], "level": "URGENT", '  # noqa: E731
                                           '"uncertain": false}')
        good = ("We looked at your two photos. The upper photo could not be used, so please "
                "retake it. Based on the image, there is an indication of tooth decay on tooth 36 "
                "(lower left first molar). See a dentist within 24 hours.")
        import explain
        original = explain.chat
        explain.chat = Scripted(good)
        try:
            r = cf.evaluate([case], "stub", knowledge=NoKnowledge(), verbose=False, triage_llm=urgent)
        finally:
            explain.chat = original
        c = r["cases"][0]
        self.assertEqual((c["urgency"], c["flagged"]), ("URGENT", ["36"]))
        self.assertEqual((c["hallucinated"], c["omitted"], c["contradiction"]), ([], [], ""))
        self.assertEqual((r["retake_required"], r["retake_not_requested"]), (1, 0))
        self.assertEqual((c["guardrail_log"], c["fallback"]), ([], False))   # the model's own text

        # a text that keeps the urgency but never asks for new photos: the
        # metric fails it, and the urgency check alone would not
        silent = good.replace("The upper photo could not be used, so please retake it. ", "")
        self.assertFalse(cf.retake_requested(silent))
        self.assertEqual(cf.contradiction(silent, "URGENT"), "")

        # end to end, the #18 guardrail catches it: retry, then the fallback,
        # which states the headline, names tooth 36 and asks for the retake
        explain.chat = Scripted(silent)
        try:
            r = cf.evaluate([case], "stub", knowledge=NoKnowledge(), verbose=False, triage_llm=urgent)
        finally:
            explain.chat = original
        c = r["cases"][0]
        self.assertTrue(any(p.startswith("does not ask for a retake")
                            for e in c["guardrail_log"] for p in e["first"]), c["guardrail_log"])
        self.assertTrue(c["fallback"])
        self.assertTrue(cf.retake_requested(c["text"]), c["text"])
        self.assertEqual((r["retake_required"], r["retake_not_requested"]), (1, 0))
        self.assertEqual((c["hallucinated"], c["omitted"], c["contradiction"]), ([], [], ""))

    def test_retake_not_requested_is_not_scored_on_good_photos(self):
        case = {"id": "X7", "note": "t", "findings": base_findings(), "symptoms": symptoms(),
                "follow_ups": []}
        r = self.run_one(case, Scripted(self.TEXT))
        self.assertEqual((r["retake_required"], r["retake_not_requested"]), (0, 0))

    def test_retake_wordings(self):
        self.assertTrue(cf.retake_requested("The photos could not be used, so please take them again."))
        self.assertTrue(cf.retake_requested("Please retake the upper photo."))
        self.assertTrue(cf.retake_requested("Take a new photo of your lower teeth."))
        self.assertFalse(cf.retake_requested("See a dentist within 24 hours."))

    def test_follow_up_hallucination_and_discouragement(self):
        case = {"id": "X4", "note": "t", "findings": base_findings(), "symptoms": symptoms(),
                "follow_ups": ["Do I really need to go to a dentist?"]}
        bad = "Tooth 48 looks fine, so you don't need to see a dentist."
        r = self.run_one(case, Scripted(self.TEXT, follow=bad, follow_retry=bad))
        fu = r["follow_up"]
        self.assertEqual((fu["hallucination"], fu["discourages"]), (1, 1))
        self.assertEqual(r["cases"][0]["follow_ups"][0]["hallucinated"], ["48"])


class SyntheticV2(unittest.TestCase):
    def test_legacy_cases_unchanged_and_v2_shape(self):
        import eval_data
        old, new = eval_data.generate(60, 0), eval_data.generate_v2(60, 0)
        self.assertEqual([c["findings"] for c in old], [c["findings"] for c in new])
        self.assertEqual(old, eval_data.generate(60, 0))
        pain = [c for c in new if c["symptoms"]["pain_present"]]
        self.assertGreater(sum(bool(c["symptoms"]["location"]) for c in pain), 5)
        for c in new:
            s = c["symptoms"]
            self.assertEqual(len(c["follow_ups"]), 2)
            if not s["pain_present"]:
                self.assertTrue(all(s[f] is None for f in ("location", "pain_severity", "duration_days")))
        self.assertEqual(new, eval_data.generate_v2(60, 0))


if __name__ == "__main__":
    unittest.main()
