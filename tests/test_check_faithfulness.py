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
