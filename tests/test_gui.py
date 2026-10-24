"""Exercise the real UI completion path without windows, hotkeys, or game input."""

import queue
import threading
import tkinter as tk
from concurrent.futures import Future
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import render_frame
from PIL import ImageDraw

from tfc_forge_helper.engine import Analysis
from tfc_forge_helper.gui import App
from tfc_forge_helper.model import Action, Rule
from tfc_forge_helper.solver import solve
from tfc_forge_helper.vision import DetectionError, Detector


@pytest.fixture
def app():
    interpreter = tk.Tcl()
    window = App.__new__(App)
    window.root = Mock()
    window.engine = SimpleNamespace(revision=1, candidates=[])
    window.future = None
    window.generation = 0
    window.updating = False
    window.closed = False
    window.last_auto = 0
    window.last_refresh = 0
    window.last_source = ""
    window.last_solution = None
    window.last_capture_key = None
    window.source_revision = 0
    window.pending_forging = False
    window.forge_stop = threading.Event()
    window.forge_messages = queue.Queue()
    window.hotkeys = queue.Queue()
    window.live = tk.BooleanVar(interpreter, False)
    window.allow_forging = tk.BooleanVar(interpreter, False)
    for name in ("current", "target", "history", "next_step", "summary", "overlay_text",
                 "status", "resource_status"):
        setattr(window, name, tk.StringVar(interpreter, "等待识别"))
    window.rule_vars = [(tk.StringVar(interpreter, "无"), tk.StringVar(interpreter, "")) for _ in range(3)]
    for variable in (window.current, window.target, window.history,
                     *(var for pair in window.rule_vars for var in pair)):
        variable.trace_add("write", window._changed)
    window.table = Mock()
    window.table.get_children.return_value = ()
    window.bar = Mock()
    window.bar.winfo_width.return_value = 400
    window.instance_combo = Mock()
    window._render = Mock(wraps=window._render)
    window._resource_info = Mock()
    return window


@pytest.fixture
def analysis(atlas):
    observation = Detector(atlas).detect(render_frame(atlas))
    solution = solve(observation.current, observation.target, observation.rules, observation.history)
    return Analysis(observation, solution, atlas, "test instance")


def complete(app, result, kind="auto_capture", generation=None):
    future = Future()
    if isinstance(result, Exception):
        future.set_exception(result)
    else:
        future.set_result(result)
    app.future = future
    app.future_kind = kind
    app.future_generation = app.generation if generation is None else generation
    app._poll()


def display(app):
    return tuple(getattr(app, name).get() for name in
                 ("current", "target", "history", "next_step", "summary", "overlay_text", "status"))


def test_occluded_frame_and_recovery_preserve_unfinished_plan(app, analysis, atlas):
    complete(app, analysis)
    original = display(app)
    frame = render_frame(atlas)
    ImageDraw.Draw(frame).rectangle((200, 65, 350, 140), fill="black")
    with pytest.raises(DetectionError) as error:
        Detector(atlas).detect(frame)
    complete(app, error.value)
    assert display(app) == original
    assert app.last_solution is analysis.solution
    complete(app, analysis)
    assert display(app) == original
    assert app._render.call_count == app.table.delete.call_count == 1
    assert app._resource_info.call_count == 1


def test_confidence_position_scale_and_hit_strength_do_not_redraw_same_state(app, analysis):
    analysis = replace(analysis, observation=replace(analysis.observation, history=(Action.HIT_LIGHT,)))
    complete(app, analysis)
    original = display(app)
    changed = replace(analysis.observation, confidence=.95, region=(1, 2, 528, 621),
                      scale=3, history=(Action.HIT_HARD,))
    complete(app, replace(analysis, observation=changed))
    assert display(app) == original
    assert app._render.call_count == app.table.delete.call_count == 1
    assert app.generation == 0  # Programmatic updates never invalidate their own result.


