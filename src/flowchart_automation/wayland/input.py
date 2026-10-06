"""Mouse and keyboard injection on Wayland via ydotool.

Wayland deliberately blocks one client from injecting input into another, so
``pyautogui`` (which speaks X11) cannot drive native Wayland windows at all.
ydotool goes below the compositor and emulates a real input device through the
kernel's uinput interface, which is why it works everywhere.

This means ydotool is a hard requirement for the clicking and typing steps:

    sudo pacman -S ydotool
    systemctl --user enable --now ydotool

``ydotoold`` must be running; since ydotool v1.0 the client talks to that daemon
over a unix socket and fails without it.

Button encoding: ydotool takes a single byte where 0x40 is "press", 0x80 is
"release", 0xC0 is both, and the low bits select the button (0 left, 1 right,
2 middle). So 0xC0 is a left click and 0xC1 a right click.

Pointer *positioning* is the one thing ydotool is not used for: its absolute mode
does not map onto screen pixels reliably. The compositor moves the cursor
instead, and ydotool delivers the button and key events at wherever it landed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .compositor import move_cursor, query_cursor_position
from .keycodes import KEY_LEFTSHIFT, keycode_for, shift_needed

YDOTOOL = "ydotool"

BUTTONS = {"left": 0, "right": 1, "middle": 2, "primary": 0, "secondary": 1}

_PRESS = 0x40
_RELEASE = 0x80
_CLICK = 0xC0

# A virtual device cannot move instantaneously; pacing the interpolation keeps
# the cursor motion smooth and gives the compositor time to process it.
_DEFAULT_STEPS_PER_SECOND = 60
_MAX_STEPS = 40


class InputError(RuntimeError):
    """Raised when an input event cannot be delivered."""


def ydotool_available() -> bool:
    return shutil.which(YDOTOOL) is not None


def ydotool_socket() -> Path:
    """The socket ydotoold is expected to be listening on."""
    override = os.environ.get("YDOTOOL_SOCKET")
    if override:
        return Path(override)
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return Path(runtime_dir) / ".ydotool_socket"


def daemon_running() -> bool:
    return ydotool_socket().exists()


def unavailable_reason() -> str | None:
    """Return why input injection would fail, or None if it should work."""
    if not ydotool_available():
        return (
            "ydotool is not installed. Wayland blocks X11-style input injection, "
            "so clicking and typing need it. Install with: sudo pacman -S ydotool"
        )
    if not daemon_running():
        return (
            f"the ydotoold daemon is not running (no socket at {ydotool_socket()}). "
            "Start it with: systemctl --user enable --now ydotool "
            "(the Arch package names the user unit ydotool.service)"
        )
    return None


class YdotoolInput:
    """Mouse and keyboard output through the ydotool client.

    Pointer position is read and set through the compositor, so this needs no
    capture backend and works even when ydotool is missing.
    """

    # --- low level ---------------------------------------------------------

    def _run(self, args: list[str], *, timeout: float = 10.0) -> None:
        reason = unavailable_reason()
        if reason is not None:
            raise InputError(reason)
        try:
            proc = subprocess.run([YDOTOOL, *args], capture_output=True, timeout=timeout)
        except FileNotFoundError as exc:
            raise InputError("ydotool is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise InputError(f"ydotool {' '.join(args)} timed out") from exc
        if proc.returncode != 0:
            detail = proc.stderr.decode(errors="replace").strip()
            raise InputError(f"ydotool {' '.join(args)} failed: {detail}")

    def _mouse_move(self, x: int, y: int) -> None:
        """Position the pointer via the compositor, not ydotool.

        ydotool's absolute mode maps its own device range onto the output and
        lands in the wrong place (see compositor.move_cursor). hyprctl is exact.
        """
        move_cursor(x, y)

    def _button(self, button: str, action: int) -> None:
        index = BUTTONS.get(button)
        if index is None:
            raise InputError(f"Unknown mouse button {button!r}")
        self._run(["click", hex(action | index)])

    # --- pointer -----------------------------------------------------------

    def position(self) -> tuple[int, int]:
        return query_cursor_position()

    def move_to(
        self,
        x: int,
        y: int,
        duration: float = 0.0,
        tween=None,
    ) -> None:
        """Move the pointer, optionally easing over *duration* seconds."""
        x, y = int(x), int(y)
        if duration is None or duration <= 0:
            self._mouse_move(x, y)
            return

        try:
            start_x, start_y = self.position()
        except Exception:
            self._mouse_move(x, y)
            return

        steps = int(duration * _DEFAULT_STEPS_PER_SECOND)
        steps = max(1, min(steps, _MAX_STEPS))
        sleep_for = duration / steps

        for step in range(1, steps + 1):
            progress = step / steps
            eased = tween(progress) if tween is not None else progress
            self._mouse_move(
                round(start_x + (x - start_x) * eased),
                round(start_y + (y - start_y) * eased),
            )
            if step < steps:
                time.sleep(sleep_for)

    def move_rel(self, dx: int, dy: int) -> None:
        """Move by an offset, resolved through the exact absolute path.

        ydotool's relative mode would avoid the absolute-range problem, but
        composing it with hyprctl's reading keeps every move in one coordinate
        space instead of mixing two.
        """
        current_x, current_y = self.position()
        self._mouse_move(current_x + int(dx), current_y + int(dy))

    def click(
        self,
        button: str = "left",
        *,
        hold: float = 0.0,
        clicks: int = 1,
        interval: float = 0.0,
    ) -> None:
        """Click *button*; *hold* is how long the button stays down."""
        for index in range(max(1, clicks)):
            if hold and hold > 0:
                self._button(button, _PRESS)
                time.sleep(hold)
                self._button(button, _RELEASE)
            else:
                self._button(button, _CLICK)
            if interval > 0 and index < clicks - 1:
                time.sleep(interval)

    def mouse_down(self, button: str = "left") -> None:
        self._button(button, _PRESS)

    def mouse_up(self, button: str = "left") -> None:
        self._button(button, _RELEASE)

    # --- keyboard ----------------------------------------------------------

    def press(self, key: str, presses: int = 1, interval: float = 0.0) -> None:
        """Press and release a key by pyautogui name."""
        shift = shift_needed(key)
        code = keycode_for(key)
        for index in range(max(1, presses)):
            if shift:
                self._run(
                    [
                        "key",
                        f"{KEY_LEFTSHIFT}:1",
                        f"{code}:1",
                        f"{code}:0",
                        f"{KEY_LEFTSHIFT}:0",
                    ]
                )
            else:
                self._run(["key", f"{code}:1", f"{code}:0"])
            if interval > 0 and index < presses - 1:
                time.sleep(interval)

    def hotkey(self, *keys: str) -> None:
        """Press several keys together, e.g. hotkey('ctrl', 'c')."""
        codes = [keycode_for(k) for k in keys]
        if not codes:
            return
        sequence = [f"{code}:1" for code in codes]
        sequence += [f"{code}:0" for code in reversed(codes)]
        self._run(["key", *sequence])

    def key_down(self, key: str) -> None:
        """Hold a key down until key_up is called."""
        self._run(["key", f"{keycode_for(key)}:1"])

    def key_up(self, key: str) -> None:
        self._run(["key", f"{keycode_for(key)}:0"])

    def scroll(self, clicks: int) -> None:
        """Not supported by the ydotool client.

        ydotool 1.0 exposes only click, mousemove, type, key, debug, bakers and
        stdin. Scrolling is a REL_WHEEL event with no CLI equivalent, so this
        fails loudly rather than sending a wrong button event.
        """
        raise InputError("Scrolling is not supported on the Wayland backend; ydotool has no wheel command.")

    def write(self, text: str, interval: float = 0.0) -> None:
        """Type a string.

        ydotool's ``type`` understands keyboard layouts, so this is preferred
        over translating every character into keycodes. ``interval`` is ignored
        because the daemon types at its own pace.
        """
        if text == "":
            return
        self._run(["type", "--", str(text)], timeout=60.0)
