# interface.md — data contract

Four JSON objects flow through the system. Everything downstream depends
on these shapes. Change them here first, then update code.

```
findings  (vision)            ─┐
symptoms  (interview)         ─┼─> triage proposal (LLM) ─> assessment (code)
                               └──────────────────────────────┘
assessment + findings + symptoms + knowledge -> explanation (LLM, text)
```

The LLM proposes a triage level; code validates it, applies the red-flag
floor and the protocol check, and writes the `assessment`. Code can only
raise the proposed urgency, never lower it. Design:
`docs/plans/llm-triage-design.md`.

---

## 1. `findings` — produced by the vision pipeline

Unchanged (schema 1.0).

```json
{
  "schema_version": "1.0",
  "image_quality": {
    "upper": {"usable": true,  "reasons": []},
    "lower": {"usable": false, "reasons": ["blurry", "arch_cropped"]}
  },
  "arches": {
    "upper": {"present": true, "teeth_detected": 14},
    "lower": {"present": true, "teeth_detected": 13}
  },
  "teeth": {
    "16": {
      "present": true,
      "detections": [
        {"type": "caries", "confidence": 0.81, "area_frac": 0.12}
      ]
    },
    "26": {"present": true, "detections": []},
    "36": {"present": false, "detections": []}
  },
  "unassigned_detections": [
    {"type": "caries", "confidence": 0.44, "reason": "no_tooth_overlap"}
  ],
  "model_versions": {
    "segmentation": "segmentanytooth_yolo11_upper+lower",
    "caries": "<your model id>"
  }
}
```

Field notes:

- Tooth keys are **FDI strings** ("11".."48"). Only include teeth the
  segmenter reported on; absence of a key means "not assessed", which is
  different from `"present": false` ("assessed, appears missing").
- `type` is one of: `caries`, `cavity`, `restoration`, `other`.
- `area_frac` = detection box area / tooth mask area. Optional; used only
  for wording, never for urgency.
- `unassigned_detections` are boxes that overlapped no tooth mask. Never
  mentioned to the user as a specific tooth; they may trigger a retake.
- **Mirror convention:** occlusal photos taken with an intraoral mirror are
  left-right flipped. State here which convention your FDI numbering
  assumes, and make the app enforce it at capture time.
- The triage LLM never receives `findings`. It receives a `visual_summary`
  that code computes from it (section 3).

---

## 2. `symptoms` — produced by the LLM interview, validated against schema

Schema **1.1** (additive over 1.0: new fields only, none removed or renamed).

```json
{
  "schema_version": "1.1",
  "pain_present": true,
  "pain_triggers": ["cold"],
  "pain_lingers_over_30s": true,
  "pain_wakes_at_night": false,
  "pain_on_biting": false,
  "pain_relief_effect": "not_helped",
  "pain_severity": "severe",
  "swelling": false,
  "swelling_features": null,
  "fever": false,
  "systemically_unwell": false,
  "difficulty_swallowing_or_breathing": false,
  "chest_pain_or_breathless": false,
  "recent_trauma": false,
  "trauma_features": null,
  "bleeding_uncontrolled": false,
  "exceeded_pain_relief_dose": false,
  "recent_extraction": false,
  "persistent_ulcer": false,
  "bleeding_gums": false,
  "location": "lower_left",
  "duration_days": 7,
  "notes": "verbatim user phrasing, optional"
}
```

- Any field the user did not answer must be `null`, never guessed. Each
  value needs the user's own words as a quote, checked against the
  transcript.
- `pain_triggers` subset of: `cold`, `hot`, `sweet`, `biting`,
  `spontaneous`, `unknown`.
- `pain_relief_effect` one of: `helped`, `not_helped`, `not_tried`, `null`.
  Asked without naming any drug or dose.
- `pain_severity` one of: `mild`, `moderate`, `severe`, `null`. `severe`
  covers "unbearable" and "can't sleep or eat because of it".
- `swelling_features` subset of: `spreading_to_eye_or_neck`,
  `worsening_fast`, `worsening_slowly`, `limited_mouth_opening`,
  `tongue_raised`, `none`; or `null`.
- `trauma_features` subset of: `head_injury_or_passed_out`,
  `tooth_knocked_out`, `bite_changed`, `none`; or `null`.
- `persistent_ulcer`: a mouth ulcer, sore or lump lasting more than 3 weeks
  (checklist A; asked with or without pain).
- `location` one of: `upper_left`, `upper_right`, `lower_left`,
  `lower_right`, `front`, `generalised`, `unknown`, `null`.
- Array fields: each item needs its own supporting quote; an empty list is
  stored as `null`.
