"""独立报错程序 —— 即使训练器和导入器都崩溃，也能弹窗显示错误信息。

优先使用 PyQt5 对话框（可滚动、DPI 自适应、深浅色模式、4:3 比例）。
若 PyQt5 不可用（OOM / 段错误 / 缺库），回退到 Win32 原生 MessageBox。

用法: python error_reporter.pyw <错误文件路径> <标题> [来源] [--auto|--manual]
- 错误文件为 UTF-8 文本，内容为完整错误信息
- 来源："训练器" 或 "导入器"，用于区分崩溃来源
- --auto: 自动化测试，不弹窗，直接存盘退出
- --manual: 手动测试，弹窗让用户操作

特性：
1. 扫描临时目录下所有 banner_tool_error_*.txt，合并显示
2. 每份错误标明来源（训练器/导入器）
3. 长文本支持滚轮滚动（PyQt5）/ 截断提示（原生）
4. 完整日志自动保存到 log 目录
5. 用全局 Mutex 保证同时崩溃时只弹一个窗
6. OOM 安全：先存盘再弹窗，即便弹窗失败日志也已落盘
7. 关闭键（X）= 退出，不导出报告
"""
import sys
import os
# 软件渲染：强制 Qt 走 CPU 软件渲染，兼容自动化 agent（截图/OCR/坐标点击）
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
# pythonw.exe 启动时 stdout/stderr 为 None，必须最早修复
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
# 防污染系统 Python：优先从安装目录的 Lib/site-packages 加载包
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
# dml_env Python 3.10 检测：用 dml_env 的 site-packages 避免 cp313 包冲突
_dml_sp = os.path.join(_PROJECT_ROOT, "dml_env", "Lib", "site-packages")
if sys.version_info[:2] == (3, 10) and os.path.isdir(os.path.join(_dml_sp, "PyQt5")):
    _VENDOR_PKGS = _dml_sp  # python310._pth 已将 dml_env/Lib/site-packages 加入 sys.path
else:
    _VENDOR_PKGS = os.path.join(_PROJECT_ROOT, "Lib", "site-packages")
    if os.path.isdir(_VENDOR_PKGS):
        sys.path.insert(0, _VENDOR_PKGS)
# Qt 平台插件引导：确保 pythonw.exe 启动时能找到 qwindows.dll 和 Qt5Core.dll 等
_qt5_dir = os.path.join(_VENDOR_PKGS, "PyQt5", "Qt5")
if os.path.isdir(_qt5_dir):
    _qt_bin = os.path.join(_qt5_dir, "bin")
    _qt_plugins = os.path.join(_qt5_dir, "plugins")
    if os.path.isdir(_qt_bin) and _qt_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _qt_bin + os.pathsep + os.environ.get("PATH", "")
    if os.path.isdir(_qt_plugins):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(_qt_plugins, "platforms")
        os.environ.setdefault("QT_PLUGIN_PATH", _qt_plugins)
import time
import glob
import ctypes
import tempfile

# 测试模式标志：当错误文件名为 "testerror" 或命令行含 "--auto"/"--manual" 时启用
_test_mode = False
# 自动导出标志：仅当命令行含 "--auto" 时启用（自动化测试，不弹窗，直接存盘退出）
_auto_export = False
# 手动测试模式：弹窗口，存盘到 log 目录，用户点击"是"打开文件夹
_manual_mode = False
# 安装目录的 log/ 路径（由 report_error 通过命令行传入）
# 打包后 __file__ 指向 _MEIPASS 临时目录，无法自行解析安装目录的 log/
_log_dir = None
# 继承主窗口缩放比例：由调用方通过 --scale <float> 传入（未传则按屏幕自适应）
_inherit_scale = None
# 强制主题：--theme light|dark（未传则按系统主题）
_force_theme = None


# ===== Win32 原生 API 常量 =====
_MB_YESNO = 0x00000004
_MB_ICONERROR = 0x00000010
_MB_DEFBUTTON2 = 0x00000100
_MB_TOPMOST = 0x00040000
_MB_SETFOREGROUND = 0x00010000
_IDYES = 6
_IDNO = 7
_SW_SHOWNORMAL = 1


# ===== 主题检测 =====

