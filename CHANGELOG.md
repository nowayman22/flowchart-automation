# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Split monolithic `FlowchartClickerApp66.py` into `src/flowchart_automation/` modules.
- Replace dict-based step data with typed dataclasses.
- UI refresh (see `docs/CODE_REVIEW.md`).
- First tests for detection, persistence, and GE price math.

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
