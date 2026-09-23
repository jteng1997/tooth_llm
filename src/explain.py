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
    """(decay, missing): rules.py R8 flags a tooth that is absent, and that
    tooth must never be described as decay."""
    absent = set(rules.missing_teeth(findings or {}))
    flagged = assessment.get("flagged_teeth") or []
    return ([t for t in flagged if t not in absent], [t for t in flagged if t in absent])


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


def _teeth(teeth: list) -> str:
    return ", ".join(f"tooth {t} ({fdi_label(t)})" for t in teeth)


def fallback_text(assessment: dict, findings: dict = None) -> str:
    """Deterministic first response, used when the model's text keeps
    breaking a guardrail. Plain, and built only from the assessment (and
    findings, to tell a missing tooth from decay)."""
    parts = ["We looked at your two photos of the biting surfaces of your teeth."]
    decay, missing = split_flagged(assessment, findings)
    if assessment["retake_required"] and assessment["urgency"] == "RETAKE":
        parts.append("The photos could not be used, so please take them again: good "
                     "light, the whole arch in view, and the camera held still.")
    elif decay or missing:
        if decay:
            parts.append(f"Based on the image, there is an indication of tooth decay on "
                         f"{_teeth(decay)}.")
        if missing:
            parts.append(f"Based on the image, {_teeth(missing)} "
                         f"{'appears' if len(missing) == 1 else 'appear'} to be missing.")
    else:
        parts.append("Nothing in these photos reached the level we report. That does not "
                     "rule anything out.")
    headline = assessment["headline"].strip()
    # The protocol's headlines already end in a full stop; older 1.0 ones don't.
    parts.append(headline if headline.endswith((".", "!", "?")) else headline + ".")
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
        content = "\n\n".join([
            "findings:\n" + json.dumps(self.findings, indent=2),
            "symptoms:\n" + json.dumps(self.symptoms, indent=2) if self.symptoms
            else "symptoms: null (the user did not do the interview)",
            "assessment:\n" + json.dumps(self.assessment, indent=2),
            "tooth_names (plain-word location for each number; write a tooth as "
            "\"tooth 36 (lower left first molar)\", always giving both):\n"
            + json.dumps(tooth_names(self.findings), indent=2),
            _passages_block(passages),
            self._scope_instruction(),
        ])
        decay, missing = split_flagged(self.assessment, self.findings)
        self.first_text = self._checked_turn(content, decay, missing=missing,
                                             fallback=fallback_text(self.assessment,
                                                                    self.findings))
        return self.first_text

    def _scope_instruction(self) -> str:
        """What may be reported at all.

        findings.teeth carries every detection the model made, including
        ones below the reporting threshold in rules.py. Only the teeth
        rules.py flagged may be described as possible cavities — otherwise
        a 0.22-confidence blip gets told to the user as a finding.
        """
        if self.assessment["retake_required"]:
            return ("Write the first response now. The photos could not be used: ask for "
                    "a retake and explain how. Do not mention any tooth, number or "
                    "finding — not even in plain words.")
        decay, missing = split_flagged(self.assessment, self.findings)
        if decay or missing:
            scope = "Only these teeth may be described as having a possible finding: "
            if decay:
                scope += "possible tooth decay on " + ", ".join(decay) + ". "
            if missing:
                scope += ("appears to be missing: " + ", ".join(missing) + " (a missing "
                          "tooth is not decay: never say decay or a cavity for it). ")
        else:
            scope = ("No tooth may be described as having a finding: nothing reached the "
                     "reporting threshold. Say nothing was found, and that this does not "
                     "rule anything out. ")
        return (scope + "Any other detection in findings was below the reporting threshold "
                "and must not be mentioned at all. Write the first response now.")

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
                      echo_of: str = None, missing=None) -> str:
        """One turn, with the guardrails checked on the reply: one
        regeneration that names the problem, then the fixed fallback.
        A follow-up that re-prints the first response (echo_of) gets one
        rewrite too, but an echo is not unsafe, so it never forces the
        fallback."""
        self.messages.append({"role": "user", "content": content})
        location = (self.symptoms or {}).get("location")
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
            return found

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
        if problems:
            retry = self.messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": "Rewrite your reply. It " + "; it ".join(problems)
                                            + ". Follow the hard rules."}]
            reply = chat(retry, self.model)
            later = violations(reply)
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
