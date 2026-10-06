"""Tests for the "Settings Inject" logical step.

It changes a global setting part-way through a flow, which is what lets a run
speed the mouse up while travelling and slow it down for a precise click.

These need the real app, so they skip without a display.
"""

from __future__ import annotations

import pytest
from conftest import requires_display

pytestmark = requires_display


def make_inject_step(setting_name: str, value: str) -> dict:
    return {
        "type": "logical",
        "logical_type": "Settings Inject",
        "name": "inj",
        "x": 0,
        "y": 0,
        "inject_setting_name": setting_name,
        "inject_setting_value": value,
        "_last_run_info": {},
    }


def run_inject(app, setting_name: str, value: str):
    """Drive the real executor branch and return (result, details)."""
    step = make_inject_step(setting_name, value)
    app.steps = [step]
    app.current_step_index = 0
    app.execute_logical_step(step)
    info = step["_last_run_info"]
    return info.get("result"), info.get("details", "")


# --- the registry -----------------------------------------------------------


def test_injectable_names_all_resolve_to_real_settings(app) -> None:
    """A name offered in the dropdown must exist in global_settings_map.

    The UI list and the runtime list used to be separate dicts, so a name could
    be offered and then rejected at run time with "Unknown setting".
    """
    instance, _root = app
    for name, key in instance.INJECTABLE_SETTINGS.items():
        assert key in instance.global_settings_map, f"{name!r} points at unknown setting {key!r}"


def test_mouse_move_speed_is_injectable(app) -> None:
    """The reported gap: mouse movement speed could not be changed mid-flow."""
    instance, _root = app
    assert "Mouse Move Speed (s)" in instance.INJECTABLE_SETTINGS
    assert instance.INJECTABLE_SETTINGS["Mouse Move Speed (s)"] == "mouse_speed"


def test_new_steps_default_to_a_name_that_exists(app) -> None:
    instance, root = app
    instance.add_step("logical")
    root.update()
    step = instance.steps[-1]
    assert step["inject_setting_name"] in instance.INJECTABLE_SETTINGS


# --- injecting --------------------------------------------------------------


def test_injects_mouse_move_speed(app) -> None:
    instance, _root = app
    instance.mouse_speed.set(0.25)
    result, details = run_inject(instance, "Mouse Move Speed (s)", "0.05")
    assert result is True
    assert instance.mouse_speed.get() == pytest.approx(0.05)
    assert "0.05" in details


def test_injects_pixels_per_second(app) -> None:
    instance, _root = app
    result, _ = run_inject(instance, "Pixels Per Second", "2500")
    assert result is True
    assert instance.pixels_per_second.get() == 2500


def test_injects_min_and_max_move_time(app) -> None:
    instance, _root = app
    run_inject(instance, "Min Move Time (s)", "0.02")
    run_inject(instance, "Max Move Time (s)", "0.9")
    assert instance.min_move_time.get() == pytest.approx(0.02)
    assert instance.max_move_time.get() == pytest.approx(0.9)


def test_injects_scan_interval(app) -> None:
    """Scan interval is the other half of tracking a moving target."""
    instance, _root = app
    result, _ = run_inject(instance, "Scan Interval (s)", "0.01")
    assert result is True
    assert instance.scan_interval.get() == pytest.approx(0.01)


def test_injects_integer_setting_as_int(app) -> None:
    instance, _root = app
    run_inject(instance, "Location Offset (±px)", "9")
    assert instance.loc_offset_variance.get() == 9
    assert isinstance(instance.loc_offset_variance.get(), int)


def test_existing_names_still_work(app) -> None:
    """Projects saved before this change must keep working."""
    instance, _root = app
    result, _ = run_inject(instance, "Speed Variance (±s)", "0.2")
    assert result is True
    assert instance.speed_variance.get() == pytest.approx(0.2)


# --- the string-valued move mode -------------------------------------------


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("Regular", "Regular"),
        ("Dynamic", "Dynamic"),
        ("Pixels Per Second", "Pixels Per Second"),
        ("dynamic", "Dynamic"),
        ("PIXELS PER SECOND", "Pixels Per Second"),
        ("  dynamic  ", "Dynamic"),
    ],
)
def test_move_mode_accepts_and_normalises_spellings(app, typed: str, expected: str) -> None:
    instance, _root = app
    result, _ = run_inject(instance, "Mouse Move Mode", typed)
    assert result is True
    assert instance.mouse_move_mode.get() == expected


def test_move_mode_rejects_an_unknown_value(app) -> None:
    instance, _root = app
    instance.mouse_move_mode.set("Regular")
    result, details = run_inject(instance, "Mouse Move Mode", "Fastish")
    assert result is False
    assert "Regular, Dynamic, Pixels Per Second" in details
    assert instance.mouse_move_mode.get() == "Regular", "must not change on a bad value"


def test_unknown_setting_name_fails_cleanly(app) -> None:
    """Hand-edited or older JSON may name a setting that no longer exists."""
    instance, _root = app
    result, details = run_inject(instance, "Turbo Mode", "11")
    assert result is False
    assert "Unknown setting" in details


def test_bad_number_fails_cleanly(app) -> None:
    instance, _root = app
    instance.mouse_speed.set(0.25)
    result, details = run_inject(instance, "Mouse Move Speed (s)", "quick")
    assert result is False
    assert "Invalid value" in details
    assert instance.mouse_speed.get() == pytest.approx(0.25), "must not change on a bad value"


def test_injected_values_reach_the_global_settings_panel(app) -> None:
    """The panel mirrors the model, so the change is visible to the user."""
    instance, root = app
    run_inject(instance, "Mouse Move Speed (s)", "0.07")
    root.update()
    assert instance.global_settings_ui_vars["mouse_speed"].get() == "0.07"
