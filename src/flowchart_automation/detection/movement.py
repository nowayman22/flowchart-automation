"""Frame-difference movement detection.

Pure functions; no UI state. Caller is responsible for capturing frames with
pyautogui and storing the previous frame between calls.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class MovementResult:
    change_percentage: float
    is_still: bool


def compare_frames(
    previous: np.ndarray,
    current: np.ndarray,
    tolerance: float = 5.0,
    diff_threshold: int = 30,
) -> MovementResult:
    """Compare two grayscale frames and return whether the scene is still.

    Args:
        previous: Grayscale frame from the previous scan cycle.
        current: Grayscale frame from the current scan cycle.
        tolerance: Maximum percentage of changed pixels that counts as still.
        diff_threshold: Pixel intensity difference that counts as changed (0-255).

    Returns:
        MovementResult with the change percentage and whether the scene is still.
    """
    if previous.shape != current.shape:
        raise ValueError(
            f"Frame shape mismatch: {previous.shape} vs {current.shape}"
        )
    diff = cv2.absdiff(previous, current)
    _, thresholded = cv2.threshold(diff, diff_threshold, 255, cv2.THRESH_BINARY)
    non_zero = int(np.count_nonzero(thresholded))
    total = thresholded.size
    change_pct = (non_zero / total) * 100.0 if total > 0 else 0.0
    return MovementResult(change_percentage=change_pct, is_still=change_pct <= tolerance)
