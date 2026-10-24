"""Executable smoke check without screenshots, hotkeys, or game input."""

import json
import platform
import sys
import tkinter as tk
from pathlib import Path

import cv2
import mss
import numpy as np
import psutil
from PIL import Image, ImageTk

from . import __version__
from .model import parse_rules
from .paths import data_directory
from .solver import solve


def self_test(report: Path):
    result = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)),
              "python": platform.python_version(), "architecture": platform.machine(),
              "data_directory": str(data_directory()), "ok": False}
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            photo = ImageTk.PhotoImage(Image.new("RGB", (16, 16), "white"), master=root)
            if photo.width() != 16:
                raise RuntimeError("Pillow/Tk image bridge failed")
            root.update_idletasks()
            result["tk"] = root.tk.call("info", "patchlevel")
        finally:
            root.destroy()
        image = np.arange(64, dtype=np.uint8).reshape(8, 8)
        if cv2.resize(image, (16, 16)).shape != (16, 16):
            raise RuntimeError("OpenCV/NumPy runtime failed")
        if not psutil.Process().is_running() or not callable(mss.MSS):
            raise RuntimeError("Process/capture runtime failed")
        rules = parse_rules("hit_third_last,draw_second_last,draw_last")
        solution = solve(83, 108, rules)
        if solution.steps != 7 or solution.positions[-1] != 108:
            raise RuntimeError("Solver smoke check failed")
        result.update(ok=True, solver_steps=solution.steps, opencv=cv2.__version__, numpy=np.__version__)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        # Keep failed automated checks from opening PyInstaller's blocking error dialog.
        raise SystemExit(1) from exc
    finally:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
