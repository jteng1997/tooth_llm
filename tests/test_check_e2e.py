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
# Protocol v0.3 (docs/plans/protocol-v0.3/README.md §2): pain relief decides the
# pain level. helped or not tried -> S1 SOON; not helped -> U1 URGENT;
# unanswered -> U10 URGENT. Lingering or night pain no longer changes it.
SOON_KEY = make_key("SOON", ["S1"], **{**PAIN, "pain_relief_effect": "helped"})
SEVERE_KEY = make_key("URGENT", ["U2", "S1"],
                      **{**PAIN, "pain_relief_effect": "helped", "pain_severity": "severe"})
RELIEF_TABLE = (("helped", "SOON", ["S1"]), ("not_tried", "SOON", ["S1"]),
                ("not_helped", "URGENT", ["U1", "S1"]), (None, "URGENT", ["U10", "S1"]))
ROUTINE_KEY = make_key("ROUTINE", [])
# Protocol v0.2: a broken filling is a checklist-A row (Q20), no longer narrative.
BROKEN_FILLING_KEY = make_key("SOON", ["S3"], facts=["a filling fell out, no pain"],
                              broken_filling_or_tooth=True)


def dropping(field, oracle):
    """The oracle extractor, but `field` is never settled."""
    def llm(messages, schema):
        out = json.loads(oracle(messages, schema))
        out[field] = {"value": None, "quote": None}
        return json.dumps(out)
    return llm


def run(key, opening="drop", extract=None, text=None):
    text = text or e2e.placeholder_text(key)
    extract = extract or e2e.oracle_extractor(key, PROTOCOL)
    result = e2e.run_case(key, text, PROTOCOL, extract, e2e.mock_triage, "mock", opening)
    att = e2e.attribute(key, result, PROTOCOL, opening) if result["final"] != key["key_level"] else None
    return result, att


