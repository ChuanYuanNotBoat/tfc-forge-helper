import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from . import __version__
from .capture import enable_dpi_awareness, screenshot
from .discovery import discover
from .engine import Config, Engine
from .model import parse_history, parse_rules
from .solver import solve


def solution_dict(solution):
    return {"current": solution.current, "target": solution.target, "steps": solution.steps,
            "actions": [a.name.lower() for a in solution.actions],
            "positions": solution.positions, "explored": solution.explored}


def add_sources(parser):
    parser.add_argument("--instance", type=Path, help="Minecraft 实例目录；省略则从进程自动检测")
    parser.add_argument("--jar", type=Path, help="TFC 1.21.1 JAR")
    parser.add_argument("--pack", type=Path, action="append", default=[], help="额外资源包，重复指定时后者优先")
    parser.add_argument("--profile", type=Path)


def config_from(args):
    return Config(str(args.instance or ""), str(args.jar or ""), tuple(str(p) for p in args.pack),
                  str(args.profile or ""), auto_instance=args.instance is None)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="TFC 1.21.1 外部锻造助手（默认辅助，可在窗口内启用自动打铁）")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    manual = sub.add_parser("solve", help="手工输入并求最少剩余步数")
    manual.add_argument("--current", type=int, required=True)
    manual.add_argument("--target", type=int, required=True)
    manual.add_argument("--rules", default="", help="例如 bend_not_last,draw_not_last,punch_last")
    manual.add_argument("--history", default="", help="最近三步，由旧到新，例如 shrink,bend")
    manual.add_argument("--tolerance", type=int, default=0)
    inspect = sub.add_parser("detect", help="识别图片或当前屏幕并求解")
    add_sources(inspect)
    inspect.add_argument("--image", type=Path)
    inspect.add_argument("--monitor", type=int, default=-1, help="-1 自动跟随游戏窗口，1 主屏，0 全部屏幕")
    inspect.add_argument("--tolerance", type=int, default=0)
    inspect.add_argument("--annotate", type=Path, help="保存带定位框的诊断图")
    assets = sub.add_parser("assets", help="显示最终砧贴图来源和优先级")
    add_sources(assets)
    assets.add_argument("--export", type=Path, help="导出规范化后的 256×256 贴图")
    sub.add_parser("discover", help="自动检测正在运行的 TFC 实例")
    diagnostic = sub.add_parser("self-test", help="验证运行时、桌面组件及求解器，不发送游戏操作")
    diagnostic.add_argument("--report", type=Path, required=True, help="将验证结果写入 JSON 文件")
    gui = sub.add_parser("gui", help="打开桌面窗口")
    add_sources(gui)
    args = parser.parse_args(argv)
    try:
        if args.command == "self-test":
            from .diagnostics import self_test
            self_test(args.report)
        elif args.command == "solve":
            result = solve(args.current, args.target, parse_rules(args.rules), parse_history(args.history), args.tolerance)
            print(json.dumps(solution_dict(result), ensure_ascii=False, indent=2))
        elif args.command == "discover":
            instances, warnings = discover()
            print(json.dumps({"instances": [{"path": str(x.path), "origin": x.origin, "pid": x.pid}
                                            for x in instances], "warnings": warnings}, ensure_ascii=False, indent=2))
        elif args.command == "assets":
            atlas, _ = Engine().refresh(config_from(args), force=True)
            if args.export:
                args.export.parent.mkdir(parents=True, exist_ok=True)
                atlas.image.save(args.export)
            print(json.dumps({"source": atlas.source, "stack_low_to_high": atlas.stack,
                              "warnings": atlas.warnings}, ensure_ascii=False, indent=2))
        elif args.command == "detect":
            enable_dpi_awareness()
            engine, config = Engine(), config_from(args)
            engine.refresh(config)
            image = Image.open(args.image).convert("RGB") if args.image else screenshot(args.monitor, engine.pid)
            result = engine.analyze(image, config, args.tolerance)
            report = {"observation": {**asdict(result.observation),
                                      "rules": [r.name for r in result.observation.rules],
                                      "history": [a.category for a in result.observation.history]},
                      "solution": solution_dict(result.solution), "texture_source": result.assets.source,
                      "warnings": result.assets.warnings}
            if args.annotate:
                from PIL import ImageDraw
                x, y, w, h = result.observation.region
                ImageDraw.Draw(image).rectangle((x, y, x + w, y + h), outline="#22ddaa", width=3)
                args.annotate.parent.mkdir(parents=True, exist_ok=True)
                image.save(args.annotate)
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            from .gui import launch
            launch(config_from(args) if args.command == "gui" else Config())
    except (ValueError, OSError) as exc:
        parser.exit(2, f"错误：{exc}\n")


if __name__ == "__main__":
    main()
