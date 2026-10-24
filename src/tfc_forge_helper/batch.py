"""Batch one-item forging with verified inventory transfers and no text OCR."""
import threading
import time
from dataclasses import dataclass, replace

import numpy as np
from PIL import Image

from .automation import AutoForge, AutomationStopped, Frame, WindowsInput
from .engine import Config, Engine
from .profile import Profile
from .vision import DetectionError, Detector, distance


@dataclass(frozen=True)
class BatchResult:
    completed: int
    clicks: int
    message: str
    verified: bool


@dataclass(frozen=True)
class Icon:
    pixels: np.ndarray
    mask: np.ndarray

    @classmethod
    def capture(cls, actual, background):
        pixels = np.array(actual.convert("RGB"))
        mask = np.max(np.abs(pixels.astype(float) - np.array(background.convert("RGB"))), axis=2) > 24
        # Stack counts / heat bars are irrelevant for identifying an item.
        # Resource-pack fonts can start stack digits as high as row 7.
        mask[7:] = False
        if np.count_nonzero(mask) < 5:
            raise AutomationStopped("物品图标信息不足，无法自动区分原料和成品")
        return cls(pixels, mask)

    def error(self, image):
        return distance(np.array(image.convert("RGB"))[self.mask], self.pixels[self.mask])


class InventoryView:
    def __init__(self, frame: Frame, detector: Detector, profile: Profile):
        self.frame, self.profile, self.atlas = frame, profile, detector.atlas
        self.region, self.scale, _ = detector.locate(frame.image)
        x, y, w, h = self.region
        self.gui = frame.image.crop((x, y, x + w, y + h)).resize(
            (profile.gui_width, profile.gui_height), Image.Resampling.NEAREST).convert("RGB")

    def crop(self, point):
        x, y = point
        return self.gui.crop((x, y, x + 16, y + 16))

    def background(self, point):
        x, y = point
        return self.atlas.crop((x, y, x + 16, y + 16)).convert("RGB")

    def empty(self, point):
        return distance(np.array(self.crop(point)), np.array(self.background(point))) < .018

    @property
    def cursor_point(self):
        x, y = self.profile.cursor_park
        return x - 8, y - 8

    @property
    def cursor_empty(self):
        return self.empty(self.cursor_point)

    def screen_point(self, point, center=True):
        x, y, w, h = self.region
        offset = 8 if center else 0
        return (round(x + (point[0] + offset) * w / self.profile.gui_width),
                round(y + (point[1] + offset) * h / self.profile.gui_height))

    def slots(self):
        p = self.profile
        # Favor hotbar supplies, then scan the main inventory. No source setup.
        return [(p.hotbar[0] + col * p.slot_spacing, p.hotbar[1]) for col in range(9)] + [
            (p.inventory[0] + col * p.slot_spacing, p.inventory[1] + row * p.slot_spacing)
            for row in range(3) for col in range(9)]


