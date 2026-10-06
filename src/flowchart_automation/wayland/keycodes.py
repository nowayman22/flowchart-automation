"""Mapping from pyautogui key names to Linux input-event-codes keycodes.

``ydotool key`` accepts keycodes only (per the ydotool README: "key now (only)
accepts keycodes, so it is not limited to a specific keyboard layout"), so every
name pyautogui understands has to be translated.

Every value below was read from ``/usr/include/linux/input-event-codes.h``
rather than from memory. Keys whose names differ only by pyautogui alias
(``esc``/``escape``, ``pgup``/``pageup``) share a code.
"""

from __future__ import annotations

# --- letters ---------------------------------------------------------------

_LETTERS = {
    "a": 30,
    "b": 48,
    "c": 46,
    "d": 32,
    "e": 18,
    "f": 33,
    "g": 34,
    "h": 35,
    "i": 23,
    "j": 36,
    "k": 37,
    "l": 38,
    "m": 50,
    "n": 49,
    "o": 24,
    "p": 25,
    "q": 16,
    "r": 19,
    "s": 31,
    "t": 20,
    "u": 22,
    "v": 47,
    "w": 17,
    "x": 45,
    "y": 21,
    "z": 44,
}

# --- digits (top row) ------------------------------------------------------

_DIGITS = {
    "1": 2,
    "2": 3,
    "3": 4,
    "4": 5,
    "5": 6,
    "6": 7,
    "7": 8,
    "8": 9,
    "9": 10,
    "0": 11,
}

# --- function keys ---------------------------------------------------------

_FUNCTION = {
    "f1": 59,
    "f2": 60,
    "f3": 61,
    "f4": 62,
    "f5": 63,
    "f6": 64,
    "f7": 65,
    "f8": 66,
    "f9": 67,
    "f10": 68,
    "f11": 87,
    "f12": 88,
    "f13": 183,
    "f14": 184,
    "f15": 185,
    "f16": 186,
    "f17": 187,
    "f18": 188,
    "f19": 189,
    "f20": 190,
    "f21": 191,
    "f22": 192,
    "f23": 193,
    "f24": 194,
}

# --- editing / navigation --------------------------------------------------

_NAMED = {
    "esc": 1,
    "escape": 1,
    "backspace": 14,
    "tab": 15,
    "enter": 28,
    "return": 28,
    "space": 57,
    "spacebar": 57,
    "capslock": 58,
    "numlock": 69,
    "scrolllock": 70,
    "sysrq": 99,
    "printscreen": 99,
    "prntscrn": 99,
    "prtsc": 99,
    "prtscr": 99,
    "insert": 110,
    "delete": 111,
    "del": 111,
    "home": 102,
    "end": 107,
    "pageup": 104,
    "pgup": 104,
    "pagedown": 109,
    "pgdn": 109,
    "up": 103,
    "down": 108,
    "left": 105,
    "right": 106,
    "pause": 119,
    "menu": 139,
    "compose": 127,
    "sleep": 142,
}

# --- modifiers -------------------------------------------------------------

_MODIFIERS = {
    # pyautogui's canonical names put the side last ("ctrlleft"), which is what
    # its X11 backend accepts. The "leftctrl" spellings are added on top because
    # the app's "Key to Press" box is free text, so users type both.
    "ctrl": 29,
    "ctrlleft": 29,
    "control": 29,
    "leftctrl": 29,
    "ctrlright": 97,
    "rightctrl": 97,
    "shift": 42,
    "shiftleft": 42,
    "leftshift": 42,
    "shiftright": 54,
    "rightshift": 54,
    "alt": 56,
    "altleft": 56,
    "leftalt": 56,
    "option": 56,
    "optionleft": 56,
    "altright": 100,
    "rightalt": 100,
    "optionright": 100,
    "win": 125,
    "winleft": 125,
    "leftwin": 125,
    "command": 125,
    "winright": 126,
    "rightwin": 126,
}

# --- numeric keypad --------------------------------------------------------

_NUMPAD = {
    "num0": 82,
    "num1": 79,
    "num2": 80,
    "num3": 81,
    "num4": 75,
    "num5": 76,
    "num6": 77,
    "num7": 71,
    "num8": 72,
    "num9": 73,
    "decimal": 83,
    "divide": 98,
    "multiply": 55,
    "subtract": 74,
    "add": 78,
}

# --- media / browser -------------------------------------------------------

_MEDIA = {
    "volumemute": 113,
    "volumedown": 114,
    "volumeup": 115,
    "playpause": 164,
    "nexttrack": 163,
    "prevtrack": 165,
    "stop": 128,
    "browserback": 158,
    "browserforward": 159,
    "browserhome": 172,
    "browserrefresh": 173,
    "browsersearch": 217,
    "browserfavorites": 156,
    "launchmail": 155,
    "launchapp1": 226,
}


KEYCODES: dict[str, int] = {
    **_LETTERS,
    **_DIGITS,
    **_FUNCTION,
    **_NAMED,
    **_MODIFIERS,
    **_NUMPAD,
    **_MEDIA,
}

# Characters that need Shift held on a US layout, mapped to the key they sit on.
SHIFTED_CHARS: dict[str, str] = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "minus",
    "+": "equal",
    "{": "bracketleft",
    "}": "bracketright",
    "|": "backslash",
    ":": "semicolon",
    '"': "apostrophe",
    "<": "comma",
    ">": "period",
    "?": "slash",
    "~": "grave",
}

# Extra keys referenced only by SHIFTED_CHARS.
_PUNCTUATION = {
    "minus": 12,
    "equal": 13,
    "bracketleft": 26,
    "bracketright": 27,
    "backslash": 43,
    "semicolon": 39,
    "apostrophe": 40,
    "grave": 41,
    "comma": 51,
    "period": 52,
    "slash": 53,
}
KEYCODES.update(_PUNCTUATION)

KEY_LEFTSHIFT = 42


def keycode_for(key: str) -> int:
    """Return the Linux keycode for a pyautogui key name.

    Raises ValueError with the supported names if the key is unknown, so the
    app log says something useful instead of silently doing nothing.
    """
    if not isinstance(key, str) or not key.strip():
        raise ValueError("No key name given")

    normalised = key.strip().lower()
    if normalised in KEYCODES:
        return KEYCODES[normalised]

    # Single printable characters that are not letters or digits.
    if len(normalised) == 1 and normalised in SHIFTED_CHARS:
        return KEYCODES[SHIFTED_CHARS[normalised]]

    raise ValueError(
        f"Unsupported key {key!r} on Wayland. Supported: letters, digits, "
        f"f1-f24, arrows, enter, esc, tab, space, backspace, delete, home, "
        f"end, pageup, pagedown, ctrl, shift, alt, win, numpad keys."
    )


def shift_needed(key: str) -> bool:
    """True if *key* is a character that requires Shift on a US layout."""
    return isinstance(key, str) and len(key.strip()) == 1 and key.strip() in SHIFTED_CHARS
