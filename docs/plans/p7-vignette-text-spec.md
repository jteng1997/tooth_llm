# P7 — writing patient words for the held-out keys

For qa-engineer, who runs it. Written by research-pm, 2026-09-23. The keys
exist (`labels/heldout/`, 200 triage-level + 60 end-to-end); what is missing is
the text a patient would actually have typed.

Why this needs care: the same text is scored by the system **and** read by a
dentist in Form B. Text that echoes our criteria makes the system look good
and the dentist agree with us for the wrong reason.

---

## 1. What to produce

| Key set | Field to add | Contents |
|---|---|---|
| `triage_heldout_keys.json` | `patient_words` (one string, 1–4 sentences) | What the patient typed in the free-text turns: the complaint plus anything the chat questions elicited. |
| `e2e_keys.json` | `script` (object: question id → answer string) plus `opening` | One answer per **chat** question the key expects (Q10, Q11, Q12, Q17, Q18), and an opening message. |

Checklist rows are clicks, not prose. Never write "I said yes to swelling".
The checklist answers already live in `symptoms`; the text must simply not
contradict them.

## 2. Rules for the text

1. **Never use protocol language.** No criterion ids, no statement wording, no
   level names (emergency, urgent, routine), no time frames as advice ("I need
   to be seen within 24 hours"). Patients describe, they do not triage.
2. **Never use field names.** Not "my pain lingers over 30 seconds" but "it
   keeps aching for a minute or so after". Not "pain_relief_effect: not
   helped" but "I took something for it and it didn't touch it".
3. **Say everything the non-null chat fields need, and nothing about the
   others.** If `duration_days` is null in the key, the text must not mention
   how long it has been going on. A field the key says is unanswered must stay
   unanswerable from the text — that is what makes the null case meaningful.
4. **Carry every item in `facts`.** They are the clinical substance; the style
   changes the wrapping, never the content.
5. **No diagnosis terms a patient would not use.** "Abscess" and "gum boil"
   are fine; "irreversible pulpitis", "symptomatic apical periodontitis" are
   not.
6. **No medicine names or doses**, even where a real patient might write one.
   They would trip the guardrail checks downstream and confuse the measurement.
7. **Length:** 15–90 words for `patient_words`; 3–40 for a scripted answer.

## 3. Styles

Each key already carries one of six styles. What each must still preserve:

| Style | What it means | Still true |
|---|---|---|
| `plain` | ordinary clear English | all facts present |
| `vague` | hedged, imprecise ("sort of", "I think") | the fact is recoverable, just softened |
| `non_native` | non-native English: simple tenses, dropped articles, word order slips | no invented dialect, no mockery |
| `self_correcting` | says one thing, corrects it ("three days — no, since Monday") | the **later** statement matches the key |
| `verbose` | long, with irrelevant life detail | irrelevant detail never contradicts a field |
| `terse` | a few words, no punctuation | facts present even if bare |

The injection cases carry their injection line verbatim from `facts`; it goes
in unchanged and must read as the patient typed it.

## 4. Generation

- Local model, one heavy job at a time. Use a model **other than the one under
  test** where possible; if that is not practical, record which model wrote the
  text, because it is a threat to the result either way.
- Temperature 0.7–0.9 for variety, fixed seed, one pass per key, results
  written back into the key files.
- The prompt gets: `facts`, the non-null chat fields with their values, and the
  style. It does **not** get the level, the criteria ids, the archetype name,
  or any protocol text. Nothing that names the answer goes into the prompt.
- Generate in batches by style, not by level, so the model cannot infer the
  level from its neighbours.

## 5. Automatic checks (code, before any human looks)

Reject and regenerate on any of these:

1. A criterion id, a level name, a protocol statement (≥ 5 consecutive words
   shared with any `statement` in the YAML), or a symptom field name appears.
2. A field the key marks null is answerable from the text. Checked by the
   blind extraction in §6, not by regex.
3. Length outside the bounds in §2.7.
4. Near-duplicate of another case: token Jaccard > 0.8 within the same
   archetype.
5. A medicine name or dose pattern (same lists as the guardrail check).

Report how many keys needed a regeneration, and how many needed more than one.

## 6. Blind second-model extraction

**Purpose.** Prove the text says what the key says, without asking the system
under test to mark its own homework.

- **Model B:** a different family from both the generator and the system under
  test. gemma3:12b or llama3.1:8b; record which. (Chosen: gemma4:12b, user's
  decision 2026-09-23; see `docs/decisions.md`.)
- **Input:** the text only — no key, no fields, no protocol.
- **Prompt:** the production extraction prompt, unchanged.
- **Compare:** only the **chat** fields (Q10, Q11, Q12, Q17, Q18 and their
  key values). Checklist fields are clicks and are not in the text.

**A disagreement is any of:**
- B returns a value where the key says null, or null where the key has a value;
- B returns a different value (for `pain_triggers`, compare as sets; order and
  duplicates do not count);
- B returns a value the schema does not allow.

**Adjudication is research-pm's, case by case**, reading the text and the key:
- text wrong → regenerate that case;
- key wrong → fix the key and log the change in `docs/decisions.md`;
- text fair but genuinely ambiguous → keep, and mark the case `ambiguous:
  true`; these are reported separately and excluded from nothing.

**Report:** per-field disagreement rate before adjudication, the counts of each
adjudication outcome, and the residual rate after. Bar for using the set:
residual disagreement ≤ 2% of chat fields. Above that, the text generation is
not good enough and the run stops.

## 7. Human read

research-pm reads 50 cases at random and reports the error rate (a case is an
error if a fact is missing, contradicted, or the style rule is broken). This
is reported in the methods section as written, whatever it says.

## 8. Access

The key files stay out of git (`labels/heldout/` is gitignored). qa-engineer
runs the generation; llm-dev does not see the outputs. Generated text never
goes into the dev set, prompts or few-shot examples.
