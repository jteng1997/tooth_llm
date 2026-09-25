# Test 5 analysis spec (pre-registered)

Status: **pre-registered 2026-09-23 by research-pm, before any held-out run.**
Agreed with the lead. Anything decided after seeing held-out numbers is a
post-hoc choice and must be labelled as one in the report.

Implementation is qa-engineer's (`src/check_triage.py`); this file fixes what
is measured, how it is reported and what it may change. The point of writing
it first is simple: with one held-out set and a target of zero under-triage,
it is otherwise too easy to pick the flattering cut after the fact.

---

## 1. Data

| Set | File | Size | Who may see it |
|---|---|---|---|
| Held-out, triage-level | `labels/heldout/triage_heldout_keys.json` | 200 (EMERGENCY 45, URGENT 55, SOON 55, ROUTINE 45; 84 boundary) | qa-engineer, to run. Never llm-dev. |
| Held-out, end-to-end | `labels/heldout/e2e_keys.json` | 60 (15 per level) | same |
| Dev | `llm/eval/triage_vignettes_dev.json` (built as in §9.4) | 100 | anyone; all tuning happens here |

The key is the level the protocol gives, computed from the criteria and
checked against the loader (0 mismatches at v0.1). **It is not a dentist's
label.** Every report of these numbers carries the sentence: *"agreement with
SDCEP as encoded in protocol v0.1, including the user's 2026-09-22 decisions;
not a clinical validation."*

**Scored once per configuration.** A configuration = model + prompt + protocol
version + composition options. Each held-out scoring is logged in
`docs/decisions.md` (date, configuration, who ran it) whether or not the
result is used. Re-running the same configuration after a code fix is allowed
and must be logged as a re-run.

## 2. Systems compared, on the same cases

1. `final` — `assessment.urgency` as the patient would see it (LLM + floor +
   protocol check + retake rule).
2. `llm_proposed` — the model's own level before any code override. This is
   what says whether the LLM adds anything.
3. `rules` — `rules.assess()` shadow baseline, unchanged.
4. `protocol_check` — code's own level from the structured criteria.
5. `key` — the answer key.

Report all four against the key, and `final` against `rules` head to head.

## 3. Metrics

Levels are ordered EMERGENCY > URGENT > SOON > ROUTINE. RETAKE is excluded
from every level metric and reported separately as a photo-quality count; no
held-out key has RETAKE as its level.

**Primary — under-triage.** A case is under-triaged when the system's level is
less urgent than the key. Report the count and rate with an exact
(Clopper-Pearson) 95% CI, for `final` and for `llm_proposed`. Target 0.
With 0/200 the upper bound is 1.5%; state that bound every time rather than
writing "no under-triage".

Also report, as pre-declared sub-counts:
- severe under-triage: two or more levels below the key;
- missed EMERGENCY: key EMERGENCY, system anything else (this is the one that
  can hurt someone);
- under-triage among boundary cases vs the rest.

**RETAKE.** RETAKE is not a level, but a system can emit it, so the rule is
fixed here (added 2026-09-23 after the dry run, §8): with an EMERGENCY or
URGENT key, a RETAKE counts as **under-triage and as severe** — asking for new
photos when the patient needs care today delays it, and names no urgency at
all. With a SOON or ROUTINE key it is neither under- nor over-triage; what
happens next depends on the photos (amended before scoring, §9.1): if they were
unusable, RETAKE is the designed output and the case is excluded from the
level metrics and counted; if they were usable, it is an **unwarranted
RETAKE** and stays in the denominator as a miss. Without this rule a system
could dodge the primary endpoint by asking for photos.

**Paired tests** are computed only on cases scored for both systems (the two
may exclude different RETAKE cases).

**Secondary.**
- Over-triage rate, same method.
- Exact agreement.
- Linearly weighted κ (weights 1 − |i − j| / 3), with a percentile bootstrap
  95% CI, 2,000 resamples, seed 20260923.
- Per-level recall and precision, as a 4×4 confusion matrix.

**Head-to-head (`final` vs `rules`).** Exact McNemar on the discordant pairs
for under-triage, two-sided, α = 0.05. If fewer than 10 discordant pairs,
report the counts and the exact CI only and say the comparison is
underpowered; do not report a p-value alone. What "the counts and the exact
CI" means is fixed in §9.2.

**Operational.** Valid-output rate, retry rate, fallback-to-rules rate (bar:
≤ 1%), the `decided_by` distribution (how often the LLM's own level decided
the outcome), latency p50/p95 for the triage call, and stability: each of 20
pre-chosen held-out cases run 3 times plus 2 paraphrases, reporting the share
with an identical level. The 20 cases and the paraphrases are fixed in §9.3.

