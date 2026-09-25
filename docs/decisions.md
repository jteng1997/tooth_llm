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

### 2026-09-26 — Pain severity definitions (user); the code guard on "severe" was tried and removed
**Decision (user, 2026-09-26; option A as proposed by research-pm and the
lead):** one set of definitions, shared by the production extraction prompt
and the P7 generator brief:
- **mild**: they notice it, but it does not get in the way;
- **moderate**: it bothers them, but they still sleep and eat normally;
- **severe**: it stops them sleeping or eating, or they call it unbearable.

This is a clinical definition. "Severe" is the input to criterion U2
(URGENT, "Severe pain that stops normal sleeping or eating"). The user signed
it off; a dentist has not reviewed it yet.

**Applied by the lead (uncommitted until measured):**
1. `interview.EXTRACTION_INSTRUCTION` uses these definitions, and adds:
   strong words alone ("really bad", "throbbing badly") are moderate while
   they still sleep and eat.
2. `verify()` guard: "severe" is kept only if the patient's words meet the
   definition. That means disrupted sleep or eating that is not denied in
   the same clause, or "unbearable"; in a reply to Q11, choosing its severe
   option also counts. Otherwise the value becomes null. Checks only drop
   values.
3. The P7 `SEVERITY` lines use the same definitions.
Suite 407/407; check_rules 20/20.

**Why:** on dev, model B misread 4/9 clearly moderate texts, in both
directions. One of them (V081) was read as severe against an explicit "doesn't
stop me sleeping or eating". qwen3:14b uses the same prompt, and a
moderate → severe misread moves a level (P7 dev summary, smoke check).

**Caveat found the same day (research-pm; not resolved):** dropping
"severe" lowers urgency, because U2 is lost. That is the direction code must
never move urgency (hard rule 2). A probe of `_severe_said` with 15 severe
phrasings of my own, identical as opening message and as Q11 reply, found
7 dropped:
- meeting the definition: "It doesn't let me sleep", "I don't sleep because
  of it", "I'm up all night with it", "I can only eat soup now, chewing is
  impossible";
- a user call on whether they count as unbearable: "agony",
  "excruciating", "worst pain I've ever had".
The 5 moderate/mild controls were all correctly not severe. This shows the
fault exists; it is not a rate. The proposed conditions before commit are
listed below. They are the lead's and the user's call.
- A severe-phrasing test set with 0 false drops (written by research-pm or
  qa-engineer).
- The user's ruling on agony-type words.
- Optionally, re-asking Q11 when the guard drops "severe" in the live
  interview.

**Update (same day): guard redesigned, and the P7 dev result.**
- **Guard.** The cue-based guard failed the independent set
  (`llm/eval/severity_phrases.json`, 44 severe + 33 controls): 8/44 false
  drops and 7/33 false keeps. The lead changed the design: "severe" is now
  dropped only when the patient denies the disruption and nothing meets
  the definition, with the later answer winning. Result: 0/44 false drops
  and 16/33 false keeps (the safe direction). The later-answer fix was made
  after seeing SV25, so that set is now tuned. A fresh set,
  `llm/eval/severity_phrases_b.json` (22 severe, heavy on self-corrections
  and mixed clauses; 14 controls, each with a real denial), was written by
  research-pm without reading the guard code. It is for the claim.
- **What the guard now protects.** Only the case of an explicit denial.
  Keeping false "severe" (which raises urgency) out rests on the prompt
  anchor.
- **P7 dev in the anchored configuration** (prompt dfaad381bd32, all dev
  cases re-read by B): 1/195 disagree (V087 triggers, B wrong: a stitched
  quote).
  - Residual 0/195 as written, 2/195 = 1.03% (CI 0.1–3.7) conservatively.
  - B error 1/195 = 0.51%.
  - Without severity: residual 0/156, B error 1/156.
  - **Dev clears both rules, both ways.** This is tuned: the anchor and the
    guard were designed after seeing these dev texts, so it is a
    calibration result. The first untuned measurement is held-out P7.
  - All earlier severity cells (ambiguous and B wrong) agree under the
    anchor.

