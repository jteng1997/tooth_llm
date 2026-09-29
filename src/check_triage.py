"""Test 5: triage level against the answer key (or the dentist), with CIs.

Implements docs/plans/test5-analysis-spec.md (pre-registered 2026-09-23).

    python src/check_triage.py --system rules                  # rules.py + protocol check, no GPU
    python src/check_triage.py --system llm --model qwen3:14b  # triage.py, Ollama
    python src/check_triage.py --cases llm/eval/triage_sanity_cases.json --system rules
    python src/check_triage.py --cases labels/heldout/triage_heldout_keys.json --system rules
    python src/check_triage.py --cases labels/dev/triage_dev_keys.json --write-vignettes llm/eval/triage_vignettes_dev.json
    python src/check_triage.py --validate-only

Case files: the vignette shape (llm/eval/triage_vignettes.schema.json) or
research-pm's held-out key shape ({"_meta", "keys"}), converted on load. The
held-out split is research-pm's: run the llm system on it only on the lead's
go (--confirm-heldout), report aggregates only, and never show its cases or
per-case output to llm-dev. Every held-out scoring is appended to
runs/evals/test5_runlog.jsonl; an llm configuration already scored on the same
file needs --rerun-reason (spec §1: scored once per configuration).

Scoring (spec §3). Levels are ordered EMERGENCY > URGENT > SOON > ROUTINE.
- under-triage: less urgent than the key; severe: two or more levels below it;
  missed EMERGENCY: key EMERGENCY, system anything else.
- RETAKE with an EMERGENCY or URGENT key: under-triage and severe.
- RETAKE with a SOON or ROUTINE key (§9.1): with unusable photos it is the
  designed output, excluded and counted; with usable photos it is an
  unwarranted RETAKE, kept in n as a miss (exact agreement, recall), neither
  under- nor over-triage, left out of kappa.
- exact agreement is over the scored cases; kappa over those whose system
  answer is a level; paired tests over cases scored for both systems.

Systems scored from one run:
  rules           rules.assess() urgency, the shadow baseline    (both modes)
  protocol_check  the level from the protocol's structured criteria: the code
                  ceiling (spec 3a); protocols v0.2 and v0.3 have no narrative
                  criteria. Held-out files are scored against the pinned v0.2
                  protocol (HELDOUT_PROTOCOL_FILE), dev files against the live one
  llm_proposed    triage llm_proposed, the model's own level before any code
                  override (llm mode; None when the floor skipped the model or
                  the output was invalid twice)
  final           triage.assess() urgency: what the patient is told (llm mode)

Pass bar (docs/decisions.md 2026-09-22 #12): zero under-triage and linearly
weighted kappa >= 0.8 for `final`, against the SDCEP-derived key.
"""
import argparse
import copy
import datetime
import hashlib
import json
import math
import random
import re
import statistics
import subprocess
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
RUNLOG = OUT_DIR / "test5_runlog.jsonl"
PROTOCOL_FILE = REPO_ROOT / "llm" / "protocol" / "triage_protocol.yaml"
# Held-out keys are frozen v0.2 artefacts: they are scored against the v0.2
# protocol they were built from (as labels/heldout/build_keys.py is), never
# re-keyed on a later live protocol (docs/plans/protocol-v0.3/README.md §4).
HELDOUT_PROTOCOL_FILE = REPO_ROOT / "docs" / "plans" / "protocol-v0.2" / "triage_protocol.yaml"
HELDOUT_PROTOCOL_VERSION = "0.2"
TRIAGE_PROMPT = REPO_ROOT / "llm" / "prompts" / "system_triage.md"
RULES_FILE = REPO_ROOT / "llm" / "rules.py"

LEVELS = ("EMERGENCY", "URGENT", "SOON", "ROUTINE")
ORDER = {lv: i for i, lv in enumerate(LEVELS)}   # 0 = most urgent. NOT rules.URGENCY_RANK,
                                                 # which ranks RETAKE above EMERGENCY.
KAPPA_BAR = 0.8
FALLBACK_BAR = 0.01
BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20260923
MCNEMAR_MIN_DISCORDANT = 10
STABILITY_REPEATS = 3
# Spec §9.3, fixed by research-pm (labels/heldout/pick_stability.py); used by
# default on the held-out triage file.
HELDOUT_STABILITY_IDS = ("H032", "H081", "H095", "H104", "H108", "H134", "H178", "H198", "H080",
                         "H070", "H115", "H136", "H101", "H170", "H090", "H047", "H010", "H008",
                         "H124", "H062")
SCORING_VERSION = "test5-analysis-spec 2026-09-23 incl. section 9 amendments"
SYSTEMS = ("final", "llm_proposed", "protocol_check", "rules")
COMPARISONS = (("final", "rules"), ("llm_proposed", "rules"), ("protocol_check", "rules"),
               ("final", "protocol_check"))

CAVEATS = (
    "Agreement with SDCEP as encoded in protocol {version}, including the user's 2026-09-22 "
    "decisions; not a clinical validation.",
    "The vignettes assume the photo findings are correct; the detector catches about 29% of "
    "carious photos at the current threshold, so end-to-end accuracy on real patients is not "
    "measured here.",
    "Every criterion in protocol {version} is structured and decided by code, so on triage-level cases "
    "the final level is right by construction; the informative parts are llm_proposed, the "
    "injection cases and the end-to-end set.",
)

def caveats(protocol_version) -> list:
    """CAVEATS with the version of the protocol the run actually loaded."""
    version = f"v{protocol_version}" if protocol_version else "(version unknown: protocol not loaded)"
    return [c.format(version=version) for c in CAVEATS]


RED_FLAGS = ("difficulty_swallowing_or_breathing", "chest_pain_or_breathless", "swelling",
             "fever", "systemically_unwell", "recent_trauma", "bleeding_uncontrolled",
             "exceeded_pain_relief_dose")
PAIN_DETAILS = ("pain_relief_effect", "pain_severity", "pain_triggers", "pain_lingers_over_30s",
                "pain_wakes_at_night", "pain_on_biting", "recent_extraction", "location",
                "duration_days")


# --- Cases -----------------------------------------------------------------------

def _fdi_list(items: list) -> list:
    return [t["fdi"] if isinstance(t, dict) else t for t in items]


