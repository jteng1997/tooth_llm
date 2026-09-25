"""Test 2 from llm/eval: does the explanation say only what the JSON says?

    python src/check_faithfulness.py                      # 8 seed cases
    python src/check_faithfulness.py --synthetic 200      # generated cases
    python src/check_faithfulness.py --model qwen3:4b --json out.json
    python src/check_faithfulness.py --synthetic 60 --mode both   # headline + legacy line

Modes: triage (default, the headline) explains the triage.py 2.0 assessment
the way the web app does, then asks each synthetic case two follow-up
questions; legacy explains the rules.py 1.0 assessment (Explanation() with no
assessment), the path Test 2 measured until 2026-09-23.

Three rates, as the eval spec asks:

  hallucination  a tooth mentioned that is not in findings.teeth
  omission       a tooth rules.py flagged that the text never mentions
  contradiction  the stated urgency isn't the assessed one, or the text
                 tells the user they can skip or delay the dentist

Also: misstated (a missing tooth called decay), unreported (a tooth told
as a finding that the assessment did not flag, e.g. a sub-threshold
detection) and retake not requested (an unusable photo never asked for again).

Teeth are matched by FDI number and by plain-word name ("lower left first
molar"), because the model frequently writes one without the other and a
digits-only regex scores those as silence.

Urgency and discouragement are matched by keyword, which is cruder than
the tooth checks: treat a contradiction as a flag to read, not a verdict.
The natural-language must/must_not lines on the seed cases are printed
for a human, never scored here.
"""
import argparse
import copy
import json
import re
from pathlib import Path

import explain
from eval_data import generate, generate_v2
from explain import Explanation, fdi_label
from retrieval import Knowledge

REPO_ROOT = Path(__file__).resolve().parent.parent
FAITHFULNESS = REPO_ROOT / "llm" / "eval" / "faithfulness_cases.json"
RULE_CASES = REPO_ROOT / "llm" / "eval" / "rule_cases.json"
CASE_ONLY_KEYS = {"id", "note", "findings_base", "symptoms", "must", "must_not"}
# Not \b: that matches the "42" inside a confidence like 0.42, which scores
# as a hallucinated tooth. A full stop after the number is fine ("on 36."); a
# digit after one is not. The earlier (?![\d.]) missed every tooth that ended
# a sentence (2026-09-22; re-scoring the stored 14b/4b runs changed no rate).
FDI =re.compile(r"(?<!\d)(?<!\d\.)([1-4][1-8])(?!\d)(?!\.\d)")
ALL_FDI = [f"{q}{p}" for q in range(1, 5) for p in range(1, 9)]
# A number that counts something is not a tooth. The URGENT headline "within
# 24 hours" scored as tooth 24 on 12/60 triage cases, and "14 teeth" as tooth
# 14 (2026-09-24). It also hid omissions: "24 hours" counted as naming a
# flagged tooth 24. Blanked before FDI matching.
QUANTITY = re.compile(r"(?<![\d.])\d+(?:\.\d+)?\s*-?\s*"
                      r"(?:hours?|hrs?|days?|weeks?|months?|years?|yrs?|teeth)\b", re.I)

# Phrases that mark each urgency level in the generated text.
URGENCY_MARKERS = {
    # assessment 1.0 headlines, then the protocol v0.1 ones (decisions.md 2026-09-22 #1, #9)
    "EMERGENCY": ["today", "right away", "straight away", "emergency", "immediately",
                  "hospital", "as soon as possible"],
    "URGENT": ["few days", "within days", "24 hours", "within a day"],
    "SOON": ["few weeks", "coming weeks", "next weeks", "7 days", "seven days", "within a week"],
    "ROUTINE": ["routine", "regular checkup", "regular check-up", "no action", "check-up",
                "no urgent"],
    "RETAKE": ["retake", "take new photo", "take the photos again", "photos again", "new photo",
               "take them again", "take it again", "photo again"],
}
DISCOURAGE = [
    "you don't need to see a dentist", "you do not need to see a dentist",
    "no need to see a dentist", "no need for a dentist", "skip the dentist",
    "don't need a dentist", "do not need a dentist", "avoid the dentist",
    "you can wait", "it can wait", "no need to visit",
]


