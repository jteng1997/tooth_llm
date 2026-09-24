"""Unit tests for src/check_e2e.py (Test 5 end-to-end harness). No model: the
extractor and the triage model are mocks. Keys are synthetic, built against
the real protocol; one skip-if-absent test runs the local e2e keys.

    .venv/Scripts/python -m unittest discover -s tests -p "test_check_e2e.py" -v
"""
import copy
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import check_e2e as e2e  # noqa: E402
import check_triage as ct  # noqa: E402

PROTOCOL, ERR = ct.load_protocol()
RED = ("difficulty_swallowing_or_breathing", "chest_pain_or_breathless", "swelling", "fever",
       "systemically_unwell", "recent_trauma", "bleeding_uncontrolled", "exceeded_pain_relief_dose")


def expected_questions(s):
    qs = PROTOCOL.questions
    asked = [q.id for q in qs if q.group == "A"]
    if any(s.get(f) is True for f in RED) or not s.get("pain_present"):
        return asked
    return asked + [q.id for q in qs if q.group == "B"] + [q.id for q in qs if q.input == "chat"]


def make_key(level, criteria, facts=("a fact",), **symptoms):
    s = {"schema_version": "1.2", **{f: False for f in RED}, "pain_present": False,
         "persistent_ulcer": False, "broken_filling_or_tooth": False, "pus_or_discharge": False,
         "pain_relief_effect": None, "pain_severity": None,
         "pain_triggers": None, "pain_lingers_over_30s": None, "pain_wakes_at_night": None,
         "pain_on_biting": None, "recent_extraction": None, "location": None, "duration_days": None,
         "bleeding_gums": None, "swelling_features": None, "trauma_features": None}
    s.update(symptoms)
    return {"id": "T001", "key_level": level, "criteria_met": list(criteria), "boundary": False,
            "facts": list(facts), "symptoms": s, "expected_questions": expected_questions(s),
            "visual_summary": {"images_usable": True, "flagged_teeth": [], "unexpected_missing_teeth": []}}


PAIN = dict(pain_present=True, pain_lingers_over_30s=False, pain_wakes_at_night=False,
            pain_on_biting=False, recent_extraction=False, pain_severity="mild",
            pain_triggers=["cold"], location="lower_left", duration_days=4)
URGENT_KEY = make_key("URGENT", ["U1", "S1"], **{**PAIN, "pain_relief_effect": "not_helped"})
ROUTINE_KEY = make_key("ROUTINE", [])
# Protocol v0.2: a broken filling is a checklist-A row (Q20), no longer narrative.
BROKEN_FILLING_KEY = make_key("SOON", ["S3"], facts=["a filling fell out, no pain"],
                              broken_filling_or_tooth=True)


def run(key, opening="drop", extract=None, text=None):
    text = text or e2e.placeholder_text(key)
    extract = extract or e2e.oracle_extractor(key, PROTOCOL)
    result = e2e.run_case(key, text, PROTOCOL, extract, e2e.mock_triage, "mock", opening)
    att = e2e.attribute(key, result, PROTOCOL, opening) if result["final"] != key["key_level"] else None
    return result, att


