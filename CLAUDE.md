Read existing files before writing. Don't re-read unless changed.
Thorough in reasoning, concise in output.
Skip files over 100KB unless required.
No sycophantic openers or closing fluff.
No emojis or em-dashes.
Do not guess APIs, versions, flags, commit SHAs, or package names. Verify by reading code or docs before asserting.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"

# Run the app
flowchart-automation            # via installed entry point
python FlowchartClickerApp66.py # legacy direct launch (needs the shim on Wayland)

# Linux/Wayland input backend (installs ydotool, starts the ydotoold user service)
./scripts/setup-wayland.sh

# Lint / format
ruff check .
ruff format .

# Tests
pytest
pytest tests/path/to/test.py::test_name   # single test
pytest --cov=flowchart_automation --cov-report=term-missing

# Windows binary (tagged release only, runs via CI)
pyinstaller --noconfirm --onefile --windowed --name FlowchartAutomation --icon Flow2.ico --add-data "Flow2.ico;." src/flowchart_automation/__main__.py
```

## Architecture

The project is mid-refactor. Today there are two parallel layers:

**`FlowchartClickerApp66.py`** - the working app, a single 4,000-line `FlowchartClickerApp` class that mixes the Tkinter UI, automation run-loop, all detection logic (color, PNG template-matching, OCR, movement), JSON persistence, and the OSRS Grand Exchange API client. Excluded from `ruff` linting via `extend-exclude` in `pyproject.toml`.

**`src/flowchart_automation/`** - the refactor target (Phase 1 + 2 in progress):
- `__init__.py` - exposes `__version__`
- `__main__.py` - entry point shim that imports `FlowchartClickerApp` from the legacy file during migration
- `models.py` - typed dataclasses replacing the free-form step dicts in the legacy file
- `persistence.py` - `save(path, project)` / `load(path, strict=False) -> Project` with v1->v2 migration. Unreadable steps land in `Project.load_warnings` and emit a `UserWarning`; they are never dropped silently.
- `util/paths.py` - `get_base_path()` (portable/PyInstaller aware)
- `util/expressions.py` - `evaluate(expression_str, value)` (the `>= 5` evaluator used in three places)
- `detection/color.py` - `find_color_hsv`, `find_color_rgb`, `count_color`, plus the aiming helpers `find_blobs`, `select_target`, `separate_touching` (pure functions). `find_color_*` take `target` and `split_width`: `cv2.findContours` merges blobs that touch, so "largest blob" can silently mean two blobs and the gap between them. `separate_touching` opens the mask to cut the thin bridges that cause it. The legacy app delegates to these rather than keeping its own copy.
- `detection/png.py` - `find_png`, `count_png`, `load_template`, `find_template_in_region`, `count_distinct_rects` (pure, cache-dict based). `count_distinct_rects` replaces `cv2.groupRectangles`, which OpenCV 5 removed; the legacy app's own `find_and_count_png` must call it too, because it crashed on every PNG Count until it did.
- A PNG step holds a **list** of templates (`paths`), so one step detects any of several snips. `step_template_paths` resolves the list, a legacy single `path`, or nothing; `collect_step_templates` loads them as `(label, data)` and both `find_png` and `find_and_count_png` go through it. `path` mirrors the first entry for previews, canvas labels and old saves.
- `detection/movement.py` - `compare_frames(previous, current, tolerance) -> MovementResult`
- `detection/ocr.py` - `extract_number`, `preprocess`, `AVAILABLE` flag; sets up Tesseract path on import
- `execution/actions.py` - `execute_move`, `execute_click`, `execute_action` taking `GlobalSettings`
- `integrations/ge_client.py` - `fetch_mapping`, `fetch_item_price`, `fetch_all_prices`, `calculate_price` (pure HTTP)
- `wayland/` - Linux/Wayland backend. `compositor.py` (hyprctl: monitor geometry, cursor position, `movecursor`), `capture.py` (grim screenshots, HiDPI scaling, clamps regions to the monitor), `input.py` (ydotool button/key events, including the 0x40 press / 0x80 release / 0xC0 click byte encoding), `keycodes.py` (pyautogui key names to Linux input-event-codes), `shim.py` (a `PyAutoGUIShim` ModuleType installed into `sys.modules['pyautogui']`).

Pointer positioning must go through `compositor.move_cursor`, never `ydotool mousemove --absolute`. That command does not map 1:1 onto screen pixels: measured on a 2560x1600 output, x=300 landed at 775, y=800 saturated at the bottom edge, and setting one axis moved the reported position on the other. `hyprctl dispatch movecursor` was exact on every probe. ydotool is only for events at wherever the cursor already is. `YdotoolInput.position()` and `move_to()` therefore need no ydotool and work without it.

### Scan performance

Capture dominates the scan loop; colour detection costs ~5 ms while a full-screen PNG frame cost ~350 ms. `GrimCapture.screenshot_array` therefore asks grim for uncompressed PPM (`-t ppm`) and views the payload with `np.frombuffer`, skipping both PNG codecs. `parse_ppm` is byte-identical to PIL's decoder and is asserted against it; the PNG path remains as a fallback and `_ppm_supported` remembers a failure so a grim without PPM costs one attempt, not one per frame. Anything on the per-frame path must call `screenshot_array`, not `screenshot()`, which builds a PIL image that callers would convert straight back to numpy.

Measured per scan (capture + detect): full screen 2560x1600 was 485 ms, now 68 ms. The remaining floor is ~33 ms from spawning `grim` once per frame, so shrinking the scan area below roughly 640x480 no longer helps. Beating that needs a persistent capture stream rather than a process per frame.

Per-frame work runs on the Tk main thread in `run_step_executor`, so a slow capture freezes the UI for its duration.

### Platform support

`pyautogui` is X11/Windows only and **cannot be imported at all on Wayland**: it calls `size()` at import time and raises `Xlib.error.XauthError`. `wayland.install_shim()` must therefore run before anything imports pyautogui, which is why `__main__.py` calls it first. On Wayland, capture goes through grim and input through ydotool, so input requires both the `ydotool` package and a running `ydotoold` daemon (`scripts/setup-wayland.sh`). Without them the editor and detection still work and input calls raise `InputError` with the fix in the message.

Global hotkeys are attempted in two steps. The `keyboard` library is tried first (it works on Windows), but on Linux it refuses to run unless euid is 0, so `wayland/hotkeys.py` takes over: it reads `/dev/input/event*` directly, which needs only membership of the `input` group. It is a passive listener, never a grab, so the focused application still receives the key. Devices named `ydotoold`/`virtual`/`uinput` must be ignored or the app would react to its own injected keys. F2/F3/Escape are also bound in-window as a fallback. Detection and input code must never assume a global hotkey exists.

`wm attributes` (`-topmost`, `-alpha`) are accepted by Tk and then **ignored** under Hyprland/XWayland: they read straight back as `0`/`1.0` and have no effect. Anything needing a dimmed, translucent or always-on-top window must not rely on them. Full-screen selection UI therefore uses `begin_screen_selection`, which captures the screen **before** showing anything and crops the selection out of that frozen frame. Never take a second screenshot after tearing down a selection overlay: Tk only queues a destroy, and a sleep in the callback blocks the event loop, so the request may not have reached the X server and the overlay ends up in the capture. Override-redirect windows also never receive keyboard focus, so any full-screen picker needs a mouse-only way out (right-click).

Note that `FlowchartClickerApp66.py` is excluded from ruff, so its own style is unchanged.

### Data model (`models.py`)

Steps use a discriminated union: `Step = ColorStep | PngStep | ClickStep | LogicalStep`. All four inherit from `BaseStep`, which holds common fields (`name`, `x/y` canvas position, `on_success: FlowBranch`, `on_timeout: FlowBranch`, `timeout`, `last_run`).

`FlowBranch` describes where execution goes after a step completes (`action`, `goto_step`, `delay`). The post-step delay lives on the branch, so success and timeout can be paced independently. `step.delay_after` still reads and writes, but it is a property aliasing `on_success.delay`, not a stored field. `Area` is a screen rectangle in absolute pixels. `Project` is the top-level container (`steps`, `annotations`, `globals`, `schema_version`, plus runtime-only `load_warnings`).

JSON round-trip is explicit via `step_to_dict` / `step_from_dict`. `step_from_dict` never mutates its input, restores `rgb`/`coords` to tuples, ignores unknown keys with a warning (or raises under `strict=True`). Bump `SCHEMA_VERSION` when the on-disk shape changes.

### Tests (`tests/`)

`tests/fixtures/legacy_v1_project.json` is a v1 export containing all four step types; `test_persistence.py` drives the migration through it. Detection tests build synthetic numpy images, so they need no image fixtures. Prefer asserting against a real captured value over a guess: `cv2.contourArea` returns 361 for a 20x20 filled rect, and centroids are truncated to `int`.

### Remaining work (see `docs/CODE_REVIEW.md`)

```
src/flowchart_automation/
  execution/
    executor.py     state machine with on_step_start/on_step_complete/on_stop callbacks
    step_handlers.py  one handler per step kind
    context.py      ExecutionContext (screen grab, mouse, keyboard)
  ui/               app, canvas, nodes, panels/, theme, hotkeys
```

The executor should be a state machine with callbacks (`on_step_start`, `on_step_complete`, `on_stop`) so the UI can subscribe and tests can drive it headlessly. Detection functions and actions are already extracted to standalone modules; the executor just needs to call them.

### OCR

`pytesseract` is an optional dependency. `PYTESSERACT_AVAILABLE` is set at import time. Portable Tesseract: place a `tesseract/` folder next to the script/EXE containing `tesseract.exe` and `tessdata/`. Falls back to `C:\Program Files\Tesseract-OCR\tesseract.exe`.

### Hotkeys (runtime)

| Key | Action |
|-----|--------|
| F2 | Start / stop automation |
| F3 | Capture at cursor |
| F4 | Draw global scan area |

## Contributing

- Run `ruff check .` and `ruff format .` before committing.
- New non-UI logic goes in `src/flowchart_automation/` and needs a test under `tests/`.
- Document changes under *Unreleased* in `CHANGELOG.md`.
- The Windows `.exe` is built automatically on `v*` tags via `.github/workflows/ci.yml`.
