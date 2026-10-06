"""Tests for multi-snip PNG steps: one step matching any of several templates.

A step can now hold a list of snips, so a single step detects whichever of them
appears rather than needing one step per template. The path helpers are pure and
always run; the detection tests need the real app and skip without a display.
"""

from __future__ import annotations

import tkinter as tk

import cv2
import numpy as np
import pytest
from conftest import requires_display

# --- path resolution (pure) -------------------------------------------------


def _paths(step):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from FlowchartClickerApp66 import FlowchartClickerApp

    return FlowchartClickerApp.step_template_paths(None, step)


def test_paths_list_is_used_when_present() -> None:
    assert _paths({"paths": ["a.png", "b.png"], "path": "a.png"}) == ["a.png", "b.png"]


def test_single_legacy_path_is_treated_as_a_one_entry_list() -> None:
    """Projects saved before the list existed must keep working."""
    assert _paths({"path": "only.png"}) == ["only.png"]


def test_empty_entries_are_dropped() -> None:
    assert _paths({"paths": ["a.png", "", None], "path": ""}) == ["a.png"]


def test_no_templates_resolves_to_nothing() -> None:
    assert _paths({}) == []
    assert _paths({"paths": [], "path": ""}) == []


def test_explicit_list_wins_over_a_stale_path() -> None:
    assert _paths({"paths": ["new.png"], "path": "old.png"}) == ["new.png"]


# --- detection --------------------------------------------------------------


@pytest.fixture
def multi(app, tmp_path):
    """A PNG step holding three distinct templates."""
    from flowchart_automation.wayland import install_shim

    instance, root = app
    install_shim(verbose=False)

    templates = {}
    for name in ("bank.png", "tree.png", "rock.png"):
        data = np.random.default_rng(abs(hash(name)) % 1000).integers(0, 256, (24, 24), dtype=np.uint8)
        path = tmp_path / name
        cv2.imwrite(str(path), data)
        templates[name] = (str(path), data)

    instance.add_step("png")
    root.update()
    step = instance.steps[-1]
    step.update(
        {
            "mode": "file",
            "paths": [p for p, _ in templates.values()],
            "path": templates["bank.png"][0],
            "threshold": 0.9,
            "image_mode": "Grayscale",
            "find_first_match": False,
        }
    )
    instance.selected_items = [{"type": "step", "index": len(instance.steps) - 1}]
    return instance, root, step, templates


