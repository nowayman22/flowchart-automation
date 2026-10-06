# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **The app could not start on Linux at all.** `import pyautogui` runs
  `size()` at import time, which needs an X connection and dies with
  `Xlib.error.XauthError` on Wayland, so the module never loaded. The entry
  point now installs the Wayland shim first.
- **Startup crash on any non-Windows machine.** `setup_hotkeys()` ran before
  `apply_theme()`, so when hotkey registration failed (the `keyboard` library
  needs root on Linux) the error handler called `log()`, which indexed the
  still-empty `current_theme` and raised `KeyError: 'status_red'`. The theme is
  applied first now, and `log()` falls back to a default colour instead of
  raising, so logging can never take the app down.
- **v1 import silently dropped every logical step.** The migration left v1's
  `action: 'Execute'` key on logical steps, which `LogicalStep` has no field for,
  so the constructor raised inside a bare `except Exception: pass`. A four-step
  project loaded as three steps with no warning.
- **`delay_after` had two homes.** It was both a `BaseStep` field and
  `FlowBranch.delay`. Importing a v1 file set the branch delay correctly but reset
  the step field to its `1.0` default, and re-saving wrote both. The delay now
  lives only on `FlowBranch`; `step.delay_after` is a read/write alias.
- **`rgb` and `coords` came back from JSON as lists.** `rgb == (255, 0, 0)` is
  compared directly by callers, so it silently stopped matching after one
  save/load cycle. Tuple fields are now restored on load.
- **`count_png` raised `AttributeError` on OpenCV 5,** which removed
  `cv2.groupRectangles`. `opencv-python>=4.8` has no upper bound, so a fresh
  install resolves to 5.x and every PNG count step failed. Replaced with the
  self-contained `detection.png.count_distinct_rects`, which works on both.
- `compare_frames` raised `AttributeError` on zero-size frames: `cv2.absdiff`
  returns `None` for empty input, leaving the existing `total > 0` guard
  unreachable.
- CI never ran. The workflow triggered on `main`; the default branch is `master`.
- `ruff format` was rewriting the deliberately bad Python examples quoted in
  `docs/CODE_REVIEW.md`; `docs/` is now excluded from ruff.

### Added
- **Wayland support.** The app now runs on Hyprland/Sway and other Wayland
  compositors via `flowchart_automation/wayland/`: screen capture through grim,
  pointer positioning through the compositor (`hyprctl dispatch movecursor`) and
  button/key events through ydotool. `install_shim()` places a
  pyautogui-compatible object in `sys.modules` before the legacy module loads,
  so its ~20 existing `pyautogui.*` call sites work unchanged. Input needs
  `ydotool` plus the `ydotoold` daemon (`scripts/setup-wayland.sh` sets both
  up); capture needs only grim.
- Pointer positioning deliberately does **not** use `ydotool mousemove
  --absolute`. Measured on a 2560x1600 output it is neither linear nor
  predictable: asking for x=300 landed at x=775, y=800 saturated at the bottom
  edge, and setting one axis changed the reported position on the other. The
  virtual device's absolute range does not match the output, so the compositor
  moves the cursor instead and ydotool delivers events where it landed. Verified
  exact on all four corners and through an end-to-end test that clicks a real
  widget.
- `packaging/flowchart-automation.desktop` and a PNG icon so the app can be
  launched from Walker.
- `tests/` with 145 tests covering the v1 migration, JSON round trip, the
  expression evaluator, colour/template/movement detection, and GE price math.
  `tests/fixtures/legacy_v1_project.json` is a v1 export with all four step types.
- `tests/test_wayland_backend.py` (59 tests) covering keycodes, grim geometry
  including HiDPI scaling and clamping, ydotool button encoding, and the shim,
  with subprocess calls mocked so it runs without a compositor.
- `Project.load_warnings` records every step that could not be read, and
  `persistence.load()` emits a `UserWarning` instead of losing data quietly.
  `load(path, strict=True)` and `step_from_dict(data, strict=True)` raise instead.
- Unknown keys on a step are reported and ignored, so one stray field can no
  longer cost the user an entire step.

### Changed
- `BaseStep.delay_after` is a property aliasing `on_success.delay`, not a stored
  field. On-disk shape is unchanged: `on_success.delay` already carried it.

### Planned
- Split monolithic `FlowchartClickerApp66.py` into `src/flowchart_automation/` modules.
- Replace dict-based step data with typed dataclasses.
- UI refresh (see `docs/CODE_REVIEW.md`).
- Executor state machine (`execution/executor.py`, `step_handlers.py`, `context.py`).

## [0.66.0] — 2026-04-23

Initial public snapshot. Single-file Tkinter application.

### Features
- Visual flowchart editor with zoom/pan, grid snapping, multi-select, copy/paste.
- Step types: Color, PNG, Click/Press, Logical (Count, Timer, Wait, Type Text, Number/OCR, Movement Detect, GE Inject, Settings Inject).
- Configurable mouse movement modes: Regular, Dynamic, Pixels-per-Second.
- Global and per-step scan areas with overlay visualisation.
- Optional OCR via portable Tesseract.
- JSON import/export.
- Grand Exchange (OSRS) price lookup panel and deal finder.
- Dark theme with custom Windows title bar.

### Known issues
- One 4,000-line class mixes UI, runtime, detection, persistence, and API calls.
- No automated tests.
- No packaging — must run `python FlowchartClickerApp66.py`.
