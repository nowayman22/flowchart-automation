"""Regression tests for the F3 capture picker in the legacy app.

The picker used to hide the main window and wait for the global F3 hotkey. On
Linux that hotkey cannot be registered (the `keyboard` library needs root), so
nothing ever fired and the app stayed hidden forever with no way back. These
tests pin the two things that made it unrecoverable:

1. the picker window must be a normal managed toplevel, because Hyprland never
   delivers keyboard input to an override-redirect window, and
2. every exit path must restore the main window and clear the picker state.

They need a real display and the legacy app, so they skip on headless CI rather
than failing there.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tkinter as tk
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="needs a display server",
)


@pytest.fixture
def app():
    """A constructed FlowchartClickerApp, with the Wayland shim installed."""
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
        with contextlib.suppress(tk.TclError):
            root.destroy()


def test_picker_overlay_is_not_override_redirect(app) -> None:
    """Hyprland drops keyboard input for override-redirect windows.

    This is the root cause of the original bug: the overlay looked focused (Tk
    reported .!toplevel) but F3 and Escape were never delivered.

    Note: `wm attributes -topmost`/`-alpha` are deliberately not asserted. Under
    Hyprland/XWayland Tk accepts them and reads them straight back as 0/1.0, so
    they are best-effort only; the window still needs to be a managed toplevel.
    """
    instance, root = app
    instance.enter_f3_mode("pick_color")
    root.update()

    overlay = instance.picker_overlay
    assert overlay is not None, "picker overlay was not created"
    assert not overlay.overrideredirect(), (
        "picker must be a managed toplevel; override-redirect windows receive no keys"
    )
    assert overlay.winfo_ismapped(), "picker overlay is not on screen"

    instance.cancel_f3_mode()
    root.update()


def test_entering_picker_hides_and_cancel_restores(app) -> None:
    instance, root = app
    instance.enter_f3_mode("pick_location")
    root.update()
    assert instance.f3_mode is not None

    instance.cancel_f3_mode()
    root.update()
    assert instance.f3_mode is None
    assert instance.picker_overlay is None
    assert root.state() == "normal", "app was left hidden after cancelling"


def test_capture_restores_the_window(app) -> None:
    """The capture path must always restore, even though it reads the screen."""
    instance, root = app
    instance.enter_f3_mode("pick_location")
    root.update()

    instance.capture_from_hotkey()
    root.update()

    assert instance.f3_mode is None
    assert instance.picker_overlay is None
    assert root.state() == "normal", "app was left hidden after capturing"


def test_cancelling_without_a_picker_is_a_noop(app) -> None:
    instance, root = app
    instance.cancel_f3_mode()
    root.update()
    assert instance.f3_mode is None
    assert root.state() == "normal"


def test_reentering_the_picker_replaces_the_overlay(app) -> None:
    """Entering twice must not leak a second overlay or a second poll loop."""
    instance, root = app
    instance.enter_f3_mode("pick_color")
    root.update()
    first = instance.picker_overlay

    instance.enter_f3_mode("pick_location")
    root.update()
    second = instance.picker_overlay

    assert second is not None
    assert second is not first
    assert instance.f3_mode["action"] == "pick_location"

    instance.cancel_f3_mode()
    root.update()
    assert root.state() == "normal"


def test_picker_tracks_cursor_and_records_a_point_outside_itself(app) -> None:
    """The mouse-only path depends on remembering the last point off the overlay."""
    instance, root = app
    instance.enter_f3_mode("pick_location")
    root.update()
    instance._picker_tick()
    root.update()

    assert "cursor" in instance.f3_mode
    assert instance.f3_mode["last_outside"] is not None

    instance.cancel_f3_mode()
    root.update()


def test_in_window_bindings_exist(app) -> None:
    """F3/Escape must work from the keyboard even without global hotkeys."""
    _instance, root = app
    for sequence in ("<F3>", "<Escape>", "<F2>"):
        assert root.bind(sequence), f"{sequence} is not bound on the main window"


def test_poller_is_cancelled_when_the_picker_closes(app) -> None:
    instance, root = app
    instance.enter_f3_mode("pick_color")
    root.update()
    assert instance.picker_poll_id is not None

    instance.cancel_f3_mode()
    root.update()
    assert instance.picker_poll_id is None, "cursor poll loop was left running"
