"""A drop-in stand-in for the ``pyautogui`` module, backed by grim and ydotool.

The legacy app calls ``pyautogui.*`` directly in about twenty places, and
``pyautogui`` cannot even be *imported* on a Wayland session: it calls
``size()`` at import time, which needs an X connection and dies with
``Xlib.error.XauthError`` when there is no ``~/.Xauthority``.

Rather than rewrite 4,000 lines, ``install()`` puts this object into
``sys.modules['pyautogui']`` before the legacy module is imported. Every
``pyautogui.x`` call then lands here without the app knowing.

Only the surface the app actually uses is implemented, plus the usual
neighbours so future call sites do not explode.
"""

from __future__ import annotations

import os
import sys
import time
import types

from .capture import GrimCapture, grim_available, hyprctl_available
from .input import YdotoolInput, unavailable_reason

__all__ = ["PyAutoGUIShim", "already_installed", "install", "is_wayland_session"]


def is_wayland_session() -> bool:
    """True when running under a Wayland compositor."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def _ease_out_quad(n: float) -> float:
    """Identical to pytweening.easeOutQuad, which pyautogui re-exports."""
    return -n * (n - 2)


def _ease_linear(n: float) -> float:
    return n


def _ease_in_quad(n: float) -> float:
    return n * n


def _ease_in_out_quad(n: float) -> float:
    n *= 2
    if n < 1:
        return 0.5 * n * n
    n -= 1
    return -0.5 * (n * (n - 2) - 1)


class PyAutoGUIShim(types.ModuleType):
    """pyautogui-compatible facade over the Wayland backend.

    Subclasses ModuleType so that ``import pyautogui`` hands back something
    that still looks like a module.
    """

    def __init__(self) -> None:
        super().__init__("pyautogui")
        self.__doc__ = "Wayland pyautogui shim (grim + ydotool)"

        self.FAILSAFE = False
        self.PAUSE = 0.0

        self.easeOutQuad = _ease_out_quad
        self.easeLinear = _ease_linear
        self.easeInQuad = _ease_in_quad
        self.easeInOutQuad = _ease_in_out_quad

        # Aliases pyautogui also exposes.
        self.easeInOutElastic = _ease_in_out_quad
        self.easeInCubic = _ease_in_quad
        self.easeOutCubic = _ease_out_quad

        self.LEFT = "left"
        self.RIGHT = "right"
        self.MIDDLE = "middle"

        self._capture = GrimCapture()
        self._input = YdotoolInput()

    # --- diagnostics -------------------------------------------------------

    @property
    def backend_status(self) -> str:
        """Human-readable backend state, surfaced in the app log."""
        reason = unavailable_reason()
        if reason:
            return f"capture: grim, input: unavailable ({reason})"
        return "capture: grim, input: ydotool"

    # --- screen ------------------------------------------------------------

    def size(self) -> tuple[int, int]:
        return self._capture.size()

    def position(self) -> tuple[int, int]:
        return self._capture.position()

    def screenshot(self, region: tuple[int, int, int, int] | None = None):
        """Return a PIL Image, matching pyautogui's return type."""
        return self._capture.screenshot(region)

    def screenshot_array(self, region: tuple[int, int, int, int] | None = None):
        """Return a raw RGB numpy array instead of a PIL image.

        Not part of the pyautogui API. The app uses it for detection frames,
        which saves building a PIL image only to convert it straight back to
        numpy. Callers must feature-detect it, as the real pyautogui lacks it.
        """
        return self._capture.screenshot_array(region)

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return self._capture.pixel(x, y)

    # --- pointer -----------------------------------------------------------

    def moveTo(self, x, y, duration=0.0, tween=None, **kwargs) -> None:
        self._input.move_to(x, y, duration=duration, tween=tween or _ease_out_quad)

    def moveRel(self, xOffset=0, yOffset=0, duration=0.0, **kwargs) -> None:
        self._input.move_rel(xOffset, yOffset)

    def click(
        self,
        x=None,
        y=None,
        clicks: int = 1,
        interval: float = 0.0,
        button: str = "left",
        duration: float = 0.0,
        **kwargs,
    ) -> None:
        if x is not None and y is not None:
            self._input.move_to(x, y)
        self._input.click(button, hold=duration or 0.0, clicks=clicks, interval=interval)

    def rightClick(self, x=None, y=None, duration=0.0, **kwargs) -> None:
        self.click(x, y, button="right", duration=duration)

    def middleClick(self, x=None, y=None, duration=0.0, **kwargs) -> None:
        self.click(x, y, button="middle", duration=duration)

    def doubleClick(self, x=None, y=None, interval=0.0, button="left", duration=0.0, **kwargs) -> None:
        self.click(x, y, clicks=2, interval=interval, button=button, duration=duration)

    def mouseDown(self, x=None, y=None, button="left", **kwargs) -> None:
        if x is not None and y is not None:
            self._input.move_to(x, y)
        self._input.mouse_down(button)

    def mouseUp(self, x=None, y=None, button="left", **kwargs) -> None:
        if x is not None and y is not None:
            self._input.move_to(x, y)
        self._input.mouse_up(button)

    def dragTo(self, x, y, duration=0.0, button="left", **kwargs) -> None:
        self._input.mouse_down(button)
        self._input.move_to(x, y, duration=duration, tween=_ease_out_quad)
        self._input.mouse_up(button)

    def scroll(self, clicks: int, x=None, y=None) -> None:
        if x is not None and y is not None:
            self._input.move_to(x, y)
        self._input.scroll(clicks)

    # --- keyboard ----------------------------------------------------------

    def press(self, keys, presses: int = 1, interval: float = 0.0, **kwargs) -> None:
        sequence = [keys] if isinstance(keys, str) else list(keys)
        for index, key in enumerate(sequence):
            self._input.press(key, presses=presses, interval=interval)
            if interval > 0 and index < len(sequence) - 1:
                time.sleep(interval)

    def keyDown(self, key: str, **kwargs) -> None:
        self._input.key_down(key)

    def keyUp(self, key: str, **kwargs) -> None:
        self._input.key_up(key)

    def hotkey(self, *keys, **kwargs) -> None:
        self._input.hotkey(*keys)

    def write(self, message: str, interval: float = 0.0, **kwargs) -> None:
        self._input.write(message, interval=interval)

    def typewrite(self, message, interval: float = 0.0, **kwargs) -> None:
        if isinstance(message, (list, tuple)):
            for item in message:
                self._input.write(str(item), interval=interval)
        else:
            self._input.write(str(message), interval=interval)


def already_installed() -> bool:
    return isinstance(sys.modules.get("pyautogui"), PyAutoGUIShim)


def install(force: bool = False) -> bool:
    """Install the shim as ``pyautogui`` if this is a Wayland session.

    Returns True when the shim is active. Must be called before anything
    imports pyautogui.
    """
    if already_installed():
        return True
    if not force and not is_wayland_session():
        return False
    if not grim_available() or not hyprctl_available():
        return False

    shim = PyAutoGUIShim()
    sys.modules["pyautogui"] = shim
    return True
