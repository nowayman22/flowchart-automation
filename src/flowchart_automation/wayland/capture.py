"""Screen capture on Wayland via grim.

grim is the correct capture tool on wlroots/Hyprland: it asks the compositor for
the frame, so it works where ``pyautogui.screenshot()`` (an X11 screen grab)
cannot.

Monitor geometry and pointer positioning live in ``compositor.py``; the names are
re-exported here so callers that only care about the screen have one import.

Coordinate spaces
-----------------
The app reasons in *logical* pixels, which is what the user draws on screen and
what Hyprland reports. grim captures *physical* pixels. On a scale-1 monitor the
two are identical; on a HiDPI monitor a logical region must be multiplied by the
monitor scale before it is handed to grim. All of that conversion lives here so
callers never have to think about it.
"""

from __future__ import annotations

import io
import shutil

import numpy as np
from PIL import Image

from .compositor import (
    Monitor,
    WaylandError,
    _run,
    hyprctl_available,
    move_cursor,
    query_cursor_position,
    query_monitors,
)

GRIM = "grim"

# Capture failures are a kind of backend failure; kept as its own name because
# callers catch it around screenshot code.
CaptureError = WaylandError

__all__ = [
    "CaptureError",
    "GrimCapture",
    "Monitor",
    "WaylandError",
    "grim_available",
    "hyprctl_available",
    "move_cursor",
    "parse_ppm",
    "query_cursor_position",
    "query_monitors",
]


def grim_available() -> bool:
    return shutil.which(GRIM) is not None


def parse_ppm(data: bytes) -> np.ndarray:
    """Parse a binary P6 PPM into an (h, w, 3) uint8 RGB array.

    grim can hand back uncompressed pixels, which skips both grim's PNG encoder
    and PIL's PNG decoder. Measured on a 2560x1600 output that is the difference
    between roughly 347 ms and 52 ms per frame. Capture dominates the scan loop
    (colour detection itself costs about 5 ms), so this decides how well a moving
    target can be tracked.

    The array is a view onto *data*; copy it before mutating in place.
    """
    if not data.startswith(b"P6"):
        raise CaptureError("grim did not return a P6 PPM")

    fields: list[bytes] = []
    index = 2
    while len(fields) < 3:
        while index < len(data) and data[index : index + 1].isspace():
            index += 1
        if index >= len(data):
            raise CaptureError("truncated PPM header")
        if data[index : index + 1] == b"#":  # comment line, permitted by the spec
            while index < len(data) and data[index : index + 1] not in (b"\r", b"\n"):
                index += 1
            continue
        start = index
        while index < len(data) and not data[index : index + 1].isspace():
            index += 1
        fields.append(data[start:index])

    index += 1  # exactly one whitespace byte sits between header and pixels

    try:
        width, height, maxval = (int(f) for f in fields)
    except ValueError as exc:
        raise CaptureError(f"unreadable PPM header: {fields!r}") from exc
    if maxval != 255:
        raise CaptureError(f"unsupported PPM maxval {maxval}")

    payload = data[index:]
    expected = width * height * 3
    if len(payload) != expected:
        raise CaptureError(f"PPM payload is {len(payload)} bytes, expected {expected}")
    return np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 3)


class GrimCapture:
    """Screenshot and pixel sampling backed by grim."""

    def __init__(self, monitor: Monitor | None = None) -> None:
        self._monitor = monitor
        self._ppm_supported = True

    @property
    def monitor(self) -> Monitor:
        if self._monitor is None:
            monitors = query_monitors()
            if not monitors:
                raise CaptureError("Hyprland reported no monitors")
            # The leftmost monitor anchors the coordinate origin.
            self._monitor = monitors[0]
        return self._monitor

    def refresh(self) -> None:
        """Drop cached geometry, e.g. after a resolution or scale change."""
        self._monitor = None

    def size(self) -> tuple[int, int]:
        """Logical screen size, matching what pyautogui.size() would return."""
        monitor = self.monitor
        return monitor.logical_width, monitor.logical_height

    def position(self) -> tuple[int, int]:
        return query_cursor_position()

    def move_to(self, x: int, y: int) -> None:
        move_cursor(x, y)

    def _capture_png(self, geometry: str | None) -> Image.Image:
        cmd = [GRIM]
        if geometry is not None:
            cmd += ["-g", geometry]
        cmd += ["-t", "png", "-"]
        data = _run(cmd)
        if not data:
            raise CaptureError("grim returned no image data")
        return Image.open(io.BytesIO(data)).convert("RGB")

    def _capture_ppm(self, geometry: str | None) -> np.ndarray:
        cmd = [GRIM]
        if geometry is not None:
            cmd += ["-g", geometry]
        cmd += ["-t", "ppm", "-"]
        data = _run(cmd)
        if not data:
            raise CaptureError("grim returned no image data")
        return parse_ppm(data)

    def screenshot_array(self, region: tuple[int, int, int, int] | None = None) -> np.ndarray:
        """Capture as an RGB numpy array, taking the fastest path available.

        Prefers grim's uncompressed PPM output. If that is unavailable the PNG
        path is used and remembered, so a grim built without PPM support costs
        one failed attempt rather than one per frame.
        """
        geometry = self._to_geometry(region) if region is not None else None
        if self._ppm_supported:
            try:
                return self._capture_ppm(geometry)
            except CaptureError:
                self._ppm_supported = False
        return np.asarray(self._capture_png(geometry))

    def _to_geometry(self, region: tuple[int, int, int, int]) -> str:
        """Convert a logical (x, y, w, h) region to grim's physical geometry.

        grim expects ``"x,y wxh"``. The region is intersected with the monitor
        so an area dragged partly off-screen captures the visible part instead
        of erroring out or silently grabbing the wrong pixels.
        """
        x, y, width, height = region
        monitor = self.monitor
        scale = monitor.scale or 1.0

        x1 = max(0, int(x))
        y1 = max(0, int(y))
        x2 = min(monitor.logical_width, int(x) + max(1, int(width)))
        y2 = min(monitor.logical_height, int(y) + max(1, int(height)))

        # A region entirely off-screen still has to produce something valid.
        if x2 <= x1:
            x2 = min(monitor.logical_width, x1 + 1)
        if y2 <= y1:
            y2 = min(monitor.logical_height, y1 + 1)

        return (
            f"{int(x1 * scale)},{int(y1 * scale)} "
            f"{max(1, int((x2 - x1) * scale))}x{max(1, int((y2 - y1) * scale))}"
        )

    def screenshot(self, region: tuple[int, int, int, int] | None = None) -> Image.Image:
        """Capture the screen, or a logical (x, y, w, h) region of it."""
        return Image.fromarray(self.screenshot_array(region))

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        """Return the RGB colour at a logical screen coordinate."""
        image = self.screenshot((int(x), int(y), 1, 1))
        r, g, b = image.getpixel((0, 0))[:3]
        return int(r), int(g), int(b)
