"""Test 5: triage level against the answer key (or the dentist), with CIs.

    python src/check_triage.py --system rules                 # rules.py alone, no GPU
    python src/check_triage.py --system llm --model qwen3:14b # triage.py, Ollama
    python src/check_triage.py --cases llm/eval/triage_sanity_cases.json --system rules
    python src/check_triage.py --validate-only                # case file checks only

Cases: llm/eval/triage_vignettes.schema.json. Default file is the dev split
(llm/eval/triage_vignettes_dev.json). The held-out split lives in
labels/heldout/ and is research-pm's: run it only when a configuration is
final, report aggregates only, and never show its cases or per-case output to
llm-dev.

Levels are ordered EMERGENCY > URGENT > SOON > ROUTINE. RETAKE is not a level:
- the key expects RETAKE only when the photos are unusable and the key level
  is SOON or ROUTINE (triage.py's photo step);
- a system RETAKE where the key is EMERGENCY/URGENT, or SOON with usable
  photos, is UNDER-triage (the patient is told to retake photos instead of to
  see someone) and counts as less urgent than ROUTINE;
- a system RETAKE where the key is ROUTINE with usable photos is a spurious
  retake: not under-triage, counted on its own line;
- pairs with a RETAKE on either side are left out of kappa and exact agreement.

Systems scored from one run:
  rules     rules.assess() urgency                 (both modes)
  protocol  protocol level from the structured criteria in code (level only;
            blind to narrative criteria by construction)
  llm_only  triage.llm_proposed: the model's own level (llm mode; None when the
            floor skipped the model or the output was invalid twice)
  final     triage.assess() urgency: what the patient is told (llm mode)

Pass bar (docs/decisions.md 2026-09-22 #12): zero under-triage and linearly
weighted kappa >= 0.8 for `final`, against the SDCEP-derived key. That is
"agreement with SDCEP as encoded", not clinical correctness.
"""
import argparse
import copy
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import jsonschema
import numpy as np
from scipy.stats import beta, binomtest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from assess import rules  # noqa: E402  (puts llm/ on sys.path)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEV_CASES = REPO_ROOT / "llm" / "eval" / "triage_vignettes_dev.json"
SCHEMA = REPO_ROOT / "llm" / "eval" / "triage_vignettes.schema.json"
OUT_DIR = REPO_ROOT / "runs" / "evals"

LEVELS = ("EMERGENCY", "URGENT", "SOON", "ROUTINE")
ORDER = {lv: i for i, lv in enumerate(LEVELS)}   # 0 = most urgent. NOT rules.URGENCY_RANK,
RETAKE_ORDER = len(LEVELS)                       # which ranks RETAKE above EMERGENCY.
KAPPA_BAR = 0.8
RED_FLAGS = ("difficulty_swallowing_or_breathing", "chest_pain_or_breathless", "swelling",
             "fever", "systemically_unwell", "recent_trauma", "bleeding_uncontrolled",
             "exceeded_pain_relief_dose")
PAIN_DETAILS = ("pain_relief_effect", "pain_severity", "pain_triggers", "pain_lingers_over_30s",
                "pain_wakes_at_night", "pain_on_biting", "recent_extraction", "location",
                "duration_days")


# --- Cases -----------------------------------------------------------------------

def findings_from_visual(visual: dict) -> dict:
    """A findings object that rules.py and triage.visual_summary() read back
    as exactly this visual_summary (checked by `validate_cases`)."""
    usable = visual["images_usable"]
    findings = {
        "image_quality": {arch: {"usable": usable, "reasons": [] if usable else ["no_teeth_detected"]}
                          for arch in ("upper", "lower")},
        "arches": {arch: {"present": usable, "teeth_detected": 14 if usable else 0}
                   for arch in ("upper", "lower")},
        "teeth": {},
    }
    for fdi in visual["flagged_teeth"]:
        findings["teeth"][fdi] = {"present": True,
                                  "detections": [{"type": "caries", "confidence": 0.9}]}
    for fdi in visual["unexpected_missing_teeth"]:
        findings["teeth"][fdi] = {"present": False, "detections": []}
    return findings