@pytest.mark.parametrize("change", [{"current": 85}, {"target": 110},
                                  {"rules": (Rule("punch", "last"),)}, {"history": (Action.PUNCH,)}])
def test_valid_forging_state_change_updates_plan(app, analysis, change):
    complete(app, analysis)
    obs = replace(analysis.observation, **change)
    solution = solve(obs.current, obs.target, obs.rules, obs.history)
    complete(app, replace(analysis, observation=obs, solution=solution))
    assert app.last_solution is solution
    assert app._render.call_count == 2
    assert app.current.get() == str(obs.current)
    assert app.target.get() == str(obs.target)
    assert app.history.get() == ",".join(a.category for a in obs.history)


def test_initial_auto_miss_keeps_waiting_display(app):
    original = display(app)
    complete(app, DetectionError("未识别到配方指针"))
    assert display(app) == original
    assert app.last_solution is None
    app._render.assert_not_called()


def test_manual_capture_still_reports_a_failed_read(app, analysis):
    complete(app, analysis)
    complete(app, DetectionError("规则被遮挡"), kind="capture")
    assert app.last_solution is None
    assert app.status.get() == "规则被遮挡"
    assert app.last_capture_key is None


@pytest.mark.parametrize("error", [OSError("截图失败"), ValueError("没有可行方案"), RuntimeError("异常")])
def test_other_background_failures_remain_visible(app, analysis, error):
    complete(app, analysis)
    complete(app, error)
    assert app.last_solution is None
    assert app.status.get() == str(error)


def test_resource_switch_invalidates_retained_plan_even_if_next_frame_is_obscured(app, analysis):
    complete(app, analysis)
    app.engine.revision += 1
    complete(app, DetectionError("匹配度不足"))
    assert app.last_solution is None
    assert "资源已变化" in app.status.get()


def test_valid_state_from_new_resources_is_presented_again(app, analysis):
    complete(app, analysis)
    app.engine.revision += 1
    complete(app, analysis)
    assert app.source_revision == app.engine.revision
    assert app._render.call_count == 2


def test_edit_clears_retained_result_and_allows_same_state_to_be_read_again(app, analysis):
    complete(app, analysis)
    app.current.set("12")
    assert app.last_solution is None
    assert app.last_capture_key is None
    assert app.forge_stop.is_set()
    complete(app, analysis)
    assert app.last_solution is analysis.solution
    assert app._render.call_count == 2


def test_pause_retains_plan_and_discards_inflight_result(app, analysis):
    complete(app, analysis)
    generation = app.generation
    previous_plan = app.last_solution
    app._live_changed()
    complete(app, replace(analysis, observation=replace(analysis.observation, current=85)), generation=generation)
    assert app.last_solution is previous_plan
    assert app.current.get() == "83"
    assert "暂停" in app.status.get()
    assert app._render.call_count == 1


def test_background_submission_does_not_replace_status_with_loading_text(app):
    app.pool = Mock()
    app.pool.submit.return_value = Future()
    original = app.status.get()
    app._submit("auto_capture", lambda: None)
    assert app.status.get() == original
    assert app.future_kind == "auto_capture"


def test_next_auto_capture_waits_one_second_after_previous_finishes(app, analysis, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("tfc_forge_helper.gui.time.monotonic", lambda: clock[0])
    app.live.set(True)
    app.capture = Mock()
    complete(app, analysis)
    app.capture.assert_not_called()
    clock[0] = 10.9
    app._poll()
    app.capture.assert_not_called()
    clock[0] = 11.1
    app._poll()
    app.capture.assert_called_once_with(automatic=True)


def test_forging_failure_does_not_keep_passive_plan(app, analysis):
    complete(app, analysis)
    app.allow_forging.set(True)
    complete(app, DetectionError("自动执行中识别失败"), kind="forge")
    assert not app.allow_forging.get()
    assert app.last_solution is None
    assert app.status.get() == "自动执行中识别失败"
