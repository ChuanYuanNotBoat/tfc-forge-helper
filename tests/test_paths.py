import sys
from pathlib import Path

from tfc_forge_helper.paths import data_directory, profiles_directory


def test_source_preserves_existing_settings_location(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    root = Path(__file__).resolve().parents[1]
    assert data_directory() == root / "work"
    assert profiles_directory() == root / "profiles"


def test_frozen_settings_survive_onefile_extraction(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "temporary"), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "用户设置"))
    expected = tmp_path / "用户设置" / "TFCForgeHelper"
    assert data_directory() == expected
    assert profiles_directory() == expected / "profiles"
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "another-extraction"))
    assert data_directory() == expected


def test_frozen_settings_without_localappdata(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert data_directory() == Path.home() / "AppData" / "Local" / "TFCForgeHelper"
