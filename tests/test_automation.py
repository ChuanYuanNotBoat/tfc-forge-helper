import threading

import pytest
from conftest import render_frame
from PIL import Image, ImageDraw

from tfc_forge_helper.automation import AutoForge, AutomationStopped, Frame
from tfc_forge_helper.engine import Config
from tfc_forge_helper.model import Action
from tfc_forge_helper.profile import Profile


class FakeEngine:
    def __init__(self, atlas, pid=123, change_resources=False):
        self.atlas, self.pid, self.revision = atlas, pid, 1
        self.change_resources, self.calls = change_resources, 0

    def refresh(self, config):
        self.calls += 1
        if self.change_resources and self.calls >= 2:
            self.revision = 2
        return self.atlas, Profile()


class FakeGame:
    """A deterministic game model; never imports or calls the Windows input backend."""
    def __init__(self, atlas, current=83, target=108,
                 rules=("hit_third_last", "draw_second_last", "draw_last"),
                 history=(), behavior="normal", cancel=None):
        self.atlas, self.current, self.target = atlas, current, target
        self.rules, self.history, self.behavior = rules, history, behavior
        self.clicks, self.cancel = [], cancel

    def frame(self, pid):
        if self.clicks and self.behavior == "lost_focus":
            raise AutomationStopped("游戏已失去焦点")
        image = render_frame(self.atlas, self.current, self.target, self.rules, self.history)
        if self.behavior == "obscured_button":
            ImageDraw.Draw(image).rectangle((103 + 89 * 2, 57 + 56 * 2,
                                            103 + 105 * 2 - 1, 57 + 72 * 2 - 1), fill="black")
        if self.clicks and self.behavior == "recipe_reset":
            gui = self.atlas.image.crop((0, 0, 176, 207)).resize((352, 414), Image.Resampling.NEAREST)
            image.paste(gui, (103, 57))
        return Frame(image, (1000, 100), pid, 999)

    def click(self, frame, point, neutral, cancel):
        if self.clicks and self.behavior == "lost_focus":
            raise AutomationStopped("游戏已失去焦点")
        centers = {a: (103 + (a.button[0] + 8) * 2, 57 + (a.button[1] + 8) * 2) for a in Action}
        action = next(a for a, center in centers.items() if center == point)
        self.clicks.append(action)
        if self.behavior == "cancel":
            cancel.set()
        elif self.behavior != "ignored":
            self.current += action.delta + (1 if self.behavior == "wrong_delta" else 0)
            self.history = (self.history + (action.name.lower(),))[-3:]
        if self.behavior == "recipe_changed":
            self.target += 1


def run(atlas, backend, **kwargs):
    return AutoForge(FakeEngine(atlas), backend, timeout=.15, settle=0).run(
        Config(), threading.Event(), countdown=0, **kwargs)


def test_full_sequence_with_verified_completion(atlas):
    game = FakeGame(atlas)
    result = run(atlas, game)
    assert result.clicks == len(game.clicks) == 7
    assert result.verified
    assert game.current == 108


def test_real_pack_buttons_and_closed_loop(reference_atlas):
    game = FakeGame(reference_atlas)
    result = run(reference_atlas, game)
    assert result.verified and result.clicks == 7


@pytest.mark.parametrize("behavior,expected_clicks", [("ignored", 7), ("wrong_delta", 7),
                                                    ("lost_focus", 1), ("recipe_changed", 7), ("cancel", 1)])
def test_failed_sequence_never_retried(atlas, behavior, expected_clicks):
    game = FakeGame(atlas, behavior=behavior)
    with pytest.raises(AutomationStopped):
        run(atlas, game)
    assert len(game.clicks) == expected_clicks


def test_button_obscured_sends_no_click(atlas):
    game = FakeGame(atlas, current=100, target=102, rules=("punch_last",), behavior="obscured_button")
    with pytest.raises(AutomationStopped, match="按钮"):
        run(atlas, game)
    assert not game.clicks


def test_missing_process_and_resource_changes_send_no_click(atlas):
    game = FakeGame(atlas)
    for engine in (FakeEngine(atlas, pid=None), FakeEngine(atlas, change_resources=True)):
        with pytest.raises(AutomationStopped):
            AutoForge(engine, game).run(Config(), threading.Event(), countdown=0)
    assert not game.clicks


def test_cancelled_before_start_sends_no_click(atlas):
    stop = threading.Event()
    stop.set()
    game = FakeGame(atlas)
    with pytest.raises(AutomationStopped):
        AutoForge(FakeEngine(atlas), game).run(Config(), stop, countdown=0)
    assert not game.clicks


def test_recipe_reset_after_last_action_stops_without_claiming_verified_success(atlas):
    game = FakeGame(atlas, current=100, target=102, rules=("punch_last",), behavior="recipe_reset")
    result = run(atlas, game)
    assert result.clicks == 1
    assert not result.verified
    assert "核对成品" in result.message


def test_already_complete_sends_no_click(atlas):
    game = FakeGame(atlas, current=102, target=102, rules=("punch_last",), history=("punch",))
    result = run(atlas, game)
    assert result.verified and result.clicks == 0


def test_seven_actions_use_one_plan_and_only_initial_final_frames(atlas, monkeypatch):
    from unittest.mock import Mock

    from tfc_forge_helper import automation

    game = FakeGame(atlas)
    game.frame = Mock(wraps=game.frame)
    solver = Mock(wraps=automation.solve)
    monkeypatch.setattr(automation, "solve", solver)
    result = run(atlas, game)
    assert result.verified and result.clicks == 7
    solver.assert_called_once()
    assert game.frame.call_count == 2


def test_all_planned_buttons_are_checked_before_first_click(atlas):
    game = FakeGame(atlas)
    original = game.frame
    def obscured_final_button(pid):
        frame = original(pid)
        # Draw is used at the end of this plan, after several other actions.
        ImageDraw.Draw(frame.image).rectangle((103 + 71 * 2, 57 + 74 * 2,
                                              103 + 87 * 2 - 1, 57 + 90 * 2 - 1), fill="black")
        return frame
    game.frame = obscured_final_button
    with pytest.raises(AutomationStopped, match="按钮"):
        run(atlas, game)
    assert not game.clicks


def test_delayed_completion_waits_without_replaying_sequence(atlas):
    game = FakeGame(atlas)
    original = game.frame
    initial = original(123)
    calls = []
    def delayed_frame(pid):
        calls.append(pid)
        if len(calls) < 4:
            return initial
        return original(pid)
    game.frame = delayed_frame
    result = run(atlas, game)
    assert result.verified and result.clicks == len(game.clicks) == 7
    assert len(calls) == 4


def test_cancel_between_planned_actions_stops_before_next_click(atlas):
    class CancelAfterFirstWait(threading.Event):
        def wait(self, timeout=None):
            self.set()
            return True
    game = FakeGame(atlas)
    stop = CancelAfterFirstWait()
    with pytest.raises(AutomationStopped, match="停止"):
        AutoForge(FakeEngine(atlas), game).run(Config(), stop, countdown=0)
    assert len(game.clicks) == 1


def test_confirmed_frame_from_another_process_is_rejected_before_click(atlas):
    from dataclasses import replace

    game = FakeGame(atlas)
    frame = replace(game.frame(123), pid=456)
    with pytest.raises(AutomationStopped, match="进程"):
        AutoForge(FakeEngine(atlas), game).run(Config(), threading.Event(), countdown=0, initial_frame=frame)
    assert not game.clicks
