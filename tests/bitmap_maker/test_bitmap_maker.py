import gui_components as gui
import numpy as np
import pytest
import utils
from PIL import Image
from utils import create_bitmap, mm_to_pixels

MARGINS = {"top": 2, "bottom": 2, "left": 2, "right": 2}


def test_mm_to_pixels_converts_at_given_dpi():
    assert mm_to_pixels(25.4, 300) == 300
    assert mm_to_pixels(0, 300) == 0


def test_create_bitmap_returns_expected_size_and_mode():
    img = create_bitmap(20, 10, 100, MARGINS, black_percentage=50, pattern_type="random")

    expected_width = mm_to_pixels(20, 100)
    expected_height = mm_to_pixels(10, 100)

    assert isinstance(img, Image.Image)
    assert img.mode == "L"
    assert img.size == (expected_width, expected_height)


def test_create_bitmap_ordered_pattern_is_deterministic():
    img1 = create_bitmap(20, 10, 100, MARGINS, black_percentage=30, pattern_type="ordered")
    img2 = create_bitmap(20, 10, 100, MARGINS, black_percentage=30, pattern_type="ordered")

    assert np.array_equal(np.asarray(img1), np.asarray(img2))


def test_create_bitmap_zero_percent_black_is_all_white():
    img = create_bitmap(10, 10, 50, MARGINS, black_percentage=0, pattern_type="ordered")

    assert set(np.unique(np.asarray(img))) == {255}


def test_create_bitmap_unknown_pattern_falls_back_to_random_without_error():
    img = create_bitmap(10, 10, 50, MARGINS, black_percentage=50, pattern_type="not_a_real_pattern")

    assert isinstance(img, Image.Image)


# ---------------------------------------------------------------------------
# 5.6: every pattern gives the black share that was asked for
# ---------------------------------------------------------------------------

_FIELD = 200
_NO_MARGINS = {"top": 0, "bottom": 0, "left": 0, "right": 0}

# Tolerance in percentage points. The tiled threshold-matrix patterns can only produce
# multiples of 1/n (Bayer 8x8 = 1.56%, publication base 4 = 6.25%), random is statistical.
_PATTERNS = {
    "random": {},
    "ordered": {},
    "blue_noise": {},
    "complementary": {"pattern_id": 0},
    "poisson": {},
    "floyd_steinberg": {},
    "void_cluster": {},
    "jittered": {},
    "multi_level": {},
    "publication": {"base_size": 3},
}
_TOLERANCE = {"publication": 6.0, "ordered": 2.0, "multi_level": 2.5, "complementary": 2.5}


def _coverage(pattern, black_percentage, **kwargs):
    # 200 px at 25.4 dpi is exactly 200 mm / 25.4 * 25.4 = 200 pixels
    image = utils.create_bitmap(
        _FIELD, _FIELD, 25.4, _NO_MARGINS, black_percentage, pattern, **kwargs
    )
    return utils.black_coverage(image, _NO_MARGINS, 25.4)


@pytest.mark.parametrize("pattern", sorted(_PATTERNS))
@pytest.mark.parametrize("black_percentage", [5, 20, 50, 80])
def test_every_pattern_gives_the_requested_black_share(pattern, black_percentage):
    """Blue noise gave 86% for 20%, Jittered 100% from 30%, Poisson 15.8% from 20%."""
    achieved = _coverage(pattern, black_percentage, **_PATTERNS[pattern])
    assert abs(achieved - black_percentage) <= _TOLERANCE.get(pattern, 1.5), (pattern, achieved)


@pytest.mark.parametrize("pattern", sorted(_PATTERNS))
@pytest.mark.parametrize("black_percentage", [0, 100])
def test_zero_and_full_coverage_do_not_raise(pattern, black_percentage):
    """Jittered Grid raised ZeroDivisionError at 0%."""
    achieved = _coverage(pattern, black_percentage, **_PATTERNS[pattern])
    assert achieved == pytest.approx(black_percentage, abs=0.5)


