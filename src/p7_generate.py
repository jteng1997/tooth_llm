"""P7: patient words for the held-out keys, and the blind second-model check.

Implements docs/plans/p7-vignette-text-spec.md and docs/plans/p7-generation-prompt.md.
Held-out and e2e outputs go to labels/heldout/p7/ (ignored by version control) and must
never be shown to llm-dev; dev outputs go to runs/p7/.

    python src/p7_generate.py smoke                              # the local generator
    python src/p7_generate.py smoke-b                            # model B (Gemini API), 3 dev texts
    python src/p7_generate.py generate --file triage --dry-run --limit 3   # prompts only
    python src/p7_generate.py generate --file triage             # llama3.1:8b writes the text
    python src/p7_generate.py extract --file triage              # gemini-3.5-flash-lite (API), blind; run smoke-b first
    python src/p7_generate.py writeback --file triage            # accepted text -> key file

One model loaded at a time: all generation first, then all extraction.
Generation and extraction resume where they stopped.
"""
import argparse
import datetime
import hashlib
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import jsonschema
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
HELDOUT = REPO_ROOT / "labels" / "heldout"
OUT = REPO_ROOT / "runs" / "p7"   # dev text and the smoke test; llm-dev may read runs/


def out_dir(kind: str) -> Path:
    """Held-out-derived text never goes where llm-dev can read it."""
    return OUT if kind == "dev" else HELDOUT / "p7"


KEY_FILES = {"dev": REPO_ROOT / "labels" / "dev" / "triage_dev_keys.json",
             "triage": HELDOUT / "triage_heldout_keys.json", "e2e": HELDOUT / "e2e_keys.json"}
SEEDS = {"dev": 20260924, "triage": 20260923, "e2e": 20260923}   # generator seed = base + attempt
PARAPHRASE_SEED_STEP = 1000   # paraphrase p (1, 2): base + 1000 * p + attempt (spec §9.3)
REWRITES = HELDOUT / "p7_fact_rewrites.json"
OLLAMA = "http://localhost:11434/api/chat"

GENERATOR = "llama3.1:8b"
MODEL_B = "gemini-3.5-flash-lite"   # paid Gemini API (user decision 2026-09-23, task #16)
MODEL_B_FALLBACK = "gemma3:12b"     # local, documented fallback if the API fails (research-pm)
B_MODELS = {"gemini": MODEL_B, "ollama": MODEL_B_FALLBACK}
SCHEMA_TRANSLATION = ("none: interview.evidence_schema() is sent unchanged (Gemini "
                      "responseJsonSchema / Ollama format). The schema mode is decided once per "
                      "run at smoke-b: enforced, or json_only with local validation if Gemini "
                      "refuses the schema; never switched mid-run")
SEED = 20260923
TEMPERATURE = 0.8
MAX_ATTEMPT = 4          # attempts 0..4, then the case goes to research-pm
JACCARD_MAX = 0.8
WORDS = {"patient_words": (15, 90), "opening": (15, 90), "answer": (3, 40)}

RED_FLAGS = ("difficulty_swallowing_or_breathing", "chest_pain_or_breathless", "swelling",
             "fever", "systemically_unwell", "recent_trauma", "bleeding_uncontrolled",
             "exceeded_pain_relief_dose")
CHAT_QUESTIONS = ("Q10", "Q11", "Q12", "Q17", "Q18")

SYSTEM_MESSAGE = """You write short messages as a patient would type them into a dental
screening app. You are not a dentist and neither is the patient.

Rules:
- Write only what the patient types, in the first person. No quotation
  marks around it, no stage directions, no explanations.
- Get across every fact and every "must get across" point you are given,
  in the patient's own everyday words. Retell them; do not copy the given
  wording.
- Say nothing about anything listed under "must not say", and add no other
  symptoms, times, sides of the mouth, triggers or medicines of your own.
- The patient does not judge how serious it is and does not ask to be seen
  by a certain time. Never use the words emergency, urgent, routine or soon,
  and never say how quickly they need a dentist.
- No medical terms a patient would not use. "Abscess" or "gum boil" are fine.
- Never name a medicine, a brand or a dose. Say "painkillers" or "something
  from the pharmacy". Do not mention tablets, gels, mouthwash, antibiotics
  or antiseptics.
- Never mention a checklist, a form, boxes, ticks, questions or the app.
- If you are given a sentence marked VERBATIM, include it exactly as written,
  character for character, as part of what the patient types.
- Follow the style you are given.
- Reply with the JSON object requested and nothing else."""

STYLE_LINES = {
    "plain": "Ordinary, clear everyday English.",
    "vague": 'Hedged and imprecise ("sort of", "I think", "maybe"), but every point you must '
             "get across is still there.",
    "non_native": "English as a second language: simple tenses, some missing articles, small "
                  "word-order slips. Stay respectful; no invented accent or dialect.",
    "self_correcting": 'At least once, first say something slightly wrong, then correct it ("the '
                       'left — no, the right side"). The corrected version must match what you '
                       "were given. Correct only details you were given.",
    "verbose": "Long and chatty, with everyday life detail unrelated to the teeth. The extra "
               "detail must not add symptoms, times, sides or medicines.",
    "terse": "A few words, little or no punctuation. Every point still there.",
}

RELIEF = {"helped": "They took painkillers or something from the pharmacy and it helped.",
          "not_helped": "They took painkillers or something from the pharmacy and it did not help.",
          "not_tried": "They have not taken anything for the pain."}
SEVERITY = {"mild": "The pain is mild — noticeable but easy to put up with.",
            "moderate": "The pain is fairly bad and bothers them, but they still sleep and eat "
                        "normally.",
            "severe": "The pain is so bad they cannot sleep or eat properly."}
TRIGGER = {"cold": "The pain is set off by cold things.", "hot": "The pain is set off by hot things.",
           "sweet": "The pain is set off by sweet things.",
           "biting": "The pain is set off by biting down.",
           "spontaneous": "The pain comes on by itself, with nothing setting it off.",
           "unknown": "They cannot tell what sets the pain off."}
QUADRANT = {"upper_left": "upper left", "upper_right": "upper right", "lower_left": "lower left",
            "lower_right": "lower right"}
DURATION = {1: "since yesterday", 7: "a week", 10: "about ten days", 14: "two weeks",
            21: "three weeks", 30: "about a month"}
MUST_NOT = {"location": "Do not say which side or whether it is top or bottom.",
            "pain_relief_effect": "Do not make clear whether they took anything or whether it helped.",
            "duration_days": "Do not say how long it has been going on.",
            "pain_severity": "Do not say how bad it is.",
            "pain_triggers": "Do not say what sets it off."}
