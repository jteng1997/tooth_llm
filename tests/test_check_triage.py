"""Unit tests for src/check_triage.py (Test 5) — the checker must be able to fail.

    .venv/Scripts/python -m unittest discover -s tests -p "test_check_triage.py" -v

No GPU, no Ollama. The statistics are checked against independent
implementations or closed forms, the scoring rules of
docs/plans/test5-analysis-spec.md §3 against hand-worked cases, and the whole
pipeline against llm/eval/triage_sanity_cases.json (worked out by hand from
rules.py's source) and, where the local held-out keys exist, against the
spec's own dry-run numbers (§3a).
"""
import copy
import json
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import check_triage as ct  # noqa: E402

SANITY_RAW = json.loads((REPO_ROOT / "llm" / "eval" / "triage_sanity_cases.json").read_text(encoding="utf-8"))
SANITY = ct.for_protocol(SANITY_RAW, "0.3")       # the primary keys
SANITY_V02 = ct.for_protocol(SANITY_RAW, "0.2")   # the keys under the frozen v0.2 protocol
DRAFT_V03 = REPO_ROOT / "docs" / "plans" / "protocol-v0.3" / "triage_protocol.yaml"
HELDOUT = REPO_ROOT / "labels" / "heldout" / "triage_heldout_keys.json"


def row(cid, ref, got, boundary=False, ambiguous=False, ref_expected=None, images_usable=True):
    return {"id": cid, "ref": ref, "ref_expected": ref_expected or ref, "got": got,
            "boundary": boundary, "ambiguous": ambiguous, "images_usable": images_usable}


class Direction(unittest.TestCase):
    def test_less_urgent_is_under(self):
        self.assertEqual(ct.compare("URGENT", "SOON")["outcome"], "under")
        self.assertEqual(ct.compare("URGENT", "EMERGENCY")["outcome"], "over")
        self.assertEqual(ct.compare("SOON", "SOON")["outcome"], "agree")

    def test_severe_is_two_levels(self):
        # spec §3: severe = two or more levels below the key; a missed
        # emergency one level down is counted as missed EMERGENCY, not severe.
        one_down = ct.compare("EMERGENCY", "URGENT")
        self.assertFalse(one_down["severe"])
        self.assertTrue(one_down["missed_emergency"])
        self.assertTrue(ct.compare("URGENT", "ROUTINE")["severe"])
        self.assertTrue(ct.compare("EMERGENCY", "SOON")["severe"])
        self.assertFalse(ct.compare("URGENT", "SOON")["severe"])
        self.assertFalse(ct.compare("URGENT", "SOON")["missed_emergency"])

    def test_retake_with_emergency_or_urgent_key_is_severe_under(self):
        # rules.URGENCY_RANK puts RETAKE at 0, above EMERGENCY; using it would
        # score this as over-triage.
        for key in ("EMERGENCY", "URGENT"):
            out = ct.compare(key, "RETAKE")
            self.assertEqual(out["outcome"], "under", key)
            self.assertTrue(out["severe"], key)
            self.assertEqual(out["missed_emergency"], key == "EMERGENCY")

    def test_retake_with_soon_or_routine_key(self):
        # spec §9.1: designed (unusable photos) -> excluded; usable -> unwarranted, a scored miss
        for key in ("SOON", "ROUTINE"):
            out = ct.compare(key, "RETAKE", images_usable=False)
            self.assertEqual(out["outcome"], "excluded_retake", key)
            self.assertFalse(ct.is_scored(out))
            out = ct.compare(key, "RETAKE", images_usable=True)
            self.assertEqual(out["outcome"], "unwarranted_retake", key)
            self.assertTrue(ct.is_scored(out))

    def test_retake_with_urgent_key_is_under_whatever_the_photos(self):
        self.assertEqual(ct.compare("URGENT", "RETAKE", images_usable=False)["outcome"], "under")

    def test_unscored(self):
        self.assertEqual(ct.compare("SOON", None)["outcome"], "not_scored")
        self.assertFalse(ct.is_scored(ct.compare("SOON", None)))


class Statistics(unittest.TestCase):
    def test_kappa_matches_sklearn(self):
        from sklearn.metrics import cohen_kappa_score
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


class Bootstrap(unittest.TestCase):
    PAIRS = ([("EMERGENCY", "EMERGENCY")] * 12 + [("EMERGENCY", "SOON")] * 3
             + [("URGENT", "URGENT")] * 10 + [("URGENT", "SOON")] * 4
             + [("SOON", "SOON")] * 11 + [("SOON", "ROUTINE")] * 2
             + [("ROUTINE", "ROUTINE")] * 9 + [("ROUTINE", "SOON")] * 3)

    def test_pre_registered_parameters(self):
        self.assertEqual((ct.BOOTSTRAP_REPS, ct.BOOTSTRAP_SEED), (2000, 20260923))

    def test_matches_an_independent_implementation(self):
        from sklearn.metrics import cohen_kappa_score
        rng = random.Random(ct.BOOTSTRAP_SEED)
        n, values = len(self.PAIRS), []
        for _ in range(300):
            sample = [self.PAIRS[rng.randrange(n)] for _ in range(n)]
            ref, got = zip(*sample)
            values.append(cohen_kappa_score(ref, got, weights="linear", labels=list(ct.LEVELS)))
        values.sort()
        want = (values[int(0.025 * 300)], values[int(0.975 * 300) - 1])
        got = ct.bootstrap_kappa(self.PAIRS, reps=300)
        self.assertAlmostEqual(got[0], want[0], places=10)
        self.assertAlmostEqual(got[1], want[1], places=10)

    def test_seeded_and_brackets_the_estimate(self):
        a = ct.bootstrap_kappa(self.PAIRS, reps=400)
        self.assertEqual(a, ct.bootstrap_kappa(self.PAIRS, reps=400))
        self.assertNotEqual(a, ct.bootstrap_kappa(self.PAIRS, reps=400, seed=1))
        k = ct.weighted_kappa(self.PAIRS)
        self.assertLess(a[0], k)
        self.assertGreater(a[1], k)


