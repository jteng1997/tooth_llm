"""Unit tests for the planned interview in src/interview.py (no GPU, no Ollama).

    .venv/Scripts/python -m unittest discover -s tests -v

Uses the real llm/protocol/triage_protocol.yaml, because QUESTION_PLAN
names its question ids; the model is replaced by a stub extractor.
"""
import json
import unittest

import fixtures  # noqa: F401  (sys.path)

import interview  # noqa: E402
import protocol as P  # noqa: E402
import rules  # noqa: E402

PROTOCOL = P.load(allow_unreviewed=True)
A_ROWS = [q.id for q in PROTOCOL.questions if q.input == "yesno_checklist" and q.group == "A"]
B_ROWS = [q.id for q in PROTOCOL.questions if q.input == "yesno_checklist" and q.group == "B"]
FIELD_OF = {q.id: q.fields[0] for q in PROTOCOL.questions}
PAIN_ROW = next(q.id for q in PROTOCOL.questions if q.fields == ["pain_present"])


class Extractor:
    """Stands in for the model: each call returns the next queued
    {field: (value, quote)} for whichever fields the schema asks about."""

    def __init__(self):
        self.queue = []
        self.schemas = []

    def __call__(self, messages, schema):
        self.schemas.append(schema)
        answer = self.queue.pop(0) if self.queue else {}
        out = {f: {"value": None, "quote": None} for f in schema["properties"]}
        for field, (value, quote) in answer.items():
            if field in out:
                out[field] = {"value": value, "quote": quote}
        return json.dumps(out)


def all_no(rows, **yes):
    answers = {qid: False for qid in rows}
    answers.update(yes)
    return answers


class Checklists(unittest.TestCase):
    def setUp(self):
        self.llm = Extractor()
        self.session = interview.Interview(protocol=PROTOCOL, llm=self.llm)

    def test_starts_with_checklist_a_from_the_protocol(self):
        step = self.session.start()
        self.assertEqual((step["type"], step["group"]), ("checklist", "A"))
        self.assertEqual([i["id"] for i in step["items"]], A_ROWS)
        self.assertTrue(set(rules.RED_FLAG_FIELDS) <= {i["field"] for i in step["items"]})
        self.assertIn("pain_present", {i["field"] for i in step["items"]})
        self.assertEqual(step["items"][0]["text"], PROTOCOL.questions[0].text)

    def test_every_row_needs_an_explicit_yes_or_no(self):
        self.session.start()
        partial = all_no(A_ROWS)
        del partial[A_ROWS[0]]
        for bad in (partial, {**all_no(A_ROWS), A_ROWS[1]: None},
                    {**all_no(A_ROWS), A_ROWS[1]: "no"}, {**all_no(A_ROWS), A_ROWS[1]: 0},
                    {**all_no(A_ROWS), A_ROWS[1]: "not_sure"},
                    {**all_no(A_ROWS), "Q99": False}):
            with self.subTest(answers=bad), self.assertRaises(ValueError):
                self.session.submit_checklist("A", bad)
        self.assertEqual(self.session.symptoms, {})  # nothing half-recorded

    def test_not_sure_is_null_and_only_where_the_row_offers_it(self):
        self.session.start()
        step = self.session.submit_checklist("A", all_no(A_ROWS, **{PAIN_ROW: True}))
        by_id = {q.id: q for q in PROTOCOL.questions}
        unsure = [qid for qid in B_ROWS if "not_sure" in by_id[qid].options]
        sure_only = [qid for qid in B_ROWS if qid not in unsure]
        self.assertTrue(unsure and sure_only)
        self.assertIn({"label": "Not sure", "value": None},
                      next(i["options"] for i in step["items"] if i["id"] == unsure[0]))
        with self.assertRaises(ValueError):
            self.session.submit_checklist("B", {**all_no(B_ROWS), sure_only[0]: None})
        self.session.submit_checklist("B", {**all_no(B_ROWS), unsure[0]: None})
        self.assertIsNone(self.session.symptoms[FIELD_OF[unsure[0]]])   # recorded as null

    def test_checklist_step_carries_options_and_intro(self):
        step = self.session.start()
        self.assertEqual(step["items"][0]["options"],
                         [{"label": "Yes", "value": True}, {"label": "No", "value": False}])
        self.assertIn("intro", step)

    def test_no_result_before_checklist_a(self):
        self.session.start()
        with self.assertRaises(ValueError):
            self.session.extract()                       # "skip to result"
        self.session.submit_checklist("A", all_no(A_ROWS, **{PAIN_ROW: True}))
        self.llm.queue.append({})
        self.session.extract()                           # allowed once A is answered

    def test_double_submit_and_out_of_order_are_refused(self):
        self.session.start()
        self.session.submit_checklist("A", all_no(A_ROWS, **{PAIN_ROW: True}))
        with self.assertRaises(ValueError):
            self.session.submit_checklist("A", all_no(A_ROWS))   # already done, B is pending
        with self.assertRaises(ValueError):
            self.session.reply("hello")                          # a checklist is pending

    def test_no_red_flag_row_offers_not_sure(self):
        for q in PROTOCOL.questions:
            if q.red_flag:
                self.assertNotIn("not_sure", q.options, q.id)

    def test_wrong_group_is_refused(self):
        self.session.start()
        with self.assertRaises(ValueError):
            self.session.submit_checklist("B", {})

    def test_any_red_flag_stops_at_once_without_the_model(self):
        for qid in A_ROWS:
            if FIELD_OF[qid] not in rules.RED_FLAG_FIELDS:
                continue
            with self.subTest(row=qid):
                session = interview.Interview(protocol=PROTOCOL, llm=self.llm)
                session.start()
                step = session.submit_checklist("A", all_no(A_ROWS, **{qid: True}))
                self.assertEqual((step["type"], step["red_flag"]), ("done", True))
                self.assertIs(step["symptoms"][FIELD_OF[qid]], True)
                self.assertTrue(session.done)
        self.assertEqual(self.llm.schemas, [])

    def test_no_pain_ends_without_the_model(self):
        self.session.start()
        step = self.session.submit_checklist("A", all_no(A_ROWS))
        self.assertEqual((step["type"], step["red_flag"]), ("done", False))
        self.assertIs(step["symptoms"]["pain_present"], False)
        self.assertEqual(self.llm.schemas, [])

    def test_pain_leads_to_checklist_b_then_the_chat(self):
        self.session.start()
        step = self.session.submit_checklist("A", all_no(A_ROWS, **{PAIN_ROW: True}))
        self.assertEqual((step["type"], step["group"]), ("checklist", "B"))
        self.assertEqual([i["id"] for i in step["items"]], B_ROWS)
        step = self.session.submit_checklist("B", all_no(B_ROWS))
        self.assertEqual((step["type"], step["id"]), ("question", "Q10"))


