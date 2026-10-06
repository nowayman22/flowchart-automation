"""Tests for JSON persistence and the v1 -> v2 migration.

The migration is the highest-risk code in the project: it runs against files
users already have on disk, and before this suite existed a failure inside it
was swallowed by a bare ``except Exception: pass``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flowchart_automation import persistence
from flowchart_automation.models import (
    SCHEMA_VERSION,
    Area,
    ClickStep,
    ColorStep,
    LogicalKind,
    LogicalStep,
    PngStep,
    Project,
    StepKind,
)

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY_V1 = FIXTURES / "legacy_v1_project.json"


@pytest.fixture
def legacy_project() -> Project:
    return persistence.load(LEGACY_V1)


# --- migration --------------------------------------------------------------


def test_v1_keeps_every_step(legacy_project: Project) -> None:
    """Regression: v1 logical steps used to be dropped without a word.

    v1 wrote ``action: 'Execute'`` on logical steps, which LogicalStep has no
    field for, so the constructor raised inside a bare except and the step
    disappeared. Two of the four fixture steps are exactly that shape.
    """
    assert len(legacy_project.steps) == 4
    assert [type(s) for s in legacy_project.steps] == [ColorStep, PngStep, ClickStep, LogicalStep]


def test_v1_load_is_clean(legacy_project: Project) -> None:
    assert legacy_project.load_warnings == []


def test_v1_annotations_drop_ui_only_type_key(legacy_project: Project) -> None:
    assert len(legacy_project.annotations) == 1
    assert legacy_project.annotations[0].text == "Start here"


def test_v1_branch_delay_is_preserved() -> None:
    """v1 had one delay_after, applied on whichever branch was taken."""
    step = persistence.load(LEGACY_V1).steps[0]
    assert step.delay_after == 2.5
    assert step.on_success.delay == 2.5
    assert step.on_timeout.delay == 2.5


def test_v1_per_step_delays_differ(legacy_project: Project) -> None:
    assert [s.delay_after for s in legacy_project.steps] == [2.5, 1.0, 0.5, 0.1]


def test_v1_flow_branches(legacy_project: Project) -> None:
    png = legacy_project.steps[1]
    assert png.on_timeout.action == "Go To"
    assert png.on_timeout.goto_step == 1
    assert png.on_success.action == "Next Step"

    location = legacy_project.steps[2]
    assert location.on_success.action == "Go To"


def test_v1_areas_are_rebuilt(legacy_project: Project) -> None:
    assert legacy_project.steps[0].area == Area(x1=10, y1=20, x2=110, y2=220)
    assert legacy_project.steps[1].area is None


def test_v1_logical_type_is_an_enum(legacy_project: Project) -> None:
    logical = legacy_project.steps[3]
    assert isinstance(logical, LogicalStep)
    assert logical.logical_type is LogicalKind.COUNT
    assert logical.max_time == 5


def test_v1_location_action_rename(legacy_project: Project) -> None:
    location = legacy_project.steps[2]
    assert location.action == "Left Click"
    assert location.coords == (640, 480)


def test_v1_global_settings_are_nested(legacy_project: Project) -> None:
    g = legacy_project.globals
    assert g.mouse.mode == "Dynamic"
    assert g.mouse.speed == 0.25
    assert g.variance.location_offset == 4
    assert g.variance.hold_variance == 0.03
    assert g.grid.visible is True
    assert g.grid.spacing == 30
    assert g.global_area == Area(x1=100, y1=200, x2=500, y2=600)
    assert g.hide_on_select is True


def test_v1_number_step_becomes_logical() -> None:
    project = persistence.load(LEGACY_V1)
    assert all(s.kind is not StepKind.LOGICAL for s in project.steps[:3])

    raw = {
        "global_settings": {},
        "steps": [{"type": "number", "name": "ocr", "x": 1, "y": 2, "expression": "> 3"}],
        "annotations": [],
    }
    migrated = persistence._migrate(raw, from_version=1)["steps"][0]
    assert migrated["kind"] == "logical"
    assert migrated["logical_type"] == "Number"


def test_v1_timer_becomes_wait() -> None:
    raw = {
        "global_settings": {},
        "steps": [{"type": "logical", "logical_type": "Timer", "name": "t", "x": 1, "y": 2}],
        "annotations": [],
    }
    migrated = persistence._migrate(raw, from_version=1)["steps"][0]
    assert migrated["logical_type"] == "Wait"


def test_v1_ge_step_is_dropped_by_design() -> None:
    raw = {
        "global_settings": {},
        "steps": [
            {"type": "ge", "name": "old ge step"},
            {"type": "color", "name": "kept", "x": 1, "y": 2},
        ],
        "annotations": [],
    }
    migrated = persistence._migrate(raw, from_version=1)
    assert [s["name"] for s in migrated["steps"]] == ["kept"]


# --- round trip -------------------------------------------------------------


def test_save_load_round_trip(tmp_path: Path, legacy_project: Project) -> None:
    out = tmp_path / "round_trip.json"
    persistence.save(out, legacy_project)
    reloaded = persistence.load(out)

    assert reloaded.load_warnings == []
    assert len(reloaded.steps) == len(legacy_project.steps)
    assert reloaded.globals == legacy_project.globals
    assert reloaded.annotations == legacy_project.annotations


def test_delays_survive_round_trip(tmp_path: Path, legacy_project: Project) -> None:
    out = tmp_path / "delays.json"
    persistence.save(out, legacy_project)
    reloaded = persistence.load(out)
    assert [s.delay_after for s in reloaded.steps] == [2.5, 1.0, 0.5, 0.1]


def test_tuples_stay_tuples_after_round_trip(tmp_path: Path, legacy_project: Project) -> None:
    """JSON has no tuples; rgb/coords must not drift into lists.

    ``rgb == (255, 0, 0)`` is compared directly by callers, so a list coming
    back from disk is a silent behavioural change, not a cosmetic one.
    """
    out = tmp_path / "tuples.json"
    persistence.save(out, legacy_project)
    reloaded = persistence.load(out)

    color = reloaded.steps[0]
    assert isinstance(color, ColorStep)
    assert color.rgb == (255, 0, 0)
    assert isinstance(color.rgb, tuple)

    location = reloaded.steps[2]
    assert isinstance(location, ClickStep)
    assert isinstance(location.coords, tuple)


def test_save_writes_schema_version(tmp_path: Path, legacy_project: Project) -> None:
    out = tmp_path / "versioned.json"
    persistence.save(out, legacy_project)
    assert json.loads(out.read_text())["schema_version"] == SCHEMA_VERSION


def test_load_does_not_leak_load_warnings_to_disk(tmp_path: Path, legacy_project: Project) -> None:
    out = tmp_path / "no_leak.json"
    persistence.save(out, legacy_project)
    assert "load_warnings" not in json.loads(out.read_text())


def test_save_fails_loudly_when_parent_directory_missing(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "deeper" / "project.json"
    with pytest.raises(FileNotFoundError):
        persistence.save(out, Project())


# --- failure handling -------------------------------------------------------


def test_unparseable_step_is_reported_not_swallowed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "global_settings": {},
                "steps": [
                    {"kind": "color", "name": "fine", "x": 1, "y": 2},
                    {"name": "no kind at all"},
                ],
                "annotations": [],
            }
        )
    )
    with pytest.warns(UserWarning, match="step 2 of 2"):
        project = persistence.load(bad)

    assert len(project.steps) == 1
    assert len(project.load_warnings) == 1
    assert "step 2 of 2" in project.load_warnings[0]


def test_strict_load_raises_on_bad_step(tmp_path: Path) -> None:
    bad = tmp_path / "bad_strict.json"
    bad.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "global_settings": {},
                "steps": [{"name": "no kind"}],
                "annotations": [],
            }
        )
    )
    with pytest.raises(ValueError, match="was skipped"):
        persistence.load(bad, strict=True)


def test_unknown_step_field_warns_but_keeps_step() -> None:
    from flowchart_automation.models import step_from_dict

    data = {"kind": "color", "name": "c", "x": 1, "y": 2, "totally_bogus": 42}
    with pytest.warns(UserWarning, match="unknown field"):
        step = step_from_dict(data)

    assert isinstance(step, ColorStep)
    assert step.name == "c"


def test_unknown_step_field_raises_in_strict_mode() -> None:
    from flowchart_automation.models import step_from_dict

    with pytest.raises(ValueError, match="unknown field"):
        step_from_dict({"kind": "color", "totally_bogus": 1}, strict=True)


def test_migration_does_not_mutate_caller_data() -> None:
    from flowchart_automation.models import step_from_dict

    original = {"kind": "color", "name": "c", "x": 1, "y": 2}
    snapshot = dict(original)
    step_from_dict(original)
    assert original == snapshot


def test_load_v1_emits_no_warnings(recwarn: pytest.WarningsRecorder) -> None:
    persistence.load(LEGACY_V1)
    assert [w for w in recwarn if issubclass(w.category, UserWarning)] == []


# --- global settings --------------------------------------------------------


def test_defaults_fill_in_when_global_settings_absent(tmp_path: Path) -> None:
    p = tmp_path / "bare.json"
    p.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "steps": [], "annotations": []}))
    project = persistence.load(p)
    assert project.globals.mouse.mode == "Regular"
    assert project.globals.global_area is None
    assert project.globals.scan_interval == 0.25


def test_global_area_left_unset_for_zero_origin() -> None:
    """v1 used area_x1/y1 == 0 to mean 'no area captured'."""
    migrated = persistence._migrate_v1_to_v2(
        {"global_settings": {"area_x1": 0, "area_y1": 0, "area_x2": 0, "area_y2": 0}}
    )
    assert migrated["global_settings"]["global_area"] is None


def test_unknown_global_setting_keys_are_ignored(tmp_path: Path) -> None:
    p = tmp_path / "extra_globals.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "global_settings": {"scan_interval": 0.5, "something_new": True},
                "steps": [],
                "annotations": [],
            }
        )
    )
    project = persistence.load(p)
    assert project.globals.scan_interval == 0.5
