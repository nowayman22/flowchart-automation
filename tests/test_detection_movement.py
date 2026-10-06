"""Tests for frame-difference movement detection."""

from __future__ import annotations

import numpy as np
import pytest

from flowchart_automation.detection.movement import MovementResult, compare_frames


def frame(value: int, size: int = 10) -> np.ndarray:
    return np.full((size, size), value, dtype=np.uint8)


def test_identical_frames_are_still() -> None:
    result = compare_frames(frame(100), frame(100))
    assert result == MovementResult(change_percentage=0.0, is_still=True)


def test_fully_changed_frames_are_moving() -> None:
    result = compare_frames(frame(0), frame(255))
    assert result.change_percentage == 100.0
    assert result.is_still is False


def test_partial_change_percentage() -> None:
    previous = frame(0)
    current = frame(0)
    current[:5, :] = 255  # half the rows
    result = compare_frames(previous, current, tolerance=5.0)
    assert result.change_percentage == pytest.approx(50.0)
    assert result.is_still is False


def test_change_at_the_tolerance_boundary_counts_as_still() -> None:
    previous = frame(0)
    current = frame(0)
    current[0, :] = 255  # 1 of 10 rows = 10%
    assert compare_frames(previous, current, tolerance=10.0).is_still is True
    assert compare_frames(previous, current, tolerance=9.9).is_still is False


def test_differences_below_diff_threshold_are_ignored() -> None:
    """Sensor noise should not register as movement."""
    result = compare_frames(frame(100), frame(110), tolerance=0.0, diff_threshold=30)
    assert result.change_percentage == 0.0
    assert result.is_still is True


def test_differences_above_diff_threshold_register() -> None:
    result = compare_frames(frame(100), frame(140), tolerance=0.0, diff_threshold=30)
    assert result.change_percentage == 100.0


def test_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="Frame shape mismatch"):
        compare_frames(frame(0, size=10), frame(0, size=12))


def test_zero_size_frames_do_not_divide_by_zero() -> None:
    empty = np.zeros((0, 0), dtype=np.uint8)
    assert compare_frames(empty, empty).change_percentage == 0.0