@unittest.skipIf(ERR, f"protocol does not load: {ERR}")
class Cases(unittest.TestCase):
    def test_keys_are_protocol_consistent(self):
        for k in (URGENT_KEY, SOON_KEY, SEVERE_KEY, ROUTINE_KEY, BROKEN_FILLING_KEY):
            case = ct._case_from_key(k, {"author": "t"})
            self.assertEqual(ct._check_key(case, PROTOCOL), [], k["key_level"])

    def test_relief_answer_decides_the_pain_level(self):
        # v0.3 table (protocol-v0.3/README.md §2), end to end through the
        # interview; with and without lingering, night and spontaneous pain,
        # which v0.3 no longer counts (U5/U6 retired).
        extras = {"plain": {},
                  "lingering_night": {"pain_lingers_over_30s": True, "pain_wakes_at_night": True,
                                      "pain_triggers": ["cold", "spontaneous"]}}
        for relief, level, criteria in RELIEF_TABLE:
            for name, extra in extras.items():
                with self.subTest(relief=relief, pain=name):
                    key = make_key(level, criteria, **{**PAIN, **extra, "pain_relief_effect": relief})
                    case = ct._case_from_key(key, {"author": "t"})
                    self.assertEqual(ct._check_key(case, PROTOCOL), [])
                    result, att = run(key)
                    self.assertIsNone(att)
                    self.assertEqual((result["final"], result["protocol_check"]), (level, level))
                    self.assertEqual(result["symptoms"]["pain_relief_effect"], relief)

    def test_dropped_relief_is_never_reassuring(self):
        # v0.3 U10: relief not helped, extractor loses it -> still URGENT, no miss
        result, att = run(URGENT_KEY, extract=dropping("pain_relief_effect",
                                                       e2e.oracle_extractor(URGENT_KEY, PROTOCOL)))
        self.assertIsNone(att)
        self.assertIsNone(result["symptoms"]["pain_relief_effect"])
        self.assertEqual((result["final"], result["protocol_check"]), ("URGENT", "URGENT"))

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
        # severe pain lost: U2 URGENT key, S1 SOON result (under)
        result, att = run(SEVERE_KEY, extract=dropping("pain_severity",
                                                       e2e.oracle_extractor(SEVERE_KEY, PROTOCOL)))
        self.assertEqual(result["final"], "SOON")
        self.assertEqual(att["proposed"], "extraction")
        self.assertEqual([d["field"] for d in att["evidence"]["field_diffs"]], ["pain_severity"])
        self.assertIn("Q11", result["reasked"])   # unsettled -> asked again once
        # relief lost on a SOON key: v0.3 U10 makes it URGENT (over), still extraction's
        result, att = run(SOON_KEY, extract=dropping("pain_relief_effect",
                                                     e2e.oracle_extractor(SOON_KEY, PROTOCOL)))
        self.assertEqual(result["final"], "URGENT")
        self.assertEqual(att["proposed"], "extraction")
        self.assertEqual([d["field"] for d in att["evidence"]["field_diffs"]], ["pain_relief_effect"])
        self.assertIn("Q10", result["reasked"])

    def test_missing_question_is_attributed_to_the_interview_first(self):
        key = copy.deepcopy(SEVERE_KEY)
        key["expected_questions"].append("Q99")
        result, att = run(key, extract=dropping("pain_severity", e2e.oracle_extractor(key, PROTOCOL)))
        self.assertEqual(result["final"], "SOON")
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
                                                                   else "structured"),
                               questions=PROTOCOL.questions)
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
class SkippedVersusNeverAsked(unittest.TestCase):
    """Spec §3 bucket 1 is a question never put. A chat question the interview
    skipped because an earlier answer already settled its field is not that."""

    def result(self, shown_minus, **symptoms):
        return {"questions_shown": [q for q in URGENT_KEY["expected_questions"] if q not in shown_minus],
                "symptoms": {**URGENT_KEY["symptoms"], **symptoms}, "chat_asked": []}

    def test_split(self):
        r = self.result({"Q11", "Q12"}, pain_severity="mild", pain_triggers=None)
        never, settled = e2e.unasked(URGENT_KEY, r, PROTOCOL)
        self.assertEqual((never, settled), (["Q12"], ["Q11"]))

    def test_a_skip_alone_is_not_the_interview_bucket(self):
        r = self.result({"Q11"}, pain_severity="mild", pain_relief_effect=None)
        att = e2e.attribute(URGENT_KEY, r, PROTOCOL, "prepend")
        self.assertEqual(att["evidence"]["missing_questions"], [])
        self.assertEqual(att["evidence"]["skipped_already_settled"], ["Q11"])
        self.assertEqual(att["proposed"], "extraction")        # the relief field differs
        r = self.result({"Q12"}, pain_triggers=None)
        self.assertEqual(e2e.attribute(URGENT_KEY, r, PROTOCOL, "prepend")["proposed"], "interview")

    def test_counts(self):
        keys = {}
        results = []
        for cid, shown_minus, sym in (("A", {"Q11"}, {"pain_severity": "mild"}),
                                      ("B", {"Q11", "Q18"}, {"pain_severity": "mild", "duration_days": 4}),
                                      ("C", {"Q12"}, {"pain_triggers": None}),
                                      ("D", set(), {})):
            keys[cid] = URGENT_KEY
            results.append({"id": cid, **self.result(shown_minus, **sym)})
        c = e2e.interview_counts(results, keys, PROTOCOL)
        self.assertEqual((c["cases_with_missing_questions"], c["questions_never_asked"],
                          c["cases_with_skipped_settled"], c["questions_skipped_settled"]), (1, 1, 2, 3))


