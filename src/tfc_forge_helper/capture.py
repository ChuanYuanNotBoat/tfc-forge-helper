import os

from PIL import Image


def enable_dpi_awareness():
    if os.name == "nt":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def game_window_region(pid: int | None) -> dict | None:
    if os.name != "nt" or pid is None:
        return None
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    windows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        process = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
        if process.value == pid and user.IsWindowVisible(hwnd) and not user.IsIconic(hwnd):
            rectangle, point = wintypes.RECT(), wintypes.POINT(0, 0)
            if user.GetClientRect(hwnd, ctypes.byref(rectangle)) and user.ClientToScreen(hwnd, ctypes.byref(point)):
                w, h = rectangle.right, rectangle.bottom
                if w >= 176 and h >= 207:
                    windows.append({"left": point.x, "top": point.y, "width": w, "height": h})
        return True
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows(callback_type(visit), 0)
    return max(windows, key=lambda r: r["width"] * r["height"]) if windows else None


def screenshot(monitor: int = -1, pid: int | None = None) -> Image.Image:
    import mss
    with mss.MSS() as capture:
        region = game_window_region(pid) if monitor == -1 else None
        if monitor == -1:
            monitor = 1
        if not 0 <= monitor < len(capture.monitors):
            raise ValueError(f"显示器编号无效；可用范围：-1–{len(capture.monitors)-1}")
        shot = capture.grab(region or capture.monitors[monitor])
        return Image.frombytes("RGB", shot.size, shot.rgb)
