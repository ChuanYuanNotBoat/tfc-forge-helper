import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Profile:
    name: str = "TFC 1.21.1"
    gui_width: int = 176
    gui_height: int = 207
    track_x: int = 11
    current_y: int = 104
    target_y: int = 98
    rule_x: int = 59
    rule_y: int = 13
    rule_spacing: int = 19
    history_x: int = 61
    history_y: int = 34
    anchor: tuple[int, int, int, int] = (0, 124, 176, 79)
    scales: tuple[float, ...] = (1, 2, 3, 4, 5, 6, 7, 8)
    # Physical pixels in the captured image, not Windows logical screen coordinates.
    region: tuple[int, int, int, int] | None = None
    threshold: float = 0.94
    margin: float = 0.004
    resource: str = "assets/tfc/textures/gui/anvil.png"
    # Top-left of each 16x16 action button, in Action enum order.
    buttons: tuple[tuple[int, int], ...] = ((53, 56), (71, 56), (53, 74), (71, 74),
                                          (89, 56), (107, 56), (89, 74), (107, 74))
    input_slot: tuple[int, int] = (22, 76)
    inventory: tuple[int, int] = (8, 125)
    hotbar: tuple[int, int] = (8, 183)
    slot_spacing: int = 18
    plan_icon: tuple[int, int] = (138, 57)
    cursor_park: tuple[int, int] = (145, 20)

    def __post_init__(self):
        if self.gui_width <= 0 or self.gui_height <= 0 or self.gui_width > 256 or self.gui_height > 256:
            raise ValueError("profile GUI 尺寸必须在 1–256 内")
        if not self.scales or any(s <= 0 or s > 16 for s in self.scales):
            raise ValueError("profile 缩放必须在 0–16 之间")
        if not 0 < self.threshold <= 1 or not 0 <= self.margin <= 1:
            raise ValueError("profile 置信度设置错误")
        if self.region is not None and (len(self.region) != 4 or min(self.region[2:]) <= 0):
            raise ValueError("profile region 应为 [x,y,width,height]")
        x, y, w, h = self.anchor
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > self.gui_width or y + h > self.gui_height:
            raise ValueError("profile anchor 越过 GUI 范围")
        if self.track_x < 0 or self.track_x + 155 > self.gui_width:
            raise ValueError("profile 进度条超出 GUI 范围")
        if not 0 <= self.current_y <= self.gui_height - 5 or not 0 <= self.target_y <= self.gui_height - 5:
            raise ValueError("profile 指针行越界")
        if min(self.rule_x, self.rule_y, self.history_x, self.history_y) < 0:
            raise ValueError("profile 图标坐标不能为负数")
        if self.rule_x + 2 * self.rule_spacing + 20 > self.gui_width or self.rule_y + 22 > self.gui_height:
            raise ValueError("profile 规则区域越界")
        if self.history_x + 2 * self.rule_spacing + 16 > self.gui_width or self.history_y + 16 > self.gui_height:
            raise ValueError("profile 历史区域越界")
        if len(self.buttons) != 8 or any(len(b) != 2 or min(b) < 0 or b[0] + 16 > self.gui_width
                                        or b[1] + 16 > self.gui_height for b in self.buttons):
            raise ValueError("profile 必须提供八个有效的 16×16 动作按钮位置")
        for point in (self.input_slot, self.inventory, self.hotbar, self.plan_icon):
            if len(point) != 2 or min(point) < 0 or point[0] + 16 > self.gui_width or point[1] + 16 > self.gui_height:
                raise ValueError("profile 批量操作槽位越界")
        if self.slot_spacing <= 0 or self.inventory[0] + 8 * self.slot_spacing + 16 > self.gui_width or self.inventory[1] + 2 * self.slot_spacing + 16 > self.gui_height:
            raise ValueError("profile 背包网格越界")
        if self.hotbar[0] + 8 * self.slot_spacing + 16 > self.gui_width:
            raise ValueError("profile 快捷栏越界")
        if not 8 <= self.cursor_park[0] <= self.gui_width - 8 or not 8 <= self.cursor_park[1] <= self.gui_height - 8:
            raise ValueError("profile 鼠标停放位置越界")

    @classmethod
    def load(cls, path: Path | None) -> "Profile":
        if path is None:
            return cls()
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"未知 profile 字段：{sorted(unknown)}")
        for key in ("anchor", "scales", "region", "input_slot", "inventory", "hotbar", "plan_icon", "cursor_park"):
            if data.get(key) is not None:
                data[key] = tuple(data[key])
        if "buttons" in data:
            data["buttons"] = tuple(tuple(b) for b in data["buttons"])
        return cls(**data)

    def save(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