@unittest.skipIf(ERR, f"protocol does not load: {ERR}")
class Scoring(unittest.TestCase):
    def test_summary_counts(self):
        keys = []
        for i, k in enumerate((URGENT_KEY, ROUTINE_KEY, BROKEN_FILLING_KEY), 1):
            k = copy.deepcopy(k)
            k["id"] = f"T{i:03d}"
            keys.append(k)
        # a fourth case the stub triage model misses: URGENT key, severe pain
        # (U2), with the extractor dropping the severity (v0.3: dropping the
        # relief answer would no longer lower it, U10)
        miss = copy.deepcopy(SEVERE_KEY)
        miss["id"] = "T004"
        keys.append(miss)
        texts = {k["id"]: e2e.placeholder_text(k) for k in keys}

        def extract_for(k):
            oracle = e2e.oracle_extractor(k, PROTOCOL)
            return dropping("pain_severity", oracle) if k["id"] == "T004" else oracle
        s = e2e.evaluate(keys, texts, PROTOCOL, "mock", extract_for, e2e.mock_triage, "drop")
        self.assertEqual(s["systems"]["final"]["n_scored"], 4)
        self.assertEqual(s["systems"]["final"]["under_ids"], ["T004"])
        self.assertEqual(s["systems"]["final"]["over_ids"], [])
        self.assertEqual(s["attribution"]["proposed"], {"extraction": 1})
        self.assertEqual(s["extraction"]["cells"], 10)          # two cases reached the chat
        self.assertEqual(s["extraction"]["wrong_cells"], 1)
        tc = s["triage_calls"]
        called = [r for r in s["cases"] if r["model_called"]]
        self.assertEqual(tc["n"], len(called))
        self.assertEqual(tc["llm_decided"], sum(r["decided_by"] == "llm" for r in called))
        self.assertEqual(tc["level_raised"], 0)          # the stub's ROUTINE cites nothing

    def test_triage_calls_counts_raised_apart(self):
        results = [{"id": "A", "model_called": True, "decided_by": "llm", "level_raised_from": None,
                    "llm_valid": True, "rejections": 0},
                   {"id": "B", "model_called": True, "decided_by": "llm_raised",
                    "level_raised_from": "SOON", "llm_valid": True, "rejections": 2},
                   {"id": "C", "model_called": True, "decided_by": "protocol_check",
                    "level_raised_from": "ROUTINE", "llm_valid": True, "rejections": 2},
                   {"id": "E", "model_called": True, "decided_by": "fallback_rules",
                    "level_raised_from": None, "llm_valid": False, "rejections": 2},
                   {"id": "D", "model_called": False, "decided_by": "red_flag_floor",
                    "level_raised_from": None, "llm_valid": False, "rejections": 0}]
        tc = e2e.triage_calls(results)
        self.assertEqual((tc["n"], tc["llm_decided"], tc["level_raised_ids"], tc["rejections"]),
                         (4, 1, ["B", "C"], 6))
        self.assertEqual(tc["level_raised_ci95"], ct.clopper_pearson(2, 4))
        # spec 9.9: the bar's count, llm_raised, and the sum under the first rule
        self.assertEqual((tc["fallback_rules"], tc["llm_raised"], tc["fallback_as_first_registered"],
                          tc["valid"]), (1, 1, 3, 3))
        self.assertEqual(tc["fallback_as_first_registered_ci95"], ct.clopper_pearson(3, 4))


def _with_severity(oracle, value):
    """The oracle extractor, but pain_severity is `value` (quoted from the Q11
    reply the oracle found) whenever the oracle settled it."""
    def llm(messages, schema):
        out = json.loads(oracle(messages, schema))
        if out.get("pain_severity", {}).get("value") is not None:
            out["pain_severity"]["value"] = value
        return json.dumps(out)
    return llm


