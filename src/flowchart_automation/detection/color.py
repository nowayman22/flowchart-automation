"""Color-based screen detection.

All functions are pure (no UI state). They accept explicit parameters so they
can be unit-tested with fixture images.
"""

from __future__ import annotations

import cv2
import numpy as np


def _color_mask_hsv(
    img_bgr: np.ndarray,
    rgb: tuple[int, int, int],
    tolerance: int,
) -> np.ndarray:
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    target_hsv = cv2.cvtColor(np.uint8([[list(reversed(rgb))]]), cv2.COLOR_BGR2HSV)[0][0]
    h, s, v = int(target_hsv[0]), int(target_hsv[1]), int(target_hsv[2])
    h_tol = int(tolerance * 1.8)
    s_tol = int(tolerance * 2.5)
    v_tol = int(tolerance * 2.5)
    lower = np.array([max(0, h - h_tol), max(0, s - s_tol), max(0, v - v_tol)])
    upper = np.array([min(179, h + h_tol), min(255, s + s_tol), min(255, v + v_tol)])
    return cv2.inRange(hsv, lower, upper)


def _color_mask_rgb(
    img_bgr: np.ndarray,
    rgb: tuple[int, int, int],
    tolerance: int,
) -> np.ndarray:
    lower = np.array([max(0, rgb[2] - tolerance), max(0, rgb[1] - tolerance), max(0, rgb[0] - tolerance)])
    upper = np.array(
        [min(255, rgb[2] + tolerance), min(255, rgb[1] + tolerance), min(255, rgb[0] + tolerance)]
    )
    return cv2.inRange(img_bgr, lower, upper)


def _largest_contour_pos(
    mask: np.ndarray,
    offset: tuple[int, int],
    min_pixel_area: int,
) -> tuple[tuple[int, int] | None, float]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, 0.0
    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    if area <= min_pixel_area:
        return None, 0.0
    m = cv2.moments(largest)
    if m["m00"] == 0:
        return None, 0.0
    cx = int(m["m10"] / m["m00"]) + offset[0]
    cy = int(m["m01"] / m["m00"]) + offset[1]
    return (cx, cy), float(area)


def find_color_hsv(
    img_bgr: np.ndarray,
    offset: tuple[int, int],
    rgb: tuple[int, int, int],
    tolerance: int,
    min_pixel_area: int = 10,
) -> tuple[tuple[int, int] | None, float]:
    """Return the centroid of the largest HSV-matched blob and its area."""
    mask = _color_mask_hsv(img_bgr, rgb, tolerance)
    return _largest_contour_pos(mask, offset, min_pixel_area)


def find_color_rgb(
    img_bgr: np.ndarray,
    offset: tuple[int, int],
    rgb: tuple[int, int, int],
    tolerance: int,
    min_pixel_area: int = 10,
) -> tuple[tuple[int, int] | None, float]:
    """Return the centroid of the largest RGB-matched blob and its area."""
    mask = _color_mask_rgb(img_bgr, rgb, tolerance)
    return _largest_contour_pos(mask, offset, min_pixel_area)


def count_color(
    screen_cv: np.ndarray,
    rgb: tuple[int, int, int],
    tolerance: int,
    color_space: str = "HSV",
    min_pixel_area: int = 10,
) -> int:
    """Return the number of distinct color blobs meeting the area threshold."""
    if color_space == "RGB":
        mask = _color_mask_rgb(screen_cv, rgb, tolerance)
    else:
        mask = _color_mask_hsv(screen_cv, rgb, tolerance)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return sum(1 for c in contours if cv2.contourArea(c) > min_pixel_area)