class Chat(unittest.TestCase):
    def setUp(self):
        self.llm = Extractor()
        self.session = interview.Interview(protocol=PROTOCOL, llm=self.llm)
        self.session.start()
        self.session.submit_checklist("A", all_no(A_ROWS, **{PAIN_ROW: True}))
        self.step = self.session.submit_checklist("B", all_no(B_ROWS, Q15=True))

    def answer(self, text, **fields):
        self.llm.queue.append(fields)
        return self.session.reply(text)

    def test_full_path_to_done(self):
        steps = [
            ("I took some painkillers but they didn't help",
             {"pain_relief_effect": ("not_helped", "they didn't help")}),
            ("It's so bad I can't sleep", {"pain_severity": ("severe", "can't sleep")}),
            ("cold drinks", {"pain_triggers": (["cold"], "cold drinks")}),
            ("bottom left", {"location": ("lower_left", "bottom left")}),
            ("about a week", {"duration_days": (7, "about a week")}),
        ]
        asked = [self.step["id"]]
        for text, fields in steps:
            step = self.answer(text, **fields)
            asked.append(step.get("id", "done"))
        self.assertEqual(asked, ["Q10", "Q11", "Q12", "Q17", "Q18", "done"])
        s = step["symptoms"]
        self.assertEqual((s["schema_version"], s["pain_relief_effect"], s["duration_days"]),
                         ("1.1", "not_helped", 7))
        self.assertIs(s["pain_on_biting"], True)          # from checklist B
        self.assertIs(s["pain_wakes_at_night"], False)
        self.assertFalse(step["red_flag"])

    def test_only_chat_fields_are_extracted(self):
        self.answer("they didn't help", pain_relief_effect=("not_helped", "they didn't help"))
        fields = set(self.llm.schemas[-1]["properties"]) - {"notes"}
        chat_fields = {f for q in PROTOCOL.questions if q.input == "chat" for f in q.fields}
        self.assertEqual(fields, chat_fields)
        self.assertFalse(fields & set(rules.RED_FLAG_FIELDS))

    def test_checklist_answers_are_never_overwritten(self):
        # Even if a (buggy) model returned a checklist field, it is ignored.
        self.answer("they didn't help", pain_relief_effect=("not_helped", "they didn't help"),
                    swelling=(True, "they didn't help"))
        self.assertIs(self.session.symptoms["swelling"], False)

    def test_unsupported_answer_is_reasked_once_then_left_null(self):
        step = self.answer("hmm", pain_relief_effect=("helped", "it helped a lot"))  # invented quote
        self.assertEqual(step["id"], "Q10")
        q10 = next(q for q in PROTOCOL.questions if q.id == "Q10")
        self.assertEqual(step["text"], PROTOCOL.reask_template.format(question=q10.text))
        step = self.answer("not sure")
        self.assertEqual(step["id"], "Q11")                   # moved on after one re-ask
        self.assertIsNone(self.session.symptoms["pain_relief_effect"])

    def test_a_correction_replaces_an_earlier_value(self):
        self.answer("they helped", pain_relief_effect=("helped", "they helped"))
        self.answer("actually no, they didn't help at all",
                    pain_relief_effect=("not_helped", "they didn't help at all"))
        self.assertEqual(self.session.symptoms["pain_relief_effect"], "not_helped")

    def test_bare_yes_settles_no_chat_question(self):
        step = self.answer("yes", pain_relief_effect=("helped", "yes"))
        self.assertEqual(step["id"], "Q10")                   # re-asked
        self.assertIsNone(self.session.symptoms["pain_relief_effect"])

    def test_question_already_answered_is_skipped(self):
        step = self.answer("painkillers didn't help and it's unbearable, I can't sleep",
                           pain_relief_effect=("not_helped", "painkillers didn't help"),
                           pain_severity=("severe", "unbearable, I can't sleep"))
        self.assertEqual(step["id"], "Q12")

    def test_not_english_notice_is_shown_once(self):
        step = self.answer("止痛药没用", pain_relief_effect=("not_helped", "止痛药没用"))
        self.assertEqual(step["notice"], interview.NOT_ENGLISH_NOTICE)
        self.assertEqual(self.session.symptoms["pain_relief_effect"], "not_helped")  # still evidence
        step = self.answer("很痛", pain_severity=("severe", "很痛"))
        self.assertIsNone(step["notice"])

    def test_transcript_holds_only_the_chat(self):
        self.answer("they didn't help", pain_relief_effect=("not_helped", "they didn't help"))
        user_turns = [m["content"] for m in self.session.messages if m["role"] == "user"]
        self.assertEqual(user_turns, ["they didn't help"])

    def test_reply_without_an_open_question_is_refused(self):
        session = interview.Interview(protocol=PROTOCOL, llm=self.llm)
        session.start()
        with self.assertRaises(ValueError):
            session.reply("hello")


class Plan(unittest.TestCase):
    def test_plan_matches_the_real_protocol(self):
        interview.check_plan(PROTOCOL)

    def test_unplanned_chat_question_is_an_error(self):
        extra = P.Question(id="Q99", fields=["bleeding_gums"], text="Do your gums bleed?",
                           input="chat")
        broken = P.Protocol(**{**PROTOCOL.__dict__, "questions": PROTOCOL.questions + [extra]})
        with self.assertRaises(P.ProtocolError):
            interview.check_plan(broken)


class Replay(unittest.TestCase):
    """Test 3 replays scripted dialogues through record() + extract()."""

    def test_replay_extracts_every_field_with_the_old_bare_rule(self):
        llm = Extractor()
        session = interview.Interview(llm=llm)        # no protocol needed, never started
        session.record("Any swelling?", "no")
        llm.queue.append({"swelling": (False, "no")})
        symptoms = session.extract()
        self.assertEqual(set(llm.schemas[0]["properties"]) - {"notes"}, set(interview.EVIDENCE_FIELDS))
        self.assertIs(symptoms["swelling"], False)
        self.assertIsNone(session.protocol)


if __name__ == "__main__":
    unittest.main()
