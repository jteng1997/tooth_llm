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

    def reach(self, qid):
        """Answer the chat questions before qid, each settling its own field."""
        given = {"Q10": ("pain_relief_effect", "not_tried", "Nothing taken yet."),
                 "Q11": ("pain_severity", "moderate", "Moderate."),
                 "Q12": ("pain_triggers", ["cold"], "Cold drinks."),
                 "Q17": ("location", "lower_right", "Lower right.")}
        step = self.step
        while step["id"] != qid:
            field, value, quote = given[step["id"]]
            step = self.answer(quote, **{field: (value, quote)})
        return step

    # (a) location needs arch and side, each in the patient's own words

    def test_side_without_arch_is_not_a_quadrant(self):
        self.reach("Q17")
        text = "It hurts when I bite down on the left."
        step = self.answer(text, location=("lower_left", text))
        self.assertEqual(step["id"], "Q17")                   # re-asked, not settled
        self.assertIsNone(self.session.symptoms["location"])

    def test_arch_without_side_is_not_a_quadrant(self):
        self.reach("Q17")
        text = "At the front, top."
        self.answer(text, location=("upper_left", text))
        self.assertIsNone(self.session.symptoms["location"])

    def test_arch_and_side_in_the_patients_words_is_kept(self):
        self.reach("Q17")
        for text, value in (("Down left side.", "lower_left"), ("Top right.", "upper_right")):
            session = self.session
            self.answer(text, location=(value, text))
            self.assertEqual(session.symptoms["location"], value)
            self.setUp()
            self.reach("Q17")

    def test_front_and_generalised_need_no_side(self):
        self.reach("Q17")
        self.answer("At the front, top.", location=("front", "At the front, top."))
        self.assertEqual(self.session.symptoms["location"], "front")
        self.setUp()
        self.reach("Q17")
        text = "It's all over, hard to pin down."
        self.answer(text, location=("generalised", text))
        self.assertEqual(self.session.symptoms["location"], "generalised")

    def test_not_sure_where_is_null_not_unknown(self):
        self.reach("Q17")
        self.answer("Not sure.", location=("unknown", "Not sure."))
        self.answer("I can't point to it.", location=("unknown", "I can't point to it."))
        self.assertIsNone(self.session.symptoms["location"])

    def test_quote_split_across_two_messages_is_not_evidence(self):
        self.reach("Q17")
        self.answer("Lower.")
        self.answer("Left.", location=("lower_left", "Lower. Left."))
        self.assertIsNone(self.session.symptoms["location"])

    # (b) a "don't know" answer settles nothing: re-ask, then null

    def test_hedge_after_reask_is_left_null(self):
        step = self.answer("I don't remember.", pain_relief_effect=("not_tried", "I don't remember."))
        self.assertEqual(step["id"], "Q10")                   # re-asked
        step = self.answer("Really couldn't say.",
                           pain_relief_effect=("not_tried", "Really couldn't say."))
        self.assertEqual(step["id"], "Q11")                   # moved on
        self.assertIsNone(self.session.symptoms["pain_relief_effect"])

    def test_hedge_is_an_unknown_trigger_only_in_reply_to_the_trigger_question(self):
        self.reach("Q11")
        step = self.answer("Hard to say really.", pain_triggers=(["unknown"], "Hard to say really."))
        self.assertIsNone(self.session.symptoms["pain_triggers"])
        self.assertEqual(step["id"], "Q11")                   # severity re-asked
        step = self.answer("Moderate.", pain_severity=("moderate", "Moderate."))
        self.assertEqual(step["id"], "Q12")                   # triggers still asked
        text = "I can't tell what sets it off."
        self.answer(text, pain_triggers=(["unknown"], text))
        self.assertEqual(self.session.symptoms["pain_triggers"], ["unknown"])

    # (c) every pain_triggers item needs its own evidence

    def test_trigger_the_patient_never_named_is_dropped(self):
        self.reach("Q12")
        text = "Cold, and my cheek feels a bit puffy and I feel hot."
        self.answer(text, pain_triggers=(["cold", "spontaneous", "hot"], text))
        self.assertEqual(self.session.symptoms["pain_triggers"], ["cold"])
        self.assertIs(self.session.symptoms["swelling"], False)
        self.assertIs(self.session.symptoms["fever"], False)

    def test_every_named_trigger_is_kept(self):
        self.reach("Q12")
        text = "Cold, sweet things, and biting down on it too."
        self.answer(text, pain_triggers=(["cold", "sweet", "biting"], text))
        self.assertEqual(self.session.symptoms["pain_triggers"], ["cold", "sweet", "biting"])

    def test_hot_drink_is_a_hot_trigger(self):
        self.reach("Q12")
        self.answer("Hot tea makes it worse.", pain_triggers=(["hot"], "Hot tea makes it worse."))
        self.assertEqual(self.session.symptoms["pain_triggers"], ["hot"])

    # bare answers: only to their own yes/no question, only for listed values

    def test_bare_no_to_the_pain_relief_question_is_not_tried(self):
        step = self.answer("No.", pain_relief_effect=("not_tried", "No."))
        self.assertEqual(step["id"], "Q11")
        self.assertEqual(self.session.symptoms["pain_relief_effect"], "not_tried")

    def test_bare_yes_to_the_pain_relief_question_settles_nothing(self):
        step = self.answer("Yes.", pain_relief_effect=("helped", "Yes."))
        self.assertEqual(step["id"], "Q10")                   # re-asked: did it help?
        self.assertIsNone(self.session.symptoms["pain_relief_effect"])

    def test_bare_no_to_another_question_settles_nothing(self):
        self.reach("Q11")
        self.answer("No.", pain_relief_effect=("not_tried", "No."))   # given to severity
        self.assertEqual(self.session.symptoms["pain_relief_effect"], "not_tried")  # from Q10
        self.setUp()
        step = self.reach("Q12")
        self.answer("No.", pain_triggers=(["unknown"], "No."))
        self.assertIsNone(self.session.symptoms["pain_triggers"])

    def test_no_inside_a_longer_answer_is_not_a_bare_answer(self):
        self.reach("Q11")
        self.answer("I know it hurts but not much.", pain_relief_effect=("not_tried", "no"))
        self.assertEqual(self.session.symptoms["pain_relief_effect"], "not_tried")  # Q10's, kept
        self.assertEqual(interview.verify(
            "pain_relief_effect", "not_tried", "no", [("Q11", "I know it hurts but not much.")],
            "Q10", True), None)

    # spontaneous pain and night

    def test_spontaneous_idioms_are_evidence(self):
        for text in ("It comes out of the blue.", "It throbs even when I'm not eating.",
                     "It keeps me awake.", "It just aches, no trigger at all.",
                     "It hurts at night mostly.", "At night it throbs."):
            with self.subTest(text=text):
                self.assertEqual(interview.verify("pain_triggers", ["spontaneous"], text,
                                                  [("Q12", text)], "Q12"), ["spontaneous"])

    def test_night_not_about_the_pain_is_not_spontaneous(self):
        for text in ("I can't tell what sets it off, I work at night.",
                     "No idea. I noticed it last night.",
                     "Cold, and I brush at night."):
            with self.subTest(text=text):
                got = interview.verify("pain_triggers", ["unknown", "spontaneous", "cold"], text,
                                       [("Q12", text)], "Q12")
                self.assertNotIn("spontaneous", got or [])

    # informal arch words

    def test_informal_arch_words(self):
        for text, value in (("Up top on the left.", "upper_left"),
                            ("Downstairs, right side.", "lower_right"),
                            ("Up on the right, near the back.", "upper_right"),
                            ("Upstairs left.", "upper_left")):
            with self.subTest(text=text):
                self.assertEqual(interview.verify("location", value, text, [("Q17", text)],
                                                  "Q17"), value)
        text = "On top of that, it's on the left."
        self.assertIsNone(interview.verify("location", "upper_left", text, [("Q17", text)], "Q17"))

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
