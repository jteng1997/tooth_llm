# Decision log

Newest first. Each entry: what was decided, why, and what evidence it rests
on. Owned by `research-pm`; any agent may propose an entry.

## Open

### Symptoms the interview does not ask about (for a dentist)
Found while hand-labelling 200 real patient messages (P10, 2026-09-23;
`labels/redflag_messages.csv`, plan §3.3). Each of these turned up more than
once in patients' own words, each has an SDCEP pathway, and none has a
question in protocol v0.1:

| Near miss | What SDCEP does with it | In our protocol? |
|---|---|---|
| Cannot open the mouth ("only one finger wide"), trismus | Cardinal sign of spreading infection; with swelling it is an emergency | no row; `swelling_features` was dropped when the interview stopped asking follow-ups |
| Double vision or visual disturbance with jaw or face pain | Pain pathway: visual disturbance suggestive of giant cell arteritis → Emergency Medical | no |
| Hoarse or muffled voice, changed voice | Listed with airway compromise in the acute apical abscess page (dysphonia) | no |
| Pain relief not helping | Urgent (24 h) | **yes**, criterion U1 |

Not added: adding a question is a clinical call, and each one costs a
checklist row. A dentist should decide whether trismus, visual disturbance and
voice change belong in checklist A. Until then the protocol cannot detect
them, and the evaluation cannot measure them.

### Caries threshold in `llm/rules.py`
`CARIES_CONF_THRESHOLD = 0.50`. The file's own comment says to tune for
sensitivity. Measured on 4,929 labelled Mendeley photos (photo-level labels):

| Threshold | Carious photos caught | Healthy photos wrongly flagged |
|---|---|---|
| 0.50 | 29% | 3% |
| 0.25 | 62% | 14% |

Needs a dentist's call. Not changed.

### Knowledge files review
All 32 sections in `llm/knowledge/` are `DRAFT-UNREVIEWED`. The explanation
step only runs with the development override until a dentist signs them off.

### Human evaluation (Test 4)
30 explanation samples in `runs/evals/eval_samples.md` await dentist scoring.
The 20 rule cases in `llm/eval/rule_cases.json` also need blind dentist labels.

## Decided

### 2026-09-23 — Test 5 pre-scoring amendments (research-pm)
Made before any held-out LLM scoring, in answer to qa-engineer; details in
`docs/plans/test5-analysis-spec.md` §9.
1. **Unwarranted RETAKE.** No held-out key pairs unusable photos with SOON or
   ROUTINE, so a RETAKE on those keys is never called for. It now stays in
   the denominator as a miss (exact agreement, recall), not an exclusion.
   RETAKE on EMERGENCY/URGENT is unchanged (under-triage, severe). Why:
   excluding it let a system drop hard cases from every metric.
2. **Underpowered McNemar** (< 10 discordant pairs): report b, c, each
   system's under-triage with a Clopper-Pearson CI on the common set, and the
   exact CI for b/(b+c); no p-value.
3. **Stability list fixed** to 20 cases where the model is called (all 8
   narrative cases, 2 injection, 10 seeded others). The code's seeded
   5-per-level pick spent 5 slots on floor-decided EMERGENCY cases with no
   model call and drew no narrative case. Two paraphrases each are written in
   P7.
4. **Dev set:** research-pm writes 100 fresh keys (`labels/dev/`, seed
   20260924, no fact copied from held-out); qa-engineer writes the text in P7
   (dev first) and converts it to `llm/eval/triage_vignettes_dev.json`.
   Built the same day: `labels/dev/triage_dev_keys.json`, 100 keys (25 per
   level, 45 boundary, 5 SOON/ROUTINE with unusable photos), 0 protocol
   mismatches; `check_triage.py --validate-only` 0 errors. In git: dev is
   not secret and llm-dev may read it.
   **No held-out copies, how checked:** the builder compares every dev fact
   with every held-out fact (triage and end-to-end keys, 33 distinct) by
   token Jaccard and refuses to write at ≥ 0.5 (P7's own near-duplicate bar
   is 0.8). Result: 46 distinct dev facts, highest overlap 0.35. Tooth sets,
   durations and styles come from a different seed (20260924).
   Also checked: no dev fact names a trigger its key's `pain_triggers` lacks
   (0 of the reached dev keys; 3 found and reworded before this count).

