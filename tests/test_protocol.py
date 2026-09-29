"""Unit tests for src/protocol.py: predicate grammar, protocol validation, levels.

    .venv/Scripts/python -m unittest discover -s tests -v
"""
import unittest

from fixtures import SYMPTOM_SCHEMA, build_protocol, protocol_raw

import protocol as P  # noqa: E402
import rules  # noqa: E402


def holds(predicate: str, symptoms: dict = None, visual: dict = None) -> bool:
    return P.evaluate(P.parse_predicate(predicate),
                      {"symptoms": symptoms or {}, "visual_summary": visual or {}})


class Grammar(unittest.TestCase):
    def test_comparisons(self):
        self.assertTrue(holds("pain_relief_effect == not_helped", {"pain_relief_effect": "not_helped"}))
        self.assertFalse(holds("pain_relief_effect == not_helped", {"pain_relief_effect": "helped"}))
        self.assertTrue(holds("pain_relief_effect != helped", {"pain_relief_effect": "not_tried"}))
        self.assertTrue(holds('location == "lower_left"', {"location": "lower_left"}))

    def test_bare_field_means_true(self):
        self.assertTrue(holds("fever", {"fever": True}))
        self.assertFalse(holds("fever", {"fever": False}))

    def test_null_satisfies_nothing(self):
        for predicate in ("fever", "fever == false", "fever != true",
                          "pain_triggers contains cold", "pain_triggers non-empty"):
            with self.subTest(predicate=predicate):
                self.assertFalse(holds(predicate, {"fever": None, "pain_triggers": None}))
                self.assertFalse(holds(predicate, {}))

    def test_contains_and_non_empty(self):
        s = {"pain_triggers": ["cold", "biting"]}
        self.assertTrue(holds("pain_triggers contains biting", s))
        self.assertFalse(holds("pain_triggers contains hot", s))
        self.assertTrue(holds("pain_triggers non-empty", s))
        self.assertFalse(holds("pain_triggers non-empty", {"pain_triggers": []}))

    def test_precedence_and_parentheses(self):
        s = {"fever": True, "swelling": False, "pain_present": False}
        # AND binds tighter than OR
        self.assertTrue(holds("fever OR swelling AND pain_present", s))
        self.assertFalse(holds("(fever OR swelling) AND pain_present", s))

    def test_visual_summary_fields(self):
        v = {"flagged_teeth": [{"fdi": "16"}], "unexpected_missing_teeth": []}
        self.assertTrue(holds("visual_summary.flagged_teeth non-empty", visual=v))
        self.assertTrue(holds("flagged_teeth non-empty", visual=v))
        self.assertFalse(holds("unexpected_missing_teeth non-empty", visual=v))

    def test_bad_predicates_raise(self):
        for bad in ("", "fever ==", "(fever", "fever) OR swelling", "== true",
                    "fever AND", "fever; import os"):
            with self.subTest(bad=bad), self.assertRaises(P.ProtocolError):
                P.parse_predicate(bad)


