import os
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from tfc_forge_helper.automation import AutomationStopped, Frame, WindowsInput
from tfc_forge_helper.coordinates import CoordinateError, DesktopLayout, Rect


def desktop(*monitors):
    left, top = min(m.left for m in monitors), min(m.top for m in monitors)
    right, bottom = max(m.right for m in monitors), max(m.bottom for m in monitors)
    return DesktopLayout(Rect(left, top, right - left, bottom - top), tuple(monitors))


def test_regression_window_right_edge_34_pixels_offscreen():
    layout = desktop(Rect(0, 0, 2560, 1440))
    client = Rect(994, 292, 1600, 895)
    assert not layout.bounds.contains(client.left + 1588, client.top + 12)
    x, y = layout.visible_park(client)
    assert (x, y) == (1553, 12)
    assert layout.monitors[0].contains(client.left + x, client.top + y)


@pytest.mark.parametrize("client", [Rect(-150, 50, 1000, 800), Rect(50, -160, 1000, 800),
                                    Rect(2200, 1200, 1000, 800), Rect(-1000, 700, 1400, 800)])
def test_parking_uses_visible_part_for_all_clipped_edges(client):
    layout = desktop(Rect(0, 0, 2560, 1440))
    x, y = layout.visible_park(client)
    assert 0 <= x < client.width and 0 <= y < client.height
    assert layout.bounds.contains(client.left + x, client.top + y)


def test_negative_monitor_origin_and_normalized_corners():
    layout = desktop(Rect(-1920, -200, 1920, 1080), Rect(0, 0, 2560, 1440))
    assert layout.normalize(-1920, -200) == (0, 0)
    assert layout.normalize(2559, 1439) == (65535, 65535)
    client = Rect(-2000, -100, 1200, 800)
    x, y = layout.visible_park(client)
    assert layout.monitors[0].contains(client.left + x, client.top + y)


def test_monitor_gap_rejected_even_inside_virtual_rectangle():
    layout = desktop(Rect(-1920, -1080, 1920, 1080), Rect(0, 0, 2560, 1440))
    with pytest.raises(CoordinateError):
        layout.normalize(-100, 500)
    client = Rect(-200, -300, 1600, 1000)
    x, y = layout.visible_park(client)
    assert any(m.contains(client.left + x, client.top + y) for m in layout.monitors)


@pytest.mark.parametrize("client", [Rect(2700, 100, 500, 500), Rect(2550, 100, 500, 500)])
def test_hidden_or_tiny_visible_window_is_rejected(client):
    with pytest.raises(CoordinateError):
        desktop(Rect(0, 0, 2560, 1440)).visible_park(client)


@pytest.fixture
def native_adapter():
    if os.name != "nt":
        pytest.skip("Windows input ABI adapter test")
    # Exercise the actual adapter/struct packing, but replace every native
    # binding. These tests never move the cursor or send a real mouse/key event.
    import ctypes
    from ctypes import wintypes as w
    events = []
    cancel = threading.Event()
    cancel_on_down = [False]
    def process(hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(w.DWORD)).contents.value = 123
        return 1
    def send(count, pointer, size):
        event = pointer._obj
        assert size in (28, 40)
        if event.type == 0:
            mouse = event.payload.mi
            events.append(("mouse", mouse.dwFlags, mouse.dx, mouse.dy))
            if mouse.dwFlags == 2 and cancel_on_down[0]:
                cancel.set()
        else:
            key = event.payload.ki
            events.append(("key", key.dwFlags, key.wVk))
        return 1
    def foreground():
        return 999
    def point_window(point):
        return 999
    def unused(*args):
        raise AssertionError("Unexpected unmocked native window operation")
    user = SimpleNamespace(GetForegroundWindow=foreground, GetWindowThreadProcessId=process,
                           GetClientRect=unused, ClientToScreen=unused, WindowFromPoint=point_window,
                           SendInput=send)
    layout = desktop(Rect(0, 0, 2560, 1440))
    adapter = WindowsInput(user=user, desktop=layout)
    frame = Frame(Image.new("RGB", (1600, 895)), (994, 292), 123, 999)
    adapter._window = lambda pid: (999, (*frame.origin, frame.image.width, frame.image.height))
    return adapter, frame, events, cancel, cancel_on_down


def test_native_parking_of_clipped_window_emits_only_valid_move(native_adapter):
    adapter, frame, events, cancel, _ = native_adapter
    point = adapter.park(frame, cancel)
    assert point == (1553, 12)
    assert len(events) == 1 and events[0][1] == 0xC001
    assert 0 <= events[0][2] <= 65535 and 0 <= events[0][3] <= 65535


def test_offscreen_action_is_rejected_without_any_input(native_adapter):
    adapter, frame, events, cancel, _ = native_adapter
    with pytest.raises(AutomationStopped, match="屏幕"):
        adapter.click(frame, (1590, 400), (400, 100), cancel)
    assert not events


def test_offscreen_neutral_is_rejected_before_button_down(native_adapter):
    adapter, frame, events, cancel, _ = native_adapter
    with pytest.raises(AutomationStopped, match="屏幕"):
        adapter.click(frame, (400, 400), (1590, 100), cancel)
    assert not events


def test_cancellation_releases_native_shift_and_mouse(native_adapter):
    adapter, frame, events, cancel, cancel_on_down = native_adapter
    cancel_on_down[0] = True
    adapter.click(frame, (400, 400), (500, 100), cancel, shift=True)
    assert events[1:] == [("key", 0, 0xA0), ("mouse", 2, 0, 0),
                          ("mouse", 4, 0, 0), ("key", 2, 0xA0)]


def test_window_change_after_move_stops_before_click(native_adapter):
    adapter, frame, events, cancel, _ = native_adapter
    windows = iter([(999, (*frame.origin, frame.image.width, frame.image.height)),
                    (999, (995, 292, frame.image.width, frame.image.height))])
    adapter._window = lambda pid: next(windows)
    with pytest.raises(AutomationStopped, match="变化"):
        adapter.click(frame, (400, 400), (500, 100), cancel)
    assert len(events) == 1 and events[0][1] == 0xC001
