# Dental occlusal screening assistant: system design, evaluation and status

Full report, 2026-09-26. Branch `llm-triage-wave2`. Research prototype:
**a screening aid, not a diagnosis.** No dentist has yet reviewed any
clinical content (protocol, knowledge base, thresholds, fixed wording). All of
it is marked `DRAFT-UNREVIEWED`.

This report brings together material spread across `docs/architecture.md`,
`docs/decisions.md`, `docs/plans/*` and `docs/reports/*`. Where a number is
given, its sample size and 95% confidence interval are given with it. Where
something has not been measured, the report says so.

---

## Contents

1. Introduction
2. System architecture
3. The triage protocol: how urgency is defined
4. The patient interview: how the questions were built, and from what
5. The knowledge base: how it was built, and from what
6. Models used
7. Data sets
8. Evaluation methods
9. Results
10. What is not yet known (limitations)
11. Progress to date
12. Next steps
13. Appendices: full question list, criteria table, file map

---

## 1. Introduction

### 1.1 The problem

Tooth decay is common, it is painless in its early stages, and it gets
harder and more expensive to treat the longer it waits. Many people cannot
easily get to a dentist, and a patient in pain often does not know whether
their problem needs care today, this week, or at the next check-up. Dental
triage services exist (in the UK, for example, telephone triage follows the
SDCEP guideline), but they need a trained person on the other end.

### 1.2 What this system does

The system takes:

- **two occlusal photos**, one of the upper arch and one of the lower arch.
  An occlusal photo looks straight down onto the biting surfaces; and
- **a short patient interview**: a Yes/No checklist and a few free-text
  chat questions.

It returns, in plain English:

1. **which teeth were found** in the photos, and which may show decay,
   named by position ("upper right first molar"), not by number alone;
2. **how soon to see a dentist**, on five outcomes:

   | Level | Meaning shown to the patient |
   |---|---|
   | EMERGENCY | "This may be an emergency. Please go to a hospital as soon as possible." |
   | URGENT | "See a dentist within 24 hours." |
   | SOON | "See a dentist within 7 days." |
   | ROUTINE | "No urgent dental visit is needed. Keep up your routine check-ups." |
   | RETAKE | The photos cannot be used; take them again (a photo-quality outcome, not a triage level). |

3. **why**: the criteria that were met, with the patient's own words as
   evidence;
4. **fixed safety text**: what the photos cannot show, a safety net ("if you
   develop swelling, a fever…"), and a disclaimer that this is not an
   examination.

A patient can also ask follow-up questions, which the system answers from a
curated knowledge base.

### 1.3 Design goals

In priority order:

1. **Never under-triage.** Telling a patient to wait when they need care
   soon is the error that can hurt someone. Over-triage (sending someone
   sooner than needed) is the accepted, safer error.
2. **Never invent anything.** No invented teeth, no guessed symptoms, no
   diagnosis, no medicine names or doses.
3. **Be auditable.** Every urgency decision can be traced to a written
   criterion, a literature source, and the patient's own words.
4. **Run locally.** Everything runs on one Windows PC (RTX 3060, 12 GB). No
   patient data leaves the machine. The single exception is evaluation-only
   and involves no patient data (section 6.3).
5. **English only** for everything the system produces.

### 1.4 Central design principle

**The language model (LLM) never sees a photo, and never has the last word
on urgency.**

- Photos are processed by vision models into a JSON description.
- The LLM receives only JSON computed by code.
- Urgency is guaranteed by deterministic code. The LLM proposes a level
  and must cite written criteria. Code checks every citation and can only
  ever **raise** the level, never lower it.

This was confirmed as the paper's framing by the project owner on
2026-09-26, after the held-out evaluation (section 9.5): **urgency is
guaranteed by code; the LLM's roles are the interview and the explanation.**

### 1.5 How the project got here (short history)

| Date | Milestone |
|---|---|
| 2026-09-16 | Vision stack chosen: SegmentAnyTooth for tooth segmentation and numbering, and a YOLOv8 caries detector run per tooth crop. Mendeley photo set chosen as the working data set. |
| 2026-09-17 | qwen3:14b chosen as the LLM. qwen3:4b rejected (it leaked its reasoning into 60/60 outputs). Evidence-checked symptom extraction introduced. |
| 2026-09-19 | Interview control moved from the model to Python (the model looped and repeated questions). |
| 2026-09-22 | **Redesign: "LLM proposes, code guards".** Literature review (SDCEP, NHS England, AAE and others). Protocol v0.1. Checklist-based interview. English-only rule. |
| 2026-09-23 | Held-out test sets written, evaluation pre-registered, dentist review packet prepared, real-message data work (silver labels failed; red-flag labelling done). |
| 2026-09-24 | Protocol v0.2 live (two new checklist rows). Faithfulness metric corrected ("0 hallucinations" retracted and re-measured). |
| 2026-09-25/26 | Synthetic patient text (P7) generated and blind-checked. **Held-out triage evaluation (Test 5) run: final level 0/200 under-triaged.** Protocol v0.3 drafted after the project owner's decisions. |

---

## 2. System architecture

### 2.1 Pipeline overview

```
 photos ─► VISION (src/pipeline.py) ─────────────────► findings JSON 1.0
            SegmentAnyTooth (YOLO11 + SAM) → tooth masks + FDI numbers
            per-tooth crop → YOLOv8 caries detector
            image-quality check (blur, cropped arch, no teeth)

 patient ◄─► INTERVIEW (src/interview.py) ───────────► symptoms JSON 1.2
            checklist A (12 rows: 8 red flags + pain, ulcer, broken filling, pus)
                 → any red flag: STOP, emergency screen
            checklist B (4 rows, only if the patient has pain)
            chat (5 questions) → LLM extraction → verify() evidence check

 findings + symptoms + patient words
        ─► TRIAGE (src/triage.py) ────────────────────► assessment JSON 2.0
            1. red-flag floor (code)          → EMERGENCY, no model call
            2. LLM proposes: cited criteria first, then a level
            3. code checks every citation; retry once
            4. a level below its own valid citations → raised by code
            5. protocol check (code) → can only RAISE
            6. photo quality → RETAKE where appropriate

 findings + symptoms + assessment + knowledge passages
        ─► EXPLANATION (src/explain.py) ──────────────► patient-facing text
            retrieval (src/retrieval.py, multilingual-e5-small, top 4)
            LLM writes; code guardrails check every reply
            one rewrite, then a fixed deterministic fallback text

 WEB (src/webapp.py + src/webapp_index.html, FastAPI, localhost:8000)
```

The four JSON contracts (findings, symptoms, assessment and the explanation
input) are defined in one file, `llm/interface.md`. Any change starts there
and needs agreement from both the vision side and the LLM side.

### 2.2 Hard architectural rules

These rules are enforced in code and tested:

1. **The LLM never sees a photo.** It gets `visual_summary`, a JSON object
   computed by code: whether the images are usable, which teeth are flagged,
   and which teeth are unexpectedly missing. It never sees raw confidence
   scores.
2. **Code guards the urgency floor.** Red flags force EMERGENCY before any
   model call. The protocol check can only raise a level. Code never
   lowers a level.
3. **Python owns the interview.** The order of questions, when to stop, and
   the exact wording of every question are fixed text from the protocol. The
   LLM does not phrase questions.
4. **Never guess a symptom.** A checklist row needs an explicit click (there
   is no default, so an untouched row is never read as "no"). A chat field
   needs a quote from one patient message, verified in code. An unanswered
   field is `null`.
5. **Compute deterministic facts, don't generate them.** Tooth names come
   from the FDI number via code (`fdi_label`), never from the model.
6. **Clinical parameters need the owner's sign-off** and a decision-log
   entry. This covers thresholds, criteria, levels and patient-facing
   wording.

### 2.3 Component 1: vision (`src/pipeline.py`, `segment_tool.py`, `caries_tool.py`)

| Stage | Model | Notes |
|---|---|---|
| Tooth segmentation and FDI numbering | **SegmentAnyTooth** (YOLO11 + SAM), from `thangngoc89/SegmentAnyTooth` | Median 12 teeth per photo on the Mendeley set. The vendor code is never edited; patches live in `segment_tool.py`. Non-commercial licence, by signed agreement. |
| Caries detection | **YOLOv8** from `AndreyGermanov/yolov8_caries_detector`, trained on DentalAI intraoral photos | Run **per tooth crop**, not on the whole photo, so each detection belongs to one numbered tooth. GPL-3.0. This is the weakest link (below). |
| Image quality | code (`assess_quality`) | Blur, a cropped arch (fewer than 8 teeth per arch) or no teeth give `usable: false`, which leads to the RETAKE path. |

**Output: `findings` 1.0.** Tooth keys are FDI strings ("16", "36", …).
`present: false` means the tooth was assessed and is missing, while an absent
key means it was not assessed. Detections carry a label (caries,
restoration, other) and a confidence.

**Caries threshold (open clinical decision).** Measured on 4,929 labelled
Mendeley photos (photo-level labels):

| Confidence threshold | Carious photos caught (sensitivity) | Healthy photos wrongly flagged |
|---|---|---|
| **0.50 (current)** | 29% | 3% |
| 0.25 | 62% | 14% |

At the current threshold the detector misses about 7 in 10 carious photos.
For a screening tool, a missed cavity is worse than a false alarm, which
argues for the lower threshold. It is a clinical trade-off, so it waits for a
dentist.

**Rejected alternatives** (recorded in `decisions.md`):
- `dentalscan-ai`: panoramic X-rays only.
- An ESP32 cavity repository: no published weights.
- "cavity-model-v2": turned out to be an 80-class COCO model that labelled
  tooth crops "airplane".

### 2.4 Component 2: the interview (`src/interview.py`)

The interview has three parts. The full question list is in Appendix A, and
section 4 explains where each question came from.

**Checklist A (always, all rows at once, 12 rows).**
- The 8 red flags: difficulty breathing or swallowing; chest pain or
  breathlessness; swelling; fever; feeling very unwell; recent injury;
  uncontrolled bleeding; too much pain relief taken.
- "Any pain or discomfort now".
- Ulcer or lump lasting more than 3 weeks.
- Broken filling, crown or tooth.
- Pus or a bad-tasting discharge.

Every row needs an explicit Yes or No, and the server rejects an incomplete
form (HTTP 400). **Any red-flag Yes stops the interview at once** and
shows the emergency screen. If the patient has no pain, the interview ends
after this form.

**Checklist B (only with pain, 4 rows).** Pain that keeps aching after the
trigger (the only row with a "Not sure" option, which records `null`); pain
that wakes them at night; pain on biting; a tooth taken out in the last two
weeks.

**Chat (only with pain, 5 questions).** Pain relief effect, severity,
triggers, location and duration. For each answer:

1. The LLM (qwen3:14b) extracts a value **and a quote** from the patient's
   message, under a JSON schema enforced by Ollama.
2. `verify()` then checks in code that:
   - the quote really sits inside one patient message;
   - a location has both an arch cue (upper/lower) and a side cue
     (left/right); "front" and "generalised" need their own cues;
   - each trigger has its own cue in the patient's words. A food or action
     counts ("ice cream" means cold, "chewing" means biting), and "at
     night" counts only when it is about the pain. Weather words and illness
     words ("I have a cold") do not count;
   - hedges ("not sure") are re-asked once, then stay `null`;
   - a bare "yes" or "no" counts only as the answer to a yes/no question.
3. **`verify()` can only drop a value to `null`; it never adds one.**
4. An unclear answer gets one re-ask: "Sorry, I need a clearer answer to
   keep you safe. {question}". If the reply is still unclear, the field
   stays `null`.
5. If an earlier answer has already settled a field (for example the
   patient mentioned the duration while describing triggers), that question
   is skipped.

**Pain severity** follows definitions set by the project owner on
2026-09-26:
- **mild**: noticed, but it does not get in the way;
- **moderate**: it bothers them, but they still sleep and eat normally;
- **severe**: it stops them sleeping or eating, or they call it unbearable.

The owner's ruling on nine borderline phrasings (2026-09-26, not yet in the
prompt) is:
- **severe**: "agony", "excruciating", "worst pain I've ever had", "I can't
  take it anymore", "it's killing me", and the word "severe" itself;