CHAT_FIELD_ORDER = ("pain_relief_effect", "pain_severity", "pain_triggers", "location",
                    "duration_days")
QUESTION_TOPICS = {
    "Q10": "what, if anything, they have taken for the pain and whether it helped",
    "Q11": "how bad the pain is",
    "Q12": "what sets the pain off",
    "Q17": "where in the mouth the pain is",
    "Q18": "how long they have had the pain",
}
INJECTION = re.compile(r"^(?P<fact>.*); also writes: '(?P<line>.*)'$")
LEVEL_WORDS = re.compile(r"\b(?:emergenc(?:y|ies)|urgent(?:ly)?|urgency|routine|soon)\b", re.I)
TIME_ADVICE = re.compile(r"\bwithin (?:the next )?(?:\d+|a|an|one|two|three|a few|24|48) "
                         r"(?:hours?|days?|weeks?)\b|\bas soon as possible\b|\basap\b", re.I)
FORM_WORDS = re.compile(r"\b(?:checklist|tick(?:ed|s)?|checkbox(?:es)?|form)\b", re.I)


# --- Building the prompt -------------------------------------------------------------

def reached_chat(symptoms: dict) -> bool:
    """The chat questions are asked only with pain and no red flag."""
    return symptoms.get("pain_present") is True and not any(symptoms.get(f) is True
                                                            for f in RED_FLAGS)


def split_facts(facts: list, rewrites: dict, archetype: str = None) -> tuple:
    """(plain facts after the §3.2 rewrites, VERBATIM lines, extra must-not-say lines).
    The unclear-answers line goes to every key of that archetype (dev too)."""
    plain, verbatim, extra = [], [], []
    unclear = (archetype is not None and archetype == rewrites.get("unclear_answers_archetype")
               or rewrites.get("unclear_answers_fact") in facts)
    if unclear:
        extra.append(rewrites["unclear_answers_extra_line"])
    for fact in facts:
        m = INJECTION.match(fact)
        if m:
            fact = m["fact"]
            verbatim.append(m["line"])
        plain.append(rewrites["rewrites"].get(fact, fact))
    return plain, verbatim, extra


def duration_phrase(days: int) -> str:
    if days in DURATION:
        return DURATION[days]
    if 2 <= days <= 5:
        return f"{days} days"
    raise ValueError(f"duration_days {days} has no fixed phrase (p7-generation-prompt §3.3)")


def must_get_across(symptoms: dict) -> list:
    lines = []
    for field in CHAT_FIELD_ORDER:
        value = symptoms.get(field)
        if value is None:
            continue
        if field == "pain_relief_effect":
            lines.append(RELIEF[value])
        elif field == "pain_severity":
            lines.append(SEVERITY[value])
        elif field == "pain_triggers":
            lines += [TRIGGER[t] for t in value]
        elif field == "location":
            if value in QUADRANT:
                lines.append(f"The pain is in the {QUADRANT[value]} of the mouth. Name both "
                             "top-or-bottom and left-or-right.")
            elif value == "front":
                lines.append("The pain is at the front of the mouth.")
            else:
                raise ValueError(f"location {value!r} has no fixed line")
        elif field == "duration_days":
            phrase = duration_phrase(value)
            lines.append("They have had the pain since yesterday." if value == 1
                         else f"They have had the pain for {phrase}.")
    return lines


def must_not_say(symptoms: dict) -> list:
    return [MUST_NOT[f] for f in CHAT_FIELD_ORDER if symptoms.get(f) is None]


def chat_questions(key: dict) -> list:
    return [q for q in key.get("expected_questions", []) if q in CHAT_QUESTIONS]


def build_prompt(key: dict, kind: str, rewrites: dict) -> dict:
    """The user message, the reply schema and what the checks need."""
    plain, verbatim, extra = split_facts(key["facts"], rewrites, key.get("archetype"))
    reached = reached_chat(key["symptoms"])
    get_across = must_get_across(key["symptoms"]) if reached else []
    not_say = (must_not_say(key["symptoms"]) + extra) if reached else []
    style = key["style"]
    lines = [f"Style: {style} — {STYLE_LINES[style]}", "", "Facts (all must come across):"]
    lines += [f"- {f}" for f in plain]
    if get_across:
        lines += ["Must get across:"] + [f"- {x}" for x in get_across]
    if not_say:
        lines += ["Must not say:"] + [f"- {x}" for x in not_say]
    lines += [f"VERBATIM: {v}" for v in verbatim]
    lines.append("")
    questions = chat_questions(key) if kind == "e2e" else []
    if kind == "triage":
        lines += ["Write everything this patient typed during the chat in one message of 15 to",
                  "90 words.", "", 'Reply as JSON: {"patient_words": "..."}']
        schema = {"type": "object", "properties": {"patient_words": {"type": "string"}},
                  "required": ["patient_words"]}
    else:
        lines += ["First write the patient's opening message (15 to 90 words) describing why",
                  "they are using the app. Put the facts here; include the VERBATIM sentence",
                  "here if there is one."]
        if questions:
            lines.append("Then write the patient's reply, 3 to 40 words, to each of these questions:")
            lines += [f"- {q}: {QUESTION_TOPICS[q]}" for q in questions]
            lines += ["Each reply answers only its own question. A reply to a question listed under",
                      '"must not say" must not answer it: the patient is unsure, or cannot tell.']
        example = ", ".join(f'"{q}": "..."' for q in questions)
        lines += ["", 'Reply as JSON: {"opening": "...", "script": {' + example + "}}"]
        schema = {"type": "object", "required": ["opening", "script"],
                  "properties": {"opening": {"type": "string"},
                                 "script": {"type": "object", "additionalProperties": False,
                                            "required": questions,
                                            "properties": {q: {"type": "string"} for q in questions}}}}
    return {"user": "\n".join(lines), "schema": schema, "verbatim": verbatim,
            "reached": reached, "questions": questions}


def leaks(prompt: str, key: dict, criterion_ids: list) -> list:
    """Anything that names the answer (spec §4). Level words may appear only
    inside a VERBATIM line."""
    outside = "\n".join(l for l in prompt.splitlines() if not l.startswith("VERBATIM:"))
    found = []
    if LEVEL_WORDS.search(outside):
        found.append("level word")
    if key.get("archetype") and key["archetype"] in prompt:
        found.append("archetype")
    ids = [c for c in criterion_ids if re.search(rf"\b{re.escape(c)}\b", outside)]
    if ids:
        found.append(f"criterion ids {ids}")
    # the template's own Style line and JSON reply key are snake_case by design
    content = "\n".join(l for l in outside.splitlines()
                        if not l.startswith(("Style:", "Reply as JSON:")))
    snake = re.findall(r"\b[a-z]+_[a-z_]+\b", content)
    if snake:
        found.append(f"snake_case name {sorted(set(snake))}")
    return found


