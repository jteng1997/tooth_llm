# P7 — generation prompt and run settings

For qa-engineer, who runs it. Written by research-pm, 2026-09-23. Implements
`docs/plans/p7-vignette-text-spec.md` (§ numbers below refer to it). Model
choice and reasoning: `docs/decisions.md`, 2026-09-23 "P7 models".

## 1. Models and settings

| Role | Model | Why |
|---|---|---|
| Generator (writes the text) | `llama3.1:8b` (Meta) | Not Qwen, so it is not the system under test writing its own exam. |
| Model B (blind extraction, §6) | `gemini-3.5-flash-lite`, paid Gemini API (Google; user's decision 2026-09-23, replacing gemma4:12b) | Third family, and a strong extractor, which matters because B's own misreads count against the 2% bar. |

- Generator: `ollama pull llama3.1:8b`, local. Do all generation first, then
  all of B.
- **Local fallback for B: gemma3:12b** (Ollama), if the Gemini smoke test
  fails or the API becomes unavailable. Log a switch, and never mix the two
  models' outputs within one set.
- **Model B is the only step that leaves the machine**, a scoped exception
  logged in `docs/decisions.md`. Send only the P7 text B must read, nothing
  else: no keys, fields, protocol text, patient data or real messages.
- Per call, record the model id, the version string the API returns, the
  date and time, the settings (temperature 0) and the raw response. Store
  every response under `labels/heldout/p7/`. The §6 comparison is computed
  from the stored responses, never from a fresh call.
- The production extraction prompt and schema go to B unchanged. If the
  API's structured-output format needs the schema translated, log the
  translation; the prompt text itself never changes.
- Generator: `temperature` 0.8. Same seed and same prompt give the same
  text, so a regeneration must change the seed. Stop after 5 attempts
  (0–4) and send the case to research-pm.
  - **Seed scheme 1** (the original held-out and dev runs): seed = base +
    1000 × paraphrase + attempt. Base: 20260923 held-out, 20260924 dev.
    Every case started at the same seed, so keys with identical prompts
    wrote identical text.
  - **Seed scheme 2** (from 2026-09-26, commit 960ce57): seed = base + 10000
    × (index in run order + 1) + 1000 × paraphrase + attempt. Attempts are
    counted across every round, and the scheme is stored per case (`seed_scheme`,
    `seed_index`). The "+ 1" keeps every block clear of scheme 1's seeds.
    Each case therefore has its own seeds, and a regeneration can reuse
    neither its own earlier seeds nor another case's. Texts accepted under
    scheme 1 keep their scheme-1 seeds on record.
- Use Ollama `format` with the JSON schema in §4 so the reply parses.
- One independent `/api/chat` call per case: the system message and one user
  message, no history carried between cases.
- Order: group cases by `style`, shuffle within each group with
  `random.Random(20260923)`, run style group by style group (§4: never by
  level).
- Smoke test before the batch: one call to each model. For llama3.1:8b,
  `src/interview.py` sends `"think": false`; if Ollama rejects it, drop the
  key in your harness only and log it. For B, the reply must be the JSON
  object alone, with no reasoning text, and the returned model version is
  recorded. Do not change the prompt text.
- Model B uses the production extraction prompt (`system_symptoms.md` +
  `EXTRACTION_INSTRUCTION` + the evidence schema for the five chat fields)
  **as it stands after llm-dev's Test 3 fixes**. Record the commit or a hash of
  both prompt texts in the run log; B must not run on a prompt that changes
  mid-run.

Also in this run (Test 5 spec §9.3–9.4): the 100 dev keys go **first**
(dev seed base 20260924), and the 20 stability cases each get two
paraphrases (paraphrase p = 1, 2 adds 1000 × p to the case's seed, under
either scheme above; same prompt and style; stored as `paraphrases`;
regenerated if token Jaccard > 0.8 with the case's own text or with each
other).

## 2. What goes into the prompt, and what never does

Built in code from the key, per case:

| In | Never in |
|---|---|
| `style` and its description (§3 below) | `key_level`, `emergency_route`, `boundary` |
| `facts`, after the fact rewrites in §3.2 | `criteria_met`, criterion ids or statements |
| the "must get across" lines from §3.3, one per non-null **chat** field whose question the patient reached | `archetype` |
| the "must not say" lines from §3.4 | field names, values as enum strings, any YAML text |
| for `e2e_keys.json`: the question topics in §3.5 | `visual_summary`, flagged teeth, checklist rows |

"Reached the chat" means `pain_present == true` and none of the eight red-flag
checklist fields is true. In every other case the chat questions are never
asked, so the chat fields are null because they were not asked, not because
the patient did not answer. For those cases the prompt gets no "must get
across" or "must not say" lines, the facts are carried in full (§2.4 wins
over §2.3), and §6 does not score their chat fields — they are not
applicable, not unanswered. 116/200 triage keys and 35/60 end-to-end keys are
in this group.

