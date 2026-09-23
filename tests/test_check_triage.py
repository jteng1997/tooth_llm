"""Unit tests for src/check_triage.py (Test 5) — the checker must be able to fail.

    .venv/Scripts/python -m unittest discover -s tests -p "test_check_triage.py" -v

No GPU, no Ollama. The statistics are checked against independent
implementations or closed forms, the direction of under/over-triage against
hand-worked cases, and the whole pipeline against llm/eval/triage_sanity_cases.json,
whose expected rules.py result was worked out by hand from rules.py's source.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import check_triage as ct  # noqa: E402

SANITY = json.loads((REPO_ROOT / "llm" / "eval" / "triage_sanity_cases.json").read_text(encoding="utf-8"))


class Direction(unittest.TestCase):
    def test_less_urgent_is_under(self):
        self.assertEqual(ct.compare("URGENT", "URGENT", "SOON")["outcome"], "under")
        self.assertEqual(ct.compare("URGENT", "URGENT", "EMERGENCY")["outcome"], "over")
        self.assertEqual(ct.compare("SOON", "SOON", "SOON")["outcome"], "agree")

    def test_severity(self):
        self.assertTrue(ct.compare("EMERGENCY", "EMERGENCY", "URGENT")["severe"])  # any missed emergency
        self.assertTrue(ct.compare("URGENT", "URGENT", "ROUTINE")["severe"])       # two levels
        self.assertFalse(ct.compare("URGENT", "URGENT", "SOON")["severe"])

    def test_retake_instead_of_care_is_under(self):
        # rules.URGENCY_RANK puts RETAKE at 0, above EMERGENCY; using it would
        # score this as over-triage. It must be the worst kind of under-triage.
        out = ct.compare("EMERGENCY", "EMERGENCY", "RETAKE")
        self.assertEqual(out["outcome"], "under")
        self.assertTrue(out["severe"])
        self.assertEqual(ct.compare("SOON", "SOON", "RETAKE")["outcome"], "under")

    def test_retake_cases(self):
        self.assertEqual(ct.compare("ROUTINE", "RETAKE", "RETAKE"),
                         {"outcome": "agree", "retake": "correct"})
        self.assertEqual(ct.compare("ROUTINE", "ROUTINE", "RETAKE")["outcome"], "spurious_retake")
        missed = ct.compare("SOON", "RETAKE", "ROUTINE")
        self.assertEqual((missed["outcome"], missed["retake"]), ("under", "missed"))

    def test_level_systems_ignore_retake(self):
        self.assertEqual(ct.compare("SOON", "RETAKE", "SOON", kind="level")["outcome"], "agree")

    def test_unscored(self):
        self.assertEqual(ct.compare("SOON", "SOON", None)["outcome"], "not_scored")


class Statistics(unittest.TestCase):
    def test_kappa_matches_sklearn(self):
        from sklearn.metrics import cohen_kappa_score
        import random
        rng = random.Random(3)
        for _ in range(20):
            pairs = [(rng.choice(ct.LEVELS), rng.choice(ct.LEVELS)) for _ in range(rng.randint(5, 60))]
            ref, got = zip(*pairs)
            want = cohen_kappa_score(ref, got, weights="linear", labels=list(ct.LEVELS))
            self.assertAlmostEqual(ct.weighted_kappa(pairs), want, places=10)

    def test_kappa_perfect_and_reversed(self):
        pairs = [(lv, lv) for lv in ct.LEVELS for _ in range(5)]
        self.assertAlmostEqual(ct.weighted_kappa(pairs), 1.0)
        flipped = [(lv, ct.LEVELS[3 - ct.ORDER[lv]]) for lv, _ in pairs]
        self.assertLess(ct.weighted_kappa(flipped), 0)

    def test_kappa_single_category(self):
        self.assertEqual(ct.weighted_kappa([("SOON", "SOON")] * 4), 1.0)

    def test_clopper_pearson_closed_forms(self):
        lo, hi = ct.clopper_pearson(0, 200)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 1 - 0.025 ** (1 / 200), places=10)   # 1.83%, not the 1.5% of the rule of three
        self.assertAlmostEqual(ct.upper_one_sided(0, 200), 1 - 0.05 ** (1 / 200), places=10)  # 1.49%
        lo, hi = ct.clopper_pearson(200, 200)
        self.assertAlmostEqual(lo, 0.025 ** (1 / 200), places=10)
        self.assertEqual(hi, 1.0)

    def test_clopper_pearson_known_value(self):
        # 5/20: exact 95% CI (0.0866, 0.4910), standard tables
        lo, hi = ct.clopper_pearson(5, 20)
        self.assertAlmostEqual(lo, 0.0866, places=4)
        self.assertAlmostEqual(hi, 0.4910, places=4)

    def test_mcnemar(self):
        a = [True] * 6 + [False] * 10
        b = [False] * 6 + [False] * 10
        out = ct.mcnemar_exact(a, b)
        self.assertEqual((out["only_first_under"], out["only_second_under"]), (6, 0))
        self.assertAlmostEqual(out["p_exact"], 2 * 0.5 ** 6)
        self.assertEqual(ct.mcnemar_exact([True], [True])["p_exact"], 1.0)


class SanityRun(unittest.TestCase):
    """rules.py on the sanity file: the numbers in the file's note, by hand."""

    @classmethod
    def setUpClass(cls):
        cls.summary = ct.evaluate(SANITY, "rules", verbose=False)
        cls.rules = cls.summary["systems"]["rules"]

    def test_file_is_valid(self):
        errors, _ = ct.validate_cases(SANITY)
        self.assertEqual(errors, [])

    def test_hand_worked_result(self):
        r = self.rules
        self.assertEqual(r["n_scored"], 20)
        self.assertEqual(r["under_ids"], ["S001", "S002", "S003", "S004", "S005", "S006",
                                          "S013", "S016", "S017", "S018", "S019"])
        self.assertEqual(r["severe_under_ids"], ["S001", "S002", "S003", "S013", "S017",
                                                 "S018", "S019"])
        self.assertEqual(r["over_ids"], ["S010"])
        self.assertEqual(r["agree"], 8)
        self.assertEqual(r["retake_correct"], 1)
        self.assertEqual(r["kappa_n"], 17)  # S012, S013, S019 have a RETAKE side

    def test_every_rationale_names_the_outcome(self):
        # The rationale was written before the run; it must say the same thing.
        words = {"agree": "(agree)", "over": "(over)", "under": "under)"}
        for case in SANITY["cases"]:
            outcome = self.rules["outcomes"][case["id"]]["outcome"]
            with self.subTest(case=case["id"]):
                self.assertIn(words[outcome], case["key"]["rationale"])


