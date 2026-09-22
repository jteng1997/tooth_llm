"""Run segmentation + per-tooth caries screening over a labeled dataset.

    python src/screen_dataset.py --output runs/mendeley_screening

Walks dataset/mendeley-{carious,noncarious}-dataset, taking the view from
the "Upper/Lower Occlusal" folder and the image-level caries label from the
dataset folder. Writes:

  teeth.csv   one row per segmented tooth, with the best caries detection
              confidence (0 if none) — so thresholds can be swept later
              without re-running the models
  images.csv  one row per photo: teeth found and the highest per-tooth
              caries confidence in it
  crops/      annotated crops for the first --crop-examples flagged teeth
              of each label, for eyeballing results

Resumable: images already in teeth.csv are skipped.
"""
import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

from caries_tool import CariesDetector, annotate, crop_tooth
from preprocess import REPO_ROOT
from segment_tool import segment_teeth_mask

DATASETS = {"carious": REPO_ROOT / "dataset" / "mendeley-carious-dataset",
            "noncarious": REPO_ROOT / "dataset" / "mendeley-noncarious-dataset"}
VIEWS = {"Upper Occlusal": "upper", "Lower Occlusal": "lower"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default=str(REPO_ROOT / "runs" / "mendeley_screening"))
    ap.add_argument("--conf", type=float, default=0.25, help="Detector floor; sweep higher later")
    ap.add_argument("--crop-examples", type=int, default=40)
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    teeth_csv, images_csv = out / "teeth.csv", out / "images.csv"

    # Resume from images.csv: a photo with no teeth writes no teeth.csv rows,
    # so keying on that file would reprocess it every run.
    done = set()
    if images_csv.exists():
        done = {r["file"] for r in csv.DictReader(open(images_csv))}

    detector = CariesDetector(conf=args.conf)
    tf = open(teeth_csv, "a", newline="")
    imf = open(images_csv, "a", newline="")
    tw = csv.writer(tf)
    iw = csv.writer(imf)
    if not done:
        tw.writerow(["label", "view", "file", "fdi", "caries_conf", "caries_label", "box_area_frac"])
        iw.writerow(["label", "view", "file", "n_teeth", "max_caries_conf"])

    saved = {"carious": 0, "noncarious": 0}
    todo = [(label, VIEWS[sub.name], p)
            for label, root in DATASETS.items()
            for sub in sorted(root.iterdir()) if sub.is_dir() and sub.name in VIEWS
            for p in sorted(q for ext in ("*.jpg", "*.jpeg") for q in sub.glob(ext))]

    for i, (label, view, path) in enumerate(todo):
        if path.name in done:
            continue
        image = cv2.imread(str(path))
        if image is None:
            continue
        mask = segment_teeth_mask(str(path), view=view)
        fdis = sorted(int(v) for v in np.unique(mask) if v)
        best_image_conf = 0.0
        for fdi in fdis:
            crop, _, _ = crop_tooth(image, mask, fdi)
            findings = detector.findings(crop)
            if findings:
                f = findings[0]
                x0, y0, x1, y1 = f["box"]
                area_frac = ((x1 - x0) * (y1 - y0)) / (crop.shape[0] * crop.shape[1])
                tw.writerow([label, view, path.name, fdi, f["confidence"], f["label"], round(area_frac, 5)])
                best_image_conf = max(best_image_conf, f["confidence"])
                if saved[label] < args.crop_examples and f["confidence"] >= 0.4:
                    d = out / "crops" / label
                    d.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(d / f"{path.stem}_t{fdi}.jpg"), annotate(crop, findings))
                    saved[label] += 1
            else:
                tw.writerow([label, view, path.name, fdi, 0.0, "", 0.0])
        iw.writerow([label, view, path.name, len(fdis), best_image_conf])
        if i % 25 == 0:
            tf.flush()
            imf.flush()
            print(f"[{i + 1}/{len(todo)}] {label}/{path.name}: {len(fdis)} teeth, max conf {best_image_conf:.2f}")

    tf.close()
    imf.close()
    print(f"done -> {teeth_csv}")


if __name__ == "__main__":
    main()
