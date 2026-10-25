from dataclasses import replace

import pytest
from conftest import render_frame
from PIL import Image, ImageDraw

from tfc_forge_helper.profile import Profile
from tfc_forge_helper.vision import DetectionError, Detector


@pytest.mark.parametrize("scale,origin", [(1, (101, 83)), (2, (103, 57)), (3, (107, 53)), (4, (23, 19))])
def test_auto_scale_and_moved_window(atlas, scale, origin):
    image = render_frame(atlas, scale=scale, origin=origin, history=("shrink", "bend", "hit_hard"))
    observation = Detector(atlas).detect(image)
    assert (observation.current, observation.target) == (83, 108)
    assert [r.name for r in observation.rules] == ["hit_third_last", "draw_second_last", "draw_last"]
    assert [a.category for a in observation.history] == ["shrink", "bend", "hit"]
    assert observation.region == (*origin, 176 * scale, 207 * scale)
    assert observation.scale == scale


@pytest.mark.parametrize("history", [(), ("punch",), ("upset", "draw"), ("hit_light", "hit_medium", "hit_hard")])
def test_short_history_and_rule_counts(atlas, history):
    image = render_frame(atlas, rules=("punch_any",), history=history, tinted_green=True)
    result = Detector(atlas).detect(image)
    assert [a.category for a in result.history] == ["hit" if h.startswith("hit_") else h for h in history]
    assert [r.name for r in result.rules] == ["punch_any"]


def test_no_gui_rejected(atlas):
    with pytest.raises(DetectionError):
        Detector(atlas).detect(Image.new("RGB", (1280, 720), "#333333"))


def test_blank_anvil_rejected(atlas):
    image = Image.new("RGB", (1000, 720), "black")
    image.paste(atlas.image.crop((0, 0, 176, 207)).resize((352, 414), Image.Resampling.NEAREST), (100, 50))
    with pytest.raises(DetectionError):
        Detector(atlas).detect(image)


def test_occlusion_rejected(atlas):
    image = render_frame(atlas)
    ImageDraw.Draw(image).rectangle((200, 65, 350, 140), fill="black")
    with pytest.raises(DetectionError):
        Detector(atlas).detect(image)


def test_manual_calibration_and_profile_roundtrip(atlas, tmp_path):
    profile = replace(Profile(), region=(103, 57, 352, 414))
    file = tmp_path / "profile.json"
    profile.save(file)
    assert Profile.load(file) == profile
    result = Detector(atlas, Profile.load(file)).detect(render_frame(atlas))
    assert result.current == 83


def test_reused_detector_revalidates_location_when_gui_moves(atlas):
    detector = Detector(atlas)
    first = detector.detect(render_frame(atlas, origin=(103, 57)))
    moved = detector.detect(render_frame(atlas, origin=(217, 91), current=85, target=110))
    assert first.region[:2] == (103, 57)
    assert moved.region[:2] == (217, 91)
    assert (moved.current, moved.target) == (85, 110)


@pytest.mark.parametrize("scale", [1, 2, 3])
def test_real_default_and_user_pack(reference_atlas, scale):
    image = render_frame(reference_atlas, scale=scale, origin=(101, 55), history=("bend", "draw"))
    result = Detector(reference_atlas).detect(image)
    assert (result.current, result.target) == (83, 108)
    assert [r.name for r in result.rules] == ["hit_third_last", "draw_second_last", "draw_last"]
    assert [a.name.lower() for a in result.history] == ["bend", "draw"]


def test_every_rule_and_both_tints(reference_atlas):
    from tfc_forge_helper.model import CATEGORIES, ORDER_ROWS
    detector = Detector(reference_atlas, replace(Profile(), region=(103, 57, 352, 414)))
    for category in CATEGORIES:
        for order in ORDER_ROWS:
            rule = f"{category}_{order}"
            for green in (False, True):
                image = render_frame(reference_atlas, rules=(rule,), tinted_green=green)
                result = detector.detect(image)
                assert [r.name for r in result.rules] == [rule]


def test_user_screenshot_with_stack_digits_and_batch_source(reference_atlas):
    from pathlib import Path

    import numpy as np

    from tfc_forge_helper.automation import Frame
    from tfc_forge_helper.batch import Icon, InventoryView
    from tfc_forge_helper.model import Action
    from tfc_forge_helper.vision import distance

    path = Path(__file__).resolve().parents[1] / "work/reference/user-anvil-screen.png"
    if not path.is_file():
        pytest.skip("用户实机截图未提供；不随源代码分发")
    image = Image.open(path).convert("RGB")
    detector = Detector(reference_atlas)
    if Path(reference_atlas.source).name == "anvil.png":
        with pytest.raises(DetectionError):
            detector.detect(image)  # The wrong atlas must not be silently accepted.
        return
    observation = detector.detect(image)
    assert (observation.current, observation.target, observation.scale) == (0, 88, 3)
    assert {r.name for r in observation.rules} == {"hit_last", "hit_second_last", "hit_third_last"}
    assert observation.confidence > .985
    view = InventoryView(Frame(image, (0, 0), 123, 1), detector, Profile())
    raw = Icon.capture(view.crop((22, 76)), view.background((22, 76)))
    assert raw.error(view.crop((134, 183))) < .01  # Hotbar 8, stack glyph '16'.
    bx, by = Action.BEND.button
    expected = reference_atlas.image.crop((bx, by, bx + 16, by + 16))
    expected.alpha_composite(reference_atlas.image.crop((16, 240, 32, 256)))
    assert distance(np.array(view.crop((bx, by))), np.array(expected.convert("RGB"))) < .015
