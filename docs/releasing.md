# 构建和发布

## Windows x64 发布包

在 Windows x64 安装 Python 3.12（含 Tk），双击 `build-release.cmd`，或运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt -r requirements-release-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e ".[dev,release]"
.\.venv\Scripts\python.exe scripts\build_release.py
```

脚本核对版本、运行测试和静态检查，构建 wheel、源码包以及 PyInstaller 单文件桌面 EXE。随后将 EXE 复制到含中文和空格的临时目录，移除 PATH 中的 Python，在项目目录外验证 Tcl 解释器、Tk/ImageTk 模块、Pillow、NumPy、OpenCV、进程/截图模块与求解器。该验证不创建桌面窗口、不截图、不注册热键、不向游戏发送输入。

输出目录 `dist/<版本>/` 包含 Windows ZIP、wheel、源码包和 `SHA256SUMS.txt`。ZIP 包含 EXE、MIT 许可证、第三方依赖许可证、说明及示例 profile；不包含本机设置、截图、游戏 JAR 或材质包。未使用代码签名证书。已有同版本输出时脚本拒绝覆盖，请先移走旧输出。

GitHub 的 **Build Windows release** 工作流也可手动触发，产物保存在工作流附件中。**Checks** 自动检查 main 分支和拉取请求，使用 Windows / Python 3.11、3.12。

## 发布到 GitHub

更新 `pyproject.toml` 和 `src/tfc_forge_helper/__init__.py` 中的版本，补充 `CHANGELOG.md`、发布说明和验证记录。运行构建后检查产物，提交并推送代码，再使用本机 Git 和 GitHub CLI 创建标签和 Release：

```powershell
git tag -a v0.2.6 -m "Release v0.2.6"
git push origin main
git push origin v0.2.6
gh release create v0.2.6 dist/0.2.6/* --verify-tag --title "TFC 锻造助手 v0.2.6" --notes-file docs/release-notes-v0.2.6.md
```

发布前确认实机验收的范围。当前自动操作仍以模拟接口测试为依据，发布说明必须保留这一限制。