### 2026-09-23 — Test 5 run log: baseline `rules`, config f8adf24e3fd9360a
Run by qa-engineer, 2026-09-23 16:56, `check_triage.py --system rules` on the
200 held-out triage keys (cases sha256 dfe0229d…, protocol v0.1, commit
6bf9bcf with a dirty tree). No model involved. Result identical to the dry run
(§8 of the spec): `rules` under-triage 51/200 = 25.5% (CI 19.6–32.1), severe
31, missed EMERGENCY 25, over 10, κ 0.595 (CI 0.50–0.68); `protocol_check`
8/200 = 4.0% (CI 1.7–7.7), κ 0.967 (CI 0.94–0.99). No RETAKE was excluded,
so the §9.1 amendment does not change these numbers. This is the baseline,
not an LLM configuration; the held-out LLM scoring has not happened.

### 2026-09-23 — P7: one more prompt-input rewrite (research-pm)
qa-engineer's prompt dry run found the fact "short twinge with cold or sweet
things…" on 18 reached keys (14 triage: 7 `["cold"]`, 7 `["sweet"]`; 4
end-to-end, all `["sweet"]`) whose `pain_triggers` holds only one of the two.
Carrying the fact would make every one a triggers disagreement (14/420 = 3.3%
of triage chat cells, above the 2% bar) through a key-authoring slip, not a
text error. Fixed in the prompt input only (`p7_fact_rewrites.json`): the
fact loses the trigger words and the single trigger comes from the "must get
across" line. Keys unchanged, so no level can move.
No other fact/trigger conflict among reached held-out keys (research-pm's and
qa-engineer's scans agree).
Evidence: key-field counts only (4 unusable-photo keys, all URGENT or
EMERGENCY; 155 non-floor keys; 8 narrative). No held-out outcome seen.

### 2026-09-23 — Wave 2 plan: GPU queue order (research-pm, for the lead)
One heavy job at a time, in this order:
1. Test 2 / Test 3 verification of llm-dev's extraction fixes.
2. P7 generation, then P7 blind extraction (model B).
3. Held-out Test 5, once `check_triage.py` is aligned with the pre-registered
   spec and P7's residual disagreement is ≤ 2%.
4. Topic-cleanup run (2.5 h, the 2,388 `oral_soft_tissue` rows) — lowest.

On item 4: **deferred until Test 5 has been scored** (research-pm's
proposal, accepted by the lead 2026-09-23; not cancelled). The filtered corpus now feeds nothing:
the silver labels are closed, and the only other planned use is the QLoRA
fine-tune, which happens only if measured results fall short (2026-09-22).
If a fine-tune is ever started, run the cleanup first: ~80% of those 2,388
rows are not dental (topic-classifier trial, 20/20 against hand labels) and
would pollute the training set.
Status at the start of wave 2: the run never happened (`dataset/dental_qa/`
has only the 15:08 trial file); P7 had not started.

### 2026-09-23 — P7 models and generation prompt
Generator: **llama3.1:8b** (Meta). Model B for the blind extraction:
**gemma3:12b** (Google). System under test: qwen3:14b (Alibaba). Three
different families, as spec §4/§6 ask; each fits the 12 GB RTX 3060 alone
(about 4.9 GB and 8.1 GB at Q4). Not used: the `oralgpt` models (base family
unconfirmed, so they may be Qwen) and qwen3:4b (same family as the system
under test).
Why B is the larger model: B's own misreads count against the ≤ 2% residual
disagreement bar, so the stronger extractor goes there. Generator mistakes
are caught by the automatic checks and regenerated.
Threat, stated either way: the text is written by one model family, so its
phrasing habits are part of the test. Report it in the methods.
Prompt and settings: `docs/plans/p7-generation-prompt.md` (temperature 0.8,
seed 20260923 + attempt, batched by style). Three method calls made there,
none clinical:
- **Chat fields where the chat was never reached** (no pain, or a checklist-A
  red flag: 116/200 triage, 35/60 end-to-end keys) are null because the
  question was never asked. For these, spec §2.4 (carry every fact) wins over
  §2.3, and §6 does not score their chat fields: a time a patient mentions
  with a red flag stays in the text although `duration_days` is null.
- **Three facts are rewritten in the prompt input only** (the key is
  unchanged): two describe checklist clicks, one refers to the photo result,
  none of which a patient would type. Mapping kept with the keys
  (`labels/heldout/p7_fact_rewrites.json`), out of git.
- **Field values reach the generator as plain-English lines**, never as field
  names or enum strings, and the chat questions as our paraphrased topics,
  never the fixed question text.
Also: the level-name and 5-gram checks exempt the verbatim injection lines,
which contain "routine" and "emergency" by design.

### 2026-09-23 — Criterion R0 removed from the protocol
R0 (ROUTINE, `images_usable == true`) was "none of the above" written as a
criterion: it held on every usable photo. llm-dev measured the cost — the
model was sent back to retry for not citing it in 5 of 6 probe runs, and the
retry changed nothing. `protocol_level()` already returns ROUTINE when nothing
holds, and the ROUTINE headline tells the patient the same thing, so nothing
patient-facing changes. Protocol now has 21 criteria.
Verified: the held-out keys rebuild unchanged (200 / 60, same level counts),
and the dry-run numbers are identical (protocol check 8/200 under-triage, 96.0%
exact, κ 0.967) — which is the evidence that R0 was inert.
Also from the same probe: llm-dev's "missed criteria" feedback now names only
criteria at least as urgent as the protocol level, since a missed ROUTINE
criterion cannot change the outcome.

### 2026-09-23 — Silver labels fail their bars; reported as a negative result
Pre-registered bars (plan §3.2): κ ≥ 0.6 and EMERGENCY precision ≥ 90%.
Measured: κ **0.269** blind on 200 rows (0.406 after two corrections made by
qa-engineer on those same rows — tuned, not blind, and labelled as such in any
write-up), agreement 73.4%; EMERGENCY precision **8/40 = 20%** (95% CI 10–35%)
on the 80-row calibration batch, read blind, labels saved before the key was
opened.

Decided (research-pm, with the lead): **stop, and report it as a documented
failed attempt** rather than iterate.
- The false emergencies come from "immediately" attached to a clinician rather
  than a place (12 of 32), "Emergency room" as a venue for a test, the
  corpus's own garbling of ENT into ER, immediacy attached to something else
  ("stop [cocaine] immediately"), and conditionals or negations ("I do not see
  anything to go to ER … wait for your dentist's next appointment").
- The biggest disagreement group is an ambiguity in the rubric itself
  (reassurance + self-care + an untimed "see a dentist" satisfies both the
  ROUTINE and the UNSPECIFIED clause). Recorded resolution, for interpreting
  the artefacts: UNSPECIFIED wins whenever a visit is recommended without a
  time frame.
- Ceiling too low to matter: 24.5% coverage, ~1% emergencies, on rows ~76%
  dental. It could never test the EMERGENCY/URGENT boundary.
- The construct is weak: the label is what a doctor wrote on a Q&A site, not
  how soon the patient needed care.

Kept: `src/silver_labels.py`, `dataset/dental_qa/silver_labels.jsonl`,
`labels/silver_hand_labels.csv`, `labels/silver_calibration_hand.csv`, and the
corpus counts, which stand as a finding about the data (of 9,955 rows:
EMERGENCY 424, URGENT 349, SOON 305, ROUTINE 1,358, UNSPECIFIED 7,518).
Nothing downstream depends on them. The evaluation rests on the SDCEP-derived
held-out keys, dentist labels when a dentist is found, and P10 red-flag recall
on real messages.

### 2026-09-23 — Dentist review packet ready (P4)
`docs/dentist-review/`: README (what the tool is, what we need, ground rules),
Form A (protocol: levels, 22 criteria, 19 questions, fixed text — generated
from the YAML so it cannot drift), Form B (blind vignette labelling: level
definitions, "not enough information" and route boxes, two-rater and
single-rater procedures) with `make_form_b.py`, which refuses to print a sheet
until P7 has written real patient wording and keeps the case-id map out of the
dentist's copy, Form C (9 open clinical questions, each with what we do, why,
and what the guidelines say), Form D (6 knowledge files / 32 sections; only
the dentist may set `review_status`). Not sent: no dentist yet.

### 2026-09-23 — Test 5 analysis pre-registered
`docs/plans/test5-analysis-spec.md`, written before any held-out run (lead's
instruction). Fixes the metrics (under-triage with exact CIs as the primary
endpoint, weighted κ with a bootstrap CI, exact McNemar for LLM vs rules), the
systems compared (final, llm_proposed, rules, protocol_check, key), the
error-attribution buckets, and what each result may change. Held-out is scored
once per configuration, and every scoring is logged here. No exclusions after
scoring; the only pre-declared one is RETAKE from level metrics.
Caveat that goes in every report: agreement with SDCEP *as encoded* in
protocol v0.1 including the user's 2026-09-22 decisions, not clinical
validation.


### 2026-09-22 — Ulcer question, silver labels, finding wording, Q13 on checklist (user + lead)
Decided by the user (items 1–3) and the lead (item 4). Applied to
`llm/protocol/triage_protocol.yaml`. The protocol stays DRAFT-UNREVIEWED.
1. **Persistent ulcer or lump → URGENT (user).** New checklist-A row Q19
   (placed after the red flags, not a red flag): "Do you have a mouth ulcer,
   sore or lump that has lasted more than 3 weeks?" New field
   `persistent_ulcer` (symptoms 1.1, llm-dev T6) and criterion U9 → URGENT.
   Source: SDCEP 2nd ed. (2026) ulceration pathway (ulcer present more than 3
   weeks → urgent dental assessment for possible cancer referral), plus the
   SDCEP 2013 abnormal-appearance pathway for lumps and patches. This closes
   the gap research-pm found in P3. It is still not a lump or ulcer *screen*:
   occlusal photos don't show soft tissue.
2. **Silver labels come from the doctor's answer *before* the drug/dose
   filter (user's clarification of decision 13, 2026-09-22 plan decisions).**
   The doctor's text is read only by the rule script that derives the label.
   It is never shown to a model, and never used for prompts or training.
   The drug/dose/diagnosis filter still applies to any text a model sees or
   learns from. Rubric: `docs/plans/phase1-2-plan.md` §3.2.
3. **Finding wording (user):** "Based on the image, there is an indication of
   tooth decay on: …" (`fixed_text.photo_finding_phrase`). Code fills in the
   tooth names with `fdi_label`.
4. **Q13 moves to checklist B (lead):** "After the pain is set off, does it
   keep aching for more than about half a minute?" This row alone has a third
   option, "Not sure", which records `null`; it is encoded as
   `options: [yes, no, not_sure]` so no code hard-codes the exception.
   Red-flag rows stay strict Yes/No. Chat is now Q10–Q12, Q17, Q18: 5 turns.
   `reask_template` (chat only) no longer says "yes or no": "Sorry, I need a
   clearer answer to keep you safe. {question}".

Consequence for the held-out keys: rebuilt 2026-09-22 so that every
checklist-A row has a value (a checklist can't leave a red flag unanswered),
and 3 held-out / 1 end-to-end persistent-ulcer cases were added. There are
still 200 / 60 keys, with 0 mismatches against the loader's protocol level.

### 2026-09-22 — Triage protocol v0.1 items and checklist input (user + lead)
Decided by the user on four items research-pm flagged in
`llm/protocol/triage_protocol.yaml` v0.1, plus one new user decision. The
protocol stays DRAFT-UNREVIEWED; every clinical item needs a dentist.
1. **U7 stays**: possible cavity in the photo + any tooth pain → URGENT.
   Mirrors `rules.py` R4 so the protocol is never less urgent than the rules
   baseline. SDCEP 2nd ed. would give Non-urgent (7 days) when pain relief
   works. Pending dentist review.
2. **Longer interview accepted.** The protocol has 18 questions (was 9), with
   the input change in item 5.
3. **"Recent extraction" = within the last two weeks** (Q16). SDCEP says only
   "recently"; the two weeks is a project convention.
4. **Fixed texts approved as drafted**: `safety_net`, `fixed_text.disclaimer`
   and `fixed_text.routine_advice` in the protocol file. This is user-approved
   *wording*; the clinical content stays DRAFT-UNREVIEWED until a dentist signs
   off. The protocol file is the single copy the code reads.
5. **Yes/no questions on a checklist** (user), shown all rows at once to
   shorten input. Design (lead, non-clinical):
   - Each row has an explicit Yes/No with no default; the form cannot be
     submitted until every row is answered, so an untouched row is never read
     as "no" (hard rule 7).
   - Checklist A: Q1–Q9 (the 8 red flags + "any pain"). Any red-flag Yes →
     the emergency screen. Pain No → result.
   - Checklist B, only with pain: Q14 (wakes at night), Q15 (pain on biting),
     Q16 (recent extraction).
   - Chat with evidence-checked LLM extraction stays for Q10, Q11, Q12, Q13,
     Q17, Q18.
   - With pain: 2 forms + 6 chat turns instead of 18 turns; without pain: 1
     form. `reask_template` applies to chat questions only.
   - Encoded in the protocol as `input: yesno_checklist` + `group: A|B`, or
     `input: chat`.
   - Consequence for evaluation: a checklist answer is a click, not a quote, so
     Test 3's quote check covers only the six chat fields; end-to-end keys are
     scored by field values, and their `expected_questions` order is
     informational for checklist rows.

### 2026-09-22 — Phase 1–2 plan decisions (user)
Decided by the user on the plans in `docs/plans/phase1-2-plan.md` and
`docs/plans/llm-triage-design.md`. Provisional for the prototype; each clinical
item still needs dentist confirmation.
1. On-screen time frames: URGENT = within 24 hours, SOON = within 7 days
   (SDCEP 2nd ed. 2026, NHS England 2025). Replaces "a few days/weeks".
2. Unbearable or uncontrolled pain: URGENT (dentist within 24 h), per SDCEP and
   NHS England, not the emergency department — unless a red flag is present.
3. Red-flag floor extended: uncontrolled bleeding, chest pain or breathlessness,
   pain-relief overdose, feeling very unwell. These also stop the interview.
4. Any swelling or any trauma stays EMERGENCY (safe over-triage vs SDCEP's
   grading), to be revisited with a dentist.
5. Lingering or night pain with effective pain relief: stays URGENT for now;
   SDCEP says non-urgent, and lowering needs a dentist's sign-off.
6. Photo-only finding, no symptoms: SOON (within 7 days).
7. Missing tooth, no symptoms: ROUTINE.
8. The brief's "safe self-care" merges into ROUTINE plus prevention advice.
9. Red flag: stop the interview at once and show one screen — "This may be an
   emergency. Please go to a hospital as soon as possible." No emergency
   phone number, no separate medical/dental routes on screen (the route may
   still be recorded for research).
10. When the LLM's level is inconsistent with the protocol's criteria, code
    raises the level (option A), not just records it.
11. Interview questions use fixed, pre-written English text; the LLM no longer
    phrases each question. Supersedes the "model phrases the question" part of
    hard rule 6 — Python still owns the plan and stopping.
13. Download ChatDoctor-HealthCareMagic-100k and LiveQA TREC 2017 for research
    use only: kept local, never pushed to GitHub, licence limits (no licence
    declared; ChatDoctor academic-research-only) stated in the paper.
12. Acceptance bar (no dentist available yet):
    - Primary key: SDCEP-derived answer keys for 200 held-out vignettes,
      written by research-pm before the system sees them. Pass = zero
      under-triage and weighted κ ≥ 0.8. Reported honestly as "agreement with
      SDCEP as encoded", not clinical correctness.
    - Secondary: urgency implied by the doctors' answers in the dental subset
      of ChatDoctor, reported separately as weak (silver) labels.
    - When a dentist is available: blind labels on a subset to validate both.
    - research-pm searches Hugging Face for dental triage data that already
      carries urgency labels.
Lead decisions (non-clinical): research-pm owns the protocol YAML content,
llm-dev owns its loader/validator; test D05 stays as a separately scored
robustness case; existing Chinese bare answers stay; the embedder stays
multilingual-e5-small.

### 2026-09-22 — English only for all project output
Decided by the user. The web app, every LLM interaction with users, prompts,
knowledge, reports and docs are in English. The current prompts' "reply in
the language the user is writing in" must change (llm-dev). Indonesian is
only the user's chat language with the lead.

### 2026-09-22 — Triage moves to the LLM, with a red-flag floor in code
Decided by the user, from the project brief (Dental Vision-LLM Triage System).
- The LLM determines urgency from the patient's complaints plus the findings,
  following a triage protocol built from the clinical literature.
- A deterministic red-flag floor stays in code: swelling, difficulty breathing
  or swallowing, fever, dental trauma force EMERGENCY. Code may only raise
  urgency, never lower it.
- The protocol goes into the prompt and knowledge base first. Fine-tune (QLoRA
  on the RTX 3060) only if measured results against dentist labels fall short.
- ChatDoctor-HealthCareMagic-100k and LiveQA TREC 2017 are filtered to dental,
  oral, gum and jaw topics, and answers naming drugs, doses or definitive
  diagnoses are removed, since the brief's guardrails forbid exactly those.
- Target: zero under-triage against blind dentist labels. Planned comparison
  for the paper: LLM triage vs rule-based triage vs dentist.
- Caveat recorded: `llm/rules.py`'s cited sources (SDCEP, AAE, ICCMS, WHO) were
  never checked against the originals. An LLM protocol built from the same
  literature needs the same dentist verification.
- Work runs phase by phase: research-pm + llm-dev plan phases 1–2 first; the
  user reviews the plan before any code changes.

### 2026-09-22 — Agent team of four
Agent teams enabled (`.claude/settings.json`). backend-dev and frontend-dev
merged into `app-dev`: the UI is one HTML file tied to `webapp.py`, so keeping
them apart only added an API hand-off. Team: research-pm, app-dev, llm-dev,
qa-engineer; the main session leads and owns git (teammates share one working
folder, so they don't branch or commit).

### 2026-09-22 — Repository cleanup
Stay in this folder rather than moving (dataset/weights large, `.venv` not
relocatable). Unused material moved to `_archive/` (not deleted). `llm/`
reorganised into `prompts/`, `knowledge/`, `eval/`. All tests re-run after the
move: rules 20/20, faithfulness 0/0/0 on 8 seed cases, symptoms 98.8%.

### 2026-09-19 — Interview stopping rule is Python's, not the model's
Left to itself the model looped and repeated questions. Python now walks a
fixed plan (`QUESTION_PLAN`) and stops on a red flag, on "no pain", when all
pain details are answered, or at 11 questions. A bare yes/no only answers the
question it replied to — without that, a patient in pain was never asked
about pain.

### 2026-09-19 — cavity-model-v2 rejected
`pretrained_cavity.pt` is an 80-class COCO YOLO11n (people, cars, …), not a
cavity model. On 200 photos it flagged more healthy mouths than carious ones
and labelled tooth crops "airplane". Kept the previous caries detector.

### 2026-09-17 — Development LLM: qwen3:14b; 4B not deployable
qwen3:4b leaked its private reasoning into all 60 of 60 test explanations and
invented teeth in 40%. qwen3:14b: 0% on all three faithfulness measures.

### 2026-09-17 — Evidence-checked symptom extraction
Prompt wording alone kept trading invented answers for dropped ones. Every
extracted field now needs a quote from the patient, verified against the
transcript; unsupported fields become `null`.

### 2026-09-16 — Caries detector
YOLOv8 from AndreyGermanov/yolov8_caries_detector (DentalAI intraoral photos),
run per tooth crop rather than on the whole photo. Rejected: dentalscan-ai
(panoramic X-rays only) and the ESP32 cavity repo (no published weights).

### 2026-09-16 — Mendeley is the working dataset
SegmentAnyTooth finds a median of 12–13 teeth on Mendeley photos but only 3.6
on Malawi upper arches (domain gap: fisheye camera). Malawi preprocessing
exists (`src/preprocess_malawi.py`) but upper-arch segmentation there is not
reliable enough to build on.
