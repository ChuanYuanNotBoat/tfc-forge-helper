import json

from tfc_forge_helper import diagnostics


def test_packaged_runtime_check_never_initializes_a_desktop_window(monkeypatch, tmp_path):
    original = diagnostics.tk.Tk
    def headless_only(*args, **kwargs):
        use_tk = kwargs.get("useTk", args[3] if len(args) > 3 else True)
        assert not use_tk, "The runtime check must not create a native window"
        return original(*args, **kwargs)
    monkeypatch.setattr(diagnostics.tk, "Tk", headless_only)
    report = tmp_path / "report.json"
    diagnostics.self_test(report)
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["ok"] and not result["desktop_window_created"]
    assert result["solver_steps"] == 7
