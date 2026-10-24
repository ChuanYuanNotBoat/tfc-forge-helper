"""Read Java launch arguments on Windows, exposing only validated game directories."""
import ctypes
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Instance:
    path: Path
    origin: str
    pid: int | None = None


def windows_arguments(command: str) -> list[str]:
    if os.name != "nt":
        raise OSError("进程启动参数检测目前支持 Windows")
    argc = ctypes.c_int()
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argv = shell.CommandLineToArgvW(command, ctypes.byref(argc))
    if not argv:
        return []
    try:
        return [argv[i] for i in range(argc.value)]
    finally:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(argv, ctypes.c_void_p))


def game_directory(arguments: list[str]) -> Path | None:
    value = None
    for i, token in enumerate(arguments):
        if token == "--gameDir" and i + 1 < len(arguments):
            value = arguments[i + 1]
            break
        if token.startswith("--gameDir="):
            value = token.split("=", 1)[1]
            break
    if value is None:
        value = next((x[len("-Duser.dir="):] for x in arguments if x.startswith("-Duser.dir=")), None)
    if value:
        path = Path(value)
        # Relative paths need a process working directory we deliberately do not probe.
        if path.is_absolute() and (path / "options.txt").is_file() and (path / "mods").is_dir():
            return path.resolve()
    return None


def directory_from_process(pid: int, arguments: list[str], cwd_reader=None) -> Path | None:
    """Launchers can hide --gameDir after startup. Use OS process cwd as fallback."""
    direct = game_directory(arguments)
    if direct is not None:
        return direct
    if not any("minecraft" in arg.lower() or "bootstraplauncher" in arg.lower()
               or "modlauncher" in arg.lower() for arg in arguments):
        return None
    try:
        if cwd_reader is None:
            import psutil
            def read_cwd(value):
                try:
                    return psutil.Process(value).cwd()
                except psutil.Error as exc:
                    raise OSError("进程已退出或无法读取其工作目录") from exc
            cwd_reader = read_cwd
        base = Path(cwd_reader(pid))
        for candidate in (base, base / ".minecraft", base / "minecraft"):
            if (candidate / "options.txt").is_file() and (candidate / "mods").is_dir():
                return candidate.resolve()
    except (OSError, RuntimeError):
        pass
    return None


def process_instances() -> tuple[list[Instance], list[str]]:
    if os.name != "nt":
        return [], ["进程检测目前支持 Windows；可手动指定实例目录"]
    script = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
              "@(Get-CimInstance Win32_Process -Filter \"Name='java.exe' OR Name='javaw.exe'\" | "
              "Select-Object ProcessId,CommandLine) | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=8,
                                creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        if result.returncode:
            return [], ["无法读取 Java 进程启动信息；将检查常见实例目录"]
        rows = json.loads(result.stdout or "[]")
        if isinstance(rows, dict):
            rows = [rows]
        found = []
        for row in rows:
            args = windows_arguments(row.get("CommandLine") or "")
            path = directory_from_process(int(row["ProcessId"]), args)
            if path is not None:
                found.append(Instance(path, "运行中的 Java 进程", int(row["ProcessId"])))
        return found, []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        # Never report the raw command line: it can contain access tokens.
        return [], ["进程检测不可用；请从候选目录选择或手动指定"]


def discover() -> tuple[list[Instance], list[str]]:
    found, warnings = process_instances()
    appdata = Path(os.environ.get("APPDATA", Path.home()))
    roots = [appdata / ".minecraft", Path.home() / ".minecraft", Path.cwd() / ".minecraft"]
    for launcher in (appdata / "PrismLauncher", appdata / "MultiMC"):
        instances = launcher / "instances"
        if instances.is_dir():
            roots.extend(p / ".minecraft" for p in instances.iterdir() if p.is_dir())
            roots.extend(p / "minecraft" for p in instances.iterdir() if p.is_dir())
    found.extend(Instance(p.resolve(), "常见启动器目录") for p in roots
                 if (p / "options.txt").is_file() and (p / "mods").is_dir())
    unique = {}
    for item in found:
        unique.setdefault(os.path.normcase(str(item.path)), item)
    return list(unique.values()), warnings


def resource_signature(instance: Path | None, jar: Path | None, packs: tuple[Path, ...]) -> tuple:
    """Cheap watch key; resolved stack covers options, enabled packs and selected jar."""
    paths = list(packs)
    if jar:
        paths.append(jar)
    if instance:
        paths.append(instance / "options.txt")
        mods = instance / "mods"
        if mods.is_dir():
            paths.extend(p for p in mods.glob("*.jar")
                         if "tfc" in p.name.lower() or "terrafirmacraft" in p.name.lower())
        resourcepacks = instance / "resourcepacks"
        if resourcepacks.is_dir():
            paths.extend(resourcepacks.iterdir())
    values = []
    for path in paths:
        try:
            stat = path.stat()
            values.append((str(path), stat.st_mtime_ns, stat.st_size))
            if path.is_dir():
                for relative in ("pack.mcmeta", "assets/tfc/textures/gui/anvil.png"):
                    item = path / relative
                    if item.is_file():
                        st = item.stat()
                        values.append((str(item), st.st_mtime_ns, st.st_size))
                metadata = path / "pack.mcmeta"
                if metadata.is_file():
                    try:
                        entries = json.loads(metadata.read_text(encoding="utf-8-sig")).get("overlays", {}).get("entries", [])
                        for entry in entries:
                            item = (path / entry["directory"] / "assets/tfc/textures/gui/anvil.png").resolve()
                            if item.is_relative_to(path.resolve()):
                                st = item.stat() if item.is_file() else None
                                values.append((str(item), st.st_mtime_ns if st else None, st.st_size if st else None))
                    except (OSError, ValueError, KeyError, TypeError):
                        values.append((str(metadata), "invalid-overlay"))
        except OSError:
            values.append((str(path), None))
    return tuple(values)