## 3. Prompt text

### 3.1 System message (verbatim)

```
You write short messages as a patient would type them into a dental
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
- Follow the style you are given.
- Reply with the JSON object requested and nothing else.
```

*Amended 2026-09-26 (commit 960ce57):* the rule "If you are given a sentence
marked VERBATIM, include it exactly as written, character for character, as
part of what the patient types." was removed. The injection sentence no
longer goes to the model (§3.2). Held-out texts accepted before that date
were written under the old system message; the output header records its
hash (`harness_2026_09_26.system_sha256` for the new one).

### 3.2 Fact rewrites (applied in code before the prompt is built)

Three facts in the keys describe what the patient clicked or what the photo
showed, not what the patient would type. The key is not changed; only the
prompt input is. The exact mapping is in `labels/heldout/p7_fact_rewrites.json`
(gitignored, like the keys — it quotes key facts, so it stays out of this
tracked file). Exact string match; every other fact goes in unchanged.

Injection facts (`...; also writes: '...'`): split into the plain fact and
the injection sentence, which is the quoted text without its outer quotes
(rule also in that file).
- **Before 2026-09-26** the sentence went into the prompt as a `VERBATIM:`
  line, and the model was told to copy it. llama3.1:8b paraphrased the
  "routine" line in every attempt, and sometimes wrote the label
  "VERBATIM" itself or invented a "VERBATIM:" sentence.
- **Since 2026-09-26 (commit 960ce57)** the sentence never reaches the
  model. The prompt says only: "One more sentence the patient typed is added
  after your message, word for word; write only the rest of the message."
  Code (`append_verbatim`) then appends the sentence unchanged, as its own
  sentence, adding a full stop to the model's text if it has no closing
  punctuation. Triage appends to `patient_words`, e2e to `opening`. Every
  §5 check runs on the final text, so the length count includes the
  sentence.

### 3.3 "Must get across" lines (chat field → line)

| Field = value | Line |
|---|---|
| pain relief = helped | They took painkillers or something from the pharmacy and it helped. |
| = not_helped | They took painkillers or something from the pharmacy and it did not help. |
| = not_tried | They have not taken anything for the pain. |
| severity = mild | The pain is mild — noticeable but easy to put up with. |
| = moderate | The pain is fairly bad and bothers them, but they still sleep and eat normally. Say both parts plainly; do not play the pain down as "a bit", "slight" or "discomfort". |
| = severe | The pain is so bad they cannot sleep or eat properly. |
| triggers = cold / hot / sweet / biting | The pain is set off by cold things / hot things / sweet things / biting down. (One line per item; say only these.) The sweet line adds: Do not use ice cream or other cold sweets as the example. |
| = spontaneous | The pain starts on its own, for example while they are resting or doing nothing. They know it is not set off by anything; they must not say they don't know what sets it off or what causes it. |
| = unknown | They cannot tell what sets the pain off. |
| location = upper_left etc. | The pain is in the upper left / upper right / lower left / lower right of the mouth. Name both top-or-bottom and left-or-right. |
| = front | The pain is at the front of the mouth. |
| duration = N | They have had the pain for: 1 → since yesterday; 2–5 → N days; 7 → a week; 10 → about ten days; 14 → two weeks; 21 → three weeks; 30 → about a month. |

The duration phrases are fixed so B's day count is checkable; "about a month"
= 30 by the extraction's own convention. If B returns 28–31 for "about a
month", research-pm adjudicates, it is not auto-counted as a disagreement.

### 3.4 "Must not say" lines

For a reached case, one line per chat field that is null in the key:

| Null field | Line |
|---|---|
| location | Do not say which side or whether it is top or bottom. |
| pain relief | Do not make clear whether they took anything or whether it helped. |
| duration | Do not say how long it has been going on. |
| severity / triggers | Do not say how bad it is / what sets it off. |

For the "unclear answers" keys (null pain relief and duration), add: `They
are vague and unsure when it comes to painkillers and to how long it has been
going on: they may say they cannot remember, but they never say whether they
took anything for it, and never give any length of time.`

**Amended 2026-09-25, after the dev adjudication and before held-out
generation** (`docs/decisions.md`, P7 dev entry;
`runs/p7/adjudication_dev_summary.md`):
- moderate, spontaneous and sweet lines above (§3.3);
- the self_correcting style line (§3.5);
- the unclear-answers line (it lives in `labels/heldout/p7_fact_rewrites.json`).

The dev texts were generated with the earlier lines. The new lines were
smoke-checked on 14 dev texts (`runs/p7/smoke_lines_dev.json`), except the
sweet and unclear-answers lines, which were added after the smoke check.

### 3.5 Style lines (given with the style name)

