"""Screen capture on Wayland via grim, with monitor geometry from hyprctl.

grim is the correct capture tool on wlroots/Hyprland: it asks the compositor for
the frame, so it works where ``pyautogui.screenshot()`` (an X11 screen grab)
cannot.

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
import json
import shutil
import subprocess
from dataclasses import dataclass

from PIL import Image

GRIM = "grim"
HYPRCTL = "hyprctl"


class CaptureError(RuntimeError):
    """Raised when a screenshot cannot be taken."""


@dataclass(frozen=True)
class Monitor:
    """A Hyprland monitor as reported by ``hyprctl monitors -j``."""

    name: str
    width: int  # physical pixels
    height: int  # physical pixels
    scale: float
    x: int
    y: int

    @property
    def logical_width(self) -> int:
        return int(self.width / self.scale) if self.scale else self.width

    @property
    def logical_height(self) -> int:
        return int(self.height / self.scale) if self.scale else self.height


def _run(cmd: list[str], *, timeout: float = 10.0) -> bytes:
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise CaptureError(f"{cmd[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise CaptureError(f"{cmd[0]} timed out") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise CaptureError(f"{' '.join(cmd)} failed: {detail}")
    return proc.stdout


def grim_available() -> bool:
    return shutil.which(GRIM) is not None


def hyprctl_available() -> bool:
    return shutil.which(HYPRCTL) is not None


def query_monitors() -> list[Monitor]:
    """Return all monitors, ordered by x position."""
    raw = _run([HYPRCTL, "monitors", "-j"])
    data = json.loads(raw.decode())
    monitors = [
        Monitor(
            name=m.get("name", "unknown"),
            width=int(m.get("width", 0)),
            height=int(m.get("height", 0)),
            scale=float(m.get("scale", 1.0) or 1.0),
            x=int(m.get("x", 0)),
            y=int(m.get("y", 0)),
        )
        for m in data
    ]
    return sorted(monitors, key=lambda m: m.x)


def query_cursor_position() -> tuple[int, int]:
    """Return the logical cursor position."""
    raw = _run([HYPRCTL, "cursorpos"]).decode().strip()
    try:
        x_str, y_str = raw.split(",")
        return int(x_str.strip()), int(y_str.strip())
    except ValueError as exc:
        raise CaptureError(f"Unexpected cursorpos output: {raw!r}") from exc


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
