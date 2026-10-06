"""Hyprland (hyprctl) compositor queries and pointer positioning.

Split out from ``capture.py`` because both capture and input need it: grim needs
monitor geometry, and pointer movement is done here rather than through ydotool.

Why the pointer is moved with hyprctl and not ydotool
-----------------------------------------------------
``ydotool mousemove --absolute`` does not map 1:1 onto screen pixels on this
setup. Measured against a 2560x1600 output, asking for x=300 landed at x=775 and
asking for y=800 saturated at the bottom edge, and the reported cursor position
changed on the *other* axis while only one was being set. The virtual device's
absolute range does not match the output, so the mapping is neither linear nor
predictable.

``hyprctl dispatch movecursor`` takes logical screen coordinates and was exact on
every probe, including all four corners, so positioning goes through it. ydotool
is still used for button and key events, which are unaffected: those are discrete
events delivered wherever the cursor already is.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

HYPRCTL = "hyprctl"


class WaylandError(RuntimeError):
    """Raised when a compositor or capture command fails."""


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
        raise WaylandError(f"{cmd[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise WaylandError(f"{cmd[0]} timed out") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise WaylandError(f"{' '.join(cmd)} failed: {detail}")
    return proc.stdout


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
        raise WaylandError(f"Unexpected cursorpos output: {raw!r}") from exc


def move_cursor(x: int, y: int) -> None:
    """Warp the pointer to an exact logical screen coordinate."""
    _run([HYPRCTL, "dispatch", "movecursor", str(int(x)), str(int(y))])
