import base64
import io
import logging
from itertools import combinations

import numpy as np
from PIL import Image
from scipy.special import comb

try:
    from scipy import ndimage

    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

logger = logging.getLogger(__name__)


# Combinatorial inkjet printing algorithm from publication
# https://pubs.rsc.org/en/content/articlehtml/2018/a0/d1ta08841f
def combs(a, r):
    """
    Return successive r-length combinations of elements in the array a.
    Faster than array(list(combinations(a, r)))
    """
    a = np.asarray(a)
    dt = np.dtype([("", a.dtype)] * r)
    b = np.fromiter(combinations(a, r), dt)
    return b.view(a.dtype).reshape(-1, r)


def droplet_position_optimization(n, k):
    """
    Function for generating a base matrix with side n and filling k.
    Optimizes droplet positions to maximize minimum distance between droplets.
    """
    x, y = np.indices((n, n))
    pos = combs(np.arange(n**2), k)
    x_base_pos = x.flatten()[pos]
    y_base_pos = y.flatten()[pos]
    points = comb(n**2, k, exact=True)
    x_pos = np.zeros((points, k * 9))
    y_pos = np.zeros((points, k * 9))
    count = 0
    for y_rep in [-1, 0, 1]:
        for x_rep in [-1, 0, 1]:
            roi = slice(k * count, k * (count + 1))
            x_pos[:, roi] = x_base_pos + (x_rep * n)
            y_pos[:, roi] = y_base_pos + (y_rep * n)
            count += 1
    x_pos = np.tile(x_pos, (k, 1, 1))
    y_pos = np.tile(y_pos, (k, 1, 1))
    distances = np.sqrt(
        np.power(x_pos - np.broadcast_to(x_base_pos, (k * 9, points, k)).T, 2)
        + np.power(y_pos - np.broadcast_to(y_base_pos, (k * 9, points, k)).T, 2)
    )
    distances[np.where(distances < 1)] = (2 * n) ** 2
    min_dist = np.min(distances, axis=2)
    worst_point = np.argmin(min_dist, axis=0)
    if np.max(min_dist[worst_point, np.arange(points)]) > 1:
        best_option_index = np.argmax(min_dist[worst_point, np.arange(points)])
    else:
        worst_min_dist = np.min(min_dist, axis=0)
        min_dist_copy = min_dist
        min_dist_copy[np.where(min_dist != worst_min_dist)] = 0
        best_option_index = np.argmin(np.sum(min_dist_copy, axis=0))
    return x_base_pos[best_option_index], y_base_pos[best_option_index]


def generate_bases(size):
    """
    Function for generating all base matrices for a certain size.
    Creates optimized patterns for combinatorial printing.
    """
    high = int(np.ceil((size**2 + 1) / 2)) - 1
    bases = [np.zeros((size, size), dtype=bool)]
    for fill in range(high):
        best_x, best_y = droplet_position_optimization(size, fill + 1)
        base = np.zeros((size, size), dtype=bool)
        for idx in range(len(best_x)):
            base[best_y[idx], best_x[idx]] = True
        bases.append(base)
    remaining = size**2 + 1 - len(bases)
    for idx in range(remaining):
        bases.append(np.invert(bases[remaining - idx - 1]))
    return bases


SUPPORTED_BASE_SIZES = (3, 4)

# Cache for publication bases to avoid regeneration
_publication_bases_cache = {}


def publication_pattern(shape, black_percentage, base_size=4):
    """
    Combinatorial inkjet printing pattern from publication.
    Uses optimized base matrices that maximize minimum distance between droplets.

    base_size: 3 or 4. Base 5 is refused: building its bases enumerates every placement of
    up to 12 droplets in 25 cells (tens to hundreds of GB of RAM), which kills the kernel.
    """
    if base_size not in SUPPORTED_BASE_SIZES:
        raise ValueError(
            f"Publication base {base_size} is not supported (use {SUPPORTED_BASE_SIZES}): "
            "larger bases need more memory than a kernel has."
        )
    # Generate or retrieve cached bases
    if base_size not in _publication_bases_cache:
        _publication_bases_cache[base_size] = generate_bases(base_size)

    bases = _publication_bases_cache[base_size]

    # Select appropriate base based on black percentage
    n_bases = len(bases)
    base_index = int(round(black_percentage / 100.0 * (n_bases - 1)))
    base_index = np.clip(base_index, 0, n_bases - 1)

    selected_base = bases[base_index]

    # Tile the base across the image
    rows, cols = shape
    n_tiles_y = rows // base_size + 1
    n_tiles_x = cols // base_size + 1

    tiled = np.tile(selected_base, (n_tiles_y, n_tiles_x))
    return tiled[:rows, :cols]


