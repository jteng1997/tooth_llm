"""Symptom interview: conversation -> symptoms JSON.

Step 3 of llm/README.md. The model asks the questions in
llm/prompts/system_symptoms.md, then the answers are extracted into the object in
llm/prompts/symptoms_schema.json with schema-constrained decoding, so the result
is valid JSON by construction rather than by parsing hope.

Two calls per interview, not one: asking questions needs prose, and
constrained decoding would force JSON on every turn. So the same
transcript is replayed once more with the schema attached to extract the
object. The extraction call is told to use null for anything unanswered.

Runs against Ollama (llama.cpp underneath, same GBNF grammar path).

    python src/interview.py                     # talk to it yourself

Replaying the scripted dialogues is Test 3, in src/check_symptoms.py.
"""
import argparse
import json
import sys
from pathlib import Path

import requests

for stream in (sys.stdout, sys.stderr):  # dialogues carry non-Latin text
    stream.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
LLM_DIR = REPO_ROOT / "llm"
SYSTEM_PROMPT = (LLM_DIR / "prompts" / "system_symptoms.md").read_text(encoding="utf-8")
SCHEMA = json.loads((LLM_DIR / "prompts" / "symptoms_schema.json").read_text(encoding="utf-8"))

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen3:14b"

# Extraction asks for {value, quote} per field, so each value can be checked
# against the transcript before it is kept.
EVIDENCE_FIELDS = [f for f in SCHEMA["properties"] if f not in ("schema_version", "notes")]
EVIDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": EVIDENCE_FIELDS + ["notes"],
    "properties": {
        **{field: {"type": "object",
                   "additionalProperties": False,
                   "required": ["value", "quote"],
                   "properties": {"value": SCHEMA["properties"][field],
                                  "quote": {"type": ["string", "null"]}}}
           for field in EVIDENCE_FIELDS},
        "notes": {"type": "object",
                  "additionalProperties": False,
                  "required": ["value", "quote"],
                  "properties": {"value": {"type": ["string", "null"]},
                                 "quote": {"type": ["string", "null"]}}},
    },
}


def _normalize(text: str) -> str:
    """Loose match for quote checking: case and punctuation/spacing folded,
    so a quote counts as supported without being byte-exact."""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


# The interview plan, in the order llm/prompts/system_symptoms.md prescribes: red
# flags first, then pain, and pain details only if there is pain. Python
# walks this list and decides when the interview is over; the model only
# phrases the question it is handed. Left to itself the model repeated
# questions and never stopped.
QUESTION_PLAN = [
    (("swelling", "fever"), "any swelling in the face or gums, and any fever", False),
    (("difficulty_swallowing_or_breathing",), "any difficulty swallowing or breathing", False),
    (("recent_trauma",), "any recent knock or injury to a tooth", False),
    (("pain_present",), "any pain or discomfort in the teeth or gums right now", False),
    (("pain_triggers",), "what sets the pain off: cold, hot, sweet, biting, or whether "
                         "it comes on by itself", True),
    (("pain_lingers_over_30s",), "whether the pain fades quickly or keeps aching for "
                                 "more than about half a minute", True),
    (("pain_wakes_at_night",), "whether the pain ever wakes them at night", True),
    (("location",), "where the pain is: upper or lower, left or right side, or the front", True),
    (("duration_days",), "how long the pain has been going on", True),
]
RED_FLAGS = ("swelling", "fever", "difficulty_swallowing_or_breathing", "recent_trauma")
MAX_QUESTIONS = len(QUESTION_PLAN) + 2  # headroom, never unbounded
FIELD_ITEM = {f: i for i, (fields, _, _) in enumerate(QUESTION_PLAN) for f in fields}

# A bare yes/no only answers the question it was a reply to. Without this
# the extractor let the "no" given to the injury question also settle
# pain_present — the quote genuinely is in the transcript — so the pain
# question was skipped and a patient in pain was never asked about it.
BARE_ANSWERS = {"no", "nope", "nah", "none", "notreally", "never", "yes", "yeah", "yep",
                "yup", "sure", "ok", "okay", "没有", "沒有", "有", "是", "不是", "不", "对", "對"}


def _is_bare(quote: str) -> bool:
    return _normalize(quote) in BARE_ANSWERS

