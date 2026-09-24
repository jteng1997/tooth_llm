# Architecture — dental occlusal screening assistant

State as of 2026-09-23, branch `llm-triage-wave2`. Research prototype: **a
screening aid, not a diagnosis.** Clinical content (protocol, knowledge,
thresholds) is `DRAFT-UNREVIEWED` until a dentist signs it off.

Companion documents: `llm/interface.md` (the data contract, authoritative for
JSON shapes), `docs/decisions.md` (why things are the way they are),
`docs/plans/llm-triage-design.md` (triage design).

---

## 1. What the system does

Input: two occlusal photos (upper and lower arch) and a short patient
interview. Output, in plain English:

- which teeth were found, and which may show decay;
- how soon to see a dentist: EMERGENCY / URGENT (24 h) / SOON (7 days) /
  ROUTINE, or RETAKE when the photos are unusable;
- why: the criteria that were met, with the patient's own words as evidence;
- a fixed safety net, limitations and disclaimer.

Everything runs on one Windows machine (RTX 3060 12 GB, Ollama). The only
exception is evaluation-only: P7 test-text checking calls the paid Gemini API
with synthetic vignette text (user decision 2026-09-23). No patient data
leaves the machine.

---

## 2. Pipeline

```
 photos ─► VISION (src/pipeline.py) ─────────────► findings JSON 1.0
            SegmentAnyTooth (YOLO11+SAM) → tooth masks + FDI numbers
            per-tooth crop → YOLOv8 caries detector
            image-quality check

 patient ◄─► INTERVIEW (src/interview.py) ────────► symptoms JSON 1.1 (1.2 pending)
            checklist A (red flags, pain, ulcer) → any red flag: STOP
            checklist B (only with pain)
            chat questions (5) → LLM extraction → verify() evidence check

 findings + symptoms + patient words
        ─► TRIAGE (src/triage.py) ────────────────► assessment JSON 2.0
            1. red-flag floor (llm/rules.py)      → EMERGENCY, no model call
            2. LLM proposes level + cited criteria (schema-constrained)
            3. code evidence-checks every citation (2 invalid → rules.py fallback)
            4. protocol check (code) can only RAISE the level
            5. photo quality → RETAKE for SOON/ROUTINE when unusable

 findings + symptoms + assessment + knowledge passages
        ─► EXPLANATION (src/explain.py) ──────────► patient-facing text
            retrieval (src/retrieval.py, multilingual-e5-small)
            LLM writes; code guardrails check every reply
            one rewrite, then a fixed deterministic fallback text

 WEB (src/webapp.py + webapp_index.html, FastAPI, localhost:8000)
```

### Hard architectural rules

1. **The LLM never sees a photo.** It only receives JSON computed by code
   (`visual_summary`, never raw confidences).
2. **The LLM proposes urgency, code guards the floor.** Red flags force
   EMERGENCY before any model call; the protocol check can only raise. Code
   never lowers a level.
3. **Python owns the interview.** Order, stopping and question wording are
   fixed text from the protocol; the LLM does not phrase questions.
4. **Never guess a symptom.** Checklist rows need an explicit click (no
   default). Chat fields need a quote from one patient message, verified in
   code; unanswered means `null`.
5. **Compute deterministic facts.** Tooth names come from `fdi_label`, not
   the model.
6. **JSON shapes live in `llm/interface.md`**, changed there first.

---

## 3. Components

### 3.1 Vision — `src/pipeline.py`, `segment_tool.py`, `caries_tool.py`

| Stage | Model | Notes |
|---|---|---|
| Tooth segmentation + FDI numbering | SegmentAnyTooth (YOLO11 + SAM), `vendor/segmentanytooth`, `weights/` | Median 12 teeth/photo on Mendeley. Vendor code is never edited; patches live in `segment_tool.py`. |
| Caries detection | YOLOv8, AndreyGermanov/yolov8_caries_detector (`weights/caries_yolov8.pt`) | Run **per tooth crop**, not on the whole photo. Weakest link. |
| Image quality | code (`assess_quality`) | Blur, cropped arch, no teeth → `usable: false` → RETAKE path. |

