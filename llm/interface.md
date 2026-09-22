# interface.md — data contract

Three JSON objects flow through the system. Everything downstream depends
on these shapes. Change them here first, then update code.

---

## 1. `findings` — produced by the vision pipeline

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

---

## 2. `symptoms` — produced by the LLM interview, validated against schema

```json
{
  "schema_version": "1.0",
  "pain_present": true,
  "pain_triggers": ["cold"],
  "pain_lingers_over_30s": true,
  "pain_wakes_at_night": false,
  "pain_on_biting": false,
  "swelling": false,
  "fever": false,
  "difficulty_swallowing_or_breathing": false,
  "recent_trauma": false,
  "bleeding_gums": false,
  "location": "lower_left",
  "duration_days": 7,
  "notes": "verbatim user phrasing, optional"
}
```

- Any field the user did not answer must be `null`, never guessed.
- `pain_triggers` subset of: `cold`, `hot`, `sweet`, `biting`,
  `spontaneous`, `unknown`.
- `location` one of: `upper_left`, `upper_right`, `lower_left`,
  `lower_right`, `front`, `generalised`, `unknown`, `null`.
- See `prompts/symptoms_schema.json` for the machine-readable version.

---

## 3. `assessment` — produced by `rules.py`

```json
{
  "schema_version": "1.0",
  "urgency": "URGENT",
  "urgency_rank": 2,
  "rule_id": "R3",
  "rule_reason": "pain_lingers_over_30s",
  "headline": "See a dentist within a few days",
  "flagged_teeth": ["16"],
  "retake_required": false,
  "limitations": [
    "Occlusal photos cannot show surfaces between teeth.",
    "They cannot show anything below the gum line or inside the tooth."
  ]
}
```

`urgency` ∈ `EMERGENCY` (rank 1), `URGENT` (2), `SOON` (3),
`ROUTINE` (4), `RETAKE` (0).

The LLM receives all three objects and may restate them. It may not
contradict them, add teeth, or change the urgency.
