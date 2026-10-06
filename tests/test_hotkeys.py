"""Tests for the root-free global hotkey listener.

These never open a real input device: the evdev byte stream is synthesised, so
they run on any machine including headless CI. The parts that genuinely need
/dev/input are checked through the pure helpers instead.
"""

from __future__ import annotations

import struct
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="evdev hotkeys are Linux-only")

from flowchart_automation.wayland import hotkeys  # noqa: E402


def ev(type_: int, code: int, value: int, sec: int = 0, usec: int = 0) -> bytes:
    return hotkeys.EVENT.pack(sec, usec, type_, code, value)


def key_press(code: int) -> bytes:
    return ev(hotkeys.EV_KEY, code, hotkeys.KEY_PRESS)


def test_event_struct_is_24_bytes() -> None:
    """struct input_event is timeval(16) + u16 + u16 + s32 on 64-bit."""
    assert hotkeys.EVENT.size == 24
    assert hotkeys.EVENT.size == struct.calcsize("llHHi")


def test_hotkey_codes_match_input_event_codes() -> None:
    """Values taken from /usr/include/linux/input-event-codes.h."""
    assert hotkeys.KEY_ESC == 1
    assert hotkeys.KEY_F2 == 60
    assert hotkeys.KEY_F3 == 61
    assert hotkeys.KEY_F4 == 62


def test_hotkey_names_cover_the_bindings() -> None:
    assert hotkeys.HOTKEY_NAMES[61] == "f3"
    assert hotkeys.HOTKEY_NAMES[60] == "f2"
    assert hotkeys.HOTKEY_NAMES[62] == "f4"
    assert hotkeys.HOTKEY_NAMES[1] == "escape"


class Recorder:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def __call__(self, name: str) -> None:
        self.keys.append(name)

    def listener(self, **kwargs) -> hotkeys.EvdevHotkeyListener:
        return hotkeys.EvdevHotkeyListener(self, **kwargs)


def test_press_is_reported() -> None:
    rec = Recorder()
    rec.listener()._handle_buffer(0, key_press(hotkeys.KEY_F3))
    assert rec.keys == ["f3"]


def test_multiple_presses_in_one_read() -> None:
    """A single read can carry several events."""
    rec = Recorder()
    data = key_press(hotkeys.KEY_F3) + key_press(hotkeys.KEY_F2) + key_press(hotkeys.KEY_ESC)
    rec.listener()._handle_buffer(0, data)
    assert rec.keys == ["f3", "f2", "escape"]


def test_release_is_not_reported() -> None:
    """Only presses fire; otherwise every hotkey would trigger twice."""
    rec = Recorder()
    rec.listener()._handle_buffer(0, ev(hotkeys.EV_KEY, hotkeys.KEY_F3, hotkeys.KEY_RELEASE))
    assert rec.keys == []


def test_non_key_events_are_ignored() -> None:
    rec = Recorder()
    data = ev(0x02, 0, 1) + ev(0x00, 0, 0)  # EV_REL and EV_SYN
    rec.listener()._handle_buffer(0, data)
    assert rec.keys == []


def test_uninteresting_keys_are_ignored() -> None:
    """A letter must not be mistaken for a hotkey."""
    rec = Recorder()
    rec.listener()._handle_buffer(0, key_press(30))  # KEY_A
    assert rec.keys == []


def test_partial_trailing_event_is_not_misparsed() -> None:
    """A short read must not raise or invent an event."""
    rec = Recorder()
    rec.listener()._handle_buffer(0, key_press(hotkeys.KEY_F3) + b"\x00\x01\x02")
    assert rec.keys == ["f3"]


def test_empty_buffer_is_a_noop() -> None:
    rec = Recorder()
    rec.listener()._handle_buffer(0, b"")
    assert rec.keys == []


# --- the ydotool filter -----------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["ydotoold virtual device", "ydotoold", "Virtual Keyboard", "uinput-keys"],
)
def test_apps_own_virtual_devices_are_ignored(name: str) -> None:
    """Reacting to these would let the app trigger its own hotkeys.

    A "press key" step could inject F3, which would then re-open the picker.
    Verified on the real machine: with the filter off an injected F3 is seen;
    with it on the same F3 is correctly ignored.
    """
    rec = Recorder()
    assert rec.listener()._is_ignored(name) is True


@pytest.mark.parametrize(
    "name",
    ["AT Translated Set 2 keyboard", "Logitech Wireless Mouse MX Master 3", "ThinkPad Extra Buttons"],
)
def test_real_devices_are_not_ignored(name: str) -> None:
    rec = Recorder()
    assert rec.listener()._is_ignored(name) is False


def test_ignore_matching_is_case_insensitive() -> None:
    rec = Recorder()
    assert rec.listener()._is_ignored("YDOToold Virtual Device") is True


def test_custom_ignore_list_replaces_the_default() -> None:
    rec = Recorder()
    listener = rec.listener(ignored_names=["banana"])
    assert listener._is_ignored("ydotoold virtual device") is False
    assert listener._is_ignored("banana keyboard") is True


# --- lifecycle --------------------------------------------------------------


def test_start_returns_false_when_no_keyboard_is_found(monkeypatch) -> None:
    monkeypatch.setattr(hotkeys.glob, "glob", lambda pattern: [])
    rec = Recorder()
    listener = rec.listener()
    assert listener.start() is False
    assert listener.devices == []


def test_stop_is_safe_before_start() -> None:
    rec = Recorder()
    rec.listener().stop()  # must not raise


def test_stop_is_idempotent() -> None:
    rec = Recorder()
    listener = rec.listener()
    listener.stop()
    listener.stop()
    assert listener.devices == []


def test_keyboards_available_returns_a_bool() -> None:
    """Must not raise on a machine with no readable input devices."""
    assert isinstance(hotkeys.keyboards_available(), bool)
