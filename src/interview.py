"""Symptom interview: checklists + fixed questions -> symptoms JSON.

Step 3 of llm/README.md. Python runs the whole interview; the model only
reads the patient's chat answers (docs/decisions.md 2026-09-22: fixed
question text, #11; yes/no questions on a checklist, protocol v0.1 #5):

- Checklist A: the eight red flags and "any pain", all rows at once, each
  needing an explicit Yes or No. Any red-flag Yes ends the interview at
  once; no pain ends it too.
- Checklist B, with pain: night pain, pain on biting, recent extraction.
- Chat, with pain: pain relief, severity, triggers, lingering, where, how
  long. Each answer is extracted into llm/prompts/symptoms_schema.json with
  schema-constrained decoding, and every value needs the patient's own
  words as a quote, checked against the transcript. An answer that settles
  nothing is asked once more, then left null.

The question text, the checklist rows and when each applies come from
llm/protocol/triage_protocol.yaml; the order and the stopping rule are
QUESTION_PLAN below.

Runs against Ollama (llama.cpp underneath, same GBNF grammar path).

    python src/interview.py --allow-unreviewed   # answer it yourself

Replaying the scripted dialogues is Test 3, in src/check_symptoms.py; it
uses record() and extract() and never starts the planned interview.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import requests

import protocol as protocol_mod
from assess import rules

for stream in (sys.stdout, sys.stderr):  # dialogues carry non-Latin text
    stream.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
LLM_DIR = REPO_ROOT / "llm"
SYSTEM_PROMPT = (LLM_DIR / "prompts" / "system_symptoms.md").read_text(encoding="utf-8")
SCHEMA = json.loads((LLM_DIR / "prompts" / "symptoms_schema.json").read_text(encoding="utf-8"))
SCHEMA_VERSION = SCHEMA["properties"]["schema_version"]["const"]

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen3:14b"

# Every symptom field. Extraction asks for {value, quote} per field, so each
# value can be checked against the transcript before it is kept.
EVIDENCE_FIELDS = [f for f in SCHEMA["properties"] if f not in ("schema_version", "notes")]


def evidence_schema(fields: list) -> dict:
    """The constrained-decoding schema for extracting `fields`, each as
    {value, quote}, plus free-text notes."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(fields) + ["notes"],
        "properties": {
            **{field: {"type": "object",
                       "additionalProperties": False,
                       "required": ["value", "quote"],
                       "properties": {"value": SCHEMA["properties"][field],
                                      "quote": {"type": ["string", "null"]}}}
               for field in fields},
            "notes": {"type": "object",
                      "additionalProperties": False,
                      "required": ["value", "quote"],
                      "properties": {"value": {"type": ["string", "null"]},
                                     "quote": {"type": ["string", "null"]}}},
        },
    }


EVIDENCE_SCHEMA = evidence_schema(EVIDENCE_FIELDS)


def _normalize(text: str) -> str:
    """Loose match for quote checking: case and punctuation/spacing folded,
    so a quote counts as supported without being byte-exact."""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


# The interview plan. Python owns the order and when to stop (hard rule 6);
# the protocol owns the wording, which rows sit in which checklist, and the
# asked_if conditions. Every protocol question must appear here exactly once
# (check_plan), so a question added to the protocol cannot be silently skipped.
QUESTION_PLAN = [
    ("checklist", "A"),   # red flags + any pain; a red-flag Yes stops here
    ("checklist", "B"),   # with pain: lingering, night pain, biting, recent extraction
    ("chat", "Q10"),      # pain relief tried, and did it help
    ("chat", "Q11"),      # severity
    ("chat", "Q12"),      # triggers
    ("chat", "Q17"),      # where
    ("chat", "Q18"),      # how long
]

# The same eight fields as the red-flag floor in llm/rules.py.
RED_FLAGS = rules.RED_FLAG_FIELDS

NOT_ENGLISH_NOTICE = "This assistant works in English only. Please answer in English if you can."

