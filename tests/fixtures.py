"""Shared fixtures for the triage unit tests (no GPU, no Ollama).

PROTOCOL mirrors the shape of research-pm's protocol in
docs/plans/phase1-2-plan.md §2.2–2.3, trimmed. It is test data, not
clinical content: the wording and levels here are placeholders, and the real
file is llm/protocol/triage_protocol.yaml.
"""
import copy
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for sub in ("src", "llm"):
    if str(REPO_ROOT / sub) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / sub))

_BOOL = {"type": ["boolean", "null"]}

# symptoms 1.1 (interface.md §2), built on the 1.0 file so the two can't drift.
SYMPTOM_SCHEMA = json.loads((REPO_ROOT / "llm" / "prompts" / "symptoms_schema.json")
                            .read_text(encoding="utf-8"))
if SYMPTOM_SCHEMA["properties"]["schema_version"].get("const") == "1.0":
    SYMPTOM_SCHEMA = copy.deepcopy(SYMPTOM_SCHEMA)
    SYMPTOM_SCHEMA["properties"].update({
        "pain_relief_effect": {"type": ["string", "null"],
                               "enum": ["helped", "not_helped", "not_tried", None]},
        "pain_severity": {"type": ["string", "null"],
                          "enum": ["mild", "moderate", "severe", None]},
        "systemically_unwell": _BOOL,
        "swelling_features": {"type": ["array", "null"], "uniqueItems": True,
                              "items": {"enum": ["spreading_to_eye_or_neck", "worsening_fast",
                                                 "worsening_slowly", "limited_mouth_opening",
                                                 "tongue_raised", "none"]}},
        "trauma_features": {"type": ["array", "null"], "uniqueItems": True,
                            "items": {"enum": ["head_injury_or_passed_out", "tooth_knocked_out",
                                               "bite_changed", "none"]}},
        "bleeding_uncontrolled": _BOOL,
        "chest_pain_or_breathless": _BOOL,
        "exceeded_pain_relief_dose": _BOOL,
        "recent_extraction": _BOOL,
    })