@unittest.skipIf(ERR, f"protocol does not load: {ERR}")
class SeverityBlock(unittest.TestCase):
    """Pre-declared 2026-09-26: severity errors by direction, and the level
    moves they cause, as an extra block that leaves every other number alone."""

    def keys(self):
        mild = make_key("SOON", ["S1"], **{**PAIN, "pain_relief_effect": "helped"})
        severe = make_key("URGENT", ["U2", "S1"],
                          **{**PAIN, "pain_relief_effect": "helped", "pain_severity": "severe"})
        out = []
        for i, k in enumerate((mild, mild, severe, severe, ROUTINE_KEY), 1):
            k = copy.deepcopy(k)
            k["id"] = f"S{i:03d}"
            out.append(k)
        for k in out:
            case = ct._case_from_key(k, {"author": "t"})
            self.assertEqual(ct._check_key(case, PROTOCOL), [], k["id"])
        return out

    def run_all(self, keys, wrong):
        """wrong: {id: extracted severity}; everything else from the oracle."""
        texts = {k["id"]: e2e.placeholder_text(k) for k in keys}

        def extract_for(k):
            oracle = e2e.oracle_extractor(k, PROTOCOL)
            return _with_severity(oracle, wrong[k["id"]]) if k["id"] in wrong else oracle
        return e2e.evaluate(keys, texts, PROTOCOL, "mock", extract_for, e2e.mock_triage, "drop")

    def test_directions_ids_and_level_moves(self):
        s = self.run_all(self.keys(), {"S001": "severe", "S003": "moderate"})
        err, shift = s["severity"]["errors"], s["severity"]["level_shift"]
        self.assertEqual(err["n"], 4)                      # S005 has no pain: never reaches the chat
        self.assertEqual((err["n_key_below_severe"], err["n_key_severe"]), (2, 2))
        self.assertEqual((err["false_severe"], err["false_severe_ids"]), (1, ["S001"]))
        self.assertEqual((err["missed_severe"], err["missed_severe_ids"]), (1, ["S003"]))
        self.assertEqual(err["false_severe_ci95"], ct.clopper_pearson(1, 4))
        self.assertEqual(err["missed_severe_ci95_of_key_severe"], ct.clopper_pearson(1, 2))
        self.assertEqual(shift["n_severity_differs"], 2)
        for system in ("final", "protocol_check"):
            self.assertEqual((shift[system]["up_ids"], shift[system]["down_ids"]),
                             (["S001"], ["S003"]), system)
        # the pre-registered numbers are those of the same run's systems, untouched
        final = s["systems"]["final"]
        self.assertEqual((final["under_ids"], final["over_ids"]), (["S003"], ["S001"]))

    def test_null_extraction_is_a_missed_severe(self):
        s = self.run_all(self.keys(), {"S004": None})
        err = s["severity"]["errors"]
        self.assertEqual((err["missed_severe_ids"], err["false_severe"]), (["S004"], 0))
        self.assertEqual(s["severity"]["level_shift"]["final"]["down_ids"], ["S004"])

    def test_a_perfect_run_counts_nothing(self):
        # the checker must be able to report zero: nothing flagged on the oracle
        s = self.run_all(self.keys(), {})
        err, shift = s["severity"]["errors"], s["severity"]["level_shift"]
        self.assertEqual((err["false_severe"], err["missed_severe"], shift["n_severity_differs"]),
                         (0, 0, 0))

    def test_a_severity_diff_that_moves_nothing_is_not_a_shift(self):
        # mild -> moderate: pain_severity differs, the level cannot move
        s = self.run_all(self.keys(), {"S002": "moderate"})
        shift = s["severity"]["level_shift"]
        self.assertEqual(shift["n_severity_differs"], 1)
        self.assertEqual((shift["final"]["up"], shift["final"]["down"]), (0, 0))
        self.assertEqual(s["severity"]["errors"]["false_severe"], 0)

    def test_retake_is_not_placed_on_the_scale(self):
        results = [{"id": "X1", "chat_asked": ["Q11"], "symptoms": {"pain_severity": "severe"},
                    "protocol_on_key_symptoms": "SOON", "final": "RETAKE",
                    "protocol_check": "URGENT"}]
        by_id = {"X1": {"symptoms": {"pain_severity": "mild"}}}
        shift = e2e.severity_block(results, by_id)["level_shift"]
        self.assertEqual(shift["final"]["not_a_level_ids"], ["X1"])
        self.assertEqual(shift["protocol_check"]["up_ids"], ["X1"])

    def test_report_prints_the_block(self):
        import contextlib
        import io
        s = self.run_all(self.keys(), {"S001": "severe", "S003": "moderate"})
        s.update(mock=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            e2e.print_report(s, mock=True)
        text = buf.getvalue()
        self.assertIn("false severe  (key mild/moderate, got severe; raises urgency)  1/4", text)
        self.assertIn("missed severe (key severe, got other or null; lowers urgency)  1/4", text)
        self.assertIn("final           up 1/2 ['S001']  down 1/2 ['S003']", text)
        self.assertIn(f"as encoded in protocol v{PROTOCOL.version}, including", text)


@unittest.skipUnless((REPO_ROOT / "labels" / "heldout" / "e2e_keys.json").exists() and not ERR,
                     "held-out e2e keys are local-only")
class HeldoutMockRun(unittest.TestCase):
    """With a perfect extractor and a triage model that adds nothing, the
    end-to-end result must equal code's own level on the keys (60/60 under
    protocol v0.2, where no criterion is narrative), and the interview must
    ask exactly what every key expects. The keys are frozen on v0.2, so the
    run uses the pinned v0.2 protocol, not the live one."""

    def test_mock_run(self):
        data = json.loads(e2e.E2E_KEYS.read_text(encoding="utf-8"))
        keys = data["keys"]
        split = ct.key_file_split(data.get("_meta", {}), e2e.E2E_KEYS)
        protocol, path, err = ct.load_protocol_for(split)
        self.assertIsNone(err)
        self.assertEqual((split, path, protocol.version, str(data["_meta"]["protocol_version"])),
                         ("heldout", ct.HELDOUT_PROTOCOL_FILE, "0.2", "0.2"))
        texts = {k["id"]: e2e.placeholder_text(k) for k in keys}
        s = e2e.evaluate(keys, texts, protocol, "mock", lambda k: e2e.oracle_extractor(k, protocol),
                         e2e.mock_triage, "drop")
        self.assertEqual(s["protocol_version"], "0.2")
        final = s["systems"]["final"]
        self.assertEqual((final["n_scored"], final["agree"], final["under"]), (60, 60, 0))
        self.assertEqual(s["interview"]["cases_with_missing_questions"], 0)
        self.assertEqual(s["interview"]["cases_with_extra_questions"], 0)
        self.assertEqual(s["extraction"]["wrong_cells"], 0)
        self.assertEqual(s["attribution"]["n_misses"], 0)


if __name__ == "__main__":
    unittest.main()
