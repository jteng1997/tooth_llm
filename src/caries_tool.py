"""Per-tooth caries screening, for Claude to call as a tool.

SegmentAnyTooth gives an FDI-numbered mask; each tooth is cut out of the
photo and passed to a caries detector on its own, so every finding is
attributed to one tooth number. Returns JSON plus, for each affected
tooth, a cropped image with the finding boxed — the pictures to hand to
the model alongside the JSON.

    python src/caries_tool.py --image photo.jpg --view lower --output runs/caries_demo

Caries model: YOLOv8 from github.com/AndreyGermanov/yolov8_caries_detector
(classes Caries / Cavity / Crack / Tooth), trained on the DentalAI set of
intraoral photographs. Its confidences on occlusal photos run low, and
CARIES_CONF below is a starting threshold, not a calibrated one — there
are no caries labels for this project's photos to tune it against. Treat
output as a screening flag to review, not a diagnosis.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from preprocess import REPO_ROOT
from segment_tool import segment_teeth_mask

CARIES_WEIGHTS = REPO_ROOT / "weights" / "caries_yolov8.pt"
CARIES_LABELS = {"Caries", "Cavity"}
CARIES_CONF = 0.3
CROP_PADDING = 12
CROP_LONG_SIDE = 300


class CariesDetector:
    def __init__(self, weights: Path = CARIES_WEIGHTS, conf: float = CARIES_CONF):
        from ultralytics import YOLO

        self.model = YOLO(str(weights))
        self.conf = conf

    def findings(self, tooth_crop: np.ndarray) -> list:
        """Caries/cavity detections in one tooth image, most confident first."""
        result = self.model.predict(tooth_crop, conf=self.conf, verbose=False)[0]
        out = []
        for cls, confidence, box in zip(result.boxes.cls.tolist(),
                                        result.boxes.conf.tolist(),
                                        result.boxes.xyxy.tolist()):
            label = self.model.names[int(cls)]
            if label in CARIES_LABELS:
                out.append({"label": label, "confidence": round(float(confidence), 3),
                            "box": [int(v) for v in box]})
        return sorted(out, key=lambda f: -f["confidence"])


def crop_tooth(image: np.ndarray, mask: np.ndarray, fdi: int) -> tuple:
    """Cut one tooth out of the photo, padded and enlarged. Returns
    (crop, (x0, y0) offset in the original image, scale applied), so box
    coordinates can be mapped back to original-image pixels."""
    ys, xs = np.where(mask == fdi)
    y0, y1 = max(0, ys.min() - CROP_PADDING), min(image.shape[0], ys.max() + CROP_PADDING)
    x0, x1 = max(0, xs.min() - CROP_PADDING), min(image.shape[1], xs.max() + CROP_PADDING)
    crop = image[y0:y1, x0:x1]
    scale = CROP_LONG_SIDE / max(crop.shape[:2])
    if scale > 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    else:
        scale = 1.0
    return crop, (x0, y0), scale


def annotate(crop: np.ndarray, findings: list) -> np.ndarray:
    out = crop.copy()
    for f in findings:
        x0, y0, x1, y1 = f["box"]
        cv2.rectangle(out, (x0, y0), (x1, y1), (0, 0, 255), 2)
        cv2.putText(out, f"{f['label']} {f['confidence']:.2f}", (x0, max(14, y0 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
    return out


def screen_teeth(image_path: str, view: str, output_dir: str = None,
                 detector: CariesDetector = None) -> dict:
    """Segment the teeth in one occlusal photo and screen each for caries.

    Returns {"image", "view", "teeth": [{"fdi", "caries", "findings",
    "image"}], "summary"}. Each affected tooth's "image" is a saved crop
    with the finding boxed (when output_dir is given).
    """
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)
    detector = detector or CariesDetector()
    mask = segment_teeth_mask(str(image_path), view=view)

    out_dir = Path(output_dir) if output_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    teeth = []
    for fdi in sorted(int(v) for v in np.unique(mask) if v):
        crop, _, _ = crop_tooth(image, mask, fdi)
        findings = detector.findings(crop)
        record = {"fdi": fdi, "caries": bool(findings), "findings": findings}
        if findings and out_dir:
            path = out_dir / f"{Path(image_path).stem}_tooth{fdi}.jpg"
            cv2.imwrite(str(path), annotate(crop, findings))
            record["image"] = str(path)
        teeth.append(record)

    affected = [t["fdi"] for t in teeth if t["caries"]]
    return {
        "image": str(image_path),
        "view": view,
        "teeth": teeth,
        "summary": {
            "teeth_segmented": len(teeth),
            "teeth_with_caries": len(affected),
            "fdi_with_caries": affected,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--view", required=True, choices=["upper", "lower", "left", "right", "front"])
    ap.add_argument("--output", help="Directory for annotated crops of affected teeth")
    ap.add_argument("--conf", type=float, default=CARIES_CONF)
    args = ap.parse_args()

    result = screen_teeth(args.image, args.view, args.output, CariesDetector(conf=args.conf))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