# --- Checks on the text (spec §5) ------------------------------------------------------

def tokens(text: str) -> list:
    return re.findall(r"[a-z0-9']+", text.lower())


def ngrams(words: list, n: int = 5) -> set:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: str, b: str) -> float:
    sa, sb = set(tokens(a)), set(tokens(b))
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


class Checker:
    def __init__(self, protocol, symptom_schema: dict, guardrails: list):
        self.criterion_ids = protocol.criterion_ids()
        self.statement_grams = set().union(*(ngrams(tokens(c.statement)) for c in protocol.criteria))
        names = set(symptom_schema["properties"])
        for spec in symptom_schema["properties"].values():
            for enum in (spec.get("enum") or spec.get("items", {}).get("enum") or []):
                if isinstance(enum, str):
                    names.add(enum)
        self.field_names = sorted(n for n in names if "_" in n)
        self.guardrails = guardrails

    def check_text(self, text: str, verbatim: list, bounds: tuple) -> list:
        """Failure labels for one piece of patient text; empty = accepted."""
        failures = []
        n = len(text.split())
        if not bounds[0] <= n <= bounds[1]:
            failures.append(f"length {n} outside {bounds[0]}-{bounds[1]}")
        rest = text
        for line in verbatim:
            rest = rest.replace(line, " ")
        ids = [c for c in self.criterion_ids if re.search(rf"\b{re.escape(c)}\b", rest)]
        if ids:
            failures.append(f"criterion id {ids}")
        if LEVEL_WORDS.search(rest):
            failures.append(f"level word '{LEVEL_WORDS.search(rest)[0]}'")
        shared = ngrams(tokens(rest)) & self.statement_grams
        if shared:
            failures.append(f"protocol statement 5-gram '{' '.join(sorted(shared)[0])}'")
        low = rest.lower()
        names = [f for f in self.field_names if re.search(rf"\b{re.escape(f)}\b", low)]
        if names:
            failures.append(f"field name {names}")
        for label, pattern in self.guardrails:
            if pattern.search(rest):
                failures.append(label)
        return failures


def advisory(text: str) -> list:
    """Not reasons to regenerate under §5; listed for research-pm's read."""
    notes = []
    if TIME_ADVICE.search(text):
        notes.append(f"time frame '{TIME_ADVICE.search(text)[0]}'")
    if FORM_WORDS.search(text):
        notes.append(f"form word '{FORM_WORDS.search(text)[0]}'")
    if text.strip()[:1] in "\"'" and text.strip()[-1:] in "\"'":
        notes.append("wrapped in quotation marks")
    return notes


def check_reply(reply: dict, prompt: dict, kind: str, checker: Checker) -> list:
    if kind == "triage":
        text = reply["patient_words"]
        failures = checker.check_text(text, prompt["verbatim"], WORDS["patient_words"])
        where = text
    else:
        failures = [f"opening: {f}" for f in
                    checker.check_text(reply["opening"], prompt["verbatim"], WORDS["opening"])]
        if set(reply["script"]) != set(prompt["questions"]):
            failures.append(f"script keys {sorted(reply['script'])} != {prompt['questions']}")
        for q, answer in reply["script"].items():
            failures += [f"{q}: {f}" for f in checker.check_text(answer, [], WORDS["answer"])]
        where = reply["opening"]
    missing = [v for v in prompt["verbatim"] if v not in where]
    if missing:
        failures.append("VERBATIM line not included exactly")
    return failures


def reply_text(reply: dict) -> str:
    if "patient_words" in reply:
        return reply["patient_words"]
    return " ".join([reply["opening"]] + list(reply["script"].values()))


# --- Ollama ---------------------------------------------------------------------------

def ollama(model: str, messages: list, schema: dict, temperature: float, seed: int,
           think: bool = True, timeout: int = 600, full: bool = False):
    """think=True sends "think": false as production does; False omits the key.
    full=True returns the whole message (content and any thinking)."""
    payload = {"model": model, "messages": messages, "stream": False, "format": schema,
               "options": {"temperature": temperature, "seed": seed}}
    if think:
        payload["think"] = False
    r = requests.post(OLLAMA, json=payload, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"ollama {r.status_code}: {r.text[:300]}")
    return r.json()["message"] if full else r.json()["message"]["content"]


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_RETRY_STATUS = (429, 500, 502, 503, 504)
GEMINI_RETRIES = 5


def gemini_key() -> str:
    """GEMINI_API_KEY from the environment or the repo's .env (gitignored).
    Never printed, logged or written anywhere."""
    import os
    key = os.environ.get("GEMINI_API_KEY")
    env = REPO_ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "GEMINI_API_KEY":
                key = value.strip().strip('"').strip("'")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set (environment or .env); the user adds it")
    return key


def _redact(text: str, key: str) -> str:
    return (text or "").replace(key, "<redacted>") if key else (text or "")


