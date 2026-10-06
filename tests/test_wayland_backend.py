"""Tests for the Wayland backend (grim capture + ydotool input).

Nothing here needs a compositor, grim or ydotool: subprocess calls are
monkeypatched and a Monitor is injected directly, so the suite runs anywhere.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from flowchart_automation.wayland import capture as capture_mod
from flowchart_automation.wayland import compositor as compositor_mod
from flowchart_automation.wayland import input as input_mod
from flowchart_automation.wayland.capture import CaptureError, GrimCapture
from flowchart_automation.wayland.compositor import Monitor
from flowchart_automation.wayland.input import InputError, YdotoolInput
from flowchart_automation.wayland.keycodes import (
    KEYCODES,
    SHIFTED_CHARS,
    keycode_for,
    shift_needed,
)
from flowchart_automation.wayland.shim import PyAutoGUIShim, is_wayland_session

MONITOR = Monitor(name="eDP-1", width=2560, height=1600, scale=1.0, x=0, y=0)


def png_bytes(width: int = 8, height: int = 8, colour=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


class Completed:
    def __init__(self, stdout: bytes = b"", returncode: int = 0, stderr: bytes = b"") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


# --- keycodes ---------------------------------------------------------------


def test_keycodes_match_linux_input_event_codes() -> None:
    """Spot-check values against /usr/include/linux/input-event-codes.h."""
    assert KEYCODES["a"] == 30
    assert KEYCODES["z"] == 44
    assert KEYCODES["1"] == 2
    assert KEYCODES["0"] == 11
    assert KEYCODES["enter"] == 28
    assert KEYCODES["space"] == 57
    assert KEYCODES["esc"] == 1
    assert KEYCODES["tab"] == 15
    assert KEYCODES["backspace"] == 14
    assert KEYCODES["delete"] == 111
    assert KEYCODES["f1"] == 59
    assert KEYCODES["f10"] == 68
    assert KEYCODES["f11"] == 87
    assert KEYCODES["f12"] == 88
    assert KEYCODES["up"] == 103
    assert KEYCODES["down"] == 108
    assert KEYCODES["left"] == 105
    assert KEYCODES["right"] == 106
    # pyautogui's canonical spelling puts the side last.
    assert KEYCODES["ctrlleft"] == 29
    assert KEYCODES["shiftleft"] == 42
    assert KEYCODES["altleft"] == 56


def test_modifier_spelling_aliases() -> None:
    """Both spellings are accepted because the key box is free text."""
    assert keycode_for("ctrlleft") == keycode_for("leftctrl") == 29
    assert keycode_for("shiftleft") == keycode_for("leftshift") == 42
    assert keycode_for("altright") == keycode_for("rightalt") == 100


@pytest.mark.parametrize(
    ("alias_a", "alias_b"),
    [("esc", "escape"), ("enter", "return"), ("space", "spacebar"), ("pageup", "pgup"), ("delete", "del")],
)
def test_key_aliases_share_a_code(alias_a: str, alias_b: str) -> None:
    assert keycode_for(alias_a) == keycode_for(alias_b)


def test_keycode_lookup_is_case_insensitive_and_trims() -> None:
    assert keycode_for("ENTER") == 28
    assert keycode_for("  Enter  ") == 28


def test_unknown_key_raises_a_helpful_error() -> None:
    with pytest.raises(ValueError, match="Unsupported key"):
        keycode_for("banana")


def test_empty_key_raises() -> None:
    with pytest.raises(ValueError, match="No key name"):
        keycode_for("")


def test_shifted_characters_are_detected() -> None:
    assert shift_needed("!") is True
    assert shift_needed(":") is True
    assert shift_needed("a") is False
    assert shift_needed("enter") is False


def test_shifted_chars_map_to_real_keycodes() -> None:
    for char, base in SHIFTED_CHARS.items():
        assert base in KEYCODES, f"{char!r} maps to unknown key {base!r}"


# --- capture: geometry ------------------------------------------------------


def test_monitor_logical_size_accounts_for_scale() -> None:
    hidpi = Monitor(name="eDP-1", width=2560, height=1600, scale=2.0, x=0, y=0)
    assert hidpi.logical_width == 1280
    assert hidpi.logical_height == 800


def test_geometry_is_identity_at_scale_one() -> None:
    capture = GrimCapture(MONITOR)
    assert capture._to_geometry((10, 20, 100, 50)) == "10,20 100x50"


def test_geometry_scales_to_physical_pixels() -> None:
    hidpi = Monitor(name="eDP-1", width=2560, height=1600, scale=2.0, x=0, y=0)
    capture = GrimCapture(hidpi)
    assert capture._to_geometry((10, 20, 100, 50)) == "20,40 200x100"


def test_geometry_clamps_region_to_the_monitor() -> None:
    capture = GrimCapture(MONITOR)
    # A region dragged past the right/bottom edge must not ask grim for pixels
    # that do not exist.
    assert capture._to_geometry((2500, 1550, 500, 500)) == "2500,1550 60x50"


def test_geometry_clamps_negative_origin() -> None:
    capture = GrimCapture(MONITOR)
    assert capture._to_geometry((-50, -50, 100, 100)) == "0,0 50x50"


def test_geometry_never_produces_zero_size() -> None:
    capture = GrimCapture(MONITOR)
    assert capture._to_geometry((0, 0, 0, 0)) == "0,0 1x1"


def test_size_returns_logical_dimensions() -> None:
    assert GrimCapture(MONITOR).size() == (2560, 1600)


# --- capture: grim invocation ----------------------------------------------


def test_screenshot_region_uses_grim_geometry(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return png_bytes(8, 8)

    monkeypatch.setattr(capture_mod, "_run", fake_run)
    image = GrimCapture(MONITOR).screenshot((100, 200, 8, 8))

    assert image.size == (8, 8)
    assert seen[0] == ["grim", "-g", "100,200 8x8", "-t", "ppm", "-"]


def test_full_screenshot_omits_geometry(monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(capture_mod, "_run", lambda cmd, **kw: (seen.append(cmd), png_bytes())[1])

    GrimCapture(MONITOR).screenshot()
    assert "-g" not in seen[0]


def test_screenshot_returns_rgb_image(monkeypatch) -> None:
    monkeypatch.setattr(capture_mod, "_run", lambda cmd, **kw: png_bytes(4, 4, (1, 2, 3)))
    image = GrimCapture(MONITOR).screenshot((0, 0, 4, 4))
    assert image.mode == "RGB"
    assert image.getpixel((0, 0)) == (1, 2, 3)


def test_pixel_reads_a_single_pixel(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return png_bytes(1, 1, (40, 50, 60))

    monkeypatch.setattr(capture_mod, "_run", fake_run)
    assert GrimCapture(MONITOR).pixel(7, 9) == (40, 50, 60)
    assert seen[0][2] == "7,9 1x1"


def test_missing_grim_raises_capture_error(monkeypatch) -> None:
    def boom(cmd, **kwargs):
        raise FileNotFoundError("grim")

    monkeypatch.setattr(compositor_mod.subprocess, "run", boom)
    with pytest.raises(CaptureError, match="not installed"):
        compositor_mod._run(["grim"])


def test_nonzero_exit_raises_with_stderr(monkeypatch) -> None:
    monkeypatch.setattr(
        compositor_mod.subprocess,
        "run",
        lambda cmd, **kw: Completed(returncode=1, stderr=b"compositor does not support"),
    )
    with pytest.raises(CaptureError, match="compositor does not support"):
        compositor_mod._run(["grim"])


def test_empty_image_data_raises(monkeypatch) -> None:
    monkeypatch.setattr(capture_mod, "_run", lambda cmd, **kw: b"")
    with pytest.raises(CaptureError, match="no image data"):
        GrimCapture(MONITOR).screenshot((0, 0, 4, 4))


def test_cursor_position_parses_hyprctl_output(monkeypatch) -> None:
    monkeypatch.setattr(compositor_mod, "_run", lambda cmd, **kw: b"684, 987\n")
    assert compositor_mod.query_cursor_position() == (684, 987)


def test_cursor_position_rejects_garbage(monkeypatch) -> None:
    monkeypatch.setattr(compositor_mod, "_run", lambda cmd, **kw: b"not a position")
    with pytest.raises(CaptureError, match="Unexpected cursorpos"):
        compositor_mod.query_cursor_position()


def test_query_monitors_orders_by_x(monkeypatch) -> None:
    payload = (
        b'[{"name":"DP-2","width":1920,"height":1080,"scale":1.0,"x":2560,"y":0},'
        b'{"name":"eDP-1","width":2560,"height":1600,"scale":1.0,"x":0,"y":0}]'
    )
    monkeypatch.setattr(compositor_mod, "_run", lambda cmd, **kw: payload)
    monitors = compositor_mod.query_monitors()
    assert [m.name for m in monitors] == ["eDP-1", "DP-2"]


# --- compositor: pointer positioning ----------------------------------------


def test_move_cursor_uses_the_movecursor_dispatcher(monkeypatch) -> None:
    """Positioning must not go through ydotool: its absolute mode mis-maps."""
    seen: list[list[str]] = []
    monkeypatch.setattr(compositor_mod, "_run", lambda cmd, **kw: (seen.append(cmd), b"ok")[1])

    compositor_mod.move_cursor(1520, 816)
    assert seen[0] == ["hyprctl", "dispatch", "movecursor", "1520", "816"]


def test_move_cursor_truncates_floats(monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(compositor_mod, "_run", lambda cmd, **kw: (seen.append(cmd), b"ok")[1])

    compositor_mod.move_cursor(10.7, 20.2)
    assert seen[0][-2:] == ["10", "20"]


# --- input ------------------------------------------------------------------


@pytest.fixture
def ydotool_ready(monkeypatch):
    """Make the input backend look installed and running."""
    monkeypatch.setattr(input_mod, "unavailable_reason", lambda: None)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr(input_mod.subprocess, "run", fake_run)
    return calls


def _args(calls: list[list[str]]) -> list[list[str]]:
    return [c[1:] for c in calls]


def test_button_encoding_matches_ydotool(ydotool_ready) -> None:
    """ydotool: 0x40 press, 0x80 release, 0xC0 click, low bits = button."""
    YdotoolInput().click("left")
    YdotoolInput().click("right")
    YdotoolInput().click("middle")
    assert _args(ydotool_ready) == [["click", "0xc0"], ["click", "0xc1"], ["click", "0xc2"]]


def test_click_with_hold_presses_then_releases(ydotool_ready) -> None:
    YdotoolInput().click("left", hold=0.01)
    assert _args(ydotool_ready) == [["click", "0x40"], ["click", "0x80"]]


def test_repeated_clicks(ydotool_ready) -> None:
    YdotoolInput().click("left", clicks=3)
    assert _args(ydotool_ready) == [["click", "0xc0"]] * 3


def test_unknown_button_raises(ydotool_ready) -> None:
    with pytest.raises(InputError, match="Unknown mouse button"):
        YdotoolInput().click("pinky")


@pytest.fixture
def cursor_moves(monkeypatch):
    """Capture compositor cursor warps instead of running hyprctl."""
    moves: list[tuple[int, int]] = []
    monkeypatch.setattr(input_mod, "move_cursor", lambda x, y: moves.append((int(x), int(y))))
    return moves


def test_move_to_uses_the_compositor_not_ydotool(ydotool_ready, cursor_moves) -> None:
    """ydotool's absolute mode mis-maps onto the output, so hyprctl positions."""
    YdotoolInput().move_to(100, 200)
    assert cursor_moves == [(100, 200)]
    assert ydotool_ready == [], "positioning must not shell out to ydotool"