# A bare yes/no only answers the question it was a reply to. Without this
# the extractor let the "no" given to the injury question also settle
# pain_present — the quote genuinely is in the transcript — so the pain
# question was skipped and a patient in pain was never asked about it.
# In the planned interview every chat question asks which, how, where or
# how long, so there a bare answer settles nothing at all.
BARE_ANSWERS = {"no", "nope", "nah", "none", "notreally", "never", "yes", "yeah", "yep",
                "yup", "sure", "ok", "okay", "uhhuh", "没有", "沒有", "有", "是", "不是",
                "不", "对", "對"}


def _is_bare(quote: str) -> bool:
    return _normalize(quote) in BARE_ANSWERS


def _plain(text: str) -> str:
    return " ".join((text or "").lower().replace("’", "'").split())


# "I don't know"-type answers. Such an answer settles nothing, except that
# it may be the 'unknown' answer to the question it was the reply to: "hard
# to say" given to the severity question is not an unknown trigger.
HEDGE = re.compile(
    r"\b(?:not (?:really |quite |too )?sure|unsure|not certain|no idea|no clue|dunno|idk"
    r"|(?:do ?n'?t|do not|can'?t|cannot|could ?n'?t|could not) (?:really |honestly )?"
    r"(?:know|remember|recall|say|tell|describe|point|put|pin)"
    r"|hard to (?:say|tell|describe|pin))\b")

# Each pain_triggers item must be named in the patient's own message.
TRIGGER_CUES = {
    "cold": re.compile(r"\b(?:cold|cool|ice|iced|icy|chilled|freezing|frozen)\b"),
    "hot": re.compile(r"\b(?:hot|warm|heat|heated|boiling|steaming)\b"),
    "sweet": re.compile(r"\b(?:sweets?|sugary|sugar|candy|candies|chocolates?|desserts?|cakes?"
                        r"|biscuits?|cookies?|soda)\b"),
    "biting": re.compile(r"\b(?:bite|bites|biting|bit (?:on|down|into)|chew|chews|chewing|chewed"
                         r"|clench\w*|grind\w*)\b"),
    "spontaneous": re.compile(r"\b(?:on its own|by itself|out of nowhere|(?:for )?no reason"
                              r"|without (?:any )?reason|randomly|at random|all the time"
                              r"|constant(?:ly)?|at night|wakes? me|just (?:starts|comes|happens)"
                              r"|nothing (?:sets|brings|sparks) it)\b"),
    "unknown": re.compile(HEDGE.pattern + r"|\b(?:comes and goes|nothing in particular)\b"),
}
# Words that look like a trigger but describe the patient, not the pain.
NOT_A_TRIGGER = re.compile(
    r"\b(?:i|i'm|i am|i've been|feel|feels|feeling|felt|running|am) (?:a bit |quite |very |really |so )?"
    r"(?:hot|warm|cold)\b|\bhot flush\w*|\bcold sweats?\b|\b(?:have|got|caught|had) a cold\b")

# location needs arch AND side each in the patient's words ("on the left"
# alone is not a quadrant). "bite down" is not an arch.
ARCH_CUES = {
    "upper": re.compile(r"\b(?:upper|top|above|maxilla\w*)\b"),
    "lower": re.compile(r"\b(?:lower|bottom|below|down|mandib\w*)\b"),
}
SIDE_CUES = {"left": re.compile(r"\bleft\b"), "right": re.compile(r"\bright\b")}
NOT_A_LOCATION = re.compile(
    r"\b(?:bite|bites|biting|bit|chew\w*|press\w*|push\w*|clench\w*|lie|lying|lay|goes|go|went"
    r"|come|comes|calm\w*|settle\w*|slow\w*|sit\w*) down\b"
    r"|\b(?:all|that's|that is|you're|is) right\b|\bright (?:now|away|after|before)\b"
    r"|\b(?:nothing|none|still|have|has|had) left\b|\bleft (?:it|over|alone|untreated)\b")
PLACE_CUES = {
    "front": re.compile(r"\b(?:front|incisors?|middle|centre|center)\b"),
    "generalised": re.compile(r"\b(?:all over|everywhere|whole|entire|both sides|all around"
                              r"|all (?:of )?(?:my|the) teeth|all of (?:it|them))\b"),
}


