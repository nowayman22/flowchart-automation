"""JSON persistence for Project objects.

Supports the v2 schema (models.py dataclasses) and can migrate v1 saves
(the flat-dict format written by FlowchartClickerApp66.py).

v1 save format characteristics:
- No 'schema_version' key
- Steps use 'type' instead of 'kind'
- Flow branches are flat keys: on_success_action, on_success_goto_step, delay_after
- Global settings are flat: mouse_move_mode, mouse_speed, loc_offset_variance, ...
- Area stored as tuple/list [x1, y1, x2, y2] or separate area_x1/y1/x2/y2 keys
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import (
    SCHEMA_VERSION,
    Annotation,
    Area,
    FlowBranch,
    GlobalSettings,
    GridSettings,
    LastRun,
    MouseSettings,
    Project,
    Step,
    VarianceSettings,
    step_from_dict,
    step_to_dict,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save(path: str | Path, project: Project) -> None:
    """Serialise *project* to JSON at *path* (overwrites)."""
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "global_settings": asdict(project.globals),
        "steps": [step_to_dict(s) for s in project.steps],
        "annotations": [asdict(a) for a in project.annotations],
    }
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load(path: str | Path) -> Project:
    """Load a project from *path*, migrating from v1 if necessary."""
    raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    version = raw.get("schema_version", 1)
    if version < SCHEMA_VERSION:
        raw = _migrate(raw, from_version=version)

    globals_ = _parse_global_settings(raw.get("global_settings", {}))
    steps: list[Step] = []
    for s in raw.get("steps", []):
        try:
            steps.append(step_from_dict(dict(s)))
        except Exception:
            pass  # skip steps that can't be parsed after migration

    annotations = [
        Annotation(**{k: v for k, v in a.items() if k in Annotation.__dataclass_fields__})
        for a in raw.get("annotations", [])
    ]
    return Project(steps=steps, annotations=annotations, globals=globals_, schema_version=SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_global_settings(data: dict[str, Any]) -> GlobalSettings:
    mouse_d = data.get("mouse", {})
    variance_d = data.get("variance", {})
    grid_d = data.get("grid", {})
    area_d = data.get("global_area")

    return GlobalSettings(
        mouse=MouseSettings(**{k: v for k, v in mouse_d.items() if k in MouseSettings.__dataclass_fields__})
        if mouse_d
        else MouseSettings(),
        variance=VarianceSettings(**{k: v for k, v in variance_d.items() if k in VarianceSettings.__dataclass_fields__})
        if variance_d
        else VarianceSettings(),
        grid=GridSettings(**{k: v for k, v in grid_d.items() if k in GridSettings.__dataclass_fields__})
        if grid_d
        else GridSettings(),
        scan_interval=data.get("scan_interval", 0.25),
        hold_duration=data.get("hold_duration", 0.08),
        global_area=Area(**area_d) if isinstance(area_d, dict) else None,
        hide_on_select=data.get("hide_on_select", True),
        enable_all_show_area=data.get("enable_all_show_area", False),
    )


def _migrate(raw: dict[str, Any], from_version: int) -> dict[str, Any]:
    if from_version < 2:
        raw = _migrate_v1_to_v2(raw)
    return raw


def _migrate_v1_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    gs = raw.get("global_settings", {})

    # Determine mouse mode (old saves may use a bool enable_dynamic_speed)
    mode = gs.get("mouse_move_mode")
    if mode is None:
        mode = "Dynamic" if gs.get("enable_dynamic_speed", False) else "Regular"

    # Build nested global_settings
    global_area: dict | None = None
    if all(k in gs for k in ("area_x1", "area_y1", "area_x2", "area_y2")):
        x1, y1, x2, y2 = gs["area_x1"], gs["area_y1"], gs["area_x2"], gs["area_y2"]
        if x1 != 0 or y1 != 0:
            global_area = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}

    migrated_gs: dict[str, Any] = {
        "mouse": {
            "mode": mode,
            "speed": gs.get("mouse_speed", 0.25),
            "pixels_per_second": gs.get("pixels_per_second", 1000),
            "min_move_time": gs.get("min_move_time", 0.05),
            "max_move_time": gs.get("max_move_time", 0.3),
        },
        "variance": {
            "location_offset": gs.get("loc_offset_variance", 4),
            "speed_variance": gs.get("speed_variance", 0.06),
            "hold_variance": gs.get("hold_duration_variance", 0.03),
        },
        "grid": {
            "visible": gs.get("grid_visible", False),
            "latching": gs.get("grid_latching", False),
            "spacing": gs.get("grid_spacing", 30),
            "opacity": gs.get("grid_opacity", 0.3),
        },
        "scan_interval": gs.get("scan_interval", 0.25),
        "hold_duration": gs.get("hold_duration", 0.08),
        "global_area": global_area,
        "hide_on_select": gs.get("hide_on_select", True),
        "enable_all_show_area": gs.get("enable_all_show_area", False),
    }

    migrated_steps = []
    for s in raw.get("steps", []):
        s = dict(s)
        step_type = s.pop("type", None)
        if step_type == "ge":
            continue  # old GE step type was removed
        if step_type == "number":
            step_type = "logical"
            s["logical_type"] = "Number"
        if step_type == "location" and s.get("action") == "Click Object":
            s["action"] = "Left Click"
        if s.get("logical_type") == "Timer":
            s["logical_type"] = "Wait"

        s["kind"] = step_type or "png"

        # Migrate flat flow-branch keys to nested dicts
        s["on_success"] = {
            "action": s.pop("on_success_action", "Next Step"),
            "goto_step": s.pop("on_success_goto_step", 1),
            "delay": s.pop("delay_after", 1.0),
        }
        s["on_timeout"] = {
            "action": s.pop("on_timeout_action", "Stop"),
            "goto_step": s.pop("on_timeout_goto_step", 1),
            "delay": 0.0,
        }

        # Migrate last_run_info
        lri = s.pop("_last_run_info", None) or {}
        s["last_run"] = {
            "timestamp": lri.get("timestamp"),
            "result": lri.get("result"),
            "details": lri.get("details", "Migrated from v1"),
        }

        # Migrate area from list/tuple to dict
        area = s.get("area")
        if isinstance(area, (list, tuple)) and len(area) == 4:
            s["area"] = {"x1": area[0], "y1": area[1], "x2": area[2], "y2": area[3]}

        # Drop runtime / UI-only fields
        for key in ("_width", "_height", "_previous_frame_for_movement", "_count_current_cycle",
                    "timer_start_time", "last_cycle_time", "on_count_reached_action",
                    "on_count_reached_goto_step", "on_count_reached_delay",
                    "ge_inject_name", "ge_inject_field", "ge_inject_quantity", "ge_inject_refresh",
                    "inject_setting_name", "inject_setting_value"):
            s.pop(key, None)

        migrated_steps.append(s)

    return {
        "schema_version": SCHEMA_VERSION,
        "global_settings": migrated_gs,
        "steps": migrated_steps,
        "annotations": raw.get("annotations", []),
    }
