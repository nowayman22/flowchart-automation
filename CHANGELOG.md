# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **The F3 picker made the app vanish with no way back.** "Pick (F3)" and
  "Get Loc (F3)" withdrew the main window and then waited for the global F3
  hotkey, and only `capture_from_hotkey` (whose `finally` restores the window)
  could carry out the capture. The `keyboard` library needs root on Linux, so
  that hotkey is never registered and nothing ever fired: the window stayed
  hidden permanently and the process had to be killed. The picker now owns a
  small window that takes focus and binds F3 and Escape itself, with Capture and
  Cancel buttons for mouse-only use and a live cursor readout.
- **The picker window must not be override-redirect.** Hyprland never delivers
  keyboard input to an override-redirect window, so F3 and Escape never arrived
  even though Tk reported the window as focused (`focus_get()` returned
  `.!toplevel`). Isolated by comparing a plain root, an override-redirect
  toplevel and a normal toplevel: only the first and last received keys.
- **A picker capture could sample the picker itself.** Clicking the Capture
  button moves the cursor onto it, and a pixel read taken while the window was
  on screen would return the window's own colour. The picker now remembers the
  last cursor position seen outside itself, and tears the window down (giving the
  compositor 150 ms to repaint) before sampling.
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
- **Settings Inject can now change mouse movement**, which it could not at all
  before. The list gains `Mouse Move Speed (s)`, `Mouse Move Mode`,
  `Pixels Per Second`, `Min Move Time (s)` and `Max Move Time (s)`, so a flow can
  speed the mouse up while travelling and slow it down for a precise click. The
  move mode is matched case-insensitively, so `dynamic` normalises to `Dynamic`,
  and a bad value leaves the setting untouched and logs why.

  The dropdown and the runtime used two separate hand-maintained dictionaries, so
  a name could be offered in the UI and then rejected at run time with "Unknown
  setting". Both now derive from one table that keys into `global_settings_map`,
  which already carries each setting's model variable and its type, so adding an
  entry there is all that is needed to make a setting injectable.

  New Settings Inject steps default to `Mouse Move Speed (s)` instead of
  `Location Offset (±px)`. Saved projects store their own setting name and are
  unaffected.
- **Colour aim point and blob splitting.** A colour step already picked the
  largest matching region, but `cv2.findContours` merges any regions that touch,
  and anti-aliasing joins blobs with a bridge one pixel wide, so "largest blob"
  could silently mean *two blobs and the gap between them*: two 40x40 blocks
  joined by a one-pixel line reported their midpoint, which is also numerically
  the centre of mass. Two new per-step options:
  `Aim Point` (`Largest Blob`, the existing default; `Center Of All Matches`,
  which averages every matching pixel and so deliberately lands between separated
  blobs; `Nearest Blob To Area Center`, which picks one blob when several match)
  and `Split Blobs (px)`, a morphological opening that cuts bridges up to twice
  the given width so touching blobs become separate contours again. `0` disables
  splitting, which keeps existing projects behaving exactly as before.

  Both live on `ColorStep` (`blob_target`, `split_blob_width`), are written to
  saved projects, and default to the previous behaviour. Colour detection in the
  legacy app now delegates to `detection.color` instead of keeping a second copy
  of the mask and contour code.
- **Global hotkeys on Linux without root.** F2/F3/F4 previously died wherever the
  `keyboard` library could not register them, which is everywhere on Linux because
  it refuses to run unless euid is 0. `wayland/hotkeys.py` reads `/dev/input/event*`
  directly instead, exactly as that library does internally but without the root
  check, so only membership of the `input` group is needed. It is a passive
  listener: keys are not grabbed, so the focused application still receives them,
  matching the original Windows behaviour.
- The listener ignores devices named `ydotoold`/`virtual`/`uinput`. Those are the
  app's own output, so reacting to them would let a "press key" step feeding F3
  re-open the picker.
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
- **Screen capture is ~7x faster, which is what makes a moving target
  trackable.** Capture was ~85% of the scan cycle while colour detection itself
  costs about 5 ms, so the bottleneck was grim's PNG encoder plus PIL's decoder,
  not the detection. Frames now come back as uncompressed PPM and are viewed
  straight into numpy. Measured, capture plus detection:

  | Scan area | Before | Now | Speedup |
  |---|---|---|---|
  | full screen 2560x1600 | 485 ms | 68 ms | 7.2x |
  | 1280x800 | 231 ms | 47 ms | 4.9x |
  | 640x480 | 100 ms | 34 ms | 2.9x |
  | 320x240 | 50 ms | 35 ms | 1.4x |

  With the default 0.25 s scan interval a full-screen step ran 3 scans/sec; it
  now runs about 9, and a 640x480 area with a 0.01 s interval reaches ~23. The
  PPM parser is byte-identical to PIL's decoder (asserted in tests) and grim's
  PNG path is kept as a fallback, remembered after one failed attempt, for a
  grim built without PPM support.

  What remains is a ~33 ms floor from spawning `grim` once per frame; a
  persistent capture stream (wf-recorder or wl-screenrec) is the next step and
  would need one of those installed.
- Detection call sites use a new `grab_frame()` helper that skips the PIL round
  trip, saving ~12 ms per full-screen frame. The F3 picker and template capture
  still get PIL images, since they save them to disk.
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