- See `prompts/symptoms_schema.json` for the machine-readable version.
- Checklist fields hold the patient's explicit Yes/No click; chat fields
  hold an extracted value with a verified quote (decision 2026-09-22,
  protocol v0.1 #5).

### 2.1 Interview steps (`src/interview.py` ↔ `src/webapp.py`)

Every call on an `Interview` returns one step:

```json
{"type": "checklist", "group": "A", "intro": null,
 "items": [{"id": "Q1", "field": "difficulty_swallowing_or_breathing",
            "text": "Are you having any difficulty breathing or swallowing?",
            "options": [{"label": "Yes", "value": true},
                        {"label": "No", "value": false}]},
           {"id": "Q13", "field": "pain_lingers_over_30s",
            "text": "After the pain is set off, does it keep aching for more than about half a minute?",
            "options": [{"label": "Yes", "value": true},
                        {"label": "No", "value": false},
                        {"label": "Not sure", "value": null}]}]}

{"type": "question", "id": "Q10",
 "text": "Have you taken any pain relief for it? If so, did it help?",
 "notice": null}

{"type": "done", "symptoms": {"schema_version": "1.1"}, "red_flag": false}
```

- `start()` → checklist A (the eight red flags, "any pain" and the ulcer row).
- `submit_checklist(group, answers)`, where `answers` is
  `{question_id: <value>}` for **every** row of that checklist, and each
  value is one of that row's `options[*].value`. Everything else raises
  `ValueError`, which the web layer returns as HTTP 400: a missing row, a
  string, a number, or `null` on a row that does not offer "Not sure"
  (hard rule 7 — an untouched row is never read as "no"). Nothing is
  recorded when a submission is rejected.
- `options` come from the protocol. A row without an `options` list offers
  Yes/No only. `null` means "not sure" and records the field as `null`;
  a red-flag row may never offer it, because `null` cannot fire the floor.
- `intro` is optional text from the protocol
  (`fixed_text.checklist_intro`), `null` when the protocol has none.
- `reply(text)` → the answer to the open `question`.
- **Out-of-order calls raise `ValueError`**: `submit_checklist` for a group
  that is not the pending one (including a double submit, or B before A),
  and `reply()` while a checklist is pending.
- **No result before checklist A.** `extract()` raises `ValueError` until
  checklist A has been submitted, so "skip to result" can never skip the
  red-flag rows (lead, 2026-09-22). After A, skipping is allowed and the
  unanswered chat fields stay `null`.
- Order and stopping are Python's (`QUESTION_PLAN`): checklist A; any
  red-flag Yes → `done` with `red_flag: true` at once; no pain → `done`;
  with pain, checklist B, then the chat questions. An unclear chat answer
  is asked once more (the protocol's `reask_template`), then left `null`.
- `notice` is set once, on the question after a reply written in a
  non-Latin script: "This assistant works in English only. Please answer
  in English if you can." The reply still counts as evidence.
- `Interview.messages` holds the chat turns only. The triage step reads
  its user turns as `patient_words`. The checklist answers are in
  `symptoms` (and in `Interview.checklist`), which is what the debug JSON
  shows.
- **Evidence differs by input.** A checklist field is the patient's own
  click: it is recorded as given, with no quote and no LLM extraction, and
  the row's text plus the chosen label is what they answered. A chat field
  needs a quote from the patient, checked against the transcript, and a
  bare "yes"/"no" never settles one, because every chat question asks
  which, how, where or how long. Extraction runs over the chat fields only
  and can never overwrite a checklist answer.
- Question text comes from `llm/protocol/triage_protocol.yaml`. The protocol
  is `DRAFT-UNREVIEWED`, so `Interview(..., allow_unreviewed=True)` is needed
  in development.

**Red-flag fields.** A `true` in any of these stops the interview at once
and forces EMERGENCY (the floor, `rules.red_flag_floor`):
`difficulty_swallowing_or_breathing`, `chest_pain_or_breathless`,
`swelling`, `fever`, `systemically_unwell`, `recent_trauma`,
`bleeding_uncontrolled`, `exceeded_pain_relief_dose`.

---

## 3. Triage — LLM input and output

### 3.1 Input (built by code)

- `symptoms` (section 2), after evidence checking.
- `patient_words`: the user turns of the transcript, verbatim, fenced as data.
- `visual_summary`, computed by code from `findings` (the LLM never sees
  raw confidences or a photo):

```json
{
  "images_usable": true,
  "retake_reasons": [],
  "flagged_teeth": [{"fdi": "16", "name": "upper right first molar"}],
  "unexpected_missing_teeth": []
}
```

  `flagged_teeth` are the teeth `rules.caries_teeth()` reports at the
  current threshold; names come from `fdi_label`.
- The triage protocol (`llm/protocol/triage_protocol.yaml`): criteria by id.

### 3.2 Output (schema-constrained, Ollama `format`)

```json
{
  "criteria_met": [
    {
      "criterion_id": "U1",
      "evidence": [
        {"source": "symptoms", "field": "pain_relief_effect",
         "quote": "took some painkillers but it didn't do anything"}
      ]
    }
  ],
  "level": "URGENT",
  "uncertain": false
}
```

- `criterion_id` is an enum generated from the protocol's criterion ids.
- `source` one of `symptoms`, `patient_words`, `visual_summary`. `field`
  is a symptom field name, `flagged_teeth`, `unexpected_missing_teeth`,
  `images_usable`, or `free_text` (for `patient_words`).
- `level` one of `EMERGENCY`, `URGENT`, `SOON`, `ROUTINE` (never `RETAKE`;
  photo quality is code's job).
- `criteria_met` precedes `level`, so the model commits to evidence first.
- No free-text rationale: anything the patient reads is written by the
  explanation step from the validated `assessment.reasons`.

A proposal is **invalid** — retried once, then replaced by the `rules.py`
result — if a cited criterion is unknown, a cited symptom value does not
satisfy the criterion, a quote is not in a user turn or is a bare yes/no,
or `level` is not the most urgent level among the cited criteria
(`ROUTINE` if none).

---

## 4. `assessment` — produced by code (`src/triage.py`)

Schema **2.0**. The keys the UI already uses keep their names and meaning:
`urgency`, `urgency_rank`, `headline`, `flagged_teeth`, `retake_required`,
`limitations`.

```json
{
  "schema_version": "2.0",
  "urgency": "URGENT",
  "urgency_rank": 2,
  "headline": "See a dentist within 24 hours",
  "flagged_teeth": ["16"],
  "retake_required": false,
  "limitations": [
    "Occlusal photos cannot show surfaces between teeth.",
    "They cannot show anything below the gum line or inside the tooth.",
    "This is a screening aid, not a diagnosis."
  ],
  "safety_net": "If you get swelling, a fever, bleeding that will not stop, or trouble breathing or swallowing, go to a hospital straight away.",

  "emergency_route": null,
  "decided_by": "llm",
  "reasons": [
    {
      "criterion_id": "U1",
      "statement": "Tooth pain not controlled by pain relief the patient has taken",
      "evidence": [
        {"source": "symptoms", "field": "pain_relief_effect",
         "value": "not_helped",
         "quote": "took some painkillers but it didn't do anything"}
      ]
    }
  ],

  "triage": {
    "protocol_version": "0.1",
    "protocol_review_status": "DRAFT-UNREVIEWED",
    "model": "qwen3:14b",
    "llm_proposed": "URGENT",
    "llm_valid": true,
    "attempts": 1,
    "validation_errors": [],
    "protocol_level": "URGENT",
    "level": "URGENT",
    "floor": {"level": null, "red_flags": []},
    "overridden_by": null
  },

  "rules_baseline": {
    "urgency": "URGENT",
    "rule_id": "R3",
    "rule_reason": "lingering_or_spontaneous_or_biting_pain"
  }
}
```

`urgency` ∈ `EMERGENCY` (rank 1), `URGENT` (2), `SOON` (3),
`ROUTINE` (4), `RETAKE` (0).

- `headline`: fixed text per level, from the protocol. EMERGENCY is always
  "This may be an emergency. Please go to a hospital as soon as possible."
  (decision 2026-09-22 #9); URGENT = within 24 hours; SOON = within 7 days.
- `safety_net`: fixed text, present in every assessment.
- `emergency_route` ∈ `medical`, `dental`, `either`, `null`. Recorded for
  research only; **not shown** to the patient. `null` unless EMERGENCY.
  Set by code from the EMERGENCY criteria that hold (medical wins).
- `decided_by` ∈ `llm`, `red_flag_floor`, `protocol_check`,
  `fallback_rules`: which source set the final level.
- `reasons`: the validated criteria behind the final level. When the floor,
  the protocol check or the fallback decides, code writes them.
- `triage.llm_proposed`: the model's level, `null` if the model was not
  called (red-flag stop) or was invalid twice.
  `triage.overridden_by` ∈ `null`, `red_flag_floor`, `protocol_check`: set
  only when that source raised the level above `llm_proposed`.
- `triage.level`: the composed level **before** the photo-quality step, so a
  case whose photos were unusable can still be scored on the level it
  reached. `urgency` is what the patient is shown; `triage.level` is what
  triage decided.
- `triage.floor.red_flags`: the red-flag fields that were `true`.
- `rules_baseline`: what `llm/rules.py` decides on the same input. Shadow
  only — used for comparison and as the fallback.
- If the images are unusable and the level would be `SOON` or `ROUTINE`,
  `urgency` is `RETAKE`. `retake_required` is `true` whenever the images are
  unusable, whatever the level; symptoms that need care are never hidden
  behind a bad photo.
- `rule_id` / `rule_reason` no longer exist at the top level (they moved
  into `rules_baseline`).

**Status:** `src/assess.py` stays the thin wrapper around `rules.py` and keeps
returning the rules result in the 1.0 shape. That is the baseline that Test 1
(`check_rules.py`) checks, and it is what fills `rules_baseline`. The
2.0 `assessment` comes from `src/triage.py` (task T5).

---

## 5. Explanation step

The explanation LLM receives `findings`, `symptoms` and `assessment` and may
restate them. It may not contradict them, add teeth, or change the urgency.