class IsNull(unittest.TestCase):
    """`field is null` (lead, 2026-09-26): true only when the field is unanswered."""

    def test_parses_to_its_own_atom(self):
        self.assertEqual(P.parse_predicate("pain_relief_effect is null"),
                         ("is null", "pain_relief_effect", None))
        self.assertEqual(P.parse_predicate("pain_present AND pain_relief_effect is null"),
                         ("and", ("==", "pain_present", True),
                          ("is null", "pain_relief_effect", None)))

    def test_malformed_is_raises(self):
        for bad in ("pain_relief_effect is", "pain_relief_effect is true",
                    "pain_relief_effect is not null", "is null", "fever is null null"):
            with self.subTest(bad=bad), self.assertRaises(P.ProtocolError):
                P.parse_predicate(bad)

    def test_equals_null_is_refused(self):
        # `== null` could never hold, since null satisfies no comparison.
        for bad in ("pain_relief_effect == null", "fever != null"):
            with self.subTest(bad=bad), self.assertRaises(P.ProtocolError) as ctx:
                P.parse_predicate(bad)
            self.assertIn("is null", str(ctx.exception))
        self.assertTrue(holds('location == "null"', {"location": "null"}))  # a quoted string

    def test_other_spellings_of_null_are_refused(self):
        # qa 2026-09-29: only lower-case `is null` is the atom; nothing else may
        # parse into a test that silently never holds.
        for bad in ("fever is NULL", "fever IS null", "fever is None", "fever is (null)",
                    "fever is null is null", "pain_triggers contains null"):
            with self.subTest(bad=bad), self.assertRaises(P.ProtocolError):
                P.parse_predicate(bad)
        # null in any case is the parser's error, whatever the field
        for bad in ("pain_relief_effect == NULL", "fever != NULL", "location == Null",
                    "duration_days == NULL"):
            with self.subTest(bad=bad), self.assertRaises(P.ProtocolError) as ctx:
                P.parse_predicate(bad)
            self.assertIn("is null", str(ctx.exception))
        # None is a word, refused by validation as a value of the field
        raw = protocol_raw()
        raw["criteria"][-1]["predicate"] = "fever == None"
        self.assertEqual(P.validate(raw, SYMPTOM_SCHEMA, rules.RED_FLAG_FIELDS),
                         ["criterion 'P2': 'None' is not a value of fever"])

    def test_literal_type_is_checked_on_fields_without_an_enum(self):
        # qa 2026-09-29: an integer field took any literal, so "== None" or
        # '== "3"' was valid and could never hold. Checked on the live file,
        # whose questions ask duration_days.
        import json
        import yaml
        live = yaml.safe_load(P.PROTOCOL_PATH.read_text(encoding="utf-8"))
        schema = json.loads(P.SYMPTOM_SCHEMA_PATH.read_text(encoding="utf-8"))
        errs = lambda pred: P.validate({**live, "criteria": live["criteria"][:-1] + [
            {**live["criteria"][-1], "predicate": pred}]}, schema, rules.RED_FLAG_FIELDS)
        self.assertEqual(errs("duration_days == 3"), [])
        for pred in ("duration_days == None", 'duration_days == "3"'):
            with self.subTest(predicate=pred):
                self.assertTrue(any("does not match the type of duration_days" in e
                                    for e in errs(pred)), errs(pred))

    def test_zero_and_empty_string_are_answers(self):
        self.assertFalse(holds("duration_days is null", {"duration_days": 0}))
        self.assertFalse(holds("location is null", {"location": ""}))

    def test_true_only_when_unanswered(self):
        p = "pain_relief_effect is null"
        self.assertTrue(holds(p, {"pain_relief_effect": None}))
        self.assertTrue(holds(p, {}))                          # missing = unanswered
        for value in ("helped", "not_helped", "not_tried"):
            with self.subTest(value=value):
                self.assertFalse(holds(p, {"pain_relief_effect": value}))

    def test_false_and_empty_are_answers_not_null(self):
        self.assertFalse(holds("fever is null", {"fever": False}))
        self.assertFalse(holds("pain_triggers is null", {"pain_triggers": []}))

    def test_visual_summary_fields(self):
        self.assertTrue(holds("visual_summary.images_usable is null", visual={"images_usable": None}))
        self.assertFalse(holds("images_usable is null", visual={"images_usable": True}))

    def test_composes_with_and_or_parentheses(self):
        p = "pain_present AND (pain_relief_effect is null OR pain_relief_effect == not_helped)"
        self.assertTrue(holds(p, {"pain_present": True, "pain_relief_effect": None}))
        self.assertTrue(holds(p, {"pain_present": True, "pain_relief_effect": "not_helped"}))
        self.assertFalse(holds(p, {"pain_present": True, "pain_relief_effect": "helped"}))
        self.assertFalse(holds(p, {"pain_present": False, "pain_relief_effect": None}))
        # the null test does not leak: pain_present unanswered is still not evidence
        self.assertFalse(holds(p, {"pain_present": None, "pain_relief_effect": None}))
        self.assertFalse(holds(p, {}))
        # AND still binds tighter than OR
        self.assertTrue(holds("fever OR pain_present AND pain_severity is null", {"fever": True}))
        self.assertFalse(holds("(fever OR pain_present) AND pain_severity is null",
                               {"fever": True, "pain_severity": "mild"}))

    def test_other_atoms_keep_null_as_no_evidence(self):
        # Beside an `is null` atom, null still satisfies no other comparison.
        for p in ("pain_relief_effect is null AND pain_relief_effect != helped",
                  "pain_relief_effect is null AND pain_triggers non-empty",
                  "pain_relief_effect is null AND fever == false"):
            with self.subTest(predicate=p):
                self.assertFalse(holds(p, {"pain_relief_effect": None, "pain_triggers": None,
                                           "fever": None}))

    def test_criterion_fields_and_null_fields(self):
        c = build_protocol(with_u7()).criterion("U7")
        self.assertEqual(c.fields(), ["pain_present", "pain_relief_effect"])
        self.assertEqual(c.null_fields(), ["pain_relief_effect"])
        self.assertEqual(build_protocol().criterion("U1").null_fields(), [])

    def test_rendering_for_the_model(self):
        self.assertEqual(P.render_predicate("pain_present == true AND pain_relief_effect is null"),
                         "pain_present == true AND pain_relief_effect not answered")
        self.assertEqual(P.render_predicate("(a is null OR visual_summary.images_usable  is  null)"),
                         "(a not answered OR visual_summary.images_usable not answered)")
        plain = "visual_summary.flagged_teeth non-empty"
        self.assertEqual(P.render_predicate(plain), plain)        # nothing else changes
        quoted = 'location == "x is null"'                        # qa 2026-09-29: a literal
        self.assertEqual(P.render_predicate(quoted), quoted)      # is not rewritten
        c = build_protocol(with_u7()).criterion("U7")
        self.assertEqual(c.holds_when(), "pain_present == true AND pain_relief_effect not answered")
        self.assertEqual(c.predicate, "pain_present == true AND pain_relief_effect is null")

    def test_validation(self):
        errs = lambda raw: "\n".join(P.validate(raw, SYMPTOM_SCHEMA, rules.RED_FLAG_FIELDS))
        self.assertEqual(errs(with_u7()), "")
        raw = with_u7()
        raw["criteria"][-1]["predicate"] = "pain_present AND tooth_wobbly is null"
        self.assertIn("'U7': unknown field 'tooth_wobbly'", errs(raw))
        raw = with_u7()
        raw["questions"] = [q for q in raw["questions"] if q["id"] != "Q8"]
        self.assertIn("'U7': field 'pain_relief_effect' is not asked", errs(raw))

    def test_floor_criterion_may_not_use_is_null(self):
        raw = protocol_raw()
        raw["criteria"][0]["predicate"] = ("difficulty_swallowing_or_breathing == true "
                                           "OR fever is null")
        self.assertIn("'EM1': a floor criterion may not use 'is null'",
                      "\n".join(P.validate(raw, SYMPTOM_SCHEMA, rules.RED_FLAG_FIELDS)))

    def test_every_floor_criterion_is_checked_even_nested(self):
        # qa 2026-09-29: not only the first floor criterion, and not only at the top level
        raw = protocol_raw()
        floors = [c for c in raw["criteria"] if c.get("floor")]
        self.assertGreater(len(floors), 1)
        for c in floors:
            with self.subTest(criterion=c["id"]):
                changed = protocol_raw()
                target = next(x for x in changed["criteria"] if x["id"] == c["id"])
                target["predicate"] = (f"({target['predicate']}) AND "
                                       "(pain_present == true OR pain_severity is null)")
                self.assertIn(f"'{c['id']}': a floor criterion may not use 'is null'",
                              "\n".join(P.validate(changed, SYMPTOM_SCHEMA, rules.RED_FLAG_FIELDS)))

    def test_the_live_protocol_uses_it_only_for_u10(self):
        # v0.3: U10 is the one `is null` criterion, on the relief answer; no floor uses it
        live = P.load(allow_unreviewed=True)
        if live.version != "0.3":
            self.skipTest(f"live protocol is v{live.version}; this pins v0.3")
        self.assertEqual({c.id: c.null_fields() for c in live.criteria if c.null_fields()},
                         {"U10": ["pain_relief_effect"]})
        self.assertEqual([c.id for c in live.criteria if c.floor and c.null_fields()], [])
        self.assertEqual(live.criterion("U10").level, "URGENT")
        self.assertFalse({"U5", "U6"} & {c.id for c in live.criteria})

    def test_protocol_level(self):
        protocol = build_protocol(with_u7())
        level = lambda s: protocol.protocol_level(s, {})
        self.assertEqual(level({"pain_present": True, "pain_relief_effect": None}), "URGENT")
        self.assertEqual(level({"pain_present": True}), "URGENT")          # field absent
        self.assertEqual(level({"pain_present": True, "pain_relief_effect": "helped"}), "SOON")
        self.assertEqual(level({"pain_present": False, "pain_relief_effect": None}), "ROUTINE")
        self.assertEqual(level({"pain_present": None, "pain_relief_effect": None}), "ROUTINE")
        self.assertEqual([c.id for c in protocol.met({"pain_present": True}, {})], ["N1", "U7"])