Output: `findings` 1.0. Tooth keys are FDI strings; `present: false` means
assessed and missing, while an absent key means not assessed.

Caries threshold: `llm/rules.py` uses 0.50, which catches about 29% of carious
photos (3% false alarms). At 0.25 it catches 62% (14% false alarms). This is
an **open clinical decision**.

### 3.2 Interview — `src/interview.py`

- **Checklist A**, always first, with 10 rows (12 once v0.2 is live): the 8
  red flags, "any pain", ulcer/lump over 3 weeks, and in v0.2 broken
  filling/tooth (Q20) and pus/discharge (Q21). Any red-flag Yes stops the
  interview and goes straight to EMERGENCY.
- **Checklist B**, only with pain: lingering pain (with "Not sure"), night
  pain, pain on biting, recent extraction.
- **Chat**, 5 questions: pain relief effect, severity, triggers, location,
  duration. The LLM (qwen3:14b) extracts a value plus a quote.
  `verify()` then enforces in code that:
  - the quote sits inside one patient message;
  - a location needs an arch cue and a side cue ("front" and "generalised"
    need their own);
  - each trigger needs its own cue, and "at night" counts only when it is
    about the pain;
  - hedges ("not sure") are re-asked once, then stay `null`;
  - a bare Yes/No counts only for a yes/no question.
  `verify()` can only drop a value to `null`; it never adds one.
- The server rejects incomplete checklists (400) and results before
  checklist A (409).

### 3.3 Triage — `src/triage.py`, `src/protocol.py`, `llm/rules.py`

- **Protocol** `llm/protocol/triage_protocol.yaml` (v0.1 live, v0.2 draft in
  `docs/plans/protocol-v0.2/`): 21 criteria with machine-readable predicates,
  all questions, and all fixed patient-facing text. Built from SDCEP 2nd ed.
  (2026) and NHS England 2025 plus the user's decisions. `protocol.py` parses
  and validates it against the symptom schema.
- **LLM proposal**: the output schema is constrained through Ollama `format`.
  `criteria_met` (with evidence) comes before `level`, so the model commits
  to evidence first. There is no free-text rationale.
- **Validation**: unknown criterion, value not satisfying the criterion,
  quote not in the transcript, or a level inconsistent with the citations
  make the proposal invalid. It is retried once, then the `rules.py` fallback
  is used.
- **Output** `assessment` 2.0: `urgency`, a fixed `headline`, `reasons` with
  evidence, `decided_by` (`llm` / `red_flag_floor` / `protocol_check` /
  `fallback_rules`), a full `triage` audit block, and a `rules_baseline`
  shadow for comparison.
- `llm/rules.py` is the deterministic baseline (Test 1, 20/20), and also
  holds `red_flag_floor()`.

### 3.4 Explanation — `src/explain.py`, `src/retrieval.py`

- Retrieval: 32 knowledge sections in `llm/knowledge/` (6 files,
  `DRAFT-UNREVIEWED`), embedded with multilingual-e5-small into
  `models/knowledge_index.npz`.
- The LLM writes the first response and answers follow-up questions. It may
  restate the JSON but never contradict it, add teeth or change the urgency.