def test_move_with_duration_interpolates(ydotool_ready, cursor_moves, monkeypatch) -> None:
    backend = YdotoolInput()
    monkeypatch.setattr(backend, "position", lambda: (0, 0))
    monkeypatch.setattr(input_mod.time, "sleep", lambda _s: None)

    backend.move_to(100, 100, duration=0.2, tween=lambda n: n)

    assert len(cursor_moves) > 1, "a timed move should produce intermediate points"
    xs = [x for x, _ in cursor_moves]
    assert xs == sorted(xs), "movement should be progressive"
    assert 0 < xs[0] < 100
    assert cursor_moves[-1] == (100, 100)


def test_move_interpolation_is_capped(ydotool_ready, cursor_moves, monkeypatch) -> None:
    backend = YdotoolInput()
    monkeypatch.setattr(backend, "position", lambda: (0, 0))
    monkeypatch.setattr(input_mod.time, "sleep", lambda _s: None)

    backend.move_to(100, 100, duration=60.0, tween=lambda n: n)
    assert len(cursor_moves) <= 40


def test_move_falls_back_when_position_unavailable(cursor_moves, monkeypatch) -> None:
    backend = YdotoolInput()

    def fail():
        raise InputError("no capture")

    monkeypatch.setattr(backend, "position", fail)
    backend.move_to(5, 6, duration=0.5)
    assert cursor_moves == [(5, 6)]


