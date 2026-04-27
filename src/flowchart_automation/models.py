"""Typed data models for the flowchart automation tool.

This is a starter for the Phase 1 refactor described in docs/CODE_REVIEW.md.
It replaces the free-form dicts currently used in FlowchartClickerApp66.py
(``self.steps`` and ``self.annotations``) with proper dataclasses.

Design goals:

* One discriminated union per concept ("Step" → Color | Png | Click | Logical).
* Every JSON project carries a ``schema_version`` so old exports keep loading.
* Conversion is explicit (``from_dict`` / ``to_dict``) — no magic.
* No UI imports here; this module is meant to be testable in isolation.

Once the UI is wired to this, the big ``apply_properties_changes`` /
``run_step_executor`` branches in the legacy file collapse into
small per-type methods.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal

SCHEMA_VERSION = 2  # bump when the on-disk shape changes


# --- enums & unions -------------------------------------------------------

class StepKind(str, Enum):
    COLOR = "color"
    PNG = "png"
    LOCATION = "location"   # click / keypress
    LOGICAL = "logical"


class LogicalKind(str, Enum):
    COUNT = "Count"
    TIMER = "Timer"
    WAIT = "Wait"
    TYPE_TEXT = "Type Text"
    NUMBER = "Number"
    MOVEMENT = "Movement Detect"
    GE_INJECT = "GE Inject"
    SETTINGS_INJECT = "Settings Inject"


FlowAction = Literal["Next Step", "Go To", "Stop", "Restart"]
ColorSpace = Literal["HSV", "RGB"]
ImageMode = Literal["Grayscale", "Color", "Binary (B&W)"]


# --- shared primitives ----------------------------------------------------

@dataclass
class Area:
    """Rectangular screen region in absolute pixels."""
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0


@dataclass
class FlowBranch:
    """Where execution goes after a step finishes (success or timeout)."""
    action: FlowAction = "Next Step"
    goto_step: int = 1  # 1-indexed, matches the UI
    delay: float = 0.0


@dataclass
class LastRun:
    timestamp: float | None = None
    result: bool | str | None = None
    details: str = "Not yet run"


# --- steps -----------------------------------------------------------------

@dataclass
class BaseStep:
    """Fields every step kind has."""
    name: str = "Unnamed"
    x: float = 50.0
    y: float = 50.0
    delay_after: float = 1.0
    enable_logging: bool = True
    show_area: bool = False
    on_success: FlowBranch = field(default_factory=FlowBranch)
    on_timeout: FlowBranch = field(default_factory=lambda: FlowBranch(action="Stop"))
    timeout: float = 0.0
    last_run: LastRun = field(default_factory=LastRun)


@dataclass
class ColorStep(BaseStep):
    kind: Literal[StepKind.COLOR] = StepKind.COLOR
    action: str = "Click Object"
    rgb: tuple[int, int, int] = (255, 0, 0)
    tolerance: int = 2
    color_space: ColorSpace = "HSV"
    min_pixel_area: int = 10
    area: Area | None = None
    count_expression: str = ">= 1"
    count_max_cycles: int = 1


@dataclass
class PngStep(BaseStep):
    kind: Literal[StepKind.PNG] = StepKind.PNG
    action: str = "Click Object"
    mode: Literal["file", "folder"] = "file"
    path: str = ""
    threshold: float = 0.8
    image_mode: ImageMode = "Grayscale"
    find_first_match: bool = True
    area: Area | None = None
    count_expression: str = ">= 1"
    count_max_cycles: int = 1


@dataclass
class ClickStep(BaseStep):
    """Unconditional click or keypress at a fixed location."""
    kind: Literal[StepKind.LOCATION] = StepKind.LOCATION
    action: str = "Left Click"
    coords: tuple[int, int] = (100, 100)
    key_to_press: str = ""


@dataclass
class LogicalStep(BaseStep):
    kind: Literal[StepKind.LOGICAL] = StepKind.LOGICAL
    logical_type: LogicalKind = LogicalKind.COUNT
    # count
    counter_value: int = 0
    max_count: int = 0
    reset_on_start: bool = False
    reset_on_reach: bool = False
    # wait/timer
    max_time: float = 5.0
    # text
    text_source: Literal["Static Text", "GE Interface"] = "Static Text"
    text_to_type: str = ""
    ge_data_field: str = "Calculated Buy Price"
    press_enter: bool = False
    enter_press_delay: float = 0.1
    # number (OCR)
    expression: str = "> 0"
    psm_mode: str = "6: Assume a single uniform block of text."
    oem_mode: str = "3: Default, based on what is available."
    image_mode: ImageMode = "Grayscale"
    area: Area | None = None
    # movement
    movement_tolerance: float = 5.0


Step = ColorStep | PngStep | ClickStep | LogicalStep


# --- annotations & project --------------------------------------------------

@dataclass
class Annotation:
    x: float = 60.0
    y: float = 60.0
    width: float = 200.0
    height: float = 120.0
    text: str = "New Note"
    color: str = "#fffacd"
    opacity: str = "0% (Border Only)"


@dataclass
class MouseSettings:
    mode: Literal["Regular", "Dynamic", "Pixels Per Second"] = "Regular"
    speed: float = 0.25
    pixels_per_second: int = 1000
    min_move_time: float = 0.05
    max_move_time: float = 0.3


@dataclass
class VarianceSettings:
    location_offset: int = 4      # ±px
    speed_variance: float = 0.06  # ±s
    hold_variance: float = 0.03   # ±s


@dataclass
class GridSettings:
    visible: bool = False
    latching: bool = False
    spacing: int = 30
    opacity: float = 0.3


@dataclass
class GlobalSettings:
    mouse: MouseSettings = field(default_factory=MouseSettings)
    variance: VarianceSettings = field(default_factory=VarianceSettings)
    grid: GridSettings = field(default_factory=GridSettings)
    scan_interval: float = 0.25
    hold_duration: float = 0.08
    global_area: Area | None = None
    hide_on_select: bool = True
    enable_all_show_area: bool = False


@dataclass
class Project:
    steps: list[Step] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
    globals: GlobalSettings = field(default_factory=GlobalSettings)
    schema_version: int = SCHEMA_VERSION


# --- JSON round-trip --------------------------------------------------------
#
# Kept intentionally simple — ``asdict`` works for all the dataclasses above
# because every field is either a primitive, a dataclass, or a list of them.

_STEP_BY_KIND = {
    StepKind.COLOR: ColorStep,
    StepKind.PNG: PngStep,
    StepKind.LOCATION: ClickStep,
    StepKind.LOGICAL: LogicalStep,
}


def step_to_dict(step: Step) -> dict[str, Any]:
    data = asdict(step)
    # dataclasses encode enums as Enum objects; coerce for JSON compatibility
    data["kind"] = step.kind.value
    if isinstance(step, LogicalStep):
        data["logical_type"] = step.logical_type.value
    return data


def step_from_dict(data: dict[str, Any]) -> Step:
    kind = StepKind(data.pop("kind"))
    cls = _STEP_BY_KIND[kind]
    # nested dataclass fields need rebuilding
    data["on_success"] = FlowBranch(**data.get("on_success", {}))
    data["on_timeout"] = FlowBranch(**data.get("on_timeout", {}))
    if "last_run" in data and isinstance(data["last_run"], dict):
        data["last_run"] = LastRun(**data["last_run"])
    if "area" in data and data["area"] is not None and isinstance(data["area"], dict):
        data["area"] = Area(**data["area"])
    if cls is LogicalStep and "logical_type" in data:
        data["logical_type"] = LogicalKind(data["logical_type"])
    return cls(**data)