class CheckerMustFail(unittest.TestCase):
    def _stub_rules(self, level):
        """evaluate() with rules.assess replaced by a constant answer."""
        original = ct.run_rules
        ct.run_rules = lambda case: {"rules": level}
        try:
            return ct.evaluate(SANITY, "rules", verbose=False)["systems"]["rules"]
        finally:
            ct.run_rules = original

    def test_always_routine_is_caught(self):
        r = self._stub_rules("ROUTINE")
        # every non-ROUTINE key under-triaged, the RETAKE-expected case scored as a missed retake
        non_routine = sum(c["key"]["level"] != "ROUTINE" for c in SANITY["cases"])
        self.assertEqual(r["under"], non_routine)
        self.assertEqual(r["retake_missed"], 1)

    def test_always_emergency_never_under(self):
        r = self._stub_rules("EMERGENCY")
        self.assertEqual(r["under"], 0)
        self.assertEqual(r["over"], sum(c["key"]["level"] != "EMERGENCY" for c in SANITY["cases"]))
        self.assertLess(r["kappa_linear"], ct.KAPPA_BAR)

    def test_perfect_system_passes(self):
        original = ct.run_rules
        ct.run_rules = lambda case: {"rules": ct.expected_urgency(case)}
        try:
            r = ct.evaluate(SANITY, "rules", verbose=False)["systems"]["rules"]
        finally:
            ct.run_rules = original
        self.assertEqual((r["under"], r["over"], r["agree"]), (0, 0, 20))
        self.assertAlmostEqual(r["kappa_linear"], 1.0)


