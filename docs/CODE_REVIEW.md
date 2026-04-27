# Code review — `FlowchartClickerApp66.py`

*Rev. 65/66 · 4,147 lines · single-file Tkinter app*

## TL;DR

The app works and is clearly the product of a lot of iteration — feature set is impressive (flowchart editor, image/color/OCR/movement detection, hotkey capture, GE pricing). The problems are almost entirely structural, not functional:

1. **One 4,000-line class doing everything** — no separation between UI, automation runtime, detection, persistence, and the GE API client.
2. **Step data is untyped dicts** sprayed with string keys, making every addition a game of "did I remember to touch every branch?"
3. **A handful of mega-methods** (`run_step_executor` ≈ 200 lines, `execute_logical_step` ≈ 250 lines, `apply_properties_changes` ≈ 90 branching lines, `__init__` ≈ 170 lines) that are effectively untestable and very hard to change safely.
4. **Semicolon-chained statements** in a lot of UI code hurt readability more than any other single thing.
5. **Theming by string-matching button labels** (`if "Color Step" in widget.cget('text')`) — fragile and will silently break if you rename a button.
6. **No tests, no type hints, no packaging, no CI, no changelog.**

Nothing here is a crisis. The code runs. But the ceiling on how fast you can add features or fix bugs is low right now, and that's the problem worth solving.

---

## Scoring the codebase

| Area | Score | Notes |
|---|---|---|
| Feature set | 9 / 10 | Genuinely a lot here. Node editor, multiple detection modes, OCR, macro-like logical steps, GE interface, movement detection, folder-based template caching. |
| Correctness (apparent) | 7 / 10 | Error handling exists (try/except at boundaries, threading lock for detection). Some rough edges around validation. |
| Readability | 4 / 10 | Semicolons everywhere, giant methods, inconsistent spacing, opaque dict keys. |
| Architecture | 3 / 10 | One god-class. No layers. UI callbacks directly mutate runtime state. |
| Testability | 2 / 10 | No tests. Nothing is mockable. Detection functions are the cheapest thing to test and they aren't. |
| Packaging / distribution | 3 / 10 | No `pyproject.toml`, no `requirements.txt`, Tesseract path hardcoded with a Windows fallback. |
| UI polish | 5 / 10 | Dark theme is fine, layout is dense, nodes are flat rectangles, 6 tabs on the right is too many. |
| Docs | 2 / 10 | Just the in-app "Info" tab and scattered comments. No README, no screenshots, no usage guide. |

---

## Code smells — concrete examples

### 1. Semicolons collapsing multi-statement lines

```python
h_scroll = ttk.Scrollbar(canvas_container, orient=tk.HORIZONTAL); v_scroll = ttk.Scrollbar(canvas_container, orient=tk.VERTICAL); self.canvas = tk.Canvas(canvas_container, bg="#3c3c3c", highlightthickness=0, xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set); h_scroll.config(command=self.canvas.xview); v_scroll.config(command=self.canvas.yview); h_scroll.pack(side=tk.BOTTOM, fill=tk.X); v_scroll.pack(side=tk.RIGHT, fill=tk.Y); self.canvas.pack(fill=tk.BOTH, expand=True); main_pane.add(canvas_container, weight=3); self.canvas.bind("<ButtonPress-1>", self.on_canvas_press); ...
```

That's one physical line with ~12 statements. It's impossible to diff, step through in a debugger, or comment selectively. Python is not C — there is no upside.

**Fix:** `ruff` with default settings will flag these; `black` will rewrite them automatically.

### 2. `Step` is a free-form dict

```python
step_defaults = {
    'type': step_type, 'name': step_name, 'delay_after': 1.0, 'timeout': 0,
    'on_timeout_action': 'Stop', 'on_timeout_goto_step': 1, ...
}
if step_type == 'color':
    step_defaults.update({'action':'Click Object', 'rgb':(255,0,0), ...})
```

Every read is `step.get('min_pixel_area', 10)` scattered across the executor and the properties panel. Every rename is grep-and-pray. Nothing catches typos (`step.get('tolerence')` silently returns None).

**Fix:** dataclasses or Pydantic models — one per step type, with a discriminated union. Starter in `src/flowchart_automation/models.py`.

### 3. `apply_properties_changes` — ~90 lines of nested branches

Reads every widget, converts its value, writes back into the step dict. No validation, no undo, no feedback other than a final `messagebox.showerror` if anything fails. A typo in a number field blows up the whole save.

**Fix:** Each step type should own a `PropertiesEditor` component that knows how to read/write its own data. One dispatch, per-field validation, inline error markers next to the offending field.

### 4. `run_step_executor` — one method, all step types

It's a ~200-line `if/elif` chain over `step['type']` and `step.get('logical_type')`. Every new step kind means editing this method. Bugs in one branch can block progress on unrelated branches.