def build_findings(case: dict, bases: dict) -> dict:
    findings = copy.deepcopy(bases[case.get("findings_base", "_good_findings")])
    for key, value in case.items():
        if key not in CASE_ONLY_KEYS:
            findings[key] = value
    return findings


def mentioned_teeth(text: str) -> set:
    lowered = text.lower()
    return set(FDI.findall(QUANTITY.sub(" ", text))) | {f for f in ALL_FDI if fdi_label(f) in lowered}


DECAY_WORDS = re.compile(r"decay|cavit|caries", re.I)


def misstated(text: str, findings: dict) -> list:
    """Teeth the findings mark as missing (present: false) that a sentence
    describes as decayed: a finding the photo never showed."""
    missing = [fdi for fdi, t in (findings.get("teeth") or {}).items() if t.get("present") is False]
    bad = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if not DECAY_WORDS.search(sentence):
            continue
        named = mentioned_teeth(sentence)
        bad += [fdi for fdi in missing if fdi in named]
    return sorted(set(bad))


FINDING_CLAIM = re.compile(
    r"\b(?:decay\w*|cavit\w*|caries|carious|indication|unusual|issues?|problems?|fillings?"
    r"|restorations?|signs? of|lesions?|damage\w*|detect\w*|spots?|findings?|abnormal\w*)\b", re.I)


def unreported(text: str, allowed) -> list:
    """Teeth a sentence reports as a finding ("an indication of decay on
    tooth 21", "something unusual on the upper left canine") that are not
    among the teeth the assessment lets the text report. The hallucination
    rate allows any tooth in findings.teeth, so a sub-threshold detection
    told to the patient passed it (llm-dev, 2026-09-24, #22). A tooth named
    in a sentence with no finding claim (a retake or limitation sentence)
    is not counted."""
    bad = set()
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if FINDING_CLAIM.search(sentence):
            bad |= mentioned_teeth(sentence) - set(allowed)
    return sorted(bad)


def reportable(assessment: dict, findings: dict) -> set:
    """The teeth the text may report as a finding: flagged decay plus the
    missing teeth the assessment reports. None on a RETAKE."""
    if assessment["urgency"] == "RETAKE":
        return set()
    decay, missing = explain.split_flagged(assessment, findings)
    return set(decay) | set(missing)


_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
_ARCH_WORDS = {"upper": re.compile(r"\b(?:upper|top|maxilla\w*)\b", re.I),
               "lower": re.compile(r"\b(?:lower|bottom|mandib\w*)\b", re.I)}
# "Nothing was found", "no problems were visible", "we did not see any
# problems": a claim that the photos showed nothing.
_ABSENCE = re.compile(
    r"\b(?:nothing|no (?:signs?|problems?|issues?|decay|cavit\w*|findings?|concerns?))\b"
    r"[^.!?]{0,60}?\b(?:found|visible|seen|shows?|showed|detected|spotted)\b"
    r"|\bnothing (?:visible|found|seen)\b"
    r"|\b(?:did not|didn'?t) (?:see|find|spot) (?:any|anything)\b"
    r"|\b(?:photos?|images?|pictures?) (?:show|showed) nothing\b", re.I)
# "A cavity can be there even when the photos show nothing" is a limitation.
_LIMITATION = re.compile(r"\b(?:can|could|may|might) (?:still )?be there\b|\beven (?:when|if)\b", re.I)
_CLAUSES = re.compile(r"[,;]\s*|\s[-–—]\s|\b(?:but|and|while|whereas|although|however)\b", re.I)
_UNUSABLE = re.compile(r"\b(?:could ?n[o']t|can ?n?[o']t|cannot) be used\b|\bnot usable\b|\bunusable\b"
                       r"|\b(?:did ?n[o']t|does ?n[o']t|could ?n[o']t) show\b|\bnot clear enough\b"
                       r"|\bno teeth\b|\bretake\b", re.I)
