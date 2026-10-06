"""Global hotkeys on Linux without root, by reading /dev/input directly.

The `keyboard` library registers global hotkeys by reading ``/dev/input/event*``,
which needs nothing more than membership of the ``input`` group, but it refuses
to run unless euid is 0. This listener does the same job without the root check,
so F2/F3/F4 keep working while another window has focus.

It is a *passive* listener: keys are never grabbed, so the focused application
still receives them. That matches how the app behaved on Windows.

The evdev wire format is ``struct input_event``::

    struct input_event {
        struct timeval time;   // 8 + 8 bytes on 64-bit
        __u16 type;
        __u16 code;
        __s32 value;
    };

so ``"llHHi"`` is 24 bytes with no padding. ``type == EV_KEY`` and
``value == 1`` is a key press; the keycodes are the same Linux
input-event-codes used by ``keycodes.py``.
"""

from __future__ import annotations

import contextlib
import fcntl
import glob
import os
import select
import struct
import threading
from collections.abc import Callable, Iterable

EVENT = struct.Struct("llHHi")
EVENT_SIZE = EVENT.size

EV_KEY = 0x01
KEY_PRESS = 1
KEY_RELEASE = 0

# Linux input-event-codes for the keys the app binds.
KEY_ESC = 1
KEY_F2 = 60
KEY_F3 = 61
KEY_F4 = 62

HOTKEY_NAMES = {
    KEY_ESC: "escape",
    KEY_F2: "f2",
    KEY_F3: "f3",
    KEY_F4: "f4",
}

# Devices the listener must never read: ydotoold's virtual device is the app's
# own output, so reacting to it would let a "press F3" step trigger the picker.
DEFAULT_IGNORED_NAMES = ("ydotoold", "virtual", "uinput")

_IOC_READ = 2


def _ioc(direction: int, type_char: str, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(type_char) << 8) | nr


def _eviocgname(length: int = 256) -> int:
    return _ioc(_IOC_READ, "E", 0x06, length)


def _eviocgbit(ev: int, length: int = 96) -> int:
    return _ioc(_IOC_READ, "E", 0x20 + ev, length)


def device_name(fd: int) -> str:
    """Return the human-readable name of an open event device."""
    try:
        raw = fcntl.ioctl(fd, _eviocgname(), b"\0" * 256)
    except OSError:
        return ""
    return raw.split(b"\0", 1)[0].decode(errors="replace")


def has_key(fd: int, keycode: int) -> bool:
    """True if the device reports the given key, i.e. it is a keyboard.

    Uses EVIOCGBIT so trackpads, lid switches and microphones are skipped
    instead of being read every cycle for keys they cannot produce.
    """
    try:
        bits = fcntl.ioctl(fd, _eviocgbit(EV_KEY), b"\0" * 96)
    except OSError:
        # Unknown capability: better to listen than to silently miss hotkeys.
        return True
    byte_index, bit_index = divmod(keycode, 8)
    if byte_index >= len(bits):
        return False
    return bool(bits[byte_index] & (1 << bit_index))


class EvdevHotkeyListener:
    """Watches every keyboard for F2/F3/F4/Escape and reports presses.

    ``on_key`` is called from the listener thread, so a Tk caller must marshal
    back onto the UI thread (see the app's ``root.after`` wrapper).
    """

    def __init__(
        self,
        on_key: Callable[[str], None],
        ignored_names: Iterable[str] = DEFAULT_IGNORED_NAMES,
        rescan_interval: float = 5.0,
    ) -> None:
        self._on_key = on_key
        self._ignored = tuple(n.lower() for n in ignored_names)
        self._rescan_interval = rescan_interval
        self._fds: dict[int, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.errors: list[str] = []

    # --- device management -------------------------------------------------

    def _is_ignored(self, name: str) -> bool:
        lowered = name.lower()
        return any(marker in lowered for marker in self._ignored)

    def _open_devices(self) -> None:
        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            name = device_name(fd)
            if self._is_ignored(name) or not has_key(fd, KEY_F3):
                os.close(fd)
                continue
            if fd not in self._fds:
                self._fds[fd] = name or path

    def _close_all(self) -> None:
        for fd in list(self._fds):
            with contextlib.suppress(OSError):
                os.close(fd)
        self._fds.clear()

    def _drop(self, fd: int) -> None:
        self._fds.pop(fd, None)
        with contextlib.suppress(OSError):
            os.close(fd)

    @property
    def devices(self) -> list[str]:
        with self._lock:
            return list(self._fds.values())

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Begin listening. Returns False if no usable keyboard was found."""
        self._open_devices()
        if not self._fds:
            self._close_all()
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="evdev-hotkeys", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self._close_all()

    # --- main loop ---------------------------------------------------------

    def _handle_buffer(self, fd: int, data: bytes) -> None:
        for offset in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
            _sec, _usec, ev_type, code, value = EVENT.unpack_from(data, offset)
            if ev_type != EV_KEY or value != KEY_PRESS:
                continue
            name = HOTKEY_NAMES.get(code)
            if name is not None:
                self._on_key(name)

    def _run(self) -> None:
        import time

        next_scan = time.monotonic() + self._rescan_interval
        while not self._stop.is_set():
            with self._lock:
                fds = list(self._fds)
            if not fds:
                if not self._wait(0.5):
                    return
                continue

            try:
                readable, _, _ = select.select(fds, [], [], 0.25)
            except (OSError, ValueError):
                # A descriptor went away underneath us; rescan.
                for fd in fds:
                    self._drop(fd)
                continue

            for fd in readable:
                try:
                    data = os.read(fd, EVENT_SIZE * 64)
                except BlockingIOError:
                    continue
                except OSError:
                    self._drop(fd)
                    continue
                if not data:
                    self._drop(fd)  # device unplugged
                    continue
                self._handle_buffer(fd, data)

            if time.monotonic() >= next_scan:
                next_scan = time.monotonic() + self._rescan_interval
                self._open_devices()

    def _wait(self, seconds: float) -> bool:
        """Sleep, returning False if we were asked to stop."""
        return not self._stop.wait(seconds)


def keyboards_available() -> bool:
    """True if at least one readable keyboard device exists."""
    for path in glob.glob("/dev/input/event*"):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            if not device_name(fd) or has_key(fd, KEY_F3):
                return True
        finally:
            os.close(fd)
    return False