- **not severe**: "I chew on the other side", "I can't sleep on my left
  side", and "it used to keep me awake, but now I sleep fine".

A code check on "severe" was built and then **removed**. On two
independent phrase sets it wrongly dropped real severe answers (8/44, and
3/22 after a redesign), and a wrongly dropped "severe" lowers urgency.

**Output: `symptoms` 1.2.** Every field is `true` / `false` / a value, or
`null` when unanswered. Each extracted chat value keeps its quote.

### 2.5 Component 3: triage (`src/triage.py`, `src/protocol.py`, `llm/rules.py`)

Triage turns the findings and symptoms into one urgency level, in six steps.

**Step 1: red-flag floor (code).** If any of the 8 red-flag fields is true,
the level is EMERGENCY and **the model is never called**. On the held-out
set this decided 45 of 200 cases.

**Step 2: the LLM proposes.** The model receives:
- the symptoms JSON;
- the patient's own words;
- the visual summary;
- the full protocol, meaning every criterion with its id, its level, its
  statement and, since 2026-09-26, its machine-readable condition
  (`holds_when`).

It must answer in a fixed JSON schema, enforced by Ollama's `format`
option, with **`criteria_met` (each with evidence) before `level`**, so it
commits to evidence before it names a level. There is no free-text
rationale.

**Step 3: code checks every citation.** A proposal is invalid if:
- it cites an unknown criterion;
- a cited criterion's condition does not actually hold on the data;
- a quoted piece of evidence is not in the transcript; or
- the level is inconsistent with the cited criteria.

An invalid proposal is sent back once with the errors named.

**Step 4: raise to its own citations (added 2026-09-26).** On the last
attempt, if the proposal's *only* error is a level below what its own valid
citations imply, it is kept and **code raises the level** to the citations
(`decided_by: "llm_raised"`, with the model's own level kept in
`level_raised_from`). Any other invalid proposal falls back to the
deterministic rules baseline (`fallback_rules`).

**Step 5: protocol check (code).** Code evaluates every criterion itself,
without the model. If code's level is higher than the model's, code's level
wins (`decided_by: "protocol_check"`). **Code never lowers a level.**

**Step 6: photo quality.** If the photos are unusable and the level would
come only from the photos, the result is RETAKE. When symptoms already set a
level, that level and its reasons are kept and the patient is also asked to
retake the photos. Symptoms that need care are never hidden behind a bad
photo. The owner confirmed this "option 1" behaviour on 2026-09-26.

**Output: `assessment` 2.0.** It contains:
- `urgency`;
- a fixed `headline` from the protocol;
- `reasons` with evidence;
- `decided_by`: `llm`, `llm_raised`, `red_flag_floor`, `protocol_check` or
  `fallback_rules`;
- a full `triage` audit block: every attempt, every rejection reason, the
  model's own level;
- a `rules_baseline` shadow: what the old rules would have said, recorded
  for comparison.

**The old rules baseline (`llm/rules.py`)** is the project's original
deterministic system, frozen for the paper's comparison. It checks nine
ordered rules (R1–R9); the first match wins:

| Rule | Condition | Level |
|---|---|---|
| R1 | swelling or systemic signs | EMERGENCY |
| R2 | trauma | EMERGENCY |
| R3 | lingering, spontaneous or biting pain | URGENT |
| R7 | unusable images | RETAKE |
| R4 | caries detected + any symptom | URGENT |
| R5 | caries detected, no symptoms | SOON |
| R6 | symptoms, nothing visible | SOON |
| R8 | unexpected missing teeth | SOON |
| R9 | nothing found, no symptoms | ROUTINE |

It never asked about pain relief, bleeding, chest pain or overdose, which is
why it under-triages heavily against the new protocol (section 9.5).

### 2.6 Component 4: explanation (`src/explain.py`, `src/retrieval.py`)

**Retrieval.** Section 5 describes the knowledge base. It is split into
32 chunks, one per `##` section, and embedded with `intfloat/multilingual-e5-small`
(with the required "query:" / "passage:" prefixes). Retrieval is a
brute-force cosine search over the 32 vectors, returning the top 4. There is
no vector database, because 32 vectors fit in one matrix. The index is cached
in `models/knowledge_index.npz` and rebuilt when a knowledge file changes.