def _case_from_key(k: dict, meta: dict) -> dict:
    """One held-out key (labels/heldout/README.md) as a vignette case."""
    words = k.get("patient_words")
    if isinstance(words, str):
        words = [words]
    elif words is None and "script" in k:   # e2e keys after P7: opening + chat answers
        words = [k.get("opening", "")] + list(k["script"].values())
        words = [w for w in words if w]
    case = {
        "id": k["id"],
        "key": {"level": k["key_level"], "criteria_met": k["criteria_met"],
                "emergency_route": k.get("emergency_route"), "author": meta.get("author", "?"),
                "boundary": k["boundary"], "stratum": k.get("archetype", "")},
        "symptoms": k["symptoms"],
        "visual_summary": {"images_usable": k["visual_summary"]["images_usable"],
                           "flagged_teeth": _fdi_list(k["visual_summary"]["flagged_teeth"]),
                           "unexpected_missing_teeth":
                               _fdi_list(k["visual_summary"]["unexpected_missing_teeth"])},
        "patient_words": words or [],
        "style": k.get("style"),
        "dentist_label": k.get("dentist_label"),
    }
    if k.get("paraphrases"):
        case["paraphrases"] = [[p] if isinstance(p, str) else p for p in k["paraphrases"]]
    if k.get("ambiguous"):
        case["ambiguous"] = True
    return case


def key_file_split(meta: dict, path) -> str:
    """The split a key file declares: `_meta.split`, or, for the held-out files
    written before that field existed, a status that says HELD-OUT. Anything
    else is refused rather than defaulted either way."""
    split = meta.get("split")
    if split in ("dev", "heldout"):
        return split
    if split is None and str(meta.get("status", "")).upper().startswith("HELD-OUT"):
        return "heldout"
    raise ValueError(f"{Path(path).name}: _meta.split must be 'dev' or 'heldout' "
                     f"(got {split!r}); refusing to guess which split this is")