def mm_to_pixels(mm, dpi):
    """Convert millimeters to pixels at given DPI"""
    inches = mm / 25.4
    return int(inches * dpi)


def create_bayer_matrix(n):
    """Create Bayer matrix of size n x n (n must be power of 2)"""
    if n == 1:
        return np.array([[0]])
    elif n == 2:
        return np.array([[0, 2], [3, 1]])
    else:
        smaller = create_bayer_matrix(n // 2)
        # Build the larger matrix without normalizing yet
        return np.block([[4 * smaller + 0, 4 * smaller + 2], [4 * smaller + 3, 4 * smaller + 1]])


def random_dithering(shape, black_percentage, seed=None):
    """Random distribution of black pixels"""
    rng = np.random.default_rng(seed)
    return _lowest_fraction_mask(rng.random(shape), black_percentage)


def ordered_dithering(shape, black_percentage):
    """Bayer ordered dithering"""
    bayer_size = 8
    bayer = create_bayer_matrix(bayer_size)
    # Normalize to 0-1 range
    bayer = bayer / float(bayer_size * bayer_size)

    # Tile the Bayer matrix to cover the image
    rows, cols = shape
    tiled = np.tile(bayer, (rows // bayer_size + 1, cols // bayer_size + 1))
    tiled = tiled[:rows, :cols]

    threshold = black_percentage / 100.0
    return tiled < threshold


# Above this many points the pure-Python Poisson loop takes minutes (100 mm x 100 mm at 350 dpi
# is about 1.9 million pixels), so such requests use the blue-noise map instead.
MAX_POISSON_POINTS = 20_000


def _lowest_fraction_mask(values, black_percentage):
    """Boolean mask with exactly round(black_percentage % of the pixels) True, at the lowest
    `values`. Thresholding on a rank instead of on a fixed number gives the requested
    coverage whatever the distribution of the values is."""
    values = np.asarray(values)
    total = values.size
    n_black = int(round(total * min(max(black_percentage, 0.0), 100.0) / 100.0))
    mask = np.zeros(total, dtype=bool)
    if n_black >= total:
        mask[:] = True
    elif n_black > 0:
        mask[np.argpartition(values.ravel(), n_black - 1)[:n_black]] = True
    return mask.reshape(values.shape)


def _blue_noise_values(shape, rng):
    """High-pass filtered noise in 0..1: neighbouring pixels avoid being both low."""
    noise = rng.random(shape)
    if not SCIPY_AVAILABLE:
        return noise
    return np.clip(noise - ndimage.gaussian_filter(noise, sigma=1.0) + 0.5, 0, 1)


def poisson_disk_sampling(shape, black_percentage, min_distance=None, seed=None):
    """
    Poisson disk sampling - guarantees minimum distance between points
    Creates very uniform spatial distribution.

    The minimum distance follows the requested density (no 2 px floor: that floor capped every
    request above 16% at 15.8%). The number of black pixels is always exactly the requested
    share: points the sampler cannot place (a dense request, or two points landing on one
    pixel) are added at the lowest blue-noise values, and a request with more than
    MAX_POISSON_POINTS points uses the blue-noise map alone.
    """
    rng = np.random.default_rng(seed)
    rows, cols = shape
    total_pixels = rows * cols
    n_black = int(round(total_pixels * min(max(black_percentage, 0.0), 100.0) / 100.0))
    pattern = np.zeros(shape, dtype=bool)
    if n_black == 0 or total_pixels == 0:
        return pattern
    if n_black >= total_pixels:
        return ~pattern

    fill_values = _blue_noise_values(shape, rng)
    if n_black <= MAX_POISSON_POINTS:
        if min_distance is None:
            min_distance = 0.7 * np.sqrt(total_pixels / n_black)
        for x, y in _bridson_points(rows, cols, min_distance, n_black, rng):
            pattern[min(int(y), rows - 1), min(int(x), cols - 1)] = True
    missing = n_black - int(pattern.sum())
    if missing > 0:
        candidates = np.where(pattern, np.inf, fill_values)
        order = np.argpartition(candidates.ravel(), missing - 1)[:missing]
        pattern.ravel()[order] = True
    return pattern


def _bridson_points(rows, cols, min_distance, max_points, rng):
    """Poisson-disk points (x, y) in a cols x rows field, at most max_points of them."""
    cell_size = min_distance / np.sqrt(2)
    grid_w = int(np.ceil(cols / cell_size))
    grid_h = int(np.ceil(rows / cell_size))
    grid = [[None] * grid_w for _ in range(grid_h)]

    def cell(point):
        return int(point[0] / cell_size), int(point[1] / cell_size)

    def is_valid(point):
        gx, gy = cell(point)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < grid_w and 0 <= ny < grid_h and grid[ny][nx] is not None:
                    other = grid[ny][nx]
                    if (point[0] - other[0]) ** 2 + (point[1] - other[1]) ** 2 < min_distance**2:
                        return False
        return True

    first = (rng.uniform(0, cols), rng.uniform(0, rows))
    points = [first]
    active = [first]
    gx, gy = cell(first)
    grid[gy][gx] = first
    attempts = 30
    while active and len(points) < max_points:
        idx = int(rng.integers(len(active)))
        point = active[idx]
        for _ in range(attempts):
            angle = rng.uniform(0, 2 * np.pi)
            radius = rng.uniform(min_distance, 2 * min_distance)
            candidate = (point[0] + radius * np.cos(angle), point[1] + radius * np.sin(angle))
            if 0 <= candidate[0] < cols and 0 <= candidate[1] < rows and is_valid(candidate):
                points.append(candidate)
                active.append(candidate)
                gx, gy = cell(candidate)
                grid[gy][gx] = candidate
                break
        else:
            active.pop(idx)
    return points


def floyd_steinberg_dither(shape, black_percentage):
    """
    Floyd-Steinberg error diffusion dithering
    Classic algorithm for uniform distribution
    """
    rows, cols = shape

    # Create initial grayscale image with target percentage
    threshold_value = (100 - black_percentage) / 100.0
    image = np.full(shape, threshold_value, dtype=float)

    # Apply Floyd-Steinberg dithering
    for y in range(rows):
        for x in range(cols):
            old_pixel = image[y, x]
            new_pixel = 1.0 if old_pixel > 0.5 else 0.0
            image[y, x] = new_pixel
            error = old_pixel - new_pixel

            # Distribute error to neighbors
            if x + 1 < cols:
                image[y, x + 1] += error * 7 / 16
            if y + 1 < rows:
                if x > 0:
                    image[y + 1, x - 1] += error * 3 / 16
                image[y + 1, x] += error * 5 / 16
                if x + 1 < cols:
                    image[y + 1, x + 1] += error * 1 / 16

    return image < 0.5


def void_and_cluster(shape, black_percentage):
    """
    Void-and-cluster algorithm for homogeneous distribution
    Iteratively fills voids and removes clusters
    """
    rows, cols = shape
    total_pixels = rows * cols
    n_black = int(total_pixels * black_percentage / 100.0)  # noqa: F841

    # Start with random distribution
    pattern = np.random.random(shape) < (black_percentage / 100.0)

    # Create Gaussian filter for detecting voids/clusters
    def gaussian_weights(size=5, sigma=1.5):
        ax = np.arange(-size // 2 + 1.0, size // 2 + 1.0)
        xx, yy = np.meshgrid(ax, ax)
        kernel = np.exp(-(xx**2 + yy**2) / (2.0 * sigma**2))
        return kernel / kernel.sum()

    kernel = gaussian_weights()

    # Refine pattern
    iterations = min(20, max(5, int(np.sqrt(total_pixels) / 10)))
    for _ in range(iterations):
        if not SCIPY_AVAILABLE:
            break

        density = ndimage.convolve(pattern.astype(float), kernel, mode="constant")

        # Find largest void (lowest density in empty area)
        void_candidates = ~pattern
        if void_candidates.any():
            void_densities = np.where(void_candidates, density, np.inf)
            void_pos = np.unravel_index(np.argmin(void_densities), shape)

            # Find largest cluster (highest density in filled area)
            cluster_candidates = pattern
            if cluster_candidates.any():
                cluster_densities = np.where(cluster_candidates, density, -np.inf)
                cluster_pos = np.unravel_index(np.argmax(cluster_densities), shape)

                # Swap
                pattern[void_pos] = True
                pattern[cluster_pos] = False

    return pattern


def jittered_grid(shape, black_percentage, jitter_amount=0.4, seed=None):
    """
    Jittered grid - regular grid with random offsets
    Balances structure with randomness.

    Exactly the requested share of pixels is black. The field is divided into about
    n_black cells (float cell sizes, so any density works; the old integer spacing was 1 above
    25% and turned every pixel black), one point is dropped at a random offset inside each
    cell, and points that collide on a pixel are replaced by random free pixels.
    """
    rng = np.random.default_rng(seed)
    rows, cols = shape
    total_pixels = rows * cols
    n_black = int(round(total_pixels * min(max(black_percentage, 0.0), 100.0) / 100.0))
    pattern = np.zeros(shape, dtype=bool)
    if n_black == 0 or total_pixels == 0:
        return pattern
    if n_black >= total_pixels:
        return ~pattern

    cells_x = max(1, int(np.ceil(np.sqrt(n_black * cols / rows))))
    cells_y = max(1, int(np.ceil(n_black / cells_x)))
    cells_x = min(cells_x, cols)
    cells_y = min(cells_y, rows)
    n_cells = cells_x * cells_y
    chosen = rng.permutation(n_cells)[: min(n_black, n_cells)]
    cell_w, cell_h = cols / cells_x, rows / cells_y
    for index in chosen:
        cy, cx = divmod(int(index), cells_x)
        # offset from the cell centre, up to jitter_amount of the cell size either way
        x = (cx + 0.5 + rng.uniform(-jitter_amount, jitter_amount)) * cell_w
        y = (cy + 0.5 + rng.uniform(-jitter_amount, jitter_amount)) * cell_h
        pattern[min(int(y), rows - 1), min(int(x), cols - 1)] = True
    short = n_black - int(pattern.sum())
    if short > 0:
        free = np.flatnonzero(~pattern.ravel())
        pattern.ravel()[rng.choice(free, size=short, replace=False)] = True
    return pattern


def multi_level_halftone(shape, black_percentage):
    """
    Multi-level halftone using different Bayer matrix sizes
    Combines fine and coarse patterns for better uniformity
    """
    rows, cols = shape

    # Use multiple Bayer matrices at different scales
    bayer_4 = create_bayer_matrix(4) / 16.0  # 4*4 = 16
    bayer_8 = create_bayer_matrix(8) / 64.0  # 8*8 = 64

    # Tile both matrices
    tiled_4 = np.tile(bayer_4, (rows // 4 + 1, cols // 4 + 1))[:rows, :cols]
    tiled_8 = np.tile(bayer_8, (rows // 8 + 1, cols // 8 + 1))[:rows, :cols]

    # Combine with weights
    combined = 0.6 * tiled_8 + 0.4 * tiled_4

    threshold = black_percentage / 100.0
    return combined < threshold


def complementary_pattern(shape, black_percentage, pattern_id=0):
    """
    Create complementary patterns that combine when rotated 180° or mirrored
    pattern_id: 0 or 1 for complementary pair
    """
    rows, cols = shape

    # Create a structured pattern using Bayer-like approach
    bayer = create_bayer_matrix(8)
    # Normalize to 0-1 range
    bayer = bayer / 64.0  # 8*8 = 64
    tiled = np.tile(bayer, (rows // 8 + 1, cols // 8 + 1))[:rows, :cols]

    # For complementary patterns, split the threshold space
    threshold = black_percentage / 100.0

    if pattern_id == 0:
        # First pattern: use lower threshold values
        return tiled < threshold
    else:
        # Second pattern: use complementary threshold values
        # This ensures that when combined, they cover the full range
        return tiled >= (1 - threshold)


def blue_noise_pattern(shape, black_percentage, seed=None):
    """Blue noise pattern (high frequency noise) with exactly the requested black share.

    The old version thresholded at 1 - share, which marked the opposite share black (20%
    requested gave 86%), and the filtering makes the values non-uniform, so a fixed threshold
    could not be exact anyway: the lowest `share` of the values are black instead."""
    rng = np.random.default_rng(seed)
    return _lowest_fraction_mask(_blue_noise_values(shape, rng), black_percentage)


def create_bitmap(
    width_mm, height_mm, dpi, margins, black_percentage, pattern_type="random", **kwargs
):
    """
    Create bitmap image with specified parameters

    margins: dict with 'top', 'bottom', 'left', 'right' in mm
    pattern_type: 'random', 'ordered', 'blue_noise', 'complementary',
                  'poisson', 'floyd_steinberg', 'void_cluster', 'jittered', 'multi_level', 'publication'  # noqa: E501
    """
    # Convert dimensions to pixels
    width_px = mm_to_pixels(width_mm, dpi)
    height_px = mm_to_pixels(height_mm, dpi)

    margin_top_px = mm_to_pixels(margins["top"], dpi)
    margin_bottom_px = mm_to_pixels(margins["bottom"], dpi)
    margin_left_px = mm_to_pixels(margins["left"], dpi)
    margin_right_px = mm_to_pixels(margins["right"], dpi)

    # Create white image
    img_array = np.ones((height_px, width_px), dtype=bool)

    # Calculate active area (outside margins)
    active_top = margin_top_px
    active_bottom = height_px - margin_bottom_px
    active_left = margin_left_px
    active_right = width_px - margin_right_px

    if active_bottom > active_top and active_right > active_left:
        active_shape = (active_bottom - active_top, active_right - active_left)

        # Generate pattern based on type
        if pattern_type == "random":
            pattern = random_dithering(active_shape, black_percentage)
        elif pattern_type == "ordered":
            pattern = ordered_dithering(active_shape, black_percentage)
        elif pattern_type == "blue_noise":
            pattern = blue_noise_pattern(active_shape, black_percentage)
        elif pattern_type == "complementary":
            pattern_id = kwargs.get("pattern_id", 0)
            pattern = complementary_pattern(active_shape, black_percentage, pattern_id)
        elif pattern_type == "poisson":
            pattern = poisson_disk_sampling(active_shape, black_percentage)
        elif pattern_type == "floyd_steinberg":
            pattern = floyd_steinberg_dither(active_shape, black_percentage)
        elif pattern_type == "void_cluster":
            pattern = void_and_cluster(active_shape, black_percentage)
        elif pattern_type == "jittered":
            pattern = jittered_grid(active_shape, black_percentage)
        elif pattern_type == "multi_level":
            pattern = multi_level_halftone(active_shape, black_percentage)
        elif pattern_type == "publication":
            base_size = kwargs.get("base_size", 4)
            pattern = publication_pattern(active_shape, black_percentage, base_size)
        else:
            pattern = random_dithering(active_shape, black_percentage)

        # Invert: True = white, False = black
        img_array[active_top:active_bottom, active_left:active_right] = ~pattern

    # Convert to PIL Image (True=255=white, False=0=black)
    img = Image.fromarray(img_array.astype(np.uint8) * 255, mode="L")

    return img


def to_binary_image(img):
    """The 1-bit version of a black/white image, so what is saved or shown is exactly the
    mask. (A lossy format such as JPEG puts grey ringing around every dot, and a printer RIP
    that thresholds it then changes the drop count.)"""
    dither = getattr(Image, "Dither", Image).NONE
    return img.convert("1", dither=dither)


def black_coverage(img, margins, dpi):
    """Percentage of the active area (inside the margins) that is black, as generated."""
    array = np.asarray(img)
    top = mm_to_pixels(margins["top"], dpi)
    bottom = array.shape[0] - mm_to_pixels(margins["bottom"], dpi)
    left = mm_to_pixels(margins["left"], dpi)
    right = array.shape[1] - mm_to_pixels(margins["right"], dpi)
    if bottom <= top or right <= left:
        return 0.0
    return float(100.0 * (array[top:bottom, left:right] == 0).mean())


def image_to_base64(img, format="PNG"):
    """Convert PIL Image to base64 string for display"""
    buffer = io.BytesIO()
    to_binary_image(img).save(buffer, format=format)
    buffer.seek(0)
    img_str = base64.b64encode(buffer.read()).decode()
    return f"data:image/{format.lower()};base64,{img_str}"


def invert_image(img, width_mm, height_mm, dpi, margins):
    """
    Invert a bitmap image (black <-> white) but keep margins white

    margins: dict with 'top', 'bottom', 'left', 'right' in mm
    """
    img_array = np.array(img)
    inverted_array = img_array.copy()

    # Calculate margin pixels
    margin_top_px = mm_to_pixels(margins["top"], dpi)
    margin_bottom_px = mm_to_pixels(margins["bottom"], dpi)
    margin_left_px = mm_to_pixels(margins["left"], dpi)
    margin_right_px = mm_to_pixels(margins["right"], dpi)

    height_px, width_px = img_array.shape

    # Calculate active area
    active_top = margin_top_px
    active_bottom = height_px - margin_bottom_px
    active_left = margin_left_px
    active_right = width_px - margin_right_px

    # Invert only the active area
    if active_bottom > active_top and active_right > active_left:
        inverted_array[active_top:active_bottom, active_left:active_right] = (
            255 - img_array[active_top:active_bottom, active_left:active_right]
        )

    return Image.fromarray(inverted_array.astype(np.uint8), mode="L")