_USABLE_PHOTO = re.compile(r"\bphotos? (?:we|that) could (?:be )?use\b|\busable photo\b"
                           r"|\bphoto that could be used\b", re.I)


def unscoped_absence(text: str, usable: list) -> list:
    """With an unusable photo, sentences saying nothing was found or seen
    that are not scoped to the usable photo ("nothing was found in the
    photos" reads as covering the arch nobody could see). Scoped: names only
    the usable arch, or "the photo we could use". Naming the unusable arch
    is never scoped."""
    bad = []
    for sentence in _SENTENCES.split(text or ""):
        if not _ABSENCE.search(sentence) or _LIMITATION.search(sentence):
            continue
        # An arch named only to say its photo could not be used does not
        # widen the scope: "nothing was found on the lower teeth, but the upper
        # photo could not be used" is scoped (Test 2 v5 S0030, S0034).
        clauses = [c for c in _CLAUSES.split(sentence) if c and not _UNUSABLE.search(c)]
        named = {arch for arch, rx in _ARCH_WORDS.items() if any(rx.search(c) for c in clauses)}
        scoped = (bool(named) and named <= set(usable)) or (
            not named and bool(_USABLE_PHOTO.search(sentence)))
        if not scoped:
            bad.append(sentence.strip())
    return bad


# "The lower teeth look fine", "your upper jaw is okay": the photos can miss a
# problem, so a whole arch is never called fine (#17, lead 2026-09-24).
_ARCH_FINE = re.compile(
    r"\b(?:(?:upper|lower|top|bottom|your|the|other) )?(?:teeth|jaw|arch|gums|mouth)\b"
    r"[^.!?]{0,25}?\b(?:look|looks|looked|are|is|was|were|seem|seems|appear|appears)"
    r"(?: to be)? (?:all )?(?:completely |totally |perfectly )?"
    # not bare "clear": "the photos of your lower teeth were clear" is photo quality
    r"(?:fine|okay|ok|healthy|normal|good|in good (?:shape|condition)|clear of|free of"
    r"|problem-free)\b", re.I)
_NOT_A_CLAIM = re.compile(r"\b(?:not|n't) (?:mean|necessarily|say|tell)\b|\bnot that\b|\beven if\b"
                          r"|\bcannot say\b|\bcan'?t say\b|\bdoes not prove\b"
                          # advice, not a finding: "a check-up is the way to make sure your
                          # teeth are healthy"
                          r"|\b(?:make sure|ensure|keep|keeping|check (?:that|whether|if)|help)\b", re.I)


def arch_reassurance(text: str) -> list:
    """Sentences calling the teeth, a jaw or an arch fine/healthy/okay. "It
    does not mean your teeth are fine" is the opposite and is not counted."""
    bad = []
    for sentence in _SENTENCES.split(text or ""):
        m = _ARCH_FINE.search(sentence)
        if m and not _NOT_A_CLAIM.search(sentence[:m.end()]):
            bad.append(sentence.strip())
    return bad


def usable_arches(findings: dict) -> list:
    return [a for a, q in (findings.get("image_quality") or {}).items() if q.get("usable")]


def discourages(text: str) -> str:
    lowered = (text or "").lower()
    return next((phrase for phrase in DISCOURAGE if phrase in lowered), "")


def contradiction(text: str, urgency: str) -> str:
    lowered = text.lower()
    if discourages(text):
        return f"discourages care: {discourages(text)!r}"
    if not any(marker in lowered for marker in URGENCY_MARKERS[urgency]):
        return f"never states {urgency}"
    return ""