def expected_urgency(case: dict) -> str:
    level = case["key"]["level"]
    if not case["visual_summary"]["images_usable"] and level in ("SOON", "ROUTINE"):
        return "RETAKE"
    return level


def reference_level(case: dict, reference: str):
    """(level, expected_urgency) to score against, or (None, None) if unscored."""
    if reference == "key":
        return case["key"]["level"], expected_urgency(case)
    label = case.get("dentist_label")
    if not label or label.get("level") not in ORDER:
        return None, None
    tmp = {**case, "key": {**case["key"], "level": label["level"]}}
    return label["level"], expected_urgency(tmp)


def _most_urgent(levels) -> str:
    present = [lv for lv in levels if lv in ORDER]
    return min(present, key=ORDER.__getitem__) if present else "ROUTINE"


def validate_cases(spec: dict, protocol=None) -> tuple:
    """(errors, warnings). Errors make the file unusable for scoring."""
    errors, warnings = [], []
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for err in jsonschema.Draft7Validator(schema).iter_errors(spec):
        errors.append(f"schema: {'/'.join(map(str, err.path))}: {err.message}")
    if errors:
        return errors, warnings

    ids = Counter(c["id"] for c in spec["cases"])
    errors += [f"{i}: duplicate id" for i, n in ids.items() if n > 1]
    seen_facts, seen_words = {}, {}
    for case in spec["cases"]:
        cid, s, vs, key = case["id"], case["symptoms"], case["visual_summary"], case["key"]
        # impossible combinations
        if s.get("pain_present") is False:
            set_details = [f for f in PAIN_DETAILS if s.get(f) is not None]
            if set_details:
                errors.append(f"{cid}: pain_present is false but {set_details} are answered")
        elif s.get("pain_present") is None:
            set_details = [f for f in PAIN_DETAILS if s.get(f) is not None]
            if set_details:
                warnings.append(f"{cid}: pain_present unanswered but {set_details} answered")
        if s.get("swelling_features") and s.get("swelling") is not True:
            errors.append(f"{cid}: swelling_features without swelling == true")
        if s.get("trauma_features") and s.get("recent_trauma") is not True:
            errors.append(f"{cid}: trauma_features without recent_trauma == true")
        if s.get("exceeded_pain_relief_dose") is True and s.get("pain_relief_effect") == "not_tried":
            errors.append(f"{cid}: exceeded the pain relief dose but pain relief 'not_tried'")
        both = set(vs["flagged_teeth"]) & set(vs["unexpected_missing_teeth"])
        if both:
            errors.append(f"{cid}: teeth {sorted(both)} both flagged and missing")
        if not vs["images_usable"] and (vs["flagged_teeth"] or vs["unexpected_missing_teeth"]):
            errors.append(f"{cid}: unusable photos cannot flag or miss teeth")
        # the findings we build must read back as this visual_summary
        f = findings_from_visual(vs)
        back = {"images_usable": not rules.quality_problems(f),
                "flagged_teeth": rules.caries_teeth(f),
                "unexpected_missing_teeth": rules.missing_teeth(f)}
        want = {"images_usable": vs["images_usable"], "flagged_teeth": sorted(vs["flagged_teeth"]),
                "unexpected_missing_teeth": sorted(vs["unexpected_missing_teeth"])}
        if back != want:
            errors.append(f"{cid}: visual_summary cannot be produced by findings "
                          f"(rules.py reads back {back}); third molars are never 'missing'")
        # the key
        route = key.get("emergency_route")
        if (key["level"] == "EMERGENCY") != (route is not None):
            errors.append(f"{cid}: emergency_route must be set exactly when the level is EMERGENCY")
        if protocol is not None:
            errors += _check_key(case, protocol)
        # duplicates
        facts = json.dumps([s, vs, case["patient_words"]], sort_keys=True)
        if facts in seen_facts:
            errors.append(f"{cid}: same symptoms, photo and words as {seen_facts[facts]}")
        seen_facts.setdefault(facts, cid)
        words = " ".join(case["patient_words"]).strip().lower()
        if words:
            if words in seen_words:
                warnings.append(f"{cid}: same patient words as {seen_words[words]}")
            seen_words.setdefault(words, cid)
        if not case["patient_words"]:
            if any(_is_narrative(protocol, c) for c in key["criteria_met"]):
                errors.append(f"{cid}: a narrative criterion needs patient_words")
    missing_text = sum(not c["patient_words"] for c in spec["cases"])
    if missing_text:
        warnings.append(f"{missing_text}/{len(spec['cases'])} cases have no patient_words yet (P7)")
    return errors, warnings


