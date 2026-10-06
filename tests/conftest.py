"""Shared fixtures for tests that need the legacy Tkinter app.

The picker and the Settings Inject step both live in ``FlowchartClickerApp66``
and need a real display, so they share one fixture here. Everything else in the
suite is pure and runs headless.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


#: Apply to any test that builds the real app.
requires_display = pytest.mark.skipif(not _has_display(), reason="needs a display server")


@pytest.fixture
def app():
    """A constructed FlowchartClickerApp with one colour step added.

    Yields ``(instance, root)``. The Wayland shim is installed first because
    importing the legacy module imports pyautogui, which cannot be imported on a
    Wayland session at all.
    """
    if not _has_display():
        pytest.skip("needs a display server")

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from flowchart_automation.wayland import install_shim

    install_shim(verbose=False)

    FlowchartClickerApp66 = pytest.importorskip("FlowchartClickerApp66")

    root = tk.Tk()
    instance = FlowchartClickerApp66.FlowchartClickerApp(root)
    root.update()
    instance.add_step("color")
    root.update()
    try:
        yield instance, root
    finally:
        import contextlib

        with contextlib.suppress(tk.TclError):
            root.destroy()
