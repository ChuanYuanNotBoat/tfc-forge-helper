import io
import json
from zipfile import ZipFile

import pytest
from PIL import Image

from tfc_forge_helper.assets import RESOURCE, AssetError, enabled_packs, resolve_atlas
from tfc_forge_helper.discovery import game_directory, resource_signature, windows_arguments


def png(color, size=256):
    buffer = io.BytesIO()
    Image.new("RGBA", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


def pack(path, members):
    with ZipFile(path, "w") as z:
        for name, value in members.items():
            z.writestr(name, value)
    return path


def test_options_priority_and_block_texture_fallback(tmp_path):
    mods, packs = tmp_path / "mods", tmp_path / "resourcepacks"
    mods.mkdir()
    packs.mkdir()
    pack(mods / "TerraFirmaCraft-1.21.1.jar", {RESOURCE: png("red")})
    pack(packs / "low.zip", {RESOURCE: png("green")})
    pack(packs / "high.zip", {RESOURCE: png("blue")})
    pack(packs / "blocks.zip", {"assets/minecraft/textures/block/stone.png": png("black")})
    (tmp_path / "options.txt").write_text('resourcePacks:["vanilla","mod_resources","file/low.zip","file/high.zip","file/blocks.zip"]', encoding="utf-8")
    result = resolve_atlas(tmp_path)
    assert result.image.getpixel((0, 0)) == (0, 0, 255, 255)
    assert result.source.endswith("high.zip")


def test_folder_and_hd_override(tmp_path):
    jar = pack(tmp_path / "tfc.jar", {RESOURCE: png("red")})
    folder = tmp_path / "folder"
    asset = folder / RESOURCE
    asset.parent.mkdir(parents=True)
    asset.write_bytes(png("blue", 512))
    result = resolve_atlas(jar=jar, packs=(folder,))
    assert result.image.size == (256, 256)
    assert result.image.getpixel((0, 0)) == (0, 0, 255, 255)


def test_overlays_and_filter(tmp_path):
    base = pack(tmp_path / "tfc.jar", {RESOURCE: png("red")})
    overlay = pack(tmp_path / "o.zip", {"pack.mcmeta": json.dumps({"overlays": {"entries": [
        {"formats": {"min_inclusive": 34, "max_inclusive": 34}, "directory": "new"}]}}),
        RESOURCE: png("green"), "new/" + RESOURCE: png("blue")})
    assert resolve_atlas(jar=base, packs=(overlay,)).image.getpixel((0, 0)) == (0, 0, 255, 255)
    filtered = pack(tmp_path / "f.zip", {"pack.mcmeta": json.dumps({"filter": {"block": [
        {"namespace": "tfc", "path": "textures/gui/.*"}]}})})
    with pytest.raises(AssetError, match="屏蔽"):
        resolve_atlas(jar=base, packs=(filtered,))


def test_missing_and_traversal(tmp_path):
    with pytest.raises(AssetError):
        resolve_atlas(packs=(tmp_path / "missing.zip",))
    (tmp_path / "options.txt").write_text('resourcePacks:["file/../elsewhere.zip"]', encoding="utf-8")
    with pytest.raises(AssetError, match="越界"):
        enabled_packs(tmp_path)


def test_signature_detects_pack_changes(tmp_path):
    p = tmp_path / "p.zip"
    pack(p, {RESOURCE: png("red")})
    before = resource_signature(None, None, (p,))
    pack(p, {RESOURCE: png("blue"), "extra": "change"})
    assert resource_signature(None, None, (p,)) != before


def test_process_directory_with_spaces(tmp_path):
    instance = tmp_path / "测试 instance"
    instance.mkdir()
    (instance / "options.txt").touch()
    (instance / "mods").mkdir()
    assert game_directory(["javaw.exe", "--gameDir", str(instance), "--accessToken", "secret"]) == instance.resolve()
    assert game_directory(["javaw.exe", f"--gameDir={instance}"]) == instance.resolve()
    assert game_directory(["javaw.exe", "--gameDir", "relative"]) is None


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows argument parser")
def test_windows_process_arguments():
    args = windows_arguments('"C:\\Program Files\\Java\\javaw.exe" --gameDir "E:\\游戏\\My Instance" --accessToken hidden')
    assert args[2] == "E:\\游戏\\My Instance"
    assert args[0] == "C:\\Program Files\\Java\\javaw.exe"


def test_launcher_hidden_arguments_uses_process_working_directory(tmp_path):
    from tfc_forge_helper.discovery import directory_from_process
    (tmp_path / "options.txt").touch()
    (tmp_path / "mods").mkdir()
    args = ["java.exe", "net.minecraft.client.main.Main"]
    assert directory_from_process(123, args, lambda pid: str(tmp_path)) == tmp_path.resolve()
    # An unrelated Java service must not be treated as a game merely because it
    # happens to run in the same folder.
    assert directory_from_process(123, ["java.exe", "server.Main"], lambda pid: str(tmp_path)) is None


def test_process_exit_during_working_directory_detection():
    from tfc_forge_helper.discovery import directory_from_process
    def gone(pid):
        raise OSError("process exited")
    assert directory_from_process(123, ["java.exe", "net.minecraft.client.main.Main"], gone) is None


def test_file_atlas_shadows_lower_unknown_builtin_packs(tmp_path):
    packs = tmp_path / "resourcepacks"
    packs.mkdir()
    pack(packs / "ui.zip", {RESOURCE: png("blue")})
    (tmp_path / "options.txt").write_text(
        'resourcePacks:["vanilla","fabric","mod_resources","moonlight:merged_pack","file/ui.zip"]',
        encoding="utf-8")
    paths, warnings = enabled_packs(tmp_path)
    assert len(paths) == 1 and not warnings
    # Unknown packs above the last atlas supplier remain unresolved.
    (tmp_path / "options.txt").write_text(
        'resourcePacks:["file/ui.zip","moonlight:merged_pack"]', encoding="utf-8")
    assert enabled_packs(tmp_path)[1]