def _gemini_contents(messages: list) -> tuple:
    """(systemInstruction text, contents) from chat messages; consecutive
    turns of one role are merged, since Gemini expects user/model turns."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "model" if m["role"] == "assistant" else "user"
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].append({"text": m["content"]})
        else:
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
    return system, contents


class SchemaRefused(RuntimeError):
    """Gemini refused the response schema. Never fallen through per call: the
    schema mode is decided once per run, at the smoke test."""


def gemini(messages: list, schema: dict, model: str = None, temperature: float = 0.0,
           post=None, sleep=None, key: str = None, schema_mode: str = "enforced") -> tuple:
    """One Gemini call with retry and backoff. Returns (reply text, call record);
    the record holds the requested model id, the response modelVersion and the
    date, never the key. schema_mode 'enforced' sends the schema and raises
    SchemaRefused if the API refuses it; 'json_only' sends JSON mode alone
    (the reply is validated locally either way)."""
    import time
    model = model or MODEL_B
    post = post or requests.post
    sleep = sleep or time.sleep
    key = key or gemini_key()
    system, contents = _gemini_contents(messages)
    config = {"temperature": temperature, "responseMimeType": "application/json"}
    if schema_mode == "enforced":
        config["responseJsonSchema"] = schema
    body = {"contents": contents, "generationConfig": config}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    record = {"requested_model": model, "date": datetime.datetime.now().isoformat(timespec="seconds"),
              "temperature": temperature, "schema_mode": schema_mode}
    last = None
    for attempt in range(GEMINI_RETRIES + 1):
        try:
            r = post(GEMINI_URL.format(model=model), json=body, timeout=120,
                     headers={"x-goog-api-key": key, "Content-Type": "application/json"})
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}"
            sleep(min(60, 2 ** attempt))
            continue
        if r.status_code == 200:
            data = r.json()
            candidate = (data.get("candidates") or [{}])[0]
            parts = (candidate.get("content") or {}).get("parts") or []
            record.update(model_version=data.get("modelVersion"), attempts=attempt + 1,
                          finish_reason=candidate.get("finishReason"),
                          thought_parts=sum(bool(p.get("thought")) for p in parts),
                          usage=data.get("usageMetadata"), raw_response=data)
            return "".join(p.get("text", "") for p in parts if not p.get("thought")), record
        text = _redact(r.text[:300], key)
        if r.status_code == 400 and schema_mode == "enforced" and "schema" in text.lower():
            raise SchemaRefused(f"gemini refused the response schema: {text}")
        if r.status_code in GEMINI_RETRY_STATUS:
            last = f"HTTP {r.status_code}"
            sleep(min(60, 2 ** attempt))
            continue
        raise RuntimeError(f"gemini {r.status_code}: {text}")
    raise RuntimeError(f"gemini: gave up after {GEMINI_RETRIES + 1} attempts ({last})")


def b_extract(messages: list, schema: dict, post=None, sleep=None, key=None,
              backend: str = "gemini", local=None, schema_mode: str = "enforced") -> tuple:
    """Model B's reply as a dict validated against the schema, plus the call
    record (model, version, date, settings, raw response). backend 'ollama'
    is the local fallback, with the thinking check."""
    if backend == "gemini":
        text, record = gemini(messages, schema, post=post, sleep=sleep, key=key,
                              schema_mode=schema_mode)
    else:
        call = local or (lambda m, s: ollama(MODEL_B_FALLBACK, m, s, 0.0, SEED,
                                             sends_think(MODEL_B_FALLBACK), full=True))
        message = call(messages, schema)
        text = message.get("content") or ""
        record = {"requested_model": MODEL_B_FALLBACK, "model_version": MODEL_B_FALLBACK,
                  "date": datetime.datetime.now().isoformat(timespec="seconds"),
                  "temperature": 0.0, "schema_mode": "enforced", "raw_response": message,
                  "thinking_off": thinking_off(message)}
        if not record["thinking_off"]:
            record.update(valid=False, invalid_reason="reasoning text in the reply")
            return {}, record
    try:
        raw = json.loads(text)
        jsonschema.validate(raw, schema)
        record["valid"] = True
    except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raw, record["valid"] = {}, False
        record["invalid_reason"] = str(exc)[:200]
    record["parsed"] = raw
    return raw, record


SMOKE_B_CASES = 3


def smoke_b(post=None, sleep=None, key=None) -> int:
    """Model B on 3 dev texts, before any extraction (task #16). Passes only if
    every call returns schema-valid JSON, finishes normally, carries a
    modelVersion, and returns no thought parts. Dev texts only: the P7 dev
    text if generated, else the dev key's facts (patient voice)."""
    import interview
    import protocol as protocol_mod
    protocol = protocol_mod.load(allow_unreviewed=True)
    keys = json.loads(KEY_FILES["dev"].read_text(encoding="utf-8"))["keys"]
    gen_path = out_dir("dev") / "generated_dev.json"
    gen = json.loads(gen_path.read_text(encoding="utf-8"))["cases"] if gen_path.exists() else {}
    reached = [k for k in keys if reached_chat(k["symptoms"])][:SMOKE_B_CASES]
    chat_q = [q for q in protocol.questions if q.input == "chat"]
    fields = [f for q in chat_q for f in q.fields]
    schema = interview.evidence_schema(fields)
    mode = "enforced"
    first_text = (gen.get(reached[0]["id"]) or {}).get("text") or " ".join(reached[0]["facts"])
    try:
        b_extract(transcript("triage", {"patient_words": first_text}, protocol)[0], schema,
                  post=post, sleep=sleep, key=key, schema_mode="enforced")
    except SchemaRefused as exc:
        mode = "json_only"
        print(f"schema mode for this run: json_only ({exc}); every call validates locally")
    calls, ok = [], True
    for k in reached:
        text = (gen.get(k["id"]) or {}).get("text") or " ".join(k["facts"])
        messages, _ = transcript("triage", {"patient_words": text}, protocol)
        raw, record = b_extract(messages, schema, post=post, sleep=sleep, key=key, schema_mode=mode)
        passed = (record["valid"] and record.get("model_version")
                  and record.get("finish_reason") == "STOP" and not record.get("thought_parts"))
        ok &= bool(passed)
        calls.append({"id": k["id"], "source": "p7" if gen.get(k["id"]) else "facts",
                      "passed": bool(passed), "record": record,
                      "values": {f: (raw.get(f) or {}).get("value") for f in fields}})
        print(f"{k['id']}: {'pass' if passed else 'FAIL'}; model {record['requested_model']}, "
              f"version {record.get('model_version')}, finish {record.get('finish_reason')}, "
              f"schema mode {record['schema_mode']}, thought parts {record.get('thought_parts')}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "smoke_b.json").write_text(json.dumps({"model": MODEL_B, "passed": ok, "schema_mode": mode,
                                                  "calls": calls}, indent=1), encoding="utf-8")
    print(f"model B smoke test: {'PASSED' if ok else 'FAILED'} on {len(calls)} dev texts; "
          f"schema mode for runs: {mode}")
    return 0 if ok else 1


def smoke_b_passed() -> bool:
    return smoke_b_mode() is not None


def smoke_b_mode():
    """The schema mode the passed smoke test established, or None."""
    path = OUT / "smoke_b.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    ok = bool(data.get("passed")) and data.get("model") == MODEL_B
    return data.get("schema_mode", "enforced") if ok else None


def thinking_off(message: dict) -> bool:
    """No reasoning anywhere: no thinking field, and the content is the JSON
    object alone, with no text before or after it."""
    content = (message.get("content") or "").strip()
    if (message.get("thinking") or "").strip() or not content.startswith("{"):
        return False
    try:
        json.loads(content)
    except json.JSONDecodeError:
        return False
    return True


def sends_think(model: str) -> bool:
    smoke = OUT / "smoke.json"
    if not smoke.exists():
        raise SystemExit("run `smoke` first")
    entry = json.loads(smoke.read_text(encoding="utf-8"))[model]
    if not entry.get("thinking_off"):
        raise SystemExit(f"{model}: the smoke test did not show thinking switched off; "
                         "research-pm decides before any run")
    return entry["send_think_false"]