PROTOCOL = {
    "protocol_version": "0.0-test",
    "review_status": "DRAFT-UNREVIEWED",
    "levels": {
        "EMERGENCY": {"headline": "This may be an emergency. Please go to a hospital as soon as possible."},
        "URGENT": {"headline": "See a dentist within 24 hours"},
        "SOON": {"headline": "See a dentist within 7 days"},
        "ROUTINE": {"headline": "No urgent action; mention this at your next check-up"},
    },
    "safety_net": "If you get swelling, a fever, bleeding that will not stop, or trouble "
                  "breathing or swallowing, go to a hospital straight away.",
    "limitations": ["These photos show the biting surfaces only.",
                    "A cavity can be there even when the photos show nothing."],
    "fixed_text": {"disclaimer": "This is an AI screening tool, not an examination by a dentist.",
                   "photo_finding_phrase": "Based on the image, there is an indication of",
                   "routine_advice": "Brush twice a day with fluoride toothpaste."},
    "reask_template": "Sorry, I need a clearer answer to keep you safe. {question}",
    "criteria": [
        {"id": "EM1", "level": "EMERGENCY", "kind": "structured", "floor": True, "route": "medical",
         "predicate": "difficulty_swallowing_or_breathing == true",
         "statement": "Difficulty breathing or swallowing", "source": "test"},
        {"id": "EM2", "level": "EMERGENCY", "kind": "structured", "route": "medical",
         "predicate": "swelling_features contains spreading_to_eye_or_neck OR "
                      "swelling_features contains worsening_fast",
         "statement": "Swelling spreading or getting worse quickly", "source": "test"},
        {"id": "EM4", "level": "EMERGENCY", "kind": "structured", "floor": True, "route": "medical",
         "predicate": "fever OR systemically_unwell",
         "statement": "Fever or feeling very unwell", "source": "test"},
        {"id": "ED1", "level": "EMERGENCY", "kind": "structured", "route": "dental",
         "predicate": "trauma_features contains tooth_knocked_out",
         "statement": "Adult tooth knocked out", "source": "test"},
        {"id": "ED2", "level": "EMERGENCY", "kind": "structured", "floor": True, "route": "dental",
         "predicate": "bleeding_uncontrolled == true",
         "statement": "Bleeding that pressure does not stop", "source": "test"},
        {"id": "EF1", "level": "EMERGENCY", "kind": "structured", "floor": True, "route": "either",
         "predicate": "swelling == true OR recent_trauma == true OR chest_pain_or_breathless == true "
                      "OR exceeded_pain_relief_dose == true",
         "statement": "Other red flag", "source": "test"},
        {"id": "U1", "level": "URGENT", "kind": "structured",
         "predicate": "pain_present AND pain_relief_effect == not_helped",
         "statement": "Tooth pain not controlled by pain relief", "source": "test"},
        {"id": "U2", "level": "URGENT", "kind": "structured",
         "predicate": "pain_on_biting == true OR pain_triggers contains biting",
         "statement": "Pain on biting", "source": "test"},
        {"id": "U3", "level": "URGENT", "kind": "structured",
         "predicate": "pain_present AND pain_severity == severe",
         "statement": "Unbearable pain", "source": "test"},
        {"id": "U5", "level": "URGENT", "kind": "narrative",
         "statement": "Adult tooth moved or broken to the nerve after an injury", "source": "test"},
        {"id": "N1", "level": "SOON", "kind": "structured", "predicate": "pain_present == true",
         "statement": "Tooth pain", "source": "test"},
        {"id": "N3", "level": "SOON", "kind": "narrative",
         "statement": "Broken or lost filling, chipped tooth", "source": "test"},
        {"id": "P1", "level": "SOON", "kind": "structured",
         "predicate": "visual_summary.flagged_teeth non-empty",
         "statement": "Possible cavity flagged in the photo", "source": "test"},
        {"id": "P2", "level": "ROUTINE", "kind": "structured",
         "predicate": "unexpected_missing_teeth non-empty",
         "statement": "A tooth appears to be missing", "source": "test"},
    ],
    "questions": [
        {"id": "Q1", "input": "yesno_checklist", "group": "A", "fields": ["difficulty_swallowing_or_breathing"], "red_flag": True,
         "text": "Do you have any difficulty breathing or swallowing?"},
        {"id": "Q1b", "input": "yesno_checklist", "group": "A", "fields": ["chest_pain_or_breathless"], "red_flag": True,
         "text": "Along with the tooth or jaw pain, do you have chest pain or feel short of breath?"},
        {"id": "Q2", "input": "yesno_checklist", "group": "A", "fields": ["swelling"], "red_flag": True,
         "text": "Is there any swelling in your face or gums?"},
        {"id": "Q3", "input": "yesno_checklist", "group": "A", "fields": ["fever"], "red_flag": True, "text": "Do you have a fever?"},
        {"id": "Q3b", "input": "yesno_checklist", "group": "A", "fields": ["systemically_unwell"], "red_flag": True,
         "text": "Are you shivering, or feeling very unwell or very tired?"},
        {"id": "Q4", "input": "yesno_checklist", "group": "A", "fields": ["recent_trauma"], "red_flag": True,
         "text": "Have you recently had a knock or injury to your mouth or teeth?"},
        {"id": "Q5", "input": "yesno_checklist", "group": "A", "fields": ["bleeding_uncontrolled"], "red_flag": True,
         "text": "Is there bleeding in your mouth that won't stop when you press on it?"},
        {"id": "Q7", "input": "yesno_checklist", "group": "A", "fields": ["exceeded_pain_relief_dose"], "red_flag": True,
         "text": "Have you taken more pain relief than the packet says is safe?"},
        {"id": "Q6", "input": "yesno_checklist", "group": "A", "fields": ["pain_present"], "text": "Do you have any tooth or gum pain right now?"},
        {"id": "Q15", "input": "yesno_checklist", "group": "B", "fields": ["pain_on_biting"],
         "asked_if": "pain_present == true", "text": "Does it hurt when you bite down?"},
        {"id": "Q8", "input": "chat", "fields": ["pain_relief_effect"], "asked_if": "pain_present == true",
         "text": "Have you tried pain relief from a pharmacy, and did it help?"},
        {"id": "Q9", "input": "chat", "fields": ["pain_severity"], "asked_if": "pain_present == true",
         "text": "How bad is the pain? Can you sleep and eat normally?"},
        {"id": "Q10", "input": "chat", "fields": ["pain_triggers"], "asked_if": "pain_present == true",
         "text": "What sets the pain off: cold, hot, sweet, biting, or does it come on by itself?"},
        {"id": "Q14", "input": "chat", "fields": ["location"], "asked_if": "pain_present == true",
         "text": "Where is the pain: upper or lower, left or right, or at the front?"},
        {"id": "Q2a", "input": "chat", "fields": ["swelling_features"], "asked_if": "swelling == true",
         "text": "unused in live sessions (decision #9); present so EM2 is covered"},
        {"id": "Q4a", "input": "chat", "fields": ["trauma_features"], "asked_if": "recent_trauma == true",
         "text": "unused in live sessions (decision #9); present so ED1 is covered"},
    ],
}


def protocol_raw() -> dict:
    return copy.deepcopy(PROTOCOL)


def build_protocol(raw: dict = None):
    import protocol
    return protocol.build(raw or protocol_raw(), symptom_schema=SYMPTOM_SCHEMA)