def scene_with(template, at=(120, 80), size=(200, 300)):
    rng = np.random.default_rng(99)
    screen = cv2.cvtColor(rng.integers(0, 256, size=size, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    h, w = template.shape
    screen[at[1] : at[1] + h, at[0] : at[0] + w] = template[:, :, None]
    return screen


@requires_display
@pytest.mark.parametrize("name", ["bank.png", "tree.png", "rock.png"])
def test_any_of_the_snips_matches(multi, name: str) -> None:
    instance, _root, step, templates = multi
    _path, data = templates[name]
    step.pop("_last_matched_template", None)

    pos, confidence = instance.find_png(scene_with(data), (0, 0), step)

    assert pos == (120 + 12, 80 + 12)
    assert confidence > 0.9
    assert step["_last_matched_template"] == name, "should report which snip matched"


@requires_display
def test_nothing_matches_when_no_snip_is_present(multi) -> None:
    instance, _root, step, _templates = multi
    rng = np.random.default_rng(5)
    blank = cv2.cvtColor(rng.integers(0, 256, size=(200, 300), dtype=np.uint8), cv2.COLOR_GRAY2BGR)

    pos, confidence = instance.find_png(blank, (0, 0), step)
    assert pos is None
    assert confidence == 0


@requires_display
def test_a_missing_file_does_not_stop_the_others(multi, tmp_path) -> None:
    instance, _root, step, templates = multi
    step["paths"] = [str(tmp_path / "gone.png")] + step["paths"]

    pos, _confidence = instance.find_png(scene_with(templates["rock.png"][1]), (0, 0), step)
    assert pos == (132, 92)
    assert step["_last_matched_template"] == "rock.png"


@requires_display
def test_count_mode_sees_every_snip(multi) -> None:
    """PNG Count also has to handle a list, and must not need cv2.groupRectangles.

    That function was removed in OpenCV 5 and calling it crashed every count.
    """
    instance, _root, step, templates = multi
    count = 0
    for name in templates:
        count += instance.find_and_count_png(scene_with(templates[name][1]), (0, 0), dict(step))
    assert count == 3, "each snip should be found once in its own scene"


@requires_display
def test_count_mode_uses_the_list_for_a_single_scene(multi) -> None:
    instance, _root, step, templates = multi
    assert instance.find_and_count_png(scene_with(templates["tree.png"][1]), (0, 0), dict(step)) == 1


@requires_display
def test_fast_mode_returns_the_first_template_that_hits(multi) -> None:
    instance, _root, step, templates = multi
    step["find_first_match"] = True
    step.pop("_last_matched_template", None)

    pos, _confidence = instance.find_png(scene_with(templates["tree.png"][1]), (0, 0), step)
    assert pos == (132, 92)
    assert step["_last_matched_template"] in templates


# --- the list UI ------------------------------------------------------------


@requires_display
def test_listbox_shows_every_snip(multi) -> None:
    instance, root, _step, _templates = multi
    instance.populate_properties_panel()
    root.update()

    listbox = instance.properties_widgets["paths_listbox"]
    shown = [listbox.get(i) for i in range(listbox.size())]
    assert shown == ["bank.png", "tree.png", "rock.png"]


@requires_display
def test_listbox_marks_missing_files(multi, tmp_path) -> None:
    instance, root, step, _templates = multi
    step["paths"] = [str(tmp_path / "gone.png")]
    instance.populate_properties_panel()
    root.update()

    listbox = instance.properties_widgets["paths_listbox"]
    assert "missing" in listbox.get(0)


@requires_display
def test_removing_one_snip_keeps_the_rest(multi) -> None:
    instance, root, step, _templates = multi
    instance.populate_properties_panel()
    root.update()

    listbox = instance.properties_widgets["paths_listbox"]
    listbox.selection_set(1)  # tree.png
    instance.remove_step_template()
    root.update()

    assert [p.rsplit("/", 1)[-1] for p in step["paths"]] == ["bank.png", "rock.png"]
    assert step["path"].endswith("bank.png"), "path should mirror the first entry"


@requires_display
def test_clearing_empties_the_step(multi) -> None:
    instance, root, step, _templates = multi
    instance.populate_properties_panel()
    root.update()

    instance.clear_step_templates()
    root.update()

    assert step["paths"] == []
    assert step["path"] == ""


@requires_display
def test_adding_files_appends_without_duplicating(multi, tmp_path, monkeypatch) -> None:
    instance, root, step, templates = multi
    extra = tmp_path / "extra.png"
    cv2.imwrite(str(extra), np.zeros((10, 10), np.uint8))
    instance.populate_properties_panel()
    root.update()

    monkeypatch.setattr(
        "tkinter.filedialog.askopenfilenames",
        lambda **kwargs: (str(extra), templates["bank.png"][0]),
    )
    instance.add_step_templates()
    root.update()

    names = [p.rsplit("/", 1)[-1] for p in step["paths"]]
    assert names == ["bank.png", "tree.png", "rock.png", "extra.png"], "existing snip must not duplicate"


@requires_display
def test_snip_accumulates_rather_than_replacing(multi, tmp_path, monkeypatch) -> None:
    """The snip button should add to the list, which is the whole point."""
    from PIL import Image

    instance, root, step, _templates = multi
    out = tmp_path / "fourth.png"
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kwargs: str(out))
    monkeypatch.setattr(instance, "_crop_frozen", lambda frozen, box: Image.new("RGB", (10, 10)))
    # drive the completion handler directly, skipping the interactive selection
    frame = Image.new("RGB", (40, 40))
    instance.begin_screen_selection = lambda on_selected, **kw: on_selected(frame, (0, 0, 10, 10))
    instance.snip_image_for_step()
    root.update()

    assert len(step["paths"]) == 4
    assert step["paths"][-1] == str(out)


# --- per-snip preview -------------------------------------------------------


def caption(instance) -> str:
    return instance.properties_widgets["png_preview_caption"].cget("text")


@requires_display
def test_preview_defaults_to_the_first_snip(multi) -> None:
    instance, root, _step, _templates = multi
    instance.populate_properties_panel()
    root.update()

    assert instance.properties_widgets["png_preview"].cget("image")
    assert "1 of 3" in caption(instance)
    assert "bank.png" in caption(instance)


@requires_display
def test_preview_follows_the_list_selection(multi) -> None:
    """With several snips the preview has to show which one you selected."""
    instance, root, _step, _templates = multi
    instance.populate_properties_panel()
    root.update()
    listbox = instance.properties_widgets["paths_listbox"]

    for index, name in enumerate(["bank.png", "tree.png", "rock.png"]):
        listbox.selection_clear(0, tk.END)
        listbox.selection_set(index)
        listbox.event_generate("<<ListboxSelect>>")
        root.update()
        assert f"{index + 1} of 3" in caption(instance)
        assert name in caption(instance)


@requires_display
def test_preview_reports_the_source_dimensions(multi) -> None:
    instance, root, _step, _templates = multi
    instance.populate_properties_panel()
    root.update()
    assert "(24x24)" in caption(instance), "the caption should state the template size"


@requires_display
def test_preview_thumbnail_fits_without_distorting(multi, tmp_path) -> None:
    from PIL import Image

    instance, root, step, _templates = multi
    tall = tmp_path / "tall.png"
    # Save a real, very tall image and point the step at it.
    Image.new("RGB", (30, 400)).save(tall)
    step["paths"] = [str(tall)]
    instance.populate_properties_panel()
    root.update()

    photo = instance.properties_widgets["png_preview"].image
    assert photo.width() <= 220 and photo.height() <= 90
    assert abs((30 / 400) - (photo.width() / photo.height())) < 0.02, "aspect ratio must be kept"


@requires_display
def test_preview_says_so_when_there_are_no_snips(multi) -> None:
    instance, root, _step, _templates = multi
    instance.clear_step_templates()
    root.update()
    assert "No snips yet" in caption(instance)


@requires_display
def test_preview_reports_a_missing_file(multi, tmp_path) -> None:
    instance, root, step, _templates = multi
    step["paths"] = [str(tmp_path / "gone.png")]
    instance.populate_properties_panel()
    root.update()

    assert "No Preview Available" in instance.properties_widgets["png_preview"].cget("text")


@requires_display
def test_new_snip_becomes_the_previewed_one(multi, tmp_path, monkeypatch) -> None:
    """After snipping, the preview should show what you just captured."""
    from PIL import Image

    instance, root, step, _templates = multi
    out = tmp_path / "fresh.png"
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kwargs: str(out))
    frame = Image.new("RGB", (40, 40))
    monkeypatch.setattr(instance, "begin_screen_selection", lambda cb, **kw: cb(frame, (0, 0, 20, 20)))
    # a real 20x20 crop out of a real frame, so _crop_frozen's scaling is a no-op
    monkeypatch.setattr(instance, "_crop_frozen", lambda frozen, box: Image.new("RGB", (20, 20)))

    instance.snip_image_for_step()
    root.update()

    assert step["paths"][-1] == str(out)
    assert "fresh.png" in caption(instance)
    assert instance.properties_widgets["paths_listbox"].curselection() == (len(step["paths"]) - 1,)