def _is_narrative(protocol, cid: str) -> bool:
    if protocol is None:
        return False
    try:
        return protocol.criterion(cid).kind == "narrative"
    except KeyError:
        return False


def _check_key(case: dict, protocol) -> list:
    """The key must agree with the protocol file: every structured criterion
    that holds is listed, nothing else structured is, and the level is the
    most urgent listed. A key that fails this is a key bug or a protocol gap —
    either way it must be resolved before the case scores anything."""
    cid, key = case["id"], case["key"]
    visual = {"images_usable": case["visual_summary"]["images_usable"],
              "flagged_teeth": case["visual_summary"]["flagged_teeth"],
              "unexpected_missing_teeth": case["visual_summary"]["unexpected_missing_teeth"]}
    errors = []
    listed = set(key["criteria_met"])
    unknown = [c for c in listed if c not in protocol.criterion_ids()]
    if unknown:
        return [f"{cid}: key cites unknown criteria {unknown}"]
    holds = {c.id for c in protocol.met(case["symptoms"], visual)}
    structured_listed = {c for c in listed if protocol.criterion(c).kind == "structured"}
    if holds - structured_listed:
        errors.append(f"{cid}: key omits criteria that hold: {sorted(holds - structured_listed)}")
    if structured_listed - holds:
        errors.append(f"{cid}: key lists criteria that do not hold: "
                      f"{sorted(structured_listed - holds)}")
    implied = _most_urgent(protocol.criterion(c).level for c in listed)
    if key["level"] != implied:
        errors.append(f"{cid}: key level {key['level']} but its criteria imply {implied}")
    return errors


# --- Scoring ---------------------------------------------------------------------

def compare(ref_level: str, ref_expected: str, got: str, kind: str = "urgency") -> dict:
    """One case, one system. kind='level' systems never say RETAKE and are
    compared with the key level; 'urgency' systems with the expected urgency."""
    if got is None:
        return {"outcome": "not_scored"}
    if kind == "level" or (got != "RETAKE" and ref_expected != "RETAKE"):
        a, b = ORDER[got], ORDER[ref_level]
    elif got == "RETAKE" and ref_expected == "RETAKE":
        return {"outcome": "agree", "retake": "correct"}
    elif got == "RETAKE":
        if ref_level == "ROUTINE":
            return {"outcome": "spurious_retake"}
        a, b = RETAKE_ORDER, ORDER[ref_level]
    else:  # key expects RETAKE, system gave a level: score the level, note the miss
        out = compare(ref_level, ref_level, got, "level")
        return {**out, "retake": "missed"}
    if a == b:
        return {"outcome": "agree"}
    if a > b:
        return {"outcome": "under", "levels": a - b,
                "severe": ref_level == "EMERGENCY" or a - b >= 2}
    return {"outcome": "over", "levels": b - a}


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple:
    """Exact two-sided (1 - alpha) CI for k/n."""
    if n == 0:
        return (float("nan"), float("nan"))
    lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return lo, hi


def upper_one_sided(k: int, n: int, alpha: float = 0.05) -> float:
    """Exact one-sided (1 - alpha) upper bound; for k = 0 this is
    1 - alpha**(1/n), which the rule of three approximates as 3/n."""
    if n == 0:
        return float("nan")
    return 1.0 if k == n else float(beta.ppf(1 - alpha, k + 1, n - k))