class Summarise(unittest.TestCase):
    """Eight hand-worked rows, one per scoring path."""

    @classmethod
    def setUpClass(cls):
        cls.rows = [
            row("A", "EMERGENCY", "URGENT", boundary=True),   # under, missed EM, not severe
            row("B", "URGENT", "RETAKE"),                     # under, severe, not in kappa
            row("C", "SOON", "RETAKE"),                       # unwarranted: a miss, not in kappa
            row("D", "ROUTINE", "SOON"),                      # over
            row("E", "SOON", "SOON", boundary=True),          # agree
            row("F", "ROUTINE", None),                        # not scored
            row("G", "EMERGENCY", "EMERGENCY", ambiguous=True),  # agree
            row("H", "ROUTINE", "RETAKE", images_usable=False),  # designed: excluded
        ]
        cls.s = ct.summarise(cls.rows, "x")

    def test_denominators(self):
        s = self.s
        self.assertEqual((s["n_cases"], s["n_scored"], s["not_scored"], s["excluded_retake"]),
                         (8, 6, 1, 1))
        self.assertEqual(s["kappa_n"], 4)
        self.assertAlmostEqual(s["exact_agreement"], 2 / 6)
        self.assertAlmostEqual(s["under_rate"], 2 / 6)

    def test_unwarranted_retake(self):
        s = self.s
        self.assertEqual(s["unwarranted_retake_ids"], ["C"])
        self.assertNotIn("C", s["under_ids"] + s["over_ids"])
        lo, hi = s["unwarranted_retake_ci95"]
        self.assertEqual((round(lo, 6), round(hi, 6)),
                         tuple(round(x, 6) for x in ct.clopper_pearson(1, 6)))
        self.assertEqual(s["per_level"]["SOON"]["n_key"], 2)     # C is a miss in SOON recall
        self.assertAlmostEqual(s["per_level"]["SOON"]["recall"], 1 / 2)

    def test_counts(self):
        s = self.s
        self.assertEqual(s["under_ids"], ["A", "B"])
        self.assertEqual(s["severe_under_ids"], ["B"])
        self.assertEqual(s["missed_emergency_ids"], ["A"])
        self.assertEqual((s["missed_emergency"], s["n_key_emergency"]), (1, 2))
        self.assertEqual(s["over_ids"], ["D"])
        self.assertEqual(s["agree"], 2)

    def test_boundary_and_ambiguous_split(self):
        self.assertEqual(self.s["under_boundary"], {"under": 1, "n": 2})
        self.assertEqual(self.s["under_not_boundary"], {"under": 1, "n": 4})
        self.assertEqual(self.s["under_ambiguous"], {"under": 0, "n": 1})

    def test_confusion_recall_precision(self):
        s = self.s
        self.assertEqual(s["confusion"]["EMERGENCY"]["URGENT"], 1)
        self.assertEqual(s["confusion"]["ROUTINE"]["SOON"], 1)
        self.assertEqual(sum(v for r in s["confusion"].values() for v in r.values()), 4)
        pl = s["per_level"]
        self.assertAlmostEqual(pl["EMERGENCY"]["recall"], 1 / 2)
        self.assertAlmostEqual(pl["URGENT"]["recall"], 0.0)      # the RETAKE is a miss
        self.assertEqual(pl["URGENT"]["n_key"], 1)
        self.assertAlmostEqual(pl["SOON"]["precision"], 1 / 2)   # D said SOON wrongly
        self.assertAlmostEqual(pl["EMERGENCY"]["precision"], 1.0)

    def test_photo_quality_counts(self):
        ph = self.s["photo_quality"]
        self.assertEqual((ph["retake_emitted"], ph["retake_under"], ph["retake_excluded"],
                          ph["retake_unwarranted"]), (3, 1, 1, 1))

    def test_retake_by_design_is_counted_not_scored(self):
        s = ct.summarise([row("P", "SOON", "SOON", ref_expected="RETAKE", images_usable=False),
                          row("Q", "ROUTINE", "RETAKE", ref_expected="RETAKE", images_usable=False)],
                         "x")
        self.assertEqual((s["n_scored"], s["agree"], s["excluded_retake"]), (1, 1, 1))
        self.assertEqual(s["photo_quality"]["retake_expected_by_design"], 2)
        self.assertEqual(s["photo_quality"]["retake_missed_by_design"], 1)


class Paired(unittest.TestCase):
    def test_common_index_set(self):
        # C is excluded for `a` (designed RETAKE, SOON key, unusable photos) but
        # under-triaged by `b`: it must not enter the paired test at all.
        a = ct.summarise([row("A", "URGENT", "SOON"), row("B", "SOON", "SOON"),
                          row("C", "SOON", "RETAKE", images_usable=False)], "a")
        b = ct.summarise([row("A", "URGENT", "URGENT"), row("B", "SOON", "ROUTINE"),
                          row("C", "SOON", "ROUTINE", images_usable=False)], "b")
        p = ct.paired(a, b)
        self.assertEqual(p["n_common"], 2)
        self.assertEqual((p["only_first_under"], p["only_second_under"]), (1, 1))
        self.assertEqual((p["first_under"], p["second_under"]), (1, 1))

    def _pair(self, n_only_a, n_only_b, n_both_ok=5):
        ra, rb = [], []
        for i in range(n_only_a):
            ra.append(row(f"a{i}", "URGENT", "SOON"))
            rb.append(row(f"a{i}", "URGENT", "URGENT"))
        for i in range(n_only_b):
            ra.append(row(f"b{i}", "URGENT", "URGENT"))
            rb.append(row(f"b{i}", "URGENT", "SOON"))
        for i in range(n_both_ok):
            ra.append(row(f"c{i}", "SOON", "SOON"))
            rb.append(row(f"c{i}", "SOON", "SOON"))
        return ct.paired(ct.summarise(ra, "a"), ct.summarise(rb, "b"))

    def test_underpowered_reports_no_p_value(self):
        p = self._pair(6, 3)
        self.assertTrue(p["underpowered"])
        self.assertIsNone(p["p_exact"])
        self.assertEqual((p["discordant"], p["only_first_under"], p["only_second_under"]), (9, 6, 3))
        self.assertEqual(p["first_under_ci95"], ct.clopper_pearson(6, 14))
        self.assertEqual(p["second_under_ci95"], ct.clopper_pearson(3, 14))
        self.assertEqual(p["discordant_share_ci95"], ct.clopper_pearson(6, 9))   # b / (b + c)

    def test_no_discordant_pairs_no_share_ci(self):
        p = self._pair(0, 0)
        self.assertTrue(p["underpowered"])
        self.assertIsNone(p["discordant_share_ci95"])

    def test_ten_discordant_pairs_get_a_p_value(self):
        p = self._pair(10, 0)
        self.assertFalse(p["underpowered"])
        self.assertAlmostEqual(p["p_exact"], 2 * 0.5 ** 10)
        self.assertEqual(p["discordant_share_ci95"], ct.clopper_pearson(10, 10))