def load_cases(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "cases" in data:
        return data
    meta = data.get("_meta", {})
    return {"schema_version": "1.0", "split": key_file_split(meta, path),
            "protocol_version": str(meta.get("protocol_version", "?")),
            "note": f"converted on load from {Path(path).name}",
            "cases": [_case_from_key(k, meta) for k in data["keys"]]}


def _version(v) -> tuple:
    """'0.2' -> (0, 2); a suffix such as '0.0-test' is ignored."""
    return tuple(int(part) for part in re.findall(r"\d+", str(v).split("-")[0]))


def for_protocol(spec: dict, version) -> dict:
    """The case file as keyed for protocol `version`. A case may carry
    `key_until` ({"0.2": key}): that key applies while the protocol is at or
    below the version named, so the sanity file can pin a protocol change
    before it goes live and stay green on both sides of the switch. The
    lowest version that still applies wins; `version` None keeps the primary
    keys. Returns a copy without `key_until`, or `spec` itself if no case has one."""
    if not any("key_until" in c for c in spec["cases"]):
        return spec
    out = copy.deepcopy(spec)
    for case in out["cases"]:
        until = case.pop("key_until", {})
        if version is None:
            continue
        applies = sorted((v for v in until if _version(version) <= _version(v)), key=_version)
        if applies:
            case["key"] = until[applies[0]]
    if version is not None and _version(version) < _version(spec["protocol_version"]):
        out["protocol_version"] = str(version)
    return out


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
    """What triage.py is designed to show: RETAKE for unusable photos when the
    level is SOON or ROUTINE. Used for the photo-quality counts only; the key
    level is what every level metric scores against."""
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


def validate_cases(spec: dict, protocol=None, need_words: bool = True) -> tuple:
    """(errors, warnings). Errors make the file unusable for scoring.
    need_words=False for systems that never read the patient's words."""
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
            if case["patient_words"]:
                errors.append(f"{cid}: same symptoms, photo and words as {seen_facts[facts]}")
            else:   # held-out keys share facts by design until P7 writes the words
                warnings.append(f"{cid}: same symptoms and photo as {seen_facts[facts]}, no words yet")
        seen_facts.setdefault(facts, cid)
        words = " ".join(case["patient_words"]).strip().lower()
        if words:
            if words in seen_words:
                warnings.append(f"{cid}: same patient words as {seen_words[words]}")
            seen_words.setdefault(words, cid)
        elif any(_is_narrative(protocol, c) for c in key["criteria_met"]):
            (errors if need_words else warnings).append(
                f"{cid}: a narrative criterion needs patient_words")
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

def compare(ref_level: str, got: str, images_usable: bool = True) -> dict:
    """One case, one system, against the reference level (spec §3, §9.1)."""
    if got is None:
        return {"outcome": "not_scored"}
    if got == "RETAKE":
        if ORDER[ref_level] <= ORDER["URGENT"]:
            return {"outcome": "under", "levels": None, "severe": True, "retake": True,
                    "missed_emergency": ref_level == "EMERGENCY"}
        if not images_usable:   # the designed output
            return {"outcome": "excluded_retake", "retake": True}
        return {"outcome": "unwarranted_retake", "retake": True}
    diff = ORDER[got] - ORDER[ref_level]
    missed = ref_level == "EMERGENCY" and got != "EMERGENCY"
    if diff == 0:
        return {"outcome": "agree"}
    if diff > 0:
        return {"outcome": "under", "levels": diff, "severe": diff >= 2, "missed_emergency": missed}
    return {"outcome": "over", "levels": -diff}


def is_scored(outcome: dict) -> bool:
    return outcome["outcome"] not in ("not_scored", "excluded_retake")


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
    """Linearly weighted Cohen's kappa over the four levels, weights 1 - |i-j|/3.
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


def bootstrap_kappa(pairs: list, reps: int = BOOTSTRAP_REPS, seed: int = BOOTSTRAP_SEED) -> tuple:
    """Percentile bootstrap 95% CI (spec §3). The resampling stream and the
    percentile indices are those of research-pm's dry run
    (runs/review/dryrun_test5.py), so the two reproduce each other exactly."""
    n = len(pairs)
    if n < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    values = []
    for _ in range(reps):
        kappa = weighted_kappa([pairs[rng.randrange(n)] for _ in range(n)])
        if not math.isnan(kappa):
            values.append(kappa)
    if not values:
        return (float("nan"), float("nan"))
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


def mcnemar_exact(a_under: list, b_under: list) -> dict:
    """Paired under-triage, system A vs B. b = only A under, c = only B under."""
    b = sum(x and not y for x, y in zip(a_under, b_under))
    c = sum(y and not x for x, y in zip(a_under, b_under))
    p = 1.0 if b + c == 0 else float(binomtest(min(b, c), b + c, 0.5).pvalue)
    return {"only_first_under": b, "only_second_under": c, "p_exact": p}


def summarise(rows: list, system: str) -> dict:
    """rows: [{'id', 'ref', 'ref_expected', 'got', 'boundary', 'ambiguous',
    'images_usable'}], in case order."""
    outcomes = {r["id"]: {**compare(r["ref"], r["got"], r.get("images_usable", True)),
                          "got": r["got"], "ref": r["ref"]}
                for r in rows}
    scored = [r for r in rows if is_scored(outcomes[r["id"]])]
    n = len(scored)

    def ids(pred):
        return [r["id"] for r in scored if pred(outcomes[r["id"]], r)]

    under = ids(lambda o, r: o["outcome"] == "under")
    severe = ids(lambda o, r: o["outcome"] == "under" and o["severe"])
    missed_em = ids(lambda o, r: o["outcome"] == "under" and o["missed_emergency"])
    over = ids(lambda o, r: o["outcome"] == "over")
    agree = ids(lambda o, r: o["outcome"] == "agree")
    unwarranted = ids(lambda o, r: o["outcome"] == "unwarranted_retake")
    n_em = sum(r["ref"] == "EMERGENCY" for r in scored)

    def split(flag):
        sub = [r for r in scored if r.get(flag)]
        return {"under": sum(outcomes[r["id"]]["outcome"] == "under" for r in sub), "n": len(sub)}

    pairs = [(r["ref"], r["got"]) for r in scored if r["got"] in ORDER]
    confusion = {ref: {got: sum(p == (ref, got) for p in pairs) for got in LEVELS} for ref in LEVELS}
    per_level = {}
    for lv in LEVELS:
        n_ref = sum(r["ref"] == lv for r in scored)          # a RETAKE here is a miss
        n_got = sum(confusion[ref][lv] for ref in LEVELS)
        hit = confusion[lv][lv]
        per_level[lv] = {"n_key": n_ref, "n_system": n_got, "correct": hit,
                         "recall": hit / n_ref if n_ref else float("nan"),
                         "precision": hit / n_got if n_got else float("nan")}

    retake = [r for r in rows if r["got"] == "RETAKE"]
    photo = {
        "retake_emitted": len(retake),
        "retake_under": sum(outcomes[r["id"]]["outcome"] == "under" for r in retake),
        "retake_excluded": sum(outcomes[r["id"]]["outcome"] == "excluded_retake" for r in retake),
        "retake_unwarranted": len(unwarranted),
        "retake_expected_by_design": sum(r["ref_expected"] == "RETAKE" for r in rows),
        "retake_missed_by_design": sum(r["ref_expected"] == "RETAKE" and r["got"] in ORDER
                                       for r in rows),
    }
    return {
        "system": system, "n_cases": len(rows), "n_scored": n,
        "not_scored": sum(o["outcome"] == "not_scored" for o in outcomes.values()),
        "excluded_retake": photo["retake_excluded"],
        "agree": len(agree), "under": len(under), "severe_under": len(severe),
        "missed_emergency": len(missed_em), "n_key_emergency": n_em,
        "over": len(over),
        "unwarranted_retake": len(unwarranted),
        "unwarranted_retake_ci95": clopper_pearson(len(unwarranted), n),
        "under_rate": len(under) / n if n else float("nan"),
        "under_ci95": clopper_pearson(len(under), n),
        "under_upper95_one_sided": upper_one_sided(len(under), n),
        "under_boundary": split("boundary"),
        "under_not_boundary": {"under": len(under) - split("boundary")["under"],
                               "n": n - split("boundary")["n"]},
        "under_ambiguous": split("ambiguous"),
        "over_rate": len(over) / n if n else float("nan"),
        "over_ci95": clopper_pearson(len(over), n),
        "exact_agreement": len(agree) / n if n else float("nan"),
        "kappa_n": len(pairs), "kappa_linear": weighted_kappa(pairs),
        "kappa_ci95": bootstrap_kappa(pairs),
        "confusion": confusion, "per_level": per_level, "photo_quality": photo,
        "under_ids": under, "severe_under_ids": severe, "missed_emergency_ids": missed_em,
        "over_ids": over, "unwarranted_retake_ids": unwarranted,
        "outcomes": outcomes,
    }


def paired(first: dict, second: dict) -> dict:
    """Head to head on the cases scored for both systems (spec §3)."""
    oa, ob = first["outcomes"], second["outcomes"]
    common = [i for i in oa if i in ob and is_scored(oa[i]) and is_scored(ob[i])]
    a_under = [oa[i]["outcome"] == "under" for i in common]
    b_under = [ob[i]["outcome"] == "under" for i in common]
    out = {"n_common": len(common),
           "first_under": sum(a_under), "first_under_ci95": clopper_pearson(sum(a_under), len(common)),
           "second_under": sum(b_under),
           "second_under_ci95": clopper_pearson(sum(b_under), len(common)),
           **mcnemar_exact(a_under, b_under)}
    out["discordant"] = out["only_first_under"] + out["only_second_under"]
    out["underpowered"] = out["discordant"] < MCNEMAR_MIN_DISCORDANT
    d = out["discordant"]
    # spec §9.2: the exact interval behind McNemar's test, omitted when b + c = 0
    out["discordant_share_ci95"] = clopper_pearson(out["only_first_under"], d) if d else None
    if out["underpowered"]:
        out["p_exact"] = None     # spec §9.2: counts and exact CIs only, no p-value
    pairs = [(ob[i]["got"], oa[i]["got"]) for i in common
             if oa[i]["got"] in ORDER and ob[i]["got"] in ORDER]
    out["kappa_linear"] = weighted_kappa(pairs)
    out["kappa_n"] = len(pairs)
    return out


def code_ceiling(systems: dict) -> dict:
    """Spec §3a: protocol_check against the key is what code alone achieves;
    what a model-backed system gets right beyond it is the model's share."""
    pc = systems.get("protocol_check")
    if pc is None:
        return {}
    po = pc["outcomes"]
    misses = [i for i, o in po.items() if is_scored(o) and o["outcome"] != "agree"]
    out = {"protocol_check_n": pc["n_scored"], "protocol_check_agree": pc["agree"],
           "protocol_check_misses": misses}
    for name in ("final", "llm_proposed"):
        s = systems.get(name)
        if s is None:
            continue
        so = s["outcomes"]
        fixed = [i for i in misses if is_scored(so[i]) and so[i]["outcome"] == "agree"]
        worse = [i for i, o in so.items() if is_scored(o) and o["outcome"] == "under"
                 and is_scored(po[i]) and po[i]["outcome"] != "under"]
        broken = [i for i, o in so.items() if is_scored(o) and o["outcome"] != "agree"
                  and is_scored(po[i]) and po[i]["outcome"] == "agree"]
        out[name] = {"fixes_protocol_miss": len(fixed), "fixed_ids": fixed,
                     "under_where_protocol_not": len(worse), "under_where_protocol_not_ids": worse,
                     "wrong_where_protocol_right": len(broken), "wrong_where_protocol_right_ids": broken}
    return out


# --- Running systems -------------------------------------------------------------

def load_protocol(path: Path = PROTOCOL_FILE):
    """The protocol at `path` (default: the live one), or (None, error) if it
    does not load."""
    try:
        import protocol as protocol_mod
        return protocol_mod.load(path, allow_unreviewed=True), None
    except Exception as exc:  # reported, never patched around here
        return None, f"{type(exc).__name__}: {str(exc).splitlines()[-1].strip()}"


def protocol_file_for(split: str) -> Path:
    """The protocol a case file is scored against: the pinned v0.2 file for
    held-out, the live file for dev."""
    return HELDOUT_PROTOCOL_FILE if split == "heldout" else PROTOCOL_FILE


def load_protocol_for(split: str):
    """load_protocol() for the split, as (protocol, file, error). Held-out also
    fails if the pinned file is not the version its keys were built on."""
    path = protocol_file_for(split)
    protocol, err = load_protocol(path)
    if protocol is not None and split == "heldout" and protocol.version != HELDOUT_PROTOCOL_VERSION:
        protocol, err = None, (f"pinned held-out protocol is v{protocol.version}, "
                               f"expected v{HELDOUT_PROTOCOL_VERSION}")
    return protocol, path, err


def run_rules(case: dict) -> dict:
    return {"rules": rules.assess(findings_from_visual(case["visual_summary"]),
                                  case["symptoms"])["urgency"]}


def run_protocol(case: dict, protocol) -> dict:
    vs = case["visual_summary"]
    visual = {"images_usable": vs["images_usable"], "flagged_teeth": vs["flagged_teeth"],
              "unexpected_missing_teeth": vs["unexpected_missing_teeth"]}
    return {"protocol_check": protocol.protocol_level(case["symptoms"], visual)}


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
    return {"final": a["urgency"], "llm_proposed": t["llm_proposed"],
            "protocol_check": t["protocol_level"], "rules": a["rules_baseline"]["urgency"],
            "decided_by": a["decided_by"], "overridden_by": t["overridden_by"],
            "level_raised_from": t.get("level_raised_from"),
            "llm_valid": t["llm_valid"], "attempts": t["attempts"],
            "model_called": t["model"] is not None,
            "validation_errors": t["validation_errors"],
            "seconds": time.perf_counter() - start}


def evaluate(spec: dict, system: str, reference: str = "key", model: str = None,
             stability_ids=(), repeats: int = STABILITY_REPEATS, protocol=None, llm=None,
             verbose: bool = True) -> dict:
    """Run one system over the cases and score every system the run yields.
    Stability cases get `repeats` runs of their words plus one per paraphrase;
    only the first run of each case enters the level metrics."""
    stability_ids = set(stability_ids)
    per_case = []
    for case in spec["cases"]:
        ref, ref_expected = reference_level(case, reference)
        if system == "rules":
            out = run_rules(case)
            if protocol is not None:
                out.update(run_protocol(case, protocol))
            runs = [out]
        else:
            runs = [run_llm(case, model, case["patient_words"], llm, protocol)]
            if case["id"] in stability_ids:
                runs += [run_llm(case, model, case["patient_words"], llm, protocol)
                         for _ in range(repeats - 1)]
                runs += [run_llm(case, model, words, llm, protocol)
                         for words in case.get("paraphrases", [])]
        per_case.append({"id": case["id"], "ref": ref, "ref_expected": ref_expected,
                         "boundary": case["key"].get("boundary", False),
                         "ambiguous": case.get("ambiguous", False),
                         "images_usable": case["visual_summary"]["images_usable"],
                         "stability": case["id"] in stability_ids,
                         "n_paraphrases": len(case.get("paraphrases", [])), "runs": runs})
        if verbose:
            first = runs[0]
            got = first.get("final", first.get("rules"))
            c = (compare(ref, got, case["visual_summary"]["images_usable"]) if ref
                 else {"outcome": "not_scored"})
            mark = {"agree": "ok  ", "under": "UNDER", "over": "over"}.get(c["outcome"], c["outcome"])
            extra = f" decided_by={first['decided_by']}" if "decided_by" in first else ""
            print(f"{mark:6} {case['id']}  key {ref}  got {got}{extra}")

    present = [s for s in SYSTEMS if any(s in pc["runs"][0] for pc in per_case)]
    summary = {"system_run": system, "model": model, "reference": reference,
               "n_cases": len(per_case), "protocol_version": getattr(protocol, "version", None),
               "systems": {}}
    for s in present:
        rows = [{"id": pc["id"], "ref": pc["ref"], "ref_expected": pc["ref_expected"],
                 "boundary": pc["boundary"], "ambiguous": pc["ambiguous"],
                 "images_usable": pc["images_usable"],
                 "got": pc["runs"][0].get(s)} for pc in per_case if pc["ref"]]
        summary["systems"][s] = summarise(rows, s)
    summary["comparisons"] = {f"{a}_vs_{b}": paired(summary["systems"][a], summary["systems"][b])
                              for a, b in COMPARISONS
                              if a in summary["systems"] and b in summary["systems"]}
    summary["code_ceiling"] = code_ceiling(summary["systems"])
    if system == "llm":
        summary["operations"] = _operations(per_case)
    summary["cases"] = per_case
    return summary


def sensitivity(summary: dict, exclude: set) -> dict:
    """Spec §9.5: every headline metric recomputed without the excluded
    cases, from the same runs (no model call). Ids are kept out of the output."""
    per_case = [pc for pc in summary["cases"] if pc["id"] not in exclude]
    systems = {}
    for s in summary["systems"]:
        rows = [{"id": pc["id"], "ref": pc["ref"], "ref_expected": pc["ref_expected"],
                 "boundary": pc["boundary"], "ambiguous": pc["ambiguous"],
                 "images_usable": pc["images_usable"], "got": pc["runs"][0].get(s)}
                for pc in per_case if pc["ref"]]
        systems[s] = summarise(rows, s)
    out = {"n_excluded": len(summary["cases"]) - len(per_case), "systems": systems,
           "comparisons": {f"{a}_vs_{b}": paired(systems[a], systems[b])
                           for a, b in COMPARISONS if a in systems and b in systems}}
    if "operations" in summary:
        out["operations"] = _operations(per_case)
    return out


RAISED_NOTE = "kept, level raised in code"   # triage.py's note line, not an error


def rejection_lines(validation_errors: list) -> list:
    """The validation errors proper: triage.py also logs 'attempt N: kept,
    level raised in code from X to Y' there, which is a note, not a rejection."""
    return [e for e in validation_errors or [] if RAISED_NOTE not in e]


def was_raised(run: dict) -> bool:
    """A proposal kept on the last attempt with its level raised in code to
    its own citations: level_raised_from, or (runs saved before that field
    was carried) triage.py's note in validation_errors."""
    if run.get("level_raised_from") is not None:
        return True
    return any(RAISED_NOTE in e for e in run.get("validation_errors") or [])


FALLBACK_RULE_NOTE = (
    "The fallback rule changed after a dev finding (2026-09-26, spec 9.9): a last-attempt proposal "
    "whose only error is a level below its own verified citations is now kept and raised in code "
    "(llm_raised) instead of falling back to rules. The bar is judged on fallback_rules; the sum "
    "fallback_rules + raised is the fallback rate under the rule as first registered.")


def _operations(per_case: list) -> dict:
    first = [pc["runs"][0] for pc in per_case]
    calls = [r for pc in per_case for r in pc["runs"] if r["model_called"]]
    fallback = sum(not r["llm_valid"] for r in calls)
    seconds = sorted(r["seconds"] for r in calls)
    stable = [pc for pc in per_case if pc["stability"]]
    n = len(calls)
    raised = sum(was_raised(r) for r in calls)
    # spec 9.9: llm_raised is decided_by; a raised proposal the protocol then
    # raised further is decided_by protocol_check, but under the rule as first
    # registered it too would have fallen back, so the sum counts every raise
    llm_raised = sum(r["decided_by"] == "llm_raised" for r in calls)
    old_rule = fallback + raised
    first_called = [r for r in first if r["model_called"]]
    # spec §3 "how often the LLM's own level decided the outcome": decided_by
    # 'llm' only; a level code raised to the model's own citations is not that
    llm_decided = sum(r["decided_by"] == "llm" for r in first_called)
    return {
        "level_raised": raised,
        "level_raised_rate": raised / n if n else float("nan"),
        "level_raised_ci95": clopper_pearson(raised, n),
        "level_raised_ids": [pc["id"] for pc in per_case if was_raised(pc["runs"][0])],
        "llm_raised": llm_raised,
        "llm_raised_rate": llm_raised / n if n else float("nan"),
        "llm_raised_ci95": clopper_pearson(llm_raised, n),
        "raised_then_protocol": raised - llm_raised,
        "fallback_as_first_registered": old_rule,
        "fallback_as_first_registered_rate": old_rule / n if n else float("nan"),
        "fallback_as_first_registered_ci95": clopper_pearson(old_rule, n),
        # spec 9.9: above 1% is a finding against the model (its levels
        # disagree with its own citations); every raise counts
        "raised_above_bar": (raised / n > FALLBACK_BAR) if n else None,
        "valid_output_raised": raised,
        "llm_decided": llm_decided,
        "llm_decided_n": len(first_called),
        "llm_decided_ci95": clopper_pearson(llm_decided, len(first_called)),
        "rejections": sum(len(rejection_lines(r.get("validation_errors"))) for r in calls),
        "triage_calls": n,
        "first_runs_model_called": sum(r["model_called"] for r in first),
        "first_runs_floor_skipped_model": sum(not r["model_called"] for r in first),
        "valid_output": sum(r["llm_valid"] for r in calls),
        "valid_output_rate": sum(r["llm_valid"] for r in calls) / n if n else float("nan"),
        "retried": sum(r["attempts"] > 1 for r in calls),
        "retry_rate": sum(r["attempts"] > 1 for r in calls) / n if n else float("nan"),
        "fallback": fallback,
        "fallback_rate": fallback / n if n else float("nan"),
        "fallback_ci95": clopper_pearson(fallback, n),
        "fallback_bar_ok": (fallback / n <= FALLBACK_BAR) if n else None,
        "decided_by": dict(Counter(r["decided_by"] for r in first)),
        "overridden_by": dict(Counter(r["overridden_by"] for r in first if r["overridden_by"])),
        "latency_p50_s": statistics.median(seconds) if seconds else None,
        "latency_p95_s": float(np.percentile(seconds, 95)) if seconds else None,
        "stability_cases": len(stable),
        "stability_runs_per_case": dict(Counter(len(pc["runs"]) for pc in stable)),
        "stability_short_of_paraphrases": [pc["id"] for pc in stable if pc["n_paraphrases"] < 2],
        **{f"stable_{s}_{part}": _stable(stable, s, part)
           for s in ("final", "llm_proposed") for part in ("all", "repeats", "paraphrases")},
    }


def _stable(stable: list, system: str, part: str) -> dict:
    """Spec §9.3: runs are [patient_words x repeats, then each paraphrase].
    'repeats' = the repeat runs; 'paraphrases' = the first run plus the
    paraphrase runs, i.e. does the level survive rewording."""
    identical = n = 0
    for pc in stable:
        runs = pc["runs"]
        k = len(runs) - pc["n_paraphrases"]
        chosen = {"all": runs, "repeats": runs[:k], "paraphrases": runs[:1] + runs[k:]}[part]
        if part == "paraphrases" and pc["n_paraphrases"] == 0:
            continue
        n += 1
        identical += len({r[system] for r in chosen}) == 1
    return {"identical": identical, "n": n}


# --- Run log (spec §1: every held-out scoring is logged) ---------------------------

def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def configuration(system: str, model: str, protocol, protocol_file: Path = PROTOCOL_FILE) -> dict:
    """What makes a configuration (spec §1): model + prompt + protocol version
    + composition options. Code fixes are recorded (git commit) but do not
    make a new configuration; re-running after one is a logged re-run.
    `protocol_file` is the file `protocol` was loaded from (the pinned v0.2
    file for held-out, byte-identical to the live file of the v0.2 runs)."""
    cfg = {"system": system, "scoring": SCORING_VERSION,
           "protocol_version": getattr(protocol, "version", None),
           "protocol_sha256": _sha256(protocol_file),
           "rules_sha256": _sha256(RULES_FILE)}
    if system == "llm":
        import triage
        cfg.update({"model": model, "prompt_sha256": _sha256(TRIAGE_PROMPT),
                    "max_attempts": triage.MAX_ATTEMPTS})
    cfg["fingerprint"] = hashlib.sha256(
        json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]
    return cfg


def _git_state() -> dict:
    def git(*args):
        try:
            return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True,
                                  text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    status = git("status", "--porcelain")
    return {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(status) if status is not None else None}


def read_runlog(path: Path = RUNLOG) -> list:
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def prior_runs(fingerprint: str, cases_sha: str, path: Path = RUNLOG) -> list:
    return [e for e in read_runlog(path)
            if e["configuration"]["fingerprint"] == fingerprint and e["cases_sha256"] == cases_sha]


def heldout_refusal(system: str, confirmed: bool, prior: list, rerun_reason: str):
    """Why a held-out run must not start, or None."""
    if system != "llm":
        return None
    if not confirmed:
        return ("the llm system on held-out data needs the lead's go: pass --confirm-heldout "
                "(spec §1, scored once per configuration)")
    if prior and not rerun_reason:
        when = ", ".join(e["date"] for e in prior)
        return (f"this configuration was already scored on this file ({when}); a re-run after "
                "a code fix needs --rerun-reason and is logged as a re-run")
    return None


def headline(summary: dict) -> dict:
    keys = ("n_scored", "under", "severe_under", "missed_emergency", "over", "agree",
            "excluded_retake", "kappa_linear", "kappa_ci95", "under_ci95")
    out = {s: {k: v[k] for k in keys} for s, v in summary["systems"].items()}
    if summary.get("sensitivity"):
        sens = summary["sensitivity"]
        out["sensitivity"] = {"n_excluded": sens["n_excluded"],
                              **{s: {k: v[k] for k in keys} for s, v in sens["systems"].items()}}
    ops = summary.get("operations")
    if ops:
        out["operations"] = {k: ops[k] for k in ("triage_calls", "fallback", "fallback_rate",
                                                 "valid_output_rate", "retry_rate")}
    return out


def append_runlog(entry: dict, path: Path = RUNLOG) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


# --- Report ------------------------------------------------------------------------

def _pct(x) -> str:
    return "  n/a" if x is None or x != x else f"{x:5.1%}"


def _ci(ci) -> str:
    return f"[{_pct(ci[0])}, {_pct(ci[1])}]"


def print_report(summary: dict) -> None:
    print(f"\nreference: {summary['reference']}   cases: {summary['n_cases']}"
          + (f"   model: {summary['model']}" if summary["model"] else ""))
    for name, s in summary["systems"].items():
        n = s["n_scored"]
        klo, khi = s["kappa_ci95"]
        b, nb = s["under_boundary"], s["under_not_boundary"]
        print(f"\n=== {name}  (n = {n} scored of {s['n_cases']}) ===")
        print(f"under-triage      {s['under']:3d}/{n}  {_pct(s['under_rate'])}  95% CI "
              f"{_ci(s['under_ci95'])}  one-sided upper {_pct(s['under_upper95_one_sided'])}")
        print(f"  severe (>=2 lv or RETAKE)  {s['severe_under']}")
        print(f"  missed EMERGENCY           {s['missed_emergency']}/{s['n_key_emergency']}")
        print(f"  boundary {b['under']}/{b['n']}   elsewhere {nb['under']}/{nb['n']}"
              + (f"   ambiguous {s['under_ambiguous']['under']}/{s['under_ambiguous']['n']}"
                 if s["under_ambiguous"]["n"] else ""))
        print(f"over-triage       {s['over']:3d}/{n}  {_pct(s['over_rate'])}  95% CI {_ci(s['over_ci95'])}")
        print(f"exact agreement   {s['agree']:3d}/{n}  {_pct(s['exact_agreement'])}")
        print(f"weighted kappa    {s['kappa_linear']:.3f}  95% CI {klo:.3f}-{khi:.3f}  "
              f"(n = {s['kappa_n']}; bootstrap {BOOTSTRAP_REPS}, seed {BOOTSTRAP_SEED})")
        print("confusion (key down, system across)          recall   precision")
        print("            " + "".join(f"{lv[:4]:>7}" for lv in LEVELS))
        for ref in LEVELS:
            pl = s["per_level"][ref]
            print(f"  {ref:<10}" + "".join(f"{s['confusion'][ref][g]:7d}" for g in LEVELS)
                  + f"   {pl['correct']:3d}/{pl['n_key']:<3d} {_pct(pl['recall'])}"
                  f"  {pl['correct']:3d}/{pl['n_system']:<3d} {_pct(pl['precision'])}")
        ph = s["photo_quality"]
        notes = []
        if ph["retake_emitted"]:
            notes.append(f"RETAKE emitted {ph['retake_emitted']} (under-triage {ph['retake_under']}, "
                         f"designed and excluded {ph['retake_excluded']}, unwarranted "
                         f"{ph['retake_unwarranted']}/{n} {_ci(s['unwarranted_retake_ci95'])}: "
                         "counted as misses, not in kappa)")
        if ph["retake_expected_by_design"] and name in ("final", "rules"):   # the others never say RETAKE
            notes.append(f"unusable photos with a SOON/ROUTINE key {ph['retake_expected_by_design']}"
                         f" (given a level instead of RETAKE: {ph['retake_missed_by_design']})")
        if s["not_scored"]:
            notes.append(f"{s['not_scored']} not scored (no answer)")
        if notes:
            print("  " + "; ".join(notes))
    if summary["comparisons"]:
        print("\nhead to head, under-triage, on cases scored for both:")
    for name, c in summary["comparisons"].items():
        a, b = name.split("_vs_")
        test = ("underpowered: fewer than 10 discordant pairs, so no test of a difference is "
                "reported" if c["underpowered"] else f"exact McNemar p = {c['p_exact']:.3g}")
        share = (f"share against {a} {c['only_first_under']}/{c['discordant']} "
                 f"{_ci(c['discordant_share_ci95'])}" if c["discordant_share_ci95"]
                 else "no discordant pairs, so no CI for b/(b+c)")
        print(f"  {name} (n = {c['n_common']}): {a} {c['first_under']} {_ci(c['first_under_ci95'])}, "
              f"{b} {c['second_under']} {_ci(c['second_under_ci95'])}; b = only {a} "
              f"{c['only_first_under']}, c = only {b} {c['only_second_under']}; {share}; {test}; "
              f"kappa between them {c['kappa_linear']:.3f} (n = {c['kappa_n']})")
    cc = summary.get("code_ceiling")
    if cc:
        print(f"\ncode ceiling (spec 3a): protocol_check agrees on {cc['protocol_check_agree']}/"
              f"{cc['protocol_check_n']}; it misses {len(cc['protocol_check_misses'])}")
        for name in ("final", "llm_proposed"):
            if name in cc:
                x = cc[name]
                print(f"  {name}: right on {x['fixes_protocol_miss']}/{len(cc['protocol_check_misses'])}"
                      f" of those; under-triaged where protocol_check was not "
                      f"{x['under_where_protocol_not']}; wrong where protocol_check was right "
                      f"{x['wrong_where_protocol_right']}")
    ops = summary.get("operations")
    if ops:
        n = ops["triage_calls"]
        raised_note = (f", of which {ops['valid_output_raised']} kept with the level raised in code"
                       if "valid_output_raised" in ops else "")
        print(f"\noperations over {n} triage calls: valid output {ops['valid_output']}/{n} "
              f"({_pct(ops['valid_output_rate'])}{raised_note}), retried {ops['retried']}/{n} "
              f"({_pct(ops['retry_rate'])}), fallback to rules {ops['fallback']}/{n} "
              f"({_pct(ops['fallback_rate'])}, 95% CI {_ci(ops['fallback_ci95'])}; bar <= 1%: "
              f"{'met' if ops['fallback_bar_ok'] else 'NOT MET'})")
        print(f"  first runs: model called {ops['first_runs_model_called']}, floor skipped it "
              f"{ops['first_runs_floor_skipped_model']}; decided_by {ops['decided_by']}; "
              f"overridden_by {ops['overridden_by']}")
        if "level_raised" in ops:
            print(f"  the model's own level decided (decided_by 'llm') {ops['llm_decided']}/"
                  f"{ops['llm_decided_n']} first runs with a model call {_ci(ops['llm_decided_ci95'])}; "
                  f"kept with the level raised in code to its own citations {ops['level_raised']}/{n} "
                  f"calls ({_pct(ops['level_raised_rate'])}, 95% CI {_ci(ops['level_raised_ci95'])}); "
                  f"rejected attempts logged {ops['rejections']}")
        if "fallback_as_first_registered" in ops:
            print("  fallback, spec 9.9 (exact 95% CIs over the triage calls):")
            print(f"    fallback_rules (the bar, <= 1%)      {ops['fallback']:3d}/{n} "
                  f"{_pct(ops['fallback_rate'])}  {_ci(ops['fallback_ci95'])}")
            print(f"    llm_raised                           {ops['llm_raised']:3d}/{n} "
                  f"{_pct(ops['llm_raised_rate'])}  {_ci(ops['llm_raised_ci95'])}"
                  + (f"  (+ {ops['raised_then_protocol']} raised, then raised further by the "
                     "protocol: decided_by protocol_check)" if ops["raised_then_protocol"] else ""))
            print(f"    sum, the rule as first registered    {ops['fallback_as_first_registered']:3d}/{n} "
                  f"{_pct(ops['fallback_as_first_registered_rate'])}  "
                  f"{_ci(ops['fallback_as_first_registered_ci95'])}")
            print(f"    {FALLBACK_RULE_NOTE}")
            if ops["raised_above_bar"]:
                print(f"    FINDING: {ops['level_raised']}/{n} proposals ({_pct(ops['level_raised_rate'])}) "
                      "stated a level below their own verified citations, above 1%: the model's "
                      "levels disagree with its own citations.")
        if ops["latency_p50_s"] is not None:
            print(f"  latency per triage call: p50 {ops['latency_p50_s']:.1f}s, "
                  f"p95 {ops['latency_p95_s']:.1f}s")
        if ops["stability_cases"]:
            k = ops["stability_cases"]
            print(f"  stability over {k} cases (runs per case {ops['stability_runs_per_case']}); "
                  "EMERGENCY cases never reach the model and are not described:")
            for s in ("final", "llm_proposed"):
                print(f"    {s:<13}" + ", ".join(
                    f"{part} identical {ops[f'stable_{s}_{part}']['identical']}/"
                    f"{ops[f'stable_{s}_{part}']['n']}" for part in ("all", "repeats", "paraphrases")))
            if ops["stability_short_of_paraphrases"]:
                print(f"  WARNING: {len(ops['stability_short_of_paraphrases'])} stability cases "
                      "have fewer than 2 paraphrases")
    print("\nThese numbers must be reported with:")
    version = summary.get("protocol_version") or (summary.get("configuration") or {}).get(
        "protocol_version")
    for i, text in enumerate(caveats(version), 1):
        print(f"  {i}. {text}")
    sens = summary.get("sensitivity")
    if sens:
        print(f"\nsensitivity analysis (spec 9.5): the same runs without {sens['n_excluded']} "
              "exposed cases; the primary figures above use all cases")
        print(f"  {'system':<15}{'n':>4}{'under':>7}{'severe':>8}{'missed EM':>11}{'over':>6}"
              f"{'exact':>9}{'kappa':>8}  kappa 95% CI")
        for name, s in sens["systems"].items():
            lo, hi = s["kappa_ci95"]
            print(f"  {name:<15}{s['n_scored']:>4}{s['under']:>7}{s['severe_under']:>8}"
                  f"{s['missed_emergency']:>7}/{s['n_key_emergency']:<3}{s['over']:>6}"
                  f"{s['agree']:>5}/{s['n_scored']:<3}{s['kappa_linear']:>8.3f}  [{lo:.3f}, {hi:.3f}]"
                  f"  under 95% CI {_ci(s['under_ci95'])}")
        ops = sens.get("operations")
        if ops and ops["stability_cases"]:
            k = ops["stability_cases"]
            for s in ("final", "llm_proposed"):
                print(f"  stability {s:<13} over {k} cases: " + ", ".join(
                    f"{part} {ops[f'stable_{s}_{part}']['identical']}/{ops[f'stable_{s}_{part}']['n']}"
                    for part in ("all", "repeats", "paraphrases")))
    primary = summary["systems"].get("final") or summary["systems"].get("rules")
    ok = primary["under"] == 0 and primary["kappa_linear"] >= KAPPA_BAR
    print(f"\npass bar (0 under-triage, kappa >= {KAPPA_BAR}) for {primary['system']}: "
          f"{'PASS' if ok else 'FAIL'}")


def report_from(path: Path, exclude: set = frozenset()) -> int:
    """The report of a saved run, with the operations block recomputed from
    its stored runs, so figures added to the report later (e.g. spec 9.9)
    appear for a run made before them. Scores are not recomputed. With
    `exclude`, the spec 9.5 sensitivity block is computed from the same
    stored runs (no model call)."""
    summary = json.loads(Path(path).read_text(encoding="utf-8"))
    if summary.get("operations") and summary.get("cases"):
        summary["operations"] = _operations(summary["cases"])
    if exclude:
        ids = {pc["id"] for pc in summary.get("cases", [])}
        if exclude - ids:
            print(f"ERROR: {len(exclude - ids)} excluded ids are not in the saved run")
            return 1
        summary["sensitivity"] = sensitivity(summary, set(exclude))
    print(f"re-report of {Path(path).name} (saved run; operations recomputed from its runs"
          + (f"; sensitivity without {len(exclude)} cases" if exclude else "") + ")")
    print_report(summary)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", default=str(DEV_CASES))
    ap.add_argument("--system", choices=["rules", "llm"], default="rules")
    ap.add_argument("--model", default=None)
    ap.add_argument("--reference", choices=["key", "dentist"], default="key")
    ap.add_argument("--stability-ids", help="JSON list of case ids run for stability "
                                            f"({STABILITY_REPEATS} runs + each paraphrase); "
                                            "default on the held-out triage file: spec §9.3")
    ap.add_argument("--sensitivity-exclude", metavar="JSON",
                    help="spec 9.5: also report every headline metric without these case ids "
                         "(a JSON list, or an object with 'exposed_ids')")
    ap.add_argument("--write-vignettes", metavar="OUT",
                    help="write the (converted) case file here after validation, and exit; "
                         "e.g. dev keys + P7 text -> llm/eval/triage_vignettes_dev.json")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--confirm-heldout", action="store_true",
                    help="the lead has given the go to score the llm system on held-out data")
    ap.add_argument("--rerun-reason", help="why an already-scored configuration is run again")
    ap.add_argument("--ran-by", default="qa-engineer")
    ap.add_argument("--runlog", default=str(RUNLOG), help="held-out run log (JSON lines)")
    ap.add_argument("--json", help="write the full result here (default: runs/evals/)")
    ap.add_argument("--report-from", metavar="JSON",
                    help="re-print the report of a saved result (no model call, nothing logged or "
                         "written); the operations block is recomputed from its stored runs")
    args = ap.parse_args()
    if args.report_from:
        exclude = set()
        if args.sensitivity_exclude:
            raw = json.loads(Path(args.sensitivity_exclude).read_text(encoding="utf-8"))
            exclude = set(raw["exposed_ids"] if isinstance(raw, dict) else raw)
        return report_from(Path(args.report_from), exclude)

    path = Path(args.cases)
    try:
        spec = load_cases(path)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    heldout = spec["split"] == "heldout"
    if args.write_vignettes and heldout:
        print("REFUSED: held-out cases are never written out as a vignette file")
        return 1
    protocol, protocol_file, perr = load_protocol_for(spec["split"])
    if perr:
        print(f"WARNING: protocol not loaded ({perr}); keys are not checked against it "
              "and protocol_check is skipped")
        if heldout:
            print("ERROR: held-out keys are never scored without the protocol check")
            return 1
    if heldout:
        if spec["protocol_version"] != HELDOUT_PROTOCOL_VERSION:
            print(f"ERROR: held-out keys say protocol v{spec['protocol_version']}; held-out is "
                  f"frozen on v{HELDOUT_PROTOCOL_VERSION} and never re-keyed")
            return 1
        print(f"held-out: scored against the pinned protocol v{protocol.version} "
              f"({protocol_file.relative_to(REPO_ROOT).as_posix()}), not the live file")
    if any("key_until" in c for c in spec["cases"]):
        spec = for_protocol(spec, protocol.version if protocol else None)
        print(f"keys for protocol v{spec['protocol_version']} (key_until resolved)")
    errors, warnings = validate_cases(spec, protocol, need_words=args.system == "llm")
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
    if args.write_vignettes:
        out = Path(args.write_vignettes)
        out.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {len(spec['cases'])} {spec['split']} cases to {out}")
        return 0

    if args.system == "llm":
        from interview import DEFAULT_MODEL
        args.model = args.model or DEFAULT_MODEL
        if any(not c["patient_words"] for c in spec["cases"]):
            print("ERROR: the llm system needs patient_words for every case (P7)")
            return 1
    if args.stability_ids:
        stability_ids = json.loads(Path(args.stability_ids).read_text(encoding="utf-8"))
    elif args.system == "llm" and path.name == "triage_heldout_keys.json":
        stability_ids = list(HELDOUT_STABILITY_IDS)
    else:
        stability_ids = []
    ids = {c["id"] for c in spec["cases"]}
    unknown = set(stability_ids) - ids
    if unknown:
        # counts only: an error path must not print held-out ids or keys
        print(f"ERROR: {len(unknown)} stability ids are not in the case file")
        return 1
    exclude = set()
    if args.sensitivity_exclude:
        raw = json.loads(Path(args.sensitivity_exclude).read_text(encoding="utf-8"))
        exclude = set(raw["exposed_ids"] if isinstance(raw, dict) else raw)
        if not exclude or exclude - ids:
            print(f"ERROR: sensitivity exclusion list is empty or has {len(exclude - ids)} ids "
                  "not in the case file")
            return 1

    cases_sha = _sha256(path)
    cfg = configuration(args.system, args.model, protocol, protocol_file)
    prior = prior_runs(cfg["fingerprint"], cases_sha, args.runlog) if heldout else []
    if heldout:
        refusal = heldout_refusal(args.system, args.confirm_heldout, prior, args.rerun_reason)
        if refusal:
            print(f"REFUSED: {refusal}")
            return 2
        if prior:
            print(f"re-run {len(prior) + 1} of configuration {cfg['fingerprint']} on this file")

    summary = evaluate(spec, args.system, args.reference, args.model, stability_ids,
                       protocol=protocol, verbose=not heldout)
    summary["cases_file"] = str(path)
    summary["protocol_loaded"] = protocol is not None
    if exclude:
        summary["sensitivity"] = sensitivity(summary, exclude)
    summary["configuration"] = cfg
    print_report(summary)

    out = Path(args.json) if args.json else OUT_DIR / (
        f"triage_{path.stem}_{args.system}"
        + (f"_{args.model.replace(':', '_')}" if args.model else "") + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {out}")

    if heldout:
        entry = {"date": datetime.datetime.now().isoformat(timespec="seconds"),
                 "ran_by": args.ran_by, "cases_file": str(path), "cases_sha256": cases_sha,
                 "n_cases": len(spec["cases"]), "reference": args.reference,
                 "configuration": cfg, "git": _git_state(),
                 "rerun": bool(prior), "rerun_of": [e["date"] for e in prior],
                 "rerun_reason": args.rerun_reason, "stability_ids": stability_ids,
                 "output": str(out), "headline": headline(summary)}
        append_runlog(entry, args.runlog)
        print(f"logged in {args.runlog}. For docs/decisions.md (research-pm): {entry['date'][:10]}, "
              f"Test 5 held-out scoring, {path.name}, system {args.system}"
              + (f" {args.model}" if args.model else "")
              + f", configuration {cfg['fingerprint']}, run by {args.ran_by}"
              + (" (re-run)" if prior else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
