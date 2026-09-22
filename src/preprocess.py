"""Preprocessing for the Malawi dataset's wide-angle fisheye intraoral
photos: decide whether each photo is an upper or lower occlusal shot, then
crop so the dental arch fills ~80% of the output image.

Each photo documents one arch. In both view types that arch appears as a U
with the incisors nearest the lens (bottom of frame); the other arch may
show as a few teeth in the top corners. Geometry therefore can't tell the
views apart — what's inside the U does: palate (rugae, midline raphe) for
upper, tongue tip / floor of mouth for lower. SegmentAnyTooth's upper and
lower detectors both fire on any teeth (≈50% as a view classifier on
hand-labeled photos), so both steps below use frozen DINOv2 features with
small trained heads instead.

Pipeline per photo:
1. Oral cavity: the camera's LED gives the inside of the mouth a bright,
   blue/purple cast unlike the warm, dim room; an HSV threshold isolates it.
2. View: DINOv2 global embedding of the oral crop -> logistic regression
   trained on hand labels (train_view_classifier.py).
3. Arch: DINOv2 patch tokens of the whole photo -> per-patch tooth
   probability (train_tooth_patch_classifier.py). The main arch is the
   tooth region with the largest convex hull — a U encloses the palate or
   tongue, while the other arch's corner teeth don't — plus any pieces in
   the same vertical band (arches often split at blurry incisors).
4. Crop: expand the arch box so it spans ARCH_FILL of the output in each
   dimension; pad with black where that runs past the photo edge.
"""
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"
VIEW_CLASSIFIER_PATH = MODELS_DIR / "view_classifier.joblib"
TOOTH_PATCH_CLASSIFIER_PATH = MODELS_DIR / "tooth_patch_classifier.joblib"

EMBED_MODEL = "vit_small_patch14_dinov2.lvd142m"
PATCH_INPUT = 518
PATCH_GRID = PATCH_INPUT // 14
MASK_UPSAMPLE = 4

ORAL_HUE_RANGE = (80, 160)
ORAL_MIN_VALUE = 100
MORPH_KERNEL = np.ones((9, 9), np.uint8)

TOOTH_PROB_THRESHOLD = 0.8
ARCH_FILL = 0.8
UNCERTAIN_VIEW_BAND = (0.25, 0.75)


