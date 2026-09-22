"""
rules.py — deterministic urgency decision.

The LLM does NOT make this decision. This module does.

Rules are evaluated in order; the FIRST match wins. This ordering
guarantees a red flag can never be downgraded by a later rule.

Clinical basis (paraphrased, see knowledge/ for citations):
  R1, R2  SDCEP "Management of Acute Dental Problems" triage flowcharts
  R3, R4  AAE diagnostic terminology (pulpal / periapical conditions)
  R5, R6  ICCMS lesion staging + AAE reversible pulpitis
  R8      WHO Oral Health Surveys: Basic Methods (DMFT recording)

STATUS: DRAFT-UNREVIEWED. Must be signed off by a dentist before use.
"""

from dataclasses import dataclass, field
from typing import Any

# --- Tunable parameters -------------------------------------------------
# These are PARAMETERS, not clinical constants. A dentist should set them.
# Tune CARIES_CONF_THRESHOLD on your validation set favouring SENSITIVITY:
# a missed cavity is worse than a false alarm in a screening tool.

CARIES_CONF_THRESHOLD = 0.50
MIN_TEETH_PER_ARCH = 8          # below this, assume the photo is cropped
LINGERING_PAIN_SECONDS = 30     # convention; documented in knowledge/

EXPECTED_ADULT_FDI = {
    "upper": [f"1{i}" for i in range(1, 9)] + [f"2{i}" for i in range(1, 9)],
    "lower": [f"3{i}" for i in range(1, 9)] + [f"4{i}" for i in range(1, 9)],
}

URGENCY_RANK = {
    "RETAKE": 0, "EMERGENCY": 1, "URGENT": 2, "SOON": 3, "ROUTINE": 4,
}

HEADLINES = {
    "EMERGENCY": "Seek dental or medical care today",
    "URGENT": "See a dentist within a few days",
    "SOON": "Book a dental appointment in the next few weeks",
    "ROUTINE": "No action needed beyond your routine checkup",
    "RETAKE": "Please retake the photos",
}

LIMITATIONS = [
    "Occlusal photos cannot show surfaces between teeth.",
    "They cannot show anything below the gum line or inside the tooth.",
    "This is a screening aid, not a diagnosis.",
]


@dataclass
class Assessment:
    urgency: str
    rule_id: str
    rule_reason: str
    headline: str = ""
    flagged_teeth: list = field(default_factory=list)
    retake_required: bool = False
    schema_version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "urgency": self.urgency,
            "urgency_rank": URGENCY_RANK[self.urgency],
            "rule_id": self.rule_id,
            "rule_reason": self.rule_reason,
            "headline": self.headline or HEADLINES[self.urgency],
            "flagged_teeth": self.flagged_teeth,
            "retake_required": self.retake_required,
            "limitations": LIMITATIONS,
        }


# --- Helpers ------------------------------------------------------------

def _get(d: Any, key: str, default=None):
    return (d or {}).get(key, default)


def caries_teeth(findings: dict) -> list:
    """FDI numbers with a caries/cavity detection above threshold."""
    out = []
    for fdi, t in _get(findings, "teeth", {}).items():
        for det in t.get("detections", []):
            if det.get("type") in ("caries", "cavity") and \
               det.get("confidence", 0) >= CARIES_CONF_THRESHOLD:
                out.append(fdi)
                break
    return sorted(out)


def quality_problems(findings: dict) -> list:
    """Reasons the images are not usable."""
    problems = []
    for arch, q in _get(findings, "image_quality", {}).items():
        if not q.get("usable", True):
            problems += [f"{arch}:{r}" for r in q.get("reasons", [])]
    for arch, a in _get(findings, "arches", {}).items():
        if a.get("present") and a.get("teeth_detected", 0) < MIN_TEETH_PER_ARCH:
            problems.append(f"{arch}:too_few_teeth")
    return problems


def missing_teeth(findings: dict) -> list:
    """Teeth assessed and reported absent, against the adult expectation.

    Note: this over-reports in children and in mixed dentition, and for
    third molars. Suppress or relax it if you collect patient age.
    """
    out = []
    for fdi, t in _get(findings, "teeth", {}).items():
        if t.get("present") is False and not fdi.endswith("8"):
            out.append(fdi)
    return sorted(out)


def any_pain(s: dict) -> bool:
    return bool(_get(s, "pain_present")) or bool(_get(s, "pain_triggers"))


# --- Main entry point ---------------------------------------------------

def assess(findings: dict, symptoms: dict | None = None) -> dict:
    """Return an `assessment` dict. See interface.md."""
    symptoms = symptoms or {}
    caries = caries_teeth(findings)

    # R1 — spreading infection red flags
    if (_get(symptoms, "difficulty_swallowing_or_breathing")
            or (_get(symptoms, "swelling") and _get(symptoms, "fever"))
            or _get(symptoms, "swelling")):
        return Assessment(
            "EMERGENCY", "R1", "swelling_or_systemic_signs", flagged_teeth=caries
        ).to_dict()

    # R2 — trauma
    if _get(symptoms, "recent_trauma"):
        return Assessment(
            "EMERGENCY", "R2", "recent_dental_trauma", flagged_teeth=caries
        ).to_dict()

    # R3 — signs suggesting the pulp is irreversibly involved
    if (_get(symptoms, "pain_lingers_over_30s")
            or _get(symptoms, "pain_wakes_at_night")
            or _get(symptoms, "pain_on_biting")
            or "spontaneous" in (_get(symptoms, "pain_triggers") or [])):
        return Assessment(
            "URGENT", "R3", "lingering_or_spontaneous_or_biting_pain",
            flagged_teeth=caries
        ).to_dict()

    # R7 — unusable images. Placed AFTER red flags on purpose: symptoms
    # that demand care must not be suppressed by a bad photo.
    problems = quality_problems(findings)
    if problems:
        return Assessment(
            "RETAKE", "R7", "image_quality:" + ",".join(problems),
            retake_required=True
        ).to_dict()

    # R4 — detection plus any symptom
    if caries and any_pain(symptoms):
        return Assessment(
            "URGENT", "R4", "caries_detected_with_symptoms", flagged_teeth=caries
        ).to_dict()

    # R5 — detection, no symptoms
    if caries:
        return Assessment(
            "SOON", "R5", "caries_detected_no_symptoms", flagged_teeth=caries
        ).to_dict()

    # R6 — symptoms, nothing visible
    if any_pain(symptoms):
        return Assessment(
            "SOON", "R6", "symptoms_without_visible_finding"
        ).to_dict()

    # R8 — unexpected missing teeth
    missing = missing_teeth(findings)
    if missing:
        return Assessment(
            "SOON", "R8", "unexpected_missing_teeth", flagged_teeth=missing
        ).to_dict()

    # R9 — nothing found, no symptoms
    return Assessment("ROUTINE", "R9", "no_findings_no_symptoms").to_dict()


if __name__ == "__main__":
    import json
    demo_findings = {
        "image_quality": {"upper": {"usable": True, "reasons": []},
                          "lower": {"usable": True, "reasons": []}},
        "arches": {"upper": {"present": True, "teeth_detected": 14},
                   "lower": {"present": True, "teeth_detected": 14}},
        "teeth": {"16": {"present": True,
                         "detections": [{"type": "caries", "confidence": 0.81}]}},
    }
    demo_symptoms = {"pain_present": True, "pain_triggers": ["cold"],
                     "pain_lingers_over_30s": True}
    print(json.dumps(assess(demo_findings, demo_symptoms), indent=2))
