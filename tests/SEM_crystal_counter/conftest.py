"""Fixtures for SEM_crystal_counter tests. Images are synthetic; the real SEM data never
enters the repo."""

import importlib.util
import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from scipy.spatial import cKDTree
from skimage import segmentation

APP_DIR = Path(__file__).parent.parent.parent / "apps" / "SEM_crystal_counter"

# Load order matters: run_batch imports grain_core, evaluate imports both, by bare name.
for _name in ("grain_core", "run_batch", "evaluate"):
    _spec = importlib.util.spec_from_file_location(_name, APP_DIR / f"{_name}.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _module
    _spec.loader.exec_module(_module)


def tiff_bytes(image: np.ndarray, metadata: bytes = b"") -> bytes:
    """A grayscale TIFF with free text appended, the way the Zeiss tag text sits in the file."""
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="TIFF")
    return buffer.getvalue() + metadata


@pytest.fixture
def make_tiff():
    return tiff_bytes


@pytest.fixture(scope="session")
def voronoi_film():
    """(image, true_labels): 30 grains with dark 3 px grooves, noisy, 5 nm/px."""
    rng = np.random.default_rng(7)
    height, width = 300, 400
    centers = rng.uniform((0, 0), (height, width), size=(30, 2))
    yy, xx = np.mgrid[:height, :width]
    _, nearest = cKDTree(centers).query(np.column_stack([yy.ravel(), xx.ravel()]))
    labels = nearest.reshape(height, width) + 1
    shades = rng.uniform(120, 160, size=labels.max() + 1)
    image = shades[labels]
    grooves = segmentation.find_boundaries(labels, mode="thick")
    image[grooves] = 70
    image = image + rng.normal(0, 6, size=image.shape)
    return np.clip(image, 0, 255).astype(np.uint8), labels
