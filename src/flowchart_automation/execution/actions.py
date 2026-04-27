"""Mouse and keyboard actions with humanised movement.

All functions accept a GlobalSettings instance so they can be driven by tests
or by the executor without going through the UI layer.
"""

from __future__ import annotations

import math
import random

import pyautogui

from ..models import GlobalSettings


def execute_move(pos: tuple[int, int], settings: GlobalSettings) -> None:
    """Move the mouse to *pos* with humanised speed and offset variance."""
    offset = settings.variance.location_offset
    rand_x = pos[0] + random.randint(-offset, offset)
    rand_y = pos[1] + random.randint(-offset, offset)

    start_x, start_y = pyautogui.position()
    distance = math.hypot(rand_x - start_x, rand_y - start_y)
    speed_var = random.uniform(-settings.variance.speed_variance, settings.variance.speed_variance)

    mode = settings.mouse.mode

    if mode == "Dynamic":
        screen_w, screen_h = pyautogui.size()
        max_dist = math.hypot(screen_w, screen_h)
        base = (
            settings.mouse.min_move_time
            + (settings.mouse.max_move_time - settings.mouse.min_move_time) * (distance / max_dist)
            if max_dist > 0
            else settings.mouse.min_move_time
        )
        duration = max(0.0, base + speed_var)

    elif mode == "Pixels Per Second":
        pps = settings.mouse.pixels_per_second
        base = distance / pps if pps > 0 else 0.1
        duration = max(0.0, base + speed_var)

    else:  # Regular
        duration = max(0.0, settings.mouse.speed + speed_var)

    pyautogui.moveTo(rand_x, rand_y, duration=duration, tween=pyautogui.easeOutQuad)


def execute_click(pos: tuple[int, int], settings: GlobalSettings) -> None:
    """Move to *pos* then left-click with hold-duration variance."""
    execute_move(pos, settings)
    hold_var = random.uniform(-settings.variance.hold_variance, settings.variance.hold_variance)
    hold = max(0.01, settings.hold_duration + hold_var)
    pyautogui.click(duration=hold)


def execute_right_click(pos: tuple[int, int], settings: GlobalSettings) -> None:
    """Move to *pos* then right-click."""
    execute_move(pos, settings)
    pyautogui.rightClick()


def execute_action(
    action: str,
    pos: tuple[int, int],
    settings: GlobalSettings,
) -> None:
    """Dispatch *action* string to the corresponding mouse operation.

    Recognised actions: 'Click Object', 'Left Click', 'Click Only',
    'Right Click', 'Move Only'.
    """
    if action in ("Click Object", "Left Click"):
        execute_click(pos, settings)
    elif action == "Click Only":
        hold_var = random.uniform(-settings.variance.hold_variance, settings.variance.hold_variance)
        hold = max(0.01, settings.hold_duration + hold_var)
        pyautogui.click(duration=hold)
    elif action == "Right Click":
        execute_right_click(pos, settings)
    elif action == "Move Only":
        execute_move(pos, settings)