def weighted_kappa(pairs: list) -> float:
    """Linearly weighted Cohen's kappa over the four levels.
    pairs: [(reference_level, system_level)]."""
    k = len(LEVELS)
    n = len(pairs)
    if n == 0:
        return float("nan")
    obs = np.zeros((k, k))
    for ref, got in pairs:
        obs[ORDER[ref], ORDER[got]] += 1
    obs /= n
    w = 1 - np.abs(np.subtract.outer(np.arange(k), np.arange(k))) / (k - 1)
    exp = np.outer(obs.sum(axis=1), obs.sum(axis=0))
    po, pe = (w * obs).sum(), (w * exp).sum()
    if np.isclose(pe, 1.0):
        return 1.0 if np.isclose(po, 1.0) else float("nan")
    return float((po - pe) / (1 - pe))


def bootstrap_kappa(pairs: list, reps: int = 2000, seed: int = 0) -> tuple:
    if len(pairs) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = np.arange(len(pairs))
    values = []
    for _ in range(reps):
        sample = [pairs[i] for i in rng.choice(idx, size=len(idx), replace=True)]
        kappa = weighted_kappa(sample)
        if not np.isnan(kappa):
            values.append(kappa)
    if not values:
        return (float("nan"), float("nan"))
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


def mcnemar_exact(a_under: list, b_under: list) -> dict:
    """Paired under-triage, system A vs B. b = only A under, c = only B under."""
    b = sum(x and not y for x, y in zip(a_under, b_under))
    c = sum(y and not x for x, y in zip(a_under, b_under))
    p = 1.0 if b + c == 0 else float(binomtest(min(b, c), b + c, 0.5).pvalue)
    return {"only_first_under": b, "only_second_under": c, "p_exact": p}


def summarise(rows: list, system: str, kind: str) -> dict:
    """rows: [{'ref': level, 'ref_expected': urgency, 'got': ..., 'id': ...}]."""
    results = [(r, compare(r["ref"], r["ref_expected"], r["got"], kind)) for r in rows]
    scored = [(r, c) for r, c in results if c["outcome"] != "not_scored"]
    n = len(scored)
    count = Counter(c["outcome"] for _, c in scored)
    under = [r["id"] for r, c in scored if c["outcome"] == "under"]
    severe = [r["id"] for r, c in scored if c["outcome"] == "under" and c["severe"]]
    over = [r["id"] for r, c in scored if c["outcome"] == "over"]
    pairs = [(r["ref"], r["got"]) for r, c in scored if r["got"] in ORDER
             and not (kind == "urgency" and r["ref_expected"] == "RETAKE")]
    by_level = {}
    for lv in LEVELS:
        sub = [c for r, c in scored if r["ref"] == lv]
        by_level[lv] = {"n": len(sub), "under": sum(c["outcome"] == "under" for c in sub),
                        "over": sum(c["outcome"] == "over" for c in sub)}
    kappa = weighted_kappa(pairs)
    return {
        "system": system, "n_cases": len(rows), "n_scored": n,
        "not_scored": len(rows) - n,
        "agree": count["agree"], "under": len(under), "severe_under": len(severe),
        "over": len(over), "spurious_retake": count["spurious_retake"],
        "retake_correct": sum(c.get("retake") == "correct" for _, c in scored),
        "retake_missed": sum(c.get("retake") == "missed" for _, c in scored),
        "under_rate": len(under) / n if n else float("nan"),
        "under_ci95": clopper_pearson(len(under), n),
        "under_upper95_one_sided": upper_one_sided(len(under), n),
        "over_rate": len(over) / n if n else float("nan"),
        "over_ci95": clopper_pearson(len(over), n),
        "exact_agreement": (sum(a == b for a, b in pairs) / len(pairs)) if pairs else float("nan"),
        "kappa_n": len(pairs), "kappa_linear": kappa, "kappa_ci95": bootstrap_kappa(pairs),
        "by_reference_level": by_level,
        "under_ids": under, "severe_under_ids": severe, "over_ids": over,
        "outcomes": {r["id"]: c for r, c in results},
    }


