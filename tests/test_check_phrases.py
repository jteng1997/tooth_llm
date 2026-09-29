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
                {"id": "D", "tuned": False, "ok": True, "severe": False},
                {"id": "C", "tuned": True, "ok": False, "severe": False}]
        s = cp.summarise(rows)
        ind, tun = s["independent"], s["tuned"]
        self.assertEqual((ind["n"], ind["correct"], ind["wrong_ids"]), (3, 2, ["B"]))
        self.assertEqual((ind["false_drops"], ind["false_keeps"]),
                         ({"n": 2, "k": 1, "ids": ["B"]}, {"n": 1, "k": 0, "ids": []}))
        self.assertEqual((tun["n"], tun["correct"], tun["false_keeps"]["ids"]), (1, 0, ["C"]))
        self.assertNotIn("unclear_not_scored", s)

    def test_unclear_cases_are_never_scored(self):
        case = {"id": "HU01", "severe": None, "unclear": True}
        self.assertIsNone(cp.score(case, "severe"))
        self.assertIsNone(cp.score(case, None))
        rows = [{"id": "A", "tuned": False, "ok": True, "severe": True, "got": "severe"},
                {"id": "HU01", "tuned": False, "ok": None, "severe": None, "got": "moderate"}]
        s = cp.summarise(rows)
        self.assertEqual(s["independent"]["n"], 1)                  # not in n
        self.assertEqual(s["unclear_not_scored"], {"HU01": "moderate"})

    def test_breakout_is_its_own_block(self):
        rows = [{"id": "H1", "tuned": False, "ok": False, "severe": True, "got": "moderate"},
                {"id": "H2", "tuned": True, "ok": True, "severe": False, "got": "mild"},
                {"id": "X", "tuned": False, "ok": True, "severe": True, "got": "severe"}]
        s = cp.summarise(rows, {"HEDGE": {"H1", "H2"}})
        b = s["breakout_HEDGE"]
        self.assertEqual((b["n"], b["correct"], b["false_drops"]["ids"]), (2, 1, ["H1"]))
        self.assertEqual(s["independent"]["n"], 2)                  # still inside the headline blocks

    def test_interview_from_another_file(self):
        # --interview: the old configuration runs without touching src/interview.py
        import hashlib
        import tempfile
        live = (REPO_ROOT / "src" / "interview.py").read_text(encoding="utf-8")
        marker = "# qa test copy\n"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "interview_copy.py"
            path.write_text(live.replace("EXTRACTION_INSTRUCTION = (", marker +
                                         'EXTRACTION_INSTRUCTION = ("QA-COPY " \n', 1),
                            encoding="utf-8")
            module, sha = cp.load_interview(path)
            self.assertEqual(sha, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertTrue(module.EXTRACTION_INSTRUCTION.startswith("QA-COPY"))
        self.assertEqual(Path(module.__file__), REPO_ROOT / "src" / "interview.py")   # paths resolve
        saved = cp.IV
        cp.IV = module
        try:
            cfg = cp.configuration("stub", path, sha)
            case = {"id": "R", "expected": "not_tried", "text": "I have not taken anything for it."}
            r = cp.run_phrase(case, "stub", PROTOCOL, stub("pain_relief_effect", "not_tried"))
        finally:
            cp.IV = saved
        self.assertEqual(cfg["interview_py_sha256"], sha)
        self.assertNotEqual(cfg["extraction_instruction_sha256"],
                            cp.configuration("stub")["extraction_instruction_sha256"])
        self.assertEqual(r["got"], "not_tried")
        self.assertEqual((REPO_ROOT / "src" / "interview.py").read_text(encoding="utf-8"), live)

    def test_set_c_shape(self):
        # the held-back file loads and its breakout ids exist (no model run here)
        path = cp.REPO_ROOT / "llm" / "eval" / "heldback" / "severity_phrases_c.json"
        if not path.exists():
            self.skipTest("set c not present")
        import json as _json
        cases = _json.loads(path.read_text(encoding="utf-8"))
        ids = {c["id"] for c in cases}
        self.assertTrue({"HS19", "HS20", "HS22", "HS23", "HS35"} <= ids)
        unclear = [c for c in cases if c.get("unclear")]
        self.assertEqual(len(unclear), 8)
        self.assertTrue(all(c["severe"] is None for c in unclear))
        self.assertTrue(all(isinstance(c["severe"], bool) for c in cases if not c.get("unclear")))


if __name__ == "__main__":
    unittest.main()
