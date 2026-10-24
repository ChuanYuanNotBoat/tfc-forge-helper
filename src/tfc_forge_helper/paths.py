"""Keep frozen-app settings outside PyInstaller's temporary extraction folder."""

import os
import sys
from pathlib import Path


def data_directory() -> Path:
    if getattr(sys, "frozen", False):
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else Path.home() / "AppData" / "Local") / "TFCForgeHelper"
    return Path(__file__).resolve().parents[2] / "work"


def profiles_directory() -> Path:
    if getattr(sys, "frozen", False):
        return data_directory() / "profiles"
    return Path(__file__).resolve().parents[2] / "profiles"
