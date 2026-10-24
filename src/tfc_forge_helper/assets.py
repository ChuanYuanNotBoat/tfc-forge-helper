"""Resolve the atlas from a mod jar, then enabled packs from low to high priority.

Archives are read directly; neither game files nor resource packs are modified.
"""
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from PIL import Image

RESOURCE = "assets/tfc/textures/gui/anvil.png"
PACK_FORMAT = 34  # Minecraft 1.21 / 1.21.1 resource pack format.


class AssetError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedAtlas:
    image: Image.Image
    source: str
    stack: tuple[str, ...]
    warnings: tuple[str, ...]


class Pack:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        if not self.path.exists():
            raise AssetError(f"资源不存在：{self.path}")
        if not self.path.is_dir() and not self.path.is_file():
            raise AssetError(f"无效资源路径：{self.path}")
        self.meta = {}
        data = self.read("pack.mcmeta")
        if data:
            try:
                self.meta = json.loads(data.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AssetError(f"pack.mcmeta 无法读取：{self.path}") from exc

    def read(self, member: str) -> bytes | None:
        parts = member.split("/")
        if ".." in parts or member.startswith(("/", "\\")) or "\\" in member:
            raise AssetError("资源路径必须是包内相对路径")
        if self.path.is_dir():
            candidate = self.path.joinpath(*parts).resolve()
            if not candidate.is_relative_to(self.path):
                raise AssetError("资源路径越界")
            return candidate.read_bytes() if candidate.is_file() else None
        try:
            with ZipFile(self.path) as archive:
                try:
                    info = archive.getinfo(member)
                except KeyError:
                    return None
                if info.file_size > 32 * 1024 * 1024:
                    raise AssetError(f"单个资源大于 32MB：{member}")
                return archive.read(info)
        except BadZipFile as exc:
            raise AssetError(f"不是有效的 ZIP/JAR：{self.path}") from exc

    def resource(self, member: str) -> bytes | None:
        # Later applicable overlays override earlier entries, then the pack root.
        entries = self.meta.get("overlays", {}).get("entries", [])
        for entry in reversed(entries):
            formats = entry.get("formats", {})
            if isinstance(formats, int):
                low = high = formats
            elif isinstance(formats, list) and len(formats) == 2:
                low, high = formats
            elif isinstance(formats, dict):
                low, high = formats.get("min_inclusive", 0), formats.get("max_inclusive", 0)
            else:
                continue
            if low <= PACK_FORMAT <= high:
                result = self.read(f"{entry['directory']}/{member}")
                if result is not None:
                    return result
        return self.read(member)

    def blocks(self, member: str) -> bool:
        _, namespace, resource_path = member.split("/", 2)
        for entry in self.meta.get("filter", {}).get("block", []):
            try:
                if re.fullmatch(entry.get("namespace", ".*"), namespace) and re.fullmatch(
                    entry.get("path", ".*"), resource_path
                ):
                    return True
            except re.error as exc:
                raise AssetError(f"不支持的资源过滤表达式：{self.path}") from exc
        return False


def enabled_packs(instance: Path) -> tuple[list[Path], list[str]]:
    options = instance / "options.txt"
    if not options.is_file():
        raise AssetError(f"找不到 {options}；请选择实际游戏实例目录")
    identifiers = []
    for line in options.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("resourcePacks:"):
            try:
                identifiers = json.loads(line.split(":", 1)[1])
            except json.JSONDecodeError as exc:
                raise AssetError("options.txt 的 resourcePacks 不是有效 JSON") from exc
            break
    if not isinstance(identifiers, list) or not all(isinstance(x, str) for x in identifiers):
        raise AssetError("resourcePacks 必须是字符串列表")
    paths, warnings = [], []
    base = (instance / "resourcepacks").resolve()
    for index, identifier in enumerate(identifiers):
        if identifier.startswith("file/"):
            candidate = (base / identifier[5:]).resolve()
            if not candidate.is_relative_to(base):
                raise AssetError("options.txt 中的资源包路径越界")
            paths.append(candidate)
        elif identifier not in ("vanilla", "mod_resources", "neoforge", "fabric"):
            # A later file pack that supplies this atlas fully shadows lower
            # built-in packs. Their unknown contents cannot affect this resource.
            shadowed = False
            for later in identifiers[index + 1:]:
                if later.startswith("file/"):
                    candidate = (base / later[5:]).resolve()
                    if candidate.is_relative_to(base) and candidate.exists() and Pack(candidate).resource(RESOURCE) is not None:
                        shadowed = True
                        break
            if shadowed:
                continue
            # Unknown built-in packs can override this atlas; do not silently ignore.
            warnings.append(f"内置资源包 {identifier} 未解析；如覆盖砧 GUI，请显式添加其 ZIP/目录")
    return paths, warnings


def find_tfc_jar(instance: Path) -> Path:
    candidates = []
    for path in sorted((instance / "mods").glob("*.jar")):
        if ("tfc" in path.name.lower() or "terrafirmacraft" in path.name.lower()) and Pack(path).read(RESOURCE) is not None:
            candidates.append(path)
    if len(candidates) != 1:
        raise AssetError("不能唯一确定 TFC JAR，请在界面或 --jar 中指定")
    return candidates[0]


def resolve_atlas(instance: Path | None = None, jar: Path | None = None,
                  packs: tuple[Path, ...] = (), resource: str = RESOURCE) -> ResolvedAtlas:
    paths, warnings = [], []
    if instance is not None:
        instance = Path(instance)
        if jar is None:
            jar = find_tfc_jar(instance)
        enabled, notices = enabled_packs(instance)
        paths.extend(enabled)
        warnings.extend(notices)
    if jar is not None:
        paths.insert(0, Path(jar))
    paths.extend(Path(x) for x in packs)
    if not paths:
        raise AssetError("请指定游戏实例、TFC JAR 或覆盖砧 GUI 的资源包")
    sources = [Pack(path) for path in paths]
    for pack in sources:
        info = pack.meta.get("pack", {})
        version = info.get("pack_format")
        supported = info.get("supported_formats", version)
        compatible = version == PACK_FORMAT
        if isinstance(supported, list) and len(supported) == 2:
            compatible = supported[0] <= PACK_FORMAT <= supported[1]
        elif isinstance(supported, dict):
            compatible = supported.get("min_inclusive", 0) <= PACK_FORMAT <= supported.get("max_inclusive", 0)
        if version is not None and not compatible:
            warnings.append(f"{pack.path.name} 标注 pack_format={version}，1.21.1 使用 34；按显式/启用顺序读取")
    data, source = None, None
    for pack in reversed(sources):
        data = pack.resource(resource)
        if data is not None:
            source = pack.path
            break
        if pack.blocks(resource):
            raise AssetError(f"砧贴图被资源过滤器屏蔽：{pack.path}")
    if data is None:
        raise AssetError(f"资源栈中没有 {resource}；普通方块包需要 TFC JAR 作为回退")
    try:
        atlas = Image.open(io.BytesIO(data)).convert("RGBA")
    except (OSError, ValueError) as exc:
        raise AssetError(f"无法读取砧贴图：{source}") from exc
    if atlas.width != atlas.height or atlas.width < 256 or atlas.width % 256:
        raise AssetError("砧贴图应为 256×256 或等比例高清图；特殊布局请提供 profile")
    atlas = atlas.resize((256, 256), Image.Resampling.NEAREST)
    return ResolvedAtlas(atlas, str(source), tuple(str(p.path) for p in sources), tuple(warnings))