# --- Running systems -------------------------------------------------------------

def load_protocol():
    """The real protocol, or (None, error) if it does not load."""
    try:
        import protocol as protocol_mod
        return protocol_mod.load(allow_unreviewed=True), None
    except Exception as exc:  # reported, never patched around here
        return None, f"{type(exc).__name__}: {str(exc).splitlines()[-1].strip()}"


def run_rules(case: dict) -> dict:
    return {"rules": rules.assess(findings_from_visual(case["visual_summary"]),
                                  case["symptoms"])["urgency"]}


def run_protocol(case: dict, protocol) -> dict:
    vs = case["visual_summary"]
    visual = {"images_usable": vs["images_usable"], "flagged_teeth": vs["flagged_teeth"],
              "unexpected_missing_teeth": vs["unexpected_missing_teeth"]}
    return {"protocol": protocol.protocol_level(case["symptoms"], visual)}


def run_llm(case: dict, model: str, words: list, llm=None, protocol=None) -> dict:
    import triage
    messages = [{"role": "user", "content": w} for w in words]
    start = time.perf_counter()
    kwargs = {"model": model, "allow_unreviewed": True}
    if llm is not None:
        kwargs["llm"] = llm
    if protocol is not None:
        kwargs["protocol"] = protocol
    a = triage.assess(findings_from_visual(case["visual_summary"]),
                      copy.deepcopy(case["symptoms"]), messages, **kwargs)
    t = a["triage"]
    return {"final": a["urgency"], "llm_only": t["llm_proposed"],
            "protocol": t["protocol_level"], "rules": a["rules_baseline"]["urgency"],
            "decided_by": a["decided_by"], "overridden_by": t["overridden_by"],
            "llm_valid": t["llm_valid"], "attempts": t["attempts"],
            "model_called": t["model"] is not None,
            "validation_errors": t["validation_errors"],
            "seconds": time.perf_counter() - start}


KINDS = {"final": "urgency", "rules": "urgency", "llm_only": "level", "protocol": "level"}


def evaluate(spec: dict, system: str, reference: str = "key", model: str = None,
             repeats: int = 1, protocol=None, llm=None, verbose: bool = True) -> dict:
    per_case = []
    for case in spec["cases"]:
        ref, ref_expected = reference_level(case, reference)
        runs = []
        if system == "rules":
            out = run_rules(case)
            if protocol is not None:
                out.update(run_protocol(case, protocol))
            runs.append(out)
        else:
            variants = [case["patient_words"]] + case.get("paraphrases", [])
            for words in variants:
                for _ in range(repeats):
                    runs.append(run_llm(case, model, words, llm, protocol))
        per_case.append({"id": case["id"], "ref": ref, "ref_expected": ref_expected,
                         "runs": runs})
        if verbose:
            first = runs[0]
            got = first.get("final", first.get("rules"))
            c = compare(ref, ref_expected, got) if ref else {"outcome": "not_scored"}
            mark = {"agree": "ok  ", "under": "UNDER", "over": "over"}.get(c["outcome"], c["outcome"])
            extra = f" decided_by={first['decided_by']}" if "decided_by" in first else ""
            print(f"{mark:6} {case['id']}  key {ref}/{ref_expected}  got {got}{extra}")

    systems = [s for s in ("final", "llm_only", "protocol", "rules")
               if any(s in pc["runs"][0] for pc in per_case)]
    summary = {"system_run": system, "model": model, "reference": reference,
               "n_cases": len(per_case), "systems": {}}
    for s in systems:
        rows = [{"id": pc["id"], "ref": pc["ref"], "ref_expected": pc["ref_expected"],
                 "got": pc["runs"][0].get(s)} for pc in per_case if pc["ref"]]
        summary["systems"][s] = summarise(rows, s, KINDS[s])

    def under_flags(s):
        return [summary["systems"][s]["outcomes"].get(pc["id"], {}).get("outcome") == "under"
                for pc in per_case if pc["ref"]]
    comparisons = {}
    for a, b in (("final", "rules"), ("llm_only", "rules"), ("protocol", "rules")):
        if a in summary["systems"] and b in summary["systems"]:
            comparisons[f"{a}_vs_{b}"] = mcnemar_exact(under_flags(a), under_flags(b))
            pairs = [(pc["runs"][0][b], pc["runs"][0][a]) for pc in per_case
                     if pc["runs"][0].get(a) in ORDER and pc["runs"][0].get(b) in ORDER]
            comparisons[f"{a}_vs_{b}"]["kappa_linear"] = weighted_kappa(pairs)
            comparisons[f"{a}_vs_{b}"]["kappa_n"] = len(pairs)
    summary["comparisons"] = comparisons

    if system == "llm":
        summary["operations"] = _operations(per_case)
    summary["cases"] = per_case
    return summary


