import json
from concurrent.futures import Future
from unittest.mock import Mock

import pytest

from tfc_forge_helper.engine import Config
from tfc_forge_helper.settings import Preferences, Settings, load_settings, save_settings


def test_legacy_flat_configuration_is_loaded_and_can_be_migrated(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"instance": "实例", "jar": "tfc.jar", "packs": ["a.zip", "b.zip"],
                                "profile": "profile.json", "auto_instance": False}), encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.config == Config("实例", "tfc.jar", ("a.zip", "b.zip"), "profile.json", False)
    assert loaded.preferences == Preferences()
    save_settings(path, loaded)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    assert load_settings(path) == loaded


def test_all_preferences_and_unicode_paths_survive_roundtrip(tmp_path):
    expected = Settings(Config("游戏 目录", "模组.jar", ("材质.zip",), "校准.json", False),
                        Preferences("2", "3", False, "12", False, True, True))
    path = tmp_path / "用户设置" / "settings.json"
    save_settings(path, expected)
    assert load_settings(path) == expected


@pytest.mark.parametrize("contents", [b"{", b"[]", b"\xff"])
def test_invalid_settings_fall_back_without_crashing(tmp_path, contents):
    path = tmp_path / "settings.json"
    path.write_bytes(contents)
    assert load_settings(path) == Settings()


def test_invalid_fields_do_not_discard_other_valid_preferences(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"config": {"instance": "instance", "packs": "wrong", "auto_instance": "no"},
                                "preferences": {"monitor": "bad", "tolerance": 151, "batch_count": 12,
                                                "topmost": "yes", "show_overlay": True, "live": False,
                                                "batch_mode": False, "allow_forging": True}}), encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.config == Config(instance="instance")
    assert loaded.preferences == Preferences(batch_count="12", batch_mode=False, live=False, show_overlay=True)
    assert not hasattr(loaded.preferences, "allow_forging")


