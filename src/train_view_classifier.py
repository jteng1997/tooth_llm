"""Train the upper/lower occlusal view classifier from hand labels.

    python src/train_view_classifier.py

Reads labels/malawi_view_labels.csv, embeds each photo's oral-cavity crop
with frozen DINOv2, reports leave-one-patient-out accuracy, then fits on
all labels and saves models/view_classifier.joblib.
"""
import csv
from pathlib import Path

import cv2
import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from preprocess import REPO_ROOT, VIEW_CLASSIFIER_PATH, Dino, find_oral_region

LABELS = REPO_ROOT / "labels" / "malawi_view_labels.csv"
DATASET = REPO_ROOT / "dataset" / "malawi-dataset"


def make_classifier():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=5000))


def main():
    with open(LABELS) as f:
        rows = list(csv.DictReader(f))

    dino = Dino()
    X, y, groups = [], [], []
    for r in rows:
        image = cv2.imread(str(DATASET / r["patient"] / r["file"]))
        oral = find_oral_region(image)
        if oral is None:
            print(f"skip (no oral region): {r['patient']}/{r['file']}")
            continue
        bx, by, bw, bh = oral
        X.append(dino.global_embedding(image[by:by + bh, bx:bx + bw]))
        y.append(1 if r["view"] == "upper" else 0)
        groups.append(r["patient"])
    X, y, groups = np.stack(X), np.array(y), np.array(groups)

    correct = 0
    for g in np.unique(groups):
        test = groups == g
        clf = make_classifier().fit(X[~test], y[~test])
        correct += int((clf.predict(X[test]) == y[test]).sum())
    print(f"leave-one-patient-out accuracy: {correct}/{len(y)} "
          f"({len(np.unique(groups))} patients)")

    VIEW_CLASSIFIER_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(make_classifier().fit(X, y), VIEW_CLASSIFIER_PATH)
    print(f"saved {VIEW_CLASSIFIER_PATH}")


if __name__ == "__main__":
    main()
