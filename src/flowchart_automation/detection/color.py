"""Color-based screen detection.

All functions are pure (no UI state). They accept explicit parameters so they
can be unit-tested with fixture images.

Choosing *where* to click
-------------------------
A colour match is rarely one tidy shape. ``cv2.findContours`` merges any two
regions that touch, and anti-aliasing joins blobs with a bridge a single pixel
wide, so "the largest blob" can easily be two blobs wearing a trench coat. The
centroid of such a merged contour sits in the gap between them, exactly where
the user did not want to click::

    blobs at x=39 and x=199, joined by a 1px line
    -> largest-contour centroid = 119   (identical to the centre of mass)

Two independent controls deal with that:

``target``
    Which point to aim at once blobs are known. ``Largest Blob`` keeps the
    original behaviour, ``Center Of All Matches`` averages every matching pixel
    (so it deliberately lands between separated blobs), and
    ``Nearest Blob To Area Center`` picks a single blob near the middle of the
    scanned region when several are present.

``split_width``
    Morphological opening applied first, to cut the thin bridges that merge
    neighbouring blobs into one contour. Width in pixels; 0 disables it.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Aim-point modes. These strings are stored in saved projects, so they are part
# of the on-disk format; do not rename them without a migration.
TARGET_LARGEST_BLOB = "Largest Blob"
TARGET_ALL_MATCHES = "Center Of All Matches"
TARGET_NEAREST_BLOB = "Nearest Blob To Area Center"
TARGET_MODES = (TARGET_LARGEST_BLOB, TARGET_ALL_MATCHES, TARGET_NEAREST_BLOB)
DEFAULT_TARGET = TARGET_LARGEST_BLOB


@dataclass(frozen=True)
class Blob:
    """One matched region: its centroid in region-local pixels, and its area."""

    x: int
    y: int
    area: float

    @property
    def pos(self) -> tuple[int, int]:
        return (self.x, self.y)


def separate_touching(mask: np.ndarray, width: int) -> np.ndarray:
    """Cut thin bridges between blobs with a morphological opening.

    A kernel of ``2 * width + 1`` erodes ``width`` pixels from every side, so a
    bridge up to ``2 * width`` pixels across is severed; the following dilate
    restores the surviving blobs to roughly their original size.
    """
    if width is None or int(width) <= 0:
        return mask
    size = 2 * int(width) + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)


def find_blobs(mask: np.ndarray, min_pixel_area: int = 10) -> list[Blob]:
    """Return every matched region larger than *min_pixel_area*."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blobs: list[Blob] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area <= min_pixel_area:
            continue
        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            continue
        blobs.append(
            Blob(
                x=int(moments["m10"] / moments["m00"]),
                y=int(moments["m01"] / moments["m00"]),
                area=float(area),
            )
        )
    return blobs


def _center_of_all_matches(
    mask: np.ndarray,
    offset: tuple[int, int],
    min_pixel_area: int,
) -> tuple[tuple[int, int] | None, float]:
    """Average position of every matching pixel, ignoring blob boundaries.

    The reported area is the matched pixel count rather than a contour area,
    since there is no single contour here.
    """
    ys, xs = np.nonzero(mask)
    count = int(xs.size)
    if count == 0 or count <= min_pixel_area:
        return None, 0.0
    return (int(xs.mean()) + offset[0], int(ys.mean()) + offset[1]), float(count)


def select_target(
    mask: np.ndarray,
    offset: tuple[int, int] = (0, 0),
    min_pixel_area: int = 10,
    target: str = DEFAULT_TARGET,
) -> tuple[tuple[int, int] | None, float]:
    """Pick the aim point from a colour mask.

    Returns ``((x, y), area)`` in screen coordinates, or ``(None, 0.0)`` when
    nothing qualifies. An unrecognised *target* falls back to the largest blob
    so a project saved by a newer version still loads.
    """
    if target == TARGET_ALL_MATCHES:
        return _center_of_all_matches(mask, offset, min_pixel_area)

    blobs = find_blobs(mask, min_pixel_area)
    if not blobs:
        return None, 0.0

    if target == TARGET_NEAREST_BLOB:
        # The scanned region's own centre, so no extra geometry is needed.
        center_x, center_y = mask.shape[1] / 2.0, mask.shape[0] / 2.0
        chosen = min(blobs, key=lambda b: (b.x - center_x) ** 2 + (b.y - center_y) ** 2)
    else:
        chosen = max(blobs, key=lambda b: b.area)

    return (chosen.x + offset[0], chosen.y + offset[1]), chosen.area


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


def _color_mask(
    img_bgr: np.ndarray,
    rgb: tuple[int, int, int],
    tolerance: int,
    color_space: str = "HSV",
) -> np.ndarray:
    if color_space == "RGB":
        return _color_mask_rgb(img_bgr, rgb, tolerance)
    return _color_mask_hsv(img_bgr, rgb, tolerance)


def find_color_hsv(
    img_bgr: np.ndarray,
    offset: tuple[int, int],
    rgb: tuple[int, int, int],
    tolerance: int,
    min_pixel_area: int = 10,
    target: str = DEFAULT_TARGET,
    split_width: int = 0,
) -> tuple[tuple[int, int] | None, float]:
    """Return the aim point of the HSV-matched colour and its area."""
    mask = separate_touching(_color_mask_hsv(img_bgr, rgb, tolerance), split_width)
    return select_target(mask, offset, min_pixel_area, target)


def find_color_rgb(
    img_bgr: np.ndarray,
    offset: tuple[int, int],
    rgb: tuple[int, int, int],
    tolerance: int,
    min_pixel_area: int = 10,
    target: str = DEFAULT_TARGET,
    split_width: int = 0,
) -> tuple[tuple[int, int] | None, float]:
    """Return the aim point of the RGB-matched colour and its area."""
    mask = separate_touching(_color_mask_rgb(img_bgr, rgb, tolerance), split_width)
    return select_target(mask, offset, min_pixel_area, target)


def count_color(
    screen_cv: np.ndarray,
    rgb: tuple[int, int, int],
    tolerance: int,
    color_space: str = "HSV",
    min_pixel_area: int = 10,
) -> int:
    """Return the number of distinct color blobs meeting the area threshold."""
    mask = _color_mask(screen_cv, rgb, tolerance, color_space)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return sum(1 for c in contours if cv2.contourArea(c) > min_pixel_area)
