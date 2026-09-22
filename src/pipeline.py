"""Vision pipeline: occlusal photos -> findings JSON.

Emits the `findings` object defined in llm/interface.md (schema 1.0). This
is the only thing the vision stack hands downstream; per the architecture
rule in llm/README.md the LLM never sees the photo itself.

    python src/pipeline.py --upper upper.jpg --lower lower.jpg [--out findings.json]

Per-tooth detections come from running the caries detector on each tooth
cut out on its own, which finds more than a whole-photo pass does.
`unassigned_detections` come from a second, whole-photo pass: boxes that
overlap no tooth mask, which is the only way a lesion on a tooth the
segmenter missed can surface at all.

Two honest gaps in what this can fill in, both documented at their site:
teeth are never reported `"present": false`, and `restoration` is never
emitted.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from caries_tool import CARIES_CONF, CariesDetector, crop_tooth
from segment_tool import segment_teeth_mask

SCHEMA_VERSION = "1.0"
SEGMENTATION_MODEL = "segmentanytooth_yolo11_upper+lower"
CARIES_MODEL = "yolov8_caries_detector@AndreyGermanov (DentalAI)"

# Caries model class name -> interface.md detection type. "Tooth" is the
# detector's own tooth class and is not a finding. The detector has no
# restoration class, so "restoration" is never emitted.
DETECTION_TYPES = {"Caries": "caries", "Cavity": "cavity", "Crack": "other"}

MIN_TEETH = 6           # fewer than this in an arch photo means something went wrong
EDGE_MARGIN = 2         # px; mask touching this close to the frame edge is cropped

# No "blurry" reason yet. Variance-of-Laplacian, the usual quick test, tracks
# texture rather than readability here: sharp, readable Mendeley photos score
# anywhere from 2 to 1130, so any global threshold wrongly forces retakes on
# good photos. Needs sharp/blurry labels to calibrate before it can gate usable.


def assess_quality(image: np.ndarray, mask: np.ndarray) -> dict:
    """Quality reasons for one arch photo. `usable` is false only for
    blocking problems (nothing found); framing problems are reported but
    leave the photo usable."""
    reasons = []
    n_teeth = len({int(v) for v in np.unique(mask) if v})
    if n_teeth == 0:
        reasons.append("no_teeth_detected")
    elif n_teeth < MIN_TEETH:
        reasons.append("few_teeth_detected")

    if n_teeth:
        ys, xs = np.where(mask > 0)
        if (ys.min() <= EDGE_MARGIN or xs.min() <= EDGE_MARGIN
                or ys.max() >= mask.shape[0] - 1 - EDGE_MARGIN
                or xs.max() >= mask.shape[1] - 1 - EDGE_MARGIN):
            reasons.append("arch_cropped")

    blocking = {"no_teeth_detected"}
    return {"usable": not (blocking & set(reasons)), "reasons": reasons}


def _detection(label: str, confidence: float, box_area_px: float, tooth_area_px: float) -> dict:
    out = {"type": DETECTION_TYPES[label], "confidence": round(float(confidence), 3)}
    if tooth_area_px > 0:
        out["area_frac"] = round(box_area_px / tooth_area_px, 4)
    return out


def analyze_arch(image_path: str, view: str, detector: CariesDetector) -> dict:
    """Segment one arch photo and screen each tooth. Returns the arch's
    quality, tooth count, per-tooth detections and unassigned boxes."""
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)
    mask = segment_teeth_mask(str(image_path), view=view)
    fdis = sorted(int(v) for v in np.unique(mask) if v)

    teeth = {}
    for fdi in fdis:
        crop, _, scale = crop_tooth(image, mask, fdi)
        tooth_area = float((mask == fdi).sum())
        detections = []
        for f in detector.findings(crop):
            if f["label"] not in DETECTION_TYPES:
                continue
            x0, y0, x1, y1 = f["box"]
            box_area_px = ((x1 - x0) * (y1 - y0)) / (scale ** 2)
            detections.append(_detection(f["label"], f["confidence"], box_area_px, tooth_area))
        # Teeth the segmenter found are present. It cannot tell a missing
        # tooth from one it failed to detect, so "present": false is never
        # emitted — per interface.md an absent key means "not assessed".
        teeth[str(fdi)] = {"present": True, "detections": detections}

    unassigned = []
    for f in detector.findings(image):
        if f["label"] not in DETECTION_TYPES:
            continue
        x0, y0, x1, y1 = f["box"]
        if mask[max(0, y0):y1, max(0, x0):x1].any():
            continue  # overlaps a tooth; already covered by the per-tooth pass
        unassigned.append({"type": DETECTION_TYPES[f["label"]],
                           "confidence": round(float(f["confidence"]), 3),
                           "reason": "no_tooth_overlap"})

    return {"quality": assess_quality(image, mask),
            "teeth_detected": len(fdis),
            "teeth": teeth,
            "unassigned": unassigned}


def build_findings(upper_path: str = None, lower_path: str = None,
                   conf: float = CARIES_CONF) -> dict:
    detector = CariesDetector(conf=conf)
    findings = {
        "schema_version": SCHEMA_VERSION,
        "image_quality": {},
        "arches": {},
        "teeth": {},
        "unassigned_detections": [],
        "model_versions": {"segmentation": SEGMENTATION_MODEL, "caries": CARIES_MODEL},
    }

    for view, path in (("upper", upper_path), ("lower", lower_path)):
        if not path:
            findings["image_quality"][view] = {"usable": False, "reasons": ["missing_image"]}
            findings["arches"][view] = {"present": False, "teeth_detected": 0}
            continue
        arch = analyze_arch(path, view, detector)
        findings["image_quality"][view] = arch["quality"]
        findings["arches"][view] = {"present": arch["teeth_detected"] > 0,
                                    "teeth_detected": arch["teeth_detected"]}
        findings["teeth"].update(arch["teeth"])
        findings["unassigned_detections"].extend(arch["unassigned"])

    findings["teeth"] = {k: findings["teeth"][k] for k in sorted(findings["teeth"], key=int)}
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upper", help="Upper occlusal photo")
    parser.add_argument("--lower", help="Lower occlusal photo")
    parser.add_argument("--out", help="Write JSON here instead of stdout")
    parser.add_argument("--conf", type=float, default=CARIES_CONF,
                        help="Caries detector confidence floor")
    args = parser.parse_args()
    if not (args.upper or args.lower):
        parser.error("pass --upper and/or --lower")

    result = build_findings(args.upper, args.lower, args.conf)
    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
