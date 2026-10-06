"""Tesseract OCR wrapper.

`AVAILABLE` is set at import time. Callers should check it before calling
`extract_number`. The module resolves the Tesseract binary path using the same
portable-first, system-PATH, hardcoded-fallback priority as the legacy app.
"""

from __future__ import annotations

import shutil

import cv2
import numpy as np

AVAILABLE: bool = False
_pytesseract = None


def _init() -> None:
    global AVAILABLE, _pytesseract
    try:
        import os

        import pytesseract  # type: ignore[import]

        from ..util.paths import get_base_path

        portable = os.path.join(get_base_path(), "tesseract", "tesseract.exe")
        if os.path.exists(portable):
            pytesseract.pytesseract.tesseract_cmd = portable
        else:
            system = shutil.which("tesseract")
            if system:
                pytesseract.pytesseract.tesseract_cmd = system
            else:
                pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

        pytesseract.get_tesseract_version()
        _pytesseract = pytesseract
        AVAILABLE = True
    except Exception:
        AVAILABLE = False


_init()


def preprocess(img_cv: np.ndarray, image_mode: str = "Grayscale") -> np.ndarray:
    """Convert a BGR frame to the format expected by Tesseract."""
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    if image_mode == "Binary (B&W)":
        inverted = cv2.bitwise_not(gray)
        _, result = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return result
    elif image_mode == "Color":
        return cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
    else:  # Grayscale
        return cv2.bitwise_not(gray)


def extract_number(
    img_cv: np.ndarray,
    psm: int = 6,
    oem: int = 3,
    image_mode: str = "Grayscale",
) -> str | None:
    """Run OCR and return the cleaned numeric string, or None if nothing found.

    Raises RuntimeError if Tesseract is not available.
    """
    if not AVAILABLE or _pytesseract is None:
        raise RuntimeError("Tesseract is not available")
    from PIL import Image

    processed = preprocess(img_cv, image_mode)
    config = f"--oem {oem} --psm {psm} -c tessedit_char_whitelist=0123456789:;,.-"
    raw = _pytesseract.image_to_string(Image.fromarray(processed), config=config)
    cleaned = "".join(c for c in raw if c in "0123456789.-")
    return cleaned if cleaned else None