def test_move_rel_resolves_through_absolute_position(cursor_moves, monkeypatch) -> None:
    backend = YdotoolInput()
    monkeypatch.setattr(backend, "position", lambda: (100, 100))
    backend.move_rel(10, -20)
    assert cursor_moves == [(110, 80)]


def test_move_does_not_need_ydotool(monkeypatch, cursor_moves) -> None:
    """Positioning works without ydotool; only button and key events need it."""
    monkeypatch.setattr(input_mod, "unavailable_reason", lambda: "ydotool is not installed")
    YdotoolInput().move_to(50, 60)
    assert cursor_moves == [(50, 60)]


def test_click_errors_when_ydotool_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(input_mod, "unavailable_reason", lambda: "ydotool is not installed")
    with pytest.raises(InputError, match="not installed"):
        YdotoolInput().click("left")


def test_press_sends_keycode_pairs(ydotool_ready) -> None:
    YdotoolInput().press("enter")
    assert _args(ydotool_ready) == [["key", "28:1", "28:0"]]


def test_press_shifted_char_holds_shift(ydotool_ready) -> None:
    YdotoolInput().press("!")
    assert _args(ydotool_ready) == [["key", "42:1", "2:1", "2:0", "42:0"]]


def test_hotkey_presses_then_releases_in_reverse(ydotool_ready) -> None:
    YdotoolInput().hotkey("ctrl", "c")
    assert _args(ydotool_ready) == [["key", "29:1", "46:1", "46:0", "29:0"]]


