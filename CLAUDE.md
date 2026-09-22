# Dental occlusal screening assistant

Two occlusal photos (upper + lower arch) in; a plain-language screening result
out: which teeth were found, which may have a cavity, how soon to see a dentist,
and why. Research prototype — **a screening aid, not a diagnosis**. Everything
runs locally; nothing leaves the machine.

## Architecture — hard rules, do not break

```
photos -> vision (src/pipeline.py)          -> findings JSON
user  <-> LLM interview (src/interview.py)   -> symptoms JSON
findings + symptoms -> llm/rules.py          -> assessment JSON (urgency)
findings + symptoms + assessment + knowledge -> LLM (src/explain.py) -> text
```

1. **The LLM never sees a photo.** It only receives the JSON objects above.
2. **The LLM never decides urgency.** `llm/rules.py` does, deterministically.
   The LLM restates the assessment; it may not contradict it, soften it,
   escalate it, add teeth or drop teeth.
3. **The three JSON shapes are defined in `llm/interface.md`.** Change that file
   first, then the code on both sides of the contract.
4. **`llm/rules.py` thresholds are clinical parameters.** Never change one
   without a written note in `docs/decisions.md` and sign-off from the PM.
5. **Knowledge files in `llm/knowledge/` are `DRAFT-UNREVIEWED`.** A dentist must
   sign them off. `explain.py` refuses unreviewed passages unless
   `allow_unreviewed=True`, which is development-only — never ship with it.
6. **The interview plan belongs to Python** (`QUESTION_PLAN` in
   `src/interview.py`). The model only phrases the question it is handed.
7. **Never guess a symptom.** Every extracted field needs the patient's own words
   as a quote, checked against the transcript; unanswered means `null`.
8. **Deterministic facts are computed, not generated** — e.g. tooth names from FDI
   numbers (`fdi_label` in `src/explain.py`). Don't hand the model a lookup it
   can get wrong.

## Folder map

```
src/                  all project code (see table below)
llm/
  rules.py            urgency decision — Python, not LLM
  interface.md        the JSON contracts
  prompts/            system prompts + symptoms_schema.json
  knowledge/          32 RAG fact sheets (DRAFT-UNREVIEWED)
  eval/               test cases + eval spec (eval/README.md)
labels/               hand labels (Malawi view labels)
models/               small trained heads (view classifier, tooth-patch classifier)
tests/sample_images/  upper.jpg + lower.jpg smoke-test pair
docs/decisions.md     decision log — read before changing behaviour
weights/  vendor/  dataset/  runs/  _archive/   local only, not in git
```

| Area | Files |
|---|---|
| Vision | `pipeline.py`, `segment_tool.py`, `caries_tool.py`, `preprocess.py`, `preprocess_malawi.py`, `segment_crops.py`, `screen_dataset.py`, `train_*.py` |
| LLM | `interview.py`, `explain.py`, `retrieval.py`, `assess.py` |
| Web demo | `webapp.py` (FastAPI), `webapp_index.html` (single-page UI) |
| Evaluation | `check_rules.py`, `check_faithfulness.py`, `check_symptoms.py`, `run_evals.py`, `eval_data.py` |

## Environment

- Python: always `.venv/Scripts/python` (Python 3.10). Setup in `requirements.txt`.
- GPU: RTX 3060, CUDA build of torch (cu130). CPU build works, ~6x slower.
- LLM: Ollama at `http://localhost:11434`, model `qwen3:14b` (Q4_K_M). `qwen3:4b`
  is installed for size comparison only — it is not deployable (see decisions).
- Local-only folders (gitignored, must exist on the machine):
  - `weights/` — SegmentAnyTooth weights (signed non-commercial licence) and
    `caries_yolov8.pt`
  - `vendor/segmentanytooth` — `git clone https://github.com/thangngoc89/SegmentAnyTooth`.
    Don't edit vendored code; patch from our side (see `src/segment_tool.py`).
  - `vendor/caries-yolov8` — `git clone https://github.com/AndreyGermanov/yolov8_caries_detector`
    (GPL-3.0; source of `weights/caries_yolov8.pt`)
  - `dataset/` — Mendeley carious/noncarious sets, Malawi sets

## Commands

```
.venv/Scripts/python src/webapp.py                  # demo at http://localhost:8000
.venv/Scripts/python src/pipeline.py --upper U.jpg --lower L.jpg   # findings JSON
.venv/Scripts/python src/check_rules.py             # Test 1, deterministic, target 20/20
.venv/Scripts/python src/check_faithfulness.py      # Test 2, needs Ollama
.venv/Scripts/python src/check_symptoms.py          # Test 3, needs Ollama
.venv/Scripts/python src/run_evals.py --models qwen3:14b --synthetic 60   # full suite
```

Run `check_rules.py` after any change to `llm/rules.py` or `src/assess.py`. Run
Tests 2 and 3 after any change to prompts, `interview.py`, `explain.py` or
`retrieval.py`. Report the numbers — don't just say "tests pass".

## Current state (measured, not estimated)

- Segmentation (Mendeley): median 12 teeth/photo, 4 of 4,929 photos found nothing.
- Caries detector at conf 0.25: catches 62% of carious photos, 86% specificity,
  85% precision; 38% of carious photos get no flag at all. Weakest component.
- `rules.py` counts detections at ≥ 0.50, which catches only ~29% of carious
  photos. **Open decision** — see `docs/decisions.md`.
- LLM (qwen3:14b): 0 hallucinated / omitted / contradicted teeth on 60 synthetic
  cases; symptom extraction ~97–99% of fields on 8 dialogues (tuned on those
  same dialogues — not a held-out number).
- Demo: ~17 s to analyse, ~17 s per interview turn.

## Working as a team

Five agents live in `.claude/agents/`: `research-pm`, `backend-dev`,
`frontend-dev`, `llm-dev`, `qa-engineer`. Each owns specific files (listed in its
agent file). To change a file you don't own, hand the change to its owner or get
the PM's agreement first. Contract changes (`llm/interface.md`, the web API in
`webapp.py`) need both sides agreed before either edits.

- Work on a branch per task; small commits; describe *why* in the message.
- Record any behaviour or threshold decision in `docs/decisions.md`.
- Prefer reporting a measured limitation over hiding it. Frame all user-facing
  output as descriptive screening, never as a diagnosis.

## Licences

SegmentAnyTooth weights: non-commercial, by signed agreement. Caries model
weights: GPL-3.0 repository. Both fine for research; neither is cleared for a
product.
