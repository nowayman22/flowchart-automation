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

import warnings
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal

SCHEMA_VERSION = 2  # bump when the on-disk shape changes


# --- enums & unions -------------------------------------------------------


class StepKind(str, Enum):
    COLOR = "color"
    PNG = "png"
    LOCATION = "location"  # click / keypress
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
    enable_logging: bool = True
    show_area: bool = False
    on_success: FlowBranch = field(default_factory=FlowBranch)
    on_timeout: FlowBranch = field(default_factory=lambda: FlowBranch(action="Stop"))
    timeout: float = 0.0
    last_run: LastRun = field(default_factory=LastRun)

    @property
    def delay_after(self) -> float:
        """Delay applied after this step on the success branch.

        The delay lives on the branch (``on_success.delay``) so success and
        timeout can be paced independently. This property is the compatibility
        alias for the v1 name, kept so call sites read naturally.
        """
        return self.on_success.delay

    @delay_after.setter
    def delay_after(self, value: float) -> None:
        self.on_success.delay = value


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
    # Where to aim when several blobs match. These strings are written to saved
    # projects, so they are part of the on-disk format. They are duplicated here
    # rather than imported from detection.color so that models.py stays free of
    # cv2; tests/test_models.py asserts the two stay in step.
    blob_target: str = "Largest Blob"
    # Morphological opening width in pixels, 0 = off. Cuts the thin bridges that
    # make cv2.findContours merge neighbouring blobs into a single contour.
    split_blob_width: int = 0


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
    location_offset: int = 4  # ±px
    speed_variance: float = 0.06  # ±s
    hold_variance: float = 0.03  # ±s


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
    # Populated by persistence.load() when something could not be read.
    # Runtime-only: never written to disk.
    load_warnings: list[str] = field(default_factory=list)


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

# Fields declared as ``tuple`` on the model but serialised as JSON arrays,
# mapped to the arity they must come back with.
_TUPLE_FIELDS = {"rgb": 3, "coords": 2}


def step_to_dict(step: Step) -> dict[str, Any]:
    data = asdict(step)
    # dataclasses encode enums as Enum objects; coerce for JSON compatibility
    data["kind"] = step.kind.value
    if isinstance(step, LogicalStep):
        data["logical_type"] = step.logical_type.value
    # asdict() preserves tuples, but json.dumps() writes them as arrays and
    # json.loads() reads them back as lists. Normalise here so the on-disk
    # shape is identical either way.
    for key in _TUPLE_FIELDS:
        if isinstance(data.get(key), tuple):
            data[key] = list(data[key])
    return data


def _coerce_step_fields(data: dict[str, Any], cls: type) -> None:
    """Rebuild nested dataclasses and restore tuple fields, in place."""
    for key, dc in (
        ("on_success", FlowBranch),
        ("on_timeout", FlowBranch),
        ("last_run", LastRun),
        ("area", Area),
    ):
        value = data.get(key)
        if isinstance(value, dict):
            data[key] = dc(**{k: v for k, v in value.items() if k in dc.__dataclass_fields__})
        elif key == "last_run" and value is None:
            data[key] = LastRun()

    if cls is LogicalStep and "logical_type" in data:
        data["logical_type"] = LogicalKind(data["logical_type"])

    for key, arity in _TUPLE_FIELDS.items():
        value = data.get(key)
        if isinstance(value, list) and len(value) == arity:
            data[key] = tuple(value)


def step_from_dict(data: dict[str, Any], *, strict: bool = False) -> Step:
    """Rebuild a step from its JSON dict, tolerating unknown keys.

    The input dict is never mutated. Unknown keys are reported through
    ``warnings.warn`` and dropped rather than raising, so one bad field
    cannot cost the user an entire step. Pass ``strict=True`` to raise
    ``ValueError`` instead.
    """
    data = dict(data)  # never mutate the caller's dict
    if "kind" not in data:
        raise ValueError("step is missing the required 'kind' field")

    kind = StepKind(data.pop("kind"))
    cls = _STEP_BY_KIND[kind]

    # v2 files written before the delay moved onto FlowBranch carry a
    # step-level delay_after. An explicit branch delay wins.
    legacy_delay = data.pop("delay_after", None)
    if legacy_delay is not None:
        success = data.get("on_success")
        if not isinstance(success, dict):
            success = {}
        success.setdefault("delay", legacy_delay)
        data["on_success"] = success

    _coerce_step_fields(data, cls)

    known = set(cls.__dataclass_fields__)
    unknown = sorted(set(data) - known)
    if unknown:
        message = f"{cls.__name__}: ignoring unknown field(s) {unknown}"
        if strict:
            raise ValueError(message)
        warnings.warn(message, UserWarning, stacklevel=2)
        for key in unknown:
            del data[key]

    data["kind"] = kind
    return cls(**data)