def test_key_down_and_up_are_separate_events(ydotool_ready) -> None:
    backend = YdotoolInput()
    backend.key_down("shift")
    backend.key_up("shift")
    assert _args(ydotool_ready) == [["key", "42:1"], ["key", "42:0"]]


def test_write_uses_ydotool_type(ydotool_ready) -> None:
    YdotoolInput().write("1234")
    assert _args(ydotool_ready) == [["type", "--", "1234"]]


def test_write_empty_string_is_a_noop(ydotool_ready) -> None:
    YdotoolInput().write("")
    assert ydotool_ready == []


def test_scroll_fails_loudly(ydotool_ready) -> None:
    """ydotool has no wheel command; a wrong button event would be worse."""
    with pytest.raises(InputError, match="not supported"):
        YdotoolInput().scroll(3)


def test_missing_ydotool_reports_actionable_reason(monkeypatch) -> None:
    monkeypatch.setattr(input_mod.shutil, "which", lambda _name: None)
    reason = input_mod.unavailable_reason()
    assert reason is not None
    assert "pacman -S ydotool" in reason


def test_missing_daemon_reports_actionable_reason(monkeypatch) -> None:
    monkeypatch.setattr(input_mod.shutil, "which", lambda _name: "/usr/bin/ydotool")
    monkeypatch.setattr(input_mod, "daemon_running", lambda: False)
    reason = input_mod.unavailable_reason()
    assert reason is not None
    assert "ydotoold" in reason


def test_ready_backend_has_no_reason(monkeypatch) -> None:
    monkeypatch.setattr(input_mod.shutil, "which", lambda _name: "/usr/bin/ydotool")
    monkeypatch.setattr(input_mod, "daemon_running", lambda: True)
    assert input_mod.unavailable_reason() is None


def test_key_and_button_events_error_before_spawning_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(input_mod, "unavailable_reason", lambda: "ydotool is not installed")
    with pytest.raises(InputError, match="not installed"):
        YdotoolInput().press("enter")
    with pytest.raises(InputError, match="not installed"):
        YdotoolInput().write("hello")


