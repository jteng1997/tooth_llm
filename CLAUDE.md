# Dental occlusal screening assistant

Two occlusal photos (upper + lower arch) in; a plain-language screening result
out: which teeth were found, which may have a cavity, how soon to see a dentist,
and why. Research prototype — **a screening aid, not a diagnosis**. Runs fully
local on one Windows machine; nothing leaves it. One exception (user,
2026-09-23): P7 test-text checking calls the paid Gemini API with synthetic
vignette text only — never patient data (`docs/decisions.md`).

**Language: English only** for everything the project produces — the web app,
all LLM interaction with users, prompts, knowledge, reports and docs. (The
user may chat with the lead in Indonesian; that never carries into project
output.)

## Architecture — hard rules

```
photos -> vision (src/pipeline.py)          -> findings JSON
user  <-> LLM interview (src/interview.py)   -> symptoms JSON
findings + symptoms -> llm/rules.py          -> assessment JSON (urgency)
findings + symptoms + assessment + knowledge -> LLM (src/explain.py) -> text
```

1. **The LLM never sees a photo** — only the JSON objects above.
2. **Urgency: the LLM decides, code guards the floor.** *(Being redesigned —
   `docs/decisions.md`, 2026-09-22.)* The LLM will determine the triage level from
   the patient's complaints and the findings, following a literature-based
   triage protocol. A deterministic red-flag floor in code (swelling,
   difficulty breathing or swallowing, fever, trauma → EMERGENCY) can only raise
   urgency, never lower it. The LLM may never add, drop or contradict teeth in
   the findings. Until the new design ships, `llm/rules.py` still decides.
3. **JSON shapes live in `llm/interface.md`.** Change it first, then both sides.
4. **`llm/rules.py` thresholds are clinical parameters.** Never change one
   without an entry in `docs/decisions.md` and the user's sign-off.
5. **`llm/knowledge/` is `DRAFT-UNREVIEWED`** until a dentist signs it off.
   `allow_unreviewed=True` is development-only — never ship with it.
6. **Python owns the interview** — the plan, the order, when to stop, and the
   question text itself (fixed English wording from the triage protocol;
   decided 2026-09-22). The LLM no longer phrases questions.
7. **Never guess a symptom.** Each extracted field needs the patient's own words
   as a quote checked against the transcript; unanswered means `null`. Yes/no
   questions are answered on a checklist (decided 2026-09-22): each row needs an
   explicit Yes or No, with no default, so an untouched row is never read as "no".
8. **Compute deterministic facts, don't generate them** — e.g. tooth names from
   FDI numbers (`fdi_label` in `src/explain.py`).

## Layout

```
src/        vision: pipeline, segment_tool, caries_tool, preprocess*, screen_dataset, train_*
            llm:    interview, explain, retrieval, assess
            web:    webapp.py (FastAPI), webapp_index.html
            eval:   check_rules, check_faithfulness, check_symptoms, run_evals, eval_data
llm/        rules.py, interface.md, prompts/, knowledge/ (32 fact sheets), eval/ (cases + spec)
docs/decisions.md   decision log — read before changing behaviour
labels/ models/ tests/sample_images/
weights/ vendor/ dataset/ runs/ _archive/   local only, gitignored
```

## Environment

- Python: always `.venv/Scripts/python` (3.10). Setup steps in `requirements.txt`.
- GPU: one RTX 3060, torch cu130. LLM: Ollama at `localhost:11434`, `qwen3:14b`
  (`qwen3:4b` is for size comparison only — not deployable).
- Local-only, must exist: `weights/` (SegmentAnyTooth, non-commercial licence;
  `caries_yolov8.pt`), `vendor/segmentanytooth` (clone of
  thangngoc89/SegmentAnyTooth — never edit, patch from `src/segment_tool.py`),
  `vendor/caries-yolov8` (AndreyGermanov/yolov8_caries_detector, GPL-3.0),
  `dataset/` (Mendeley carious/noncarious, Malawi).

## Commands

