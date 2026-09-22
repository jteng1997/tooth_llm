"""Wraps SegmentAnyTooth's predict() and turns its FDI-numbered mask into a
small JSON-friendly summary for Claude to reason over.

SegmentAnyTooth (vendor/segmentanytooth) ships as flat modules, not an
installable package, so we add its directory to sys.path rather than
`pip install` it.

Two things are patched into the vendored module rather than edited there:
the SAM model is moved onto the GPU when one is available (vendor code
leaves it wherever it loads, i.e. CPU), and both models are cached so
batch runs don't reload hundreds of megabytes of weights per image.
"""
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "vendor" / "segmentanytooth"
DEFAULT_WEIGHT_DIR = REPO_ROOT / "weights"

if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

# The published SAM checkpoint was saved from a CUDA tensor. On a machine
# whose installed torch build has no CUDA support (e.g. the CPU-only wheel
# uv/pip picks by default on Windows), torch.load() refuses to deserialize
# it without an explicit CPU map_location. We patch that default here
# rather than editing the vendored/third-party loading code.
if not torch.cuda.is_available():
    _original_torch_load = torch.load

    def _torch_load_cpu(*args, **kwargs):
        kwargs.setdefault("map_location", torch.device("cpu"))
        return _original_torch_load(*args, **kwargs)

    torch.load = _torch_load_cpu

import segmentanytooth as _vendor  # noqa: E402
from segmentanytooth import predict  # noqa: E402

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

_original_sam_load = _vendor.sam_load
_original_yolo = _vendor.YOLO


@lru_cache(maxsize=None)
def _load_sam(checkpoint_path: str):
    return _original_sam_load(checkpoint_path).to(DEVICE)


@lru_cache(maxsize=None)
def _load_yolo(model: str):
    return _original_yolo(model=model)


_vendor.sam_load = _load_sam
_vendor.YOLO = _load_yolo

FDI_QUADRANT_NOTE = (
    "FDI tooth numbering: 1x = upper right, 2x = upper left, "
    "3x = lower left, 4x = lower right (permanent dentition); "
    "5x-8x cover primary (deciduous) teeth in the same quadrant layout."
)

# All 32 permanent FDI tooth numbers, grouped by quadrant, for computing
# which teeth are absent from a detected view.
_UPPER_FDI = [f"1{n}" for n in range(1, 9)] + [f"2{n}" for n in range(1, 9)]
_LOWER_FDI = [f"3{n}" for n in range(1, 9)] + [f"4{n}" for n in range(1, 9)]

View = Literal["upper", "lower", "left", "right", "front"]


def segment_teeth_mask(
    image_path: str,
    view: View,
    weight_dir: str = str(DEFAULT_WEIGHT_DIR),
    sam_batch_size: int = 10,
) -> np.ndarray:
    """Run SegmentAnyTooth on one image; returns a mask whose pixel values
    are FDI tooth numbers (0 = background)."""
    try:
        return predict(
            image_path=image_path,
            view=view,
            weight_dir=weight_dir,
            sam_batch_size=sam_batch_size,
        )
    except IndexError:
        # SegmentAnyTooth's predict() hits a 0-d array edge case when YOLO
        # detects exactly one box (boxes.cls.squeeze(0) over-squeezes). We
        # can't patch vendored code, so we treat it the same as "no
        # detections" rather than crashing the pipeline.
        return np.zeros(cv2.imread(image_path).shape[:2], dtype=np.uint8)


def segment_teeth(
    image_path: str,
    view: View,
    weight_dir: str = str(DEFAULT_WEIGHT_DIR),
    sam_batch_size: int = 10,
) -> dict:
    """Run SegmentAnyTooth on one image and summarize the result.

    Returns a JSON-serializable dict with the FDI numbers detected as
    present, and — for "upper"/"lower" views, where we know the full
    expected tooth set — the FDI numbers that are missing.
    """
    mask = segment_teeth_mask(image_path, view, weight_dir, sam_batch_size)
    present_fdi = sorted(int(v) for v in set(mask.flatten().tolist()) if v != 0)

    summary = {
        "view": view,
        "present_teeth_fdi": present_fdi,
        "tooth_count": len(present_fdi),
    }

    expected = {"upper": _UPPER_FDI, "lower": _LOWER_FDI}.get(view)
    if expected is not None:
        present_str = {str(v) for v in present_fdi}
        summary["missing_teeth_fdi"] = sorted(
            int(f) for f in expected if f not in present_str
        )

    return summary