def find_oral_region(image: np.ndarray) -> Optional[tuple]:
    """Bounding box (x, y, w, h) of the largest LED-lit region, or None."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h_ch, _, v_ch = cv2.split(hsv)
    lo, hi = ORAL_HUE_RANGE
    mask = ((v_ch > ORAL_MIN_VALUE) & (h_ch > lo) & (h_ch < hi)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, MORPH_KERNEL, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, MORPH_KERNEL, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 0.02 * image.shape[0] * image.shape[1]:
        return None
    return cv2.boundingRect(largest)


class Dino:
    """Frozen DINOv2: a global embedding and a grid of patch tokens."""

    def __init__(self):
        import timm

        self.model = timm.create_model(EMBED_MODEL, pretrained=True, num_classes=0).eval()
        cfg = timm.data.resolve_data_config({}, model=self.model)
        self.transform = timm.data.create_transform(**cfg)
        self.mean = np.array(cfg["mean"])
        self.std = np.array(cfg["std"])

    def global_embedding(self, image_bgr: np.ndarray) -> np.ndarray:
        import torch
        from PIL import Image

        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        with torch.no_grad():
            return self.model(self.transform(Image.fromarray(rgb)).unsqueeze(0)).squeeze(0).numpy()

    def patch_tokens(self, image_bgr: np.ndarray) -> np.ndarray:
        """(PATCH_GRID, PATCH_GRID, dim) tokens for the whole photo."""
        import torch

        rgb = cv2.cvtColor(cv2.resize(image_bgr, (PATCH_INPUT, PATCH_INPUT)), cv2.COLOR_BGR2RGB) / 255.0
        t = torch.from_numpy(((rgb - self.mean) / self.std).transpose(2, 0, 1)).float()[None]
        with torch.no_grad():
            tokens = self.model.forward_features(t)[0, self.model.num_prefix_tokens:]
        return tokens.numpy().reshape(PATCH_GRID, PATCH_GRID, -1)


def select_main_arch(prob: np.ndarray) -> Optional[np.ndarray]:
    """From a patch tooth-probability grid, return a boolean mask (at
    MASK_UPSAMPLE x grid resolution) of the main arch, or None."""
    size = prob.shape[0] * MASK_UPSAMPLE
    fine = cv2.resize(prob.astype(np.float32), (size, size), interpolation=cv2.INTER_LINEAR)
    binary = (fine > TOOTH_PROB_THRESHOLD).astype(np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

    pieces = []
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] < 4 * MASK_UPSAMPLE ** 2:
            continue
        ys, xs = np.where(labels == k)
        hull = cv2.convexHull(np.stack([xs, ys], 1).astype(np.int32))
        x, y, w, h = stats[k, :4]
        pieces.append((cv2.contourArea(hull) + len(xs), k, (x, y, x + w, y + h)))
    if not pieces:
        return None

    pieces.sort(reverse=True)
    _, seed, (x0, y0, x1, y1) = pieces[0]
    keep = labels == seed
    pending = pieces[1:]
    merged = True
    while merged:
        merged = False
        for piece in list(pending):
            _, k, (px0, py0, px1, py1) = piece
            overlap = max(0, min(y1, py1) - max(y0, py0)) / max(1, py1 - py0)
            gap = max(0, max(x0, px0) - min(x1, px1))
            if overlap >= 0.6 and gap <= y1 - y0:
                keep |= labels == k
                x0, y0, x1, y1 = min(x0, px0), min(y0, py0), max(x1, px1), max(y1, py1)
                pending.remove(piece)
                merged = True
    return keep


def crop_to_fill(image: np.ndarray, box: tuple, fill: float = ARCH_FILL) -> tuple:
    """Crop around box so it spans `fill` of the output in each dimension.
    Returns (crop, padded) where padded says black border was added."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_w, half_h = (x1 - x0) / fill / 2, (y1 - y0) / fill / 2
    cx0, cy0 = int(round(cx - half_w)), int(round(cy - half_h))
    cx1, cy1 = int(round(cx + half_w)), int(round(cy + half_h))
    h, w = image.shape[:2]
    top, bottom, left, right = max(0, -cy0), max(0, cy1 - h), max(0, -cx0), max(0, cx1 - w)
    padded = cv2.copyMakeBorder(image, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    crop = padded[cy0 + top:cy1 + top, cx0 + left:cx1 + left]
    return crop, bool(top or bottom or left or right)


class OcclusalPreprocessor:
    def __init__(self):
        import joblib

        self.dino = Dino()
        self.view_clf = joblib.load(VIEW_CLASSIFIER_PATH)
        self.tooth_clf = joblib.load(TOOTH_PATCH_CLASSIFIER_PATH)

    def process(self, image_path: str) -> dict:
        """Returns {"view", "p_upper", "crop", "arch_box", "flags"}.
        view/crop are None when no oral region is found."""
        image = cv2.imread(str(image_path))
        if image is None:
            raise FileNotFoundError(image_path)
        result = {"view": None, "p_upper": None, "crop": None, "arch_box": None, "flags": []}

        oral = find_oral_region(image)
        if oral is None:
            result["flags"].append("no_oral_region")
            return result
        x, y, w, h = oral

        embedding = self.dino.global_embedding(image[y:y + h, x:x + w])
        p_upper = float(self.view_clf.predict_proba(embedding[None])[0, 1])
        result["p_upper"] = p_upper
        result["view"] = "upper" if p_upper >= 0.5 else "lower"
        if UNCERTAIN_VIEW_BAND[0] < p_upper < UNCERTAIN_VIEW_BAND[1]:
            result["flags"].append("uncertain_view")

        tokens = self.dino.patch_tokens(image)
        prob = self.tooth_clf.predict_proba(tokens.reshape(-1, tokens.shape[-1]))[:, 1]
        arch = select_main_arch(prob.reshape(PATCH_GRID, PATCH_GRID))
        if arch is None:
            result["flags"].append("arch_not_found")
            box = (x, y, x + w, y + h)
        else:
            ys, xs = np.where(arch)
            sx, sy = image.shape[1] / arch.shape[1], image.shape[0] / arch.shape[0]
            box = (int(xs.min() * sx), int(ys.min() * sy), int((xs.max() + 1) * sx), int((ys.max() + 1) * sy))

        result["arch_box"] = box
        result["crop"], padded = crop_to_fill(image, box)
        if padded:
            result["flags"].append("crop_padded")
        return result
