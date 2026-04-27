"""Resource-path resolution for both dev and PyInstaller frozen builds."""

import os
import sys


def get_base_path() -> str:
    """Return the directory that contains the app's bundled resources.

    When frozen by PyInstaller the temp extraction folder is used; in dev the
    directory containing the entry-point script is used instead.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.abspath(".")