def _operations(per_case: list) -> dict:
    first = [pc["runs"][0] for pc in per_case]
    called = [r for r in first if r["model_called"]]
    fallback = sum(r["decided_by"] == "fallback_rules" or not r["llm_valid"] for r in called)
    seconds = sorted(r["seconds"] for pc in per_case for r in pc["runs"] if r["model_called"])
    stable = [pc for pc in per_case if len(pc["runs"]) > 1]
    return {
        "decided_by": dict(Counter(r["decided_by"] for r in first)),
        "overridden_by": dict(Counter(r["overridden_by"] for r in first if r["overridden_by"])),
        "model_called": len(called),
        "floor_skipped_model": len(first) - len(called),
        "valid_first_try": sum(r["llm_valid"] and r["attempts"] == 1 for r in called),
        "retried": sum(r["attempts"] > 1 for r in called),
        "invalid_fallback": fallback,
        "fallback_rate": fallback / len(called) if called else float("nan"),
        "fallback_ci95": clopper_pearson(fallback, len(called)),
        "llm_decided": sum(r["decided_by"] == "llm" for r in first),
        "latency_p50_s": statistics.median(seconds) if seconds else None,
        "latency_p95_s": float(np.percentile(seconds, 95)) if seconds else None,
        "stability_cases": len(stable),
        "stable_final": sum(len({r["final"] for r in pc["runs"]}) == 1 for pc in stable),
        "stable_llm_only": sum(len({r["llm_only"] for r in pc["runs"]}) == 1 for pc in stable),
    }


# --- Report ------------------------------------------------------------------------

def _pct(x) -> str:
    return "  n/a" if x is None or x != x else f"{x:5.1%}"


