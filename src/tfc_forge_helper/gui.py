import ctypes
import json
import os
import queue
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import __version__
from .automation import AutoForge
from .batch import BatchForge
from .capture import enable_dpi_awareness, screenshot
from .engine import Config, Engine
from .model import CATEGORIES, ORDER_LABELS, Rule, parse_history
from .paths import data_directory, profiles_directory
from .profile import Profile
from .solver import solve

SETTINGS = data_directory() / "settings.json"
CAT_LABELS = dict(zip(CATEGORIES, ("击打", "拉伸", "冲孔", "弯曲", "镦锻", "收缩")))
BG, PANEL, INK, MUTED, ACCENT = "#101922", "#1b2936", "#eef4f8", "#a3b6c6", "#71e0b4"


class App:
    def __init__(self, root, config):
        self.root = root
        self.engine = Engine()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forge-read")
        self.future = None
        self.generation = 0
        self.updating = False
        self.closed = False
        self.last_auto = 0
        self.last_refresh = 0
        self.last_solution = None
        self.last_source = ""
        self.source_revision = 0
        self.overlay = None
        self.hotkeys = queue.Queue()
        self.hotkey_stop = threading.Event()
        self.forge_stop = threading.Event()
        self.forge_messages = queue.Queue()
        self.f9_registered = False
        self.pending_forging = False
        root.title(f"TFC 锻造助手 · 1.21.1 · 批量版 v{__version__}")
        root.geometry("1060x900")
        root.minsize(940, 840)
        root.configure(bg=BG)
        self._style()
        if config == Config() and SETTINGS.is_file():
            try:
                saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
                saved["packs"] = tuple(saved.get("packs", []))
                config = Config(**saved)
            except (OSError, ValueError, TypeError):
                pass
        self.instance = tk.StringVar(value=config.instance)
        self.jar = tk.StringVar(value=config.jar)
        self.packs = tk.StringVar(value=";".join(config.packs))
        self.profile = tk.StringVar(value=config.profile)
        self.auto_instance = tk.BooleanVar(value=config.auto_instance)
        self.current = tk.StringVar(value="83")
        self.target = tk.StringVar(value="108")
        self.history = tk.StringVar()
        self.tolerance = tk.StringVar(value="0")
        self.monitor = tk.StringVar(value="-1")
        self.live = tk.BooleanVar(value=True)
        self.show_overlay = tk.BooleanVar(value=False)
        self.topmost = tk.BooleanVar(value=False)
        self.allow_forging = tk.BooleanVar(value=False)
        self.batch_mode = tk.BooleanVar(value=True)
        self.batch_count = tk.StringVar(value="0")
        self.status = tk.StringVar(value="就绪 · 可直接手工求解；打开游戏后自动定位实例")
        self.resource_status = tk.StringVar(value="正在检查游戏进程和资源…")
        self.next_step = tk.StringVar(value="等待方案")
        self.summary = tk.StringVar(value="输入当前值、目标值和规则，或按 F8 识别屏幕")
        self.overlay_text = tk.StringVar(value="等待识别")
        self.rule_vars = []
        self._build()
        for variable in (self.instance, self.jar, self.packs, self.profile, self.auto_instance,
                         self.current, self.target, self.history, self.tolerance, self.monitor,
                         self.batch_mode, self.batch_count):
            variable.trace_add("write", self._changed)
        for variables in self.rule_vars:
            for variable in variables:
                variable.trace_add("write", self._changed)
        root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self._hotkey_worker, daemon=True, name="forge-hotkey").start()
        root.after(100, self._poll)
        initial_config = self.config()
        self._submit("resources", lambda: self.engine.refresh(initial_config, force=True))

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), background=BG, foreground=INK)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"))
        style.configure("Next.TLabel", font=("Microsoft YaHei UI", 24, "bold"), foreground=ACCENT)
        style.configure("TButton", background="#2c4152", foreground=INK, padding=(12, 8), borderwidth=0)
        style.map("TButton", background=[("active", "#3b586c")])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG)
        style.map("Accent.TButton", background=[("active", "#a0efd0")])
        style.configure("TEntry", fieldbackground=PANEL, foreground=INK, insertcolor=INK, padding=6)
        style.configure("TCombobox", fieldbackground=PANEL, foreground=INK, arrowcolor=INK, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", INK)])
        style.configure("TCheckbutton", background=BG, foreground=INK)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, padding=(18, 8))
        style.map("TNotebook.Tab", background=[("selected", "#2c4152")])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=INK,
                        rowheight=32, borderwidth=0)
        style.configure("Treeview.Heading", background="#2c4152", foreground=INK, padding=7)
        style.map("Treeview", background=[("selected", "#355768")])

    def _build(self):
        outer = ttk.Frame(self.root, padding=24)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="TFC 锻造助手", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=f"1.21.1  /  自动识别 · 批量锻造 v{__version__}", style="Muted.TLabel").pack(side="left", padx=22)
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(16, 12))
        ttk.Button(toolbar, text="识别屏幕  F8", style="Accent.TButton", command=self.capture).pack(side="left")
        ttk.Button(toolbar, text="打开截图", command=self.open_image).pack(side="left", padx=8)
        ttk.Checkbutton(toolbar, text="连续识别", variable=self.live, command=self._live_changed).pack(side="left", padx=8)
        ttk.Checkbutton(toolbar, text="小窗提示", variable=self.show_overlay, command=self._overlay_changed).pack(side="left", padx=8)
        ttk.Checkbutton(toolbar, text="主窗口置顶", variable=self.topmost,
                        command=lambda: self.root.attributes("-topmost", self.topmost.get())).pack(side="right")
        automation = ttk.Frame(outer)
        automation.pack(fill="x", pady=(0, 12))
        self.start_forge_button = ttk.Button(automation, text="开始自动打铁（3 秒）", command=self.start_forging,
                                             state="normal")
        self.start_forge_button.pack(side="left")
        ttk.Button(automation, text="停止  F9", command=self.stop_forging).pack(side="left")
        ttk.Checkbutton(automation, text="批量补料与收成", variable=self.batch_mode).pack(side="left", padx=12)
        ttk.Label(automation, text="数量").pack(side="left")
        ttk.Spinbox(automation, from_=0, to=4096, textvariable=self.batch_count, width=5).pack(side="left", padx=8)
        ttk.Label(automation, text="0 = 同类原料全部加工", style="Muted.TLabel").pack(side="left")
        tabs = ttk.Notebook(outer)
        tabs.pack(fill="both", expand=True)
        solve_tab, settings_tab = ttk.Frame(tabs, padding=16), ttk.Frame(tabs, padding=16)
        tabs.add(solve_tab, text="方案求解")
        tabs.add(settings_tab, text="自动适配与校准")
        solve_tab.columnconfigure(1, weight=1)
        solve_tab.rowconfigure(0, weight=1)
        inputs = ttk.Frame(solve_tab, padding=(0, 0, 24, 0))
        inputs.grid(row=0, column=0, sticky="nsew")
        for label, variable in (("当前位置", self.current), ("目标位置", self.target), ("服务器容差（默认 0）", self.tolerance)):
            ttk.Label(inputs, text=label).pack(anchor="w", pady=(4, 4))
            ttk.Entry(inputs, textvariable=variable, width=27).pack(fill="x")
        ttk.Label(inputs, text="配方规则（槽位顺序不等于执行顺序）", style="Muted.TLabel").pack(anchor="w", pady=(18, 7))
        for i, (category, order) in enumerate((("hit", "third_last"), ("draw", "second_last"), ("draw", "last"))):
            row = ttk.Frame(inputs)
            row.pack(fill="x", pady=4)
            a, b = tk.StringVar(value=CAT_LABELS[category]), tk.StringVar(value=ORDER_LABELS[order])
            self.rule_vars.append((a, b))
            ttk.Label(row, text=str(i + 1), width=2).pack(side="left")
            ttk.Combobox(row, textvariable=a, values=("无", *CAT_LABELS.values()), state="readonly", width=7).pack(side="left")
            ttk.Combobox(row, textvariable=b, values=tuple(ORDER_LABELS.values()), state="readonly", width=13).pack(side="left", padx=(6, 0))
        ttk.Label(inputs, text="最近操作（由旧到新，最多三步）").pack(anchor="w", pady=(16, 4))
        ttk.Entry(inputs, textvariable=self.history).pack(fill="x")
        ttk.Label(inputs, text="如 shrink,bend；新坯可留空\n已操作的坯料应填写或通过截图读取", style="Muted.TLabel").pack(anchor="w", pady=5)
        ttk.Button(inputs, text="计算最短方案", command=self.manual, style="Accent.TButton").pack(fill="x", pady=(18, 0))
        plan = ttk.Frame(solve_tab)
        plan.grid(row=0, column=1, sticky="nsew")
        ttk.Label(plan, text="下一步", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(plan, textvariable=self.next_step, style="Next.TLabel").pack(anchor="w", pady=(5, 3))
        ttk.Label(plan, textvariable=self.summary, style="Muted.TLabel", wraplength=530).pack(anchor="w", pady=(0, 14))
        self.bar = tk.Canvas(plan, height=55, bg=BG, highlightthickness=0)
        self.bar.pack(fill="x", pady=(0, 10))
        self.table = ttk.Treeview(plan, columns=("step", "action", "delta", "work"), show="headings", height=10)
        for key, title, width in (("step", "步骤", 60), ("action", "操作", 170), ("delta", "变化", 75), ("work", "操作后位置", 120)):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, anchor="center", stretch=key == "action")
        scroll = ttk.Scrollbar(plan, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        ttk.Checkbutton(settings_tab, text="自动从正在运行的游戏进程定位实例（每 5 秒检查）",
                        variable=self.auto_instance).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 15))
        settings_tab.columnconfigure(1, weight=1)
        for row, (label, variable, kind) in enumerate((("实例目录", self.instance, "directory"),
                                                     ("TFC JAR（可选）", self.jar, "jar"),
                                                     ("额外资源包（后者优先）", self.packs, "pack"),
                                                     ("校准 profile（可选）", self.profile, "profile")), 1):
            ttk.Label(settings_tab, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=8)
            if kind == "directory":
                entry = ttk.Combobox(settings_tab, textvariable=variable)
                self.instance_combo = entry
            else:
                entry = ttk.Entry(settings_tab, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=8)
            ttk.Button(settings_tab, text="选择", command=lambda k=kind: self.browse(k)).grid(row=row, column=2, padx=(8, 0))
        options = ttk.Frame(settings_tab)
        options.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(12, 8))
        ttk.Label(options, text="截图显示器").pack(side="left")
        ttk.Spinbox(options, from_=-1, to=16, textvariable=self.monitor, width=4).pack(side="left", padx=8)
        ttk.Label(options, text="-1=跟随游戏窗口，1=主屏，0=全部", style="Muted.TLabel").pack(side="left")
        ttk.Button(options, text="重新检测资源", command=self.resources).pack(side="right")
        ttk.Label(settings_tab, textvariable=self.resource_status, wraplength=900, style="Muted.TLabel").grid(
            row=6, column=0, columnspan=3, sticky="nw", pady=15)
        calibration = ttk.Frame(settings_tab)
        calibration.grid(row=7, column=0, columnspan=3, sticky="w", pady=12)
        ttk.Button(calibration, text="框选砧 GUI 并保存校准", command=self.calibrate).pack(side="left")
        ttk.Button(calibration, text="恢复自动位置和缩放", command=lambda: self.profile.set("")).pack(side="left", padx=8)
        ttk.Label(settings_tab, text="默认自动适配位置、整数 GUI 缩放及资源包切换。\n"
                  "进程参数无法读取或实例不唯一时，可在候选列表选择并关闭自动选择。\n"
                  "额外资源包以分号分隔；只有明确指定的包才覆盖游戏当前配置。\n"
                  "请将助手窗口移到砧区域之外；鼠标提示框和其他窗口遮挡会影响识别。",
                  wraplength=900, style="Muted.TLabel").grid(row=8, column=0, columnspan=3, sticky="w", pady=12)
        ttk.Label(outer, textvariable=self.status, wraplength=1000, style="Muted.TLabel").pack(
            side="bottom", before=tabs, fill="x", pady=(14, 0))

    def config(self):
        return Config(self.instance.get().strip(), self.jar.get().strip(),
                      tuple(p.strip() for p in self.packs.get().split(";") if p.strip()),
                      self.profile.get().strip(), self.auto_instance.get())

    def _changed(self, *_):
        if not self.updating:
            self.forge_stop.set()
            self.pending_forging = False
            self.generation += 1
            self._clear("设置已变化，请重新计算或识别")

    def _clear(self, text):
        self.last_solution = None
        self.next_step.set("等待方案")
        self.summary.set(text)
        self.overlay_text.set(text)
        self.table.delete(*self.table.get_children())
        self.bar.delete("all")

    def _submit(self, kind, operation):
        if self.future is not None:
            self.status.set("正在处理，请稍候…")
            return
        self.future_kind, self.future_generation = kind, self.generation
        self.future = self.pool.submit(operation)
        self.status.set({"manual": "正在搜索最少操作…", "resources": "正在自动检测实例与资源…",
                         "capture": "正在识别砧界面…", "calibrate": "正在获取校准截图…",
                         "forge": "自动打铁准备中，请切回游戏；F9 停止"}.get(kind, "正在处理…"))

    def _forging_enabled(self):
        if not self.allow_forging.get():
            self.stop_forging()

    def start_forging(self):
        if self.future is not None:
            if self.future_kind != "forge":
                self.pending_forging = True
                self.status.set("已排队，当前识别完成后将自动开始 3 秒倒计时")
            return
        if not self.f9_registered:
            self.status.set("F9 紧急停止热键不可用，请释放该热键后重启助手")
            return
        try:
            config, tolerance = self.config(), int(self.tolerance.get())
            batch, count = self.batch_mode.get(), int(self.batch_count.get())
            if not 0 <= tolerance <= 150:
                raise ValueError("服务器容差必须在 0–150 内")
            if not 0 <= count <= 4096:
                raise ValueError("数量必须在 0–4096 内，0 表示全部")
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.live.set(False)
        self.pending_forging = False
        self.allow_forging.set(True)
        self.forge_stop.clear()
        self._clear("准备自动打铁，请在 3 秒内切回游戏砧界面；F9 停止")
        self.last_source = "forge"
        if batch:
            self._submit("forge", lambda: BatchForge(self.engine).run(
                config, self.forge_stop, self.forge_messages.put, count=count, tolerance=tolerance))
        else:
            self._submit("forge", lambda: AutoForge(self.engine).run(
                config, self.forge_stop, self.forge_messages.put, tolerance=tolerance))

    def stop_forging(self):
        self.pending_forging = False
        self.forge_stop.set()
        if self.future is not None and self.future_kind == "forge":
            self.status.set("正在停止自动打铁…")

    def manual(self):
        try:
            cats = {v: k for k, v in CAT_LABELS.items()}
            orders = {v: k for k, v in ORDER_LABELS.items()}
            rules = tuple(Rule(cats[a.get()], orders[b.get()]) for a, b in self.rule_vars if a.get() != "无")
            current, target = int(self.current.get()), int(self.target.get())
            tolerance = int(self.tolerance.get())
            history = parse_history(self.history.get())
            self._submit("manual", lambda: solve(current, target, rules, history, tolerance))
        except ValueError as exc:
            self._error(exc)

    def capture(self, path=None):
        try:
            config, monitor, tolerance = self.config(), int(self.monitor.get()), int(self.tolerance.get())
        except ValueError as exc:
            self._error(exc)
            return
        def operation():
            self.engine.refresh(config)
            image = Image.open(path).convert("RGB") if path else screenshot(monitor, self.engine.pid)
            return self.engine.analyze(image, config, tolerance)
        self._submit("capture", operation)

    def open_image(self):
        path = filedialog.askopenfilename(title="选择砧界面截图", filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp")])
        if path:
            self.capture(path)

    def resources(self, force=True):
        config = self.config()
        self._submit("resources", lambda: self.engine.refresh(config, force=force))

    def _live_changed(self):
        if not self.live.get():
            self.generation += 1
            self._clear("连续识别已停止")
        self.last_auto = 0

    def _poll(self):
        if self.closed:
            return
        while not self.forge_messages.empty():
            message = self.forge_messages.get_nowait()
            if self.future is not None and self.future_kind == "forge" and self.future_generation == self.generation:
                self.status.set(message)
                self.overlay_text.set(message)
        while not self.hotkeys.empty():
            event = self.hotkeys.get_nowait()
            if event == "capture":
                self.capture()
            else:
                self.status.set(event)
        if self.future and self.future.done():
            future, kind, generation = self.future, self.future_kind, self.future_generation
            self.future = None
            try:
                result = future.result()
                if generation == self.generation:
                    if kind == "manual":
                        self.last_source = "manual"
                        self._render(result, "手工输入 · 最少剩余步数")
                    elif kind == "capture":
                        obs = result.observation
                        self.updating = True
                        try:
                            self.current.set(str(obs.current))
                            self.target.set(str(obs.target))
                            self.history.set(",".join(a.category for a in obs.history))
                            for i, (a, b) in enumerate(self.rule_vars):
                                a.set(CAT_LABELS[obs.rules[i].category] if i < len(obs.rules) else "无")
                                if i < len(obs.rules):
                                    b.set(ORDER_LABELS[obs.rules[i].order])
                        finally:
                            self.updating = False
                        self.last_source = "capture"
                        self.source_revision = self.engine.revision
                        self._render(result.solution, f"匹配度 {obs.confidence:.1%} · GUI ×{obs.scale:g} · 位置 {obs.region[:2]}")
                        self._resource_info(result.assets)
                    elif kind == "resources":
                        if self.last_source == "capture" and self.source_revision != self.engine.revision:
                            self._clear("游戏实例或资源已变化，请重新识别")
                        self._resource_info(result[0])
                        self.status.set("资源已就绪 · F8 识别屏幕，或启用连续识别")
                    elif kind == "calibrate":
                        self._calibration_dialog(result)
                    elif kind == "forge":
                        self.allow_forging.set(False)
                        self._clear(result.message)
                        completed = getattr(result, "completed", None)
                        self.next_step.set(f"已加工 {completed} 件" if completed is not None else
                                           ("执行完成" if result.verified else "已停止，请核对成品"))
                        self.status.set(f"{result.message} · 本次点击 {result.clicks} 次")
            except Exception as exc:  # noqa: BLE001 - worker boundary; clear stale plan and show failure
                # A failed or obsolete frame must never leave an actionable old plan.
                if generation == self.generation:
                    if kind == "forge":
                        self.allow_forging.set(False)
                    self._error(exc)
            self.last_refresh = time.monotonic()
        if self.future is None:
            now = time.monotonic()
            if self.pending_forging:
                self.pending_forging = False
                self.start_forging()
            elif self.live.get() and now - self.last_auto > 1.0:
                self.last_auto = now
                self.capture()
            elif not self.live.get() and now - self.last_refresh > 5:
                self.last_refresh = now
                self.resources(force=False)
        self.root.after(100, self._poll)

    def _resource_info(self, atlas):
        candidates = [str(c.path) for c in self.engine.candidates]
        self.instance_combo.configure(values=candidates)
        text = f"实例：{self.engine.instance or '使用指定资源'}\n贴图来源：{atlas.source}"
        if atlas.warnings:
            text += "\n" + "；".join(atlas.warnings)
        self.resource_status.set(text)
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(asdict(self.config()), ensure_ascii=False, indent=2), encoding="utf-8")

    def _render(self, solution, detail):
        self.last_solution = solution
        self.table.delete(*self.table.get_children())
        if solution.actions:
            a = solution.actions[0]
            self.next_step.set(f"{a.label}  {a.delta:+d}")
        else:
            self.next_step.set("目标与规则均已满足")
        self.summary.set(f"最少 {solution.steps} 步 · {solution.current} → {solution.positions[-1]}（目标 {solution.target}）")
        for i, action in enumerate(solution.actions):
            self.table.insert("", "end", values=(i + 1, action.label, f"{action.delta:+d}", solution.positions[i + 1]))
        text = " → ".join(a.label for a in solution.actions) or "当前条件已满足"
        self.overlay_text.set(f"{self.next_step.get()}\n{solution.steps} 步  /  {solution.current} → {solution.positions[-1]}\n{text}")
        self.status.set(detail)
        self.bar.delete("all")
        width = max(320, self.bar.winfo_width() - 24)
        self.bar.create_line(12, 28, width, 28, fill="#415869", width=7)
        for value, color, label in ((solution.target, "#ff9f85", "目标"), (solution.current, ACCENT, "当前")):
            x = 12 + value / 150 * (width - 12)
            self.bar.create_polygon(x, 23, x - 5, 13, x + 5, 13, fill=color)
            self.bar.create_text(x, 43, text=f"{label} {value}", fill=color, font=("Microsoft YaHei UI", 9))

    def _error(self, exc):
        if getattr(self, "future_kind", "") != "resources" or getattr(self, "last_source", "") == "capture":
            self._clear(str(exc))
        self.status.set(str(exc))
        self.instance_combo.configure(values=[str(c.path) for c in self.engine.candidates])
        if getattr(self, "future_kind", "") == "resources":
            self.resource_status.set(str(exc))

    def _overlay_changed(self):
        if self.show_overlay.get():
            self.overlay = tk.Toplevel(self.root)
            self.overlay.title("TFC · 下一步")
            self.overlay.geometry("390x190+40+40")
            self.overlay.configure(bg=BG)
            self.overlay.attributes("-topmost", True)
            tk.Label(self.overlay, textvariable=self.overlay_text, bg=BG, fg=ACCENT,
                     font=("Microsoft YaHei UI", 13), wraplength=350, justify="left", padx=18, pady=18).pack(fill="both", expand=True)
            self.overlay.protocol("WM_DELETE_WINDOW", lambda: (self.show_overlay.set(False), self._overlay_changed()))
        elif self.overlay:
            self.overlay.destroy()
            self.overlay = None

    def browse(self, kind):
        if kind == "directory":
            path = filedialog.askdirectory(title="选择含 options.txt 和 mods 的实例目录")
            if path:
                self.instance.set(path)
                self.auto_instance.set(False)
        else:
            path = filedialog.askopenfilename(title="选择资源或 profile", filetypes=[("支持的文件", "*.zip *.jar *.json"), ("全部", "*.*")])
            if path:
                {"jar": self.jar, "pack": self.packs, "profile": self.profile}[kind].set(path)

    def calibrate(self):
        try:
            monitor = int(self.monitor.get())
        except ValueError as exc:
            self._error(exc)
            return
        self.live.set(False)
        self._submit("calibrate", lambda: screenshot(monitor, self.engine.pid))

    def _calibration_dialog(self, image):
        dialog = tk.Toplevel(self.root)
        dialog.title("拖动框选完整砧 GUI 的外边框（不含背景遮罩）")
        factor = min(1, 1100 / image.width, 700 / image.height)
        preview = image.resize((round(image.width * factor), round(image.height * factor)))
        photo = ImageTk.PhotoImage(preview)
        canvas = tk.Canvas(dialog, width=preview.width, height=preview.height, highlightthickness=0)
        canvas.pack()
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas.photo = photo
        selection = {"start": None, "box": None}
        def start(event):
            selection["start"] = (event.x, event.y)
            if selection["box"]:
                canvas.delete(selection["box"])
            selection["box"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline=ACCENT, width=2)
        def drag(event):
            if selection["start"]:
                canvas.coords(selection["box"], *selection["start"], event.x, event.y)
        def save():
            if selection["start"] is None:
                return
            x1, y1, x2, y2 = canvas.coords(selection["box"])
            region = (round(min(x1, x2) / factor), round(min(y1, y2) / factor),
                      round(abs(x2 - x1) / factor), round(abs(y2 - y1) / factor))
            directory = profiles_directory()
            directory.mkdir(parents=True, exist_ok=True)
            path = filedialog.asksaveasfilename(parent=dialog, title="保存校准", initialdir=directory,
                                              initialfile="local.json", defaultextension=".json")
            if path:
                try:
                    replace(Profile.load(Path(self.profile.get()) if self.profile.get() else None), region=region).save(Path(path))
                    self.profile.set(path)
                    dialog.destroy()
                except (ValueError, OSError) as exc:
                    messagebox.showerror("校准失败", str(exc), parent=dialog)
        canvas.bind("<ButtonPress-1>", start)
        canvas.bind("<B1-Motion>", drag)
        ttk.Button(dialog, text="保存选区", command=save).pack(pady=12)

    def _hotkey_worker(self):
        if os.name != "nt":
            return
        from ctypes import wintypes
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        f8_registered = bool(user.RegisterHotKey(None, 1, 0x4000, 0x77))
        self.f9_registered = bool(user.RegisterHotKey(None, 2, 0x4000, 0x78))
        if not f8_registered:
            self.hotkeys.put("F8 已被其他程序占用；请使用窗口内的识别按钮")
        if not self.f9_registered:
            self.hotkeys.put("F9 被占用，自动打铁不可启动；释放热键并重启助手后可用")
        try:
            msg = wintypes.MSG()
            while not self.hotkey_stop.wait(.08):
                while user.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == 0x0312:
                        if msg.wParam == 2:
                            self.forge_stop.set()
                        elif msg.wParam == 1:
                            self.hotkeys.put("capture")
        finally:
            if f8_registered:
                user.UnregisterHotKey(None, 1)
            if self.f9_registered:
                user.UnregisterHotKey(None, 2)

    def close(self):
        self.closed = True
        self.hotkey_stop.set()
        self.forge_stop.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def launch(config=None):
    enable_dpi_awareness()
    root = tk.Tk()
    App(root, config or Config())
    root.mainloop()