def test_socket_path_follows_xdg_runtime_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("YDOTOOL_SOCKET", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert input_mod.ydotool_socket() == tmp_path / ".ydotool_socket"


def test_socket_path_honours_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("YDOTOOL_SOCKET", str(tmp_path / "custom.sock"))
    assert input_mod.ydotool_socket() == tmp_path / "custom.sock"


# --- shim -------------------------------------------------------------------


def test_ease_out_quad_matches_pytweening() -> None:
    """The app passes pyautogui.easeOutQuad straight into moveTo."""
    pytweening = pytest.importorskip("pytweening")
    shim = PyAutoGUIShim()
    for step in range(11):
        n = step / 10
        assert shim.easeOutQuad(n) == pytest.approx(pytweening.easeOutQuad(n))


def test_shim_screenshot_returns_pil_image(monkeypatch) -> None:
    shim = PyAutoGUIShim()
    monkeypatch.setattr(shim._capture, "screenshot", lambda region=None: Image.new("RGB", (5, 5)))
    image = shim.screenshot(region=(0, 0, 5, 5))
    assert isinstance(image, Image.Image)


def test_shim_click_moves_then_clicks(monkeypatch) -> None:
    shim = PyAutoGUIShim()
    events: list[str] = []
    monkeypatch.setattr(shim._input, "move_to", lambda *a, **k: events.append("move"))
    monkeypatch.setattr(shim._input, "click", lambda *a, **k: events.append("click"))

    shim.click(10, 20)
    assert events == ["move", "click"]


def test_shim_click_without_coords_does_not_move(monkeypatch) -> None:
    shim = PyAutoGUIShim()
    events: list[str] = []
    monkeypatch.setattr(shim._input, "move_to", lambda *a, **k: events.append("move"))
    monkeypatch.setattr(shim._input, "click", lambda *a, **k: events.append("click"))

    shim.click()
    assert events == ["click"]


def test_shim_right_click_uses_right_button(monkeypatch) -> None:
    shim = PyAutoGUIShim()
    captured = {}
    monkeypatch.setattr(shim._input, "click", lambda button, **k: captured.update(button=button))
    shim.rightClick()
    assert captured["button"] == "right"


def test_shim_press_accepts_a_list(monkeypatch) -> None:
    shim = PyAutoGUIShim()
    pressed: list[str] = []
    monkeypatch.setattr(shim._input, "press", lambda key, **k: pressed.append(key))
    shim.press(["a", "b"])
    assert pressed == ["a", "b"]


def test_shim_move_to_defaults_to_ease_out_quad(monkeypatch) -> None:
    shim = PyAutoGUIShim()
    captured = {}
    monkeypatch.setattr(
        shim._input, "move_to", lambda x, y, duration=0.0, tween=None: captured.update(tween=tween)
    )
    shim.moveTo(1, 2, duration=0.1)
    assert captured["tween"] is shim.easeOutQuad


def test_shim_is_a_module_type() -> None:
    """The legacy app does `import pyautogui`, so this must look like a module."""
    import types

    assert isinstance(PyAutoGUIShim(), types.ModuleType)


def test_is_wayland_session_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    assert is_wayland_session() is True

    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert is_wayland_session() is True

    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert is_wayland_session() is False


# --- fast capture path ------------------------------------------------------
#
# Capture dominates the scan loop (colour detection is ~5 ms against ~350 ms of
# PNG work before this), so the uncompressed path is what makes a moving target
# trackable. It must be exactly equivalent, not merely close.


def ppm_bytes(width: int = 4, height: int = 3, colour=(10, 20, 30)) -> bytes:
    header = f"P6\n{width} {height}\n255\n".encode()
    return header + bytes(colour) * (width * height)


def test_parse_ppm_round_trips_pixels() -> None:
    image = capture_mod.parse_ppm(ppm_bytes(4, 3, (10, 20, 30)))
    assert image.shape == (3, 4, 3)
    assert image.dtype == np.uint8
    assert tuple(image[1, 2]) == (10, 20, 30)


def test_parse_ppm_matches_pil_on_the_same_bytes() -> None:
    """Must be pixel-identical to the decoder it replaces."""
    data = ppm_bytes(8, 5, (200, 100, 50))
    assert np.array_equal(capture_mod.parse_ppm(data), np.array(Image.open(io.BytesIO(data)).convert("RGB")))


def test_parse_ppm_handles_comment_lines() -> None:
    data = b"P6\n# grim was here\n2 2\n255\n" + bytes([1, 2, 3]) * 4
    assert capture_mod.parse_ppm(data).shape == (2, 2, 3)


def test_parse_ppm_tolerates_extra_whitespace_between_fields() -> None:
    data = b"P6\n\n  2   2\n255\n" + bytes([9, 9, 9]) * 4
    assert tuple(capture_mod.parse_ppm(data)[0, 0]) == (9, 9, 9)


def test_parse_ppm_consumes_exactly_one_whitespace_byte() -> None:
    """Per the spec only one separates the header from the raster.

    Anything beyond it is image data, so skipping greedily would eat the first
    pixel. grim writes exactly one newline, and this pins that assumption.
    """
    data = b"P6\n2 2\n255\n" + bytes([1, 2, 3]) * 4
    image = capture_mod.parse_ppm(data)
    assert tuple(image[0, 0]) == (1, 2, 3)


def test_parse_ppm_keeps_leading_whitespace_pixels() -> None:
    """A first pixel of 0x20 (space) or 0x0A must survive, not be skipped."""
    data = b"P6\n2 2\n255\n" + bytes([0x20, 0x0A, 0x09]) * 4
    assert tuple(capture_mod.parse_ppm(data)[0, 0]) == (0x20, 0x0A, 0x09)


def test_parse_ppm_rejects_non_ppm() -> None:
    with pytest.raises(CaptureError, match="P6 PPM"):
        capture_mod.parse_ppm(b"\x89PNG\r\n\x1a\n")


def test_parse_ppm_rejects_truncated_payload() -> None:
    data = b"P6\n4 4\n255\n" + bytes(10)
    with pytest.raises(CaptureError, match="payload"):
        capture_mod.parse_ppm(data)


def test_parse_ppm_rejects_truncated_header() -> None:
    with pytest.raises(CaptureError, match="truncated"):
        capture_mod.parse_ppm(b"P6\n4")


def test_parse_ppm_rejects_16_bit() -> None:
    with pytest.raises(CaptureError, match="maxval"):
        capture_mod.parse_ppm(b"P6\n2 2\n65535\n" + bytes(8))


def test_capture_uses_ppm_and_skips_png(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return ppm_bytes(4, 3)

    monkeypatch.setattr(capture_mod, "_run", fake_run)
    capture_mod.GrimCapture(MONITOR).screenshot_array((0, 0, 4, 3))
    assert seen and seen[0][2] == "0,0 4x3"
    assert "ppm" in seen[0]


def test_capture_falls_back_to_png_once(monkeypatch) -> None:
    """A grim without PPM support costs one failed attempt, not one per frame."""
    calls: list[str] = []

    def fake_run(cmd, **kw):
        calls.append(cmd[-2])
        if "ppm" in cmd:
            raise CaptureError("unsupported")
        return png_bytes(4, 3)

    monkeypatch.setattr(capture_mod, "_run", fake_run)
    capture = capture_mod.GrimCapture(MONITOR)
    first = capture.screenshot_array((0, 0, 4, 3))
    second = capture.screenshot_array((0, 0, 4, 3))

    assert first.shape == second.shape == (3, 4, 3)
    assert calls.count("ppm") == 1, "should stop retrying PPM after it fails"


def test_shim_exposes_screenshot_array(monkeypatch) -> None:
    """Regression: the app feature-detects this and silently falls back without it."""
    shim = PyAutoGUIShim()
    assert hasattr(shim, "screenshot_array")

    sentinel = np.zeros((2, 2, 3), np.uint8)
    monkeypatch.setattr(shim._capture, "screenshot_array", lambda region=None: sentinel)
    assert shim.screenshot_array((0, 0, 2, 2)) is sentinel


def test_shim_screenshot_still_returns_pil(monkeypatch) -> None:
    """Template capture and the F3 picker still need a PIL image."""
    shim = PyAutoGUIShim()
    monkeypatch.setattr(shim._capture, "screenshot", lambda region=None: Image.new("RGB", (3, 3)))
    assert isinstance(shim.screenshot((0, 0, 3, 3)), Image.Image)