def print_report(summary: dict) -> None:
    print(f"\nreference: {summary['reference']}   cases: {summary['n_cases']}"
          + (f"   model: {summary['model']}" if summary["model"] else ""))
    header = (f"{'system':<9} {'n':>4} {'under':>6} {'(severe)':>8} {'under 95% CI':>17} "
              f"{'1-sided':>7} {'over':>5} {'over 95% CI':>17} {'exact':>6} {'kappa':>6} "
              f"{'kappa 95% CI':>15}")
    print(header)
    for name, s in summary["systems"].items():
        lo, hi = s["under_ci95"]
        olo, ohi = s["over_ci95"]
        klo, khi = s["kappa_ci95"]
        print(f"{name:<9} {s['n_scored']:>4} {s['under']:>6} {s['severe_under']:>8} "
              f"  [{_pct(lo)}, {_pct(hi)}] {_pct(s['under_upper95_one_sided']):>7} "
              f"{s['over']:>5}   [{_pct(olo)}, {_pct(ohi)}] "
              f"{_pct(s['exact_agreement']):>6} {s['kappa_linear']:6.3f}  [{klo:5.3f}, {khi:5.3f}]")
    for name, s in summary["systems"].items():
        notes = []
        if s["not_scored"]:
            notes.append(f"{s['not_scored']} not scored")
        if s["spurious_retake"] or s["retake_correct"] or s["retake_missed"]:
            notes.append(f"retake correct {s['retake_correct']}, missed {s['retake_missed']}, "
                         f"spurious {s['spurious_retake']}")
        if s["n_scored"] != s["kappa_n"]:
            notes.append(f"kappa on {s['kappa_n']} (RETAKE pairs excluded)")
        by = ", ".join(f"{lv} {v['under']}/{v['n']}" for lv, v in s["by_reference_level"].items())
        print(f"  {name}: under by key level: {by}" + (f"; {'; '.join(notes)}" if notes else ""))
        if s["under_ids"]:
            print(f"    under-triaged: {', '.join(s['under_ids'])}")
    for name, c in summary["comparisons"].items():
        print(f"  {name}: under-triage only in first {c['only_first_under']}, only in second "
              f"{c['only_second_under']}, exact McNemar p = {c['p_exact']:.3g}; "
              f"kappa between them {c['kappa_linear']:.3f} (n={c['kappa_n']})")
    ops = summary.get("operations")
    if ops:
        lo, hi = ops["fallback_ci95"]
        print(f"  model called {ops['model_called']}, floor skipped it {ops['floor_skipped_model']}; "
              f"valid first try {ops['valid_first_try']}, retried {ops['retried']}, "
              f"fallback {ops['invalid_fallback']} ({_pct(ops['fallback_rate'])}, 95% CI "
              f"[{_pct(lo)}, {_pct(hi)}])")
        print(f"  decided_by {ops['decided_by']}; overridden_by {ops['overridden_by']}")
        if ops["latency_p50_s"] is not None:
            print(f"  latency per triage call: p50 {ops['latency_p50_s']:.1f}s, "
                  f"p95 {ops['latency_p95_s']:.1f}s")
        if ops["stability_cases"]:
            print(f"  stability over {ops['stability_cases']} cases: final identical "
                  f"{ops['stable_final']}, llm_only identical {ops['stable_llm_only']}")
    primary = summary["systems"].get("final") or summary["systems"].get("rules")
    ok = primary["under"] == 0 and primary["kappa_linear"] >= KAPPA_BAR
    print(f"\npass bar (0 under-triage, kappa >= {KAPPA_BAR}) for {primary['system']}: "
          f"{'PASS' if ok else 'FAIL'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", default=str(DEV_CASES))
    ap.add_argument("--system", choices=["rules", "llm"], default="rules")
    ap.add_argument("--model", default=None)
    ap.add_argument("--reference", choices=["key", "dentist"], default="key")
    ap.add_argument("--repeats", type=int, default=1, help="runs per case, for stability")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--json", help="write the full result here (default: runs/evals/)")
    args = ap.parse_args()

    path = Path(args.cases)
    spec = json.loads(path.read_text(encoding="utf-8"))
    protocol, perr = load_protocol()
    if perr:
        print(f"WARNING: protocol not loaded ({perr}); keys are not checked against it "
              "and the 'protocol' system is skipped")
    errors, warnings = validate_cases(spec, protocol)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"{path.name}: {len(spec['cases'])} cases, split {spec['split']}, "
          f"{len(errors)} errors, {len(warnings)} warnings")
    levels = Counter(c["key"]["level"] for c in spec["cases"])
    print("key levels: " + ", ".join(f"{lv} {levels[lv]}" for lv in LEVELS)
          + f"; boundary {sum(c['key']['boundary'] for c in spec['cases'])}")
    if errors or args.validate_only:
        return 1 if errors else 0

    if args.system == "llm":
        from interview import DEFAULT_MODEL
        args.model = args.model or DEFAULT_MODEL
    summary = evaluate(spec, args.system, args.reference, args.model, args.repeats, protocol)
    summary["cases_file"] = str(path)
    summary["protocol_loaded"] = protocol is not None
    print_report(summary)

    out = Path(args.json) if args.json else OUT_DIR / (
        f"triage_{spec['split']}_{args.system}"
        + (f"_{args.model.replace(':', '_')}" if args.model else "") + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