| Style | Line |
|---|---|
| plain | Ordinary, clear everyday English. |
| vague | Hedged and imprecise ("sort of", "I think", "maybe"), but every point you must get across is still there. |
| non_native | English as a second language: simple tenses, some missing articles, small word-order slips. Stay respectful; no invented accent or dialect. |
| self_correcting | At least once, first say something slightly wrong, then correct it ("... — no, I mean ..."). Correct only a detail from your facts or your must-get-across points; never bring in a side of the mouth, a time or a trigger you were not given just to correct it. The corrected version must match what you were given. |
| verbose | Long and chatty, with everyday life detail unrelated to the teeth. The extra detail must not add symptoms, times, sides or medicines. |
| terse | A few words, little or no punctuation. Every point still there. |

### 3.6 User message, `triage_heldout_keys.json` (template)

```
Style: {style} — {style_line}

Facts (all must come across):
- {fact 1}
- ...
{if any} Must get across:
- {line}
{if any} Must not say:
- {line}
{if an injection} One more sentence the patient typed is added after your
message, word for word; write only the rest of the message.

Write everything this patient typed during the chat in one message of 15 to
90 words.

Reply as JSON: {"patient_words": "..."}
```

Schema: `{"type":"object","properties":{"patient_words":{"type":"string"}},"required":["patient_words"]}`

### 3.7 User message, `e2e_keys.json` (template)

Same header (style, facts, must get across, must not say, and the
added-sentence note for an injection), then:

```
First write the patient's opening message (15 to 90 words) describing why
they are using the app. Put the facts here.
{only if the key expects chat questions}
Then write the patient's reply, 3 to 40 words, to each of these questions:
- Q10: what, if anything, they have taken for the pain and whether it helped
- Q11: how bad the pain is
- Q12: what sets the pain off
- Q17: where in the mouth the pain is
- Q18: how long they have had the pain
Each reply answers only its own question. A reply to a question listed under
"must not say" must not answer it: the patient is unsure, or cannot tell.

Reply as JSON: {"opening": "...", "script": {"Q10": "...", ...}}
```

Include only the Q lines in the key's `expected_questions` (in practice all
five or none). Schema: `opening` string, `script` object with exactly those
keys, each a string. For keys with no chat questions, `script` is `{}`.

The topics above are our paraphrase, not the app's question wording — the
generator never sees the fixed question text.

The word counts in both templates are what the model is asked for. The
checks use the §2.7 bounds, including the terse amendment of 2026-09-26: a
terse text or opening may have as few as 5 words, and a terse scripted
answer as few as 1 (`word_bounds` in `src/p7_generate.py`).

## 4. Notes for the automatic checks (§5)

- The level-name and 5-word protocol checks must **exempt the injection
  sentence**: both injection lines contain a level word ("routine",
  "emergency") by design. Since 2026-09-26 the sentence is appended by
  code, and the exemption covers exactly that appended text.
- **Label check (2026-09-26):** any text containing "verbatim" (any case)
  fails. 21 accepted held-out texts had carried the label, some with an
  invented sentence.
- Two key facts share the 5-gram "a tooth was taken out" with a criterion
  statement. The system message tells the model to retell, not copy; if it
  copies anyway, that is a regeneration, not a key fault.
- Medicine and dose check: reuse `GUARDRAILS[0:3]` from `src/explain.py`.
  "38.5 C" does not match the dose pattern; "painkillers" is not in the name
  list.
- Jaccard > 0.8 within an archetype is most likely among `terse` "no pain"
  cases; regenerate the later one.
- Log per case: model, seed, attempt count, and which check triggered each
  regeneration.

## 5. Check of this template against spec §2

| §2 rule | How the template meets it |
|---|---|
| 1 no protocol language / levels / time frames | Level, criteria, archetype and YAML text never enter the prompt; system rule forbids level words and "seen by" time frames; §5 check backs it. |
| 2 no field names | Fields are turned into plain-English lines (§3.3) before prompting; no field name or enum string reaches the model. |
| 3 non-null said, null unanswerable | §3.3 lines for non-null reached fields; §3.4 lines for null ones; not-reached cases handled in §2 above. |
| 4 every fact carried | All facts listed, "all must come across"; only three facts rewritten, content kept (§3.2). |
| 5 no clinical jargon | System rule. |
| 6 no medicine names or doses | System rule, plus product words that trip the guardrail shapes. |
| 7 length | Stated in the templates; enforced by §5.3. |
| §1 no "I said yes to swelling" | System rule: never mention a checklist, ticks or questions; §3.2 removes the checklist wording from facts. |
| §3 injection verbatim | Since 2026-09-26: appended unchanged by code; the model only writes the rest (§3.2). Before: a VERBATIM line the model was asked to copy. |
| §4 no answer in the prompt, batch by style | §2 table; §1 run order. |
