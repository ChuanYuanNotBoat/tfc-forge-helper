from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from tfc_forge_helper.assets import ResolvedAtlas


@pytest.fixture
def atlas():
    # Original diagnostic art: no TFC resource is distributed with this project.
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 175, 206), fill="#b8b8b8", outline="#eeeeee", width=2)
    for row in range(4):
        for col in range(9):
            x, y = 7 + col * 18, 124 + row * 18
            draw.rectangle((x, y, x + 17, y + 17), fill="#888888", outline="#eeeeee")
    for x in (59, 78, 97):
        draw.rectangle((x, 13, x + 19, 34), fill="#808080")
    draw.rectangle((7, 100, 168, 105), fill="#555555")
    draw.polygon([(176, 0), (180, 0), (178, 4)], fill="#00e688")
    draw.polygon([(181, 4), (185, 4), (183, 0)], fill="#ff3344")
    rng = np.random.default_rng(721)
    for x in range(0, 128, 16):
        icon = np.zeros((16, 16, 4), dtype=np.uint8)
        icon[2:14, 2:14, :3] = rng.integers(50, 230, (12, 12, 3))
        icon[2:14, 2:14, 3] = 255
        image.alpha_composite(Image.fromarray(icon), (x, 224))
    for i in range(5):
        y = i * 22
        draw = ImageDraw.Draw(image)
        draw.rectangle((198, y, 217, y + 21), outline="white")
        draw.line((199, y + 17 + i % 4, 216, y + 17 + i % 4), fill="white", width=1 + i % 2)
        draw.line((199 + i * 3, y + 16, 199 + i * 3, y + 20), fill="white")
    return ResolvedAtlas(image, "diagnostic", (), ())


def render_frame(atlas, current=83, target=108,
                 rules=("hit_third_last", "draw_second_last", "draw_last"),
                 history=(), scale=2, origin=(103, 57), tinted_green=False):
    """Independent rendering of pinned AnvilScreen coordinates, not Detector code."""
    image = atlas.image.copy()
    gui = image.crop((0, 0, 176, 207))
    for ux, button in ((64, (53, 56)), (80, (71, 56)), (96, (53, 74)), (112, (71, 74)),
                       (0, (89, 56)), (16, (107, 56)), (32, (89, 74)), (48, (107, 74))):
        gui.alpha_composite(image.crop((ux, 240, ux + 16, 256)), button)
    gui.alpha_composite(image.crop((176, 0, 181, 5)), (11 + current, 104))
    gui.alpha_composite(image.crop((181, 0, 186, 5)), (11 + target, 98))
    icon_positions = {"hit": 64, "hit_light": 64, "hit_medium": 80, "hit_hard": 96,
                      "draw": 112, "punch": 0, "bend": 16, "upset": 32, "shrink": 48}
    order_rows = {"last": 0, "second_last": 22, "third_last": 44, "not_last": 66, "any": 88}
    for index, rule in enumerate(rules):
        category, _, order = rule.partition("_")
        ux = icon_positions[category]
        gui.alpha_composite(image.crop((ux, 224, ux + 16, 240)), (61 + index * 19, 13))
        y = order_rows[order]
        overlay = image.crop((198, y, 218, y + 22))
        rgba = np.asarray(overlay).copy()
        rgba[:, :, :3] = np.rint(rgba[:, :, :3] * np.array((0, .6, .2) if tinted_green else (1, .4, 0))).astype(np.uint8)
        gui.alpha_composite(Image.fromarray(rgba), (59 + index * 19, 13))
    for index, action in enumerate(history):
        ux = icon_positions[action]
        gui.alpha_composite(image.crop((ux, 224, ux + 16, 240)), (99 - index * 19, 34))
    screen = Image.new("RGB", (max(1000, 176 * scale + origin[0] + 30),
                               max(720, 207 * scale + origin[1] + 30)), "#29373e")
    screen.paste(gui.resize((176 * scale, 207 * scale), Image.Resampling.NEAREST), origin)
    return screen


@pytest.fixture(params=["anvil.png", "sample-anvil.png"])
def reference_atlas(request):
    path = Path(__file__).resolve().parents[1] / "work" / "reference" / request.param
    if not path.is_file():
        pytest.skip("本地真实贴图集成样本未提供；诊断贴图测试仍运行")
    return ResolvedAtlas(Image.open(path).convert("RGBA"), str(path), (), ())