def _location_named(value: str, text: str) -> bool:
    text = NOT_A_LOCATION.sub(" ", text)
    if value in PLACE_CUES:
        return bool(PLACE_CUES[value].search(text))
    arch, _, side = value.partition("_")
    return bool(ARCH_CUES[arch].search(text) and SIDE_CUES[side].search(text))


def verify(field: str, value, quote: str, sources: list, own_question=None):
    """What survives of an extracted {value, quote}: the value, a trimmed
    list, or None. sources are (question_id, message) for each patient
    message holding the quote; question_id is None outside the planned
    interview, where no reply is tied to a question. Checks only ever drop
    a value, never add or change one (hard rule 7)."""
    if value in (None, []) or not quote or not sources:
        return None
    planned = any(qid is not None for qid, _ in sources)
    if planned and _is_bare(quote):
        return None  # no chat question is answered by a bare yes/no
    said = " ".join(_plain(text) for _, text in sources)
    in_reply = own_question is None or any(qid == own_question for qid, _ in sources)
    hedged = bool(HEDGE.search(_plain(quote)))

    if field == "pain_triggers":
        said = NOT_A_TRIGGER.sub(" ", said)
        kept = [item for item in value if TRIGGER_CUES[item].search(said)
                and (item != "unknown" or in_reply)]
        return kept or None
    if field == "location":
        # "Not sure where" settles nothing: null, the same as never answered.
        if value == "unknown":
            return None
        return value if _location_named(value, said) else None
    return None if hedged else value


def _not_latin(text: str) -> bool:
    """Letters outside the Latin script: the answer is not in English.
    Romanised non-English text is not caught; that only costs the notice."""
    return any(ch.isalpha() and ord(ch) > 0x24F for ch in text or "")


EXTRACTION_INSTRUCTION = (
    "Fill in the symptoms for this conversation.\n"
    "For every field give two things: the value, and `quote` — the patient's own "
    "words that support it, copied exactly from their messages.\n"
    "- If the patient's words do not settle a field, set value null and quote null. "
    "Never reason a value out from another field; an unasked question stays null.\n"
    "- A denial is support: 'no swelling or fever' supports false for both.\n"
    "- pain_triggers: list what they named (cold, hot, sweet, biting). Pain that "
    "arrives on its own, including at night, is 'spontaneous'. 'Dunno', 'hard to "
    "say' when asked what sets it off is itself an answer — ['unknown'], not null.\n"
    "- pain_relief_effect: 'helped' or 'not_helped' if they took something; "
    "'not_tried' if they say they have not taken anything.\n"
    "- pain_severity: 'severe' when it stops them sleeping or eating or they call "
    "it unbearable; otherwise 'mild' or 'moderate' as they describe it.\n"
    "- location needs arch and side together: 'bottom left' is lower_left, "
    "'on the left' alone is not enough. 'front' is the front teeth, top or bottom, "
    "with no side needed; 'generalised' is pain spread over many teeth or the whole "
    "mouth.\n"
    "- If they corrected themselves, the later answer wins.\n"
    "Quotes are checked against the transcript, so never invent one."
)


def chat(messages: list, model: str = DEFAULT_MODEL, schema: dict = None,
         temperature: float = 0.0, timeout: int = 300) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature},
    }
    if schema:
        payload["format"] = schema
    r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"]


def check_plan(protocol) -> None:
    """Every protocol question is reached by QUESTION_PLAN exactly once:
    checklist rows through their group, chat questions by id."""
    planned_groups = {key for kind, key in QUESTION_PLAN if kind == "checklist"}
    planned_chat = [key for kind, key in QUESTION_PLAN if kind == "chat"]
    problems = []
    for q in protocol.questions:
        if q.input == "yesno_checklist" and q.group not in planned_groups:
            problems.append(f"{q.id}: checklist group {q.group!r} is not in QUESTION_PLAN")
        if q.input == "chat" and planned_chat.count(q.id) != 1:
            problems.append(f"{q.id}: chat question must appear once in QUESTION_PLAN")
    known = {q.id for q in protocol.questions if q.input == "chat"}
    problems += [f"{key}: in QUESTION_PLAN but not a chat question in the protocol"
                 for key in planned_chat if key not in known]
    if problems:
        raise protocol_mod.ProtocolError("interview plan and protocol disagree:\n  "
                                         + "\n  ".join(problems))


