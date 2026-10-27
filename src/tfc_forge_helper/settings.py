"""Validated preferences and atomic, backwards-compatible local settings."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .engine import Config


@dataclass(frozen=True)
class Preferences:
    monitor: str = "-1"
    tolerance: str = "0"
    batch_mode: bool = True
    batch_count: str = "0"
    live: bool = True
    show_overlay: bool = False
    topmost: bool = False

    @classmethod
    def from_dict(cls, data, base=None):
        base = base or cls()
        values = asdict(base)
        if not isinstance(data, dict):
            return base
        for name in ("batch_mode", "live", "show_overlay", "topmost"):
            if type(data.get(name)) is bool:
                values[name] = data[name]
        for name, lower, upper in (("monitor", -1, 16), ("tolerance", 0, 150), ("batch_count", 0, 4096)):
            value = data.get(name)
            if type(value) not in (str, int):
                continue
            try:
                number = int(value)
            except ValueError:
                continue
            if lower <= number <= upper:
                values[name] = str(number)
        return cls(**values)


@dataclass(frozen=True)
class Settings:
    config: Config = field(default_factory=Config)
    preferences: Preferences = field(default_factory=Preferences)


def load_settings(path: Path) -> Settings:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    # v0.2.5 and earlier stored a flat Config object with no preferences.
    source = data.get("config", data)
    values = asdict(Config())
    if isinstance(source, dict):
        for name in ("instance", "jar", "profile"):
            if isinstance(source.get(name), str):
                values[name] = source[name]
        if type(source.get("auto_instance")) is bool:
            values["auto_instance"] = source["auto_instance"]
        packs = source.get("packs")
        if isinstance(packs, (list, tuple)) and all(isinstance(pack, str) for pack in packs):
            values["packs"] = tuple(packs)
    return Settings(Config(**values), Preferences.from_dict(data.get("preferences")))


def save_settings(path: Path, settings: Settings):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".settings-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"version": 1, **asdict(settings)}, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