ASK_INSTRUCTION = (
    "This is a question turn. Ask the user about exactly this, and nothing else: {topic}. "
    "One short, plain question in the language the user is writing in. Do not output "
    "JSON, do not repeat earlier questions, and do not give results or opinions."
)
EXTRACTION_INSTRUCTION = (
    "The interview is over. Fill in the symptoms for this conversation.\n"
    "For every field give two things: the value, and `quote` — the user's own "
    "words that support it, copied exactly from their messages.\n"
    "- If the user's words do not settle a field, set value null and quote null. "
    "Never reason a value out from another field; an unasked question stays null.\n"
    "- A denial is support: 'no swelling or fever' supports false for both.\n"
    "- pain_triggers: list what they named (cold, hot, sweet, biting). Pain that "
    "arrives on its own, including at night, is 'spontaneous'. 'Dunno', 'hard to "
    "say' when asked what sets it off is itself an answer — ['unknown'], not null.\n"
    "- location needs arch and side together: 'bottom left' is lower_left, "
    "'on the left' alone is not enough.\n"
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


def next_topic(symptoms: dict, asked: set):
    """Index of the next plan item to ask about, or None when the interview
    is complete. Pure function of what is known — no model involved.

    Stops when a red flag is reported (the rule engine takes it from there),
    and skips pain details unless pain is confirmed. An item already asked
    is never asked again: if the answer didn't settle it, the field stays
    null, which is the spec's "unanswered", not a reason to loop.
    """
    if any(symptoms.get(f) is True for f in RED_FLAGS):
        return None
    for index, (fields, _, needs_pain) in enumerate(QUESTION_PLAN):
        if index in asked:
            continue
        if needs_pain and symptoms.get("pain_present") is not True:
            continue
        if any(symptoms.get(f) is None for f in fields):
            return index
    return None


class Interview:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.asked = set()
        self.symptoms = {}
        self.done = False
        self.planned = False  # True once start() runs; replayed transcripts stay False

    def start(self) -> str:
        """First question. Nothing is known yet, so no extraction needed."""
        self.planned = True
        return self._ask(next_topic({}, self.asked))

    def reply(self, answer: str) -> dict:
        """Take the user's answer. Returns {"done": False, "question": ...}
        or {"done": True, "symptoms": ...} once nothing needed is missing."""
        self.messages.append({"role": "user", "content": answer})
        self.symptoms = self.extract()
        index = next_topic(self.symptoms, self.asked)
        if index is None or len(self.asked) >= MAX_QUESTIONS:
            self.done = True
            return {"done": True, "symptoms": self.symptoms}
        return {"done": False, "question": self._ask(index)}

    def _ask(self, index: int) -> str:
        """Have the model phrase plan item `index`. The system prompt ends by
        demanding JSON, so the turn-level instruction keeps this to prose."""
        topic = QUESTION_PLAN[index][1]
        prompt = self.messages + [{"role": "system", "content": ASK_INSTRUCTION.format(topic=topic)}]
        question = chat(prompt, self.model).strip()
        self.messages.append({"role": "assistant", "content": question})
        self.asked.add(index)
        return question

    def record(self, question: str, answer: str) -> None:
        """Add an already-asked question and its answer (for replay)."""
        self.messages.append({"role": "assistant", "content": question})
        self.messages.append({"role": "user", "content": answer})

    def extract(self) -> dict:
        """Constrained-decode the transcript into the symptoms object.

        Every field must come with the user's own words. A field whose quote
        isn't actually in the transcript is dropped to null, which is what
        stops the model inferring one field from another."""
        messages = self.messages + [{"role": "user", "content": EXTRACTION_INSTRUCTION}]
        raw = json.loads(chat(messages, self.model, schema=EVIDENCE_SCHEMA))
        said = _normalize(" ".join(m["content"] for m in self.messages if m["role"] == "user"))

        symptoms = {"schema_version": "1.0"}
        for field in EVIDENCE_FIELDS:
            entry = raw.get(field) or {}
            value, quote = entry.get("value"), entry.get("quote")
            supported = bool(quote) and _normalize(quote) in said
            if (supported and self.planned and _is_bare(quote)
                    and FIELD_ITEM.get(field) not in self.asked):
                supported = False  # a yes/no given to a different question
            symptoms[field] = value if supported else None
            if symptoms[field] == []:
                symptoms[field] = None
        symptoms["notes"] = (raw.get("notes") or {}).get("value")
        return symptoms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", help="Write the symptoms JSON here")
    args = ap.parse_args()

    session = Interview(args.model)
    print("(the interview ends by itself; type 'done' to stop early)\n")
    question = session.start()
    while True:
        print(f"> {question}")
        answer = input("  ")
        if answer.strip().lower() in {"done", "quit", "exit"}:
            symptoms = session.extract()
            break
        step = session.reply(answer)
        if step["done"]:
            symptoms = step["symptoms"]
            break
        question = step["question"]

    text = json.dumps(symptoms, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\nwrote {args.out}")
    else:
        print("\n" + text)


if __name__ == "__main__":
    main()