**End-to-end set.** Same metrics, plus error attribution for every case that
misses the key, into exactly one bucket:
1. interview — a needed question was never put;
2. extraction — the field came back null or wrong although the patient said
   it;
3. triage — fields correct, level wrong;
4. protocol gap — the key itself needed a criterion the protocol lacks.

Attribution is mine, from the logs, and I will have seen which system produced
the case, so it is not blind. Buckets 1–3 are counted against the system;
bucket 4 is counted against the protocol and sent to the dentist queue.

## 3a. The code ceiling, and what is left for the model

`protocol_check` against the key measures what code alone achieves. Everything
above that line is the LLM's contribution; everything below is a code bug.
Report the gap explicitly, because on triage-level cases it is small by
construction.

Dry-run numbers, `rules.py` and the protocol check against the 200 held-out
keys, measured 2026-09-23 with no model involved (`runs/review/dryrun_test5.py`):

| | under-triage | severe | missed EMERGENCY | over-triage | exact | weighted κ |
|---|---|---|---|---|---|---|
| rules.py (old baseline) | 51/200 = 25.5% (CI 19.6–32.1) | 31 | 25 | 10/200 = 5.0% | 69.5% | 0.595 (CI 0.50–0.68) |
| protocol check (code only) | 8/200 = 4.0% (CI 1.7–7.7) | 0 | 0 | 0/200 | 96.0% | 0.967 (CI 0.94–0.99) |

Both figures are explained entirely by what each system cannot see:

- **rules.py** misses the material added since it was written: the four
  extended floor flags (uncontrolled bleeding 5, feeling very unwell 5, fever
  5, pain-relief overdose 5) and chest pain 5 — that is all 25 missed
  emergencies — plus severe pain (7), pain after a recent extraction (5),
  persistent ulcer (3), pus (3), broken filling (5) and unusable photos (3).
  It is the correct baseline and it is *expected* to lose; the paper should say
  so rather than present it as a fair contest.
- **the protocol check** misses exactly the 8 narrative cases: 5 broken
  filling or crown without pain (S3), 3 pus or bad taste (U8). Nothing else.

**So on the triage-level held-out set the LLM can only change the outcome on
those 8 cases (4%), plus any case where it proposes something code then has to
override.** That is the honest size of the contribution this set can measure,
it was known before the run, and the report must state it next to any headline
agreement figure. The end-to-end set is where more is at stake, because the
interview and extraction can fail there.

## 4. Reporting template

One table per system: n, under-triage (count, rate, CI), severe under-triage,
missed EMERGENCY, over-triage, exact agreement, weighted κ (CI). Then the
operational table, then the attribution table for the end-to-end set. Every
table states n. No rate is reported without its denominator.

Alongside, three sentences that must appear:
1. the "SDCEP as encoded" caveat above;
2. "The vignettes assume the photo findings are correct; the detector catches
   about 29% of carious photos at the current threshold, so end-to-end
   accuracy on real patients is not measured here";
3. whichever of the caveats in §6 applies.

## 5. What the numbers may change (decided now)

- **Under-triage on held-out > 0:** classify by §3's buckets. Protocol gaps go
  to the dentist queue and the protocol, not to prompt tuning. Only
  triage-bucket errors count towards the fine-tuning trigger in the design §6.
- **`final` ≥ `rules` on under-triage, or no κ gain over `rules`:** that is the
  finding and it is reported as the headline. No extra held-out runs to find a
  better number.
- **Fallback rate > 1%:** the configuration fails on reliability regardless of
  its accuracy.
- **κ (key vs `final`) below the user's bar of 0.8:** the protocol or the
  prompt is revised on dev, and the held-out set is re-scored once, as a new
  configuration.
- Prompt or protocol changes made after a held-out run make every later run a
  new configuration; earlier numbers stay in the report.

## 6. Declared limits

- One key author (me) and no dentist: agreement with the protocol, not with
  care.
- Four of the protocol's levels rest on the user's decisions rather than a
  source (any swelling, any trauma, lingering or night pain, photo-only
  finding). Agreement on those cases measures obedience to a house rule.
- Structured criteria are decided by code, so on triage-level cases the
  `final` level is right by construction wherever a structured criterion
  holds. The informative parts are `llm_proposed`, the two narrative criteria,
  the injection cases and the end-to-end set.
