# Test results — all evaluations, as of 2026-09-30

Branch `llm-triage-wave2`. Final configuration: HEAD `edc268d`, protocol
v0.3 (`llm/protocol/triage_protocol.yaml`, sha256 `6f933104…`), `qwen3:14b`
through Ollama. `src/interview.py` `78f6c6e0…`, `src/triage.py` `7181e1a3…`,
`src/explain.py` `8d28d851…`.

This report lists every test: what it measures, its input data, its output
files, and its result. Numbers come from the run logs named in each section.
The deeper write-ups are `docs/reports/test5-heldout-2026-09-26.md` and
`docs/reports/system-report-2026-09-26.md`. Decisions behind the numbers are
in `docs/decisions.md`.

**Where outputs live.** `runs/` is local only and gitignored. Every output
path below is on the project machine, under `D:\jonathan\tooth-llm\runs\`.
Held-out data (`labels/heldout/`) is also gitignored. It is backed up in
`labels/heldout/wave2_backup_2026-09-26/`.

**Caveats that travel with every triage number.**
1. The numbers measure agreement with SDCEP as encoded in protocol v0.3,
   including the user's decisions. They are not a clinical validation, and
   no dentist has labelled anything yet.
2. The vignettes assume the photo findings are correct. The caries detector
   catches about 29% of carious photos at the current threshold, so accuracy
   on real patients is not measured here.
3. Every protocol criterion is decided by code. So on triage-level cases the
   final level is right by construction. The informative numbers are the
   model's own proposal (`llm_proposed`), extraction, and the end-to-end set.

---

## Summary

| # | Test | n | Headline result | Status |
|---|---|---|---|---|
| — | Unit test suite | 573 tests | 573 OK | green |
| 1 | Rules (`check_rules`) | 20 cases | 20/20 | green |
| 2 | Explanation faithfulness (`check_faithfulness`) | 8 fixed + 60 synthetic + 120 follow-ups | 0 invented / omitted / contradicted / misstated / unreported teeth | green |
| 3 | Symptom extraction (`check_symptoms`) | 12 dialogues, 60 fields | 12/12, 60/60, 0 guessed | green |
| 5 | Triage, dev (`check_triage`) | 101 scored of 106 | final 0 under-triage, 101/101 exact | PASS |
| 5 | Triage, held-out (v0.2, spent) | 200 + 60 e2e | final 0/200 and 0/60 under-triage | PASS (v0.2) |
| 5e | End-to-end, dev (`check_e2e`) | 45 cases | final 0 under-triage, 43/43 exact | green |
| — | Phrase sets (severity, relief) | 86 + 36 + 10 + 64 phrases | see §7; known severity gaps | open follow-up |
| — | Vision (segmentation, caries) | 4,929 photos | caries sensitivity 29% at 0.50 | open decision |

---

## Unit test suite

- **Command:** `.venv/Scripts/python -m unittest discover -s tests`
  (pytest is not installed).
- **Input:** `tests/` (mocked; no GPU and no Ollama).
- **Output:** console only.
- **Result (2026-09-30, final config):** **573 tests, OK.**

## Test 1 — rules (`src/check_rules.py`)

- **Measures:** that the legacy deterministic rules (`llm/rules.py`) give the
  expected level and rule id on hand-written findings and symptoms.
- **Input:** `llm/eval/rule_cases.json` (20 cases, C01–C20).
- **Output:** console only.
- **Result:** **20/20.**

## Test 2 — explanation faithfulness (`src/check_faithfulness.py`)

- **Measures:** whether the patient-facing explanation reports exactly the
  teeth in the findings and states the assessed urgency. The metrics:
  - hallucination: an invented tooth;
  - omission: a flagged tooth left out;
  - contradiction;
  - misstated: wrong urgency or wrong facts;
  - unreported: a sub-threshold detection reported as a finding.
  It also checks the photo-retake handling, the guardrails (retry, then
  fixed fallback text) and follow-up questions.
- **Input:**
  - `llm/eval/faithfulness_cases.json`: 8 hand-written cases, F01–F08
    (baseline, zero findings, low confidence only, many findings,
    restoration, retake, emergency, unassigned detection);
  - `--synthetic 60`: 60 seeded synthetic cases (S0000–S0059), each with 2
    follow-up questions (120 turns);
  - the knowledge base `llm/knowledge/` (DRAFT-UNREVIEWED; dev override).
- **Output:** `runs/evals/test2_dev_2026-09-30_capfix/`, holding
  `test2_dev.{json,log}` and `test2_dev_syn60.{json,log}`. The pre-cap run
  of the same morning is `runs/evals/test2_dev_2026-09-30/`, with
  `relief_and_unscoped.txt`.
- **Result (final config):**

| Metric | Fixed 8 | Synthetic 60 | Follow-ups 120 |
|---|---|---|---|
| hallucination (invented tooth) | 0/8 | 0/60 | 0/120 |
| omission | 0/8 | 0/60 | — |
| contradiction | 0/8 | 0/60 | — |
| misstated | 0/8 | 0/60 | 0/120 |
| unreported (sub-threshold tooth reported) | 0/8 | 0/60 | 0/120 |
| discourages care | — | — | 0/120 |
| retake not requested | 0/1 | 0/14 | — |
| unscoped absence | 0/1 | 1/14 (S0004) | — |
| guardrail retry / fallback text | 0/8 / 0/8 | 3/60 / 3/60 | 16/120 / 10/120 |

- The old problem, sub-threshold teeth reported as findings (7–11/60 before
  task #22), is at 0/60.
- **S0004:** "nothing was found on your lower teeth" names the lower arch
  and asks for the upper photo again. The checker flags it because the
  absence is not worded as covering only the usable photo. This is
  borderline wording, not a claim about unseen teeth.
- **Checker fix:** one follow-up "arch called fine" flag (S0027, "it
  doesn’t mean your teeth are completely fine") was a checker false
  positive: the negation list missed the curly apostrophe. After the fix,
  both runs rescore to 0/60 and 0/120. Side by side:
  `compare_morning_vs_capfix.txt`.
- **Pain-relief claims:** in the morning run, 4 texts say the relief did not
  help (S0026, S0058, S0059, and one S0058 follow-up). In the final-config
  run there are 3 (S0025, S0026, S0059). All four patients answered "not helped",
  so the claims are true. 10 cases had relief unanswered, which arms the
  relief guard; they made 0 relief claims in 30 texts. The guard never
  fired.
- **Output cap:** there were 0 "empty or cut off" refusals, so the new
  1024-token cap never bit. The results match the pre-cap run.

## Test 3 — symptom extraction (`src/check_symptoms.py`)

- **Measures:** whether the interview extracts the five chat fields
  correctly from scripted patient answers, with a verified quote and never a
  guess. The fields are pain_relief_effect, pain_severity, pain_triggers,
  location and duration_days.
- **Input:** `llm/eval/symptom_dialogues.json` (sha256 `6a86915b…`):
  - 12 headline dialogues: D01–D04 and D06–D13 (native and non-native
    English, self-correction, prompt injection, vague severity, several
    triggers, and so on);
  - 1 robustness dialogue, D05 (Chinese answers), outside the headline.
- **Output:** `runs/evals/test3_dev_2026-09-30_capfix/test3_dev_qwen3_14b.{json,log}`.
- **Result (final config):**
  - exact dialogues **12/12**;
  - fields **60/60** (95% CI 94.0–100%);
  - guessed field 0/12, missed field 0/12, invented list item 0/12;
  - checklist answers overwritten by prose: 0;
  - severity: false severe 0/10 and missed severe 0/10 (n is small, CI up to
    30.8%);
  - extraction truncated 0, unparsed 0;
  - D05 (robustness): 2/5 fields, 1 guessed. The English-only notice shows.

## Test 5 — triage level, dev set (`src/check_triage.py`)

- **Measures:** the triage level against answer keys built from the
  protocol. Four systems are scored:
  - `final`: what the patient sees;
  - `llm_proposed`: the model's own level, before code checks;
  - `protocol_check`: code only;
  - `rules`: the legacy baseline.
- **Input:**
  - `llm/eval/triage_vignettes_dev.json`: 106 dev vignettes, built from the
    keys `labels/dev/triage_dev_keys.json` (100 original plus V101–V106 for
    v0.3) and the synthetic patient text `runs/p7/generated_dev.json` (P7,
    Gemini, synthetic text only);
  - scoring scheme: `llm/eval/triage_vignettes.schema.json`.
- **Output:** `runs/evals/test5_dev_2026-09-30/`, holding
  `triage_dev_llm_qwen3_14b.{json,log}` and `triage_dev_rules.{json,log}`.
  The run log is `runs/evals/test5_runlog.jsonl`.
- **Result (n = 101 scored of 106; 5 are designed RETAKE):**

| System | Under-triage (95% CI) | Exact | Weighted κ |
|---|---|---|---|
| `final` | **0/101** (0.0–3.6%) | 101/101 | 1.000 |
| `protocol_check` | 0/101 | 106/106 agree | 1.000 |
| `llm_proposed` | 18/81 | — | — |
| `rules` (legacy) | 28/101 (19.3–37.5%) | 59/101 | 0.514 |

- **Pass bar** (0 under-triage and κ ≥ 0.8): `final` **PASS**; `rules` FAIL.
- **Model behaviour:**
  - 16/81 proposals stated a level below their own verified citations;
    code raised them (`llm_raised`);
  - 15 of the 18 under-triaged proposals were SOON proposed as ROUTINE;
  - fallback to rules 0/81, valid output 81/81, retried 36/81;
  - latency per triage call: p50 8.2 s, p95 14.5 s.
- `final` vs `rules`: exact McNemar p = 7.5 × 10⁻⁹.

## Test 5 — held-out set (protocol v0.2; spent, never re-run)

- **Input:** `labels/heldout/` (gitignored): 200 triage keys and 60
  end-to-end keys, with P7 text. They were scored once, on 2026-09-26,
  against the pinned `docs/plans/protocol-v0.2/triage_protocol.yaml`.
- **Output:** `labels/heldout/` (results). The report is
  `docs/reports/test5-heldout-2026-09-26.md`.
- **Result (v0.2):**

| System | n | Under-triage (95% CI) | Exact | κ |
|---|---|---|---|---|
| `final` | 200 | **0** (0.0–1.8%) | 200/200 | 1.000 |
| `llm_proposed` | 155 | 30 = 19.4% (13.5–26.5%) | 125/155 | 0.781 |
| `rules` | 200 | 51 = 25.5% | 139/200 | 0.595 |
| end-to-end `final`, drop / prepend | 60 / 60 | **0 / 0** (0.0–6.0%) | 60/60 | 1.000 |

- **Limitation:** under v0.3, 18/200 triage keys and 6/60 e2e keys would
  change level. The held-out set is not rescored, so v0.3 has no held-out
  number.

## Test 5e — end-to-end, dev set (`src/check_e2e.py`) — new 2026-09-30

- **Measures:** the whole chain on each case: checklist clicks, then the
  scripted chat through the real interview and extraction, then triage.
  Every miss is attributed to one of: interview, extraction, triage, or
  protocol gap.
- **Input:**
  - `labels/dev/e2e_dev_keys.json`: 45 cases (20 URGENT, 25 SOON), all dev
    cases that reach the chat. Built by `labels/dev/build_e2e_dev_keys.py`
    from `labels/dev/triage_dev_keys.json`. It is deterministic (sha256
    `7d8863b7…`) and uses no held-out content;
  - the script is **one whole P7 message per case**, used as the answer to
    every chat question. Held-out e2e has per-question answers, so the two
    sets are not comparable 1:1.
- **Output:** `runs/evals/e2e_dev_2026-09-30/e2e_dev.{json,log}`. The
  crashed first run (before the fix) is `e2e_dev_CRASHED_readtimeout.log`.
- **Result (opening dropped, as in production):**

| System | n | Under | Over | Exact | κ |
|---|---|---|---|---|---|
| `final` | 43 | **0** | 0 | 43/43 | 1.000 |
| `protocol_check` | 45 | 0 | 0 | 45/45 | 1.000 |
| `llm_proposed` | 45 | 12 | 0 | 33/45 | 0.638 |
| `rules` | 43 | 11 | 9 | 23/43 | 0.109 |

- **Misses:** 2, V039 and V080. Both are the designed RETAKE cases: both
  photos are unusable, so the result is RETAKE against a SOON key. They are
  attributed to triage by code and are not a fault.
- **Interview:**
  - questions never asked 0/45;
  - extra questions 0;
  - re-asks 38;
  - unscripted questions 0.
- **Extraction:**
  - 7/225 cells differ from the key (triggers 3, severity 2, relief 1,
    duration 1);
  - none changed the level;
  - truncated 0, unparsed 0.
- **Severity:**
  - false severe 1/45 (V082, "pretty bad");
  - missed severe 0/45 (0/6 of key severe);
  - level moved by a severity error: 0/2.
- **Model's own level:** 12/45 below the key, all raised in code to its own
  citations. Fallback to rules 0/45.
- **Latency per case** (interview + extraction + triage): p50 40 s, p95 76 s,
  max 82 s.
- **Bug found and fixed by this test:**
  - The first run hung at V068: the extractor wrote one sentence into
    `notes` without end (9,747 tokens, a 300 s timeout).
  - The fix: schema length limits (notes 300 characters, quotes 500), a
    1024-token output cap on every model call, and one retry on a
    truncated reply. After that, the field stays null, never a guess.
  - After the fix, V068 completes in 21 s at the correct level.

## Phrase sets — severity and pain relief (`src/check_phrases.py`)

- **Measures:** single-phrase extraction of `pain_severity` (severe or not)
  and `pain_relief_effect`.
  - A **false drop** is a severe phrase read as not severe, which lowers
    urgency.
  - A **false keep** is a phrase that is not severe read as severe, which
    raises urgency.
- **Input:**
  - `llm/eval/severity_phrases.json` (set a, 86 phrases);
  - `llm/eval/severity_phrases_b.json` (set b, 36);
  - `llm/eval/relief_phrases.json` (10);
  - held-back `llm/eval/heldback/severity_phrases_c.json`: 64 settled
    phrases plus HU01–HU08 (never shown to llm-dev).
- **Output:**
  - `runs/evals/phrases_2026-09-29/phrases_v03.{json,log}`;
  - `runs/evals/relief_phrases_2026-09-29_fixed/`;
  - `runs/evals/severity_c_2026-09-29/` (final extraction rules);
  - `runs/evals/severity_c_2026-09-29_old/` (before the change).
- **Results:**

| Set | Config | Correct | Severe missed (lowers urgency) | False severe (raises urgency) |
|---|---|---|---|---|
| a (86) | before the severity change | 79/86 | 6/50 | 1/36 |
| b (36) | before the severity change | 27/36 | 9/22 | 0/14 |
| c, held-back (64) | old → **final** | — | 6/36 → **2/36** | 0/28 → **4/28** |
| relief (10) | final | 9/10 | — | — |

- **Set c:** the pre-declared bar of 0 false severe failed (4/28). The user
  kept the new configuration (decision 2026-09-30) because it misses fewer
  severe cases. The follow-up is measured on a new held-back set d.
- **HU01–HU08:** the user ruled on 2026-09-30 that the current readings are
  right:
  - HU01 null;
  - HU02–HU06 and HU08 severe;
  - HU07 moderate.
  These items are scored from now on. They agree with the run by
  construction, so they add no evidence of accuracy.
  - Set c now has 72 items (42 severe, 30 not severe).
  - Re-scored from the existing outputs (reference only): the final config
    misses 2/42 severe and reads 4/30 as false severe; the old config
    misses 7/42 (the old 6 plus HU05) with 0/30 false severe.
  - The reportable result stays the pre-declared 64 items above.
- **Relief:** RP03 ("what I'm meant to take") is still read as null, not as
  not_tried, which leads to URGENT. That errs on the safe side.

## Second-model extraction check on dev text (qwen vs key)

- **Input:** the 45 dev P7 texts that reach the chat
  (`runs/p7/generated_dev.json`).
- **Output:** `runs/evals/qwen_dev_extract_2026-09-29/qwen_dev_extract.{json,log}`.
- **Result:** 12/225 cells differ, from a single pass on the pre-fix
  interview (`23f41c60`).
  - Most are a null duration or trigger.
  - Two are severity: V082 is a false severe, and V086 is a missed severe
    (broken English).

## Vision components (reference; unchanged since 2026-09-24)

- **Input:** the Mendeley carious/non-carious intraoral photos (4,929,
  photo-level labels) and the Malawi set (explored).
- **Output:** see `docs/decisions.md` and `docs/reports/system-report-2026-09-26.md` §2.3.
- **Segmentation (SegmentAnyTooth):** a median of 12 teeth per photo on
  Mendeley. On Malawi, the upper arch is unreliable (median 3.6; fisheye
  camera).
- **Caries detector (YOLOv8):**

| Threshold | Carious photos caught | Healthy photos flagged |
|---|---|---|
| **0.50 (current)** | 29% | 3% |
| 0.25 | 62% | 14% |

- This is the weakest link. The threshold is an open clinical decision for
  the user.

---

## What is not tested yet

- **Dentist labels** (P14): no clinical validation. The knowledge base is
  still DRAFT-UNREVIEWED.
- **v0.3 on held-out:** the held-out set is spent on v0.2, so a new
  held-out set is needed.
- **Model benchmark** (P16), comparing other models on the same set: not
  run.
- **Severity over-triage:** to be measured on a new held-back set d.
- **Real patient photos end to end:** the vignettes assume correct photo
  findings.
