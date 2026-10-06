"""Tests for the typed step models and their JSON round trip."""

from __future__ import annotations

import json

import pytest

from flowchart_automation.models import (
    Area,
    BaseStep,
    ClickStep,
    ColorStep,
    FlowBranch,
    LastRun,
    LogicalKind,
    LogicalStep,
    PngStep,
    StepKind,
    step_from_dict,
    step_to_dict,
)


def test_area_geometry() -> None:
    area = Area(x1=10, y1=20, x2=110, y2=220)
    assert area.width == 100
    assert area.height == 200
    assert area.is_valid()


def test_area_rejects_inverted_bounds() -> None:
    area = Area(x1=100, y1=100, x2=10, y2=20)
    assert area.width == 0
    assert area.height == 0
    assert not area.is_valid()


def test_step_kinds_are_distinct() -> None:
    assert ColorStep().kind is StepKind.COLOR
    assert PngStep().kind is StepKind.PNG
    assert ClickStep().kind is StepKind.LOCATION
    assert LogicalStep().kind is StepKind.LOGICAL


def test_on_timeout_defaults_to_stop() -> None:
    assert ColorStep().on_timeout.action == "Stop"
    assert ColorStep().on_success.action == "Next Step"


def test_mutable_defaults_are_not_shared() -> None:
    a, b = ColorStep(), ColorStep()
    a.on_success.delay = 99.0
    a.rgb = (1, 2, 3)
    assert b.on_success.delay == 0.0
    assert b.rgb == (255, 0, 0)


def test_delay_after_proxies_to_success_branch() -> None:
    """delay_after is a compatibility alias, not a second stored field.

    Keeping it as a real field is what let a v1 import set delay_after=1.0
    while on_success.delay held 2.5, with no way to tell which was live.
    """
    step = ColorStep()
    step.delay_after = 2.5
    assert step.on_success.delay == 2.5

    step.on_success.delay = 4.0
    assert step.delay_after == 4.0


def test_delay_after_is_not_a_serialised_field() -> None:
    data = step_to_dict(ColorStep())
    assert "delay_after" not in data
    assert data["on_success"]["delay"] == 0.0


@pytest.mark.parametrize(
    "step",
    [
        ColorStep(name="c"),
        PngStep(name="p"),
        ClickStep(name="k"),
        LogicalStep(name="l"),
    ],
    ids=["color", "png", "click", "logical"],
)
def test_round_trip_through_json(step: BaseStep) -> None:
    restored = step_from_dict(json.loads(json.dumps(step_to_dict(step))))
    assert restored == step


def test_round_trip_keeps_tuples_as_tuples() -> None:
    """json.dumps turns tuples into arrays; the loader must undo that."""
    color = ColorStep(rgb=(1, 2, 3))
    restored = step_from_dict(json.loads(json.dumps(step_to_dict(color))))
    assert restored.rgb == (1, 2, 3)

    click = ClickStep(coords=(7, 8))
    restored_click = step_from_dict(json.loads(json.dumps(step_to_dict(click))))
    assert restored_click.coords == (7, 8)


def test_step_to_dict_is_json_serialisable() -> None:
    data = step_to_dict(LogicalStep(logical_type=LogicalKind.WAIT))
    assert data["kind"] == "logical"
    assert data["logical_type"] == "Wait"
    json.dumps(data)


def test_nested_dataclasses_become_dicts() -> None:
    data = step_to_dict(ColorStep())
    assert isinstance(data["on_success"], dict)
    assert isinstance(data["last_run"], dict)


def test_kind_accepts_enum_or_string() -> None:
    from_enum = step_from_dict({"kind": StepKind.COLOR, "name": "c"})
    from_string = step_from_dict({"kind": "color", "name": "c"})
    assert from_enum == from_string == ColorStep(name="c")


def test_missing_kind_is_an_error() -> None:
    with pytest.raises(ValueError, match="missing the required 'kind'"):
        step_from_dict({"name": "nowhere"})


def test_unknown_kind_is_an_error() -> None:
    with pytest.raises(ValueError):
        step_from_dict({"kind": "teleport"})


def test_nested_branch_defaults_are_filled() -> None:
    step = step_from_dict({"kind": "color", "name": "c"})
    assert step.on_success == FlowBranch()
    assert step.last_run == LastRun()


def test_legacy_step_level_delay_is_migrated_onto_the_branch() -> None:
    """v2 files written before the delay moved onto FlowBranch."""
    step = step_from_dict({"kind": "color", "name": "c", "delay_after": 3.5})
    assert step.on_success.delay == 3.5
    assert step.delay_after == 3.5


def test_explicit_branch_delay_wins_over_legacy_key() -> None:
    step = step_from_dict(
        {
            "kind": "color",
            "name": "c",
            "delay_after": 3.5,
            "on_success": {"action": "Go To", "goto_step": 2, "delay": 0.25},
        }
    )
    assert step.on_success.delay == 0.25
    assert step.on_success.goto_step == 2


def test_area_none_survives_the_round_trip() -> None:
    assert step_from_dict({"kind": "png", "name": "p", "area": None}).area is None


def test_last_run_is_rebuilt() -> None:
    step = step_from_dict(
        {"kind": "color", "name": "c", "last_run": {"timestamp": 1.5, "result": True, "details": "ok"}}
    )
    assert step.last_run == LastRun(timestamp=1.5, result=True, details="ok")


def test_logical_type_string_is_coerced_to_enum() -> None:
    step = step_from_dict({"kind": "logical", "name": "l", "logical_type": "Movement Detect"})
    assert isinstance(step, LogicalStep)
    assert step.logical_type is LogicalKind.MOVEMENT