class BatchForge:
    def __init__(self, engine: Engine, backend=None, timeout=2.5, settle=.16):
        self.engine, self.backend = engine, backend
        self.timeout, self.settle = timeout, settle
        self.completed, self.clicks = 0, 0

    def run(self, config: Config, cancel: threading.Event, notify=lambda value: None,
            count: int = 0, tolerance: int = 0, countdown: int = 3) -> BatchResult:
        if type(count) is not int or not 0 <= count <= 4096:
            raise ValueError("批量数量必须是 0–4096；0 表示直到同类原料用完")
        backend = self.backend or WindowsInput()
        self.completed, self.clicks = 0, 0
        for seconds in range(countdown, 0, -1):
            notify(f"{seconds} 秒后开始批量打铁，请切回砧界面；F9 停止")
            if cancel.wait(1):
                raise AutomationStopped("批量打铁已取消")
        atlas, profile = self.engine.refresh(config)
        pid, revision = self.engine.pid, self.engine.revision
        if pid is None:
            raise AutomationStopped("尚未定位运行中的游戏进程，无法批量打铁")
        profile = replace(profile, threshold=max(.985, profile.threshold))
        detector = Detector(atlas, profile)

        def check():
            if cancel.is_set():
                raise AutomationStopped("批量打铁已停止；若鼠标仍持有物品，请手动放回")
            self.engine.refresh(config)
            if self.engine.pid != pid or self.engine.revision != revision:
                raise AutomationStopped("实例或资源已变化，批量打铁已停止")

        def read():
            check()
            return InventoryView(backend.frame(pid), detector, profile)

        def wait_for(predicate, message):
            deadline = time.monotonic() + self.timeout
            if cancel.wait(self.settle):
                check()
            while time.monotonic() < deadline:
                view = read()
                if predicate(view):
                    return view
                if cancel.wait(.06):
                    check()
            raise AutomationStopped(message)

        def click(view, point, shift=False):
            check()
            backend.click(view.frame, view.screen_point(point),
                          view.screen_point(profile.cursor_park, center=False), cancel, shift=shift)
            self.clicks += 1

        try:
            # Clear existing hover tooltips before locating the GUI. This moves
            # the pointer within the foreground game window and never clicks.
            frame = backend.frame(pid)
            if hasattr(backend, "park"):
                backend.park(frame, cancel)
                if cancel.wait(.2):
                    check()
            view = read()
            if hasattr(backend, "move"):
                backend.move(view.frame, view.screen_point(profile.cursor_park, center=False), cancel)
                view = wait_for(lambda v: v.cursor_empty, "鼠标可能持有物品，请放回后重新开始")
            elif not view.cursor_empty:
                raise AutomationStopped("鼠标可能持有物品，请放回后重新开始")
            detector.detect(view.frame.image)
            if view.empty(profile.input_slot):
                raise AutomationStopped("请先放入首件原料并选择一次配方，之后会自动补料和收成")
            raw = Icon.capture(view.crop(profile.input_slot), view.background(profile.input_slot))
            # The plan result is rendered at (138,57) on the atlas button whose
            # background starts at (218,0). Its icon identifies the desired output.
            output_background = atlas.image.crop((219, 1, 235, 17))
            output = Icon.capture(view.crop(profile.plan_icon), output_background)

            def is_raw(image):
                return raw.error(image) < .065 and raw.error(image) + .008 < output.error(image)

            def is_output(image):
                return output.error(image) < .065 and output.error(image) + .008 < raw.error(image)

            if not is_raw(view.crop(profile.input_slot)):
                raise AutomationStopped("原料和成品图标过于相似，无法可靠换料；请使用单件模式")

            def output_ready(frame):
                candidate = InventoryView(frame, detector, profile)
                return candidate.cursor_empty and is_output(candidate.crop(profile.input_slot))

            limit = count or 4096
            while self.completed < limit:
                check()
                view = read()
                # Target, current and rule positions may be randomized per item.
                # Validate this item's full state afresh; only the desired
                # result icon identifies the batch's product, never old rules.
                detector.detect(view.frame.image)
                if output.error(view.crop(profile.plan_icon)) > .065:
                    raise AutomationStopped("加工目标已变化，已停止；请检查所选成品")
                notify(f"批量进度 {self.completed}/{count or '全部'} · 正在锻造下一件")
                result = AutoForge(self.engine, backend, self.timeout, self.settle).run(
                    config, cancel, notify, tolerance, countdown=0, completion_check=output_ready)
                self.clicks += result.clicks
                view = wait_for(lambda v: v.cursor_empty and is_output(v.crop(profile.input_slot)),
                                "无法确认成品，已停止；不会移动未确认的物品")
                self.completed += 1
                notify(f"已锻造 {self.completed} 件 · 自动收回成品")
                click(view, profile.input_slot, shift=True)
                try:
                    view = wait_for(lambda v: v.empty(profile.input_slot) and v.cursor_empty,
                                    "背包空间不足或成品未能收回，已停止；成品留在砧上")
                except AutomationStopped as exc:
                    if cancel.is_set():
                        raise
                    return BatchResult(self.completed, self.clicks, str(exc), False)
                if self.completed >= limit:
                    break
                source = next((point for point in view.slots()
                               if not view.empty(point) and is_raw(view.crop(point))), None)
                if source is None:
                    return BatchResult(self.completed, self.clicks, "同类原料已用完，批量打铁结束", True)
                notify(f"已完成 {self.completed} 件 · 自动放入一件同类原料")
                click(view, source)
                view = wait_for(lambda v, src=source: v.empty(src) and is_raw(v.crop(v.cursor_point)),
                                "无法确认原料已取起，已停止；不会重复点击")
                if not view.empty(profile.input_slot):
                    raise AutomationStopped("砧输入槽已被其他物品占用，已停止；请手动放回原料")
                click(view, profile.input_slot)
                view = wait_for(lambda v: is_raw(v.crop(profile.input_slot)) and
                                (v.cursor_empty or is_raw(v.crop(v.cursor_point))),
                                "无法确认原料已放入，已停止")
                if not view.cursor_empty:
                    if not view.empty(source):
                        raise AutomationStopped("原料来源槽已变化，已停止；请手动放回鼠标上的物品")
                    click(view, source)
                    view = wait_for(lambda v, src=source: v.cursor_empty and is_raw(v.crop(src)),
                                    "剩余原料未能放回，已停止；请检查鼠标上的物品")
                # Server-side anvil recipe memory may update after the slot change.
                view = wait_for(lambda v: output.error(v.crop(profile.plan_icon)) < .065,
                                "砧没有记住首件配方，请先选择一次配方再启动")
            return BatchResult(self.completed, self.clicks, f"已完成指定的 {self.completed} 件，批量打铁结束", True)
        except (AutomationStopped, DetectionError) as exc:
            raise AutomationStopped(f"已完成 {self.completed} 件。{exc}") from exc
