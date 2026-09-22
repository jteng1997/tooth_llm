"""One-off: write hand labels for reviewed Malawi sessions to CSV.

Labeled by eye: palate (rugae / midline raphe) inside the arch = upper;
floor of mouth, lingual frenulum or lifted tongue inside the arch = lower.
Each session was shot as one block of one view then one block of the other
(upper-first in most sessions, lower-first in some), so a session is a list
of (view, photo count) blocks in sorted filename order.
"""
import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET = REPO_ROOT / "dataset" / "malawi-dataset"

SESSIONS = {
    1: [("upper", 7), ("lower", 9)],
    5: [("upper", 4), ("lower", 3)],
    10: [("upper", 3), ("lower", 5)],
    12: [("upper", 4), ("lower", 4)],
    13: [("upper", 7), ("lower", 4)],
    15: [("upper", 8), ("lower", 5)],
    17: [("lower", 3), ("upper", 6)],
    19: [("lower", 7), ("upper", 8)],
    20: [("upper", 9), ("lower", 5)],
    25: [("upper", 8), ("lower", 7)],
    28: [("upper", 8), ("lower", 8)],
    30: [("upper", 5), ("lower", 4)],
}

with open(Path(__file__).parent / "malawi_view_labels.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["patient", "file", "view"])
    for pid, blocks in SESSIONS.items():
        photos = sorted((DATASET / str(pid)).glob("*.jpg"))
        views = [view for view, n in blocks for _ in range(n)]
        if len(views) != len(photos):
            raise ValueError(f"patient {pid}: {len(views)} labels for {len(photos)} photos")
        for photo, view in zip(photos, views):
            w.writerow([pid, photo.name, view])