**Fix:** A `Step.execute(context) -> StepResult` interface, one subclass per kind. The executor becomes ~15 lines: pick the step, call `execute`, act on the result.

### 5. Theming via button-text matching

```python
color_map = {
    "Color Step": 'accent_green',
    "PNG Step": 'accent_blue',
    "Click / Press Step": 'accent_grey',
    ...
}
bg_key = next((key for name, key in color_map.items() if name in widget.cget('text')), 'accent_grey')
```

Rename a button's text and its color silently drifts to grey. Also the whole tree is walked recursively on every theme application.

**Fix:** Give buttons a `style=` name when they're created. `ttk.Style().configure('Accent.Green.TButton', ...)`. No recursion, no string matching.

### 6. Hardcoded Tesseract fallback path

```python
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

Breaks on Linux/macOS contributors. Acceptable as a last resort, but it should first check `shutil.which('tesseract')`.

### 7. Network calls and file I/O on the main thread in places

`get_item_mapping`, `get_all_latest_prices` use `urllib.request.urlopen` directly. The GE auto-update wraps one call in a thread, but others aren't covered — any slow request freezes the UI.

**Fix:** Push every network call through a single `ApiClient` that dispatches on a thread pool and posts results back via `root.after`.

### 8. Globals captured at import time

```python
try:
    import pytesseract
    ...
    PYTESSERACT_AVAILABLE = True
except (ImportError, FileNotFoundError, pytesseract.TesseractNotFoundError):
    PYTESSERACT_AVAILABLE = False
```

That's fine, but `PYTESSERACT_AVAILABLE` is then only checked when building the testing panel — if the user installs Tesseract after launching, no hot-reload. Minor.

### 9. No tests, period

The cheap wins are huge:
- `_calculate_ge_price` is a pure function with ~6 branches. Test it.
- Template matching, color detection, movement detection take a screenshot array as input — feed them fixture PNGs and assert counts/coords.
- Expression parsing (`'>= 5'` → compare) is scattered inline in three places and duplicated; extract + test.

### 10. Minor / cosmetic

- `info_data["Version #:"] = "Rev. 65"` but the filename is `FlowchartClickerApp66.py`. Version should come from `__version__` in one place.
- `self.root.iconbitmap("Flow2.ico")` uses a relative path — breaks if launched from a different cwd. Use `get_base_path()`.
- `self.log_text = None` is initialized before `build_ui`, and `log()` silently no-ops until the widget exists. A simple ring-buffer would be cleaner.
- `self.properties_widgets = {}` is reused for every selected item; names collide if you're not careful (you were careful, but it's brittle).
- Mixing `tk.Button` and `ttk.Button` is why the custom theming code exists. Pick one.

---

## What I'd do — a prioritized roadmap

### Phase 0 · Hygiene (half a day)

No behavior change. Pure cleanup.

- [ ] Add `pyproject.toml`, `requirements.txt`, `.gitignore`, `LICENSE`, `README.md`.
- [ ] Run `black` and `ruff --fix` over the whole file. Fix semicolon runs.
- [ ] Extract `__version__ = "0.66.0"` to a single constant used by the info tab and the packaged EXE metadata.
- [ ] `shutil.which('tesseract')` before the hardcoded path.
- [ ] Make `Flow2.ico` load via `get_base_path()` so launching from any cwd works.
- [ ] Move the repo to GitHub. Add CI that at minimum runs `ruff check`.

### Phase 1 · Data layer (1–2 days)

Still the same app, but with a spine.

- [ ] `models.py`: `Step`, `ColorStep`, `PngStep`, `ClickStep`, `LogicalStep`, `Annotation`, `GlobalSettings` as dataclasses. Keep JSON round-trip via `asdict` / constructor.
- [ ] `persistence.py`: `save(path, project)` / `load(path) -> Project`. Versioned JSON with a `schema_version` field so old saves keep working.
- [ ] One-shot migration script that converts existing JSON exports to the new schema.
- [ ] Tests for `persistence` — load a fixture, save it, diff.

### Phase 2 · Split the god-class (2–4 days)

This is where the real gains kick in.

```
src/flowchart_automation/
  __init__.py
  __main__.py          # python -m flowchart_automation
  models.py            # Step, Annotation, GlobalSettings, Project
  persistence.py       # JSON load/save
  detection/
    __init__.py
    png.py             # find_png, find_and_count_png, template cache
    color.py           # hsv/rgb detection, color count
    movement.py        # movement detection
    ocr.py             # tesseract wrapper, expression parser
  execution/
    executor.py        # Executor(project, hooks) — owns the run loop
    step_handlers.py   # one handler per step type
    context.py         # ExecutionContext (screen grab, mouse, keyboard)
    actions.py         # execute_move, varied_click, press_key
  integrations/
    ge_client.py       # OSRS Grand Exchange API
  ui/
    app.py             # FlowchartApp — thin, just wires things together
    canvas.py          # FlowchartCanvas widget
    nodes.py           # Node drawing, hit testing
    panels/
      properties.py
      globals.py
      testing.py
      log.py
      ge_interface.py
    theme.py           # ThemeManager, ttk styles
    hotkeys.py
  util/
    paths.py           # get_base_path, resource paths
    expressions.py     # '>= 5' parser/evaluator