class Validation(unittest.TestCase):
    def _case(self, **changes):
        spec = copy.deepcopy(SANITY)
        case = spec["cases"][3]  # S004: URGENT, pain not helped
        for path, value in changes.items():
            target = case
            *parents, last = path.split(".")
            for p in parents:
                target = target[p]
            target[last] = value
        return spec

    def test_rejects_pain_details_without_pain(self):
        errors, _ = ct.validate_cases(self._case(**{"symptoms.pain_present": False}))
        self.assertTrue(any("pain_present is false" in e for e in errors), errors)

    def test_rejects_features_without_the_flag(self):
        errors, _ = ct.validate_cases(self._case(**{"symptoms.swelling_features": ["worsening_fast"]}))
        self.assertTrue(any("swelling_features" in e for e in errors), errors)

    def test_rejects_third_molar_as_missing(self):
        errors, _ = ct.validate_cases(self._case(**{"visual_summary.unexpected_missing_teeth": ["38"]}))
        self.assertTrue(any("cannot be produced" in e for e in errors), errors)

    def test_rejects_route_on_a_non_emergency(self):
        errors, _ = ct.validate_cases(self._case(**{"key.emergency_route": "dental"}))
        self.assertTrue(any("emergency_route" in e for e in errors), errors)

    def test_rejects_duplicates(self):
        spec = copy.deepcopy(SANITY)
        spec["cases"].append(copy.deepcopy(spec["cases"][0]))
        errors, _ = ct.validate_cases(spec)
        self.assertTrue(any("duplicate id" in e for e in errors), errors)
        spec["cases"][-1]["id"] = "S099"
        errors, _ = ct.validate_cases(spec)
        self.assertTrue(any("same symptoms" in e for e in errors), errors)

    def test_rejects_dentist_label_outside_the_scale(self):
        errors, _ = ct.validate_cases(self._case(dentist_label={"level": "RETAKE"}))
        self.assertTrue(any(e.startswith("schema") for e in errors), errors)

    def test_findings_round_trip(self):
        for case in SANITY["cases"]:
            f = ct.findings_from_visual(case["visual_summary"])
            self.assertEqual(ct.rules.caries_teeth(f), sorted(case["visual_summary"]["flagged_teeth"]))


class KeyAgainstProtocol(unittest.TestCase):
    """_check_key with the test protocol from fixtures (ids EM1, U1, N1, P1 ...)."""

    @classmethod
    def setUpClass(cls):
        try:
            from fixtures import build_protocol
            cls.protocol = build_protocol()
        except Exception as exc:  # the loader is being changed by llm-dev
            raise unittest.SkipTest(f"fixture protocol does not build: {exc}")

    def case(self, level, criteria, **symptoms):
        s = {"schema_version": "1.1", "pain_present": False, **symptoms}
        return {"id": "K001", "key": {"level": level, "criteria_met": criteria},
                "symptoms": s, "visual_summary": {"images_usable": True, "flagged_teeth": [],
                                                  "unexpected_missing_teeth": []}}

    def test_consistent_key(self):
        c = self.case("URGENT", ["U1", "N1"], pain_present=True, pain_relief_effect="not_helped")
        self.assertEqual(ct._check_key(c, self.protocol), [])

    def test_omitted_criterion(self):
        c = self.case("SOON", ["N1"], pain_present=True, pain_relief_effect="not_helped")
        errors = ct._check_key(c, self.protocol)
        self.assertTrue(any("omits" in e and "U1" in e for e in errors), errors)
        self.assertFalse(any("imply" in e for e in errors), errors)  # level matches what was listed

    def test_level_below_criteria(self):
        c = self.case("SOON", ["U1", "N1"], pain_present=True, pain_relief_effect="not_helped")
        self.assertTrue(any("imply URGENT" in e for e in ct._check_key(c, self.protocol)))

    def test_listed_criterion_that_does_not_hold(self):
        c = self.case("URGENT", ["U1", "N1"], pain_present=True, pain_relief_effect="helped")
        self.assertTrue(any("do not hold" in e for e in ct._check_key(c, self.protocol)))

    def test_narrative_raises_the_level(self):
        c = self.case("SOON", ["N3"])
        self.assertEqual(ct._check_key(c, self.protocol), [])


class LlmPathWithStub(unittest.TestCase):
    """The llm mode's bookkeeping, with a stub instead of Ollama."""

    @classmethod
    def setUpClass(cls):
        try:
            from fixtures import build_protocol
            cls.protocol = build_protocol()
            import triage  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(f"triage or the fixture protocol is not importable: {exc}")

    def run_with(self, answer):
        return ct.evaluate(SANITY, "llm", model="stub", protocol=self.protocol,
                           llm=lambda messages, schema: answer, verbose=False)

    def test_garbage_output_is_counted_as_fallback(self):
        s = self.run_with("not json")
        ops = s["operations"]
        self.assertEqual(ops["model_called"] + ops["floor_skipped_model"], 20)
        self.assertEqual(ops["invalid_fallback"], ops["model_called"])
        self.assertEqual(ops["fallback_rate"], 1.0)
        self.assertEqual(s["systems"]["llm_only"]["n_scored"], 0)  # never a model level

    def test_model_saying_routine_is_under_triage_for_the_model(self):
        s = self.run_with('{"criteria_met": [], "level": "ROUTINE", "uncertain": false}')
        llm_only = s["systems"]["llm_only"]
        self.assertGreater(llm_only["under"], 0)
        # the composed result can only be raised above the model, never lowered
        for case in s["cases"]:
            run = case["runs"][0]
            if run["llm_only"] and run["final"] in ct.ORDER:
                self.assertLessEqual(ct.ORDER[run["final"]], ct.ORDER[run["llm_only"]], case["id"])


if __name__ == "__main__":
    unittest.main()
