"""Regenerate the synthetic demo SEM images (run from this folder).

Real SEM images stay out of the repo. These imitate a Zeiss SmartSEM TIFF closely enough
for the app: grains bounded by dark grooves, noise, an info banner below a black frame line,
and an "Image Pixel Size" metadata string. DEMO_B has weak stripes inside its grains. Real
terraces are not reproduced well enough for the striped preset (stronger synthetic stripes
merge everything into one grain), so the auto choice treats DEMO_B as smooth; the demo shows
the app, not the striped-film accuracy.
"""

import io
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree
from skimage import segmentation

HERE = Path(__file__).parent


def film(seed: int, n_grains: int, striped: bool, size=(432, 640)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    height, width = size
    centres = rng.uniform((0, 0), (height, width), size=(n_grains, 2))
    yy, xx = np.mgrid[:height, :width]
    _, nearest = cKDTree(centres).query(np.column_stack([yy.ravel(), xx.ravel()]))
    labels = nearest.reshape(height, width)
    image = rng.uniform(115, 160, size=n_grains)[labels]
    if striped:
        angle = rng.uniform(0, np.pi, size=n_grains)[labels]
        phase = yy * np.cos(angle) + xx * np.sin(angle)
        image += 16 * np.sin(phase / 2.2)
    grooves = segmentation.find_boundaries(labels, mode="thick")
    image[grooves] = 65
    rims = segmentation.find_boundaries(labels, mode="outer") & ~grooves
    image[np.roll(rims, 2, axis=1)] += 35  # bright edge rim beside each groove
    image += rng.normal(0, 7, size=image.shape)
    return np.clip(image, 0, 255).astype(np.uint8)


def with_banner(image: np.ndarray, banner_rows: int = 48) -> np.ndarray:
    banner = np.full((banner_rows, image.shape[1]), 255, dtype=np.uint8)
    banner[:2] = 0  # black frame line that load_sem_tiff detects
    return np.vstack([image, banner])


def write_tiff(path: Path, image: np.ndarray, pixel_size_nm: float) -> None:
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="TIFF", compression="tiff_lzw")
    metadata = f"\r\nImage Pixel Size = {pixel_size_nm} nm\r\n".encode("latin-1")
    path.write_bytes(buffer.getvalue() + metadata)


if __name__ == "__main__":
    specs = [
        ("DEMO_A_01.tif", 1, 30, False, 3.722),
        ("DEMO_A_02.tif", 2, 30, False, 3.722),
        ("DEMO_B_01.tif", 3, 24, True, 5.582),
    ]
    for name, seed, n, striped, px in specs:
        write_tiff(HERE / name, with_banner(film(seed, n, striped)), px)
        print(name, (HERE / name).stat().st_size, "bytes")
