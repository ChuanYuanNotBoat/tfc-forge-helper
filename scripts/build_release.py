"""Validate and build Windows x64 and Python distributions. Run from the repository."""

import ast
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
from importlib.metadata import distribution
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DISTRIBUTIONS = ("Pillow", "numpy", "opencv-python-headless", "mss", "psutil")


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True, **kwargs)


def collect_notices(target):
    versions = {}
    for name in RUNTIME_DISTRIBUTIONS:
        package = distribution(name)
        versions[name] = package.version
        count = 0
        for entry in package.files or ():
            if not any(word in entry.name.lower() for word in ("license", "copying", "notice")):
                continue
            source = Path(package.locate_file(entry))
            if source.is_file():
                relative = Path(*[part for part in entry.parts if part not in ("..", ".")])
                destination = target / name / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                count += 1
        if not count:
            raise RuntimeError(f"No license files found for {name}")
    base = Path(sys.base_prefix)
    python_license = base / "LICENSE.txt"
    shutil.copyfile(python_license, target / "Python-LICENSE.txt")
    # The Tcl library can live under lib rather than tcl in some Python builds.
    import tkinter
    interpreter = tkinter.Tcl()
    tcl = Path(interpreter.eval("info library")) / "license.terms"
    if not tcl.is_file():
        # Microsoft Store Python omits Tcl's copy; preserve the upstream 8.6 license.
        tcl = ROOT / "packaging" / "licenses" / "Tcl-license.terms"
    tk_candidates = [base / "tcl" / "tk8.6" / "license.terms", tcl.parent.parent / "tk8.6" / "license.terms"]
    for label, source in (("Tcl", tcl), ("Tk", next((p for p in tk_candidates if p.is_file()), tk_candidates[0]))):
        shutil.copyfile(source, target / f"{label}-license.terms")
    (target / "VERSIONS.json").write_text(json.dumps({"Python": platform.python_version(), **versions}, indent=2),
                                          encoding="utf-8")


def smoke_test(executable, version):
    # Run a copy with no Python on PATH, outside the checkout, including a Unicode path.
    with tempfile.TemporaryDirectory(prefix="tfc-release-") as directory:
        scratch = Path(directory) / "独立运行 test"
        scratch.mkdir()
        copied = scratch / executable.name
        shutil.copyfile(executable, copied)
        report = scratch / "report.json"
        env = os.environ.copy()
        for key in ("PYTHONPATH", "PYTHONHOME"):
            env.pop(key, None)
        env.update(PATH=str(Path(os.environ["SystemRoot"]) / "System32"),
                   PYTHONNOUSERSITE="1", LOCALAPPDATA=str(scratch / "settings"))
        subprocess.run([str(copied), "self-test", "--report", str(report)], cwd=scratch,
                       env=env, check=True, timeout=120)
        result = json.loads(report.read_text(encoding="utf-8"))
        expected = scratch / "settings" / "TFCForgeHelper"
        if not result["ok"] or not result["frozen"] or result["version"] != version:
            raise RuntimeError(f"EXE smoke check failed: {result}")
        if Path(result["data_directory"]) != expected:
            raise RuntimeError("EXE settings must be outside its temporary extraction directory")
        (ROOT / "build" / "exe-smoke-test.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                                          encoding="utf-8")
        print("Standalone EXE smoke check passed (Tk, Pillow, NumPy, OpenCV, psutil, mss, solver).", flush=True)


def main():
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise SystemExit("Build with 64-bit Python on Windows.")
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = metadata["project"]["version"]
    module = ast.parse((ROOT / "src" / "tfc_forge_helper" / "__init__.py").read_text(encoding="utf-8"))
    source_version = next(ast.literal_eval(node.value) for node in module.body
                          if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "__version__"
                                                                 for t in node.targets))
    if version != source_version:
        raise SystemExit("Version differs between pyproject.toml and __init__.py.")
    run(sys.executable, "-m", "pytest", "-q")
    run(sys.executable, "-m", "ruff", "check", "src", "tests", "scripts", "packaging")
    run(sys.executable, "-m", "pip", "check")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    output = ROOT / "dist" / version
    if output.exists():
        raise SystemExit(f"Output already exists: {output}. Move it aside before rebuilding.")
    output.mkdir(parents=True)
    run(sys.executable, "-m", "build", "--no-isolation", "--outdir", output)
    python_artifacts = sorted(output.glob("*.whl")) + sorted(output.glob("*.tar.gz"))
    run(sys.executable, "-m", "twine", "check", "--strict", *python_artifacts)
    with tempfile.TemporaryDirectory(prefix="tfc-notices-", dir=build) as directory:
        notices = Path(directory)
        collect_notices(notices)
        # Windowed one-file build: Tcl/Tk, Pillow, NumPy and OpenCV use their upstream hooks.
        run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
            "--noupx", "--name", "TFC-Forge-Helper", "--paths", ROOT / "src",
            "--distpath", build / "windows", "--workpath", build / "pyinstaller",
            "--specpath", build, "--add-data", f"{notices}:third-party-licenses",
            "--add-data", f"{ROOT / 'LICENSE'}:.", ROOT / "packaging" / "windows_entry.py")
        executable = build / "windows" / "TFC-Forge-Helper.exe"
        smoke_test(executable, version)
        archive = output / f"tfc-forge-helper-{version}-windows-x64.zip"
        prefix = f"tfc-forge-helper-{version}"
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
            bundle.write(executable, f"{prefix}/{executable.name}")
            for name in ("README.md", "LICENSE", "CHANGELOG.md", "profiles/default.json"):
                bundle.write(ROOT / name, f"{prefix}/{name}")
            for path in sorted((ROOT / "docs").glob("*.md")):
                bundle.write(path, f"{prefix}/docs/{path.name}")
            for path in sorted(notices.rglob("*")):
                if path.is_file():
                    bundle.write(path, f"{prefix}/third-party-licenses/{path.relative_to(notices).as_posix()}")
    checksums = []
    for path in sorted(output.iterdir()):
        with path.open("rb") as stream:
            checksums.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {path.name}\n")
    (output / "SHA256SUMS.txt").write_text("".join(checksums), encoding="utf-8")
    print(f"Release artifacts ready: {output}", flush=True)


if __name__ == "__main__":
    main()