def retake_requested(text: str) -> bool:
    """Does the text ask for new photos? Scored on every retake_required
    case, including a partial retake that keeps an URGENT or EMERGENCY level
    (#18), where the urgency check alone would pass a text that never asks."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in URGENCY_MARKERS["RETAKE"])


def _recording_chat(log: list):
    """explain.chat, keeping every raw reply, so a guardrail hit can be read
    against the text that triggered it (false-positive review)."""
    original = explain.chat

    def chat(messages, model, *args, **kwargs):
        reply = original(messages, model, *args, **kwargs)
        log.append(reply)
        return reply
    return original, chat


PLACES_PAIN = "says where the patient's pain is"
ECHO = "repeats the first response"


def _turn_log(entries: list) -> dict:
    """Guardrail bookkeeping for one turn: retried, fell back to the fixed
    text, and which rules fired. An echo retry never forces the fallback."""
    return {"retried": bool(entries),
            "fallback": any(e["after_retry"] and e["first"] != [ECHO] for e in entries),
            "places_pain": any(p.startswith(PLACES_PAIN) for e in entries for p in e["first"]),
            "echo_retry": any(e["first"] == [ECHO] for e in entries),
            "entries": entries}


def evaluate(cases: list, model: str = None, knowledge: Knowledge = None, verbose: bool = True,
             mode: str = "triage", triage_llm=None) -> dict:
    """mode 'triage': explain the triage.py 2.0 assessment, as the web app
    does (the headline). mode 'legacy': Explanation() without an assessment,
    which explains rules.py 1.0 (the old Test 2 path).
    triage_llm: a stub for triage's model call, for tests."""
    import triage
    knowledge = knowledge or Knowledge()
    results = {"mode": mode, "hallucination": 0, "omission": 0, "contradiction": 0, "misstated": 0,
               "unreported": 0, "unscoped_absence": 0, "arch_reassurance": 0,
               "n": len(cases), "cases": [], "retake_required": 0, "retake_not_requested": 0,
               "guardrail_retry": 0, "guardrail_fallback": 0, "places_pain": 0,
               "follow_up": {"n": 0, "hallucination": 0, "discourages": 0, "misstated": 0,
                             "unreported": 0, "unscoped_absence": 0, "arch_reassurance": 0,
                             "retake_required": 0, "echo": 0, "echo_retry": 0, "guardrail_retry": 0,
                             "guardrail_fallback": 0, "places_pain": 0}}

    for case in cases:
        kwargs = {"allow_unreviewed": True, "knowledge": knowledge}
        if model:
            kwargs["model"] = model
        if mode == "triage":
            tkw = {"allow_unreviewed": True, **({"model": model} if model else {}),
                   **({"llm": triage_llm} if triage_llm else {})}
            kwargs["assessment"] = triage.assess(case["findings"], copy.deepcopy(case.get("symptoms")),
                                                 [], **tkw)
        session = Explanation(case["findings"], case.get("symptoms"), **kwargs)
        may_report = reportable(session.assessment, case["findings"])
        usable = usable_arches(case["findings"])
        retake = bool(session.assessment["retake_required"])

        def absence(text):
            return unscoped_absence(text, usable) if retake else []
        replies = []
        original, recording = _recording_chat(replies)
        explain.chat = recording
        follow_ups = []
        try:
            text = session.first_response()
            first_log = _turn_log(list(session.guardrail_log))
            if mode == "triage":
                for question in case.get("follow_ups", []):
                    before = len(session.guardrail_log)
                    reply = session.ask(question)
                    turn = _turn_log(session.guardrail_log[before:])
                    follow_ups.append({"question": question, "reply": reply, **turn,
                                       "echo": explain.echoes(reply, text),
                                       "hallucinated": sorted(mentioned_teeth(reply)
                                                              - set(case["findings"].get("teeth", {}))),
                                       "discourages": discourages(reply),
                                       "misstated": misstated(reply, case["findings"]),
                                       "unreported": unreported(reply, may_report),
                                       "unscoped_absence": absence(reply),
                                       "arch_reassurance": arch_reassurance(reply)})
        finally:
            explain.chat = original
        assessed = session.assessment
        retried, fell_back = first_log["retried"], first_log["fallback"]
        results["guardrail_retry"] += retried
        results["guardrail_fallback"] += fell_back
        results["places_pain"] += first_log["places_pain"]
        fu = results["follow_up"]
        for f in follow_ups:
            fu["n"] += 1
            fu["hallucination"] += bool(f["hallucinated"])
            fu["discourages"] += bool(f["discourages"])
            fu["misstated"] += bool(f["misstated"])
            fu["unreported"] += bool(f["unreported"])
            fu["unscoped_absence"] += bool(f["unscoped_absence"])
            fu["arch_reassurance"] += bool(f["arch_reassurance"])
            fu["retake_required"] += retake
            fu["echo"] += f["echo"]
            fu["echo_retry"] += f["echo_retry"]
            fu["guardrail_retry"] += f["retried"] and not f["echo_retry"]
            fu["guardrail_fallback"] += f["fallback"]
            fu["places_pain"] += f["places_pain"]

        allowed = set(case["findings"].get("teeth", {}))
        flagged = set(assessed["flagged_teeth"])
        mentioned = mentioned_teeth(text)
        extra = mentioned - allowed
        missing = flagged - mentioned
        if assessed["urgency"] == "RETAKE":
            missing = set()
            extra = mentioned  # a retake response may name no tooth at all
        # A bad photo with URGENT/EMERGENCY symptoms keeps its level and its
        # flagged teeth (interface.md 2.0; lead, 2026-09-24, #18): scored as usual.
        contra = contradiction(text, assessed["urgency"])
        wrong_finding = misstated(text, case["findings"])
        no_retake = bool(assessed["retake_required"]) and not retake_requested(text)
        not_reportable = unreported(text, may_report)
        unscoped, fine = absence(text), arch_reassurance(text)

        results["unreported"] += bool(not_reportable)
        results["unscoped_absence"] += bool(unscoped)
        results["arch_reassurance"] += bool(fine)
        results["retake_required"] += bool(assessed["retake_required"])
        results["retake_not_requested"] += no_retake
        results["misstated"] += bool(wrong_finding)
        results["hallucination"] += bool(extra)
        results["omission"] += bool(missing)
        results["contradiction"] += bool(contra)
        results["cases"].append({
            "id": case["id"], "urgency": assessed["urgency"], "text": text,
            "flagged": sorted(flagged),
            "hallucinated": sorted(extra), "omitted": sorted(missing), "contradiction": contra,
            "misstated": wrong_finding, "retake_required": bool(assessed["retake_required"]),
            "retake_not_requested": no_retake, "unreported": not_reportable,
            "unscoped_absence": unscoped, "arch_reassurance": fine,
            "location": (case.get("symptoms") or {}).get("location"),
            "guardrail_log": first_log["entries"], "fallback": fell_back,
            "places_pain": first_log["places_pain"], "follow_ups": follow_ups, "replies": replies,
        })

        if verbose:
            flags = []
            if extra:
                flags.append(f"HALLUCINATED {sorted(extra)}")
            if missing:
                flags.append(f"OMITTED {sorted(missing)}")
            if contra:
                flags.append(f"CONTRADICTION ({contra})")
            if wrong_finding:
                flags.append(f"MISSTATED: missing teeth {wrong_finding} described as decay")
            if no_retake:
                flags.append("RETAKE NOT REQUESTED (a photo was unusable)")
            if not_reportable:
                flags.append(f"UNREPORTED {not_reportable} told as a finding (not flagged)")
            if unscoped:
                flags.append("UNSCOPED ABSENCE (nothing found, not limited to the usable photo)")
            if fine:
                flags.append("ARCH CALLED FINE")
            print(f"{'FAIL' if flags else 'ok  '} {case['id']} [{assessed['urgency']}] {case['note']}")
            if flags:
                print("       " + "; ".join(flags))
                print("       text: " + text.replace("\n", " ").strip()[:300])
            for entry in first_log["entries"]:
                print(f"       guardrail: {entry['first']} -> after retry "
                      f"{entry['after_retry'] or 'clean'}{'  (FALLBACK TEXT USED)' if fell_back else ''}")
            for f in follow_ups:
                marks = [m for m, on in (("ECHO", f["echo"]), ("echo retry", f["echo_retry"]),
                                         ("FALLBACK", f["fallback"]),
                                         ("places_pain", f["places_pain"]),
                                         (f"HALLUCINATED {f['hallucinated']}", f["hallucinated"]),
                                         (f"DISCOURAGES {f['discourages']!r}", f["discourages"]),
                                         (f"MISSTATED {f['misstated']}", f["misstated"]),
                                         (f"UNREPORTED {f['unreported']}", f["unreported"]),
                                         ("UNSCOPED ABSENCE", f["unscoped_absence"]),
                                         ("ARCH CALLED FINE", f["arch_reassurance"])) if on]
                if marks:
                    print(f"       follow-up {f['question']!r}: {', '.join(marks)}")
            if case.get("must"):
                print(f"       must: {case['must']} | must_not: {case.get('must_not')}")
    return results