def _is_system_dark():
    """检测系统是否为深色模式（读注册表）。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except Exception:
        return False


def _apply_dwm_dark_mode(hwnd, is_dark):
    """设置 Windows 窗口标题栏为深色/浅色模式（DWM API）。"""
    try:
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1 if is_dark else 0)
        dwm.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


# ===== 错误文件读取 =====

def _read_all_errors(err_file):
    """读取本次错误及同目录其他未处理错误，合并为一条消息。"""
    global _test_mode
    err_dir = os.path.dirname(err_file)
    entries = []

    # 等待本次错误文件就绪
    for _ in range(30):
        if os.path.exists(err_file):
            break
        time.sleep(0.1)

    # 检测测试模式：文件名包含 "testerror" 或传入 --auto/--manual
    base_name = os.path.basename(err_file)
    if "testerror" in base_name.lower() or "--auto" in sys.argv or "--manual" in sys.argv:
        _test_mode = True

    # 测试模式：只读取指定文件，不扫描其他错误文件
    if _test_mode:
        source_name = "测试"
        if "banner_tool_error_" in base_name:
            parts = base_name.replace("banner_tool_error_", "").replace(".txt", "").rsplit("_", 1)
            if len(parts) >= 1 and parts[0]:
                source_name = parts[0]
        try:
            with open(err_file, "r", encoding="utf-8", errors="replace") as fp:
                msg = fp.read().strip()
            if msg:
                entries.append((source_name, msg, err_file))
        except Exception:
            pass
        if not entries:
            if os.path.exists(err_file):
                return f"【{source_name}】发生错误，但错误文件内容为空或读取失败。\n文件: {err_file}", [err_file]
            return None, []
        combined = f"【{source_name}】发生错误：\n{entries[0][1]}"
        return combined, [entries[0][2]]

    # 正常模式：收集所有错误文件（包括本次）
    pattern = os.path.join(err_dir, "banner_tool_error_*.txt")
    seen_files = set()
    for f in glob.glob(pattern):
        if f in seen_files:
            continue
        seen_files.add(f)
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fp:
                msg = fp.read().strip()
            if not msg:
                continue
            base = os.path.basename(f)
            source = "未知程序"
            parts = base.replace("banner_tool_error_", "").replace(".txt", "").split("_")
            if len(parts) >= 2:
                source = parts[0]
            entries.append((source, msg, f))
        except Exception:
            pass

    if not entries:
        if os.path.exists(err_file):
            return f"【未知程序】发生错误，但错误文件内容为空或读取失败。\n文件: {err_file}", [err_file]
        return None, []

    entries.sort(key=lambda e: e[0])
    lines = []
    for source, msg, _ in entries:
        lines.append(f"【{source}】发生错误：")
        lines.append(msg)
        lines.append("")
        lines.append("=" * 50)
        lines.append("")
    combined = "\n".join(lines)
    return combined, [e[2] for e in entries]


# ===== 日志保存 =====

def _save_log(combined, auto_save=False, manual_save=False, log_dir=None):
    """保存完整日志到文件（OOM 安全：无文件对话框，纯文件写）。

    auto_save=True:  保存到临时目录 testerror_export.txt（自动化测试）
    manual_save=True: 保存到 log 目录（手动测试 / 正常模式）
    log_dir: 由调用方（report_error）传入的安装目录 log/ 路径。
            打包后 error_reporter.pyw 的 __file__ 指向 _MEIPASS 临时目录，
            无法自行解析安装目录的 log/，必须依赖外部传入。
    返回: 成功返回文件路径，失败返回 None。
    """
    try:
        ts = time.strftime("%Y%m%d_%H%M%S")
        if auto_save:
            log_dir = os.environ.get("TEMP", tempfile.gettempdir())
            file_path = os.path.join(log_dir, "testerror_export.txt")
            if os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                except Exception:
                    pass
        else:
            # 优先用调用方传入的路径；回退到 __file__ 解析（开发模式）
            if not log_dir:
                log_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "log")
            os.makedirs(log_dir, exist_ok=True)
            file_path = os.path.join(log_dir, f"我的世界旗帜逆向套件错误日志_{ts}.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(combined)
        return file_path
    except Exception:
        return None


def _open_log_folder(file_path):
    """用 ShellExecuteW 打开资源管理器并选中日志文件。"""
    try:
        if file_path and os.path.exists(file_path):
            ctypes.windll.shell32.ShellExecuteW(
                0, "open", "explorer.exe",
                f'/select,"{os.path.abspath(file_path)}"', None, _SW_SHOWNORMAL)
    except Exception:
        pass


# ===== PyQt5 对话框（优先）=====

def _get_error_icon(size):
    """获取 Windows 11 原生错误图标（通过 QStyle 标准图标）。"""
    from PyQt5.QtWidgets import QStyle, QApplication
    app = QApplication.instance()
    if app is None:
        return None
    try:
        style = app.style()
        icon = style.standardIcon(QStyle.SP_MessageBoxCritical)
        return icon.pixmap(size, size)
    except Exception:
        return None


def _show_pyqt_error(title, text, log_path=None, source="程序"):
    """用 PyQt5 显示错误对话框（可滚动、分辨率自适应、深浅色、4:3）。

    成功返回 True，失败返回 False（应回退到原生 API）。
    """
    try:
        from PyQt5.QtWidgets import (
            QApplication, QDialog, QVBoxLayout, QHBoxLayout,
            QTextBrowser, QPushButton, QLabel
        )
        from PyQt5.QtCore import Qt, QPointF

        # 软件渲染（必须在 QApplication 创建前设置）：保证 agent 截图稳定可识别
        QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        # 分辨率自适应：统一单一 scale（与主窗口公式一致）等比放大。
        # 之前窗口×2.5、字体×1.54 两套比例导致高分辨率下窗口大、元素小、间距被拉散；
        # 统一后所有元素（窗口/图标/字体/间距）按同一比例放大，比例协调可控。
        if _inherit_scale:
            # 调用方传入主窗口比例：与主窗口视觉完全一致
            win_scale = _inherit_scale
        else:
            screen = app.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                sw, sh = geo.width(), geo.height()
                ui_scale = max(min(sw / 1920, sh / 1080), 0.85)
                win_scale = min(ui_scale * 1.25, 2.5)
            else:
                win_scale = 1.0
        font_scale = win_scale  # 字体与窗口同比例，避免拉伸变形

        if _force_theme:
            is_dark = _force_theme == "dark"
        else:
            is_dark = _is_system_dark()
        # 字体层级：标题 32px（主）> 正文/按钮 18px（次）。图标 80px 突出放大。
        # 像素体系不随系统 DPI 膨胀，相对 720×520 大窗比例合适（标题约窗宽 3%、正文约 1.7%）
        base_fs = max(int(18 * font_scale), 14)
        btn_fs = max(int(14 * font_scale), 12)  # 按钮字号与设置窗一致（14 基准 ×scale）

        dialog = QDialog()
        dialog.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        dialog.setWindowTitle(f"错误 — {source}")
        # DWM 深色标题栏
        _apply_dwm_dark_mode(int(dialog.winId()), is_dark)

        layout = QVBoxLayout(dialog)
        margin = int(16 * win_scale)
        layout.setContentsMargins(margin, int(8 * win_scale), margin, int(12 * win_scale))
        layout.setSpacing(int(8 * win_scale))

        # 标题行：系统错误图标 + 标题文字贴紧。
        # 系统图标请求超过 80×80 仍返回 80×80（上限）；若占位按请求尺寸放大，
        # 会出现「图标没变大、空隙被撑大」。故固定 80，占位与图标实际一致。
        header_row = QHBoxLayout()
        header_row.setSpacing(int(6 * win_scale))
        icon_size = 80  # 系统图标实际上限 80×80
        icon_lbl = QLabel()
        _pm = _get_error_icon(icon_size)
        if _pm:
            icon_lbl.setPixmap(_pm)
        icon_lbl.setFixedSize(icon_size, icon_size)
        header_row.addWidget(icon_lbl, 0, Qt.AlignVCenter)
        header = QLabel(title)
        header.setStyleSheet(
            f"font-size: {max(int(24 * font_scale), 18)}px; font-weight: bold; "
            f"color: {'#ff6b6b' if is_dark else '#c62828'}; border: none;"
        )
        header_row.addWidget(header, 1, Qt.AlignVCenter)
        layout.addLayout(header_row)

        # 可滚动文本区域
        text_browser = QTextBrowser()
        text_browser.setPlainText(text)
        text_browser.setReadOnly(True)
        text_browser.setLineWrapMode(QTextBrowser.WidgetWidth)
        bg = "#3c3c3c" if is_dark else "#ffffff"
        fg = "#eeeeee" if is_dark else "#333333"
        border_c = "#555555" if is_dark else "#cccccc"
        # 现代化滚动条样式：无背景、细窄、圆角、悬浮
        scroll_bg = "transparent"
        scroll_handle = "#666666" if is_dark else "#c1c1c1"
        scroll_hover = "#888888" if is_dark else "#a0a0a0"
        scroll_w = max(int(12 * win_scale), 10)  # 滚动条放大（用户可见，2.5倍屏约30px）
        scroll_margin = max(int(3 * win_scale), 2)
        text_browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {border_c};
                border-radius: 6px;
                font-size: {base_fs}px;
                font-family: Consolas, 'Courier New', monospace;
            }}
            QScrollBar:vertical {{
                background: {scroll_bg};
                width: {scroll_w + scroll_margin * 2}px;
                margin: {scroll_margin}px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {scroll_handle};
                border-radius: {scroll_w // 2}px;
                min-height: 24px;
                margin: 0px {scroll_margin}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {scroll_hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
                border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        layout.addWidget(text_browser, 1)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_close = QPushButton("确认")
        btn_close.setMinimumHeight(int(32 * win_scale))
        btn_close.setMinimumWidth(int(80 * win_scale))
        btn_close.clicked.connect(dialog.accept)

        btn_export = QPushButton("导出报告")
        btn_export.setObjectName("btn_export")
        btn_export.setMinimumHeight(int(32 * win_scale))
        btn_export.setMinimumWidth(int(100 * win_scale))

        def _do_export():
            """导出报告：已有日志直接打开，否则保存到 log 目录。"""
            if log_path and os.path.exists(log_path):
                saved = log_path
            else:
                saved = _save_log(text, manual_save=True, log_dir=_log_dir)
            if saved:
                btn_export.setText("已导出 ✓")
                btn_export.setEnabled(False)
                _open_log_folder(saved)

        btn_export.clicked.connect(_do_export)

        btn_layout.addWidget(btn_close)
        btn_layout.addWidget(btn_export)
        layout.addLayout(btn_layout)

        # 深色/浅色背景样式
        dlg_bg = "#2d2d30" if is_dark else "#f5f5f5"
        # 透明线框按钮：确认（主）= 蓝色；导出报告（次）= 深色发白浅灰 / 浅色偏深灰
        if is_dark:
            blue_brd, blue_fg, blue_hover_bg = "#0078D4", "#0078D4", "#1e3a5f"
            dis_brd, dis_fg = "#3a3a3a", "#777777"
            sec_brd, sec_fg, sec_hover = "#8a8a8a", "#c8c8c8", "#3f3f46"
        else:
            blue_brd, blue_fg, blue_hover_bg = "#0078D4", "#0078D4", "#e8f1fb"
            dis_brd, dis_fg = "#cccccc", "#aaaaaa"
            sec_brd, sec_fg, sec_hover = "#b5b5b5", "#5f5f5f", "#ececec"

        dialog.setStyleSheet(f"""
            QDialog {{ background-color: {dlg_bg}; }}
            QLabel {{ border: none; }}
            QPushButton {{
                font-size: {btn_fs}px;
                padding: {int(6 * win_scale)}px {int(16 * win_scale)}px;
                border: 1px solid {blue_brd};
                border-radius: 6px;
                background-color: transparent;
                color: {blue_fg};
            }}
            QPushButton:hover {{
                border-color: {blue_brd};
                color: {blue_fg};
                background-color: {blue_hover_bg};
            }}
            QPushButton:disabled {{
                color: {dis_fg};
                background-color: transparent;
                border-color: {dis_brd};
            }}
            QPushButton#btn_export {{
                border-color: {sec_brd};
                color: {sec_fg};
            }}
            QPushButton#btn_export:hover {{
                border-color: {sec_brd};
                color: {sec_fg};
                background-color: {sec_hover};
            }}
        """)

        # 固定尺寸：720×520 基础（与设置对话框典范一致），随 win_scale 缩放
        dialog.setFixedSize(int(720 * win_scale), int(520 * win_scale))

        dialog.show()
        # 窗口显示后再应用 DWM 标题栏深浅色，避免被系统主题覆盖导致错色
        try:
            _apply_dwm_dark_mode(int(dialog.winId()), is_dark)
        except Exception:
            pass
        dialog.raise_()
        dialog.activateWindow()
        # Win32 API 强制置顶 + 前台显示（突破其他进程的模态进度条遮挡）
        try:
            hwnd = int(dialog.winId())
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040
            ctypes.windll.user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            ctypes.windll.user32.BringWindowToTop(hwnd)
        except Exception:
            pass
        dialog.exec_()
        return True

    except Exception:
        return False


# ===== 原生 MessageBox（回退）=====

def _try_dark_mode():
    """尝试为后续 MessageBox 启用深色模式（Windows 10 1903+，尽力而为）。"""
    try:
        uxtheme = ctypes.windll.uxtheme
        try:
            uxtheme.SetPreferredAppMode(1)
        except Exception:
            handle = ctypes.windll.kernel32.GetModuleHandleW("uxtheme.dll")
            if handle:
                proc = ctypes.windll.kernel32.GetProcAddress(handle, 135)
                if proc:
                    func_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int)
                    func = func_type(proc)
                    func(1)
    except Exception:
        pass


def _get_native_limits():
    """根据屏幕分辨率计算 MessageBox 的行数和字符数限制（分辨率自适应）。

    基准 1920×1080 → 10行×58字符（约 4:3 窗口）。
    高分辨率 → 更多行/字符；低分辨率 → 更少。
    """
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        sw = user32.GetSystemMetrics(0)  # SM_CXSCREEN
        sh = user32.GetSystemMetrics(1)  # SM_CYSCREEN
        raw = min(sw / 1920, sh / 1080)
        scale = max(min(raw, 2.5), 0.8)
        max_lines = max(int(10 * scale), 6)
        max_chars = max(int(58 * scale), 40)
        return max_lines, max_chars
    except Exception:
        return 10, 58


def _truncate_for_native(text, max_lines=10, max_chars_per_line=58):
    """截断文本以适应 4:3 比例的 MessageBox（手动固定行数+行宽）。

    MessageBox 无滚动条，窗口随内容自动变大。
    限制到约 max_lines 行 × max_chars_per_line 字符 → 窗口大致 4:3。
    返回 (截断后文本, 是否截断)。
    """
    # 手动换行：每行最多 max_chars_per_line 字符
    wrapped = []
    for line in text.split('\n'):
        if len(line) <= max_chars_per_line:
            wrapped.append(line)
        else:
            while len(line) > 0:
                wrapped.append(line[:max_chars_per_line])
                line = line[max_chars_per_line:]
    # 限制总行数
    if len(wrapped) > max_lines:
        return '\n'.join(wrapped[:max_lines]), True
    return '\n'.join(wrapped), False


# --- MessageBox 回退 ---

def _show_message_box_fallback(title, text, log_path=None):
    """用 MessageBoxW 显示错误（最简回退，按钮为"是"/"否"）。"""
    max_lines, max_chars = _get_native_limits()
    display, truncated = _truncate_for_native(text, max_lines, max_chars)
    if truncated:
        display += "\n\n……（内容过长已截断）"
        if log_path:
            display += f"\n详细信息见：\n{log_path}"
    elif log_path:
        display += f"\n\n完整日志已保存到：\n{log_path}"
    display += "\n\n点击「是」导出报告，点击「否」关闭。"

    flags = _MB_YESNO | _MB_ICONERROR | _MB_DEFBUTTON2 | _MB_TOPMOST | _MB_SETFOREGROUND
    try:
        user32 = ctypes.windll.user32
        MessageBoxW = user32.MessageBoxW
        # 声明参数类型，避免 64 位指针被截断
        MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        MessageBoxW.restype = ctypes.c_int
        result = MessageBoxW(0, display, title, flags)
        # 关闭键（X，IDCANCEL=0）与「否」（IDNO）一致：均不导出日志；仅「是」= 导出报告
        return result == _IDYES
    except Exception:
        return False


def _show_native_error(title, text, log_path=None):
    """显示错误：PyQt 不可用时回退 Windows 原生 MessageBoxW（仅两层）。

    返回: True=用户要导出报告，False=关闭（含 X 关闭 = 否 = 不导出）。
    """
    _try_dark_mode()
    return _show_message_box_fallback(title, text, log_path)


def _is_process_alive(pid):
    """检查指定 PID 的进程是否存活。"""
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        kernel32.CloseHandle(h)
        return True
    except Exception:
        return False


def _monitor_mode(parent_pid, log_dir=None):
    """后台监控模式：轮询错误文件，发现时弹窗，父进程退出后自动关闭。

    - 每 2 秒轮询 %TEMP% 下的 banner_tool_error_*.txt
    - 发现新错误文件时读取、弹窗、删除
    - 每 5 秒检查父进程是否存活，不存活则退出
    """
    global _log_dir
    _log_dir = log_dir

    _err_dir = os.environ.get("TEMP", tempfile.gettempdir())
    _pattern = os.path.join(_err_dir, "banner_tool_error_*.txt")
    _seen = set()
    # 初始化：记录已存在的错误文件（不弹窗，只避免重复）
    for f in glob.glob(_pattern):
        _seen.add(f)

    # QApplication 只创建一次，复用
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt, QTimer, QEventLoop
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 打开父进程句柄（SYNCHRONIZE）：句柄在打开时绑定具体进程，
    # 用 WaitForSingleObject 检测其退出，避免 PID 复用导致误判父进程"仍存活"而永不退出
    kernel32 = ctypes.windll.kernel32
    SYNCHRONIZE = 0x00100000
    parent_handle = kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)

    while True:
        # 检查父进程是否已退出：句柄无效（启动时父进程已不在）或退出信号已触发 → 退出
        if not parent_handle or kernel32.WaitForSingleObject(parent_handle, 0) == 0:
            if parent_handle:
                kernel32.CloseHandle(parent_handle)
            break

        # 收集所有新错误文件（批量处理，避免逐个弹窗）
        new_files = []
        for f in glob.glob(_pattern):
            if f not in _seen:
                new_files.append(f)

        if new_files:
            # 等待 500ms 让其他 error_reporter 进程（直接启动模式）优先处理
            loop0 = QEventLoop()
            QTimer.singleShot(500, loop0.quit)
            loop0.exec_()

            # 检查是否已有 error_reporter 在处理（避免重复弹窗）
            kernel32 = ctypes.windll.kernel32
            mutex_name = "Global\\BannerToolErrorReporter"
            mutex = kernel32.CreateMutexW(None, False, mutex_name)
            already_exists = kernel32.GetLastError() == 183

            if not already_exists:
                # 标记为已处理（只有获得 mutex 的进程才标记）
                for f in new_files:
                    _seen.add(f)
                try:
                    # 批量读取所有新文件，合并为一条消息
                    entries = []
                    for f in new_files:
                        if not os.path.exists(f):
                            continue
                        try:
                            with open(f, "r", encoding="utf-8", errors="replace") as fp:
                                msg = fp.read().strip()
                            if not msg:
                                continue
                            base = os.path.basename(f)
                            source = "程序"
                            parts = base.replace("banner_tool_error_", "").replace(".txt", "").rsplit("_", 1)
                            if parts and parts[0]:
                                source = parts[0]
                            entries.append((source, msg))
                        except Exception:
                            pass

                    if entries:
                        # 合并为一条消息
                        if len(entries) == 1:
                            combined = entries[0][1]
                            title = f"错误 — {entries[0][0]}"
                        else:
                            combined = "\n\n" + "─" * 40 + "\n\n".join(
                                f"【{src}】\n{msg}" for src, msg in entries
                            )
                            title = f"错误（{len(entries)}个程序崩溃）"
                        log_path = _save_log(combined, manual_save=True, log_dir=_log_dir)
                        _show_pyqt_error(title, combined, log_path, entries[0][0])
                except Exception:
                    pass

                # 删除所有已处理的错误文件
                for f in new_files:
                    try:
                        os.remove(f)
                    except Exception:
                        pass
            # else: mutex 已存在 → 不标记 _seen，下次重试（其他进程处理后会删除文件）

            kernel32.CloseHandle(mutex)

        # 用 QEventLoop 实现非阻塞等待（保持 Qt 事件循环运转）
        loop = QEventLoop()
        QTimer.singleShot(2000, loop.quit)
        loop.exec_()


# ===== 主流程 =====

def _show_error(title, text, log_path=None, source="程序"):
    """显示错误：优先 PyQt5，失败回退原生 MessageBox。

    返回: True=用户要打开日志文件夹，False=关闭。
    """
    # 优先尝试 PyQt5（可滚动/DPI/深浅色/4:3）
    if _show_pyqt_error(title, text, log_path, source):
        return False  # PyQt5 对话框已自行处理导出，不需要再打开文件夹
    # PyQt5 不可用 → 回退原生 MessageBox
    return _show_native_error(title, text, log_path)


def main():
    global _test_mode, _auto_export, _manual_mode, _log_dir, _inherit_scale, _force_theme

    # 继承主窗口缩放：--scale <float>（与主窗口视觉比例保持一致）
    if "--scale" in sys.argv:
        _idx = sys.argv.index("--scale")
        if _idx + 1 < len(sys.argv):
            try:
                _inherit_scale = max(float(sys.argv[_idx + 1]), 0.85)
            except ValueError:
                _inherit_scale = None

    # 强制主题：--theme light|dark（供审查画廊/测试对比用）
    if "--theme" in sys.argv:
        _idx = sys.argv.index("--theme")
        if _idx + 1 < len(sys.argv):
            _force_theme = sys.argv[_idx + 1].lower()

    # 后台监控模式：--monitor --parent-pid <pid> [log_dir]
    if "--monitor" in sys.argv:
        parent_pid = 0
        log_dir = None
        for i, arg in enumerate(sys.argv):
            if arg == "--parent-pid" and i + 1 < len(sys.argv):
                try:
                    parent_pid = int(sys.argv[i + 1])
                except ValueError:
                    pass
            elif not arg.startswith("--") and i > 0 and os.path.isdir(arg):
                log_dir = arg
        if parent_pid > 0:
            _monitor_mode(parent_pid, log_dir)
        return

    if len(sys.argv) < 2:
        return
    err_file = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else "错误"
    source = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else "程序"

    # 解析调用方传入的 log 目录（report_error 通过 resolve_app_path("log") 解析）
    # 打包后 error_reporter 的 __file__ 指向 _MEIPASS 临时目录，无法自行找到安装目录的 log/
    for arg in sys.argv[4:]:
        if not arg.startswith("--") and os.path.isdir(arg):
            _log_dir = arg
            break

    # 检测命令行标志
    _auto_export = "--auto" in sys.argv
    _manual_mode = "--manual" in sys.argv
    if "testerror" in os.path.basename(err_file).lower() or _auto_export or _manual_mode:
        _test_mode = True

    # 测试模式：不走全局 Mutex，直接处理
    if _test_mode:
        combined, all_files = _read_all_errors(err_file)
        if not combined:
            combined = f"【测试】发生错误，但错误文件内容为空。\n文件: {err_file}"
        # --auto: 存盘到临时目录后直接退出（自动化测试，不弹窗）
        if _auto_export:
            _save_log(combined, auto_save=True)
            for f in all_files:
                try:
                    os.remove(f)
                except Exception:
                    pass
            return
        # --manual 或文件名 testerror：弹窗，存盘到 log 目录
        log_path = _save_log(combined, manual_save=_manual_mode, log_dir=_log_dir)
        want_open = _show_error(title, combined, log_path, source)
        if want_open:
            _open_log_folder(log_path)
        for f in all_files:
            try:
                os.remove(f)
            except Exception:
                pass
        return

    # 正常模式：全局 Mutex 保证同时崩溃时只弹一个窗
    mutex_name = "Global\\BannerToolErrorReporter"
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    already_exists = kernel32.GetLastError() == ERROR_ALREADY_EXISTS

    if already_exists:
        time.sleep(0.3)
        return

    time.sleep(0.5)

    combined, all_files = _read_all_errors(err_file)
    if not combined:
        # 错误文件已被其他进程（监控模式 / 早期报错程序）处理，静默退出避免重复弹窗
        kernel32.CloseHandle(mutex)
        return

    if len(all_files) > 1:
        display_title = f"{title}（{len(all_files)}个程序崩溃）"
    else:
        display_title = title

    # OOM 安全：先存盘（日志一定落盘），再弹窗
    log_path = _save_log(combined, manual_save=True, log_dir=_log_dir)
    want_open = _show_error(display_title, combined, log_path, source)
    if want_open:
        _open_log_folder(log_path)

    for f in all_files:
        try:
            os.remove(f)
        except Exception:
            pass

    kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
