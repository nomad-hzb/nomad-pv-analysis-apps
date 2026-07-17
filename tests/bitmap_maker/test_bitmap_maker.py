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

    assert list(img1.getdata()) == list(img2.getdata())


def test_create_bitmap_zero_percent_black_is_all_white():
    img = create_bitmap(10, 10, 50, MARGINS, black_percentage=0, pattern_type="ordered")

    assert set(img.getdata()) == {255}


def test_create_bitmap_unknown_pattern_falls_back_to_random_without_error():
    img = create_bitmap(10, 10, 50, MARGINS, black_percentage=50, pattern_type="not_a_real_pattern")

    assert isinstance(img, Image.Image)