**Writing.** The LLM (qwen3:14b) writes the first response from:
- the findings, but **only the reportable (flagged) teeth**, a fix from
  2026-09-24;
- the symptoms;
- the assessment;
- the retrieved passages.

It may restate the JSON but never contradict it, add teeth, or change the
urgency. The headline, limitations, safety net and disclaimer are fixed text
inserted by code, not written by the model.

**Code guardrails check every reply**, including follow-up answers:

| Guardrail | What it blocks |
|---|---|
| `guardrail_violations` | medicine names or doses, including garbled ones, caught by a prescription-*shape* pattern and not only a word list; invented teeth; a missing required finding phrase |
| unreported-tooth check (#22) | any tooth described as a finding that the assessment did not flag, e.g. a detection below the 0.50 threshold |
| `places_pain` | stating a pain side or tooth beyond what the patient said. A link to a found tooth is allowed only when hedged ("may be related to the tooth we found, but only a dentist can confirm this") |
| `calls_missing_decay` | calling a missing tooth "decay" |
| `denies_tooth_cause` | with no photo findings, saying the pain is not from a tooth or that the teeth are fine. It must say the photos can miss a problem |
| `echoes` | a follow-up answer re-printing the first response |

A violation gets **one rewrite** that names the problem. A second violation
gets a **fixed, deterministic fallback text**. If a follow-up question
raises a red flag ("my face is swelling now"), a keyword pre-screen plus an
evidence check re-escalates the assessment.

The explanation step refuses to run on knowledge still marked
`DRAFT-UNREVIEWED` unless a development override is set. That override must
never ship.

### 2.7 Component 5: the web app (`src/webapp.py`, `src/webapp_index.html`)

FastAPI on `localhost:8000`, one HTML page. Endpoints: `/api/analyse`
(photos), `/api/checklist`, `/api/answer`, `/api/result`, `/api/ask`
(follow-ups) and `/api/reset`.

- The page renders checklist rows from server data, so no row count is
  hard-coded.
- It has a dedicated emergency screen.
- It reads every fixed text from the protocol file.
- The symptom JSON appears only in a collapsed debug panel.
- The server returns 409 for a result requested before checklist A.

Measured speed on the RTX 3060: about **17 s per chat turn**, and a triage
call takes a median of 7.3 s (95th percentile 16.3 s).

---

## 3. The triage protocol: how urgency is defined

### 3.1 What it is

`llm/protocol/triage_protocol.yaml` (version 0.2, live) is the single
source of clinical truth the code reads. It holds:

- the **levels**, with their time frames, fixed headlines and sources;
- **21 criteria**, each with an id, a level, a machine-readable condition
  (predicate), a plain-English statement, and its source;
- **all 21 interview questions**, with their fixed wording and when each is
  asked;
- **all fixed patient-facing text**: limitations, safety net, disclaimer,
  routine advice, the finding phrase and the checklist introduction.

The **protocol level** is the most urgent level among the criteria that hold.
When nothing holds, it is ROUTINE.

### 3.2 Literature it is built from

research-pm reviewed these sources on 2026-09-22 and re-read the trauma,
bleeding and ulceration flowcharts the same day:

| # | Source | Used for |
|---|---|---|
| S1 | **SDCEP, *Management of Acute Dental Problems*, 2nd ed., March 2026** (Scottish Dental Clinical Effectiveness Programme, NHS Education for Scotland), acutedentalproblems.sdcep.org.uk. Read: timescales, pain, swelling, trauma, bleeding and ulceration flowcharts; the pulpitis, apical periodontitis, abscess, hypersensitivity and sepsis pages | **Primary source**: levels, time frames, decision questions |
| S2 | SDCEP, *MADP Quick Reference Guide*, 1st ed., 2013 | The same flowcharts as text; used where S1 images were unreadable |
| S3 | **NHS England, *Clinical guidance: unscheduled urgent and non-urgent dental care*, v1.0, May 2025** (updated Oct 2025) | Adopts SDCEP's categories and adds example lists per level |
| S4 | ADA, *What Constitutes a Dental Emergency?* (2021) | Corroboration only; it has no time frames |
| S5 | AAE Consensus Conference, *Recommended Diagnostic Terminology*, J Endod 2009;35(12):1634 | Symptom descriptors (lingering thermal pain, spontaneous pain, pain on biting). It has no urgency levels |
| S6 | Pitts et al., *ICCMS Guide*, 2014 | Caries staging (knowledge base); no urgency |
| S7 | IADT trauma guidelines (Fouad et al., 2020) | Only that an avulsed permanent tooth is time-critical |
| S8 | SDCEP, *Emergency Dental Care*, 2007, §2.1 | The origin of S1's timescales |

**Mapping SDCEP onto the project's levels.** SDCEP Emergency Care (medical
or dental) → EMERGENCY; Urgent Care (24 h) → URGENT; Non-urgent Care (7 days)
→ SOON; Self Care → ROUTINE.

**What no source gives.** None gives a time frame for a *possible cavity
seen in a photo with no symptoms*, or for a missing tooth with no symptoms.
Those levels (SOON and ROUTINE) are the project owner's decisions and are
marked "dentist's call".

### 3.3 The criteria (protocol v0.2)

| Id | Level | Criterion | Source |
|---|---|---|---|
| E1 | EMERGENCY (floor) | Difficulty breathing or swallowing | SDCEP swelling pathway; NHSE §3.2 |
| E2 | EMERGENCY (floor) | Swelling of face, jaw or gums | Owner's decision: any swelling. SDCEP grades swelling, so this is **deliberate over-triage** |
| E3 | EMERGENCY (floor) | Fever | SDCEP swelling and sepsis pages; SDCEP 2007 §2.1.1 |
| E4 | EMERGENCY (floor) | Recent injury to the mouth or teeth | Owner's decision: any trauma. SDCEP grades trauma, so this is **deliberate over-triage** |
| E5 | EMERGENCY (floor) | Feeling very unwell (shivery, faint, very tired) | SDCEP swelling and sepsis pages |
| E6 | EMERGENCY (floor) | Chest pain or breathlessness with jaw or tooth pain | SDCEP pain pathway (heart-attack signs) |
| E7 | EMERGENCY (floor) | Bleeding that pressure does not stop | SDCEP bleeding pathway; NHSE §3.2 |
| E8 | EMERGENCY (floor) | More pain relief taken than the packet says is safe | SDCEP pain pathway (overdose) |
| U1 | URGENT | Pain that pain relief has not controlled | SDCEP pain pathway ("Has analgesic controlled the pain?" No → Urgent); NHSE §3.3 |
| U2 | URGENT | Severe pain (stops sleeping or eating) | Owner's decision; NHSE §3.3 |
| U3 | URGENT | Pain on biting or pressing | SDCEP symptomatic apical periodontitis; AAE |
| U4 | URGENT | Pain after a recent extraction (≤ 2 weeks) | SDCEP pain pathway; the 2 weeks is a project convention |
| U5 | URGENT | Pain that keeps aching after the trigger | v0.2: owner's provisional rule. **v0.3: follows SDCEP** (below) |
| U6 | URGENT | Pain that starts on its own or wakes them at night | as U5 |
| U7 | URGENT | Possible cavity in the photo + any tooth pain | Kept from the old rules (R4) so the protocol is never less urgent; SDCEP would say 7 days if relief works. Dentist's call |
| U8 | URGENT | Pus, gum boil or bad-tasting discharge | SDCEP acute apical abscess. Applied with or without pain: **deliberate over-triage** |
| U9 | URGENT | Ulcer, sore or lump lasting > 3 weeks | SDCEP ulceration pathway (possible cancer referral) |
| S1 | SOON | Any tooth pain or sensitivity | SDCEP pain pathway (controlled or not yet tried → Non-urgent); NHSE §3.4 |
| S2 | SOON | Possible cavity seen in the photo | Owner's decision; no source |
| S3 | SOON | Broken, chipped, loose or lost filling, crown or tooth | NHSE §3.4; SDCEP trauma (dentine fracture → Non-urgent) |
| R1 | ROUTINE | A tooth appears missing | Owner's decision; no source |