@unittest.skipIf(ERR, f"protocol does not load: {ERR}")
class Cases(unittest.TestCase):
    def test_keys_are_protocol_consistent(self):
        for k in (URGENT_KEY, ROUTINE_KEY, BROKEN_FILLING_KEY):
            case = ct._case_from_key(k, {"author": "t"})
            self.assertEqual(ct._check_key(case, PROTOCOL), [], k["key_level"])

    def test_oracle_path_agrees(self):
        result, att = run(URGENT_KEY)
        self.assertIsNone(att)
        self.assertEqual(result["final"], "URGENT")
        self.assertEqual(result["symptoms"]["pain_relief_effect"], "not_helped")
        self.assertEqual(set(result["questions_shown"]), set(URGENT_KEY["expected_questions"]))
        self.assertEqual(result["unscripted"], [])

    def test_no_pain_stops_after_checklist_a(self):
        result, att = run(ROUTINE_KEY)
        self.assertIsNone(att)
        self.assertEqual(result["chat_asked"], [])

    def test_red_flag_stops_at_once(self):
        key = make_key("EMERGENCY", ["E3"], fever=True)
        key["emergency_route"] = "medical"
        result, att = run(key)
        self.assertIsNone(att)
        self.assertEqual((result["final"], result["decided_by"]), ("EMERGENCY", "red_flag_floor"))
        self.assertFalse(result["model_called"])

    def test_extraction_fault_is_attributed_to_extraction(self):
        oracle = e2e.oracle_extractor(URGENT_KEY, PROTOCOL)

        def drops_relief(messages, schema):
            out = json.loads(oracle(messages, schema))
            out["pain_relief_effect"] = {"value": None, "quote": None}
            return json.dumps(out)
        result, att = run(URGENT_KEY, extract=drops_relief)
        self.assertEqual(result["final"], "SOON")
        self.assertEqual(att["proposed"], "extraction")
        self.assertEqual([d["field"] for d in att["evidence"]["field_diffs"]], ["pain_relief_effect"])
        self.assertIn("Q10", result["reasked"])   # unsettled -> asked again once

    def test_missing_question_is_attributed_to_the_interview_first(self):
        key = copy.deepcopy(URGENT_KEY)
        key["expected_questions"].append("Q99")
        oracle = e2e.oracle_extractor(key, PROTOCOL)

        def drops_relief(messages, schema):
            out = json.loads(oracle(messages, schema))
            out["pain_relief_effect"] = {"value": None, "quote": None}
            return json.dumps(out)
        _, att = run(key, extract=drops_relief)
        self.assertEqual(att["proposed"], "interview")       # first failure in the chain wins
        self.assertEqual(att["evidence"]["missing_questions"], ["Q99"])
        self.assertTrue(att["evidence"]["field_diffs"])       # still reported as evidence
        self.assertIsNone(att["research_pm_bucket"])

    def test_broken_filling_on_the_checklist_is_caught_by_code(self):
        # v0.2: S3 is the Q20 checklist row, so neither the opening nor the model matters
        for opening in ("drop", "prepend"):
            with self.subTest(opening=opening):
                result, att = run(BROKEN_FILLING_KEY, opening=opening)
                self.assertIsNone(att)
                self.assertEqual((result["final"], result["protocol_check"]), ("SOON", "SOON"))
                self.assertIn("Q20", result["questions_shown"])
                self.assertEqual(result["chat_asked"], [])

    def test_narrative_attribution_branch(self):
        # No narrative criterion is left in protocol v0.2; the harness branch is
        # kept for any future one, so it is tested with a stub criterion.
        from types import SimpleNamespace
        stub = SimpleNamespace(criterion=lambda c: SimpleNamespace(kind="narrative" if c == "N9"
                                                                   else "structured"))
        key = make_key("SOON", ["N9"])
        result = {"questions_shown": list(key["expected_questions"]), "chat_asked": [],
                  "symptoms": dict(key["symptoms"])}
        att = e2e.attribute(key, result, stub, "drop")
        self.assertEqual((att["proposed"], att["evidence"]["narrative_without_a_turn"]),
                         ("interview", ["N9"]))
        self.assertEqual(e2e.attribute(key, result, stub, "prepend")["proposed"], "triage")

    def test_unscripted_question_gets_not_sure(self):
        text = e2e.placeholder_text(URGENT_KEY)
        del text["script"]["Q11"]
        result, _ = run(URGENT_KEY, text=text)
        self.assertEqual(result["unscripted"], ["Q11", "Q11"])   # asked, then re-asked
        self.assertIsNone(result["symptoms"]["pain_severity"])

    def test_checklist_null_on_a_yes_no_row_is_refused(self):
        key = copy.deepcopy(ROUTINE_KEY)
        key["symptoms"]["fever"] = None
        with self.assertRaises(ValueError):
            run(key)


@unittest.skipIf(ERR, f"protocol does not load: {ERR}")
class Scoring(unittest.TestCase):
    def test_summary_counts(self):
        keys = []
        for i, k in enumerate((URGENT_KEY, ROUTINE_KEY, BROKEN_FILLING_KEY), 1):
            k = copy.deepcopy(k)
            k["id"] = f"T{i:03d}"
            keys.append(k)
        # a fourth case the stub triage model misses: URGENT key, pain relief
        # not helped, with the extractor dropping that field
        miss = copy.deepcopy(URGENT_KEY)
        miss["id"] = "T004"
        keys.append(miss)
        texts = {k["id"]: e2e.placeholder_text(k) for k in keys}

        def extract_for(k):
            oracle = e2e.oracle_extractor(k, PROTOCOL)
            if k["id"] != "T004":
                return oracle

            def drops_relief(messages, schema):
                out = json.loads(oracle(messages, schema))
                out["pain_relief_effect"] = {"value": None, "quote": None}
                return json.dumps(out)
            return drops_relief
        s = e2e.evaluate(keys, texts, PROTOCOL, "mock", extract_for, e2e.mock_triage, "drop")
        self.assertEqual(s["systems"]["final"]["n_scored"], 4)
        self.assertEqual(s["systems"]["final"]["under_ids"], ["T004"])
        self.assertEqual(s["attribution"]["proposed"], {"extraction": 1})
        self.assertEqual(s["extraction"]["cells"], 10)          # two cases reached the chat
        self.assertEqual(s["extraction"]["wrong_cells"], 1)


@unittest.skipUnless((REPO_ROOT / "labels" / "heldout" / "e2e_keys.json").exists() and not ERR,
                     "held-out e2e keys are local-only")
class HeldoutMockRun(unittest.TestCase):
    """With a perfect extractor and a triage model that adds nothing, the
    end-to-end result must equal code's own level on the keys (60/60 under
    protocol v0.2, where no criterion is narrative), and the interview must
    ask exactly what every key expects."""

    def test_mock_run(self):
        keys = json.loads(e2e.E2E_KEYS.read_text(encoding="utf-8"))["keys"]
        texts = {k["id"]: e2e.placeholder_text(k) for k in keys}
        s = e2e.evaluate(keys, texts, PROTOCOL, "mock", lambda k: e2e.oracle_extractor(k, PROTOCOL),
                         e2e.mock_triage, "drop")
        final = s["systems"]["final"]
        self.assertEqual((final["n_scored"], final["agree"], final["under"]), (60, 60, 0))
        self.assertEqual(s["interview"]["cases_with_missing_questions"], 0)
        self.assertEqual(s["interview"]["cases_with_extra_questions"], 0)
        self.assertEqual(s["extraction"]["wrong_cells"], 0)
        self.assertEqual(s["attribution"]["n_misses"], 0)


if __name__ == "__main__":
    unittest.main()