```

Key moves:

1. **Executor as a state machine** with callbacks (`on_step_start`, `on_step_complete`, `on_stop`). UI subscribes; tests drive it headlessly.
2. **Detection functions return plain results** (e.g. `@dataclass class DetectionResult: found: bool; pos: tuple | None; count: int | None; details: str`). No UI state inside.
3. **`PropertiesPanel` is a registry** — each step type registers how to render its editor. Adding a step type no longer requires editing five files.

### Phase 3 · UI refresh (1–2 days)

See the mockup above. The short version:

- **56-px icon sidebar** replacing the "+ Color Step / + PNG Step / …" text buttons. Icons + tooltips. Still accepts drop onto the canvas.
- **Compact top toolbar** (Start, Stop, Open, Save, Zoom controls, Search). Kills the bottom-right button sprawl.
- **Nodes** redesigned as rounded cards with a colored left-icon badge, a title, and two subtitle lines (type + action). The currently-running node gets an animated dot, not a circle stuck in the top-left corner.
- **Property panel** reorganised into sections (BASICS · DETECTION · FLOW) with small caps labels — easier to scan than the current vertical pile.
- **Tabs collapsed from 6 → 4**. Info moves to a "?" button → modal. GE Interface becomes a dockable panel (it's not useful in every session).
- **Bottom status bar** showing run state, step count, cycle time, detection result, and hotkey hints.
- **Theming via named ttk styles**, not recursive widget walks.

**Framework choice.** Three options, ranked by effort:

| Option | Effort | Look / feel | Recommendation |
|---|---|---|---|
| Keep `tk` / `ttk`, clean up styles | low | 6/10 | Fine if you want a weekend. Ceiling is what you see today. |
| `customtkinter` (drop-in-ish) | medium | 8/10 | **Best bang for buck.** Rounded widgets, real theming, works with existing Tk code. Some rewrite of buttons/frames required. |
| `PySide6` / `PyQt6` | high | 10/10 | Proper docking, high-DPI, native look. Real rewrite. Only worth it if this becomes a long-term project. |

I'd go `customtkinter` unless you're already itching to learn Qt.

### Phase 4 · Tests & CI (ongoing)

- Unit: `_calculate_ge_price`, expression parser, template cache key logic, JSON migration.
- Integration: load a fixture project, run executor headlessly against a recorded screen (pass in a `Screenshotter` interface).
- GitHub Actions: `ruff` + `pytest` on every push; Windows build job publishes a `.exe` on tagged releases.

### Phase 5 · Nice-to-haves once the above lands

- **Undo/redo** — trivial once `Project` is a dataclass (snapshot on each mutation).
- **Node snapping and auto-layout** — there's grid latching already; add "Arrange tree" and "Arrange grid".
- **Debugger view** — step through the flowchart one node at a time with variable inspection.
- **Better OCR error messages** — "Tesseract not found at X, install from Y" instead of a silent false-return.
- **Multi-monitor awareness** — `pyautogui.screenshot(region=...)` respects coordinates but DPI scaling breaks on mixed-DPI Windows setups.
- **Structured logging** to a rotating file alongside the UI log panel.

---

## Things I liked

Not just negatives — credit where it's earned:

- **Folder-template pre-caching** (`_pre_cache_folder_templates`) is a genuinely good touch — matches a lot of amateur automation tools by loading images on-demand and stalling the loop.
- **Dynamic mouse speed modes** (Regular / Dynamic / Pixels-per-Second) is thoughtful; most hobby bots hardcode a `moveTo`.
- **"Show area" overlay**, live detection readout, and the cycle-time display make debugging real flows much easier than it could be.
- **Movement-detect logical step** is clever and I haven't seen it elsewhere.
- **Dark Windows title bar via `DwmSetWindowAttribute`** — nice polish.
- **Threading lock around detection** is the correct instinct even if it's under-used.

The foundation is good. It just needs to be pulled apart.

---

## What I need from you to go further

1. **UI framework decision** (ttk polish / customtkinter / Qt) — affects how much of Phase 3 is possible in one pass.
2. **GitHub username + repo name** — so I can pre-fill the README badges and workflow URLs.
3. **License choice** — MIT is in the scaffold by default. GPL if you want derivative works to stay open. "All rights reserved" if you're not sure yet.
4. **Does the GE/OSRS integration stay in the main repo, or move to a plugin?** I'd argue plugin — keeps the core tool legitimately general-purpose.