class Interview:
    def __init__(self, model: str = DEFAULT_MODEL, allow_unreviewed: bool = False,
                 protocol=None, llm=None):
        """llm: a callable (messages, schema) -> str, for tests; defaults to Ollama."""
        self.model = model
        self.allow_unreviewed = allow_unreviewed
        self.protocol = protocol
        self.llm = llm or (lambda messages, schema: chat(messages, model, schema=schema))
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.reply_to = []      # per patient message: the chat question id it answered
        self.symptoms = {}
        self.checklist = {}     # field -> the patient's explicit Yes/No
        self.completed = set()  # QUESTION_PLAN items that are finished
        self.reasked = set()
        self.pending = None     # ("checklist", group, rows) or ("chat", question)
        self.notice = None
        self.notice_shown = False
        self.done = False
        self.planned = False    # True once start() runs; replayed transcripts stay False

    # --- the planned interview ---------------------------------------------

    def start(self) -> dict:
        """The first step: checklist A."""
        if self.protocol is None:
            self.protocol = protocol_mod.load(allow_unreviewed=self.allow_unreviewed)
        check_plan(self.protocol)
        self.planned = True
        return self._next_step()

    def submit_checklist(self, group: str, answers: dict) -> dict:
        """The patient's answer for every row of the open checklist, as
        {question_id: True | False | None}, where None is "not sure" and is
        only valid on a row that offers it. Refused unless every row carries
        an answer the row allows: an untouched row must never be read as
        "no" (hard rule 7)."""
        if not self.pending or self.pending[0] != "checklist" or self.pending[1] != group:
            raise ValueError(f"checklist {group!r} is not the open step")
        rows = self.pending[2]
        expected = {q.id for q in rows}
        missing, extra = expected - set(answers), set(answers) - expected
        if missing or extra:
            raise ValueError(f"checklist {group}: missing {sorted(missing)}, "
                             f"unexpected {sorted(extra)}")
        unanswered = [q.id for q in rows if not q.allows(answers[q.id])]
        if unanswered:
            raise ValueError(f"checklist {group}: rows {unanswered} need an answer the row "
                             "offers; a row left untouched is never read as no")
        for q in rows:
            self.checklist[q.fields[0]] = answers[q.id]
            self.symptoms[q.fields[0]] = answers[q.id]
        self.completed.add(("checklist", group))
        self.pending = None
        return self._next_step()

    @property
    def checklist_a_done(self) -> bool:
        return ("checklist", "A") in self.completed

    def reply(self, answer: str) -> dict:
        """The patient's answer to the open chat question; returns the next step."""
        if not self.pending or self.pending[0] != "chat":
            raise ValueError("no chat question is open")
        question = self.pending[1]
        self.messages.append({"role": "user", "content": answer})
        self.reply_to.append(question.id)
        if _not_latin(answer) and not self.notice_shown:
            self.notice, self.notice_shown = NOT_ENGLISH_NOTICE, True
        self.symptoms = self.extract()
        unsettled = all(self.symptoms.get(f) is None for f in question.fields)
        if unsettled and question.id not in self.reasked:
            self.reasked.add(question.id)
            return self._ask(question, again=True)
        self.completed.add(("chat", question.id))
        self.pending = None
        return self._next_step()

    def _next_step(self) -> dict:
        """The next plan item that applies and is still open. Pure function of
        what is known — no model involved."""
        if any(self.symptoms.get(f) is True for f in RED_FLAGS):
            return self._finish(red_flag=True)
        for kind, key in QUESTION_PLAN:
            if (kind, key) in self.completed:
                continue
            if kind == "checklist":
                rows = [q for q in self.protocol.questions
                        if q.input == "yesno_checklist" and q.group == key
                        and q.applies(self.symptoms) and self.symptoms.get(q.fields[0]) is None]
                if not rows:
                    continue
                self.pending = ("checklist", key, rows)
                return {"type": "checklist", "group": key,
                        "intro": self.protocol.fixed_text.get("checklist_intro"),
                        "items": [{"id": q.id, "field": q.fields[0], "text": q.text,
                                   "options": q.option_items()} for q in rows]}
            question = next(q for q in self.protocol.questions if q.id == key)
            if not question.applies(self.symptoms):
                continue
            if all(self.symptoms.get(f) is not None for f in question.fields):
                continue  # already settled by an earlier answer
            return self._ask(question)
        return self._finish(red_flag=False)

    def _ask(self, question, again: bool = False) -> dict:
        text = (self.protocol.reask_template.format(question=question.text) if again
                else question.text)
        self.messages.append({"role": "assistant", "content": text})
        self.pending = ("chat", question)
        notice, self.notice = self.notice, None
        return {"type": "question", "id": question.id, "text": text, "notice": notice}

    def _finish(self, red_flag: bool) -> dict:
        self.done = True
        self.pending = None
        return {"type": "done", "symptoms": self.symptoms, "red_flag": red_flag}

    # --- extraction ----------------------------------------------------------

    def record(self, question: str, answer: str) -> None:
        """Add an already-asked question and its answer (for replay)."""
        self.messages.append({"role": "assistant", "content": question})
        self.messages.append({"role": "user", "content": answer})
        self.reply_to.append(None)

    def _chat_fields(self) -> list:
        return [f for q in self.protocol.questions if q.input == "chat" for f in q.fields]

    def extract(self) -> dict:
        """Constrained-decode the transcript into the symptoms object.

        Every field must come with the patient's own words, found inside one
        of their messages, and must pass verify(); otherwise it is dropped to
        null, which is what stops the model inferring one field from another.
        In the planned interview only the chat fields are extracted;
        checklist answers are the patient's clicks and are never overwritten."""
        if self.planned and not self.checklist_a_done:
            # No result before the red-flag rows are answered (lead, 2026-09-22),
            # so "skip to result" can never skip checklist A.
            raise ValueError("checklist A must be answered before a result")
        fields = self._chat_fields() if self.planned else EVIDENCE_FIELDS
        messages = self.messages + [{"role": "user", "content": EXTRACTION_INSTRUCTION}]
        raw = json.loads(self.llm(messages, evidence_schema(fields)))
        turns = [m["content"] for m in self.messages if m["role"] == "user"]
        replies = list(zip(self.reply_to, turns))
        asked_for = ({f: q.id for q in self.protocol.questions if q.input == "chat"
                      for f in q.fields} if self.planned else {})

        symptoms = {"schema_version": SCHEMA_VERSION}
        symptoms.update({f: None for f in EVIDENCE_FIELDS})
        symptoms.update(self.checklist)
        for field in fields:
            entry = raw.get(field) or {}
            value, quote = entry.get("value"), entry.get("quote")
            sources = [(qid, text) for qid, text in replies
                       if _normalize(quote) and _normalize(quote) in _normalize(text)]
            value = verify(field, value, quote, sources, asked_for.get(field))
            if value is not None:
                symptoms[field] = value
            elif self.planned:
                # Re-extraction runs on every turn; a value verified on an
                # earlier turn is kept rather than lost to a later miss. A new
                # supported value still replaces it (the later answer wins).
                symptoms[field] = self.symptoms.get(field)
        symptoms["notes"] = (raw.get("notes") or {}).get("value")
        return symptoms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--allow-unreviewed", action="store_true",
                    help="use the DRAFT-UNREVIEWED protocol (development only)")
    ap.add_argument("--out", help="Write the symptoms JSON here")
    args = ap.parse_args()

    session = Interview(args.model, allow_unreviewed=args.allow_unreviewed)
    step = session.start()
    while step["type"] != "done":
        if step["type"] == "checklist":
            answers = {}
            for item in step["items"]:
                reply = ""
                while reply not in ("y", "n"):
                    reply = input(f"[{step['group']}] {item['text']} (y/n) ").strip().lower()[:1]
                answers[item["id"]] = reply == "y"
            step = session.submit_checklist(step["group"], answers)
        else:
            if step["notice"]:
                print(step["notice"])
            step = session.reply(input(f"> {step['text']}\n  "))
    if step["red_flag"]:
        print("\n" + session.protocol.headlines["EMERGENCY"])

    text = json.dumps(step["symptoms"], indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\nwrote {args.out}")
    else:
        print("\n" + text)


if __name__ == "__main__":
    main()