- **Code guardrails** check every reply, including follow-ups. A violation
  gets one rewrite that names the problem; a second violation gets the fixed
  fallback text.
  - `guardrail_violations`: drug names or doses, including garbled ones;
    invented teeth; missing finding phrase.
  - `places_pain`: no pain side beyond what the patient said. Links to a
    found tooth are allowed only when hedged ("may be related…, only a
    dentist can confirm").
  - `calls_missing_decay`: a missing tooth is never called decay.
  - `echoes`: a follow-up must not re-print the first response.
  - Pending (#17): `denies_tooth_cause`, which must never say the pain is
    not from a tooth or that the teeth are fine.
- A follow-up that raises a red flag is caught by a keyword pre-screen plus
  an evidence check, and re-escalates the assessment.

### 3.5 Web — `src/webapp.py`, `src/webapp_index.html`

FastAPI on `localhost:8000`. Endpoints: `/api/analyse`, `/api/checklist`,
`/api/answer`, `/api/result`, `/api/ask`, `/api/reset`. The page renders
checklist rows from server data (no hard-coded count), has an emergency
screen, and reads the disclaimer, safety net and limitations from the
protocol. Symptom JSON appears only in a collapsed debug panel. About 17 s
per chat turn on the RTX 3060.

---

## 4. Models

| Role | Model | Where |
|---|---|---|
| Interview extraction, triage, explanation | **qwen3:14b** (qwen3:4b not deployable: leaked reasoning, invented teeth in 40%) | Ollama, local |
| Embeddings | intfloat/multilingual-e5-small | local |
| Segmentation | SegmentAnyTooth YOLO11 + SAM | local, non-commercial licence |
| Caries | YOLOv8 DentalAI | local, GPL-3.0 |
| P7 patient-text writer (evaluation only) | llama3.1:8b | Ollama, local |
| P7 blind checker "model B" (evaluation only) | gemini-3.5-flash-lite | Gemini API, paid; synthetic text only |

The three P7 roles are three model families, so the test text is not written
or checked by the system under test: Meta writes, Google checks, Qwen is
tested.

---

## 5. Evaluation

| Test | Script | What it measures | Latest |
|---|---|---|---|
| 1 Rules | `check_rules.py` | `rules.py` on 20 cases | 20/20 |
| 2 Faithfulness | `check_faithfulness.py` | explanation: hallucination, omission, contradiction, misstated; guardrail retries; follow-ups | 0/60 on the first three (legacy path); triage-2.0 mode run paused mid-run |
| 3 Symptoms | `check_symptoms.py` | chat-field extraction | dev 60/60 (tuned); blind set A 88/95 = 92.6%; blind set B not yet run |
| 5 Triage | `check_triage.py`, `check_e2e.py` | level vs SDCEP-derived keys, pre-registered spec | no-model baseline: rules.py 51/200 under-triage (25.5%), protocol check 8/200 (4.0%); LLM not yet scored |
| Unit | `python -m unittest discover -s tests` | about 330 tests | all pass except 1 expected v0.2-transition test |

Test 5 rules: `docs/plans/test5-analysis-spec.md`, pre-registered with
amendments §9.1–9.7 written before any held-out LLM scoring. Held-out keys
live in `labels/heldout/` (gitignored); llm-dev never sees them. Dev keys in
`labels/dev/` are public to the team.

P7 (`src/p7_generate.py`) turns keys into patient wording. Leak checks run
first, then a blind extraction by model B; a set is usable only when
residual disagreement is ≤ 2%.

---

## 6. Repository layout

```
src/        vision, interview, triage, protocol, explain, retrieval, webapp, eval scripts
llm/        rules.py, interface.md, prompts/, protocol/, knowledge/, eval/
docs/       decisions.md, architecture.md, plans/, dentist-review/ (forms A–D)
labels/     dev/ (tracked), heldout/ (gitignored)
tests/      unit + offline web + browser tests
weights/ vendor/ dataset/ runs/   local only, gitignored
```

## 7. Known limits and open items

- Occlusal photos cannot show surfaces between teeth, below the gum or
  inside the tooth. The caries detector misses most decay at the current
  threshold.
- Protocol, knowledge and fixed text are unreviewed. **No dentist has been
  found yet**; the review packet (`docs/dentist-review/`) is ready.
- Open clinical questions include the caries threshold; trismus, visual
  disturbance and voice change (not asked); pus without pain → URGENT (a
  provisional over-triage); and U7 (cavity + any pain → URGENT).
- All triage agreement figures are "agreement with SDCEP as encoded in our
  protocol", not clinical validation.
- Licences: the SegmentAnyTooth weights are non-commercial and the caries
  weights GPL-3.0. Fine for research, not cleared for a product.
