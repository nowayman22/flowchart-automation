"""Tests for the snip / area-selection freeze frame.

The original bug: snip drew a full-screen grey overlay, destroyed it, then took
a second screenshot in the hope the compositor had repainted. Under Hyprland the
destroy had not even reached the X server, so every snip returned the grey
overlay. The overlay was also opaque rather than the intended 30% dim, because
wm attributes are ignored there.

The fix captures the screen once, before any window exists, and crops from that
same frame. The decisive regression test is therefore that exactly one capture
happens: a second one is what raced the compositor.

These need a display, so they skip without one.
"""

from __future__ import annotations

import time
import tkinter as tk

import pytest
from conftest import requires_display
from PIL import Image

pytestmark = requires_display

BOX = (100, 80, 400, 280)  # x1, y1, x2, y2


@pytest.fixture
def snip(app, monkeypatch, tmp_path):
    """Stub the capture and the save dialog, and expose drag helpers."""
    import pyautogui

    instance, root = app
    screen = Image.new("RGB", (root.winfo_screenwidth(), root.winfo_screenheight()))
    # A recognisable pattern so we can prove the crop came from this frame.
    for x in range(0, screen.width, 32):
        for y in range(0, screen.height, 32):
            screen.putpixel((x, y), (255, (x // 32) % 256, (y // 32) % 256))

    calls: list[str] = []

    def fake_screenshot(*args, **kwargs):
        calls.append("capture")
        return screen.copy()

    monkeypatch.setattr(pyautogui, "screenshot", fake_screenshot)

    saved: list[str] = []
    out = tmp_path / "snip.png"
    monkeypatch.setattr(
        "tkinter.filedialog.asksaveasfilename", lambda **kwargs: (saved.append("asked"), str(out))[1]
    )

    instance.add_step("png")
    root.update()
    # conftest already added a colour step, so the PNG step is the last one and
    # is what actually owns the Snip button.
    png_index = len(instance.steps) - 1
    instance.selected_items = [{"type": "step", "index": png_index}]
    return instance, root, screen, calls, saved, out, png_index


def find_overlay(root):
    for widget in root.winfo_children():
        if isinstance(widget, tk.Toplevel):
            canvases = [c for c in widget.winfo_children() if isinstance(c, tk.Canvas)]
            if canvases:
                return widget, canvases[0]
    return None, None


def start_snip(instance, root):
    instance.snip_image_for_step()
    for _ in range(20):
        root.update()
        time.sleep(0.02)
    overlay, canvas = find_overlay(root)
    assert overlay is not None, "the selection overlay did not appear"
    return overlay, canvas


def drag(canvas, box=BOX):
    x1, y1, x2, y2 = box
    canvas.event_generate("<ButtonPress-1>", x=x1, y=y1, rootx=x1, rooty=y1)
    canvas.event_generate("<B1-Motion>", x=x2, y=y2, rootx=x2, rooty=y2)
    canvas.event_generate("<ButtonRelease-1>", x=x2, y=y2, rootx=x2, rooty=y2)


def settle(root, seconds=0.5):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


# --- the regression ---------------------------------------------------------


def test_only_one_capture_happens(snip) -> None:
    """A second capture after the overlay is exactly what raced the compositor."""
    instance, root, _screen, calls, _saved, _out, _idx = snip
    _overlay, canvas = start_snip(instance, root)
    drag(canvas)
    settle(root)

    assert calls == ["capture"], f"expected a single capture, got {len(calls)}"


def test_snip_is_cropped_from_the_frozen_frame(snip) -> None:
    """The saved image must be the real frame, never the selection overlay."""
    instance, root, screen, _calls, saved, out, _idx = snip
    _overlay, canvas = start_snip(instance, root)
    drag(canvas)
    settle(root)

    assert saved, "the save dialog should have been offered"
    image = Image.open(out)
    assert image.size == (BOX[2] - BOX[0], BOX[3] - BOX[1])

    x1, y1, x2, y2 = BOX
    assert image.tobytes() == screen.crop((x1, y1, x2, y2)).tobytes()


def test_the_overlay_does_not_cover_the_frozen_image(snip) -> None:
    """The frame is shown at full brightness, not behind an opaque grey sheet."""
    instance, root, _screen, _calls, _saved, _out, _idx = snip
    _overlay, canvas = start_snip(instance, root)
    images = [i for i in canvas.find_all() if canvas.type(i) == "image"]
    assert images, "the frozen frame should be displayed on the canvas"
    assert canvas.itemcget(images[0], "image"), "the image item has no image bound"


# --- the step path ----------------------------------------------------------


def test_snip_sets_the_step_path(snip) -> None:
    instance, root, _screen, _calls, _saved, out, png_index = snip
    _overlay, canvas = start_snip(instance, root)
    drag(canvas)
    settle(root)
    assert instance.steps[png_index]["path"] == str(out)


def test_snip_restores_the_main_window(snip) -> None:
    instance, root, _screen, _calls, _saved, _out, _idx = snip
    _overlay, canvas = start_snip(instance, root)
    drag(canvas)
    settle(root)
    assert root.state() == "normal"


def test_resnipping_the_same_path_clears_the_template_cache(snip) -> None:
    """Otherwise a re-snip to the same filename would serve the old template."""
    instance, root, _screen, _calls, _saved, out, _idx = snip
    instance.template_cache[f"{out}|Grayscale"] = ("stale", None)

    _overlay, canvas = start_snip(instance, root)
    drag(canvas)
    settle(root)

    assert f"{out}|Grayscale" not in instance.template_cache


# --- cancelling -------------------------------------------------------------


def test_right_click_cancels(snip) -> None:
    """The overlay is override-redirect, so it never gets keyboard focus.

    Right-click is the escape hatch that has to work.
    """
    instance, root, _screen, _calls, saved, _out, _idx = snip
    _overlay, canvas = start_snip(instance, root)
    canvas.event_generate("<Button-3>", x=200, y=200, rootx=200, rooty=200)
    settle(root)

    assert find_overlay(root)[0] is None, "overlay was left on screen"
    assert root.state() == "normal", "app was left hidden"
    assert saved == [], "cancelling must not offer to save"


def test_escape_cancels(snip) -> None:
    instance, root, _screen, _calls, saved, _out, _idx = snip
    overlay, _canvas = start_snip(instance, root)
    overlay.event_generate("<Escape>")
    settle(root)

    assert find_overlay(root)[0] is None
    assert root.state() == "normal"
    assert saved == []


def test_tiny_selection_is_treated_as_a_cancel(snip) -> None:
    instance, root, _screen, _calls, saved, _out, _idx = snip
    _overlay, canvas = start_snip(instance, root)
    drag(canvas, box=(100, 100, 103, 103))
    settle(root)

    assert find_overlay(root)[0] is None
    assert root.state() == "normal"
    assert saved == [], "a 3x3 drag is not a usable selection"


def test_cancel_does_not_touch_the_step_path(snip) -> None:
    instance, root, _screen, _calls, _saved, _out, png_index = snip
    _overlay, canvas = start_snip(instance, root)
    canvas.event_generate("<Button-3>", x=200, y=200, rootx=200, rooty=200)
    settle(root)
    assert instance.steps[png_index]["path"] == ""


# --- the area selector ------------------------------------------------------


def test_area_selection_uses_the_freeze_frame_too(snip) -> None:
    """The global area picker shared the grey overlay, so it was blind."""
    instance, root, _screen, calls, _saved, _out, _idx = snip
    instance.select_area_mode()
    for _ in range(20):
        root.update()
        time.sleep(0.02)

    overlay, canvas = find_overlay(root)
    assert overlay is not None
    drag(canvas, box=(10, 20, 210, 220))
    settle(root)

    assert calls == ["capture"], "the area picker must not take a second capture"
    assert instance.global_settings_ui_vars["area_x1"].get() == "10"
    assert instance.global_settings_ui_vars["area_y1"].get() == "20"
    assert instance.global_settings_ui_vars["area_x2"].get() == "210"
    assert instance.global_settings_ui_vars["area_y2"].get() == "220"


def test_area_selection_for_a_step(snip) -> None:
    instance, root, _screen, _calls, _saved, _out, _idx = snip
    instance.select_area_mode(step_index=0)
    for _ in range(20):
        root.update()
        time.sleep(0.02)

    _overlay, canvas = find_overlay(root)
    drag(canvas, box=(30, 40, 130, 140))
    settle(root)

    assert instance.steps[0]["area"] == (30, 40, 130, 140)