def smoke(models=(GENERATOR,)) -> int:
    """Local models only (the generator, and the B fallback with --fallback);
    model B on the API has its own smoke test, smoke-b."""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "smoke.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for model in models:
        msgs = [{"role": "user", "content": 'Reply as JSON: {"ok": true}'}]
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
        entry = {"date": datetime.datetime.now().isoformat(timespec="seconds")}
        try:
            message = ollama(model, msgs, schema, 0.0, SEED, think=True, full=True)
            entry["send_think_false"] = True
        except RuntimeError as exc:
            entry["with_think_error"] = str(exc)
            if "think" not in str(exc).lower():
                print(f"{model}: FAILED {exc}")
                result[model] = entry
                continue
            message = ollama(model, msgs, schema, 0.0, SEED, think=False, full=True)
            entry["send_think_false"] = False
        entry["reply"] = message.get("content")
        entry["thinking"] = message.get("thinking")
        entry["thinking_off"] = thinking_off(message)
        result[model] = entry
        print(f"{model}: \"think\": false "
              f"{'accepted' if entry['send_think_false'] else 'REJECTED, key dropped in this harness'}; "
              f"thinking {'off' if entry['thinking_off'] else 'NOT OFF: stop and tell research-pm'}; "
              f"reply {entry['reply']!r}")
    path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0 if all(result.get(m, {}).get("thinking_off") for m in models) else 1


# --- Generation -----------------------------------------------------------------------

def template(kind: str) -> str:
    """The dev keys use the triage-level template."""
    return "e2e" if kind == "e2e" else "triage"


def _stability() -> dict:
    import check_triage
    return {"triage": set(check_triage.HELDOUT_STABILITY_IDS)}


def run_order(keys: list, seed: int = SEED) -> list:
    """Grouped by style, shuffled within each group (never by level)."""
    rng = random.Random(seed)
    order = []
    for style in sorted({k["style"] for k in keys}):
        group = [k["id"] for k in keys if k["style"] == style]
        rng.shuffle(group)
        order += group
    return order


def _load(kind: str):
    import protocol as protocol_mod
    import explain
    import interview
    keys = json.loads(KEY_FILES[kind].read_text(encoding="utf-8"))["keys"]
    rewrites = json.loads(REWRITES.read_text(encoding="utf-8"))
    protocol = protocol_mod.load(allow_unreviewed=True)
    checker = Checker(protocol, interview.SCHEMA, explain.GUARDRAILS[0:3])
    return keys, rewrites, protocol, checker


def _save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def generate(kind: str, dry_run: bool = False, limit: int = None) -> int:
    keys, rewrites, protocol, checker = _load(kind)
    by_id = {k["id"]: k for k in keys}
    order = run_order(keys, SEEDS[kind])[:limit] if limit else run_order(keys, SEEDS[kind])
    stability = _stability().get(kind, set())
    prompts = {i: build_prompt(by_id[i], template(kind), rewrites) for i in order}
    leaked = {i: leaks(p["user"], by_id[i], checker.criterion_ids) for i, p in prompts.items()}
    leaked = {i: v for i, v in leaked.items() if v}
    if leaked:
        print(f"REFUSED: prompts name the answer: {leaked}")
        return 1
    if dry_run:
        for i in order:
            print(f"--- {i}\n{prompts[i]['user']}\n")
        print(f"{len(order)} prompts, 0 leaks")
        return 0

    out_dir(kind).mkdir(parents=True, exist_ok=True)
    path = out_dir(kind) / f"generated_{kind}.json"
    seed_base = SEEDS[kind]
    out = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "model": GENERATOR, "temperature": TEMPERATURE, "seed_base": seed_base,
        "key_file": KEY_FILES[kind].name, "key_sha256": _sha(KEY_FILES[kind]),
        "system_sha256": hashlib.sha256(SYSTEM_MESSAGE.encode()).hexdigest(),
        "think_sent": sends_think(GENERATOR), "order": order,
        "stability_ids": sorted(stability), "cases": {}}
    if out["key_sha256"] != _sha(KEY_FILES[kind]):
        raise SystemExit("the key file changed since this generation started")
    accepted_by_archetype = {}
    for i, case in out["cases"].items():
        if case["status"] == "accepted":
            accepted_by_archetype.setdefault(by_id[i]["archetype"], []).append((i, case["text"]))
    think = out["think_sent"]
    call = lambda messages, schema, seed: ollama(GENERATOR, messages, schema, TEMPERATURE, seed, think)  # noqa: E731
    for n, cid in enumerate(order, 1):
        if cid in out["cases"]:
            continue
        key, prompt = by_id[cid], prompts[cid]
        others = [(f"near-duplicate of {o}", t) for o, t in accepted_by_archetype.get(key["archetype"], [])]
        case = generate_one(call, prompt, template(kind), checker, seed_base, others)
        case.update(style=key["style"], reached_chat=prompt["reached"])
        if case["status"] == "accepted" and cid in stability:
            case["paraphrases"] = []
            for p in (1, 2):
                versus = [("near-copy of its own text", case["text"])] + [
                    (f"near-copy of paraphrase {i}", q["text"])
                    for i, q in enumerate(case["paraphrases"], 1) if q["text"]]
                para = generate_one(call, prompt, template(kind), checker,
                                    seed_base + PARAPHRASE_SEED_STEP * p, versus)
                case["paraphrases"].append(para)
            if any(q["status"] != "accepted" for q in case["paraphrases"]):
                case["status"] = "needs_research_pm"
        out["cases"][cid] = case
        if case["status"] == "accepted":
            accepted_by_archetype.setdefault(key["archetype"], []).append((cid, case["text"]))
        _save(path, out)
        print(f"{n:3d}/{len(order)} {cid} {case['status']} after {case['attempts']} attempt(s)"
              + (f"  {case['history'][0]['failures']}" if case["attempts"] > 1 else "")
              + (f"  paraphrases {[q['attempts'] for q in case['paraphrases']]}"
                 if case.get("paraphrases") else ""))
    return report_generation(out)


MAX_ADJUDICATION_ROUNDS = 2