def load_cases(mode: str, synthetic: int, seed: int) -> list:
    if synthetic:
        return generate_v2(synthetic, seed) if mode == "triage" else generate(synthetic, seed)
    spec = json.loads(FAITHFULNESS.read_text(encoding="utf-8"))
    bases = json.loads(RULE_CASES.read_text(encoding="utf-8"))
    return [{"id": c["id"], "note": c["note"], "findings": build_findings(c, bases),
             "symptoms": c.get("symptoms"), "must": c.get("must"),
             "must_not": c.get("must_not")} for c in spec["cases"]]


def report(results: dict, label: str) -> None:
    n = results["n"]
    print(f"\n{label}  cases: {n}")
    for rate in ("hallucination", "omission", "contradiction", "misstated", "unreported"):
        print(f"  {rate:14s} {results[rate]}/{n}  ({results[rate] / n:.1%})")
    print(f"  retake not requested  {results['retake_not_requested']}/{results['retake_required']} "
          f"cases with an unusable photo")
    print(f"  unscoped absence      {results['unscoped_absence']}/{results['retake_required']} "
          f"cases with an unusable photo")
    print(f"  arch called fine      {results['arch_reassurance']}/{n}")
    print(f"  guardrail retry {results['guardrail_retry']}/{n}, fallback text used "
          f"{results['guardrail_fallback']}/{n}, places_pain fired {results['places_pain']}/{n}")
    located = sum(bool(c["location"]) for c in results["cases"])
    print(f"  cases with symptoms.location set: {located}/{n}")
    fu = results["follow_up"]
    if fu["n"]:
        m = fu["n"]
        print(f"  follow-ups: {m} turns; echo in the final reply {fu['echo']}/{m}, echo retried "
              f"{fu['echo_retry']}/{m}; hallucinated tooth {fu['hallucination']}/{m}, discourages care "
              f"{fu['discourages']}/{m}, misstated {fu['misstated']}/{m}, unreported tooth "
              f"{fu['unreported']}/{m}; guardrail retry "
              f"{fu['guardrail_retry']}/{m}, fallback {fu['guardrail_fallback']}/{m}, "
              f"places_pain {fu['places_pain']}/{m}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--synthetic", type=int, default=0, help="Generate N synthetic cases instead")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", choices=["triage", "legacy", "both"], default="triage",
                    help="triage: explain the triage 2.0 assessment as the web app does "
                         "(headline); legacy: the rules.py 1.0 path")
    ap.add_argument("--json", help="Write full results here")
    args = ap.parse_args()

    modes = ["triage", "legacy"] if args.mode == "both" else [args.mode]
    out = {}
    for mode in modes:
        out[mode] = evaluate(load_cases(mode, args.synthetic, args.seed), args.model, mode=mode)
    for mode in modes:
        label = ("HEADLINE, triage 2.0 assessment (what patients get)" if mode == "triage"
                 else "LEGACY, rules.py 1.0 assessment (not the app's path)")
        report(out[mode], f"model: {args.model or 'default'}  {label}")
    if args.json:
        data = out[modes[0]] if len(modes) == 1 else out
        Path(args.json).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