def test_atomic_write_failure_preserves_previous_configuration(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    before = Settings(preferences=Preferences(batch_count="5"))
    save_settings(path, before)
    def denied(*_):
        raise PermissionError("read only")
    monkeypatch.setattr("tfc_forge_helper.settings.os.replace", denied)
    with pytest.raises(PermissionError):
        save_settings(path, Settings(preferences=Preferences(batch_count="9")))
    assert load_settings(path) == before
    assert list(tmp_path.glob(".settings-*.tmp")) == []


@pytest.fixture
def headless_app(monkeypatch, tmp_path):
    import tkinter as tk

    from tfc_forge_helper import gui

    interpreter = tk.Tcl()  # No Tk window, native hotkeys, or background work.
    string_variable, boolean_variable = tk.StringVar, tk.BooleanVar
    monkeypatch.setattr(gui.tk, "StringVar", lambda **kwargs: string_variable(interpreter, **kwargs))
    monkeypatch.setattr(gui.tk, "BooleanVar", lambda **kwargs: boolean_variable(interpreter, **kwargs))
    monkeypatch.setattr(gui.App, "_style", lambda _: None)
    def build(app):
        app.table, app.bar, app.instance_combo = Mock(), Mock(), Mock()
        app.table.get_children.return_value = ()
    monkeypatch.setattr(gui.App, "_build", build)
    overlay = Mock()
    monkeypatch.setattr(gui.App, "_overlay_changed", overlay)
    monkeypatch.setattr(gui.threading, "Thread", Mock())
    def pool(**_):
        return Mock(submit=Mock(side_effect=lambda *_: Future()))
    monkeypatch.setattr(gui, "ThreadPoolExecutor", pool)
    path = tmp_path / "settings.json"
    monkeypatch.setattr(gui, "SETTINGS", path)
    def open_app(config=None):
        root = Mock()
        return gui.App(root, config if config is not None else Config())
    return open_app, path, overlay


def test_preferences_restore_at_startup_without_resuming_execution(headless_app):
    open_app, path, overlay = headless_app
    expected = Settings(Config("游戏", "tfc.jar", ("a.zip",), "local.json", False),
                        Preferences("2", "3", False, "12", False, True, True))
    save_settings(path, expected)
    app = open_app()
    assert app.config() == expected.config
    assert (app.monitor.get(), app.tolerance.get(), app.batch_count.get()) == ("2", "3", "12")
    assert not app.live.get() and not app.batch_mode.get()
    assert app.show_overlay.get() and app.topmost.get()
    app.root.attributes.assert_called_once_with("-topmost", True)
    overlay.assert_called_once()
    assert not app.allow_forging.get() and not app.pending_forging
    assert app.future_kind == "resources" and app.last_solution is None


def test_edits_are_saved_even_before_resources_can_be_resolved(headless_app):
    open_app, path, _ = headless_app
    app = open_app()
    app.instance.set("not-yet-installed-instance")
    app.auto_instance.set(False)
    app.monitor.set("2")
    app.tolerance.set("4")
    app.batch_mode.set(False)
    app.batch_count.set("7")
    callbacks = [call.args[1] for call in app.root.after.call_args_list if call.args[0] == 400]
    assert callbacks and app.root.after_cancel.called
    callbacks[-1]()
    assert not app.future.done()  # Resource job never ran or succeeded.
    loaded = load_settings(path)
    assert loaded.config.instance == "not-yet-installed-instance" and not loaded.config.auto_instance
    assert loaded.preferences == Preferences("2", "4", False, "7")


def test_closing_flushes_pending_debounce_and_view_preferences(headless_app):
    open_app, path, _ = headless_app
    app = open_app()
    app.batch_count.set("19")
    app.show_overlay.set(True)
    app.topmost.set(True)
    app.live.set(False)
    app._live_changed()
    assert not path.exists()  # Mock timers have not run.
    app.close()
    restored = open_app()
    assert restored.batch_count.get() == "19"
    assert restored.show_overlay.get() and restored.topmost.get() and not restored.live.get()
    assert app.closed and app._settings_after is None
    app.root.destroy.assert_called_once()


def test_temporary_live_pause_during_forging_does_not_replace_user_preference(headless_app):
    open_app, path, _ = headless_app
    app = open_app()
    app.future = None
    app.f9_registered = True
    app.start_forging()
    assert not app.live.get() and app.allow_forging.get()
    app.close()
    assert load_settings(path).preferences.live
    restored = open_app()
    assert restored.live.get() and not restored.allow_forging.get()
    assert not restored.pending_forging and restored.future_kind == "resources"


def test_partial_numeric_edits_preserve_last_saved_valid_values(headless_app):
    open_app, path, _ = headless_app
    save_settings(path, Settings(preferences=Preferences("2", "3", batch_count="17")))
    app = open_app()
    app.monitor.set("")
    app.tolerance.set("invalid")
    app.batch_count.set("99999")
    app.jar.set("new.jar")
    app.close()
    saved = load_settings(path)
    assert saved.preferences == Preferences("2", "3", batch_count="17")
    assert saved.config.jar == "new.jar"


def test_cli_sources_override_saved_sources_but_keep_preferences(headless_app):
    open_app, path, _ = headless_app
    save_settings(path, Settings(Config(instance="saved"), Preferences(batch_count="9", live=False)))
    override = Config(instance="cli", auto_instance=False)
    app = open_app(override)
    assert app.config() == override
    assert app.batch_count.get() == "9" and not app.live.get()
    app.close()
    assert load_settings(path).config == override


def test_unchanged_preferences_and_forging_values_do_not_rewrite_settings(headless_app, monkeypatch):
    from tfc_forge_helper import gui

    open_app, path, _ = headless_app
    writer = Mock(wraps=gui.save_settings)
    monkeypatch.setattr(gui, "save_settings", writer)
    app = open_app()
    app._save_settings()
    app.current.set("99")
    app.target.set("100")
    app.history.set("punch")
    app._save_settings()
    app.close()
    assert writer.call_count == 1
    restored = open_app()
    assert (restored.current.get(), restored.target.get(), restored.history.get()) == ("83", "108", "")
    assert load_settings(path).preferences == Preferences()


def test_save_error_is_nonmodal_and_preserves_display(headless_app, monkeypatch):
    from tfc_forge_helper import gui

    open_app, path, _ = headless_app
    app = open_app()
    app._save_settings()
    previous = path.read_bytes()
    app.batch_count.set("10")
    plan = object()
    app.last_solution = plan
    def denied(*_):
        raise PermissionError("read only")
    monkeypatch.setattr(gui, "save_settings", denied)
    dialog = Mock()
    monkeypatch.setattr(gui.messagebox, "showerror", dialog)
    app._save_settings()
    assert app.last_solution is plan
    assert "设置保存失败" in app.status.get()
    assert path.read_bytes() == previous
    dialog.assert_not_called()
