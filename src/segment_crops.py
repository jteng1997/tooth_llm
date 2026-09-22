"""Run SegmentAnyTooth over occlusal images.

Preprocessed Malawi crops, taking each photo's view from the manifest:

    python src/segment_crops.py --input runs/malawi_clean_occlusal
                                [--output runs/malawi_clean_segmentation]

Or a folder of images that are already one known view, such as the
Mendeley dataset's "Upper Occlusal" / "Lower Occlusal" folders:

    python src/segment_crops.py --images "dataset/mendeley-dataset/Upper Occlusal"
                                --view upper --output runs/mendeley_upper

Writes per-image masks (uint8 PNG, pixel value = FDI number), colored
overlays, and segmentation.csv.

side_errors is a label-free sanity check: the fewest teeth that must move
for one quadrant to sit entirely to one side of the other (e.g. all 1x left
of all 2x). Nonzero means at least one tooth got a wrong-side number.
"""
import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

from segment_tool import segment_teeth_mask

QUADRANTS = {"upper": (1, 2), "lower": (4, 3)}


def side_errors(mask: np.ndarray, view: str) -> int:
    left_q, right_q = QUADRANTS[view]
    teeth = []
    for fdi in np.unique(mask):
        if fdi:
            teeth.append((np.where(mask == fdi)[1].mean(), fdi // 10))
    if not teeth:
        return 0
    quadrants = [q for _, q in sorted(teeth)]
    best = len(quadrants)
    for left, right in ((left_q, right_q), (right_q, left_q)):
        for split in range(len(quadrants) + 1):
            wrong = sum(q != left for q in quadrants[:split]) + sum(q != right for q in quadrants[split:])
            best = min(best, wrong)
    return best


def overlay(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    rng = np.random.default_rng(1)
    color = np.zeros_like(image)
    for fdi in np.unique(mask):
        if fdi:
            color[mask == fdi] = rng.integers(60, 255, 3)
    out = cv2.addWeighted(image, 0.55, color, 0.45, 0)
    scale = 0.6 * image.shape[1] / 700
    for fdi in np.unique(mask):
        if fdi:
            ys, xs = np.where(mask == fdi)
            cv2.putText(out, str(fdi), (int(xs.mean()) - 12, int(ys.mean()) + 6),
                        cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="Preprocessing output dir (with manifest.csv)")
    ap.add_argument("--images", help="Folder of images that are all one view")
    ap.add_argument("--view", choices=["upper", "lower"], help="Required with --images")
    ap.add_argument("--output", help="Default: <input>_segmentation")
    args = ap.parse_args()

    if args.images:
        if not args.view:
            ap.error("--images requires --view")
        src = Path(args.images)
        items = [(src.name, p.name, args.view, p) for p in sorted(src.glob("*.jpg"))]
    elif args.input:
        src = Path(args.input)
        items = [(r["patient"], r["file"], r["view"], src / r["crop"])
                 for r in csv.DictReader(open(src / "manifest.csv")) if r["crop"]]
    else:
        ap.error("pass --input or --images")

    out = Path(args.output) if args.output else src.parent / f"{src.name}_segmentation"
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for i, (patient, file, view, image_path) in enumerate(items):
        mask = segment_teeth_mask(str(image_path), view=view)
        present = sorted(int(v) for v in np.unique(mask) if v)
        stem = image_path.stem

        for kind, image in (("masks", mask), ("overlays", overlay(cv2.imread(str(image_path)), mask))):
            path = out / kind / patient / f"{stem}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), image)

        rows.append({
            "patient": patient,
            "file": file,
            "view": view,
            "n_teeth": len(present),
            "present_fdi": " ".join(map(str, present)),
            "side_errors": side_errors(mask, view),
            "overlay": f"overlays/{patient}/{stem}.png",
        })
        print(f"[{i + 1}/{len(items)}] {patient}/{stem}: {view} "
              f"{rows[-1]['n_teeth']} teeth, side errors {rows[-1]['side_errors']}")

    with open(out / "segmentation.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    counts = [r["n_teeth"] for r in rows]
    print(f"\n{len(rows)} crops, mean {np.mean(counts):.2f} teeth, "
          f"{sum(c == 0 for c in counts)} with none, "
          f"{sum(r['side_errors'] > 0 for r in rows)} with side errors -> {out / 'segmentation.csv'}")


if __name__ == "__main__":
    main()
