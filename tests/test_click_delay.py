"""Tests for the per-step click delay: move, wait, then click.

pyautogui is stubbed throughout, so these assert the ordering and timing of the
app's own code and put nothing on the screen. They need the real app, so they
skip without a display.
"""

from __future__ import annotations

import threading
import time

import pytest
from conftest import requires_display

pytestmark = requires_display


@pytest.fixture
def stub_input(app, monkeypatch):
    """Record when each input event happened, instead of driving the pointer."""
    import pyautogui

    events: list[tuple[str, float]] = []

    def fake_move(x, y, duration=0.0, tween=None, **kwargs):
        events.append(("move", time.perf_counter()))
        time.sleep(0.02)  # stand in for travel time

    monkeypatch.setattr(pyautogui, "moveTo", fake_move)
    monkeypatch.setattr(pyautogui, "click", lambda *a, **k: events.append(("click", time.perf_counter())))
    monkeypatch.setattr(
        pyautogui, "rightClick", lambda *a, **k: events.append(("rightclick", time.perf_counter()))
    )

    instance, _root = app
    instance.running = True
    instance.current_step_index = 0
    instance.log_execution = lambda *a, **k: None
    return instance, events


def names(events) -> list[str]:
    return [name for name, _ in events]


def gap(events, first: str, second: str) -> float:
    """Seconds between two recorded events."""
    start = next(t for n, t in events if n == first)
    end = next(t for n, t in events if n == second)
    return end - start


# --- ordering ---------------------------------------------------------------


def test_click_happens_after_the_move(stub_input) -> None:
    instance, events = stub_input
    instance.execute_varied_click((500, 500), 0.0)
    assert names(events) == ["move", "click"]


@pytest.mark.parametrize("delay", [0.05, 0.15, 0.3])
def test_the_wait_lands_between_move_and_click(stub_input, delay: float) -> None:
    instance, events = stub_input
    instance.execute_varied_click((500, 500), delay)

    assert names(events) == ["move", "click"], "the click still happens, just later"
    assert gap(events, "move", "click") >= delay


def test_zero_delay_clicks_immediately(stub_input) -> None:
    """With no delay the click follows the move straight away."""
    instance, events = stub_input
    instance.execute_varied_click((500, 500), 0.0)
    assert gap(events, "move", "click") < 0.1


def test_longer_delays_actually_wait_longer(stub_input) -> None:
    instance, events = stub_input
    instance.execute_varied_click((500, 500), 0.05)
    short = gap(events, "move", "click")

    events.clear()
    instance.execute_varied_click((500, 500), 0.4)
    long = gap(events, "move", "click")

    assert long - short == pytest.approx(0.35, abs=0.03)


def test_negative_delay_is_treated_as_none(stub_input) -> None:
    instance, events = stub_input
    instance.execute_varied_click((500, 500), -5.0)
    assert names(events) == ["move", "click"]
    assert gap(events, "move", "click") < 0.1


def test_right_click_waits_too(stub_input) -> None:
    instance, events = stub_input
    instance.execute_action_on_pos("Right Click", (500, 500), {"click_delay": 0.25})
    assert names(events) == ["move", "rightclick"]
    assert gap(events, "move", "rightclick") >= 0.25


def test_click_only_waits_without_moving(stub_input) -> None:
    """Click Only never moves, but the settle delay still applies."""
    instance, events = stub_input
    started = time.perf_counter()
    instance.execute_action_on_pos("Click Only", (0, 0), {"click_delay": 0.2})
    elapsed = time.perf_counter() - started

    assert names(events) == ["click"]
    assert elapsed >= 0.2


@pytest.mark.parametrize("action", ["Move Only", "Detect Object"])
def test_actions_without_a_click_ignore_the_delay(stub_input, action: str) -> None:
    instance, events = stub_input
    started = time.perf_counter()
    instance.execute_action_on_pos(action, (500, 500), {"click_delay": 0.5})
    elapsed = time.perf_counter() - started

    assert "click" not in names(events)
    assert "rightclick" not in names(events)
    assert elapsed < 0.2, "no point waiting when nothing will be pressed"


# --- stopping ---------------------------------------------------------------


def test_stop_during_the_wait_abandons_the_click(stub_input) -> None:
    """A click must not land after the user has stopped the run."""
    instance, events = stub_input

    def stop_soon():
        time.sleep(0.1)
        instance.running = False

    threading.Thread(target=stop_soon, daemon=True).start()
    instance.execute_varied_click((500, 500), 1.0)

    assert "click" not in names(events)
    assert names(events) == ["move"]


def test_stop_before_the_move_skips_everything(stub_input) -> None:
    instance, events = stub_input
    instance.running = False
    instance.execute_varied_click((500, 500), 0.0)
    assert "click" not in names(events)


def test_missing_step_means_no_delay(stub_input) -> None:
    """execute_action_on_pos is called without a step in a couple of places."""
    instance, events = stub_input
    instance.execute_action_on_pos("Left Click", (500, 500))
    assert names(events) == ["move", "click"]


# --- wiring -----------------------------------------------------------------


def test_new_colour_and_click_steps_default_to_zero_delay(app) -> None:
    instance, root = app
    instance.add_step("location")
    root.update()
    assert instance.steps[-1]["click_delay"] == 0.0
    assert instance.steps[0]["click_delay"] == 0.0


def test_delay_is_read_from_the_step(app) -> None:
    """The executor must pass the step through, or the delay is silently ignored."""
    instance, _root = app
    seen = {}
    instance.running = True
    instance.current_step_index = 0
    instance.log_execution = lambda *a, **k: None
    instance.execute_varied_click = lambda pos, click_delay=0.0: seen.update(delay=click_delay)

    instance.execute_action_on_pos("Left Click", (10, 10), {"click_delay": 0.75})
    assert seen["delay"] == pytest.approx(0.75)


def test_click_delay_widget_only_shows_for_clicking_actions(app) -> None:
    instance, root = app
    instance.selected_items = [{"type": "step", "index": 0}]
    instance.populate_properties_panel()
    root.update()

    entry = instance.properties_widgets.get("click_delay_entry")
    assert entry is not None, "the colour step must offer a click delay"

    action_var = instance.properties_widgets["action"]
    for action, expected in (
        ("Click Object", True),
        ("Right Click", True),
        ("Detect Object", False),
        ("Color Count", False),
    ):
        action_var.set(action)
        root.update()
        assert bool(entry.grid_info()) is expected, f"{action} should show={expected}"
