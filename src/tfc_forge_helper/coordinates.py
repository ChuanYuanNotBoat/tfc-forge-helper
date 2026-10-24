"""Physical desktop geometry, including clipped windows and monitor gaps."""
from dataclasses import dataclass


class CoordinateError(ValueError):
    pass


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self):
        if self.width <= 0 or self.height <= 0:
            raise CoordinateError("显示区域尺寸无效")

    @property
    def right(self):
        return self.left + self.width

    @property
    def bottom(self):
        return self.top + self.height

    def contains(self, x, y):
        return self.left <= x < self.right and self.top <= y < self.bottom

    def intersection(self, other):
        left, top = max(self.left, other.left), max(self.top, other.top)
        right, bottom = min(self.right, other.right), min(self.bottom, other.bottom)
        return Rect(left, top, right - left, bottom - top) if right > left and bottom > top else None


@dataclass(frozen=True)
class DesktopLayout:
    bounds: Rect
    monitors: tuple[Rect, ...]

    @classmethod
    def current(cls, user):
        import ctypes
        from ctypes import wintypes as w
        user.GetSystemMetrics.argtypes = [ctypes.c_int]
        user.GetSystemMetrics.restype = ctypes.c_int
        bounds = Rect(*(user.GetSystemMetrics(i) for i in (76, 77, 78, 79)))
        monitors = []
        callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HANDLE, w.HDC, ctypes.POINTER(w.RECT), w.LPARAM)
        def visit(handle, dc, rect_pointer, data):
            r = rect_pointer.contents
            if r.right > r.left and r.bottom > r.top:
                monitors.append(Rect(r.left, r.top, r.right - r.left, r.bottom - r.top))
            return True
        user.EnumDisplayMonitors.argtypes = [w.HDC, ctypes.POINTER(w.RECT), callback_type, w.LPARAM]
        user.EnumDisplayMonitors.restype = w.BOOL
        if not user.EnumDisplayMonitors(None, None, callback_type(visit), 0) or not monitors:
            raise CoordinateError("无法读取当前显示器布局，已停止")
        return cls(bounds, tuple(monitors))

    def normalize(self, x: int, y: int) -> tuple[int, int]:
        if not self.bounds.contains(x, y) or not any(m.contains(x, y) for m in self.monitors):
            raise CoordinateError(f"目标位置 ({x}, {y}) 不在可见屏幕内，请将完整砧界面移回屏幕")
        b = self.bounds
        return (round((x - b.left) * 65535 / max(1, b.width - 1)),
                round((y - b.top) * 65535 / max(1, b.height - 1)))

    def visible_park(self, client: Rect) -> tuple[int, int]:
        parts = [piece for monitor in self.monitors
                 if (piece := client.intersection(monitor)) is not None]
        parts = [part for part in parts if part.width >= 24 and part.height >= 24]
        if not parts:
            raise CoordinateError("游戏窗口可见区域过小，请将窗口移回屏幕")
        visible = max(parts, key=lambda r: r.width * r.height)
        # Only the non-clicking tooltip-clear movement selects a visible point.
        # Action-button coordinates are never clamped onto another location.
        return visible.right - 13 - client.left, visible.top + 12 - client.top