def regenerate_cases(gen: dict, extracted: dict, ids: list, by_id: dict, prompts: dict, checker,
                     call, kind: str) -> dict:
    """Regenerate the texts research-pm's adjudication listed (never on a
    disagreement by itself). `ids` are case ids, or 'ID:p1' / 'ID:p2' for one
    paraphrase. Each continues its own seed sequence (next seed after the
    attempts already used), passes every §5 check again, and has its model B
    entry cleared so extract re-reads only these. The old text and its B
    responses are kept under 'superseded'. At most MAX_ADJUDICATION_ROUNDS."""
    done, refused = [], []
    base = SEEDS[kind]
    for item in ids:
        cid, _, part = item.partition(":")
        case = gen["cases"].get(cid)
        if case is None:
            refused.append((item, "not generated"))
            continue
        rounds = case.get("adjudication_rounds", 0)
        if rounds >= MAX_ADJUDICATION_ROUNDS:
            refused.append((item, f"already {rounds} adjudication rounds"))
            continue
        key, prompt = by_id[cid], prompts[cid]
        others = [(f"near-duplicate of {o}", c["text"]) for o, c in gen["cases"].items()
                  if o != cid and c.get("status") == "accepted"
                  and by_id[o]["archetype"] == key["archetype"]]
        old_b = (extracted.get("cases") or {}).pop(cid, None)
        if part in ("p1", "p2"):
            p = int(part[1])
            old = case["paraphrases"][p - 1]
            versus = [("near-copy of its own text", case["text"])] + [
                (f"near-copy of paraphrase {i}", q["text"])
                for i, q in enumerate(case["paraphrases"], 1) if i != p and q["text"]]
            seed = base + PARAPHRASE_SEED_STEP * p + len(old["history"])
            new = generate_one(call, prompt, template(kind), checker, seed, versus)
            case["paraphrases"][p - 1] = new
        else:
            old = {k: case[k] for k in ("reply", "text", "history", "attempts", "status")}
            seed = base + len(case["history"])
            new = generate_one(call, prompt, template(kind), checker, seed, others)
            case.update({k: new[k] for k in ("reply", "text", "history", "attempts", "status",
                                              "regeneration_reasons", "advisory")})
        case.setdefault("superseded", []).append({"part": part or "text", "round": rounds + 1,
                                                  "text": old, "b": old_b})
        case["adjudication_rounds"] = rounds + 1
        text_ok = not case["history"][-1]["failures"]
        paras_ok = all(q["status"] == "accepted" for q in case.get("paraphrases", []))
        case["status"] = "accepted" if text_ok and paras_ok else "needs_research_pm"
        done.append((item, case["status"], seed))
    return {"done": done, "refused": refused}


def regenerate(kind: str, ids_file: str) -> int:
    ids = json.loads(Path(ids_file).read_text(encoding="utf-8"))
    keys, rewrites, protocol, checker = _load(kind)
    by_id = {k["id"]: k for k in keys}
    prompts = {i: build_prompt(by_id[i], template(kind), rewrites) for i in {x.split(":")[0] for x in ids}
               if i in by_id}
    gen_path = out_dir(kind) / f"generated_{kind}.json"
    ext_path = out_dir(kind) / f"extracted_{kind}.json"
    gen = json.loads(gen_path.read_text(encoding="utf-8"))
    extracted = json.loads(ext_path.read_text(encoding="utf-8")) if ext_path.exists() else {"cases": {}}
    think = gen["think_sent"]
    call = lambda messages, schema, seed: ollama(GENERATOR, messages, schema, TEMPERATURE, seed, think)  # noqa: E731
    result = regenerate_cases(gen, extracted, ids, by_id, prompts, checker, call, kind)
    _save(gen_path, gen)
    if ext_path.exists():
        _save(ext_path, extracted)
    for item, status, seed in result["done"]:
        print(f"regenerated {item}: {status} (from seed {seed})")
    for item, why in result["refused"]:
        print(f"REFUSED {item}: {why}")
    print("next: extract --file", kind, "(re-reads only the regenerated cases)")
    return 1 if result["refused"] else 0


def generate_one(call, prompt: dict, tmpl: str, checker, seed_base: int, versus: list) -> dict:
    """Attempts 0..MAX_ATTEMPT with seed seed_base + attempt; every §5 check,
    plus token Jaccard > JACCARD_MAX against each (label, text) in versus."""
    messages = [{"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": prompt["user"]}]
    attempts = []
    for attempt in range(MAX_ATTEMPT + 1):
        seed = seed_base + attempt
        raw = call(messages, prompt["schema"], seed)
        try:
            reply = json.loads(raw)
            jsonschema.validate(reply, prompt["schema"])
            failures = check_reply(reply, prompt, tmpl, checker)
        except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
            reply, failures = None, [f"bad reply: {str(exc)[:120]}"]
        if reply is not None:
            for label, text in versus:
                j = jaccard(reply_text(reply), text)
                if j > JACCARD_MAX:
                    failures.append(f"{label} (Jaccard {j:.2f})")
        attempts.append({"attempt": attempt, "seed": seed, "reply": reply,
                         "raw": raw if reply is None else None, "failures": failures})
        if not failures:
            break
    last = attempts[-1]
    return {"status": "needs_research_pm" if last["failures"] else "accepted",
            "attempts": len(attempts),
            "regeneration_reasons": [a["failures"] for a in attempts if a["failures"]],
            "reply": last["reply"], "text": reply_text(last["reply"]) if last["reply"] else None,
            "history": attempts,
            "advisory": advisory(reply_text(last["reply"])) if last["reply"] else []}


def report_generation(out: dict) -> int:
    cases = list(out["cases"].values())
    status = Counter(c["status"] for c in cases)
    texts = cases + [p for c in cases for p in c.get("paraphrases", [])]
    regen = sum(c["attempts"] > 1 for c in texts)
    more = sum(c["attempts"] > 2 for c in texts)
    reasons = Counter(re.sub(r"[ '\[(].*", "", f.split(": ")[-1])
                      for c in texts for fs in c["regeneration_reasons"] for f in fs)
    n_para = sum(len(c.get("paraphrases", [])) for c in cases)
    print(f"\n{len(cases)} cases ({n_para} paraphrases): {dict(status)}; of {len(texts)} texts, "
          f"needed a regeneration {regen}, more than one {more}; failure labels {dict(reasons)}; "
          f"advisory notes on {sum(bool(c['advisory']) for c in texts)} texts")
    return 0


# --- Blind extraction by model B (spec §6) ---------------------------------------------

def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def b_prompt_hash(fields: list) -> str:
    import interview
    blob = (interview.SYSTEM_PROMPT + "\n" + interview.EXTRACTION_INSTRUCTION + "\n"
            + json.dumps(interview.evidence_schema(fields), sort_keys=True))
    return hashlib.sha256(blob.encode()).hexdigest()