class CodeCeiling(unittest.TestCase):
    def test_counts(self):
        pc = ct.summarise([row("N1", "SOON", "ROUTINE"), row("N2", "URGENT", "SOON"),
                           row("S1", "URGENT", "URGENT"), row("S2", "SOON", "SOON")], "protocol_check")
        final = ct.summarise([row("N1", "SOON", "SOON"), row("N2", "URGENT", "SOON"),
                              row("S1", "URGENT", "URGENT"), row("S2", "SOON", "URGENT")], "final")
        cc = ct.code_ceiling({"protocol_check": pc, "final": final})
        self.assertEqual(cc["protocol_check_misses"], ["N1", "N2"])
        self.assertEqual(cc["final"]["fixed_ids"], ["N1"])
        self.assertEqual(cc["final"]["under_where_protocol_not"], 0)
        self.assertEqual(cc["final"]["wrong_where_protocol_right_ids"], ["S2"])

    def test_final_below_the_code_ceiling_is_caught(self):
        pc = ct.summarise([row("S1", "URGENT", "URGENT")], "protocol_check")
        final = ct.summarise([row("S1", "URGENT", "SOON")], "final")
        self.assertEqual(ct.code_ceiling({"protocol_check": pc, "final": final})
                         ["final"]["under_where_protocol_not_ids"], ["S1"])


class SanityRun(unittest.TestCase):
    """rules.py on the sanity file: the numbers in the file's note, by hand,
    under the v0.3 keys and the v0.2 keys (key_until)."""

    UNDER_V02 = ["S001", "S002", "S003", "S004", "S005", "S006", "S013", "S016", "S017", "S018",
                 "S019"]

    @classmethod
    def setUpClass(cls):
        cls.rules = ct.evaluate(SANITY, "rules", verbose=False)["systems"]["rules"]
        cls.rules_v02 = ct.evaluate(SANITY_V02, "rules", verbose=False)["systems"]["rules"]

    def test_file_is_valid(self):
        for name, spec in (("raw", SANITY_RAW), ("v0.3", SANITY), ("v0.2", SANITY_V02)):
            with self.subTest(keys=name):
                errors, _ = ct.validate_cases(spec)
                self.assertEqual(errors, [])

    def test_keys_agree_with_the_real_protocol(self):
        protocol, err = ct.load_protocol()
        if err:
            self.skipTest(f"protocol does not load: {err}")
        errors, _ = ct.validate_cases(ct.for_protocol(SANITY_RAW, protocol.version), protocol,
                                      need_words=False)
        self.assertEqual(errors, [])

    def test_v02_keys_agree_with_the_frozen_v02(self):
        protocol, err = ct.load_protocol(ct.HELDOUT_PROTOCOL_FILE)
        if err:
            self.skipTest(f"v0.2 protocol does not load: {err}")
        self.assertEqual(protocol.version, "0.2")
        errors, _ = ct.validate_cases(SANITY_V02, protocol, need_words=False)
        self.assertEqual(errors, [])

    def test_v03_keys_agree_with_the_v03_draft(self):
        # The research-pm draft the live file was switched to (same bytes on 2026-09-29).
        if not DRAFT_V03.exists():
            self.skipTest("no v0.3 draft (switched live, or moved)")
        import protocol as protocol_mod
        try:
            draft = protocol_mod.load(DRAFT_V03, allow_unreviewed=True)
        except Exception as exc:
            self.skipTest(f"v0.3 draft does not load here: {type(exc).__name__}: {exc}")
        self.assertEqual(draft.version, "0.3")
        errors, _ = ct.validate_cases(SANITY, draft, need_words=False)
        self.assertEqual(errors, [])

    def check_shared(self, r):
        self.assertEqual(r["n_scored"], 24)
        self.assertEqual(r["excluded_retake"], 1)
        self.assertEqual(r["severe_under_ids"], ["S001", "S002", "S003", "S013", "S017",
                                                 "S018", "S019"])
        self.assertEqual(r["missed_emergency_ids"], ["S001", "S002", "S003", "S013", "S017", "S018"])
        self.assertEqual(r["kappa_n"], 22)  # S013, S019 answered RETAKE: not a level

    def test_hand_worked_result_v03(self):
        r = self.rules
        self.check_shared(r)
        # S023: relief unanswered is URGENT (U10); rules.py says SOON, one level down
        self.assertEqual(r["under_ids"], sorted(self.UNDER_V02 + ["S023"]))
        # rules.py R3 keeps lingering or night pain URGENT whatever the relief did
        self.assertEqual(r["over_ids"], ["S007", "S010", "S021", "S022"])
        self.assertEqual(r["agree"], 8)

    def test_hand_worked_result_v02(self):
        r = self.rules_v02
        self.check_shared(r)
        self.assertEqual(r["under_ids"], self.UNDER_V02)
        self.assertEqual(r["over_ids"], ["S010"])
        self.assertEqual(r["agree"], 12)

    def test_only_the_v03_cases_change_level(self):
        changed = {c["id"]: (c2["key"]["level"], c["key"]["level"])
                   for c, c2 in zip(SANITY["cases"], SANITY_V02["cases"])
                   if c["key"]["level"] != c2["key"]["level"]}
        self.assertEqual(changed, {"S007": ("URGENT", "SOON"), "S021": ("URGENT", "SOON"),
                                   "S022": ("URGENT", "SOON"), "S023": ("SOON", "URGENT")})

    def test_every_rationale_names_the_outcome(self):
        # The rationale was written before the run; it must say the same thing.
        words = {"agree": "(agree)", "over": "(over)", "under": "under)",
                 "excluded_retake": "(excluded"}
        for name, spec, rules in (("v0.3", SANITY, self.rules), ("v0.2", SANITY_V02, self.rules_v02)):
            for case in spec["cases"]:
                outcome = rules["outcomes"][case["id"]]["outcome"]
                with self.subTest(keys=name, case=case["id"]):
                    self.assertIn(words[outcome], case["key"]["rationale"])


