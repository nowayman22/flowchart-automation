"""Tests for PNG template matching.

Templates are generated at runtime into tmp_path rather than checked in, so
the fixtures cannot rot and the exact match location is known.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from flowchart_automation.detection.png import (
    count_distinct_rects,
    count_png,
    find_png,
    find_template_in_region,
    load_template,
    preprocess_screen,
)

TEMPLATE_SIZE = 8


def patterned_template(size: int = TEMPLATE_SIZE) -> np.ndarray:
    """A high-contrast pattern.

    A constant-colour template is degenerate for TM_CCOEFF_NORMED (the
    denominator is zero), so the pattern matters.
    """
    rng = np.random.default_rng(1234)
    return rng.integers(0, 256, size=(size, size), dtype=np.uint8)


def write_template(path, array: np.ndarray):
    assert cv2.imwrite(str(path), array)
    return str(path)


def make_screen(width: int = 64, height: int = 64) -> np.ndarray:
    rng = np.random.default_rng(99)
    grey = rng.integers(0, 256, size=(height, width), dtype=np.uint8)
    return cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)


def paste(screen: np.ndarray, template: np.ndarray, x: int, y: int) -> None:
    h, w = template.shape[:2]
    if template.ndim == 2:
        screen[y : y + h, x : x + w] = template[:, :, None]
    else:
        screen[y : y + h, x : x + w] = template


@pytest.fixture
def template_file(tmp_path) -> str:
    return write_template(tmp_path / "template.png", patterned_template())


# --- preprocess_screen ------------------------------------------------------


def test_preprocess_grayscale_produces_single_channel() -> None:
    assert preprocess_screen(make_screen(), "Grayscale").ndim == 2


def test_preprocess_color_keeps_three_channels() -> None:
    processed = preprocess_screen(make_screen(), "Color")
    assert processed.ndim == 3
    assert processed.shape[2] == 3


def test_preprocess_binary_produces_only_two_values() -> None:
    processed = preprocess_screen(make_screen(), "Binary (B&W)")
    assert set(np.unique(processed)).issubset({0, 255})


# --- load_template ----------------------------------------------------------


def test_load_template_reads_and_converts(template_file: str) -> None:
    template, mask = load_template(template_file, "Grayscale")
    assert template is not None
    assert mask is None
    assert template.shape == (TEMPLATE_SIZE, TEMPLATE_SIZE)


def test_load_template_returns_none_pair_for_missing_file(tmp_path) -> None:
    template, mask = load_template(str(tmp_path / "nope.png"))
    assert template is None
    assert mask is None


def test_load_template_caches_by_path_and_mode(template_file: str) -> None:
    cache: dict = {}
    first = load_template(template_file, "Grayscale", cache)
    second = load_template(template_file, "Grayscale", cache)
    assert first is second
    assert len(cache) == 1

    load_template(template_file, "Color", cache)
    assert len(cache) == 2  # different image_mode is a different cache entry


def test_load_template_caches_failures(template_file: str, tmp_path) -> None:
    cache: dict = {}
    missing = str(tmp_path / "missing.png")
    assert load_template(missing, "Grayscale", cache) == (None, None)
    assert cache[f"{missing}|Grayscale"] == (None, None)  # failure is cached


def test_load_template_handles_alpha_channel(tmp_path) -> None:
    grey = patterned_template()
    alpha = np.full((TEMPLATE_SIZE, TEMPLATE_SIZE), 255, np.uint8)
    rgba = np.dstack([grey, grey, grey, alpha])
    assert rgba.shape == (TEMPLATE_SIZE, TEMPLATE_SIZE, 4)

    path = write_template(tmp_path / "alpha.png", rgba)
    template, mask = load_template(path, "Color")
    assert template is not None
    assert mask is not None
    assert template.shape[2] == 3  # alpha stripped
    assert np.all(mask == 255)


# --- find_template_in_region ------------------------------------------------


def test_find_template_reports_centre_of_the_match(template_file: str) -> None:
    template, mask = load_template(template_file, "Grayscale")
    screen = make_screen()
    paste(screen, template, 20, 30)
    processed = preprocess_screen(screen, "Grayscale")

    match = find_template_in_region(processed, (0, 0), (template, mask), threshold=0.9)
    assert match is not None
    x, y, confidence = match
    assert (x, y) == (20 + TEMPLATE_SIZE // 2, 30 + TEMPLATE_SIZE // 2)
    assert confidence >= 0.9


def test_find_template_applies_offset(template_file: str) -> None:
    template, mask = load_template(template_file, "Grayscale")
    screen = make_screen()
    paste(screen, template, 20, 30)
    processed = preprocess_screen(screen, "Grayscale")

    match = find_template_in_region(processed, (500, 400), (template, mask), 0.9)
    assert match is not None
    assert match[:2] == (500 + 24, 400 + 34)


def test_find_template_returns_none_when_absent(template_file: str) -> None:
    template, mask = load_template(template_file, "Grayscale")
    processed = preprocess_screen(make_screen(), "Grayscale")
    assert find_template_in_region(processed, (0, 0), (template, mask), 0.99) is None


def test_find_template_returns_none_for_unloaded_template() -> None:
    assert find_template_in_region(np.zeros((10, 10), np.uint8), (0, 0), (None, None), 0.5) is None


def test_template_larger_than_screen_is_skipped(template_file: str) -> None:
    template, mask = load_template(template_file, "Grayscale")
    tiny = np.zeros((4, 4), np.uint8)
    assert find_template_in_region(tiny, (0, 0), (template, mask), 0.5) is None


# --- find_png / count_png ---------------------------------------------------


def test_find_png_file_mode(template_file: str) -> None:
    screen = make_screen()
    template, _ = load_template(template_file, "Grayscale")
    paste(screen, template, 12, 16)

    step = {"mode": "file", "path": template_file, "image_mode": "Grayscale", "threshold": 0.9}
    pos, confidence = find_png(screen, (0, 0), step, {}, {})
    assert pos == (16, 20)
    assert confidence >= 0.9


def test_find_png_returns_none_for_empty_path() -> None:
    step = {"mode": "file", "path": "", "threshold": 0.9}
    assert find_png(make_screen(), (0, 0), step, {}, {}) == (None, 0.0)


def test_find_png_folder_mode(tmp_path) -> None:
    template = patterned_template()
    write_template(tmp_path / "a.png", template)
    write_template(tmp_path / "b.png", patterned_template())

    screen = make_screen()
    paste(screen, template, 5, 5)

    step = {"mode": "folder", "path": str(tmp_path), "image_mode": "Grayscale", "threshold": 0.9}
    folder_cache: dict = {}
    pos, _ = find_png(screen, (0, 0), step, {}, folder_cache)
    assert pos is not None
    assert len(folder_cache) == 1


def test_find_png_folder_mode_ignores_non_png(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("not an image")
    step = {"mode": "folder", "path": str(tmp_path), "threshold": 0.9}
    assert find_png(make_screen(), (0, 0), step, {}, {}) == (None, 0.0)


def test_count_png_counts_matches(template_file: str) -> None:
    screen = make_screen(96, 96)
    template, _ = load_template(template_file, "Grayscale")
    paste(screen, template, 5, 5)
    paste(screen, template, 60, 60)

    step = {"mode": "file", "path": template_file, "image_mode": "Grayscale", "threshold": 0.9}
    assert count_png(screen, (0, 0), step, {}, {}) == 2


def test_count_png_is_zero_when_absent(template_file: str) -> None:
    step = {"mode": "file", "path": template_file, "image_mode": "Grayscale", "threshold": 0.95}
    assert count_png(make_screen(), (0, 0), step, {}, {}) == 0


def test_count_png_ignores_unreadable_templates(tmp_path) -> None:
    step = {"mode": "folder", "path": str(tmp_path), "threshold": 0.9}
    assert count_png(make_screen(), (0, 0), step, {}, {}) == 0


def test_color_mode_matching(template_file: str) -> None:
    template, _ = load_template(template_file, "Color")
    screen = make_screen()
    paste(screen, template, 10, 10)

    step = {"mode": "file", "path": template_file, "image_mode": "Color", "threshold": 0.9}
    pos, _ = find_png(screen, (0, 0), step, {}, {})
    assert pos == (14, 14)


# --- rectangle grouping -----------------------------------------------------


def test_count_distinct_rects_merges_one_cluster() -> None:
    """A single template instance yields many adjacent above-threshold rects."""
    rects = [[10, 10, 8, 8], [11, 10, 8, 8], [10, 11, 8, 8], [11, 11, 8, 8]]
    assert count_distinct_rects(rects) == 1


def test_count_distinct_rects_keeps_distant_clusters_apart() -> None:
    rects = [[10, 10, 8, 8], [11, 11, 8, 8], [100, 100, 8, 8], [101, 101, 8, 8]]
    assert count_distinct_rects(rects) == 2


def test_count_distinct_rects_handles_empty_input() -> None:
    assert count_distinct_rects([]) == 0


def test_count_distinct_rects_single_rect() -> None:
    assert count_distinct_rects([[0, 0, 5, 5]]) == 1


def test_count_png_does_not_use_removed_grouprectangles(template_file: str, monkeypatch) -> None:
    """Regression: OpenCV 5 removed cv2.groupRectangles.

    pyproject allows opencv-python>=4.8 with no ceiling, so a fresh install
    resolves to 5.x. count_png must not depend on the removed symbol.
    """
    monkeypatch.delattr(cv2, "groupRectangles", raising=False)
    assert not hasattr(cv2, "groupRectangles")

    screen = make_screen(96, 96)
    template, _ = load_template(template_file, "Grayscale")
    paste(screen, template, 5, 5)
    paste(screen, template, 60, 60)

    step = {"mode": "file", "path": template_file, "image_mode": "Grayscale", "threshold": 0.9}
    assert count_png(screen, (0, 0), step, {}, {}) == 2
