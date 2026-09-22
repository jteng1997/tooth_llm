"""Train the per-patch tooth classifier used to locate the dental arch.

    python src/train_tooth_patch_classifier.py [--holdout 1 30]

No hand labels needed: SegmentAnyTooth's YOLO tooth boxes provide
pseudo-labels. Patches inside a confident box (conf >= 0.5) are teeth;
patches well away from every box are not. Patches just around boxes are
ignored, and in photos where few teeth were detected only background
outside the oral region counts as negative, since missed teeth would
otherwise be learned as "not tooth". Saves
models/tooth_patch_classifier.joblib.
"""
import argparse

import cv2
import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression

import segment_tool  # adds vendor dir to sys.path, patches torch.load
from preprocess import PATCH_GRID, REPO_ROOT, TOOTH_PATCH_CLASSIFIER_PATH, Dino, find_oral_region

DATASET = REPO_ROOT / "dataset" / "malawi-dataset"
POSITIVE_CONF = 0.5
IGNORE_MARGIN = 0.3
MIN_CONFIDENT_TEETH = 8


def detect_teeth(models, image, oral):
    import torch
    import torchvision

    x, y, w, h = oral
    crop = image[y:y + h, x:x + w]
    boxes, scores = [], []
    for m in models:
        r = m.predict(crop, conf=0.25, imgsz=1024, verbose=False)[0]
        if len(r.boxes):
            boxes.append(r.boxes.xyxy.cpu())
            scores.append(r.boxes.conf.cpu())
    if not boxes:
        return np.zeros((0, 5))
    b, s = torch.cat(boxes), torch.cat(scores)
    keep = torchvision.ops.nms(b, s, 0.4)
    out = torch.cat([b[keep], s[keep, None]], dim=1).numpy()
    out[:, [0, 2]] += x
    out[:, [1, 3]] += y
    return out


def patch_labels(boxes, oral, shape):
    H, W = shape
    gy, gx = np.mgrid[0:PATCH_GRID, 0:PATCH_GRID]
    px, py = (gx + 0.5) * W / PATCH_GRID, (gy + 0.5) * H / PATCH_GRID
    confident = boxes[boxes[:, 4] >= POSITIVE_CONF]
    pos = np.zeros((PATCH_GRID, PATCH_GRID), bool)
    near = np.zeros((PATCH_GRID, PATCH_GRID), bool)
    for b in confident:
        pos |= (px >= b[0]) & (px <= b[2]) & (py >= b[1]) & (py <= b[3])
    for b in boxes:
        mx, my = IGNORE_MARGIN * (b[2] - b[0]), IGNORE_MARGIN * (b[3] - b[1])
        near |= (px >= b[0] - mx) & (px <= b[2] + mx) & (py >= b[1] - my) & (py <= b[3] + my)
    neg = ~near
    if len(confident) < MIN_CONFIDENT_TEETH:
        x, y, w, h = oral
        neg &= ~((px >= x) & (px <= x + w) & (py >= y) & (py <= y + h))
    return pos, neg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", nargs="*", default=[], help="Patient folders to exclude")
    args = ap.parse_args()

    from segmentanytooth import get_model_path
    from ultralytics import YOLO

    weights = str(segment_tool.DEFAULT_WEIGHT_DIR)
    yolo = [YOLO(get_model_path(v, weights)) for v in ("upper", "lower")]
    dino = Dino()

    X, Y = [], []
    folders = sorted((p for p in DATASET.iterdir() if p.is_dir() and p.name not in args.holdout),
                     key=lambda p: (len(p.name), p.name))
    for folder in folders:
        for photo in sorted(folder.glob("*.jpg")):
            image = cv2.imread(str(photo))
            oral = find_oral_region(image)
            if oral is None:
                continue
            pos, neg = patch_labels(detect_teeth(yolo, image, oral), oral, image.shape[:2])
            tokens = dino.patch_tokens(image)
            X += [tokens[pos], tokens[neg]]
            Y += [np.ones(pos.sum()), np.zeros(neg.sum())]
        print(f"patient {folder.name} done")

    X, Y = np.concatenate(X), np.concatenate(Y)
    print(f"{len(Y)} patches, {Y.mean():.1%} tooth")
    clf = LogisticRegression(C=0.5, max_iter=3000, class_weight="balanced").fit(X, Y)
    TOOTH_PATCH_CLASSIFIER_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, TOOTH_PATCH_CLASSIFIER_PATH)
    print(f"saved {TOOTH_PATCH_CLASSIFIER_PATH}")


if __name__ == "__main__":
    main()
