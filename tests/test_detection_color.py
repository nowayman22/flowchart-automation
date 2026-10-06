"""Tests for colour detection, using synthetic images instead of fixtures.

These functions are pure, so a numpy array is all the "screen" they need.
"""

from __future__ import annotations

import numpy as np
import pytest

from flowchart_automation.detection.color import count_color, find_color_hsv, find_color_rgb

RED_BGR = (0, 0, 255)
GREEN_BGR = (0, 255, 0)


def make_screen(width: int = 100, height: int = 100, colour: tuple[int, int, int] = (0, 0, 0)):
    screen = np.zeros((height, width, 3), dtype=np.uint8)
    screen[:, :] = colour
    return screen


def paint(screen, x1, y1, x2, y2, colour):
    screen[y1:y2, x1:x2] = colour
    return screen


def test_find_color_rgb_locates_a_blob() -> None:
    screen = paint(make_screen(), 10, 20, 30, 40, RED_BGR)
    pos, area = find_color_rgb(screen, (0, 0), (255, 0, 0), tolerance=0, min_pixel_area=10)
    # A 20x20 block spans [10, 29] x [20, 39]; the centroid is truncated to int.
    assert pos == (19, 29)
    assert area == pytest.approx(361.0)  # cv2.contourArea of a 20x20 filled rect


def test_find_color_rgb_applies_region_offset() -> None:
    """Detection runs on a cropped region; the result is in screen space."""
    screen = paint(make_screen(), 10, 20, 30, 40, RED_BGR)
    pos, _ = find_color_rgb(screen, (1000, 500), (255, 0, 0), tolerance=0, min_pixel_area=10)
    assert pos == (1019, 529)


def test_find_color_rgb_returns_none_when_absent() -> None:
    screen = make_screen(colour=GREEN_BGR)
    pos, area = find_color_rgb(screen, (0, 0), (255, 0, 0), tolerance=0, min_pixel_area=10)
    assert pos is None
    assert area == 0.0


def test_min_pixel_area_filters_small_blobs() -> None:
    screen = paint(make_screen(), 10, 10, 12, 12, RED_BGR)  # 2x2, contourArea 1.0
    pos, _ = find_color_rgb(screen, (0, 0), (255, 0, 0), tolerance=0, min_pixel_area=10)
    assert pos is None

    # The threshold is exclusive: area must exceed min_pixel_area.
    assert find_color_rgb(screen, (0, 0), (255, 0, 0), tolerance=0, min_pixel_area=1)[0] is None
    assert find_color_rgb(screen, (0, 0), (255, 0, 0), tolerance=0, min_pixel_area=0)[0] is not None


def test_largest_blob_wins() -> None:
    screen = paint(make_screen(), 5, 5, 10, 10, RED_BGR)  # 5x5
    paint(screen, 50, 50, 70, 70, RED_BGR)  # 20x20, larger
    pos, area = find_color_rgb(screen, (0, 0), (255, 0, 0), tolerance=0, min_pixel_area=1)
    assert pos == (59, 59)
    assert area == pytest.approx(361.0)


def test_tolerance_widens_the_match() -> None:
    screen = paint(make_screen(), 10, 10, 30, 30, (10, 0, 245))  # near-red
    assert find_color_rgb(screen, (0, 0), (255, 0, 0), 0, 10)[0] is None
    assert find_color_rgb(screen, (0, 0), (255, 0, 0), 20, 10)[0] is not None


def test_find_color_hsv_locates_a_blob() -> None:
    screen = paint(make_screen(), 10, 20, 30, 40, RED_BGR)
    pos, area = find_color_hsv(screen, (0, 0), (255, 0, 0), tolerance=2, min_pixel_area=10)
    assert pos == (19, 29)
    assert area == pytest.approx(361.0)


def test_find_color_hsv_returns_none_when_absent() -> None:
    screen = make_screen(colour=GREEN_BGR)
    pos, _ = find_color_hsv(screen, (0, 0), (255, 0, 0), tolerance=2, min_pixel_area=10)
    assert pos is None


def test_count_color_counts_separate_blobs() -> None:
    screen = paint(make_screen(), 5, 5, 15, 15, RED_BGR)
    paint(screen, 40, 40, 50, 50, RED_BGR)
    paint(screen, 70, 70, 80, 80, RED_BGR)
    assert count_color(screen, (255, 0, 0), tolerance=0, color_space="RGB", min_pixel_area=10) == 3


def test_count_color_is_zero_when_nothing_matches() -> None:
    assert count_color(make_screen(colour=GREEN_BGR), (255, 0, 0), 0, "RGB", 10) == 0


def test_count_color_ignores_blobs_below_threshold() -> None:
    screen = paint(make_screen(), 5, 5, 15, 15, RED_BGR)  # 10x10 = 100
    paint(screen, 40, 40, 42, 42, RED_BGR)  # 2x2 = 4
    assert count_color(screen, (255, 0, 0), 0, "RGB", min_pixel_area=10) == 1


def test_count_color_supports_both_colour_spaces() -> None:
    screen = paint(make_screen(), 5, 5, 15, 15, RED_BGR)
    for space in ("RGB", "HSV"):
        assert count_color(screen, (255, 0, 0), 2, space, 10) == 1


def test_color_space_defaults_to_hsv() -> None:
    screen = paint(make_screen(), 5, 5, 15, 15, RED_BGR)
    assert count_color(screen, (255, 0, 0), 2) == 1