@pytest.mark.parametrize("pattern", ["blue_noise", "poisson", "jittered"])
def test_the_exact_share_patterns_hit_it_to_the_pixel(pattern):
    shape = (123, 77)
    for share in (3, 17.5, 33, 66.6):
        fn = {
            "blue_noise": utils.blue_noise_pattern,
            "poisson": utils.poisson_disk_sampling,
            "jittered": utils.jittered_grid,
        }[pattern]
        mask = fn(shape, share, seed=1)
        assert int(mask.sum()) == round(123 * 77 * share / 100), (pattern, share)


def test_seeded_patterns_are_reproducible_and_do_not_touch_the_global_rng():
    np.random.seed(1234)
    before = np.random.random()
    np.random.seed(1234)
    a = utils.random_dithering((50, 50), 30, seed=7)
    b = utils.random_dithering((50, 50), 30, seed=7)
    assert np.array_equal(a, b)
    assert np.random.random() == before  # the global state was not reseeded or consumed


def test_poisson_points_keep_their_minimum_distance_at_low_density():
    mask = utils.poisson_disk_sampling((120, 120), 2, seed=3)
    ys, xs = np.nonzero(mask)
    pts = np.stack([xs, ys], axis=1).astype(float)
    spread = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1))
    np.fill_diagonal(spread, np.inf)
    assert spread.min() >= 1.0  # no two points on the same pixel, and well separated


def test_publication_base_5_is_refused_instead_of_exhausting_memory():
    with pytest.raises(ValueError, match="not supported"):
        utils.publication_pattern((20, 20), 50, base_size=5)


def test_base_5_and_jpeg_are_no_longer_offered():
    pattern_box, pattern_type, _ = gui.create_pattern_controls(default_percentage=50)
    values = [value for _, value in pattern_type.options]
    assert "publication_5" not in values
    assert {"publication_3", "publication_4"} <= set(values)
    _, format_selector, _ = gui.create_file_format_selector()
    assert "JPEG" not in format_selector.options


@pytest.mark.parametrize("format_name", ["PNG", "BMP", "TIFF"])
def test_saved_output_is_one_bit_and_exactly_the_mask(format_name):
    import io

    from PIL import Image

    image = utils.create_bitmap(20, 20, 25.4, _NO_MARGINS, 40, "random")
    buffer = io.BytesIO()
    utils.to_binary_image(image).save(buffer, format=format_name)
    reloaded = Image.open(io.BytesIO(buffer.getvalue()))
    assert reloaded.mode == "1"
    assert np.array_equal(np.asarray(reloaded.convert("L")), np.asarray(image))


def test_app_shows_errors_and_the_achieved_coverage_in_the_output_area(monkeypatch, capsys):
    """Status and errors were only logged, which under Voila is nowhere the user looks. (Outside
    a kernel an Output widget forwards print() to stdout, so that is what is checked here.)"""
    import app as bitmap_app
    import ipywidgets as widgets

    root = bitmap_app.setup_app()

    def find(widget, predicate):
        if predicate(widget):
            return widget
        for child in getattr(widget, "children", ()):
            hit = find(child, predicate)
            if hit is not None:
                return hit
        return None

    generate = find(root, lambda w: isinstance(w, widgets.Button) and "Generate" in w.description)
    download = find(root, lambda w: isinstance(w, widgets.Button) and "Download" in w.description)
    download.click()  # nothing generated yet
    assert "No image to download yet" in capsys.readouterr().out

    generate.click()
    out = capsys.readouterr().out
    assert "Black:" in out and "requested" in out

    monkeypatch.setattr(utils, "create_bitmap", lambda *a, **k: 1 / 0)
    generate.click()
    assert "Could not generate the image" in capsys.readouterr().out


def test_controls_keep_their_width_next_to_a_wide_preview():
    """In a flex row a wide preview squeezed the controls to ~20 px after the first Generate."""
    import app as bitmap_app
    import ipywidgets as widgets

    root = bitmap_app.setup_app()
    row = next(c for c in root.children if isinstance(c, widgets.HBox))
    controls, preview = row.children
    assert controls.layout.flex == "0 0 auto" and controls.layout.min_width == "340px"
    assert preview.layout.min_width == "0" and preview.layout.flex == "1 1 0"
