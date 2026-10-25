import threading
from dataclasses import replace

import pytest
from conftest import render_frame
from PIL import Image, ImageDraw

from tfc_forge_helper.automation import AutomationStopped, Frame
from tfc_forge_helper.batch import BatchForge
from tfc_forge_helper.engine import Config
from tfc_forge_helper.model import Action
from tfc_forge_helper.profile import Profile


class InventoryGame:
    """Independent simplified container model; never sends native mouse/keys."""
    def __init__(self, atlas, supplies=2, behavior="normal", output_count=1, recipes=None):
        image = atlas.image.copy()
        ImageDraw.Draw(image).rectangle((218, 0, 235, 17), fill="#b8b8b8")
        self.atlas = replace(atlas, image=image)
        self.supplies = {(8, 183): supplies} if supplies else {}
        self.input = "raw"
        self.cursor = None
        self.current, self.history = 0, ()
        self.recipes = recipes or [(0, 2, ("punch_last",))]
        self.current, self.target, self.rules = self.recipes[0]
        self.actions = []
        self.collected, self.forged = 0, 0
        self.calls = []
        self.behavior, self.output_count = behavior, output_count
        self.pid, self.revision = 123, 1

    def refresh(self, config):
        return self.atlas, Profile()

    @staticmethod
    def icon(kind):
        image = Image.new("RGBA", (16, 16))
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, 13, 9), fill="#c12f38" if kind == "raw" else "#2473da")
        draw.line((3, 4, 12, 4), fill="#ffd8ac" if kind == "raw" else "#a8eaff", width=2)
        return image

    def frame(self, pid):
        if self.calls and self.behavior == "lost_focus":
            raise AutomationStopped("游戏失去焦点")
        screen = render_frame(self.atlas, current=self.current, target=self.target,
                              rules=self.rules, history=self.history)
        gui = screen.crop((103, 57, 455, 471)).resize((176, 207), Image.Resampling.NEAREST).convert("RGBA")
        gui.alpha_composite(self.icon("output"), (138, 57))
        if self.input:
            gui.alpha_composite(self.icon(self.input), (22, 76))
        for point, count in self.supplies.items():
            if count:
                gui.alpha_composite(self.icon("raw"), point)
                if count > 1:
                    ImageDraw.Draw(gui).rectangle((point[0] + 10, point[1] + 11,
                                                  point[0] + 14, point[1] + 14), fill="white")
        if self.collected:
            gui.alpha_composite(self.icon("output"), (8, 125))
        if self.cursor:
            gui.alpha_composite(self.icon(self.cursor[0]), (137, 12))
        screen.paste(gui.resize((352, 414), Image.Resampling.NEAREST).convert("RGB"), (103, 57))
        return Frame(screen, (1000, 100), pid, 999)

    def move(self, frame, point, cancel):
        pass

    def click(self, frame, point, neutral, cancel, shift=False):
        self.calls.append((point, shift))
        logical = (round((point[0] - 103) / 2 - 8), round((point[1] - 57) / 2 - 8))
        action = next((a for a in Action if a.button == logical), None)
        if action is not None:
            if self.behavior == "ignored_forge":
                return
            assert self.input == "raw"
            from tfc_forge_helper.model import parse_rules
            self.actions.append(action)
            self.current += action.delta
            self.history = (self.history + (action.name.lower(),))[-3:]
            categories = tuple(Action.parse(a).category for a in self.history)
            if self.current == self.target and all(r.matches(categories) for r in parse_rules(",".join(self.rules))):
                self.input = "output"
                self.forged += 1
        elif logical == (22, 76):
            if shift:
                assert self.input == "output" and self.cursor is None
                if self.behavior == "full":
                    return
                self.collected += self.output_count
                self.input = None
                self.current, self.history = 0, ()
            else:
                assert self.input is None and self.cursor and self.cursor[0] == "raw"
                self.input = "raw"
                self.current, self.target, self.rules = self.recipes[self.forged % len(self.recipes)]
                self.history = ()
                remaining = self.cursor[1] - 1
                self.cursor = ("raw", remaining) if remaining else None
        elif logical in ((8, 183), (26, 183)):
            if self.behavior == "ignored_pickup":
                return
            if self.cursor is None:
                assert self.supplies.get(logical, 0) > 0
                self.cursor = ("raw", self.supplies.pop(logical))
                if self.behavior == "cancel_transfer":
                    cancel.set()
            else:
                assert self.supplies.get(logical, 0) == 0
                self.supplies[logical] = self.cursor[1]
                self.cursor = None
        else:
            raise AssertionError(f"unexpected inventory click: {logical}")


def execute(game, count=0, stop=None):
    return BatchForge(game, game, timeout=.22, settle=0).run(
        Config(), stop or threading.Event(), count=count, countdown=0)