- Synthetic patient words, written by a local model from my keys: phrasing is
  ours, not patients'. The P10 message set (§3.3 of the phase 1–2 plan) is the
  only real-phrasing check, and its flag mix is skewed.
- The P7 text check (model B) ran on a hosted API model (user's decision
  2026-09-23). Held-out vignette text was sent to that provider, and the
  check may not be repeatable if the model changes. Its stored outputs and
  recorded versions are the record.
- No exclusions after scoring. The only pre-declared exclusion is RETAKE from
  level metrics.

## 7. Secondary analysis: silver labels

**Closed 2026-09-23: the rubric missed both bars** (κ 0.269 blind, EMERGENCY
precision 8/40 = 20%), so there is no silver-label analysis. The failure is
reported as a negative result — see `docs/decisions.md` and plan §3.2. Nothing
in Test 5 depends on it.

## 8. Dry run, 2026-09-23

`runs/review/dryrun_test5.py` produced every table in this spec from the keys
and `rules.py`, with no model. Three things it changed:

1. **RETAKE had no scoring rule.** rules.py returned RETAKE on 3 held-out
   cases whose key is URGENT. §3 now fixes the rule.
2. **Paired tests need a common index set**, since two systems can exclude
   different cases.
3. **The code ceiling needed reporting** (§3a): without it, a 96% agreement
   figure would be read as the model's achievement.

The dry run is scratch, not the implementation; `src/check_triage.py` is
qa-engineer's and should reproduce these numbers on the same inputs as its
first sanity check.

## 9. Pre-scoring amendments, 2026-09-23

Made by research-pm in answer to qa-engineer's questions while aligning
`check_triage.py`, **before any held-out LLM scoring** and before P7 text
exists. Logged in `docs/decisions.md`. Nothing here was chosen after seeing a
held-out result; the only held-out runs so far are the no-model dry run in §8.

### 9.1 RETAKE with a SOON or ROUTINE key

No held-out key, triage-level or end-to-end, has unusable photos with a SOON
or ROUTINE level (the 4 unusable-photo keys are 3 URGENT, 1 EMERGENCY). So on
held-out, **every** RETAKE with a SOON or ROUTINE key is one the photos did
not call for. Excluding those would let a system make hard cases disappear
from every denominator, which is the dodge §3 exists to stop.

| Key | Photos | System says RETAKE → |
|---|---|---|
| EMERGENCY / URGENT | any | under-triage, severe (unchanged) |
| SOON / ROUTINE | unusable | designed output: excluded from level metrics, counted as a correct RETAKE in the photo-quality table (unchanged; only dev can have these) |
| SOON / ROUTINE | usable | **unwarranted RETAKE**: stays in n; counts as a disagreement in exact agreement and as a miss in that level's recall; is neither under- nor over-triage; is left out of weighted κ (it has no place on the scale) with the κ n stated. Reported as its own count with an exact CI. |

A system that returns a level where RETAKE was designed is scored on that
level against the key, as now.

### 9.2 The underpowered head-to-head

With fewer than 10 discordant pairs, report, on the common case set:
- n_common;
- b = cases only `final` under-triaged, c = cases only `rules`
  under-triaged;
- each system's under-triage count and Clopper-Pearson 95% CI on n_common;
- the Clopper-Pearson 95% CI for b / (b + c), the share of discordant pairs
  that go against `final` — the exact interval behind McNemar's test. Omit it
  when b + c = 0 and say so.

No p-value, and the sentence: "underpowered: fewer than 10 discordant pairs,
so no test of a difference is reported." Two per-system CIs that overlap do
not show the systems are equal, and the report must not say they do.
Expected in practice: the triage-level set will not be underpowered (the dry
run has `rules` under-triaging 51/200); the 60-case end-to-end set and dev
subsets may be.

### 9.3 The 20 stability cases and their paraphrases

The seeded pick in `check_triage.py` (5 per level) would spend 5 of 20
slots on EMERGENCY cases that the red-flag floor decides with no model call,
so they are stable by construction, and it drew none of the 8 narrative
cases, the only ones where the model can change the outcome (§3a). Replaced
by a stratified list of cases where the model is actually called, chosen
from key fields only (`labels/heldout/pick_stability.py`, seed 20260923):

- all 8 narrative-criterion cases (5 × S3, 3 × U8);
- 2 injection cases (1 SOON, 1 ROUTINE);
- 4 URGENT and 3 SOON boundary cases, seeded;
- 3 ROUTINE cases, one each of missing tooth, old fillings, all clear
  (no ROUTINE case outside the injection set is marked boundary).

