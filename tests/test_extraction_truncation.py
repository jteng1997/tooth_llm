"""A reply cut off at the output cap (no GPU, no Ollama).

    .venv/Scripts/python -m unittest discover -s tests -p "test_extraction_truncation.py"

Dev e2e 2026-09-30 hung for 300 s on an extraction that never stopped. Every
chat() call now carries num_predict; a reply that hits it raises Truncated.
Each caller treats that as a failed call: extraction retries once and then
settles no field (hard rule 7: never a default), triage falls back as for
unparsable output, and the explanation gives its fixed fallback text.
"""
import copy
import unittest
from unittest import mock

import fixtures  # noqa: F401  (sys.path)

import explain  # noqa: E402
import interview  # noqa: E402
import triage  # noqa: E402
from test_explain_guardrails import (FakeKnowledge, GOOD, U10_ASSESSMENT,  # noqa: E402
                                     U10_SYMPTOMS)
from test_interview import A_ROWS, B_ROWS, PAIN_ROW, PROTOCOL, Extractor, all_no  # noqa: E402


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class Chat(unittest.TestCase):
    def test_every_call_carries_a_cap(self):
        sent = {}

        def post(url, json=None, timeout=None):
            sent.update(json)
            return FakeResponse({"message": {"content": "{}"}, "done_reason": "stop"})
        with mock.patch.object(interview.requests, "post", post):
            self.assertEqual(interview.chat([{"role": "user", "content": "x"}]), "{}")
            self.assertEqual(sent["options"]["num_predict"], interview.DEFAULT_MAX_TOKENS)
            interview.chat([], max_tokens=77)
            self.assertEqual(sent["options"]["num_predict"], 77)

    def test_hitting_the_cap_raises_truncated(self):
        body = {"message": {"content": '{"pain_severity": {"value": "sev'}, "done_reason": "length"}
        with mock.patch.object(interview.requests, "post", lambda *a, **k: FakeResponse(body)):
            with self.assertRaises(interview.Truncated):
                interview.chat([])

    def test_truncated_is_a_value_error(self):
        # so callers that already catch unparsable output catch this too
        self.assertTrue(issubclass(interview.Truncated, ValueError))


class Schemas(unittest.TestCase):
    def test_free_text_is_bounded_by_the_schema(self):
        # the V068 runaway was one sentence repeated inside `notes`
        s = interview.evidence_schema(["pain_severity", "location"])
        self.assertEqual(s["properties"]["notes"]["properties"]["value"]["maxLength"],
                         interview.NOTES_MAX_CHARS)
        for field in ("pain_severity", "location", "notes"):
            self.assertEqual(s["properties"][field]["properties"]["quote"]["maxLength"],
                             interview.QUOTE_MAX_CHARS)
        t = triage.output_schema(PROTOCOL, ["pain_present"])
        evidence = t["properties"]["criteria_met"]["items"]["properties"]["evidence"]
        self.assertEqual(evidence["items"]["properties"]["quote"]["maxLength"],
                         interview.QUOTE_MAX_CHARS)


class Flaky(Extractor):
    """The stub extractor, failing the first `failures` calls with `error`
    (an exception to raise, or a string to return as the raw reply)."""

    def __init__(self, failures, error):
        super().__init__()
        self.failures, self.error, self.calls = failures, error, 0

    def __call__(self, messages, schema):
        self.calls += 1
        if self.calls <= self.failures:
            if isinstance(self.error, str):
                return self.error
            raise self.error
        return super().__call__(messages, schema)


