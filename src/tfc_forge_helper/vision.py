"""Atlas-driven recognition. No OCR, color constants for pointers, or game IO."""
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from .assets import ResolvedAtlas
from .model import CATEGORIES, ORDER_ROWS, Action, Rule
from .profile import Profile


class DetectionError(ValueError):
    pass


@dataclass(frozen=True)
class Observation:
    current: int
    target: int
    rules: tuple[Rule, ...]
    history: tuple[Action, ...]
    region: tuple[int, int, int, int]
    scale: float
    confidence: float


def distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2)) / 255)


class Detector:
    def __init__(self, atlas: ResolvedAtlas, profile: Profile | None = None):
        profile = profile or Profile()
        self.profile = profile
        self.atlas = atlas.image
        self.background = self.atlas.crop((0, 0, profile.gui_width, profile.gui_height))
        self._rules = [Rule(c, o) for c in CATEGORIES for o in ORDER_ROWS]
        self._rule_images = []
        self._last_location = None
        for rule in self._rules:
            self._rule_images.append((rule, [self._rule_patch(rule, tint) for tint in ((1, .4, 0), (0, .6, .2))]))

    def _icon(self, action: Action) -> Image.Image:
        return self.atlas.crop((action.icon_x, 224, action.icon_x + 16, 240))

    def _rule_patch(self, rule: Rule, tint: tuple[float, ...]) -> np.ndarray:
        p = self.profile
        # All three rule slots normally share the same background.
        patch = self.background.crop((p.rule_x, p.rule_y, p.rule_x + 20, p.rule_y + 22))
        action = next(a for a in Action if a.category == rule.category)
        patch.alpha_composite(self._icon(action), (2, 0))
        overlay = self.atlas.crop((198, ORDER_ROWS[rule.order], 218, ORDER_ROWS[rule.order] + 22))
        pixels = np.array(overlay)
        pixels[:, :, :3] = np.rint(pixels[:, :, :3].astype(float) * np.array(tint)).astype(np.uint8)
        patch.alpha_composite(Image.fromarray(pixels), (0, 0))
        return np.array(patch.convert("RGB"))

    def locate(self, screenshot: Image.Image) -> tuple[tuple[int, int, int, int], float, float]:
        p = self.profile
        if p.region is not None:
            x, y, w, h = p.region
            sx, sy = w / p.gui_width, h / p.gui_height
            if abs(sx - sy) > .04 * max(sx, sy):
                raise DetectionError("校准区域的宽高比例与 profile 不符，请框选完整砧 GUI")
            if x < 0 or y < 0 or x + w > screenshot.width or y + h > screenshot.height:
                raise DetectionError("校准区域已超出截图，请重新校准或清除固定位置")
            return p.region, sx, 1.0
        screen = np.array(screenshot.convert("RGB"))
        ax, ay, aw, ah = p.anchor
        anchor = self.background.crop((ax, ay, ax + aw, ay + ah)).convert("RGB")
        # Keep borders/grid lines; inventory item interiors and text do not participate.
        mask = np.zeros((ah, aw), np.uint8)
        mask[:, :3] = mask[:, -3:] = 255
        # Count glyphs and heat bars extend beyond the lower item interior.
        # Keep only grid tops separated from counts, plus upper vertical edges.
        for yy in (124, 182):
            row = yy - ay
            if 0 <= row < ah:
                mask[row:min(ah, row + 1)] = 255
        for xx in range(7, 171, 18):
            col = xx - ax
            if 0 <= col < aw:
                for slot_y in (125, 143, 161, 183):
                    start, end = max(0, slot_y - ay), min(ah, slot_y + 7 - ay)
                    if start < end:
                        mask[start:end, max(0, col - 1):min(aw, col + 1)] = 255
        candidates = []
        template = np.array(anchor)
        if self._last_location is not None:
            region, last_scale = self._last_location
            x, y, w, h = region
            if x >= 0 and y >= 0 and x + w <= screenshot.width and y + h <= screenshot.height:
                patch = screenshot.crop((x, y, x + w, y + h)).resize(
                    (p.gui_width, p.gui_height), Image.Resampling.NEAREST).convert("RGB")
                actual = np.array(patch.crop((ax, ay, ax + aw, ay + ah)))
                score = 1 - distance(actual[mask > 0], template[mask > 0])
                if score >= p.threshold:
                    return region, last_scale, score
        for scale in p.scales:
            # Resize the screen down to logical pixels, avoiding giant masked convolutions.
            width, height = round(screenshot.width / scale), round(screenshot.height / scale)
            if width < p.gui_width or height < p.gui_height:
                continue
            if float(scale).is_integer():
                small = screen[::int(scale), ::int(scale)]
                height, width = small.shape[:2]
            else:
                small = cv2.resize(screen, (width, height), interpolation=cv2.INTER_NEAREST)
            scores = cv2.matchTemplate(small, template, cv2.TM_SQDIFF, mask=mask)
            minimum, _, location, _ = cv2.minMaxLoc(scores)
            x, y = location[0] - ax, location[1] - ay
            if x < 0 or y < 0 or x + p.gui_width > width or y + p.gui_height > height:
                continue
            error = (max(0, minimum) / (max(1, np.count_nonzero(mask)) * 3)) ** .5 / 255
            # Refine physical pixel phase: a moved window need not start at a
            # multiple of GUI scale (e.g. x=401 with scale=3).
            coarse_x, coarse_y = round(x * scale), round(y * scale)
            scaled = np.array(anchor.resize((round(aw * scale), round(ah * scale)), Image.Resampling.NEAREST))
            scaled_mask = cv2.resize(mask, (scaled.shape[1], scaled.shape[0]),
                                     interpolation=cv2.INTER_NEAREST) > 0
            # The coarse score samples one pixel phase only. It must never beat
            # a physical-pixel candidate that was actually checked on the frame.
            best = (float("inf"), coarse_x, coarse_y)
            radius = int(np.ceil(scale))
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    px, py = coarse_x + dx, coarse_y + dy
                    bx, by = px + round(ax * scale), py + round(ay * scale)
                    if min(px, py) < 0 or px + p.gui_width * scale > screenshot.width or py + p.gui_height * scale > screenshot.height:
                        continue
                    patch = screen[by:by + scaled.shape[0], bx:bx + scaled.shape[1]]
                    err = distance(patch[scaled_mask], scaled[scaled_mask])
                    if err <= best[0]:
                        best = (err, px, py)
            error, px, py = best
            candidates.append((1 - error, (px, py, round(p.gui_width * scale), round(p.gui_height * scale)), scale))
        if not candidates:
            raise DetectionError("未找到完整砧界面；请打开砧 GUI，或校准其区域")
        confidence, region, scale = max(candidates)
        if confidence < p.threshold:
            raise DetectionError(f"砧界面定位置信度不足（{confidence:.1%}），当前不显示方案")
        self._last_location = (region, scale)
        return region, scale, confidence

    def _classify(self, observed: np.ndarray, options: list[tuple[object, list[np.ndarray]]], what: str):
        ranked = sorted(((min(distance(observed, t) for t in images), index, key)
                         for index, (key, images) in enumerate(options)))
        error, _, key = ranked[0]
        if 1 - error < self.profile.threshold:
            raise DetectionError(f"{what}无法可靠识别（{1-error:.1%}），可检查材质或校准")
        if len(ranked) > 1 and ranked[1][0] - error < self.profile.margin:
            raise DetectionError(f"{what}有多个相似候选，当前不猜测")
        return key, 1 - error

    def detect(self, screenshot: Image.Image) -> Observation:
        p = self.profile
        region, scale, confidence = self.locate(screenshot)
        x, y, w, h = region
        gui = screenshot.crop((x, y, x + w, y + h)).resize(
            (p.gui_width, p.gui_height), Image.Resampling.NEAREST).convert("RGB")
        base = self.background.convert("RGB")
        scores = [confidence]
        values = []
        # Compare entire rows against all possible pointer positions. A blank bar
        # must win over the marker templates when no recipe is selected.
        for label, row, uv in (("当前位置", p.current_y, (176, 0)), ("目标位置", p.target_y, (181, 0))):
            observed = np.array(gui.crop((p.track_x, row, p.track_x + 155, row + 5)))
            blank = base.crop((p.track_x, row, p.track_x + 155, row + 5)).convert("RGBA")
            pointer = self.atlas.crop((uv[0], uv[1], uv[0] + 5, uv[1] + 5))
            options = [(None, [np.array(blank.convert("RGB"))])]
            for value in range(151):
                patch = blank.copy()
                patch.alpha_composite(pointer, (value, 0))
                options.append((value, [np.array(patch.convert("RGB"))]))
            value, score = self._classify(observed, options, label)
            if value is None:
                raise DetectionError("未识别到配方指针；请选好锻造配方（范围括号模式暂需手工输入）")
            scores.append(score)
            values.append(value)
        rules = []
        seen_empty = False
        for i in range(3):
            rx = p.rule_x + i * p.rule_spacing
            observed = np.array(gui.crop((rx, p.rule_y, rx + 20, p.rule_y + 22)))
            blank = np.array(base.crop((rx, p.rule_y, rx + 20, p.rule_y + 22)))
            # Rule overlays are 20px wide but only 19px apart. Their edge
            # columns overlap the neighboring slot; classify the inner 18px.
            options = [(key, [a[:, 1:19] for a in images])
                       for key, images in [(None, [blank]), *self._rule_images]]
            rule, score = self._classify(observed[:, 1:19], options, f"规则 {i+1}")
            scores.append(score)
            if rule is None:
                seen_empty = True
            else:
                if seen_empty:
                    raise DetectionError("规则槽不连续，请检查遮挡或 profile")
                rules.append(rule)
        if not rules:
            raise DetectionError("未识别到锻造规则；当前不显示方案")
        history = []
        seen_empty = False
        # TFC draws the chronological list starting at x=99, going leftwards.
        for i in range(3):
            hx = p.history_x + (2 - i) * p.rule_spacing
            box = (hx, p.history_y, hx + 16, p.history_y + 16)
            observed = np.array(gui.crop(box))
            bg = base.crop(box).convert("RGBA")
            options = [(None, [np.array(bg.convert("RGB"))])]
            for category in CATEGORIES:
                actions = [a for a in Action if a.category == category]
                images = []
                for action in actions:
                    patch = bg.copy()
                    patch.alpha_composite(self._icon(action))
                    images.append(np.array(patch.convert("RGB")))
                # All three vanilla hit history sprites are identical. Return
                # one canonical category representative, never guess strength.
                options.append((actions[0], images))
            # The first history row intersects the bottom of rule overlays.
            options = [(key, [a[1:] for a in images]) for key, images in options]
            action, score = self._classify(observed[1:], options, f"最近操作 {i+1}")
            scores.append(score)
            if action is None:
                seen_empty = True
            else:
                if seen_empty:
                    raise DetectionError("历史槽不连续，无法保证剩余步数最短")
                history.append(action)
        return Observation(values[0], values[1], tuple(rules), tuple(history), region, scale, min(scores))