Fixed list: `H032 H081 H095 H104 H108 H134 H178 H198 H080 H070 H115 H136 H101
H170 H090 H047 H010 H008 H124 H062` (SOON 9, URGENT 7, ROUTINE 4).

Stability is reported for `llm_proposed` and for `final`, as the share of the
20 whose five runs (3 repeats of `patient_words`, then 2 paraphrases) all give
the same level; repeats-only and paraphrases-only shares also reported. It
does not describe EMERGENCY cases, which never reach the model; say so.

Paraphrases are written in P7 by the same generator, prompt and style as the
case's `patient_words`, with seeds 20260923 + 1000 and + 2000, stored in the
key as `paraphrases`. They pass every P7 automatic check and the §6 blind
extraction, and are regenerated if their token Jaccard with the case's own
`patient_words` or the other paraphrase is above 0.8 (a near-copy measures
nothing).

### 9.4 The dev set (`llm/eval/triage_vignettes_dev.json`)

- **Keys: research-pm.** `labels/dev/build_dev_keys.py` →
  `labels/dev/triage_dev_keys.json`, tracked in git, same shape and the same
  protocol-consistency check as the held-out builder. 100 keys, 25 per level,
  ids `V001`–`V100`, seed 20260924. Same archetype coverage as held-out (the
  archetypes follow the protocol's criteria, which are public), plus at least
  4 SOON/ROUTINE keys with unusable photos so the designed RETAKE is
  exercised on dev. **Facts are newly written**: no fact string, tooth set or
  duration pattern is copied from held-out, and the builder refuses to write
  if any fact matches a held-out fact exactly.
- **Patient words: qa-engineer, inside the P7 run**, same generator, prompt,
  checks and §6 blind extraction, generator seeds 20260924 + attempt. Dev goes
  **first** in the GPU queue so llm-dev can tune on it while held-out text is
  being written.
- **Conversion: qa-engineer** writes `llm/eval/triage_vignettes_dev.json`
  from the dev keys plus text, to `llm/eval/triage_vignettes.schema.json`.
- llm-dev may read everything about dev. Nothing moves from held-out to dev:
  no text, no facts, no ids.

### 9.5 The H001 leak (pre-scoring note)

A crash in a scratch script printed held-out key H001 in full, and the level ×
photo-usable counts, to llm-dev (details in `docs/decisions.md`). Handled as
follows, decided before any held-out LLM scoring:

- **Exposed set: 6 keys, not 1.** H001's fact string is shared by every key of
  its archetype, so anything tuned towards it would reach all six. The ids
  are in `labels/heldout/leak_h001_sensitivity.json` (gitignored, so this
  tracked file does not pair ids with a level). No end-to-end key shares the
  fact. No P7 text existed yet, so no patient wording leaked.
- **Primary analysis unchanged: all 200.** Dropping cases is the kind of
  after-the-fact exclusion §6 forbids, and it is decided now, not after
  seeing a result.
- **Pre-declared sensitivity analysis:** every §3 headline metric also on the
  194 keys without the exposed six, reported next to the primary figure. If
  a conclusion differs between the two (e.g. the under-triage count, or κ
  crossing 0.8), report both and say the leak may matter.
- **What the leak can and cannot flatter.** The exposed keys are ROUTINE, so
  they cannot be under-triaged: the primary endpoint is unaffected by
  construction. Only over-triage, exact agreement and κ could be flattered,
  by at most 6/200.
- **Stability:** one exposed key (in the §9.3 list) stays in, since the
  list was fixed before the leak and swapping cases afterwards is itself a
  choice. Stability is also reported without it (19 cases).
- The level × photo-usable counts add nothing new: §9.1 of this tracked
  spec already states which levels the unusable-photo keys have.

### 9.6 End-to-end: the P7 opening (lead's decision, pre-scoring)

Production has no free-text opening before checklist A, so:

- **Headline condition: `--opening drop`**, which is what patients get. The
  P7 opening is not shown to the system.
- **Secondary, labelled as such: `--opening prepend`**, with the opening fed
  as the first patient message. It shows what an opening turn would add; it
  is not the product.
- Under `drop`, a miss on a narrative-only criterion (S3, U8) goes to bucket 1
  (interview): the words that would satisfy it had no place to be said.
- Expected size: the end-to-end set has 1 S3 and 1 U8 key.
  Under `drop`, the S3 case can never be detected: no pain means checklist A
  ends the interview. The U8 case has pain and reaches the chat, but no chat
  question asks about taste or discharge, so it is caught only if the patient
  volunteers it in a chat answer. P7's script answers are written per
  question and will rarely carry it.
- Superseded for scoring by §9.7 if protocol v0.2 ships before the held-out
  run: S3 and U8 then have checklist rows, and the interview can catch both.

### 9.7 Protocol v0.2 and the rebuilt keys (pre-scoring)

User decision 2026-09-23 (option 2): S3 (broken filling or tooth) and U8 (pus
or discharge) get checklist-A rows Q20 and Q21 and become **structured**
criteria. v0.2 has no narrative criteria left. Draft:
`docs/plans/protocol-v0.2/triage_protocol.yaml`. It goes live only when llm-dev
switches the loader, interface and interview together, and the Q20/Q21
wording is still waiting for the user's approval.

**Keys rebuilt** (held-out 200, end-to-end 60, dev 100), before any held-out
LLM run, by the same builders with the same seeds. Diffed against v0.1:
- ids, levels, styles, facts, visual summaries and every v0.1 symptom field
  are identical;
- two new checklist fields on every key (`broken_filling_or_tooth`,
  `pus_or_discharge`, schema 1.2). Yes on: broken filling keys (held-out 5 /
  e2e 1 / dev 3), pus keys (3 / 1 / 2), and minor-trauma keys, since a
  chipped tooth answers Yes to Q20 (3 / 1 / 2);
- `criteria_met` gains S3 on those minor-trauma keys (level stays EMERGENCY);
- every end-to-end key's `expected_questions` gains Q20 and Q21.

**What this changes in the analysis.**
- The cases file hash changes, so every held-out configuration is new,
  including the `rules` baseline, which must be re-run and logged. rules.py
  does not read the new fields, so its numbers should not move.
- §3a: the 8 cases the code check missed were exactly the narrative S3/U8
  cases. Under v0.2 the code check is expected to agree with all 200 keys. On
  the triage-level set the model then cannot improve on code at all. `final`
  can only differ from the key by over-triage, since code raises every lower
  proposal. The informative measures become `llm_proposed`, over-triage, the
  injection cases and the end-to-end set. Every report must say so next to any
  headline agreement figure.
- §9.3 stability list unchanged. The 8 former narrative cases still call the
  model, and swapping cases now would be a choice made after the leak (§9.5).
- §9.6 (`--opening drop`) stays the headline. Under v0.2, an S3 or U8 miss
  on the end-to-end set is a checklist or triage error, not a missing
  question.
- Not covered by any key: pus without pain, and a broken tooth with pain. The
  first is an open clinical question (Form C, C11). Keys for it are added
  only after the dentist answers, and on dev first.

### 9.8 Pain-severity errors by direction (pre-scoring, 2026-09-26)

Written before any held-out Test 5 scoring. Held-out P7 text generation was
running at the time, but no system under test had seen a held-out case.

**Background.** On 2026-09-26 the user defined the pain-severity levels
(`docs/decisions.md`, 2026-09-26):
- mild: the patient notices it, but it does not get in the way;
- moderate: it bothers them, but they still sleep and eat normally;
- severe: it stops them sleeping or eating, or they call it unbearable.

These are in the extraction instruction. There is no code guard: one was
tried and removed after two independent phrase sets. "Severe" satisfies U2
(URGENT), so an extraction error in this one field can move a level.

**What is added.** One extra block, **descriptive only**. It changes no
metric, denominator or pass bar, and nothing in the §3 attribution or §5:
- **False severe**: key mild or moderate, extracted severe. This raises
  urgency.
- **Missed severe**: key severe, extracted anything else, null included.
  This lowers urgency and is the more serious direction.
- Each is reported with case ids and an exact Clopper–Pearson 95% CI, over
  two denominators:
  - all eligible cells: in Test 3, headline cells whose key is not null;
    in the end-to-end set, cases that reach the chat;
  - the cells whose key has that value: mild or moderate for false severe,
    severe for missed severe.
- Extracted severe where the key is null is counted apart.
- **End-to-end only:** among cases whose extracted `pain_severity` differs
  from the key, how many end with a level more urgent (up) or less urgent
  (down) than the protocol gives on the key's own symptoms. This is
  reported for both `final` and `protocol_check`. RETAKE is not on this
  scale and is counted apart.
- **The triage-level set** feeds key symptoms, with no extraction, so none
  of this applies there.

**Test 3:** the held-out Test 3 sets B and C are spent. For Test 3, the
block applies to dev runs and to any new blind set.

Implemented by qa-engineer in `check_symptoms.py` and `check_e2e.py`
(`check_triage.py` is unchanged).