@pytest.mark.parametrize("supply,count,expected", [(2, 0, 3), (5, 2, 2), (0, 0, 1), (1, 10, 2)])
def test_auto_feeding_collection_and_quantity(atlas, supply, count, expected):
    game = InventoryGame(atlas, supplies=supply)
    result = execute(game, count)
    assert result.completed == game.forged == game.collected == expected
    assert game.cursor is None and game.input is None
    assert result.verified


def test_multiple_supply_stacks_and_multi_item_output(atlas):
    game = InventoryGame(atlas, supplies=1, output_count=2)
    game.supplies[(26, 183)] = 2
    result = execute(game)
    assert result.completed == 4 and game.collected == 8
    assert game.cursor is None


def test_full_inventory_keeps_output_on_anvil(atlas):
    game = InventoryGame(atlas, behavior="full")
    result = execute(game)
    assert result.completed == 1 and not result.verified
    assert game.input == "output" and game.collected == 0
    assert len(game.calls) == 2  # One forge action, one collection attempt.


@pytest.mark.parametrize("behavior", ["ignored_forge", "ignored_pickup", "lost_focus", "cancel_transfer"])
def test_uncertain_transfer_or_focus_stops_without_retry(atlas, behavior):
    game = InventoryGame(atlas, behavior=behavior)
    with pytest.raises(AutomationStopped):
        execute(game)
    if behavior == "ignored_pickup":
        assert len(game.calls) == 3  # No retry or placement after failed pickup.
    if behavior == "cancel_transfer":
        assert game.cursor is not None and game.input is None


def test_no_input_or_cursor_item_stops_before_click(atlas):
    for kind in ("empty", "cursor"):
        game = InventoryGame(atlas)
        if kind == "empty":
            game.input = None
        else:
            game.cursor = ("raw", 1)
        with pytest.raises(AutomationStopped):
            execute(game)
        assert not game.calls


def test_quantity_validation(atlas):
    game = InventoryGame(atlas)
    with pytest.raises(ValueError):
        execute(game, -1)
    assert not game.calls


def test_each_item_rereads_random_target_rules_and_current(atlas):
    recipes = [
        (0, 2, ("punch_last",)),
        (0, 13, ("upset_last",)),
        (10, 7, ("hit_last",)),
        (0, 16, ("shrink_last",)),
    ]
    game = InventoryGame(atlas, supplies=3, recipes=recipes)
    result = execute(game)
    assert result.completed == 4 and game.collected == 4
    assert game.actions == [Action.PUNCH, Action.UPSET, Action.HIT_LIGHT, Action.SHRINK]


def test_batch_recognizes_full_forging_state_once_per_item(atlas, monkeypatch):
    from tfc_forge_helper.vision import Detector

    detected = []
    original = Detector.detect
    def count_detection(detector, image):
        observation = original(detector, image)
        detected.append((observation.current, observation.target, observation.rules))
        return observation
    monkeypatch.setattr(Detector, "detect", count_detection)
    game = InventoryGame(atlas, supplies=2)
    result = execute(game)
    assert result.verified and result.completed == 3
    assert len(detected) == 3


def test_ready_inventory_transfer_never_inserts_an_idle_wait(atlas):
    game = InventoryGame(atlas, supplies=2)
    class ImmediateFeedback(threading.Event):
        def wait(self, timeout=None):
            assert not (timeout and game.cursor), "Confirmed pickup/placement should continue immediately"
            return self.is_set()
    result = BatchForge(game, game).run(Config(), ImmediateFeedback(), count=3, countdown=0)
    assert result.verified and result.completed == 3
    assert game.cursor is None


def test_confirmed_output_is_not_screenshotted_again_before_collection(atlas):
    game = InventoryGame(atlas, supplies=2)
    original = game.frame
    output_reads = []
    def count_output_reads(pid):
        if game.input == "output":
            output_reads.append(game.forged)
        return original(pid)
    game.frame = count_output_reads
    result = execute(game)
    assert result.verified and result.completed == 3
    assert output_reads == [1, 2, 3]


def test_delayed_pickup_is_confirmed_before_placement_without_retry(atlas):
    game = InventoryGame(atlas, supplies=1)
    original_frame, original_click = game.frame, game.click
    pending = []
    def delayed_click(frame, point, neutral, cancel, shift=False):
        assert not pending, "A new click must wait until the prior transfer is visible"
        before = original_frame(game.pid)
        original_click(frame, point, neutral, cancel, shift=shift)
        if game.cursor:
            pending.append(before)
    def delayed_frame(pid):
        return pending.pop() if pending else original_frame(pid)
    game.click, game.frame = delayed_click, delayed_frame
    result = execute(game)
    assert result.verified and result.completed == 2
    assert len(game.calls) == 6  # Two forge, two collect, pickup and placement; no retries.
