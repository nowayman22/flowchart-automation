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
    "query_cursor_position",
    "query_monitors",
]


def grim_available() -> bool:
    return shutil.which(GRIM) is not None


class GrimCapture:
    """Screenshot and pixel sampling backed by grim."""

    def __init__(self, monitor: Monitor | None = None) -> None:
        self._monitor = monitor

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
        if region is None:
            return self._capture_png(None)
        return self._capture_png(self._to_geometry(region))

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        """Return the RGB colour at a logical screen coordinate."""
        image = self.screenshot((int(x), int(y), 1, 1))
        r, g, b = image.getpixel((0, 0))[:3]
        return int(r), int(g), int(b)
