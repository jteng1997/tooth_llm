"""Explanation step: findings + symptoms + assessment + knowledge -> text.

Step 5 of llm/README.md. The model only verbalises what the other stages
decided — it never sees a photo, never picks the urgency, and answers
questions only from the retrieved passages.

    python src/explain.py --findings findings.json \
                          [--symptoms s.json] [--ask "is it definitely a cavity?"]

The assessment is handed in from src/triage.py (assessment 2.0), so the
text restates an urgency that code has already checked. Without one, the
rules.py result is computed here: that is the Test 2 baseline. Every reply
is checked against the brief's guardrails (no medicine names or doses, no
diagnosis, no home procedures, the "Based on the image, there is an
indication of" wording); a reply that still breaks one after a single
rewrite is replaced by fixed text.

Knowledge passages carry their file's review_status. llm/README.md says
not to ship anything still marked DRAFT-UNREVIEWED, so unreviewed
passages are refused unless --allow-unreviewed is passed, which is for
development only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import interview
import triage
from assess import assess, rules
from interview import chat, DEFAULT_MODEL
from retrieval import Knowledge

REPO_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT = (REPO_ROOT / "llm" / "prompts" / "system_explain.md").read_text(encoding="utf-8")
UNREVIEWED = "DRAFT-UNREVIEWED"


class UnreviewedKnowledge(RuntimeError):
    pass


# The prompt asks for a plain-word location beside every FDI number, and the
# model gets it wrong (it called 36 "upper right"). The mapping is fixed, so
# it is computed here and handed over rather than left to the model.
_QUADRANTS = {"1": "upper right", "2": "upper left", "3": "lower left", "4": "lower right",
              "5": "upper right baby", "6": "upper left baby",
              "7": "lower left baby", "8": "lower right baby"}
_POSITIONS = {"1": "central incisor", "2": "lateral incisor", "3": "canine",
              "4": "first premolar", "5": "second premolar", "6": "first molar",
              "7": "second molar", "8": "third molar (wisdom tooth)"}


def fdi_label(fdi: str) -> str:
    """'36' -> 'lower left first molar'."""
    quadrant, position = str(fdi)[0], str(fdi)[1]
    if quadrant not in _QUADRANTS or position not in _POSITIONS:
        return "tooth " + str(fdi)
    return f"{_QUADRANTS[quadrant]} {_POSITIONS[position]}"


def tooth_names(findings: dict) -> dict:
    return {fdi: fdi_label(fdi) for fdi in findings.get("teeth", {})}


def _passages_block(passages: list) -> str:
    if not passages:
        return "knowledge_passages: []"
    parts = [f"### {p['heading']} ({p['file']})\n{p['text']}" for p in passages]
    return "knowledge_passages:\n" + "\n\n".join(parts)


def _first_query(findings: dict, assessment: dict) -> str:
    """What to retrieve for the opening message, before the user has asked
    anything: the urgency being explained plus the kinds of finding."""
    types = sorted({d["type"] for t in findings.get("teeth", {}).values()
                    for d in t.get("detections", [])})
    if "reasons" in assessment:  # assessment 2.0, from triage.py
        why = [r["statement"] for r in assessment["reasons"]]
    else:                        # 1.0, from rules.py
        why = [assessment["rule_reason"].replace("_", " ")]
    return " ".join([assessment["urgency"], *why, *types,
                     "what this means and what to do"]).strip()


# The brief's guardrails, checked on the text itself, because a prompt rule
# alone is a request, not a guarantee. Conservative on purpose: every
# medicine name is refused, over-the-counter ones included, since the brief
# allows only a general mention of pain relief.
_MEDICINES = ("amoxicillin", "amoxycillin", "penicillin", "metronidazole", "clindamycin",
              "azithromycin", "erythromycin", "doxycycline", "cephalexin", "cefalexin",
              "co-amoxiclav", "augmentin", "antibiotic", "codeine", "tramadol", "oxycodone",
              "hydrocodone", "morphine", "diclofenac", "naproxen", "ibuprofen", "paracetamol",
              "acetaminophen", "aspirin", "chlorhexidine", "benzocaine", "lidocaine",
              "fluconazole", "nystatin", "prednisolone", "steroid")
# A name list alone is not enough: research-pm's audit of "clean" ChatDoctor
# answers found 8 of 15 medicine leaks under names the dataset's own spelling
# correction had mangled ("petrol DT", "erosion forte", "stolen gum paint",
# "President 5000 plus"). The shape survives even when the name does not, so
# these match the shape of a prescription instead.
#
# Deliberately still missed: "Evil, Lyrics & Polite", "Mention violet",
# "Metro lag". They carry no medicine shape at all, and a pattern loose
# enough to catch them fires on ordinary words. Measured, not assumed: the
# rules below flag 0 of the 60 stored qwen3:14b explanations. Do not widen
# them without re-running that check (research-pm, 2026-09-23).
_PRODUCT_SHAPES = (
    r"\bforte\b|\bDT\b",                                   # erosion forte, petrol DT
    r"\b(?:[A-Z][\w-]+|\d+)\s+(?:plus|XR|SR)\b",           # President 5000 plus
    r"\b(?:tab|tablet|cap|capsule|syp|syrup|inj|injection)\.?\s+[A-Z][\w-]+",  # Tab Diploma
    r"\b[\w-]+\s+(?:gel|ointment|paint|mouthwash|lozenges?|antiseptic)\b",     # gum paint
    r"\b[A-Z][a-z]+\s+[A-Z]{2,}\s*\d+\b",                  # Humor HP 75
)
GUARDRAILS = [
    ("names a medicine", re.compile(r"\b(" + "|".join(map(re.escape, _MEDICINES)) + r")s?\b", re.I)),
    ("names a medicine by its shape", re.compile("|".join(_PRODUCT_SHAPES))),
    ("gives a dose", re.compile(r"\b\d+(\.\d+)?\s?(mg|milligrams?|ml|mcg|g)\b"
                                r"|\b(times|x) (a|per) day\b|\bevery \d+ hours\b"
                                r"|\b(once|twice|three times) (a day|daily)\b", re.I)),
    ("sounds like a diagnosis", re.compile(
        r"\byou (definitely |clearly )?(have|'ve got|have got) (an? )?"
        r"(cavity|cavities|caries|tooth decay|decay|abscess|infection|pulpitis|gum disease)\b"
        r"|\bdefinitely (an? )?(cavity|cavities|caries|decay|abscess|infection)\b"
        r"|\bis definitely\b|\bthis is (an? )?(cavity|caries|abscess)\b|\bi diagnose\b", re.I)),
    ("suggests a home procedure", re.compile(
        r"\b(pull|drain|pop|lance|file|drill)\w*\b[^.]{0,40}\b(yourself|at home)\b"
        r"|\b(yourself|at home)\b[^.]{0,40}\b(pull|drain|pop|lance|file|drill)", re.I)),
]
FINDING_PHRASE = "based on the image, there is an indication of"

# Words that make a follow-up message worth checking for a red flag. Like the
# interview's keyword rule, a hit only starts a check: it never sets a field.
RED_FLAG_KEYWORDS = re.compile(
    r"\bswell\w*|\bpuffy\b|\bfever\b|\btemperature\b|\bshiver\w*|\bunwell\b|\bfaint\w*\b"
    r"|\bbreath\w*|\bbreathe\b|\bswallow\w*|\bchok\w*|\bbleed\w*|\bblood\b"
    r"|\bknocked\b|\bhit\b|\bfell\b|\binjur\w*|\bpassed out\b|\bchest pain\b"
    r"|\btoo many\b|\boverdose\b|\bmore than the packet\b", re.I)


def guardrail_violations(text: str, flagged_teeth: list = ()) -> list:
    """What the text does that the brief forbids; empty when it is fine."""
    found = [name for name, pattern in GUARDRAILS if pattern.search(text or "")]
    if flagged_teeth and FINDING_PHRASE not in " ".join((text or "").lower().split()):
        found.append('does not use "Based on the image, there is an indication of"')
    return found


# Where the patient's pain is comes only from symptoms.location. The model
# otherwise reads it off the photo ("Your toothache is on the upper right side,
# tooth 16" with location null), which invents a side and ties the pain to a
# finding the tool cannot link to it.
_PAIN = re.compile(r"\b(?:pain|painful|toothache|ache|aches|aching|hurts?|hurting|sore|soreness"
                   r"|discomfort|sensitiv\w*)\b", re.I)
_NOT_PAIN = re.compile(r"\bpain ?relie\w*|\bpainkillers?\b", re.I)
_SIDE = re.compile(r"\b(?:left|right|upper|lower|top|bottom)\b", re.I)
_NOT_SIDE = re.compile(r"\bright (?:away|now)\b|\ball right\b|\bupper and lower\b", re.I)
_TOOTH_REF = re.compile(r"\b(?:tooth|teeth) \d{2}\b|\b(?:tooth|teeth) (?:we|that was|that were) found\b"
                        r"|\bfirst molar\b|\bsecond molar\b|\bpremolar\b|\bincisor\b|\bcanine\b",
                        re.I)
# "May be related to the tooth we found, only a dentist can confirm" and "is
# not coming from a tooth we found" are honest; "comes from tooth 16" is not.
_HEDGED = re.compile(r"\b(?:may|might|could|possibly|perhaps|not|cannot|can't|don't|do not"
                     r"|unclear|only a dentist)\b", re.I)
_LOCATION_WORDS = {"upper_left": {"upper", "top", "left"}, "upper_right": {"upper", "top", "right"},
                   "lower_left": {"lower", "bottom", "left"},
                   "lower_right": {"lower", "bottom", "right"}}


def places_pain(text: str, location: str = None) -> bool:
    """Does the text say where the patient's pain is, beyond what they told
    us? A sentence about their pain may use only the side words of
    symptoms.location, and ties the pain to a tooth only hedged or denied."""
    allowed = _LOCATION_WORDS.get(location, set())
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        s = _NOT_SIDE.sub(" ", _NOT_PAIN.sub(" ", sentence))
        if not _PAIN.search(s):
            continue
        if {w.lower() for w in _SIDE.findall(s)} - allowed:
            return True
        if _TOOTH_REF.search(s) and not _HEDGED.search(s):
            return True
    return False


FOLLOW_UP_INSTRUCTION = (
    "This is a follow-up question, not the first response. Answer only this question, "
    "in a few short sentences, from the passages above and the findings, symptoms and "
    "assessment you already have. Do not repeat your first response: restate the "
    "findings, the urgency or the limitations only if the question asks about them.")


def _sentences(text: str) -> list:
    return [" ".join(s.lower().split()) for s in re.split(r"(?<=[.!?])\s+|\n+", text or "")
            if len(s.split()) >= 4]


def echoes(reply: str, first: str) -> bool:
    """Does the reply re-print most of the first response?"""
    earlier = set(_sentences(first))
    if not earlier:
        return False
    return len(earlier & set(_sentences(reply))) / len(earlier) >= 0.5


def split_flagged(assessment: dict, findings: dict = None) -> tuple:
    """(decay, missing): the teeth the text may report, and as what. rules.py
    R8 puts an absent tooth in flagged_teeth; assessment 2.0 keeps
    flagged_teeth for decay and cites the missing tooth as a reason. Either
    way a missing tooth must never be described as decay."""
    absent = rules.missing_teeth(findings or {})
    flagged = assessment.get("flagged_teeth") or []
    decay = [t for t in flagged if t not in absent]
    missing = [t for t in flagged if t in absent]
    cites_missing = any(
        "missing" in (r.get("statement") or "").lower()
        or any(e.get("field") == "unexpected_missing_teeth" for e in r.get("evidence") or [])
        for r in assessment.get("reasons") or [])
    if cites_missing and not assessment.get("retake_required"):
        missing = sorted(set(missing) | set(absent))
    return decay, missing


_DECAY_WORDS = re.compile(r"\b(?:decay\w*|cavit\w*|caries|carious)\b", re.I)


def calls_missing_decay(text: str, missing: list) -> list:
    """Missing teeth that a sentence of the text describes as decay."""
    if not missing:
        return []
    wrong = set()
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if _DECAY_WORDS.search(sentence):
            wrong |= {t for t in missing
                      if re.search(rf"(?<!\d){t}(?!\d)", sentence)
                      or fdi_label(t) in sentence.lower()}
    return sorted(wrong)


# User decision 2026-09-23 (sentence B): never deny a tooth cause. The
# photos can miss a problem; only a dentist can tell what causes the pain.
_DENIES_TOOTH_CAUSE = re.compile(
    r"\bnot (?:be )?(?:coming|caused|come|from) (?:from |by )?(?:a|any|your|the|one of your) "
    r"(?:tooth|teeth)\b"
    r"|\b(?:isn't|is not|doesn't|does not|won't|can't be|cannot be|unlikely to be) "
    r"(?:be )?(?:coming|come|caused|from) (?:from |by )?(?:a|any|your|the) (?:tooth|teeth)\b"
    r"|\bnot an? (?:tooth|dental) (?:problem|issue|cause)\b"
    r"|\b(?:nothing|no problem|nothing is) wrong with your teeth\b"
    r"|\byour teeth (?:are|look|seem) (?:fine|healthy|ok|okay|normal|good)\b"
    r"|\bno (?:problems?|issues?) with your teeth\b"
    r"|\b(?:rule[sd]? out|ruling out) (?:a )?(?:tooth|dental)\b", re.I)
# "This does not mean your teeth are fine" is the message we want, not a denial.
_NEGATED = re.compile(r"\b(?:not|n't|never) (?:mean|say|prove|show|tell us)\b[^.]*$", re.I)


def denies_tooth_cause(text: str) -> bool:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        m = _DENIES_TOOTH_CAUSE.search(sentence)
        if m and not _NEGATED.search(sentence[:m.start()]):
            return True
    return False


# retake_required with an urgency other than RETAKE: one photo was unusable,
# but symptoms that need care are never hidden behind a bad photo
# (interface.md). The result is given in full and the bad photo is retaken.
def partial_retake(assessment: dict) -> bool:
    return bool(assessment.get("retake_required")) and assessment.get("urgency") != "RETAKE"


def unusable_arches(findings: dict) -> list:
    return sorted({p.split(":")[0] for p in rules.quality_problems(findings or {})}
                  & {"upper", "lower"})


_RETAKE_HOW = "good light, the whole arch in view, and the camera held still."


def _retake_sentence(findings: dict) -> str:
    arches = unusable_arches(findings)
    if len(arches) == 1:
        return (f"The photo of your {arches[0]} teeth could not be used, so please take it "
                f"again: {_RETAKE_HOW}")
    return f"The photos could not be used, so please take them again: {_RETAKE_HOW}"


_ASKS_RETAKE = re.compile(
    r"\bre-?take\b|\btake (?:it|them) again\b"
    r"|\b(?:take|send|upload)\b[^.!?]{0,40}\b(?:photos?|pictures?|images?)\b[^.!?]{0,20}\bagain\b"
    r"|\b(?:photos?|pictures?|images?) again\b|\bnew (?:photos?|pictures?|images?)\b", re.I)


def _states_headline(text: str, headline: str) -> bool:
    return interview._normalize(headline) in interview._normalize(text)


def _teeth(teeth: list) -> str:
    return ", ".join(f"tooth {t} ({fdi_label(t)})" for t in teeth)


def model_findings(findings: dict, assessment: dict) -> dict:
    """The findings the explanation model is shown: image quality, arches, and
    only the teeth it may report (flagged decay, reportable missing). A
    detection below the reporting threshold never reaches the model, so it
    cannot be told to the patient as a finding."""
    decay, missing = split_flagged(assessment, findings)
    teeth = (findings or {}).get("teeth") or {}
    shown = {t: {**teeth[t], "detections": [
                d for d in teeth[t].get("detections", [])
                if d.get("type") in ("caries", "cavity")
                and d.get("confidence", 0) >= rules.CARIES_CONF_THRESHOLD]}
             for t in decay if t in teeth}
    shown.update({t: {"present": False, "detections": []} for t in missing})
    out = {k: v for k, v in (findings or {}).items()
           if k not in ("teeth", "unassigned_detections")}
    out["teeth"] = shown
    return out


_ALL_FDI = [f"{q}{p}" for q in "1234" for p in "12345678"]
_TOOTH_NUMBERS = re.compile(
    r"\b(?:tooth|teeth)\s+#?([1-4][1-8](?:(?:\s*,\s*|\s+and\s+|\s+or\s+|\s*&\s*|\s*/\s*)"
    r"(?:tooth\s+)?#?[1-4][1-8])*)\b", re.I)
_FINDING_WORDS = re.compile(
    r"\b(?:decay\w*|cavit\w*|caries|carious|fillings?|restorations?|crowns?|indication|signs?"
    r"|issues?|problems?|unusual|lesions?|spots?|damage\w*|findings?|found|detected|missing"
    r"|broken|crack\w*|shadows?)\b", re.I)
# "Nothing on tooth 26 reached...", "no decay on tooth 26": the negation governs
# the tooth. "...on tooth 11, but we are not sure what it is" is still a report.
_NEGATION = re.compile(r"\b(?:no|not|nothing|none|never|didn't|did not|doesn't|does not|isn't"
                       r"|wasn't|without|nor)\b[^.,;]{0,40}\b(?:tooth|teeth|molar|premolar"
                       r"|incisor|canine)\b", re.I)


def teeth_named(sentence: str) -> set:
    """FDI teeth a sentence names, by number ("tooth 26", "teeth 15, 31 and 34")
    or by plain-word name ("upper left first molar"). A bare number is not a
    tooth ("within 24 hours")."""
    named = set()
    for m in _TOOTH_NUMBERS.finditer(sentence):
        named |= set(re.findall(r"[1-4][1-8]", m.group(1)))
    low = sentence.lower()
    return named | {t for t in _ALL_FDI if fdi_label(t) in low}


def reports_unreported(text: str, allowed) -> list:
    """Teeth outside `allowed` that a sentence reports a finding on. A sentence
    that only names a tooth, or denies something on it, is not a report
    (denials are denies_tooth_finding's)."""
    wrong = set()
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if _FINDING_WORDS.search(sentence) and not _NEGATION.search(sentence):
            wrong |= teeth_named(sentence) - set(allowed)
    return sorted(wrong)


# "Tooth 26 is fine", "no decay on tooth 26": a tooth with nothing reported may
# still have a problem the photo missed.
_DENIES_TOOTH_FINDING = re.compile(
    r"\bno (?:signs? of |sign of )?(?:problems?|issues?|decay|cavit\w*|caries|damage)"
    r"[^.]{0,20}\b(?:on|in|with|for) (?:your )?(?:tooth|teeth) [1-4][1-8]\b"
    r"|\b(?:tooth|teeth) [1-4][1-8]\b[^.]{0,40}\b(?:is|are|looks?|seems?) (?:fine|healthy|ok"
    r"|okay|normal|good|clear|free of)\b"
    r"|\b(?:tooth|teeth) [1-4][1-8]\b[^.]{0,30}\b(?:has|have) no\b"
    # Reassurance is a denial too: the photos can miss a problem.
    r"|\bnothing (?:to|you need to|you should) worry about\b"
    r"|\bnot (?:something|anything) to worry about\b"
    r"|\bno (?:cause|reason|need) (?:for|to) (?:concern|worry|be worried|be concerned)\b"
    r"|\bprobably (?:fine|nothing|ok|okay|harmless|not (?:serious|a problem|anything))\b", re.I)


def denies_tooth_finding(text: str) -> bool:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        m = _DENIES_TOOTH_FINDING.search(sentence)
        if m and not _NEGATED.search(sentence[:m.start()]):
            return True
    return False


# Prompt rule 6: never tell the patient they can avoid or delay seeing a
# dentist. "You don't need to wait for the new photo to book" is fine.
_DISCOURAGES = re.compile(
    r"\b(?:don't|do not|won't|will not|wouldn't) (?:really |actually )?need (?:to (?:see|visit|go to"
    r"|book|call) )?(?:a |the |your |an? )?(?:dentist|dental (?:visit|appointment|check))"
    r"|\bno need (?:to (?:see|visit|go to|book|call)|for) (?:a |the |your |an? )?"
    r"(?:dentist|dental (?:visit|appointment|check)|appointment|treatment)"
    # "There is no need to visit today": no dentist word. Going to hospital, A&E,
    # a pharmacy or a doctor instead is a different message and stays allowed.
    r"|\b(?:no need|(?:don't|do not|won't|will not) (?:really |actually )?need) to (?:visit|go"
    r"|come in|book|make an appointment)\b(?!\s+(?:to\s+)?(?:the\s+|a\s+|an\s+|your\s+)?"
    r"(?:hospital|emergency|a&e|er\b|pharmacy|pharmacist|chemist|gp|doctor))"
    r"|\b(?:it|this|that|you) can wait\b|\bskip (?:the |your |a )?dentist"
    r"|\bavoid (?:the |a |your )?dentist|\b(?:unnecessary|not necessary) to see (?:a )?dentist", re.I)


def discourages_care(text: str) -> bool:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        m = _DISCOURAGES.search(sentence)
        if m and not _NEGATED.search(sentence[:m.start()]):
            return True
    return False


RETAKE_MISSING = "does not ask for a retake of the photo that could not be used"


def decay_sentence(decay: list) -> str:
    return f"Based on the image, there is an indication of tooth decay on {_teeth(decay)}."


def missing_sentence(missing: list) -> str:
    return (f"Based on the image, {_teeth(missing)} "
            f"{'appears' if len(missing) == 1 else 'appear'} to be missing.")


def fallback_text(assessment: dict, findings: dict = None) -> str:
    """Deterministic first response, used when the model's text keeps
    breaking a guardrail. Plain, and built only from the assessment (and
    findings, to tell a missing tooth from decay)."""
    parts = ["We looked at your two photos of the biting surfaces of your teeth."]
    decay, missing = split_flagged(assessment, findings)
    partial = partial_retake(assessment)
    if assessment["retake_required"] and not partial:
        parts.append(f"The photos could not be used, so please take them again: {_RETAKE_HOW}")
    elif decay or missing:
        if decay:
            parts.append(decay_sentence(decay))
        if missing:
            parts.append(missing_sentence(missing))
    elif not partial:
        parts.append("Nothing in these photos reached the level we report. That does not "
                     "rule anything out.")
    elif len(unusable_arches(findings)) == 1:
        parts.append("Nothing in the photo we could use reached the level we report. That "
                     "does not rule anything out.")
    headline = assessment["headline"].strip()
    # The protocol's headlines already end in a full stop; older 1.0 ones don't.
    parts.append(headline if headline.endswith((".", "!", "?")) else headline + ".")
    if partial:
        parts.append(_retake_sentence(findings))
    parts += assessment["limitations"]
    parts.append("You can ask me questions about this result.")
    return " ".join(parts)


class Explanation:
    def __init__(self, findings: dict, symptoms: dict = None, model: str = DEFAULT_MODEL,
                 allow_unreviewed: bool = False, knowledge: Knowledge = None,
                 assessment: dict = None):
        """assessment: the 2.0 object from triage.assess(). Without one, the
        rules.py result is explained — the Test 2 baseline."""
        self.findings = findings
        self.symptoms = symptoms
        self.assessment = assessment or assess(findings, symptoms)
        self.guardrail_log = []
        self.first_text = None
        self.model = model
        self.allow_unreviewed = allow_unreviewed
        self.knowledge = knowledge or Knowledge()
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def _retrieve(self, query: str) -> list:
        passages = self.knowledge.search(query)
        unreviewed = [p["file"] for p in passages if p["review_status"] == UNREVIEWED]
        if unreviewed and not self.allow_unreviewed:
            raise UnreviewedKnowledge(
                f"{UNREVIEWED} knowledge retrieved ({', '.join(sorted(set(unreviewed)))}). "
                "A dentist must sign these off; pass --allow-unreviewed for development."
            )
        return passages

    def first_response(self) -> str:
        passages = self._retrieve(_first_query(self.findings, self.assessment))
        shown = model_findings(self.findings, self.assessment)
        content = "\n\n".join([
            "findings:\n" + json.dumps(shown, indent=2),
            "symptoms:\n" + json.dumps(self.symptoms, indent=2) if self.symptoms
            else "symptoms: null (the user did not do the interview)",
            "assessment:\n" + json.dumps(self.assessment, indent=2),
            "tooth_names (plain-word location for each number; write a tooth as "
            "\"tooth 36 (lower left first molar)\", always giving both):\n"
            + json.dumps(tooth_names(shown), indent=2),
            _passages_block(passages),
            self._scope_instruction(),
        ])
        decay, missing = split_flagged(self.assessment, self.findings)
        self.first_text = self._checked_turn(content, decay, missing=missing, first=True,
                                             fallback=fallback_text(self.assessment,
                                                                    self.findings))
        return self.first_text

    def _scope_instruction(self) -> str:
        """What may be reported at all. The model is shown model_findings()
        only, so a detection below the reporting threshold never reaches it;
        this instruction and reports_unreported() hold the same line."""
        partial = partial_retake(self.assessment)
        if self.assessment["retake_required"] and not partial:
            return ("Write the first response now. The photos could not be used: ask for "
                    "a retake and explain how. Do not mention any tooth, number or "
                    "finding — not even in plain words.")
        decay, missing = split_flagged(self.assessment, self.findings)
        if decay or missing:
            scope = "Only these teeth may be described as having a possible finding: "
            if decay:
                scope += ("possible tooth decay on " + ", ".join(decay) + ". Write it as this "
                          f"sentence, word for word: \"{decay_sentence(decay)}\" ")
            if missing:
                scope += ("appears to be missing: " + ", ".join(missing) + " (a missing "
                          "tooth is not decay: never say decay or a cavity for it). Write it as "
                          f"this sentence, word for word: \"{missing_sentence(missing)}\" ")
        else:
            scope = ("No tooth may be described as having a finding: nothing reached the "
                     "reporting threshold. Say nothing was found, and that this does not "
                     "rule anything out. ")
        scope += ("Never describe a finding on any other tooth, and never say another "
                  "tooth is fine. ")
        if partial:
            arches = unusable_arches(self.findings)
            which = (f"The photo of the {arches[0]} teeth" if len(arches) == 1
                     else "A photo")
            scope += (f"{which} could not be used: ask for a retake of it with this sentence, "
                      f"word for word: \"{_retake_sentence(self.findings)}\" "
                      "The result still stands and must be given in full: state "
                      "assessment.headline word for word and why, from assessment.reasons. "
                      "Never make acting on it wait for the new photo. ")
        return scope + "Write the first response now."

    def red_flag_raised(self, text: str) -> bool:
        """Did the patient just report a red flag in a follow-up message?

        Design §1.6: a red flag reported after the result must still reach
        EMERGENCY. Two stages, so a normal question costs nothing: a keyword
        scan that only decides whether to look closer, then the same
        evidence-checked extraction the interview uses, over this message
        alone. The keywords never set a field — only the patient's quoted
        words do, and only for the eight floor fields."""
        if not RED_FLAG_KEYWORDS.search(text or ""):
            return False
        fields = list(rules.RED_FLAG_FIELDS)
        messages = [{"role": "system", "content": interview.SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                    {"role": "user", "content": interview.EXTRACTION_INSTRUCTION}]
        try:
            raw = json.loads(chat(messages, self.model, schema=interview.evidence_schema(fields)))
        except (ValueError, KeyError):
            return False
        said = interview._normalize(text)
        found = {}
        for field in fields:
            entry = raw.get(field) or {}
            quote = entry.get("quote")
            if (entry.get("value") is True and quote
                    and interview._normalize(quote) in said and not interview._is_bare(quote)):
                found[field] = True
        if not found:
            return False
        self.symptoms = {**(self.symptoms or {}), **found}
        # The floor fires on these, so this recomputation makes no model call.
        self.assessment = triage.assess(self.findings, self.symptoms,
                                        [{"role": "user", "content": text}], self.model,
                                        allow_unreviewed=self.allow_unreviewed)
        return True

    def ask(self, question: str) -> str:
        if self.red_flag_raised(question):
            # The fixed emergency wording, not prose: the page switches to the
            # emergency screen on the new assessment.
            return self.assessment["headline"] + " " + self.assessment["safety_net"]
        passages = self._retrieve(question)
        return self._checked_turn(
            _passages_block(passages) + f"\n\nUser asks: {question}\n\n" + FOLLOW_UP_INSTRUCTION,
            fallback="I can't answer that safely here. Please ask a dentist or pharmacist.",
            echo_of=self.first_text)

    def _checked_turn(self, content: str, flagged_teeth=(), fallback: str = "",
                      echo_of: str = None, missing=None, first: bool = False) -> str:
        """One turn, with the guardrails checked on the reply: one
        regeneration that names the problem, then the fixed fallback.
        A follow-up that re-prints the first response (echo_of) gets one
        rewrite too, but an echo is not unsafe, so it never forces the
        fallback."""
        self.messages.append({"role": "user", "content": content})
        location = (self.symptoms or {}).get("location")
        reportable = {t for group in split_flagged(self.assessment, self.findings) for t in group}
        # Any tooth the photo shows absent, flagged or not (third molars too).
        missing = sorted({*(missing or []),
                          *(t for t, v in (self.findings or {}).get("teeth", {}).items()
                            if v.get("present") is False)})

        def violations(text):
            found = guardrail_violations(text, flagged_teeth)
            wrong = calls_missing_decay(text, missing)
            if wrong:
                found.append(f"describes missing tooth {', '.join(wrong)} as decay; "
                             "a missing tooth is only missing")
            if places_pain(text, location):
                found.append("says where the patient's pain is or which tooth causes it, "
                             "beyond symptoms.location")
            if denies_tooth_cause(text):
                found.append("says the pain is not from a tooth or the teeth are fine; the "
                             "photos can miss a problem and only a dentist can tell what "
                             "causes the pain")
            unreported = reports_unreported(text, reportable)
            if unreported:
                found.append(f"describes a finding on tooth {', '.join(unreported)}, which is "
                             "not one of the teeth that may be reported")
            if discourages_care(text):
                found.append("tells the patient they can skip or delay seeing a dentist; never "
                             "do that")
            if denies_tooth_finding(text):
                found.append("says a tooth is fine or has no problem; say instead that nothing "
                             "on it reached the level we report, and that this does not rule "
                             "anything out")
            if first and partial_retake(self.assessment):
                headline = self.assessment["headline"].strip()
                if not _states_headline(text, headline):
                    found.append(f'does not state the urgency as "{headline}"; a photo to '
                                 "retake never hides the result")
                if not _ASKS_RETAKE.search(text):
                    found.append(RETAKE_MISSING)
            return found

        def with_retake(text):
            """The model's text with the fixed retake sentence appended, when
            that sentence is all it lacks; None otherwise."""
            patched = text.rstrip() + " " + _retake_sentence(self.findings)
            return None if violations(patched) else patched

        reply = chat(self.messages, self.model)
        problems = violations(reply)
        if echo_of and echoes(reply, echo_of):
            retry = self.messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": "Rewrite your reply. It repeats your first response. "
                                            "Answer only the question, in a few sentences."}]
            rewritten = chat(retry, self.model)
            self.guardrail_log.append({"first": ["repeats the first response"],
                                       "after_retry": ["repeats the first response"]
                                       if echoes(rewritten, echo_of) else []})
            reply, problems = rewritten, violations(rewritten)
        if problems == [RETAKE_MISSING] and with_retake(reply):
            # A rewrite never added it (Test 2 v3: 8/8 identical retries), and
            # the sentence is fixed text, so it is added here.
            self.guardrail_log.append({"first": problems, "after_retry": [],
                                       "appended": "retake sentence"})
            reply, problems = with_retake(reply), []
        if problems:
            ask = "Rewrite your reply. It " + "; it ".join(problems) + ". Follow the hard rules."
            if flagged_teeth and any(FINDING_PHRASE in p.lower() for p in problems):
                ask += f" Use this sentence word for word: \"{decay_sentence(flagged_teeth)}\""
            retry = self.messages + [{"role": "assistant", "content": reply},
                                     {"role": "user", "content": ask}]
            reply = chat(retry, self.model)
            later = violations(reply)
            if later == [RETAKE_MISSING] and with_retake(reply):
                reply, later = with_retake(reply), []
                self.guardrail_log.append({"first": problems, "after_retry": [],
                                           "appended": "retake sentence"})
            else:
                self.guardrail_log.append({"first": problems, "after_retry": later})
            if later:
                reply = fallback
        self.messages.append({"role": "assistant", "content": reply})
        return reply


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", required=True)
    ap.add_argument("--symptoms")
    ap.add_argument("--ask", action="append", default=[], help="Follow-up question; repeatable")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--allow-unreviewed", action="store_true")
    args = ap.parse_args()

    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    symptoms = json.loads(Path(args.symptoms).read_text(encoding="utf-8")) if args.symptoms else None

    try:
        session = Explanation(findings, symptoms, args.model, args.allow_unreviewed)
        print(f"[assessment] {session.assessment['urgency']} / {session.assessment['rule_id']}\n")
        print(session.first_response())
        for question in args.ask:
            print(f"\n--- user: {question}\n")
            print(session.ask(question))
    except UnreviewedKnowledge as exc:
        print(f"refused: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
