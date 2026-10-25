import io
import json
from zipfile import ZipFile

from conftest import render_frame

from tfc_forge_helper.discovery import Instance
from tfc_forge_helper.engine import Config, Engine


def write_atlas(path, atlas):
    buffer = io.BytesIO()
    atlas.image.save(buffer, format="PNG")
    with ZipFile(path, "w") as archive:
        archive.writestr("assets/tfc/textures/gui/anvil.png", buffer.getvalue())


def test_process_auto_selection_and_live_pack_switch(atlas, tmp_path, monkeypatch):
    instance = tmp_path / "TFC instance"
    (instance / "mods").mkdir(parents=True)
    (instance / "resourcepacks").mkdir()
    jar = instance / "mods" / "TerraFirmaCraft-1.21.1.jar"
    write_atlas(jar, atlas)
    options = instance / "options.txt"
    options.write_text('resourcePacks:["vanilla","mod_resources"]', encoding="utf-8")
    monkeypatch.setattr("tfc_forge_helper.engine.discover", lambda: ([Instance(instance, "test process", 123)], []))
    engine, config = Engine(), Config()
    first = engine.analyze(render_frame(atlas), config)
    assert engine.instance == str(instance)
    assert engine.pid == 123
    assert first.assets.source == str(jar)
    assert first.solution.positions[-1] == first.observation.target
    revision = engine.revision
    # A pack enable change must be picked up without restarting or force=True.
    override = instance / "resourcepacks" / "override.zip"
    write_atlas(override, atlas)
    options.write_text('resourcePacks:["vanilla","mod_resources","file/override.zip"]', encoding="utf-8")
    second = engine.analyze(render_frame(atlas), config)
    assert engine.revision > revision
    assert second.assets.source == str(override)
    assert second.solution is first.solution  # Same recognized state can reuse the exact plan.


def test_profile_reload_and_folder_overlay_signature(atlas, tmp_path):
    from tfc_forge_helper.discovery import resource_signature
    from tfc_forge_helper.profile import Profile
    pack = tmp_path / "pack"
    nested = pack / "new/assets/tfc/textures/gui/anvil.png"
    nested.parent.mkdir(parents=True)
    metadata = {"overlays": {"entries": [{"formats": 34, "directory": "new"}]}}
    (pack / "pack.mcmeta").write_text(json.dumps(metadata), encoding="utf-8")
    atlas.image.save(nested)
    signature = resource_signature(None, None, (pack,))
    image = atlas.image.copy()
    image.putpixel((20, 20), (1, 2, 3, 255))
    image.save(nested)
    assert resource_signature(None, None, (pack,)) != signature
    profile = tmp_path / "profile.json"
    Profile().save(profile)
    engine = Engine()
    config = Config(packs=(str(pack),), profile=str(profile), auto_instance=False)
    engine.refresh(config)
    before = engine.revision
    from dataclasses import replace
    replace(Profile(), name="changed").save(profile)
    engine.refresh(config)
    assert engine.revision > before


def test_automation_defers_process_scan_but_still_reloads_resource_changes(atlas, tmp_path, monkeypatch):
    from unittest.mock import Mock

    instance = tmp_path / "instance"
    (instance / "mods").mkdir(parents=True)
    (instance / "resourcepacks").mkdir()
    write_atlas(instance / "mods" / "TerraFirmaCraft-1.21.1.jar", atlas)
    options = instance / "options.txt"
    options.write_text('resourcePacks:["vanilla"]', encoding="utf-8")
    discovery = Mock(return_value=([Instance(instance, "test process", 123)], []))
    monkeypatch.setattr("tfc_forge_helper.engine.discover", discovery)
    clock = [0.0]
    monkeypatch.setattr("tfc_forge_helper.engine.time.monotonic", lambda: clock[0])
    engine, config = Engine(), Config()
    engine.refresh(config)
    revision = engine.revision
    clock[0] = 20.0
    engine.refresh_automation(config)
    assert discovery.call_count == 1
    assert engine.pid == 123 and engine.revision == revision
    override = instance / "resourcepacks" / "override.zip"
    write_atlas(override, atlas)
    options.write_text('resourcePacks:["file/override.zip"]', encoding="utf-8")
    resolved, _ = engine.refresh_automation(config)
    assert resolved.source == str(override)
    assert engine.revision > revision and discovery.call_count == 1
    engine.refresh(config)  # Normal idle monitoring resumes discovery.
    assert discovery.call_count == 2


def test_cold_automation_refresh_still_discovers_running_instance(atlas, tmp_path, monkeypatch):
    instance = tmp_path / "instance"
    (instance / "mods").mkdir(parents=True)
    write_atlas(instance / "mods" / "TerraFirmaCraft-1.21.1.jar", atlas)
    (instance / "options.txt").write_text('resourcePacks:[]', encoding="utf-8")
    monkeypatch.setattr("tfc_forge_helper.engine.discover", lambda: ([Instance(instance, "test process", 123)], []))
    engine = Engine()
    engine.refresh_automation(Config())
    assert engine.pid == 123 and engine.instance == str(instance)