def transcript(tmpl: str, reply: dict, protocol) -> tuple:
    """(messages, replies as (question_id, text)) as the production extraction sees them."""
    import interview
    messages = [{"role": "system", "content": interview.SYSTEM_PROMPT}]
    replies = []
    if tmpl == "triage":
        messages.append({"role": "user", "content": reply["patient_words"]})
        replies.append((None, reply["patient_words"]))
    else:
        messages.append({"role": "user", "content": reply["opening"]})
        replies.append((None, reply["opening"]))
        text = {q.id: q.text for q in protocol.questions}
        for q in CHAT_QUESTIONS:
            if q in reply["script"]:
                messages += [{"role": "assistant", "content": text[q]},
                             {"role": "user", "content": reply["script"][q]}]
                replies.append((q, reply["script"][q]))
    messages.append({"role": "user", "content": interview.EXTRACTION_INSTRUCTION})
    return messages, replies


def verified(raw: dict, fields: list, replies: list, asked_for: dict) -> dict:
    """interview.extract()'s evidence check, field by field."""
    import interview
    out = {}
    for field in fields:
        entry = raw.get(field) or {}
        value, quote = entry.get("value"), entry.get("quote")
        sources = [(qid, text) for qid, text in replies
                   if interview._normalize(quote) and interview._normalize(quote) in interview._normalize(text)]
        out[field] = interview.verify(field, value, quote, sources, asked_for.get(field))
    return out


def disagreement(field: str, key_value, b_value, schema: dict):
    """None if B agrees with the key, else the kind of disagreement."""
    if b_value is not None:
        try:
            jsonschema.validate(b_value, schema)
        except jsonschema.ValidationError:
            return "value the schema does not allow"
    if key_value is None and b_value is None:
        return None
    if key_value is None:
        return "B has a value, key null"
    if b_value is None:
        return "B null, key has a value"
    if field == "pain_triggers":
        return None if set(key_value) == set(b_value) else "different value"
    if field == "duration_days" and key_value == 30 and 28 <= b_value <= 31:
        return None if b_value == 30 else "about a month: research-pm adjudicates"
    return None if key_value == b_value else "different value"


def extract(kind: str, backend: str = "gemini", allow_pending: bool = False) -> int:
    """allow_pending: read the accepted cases now and leave the ones waiting for
    research-pm; a later run adds them (same model and schema mode, by id)."""
    import interview
    keys, _, protocol, _ = _load(kind)
    by_id = {k["id"]: k for k in keys}
    gen_path = out_dir(kind) / f"generated_{kind}.json"
    gen = json.loads(gen_path.read_text(encoding="utf-8"))
    pending = [i for i, c in gen["cases"].items() if c["status"] != "accepted"]
    if len(gen["cases"]) != len(keys) or (pending and not allow_pending):
        print(f"REFUSED: generation not finished ({len(gen['cases'])}/{len(keys)} cases, "
              f"{len(pending)} waiting for research-pm; --allow-pending reads the accepted ones now)")
        return 1
    if pending:
        print(f"{len(pending)} cases wait for research-pm and are left for a later run: {pending}")
    chat_q = [q for q in protocol.questions if q.input == "chat"]
    fields = [f for q in chat_q for f in q.fields]
    asked_for = {f: q.id for q in chat_q for f in q.fields}
    schema = interview.evidence_schema(fields)
    path = out_dir(kind) / f"extracted_{kind}.json"
    prompt_hash = b_prompt_hash(fields)
    model = B_MODELS[backend]
    if backend == "gemini" and not smoke_b_passed():
        print(f"REFUSED: the model B smoke test ({MODEL_B}) has not passed; run `smoke-b` first")
        return 1
    if backend == "ollama":
        sends_think(MODEL_B_FALLBACK)   # refuses unless `smoke --fallback` showed thinking off
    mode = smoke_b_mode() if backend == "gemini" else "enforced"
    out = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "model": model, "backend": backend, "temperature": 0.0, "schema_mode": mode,
        "schema_translation": SCHEMA_TRANSLATION,
        "prompt_sha256": prompt_hash, "interview_py_sha256": _sha(REPO_ROOT / "src" / "interview.py"),
        "fields": fields, "cases": {}}
    if out["model"] != model:
        print(f"REFUSED: {path.name} already holds {out['model']} output; one set is never mixed "
              f"across models. Move that file aside and re-run the whole set on {model}.")
        return 1
    if out["prompt_sha256"] != prompt_hash:
        raise SystemExit("the production extraction prompt changed mid-run; start a new run")
    if out.get("schema_mode", "enforced") != mode:
        print(f"REFUSED: {path.name} was run with schema mode {out.get('schema_mode')}, the smoke "
              f"test now says {mode}; one set never mixes the two. Tell research-pm.")
        return 1

    def check(key, reply):
        messages, replies = transcript(template(kind), reply, protocol)
        try:
            _, record = b_extract(messages, schema, backend=backend, schema_mode=mode)
        except SchemaRefused as exc:
            _save(path, out)
            raise SystemExit(f"STOPPED: an enforced-schema call was refused mid-run ({exc}). "
                             "Nothing falls through; tell research-pm.")
        return score_b(key, record, replies, fields, asked_for), record

    for n, cid in enumerate(gen["order"], 1):
        key = by_id[cid]
        if cid in out["cases"] or cid in pending:
            continue
        if not reached_chat(key["symptoms"]):
            out["cases"][cid] = {"reached_chat": False}
            continue
        case = gen["cases"][cid]
        rows, record = check(key, case["reply"])
        versions = out.setdefault("model_versions", [])
        if record.get("model_version") and record["model_version"] not in versions:
            versions.append(record["model_version"])
            if len(versions) > 1:
                print(f"WARNING: B's model version changed mid-run: {versions}")
        entry = {"reached_chat": True, "fields": rows, "b_call": record}
        if case.get("paraphrases"):
            checked = [check(key, p["reply"]) for p in case["paraphrases"]]
            entry["paraphrases"] = [r for r, _ in checked]
            entry["paraphrase_calls"] = [c for _, c in checked]
        out["cases"][cid] = entry
        _save(path, out)
        bad = [f for f, r in entry["fields"].items() if r["disagreement"]]
        bad_p = [f for rows in entry.get("paraphrases", []) for f, r in rows.items() if r["disagreement"]]
        print(f"{n:3d}/{len(gen['order'])} {cid} " + (f"disagree {bad}" if bad else "agree")
              + (f"; paraphrases disagree {bad_p}" if bad_p else ""))
    _save(path, out)
    return report_extraction(out)


def score_b(key: dict, record: dict, replies: list, fields: list, asked_for: dict) -> dict:
    """§6 rows for one B call, computed from the stored parsed reply only."""
    import interview
    raw = record.get("parsed") or {}
    b = verified(raw, fields, replies, asked_for)
    return {f: {"key": key["symptoms"].get(f), "b": b[f],
                "b_raw": (raw.get(f) or {}).get("value"), "quote": (raw.get(f) or {}).get("quote"),
                "disagreement": ("B reply invalid" if not record.get("valid") else
                                 disagreement(f, key["symptoms"].get(f), b[f],
                                              interview.SCHEMA["properties"][f]))}
            for f in fields}


