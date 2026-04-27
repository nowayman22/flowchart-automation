# Flowchart Automation Tool

A visual, node-based automation tool for building and running task sequences from image, color, text (OCR), and movement detection.

## What it does

- Drag-and-drop **flowchart editor** for automation steps.
- Step types: **Color detection**, **PNG/template matching**, **Click/keypress**, **Logical** (counters, timers, OCR-driven number comparisons, typed text, movement detection).
- **Humanised mouse movement** (regular, dynamic, pixels-per-second) with configurable variance.
- **Global + per-step scan areas**, live detection overlay, cycle-time display.
- **JSON import/export** for flowcharts.
- **Optional OCR** via portable Tesseract.

## Screenshot

<!-- add a screenshot or GIF here once the UI refresh lands -->
<!-- ![Main window](docs/screenshot.png) -->

## Install

### From source

```bash
git clone https://github.com/nowayman22/flowchart-automation.git
cd flowchart-automation
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -e .
flowchart-automation
```

Python 3.10+ recommended.

### Windows binary

Grab the latest `.exe` from the [Releases](https://github.com/nowayman22/flowchart-automation/releases) page. No install required — unzip and run.

### OCR (optional)

For OCR-based "Number" logical steps you also need Tesseract.

- **Installed system-wide:** grab the Windows installer from [UB-Mannheim](https://github.com/UB-Mannheim/tesseract/wiki). The app will auto-detect it on PATH or at `C:\Program Files\Tesseract-OCR`.
- **Portable:** drop a `tesseract/` folder next to the script or `.exe` containing `tesseract.exe` and its `tessdata/`. The app checks this path first.

## Hotkeys

| Key | Action |
|---|---|
| F2 | Start / stop automation |
| F3 | Capture at cursor (pixel color, coordinate, etc.) |
| F4 | Draw a global scan area |

## Quick start

1. Launch the app.
2. Click the **+ PNG Step** icon in the sidebar.
3. Use **Snip** to grab a template image from your screen.
4. Add a **+ Click / Press Step** and set its `on_success` to point back to your PNG step.
5. Press **F2** to run. Press **F2** again to stop.

Export with **File → Export JSON** to share flows.

## Project layout (target)

```
src/flowchart_automation/
  models.py          # dataclasses for Step, Project, Settings
  persistence.py     # JSON load/save with schema versioning
  detection/         # png, color, movement, ocr
  execution/         # executor + per-step handlers
  integrations/      # optional extras (e.g. price APIs)
  ui/                # tk/ttk or customtkinter UI layer
  util/
tests/
docs/
```

Right now the app is still a single `FlowchartClickerApp66.py` — see [docs/CODE_REVIEW.md](docs/CODE_REVIEW.md) for the migration plan.

## Contributing

Issues and PRs welcome. Please:

1. Run `ruff check .` and `ruff format .` before committing.
2. Add a test under `tests/` for non-UI logic.
3. Describe the change in `CHANGELOG.md` under *Unreleased*.

## License

See [LICENSE](LICENSE). Default scaffold uses MIT; swap for GPL or another if you prefer.

## Disclaimer

This tool automates mouse and keyboard input. You are responsible for how you use it. Automating third-party software may violate its terms of service — check before using it on games, commercial apps, or anything you don't own.
