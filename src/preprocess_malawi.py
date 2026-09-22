"""Batch-preprocess the Malawi dataset into upper/lower occlusal crops.

    python src/preprocess_malawi.py [--input dataset/malawi-dataset]
                                    [--output runs/malawi_occlusal]
                                    [--patients 1 5 10]

Writes <output>/<patient>/<photo stem>_<view>.jpg and <output>/manifest.csv
with one row per photo: view, p_upper, arch box (x0 y0 x1 y1), and flags that
point manual review at likely mistakes. Every hand-labeled session was shot
as one block of one view then one block of the other, so "session_order"
marks photos that break the best such split for their session.
"""
import argparse
import csv
from pathlib import Path

import cv2

from preprocess import REPO_ROOT, OcclusalPreprocessor


def session_order_outliers(views: list) -> list:
    """Indices of photos that break the best single-block split (all of one
    view, then all of the other, in either order)."""
    labeled = [(i, v) for i, v in enumerate(views) if v]
    best = None
    for first, second in (("upper", "lower"), ("lower", "upper")):
        for split in range(len(labeled) + 1):
            bad = [i for k, (i, v) in enumerate(labeled) if v != (first if k < split else second)]
            if best is None or len(bad) < len(best):
                best = bad
    return best or []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(REPO_ROOT / "dataset" / "malawi-dataset"))
    ap.add_argument("--output", default=str(REPO_ROOT / "runs" / "malawi_occlusal"))
    ap.add_argument("--patients", nargs="*", help="Patient folder names (default: all)")
    args = ap.parse_args()

    src, out = Path(args.input), Path(args.output)
    folders = sorted((p for p in src.iterdir() if p.is_dir()), key=lambda p: (len(p.name), p.name))
    if args.patients:
        folders = [f for f in folders if f.name in set(args.patients)]

    pre = OcclusalPreprocessor()
    rows = []
    for folder in folders:
        session = []
        for photo in sorted(folder.glob("*.jpg")):
            r = pre.process(str(photo))
            row = {
                "patient": folder.name,
                "file": photo.name,
                "view": r["view"] or "",
                "p_upper": "" if r["p_upper"] is None else f"{r['p_upper']:.3f}",
                "arch_box": "" if r["arch_box"] is None else " ".join(map(str, r["arch_box"])),
                "crop": "",
                "flags": list(r["flags"]),
            }
            if r["crop"] is not None:
                dest = out / folder.name / f"{photo.stem}_{r['view']}.jpg"
                dest.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(dest), r["crop"])
                row["crop"] = str(dest.relative_to(out))
            session.append(row)
            print(f"{folder.name}/{photo.name}: {row['view']} p_upper={row['p_upper']} "
                  f"{' '.join(row['flags'])}")

        for i in session_order_outliers([row["view"] for row in session]):
            session[i]["flags"].append("session_order")
        rows.extend(session)

    out.mkdir(parents=True, exist_ok=True)
    with open(out / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["patient", "file", "view", "p_upper", "arch_box", "crop", "flags"])
        w.writeheader()
        for row in rows:
            w.writerow({**row, "flags": ";".join(row["flags"])})

    flagged = sum(1 for r in rows if r["flags"])
    views = [r["view"] for r in rows]
    print(f"\n{len(rows)} photos: {views.count('upper')} upper, {views.count('lower')} lower, "
          f"{flagged} flagged for review -> {out / 'manifest.csv'}")


if __name__ == "__main__":
    main()
