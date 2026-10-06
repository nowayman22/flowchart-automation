"""Entry point for `flowchart-automation` and `python -m flowchart_automation`.

During the migration the app class still lives in FlowchartClickerApp66.py at
the project root. This shim adds the project root to sys.path so the legacy
module can be imported, then hands off to it. Once the UI is fully ported to
src/ this file becomes the real entry point.
"""

import sys
import tkinter as tk
from pathlib import Path


def main() -> None:
    _project_root = str(Path(__file__).resolve().parents[2])
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

    from FlowchartClickerApp66 import FlowchartClickerApp

    root = tk.Tk()
    app = FlowchartClickerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
