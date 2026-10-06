"""Wayland backend: screen capture via grim, input via ydotool.

The rest of the project is written against ``pyautogui``, which is X11-only and
cannot run on a Wayland session. Importing this package and calling
:func:`install_shim` before the app is loaded makes those calls work unchanged.

Typical use, from the entry point::

    from flowchart_automation.wayland import install_shim
    install_shim()
    from FlowchartClickerApp66 import FlowchartClickerApp
"""

from __future__ import annotations

from .capture import (
    CaptureError,
    GrimCapture,
    grim_available,
)
from .compositor import (
    Monitor,
    WaylandError,
    hyprctl_available,
    move_cursor,
    query_cursor_position,
    query_monitors,
)
from .input import (
    InputError,
    YdotoolInput,
    daemon_running,
    unavailable_reason,
    ydotool_available,
)
from .shim import PyAutoGUIShim, already_installed, install, is_wayland_session

__all__ = [
    "CaptureError",
    "GrimCapture",
    "InputError",
    "Monitor",
    "PyAutoGUIShim",
    "WaylandError",
    "YdotoolInput",
    "already_installed",
    "backend_report",
    "daemon_running",
    "grim_available",
    "hyprctl_available",
    "install",
    "install_shim",
    "is_wayland_session",
    "move_cursor",
    "query_cursor_position",
    "query_monitors",
    "unavailable_reason",
    "ydotool_available",
]


def install_shim(verbose: bool = True) -> bool:
    """Install the pyautogui shim when running on Wayland.

    Safe to call unconditionally: it is a no-op on X11/Windows, or when grim is
    unavailable. Call it before importing anything that imports pyautogui.
    """
    if not is_wayland_session():
        return False

    installed = install()
    if installed and verbose:
        print(f"[flowchart-automation] Wayland backend active ({backend_report()})")
    elif not installed and verbose:
        print(
            "[flowchart-automation] Wayland detected but the backend is "
            "unavailable (grim/hyprctl missing). Automation will not work."
        )
    return installed


def backend_report() -> str:
    """One-line summary of what is available, for the log and diagnostics."""
    if not is_wayland_session():
        return "native pyautogui (not a Wayland session)"

    parts = []
    parts.append("grim" if grim_available() else "grim MISSING")
    parts.append("hyprctl" if hyprctl_available() else "hyprctl MISSING")

    if not ydotool_available():
        parts.append("ydotool MISSING (no click/keypress)")
    elif not daemon_running():
        parts.append("ydotoold NOT RUNNING (no click/keypress)")
    else:
        parts.append("ydotool ready")

    return ", ".join(parts)
