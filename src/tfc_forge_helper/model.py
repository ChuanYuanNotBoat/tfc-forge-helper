from dataclasses import dataclass
from enum import Enum


class Action(Enum):
    HIT_LIGHT = ("轻击", -3, 64)
    HIT_MEDIUM = ("中击", -6, 80)
    HIT_HARD = ("重击", -9, 96)
    DRAW = ("拉伸", -15, 112)
    PUNCH = ("冲孔", 2, 0)
    BEND = ("弯曲", 7, 16)
    UPSET = ("镦锻", 13, 32)
    SHRINK = ("收缩", 16, 48)

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def delta(self) -> int:
        return self.value[1]

    @property
    def icon_x(self) -> int:
        return self.value[2]

    @property
    def button(self) -> tuple[int, int]:
        return {"HIT_LIGHT": (53, 56), "HIT_MEDIUM": (71, 56), "HIT_HARD": (53, 74),
                "DRAW": (71, 74), "PUNCH": (89, 56), "BEND": (107, 56),
                "UPSET": (89, 74), "SHRINK": (107, 74)}[self.name]

    @property
    def category(self) -> str:
        return "hit" if self.name.startswith("HIT_") else self.name.lower()

    @classmethod
    def parse(cls, text: str) -> "Action":
        if text.strip().lower() == "hit":
            # History needs the hit category only; its strength is not rendered
            # distinctly in the standard atlas and does not affect rule matching.
            return cls.HIT_LIGHT
        try:
            return cls[text.strip().upper()]
        except KeyError as exc:
            raise ValueError(f"未知动作：{text}；请使用 hit_light / hit_medium / hit_hard 等名称") from exc


ORDER_ROWS = {"last": 0, "second_last": 22, "third_last": 44, "not_last": 66, "any": 88}
ORDER_LABELS = {"last": "最后", "second_last": "倒数第二", "third_last": "倒数第三",
                "not_last": "不能最后", "any": "最后三步任意"}
CATEGORIES = ("hit", "draw", "punch", "bend", "upset", "shrink")


@dataclass(frozen=True)
class Rule:
    category: str
    order: str

    def __post_init__(self):
        if self.category not in CATEGORIES or self.order not in ORDER_ROWS:
            raise ValueError(f"无效规则：{self.category}_{self.order}")

    @classmethod
    def parse(cls, text: str) -> "Rule":
        category, _, order = text.strip().lower().partition("_")
        return cls(category, order)

    @property
    def name(self) -> str:
        return f"{self.category}_{self.order}"

    def matches(self, chronological: tuple[str, ...]) -> bool:
        recent = chronological[-3:][::-1]
        positions = {"last": (0,), "second_last": (1,), "third_last": (2,),
                     "not_last": (1, 2), "any": (0, 1, 2)}[self.order]
        return any(i < len(recent) and recent[i] == self.category for i in positions)


def parse_rules(text: str) -> tuple[Rule, ...]:
    return tuple(Rule.parse(x) for x in text.replace(",", " ").split())


def parse_history(text: str) -> tuple[Action, ...]:
    actions = tuple(Action.parse(x) for x in text.replace(",", " ").split())
    if len(actions) > 3:
        raise ValueError("历史只需最近三步，按从旧到新填写")
    return actions
