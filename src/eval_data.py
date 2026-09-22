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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    for case in generate(args.n, args.seed):
        print(json.dumps(case, indent=2)[:900])
        print("---")