```
.venv/Scripts/python src/webapp.py              # demo at http://localhost:8000
.venv/Scripts/python src/pipeline.py --upper U.jpg --lower L.jpg
.venv/Scripts/python src/check_rules.py         # Test 1, no GPU, target 20/20
.venv/Scripts/python src/check_faithfulness.py  # Test 2, Ollama
.venv/Scripts/python src/check_symptoms.py      # Test 3, Ollama
.venv/Scripts/python src/run_evals.py --models qwen3:14b --synthetic 60
```

After changing `llm/rules.py` or `assess.py`: run Test 1. After changing
prompts or `interview.py` / `explain.py` / `retrieval.py`: Tests 2 and 3.
Report the numbers and sample sizes, not "tests pass".

## Where things stand

**Resuming work? Start with the "Update 2026-09-30" section of
`docs/plans/checkpoint-2026-09-29.md`** (branch `llm-triage-wave2`).
- Protocol v0.3 is live.
- The suite is green (573) and Test 1 is 20/20.
- dev Test 3 is 12/12. Dev Test 5 in LLM mode: 0/101 under-triage.
- Dev e2e (45 cases): final 0 under-triage, 43/43 exact (2 are designed
  RETAKE). Dev Test 2: 0/68 invented, omitted, contradicted or
  sub-threshold teeth.
- Extraction output is capped (schema maxLength + num_predict 1024) after
  a runaway hang on V068.
- Test 2 re-run on the final config is unchanged.
- Still open: severity over-triage (new held-back set d), HU01–HU08.
- The severity extraction change is kept by user decision, with a known
  over-triage of 4/28 on held-back set c.

Then read `checkpoint-2026-09-26.md` for the held-out backup (held-out Test 5
is spent on v0.2). System design: `docs/architecture.md`.

Details and evidence in `docs/decisions.md`. In short: segmentation is reliable
(median 12 teeth/photo on Mendeley); the caries detector is the weakest link
(catches 62% of carious photos at conf 0.25; `rules.py` uses 0.50, which catches
~29% — open decision); on 60 synthetic cases qwen3:14b invents no tooth
absent from the findings and makes 0 omissions or contradictions, **but** in
7–11/60 explanations it reports sub-threshold detections (teeth the assessment
never flagged) as findings — fix in progress (task #22, 2026-09-24); the demo
takes ~17 s per interview turn.

## Agent team

Agent teams are enabled in `.claude/settings.json`. On this Windows machine they
run in-process: one terminal, teammates in the agent panel (↑↓ select, Enter to
talk to one, Esc interrupt, Ctrl+T task list).

The **main session is the lead**: it breaks work into tasks, assigns them,
merges results and owns git. Teammates (definitions in `.claude/agents/`):

| Teammate | Owns |
|---|---|
| `research-pm` | `docs/`, `labels/`, reports, experiment design, the decision log |
| `app-dev` | vision code, `models/`, `webapp.py` + `webapp_index.html`, `requirements.txt` |
| `llm-dev` | `interview.py`, `explain.py`, `retrieval.py`, `assess.py`, `llm/prompts/`, `llm/rules.py` code, `llm/interface.md` |
| `qa-engineer` | `tests/`, evaluation scripts, test cases in `llm/eval/` |

Team rules:

1. **One owner per file.** Need a change in someone else's file? Message its
   owner, or ask the lead. `llm/interface.md` changes need app-dev and llm-dev.
2. **One GPU, one Ollama, one port 8000.** Only one heavy job at a time
   (evaluations, dataset screening, training). qa-engineer runs the evaluations.
   Check port 8000 before starting the web server; stop what you start.
3. **One shared working folder.** Teammates never switch branches, commit or
   push — that would change the folder under everyone. The lead commits once
   qa-engineer has verified the work.
4. **Plans.** Teammate plans are approved by the lead automatically. If the user
   asked to review plans, the lead shows them to the user first.
5. **Evidence.** A claim that something works needs a measurement; qa-engineer
   verifies developer claims before the lead accepts them.
6. **Clinical calls belong to the user** (thresholds, knowledge content, urgency
   wording). Prepare evidence; never decide them.

A good brief states the goal, the constraints, a measurable "done when", and
the priority.

## Licences

SegmentAnyTooth weights: non-commercial, by signed agreement. Caries weights:
GPL-3.0 repository. Fine for research; neither is cleared for a product.