**Guard removed (lead decision, same day).** The denial-only guard failed
the fresh set too (one run on `severity_phrases_b.json`): **3/22 false drops**
and 7/14 false keeps. The false drops were SB02 (a self-correction:
"doesn't stop me eating. Well, it does now…"), SB14 ("I wish I could say I'm
sleeping okay, but I'm not") and SB17 (a denial about someone else: "kids
are sleeping well … but I haven't had a decent night").
- Summary of both independent sets:

  | Guard version | Set | False drops | False keeps |
  |---|---|---|---|
  | cue-based | A | 8/44 | 7/33 |
  | denial-only | A | 1/44 | before the later-answer fix, which was tuned on A |
  | denial-only | B | 3/22 | 7/14 |

- A false drop removes criterion U2 (URGENT), which lowers urgency, and on
  a single-message text there is no Q11 re-ask to recover it. Two
  independent sets missed the zero bar, so **no code drops "severe"**.
  `interview.py` cites both sets in a comment.
- Severity now rests only on the anchored definitions, in the extraction
  prompt and the P7 brief.
- The P7 dev rescore without the guard is unchanged (pain_severity 0/39,
  all fields 1/195). The anchor did the work, so the dev verdict above
  stands. Suite 404/404; check_rules 20/20.
- Both phrase sets are now spent for guard claims. A future guard needs a
  new set.

**For Test 3 and Test 5 (research-pm; to be pre-declared before held-out).**
With no code check, both severity errors can come straight from the model.
Each is counted separately, with n, ids and an exact CI, next to the
headline figures:
- **false severe:** key mild or moderate, extracted severe. This raises
  urgency (U2).
- **missed severe:** key severe, extracted mild, moderate or null. This
  lowers urgency, the more serious direction.
In Test 5 each is also counted at the level it produces: cases whose triage
level was raised, or lowered, because of the severity field.

### 2026-09-26 — P7 held-out: severity shown separately (pre-declared, research-pm)
Declared before any held-out P7 text is generated: the held-out B-error rate
and the residual text-attributable rate are reported **with all five chat
fields** (the rule, as before) **and also without `pain_severity`**. Both
are shown, and nothing is excluded. The 2% bar and the 5% B rule are judged
on the all-fields figures. The without-severity figures are shown to reveal
how much of any miss comes from the severity definition. Also reported, as
on dev: hand-edited cells counted as fixed and as generator failures, and
the no-split residual. Added to `docs/plans/p7-adjudication-plan.md` §5.

### 2026-09-24 — Test 3 blind set C: the blind measurement of #20 (qa-engineer)
Single run, 2026-09-24 18:54–19:11, qwen3:14b, commit 258e6b9.
Configuration (the pre-run log matches the end-of-run record):
- `interview.py` c2e00d55…1831
- `system_symptoms.md` 4aaa06a6…36f4
- `triage_protocol.yaml` 7de38ee9…3ab
- set C file b2e7d4ee…96f1
Pre-run log: `labels/heldout/results/test3_heldout_c_prerun_hashes.txt`. Dev
immediately before: 60/60, 12/12 exact (tuned).

Results, n = 24 dialogues, 120 field cells:
- Field accuracy **116/120 = 96.7%** (exact 95% CI 91.7–99.1).
- Dialogues fully correct 20/24 (CI 62.6–95.3).
- Triggers **20/24** (CI 62.6–95.3). Location 24/24 (CI 85.8–100).
  Location and triggers together 44/48 (CI 80.0–97.7).
- Other three fields 72/72 (CI 95.0–100).
- Guessed a value where the key is null: 0/4 cells (CI 0–60.2).
- Null where the key has a value: 0/116 cells (CI 0–3.1).
- Invented list items: 4/24 dialogues (CI 4.7–37.4).
- Checklist answers overwritten: 0. The pre-declared ambiguous dialogue
  scored 5/5.
- Food/action trigger dialogues: 5/8.

The 4 misses, all in `pain_triggers`:
- 2 are a temperature implied only by context, with no temperature word.
  verify() has no cue for this, before or after #20. After the harness's
  canned re-ask reply, the value ends as `["unknown"]`.
- 1 is an eating action that the #20 cue accepts, but the model did not
  extract it. This is a model miss, via the same canned-reply path.
- 1 is a false accept: a non-trigger (weather) use of "hot" in the same answer
  was kept alongside the real trigger. This is pre-existing: verify() at
  fdaf110 behaves the same, so it does not come from #20.

No #20 cue fired wrongly on set C.
Comparison: set B scored 97/100 (CI 91.5–99.4) before #20. With n = 24, set
C cannot resolve a difference of a few points.

research-pm checked the 4 missed cells against the keys: **0 test-set
artifacts.** Post-hoc remark, not a re-scoring: of the two context-only
temperature cases, the tap-water-on-a-winter-morning phrasing is the more
indirect. Its key (cold) stands.

**Set C is now spent.** It is never re-run, and any later score on it is a
dev number. Miss categories go to llm-dev as abstract behaviour descriptions
only, with no example wording.
Outputs: `labels/heldout/results/test3_heldout_c_qwen3_14b.{log,json}`,
`labels/heldout/results/test3_heldout_c_prerun_hashes.txt`.

### 2026-09-24 — "0 hallucinations" corrected: the check tested existence, not reportability (#22)
**What changed.** The Test 2 hallucination check counted a tooth as invented
only if it was absent from `findings.teeth`. qa-engineer-2's new
"unreported tooth" metric (#22) asks the question that matters to the
patient: does the explanation describe only teeth the assessment *flagged*?
The findings also hold every detection below the 0.50 reporting threshold,
so the old check passed statements about teeth the product had decided not
to report.

**Numbers** (same 60 synthetic cases, seed 0, offline re-scores of stored
runs; `runs/evals/test2_unreported_rescore_22.json`):

| Run | First responses with an unreported tooth |
|---|---|
| 2026-09-17 (behind the "0 hallucinations" claim) | **7/60** (95% CI 4.8–22.6%) |
| 2026-09-23 | 8/60 |
| v2 (2026-09-24), legacy / triage | 9/60 / 11/60 |
| v3, the current patient path, legacy / triage | 8/60 / **8/60** (CI 5.9–24.6%) |
| v3 follow-up answers | 1/120 |

Every hit is an affirmative finding claim about a detection below 0.50:
caries at confidence 0.21–0.49, "other" detections, restorations. One case
(09-17, S0027) describes a "possible spot" on a tooth with no detection at
all.

**Consequences.**
- "0 hallucinations on 60 synthetic cases" holds only under the old
  definition. It is corrected, with a dated note and the original wording
  left visible, in `docs/reports/progress-2026-09-24.md` (possibly already
  shown outside the team). It is also corrected in `docs/architecture.md`, and
  qualified in the 2026-09-17 and 2026-09-24 Test 2 entries below. The lead
  corrected CLAUDE.md.
- From now on, the headline faithfulness figure uses the #22 definition. The
  old figure may be quoted only with its definition.
- Fix in progress (llm-dev): A1, the model is given only reportable teeth;
  A2, a code guardrail rejects any mention of an unflagged tooth. Test 2 is
  re-run on the fix and reported under both definitions.

**Lesson.** A check is only as strong as its definition. "Not in the
findings" tested that a tooth *exists*, not that it may be *reported*, and
the gap between the two is exactly where the detector's low-confidence
output lives. When a metric reads 0, ask what it could never catch.

### 2026-09-25 — P7 dev adjudication, round 1 (research-pm)
13/190 chat cells disagreed before adjudication (6.8%, exact 95% CI
3.7–11.4; 38 cases reached the chat). Outcomes: text wrong 5, key wrong 0,
ambiguous 2, B wrong 3. **No key was changed.** B error rate 3/190 = 1.6%
(CI 0.3–4.5), under the 5% stop rule. The provisional residual is 2/190 =
1.1% (CI 0.1–3.8), which assumes the 5 regenerated texts come back clean.
Record: `runs/p7/adjudication_dev.jsonl`, `runs/p7/adjudication_dev_summary.md`.

**Post-hoc amendment to the plan (made after the outputs were seen):** a
fifth outcome, **check artifact**. It applies when the text is clear and
matches the key, B's raw value matches too, and the harness's `verify()`
step alone drops it. Three cells had this (the `['unknown']` triggers of V016,
V070, V073). A triage text is passed as one message with no question id,
and `verify()` keeps `unknown` only in the reply to Q12, so the value can
never survive. Counting these as B errors would blame B for a harness
property, and switching B to gemma3:12b would not remove them. They are
reported separately, and the summary gives the rates both ways. Fixing the
harness is qa-engineer's and the lead's call; I proposed a rescore from the
stored responses.

Also found: B read 4 of 9 moderate-severity texts as mild, because the
extraction prompt gives no anchor between mild and moderate. It does not
affect any triage level (only "severe" is a criterion input).

**Round 2 (same day).** The lead fixed the harness (a one-message triage
text now calls `verify()` with `own_question=None`) and rescored, which
cleared the 3 artifact cells. After regenerating the 7 cases and
re-extracting, n = 195 cells: 7 disagree (3.6%, CI 1.5–7.3).
- **B error rate 2/195 = 1.0% (CI 0.1–3.7)**: the 5% rule is cleared.
- **Residual 5/195 = 2.6%**: not yet under the 2% bar. It reaches 3/195 =
  1.5% only if the round-2 regenerations of V081 and V082 come back clean.
- New in round 2: V086 triggers marked ambiguous (the severe brief makes the
  text say eating hurts). V028 regenerated for an added symptom it was not
  given ("headaches"), found outside §6.
- Still no key changed.

**Round 3 / hand edits (same day).** After the round-2 regenerations, V081
triggers and V082 severity were still text wrong, and V028 still added a
symptom.
- **Seed reuse fault** in `regenerate_cases()`: the seed is `base +
  len(current history)`, which ignores superseded attempts. V081's round 2
  repeated seed 20260925 and returned the identical text. Fix before
  held-out (qa-engineer); the seed must count every attempt ever made for
  the case.
- **Hand edits, deletion only, by research-pm** (`hand_edited: true`, before
  and after text stored in `generated_dev.json`, §5 checks re-run and
  passed):
  - V081: ", I don't know what triggers it" removed.
  - V028: the added "painkillers for my headache" sentence removed.
  2/100 dev cases are hand-edited.
- **V082 unresolved**: the text lacks "fairly bad", which deletion cannot
  restore. The options go to the lead (a genuine regeneration after the seed
  fix is recommended).
- **Dev verdict:**
  - B error 2/195 = 1.0% (CI 0.1–3.7): the 5% rule is cleared.
  - Residual 4/195 = 2.05% (CI 0.6–5.2): the 2% bar is **not cleared**, by
    one cell. It becomes 3/195 = 1.5% if V082 is fixed. The V081 figure
    assumes its re-extraction agrees with the key.

**Final (same day).**
- **Seed fault fixed** by the lead: `seeds_used()` counts every attempt,
  including superseded ones.
- **V082 round 2 voided** for seed reuse (lead decision, recorded in
  `void_rounds`). V082 got one fresh regeneration from seed 20260933.
- V081 re-extracted after its edit: it agrees.
- V082's fresh text was text wrong for the third time ("a bit of
  discomfort" for a moderate key). With no rounds left, I edited "a bit of
  discomfort" → "pretty bad pain" (a substitution, not deletion only;
  `hand_edited: true`). I chose this over "no acceptable text" because plan
  §4 names the edit as the route and "no acceptable text" would block the
  dev set. It still needs re-extraction.
- **Correction (same day):** after the edit, B read V082 as severe ("pretty
  bad pain"), where it had read the previous text as mild. I marked the cell
  ambiguous rather than B wrong, because I wrote the span and it omits
  "sleeps and eats normally". No further edits. **Corrected dev verdict:**
  - B error 2/195 = 1.03% (CI 0.1–3.7): the 5% rule is cleared.
  - Residual 4/195 = 2.05% (CI 0.6–5.2) as written, and 5/195 = 2.56%
    conservatively: the **2% bar is not cleared**, either way.
  - No-split residual: 6/195 (3.1%) as written, 7/195 (3.6%)
    conservatively.
  - 4 of the 5 residual cells are severity (the anchor gap, which the lead
    is taking to the user).
  - Under plan §5 the run stops here. Going on to held-out after the
    generator-line changes is the lead's and the user's call.
  - The verdict below is superseded.
- **Generator lines, smoke check** (`runs/p7/smoke_lines_dev.json`, 14 dev
  texts). All three new lines kept:
  - self_correcting: 0/7 texts name a side.
  - spontaneous: 2/3 clean.
  - moderate: 9/10 texts clearly moderate by my text-first reading.
  B still misread 4 of the 9 clear moderate texts, in both directions (V081
  → severe despite "doesn't stop me sleeping or eating"). **Research-pm's
  view:** severity cells on moderate keys cannot be reliable without one
  anchored definition shared by the generator brief and the production
  extraction prompt, and possibly a code check on "severe" (it moves
  levels). That decision is the user's. The held-out P7 reporting of
  severity must be pre-declared before held-out runs.
- **Prompt-input amendments before held-out generation** (all recorded in
  `docs/plans/p7-generation-prompt.md` §3.3–§3.5):
  - applied by the lead in code: the moderate, spontaneous, sweet ("no ice
    cream as the example") and self_correcting lines;
  - applied by research-pm in `labels/heldout/p7_fact_rewrites.json`: the
    unclear-answers line now reads "... they may say they cannot remember,
    but they never say whether they took anything for it, and never give any
    length of time". Evidence: V031 and V005 answered the null pain-relief
    field.
  The sweet and unclear-answers lines are not smoke-checked. The backup copy
  in `wave2_backup_2026-09-24/` keeps the old line, by design (a snapshot).
- **Dev verdict (n = 195; assumes V082 then agrees; superseded):**
  - B error 2/195 = 1.0% (CI 0.1–3.7): the 5% rule is cleared.
  - Residual 3/195 = 1.54% (CI 0.3–4.4): the 2% bar is **cleared under the
    pre-declared rule**. Counting the 2 hand-edited scored cells as
    generator failures, it is 5/195 = 2.56%, which fails.
  - The no-split residual is 5/195 (2.6%), or 7/195 (3.6%) counted
    conservatively.
  - Hand edits: 3/100 dev cases. Keys changed: 0.
  - Held-out will be reported both ways.
- **Proposed before held-out generation** (wording in
  `runs/p7/adjudication_dev_summary.md`; the lead applies, and
  `docs/plans/p7-generation-prompt.md` §3.3/§3.5 is updated once applied):
  1. The spontaneous line says they know nothing sets it off, and forbids
     "I don't know what sets it off".
  2. The moderate line says "pretty bad" plainly and forbids playing it down.
  3. The self_correcting style line drops its left/right example, which
     primed a side while location was null.
  4. A smoke check of these lines on about 12 dev keys, stored separately.

### 2026-09-24 — P7 adjudication plan pre-declared (research-pm)
`docs/plans/p7-adjudication-plan.md`, written before any P7 output exists.
Additions to P7 spec §6/§7:
- A fourth adjudication outcome, **"B wrong"**: the text is clear, matches
  the key, and B misread it. It is counted as a B error, not a text fault.
- **Text-first reading:** each disagreement is read with the key and B values
  hidden, and my reading is recorded before they are revealed, to limit the
  key author's bias.
- **Residual bar (≤ 2%)** applies to the text-attributable residual (text
  still wrong + ambiguous). The B error rate is reported beside it, and so
  is the residual without the split. If B's error rate is above 5% on dev,
  P7 stops before held-out and the lead decides (the gemma3:12b fallback is
  the documented option).
- At most 2 regeneration rounds, then a marked, counted hand-edit by
  research-pm. No case is dropped. Keys are never changed to match text.
- 50-case read: random from the 260 held-out cases, seed 20260924, on final
  text. The error definition is fixed in advance and reported as written.

### 2026-09-24 — Test 3 blind set C written (not yet scored)
`labels/heldout/symptom_dialogues_heldout_c.json`, 24 dialogues, 120 cells,
written by research-pm without reading the #15/#20 briefs, cue lists or the
`interview.py` changes since set A.
- Composition, fixed before writing, trigger-heavy:
  - 8 food/action phrasings (cold, hot, sweet and biting, 2 each);
  - 4 negations;
  - 3 multi-trigger;
  - 3 non-trigger uses of hot, cold or sweet;
  - 2 unknown;
  - 2 spontaneous idioms;
  - 2 re-asks (one settles, one null);
  - location plain except 3 nulls;
  - 1 case marked ambiguous before scoring.
- Overlap, checked after writing:
  - 0 multi-word answers identical to set A, set B or dev;
  - Q12 max token Jaccard 0.38 vs A/B/dev and 0.19 vs `system_symptoms.md`;
  - Q12 vs the string literals in `interview.py`: max 0.20, and no answer
    contains a whole 2+-word literal. This was checked by a script that
    prints numbers only, so the author stayed blind to the cues;
  - Q17 max 0.75, by design: plain location answers.
- Rules: scored once by qa-engineer after the next trigger-related change,
  configuration logged; never shared with llm-dev before that, not even as
  categories; afterwards, misses go out as abstract categories only.

### 2026-09-24 — Test 3 blind set B: result (set B now spent)
Single run by qa-engineer-2, 2026-09-24 09:08–09:26, qwen3:14b, commit
fdaf110, after llm-dev's #15. Hashes: `interview.py` 04efa1d1…94fd,
`system_symptoms.md` 4aaa06a6…36f4, `triage_protocol.yaml` 435cf103…0aff0de,
set B file 61d576b9…f84879.
- n = 20 dialogues, 100 cells. Field accuracy **97/100 = 97.0%** (exact
  95% CI 91.5–99.4). Dialogues fully correct 17/20 (CI 62.1–96.8).
- Location **20/20** (CI 83.2–100). Triggers **17/20** (CI 62.1–96.8). The
  other three fields 60/60 (CI 94.0–100).
- Guessed a value where the key is null: 0/7 cells (CI 0–41.0). Null where
  the key has a value: 0/93 (CI 0–3.9). Checklist clicks overwritten: 0.
- Invented list items: 3/20 dialogues, all `["unknown"]` from the harness's
  canned "I'm not sure." re-ask reply after a lost first trigger answer.
  verify() correctly kept them as a patient-side hedge, so this is not a
  rule-7 guess.
- Misses: 2 are verify() cue-list gaps, a trigger named by a food or an
  action rather than its category. The set-A "foods named" class is **not**
  closed by #15. 1 is a model miss on the pre-declared ambiguous clenching
  case.
- Harness caveat: the canned re-ask reply turns a lost answer into
  "unknown" rather than null. Scored as run, no exclusion.
- Comparison: dev 60/60 (tuned on), set A 88/95 (its one blind figure; now
  dev). With n = 20, set B cannot resolve a difference of a few points from
  set A; read the CIs, not the point estimates.
- **Set B is now spent.** Any later score on it is a dev number.
- **Addendum, 2026-09-24 (provenance of #20):** #20 (verify() accepts
  triggers named by a food or an action; live 2026-09-24, suite 361/361) was
  designed from set B's miss categories after set B was spent. The lead's
  brief paraphrased qa-engineer's category description closely enough that
  one example cue nearly matches a set-B answer. No reported number is
  affected: set B was scored once, before #20. Consequence: #20 is informed
  by set B, so **no trigger-cue improvement can be claimed as held-out**
  until a fresh blind Test 3 set (set C) exists and is scored once. Lesson
  for future briefs: miss categories go to llm-dev as abstract behaviour
  descriptions, with no example wording taken from or close to a held-out
  answer.
Outputs: `labels/heldout/results/test3_heldout_b_qwen3_14b.*` (held-out),
`runs/evals/test3_dev_post15_qwen3_14b.*` (dev).

### 2026-09-24 — Test 2 re-run, scorer fix, and bug #18 (partial retake)
Re-run by qa-engineer, 2026-09-24: seed 0, 60 synthetic cases, qwen3:14b,
commit fdaf110.
- Legacy mode: 0/60 on all four rates.
- Triage-2.0 mode, as first scored: hallucination 13/60, **all checker
  artefacts**. The FDI regex read "within 24 hours" as tooth 24 and "14
  teeth" as tooth 14. Fixed in #19 and re-scored offline from the stored
  outputs:
  - hallucination 0/60, omission 0/60, misstated 0/60;
  - follow-up hallucinated tooth 0/120;
  - *(qualified the same day: hallucination here is the original "tooth
    absent from findings" definition. Under #22's "only flagged teeth" this
    run is 8/60 first responses and 1/120 follow-ups; see the unreported-teeth
    entry.)*
  - echo 0/120 (#11 closed);
  - missing tooth described as decay 0 (#13 closed).
- **Real bug #18:** 10/10 URGENT partial-retake cases failed. 6 dropped the
  urgency; 4 fell back to text that never asked for the retake.
  Lead decision, from `llm/interface.md` ("symptoms that need care are never
  hidden behind a bad photo"): with a partial retake and urgency other than
  RETAKE, the explanation states the headline, names the flagged teeth and
  asks for a retake. Implemented with protocol v0.2 and #17 on 2026-09-24.
  **Test 2 re-run pending.**
- Scorer change: it now also counts "retake not requested". A tooth mention
  on a retake is a hallucination only when urgency == RETAKE.
Also recorded: **protocol v0.2, symptoms schema 1.2 and `interface.md` 1.2
went live on 2026-09-24**, with the user-approved Q20/Q21 wording.
Held-out `protocol_check` 200/200 holds by construction (the keys were
rebuilt from v0.2, §9.7). It is not an accuracy result.

### 2026-09-23 — User decisions: Q20/Q21 approved, pus stays URGENT, explanation sentences
Decided by the user, relayed by the lead.
1. **Q20/Q21 wording approved as drafted.** The "awaiting approval"
   markers are removed from the v0.2 draft and Form A, and Form A is
   regenerated (`make_form_a.py`, from the v0.2 draft; regenerate from the live
   path once v0.2 is live).
2. **Pus → URGENT with or without pain stays** (option a): deliberate
   over-triage, like any swelling or trauma. Form C, C11 stays open for the
   dentist and now notes the project owner's provisional choice.
3. **Explanation sentence A approved:** a hedged link to a tooth found in the
   photo ("may be related to the tooth we found, but only a dentist can
   confirm this").
4. **Explanation sentence B changed:** with no photo findings, the
   explanation must never deny a tooth cause. It must say the photos can miss
   a problem and only a dentist can tell. Implemented by llm-dev (task #17).
   The earlier approved wording "The pain may be related to the findings, but
   it could also come from other issues" is superseded where there are no
   findings.
Sequence: protocol v0.2 goes live after qa-engineer's current Test 2 run.
P7 proceeds once qa-engineer has verified the switch (spec §9.7 checks).

### 2026-09-23 — P7 model B via the Gemini API: a scoped exception to "nothing leaves the machine" (user)
Decided by the user, knowingly. Before agreeing, the lead explained that
this is an exception to CLAUDE.md's "nothing leaves it", that the free tier
may train on the data (hence the paid tier, accepted), that API models can
change or be retired, and that only synthetic vignette text goes out.
research-pm had separately flagged the conflict with CLAUDE.md and with the
P7 spec ("local model"). The user chose flash-lite over the lead's
suggestion of 3.8-flash.
Local fallback kept in the spec: **gemma3:12b**, if the Gemini smoke test
fails or the API becomes unavailable. A switch is logged, and the two models'
outputs are never mixed within one set. The methods sentence is in
`docs/plans/p7-vignette-text-spec.md` §6.
- **Model B = `gemini-3.5-flash-lite`**, paid Gemini API, replacing
  gemma4:12b. The generator stays llama3.1:8b, local. Families stay
  distinct: Meta writes, Google checks, Qwen is under test.
- **Scope of the exception, and nothing wider:** only synthetic P7 text
  goes out (held-out, end-to-end and dev vignette text and paraphrases). No
  patient data, no photos, no real patient messages (the P10 set, ChatDoctor,
  LiveQA), no keys, no protocol text. The product still runs fully local; this
  is an evaluation step only. Paid tier; the user accepted the cost.
- **Caveats, stated in the paper:** (1) blind held-out material goes to a
  third party. It is synthetic and shows no level or key, but a copy exists
  outside the machine. (2) The paper cannot claim a fully local evaluation.
  (3) Hosted models are not reproducible (below).
- **Recorded per call:** the model id and the version string the API returns,
  the date and time, the request settings, and the raw response. All B
  outputs are stored, so the §6 comparison can be recomputed without calling
  the API again.
- **Reproducibility caveat for the paper:** a hosted model can change or be
  retired under the same name, so the §6 extraction may not be repeatable.
  The stored outputs and recorded versions are the record. A later re-run is
  a new configuration, logged here.
- B still uses the production extraction prompt and schema unchanged. Any
  translation needed for the API's structured-output format is a harness
  detail, logged by qa-engineer and never changes the prompt text.
- CLAUDE.md still says "nothing leaves it". Whether to add a line there
  about this exception is the lead's call; this entry is the record of it.

### 2026-09-23 — User decisions: S3/U8 rows, explanation wording, P7 model B
Decided by the user, relayed by the lead.
1. **S3/U8 gap: option 2**, two checklist-A Yes/No rows, not a free-text
   box. They are asked of every patient, including those without pain, and are
   not red flags. Drafted as protocol v0.2 (entry below). The Q20/Q21
   wording was sent to the lead for the user's approval; code waits for it.
2. **Explanation wording approved:** "Only a dentist can tell which tooth is
   causing it." and "The pain may be related to the findings, but it could
   also come from other issues."
3. **P7 model B: gemma4:12b** instead of gemma3:12b (Google family, fits
   12 GB). Generator stays llama3.1:8b. qwen3.5 excluded as the same family
   as the system under test.

### 2026-09-23 — Protocol v0.2 drafted: checklist rows for S3 and U8 (user decision, option 2)
Decided by the user; drafted by research-pm. Still DRAFT-UNREVIEWED.
- Two new checklist-A rows, not red flags (they do not stop the interview):
  Q20 → `broken_filling_or_tooth` → S3 (SOON); Q21 → `pus_or_discharge` →
  U8 (URGENT). S3 and U8 become structured criteria, and v0.2 has no
  narrative criteria left.
- **Awaiting the user's approval: the wording of Q20 and Q21** (draft
  in the YAML and in Form A, marked as pending). Code must not show them to
  patients until it is approved.
- **Clinical call, flagged for the dentist (Form C, C11), not decided:** v0.2
  sends pus to URGENT with or without pain. A painless draining sinus may
  be a chronic abscess that SDCEP places lower, so this is deliberate
  over-triage, like any swelling. Also asked: whether "bad taste" catches too
  many people, and whether some broken teeth need sooner than 7 days.
- Draft kept at `docs/plans/protocol-v0.2/triage_protocol.yaml`; the live
  `llm/protocol/triage_protocol.yaml` stays v0.1 until llm-dev switches the
  loader, `interface.md` (symptoms 1.2, with app-dev) and the interview
  together. Putting v0.2 live first would stop the loader: measured, it
  rejects the two unknown fields.
- Keys rebuilt as a pre-scoring amendment (spec §9.7): only the new fields,
  S3 on the minor-trauma keys, and Q20/Q21 in end-to-end expected
  questions changed; ids, levels, facts and styles identical to v0.1.
- Form A is now generated by `docs/dentist-review/make_form_a.py` (it had no
  surviving generator). Regenerated from the v0.2 draft; Form C gains C11.
Consequence recorded for every report: with no narrative criteria left, code
alone should match all 200 triage-level keys, so the triage-level held-out
set can no longer show the model adding accuracy, only over-triage and
`llm_proposed` behaviour.

### 2026-09-23 — End-to-end Test 5 opening mode (lead; pre-scoring)
Decided by the lead before any held-out LLM run; spec §9.6.
- Headline: `--opening drop`. Production has no free-text opening, so the
  P7 opening is not shown to the system.
- Secondary, labelled: `--opening prepend` (opening as the first patient
  message).
- Under `drop`, misses on narrative-only criteria (S3 broken filling, U8
  pus or bad taste) are attributed to the interview (bucket 1).
**Product finding, recorded here and taken to the user by the lead as a
design decision:** in the app as built, a patient with no pain never reaches
the chat, so S3 (a broken filling or crown without pain) cannot be detected
at all. U8 needs pain too, and even then no question asks about it; it
is caught only if volunteered in an answer to another question. The protocol
has both criteria, but the interview gives them no way in. On held-out:
triage-level keys carry words by construction, so this shows only in the
end-to-end set (1 S3, 1 U8 key).

### 2026-09-23 — Incident: held-out key H001 shown to llm-dev (pre-scoring note)
What happened: a qa-engineer scratch script named `inspect.py` in the shared
job tmp folder shadowed Python's standard `inspect` module. It crashed one of
llm-dev's probes, and the crash output printed held-out triage key H001 in
full plus the held-out level × photo-usable counts. llm-dev reported it
themselves and says they used none of it. Their changes in this wave are to
chat extraction (`interview.py`), not triage. The lead moved all scratch
files into `labels/heldout/_scratch/`.
Decided (research-pm, methods only; before any held-out LLM scoring), per
Test 5 spec §9.5:
- H001's fact is shared by all 6 keys of its archetype, so all 6 count as
  exposed (ids in `labels/heldout/leak_h001_sensitivity.json`). No
  end-to-end key and no P7 text is affected.
- Primary analysis stays on all 200; a sensitivity analysis on the other 194
  is pre-declared and reported next to it.
- The exposed keys cannot be under-triaged, so the primary endpoint cannot be
  flattered; over-triage, agreement and κ could be, by at most 6/200.
- The level × photo counts were already public in the tracked spec (§9.1,
  my own writing). That was a smaller slip of the same kind; it stays,
  because the amendment's reasoning depends on it and the counts are aggregate.
Prevention, proposed to the lead: a held-out-reading script never prints a
key on error, and scratch files never go in shared temp folders or take a
standard-library name.
Checked by the lead (2026-09-23): against wave 1 (6bf9bcf), `triage.py`,
`protocol.py`, `llm/protocol/`, `rules.py` and `system_triage.md` are all
unchanged. The only LLM-side changes are `interview.py` (chat extraction) and
`explain.py` / `system_explain.md` (a guardrail that stops the explanation
placing the patient's pain on a side or tooth). So the exposure cannot have
shaped triage in this wave. The sensitivity analysis stays pre-declared all
the same, since later triage work would happen after the exposure.
The level × photo counts in spec §9.1 are already committed and pushed; they
are aggregate and logged, so they stay.

### 2026-09-23 — Test 3 gets a held-out set for location and triggers
Why: llm-dev's location and trigger cue lists were partly shaped by the 13
dev dialogues, so Test 3 on those overstates how well the fixes generalise.
research-pm wrote 19 new dialogues without reading llm-dev's cue lists
(`labels/heldout/symptom_dialogues_heldout.json`, gitignored, never shown to
llm-dev). They use the dev format and focus on Q17 and Q12: 3 null locations
(side only ×2, arch only), a whole-mouth answer, the front, a self-corrected
location, a slang arch word, and landmark or roundabout wording; for
triggers, a denied trigger, another person's trigger, a hedged trigger,
foods named instead of categories, warm for hot, "cold" meaning the illness,
"hot" meaning feeling hot, and a trigger said only in passing in another
answer. 2 cases are marked ambiguous (the pain moved; the trigger said in
passing). New wording checked by token Jaccard against dev
answers to the same question: at most 0.33 (Q12) and 0.40 (Q17).
Convention restated in the file: a patient who cannot say where it hurts is
`null`, not `unknown`, following dev D07 and D12. The schema allows
`unknown` for location but no rule says when; the held-out set avoids
depending on that until the rule exists.
Scored by qa-engineer as its own line, never merged into the dev numbers,
and reported with n = 19 (95 field cells, 38 of them focus cells).
**First result (qa-engineer, 2026-09-23, post-fix extraction, qwen3:14b):**
88/95 fields correct = 92.6% (exact 95% CI 85.4–97.0). Location and
triggers 33/38 = 86.8% (71.9–95.6); the other three fields 55/57 (87.9–99.6).
Invented list items: 3/19 held-out vs 0/12 dev. Only 1 is a genuine
invention; 2 come from the harness's canned re-ask reply.
research-pm checked all 7 misses against the keys: **0 test-set artifacts.**
In each, the question was asked and the first scripted answer carries the
key value. The misses break down as:
- 3 where code rejected a correct model value: "out of the blue" and
  "upstairs" have no cue, and a bare "No." to Q10 is dropped although Q10 is
  a yes/no question;
- 3 model errors: a side invented for a lower front tooth, "as soon as I chew"
  read as spontaneous, and "a month or so" left null;
- 1 invention accepted by code: "sweaty at night" became spontaneous.
Post-hoc remark, not a re-scoring: "upstairs" (T3H06) is the most arguable
key in the set. It stays scored as written, because marking it ambiguous
after seeing the result would be a post-hoc exclusion.
So the dev set's cue lists do not fully generalise, which is what this set
was built to show. Fixes go to llm-dev as behaviour descriptions, never as
the held-out wording.
Lead's breakdown, confirmed by research-pm: the model alone was right on
91/95. verify() dropped 3 correct values and let 1 invention through, so
the gap from 91 to 88 is code, not model.

### 2026-09-23 — Test 3 set A becomes dev; blind set B written (lead + research-pm)
The 7 set-A misses become categories for llm-dev's task #15 (no text
shared). After that, set A has informed a fix and is **no longer blind**.
- **88/95 (92.6%) stays set A's one blind measurement**, reported as such.
  Any later set-A score is a dev number.
- **Set B** (`labels/heldout/symptom_dialogues_heldout_b.json`, gitignored,
  not shared with llm-dev even as categories until the final measurement):
  20 new dialogues on the same five fields, written by research-pm before #15
  is re-measured. It gives the reported post-#15 number.
- Because set B was written after seeing set A's misses, it may lean towards
  known weak spots. To limit that, its make-up was fixed before any answer
  was written: 11 answers with both arch and side, 5 that must stay null, 2
  front, 2 whole mouth; every trigger value at least twice; 3 re-ask cases
  (2 settle on the re-ask, 1 stays null after it; my first count of 2 missed
  the null one, corrected before any run);
  2 non-trigger uses of hot or cold. 1 case marked ambiguous before scoring
  (clenching mapped to biting).
- New wording: no multi-word answer is copied from set A or dev. The
  one-word severity and duration answers ("Mild.", "Four days.") repeat, as
  they must. Q12 answers overlap set A + dev by at most 0.40 token Jaccard,
  Q17 by at most 0.57 (same template with the opposite side).
- n = 20: 100 field cells, 40 on location and triggers. With n this small,
  report exact CIs. 20 dialogues cannot show a difference of a few points
  from set A.

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
§9.5 sensitivity on the same baseline (no model, qa-engineer's
`--sensitivity-exclude`), n = 194: `rules` 51/194 under, κ 0.578;
`protocol_check` 8/194 under, κ 0.965. The 6 exposed keys were agreements
for both systems, so only denominators and κ move.

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
Generator: **llama3.1:8b** (Meta, local). Model B for the blind extraction:
**gemini-3.5-flash-lite** via the paid Gemini API (Google; user's decision
2026-09-23, entry above; it replaced gemma4:12b, which had replaced
research-pm's original gemma3:12b). System under test: qwen3:14b (Alibaba).
Three different families, as spec §4/§6 ask. qwen3.5 is excluded as the same
family as the system under test. Not used: the `oralgpt` models (base family
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
*(Qualified 2026-09-24: 0% only under the original definition, "tooth
absent from the findings". Under the #22 "only flagged teeth" definition,
this run scores 7/60; see the 2026-09-24 entry on unreported teeth.)*

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