class ForProtocol(unittest.TestCase):
    """key_until: the sanity file's keys for the protocol that is loaded."""

    def test_picks_the_key_for_the_version(self):
        s007 = {c["id"]: c for c in SANITY["cases"]}["S007"]
        self.assertEqual((s007["key"]["level"], s007["key"]["criteria_met"]), ("SOON", ["S1"]))
        s007 = {c["id"]: c for c in SANITY_V02["cases"]}["S007"]
        self.assertEqual((s007["key"]["level"], s007["key"]["criteria_met"]), ("URGENT", ["U5", "S1"]))
        self.assertEqual((SANITY["protocol_version"], SANITY_V02["protocol_version"]), ("0.3", "0.2"))

    def test_later_or_unknown_version_keeps_the_primary_keys(self):
        for version in ("0.4", "1.0", None):
            spec = ct.for_protocol(SANITY_RAW, version)
            with self.subTest(version=version):
                self.assertEqual([c["key"] for c in spec["cases"]], [c["key"] for c in SANITY["cases"]])
                self.assertFalse(any("key_until" in c for c in spec["cases"]))

    def test_lowest_applying_version_wins(self):
        spec = {"protocol_version": "0.3", "cases": [
            {"id": "X001", "key": {"level": "SOON"},
             "key_until": {"0.1": {"level": "ROUTINE"}, "0.2": {"level": "URGENT"}}}]}
        self.assertEqual(ct.for_protocol(spec, "0.1")["cases"][0]["key"]["level"], "ROUTINE")
        self.assertEqual(ct.for_protocol(spec, "0.2")["cases"][0]["key"]["level"], "URGENT")
        self.assertEqual(ct.for_protocol(spec, "0.3")["cases"][0]["key"]["level"], "SOON")
        self.assertEqual(ct.for_protocol(spec, "0.0-test")["cases"][0]["key"]["level"], "ROUTINE")
        self.assertIn("key_until", spec["cases"][0])                # input untouched

    def test_file_without_key_until_is_returned_as_is(self):
        spec = {"protocol_version": "0.2", "cases": [{"id": "X001", "key": {"level": "SOON"}}]}
        self.assertIs(ct.for_protocol(spec, "0.2"), spec)

    def test_wrong_keys_fail_against_the_protocol(self):
        # The check can fail: the v0.3 keys against the v0.2 protocol, or the
        # other way round, must be refused, and on exactly the cases that differ.
        protocol, err = ct.load_protocol()
        if err:
            self.skipTest(f"protocol does not load: {err}")
        wrong = SANITY if protocol.version == "0.2" else SANITY_V02
        errors, _ = ct.validate_cases(wrong, protocol, need_words=False)
        self.assertEqual(sorted({e.split(":")[0] for e in errors}),
                         ["S007", "S021", "S022", "S023", "S024", "S025"])