class Extraction(unittest.TestCase):
    def setUp(self):
        self.before = dict(interview.EXTRACTION_STATS)

    def session(self, llm):
        s = interview.Interview(protocol=PROTOCOL, llm=llm)
        s.start()
        s.submit_checklist("A", all_no(A_ROWS, **{PAIN_ROW: True}))
        step = s.submit_checklist("B", all_no(B_ROWS))
        self.assertEqual(step["id"], "Q10")
        return s

    def stats(self):
        return {k: interview.EXTRACTION_STATS[k] - self.before[k] for k in self.before}

    def test_one_truncation_then_a_good_reply_keeps_the_value(self):
        llm = Flaky(1, interview.Truncated("cut off"))
        s = self.session(llm)
        llm.queue.append({"pain_relief_effect": ("not_helped", "didn't help")})
        step = s.reply("I took some but it didn't help")
        self.assertEqual(s.symptoms["pain_relief_effect"], "not_helped")
        self.assertEqual(step["id"], "Q11")
        self.assertEqual(llm.calls, 2)
        self.assertEqual(self.stats(), {"truncated": 1, "unparsed": 0, "fallback": 0})
        self.assertEqual(len(s.extraction_problems), 1)

    def test_truncated_twice_settles_nothing_and_reasks(self):
        llm = Flaky(2, interview.Truncated("cut off"))
        s = self.session(llm)
        llm.queue.append({"pain_relief_effect": ("helped", "it helped")})  # never reached
        step = s.reply("It helped a bit I suppose")
        self.assertIsNone(s.symptoms["pain_relief_effect"])     # null, never a default
        self.assertEqual((step["type"], step["id"]), ("question", "Q10"))   # asked again
        self.assertIn("Q10", s.reasked)
        self.assertEqual(self.stats(), {"truncated": 2, "unparsed": 0, "fallback": 1})
        self.assertIs(s.symptoms["pain_present"], True)          # clicks are untouched

    def test_unparsable_twice_settles_nothing(self):
        llm = Flaky(2, '{"pain_relief_effect": {"value": "not_he')
        s = self.session(llm)
        s.reply("didn't help")
        self.assertIsNone(s.symptoms["pain_relief_effect"])
        self.assertEqual(self.stats(), {"truncated": 0, "unparsed": 2, "fallback": 1})

    def test_a_failed_turn_keeps_values_verified_earlier(self):
        llm = Flaky(0, None)
        s = self.session(llm)
        llm.queue.append({"pain_relief_effect": ("not_helped", "didn't help")})
        s.reply("I took some but it didn't help")
        llm.failures, llm.error = llm.calls + 2, interview.Truncated("cut off")
        s.reply("It's quite bad")                                 # Q11, both attempts cut off
        self.assertEqual(s.symptoms["pain_relief_effect"], "not_helped")
        self.assertIsNone(s.symptoms["pain_severity"])
        self.assertEqual(self.stats()["fallback"], 1)

    def test_the_default_llm_passes_the_extraction_cap(self):
        seen = {}

        def fake_chat(messages, model, schema=None, max_tokens=None):
            seen["max_tokens"] = max_tokens
            return "{}"
        with mock.patch.object(interview, "chat", fake_chat):
            interview.Interview(protocol=PROTOCOL).llm([], {})
        self.assertEqual(seen["max_tokens"], interview.MAX_TOKENS["extract"])


class Triage(unittest.TestCase):
    def test_truncated_proposals_fall_back_without_crashing(self):
        def cut_off(messages, schema):
            raise interview.Truncated("cut off")
        symptoms = {"pain_present": True, "pain_relief_effect": "not_helped"}
        a = triage.assess(None, symptoms, [], protocol=PROTOCOL, llm=cut_off)
        self.assertFalse(a["triage"]["llm_valid"])
        self.assertEqual(a["triage"]["attempts"], triage.MAX_ATTEMPTS)
        self.assertEqual(a["urgency"], "URGENT")                  # U1, never lowered
        self.assertTrue(all("not JSON" in e for e in a["triage"]["validation_errors"]))


class Explain(unittest.TestCase):
    def setUp(self):
        self.real_chat, self.calls = explain.chat, 0

    def tearDown(self):
        explain.chat = self.real_chat

    def test_cut_off_twice_gives_the_fallback(self):
        def cut_off(messages, model=None, **kwargs):
            self.calls += 1
            raise interview.Truncated("cut off")
        explain.chat = cut_off
        s = explain.Explanation(GOOD, dict(U10_SYMPTOMS), knowledge=FakeKnowledge(),
                                assessment=copy.deepcopy(U10_ASSESSMENT))
        self.assertEqual(s.first_response(), explain.fallback_text(U10_ASSESSMENT, GOOD))
        self.assertEqual(self.calls, 2)
        self.assertIn("cut off", s.guardrail_log[0]["first"][0])

    def test_explanation_calls_carry_the_explain_cap(self):
        seen = []

        def spy(messages, model=None, max_tokens=None, **kwargs):
            seen.append(max_tokens)
            return "x"
        explain.chat = spy
        s = explain.Explanation(GOOD, dict(U10_SYMPTOMS), knowledge=FakeKnowledge(),
                                assessment=copy.deepcopy(U10_ASSESSMENT))
        s.first_response()
        self.assertTrue(seen)
        self.assertEqual(set(seen), {interview.MAX_TOKENS["explain"]})


if __name__ == "__main__":
    unittest.main()
