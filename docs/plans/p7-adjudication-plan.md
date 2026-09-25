# P7 — adjudication of model-B disagreements, and the 50-case read

research-pm's procedure for P7 spec §6 (adjudication) and §7 (human read).
Written 2026-09-24, **before any P7 output exists**; changes after outputs
arrive are logged as post-hoc in `docs/decisions.md`.

## 1. Inputs (from qa-engineer, `labels/heldout/p7/`; dev under `runs/p7/`)

- `generated_*.json`: final text per case, every attempt and the check that
  forced each regeneration.
- `extracted_*.json`: per case and chat field, the key value, B's raw and
  verified values, B's quote, and the disagreement flag, plus the schema
  mode and B's model version in the header.

Only chat fields of cases that reach the chat are scored (P7 prompt doc §2).

## 2. Order

1. **Dev** (100). Not blind-critical. It calibrates the procedure and shows
   whether B's error rate makes §6 informative at all (§5 below).
2. **Held-out triage-level** (200), then **end-to-end** (60), then the **40
   stability paraphrases**.

Each set is adjudicated completely before its regenerations go back to
qa-engineer, so no case is judged twice under different conditions.

## 3. Per disagreement: read the text first

To limit the key author's bias, every disagreement is read in two steps:

1. **Text first.** With the key value and B's value hidden, read the patient
   text and write down what it says for that field: a value, "not said", or
   "unclear". The adjudication sheet shows the text and the field name only.
2. **Then reveal** the key value, B's raw and verified value and B's quote,
   and choose exactly one outcome:

| Outcome | When | Action |
|---|---|---|
| **text wrong** | my reading ≠ key, and the text fails its brief (a fact missing, a null field answered, the wrong value said) | regenerate (next seed); the new text goes through every automatic check and B again |
| **key wrong** | the key contradicts its own facts or archetype (an authoring slip) | fix the key by the builder, re-run the protocol check, log the case and field in `decisions.md`. Never change a key to match the text. |
| **ambiguous** | the text fairly supports more than one value | keep, mark `ambiguous: true` on the case; reported separately, excluded from nothing |
| **B wrong** | my reading = key, and the text is clear; B misread it | keep the text; count as a B error |

"B wrong" is the fourth outcome §6 did not list; it is added here before any
output exists. A B misread on clear text says nothing about the text.

## 4. Limits on the loop

- At most **2 adjudication rounds** per case (the original text + 2
  regenerations). Still "text wrong" after that: research-pm may hand-edit
  the smallest span that fixes it, marked `hand_edited: true` and counted.
  The key author editing text is a threat, reported with the count.
- No case is dropped. A case with no acceptable text is reported as such, and
  the set is not used for Test 5 until it is resolved.
- A key fix that moves a level is a pre-scoring amendment in its own right.
  It is logged before Test 5 runs, and the builder check must still pass.

## 5. What gets reported (per set)

- Per chat field: disagreement rate **before** adjudication (n cells).
- Counts of each outcome: text wrong, key wrong, ambiguous, B wrong.
- **Residual text-attributable disagreement** = text still wrong after the
  loop + cells marked ambiguous, over all scored chat cells. **Bar: ≤ 2%**
  (spec §6). Above it, the text is not good enough and the run stops.
- **B error rate** = B wrong / scored cells, reported next to it. If it is
  above 5% on dev, B is too weak for the check to be informative: stop and
  report to the lead before held-out, with the documented gemma3:12b
  fallback as the option (the lead's and the user's call).
- The same residual computed without the B-wrong split, so a reader can see
  what the bar would have been under §6 as first written.
- **Added 2026-09-26, before any held-out text exists** (after dev; see
  `docs/decisions.md`):
  - The B-error rate and the residual are also shown **without
    `pain_severity`**. Nothing is excluded. The bar and the 5% rule are
    judged on the all-fields figures.
  - Hand-edited cells are reported both ways: as fixed, and as generator
    failures.

## 6. The 50-case human read (§7)

- **Sample:** 50 cases drawn at random from the 260 held-out cases (200
  triage + 60 end-to-end), `random.Random(20260924)`, after adjudication and
  all regenerations are final. Cases seen during adjudication are not
  removed; the overlap is reported.
- **Per case, one row:** facts all present (y/n), any fact contradicted
  (y/n), style rule kept (y/n), a null chat field answerable (y/n), protocol
  or level language outside a VERBATIM line (y/n), medicine name or dose
  (y/n). End-to-end cases: each script answer answers only its own question
  (y/n).
- **A case is an error** if any of: a fact missing, a fact contradicted, the
  style rule broken (spec §7), or a null field answerable, or level language
  outside a VERBATIM line. Reported as errors / 50 with an exact 95% CI,
  **as written, whatever it says**, plus the count for each reason.
- Not blind: I wrote the keys and read the facts beside the text. Stated in
  the methods.

## 7. Record

`labels/heldout/p7/adjudication.jsonl`, one line per disagreement: case id,
field, my text-first reading, key value, B raw and verified value, outcome,
one-line reason, round, date. `labels/heldout/p7/human_read.jsonl`, one line
per case read. Both gitignored with the rest of `labels/heldout/`; llm-dev
sees neither.

## 8. Time

Held-out chat cells: 420 triage (84 reached cases × 5) + 125 end-to-end
(25 × 5), plus the paraphrases. At a 5% disagreement rate, that is about 27
to adjudicate in the first round. The 50-case read takes about 2 h. No GPU.