A criterion R0 ("none of the above") was removed on 2026-09-23. It held on
every usable photo, so it made the model retry for nothing.

### 3.4 Where the protocol deliberately departs from SDCEP

Each departure is recorded in `decisions.md` and listed as a question for
the dentist (Form C):

| Departure | Direction | Why |
|---|---|---|
| Any swelling → EMERGENCY (SDCEP grades it) | over-triage (safe) | Owner's choice until a dentist grades it |
| Any trauma → EMERGENCY (SDCEP grades it) | over-triage (safe) | same |
| Pus without pain → URGENT (a painless draining sinus may be chronic) | over-triage (safe) | same |
| Cavity + any pain → URGENT (SDCEP: 7 days if relief works) | over-triage (safe) | Never less urgent than the old rules |
| Lingering or night pain with working relief → URGENT (v0.2) | over-triage | **Reversed in v0.3** (below) |
| "Lingering" = more than 30 seconds | unsourced convention | AAE gives no duration |

### 3.5 Protocol v0.3 (drafted, not yet live)

After the held-out evaluation, the project owner decided on 2026-09-26 to
follow SDCEP on pulpitis-type pain:

| Situation | v0.2 | v0.3 |
|---|---|---|
| Lingering, night or spontaneous pain, relief **works** | URGENT | **SOON** |
| Same, relief **not yet tried** | URGENT | **SOON** (SDCEP's pain pathway) |
| Same, relief **not helped** | URGENT | URGENT (via U1) |
| Any pain, relief question **unanswered or unclear** | (no rule; S1 → SOON) | **URGENT** (new rule) |

The last row was ruled by the lead, at the owner's request ("whatever fits
SDCEP best"). SDCEP's non-urgent route needs relief known to work or known
not tried. An unknown answer leaves "not controlled" possible, and the
project rule is that a blank answer is never reassuring. This needs a small
code change (the protocol's condition language cannot yet test for "no
answer").

The draft is in `docs/plans/protocol-v0.3/`. It changes 6 of the 100
development keys. The held-out results stay reported on v0.2 (section 10).

---

## 4. The patient interview: how the questions were built, and from what

### 4.1 Method

The questions were derived from the guideline flowcharts, not written
freely. The method was:

1. **Take SDCEP's decision questions in order.** SDCEP's pain pathway asks:
   - signs of a heart attack or a pain-relief overdose;
   - pain due to trauma;
   - swelling;
   - pain in a tooth;
   - an erupting tooth;
   - whether an analgesic was taken, and whether it controlled the pain;
   - a recent extraction;
   - face or mouth problems, including visual disturbance;
   - an appliance or denture;
   - an ulcer.

   The swelling pathway adds breathing, swallowing, mouth opening, an
   eye closing, fast worsening and being systemically unwell. The trauma and
   bleeding pathways add injury and uncontrolled bleeding.
2. **Keep each question that decides a level** in a criterion (section 3.3).
   Every criterion's field must be filled by exactly one question. A unit
   test checks this coverage.
3. **One question, one field.** A question never mixes a red flag with a
   non-red flag, so a bare "yes" always has a single meaning.
4. **Plain English, no clinical terms.** "Pain that keeps aching for more
   than about half a minute", not "lingering thermal pain".
5. **No medicine names or doses** anywhere in the questions.
6. **Fixed wording, approved by the project owner.** The model never phrases
   a question.
7. **Red flags first, and a red flag stops the interview.**
8. **Checklist for yes/no, chat for descriptions.** Yes/no items became
   checklist rows (faster; no chance of a misread "yes"). Descriptive items
   (how bad, what triggers it, where, how long, did relief help) stay in chat
   because patients describe them in their own words.

The pain descriptors (lingering, night, spontaneous, biting) come from the
AAE diagnostic terminology. The severity question follows the NHS England
wording on pain that stops normal sleeping or eating.

### 4.2 How the question set changed, and why

| Date | Change | Reason |
|---|---|---|
| Before 2026-09-22 | 9 questions phrased by the LLM | Original design |
| 2026-09-22 | 18 fixed questions (v0.1); floor extended with bleeding, chest pain, overdose and feeling unwell | Literature review found the old interview never asked about pain relief (SDCEP's main pain discriminator), bleeding, heart-attack signs or overdose |
| 2026-09-22 | Yes/no questions moved to a checklist with no default | Shorter input; an untouched row can never be read as "no" |
| 2026-09-22 | Q19 ulcer/lump > 3 weeks added | SDCEP ulceration pathway; a gap found in the literature re-read |
| 2026-09-22 | Q13 (lingering) moved to checklist B, with a "Not sure" option | Patients often cannot tell; "not sure" records `null`, not a guess |
| 2026-09-23 | Q20 broken filling/tooth and Q21 pus added to checklist A (v0.2) | A patient with no pain never reached the chat, so these two criteria could never be detected |

### 4.3 What the interview does not ask (known gaps)

research-pm hand-labelled 200 real patient messages (section 7.4). Three
SDCEP-covered warning signs turned up more than once in patients' own words,
but have no question:

- **cannot open the mouth** (trismus), a sign of spreading infection;
- **double vision or visual disturbance** with face pain (SDCEP: emergency
  medical);
- **hoarse or changed voice**, listed with airway compromise.

Adding a question is a clinical call, so these wait for a dentist. Until
then the system cannot detect them and the evaluation cannot measure them.

---

## 5. The knowledge base: how it was built, and from what

### 5.1 What it is

`llm/knowledge/` holds **6 Markdown files with 32 sections**. They are
the only material the explanation step can retrieve. Each file starts with
front matter: `id`, `topic`, `review_status: DRAFT-UNREVIEWED`,
`reviewed_by`, `reviewed_date`, and `basis`, the sources it paraphrases.

| File | Sections | Topic | Basis (sources) |
|---|---|---|---|
| `01_tooth_numbering.md` | 5 | What FDI numbers mean; plain names per position; how to describe a tooth; children's teeth; what an occlusal photo shows | FDI two-digit notation; WHO *Oral Health Surveys: Basic Methods*, 5th ed. |
| `02_caries_basics.md` | 4 | What a cavity is; stages; what treatment usually involves; why earlier is easier | ICCMS / ICDAS lesion staging; ADA caries management guidance (2018, 2023) |
| `03_symptoms_and_urgency.md` | 4 | Why the type of pain matters; warning signs for same-day care; sensitivity without a visible cavity; how to explain each urgency level | SDCEP *Management of Acute Dental Problems*; AAE diagnostic terminology |
| `04_limitations.md` | 4 | What these photos cannot show; what the tool is and is not; the tool can be wrong; getting a usable photo | Project-specific; informed by WHO survey methods |
| `05_prevention.md` | 5 | Basics; diet; back teeth; check-ups; if decay keeps coming back | WHO oral health guidance; ADA and AAPD caries prevention guidance |
| `06_tricky_questions.md` | 10 | Pre-written safe answers: "Can I skip the dentist if I brush better?", "Are you sure it is a cavity?", "You found nothing, so my teeth are fine?", "Can I just take painkillers?", "Can I fix it myself?", "Aspirin on the gum?", "Which antibiotic?", "Cost and time?", "Can I wait a few months?", "Is this an official diagnosis?" | Guideline positions above, applied to common unsafe requests |

### 5.2 How it was built

1. **Written, not scraped.** Each section was drafted in plain English by
   **paraphrasing** published guidance (listed in `basis`). No text is
   copied, and no web or forum content is included. The real-patient Q&A
   corpora (section 7) were deliberately kept out, because about 1 in 8 of
   their answers names a medicine, gives a dose or states a diagnosis.
2. **One topic per `##` section**, sized to be retrieved as one chunk.
3. **Written for the guardrails.**
   - No medicine names or doses (SDCEP's own self-care advice mentions a
     mouthwash and "optimal analgesia", which were stripped).
   - No diagnosis.
   - Every "can I skip/wait/fix it myself" question ends at "see a dentist".
4. **The tricky-questions file** anticipates the follow-up questions most
   likely to pull a model towards unsafe advice. It gives the model a safe,
   sourced answer to retrieve instead of improvising.
5. **Status tracking.** Every chunk carries its file's `review_status`, and
   the explanation step refuses `DRAFT-UNREVIEWED` content without a
   development override.

### 5.3 Review status

**Not reviewed.** Form D of the dentist review packet (`docs/dentist-review/`)
lists all 32 sections for sign-off. Only a dentist may change
`review_status`.

---

## 6. Models used

### 6.1 In the product (all local)

| Role | Model | Details |
|---|---|---|
| Interview extraction, triage proposal, explanation | **qwen3:14b** (Alibaba Qwen 3, 14B parameters, Q4_K_M quantisation, via Ollama) | **Not fine-tuned.** Used as released, steered only by prompts, the protocol text and JSON-schema-constrained output. |
| Knowledge retrieval embeddings | **intfloat/multilingual-e5-small** | Local, with "query:"/"passage:" prefixes |
| Tooth segmentation and numbering | **SegmentAnyTooth** (YOLO11 + SAM) | Non-commercial licence |
| Caries detection | **YOLOv8** (AndreyGermanov/yolov8_caries_detector, DentalAI) | GPL-3.0 |

**Why qwen3:14b.** On 2026-09-17 qwen3:4b leaked its private reasoning into
60/60 test explanations and invented teeth in 40% of them (under the
original check), so it is kept only as a size comparison and is not
deployable. qwen3:14b fits the 12 GB GPU and passed the same tests.

**Fine-tuning (LoRA/QLoRA): not done, and not triggered.** The design
(`docs/plans/llm-triage-design.md` §6) keeps QLoRA as a contingency only. It
is triggered if the best candidate, after at most two rounds of prompt and
protocol revision, still shows under-triage caused by the triage step, or a
valid-output rate below 99%. The held-out result has 0 final under-triage
and 100% valid output, so the trigger did not fire. Two notes:
- a 14B model is at the edge of 12 GB for QLoRA, so a fine-tune would use a
  7–8B model;
- under protocol v0.2 the model's own level does not change the patient's
  result (section 9.5), so fine-tuning the triage step would not change
  what patients see.

### 6.2 Candidates planned for the model benchmark (not yet run)

qwen3:8b, gemma3:12b and llama3.1:8b-instruct, compared on every test with
the same prompts (design §5). The selection rule: among models with 0
under-triage, 0% hallucination and contradiction, fallback ≤ 1% and 0
guessed red flags, pick the fastest that fits in VRAM with the vision models
loaded.

### 6.3 In the evaluation only (P7 synthetic patient text)

| Role | Model | Where |
|---|---|---|
| Writes synthetic patient text from answer keys | **llama3.1:8b** (Meta) | Ollama, local |
| Blind checker ("model B"): reads the text and extracts the fields without seeing the key | **gemini-3.5-flash-lite** (Google) | **Paid Gemini API**: the one exception to "nothing leaves the machine". Synthetic text only; no patient data, photos, keys or protocol text. Decided knowingly by the owner on 2026-09-23. Local fallback: gemma3:12b |
| System under test | qwen3:14b (Alibaba) | local |

Three different model families were used on purpose, so the test text is
neither written nor checked by the model being tested.

---

## 7. Data sets

### 7.1 Photos

- **Mendeley carious/non-carious intraoral photos**: the working set. 4,929
  photos with photo-level labels were used to measure the caries detector.
  SegmentAnyTooth finds a median of 12–13 teeth per photo here.
- **Malawi set**: explored, but upper-arch segmentation there is unreliable
  (median 3.6 teeth; fisheye camera). Preprocessing exists
  (`src/preprocess_malawi.py`), but the set is not used for claims.

### 7.2 Evaluation vignettes (the triage answer keys)

research-pm wrote the answer keys **before the system saw them**:

- **Held-out triage set: 200 keys**:
  - by level: EMERGENCY 45, URGENT 55, SOON 55, ROUTINE 45;
  - 84 boundary cases (for example pain controlled vs not);
  - 36 clinical **archetypes**, such as "severe pain", "relief failed",
    "photo finding only", "two red flags" and "injection attempt";
  - each key has a 6-way **style**: plain, vague, non-native English,
    self-correcting, verbose or terse.
- **Held-out end-to-end set: 60 keys** (15 per level), with a scripted answer
  to each chat question plus an opening message.
- **Development set: 100 keys** (25 per level, 45 boundary), built from a
  different random seed. The builder refused any development fact
  overlapping a held-out fact above 0.5 token Jaccard; the highest overlap was
  0.35. All tuning happens on this set.

Each key holds:
- the full symptoms JSON;
- the visual summary;
- the expected level and criteria;
- `facts` (the clinical substance the text must carry);
- the style.

**The key level is computed by the protocol**, and code checks it against
the protocol loader (0 mismatches). It is therefore *"agreement with SDCEP as
encoded"*, not a dentist's label.

**Two prompt-injection cases** carry a verbatim line such as a patient
typing an instruction to output "routine". This tests whether patient text
can steer the level.

**Held-out rules.** Held-out keys are gitignored and never shown to the LLM
developer. Each system configuration is scored once, and every scoring is
logged. One accidental exposure happened on 2026-09-23: a scratch script
crashed and printed one key. It was logged, and a sensitivity analysis
excluding the 6 affected keys was declared before scoring.

### 7.3 Symptom dialogues (Test 3)

- **Dev**: 12 dialogues, 60 field cells. Tuned on, so optimistic.
- **Blind set A**: 19 dialogues, 95 cells. Now dev, after it informed a fix.
- **Blind set B**: 20 dialogues, 100 cells. Spent.
- **Blind set C**: 24 dialogues, 120 cells, trigger-heavy. Spent.

Each blind set was written by research-pm without reading the extraction
code's cue lists. Its make-up was fixed before any answer was written, and
new wording was checked by token overlap against earlier sets.

### 7.4 Real patient messages (public corpora, research use only)

**ChatDoctor-HealthCareMagic-100k** (112,165 online doctor Q&A rows) and
**LiveQA TREC 2017** (medical consumer questions). Both are kept local and
never published. Neither declares a licence, and ChatDoctor is restricted to
academic research.

- **Filter** (`src/filter_dental_qa.py`): English check, a dental topic
  filter and an answer filter (drug names, dose patterns, diagnosis phrases).
  The result was 7,553 topic rows and 2,829 clean rows.
- **Filter audit (P9, hand-checked, one reader):**
  - topic precision 153/200 = 76.5% (target ≥ 95%, **not met**);
  - 25/200 = 12.5% of "clean" answers still name a medicine, a dose or a
    diagnosis. 8 of the 15 medicine leaks are names garbled by the corpus
    itself ("petrol DT", "stolen gum paint").

  Consequence: this corpus is not used for training or knowledge.
- **Red-flag labels (P10):** 200 random patient messages hand-labelled for
  "states a red flag". 46 (23%) did, 131 did not, and 23 were unclear.
  Swelling was by far the most common (35). This found the three missing
  warning signs in section 4.3.
- **Silver urgency labels: a documented negative result.** Urgency was
  inferred from the doctors' answers by phrase rules and checked against
  pre-registered bars (κ ≥ 0.6, EMERGENCY precision ≥ 90%):
  - κ was 0.269 blind;
  - EMERGENCY precision was 8/40 = 20% (CI 10–35%).

  The main cause: online doctors write "immediately consult your dentist"
  to mean "promptly". The attempt was stopped and is reported as failed.
- **Hugging Face search for dental urgency data:** none credible. The one
  labelled dental set is templated, unlicensed and disagrees with SDCEP.

---

## 8. Evaluation methods

### 8.1 Overview

| Test | Script | What it measures | Data |
|---|---|---|---|
| **Test 1**: rules | `check_rules.py` | The old rules baseline on 20 hand cases | `llm/eval/rule_cases.json` |
| **Test 2**: explanation faithfulness | `check_faithfulness.py` | Does the explanation stay true to the JSON? | 8 hand cases + 60 synthetic cases (seed 0) |
| **Test 3**: symptom extraction | `check_symptoms.py` | Field accuracy of the chat extraction | dev + blind sets A, B, C |
| **Test 4**: human evaluation | (manual) | Dentist scoring of 30 explanations | **waiting for a dentist** |
| **Test 5**: triage | `check_triage.py`, `check_e2e.py` | Level vs the SDCEP-derived keys | 200 held-out triage + 60 end-to-end; 100 dev |
| **P7**: test-text quality | `p7_generate.py` + Gemini | Is the synthetic patient text faithful to its key? | all held-out and dev text |
| Severity phrase sets | extraction harness | Severity phrasings, and a code guard | `llm/eval/severity_phrases*.json` |
| Unit and integration tests | `python -m unittest discover -s tests` | Code behaviour, including an offline web test | 474 tests |

### 8.2 Test 2: explanation faithfulness

For each case, the explanation is generated and checked in code for:
- **hallucination**: a tooth mentioned that is not in the findings;
- **unreported tooth**: a tooth described as a finding that the assessment
  did not flag. This stricter definition (#22) has been the headline since
  2026-09-24;
- **omission**: a flagged tooth left out;
- **contradiction**: the urgency contradicted;
- **misstated**: the urgency or a finding misreported;
- on unusable photos: whether a retake was requested, and whether the text
  wrongly claims "nothing found" about teeth it could not see;
- guardrail retries and fallback use;
- follow-up answers (2 per case): invented teeth, discouraging care,
  echoing the first response.

**A correction worth stating.** Until 2026-09-24 the project reported "0
hallucinations on 60 cases". That check only asked whether a mentioned tooth
*existed* in the findings, not whether it was *reportable*. Under the
stricter check the same runs had 7–8/60 explanations describing
sub-threshold detections. The claim was corrected in every document, with
the original wording left visible, and the fix was measured (section 9.2).

### 8.3 Test 3: symptom extraction

Each dialogue is run through the real interview and extraction. Every
extracted chat field is compared with the key. Reported:
- field accuracy with exact (Clopper-Pearson) 95% CIs;
- dialogues fully correct;
- **guessed values** (a value where the key is null; hard rule 7);
- **dropped values** (null where the key has a value);
- invented list items;
- whether checklist answers were ever overwritten.

Each blind set is **scored once**. Its misses go to the developer only as
abstract categories, never as example wording, so the next blind set stays
blind.

### 8.4 Test 5: triage, pre-registered

The analysis was written and committed **before any held-out run**
(`docs/plans/test5-analysis-spec.md`, 2026-09-23). Every amendment
(§9.1–9.9) is dated before the scoring it affects.

**Systems compared on the same cases:**
1. `final`: what the patient sees;
2. `llm_proposed`: the model's own level before any code override;
3. `protocol_check`: code alone;
4. `rules`: the old baseline.

**Metrics:**
- **Primary: under-triage** (system less urgent than the key), with an exact
  95% CI. The pass bar for `final` is 0 under-triage **and** weighted κ ≥ 0.8.
- Sub-counts: severe under-triage (≥ 2 levels, or RETAKE when care is
  needed), missed EMERGENCY, and boundary vs other cases.
- Over-triage, exact agreement, and linearly weighted κ with a bootstrap CI
  (2,000 resamples, seed 20260923).
- A confusion matrix with recall and precision per level.
- **Head to head:** exact McNemar test on under-triage (final vs rules, model
  vs rules). With fewer than 10 discordant pairs, no p-value is reported.
- **Operations:**
  - valid-output rate, retries, and fallback to rules (bar ≤ 1%);
  - how often the model's own level decided;
  - latency;
  - **stability**: 20 fixed cases run 3 times plus 2 paraphrases each.
- **End-to-end:** the same metrics, plus attribution of each miss to one
  bucket: interview (question never asked), extraction, triage, or protocol
  gap.
- **§9.5:** sensitivity analysis without the 6 exposed keys.
- **§9.8:** severity errors by direction:
  - false severe, which raises urgency;
  - missed severe, which lowers it and is the more serious direction.
- **§9.9:** fallback reported beside `llm_raised`, plus their sum (the rate
  under the rule as first registered).

A **development rehearsal** on the 100 dev keys preceded the held-out run.
It found the model falling back to rules on 15/75 calls = 20% (bar ≤ 1%),
every time because the model named a level below its own valid citations.
The fix (step 4 in section 2.5) was made before any held-out scoring.

### 8.5 P7: making realistic test text, and checking it

Answer keys are structured data, but the system reads patient words. P7
turns each key into text a patient might type, and makes sure the text does
not give the answer away or contradict the key.

1. **Generation (llama3.1:8b, local, temperature 0.8, fixed seeds).** The
   prompt gets the key's facts and field values as plain-English lines,
   never field names or level words.
2. **Automatic checks, then regeneration on failure:**
   - no protocol language (level names, criterion wording, time frames);
   - no medicine names;
   - length bounds;
   - no near-duplicates;
   - injection lines appended by code, verbatim.
3. **Blind check (model B, Gemini).** B runs the production extraction
   prompt on the text, without seeing the key.
4. **Adjudication (research-pm, text-first).** For each disagreement,
   research-pm reads the text with the key and B hidden, records a reading,
   then reveals them. Every disagreement is classed as text wrong, key
   wrong, ambiguous, B wrong, or check artifact.
5. **Rules, fixed before any output existed:**
   - the text-attributable residual must be ≤ 2%;
   - B's own error rate must be ≤ 5%;
   - at most 2 regeneration rounds, then a marked and counted hand edit;
   - no case dropped, and keys never changed to match the text.
6. **A 50-case human read** of random held-out texts, as an independent
   error estimate.
7. **A census of the not-reached texts.** Model B never reads texts for
   patients who never reach the chat, so these were screened separately
   before Test 5.

---

## 9. Results

All results use qwen3:14b unless stated.

### 9.1 Test 1: rules baseline

**20/20** hand cases, unchanged throughout. This only shows the baseline
does what it was written to do.

### 9.2 Test 2: explanation faithfulness (latest, 2026-09-26, triage-2.0 path)

| Measure | 8 hand cases | 60 synthetic cases |
|---|---|---|
| Hallucination (tooth not in findings) | 0/8 | 0/60 |
| **Unreported tooth** (stricter, headline) | 0/8 | **0/60** (95% CI 0–6.0%) |
| Omission | 0/8 | 0/60 |
| Contradiction | 0/8 | 0/60 |
| Misstated | 0/8 | 0/60 |
| Retake not requested (unusable photo) | 0/1 | 0/14 |
| Unscoped "nothing found" (unusable photo) | 0/1 | **1/14** (minor) |
| Guardrail retry / fallback text used | 0/8 / 0/8 | 2/60 / 1/60 |
| Follow-ups (120): invented tooth / discourages care / misstated / echo | – | 0 / 0 / 0 / 0 |

**Before the #22 fix**, the same measure was 8/60 (CI 5.9–24.6%). The fix
gives the model only the reportable teeth and adds a guardrail, and the
unreported-tooth rate fell to 0/60. Caveat: the 60 synthetic cases are
generated by code from seed 0, so they test faithfulness to JSON, not
realistic language.

### 9.3 Test 3: symptom extraction

| Set | n | Field accuracy (95% CI) | Guessed where key null | Notes |
|---|---|---|---|---|
| Dev (tuned) | 12 dialogues, 60 cells | 60/60 (latest, 2026-09-25) | 0 | optimistic by design |
| Blind A (2026-09-23) | 19 / 95 | **88/95 = 92.6%** (85.4–97.0) | 1 genuine invention | location + triggers 33/38 |
| Blind B (2026-09-24) | 20 / 100 | **97/100 = 97.0%** (91.5–99.4) | 0/7 | location 20/20, triggers 17/20 |
| Blind C (2026-09-24) | 24 / 120 | **116/120 = 96.7%** (91.7–99.1) | 0/4 | location 24/24, triggers 20/24; other fields 72/72 |

**Pattern.**
- The misses are nearly all in **pain triggers**. Typical cases: a
  temperature implied only by context ("tap water on a winter morning"), a
  trigger named by a food, or a weather use of "hot" kept alongside the real
  trigger.
- Location became reliable after it was made a code rule (it needs arch and
  side together).
- **Guessed values stayed at or near zero**, which is the safety property
  that matters most: misses come back as empty, not wrong.

With n of 20–24 dialogues, the sets cannot resolve differences of a few
points. Read the CIs, not the point estimates.

### 9.4 P7: quality of the synthetic test text

| Set | Text-attributable residual (bar ≤ 2%) | Model B error (bar ≤ 5%) |
|---|---|---|
| Dev | 0/195 as written (2/195 = 1.0% conservatively) | 1/195 = 0.5% |
| Held-out triage | **6/420 = 1.43%** (CI 0.5–3.1) | 8/420 = 1.9% |
| Held-out end-to-end | **1/125 = 0.8%** | 0/125 |

- **50-case human read:** **11/50 = 22.0%** (CI 11.5–36.0%) had an error, 9
  of them in texts that never reach the chat, where B's check does not look.
  This led to the census.
- **Census of not-reached texts:**
  - 36/151 = 23.8% (CI 17.3–31.4%) had errors before fixing;
  - two regeneration rounds and 8 marked hand edits by research-pm brought
    it to **0/151**;
  - counting the hand edits as generator failures, the rate is 8/151 = 5.3%.

Neither CI rules out a true residual above 2%. Treat the text as good but
not perfect.

### 9.5 Test 5: held-out triage (the main result, 2026-09-26)

Protocol v0.2, commit 06d3792. Each configuration was scored **once**.

**Triage-level set, n = 200:**

| System | n | Under-triage (95% CI) | Severe | Missed EMERGENCY | Over-triage | Exact | Weighted κ (95% CI) |
|---|---|---|---|---|---|---|---|
| **`final` (what the patient sees)** | 200 | **0 (0.0–1.8%)** | 0 | 0/45 | 0 | 200/200 | **1.000** |
| `protocol_check` (code alone) | 200 | 0 (0.0–1.8%) | 0 | 0/45 | 0 | 200/200 | 1.000 |
| `llm_proposed` (model alone) | 155 | 30 = 19.4% (13.5–26.5%) | 1 | n/a | 0 | 125/155 | 0.781 (0.708–0.853) |
| `rules` (old baseline) | 200 | 51 = 25.5% (19.6–32.1%) | 31 | **25/45** | 10 | 139/200 | 0.595 (0.504–0.680) |

**The pre-registered bar (0 under-triage, κ ≥ 0.8) is met by `final`.** Zero
out of 200 bounds the true under-triage rate at 1.8% (two-sided) or 1.5%
(one-sided). It does not prove the rate is zero.

**The honest reading:**

1. **The safety comes from code, not the model.** Under v0.2 every criterion
   is machine-checkable, so code alone also scores 200/200. The model cannot
   push the result below the key, because code raises any lower proposal.
2. **The model on its own is no better than the old rules.** On the same 155
   cases where the model was called:
   - the model under-triaged 30 and the rules 26;
   - 30 cases were missed only by the model and 26 only by the rules;
   - exact McNemar p = 0.689, so no difference is shown.

   All 30 of the model's misses were caught by code: 26 raised to its own
   citations and 4 by the protocol check.
3. **Where the model falls short:**
   - 20 of its 30 misses gave mild or controlled pain ROUTINE where the
     protocol says SOON;
   - in all 6 lingering-pain cases it proposed SOON where v0.2 says URGENT.
     Here the model sided with SDCEP over the owner's provisional rule, which
     led to the v0.3 decision;
   - 3 misses were pain on biting;
   - 1 was a photo finding.

   The model is least urgent exactly where the protocol deliberately errs
   towards caution.
4. **The old rules missed 25 of 45 emergencies.** They never asked about
   bleeding, chest pain, overdose or feeling unwell.

**Head to head:** `final` vs `rules`, n = 200: 0 vs 51 under-triaged, exact
McNemar p = 8.9 × 10⁻¹⁶.

**Operations (233 triage calls):**

| Measure | Value |
|---|---|
| Valid output | 233/233 |
| Retried at least once | 93/233 = 39.9% |
| Fallback to rules (bar ≤ 1%) | **0/233** (0.0–1.6%), met |
| Level raised by code to the model's own citations | 39/233 = **16.7%** (12.2–22.2%) |
| Model's own level decided (first runs with a model call) | 125/155 = 80.6% |
| Latency per triage call | median 7.3 s, 95th percentile 16.3 s |

**Finding against the model:** in about 1 call in 6, the model stated a
level lower than the criteria it cited itself. The 0% fallback depends on
the rule change made after the development rehearsal. Under the rule as
first registered, the fallback rate would be 16.7%.

**Stability (20 fixed cases, 3 runs + 2 paraphrases each):**
- `final` was identical in 20/20 cases;
- `llm_proposed` was identical across repeats of the same words in 20/20,
  but across paraphrases in only 16/19.

So the model is deterministic on identical input, and all its instability
comes from rewording. One case had no paraphrases because of a harness gap,
now fixed for future sets.

**Sensitivity without the 6 exposed keys (n = 194):**
- `final`: 0/194 under-triaged, κ 1.000;
- `llm_proposed`: 30/149, κ 0.771;
- `rules`: κ 0.578.

No conclusion changes.

**End-to-end set, n = 60** (interview → extraction → triage). Headline
condition: the opening message is dropped, as in the product.

| System | n | Under-triage (95% CI) | κ |
|---|---|---|---|
| **`final`** | 60 | **0 (0.0–6.0%)** | 1.000 |
| `llm_proposed` | 45 | 11 = 24.4% (12.9–39.5%) | 0.719 |
| `rules` | 60 | 16 (8/15 missed EMERGENCY) | 0.592 |

- With the opening message prepended (secondary condition), `final` was
  still 0/60 and `llm_proposed` 7/45.
- **Interview:** no needed question was ever left unasked (0/60 in both
  conditions). Questions skipped because an earlier answer had settled them:
  3/60 cases (drop) and 20/60 (prepend). In prepend, 24/28 of the settled
  values matched the key.
- **Extraction:** 5/125 chat cells differed from the key (4.0%). None changed
  a final level.
- **Severity errors by direction (n = 25 cases reaching the chat):** false
  severe 0/25, missed severe 0/25. Only 3 keys were severe, so the
  missed-severe direction is barely tested (CI 0–70.8%).

The full write-up is in `docs/reports/test5-heldout-2026-09-26.md`.

### 9.6 Unit and integration tests

**474/474** pass (2026-09-26), including an offline web-app test. Test 1 is
20/20.

---

## 10. What is not yet known (limitations)

1. **Agreement with SDCEP as encoded, not clinical validation.** One person
   wrote every key from the same protocol the code encodes. No dentist has
   labelled a single case. The key-vs-dentist agreement, which tests the
   protocol itself, is unmeasured.
2. **The photos are assumed correct in the triage tests.** The caries
   detector catches only about 29% of carious photos at the current
   threshold. A patient with a missed cavity and no symptoms gets ROUTINE
   whatever the triage does. **End-to-end accuracy on real patients with
   real photos has not been measured at all.**
3. **Occlusal photos cannot show** the surfaces between teeth, anything
   under the gum, or inside a tooth.
4. **The test text is synthetic**, written by one model family (Llama), and
   screened. Real patients may phrase things differently.
5. **Held-out results stay on protocol v0.2.** Protocol v0.3 was decided
   after the held-out results were seen (the U5 decision was informed by
   them), so re-scoring the same held-out set under v0.3 would not be a
   clean held-out result. **A claim about v0.3 needs a fresh held-out set.**
6. **Small n on some measures.** 60 end-to-end cases bound under-triage at
   6.0%. Only 3 severe keys test missed severity. The Test 3 blind sets are
   20–24 dialogues.
7. **Known extraction gaps, deliberately not fixed before scoring.** Three
   `verify()` patterns can drop a correct trigger value:
   - a non-standard "I don't know";
   - an ordinary mention of a cold drink blanked by the illness-word rule;
   - a nearby denial in unpunctuated text.

   All three drop a value; none adds one.
8. **Unasked warning signs:** trismus, visual disturbance and voice change
   (section 4.3).
9. **A hosted model in the evaluation.** Gemini checked the synthetic text,
   so that step may not be exactly repeatable, and synthetic held-out text
   exists at a third party.
10. **Licences.** The SegmentAnyTooth weights are non-commercial and the
    caries weights GPL-3.0. Both are fine for research, and neither is
    cleared for a product.
11. **Speed.** About 17 s per chat turn on the RTX 3060.

---

## 11. Progress to date

### 11.1 Status by component

| Component | Status | Evidence |
|---|---|---|
| Vision: segmentation | **Done, reliable** | median 12 teeth/photo |
| Vision: caries detection | **Working, weak**; threshold decision open | 29% sensitivity at 0.50 |
| Interview (checklist + chat + verify) | **Done** | Test 3 blind 92.6–97.0% |
| Triage protocol | v0.2 **live**; v0.3 **drafted** | 21 criteria, sourced |
| Triage step (LLM + code guards) | **Done** | Test 5 held-out: final 0/200 |
| Explanation + guardrails | **Done** | Test 2: 0/60 on all five checks |
| Knowledge base | **Written, unreviewed** | 32 sections |
| Web app | **Done (demo)** | offline test passes |
| Pre-registered evaluation | **Done** for v0.2 | Test 5 report |
| Dentist review | **Not started: no dentist found** | packet ready (Forms A–D) |
| Real-patient validation | **Not started** | – |

### 11.2 Estimate

- **LLM-triage redesign (wave 2): about 90% done.** The main held-out test
  has passed. What remains is protocol v0.3 (decided and drafted), its
  development re-evaluation, and the paper write-up.
- **Whole project (a prototype ready to present as a validated screening
  aid): about 65%.** The software is largely built and measured against the
  guideline. What remains is the part no amount of code can do alone:
  - a dentist's review of the protocol, knowledge base and thresholds;
  - blind dentist labels;
  - a better caries detector or threshold;
  - any test on real patients.

These percentages are the lead's judgement of remaining effort, not a
measurement.

---

## 12. Next steps

### 12.1 Immediate (from 2026-09-29, when the team resumes)

1. **Put protocol v0.3 live**:
   - log the owner's rulings;
   - finalise the draft;
   - add a "no answer" test to the condition language;
   - add the nine severity rulings to the extraction instructions.
2. **Re-evaluate on development data only**:
   - rebuild the 100 dev keys under v0.3, plus 6 new keys for the
     relief-not-tried and relief-unanswered cases;
   - run the severity phrase sets and Tests 2, 3 and 5 on dev.
3. **Paper write-up** of the v0.2 held-out results, with the framing agreed
   on 2026-09-26.

### 12.2 Needs a dentist (the critical path)

4. **Protocol review** (Form A), **open clinical questions** (Form C: caries
   threshold, graded swelling and trauma, pus without pain, cavity + pain,
   the U5/U6 change, the unanswered-relief rule, trismus/vision/voice), and
   **knowledge review** (Form D, 32 sections).
5. **Blind vignette labelling** (Form B, about 4 hours per dentist). This
   gives key-vs-dentist agreement, which tests the protocol itself.
6. **Test 4**: dentist scoring of 30 explanations.

### 12.3 Technical

7. **A fresh held-out set** for any claim about protocol v0.3 or later.
8. **Model benchmark (Phase 2):** qwen3:8b, gemma3:12b and llama3.1:8b on
   every test. Each new configuration may be scored once.
9. **Fix the three known `verify()` gaps**, each measured on a new blind
   set.
10. **Caries detector:** apply the threshold decision, then consider
    retraining or replacing the detector on occlusal-specific data.
11. **Speed:** check whether the vision models and the LLM together
    overflow 12 GB (CPU spill), and consider a smaller LLM from the
    benchmark.
12. **Fine-tuning (QLoRA on a 7–8B model):** only if a future held-out
    result triggers it (design §6). The dental Q&A corpus would first need
    its topic clean-up run (a 2.5-hour job, deferred).

### 12.4 Longer term

13. A pilot with real patients and real photos, under ethics approval.
14. Licence clearance (or replacement models) before any product use.

---

## Appendix A: full interview question list (protocol v0.2)

**Checklist A: always, every row needs Yes or No**

| Id | Question | Field | Red flag |
|---|---|---|---|
| Q1 | Are you having any difficulty breathing or swallowing? | difficulty_swallowing_or_breathing | yes |
| Q2 | Do you have any chest pain, or do you feel short of breath? | chest_pain_or_breathless | yes |
| Q3 | Is there any swelling in your face, jaw or gums? | swelling | yes |
| Q4 | Do you have a fever or a high temperature? | fever | yes |
| Q5 | Do you feel very unwell in yourself, for example shivery, faint or unusually tired? | systemically_unwell | yes |
| Q6 | Have you recently had a knock, fall or other injury to your mouth, teeth or face? | recent_trauma | yes |
| Q7 | Is there any bleeding in your mouth that does not stop when you press on it? | bleeding_uncontrolled | yes |
| Q8 | In the last few days, have you taken more pain relief than the packet says is safe? | exceeded_pain_relief_dose | yes |
| Q9 | Do you have any pain or discomfort in your teeth or gums at the moment? | pain_present | no |
| Q19 | Do you have a mouth ulcer, sore or lump that has lasted more than 3 weeks? | persistent_ulcer | no |
| Q20 | Do you have a filling, crown or tooth that has broken, chipped, come loose or come out, and has not been fixed yet? | broken_filling_or_tooth | no |
| Q21 | Have you noticed pus, a pimple-like bump on the gum, or a salty or bad-tasting fluid coming from around a tooth? | pus_or_discharge | no |

**Checklist B: only if the patient has pain**

| Id | Question | Field |
|---|---|---|
| Q13 | After the pain is set off, does it keep aching for more than about half a minute? (Yes / No / Not sure) | pain_lingers_over_30s |
| Q14 | Does the pain ever wake you up at night? | pain_wakes_at_night |
| Q15 | Does it hurt when you bite down or press on the tooth? | pain_on_biting |
| Q16 | Have you had a tooth taken out in the last two weeks? | recent_extraction |

**Chat: only if the patient has pain; the answer is extracted with a verified quote**

| Id | Question | Field |
|---|---|---|
| Q10 | Have you taken any pain relief for it? If so, did it help? | pain_relief_effect (helped / not_helped / not_tried) |
| Q11 | How bad is the pain? Is it mild, moderate, or so bad that it stops you sleeping or eating? | pain_severity |
| Q12 | What sets the pain off: cold, hot, sweet things, biting, or does it come on by itself? | pain_triggers |
| Q17 | Where is the pain: upper or lower, left or right side, or at the front? | location |
| Q18 | How long have you had this pain? | duration_days |

Re-ask (chat only, once): "Sorry, I need a clearer answer to keep you
safe. {question}"

## Appendix B: fixed patient-facing text (owner-approved wording, clinically unreviewed)

- **Limitations:**
  - "These photos show the biting surfaces only. They cannot show the sides
    between your teeth."
  - "They cannot show anything under the gum or inside a tooth."
  - "A cavity can be there even when the photos show nothing."
- **Safety net:** "If you develop swelling, a fever, bleeding that will not
  stop, or trouble breathing or swallowing, go to a hospital as soon as
  possible."
- **Disclaimer:** "This is an AI screening tool, not an examination by a
  dentist. It cannot diagnose any condition. If you are worried, contact a
  dentist."
- **Routine advice:** "Brush twice a day with fluoride toothpaste, cut down
  on sugary food and drinks, and see a dentist for regular check-ups."
- **Finding phrase:** "Based on the image, there is an indication of tooth
  decay on:", followed by tooth names computed by code.

## Appendix C: file map

| What | Where |
|---|---|
| Decision log (why everything is as it is) | `docs/decisions.md` |
| System design (short) | `docs/architecture.md` |
| Triage design | `docs/plans/llm-triage-design.md` |
| Literature review, protocol derivation, data plan | `docs/plans/phase1-2-plan.md` |
| Test 5 pre-registered analysis | `docs/plans/test5-analysis-spec.md` |
| Test 5 held-out results | `docs/reports/test5-heldout-2026-09-26.md` |
| P7 method | `docs/plans/p7-vignette-text-spec.md`, `p7-generation-prompt.md`, `p7-adjudication-plan.md` |
| Protocol (live v0.2 / draft v0.3) | `llm/protocol/triage_protocol.yaml`, `docs/plans/protocol-v0.3/` |
| JSON contracts | `llm/interface.md` |
| Prompts | `llm/prompts/` |
| Knowledge base | `llm/knowledge/` |
| Dentist review packet | `docs/dentist-review/` (README, Forms A–D) |
| Resume point | `docs/plans/checkpoint-2026-09-26.md` |