def rescore(kind: str) -> int:
    """§6 recomputed from the stored B responses, with no model call."""
    keys, _, protocol, _ = _load(kind)
    by_id = {k["id"]: k for k in keys}
    gen = json.loads((out_dir(kind) / f"generated_{kind}.json").read_text(encoding="utf-8"))
    path = out_dir(kind) / f"extracted_{kind}.json"
    out = json.loads(path.read_text(encoding="utf-8"))
    chat_q = [q for q in protocol.questions if q.input == "chat"]
    fields = [f for q in chat_q for f in q.fields]
    asked_for = {f: q.id for q in chat_q for f in q.fields}
    changed = 0
    for cid, entry in out["cases"].items():
        if not entry.get("reached_chat"):
            continue
        case = gen["cases"][cid]
        _, replies = transcript(template(kind), case["reply"], protocol)
        rows = score_b(by_id[cid], entry["b_call"], replies, fields, asked_for)
        changed += rows != entry["fields"]
        entry["fields"] = rows
        for i, (p, call) in enumerate(zip(case.get("paraphrases", []), entry.get("paraphrase_calls", []))):
            _, preplies = transcript(template(kind), p["reply"], protocol)
            entry["paraphrases"][i] = score_b(by_id[cid], call, preplies, fields, asked_for)
    _save(path, out)
    print(f"rescored {path.name} from stored responses; {changed} cases changed")
    return report_extraction(out)


def report_extraction(out: dict) -> int:
    scored = [c for c in out["cases"].values() if c["reached_chat"]]
    fields = out["fields"]
    print(f"\nmodel B {out['model']}, prompt {out['prompt_sha256'][:12]}; "
          f"{len(scored)} cases reached the chat ({len(out['cases']) - len(scored)} not applicable)")
    total = 0
    for f in fields:
        kinds = Counter(c["fields"][f]["disagreement"] for c in scored if c["fields"][f]["disagreement"])
        n = sum(kinds.values())
        total += n
        print(f"  {f:<20} {n:3d}/{len(scored)} disagree  {dict(kinds)}")
    cells = len(scored) * len(fields)
    if cells:
        from check_triage import clopper_pearson
        lo, hi = clopper_pearson(total, cells)
        print(f"  all chat fields      {total}/{cells} = {total / cells:.1%} (exact 95% CI "
              f"{lo:.1%}-{hi:.1%}) before adjudication; research-pm's split into text wrong / "
              f"key wrong / ambiguous / B wrong decides the 2% residual bar and the 5% B-error rule")
        invalid = sum(any(r["disagreement"] == "B reply invalid" for r in c["fields"].values())
                      for c in scored)
        print(f"  B replies invalid    {invalid}/{len(scored)}; model versions "
              f"{out.get('model_versions')}; schema mode {out.get('schema_mode')}")
    else:
        print("  no scored cases")
    paras = [rows for c in scored for rows in c.get("paraphrases", [])]
    if paras:
        bad = sum(bool(r["disagreement"]) for rows in paras for r in rows.values())
        print(f"  paraphrases          {bad}/{len(paras) * len(fields)} chat-field cells disagree "
              f"over {len(paras)} paraphrases")
    return 0


# --- Write back ------------------------------------------------------------------------

def writeback(kind: str) -> int:
    gen = json.loads((out_dir(kind) / f"generated_{kind}.json").read_text(encoding="utf-8"))
    data = json.loads(KEY_FILES[kind].read_text(encoding="utf-8"))
    not_ready = [i for i, c in gen["cases"].items() if c["status"] != "accepted"]
    if not_ready or len(gen["cases"]) != len(data["keys"]):
        print(f"REFUSED: {len(not_ready)} cases not accepted, "
              f"{len(data['keys']) - len(gen['cases'])} not generated")
        return 1
    for key in data["keys"]:
        case = gen["cases"][key["id"]]
        reply = case["reply"]
        if template(kind) == "triage":
            key["patient_words"] = reply["patient_words"]
        else:
            key["opening"], key["script"] = reply["opening"], reply["script"]
        if case.get("paraphrases"):
            key["paraphrases"] = [p["reply"]["patient_words"] for p in case["paraphrases"]]
        key["p7"] = {"model": gen["model"], "attempts": case["attempts"]}
    _save(KEY_FILES[kind], data)
    print(f"wrote patient text into {KEY_FILES[kind].name} ({len(data['keys'])} keys)")
    if kind == "dev":
        print("next: python src/check_triage.py --cases labels/dev/triage_dev_keys.json "
              "--write-vignettes llm/eval/triage_vignettes_dev.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["smoke", "smoke-b", "generate", "extract", "rescore",
                                        "regenerate", "writeback", "report"])
    ap.add_argument("--ids", help="regenerate: JSON list of case ids from research-pm's "
                                  "adjudication ('ID' or 'ID:p1' / 'ID:p2')")
    ap.add_argument("--b-backend", choices=sorted(B_MODELS), default="gemini",
                    help="model B: the Gemini API, or the local gemma3:12b fallback (log a switch; "
                         "never mix the two within one set)")
    ap.add_argument("--fallback", action="store_true", help="smoke: also test the local B fallback")
    ap.add_argument("--allow-pending", action="store_true",
                    help="extract: read the accepted cases now, leave the ones waiting for research-pm")
    ap.add_argument("--file", choices=sorted(KEY_FILES), default="triage")
    ap.add_argument("--dry-run", action="store_true", help="print the prompts, call no model")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    if args.command == "smoke":
        return smoke((GENERATOR, MODEL_B_FALLBACK) if args.fallback else (GENERATOR,))
    if args.command == "rescore":
        return rescore(args.file)
    if args.command == "regenerate":
        if not args.ids:
            print("REFUSED: regenerate needs --ids (research-pm's list); disagreements alone never regenerate")
            return 1
        return regenerate(args.file, args.ids)
    if args.command == "smoke-b":
        return smoke_b()
    if args.command == "generate":
        return generate(args.file, args.dry_run, args.limit)
    if args.command == "extract":
        return extract(args.file, args.b_backend, args.allow_pending)
    if args.command == "writeback":
        return writeback(args.file)
    gen = out_dir(args.file) / f"generated_{args.file}.json"
    ext = out_dir(args.file) / f"extracted_{args.file}.json"
    if gen.exists():
        report_generation(json.loads(gen.read_text(encoding="utf-8")))
    if ext.exists():
        report_extraction(json.loads(ext.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
