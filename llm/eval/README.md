# Evaluation

Four tests. Only the last needs a human. Everything else is scripted, so
it can run on every change.

The core idea: because you build the test, you already know the right
answer. That is what lets you evaluate without a labelled clinical
dataset.

---

## Test 1 — Rule correctness (`rule_cases.json`)

Does `rules.py` produce the intended urgency?

Run each case through `assess()` and compare with `expected_urgency`.
Target: 100%. These are deterministic; any failure is a bug.

Then report the **safety direction**: of the disagreements against the
dentist's independent labels, how many were over-triage (safe) versus
under-triage (unsafe). The claim you want in the paper is that no case
was under-triaged.

Have your reviewing dentist label these cases blind, without seeing the
expected column, and report agreement separately from the code check.

---

## Test 2 — LLM faithfulness (`faithfulness_cases.json`)

Does the explanation say only what the JSON contains?

For each case, generate an explanation, then extract the tooth numbers
and conditions mentioned (regex on FDI numbers is enough) and compare
against the input.

Report three rates:

- **Hallucination rate** — teeth or conditions mentioned that are not in
  `findings`. Target 0%.
- **Omission rate** — findings present but never mentioned.
- **Contradiction rate** — urgency stated differs from
  `assessment.urgency`, or the text tells the user not to see a dentist.
  Target 0%.

Generate several hundred synthetic `findings` by script: vary the number
of teeth, missing teeth, confidence values, zero findings, many findings,
unassigned detections, unusable images. No photos needed.

---

## Test 3 — Symptom extraction (`symptom_dialogues.json`)

Does the model understand what the patient said?

Each case is a scripted dialogue plus the correct `symptoms` object.
Compare field by field and report per-field accuracy.

Pay attention to: vague answers, contradictions, mixed Chinese-English,
non-native phrasing, and unanswered questions that must come back `null`.
Guessing instead of `null` is the failure mode that matters most, because
a guessed red flag propagates straight into the urgency decision.

When you generate more dialogues with a large model, **write the answer
key first and the dialogue from it**, not the other way round.

---

## Test 4 — Explanation quality (human)

Sample 30 outputs spanning all urgency levels. A dentist or senior dental
student scores each 1–5 on clarity, medical correctness of wording,
appropriate hedging, and whether the referral advice is right.

Report mean and range per dimension, plus any free-text concerns.

---

## Cross-cutting: model size comparison

Run tests 2 and 3 at both your development model size and your target
embedded size. Report the gap. This is a genuine contribution for the
paper: it tells you whether on-device deployment is viable at all.

---

## Validating synthetic data (for the methods section)

Say plainly how the synthetic dialogues were checked:

1. Answer key written first, dialogue generated from it.
2. A second, different model extracted the fields blind; disagreements
   were reviewed by hand.
3. Code checks for impossible values and near-duplicates.
4. A manual read of 50 random cases, with the error rate reported.
5. A dentist reviewed 30 for realism.
6. A pilot with 10–20 real users, comparing real accuracy against
   synthetic accuracy.

Step 6 is the one that converts this from plausible to demonstrated. Even
20 real conversations is worth reporting.
