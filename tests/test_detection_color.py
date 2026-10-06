"""Tests for colour detection, using synthetic images instead of fixtures.

These functions are pure, so a numpy array is all the "screen" they need.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from flowchart_automation.detection.color import (
    TARGET_ALL_MATCHES,
    TARGET_LARGEST_BLOB,
    TARGET_MODES,
    TARGET_NEAREST_BLOB,
    count_color,
    find_blobs,
    find_color_hsv,
    find_color_rgb,
    separate_touching,
)

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


# --- aim point selection ----------------------------------------------------
#
# A colour match is often several blobs. cv2.findContours merges any that touch,
# and anti-aliasing joins blobs with a one-pixel bridge, so "largest blob" can
# silently mean "two blobs and the gap between them".


def two_blobs(join_width: int = 0):
    """Two 40x40 blocks, optionally joined by a horizontal bridge."""
    screen = make_screen(240, 120)
    paint(screen, 20, 30, 60, 70, RED_BGR)  # centre (39, 49)
    paint(screen, 180, 30, 220, 70, RED_BGR)  # centre (199, 49)
    if join_width > 0:
        y1 = 50 - join_width // 2
        paint(screen, 60, y1, 180, y1 + join_width, RED_BGR)
    return screen


def test_separate_blobs_aim_at_one_blob() -> None:
    pos, area = find_color_rgb(two_blobs(), (0, 0), (255, 0, 0), 0, 5)
    assert pos in {(39, 49), (199, 49)}, "should land on a blob, not between them"
    assert area == pytest.approx(1521.0)


def test_a_one_pixel_bridge_merges_the_blobs() -> None:
    """This is the trap: the result is the midpoint, not a blob."""
    joined = two_blobs(join_width=1)
    pos, _ = find_color_rgb(joined, (0, 0), (255, 0, 0), 0, 5)
    assert pos == (119, 49), "merged blobs put the centroid in the gap"

    ys, xs = np.nonzero(cv2.inRange(joined, np.array([0, 0, 255]), np.array([0, 0, 255])))
    assert pos == (int(xs.mean()), int(ys.mean())), "and it equals the centre of mass"


def test_split_width_separates_a_thin_bridge() -> None:
    """The fix for the case above: cut the bridge before finding contours."""
    pos, area = find_color_rgb(two_blobs(join_width=1), (0, 0), (255, 0, 0), 0, 5, split_width=1)
    assert pos in {(39, 49), (199, 49)}
    assert area == pytest.approx(1520.0, abs=5)


def test_split_width_leaves_separate_blobs_alone() -> None:
    before, _ = find_color_rgb(two_blobs(), (0, 0), (255, 0, 0), 0, 5)
    after, _ = find_color_rgb(two_blobs(), (0, 0), (255, 0, 0), 0, 5, split_width=2)
    assert before == after


def test_split_width_zero_is_a_noop() -> None:
    screen = two_blobs(join_width=1)
    assert find_color_rgb(screen, (0, 0), (255, 0, 0), 0, 5, split_width=0) == find_color_rgb(
        screen, (0, 0), (255, 0, 0), 0, 5
    )


def test_center_of_all_matches_lands_between_blobs() -> None:
    """The deliberately different mode: average every matching pixel."""
    pos, area = find_color_rgb(two_blobs(), (0, 0), (255, 0, 0), 0, 5, target=TARGET_ALL_MATCHES)
    assert pos == (119, 49)
    assert area == pytest.approx(3200.0), "reports matched pixels, not a contour area"


def test_center_of_all_matches_respects_offset() -> None:
    pos, _ = find_color_rgb(two_blobs(), (1000, 500), (255, 0, 0), 0, 5, target=TARGET_ALL_MATCHES)
    assert pos == (1119, 549)


def test_nearest_blob_picks_the_one_closest_to_the_area_centre() -> None:
    # Area is 240 wide, so its centre is x=120; the blob at 199 is nearer than 39.
    pos, _ = find_color_rgb(two_blobs(), (0, 0), (255, 0, 0), 0, 5, target=TARGET_NEAREST_BLOB)
    assert pos == (199, 49)


def test_nearest_blob_flips_with_the_blob_positions() -> None:
    screen = make_screen(240, 120)
    paint(screen, 10, 30, 50, 70, RED_BGR)  # centre (29, 49)
    paint(screen, 200, 30, 240, 70, RED_BGR)  # centre (219, 49), outside-ish
    pos, _ = find_color_rgb(screen, (0, 0), (255, 0, 0), 0, 5, target=TARGET_NEAREST_BLOB)
    assert pos == (29, 49)


def test_unknown_target_falls_back_to_largest_blob() -> None:
    """A project written by a newer version must still load and run."""
    assert find_color_rgb(
        two_blobs(), (0, 0), (255, 0, 0), 0, 5, target="Some Future Mode"
    ) == find_color_rgb(two_blobs(), (0, 0), (255, 0, 0), 0, 5)


def test_largest_blob_wins_over_a_smaller_neighbour() -> None:
    screen = make_screen(240, 120)
    paint(screen, 10, 10, 30, 30, RED_BGR)  # small
    paint(screen, 150, 40, 230, 110, RED_BGR)  # large, centre (189, 74)
    pos, _ = find_color_rgb(screen, (0, 0), (255, 0, 0), 0, 5, target=TARGET_LARGEST_BLOB)
    assert pos == (189, 74)


def test_no_match_returns_none_for_every_target() -> None:
    blank = make_screen(colour=GREEN_BGR)
    for target in TARGET_MODES:
        assert find_color_rgb(blank, (0, 0), (255, 0, 0), 0, 5, target=target) == (None, 0.0)


def test_min_pixel_area_still_gates_every_target() -> None:
    screen = paint(make_screen(), 10, 10, 13, 13, RED_BGR)  # tiny
    for target in TARGET_MODES:
        pos, _ = find_color_rgb(screen, (0, 0), (255, 0, 0), 0, 500, target=target)
        assert pos is None, f"{target} ignored min_pixel_area"


def test_modes_are_distinct_for_a_merged_pair() -> None:
    """Largest-blob and centre-of-mass coincide when blobs are merged."""
    merged = two_blobs(join_width=1)
    largest, _ = find_color_rgb(merged, (0, 0), (255, 0, 0), 0, 5, target=TARGET_LARGEST_BLOB)
    com, _ = find_color_rgb(merged, (0, 0), (255, 0, 0), 0, 5, target=TARGET_ALL_MATCHES)
    assert largest == com, "documents why blob splitting is needed"

    split, _ = find_color_rgb(merged, (0, 0), (255, 0, 0), 0, 5, split_width=1)
    assert split != largest, "splitting is what actually changes the aim point"


# --- blob helpers -----------------------------------------------------------


def test_find_blobs_reports_each_region() -> None:
    mask = cv2.inRange(two_blobs(), np.array([0, 0, 255]), np.array([0, 0, 255]))
    blobs = find_blobs(mask, min_pixel_area=5)
    assert len(blobs) == 2
    assert sorted(b.x for b in blobs) == [39, 199]
    assert all(b.area > 1000 for b in blobs)


def test_find_blobs_respects_min_pixel_area() -> None:
    mask = cv2.inRange(two_blobs(), np.array([0, 0, 255]), np.array([0, 0, 255]))
    assert find_blobs(mask, min_pixel_area=100000) == []


def test_separate_touching_zero_width_returns_the_same_mask() -> None:
    mask = cv2.inRange(two_blobs(1), np.array([0, 0, 255]), np.array([0, 0, 255]))
    assert separate_touching(mask, 0) is mask


def test_separate_touching_splits_one_contour_into_two() -> None:
    mask = cv2.inRange(two_blobs(1), np.array([0, 0, 255]), np.array([0, 0, 255]))
    assert len(find_blobs(mask, 5)) == 1, "one merged contour to begin with"
    assert len(find_blobs(separate_touching(mask, 1), 5)) == 2


def test_hsv_path_honours_the_same_options() -> None:
    screen = two_blobs(join_width=1)
    rgb, _ = find_color_rgb(screen, (0, 0), (255, 0, 0), 2, 5, split_width=1)
    hsv, _ = find_color_hsv(screen, (0, 0), (255, 0, 0), 2, 5, split_width=1)
    assert rgb == hsv
