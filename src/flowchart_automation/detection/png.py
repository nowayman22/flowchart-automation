"""PNG template-matching detection.

Pure functions; no UI state. Caches are plain dicts passed in by the caller so
the caller controls cache lifetime. This makes the functions testable with
fixture images.

TemplateCache: maps "path|mode" -> (processed_template, mask | None)
FolderCache: maps "dir_path|mode" -> list of (processed_template, mask | None)
"""

from __future__ import annotations

import math
import os
from typing import Any

import cv2
import numpy as np

TemplateData = tuple[np.ndarray | None, np.ndarray | None]
TemplateCache = dict[str, TemplateData]
FolderCache = dict[str, list[TemplateData]]


def preprocess_screen(screen_cv: np.ndarray, image_mode: str) -> np.ndarray:
    if image_mode == "Grayscale":
        return cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY)
    if image_mode == "Binary (B&W)":
        gray = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary
    return screen_cv  # Color


def load_template(
    path: str,
    image_mode: str = "Grayscale",
    cache: TemplateCache | None = None,
) -> TemplateData:
    """Load and pre-process a PNG template, optionally caching the result.

    Returns (None, None) if the file cannot be read.
    """
    key = f"{path}|{image_mode}"
    if cache is not None and key in cache:
        return cache[key]

    try:
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError(f"Cannot read image: {path}")

        mask: np.ndarray | None = None
        if len(img.shape) == 3 and img.shape[2] == 4:
            alpha = img[:, :, 3]
            _, mask = cv2.threshold(alpha, 1, 255, cv2.THRESH_BINARY)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        if image_mode == "Color":
            processed = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if len(img.shape) == 2 else img
        else:
            processed = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            if image_mode == "Binary (B&W)":
                _, processed = cv2.threshold(processed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        result: TemplateData = (processed, mask)
    except Exception:
        result = (None, None)

    if cache is not None:
        cache[key] = result
    return result


def find_template_in_region(
    screen_processed: np.ndarray,
    offset: tuple[int, int],
    template_data: TemplateData,
    threshold: float,
) -> tuple[int, int, float] | None:
    """Find a single template in a pre-processed screen region.

    Returns (center_x, center_y, confidence) or None if not found.
    """
    template, mask = template_data
    if template is None:
        return None
    if any(s < t for s, t in zip(screen_processed.shape, template.shape, strict=False)):
        return None

    h, w = template.shape[:2]

    if mask is not None:
        res = cv2.matchTemplate(screen_processed, template, cv2.TM_SQDIFF_NORMED, mask=mask)
        min_val, _, min_loc, _ = cv2.minMaxLoc(res)
        confidence = 1.0 - min_val
        if confidence >= threshold:
            return (min_loc[0] + w // 2 + offset[0], min_loc[1] + h // 2 + offset[1], confidence)
    else:
        res = cv2.matchTemplate(screen_processed, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val >= threshold:
            return (max_loc[0] + w // 2 + offset[0], max_loc[1] + h // 2 + offset[1], max_val)

    return None


def _collect_templates(
    step: dict[str, Any],
    template_cache: TemplateCache,
    folder_cache: FolderCache,
) -> list[TemplateData]:
    image_mode = step.get("image_mode", "Grayscale")
    mode = step.get("mode", "file")
    path = step.get("path", "")

    if mode == "file" and path:
        return [load_template(path, image_mode, template_cache)]

    if mode == "folder" and path and os.path.isdir(path):
        key = f"{path}|{image_mode}"
        if key not in folder_cache:
            entries: list[TemplateData] = []
            for fname in os.listdir(path):
                if fname.lower().endswith(".png"):
                    td = load_template(os.path.join(path, fname), image_mode, template_cache)
                    if td[0] is not None:
                        entries.append(td)
            folder_cache[key] = entries
        return folder_cache.get(key, [])

    return []


def find_png(
    screen_cv: np.ndarray,
    offset: tuple[int, int],
    step: dict[str, Any],
    template_cache: TemplateCache,
    folder_cache: FolderCache,
) -> tuple[tuple[int, int] | None, float]:
    """Find a template and return (position, confidence).

    With find_first_match=True returns on the first hit; otherwise returns the
    best match across all templates.
    """
    image_mode = step.get("image_mode", "Grayscale")
    screen_processed = preprocess_screen(screen_cv, image_mode)
    threshold = step.get("threshold", 0.8)
    find_first = step.get("find_first_match", True)
    templates = _collect_templates(step, template_cache, folder_cache)

    best_pos: tuple[int, int] | None = None
    best_conf = -1.0

    for td in templates:
        match = find_template_in_region(screen_processed, offset, td, threshold)
        if match and math.isfinite(match[2]):
            if find_first:
                return match[:2], match[2]  # type: ignore[return-value]
            if match[2] > best_conf:
                best_conf = match[2]
                best_pos = match[:2]  # type: ignore[assignment]

    if find_first:
        return None, 0.0
    return best_pos, best_conf if best_conf > -1 else 0.0


def _boxes_are_adjacent(a: list[int], b: list[int], eps: float) -> bool:
    """True if two [x, y, w, h] boxes touch once each is grown by eps."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw + aw * eps < bx - bw * eps
        or bx + bw + bw * eps < ax - aw * eps
        or ay + ah + ah * eps < by - bh * eps
        or by + bh + bh * eps < ay - ah * eps
    )


def count_distinct_rects(rects: list[list[int]], eps: float = 0.2) -> int:
    """Count distinct detections by merging touching rectangles.

    Stands in for ``cv2.groupRectangles``, which OpenCV 5 removed. A single
    template instance produces a cluster of above-threshold rectangles around
    the true location; overlapping clusters collapse to one count.
    """
    if not rects:
        return 0

    parent = list(range(len(rects)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if _boxes_are_adjacent(rects[i], rects[j], eps):
                root_i, root_j = find(i), find(j)
                if root_i != root_j:
                    parent[root_j] = root_i

    return len({find(i) for i in range(len(rects))})


def count_png(
    screen_cv: np.ndarray,
    offset: tuple[int, int],
    step: dict[str, Any],
    template_cache: TemplateCache,
    folder_cache: FolderCache,
) -> int:
    """Return the number of non-overlapping template instances on screen."""
    image_mode = step.get("image_mode", "Grayscale")
    screen_processed = preprocess_screen(screen_cv, image_mode)
    threshold = step.get("threshold", 0.8)
    templates = _collect_templates(step, template_cache, folder_cache)

    all_rects: list[list[int]] = []

    for template, mask in templates:
        if template is None:
            continue
        h, w = template.shape[:2]
        if any(s < t for s, t in zip(screen_processed.shape, template.shape, strict=False)):
            continue

        if mask is not None:
            res = cv2.matchTemplate(screen_processed, template, cv2.TM_SQDIFF_NORMED, mask=mask)
            locs = np.where(res <= (1.0 - threshold))
        else:
            res = cv2.matchTemplate(screen_processed, template, cv2.TM_CCOEFF_NORMED)
            locs = np.where(res >= threshold)

        for pt in zip(*locs[::-1], strict=False):
            all_rects.append([int(pt[0]), int(pt[1]), w, h])

    return count_distinct_rects(all_rects)
