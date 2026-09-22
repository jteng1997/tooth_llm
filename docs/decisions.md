# Decision log

Newest first. Each entry: what was decided, why, and what evidence it rests
on. Owned by `research-pm`; any agent may propose an entry.

## Open

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