class LiteralRegression(unittest.TestCase):
    """qa report 2026-09-29, fixed by llm-dev: null in any case is a parse error;
    a literal must fit its field (enum value, or schema type where there is no
    enum); rendering leaves quoted literals alone. Cases verified by llm-dev-4
    (lead, 2026-09-29), against the real symptom schema."""

    NULL = ("duration_days == NULL", "duration_days == null", "duration_days == Null",
            "location == Null", "fever != NULL", "unexpected_missing_teeth contains null")
    WRONG_TYPE = ('duration_days == "3"', "duration_days == true", "duration_days == none",
                  "flagged_teeth == 3",
                  # llm-dev-4 2026-09-29: photo lists hold objects, not tooth numbers
                  "flagged_teeth contains None", 'flagged_teeth contains "16"',
                  "flagged_teeth contains 16")
    NOT_A_LIST = ("swelling contains true", "location contains upper_left",
                  "images_usable contains true")
    NOT_A_VALUE = ("swelling == 1", 'swelling == "true"', "pain_relief_effect == 1",
                   'pain_relief_effect == "NOT_HELPED"', "pain_triggers contains 5",
                   "swelling_features contains None", "location == none")
    VALID = ("duration_days == 3", "duration_days != 0", "swelling", "swelling == false",
             "pain_relief_effect == not_helped", 'pain_relief_effect == "not_helped"',
             "pain_relief_effect is null", "flagged_teeth non-empty", "pain_triggers contains cold",
             "swelling_features contains none", 'trauma_features contains "none"',
             "location == unknown", "unexpected_missing_teeth non-empty", "images_usable",
             "images_usable == false")

    @classmethod
    def setUpClass(cls):
        import json
        schema = json.loads(P.SYMPTOM_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.fields = {**P._symptom_fields(schema), **P.VISUAL_FIELDS}

    def errors(self, pred):
        errors = []
        P._check_literals(P.parse_predicate(pred), self.fields, "t", errors)
        return errors

    def test_null_is_a_parse_error(self):
        for pred in self.NULL:
            with self.subTest(pred=pred), self.assertRaises(P.ProtocolError) as ctx:
                P.parse_predicate(pred)
            self.assertIn(f"compare with null using '{pred.split()[0]} is null'", str(ctx.exception))

    def test_literal_of_the_wrong_type_is_refused(self):
        for pred in self.WRONG_TYPE:
            with self.subTest(pred=pred):
                errors = self.errors(pred)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(f"does not match the type of {pred.split()[0]}", errors[0])

    def test_literal_outside_the_enum_is_refused(self):
        for pred in self.NOT_A_VALUE:
            with self.subTest(pred=pred):
                errors = self.errors(pred)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(f"is not a value of {pred.split()[0]}", errors[0])

    def test_contains_needs_a_list_field(self):
        for pred in self.NOT_A_LIST:
            with self.subTest(pred=pred):
                self.assertEqual(self.errors(pred), [f"t: {pred.split()[0]} is not a list; "
                                                     "'contains' needs a list field"])

    def test_valid_literals_pass(self):
        # positive controls: "none" is a real enum value; a quoted value is the same value
        for pred in self.VALID:
            with self.subTest(pred=pred):
                self.assertEqual(self.errors(pred), [])

    def test_render_leaves_quoted_literals_alone(self):
        for src, want in (("pain_relief_effect is null", "pain_relief_effect not answered"),
                          ('notes == "x is null"', 'notes == "x is null"'),
                          ('a is null AND b == "c is null" AND d is null',
                           'a not answered AND b == "c is null" AND d not answered'),
                          ('a == "say \\"b is null\\"" OR c is null',
                           'a == "say \\"b is null\\"" OR c not answered')):
            with self.subTest(src=src):
                self.assertEqual(P.render_predicate(src), want)


def with_u7() -> dict:
    """The fixture plus a criterion that holds only through `is null`."""
    raw = protocol_raw()
    raw["criteria"].append({"id": "U7", "level": "URGENT", "kind": "structured",
                            "predicate": "pain_present == true AND pain_relief_effect is null",
                            "statement": "Tooth pain, pain relief question not answered",
                            "source": "test"})
    return raw


class Validation(unittest.TestCase):
    def errors(self, raw):
        return P.validate(raw, SYMPTOM_SCHEMA, rules.RED_FLAG_FIELDS)

    def test_fixture_is_valid(self):
        self.assertEqual(self.errors(protocol_raw()), [])

    def test_unknown_field_and_value(self):
        raw = protocol_raw()
        raw["criteria"][6]["predicate"] = "pain_relief_effect == useless"
        raw["criteria"][7]["predicate"] = "tooth_wobbly == true"
        errs = "\n".join(self.errors(raw))
        self.assertIn("'useless' is not a value of pain_relief_effect", errs)
        self.assertIn("unknown field 'tooth_wobbly'", errs)

    def test_emergency_needs_route_and_floor_must_be_emergency(self):
        raw = protocol_raw()
        del raw["criteria"][0]["route"]
        raw["criteria"][6]["floor"] = True
        errs = "\n".join(self.errors(raw))
        self.assertIn("'EM1': EMERGENCY criterion needs route", errs)
        self.assertIn("'U1': a floor criterion must be EMERGENCY", errs)

    def test_narrative_with_predicate_is_rejected(self):
        raw = protocol_raw()
        raw["criteria"][9]["predicate"] = "recent_trauma == true"
        self.assertTrue(any("narrative criteria take no predicate" in e for e in self.errors(raw)))

    def test_every_red_flag_must_be_asked(self):
        raw = protocol_raw()
        raw["questions"] = [q for q in raw["questions"] if q["id"] != "Q5"]
        self.assertTrue(any("'bleeding_uncontrolled' is not asked" in e for e in self.errors(raw)))

    def test_criterion_fields_must_be_asked(self):
        raw = protocol_raw()
        raw["questions"] = [q for q in raw["questions"] if q["id"] != "Q9"]
        self.assertTrue(any("'U3': field 'pain_severity' is not asked" in e for e in self.errors(raw)))

    def test_mixed_red_flag_question_is_rejected(self):
        raw = protocol_raw()
        raw["questions"][3]["fields"] = ["fever", "pain_present"]
        self.assertTrue(any("mixes red-flag and other fields" in e for e in self.errors(raw)))

    def test_red_flag_marking_must_match_fields(self):
        raw = protocol_raw()
        raw["questions"][2]["red_flag"] = False
        self.assertTrue(any("red_flag must be true exactly" in e for e in self.errors(raw)))

    def test_unconditional_red_flag_after_other_questions(self):
        raw = protocol_raw()
        q5 = raw["questions"].pop(6)            # bleeding, unconditional
        raw["questions"].append(q5)
        self.assertTrue(any("must come before every other question" in e for e in self.errors(raw)))

    def test_question_needs_fixed_text(self):
        raw = protocol_raw()
        raw["questions"][0]["text"] = ""
        self.assertTrue(any("missing the fixed question text" in e for e in self.errors(raw)))

    def test_input_and_checklist_rules(self):
        raw = protocol_raw()
        by_id = {q["id"]: q for q in raw["questions"]}
        by_id["Q1"]["input"] = "slider"
        del by_id["Q2"]["group"]
        by_id["Q8"].update(input="yesno_checklist", group="B")   # pain_relief_effect is not yes/no
        errs = "\n".join(self.errors(raw))
        self.assertIn("'Q1': input must be one of", errs)
        self.assertIn("'Q2': a checklist row needs a group", errs)
        self.assertIn("'Q8': a checklist row must fill exactly one yes/no field", errs)

    def test_checklist_options(self):
        raw = protocol_raw()
        by_id = {q["id"]: q for q in raw["questions"]}
        by_id["Q15"]["options"] = [True, False, "not_sure"]   # YAML's reading of yes, no
        self.assertEqual(self.errors(raw), [])
        q15 = next(q for q in build_protocol(raw).questions if q.id == "Q15")
        self.assertEqual(q15.options, ("yes", "no", "not_sure"))
        by_id["Q1"]["options"] = ["yes", "no", "not_sure"]    # a red flag
        by_id["Q8"]["options"] = ["yes", "no"]                # a chat question
        errs = "\n".join(self.errors(raw))
        self.assertIn("'Q1': a red-flag row may not offer not_sure", errs)
        self.assertIn("'Q8': options are for checklist rows only", errs)

    def test_a_field_may_not_be_both_a_checklist_row_and_a_chat_question(self):
        raw = protocol_raw()
        by_id = {q["id"]: q for q in raw["questions"]}
        by_id["Q8"]["fields"] = ["pain_on_biting"]     # also a checklist row (Q15)
        self.assertTrue(any("filled both on a checklist and in the chat" in e
                            for e in self.errors(raw)))

    def test_every_red_flag_needs_a_floor_criterion(self):
        raw = protocol_raw()
        raw["criteria"] = [c for c in raw["criteria"] if c["id"] != "ED2"]  # bleeding
        self.assertTrue(any("'bleeding_uncontrolled' has no floor criterion" in e
                            for e in self.errors(raw)))

    def test_option_labels_come_from_the_protocol(self):
        raw = protocol_raw()
        raw["fixed_text"]["option_labels"] = {"yes": "Ya", "no": "Nope", "not_sure": "No idea"}
        by_id = {q["id"]: q for q in raw["questions"]}
        by_id["Q15"]["options"] = ["yes", "no", "not_sure"]
        q15 = next(q for q in build_protocol(raw).questions if q.id == "Q15")
        self.assertEqual(q15.option_items(),
                         [{"label": "Ya", "value": True}, {"label": "Nope", "value": False},
                          {"label": "No idea", "value": None}])

    def test_boolean_option_label_keys_are_reported(self):
        # YAML reads bare `yes:`/`no:` keys as booleans, so they must be quoted.
        raw = protocol_raw()
        raw["fixed_text"]["option_labels"] = {True: "Yes", False: "No"}
        self.assertTrue(any("option_labels" in e for e in self.errors(raw)))

    def test_labels_fall_back_when_the_file_omits_them(self):
        raw = protocol_raw()
        raw["fixed_text"].pop("option_labels", None)
        q = build_protocol(raw).questions[0]
        self.assertEqual([i["label"] for i in q.option_items()], ["Yes", "No"])

    def test_fixed_text_and_reask_template(self):
        raw = protocol_raw()
        del raw["fixed_text"]["disclaimer"]
        raw["reask_template"] = "Please answer yes or no."
        errs = self.errors(raw)
        self.assertIn("fixed_text.disclaimer is missing", errs)
        self.assertIn("reask_template must contain {question}", errs)

    def test_the_real_protocol_file_is_valid(self):
        # llm/protocol/triage_protocol.yaml is research-pm's content; this only
        # checks it still fits the format the code reads.
        if not P.PROTOCOL_PATH.exists():
            self.skipTest("no protocol file yet")
        import yaml
        raw = yaml.safe_load(P.PROTOCOL_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.errors(raw), [])

    def test_headlines_required(self):
        raw = protocol_raw()
        del raw["levels"]["SOON"]
        self.assertIn("levels.SOON.headline is missing", self.errors(raw))


class Levels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = build_protocol()

    def level(self, symptoms, visual=None):
        return self.protocol.protocol_level(symptoms, visual or {})

    def test_decided_cases(self):
        # docs/decisions.md 2026-09-22 (Phase 1–2 plan decisions), as encoded in the fixture
        self.assertEqual(self.level({"pain_present": True, "pain_severity": "severe"}), "URGENT")
        self.assertEqual(self.level({"pain_present": True, "pain_relief_effect": "not_helped"}), "URGENT")
        self.assertEqual(self.level({"pain_present": True, "pain_relief_effect": "helped"}), "SOON")
        self.assertEqual(self.level({}, {"flagged_teeth": [{"fdi": "16"}]}), "SOON")
        self.assertEqual(self.level({}, {"unexpected_missing_teeth": ["36"]}), "ROUTINE")
        self.assertEqual(self.level({}), "ROUTINE")
        self.assertEqual(self.level({"bleeding_uncontrolled": True}), "EMERGENCY")

    def test_route(self):
        met = self.protocol.met({"trauma_features": ["tooth_knocked_out"], "fever": True}, {})
        self.assertEqual(self.protocol.route(met), "medical")
        met = self.protocol.met({"trauma_features": ["tooth_knocked_out"]}, {})
        self.assertEqual(self.protocol.route(met), "dental")
        self.assertIsNone(self.protocol.route(self.protocol.met({"pain_present": True}, {})))

    def test_most_urgent(self):
        self.assertEqual(P.most_urgent(["SOON", None, "URGENT", "ROUTINE"]), "URGENT")
        self.assertIsNone(P.most_urgent([None]))


class Loading(unittest.TestCase):
    def test_unreviewed_is_refused_without_override(self):
        import tempfile
        from pathlib import Path

        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.yaml"
            path.write_text(yaml.safe_dump(protocol_raw()), encoding="utf-8")
            with self.assertRaises(P.UnreviewedProtocol):
                P.load(path, symptom_schema=SYMPTOM_SCHEMA)
            loaded = P.load(path, allow_unreviewed=True, symptom_schema=SYMPTOM_SCHEMA)
            self.assertEqual(loaded.version, "0.0-test")
            self.assertEqual(loaded.headlines["EMERGENCY"],
                             "This may be an emergency. Please go to a hospital as soon as possible.")

    def test_invalid_protocol_raises_with_all_errors(self):
        raw = protocol_raw()
        raw["criteria"][0]["level"] = "CRITICAL"
        raw["questions"][0]["text"] = ""
        with self.assertRaises(P.ProtocolError) as ctx:
            build_protocol(raw)
        self.assertIn("CRITICAL", str(ctx.exception))
        self.assertIn("fixed question text", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
