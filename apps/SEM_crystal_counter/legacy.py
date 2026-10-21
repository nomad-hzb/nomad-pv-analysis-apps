"""The detection pipeline of SEM_Analyzer.ipynb with its default widget values, as a baseline.

Kept only so that evaluate.py can show how the new pipeline compares with what the app did.
"""

from __future__ import annotations

import cv2
import numpy as np
from skimage import segmentation


def segment(gray: np.ndarray) -> np.ndarray:
    """Label image of the 'crystals' the old app reported (defaults: CLAHE 40/25, blur 11, Otsu,
    morph 3x3, extract edges, watershed, border removal, area 100..10000 px)."""
    clahe = cv2.createCLAHE(clipLimit=40, tileGridSize=(25, 25))
    blurred = cv2.GaussianBlur(clahe.apply(gray), (11, 11), 0)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_GRADIENT, kernel)

    dist = cv2.distanceTransform(cleaned, cv2.DIST_L2, 5)
    _, sure_fg = cv2.threshold(dist, dist.max() / np.e, 255, cv2.THRESH_BINARY)
    sure_fg = np.uint8(sure_fg)
    sure_bg = cv2.dilate(cleaned, kernel, iterations=3)
    unknown = cv2.subtract(sure_bg, sure_fg)
    _, markers = cv2.connectedComponents(sure_fg)
    markers = markers + 1
    markers[unknown == 255] = 0
    markers = cv2.watershed(cv2.cvtColor(cleaned, cv2.COLOR_GRAY2BGR), markers)

    border = set(
        np.unique(np.concatenate([markers[0], markers[-1], markers[:, 0], markers[:, -1]]))
    )
    labels = np.where(markers > 1, markers, 0)
    labels[np.isin(labels, list(border))] = 0
    areas = np.bincount(labels.ravel())
    bad = (areas < 100) | (areas > 10000)
    bad[0] = False
    labels[bad[labels]] = 0
    return segmentation.relabel_sequential(labels)[0]
