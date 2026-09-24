"""Synthetic findings for Test 2, generated rather than photographed.

llm/eval asks for several hundred synthetic `findings` varying tooth
count, missing teeth, confidence values, zero and many findings,
unassigned detections and unusable images. No photos needed: the point is
to test what the explanation step does with a JSON object, and the object
is cheap to fabricate.

Seeded, so a run is reproducible and two models see identical inputs.

    python src/eval_data.py --n 5        # preview
"""
import argparse
import json
import random

UPPER = [f"1{i}" for i in range(1, 9)] + [f"2{i}" for i in range(1, 9)]
LOWER = [f"3{i}" for i in range(1, 9)] + [f"4{i}" for i in range(1, 9)]
DETECTION_TYPES = ["caries", "caries", "caries", "cavity", "restoration", "other"]

RED_FLAG_SYMPTOMS = [
    {"swelling": True, "pain_present": True},
    {"difficulty_swallowing_or_breathing": True},
    {"recent_trauma": True},
]
PAIN_SYMPTOMS = [
    {"pain_present": True, "pain_triggers": ["cold"], "pain_lingers_over_30s": True},
    {"pain_present": True, "pain_triggers": ["sweet"], "pain_lingers_over_30s": False},
    {"pain_present": True, "pain_wakes_at_night": True},
    {"pain_present": True, "pain_on_biting": True},
    {"pain_present": True, "pain_triggers": ["unknown"]},
]


def _arch(rng: random.Random, teeth_pool: list, usable: bool) -> tuple:
    """(quality, arch, teeth) for one arch."""
    if not usable:
        return ({"usable": False, "reasons": ["no_teeth_detected"]},
                {"present": False, "teeth_detected": 0}, {})
    count = rng.choice([8, 10, 12, 13, 14, 14, 15, 16])
    chosen = sorted(rng.sample(teeth_pool, count), key=int)
    teeth = {fdi: {"present": True, "detections": []} for fdi in chosen}
    # occasionally a tooth assessed and reported missing
    if rng.random() < 0.15 and chosen:
        teeth[rng.choice(chosen)] = {"present": False, "detections": []}
    reasons = ["arch_cropped"] if count < 12 and rng.random() < 0.5 else []
    return ({"usable": True, "reasons": reasons},
            {"present": True, "teeth_detected": count}, teeth)


def generate(n: int, seed: int = 0) -> list:
    rng = random.Random(seed)
    cases = []
    for i in range(n):
        upper_usable = rng.random() > 0.08
        lower_usable = rng.random() > 0.08
        qu, au, tu = _arch(rng, UPPER, upper_usable)
        ql, al, tl = _arch(rng, LOWER, lower_usable)
        teeth = {**tu, **tl}

        # how many teeth carry a detection, and how confident
        present = [f for f, t in teeth.items() if t["present"]]
        roll = rng.random()
        n_det = 0 if roll < 0.35 else (rng.randint(1, 2) if roll < 0.80 else rng.randint(3, 6))
        for fdi in rng.sample(present, min(n_det, len(present))):
            # deliberately straddle the 0.50 reporting threshold
            confidence = round(rng.choice([rng.uniform(0.20, 0.49), rng.uniform(0.50, 0.95)]), 3)
            teeth[fdi]["detections"].append({
                "type": rng.choice(DETECTION_TYPES),
                "confidence": confidence,
                "area_frac": round(rng.uniform(0.002, 0.15), 4),
            })

        findings = {
            "schema_version": "1.0",
            "image_quality": {"upper": qu, "lower": ql},
            "arches": {"upper": au, "lower": al},
            "teeth": {k: teeth[k] for k in sorted(teeth, key=int)},
            "unassigned_detections": (
                [{"type": "caries", "confidence": round(rng.uniform(0.3, 0.8), 3),
                  "reason": "no_tooth_overlap"}] if rng.random() < 0.12 else []),
            "model_versions": {"segmentation": "segmentanytooth_yolo11_upper+lower",
                               "caries": "yolov8_caries_detector@AndreyGermanov (DentalAI)"},
        }

        roll = rng.random()
        if roll < 0.50:
            symptoms = None if rng.random() < 0.5 else {"pain_present": False, "swelling": False}
        elif roll < 0.85:
            symptoms = dict(rng.choice(PAIN_SYMPTOMS))
        else:
            symptoms = dict(rng.choice(RED_FLAG_SYMPTOMS))
        if symptoms is not None:
            symptoms["schema_version"] = "1.0"

        cases.append({"id": f"S{i:04d}", "note": "synthetic", "findings": findings,
                      "symptoms": symptoms})
    return cases


CHECKLIST_A = ("difficulty_swallowing_or_breathing", "chest_pain_or_breathless", "swelling", "fever",
               "systemically_unwell", "recent_trauma", "bleeding_uncontrolled",
               "exceeded_pain_relief_dose", "persistent_ulcer", "broken_filling_or_tooth",
               "pus_or_discharge")
CHECKLIST_B = ("pain_lingers_over_30s", "pain_wakes_at_night", "pain_on_biting", "recent_extraction")
LOCATIONS = ("upper_left", "upper_right", "lower_left", "lower_right", "front")
FOLLOW_UPS = (
    "What does this result mean for me?",
    "Is this serious?",
    "Why does my tooth hurt?",
    "Which tooth is causing my pain?",
    "What can I do until I see a dentist?",
    "Could the photos have missed something?",
    "What is a cavity?",
    "Do I really need to go to a dentist?",
)


def _symptoms_v2(rng: random.Random) -> dict:
    """A symptoms object in the shape the planned interview produces:
    every checklist row answered, chat fields only with pain."""
    s = {"schema_version": "1.2", **{f: False for f in CHECKLIST_A}, "pain_present": False,
         **{f: None for f in CHECKLIST_B}, "pain_relief_effect": None, "pain_severity": None,
         "pain_triggers": None, "location": None, "duration_days": None}
    roll = rng.random()
    if roll < 0.10:
        s[rng.choice(CHECKLIST_A[:8])] = True          # a red flag: the floor decides
        return s
    if roll < 0.40:
        return s                                        # no pain
    s["pain_present"] = True
    s.update({f: rng.random() < 0.25 for f in CHECKLIST_B})
    s["pain_relief_effect"] = rng.choice(["helped", "not_helped", "not_tried", None])
    s["pain_severity"] = rng.choice(["mild", "moderate", "severe", None])
    s["pain_triggers"] = rng.choice([["cold"], ["sweet"], ["cold", "sweet"], ["biting"],
                                     ["spontaneous"], ["unknown"], None])
    # half the pain cases name where it hurts, so the allowed-side branch of
    # explain.places_pain() is exercised as well as the no-location one
    s["location"] = rng.choice(LOCATIONS) if rng.random() < 0.5 else None
    s["duration_days"] = rng.choice([1, 3, 7, 14, 30, None])
    return s


def generate_v2(n: int, seed: int = 0) -> list:
    """Cases for the triage-2.0 Test 2 mode: the same findings generator,
    1.2 symptoms, and two follow-up questions per case. A separate stream
    from generate(), so the legacy cases stay identical."""
    base = generate(n, seed)
    rng = random.Random(f"v2-{seed}")
    for case in base:
        case["symptoms"] = _symptoms_v2(rng)
        case["follow_ups"] = rng.sample(FOLLOW_UPS, 2)
        case["note"] = "synthetic v2"
    return base


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    for case in generate(args.n, args.seed):
        print(json.dumps(case, indent=2)[:900])
        print("---")