class CaveatVersion(unittest.TestCase):
    """The SDCEP caveat names the protocol version the run loaded, not a
    hard-coded one (it said v0.1 after v0.2 went live)."""

    def report(self, protocol):
        import contextlib
        import io
        summary = ct.evaluate(SANITY, "rules", protocol=protocol, verbose=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ct.print_report(summary)
        return summary, buf.getvalue()

    def test_version_comes_from_the_loaded_protocol(self):
        protocol, err = ct.load_protocol()
        if err:
            self.skipTest(f"protocol does not load: {err}")
        summary, text = self.report(protocol)
        self.assertEqual(summary["protocol_version"], protocol.version)
        self.assertIn(f"as encoded in protocol v{protocol.version}, including", text)
        self.assertNotIn("{version}", text)

    def test_another_version_is_named_as_such(self):
        from types import SimpleNamespace
        stub = SimpleNamespace(version="9.9", protocol_level=lambda s, v: "ROUTINE")
        _, text = self.report(stub)
        self.assertIn("protocol v9.9,", text)
        self.assertNotIn("v0.1", text)

    def test_no_protocol_says_so(self):
        _, text = self.report(None)
        self.assertIn("protocol (version unknown: protocol not loaded)", text)
        self.assertEqual(ct.caveats(None)[1], ct.CAVEATS[1])    # no version in it: unchanged
        self.assertFalse(any("{version}" in c for c in ct.caveats(None)))


class Caveats(unittest.TestCase):
    """Caveat 3 names the loaded protocol's version (it said v0.2 after v0.3
    went live) and is only true while that protocol has no narrative criterion."""

    def check(self, path):
        protocol, err = ct.load_protocol(path)
        if err:
            self.skipTest(f"protocol does not load: {err}")
        narrative = [c for c in protocol.criteria if c.kind == "narrative"]
        if narrative:
            self.skipTest("protocol has narrative criteria again; caveat 3 needs rewording")
        self.assertNotIn("narrative", ct.CAVEATS[2])
        self.assertIn(f"protocol v{protocol.version} is structured", ct.caveats(protocol.version)[2])
        return protocol

    def test_caveat_matches_the_live_protocol(self):
        self.check(ct.PROTOCOL_FILE)

    def test_caveat_matches_the_pinned_heldout_protocol(self):
        self.assertEqual(self.check(ct.HELDOUT_PROTOCOL_FILE).version, ct.HELDOUT_PROTOCOL_VERSION)

    def test_no_version_is_hard_coded(self):
        for c in ct.CAVEATS:
            self.assertIsNone(re.search(r"\bv\d+\.\d+", c), c)


class ReportFromSaved(unittest.TestCase):
    """--report-from with --sensitivity-exclude: spec §9.5 from stored runs."""

    def saved(self, d):
        summary = ct.evaluate(SANITY, "rules", verbose=False)
        path = Path(d) / "saved.json"
        path.write_text(json.dumps(summary, default=str), encoding="utf-8")
        return path

    def run_report(self, path, exclude):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = ct.report_from(path, exclude)
        return code, buf.getvalue()

    def test_sensitivity_block_from_stored_runs(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = self.run_report(self.saved(d), {"S001", "S010"})
        self.assertEqual(code, 0)
        self.assertIn("sensitivity analysis (spec 9.5): the same runs without 2 exposed cases", out)
        block = out.split("sensitivity analysis")[1]
        row = next(l for l in block.splitlines() if l.strip().startswith("rules"))
        # 24 scored (S012's designed retake is excluded), minus S001 and S010;
        # S001 was one of the 12 under and the 7 severe cases
        self.assertEqual(row.split()[1:4], ["22", "11", "6"])

    def test_unknown_id_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = self.run_report(self.saved(d), {"S001", "X999"})
        self.assertEqual(code, 1)
        self.assertNotIn("X999", out)                                # no ids in error paths

    def test_without_exclusion_no_sensitivity_block(self):
        with tempfile.TemporaryDirectory() as d:
            _, out = self.run_report(self.saved(d), set())
        self.assertNotIn("sensitivity analysis", out)


class Sensitivity(unittest.TestCase):
    """Spec §9.5: the same runs, recomputed without the exposed cases."""

    def test_recomputes_without_the_excluded_cases(self):
        summary = ct.evaluate(SANITY, "rules", verbose=False)
        sens = ct.sensitivity(summary, {"S001", "S010"})   # one under, one over
        r = sens["systems"]["rules"]
        self.assertEqual(sens["n_excluded"], 2)
        self.assertEqual((r["n_scored"], r["under"], r["over"]), (22, 11, 3))
        self.assertNotIn("S001", r["outcomes"])
        self.assertEqual(summary["systems"]["rules"]["under"], 12)   # primary untouched

    def test_stability_without_an_excluded_case(self):
        per_case = [{"id": i, "stability": True, "n_paraphrases": 0,
                     "runs": [{"final": "SOON", "llm_proposed": "SOON", "model_called": True,
                               "llm_valid": True, "attempts": 1, "decided_by": "llm",
                               "overridden_by": None, "seconds": 1.0}] * 3}
                    for i in ("A", "B", "C")]
        summary = {"cases": [{**pc, "ref": "SOON", "ref_expected": "SOON", "boundary": False,
                              "ambiguous": False, "images_usable": True} for pc in per_case],
                   "systems": {}, "operations": {}}
        ops = ct.sensitivity(summary, {"B"})["operations"]
        self.assertEqual(ops["stability_cases"], 2)


class CheckerMustFail(unittest.TestCase):
    def _stub_rules(self, answer):
        """evaluate() with rules.assess replaced by `answer(case)`."""
        original = ct.run_rules
        ct.run_rules = lambda case: {"rules": answer(case)}
        try:
            return ct.evaluate(SANITY, "rules", verbose=False)["systems"]["rules"]
        finally:
            ct.run_rules = original

    def count(self, *levels):
        return sum(c["key"]["level"] in levels for c in SANITY["cases"])

    def test_always_routine_is_caught(self):
        r = self._stub_rules(lambda c: "ROUTINE")
        self.assertEqual(r["under"], self.count("EMERGENCY", "URGENT", "SOON"))
        self.assertEqual(r["missed_emergency"], self.count("EMERGENCY"))

    def test_always_emergency_never_under(self):
        r = self._stub_rules(lambda c: "EMERGENCY")
        self.assertEqual(r["under"], 0)
        self.assertEqual(r["over"], self.count("URGENT", "SOON", "ROUTINE"))
        self.assertLess(r["kappa_linear"], ct.KAPPA_BAR)

    def test_always_retake_cannot_dodge_the_primary_endpoint(self):
        r = self._stub_rules(lambda c: "RETAKE")
        self.assertEqual(r["under"], self.count("EMERGENCY", "URGENT"))
        self.assertEqual(r["severe_under"], r["under"])
        designed = sum(c["key"]["level"] in ("SOON", "ROUTINE")
                       and not c["visual_summary"]["images_usable"] for c in SANITY["cases"])
        self.assertEqual(r["excluded_retake"], designed)
        self.assertEqual(r["unwarranted_retake"], self.count("SOON", "ROUTINE") - designed)
        self.assertEqual(r["agree"], 0)
        self.assertFalse(r["kappa_linear"] >= ct.KAPPA_BAR)   # NaN: no level at all

    def test_perfect_system_passes(self):
        r = self._stub_rules(lambda c: c["key"]["level"])
        n = len(SANITY["cases"])
        self.assertEqual((r["under"], r["over"], r["agree"], r["n_scored"]), (0, 0, n, n))
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
        errors, warnings = ct.validate_cases(spec)
        self.assertFalse(any("same symptoms" in e for e in errors), errors)   # no words yet
        self.assertTrue(any("S099: same symptoms" in w for w in warnings), warnings)
        for i in (0, -1):
            spec["cases"][i]["patient_words"] = ["it hurts"]
        errors, _ = ct.validate_cases(spec)
        self.assertTrue(any("S099: same symptoms" in e for e in errors), errors)

    def test_rejects_dentist_label_outside_the_scale(self):
        errors, _ = ct.validate_cases(self._case(dentist_label={"level": "RETAKE"}))
        self.assertTrue(any(e.startswith("schema") for e in errors), errors)

    def test_findings_round_trip(self):
        for case in SANITY["cases"]:
            f = ct.findings_from_visual(case["visual_summary"])
            self.assertEqual(ct.rules.caries_teeth(f), sorted(case["visual_summary"]["flagged_teeth"]))


class HeldoutKeyFormat(unittest.TestCase):
    """research-pm's key shape converts to a valid vignette case (synthetic key,
    not a held-out one)."""

    KEY = {"id": "H900", "archetype": "u_pain_relief", "key_level": "URGENT",
           "emergency_route": None, "criteria_met": ["U1"], "boundary": True, "style": "verbose",
           "facts": ["painkillers did not help"],
           "symptoms": {"schema_version": "1.1", "pain_present": True,
                        "pain_relief_effect": "not_helped", "persistent_ulcer": False},
           "visual_summary": {"images_usable": True, "retake_reasons": [],
                              "flagged_teeth": [{"fdi": "36", "name": "lower left first molar"}],
                              "unexpected_missing_teeth": []},
           "patient_words": "Took something for it, did nothing.",
           "paraphrases": ["Tablets did not help.", "Nothing I took worked."]}

    def convert(self, key, meta=None):
        meta = {"split": "heldout"} if meta is None else meta
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "keys.json"
            p.write_text(json.dumps({"_meta": {"author": "research-pm", "protocol_version": "0.1",
                                               **meta}, "keys": [key]}), encoding="utf-8")
            return ct.load_cases(p)

    def test_split_comes_from_meta_and_is_never_guessed(self):
        self.assertEqual(self.convert(self.KEY, {"split": "dev"})["split"], "dev")
        self.assertEqual(self.convert(self.KEY, {"split": "heldout"})["split"], "heldout")
        self.assertEqual(self.convert(self.KEY, {"status": "HELD-OUT — do not share"})["split"],
                         "heldout")
        for meta in ({}, {"split": "Dev "}, {"status": "DEV: tune on it"}):
            with self.subTest(meta=meta), self.assertRaises(ValueError):
                self.convert(self.KEY, meta)

    def test_dev_key_file_is_not_treated_as_heldout(self):
        dev = ct.REPO_ROOT / "labels" / "dev" / "triage_dev_keys.json"
        if not dev.exists():
            self.skipTest("no dev key file")
        spec = ct.load_cases(dev)
        self.assertEqual(spec["split"], "dev")
        # no --confirm-heldout needed and nothing written to the held-out run log
        self.assertIsNone(ct.heldout_refusal("rules", False, [], None))

    def test_converts(self):
        spec = self.convert(self.KEY)
        self.assertEqual(spec["split"], "heldout")
        case = spec["cases"][0]
        self.assertEqual(case["key"]["level"], "URGENT")
        self.assertEqual(case["visual_summary"]["flagged_teeth"], ["36"])
        self.assertEqual(case["patient_words"], ["Took something for it, did nothing."])
        self.assertEqual(case["paraphrases"], [["Tablets did not help."], ["Nothing I took worked."]])
        errors, _ = ct.validate_cases(spec)
        self.assertEqual(errors, [])

    def test_e2e_script_becomes_the_words(self):
        key = {k: v for k, v in self.KEY.items() if k != "patient_words"}
        key.update(opening="My tooth hurts.", script={"Q10": "Tablets did nothing.", "Q11": "Bad."})
        case = self.convert(key)["cases"][0]
        self.assertEqual(case["patient_words"], ["My tooth hurts.", "Tablets did nothing.", "Bad."])

    def test_narrative_without_words_blocks_only_the_llm(self):
        from fixtures import build_protocol
        key = {k: v for k, v in self.KEY.items() if k not in ("patient_words", "paraphrases")}
        key.update(key_level="SOON", criteria_met=["N3"],
                   symptoms={"schema_version": "1.1", "pain_present": False})
        spec = self.convert(key)
        protocol = build_protocol()
        errors, _ = ct.validate_cases(spec, protocol, need_words=True)
        self.assertTrue(any("narrative" in e for e in errors), errors)
        errors, warnings = ct.validate_cases(spec, protocol, need_words=False)
        self.assertFalse(any("narrative" in e for e in errors), errors)
        self.assertTrue(any("narrative" in w for w in warnings), warnings)


@unittest.skipUnless(HELDOUT.exists(), "held-out keys are local-only (labels/heldout/)")
class HeldoutDryRun(unittest.TestCase):
    """Spec §3a/§8: the checker must reproduce research-pm's dry run on the
    200 held-out keys (rules.py and the protocol check only, no model).
    Protocol v0.2 (spec §9.7): rules.py is unchanged at 51/200; the protocol
    check now sees the broken-filling and pus rows, so its 8 v0.1 misses
    (all S3/U8) are gone and it agrees on every key. The keys are frozen on
    v0.2, so the dry run uses the pinned v0.2 file whatever the live one is."""

    @classmethod
    def setUpClass(cls):
        spec = ct.load_cases(HELDOUT)
        protocol, path, err = ct.load_protocol_for(spec["split"])
        if err:
            raise unittest.SkipTest(f"protocol does not load: {err}")
        cls.spec, cls.protocol, cls.path = spec, protocol, path
        cls.errors, _ = ct.validate_cases(spec, protocol, need_words=False)
        cls.summary = ct.evaluate(spec, "rules", protocol=protocol, verbose=False)

    def test_pinned_to_v02(self):
        self.assertEqual(self.spec["split"], "heldout")
        self.assertEqual(self.path, ct.HELDOUT_PROTOCOL_FILE)
        self.assertEqual((self.protocol.version, self.spec["protocol_version"]), ("0.2", "0.2"))
        self.assertEqual(self.summary["protocol_version"], "0.2")

    def test_the_pin_matters(self):
        # The check can fail: the frozen v0.2 keys against the live protocol,
        # once it is past v0.2, are refused (counts only: held-out ids stay out).
        live, err = ct.load_protocol()
        if err or live.version == ct.HELDOUT_PROTOCOL_VERSION:
            self.skipTest("live protocol is v0.2 or does not load")
        errors, _ = ct.validate_cases(self.spec, live, need_words=False)
        self.assertGreater(len(errors), 0)

    def test_keys_agree_with_protocol(self):
        self.assertEqual(self.errors, [])

    def check(self, name, under, severe, missed, b_under, over, agree, kappa, kappa_ci):
        s = self.summary["systems"][name]
        self.assertEqual(s["n_scored"], 200)
        self.assertEqual((s["under"], s["severe_under"], s["missed_emergency"]), (under, severe, missed))
        self.assertEqual(s["under_boundary"], {"under": b_under, "n": 84})
        self.assertEqual((s["over"], s["agree"]), (over, agree))
        self.assertAlmostEqual(s["kappa_linear"], kappa, places=3)
        self.assertAlmostEqual(s["kappa_ci95"][0], kappa_ci[0], places=3)
        self.assertAlmostEqual(s["kappa_ci95"][1], kappa_ci[1], places=3)

    def test_rules(self):
        self.check("rules", 51, 31, 25, 21, 10, 139, 0.595, (0.504, 0.680))
        lo, hi = self.summary["systems"]["rules"]["under_ci95"]
        self.assertEqual((round(lo * 100, 1), round(hi * 100, 1)), (19.6, 32.1))
        self.assertEqual(self.summary["systems"]["rules"]["photo_quality"]["retake_under"], 3)

    def test_protocol_check(self):
        # 200/200 by construction: the keys were rebuilt from protocol v0.2. Not an accuracy figure.
        self.check("protocol_check", 0, 0, 0, 0, 0, 200, 1.0, (1.0, 1.0))

    def test_mcnemar(self):
        c = self.summary["comparisons"]["protocol_check_vs_rules"]
        self.assertEqual((c["n_common"], c["only_first_under"], c["only_second_under"]), (200, 0, 51))


class HeldoutPin(unittest.TestCase):
    """Held-out is scored against the pinned v0.2 file, dev against the live
    one; the held-out configuration still hashes the v0.2 protocol."""

    def test_file_for_split(self):
        self.assertEqual(ct.protocol_file_for("heldout"), ct.HELDOUT_PROTOCOL_FILE)
        self.assertEqual(ct.protocol_file_for("dev"), ct.PROTOCOL_FILE)
        self.assertNotEqual(ct.HELDOUT_PROTOCOL_FILE, ct.PROTOCOL_FILE)

    def test_heldout_loads_v02_and_dev_the_live_file(self):
        protocol, path, err = ct.load_protocol_for("heldout")
        self.assertIsNone(err)
        self.assertEqual((protocol.version, path), ("0.2", ct.HELDOUT_PROTOCOL_FILE))
        self.assertTrue({"U5", "U6"} <= {c.id for c in protocol.criteria})
        live, path, err = ct.load_protocol_for("dev")
        if err:
            self.skipTest(f"live protocol does not load: {err}")
        self.assertEqual(path, ct.PROTOCOL_FILE)
        self.assertEqual(live.version, ct.load_protocol()[0].version)

    def test_a_pinned_file_of_another_version_is_refused(self):
        original = ct.HELDOUT_PROTOCOL_FILE
        ct.HELDOUT_PROTOCOL_FILE = ct.PROTOCOL_FILE    # the live file, not v0.2
        try:
            live, _ = ct.load_protocol()
            if live is None or live.version == ct.HELDOUT_PROTOCOL_VERSION:
                self.skipTest("live protocol is v0.2 or does not load")
            protocol, _, err = ct.load_protocol_for("heldout")
        finally:
            ct.HELDOUT_PROTOCOL_FILE = original
        self.assertIsNone(protocol)
        self.assertIn("expected v0.2", err)

    def test_heldout_configuration_hashes_the_v02_file(self):
        # sha256 recorded by the 2026-09-26 v0.2 held-out runs (runs/evals/test5_runlog.jsonl)
        protocol, path, _ = ct.load_protocol_for("heldout")
        cfg = ct.configuration("rules", None, protocol, path)
        self.assertEqual(cfg["protocol_sha256"],
                         "7de38ee9db47bfbcec811a588095627846f2e8624d49b3e0f9d6685c75a073ab")
        self.assertEqual(cfg["protocol_version"], "0.2")
        self.assertNotEqual(cfg["fingerprint"],
                            ct.configuration("rules", None, protocol, ct.PROTOCOL_FILE)["fingerprint"])


class RunLog(unittest.TestCase):
    def test_refusals(self):
        self.assertIsNone(ct.heldout_refusal("rules", False, [], None))
        self.assertIn("--confirm-heldout", ct.heldout_refusal("llm", False, [], None))
        prior = [{"date": "2026-09-24T10:00:00"}]
        self.assertIn("--rerun-reason", ct.heldout_refusal("llm", True, prior, None))
        self.assertIsNone(ct.heldout_refusal("llm", True, prior, "fixed a parser bug"))
        self.assertIsNone(ct.heldout_refusal("llm", True, [], None))

    def test_fingerprint_tracks_model_and_prompt(self):
        try:
            import triage  # noqa: F401
        except Exception as exc:
            self.skipTest(f"triage not importable: {exc}")
        a = ct.configuration("llm", "qwen3:14b", None)
        self.assertEqual(a, ct.configuration("llm", "qwen3:14b", None))
        self.assertNotEqual(a["fingerprint"], ct.configuration("llm", "qwen3:4b", None)["fingerprint"])
        original = ct.TRIAGE_PROMPT
        with tempfile.TemporaryDirectory() as d:
            ct.TRIAGE_PROMPT = Path(d) / "prompt.md"
            ct.TRIAGE_PROMPT.write_text("a different prompt", encoding="utf-8")
            try:
                self.assertNotEqual(a["fingerprint"],
                                    ct.configuration("llm", "qwen3:14b", None)["fingerprint"])
            finally:
                ct.TRIAGE_PROMPT = original

    def test_prior_runs_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "log.jsonl"
            self.assertEqual(ct.prior_runs("f1", "c1", log), [])
            ct.append_runlog({"date": "d1", "configuration": {"fingerprint": "f1"},
                              "cases_sha256": "c1"}, log)
            ct.append_runlog({"date": "d2", "configuration": {"fingerprint": "f2"},
                              "cases_sha256": "c1"}, log)
            ct.append_runlog({"date": "d3", "configuration": {"fingerprint": "f1"},
                              "cases_sha256": "c2"}, log)
            self.assertEqual([e["date"] for e in ct.prior_runs("f1", "c1", log)], ["d1"])


class Stability(unittest.TestCase):
    def test_fixed_list(self):
        self.assertEqual(len(set(ct.HELDOUT_STABILITY_IDS)), 20)

    def test_shares(self):
        def pc(levels, n_para):
            return {"runs": [{"final": lv} for lv in levels], "n_paraphrases": n_para}
        stable = [pc(["SOON"] * 5, 2),                                  # stable everywhere
                  pc(["SOON", "SOON", "SOON", "URGENT", "SOON"], 2),     # rewording moves it
                  pc(["SOON", "URGENT", "SOON", "SOON", "SOON"], 2),     # a repeat moves it
                  pc(["SOON", "SOON", "SOON"], 0),                       # no paraphrases yet
                  pc(["SOON", "SOON", "SOON", "URGENT", "URGENT"], 2)]   # both rewordings move it
        self.assertEqual(ct._stable(stable, "final", "all"), {"identical": 2, "n": 5})
        self.assertEqual(ct._stable(stable, "final", "repeats"), {"identical": 4, "n": 5})
        self.assertEqual(ct._stable(stable, "final", "paraphrases"), {"identical": 2, "n": 4})


@unittest.skipUnless(HELDOUT.exists(), "held-out keys are local-only (labels/heldout/)")
class StabilityListMatchesKeys(unittest.TestCase):
    def test_ids_exist_and_none_is_emergency(self):
        spec = ct.load_cases(HELDOUT)
        by_id = {c["id"]: c for c in spec["cases"]}
        self.assertTrue(set(ct.HELDOUT_STABILITY_IDS) <= set(by_id))
        levels = [by_id[i]["key"]["level"] for i in ct.HELDOUT_STABILITY_IDS]
        self.assertEqual({lv: levels.count(lv) for lv in set(levels)},
                         {"SOON": 9, "URGENT": 7, "ROUTINE": 4})   # spec §9.3


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

    def run_with(self, answer, spec=SANITY, stability_ids=()):
        return ct.evaluate(spec, "llm", model="stub", protocol=self.protocol,
                           stability_ids=stability_ids,
                           llm=lambda messages, schema: answer, verbose=False)

    def test_garbage_output_is_counted_as_fallback(self):
        s = self.run_with("not json")
        ops = s["operations"]
        self.assertEqual(ops["first_runs_model_called"] + ops["first_runs_floor_skipped_model"],
                         len(SANITY["cases"]))
        self.assertEqual(ops["fallback"], ops["triage_calls"])
        self.assertEqual(ops["fallback_rate"], 1.0)
        self.assertFalse(ops["fallback_bar_ok"])
        self.assertEqual(ops["valid_output_rate"], 0.0)
        self.assertEqual(s["systems"]["llm_proposed"]["n_scored"], 0)  # never a model level

    def test_model_saying_routine_is_under_triage_for_the_model(self):
        s = self.run_with('{"criteria_met": [], "level": "ROUTINE", "uncertain": false}')
        self.assertGreater(s["systems"]["llm_proposed"]["under"], 0)
        # the composed result can only be raised above the model, never lowered
        for case in s["cases"]:
            run = case["runs"][0]
            if run["llm_proposed"] and run["final"] in ct.ORDER:
                self.assertLessEqual(ct.ORDER[run["final"]], ct.ORDER[run["llm_proposed"]], case["id"])
        self.assertIn("final_vs_rules", s["comparisons"])
        self.assertIn("final", s["code_ceiling"])

    def test_level_raised_in_code_is_counted_apart_from_llm_decided(self):
        # N1 (pain present, SOON) cited with level ROUTINE on every attempt:
        # triage.py keeps it on the last attempt and raises the level in code.
        s = self.run_with('{"criteria_met": [{"criterion_id": "N1", "evidence": [{"source": '
                          '"symptoms", "field": "pain_present", "quote": null}]}], '
                          '"level": "ROUTINE", "uncertain": false}')
        ops = s["operations"]
        runs = [c["runs"][0] for c in s["cases"] if c["runs"][0]["model_called"]]
        raised = [c["id"] for c in s["cases"] if c["runs"][0].get("level_raised_from")]
        self.assertTrue(raised)
        self.assertTrue(all(c["runs"][0]["level_raised_from"] == "ROUTINE" for c in s["cases"]
                            if c["id"] in raised))
        self.assertEqual((ops["level_raised"], ops["level_raised_ids"]), (len(raised), raised))
        self.assertEqual(ops["level_raised_ci95"], ct.clopper_pearson(len(raised), ops["triage_calls"]))
        self.assertEqual(ops["llm_decided"], 0)                   # a raised level is not the model's
        self.assertEqual(ops["llm_decided_n"], ops["first_runs_model_called"])
        self.assertNotIn("llm", ops["decided_by"])
        # raised proposals are valid: not fallbacks
        self.assertEqual(ops["fallback"], ops["triage_calls"] - len(raised))
        notes = sum("kept, level raised in code" in e for r in runs for e in r["validation_errors"])
        self.assertEqual(notes, len(raised))
        self.assertEqual(ops["rejections"],
                         sum(len(r["validation_errors"]) for r in runs) - notes)
        # the model's own level is what llm_proposed scores; triage.py's final
        # shape (2026-09-26): llm_raised with no override, or the protocol past it
        for c in s["cases"]:
            if c["id"] in raised:
                run = c["runs"][0]
                self.assertEqual(run["llm_proposed"], "ROUTINE")
                self.assertIn(run["decided_by"], ("llm_raised", "protocol_check"))
                if run["decided_by"] == "llm_raised":
                    self.assertIsNone(run["overridden_by"])
        self.assertIn("llm_raised", ops["decided_by"])
        # spec 9.9: the bar's count, llm_raised, and their sum (the first rule)
        n_raised_llm = sum(c["runs"][0]["decided_by"] == "llm_raised" for c in s["cases"]
                           if c["id"] in raised)
        self.assertEqual(ops["llm_raised"], n_raised_llm)
        self.assertEqual(ops["raised_then_protocol"], len(raised) - n_raised_llm)
        self.assertEqual(ops["fallback_as_first_registered"], ops["fallback"] + len(raised))
        self.assertEqual(ops["fallback_as_first_registered"], ops["triage_calls"])   # this stub: all
        self.assertEqual(ops["fallback_as_first_registered_ci95"],
                         ct.clopper_pearson(ops["triage_calls"], ops["triage_calls"]))
        self.assertEqual(ops["valid_output_raised"], len(raised))
        self.assertEqual(ops["valid_output"], len(raised))
        self.assertTrue(ops["raised_above_bar"])
        text = self.printed(s)
        self.assertIn(f"valid output {len(raised)}/{ops['triage_calls']}", text)
        self.assertIn(f"of which {len(raised)} kept with the level raised in code", text)
        self.assertIn("fallback_rules (the bar, <= 1%)", text)
        self.assertIn("sum, the rule as first registered", text)
        self.assertIn(ct.FALLBACK_RULE_NOTE, text)
        self.assertIn("FINDING:", text)

    def printed(self, summary):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ct.print_report(summary)
        return buf.getvalue()

    def test_report_from_a_saved_run_recomputes_operations(self):
        import contextlib
        import io
        s = self.run_with('{"criteria_met": [{"criterion_id": "N1", "evidence": [{"source": '
                          '"symptoms", "field": "pain_present", "quote": null}]}], '
                          '"level": "ROUTINE", "uncertain": false}')
        want = s["operations"]["level_raised"]
        saved = json.loads(json.dumps(s, default=str))
        for c in saved["cases"]:                  # a run saved before the field was carried
            for r in c["runs"]:
                r.pop("level_raised_from", None)
        saved["operations"] = {k: v for k, v in saved["operations"].items()
                               if not k.startswith(("level_raised", "llm_raised", "fallback_as"))}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "run.json"
            path.write_text(json.dumps(saved), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(ct.report_from(path), 0)
            self.assertEqual([p.name for p in Path(d).iterdir()], ["run.json"])   # nothing written
        text = buf.getvalue()
        self.assertGreater(want, 0)
        self.assertIn("re-report of run.json", text)
        self.assertIn(f"of which {want} kept with the level raised in code", text)   # from the notes
        self.assertIn(ct.FALLBACK_RULE_NOTE, text)

    def test_no_raise_no_finding(self):
        s = self.run_with('{"criteria_met": [], "level": "ROUTINE", "uncertain": false}')
        ops = s["operations"]
        self.assertEqual((ops["level_raised"], ops["llm_raised"]), (0, 0))
        self.assertEqual(ops["fallback_as_first_registered"], ops["fallback"])
        self.assertFalse(ops["raised_above_bar"])
        self.assertNotIn("FINDING:", self.printed(s))

    def test_consistent_proposal_counts_as_llm_decided(self):
        s = self.run_with('{"criteria_met": [], "level": "ROUTINE", "uncertain": false}')
        ops = s["operations"]
        self.assertEqual(ops["level_raised"], 0)
        self.assertEqual(ops["llm_decided"], ops["decided_by"].get("llm", 0))
        self.assertGreater(ops["llm_decided"], 0)

    def test_report_prints_the_new_line(self):
        import contextlib
        import io
        s = self.run_with('{"criteria_met": [], "level": "ROUTINE", "uncertain": false}')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ct.print_report(s)
        self.assertIn("the model's own level decided (decided_by 'llm')", buf.getvalue())
        self.assertIn("kept with the level raised in code to its own citations 0/", buf.getvalue())

    def test_rejection_lines_skip_the_note(self):
        lines = ["attempt 1: level SOON but the cited criteria imply URGENT",
                 "attempt 2: level SOON but the cited criteria imply URGENT",
                 "attempt 2: kept, level raised in code from SOON to URGENT"]
        self.assertEqual(ct.rejection_lines(lines), lines[:2])
        self.assertEqual(ct.rejection_lines(None), [])

    def test_stability_runs(self):
        spec = copy.deepcopy(SANITY)
        spec["cases"][3]["paraphrases"] = [["one way"], ["another way"]]
        s = self.run_with('{"criteria_met": [], "level": "ROUTINE", "uncertain": false}',
                          spec=spec, stability_ids=["S004", "S005"])
        runs = {c["id"]: len(c["runs"]) for c in s["cases"]}
        self.assertEqual((runs["S004"], runs["S005"], runs["S001"]), (5, 3, 1))
        ops = s["operations"]
        self.assertEqual(ops["stability_cases"], 2)
        self.assertEqual(ops["stability_short_of_paraphrases"], ["S005"])
        self.assertEqual(ops["stable_final_all"], {"identical": 2, "n": 2})  # a constant stub
        self.assertEqual(ops["stable_final_paraphrases"], {"identical": 1, "n": 1})


if __name__ == "__main__":
    unittest.main()
