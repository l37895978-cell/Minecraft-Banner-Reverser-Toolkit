#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旗帜逆向套件 — 补丁工具

双模式：
  1. 应用补丁（用户模式，默认可见）：选择 .zip 补丁包 → 自动备份 → 替换文件
  2. 制作补丁（开发者模式，需密码解锁）：选择文件 → 填写信息 → 生成 .zip 补丁包

开发者解锁：Ctrl+Shift+D → 输入密码
"""
import sys, os, json, zipfile, shutil, datetime
# 软件渲染：强制 Qt 走 CPU 软件渲染，兼容自动化 agent（截图/OCR/坐标点击）
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
# pythonw.exe 启动时 stdout/stderr 为 None，必须最早修复
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
# 防污染系统 Python：优先从本工具所在目录的 Lib/site-packages 加载包
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Python 寻找兜底：从补丁解压目录等子目录启动时，向上搜索应用根目录（含 utils/）
def _bootstrap_app_root(_start):
    _d = os.path.dirname(os.path.abspath(_start))
    while True:
        if os.path.isfile(os.path.join(_d, "utils", "settings_manager.py")):
            return _d
        _up = os.path.dirname(_d)
        if _up == _d:
            return _APP_DIR
        _d = _up

_APP_DIR = _bootstrap_app_root(__file__)
sys.path.insert(0, _APP_DIR)
_VENDOR_PKGS = os.path.join(_APP_DIR, "Lib", "site-packages")
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

# 早期异常捕获：在 PyQt5 等第三方库导入前生效，捕获导入/启动阶段的致命错误
def _early_crash_handler(exc_type, exc_value, exc_tb):
    import traceback as _tb_mod
    import subprocess as _sp_mod
    tb_str = "".join(_tb_mod.format_exception(exc_type, exc_value, exc_tb))
    _src = os.path.splitext(os.path.basename(__file__))[0]
    _err = os.path.join(os.environ.get('TEMP', _APP_DIR), f"banner_tool_error_{_src}_{os.getpid()}.txt")
    try:
        with open(_err, "w", encoding="utf-8") as f:
            f.write(f"程序发生致命错误:\n\n{tb_str}")
    except Exception:
        pass
    _reporter = os.path.join(_APP_DIR, "scripts", "error_reporter.pyw")
    try:
        _sp_mod.Popen([sys.executable, _reporter, _err, "程序异常", _src],
                       creationflags=_sp_mod.CREATE_NO_WINDOW | _sp_mod.DETACHED_PROCESS)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)
sys.excepthook = _early_crash_handler

try:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
        QLabel, QFileDialog, QTabWidget, QTextEdit, QProgressBar,
        QGroupBox, QLineEdit, QMessageBox, QTreeWidget, QTreeWidgetItem,
        QHeaderView, QInputDialog, QShortcut, QSizePolicy, QScrollArea,
        QSplitter
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal
    from PyQt5.QtGui import QKeySequence
except ImportError:
    # PyQt5 无法加载：不自动 pip 安装（会紊乱环境），引导用户走安装程序的修复功能
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        0,
        "无法加载 PyQt5。\n\n请运行「我的世界旗帜逆向套件」安装程序的修复功能来安装 PyQt5。",
        "PyQt5 缺失", 0x10)
    sys.exit(1)

# 主题工具（与主程序 start.pyw / bdor.pyw 统一：深浅色、统一弹窗、标题栏）
from utils.settings_manager import (apply_theme, apply_dwm_dark_mode,
                                    resolve_theme, SettingsManager, MessageBox)


# ===== 常量 =====
APP_NAME = "旗帜逆向套件补丁工具"
INSTALL_DIR_NAMES = ["我的世界旗帜逆向套件", "旗帜编织逆向器"]
DEV_PASSWORD = "banner2026"  # 开发者解锁密码
PROGRAM_FILES = [
    "start.pyw", "trainer.pyw", "importer.pyw",
    "bdor.pyw", "help.pyw", "test.pyw",
    "utils", "scripts", "models", "images", "config", "LICENSE",
]


def _detect_scale():
    """检测屏幕分辨率，返回缩放系数（与 start.pyw 一致）"""
    screen = QApplication.primaryScreen()
    if not screen:
        return 1.0
    geo = screen.availableGeometry()
    sw, sh = geo.width(), geo.height()
    ui_scale = max(min(sw / 1920, sh / 1080), 1.0)
    return min(ui_scale * 1.25, 2.5)


def _is_dev_marker_dir(directory):
    """判断 directory 是否为开发环境（含 .dev_marker/identity.json 且 role=developer）。

    与安装器 real_installer.pyw 的 _is_dev_marker_dir 保持一致，
    用于排除开发目录，避免补丁误应用到开发环境。
    """
    if not directory:
        return False
    marker_path = os.path.join(directory, ".dev_marker", "identity.json")
    if not os.path.isfile(marker_path):
        return False
    try:
        import json as _json
        with open(marker_path, encoding="utf-8") as f:
            data = _json.load(f) or {}
        return data.get("role") == "developer"
    except Exception:
        return False


def find_install_dir():
    """自动查找软件安装目录（与安装器一致，搜索新旧名称和多个位置）

    排除开发环境：如果目录中存在 .dev_marker/identity.json（开发者标记），
    说明是开发目录而非安装目录，跳过。

    返回安装目录路径或空字符串（用户可手动浏览选择）。
    """
    # ===== 优先级 1：读注册表 InstallLocation —— 100% 准，无论用户装到哪都能找到 =====
    try:
        import winreg as _wr
        for _hive in (_wr.HKEY_CURRENT_USER, _wr.HKEY_LOCAL_MACHINE):
            for _subkey_name in (
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall\BannerWeaveReverser_is1",
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall\BannerWeaveReverser",
            ):
                try:
                    _k = _wr.OpenKey(_hive, _subkey_name)
                    try:
                        _loc, _ = _wr.QueryValueEx(_k, "InstallLocation")
                        if _loc and os.path.exists(_loc) and os.path.exists(os.path.join(_loc, "start.pyw")):
                            if not _is_dev_marker_dir(_loc):
                                _wr.CloseKey(_k)
                                return _loc
                    except OSError:
                        pass
                    _wr.CloseKey(_k)
                except OSError:
                    pass
    except Exception:
        pass

    # ===== 优先级 2：4 个常见位置（安装器默认候选位置） =====
    search_bases = [
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.path.expanduser("~"), "Documents"),
        r"C:\Program Files",
    ]
    for base in search_bases:
        for name in INSTALL_DIR_NAMES:
            d = os.path.join(base, name)
            if os.path.exists(d) and os.path.exists(os.path.join(d, "start.pyw")):
                # 排除开发环境（单一特征 .dev_marker/identity.json）
                if _is_dev_marker_dir(d):
                    continue
                return d
    # 当前目录（同样排除开发环境）
    cur = os.getcwd()
    if os.path.exists(os.path.join(cur, "start.pyw")):
        if not _is_dev_marker_dir(cur):
            return cur
    # 脚本所在目录（同样排除开发环境）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.exists(os.path.join(script_dir, "start.pyw")):
        if not _is_dev_marker_dir(script_dir):
            return script_dir
    return ""


def _is_software_running():
    """检测软件是否正在运行（避免文件被占用导致替换失败）"""
    try:
        import ctypes
        # 检查多个可能的窗口标题
        for title in ["我的世界旗帜逆向套件", "旗帜编织逆向器", "旗帜逆向套件"]:
            if ctypes.windll.user32.FindWindowW(None, title):
                return True
    except Exception:
        pass
    return False


def _norm_path(p):
    """规范化路径分隔符为 / （ZIP 和 manifest 内统一用 /）"""
    return p.replace("\\", "/")


def _scan_all_drives_for_app(app_names):
    """全盘扫描所有盘符根目录下名为 app_names 之一的目录（含 start.pyw）。

    用于补丁包携带 target_app_name 时，在用户自定义安装位置（如 D 盘）也能找到。
    只扫描盘符根目录下一级，避免深入递归耗时。
    返回找到的目录路径或空字符串。
    """
    import string
    # 获取所有可用盘符
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append(drive)
    # 扫描每个盘符根目录下一级
    for drive in drives:
        try:
            for entry in os.listdir(drive):
                full = os.path.join(drive, entry)
                if not os.path.isdir(full):
                    continue
                if entry in app_names and os.path.isfile(os.path.join(full, "start.pyw")):
                    if not _is_dev_marker_dir(full):
                        return full
        except (OSError, PermissionError):
            continue
    return ""


def _qss(scale, is_dark):
    """生成适配缩放与深浅色主题的 QSS（按钮/组框/输入框/滚动条等与主程序统一）"""
    fs = max(int(12 * scale), 10)
    btn_fs = max(int(11 * scale), 10)
    title_fs = max(int(18 * scale), 15)
    pad = max(int(6 * scale), 4)
    if is_dark:
        bg = "#2d2d30"
        bg_alt = "#3c3c3c"
        fg = "#eeeeee"
        fg_sub = "#888888"
        group_border = "#555555"
        input_bg = "#3c3c3c"
        tab_bg = "#3c3c3c"
        tab_bg_sel = "#2d2d30"
        header_bg = "#3c3c3c"
        scroll_handle = "#555555"
        scroll_hover = "#666666"
        scroll_pressed = "#777777"
        bbrd, bfg, bhov = "#0078D4", "#0078D4", "#1e3a5f"
        dbrd, dfg = "#3a3a3a", "#777777"
    else:
        bg = "#f5f5f5"
        bg_alt = "#ffffff"
        fg = "#000000"
        fg_sub = "#666666"
        group_border = "#cccccc"
        input_bg = "#ffffff"
        tab_bg = "#e0e0e0"
        tab_bg_sel = "#ffffff"
        header_bg = "#e8e8e8"
        scroll_handle = "#c0c0c0"
        scroll_hover = "#a0a0a0"
        scroll_pressed = "#909090"
        bbrd, bfg, bhov = "#0078D4", "#0078D4", "#e8f1fb"
        dbrd, dfg = "#cccccc", "#aaaaaa"
    btn_h = max(int(26 * scale), 22)
    btn_pad = max(int(14 * scale), 10)
    return f"""
    QWidget {{
        font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        font-size: {fs}px;
        color: {fg};
    }}
    QWidget#central {{ background: {bg}; }}
    QLabel#title {{ font-size: {title_fs}px; font-weight: bold; color: {fg}; }}
    QLabel#hint {{ color: {fg_sub}; font-size: {max(int(11*scale),10)}px; }}
    QTabWidget::pane {{
        border: 1px solid {group_border};
        border-radius: 6px;
        top: -1px;
        background: {bg_alt};
    }}
    QTabBar::tab {{
        padding: {max(int(7*scale),5)}px {max(int(18*scale),14)}px;
        background: {tab_bg};
        border: none;
        border-radius: 6px 6px 0 0;
        margin-right: 2px;
        font-size: {btn_fs}px;
        color: {fg_sub};
    }}
    QTabBar::tab:selected {{ background: {tab_bg_sel}; color: {fg}; }}
    QTabBar::tab:hover:!selected {{ color: {fg}; }}
    QGroupBox {{
        font-weight: bold;
        border: 1px solid {group_border};
        border-radius: 6px;
        margin-top: 8px;
        padding-top: 14px;
        font-size: {btn_fs}px;
        color: {fg};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }}
    QPushButton {{
        font-size: {btn_fs}px;
        min-height: {btn_h}px;
        padding: {pad}px {btn_pad}px;
        border: 1px solid {bbrd};
        border-radius: 6px;
        background: transparent;
        color: {bfg};
    }}
    QPushButton:hover {{ background: {bhov}; }}
    QPushButton:pressed {{ background: {bhov}; }}
    QPushButton:disabled {{ background: transparent; color: {dfg}; border-color: {dbrd}; }}
    QLineEdit, QTextEdit, QTreeWidget {{
        border: 1px solid {group_border};
        border-radius: 4px;
        padding: {max(int(5*scale),4)}px;
        background: {input_bg};
        color: {fg};
        font-size: {fs}px;
    }}
    QLineEdit:focus, QTextEdit:focus, QTreeWidget:focus {{ border: 1px solid {bbrd}; }}
    QTreeWidget {{ selection-background-color: {bbrd}; selection-color: white; }}
    QHeaderView::section {{
        padding: {max(int(4*scale),3)}px;
        border: none;
        background: {header_bg};
        color: {fg};
        font-size: {btn_fs}px;
    }}
    QProgressBar {{
        border: 1px solid {group_border};
        border-radius: 4px;
        text-align: center;
        height: {max(int(22*scale),18)}px;
        font-size: {btn_fs}px;
        background: {input_bg};
        color: {fg};
    }}
    QProgressBar::chunk {{ background: {bbrd}; border-radius: 3px; }}
    QSplitter::handle {{ background: {group_border}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; border: none; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; border: none; }}
    QScrollBar::handle {{
        background: {scroll_handle};
        border-radius: 5px;
        min-height: 30px;
        min-width: 30px;
    }}
    QScrollBar::handle:hover {{ background: {scroll_hover}; }}
    QScrollBar::handle:pressed {{ background: {scroll_pressed}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ border: none; background: none; width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QToolTip {{
        background-color: {bg_alt};
        color: {fg};
        border: 1px solid {group_border};
        border-radius: 4px;
        padding: {max(int(4*scale),3)}px;
        font-size: {fs}px;
    }}
    """


# ===== use（仅识别器）安装模式筛选 =====
# 补丁应用中跳过训练器/导入器专用文件（与安装器 _SKIP_FOR_USE 及 test.pyw 的 use 模式一致）
_USE_SKIP_FILES = {
    "trainer.pyw",
    "importer.pyw",
    "scripts/dml_worker.py",       # 训练器 DirectML 子进程（识别器用的是 reverser_dml_worker.py）
    "utils/mbtl_utils.py",         # 导入器 MBTL 文件读写
    "utils/mbtlx_utils.py",        # 导入器/训练器 MBTLX 标记包读写
}


def _is_use_mode(install_dir):
    """判断目标安装目录是否为仅识别器（use）形态。

    与 test.pyw 的识别逻辑一致：install_components.json 的 purpose=use
    且磁盘上无 trainer.pyw 才算 use 模式（避免旧 json 记录误导）。
    """
    purpose = ""
    comp = os.path.join(install_dir, "install_components.json")
    if os.path.isfile(comp):
        try:
            with open(comp, encoding="utf-8-sig") as f:
                data = json.load(f) or {}
            purpose = data.get("purpose", "") or ""
        except Exception:
            pass
    has_trainer = os.path.isfile(os.path.join(install_dir, "trainer.pyw"))
    return purpose == "use" and not has_trainer


# ===== 应用补丁线程 =====
class ApplyPatchThread(QThread):
    progress = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, patch_path, install_dir):
        super().__init__()
        self.patch_path = patch_path
        self.install_dir = install_dir

    def run(self):
        try:
            self.progress.emit(5, "正在读取补丁包...")
            with zipfile.ZipFile(self.patch_path, "r") as zf:
                if "manifest.json" not in zf.namelist():
                    self.finished_signal.emit(False, "补丁包缺少 manifest.json，不是有效的补丁文件")
                    return
                manifest = json.loads(zf.read("manifest.json"))
                patch_ver = manifest.get("patch_version", "未知")
                desc = manifest.get("description", "")
                files = manifest.get("files", [])
                skipped = []
                # use（仅识别器）安装模式：跳过训练器/导入器相关文件
                if _is_use_mode(self.install_dir):
                    skipped = [f for f in files if _norm_path(f) in _USE_SKIP_FILES]
                    if skipped:
                        files = [f for f in files if _norm_path(f) not in _USE_SKIP_FILES]
                        self.progress.emit(8, "检测到仅识别器（use）安装模式，"
                                             f"跳过 {len(skipped)} 个训练器/导入器相关文件：\n"
                                             + "\n".join(skipped))
                    if not files:
                        self.progress.emit(100, "补丁中的所有文件均属训练器/导入器相关，已全部跳过。")
                        self.finished_signal.emit(True, "补丁中的所有文件均属训练器/导入器相关，\n"
                                                        "当前为仅识别器安装，无需应用。")
                        return

                _skip_note = f"（已跳过 {len(skipped)} 个训练器/导入器文件）" if skipped else ""
                self.progress.emit(10, f"补丁版本: {patch_ver}\n说明: {desc}\n包含 {len(files)} 个文件{_skip_note}")

                # 备份到 patches/ 专用文件夹（统一管理，不散落在根目录）
                ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                patches_dir = os.path.join(self.install_dir, "patches")
                backup_name = ts
                backup_dir = os.path.join(patches_dir, backup_name)
                os.makedirs(backup_dir, exist_ok=True)
                self.progress.emit(20, f"正在备份原文件到 patches/{backup_name}/...")

                for i, rel_path in enumerate(files):
                    rel_path = _norm_path(rel_path)
                    src = os.path.join(self.install_dir, rel_path)
                    dst = os.path.join(backup_dir, rel_path)
                    if os.path.exists(src):
                        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                        shutil.copy2(src, dst)
                    pct = 20 + int((i / max(len(files), 1)) * 30)
                    self.progress.emit(pct, f"已备份 {i+1}/{len(files)}: {rel_path}")

                self.progress.emit(55, "正在应用补丁文件...")
                for i, rel_path in enumerate(files):
                    rel_path = _norm_path(rel_path)
                    zip_name = f"files/{rel_path}"
                    if zip_name not in zf.namelist():
                        continue
                    dst = os.path.join(self.install_dir, rel_path)
                    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                    with zf.open(zip_name) as src, open(dst, "wb") as out:
                        out.write(src.read())
                    pct = 55 + int((i / max(len(files), 1)) * 40)
                    self.progress.emit(pct, f"已替换 {i+1}/{len(files)}: {rel_path}")

                # 保存补丁元数据和原始补丁包（供补丁管理还原使用）
                meta = {
                    "patch_version": patch_ver,
                    "description": desc,
                    "applied_time": ts,
                    "files": [_norm_path(f) for f in files],
                    "skipped": [_norm_path(f) for f in skipped],
                    "patch_zip_name": os.path.basename(self.patch_path),
                }
                with open(os.path.join(backup_dir, "patch_meta.json"), "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
                # 复制原始补丁包到备份目录（方便升级后重新应用）
                try:
                    shutil.copy2(self.patch_path, os.path.join(backup_dir, "patch.zip"))
                except Exception:
                    pass

                self.progress.emit(100, f"补丁应用完成！{_skip_note}\n备份目录: patches/{backup_name}/")
                self.finished_signal.emit(True, f"补丁 v{patch_ver} 应用成功！{_skip_note}\n备份保存在: patches/{backup_name}/")
        except Exception as e:
            self.finished_signal.emit(False, f"补丁应用失败: {e}")


# ===== 主窗口 =====
class PatchTool(QWidget):
    def __init__(self, scale=1.0):
        self._scale = scale
        super().__init__()
        # 深浅色主题：与主程序一致，从 config.json 读取并解析 system
        self._theme = resolve_theme(SettingsManager().get("theme", "light"))
        self._is_dark = self._theme == "dark"
        self.patch_path = ""
        self.install_dir = find_install_dir()
        self.worker = None
        self._dev_mode = False
        # 增量补丁：导入已有补丁包后记录路径与文件清单，便于生成时从原包抽取"源目录里没有"的文件
        self._imported_patch_path = ""
        self._imported_files = []  # 原补丁包 manifest.files（规范化后的相对路径）
        self._build_ui()
        self._setup_shortcuts()

    def _build_ui(self):
        s = self._scale
        self.setObjectName("central")
        self.setWindowTitle(APP_NAME)
        # 不设置窗口图标（图标仅用于主程序快捷方式，补丁工具不需要）
        self.setMinimumSize(int(620 * s), int(520 * s))
        self.resize(int(680 * s), int(600 * s))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(20 * s), int(20 * s), int(20 * s), int(20 * s))
        layout.setSpacing(int(12 * s))

        # 标题
        title = QLabel("旗帜逆向套件 · 补丁工具")
        title.setObjectName("title")
        layout.addWidget(title)

        # 标签页（占据主要空间）
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # === Tab 1: 应用补丁（用户可见） ===
        self._build_apply_tab(s)
        self.tabs.addTab(self.tab_apply, "应用补丁")

        # === Tab 2: 制作补丁（默认隐藏） ===
        self._build_make_tab(s)
        self.tab_make_idx = None  # 未添加时为 None

        # 应用样式（深浅色自适应，与主程序统一）
        self.setStyleSheet(_qss(s, self._is_dark))
        apply_dwm_dark_mode(self, self._is_dark)

    def showEvent(self, event):
        """窗口显示时重新应用标题栏深浅色，防止系统主题覆盖导致错色。"""
        super().showEvent(event)
        try:
            apply_dwm_dark_mode(self, self._is_dark)
        except Exception:
            pass

    def _build_apply_tab(self, s):
        self.tab_apply = QWidget()
        outer = QVBoxLayout(self.tab_apply)
        outer.setContentsMargins(0, 0, 0, 0)
        sub_c = "#888888" if self._is_dark else "#666666"

        # 用 QScrollArea 包裹整个页面内容，防止窗口小时控件被挤压/滚动条被遮挡
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        t = QVBoxLayout(content)
        t.setContentsMargins(int(10 * s), int(10 * s), int(10 * s), int(10 * s))
        t.setSpacing(int(10 * s))

        # 安装目录
        gp_dir = QGroupBox("软件安装目录")
        gl = QHBoxLayout(gp_dir)
        self.lbl_dir = QLabel(self.install_dir or "未找到安装目录，请手动选择")
        self.lbl_dir.setWordWrap(True)
        self.lbl_dir.setStyleSheet(f"color: {sub_c};")
        btn_dir = QPushButton("选择目录")
        btn_dir.setObjectName("secondary")
        btn_dir.clicked.connect(self._browse_install_dir)
        gl.addWidget(self.lbl_dir, 1)
        gl.addWidget(btn_dir)
        t.addWidget(gp_dir)

        # 补丁包
        gp_patch = QGroupBox("补丁包")
        gl_p = QVBoxLayout(gp_patch)
        hl = QHBoxLayout()
        self.lbl_patch = QLabel("请选择 .zip 补丁包文件")
        self.lbl_patch.setStyleSheet(f"color: {sub_c};")
        btn_patch = QPushButton("选择补丁包")
        btn_patch.clicked.connect(self._browse_patch)
        hl.addWidget(self.lbl_patch, 1)
        hl.addWidget(btn_patch)
        gl_p.addLayout(hl)

        self.patch_info = QTextEdit()
        self.patch_info.setReadOnly(True)
        self.patch_info.setMinimumHeight(int(180 * s))
        self.patch_info.setPlaceholderText("选择补丁包后，这里会显示补丁信息...")
        gl_p.addWidget(self.patch_info)
        t.addWidget(gp_patch)

        # 进度
        gp_prog = QGroupBox("进度")
        gl_pr = QVBoxLayout(gp_prog)
        self.progress = QProgressBar()
        gl_pr.addWidget(self.progress)
        self.progress_label = QLabel("等待操作...")
        self.progress_label.setWordWrap(True)
        gl_pr.addWidget(self.progress_label)
        t.addWidget(gp_prog)

        # 按钮
        hl_btn = QHBoxLayout()
        hl_btn.addStretch()
        self.btn_apply = QPushButton("应用补丁")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply_patch)
        hl_btn.addWidget(self.btn_apply)
        t.addLayout(hl_btn)

        t.addStretch()
        scroll.setWidget(content)

    def _build_make_tab(self, s):
        self.tab_make = QWidget()
        outer = QVBoxLayout(self.tab_make)
        outer.setContentsMargins(0, 0, 0, 0)
        sub_c = "#888888" if self._is_dark else "#666666"

        # 用 QScrollArea 包裹整个页面内容，防止窗口小时控件被挤压/滚动条被遮挡
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        t = QVBoxLayout(content)
        t.setContentsMargins(int(10 * s), int(10 * s), int(10 * s), int(10 * s))
        t.setSpacing(int(10 * s))

        # 源目录
        gp_src = QGroupBox("软件源目录（开发目录）")
        gl = QHBoxLayout(gp_src)
        self.lbl_src = QLabel("")
        self.lbl_src.setWordWrap(True)
        self.lbl_src.setStyleSheet(f"color: {sub_c};")
        btn_src = QPushButton("选择目录")
        btn_src.setObjectName("secondary")
        btn_src.clicked.connect(self._browse_src)
        gl.addWidget(self.lbl_src, 1)
        gl.addWidget(btn_src)
        t.addWidget(gp_src)

        # 文件选择
        gp_files = QGroupBox("选择要打包的文件")
        gl_f = QVBoxLayout(gp_files)
        gl_f.setSpacing(int(6 * s))
        # 按钮行放在树控件上方
        hl_files_btn = QHBoxLayout()
        hl_files_btn.setSpacing(int(6 * s))
        btn_select_all = QPushButton("全选")
        btn_select_all.setObjectName("secondary")
        btn_select_all.clicked.connect(lambda: self._set_all_checks(Qt.Checked))
        hl_files_btn.addWidget(btn_select_all)
        btn_deselect_all = QPushButton("全不选")
        btn_deselect_all.setObjectName("secondary")
        btn_deselect_all.clicked.connect(lambda: self._set_all_checks(Qt.Unchecked))
        hl_files_btn.addWidget(btn_deselect_all)
        hl_files_btn.addSpacing(int(10 * s))
        btn_refresh = QPushButton("刷新文件列表")
        btn_refresh.setObjectName("secondary")
        btn_refresh.clicked.connect(self._refresh_tree)
        hl_files_btn.addWidget(btn_refresh)
        btn_add_file = QPushButton("添加单个文件")
        btn_add_file.setObjectName("secondary")
        btn_add_file.clicked.connect(self._add_single_file)
        hl_files_btn.addWidget(btn_add_file)
        # 增量更新：导入已有补丁包，预填版本/说明，预勾选文件，支持增减后重新打包
        btn_import = QPushButton("导入已有补丁")
        btn_import.setObjectName("secondary")
        btn_import.clicked.connect(self._import_existing_patch)
        hl_files_btn.addWidget(btn_import)
        hl_files_btn.addStretch()
        gl_f.addLayout(hl_files_btn)
        # 增量补丁：上方原补丁包文件（保留/移除），下方开发目录文件（新增/替换）
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        # 上方：原补丁包文件（导入补丁包后显示）
        self.gp_patch_files = QGroupBox("原补丁包文件（保留/移除）")
        self.gp_patch_files.setVisible(False)
        _lay_patch = QVBoxLayout(self.gp_patch_files)
        _lay_patch.setContentsMargins(4, int(4 * s), 4, int(4 * s))
        self.patch_tree = QTreeWidget()
        self.patch_tree.setHeaderLabels(["文件/文件夹", "选择"])
        self.patch_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.patch_tree.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.patch_tree.header().resizeSection(1, int(50 * s))
        self.patch_tree.setAnimated(False)
        _lay_patch.addWidget(self.patch_tree)
        splitter.addWidget(self.gp_patch_files)
        # 下方：开发目录文件
        self.gp_dev_files = QGroupBox("开发目录文件（新增/替换）")
        _lay_dev = QVBoxLayout(self.gp_dev_files)
        _lay_dev.setContentsMargins(4, int(4 * s), 4, int(4 * s))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["文件/文件夹", "选择"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.tree.header().resizeSection(1, int(50 * s))
        self.tree.setAnimated(False)
        _lay_dev.addWidget(self.tree)
        splitter.addWidget(self.gp_dev_files)
        splitter.setSizes([int(150 * s), int(250 * s)])
        splitter.setMinimumHeight(int(300 * s))
        gl_f.addWidget(splitter, 1)
        t.addWidget(gp_files)

        # 补丁信息
        gp_info = QGroupBox("补丁信息")
        gl_i = QVBoxLayout(gp_info)
        gl_i.addWidget(QLabel("补丁版本号:"))
        self.txt_version = QLineEdit()
        self.txt_version.setPlaceholderText("例如: 1.0.1")
        gl_i.addWidget(self.txt_version)
        gl_i.addWidget(QLabel("补丁说明:"))
        self.txt_desc = QTextEdit()
        self.txt_desc.setMinimumHeight(int(80 * s))
        self.txt_desc.setPlaceholderText("简述此补丁修复了什么问题...")
        gl_i.addWidget(self.txt_desc)
        t.addWidget(gp_info)

        self.btn_build = QPushButton("生成补丁包")
        self.btn_build.setEnabled(False)
        self.btn_build.clicked.connect(self._build_patch)
        t.addWidget(self.btn_build)

        t.addStretch()
        scroll.setWidget(content)

    def _setup_shortcuts(self):
        """Ctrl+Shift+D 开发者解锁"""
        sc = QShortcut(QKeySequence("Ctrl+Shift+D"), self)
        sc.activated.connect(self._try_dev_unlock)
        # 启用拖拽接收（拖 .zip 补丁包到窗口直接加载）
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        """拖入文件时，仅接受 .zip 补丁包"""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith(".zip"):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        """放下文件时，自动加载补丁包（等效于点击"选择补丁包"）"""
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if not path.lower().endswith(".zip"):
            return
        self.patch_path = path
        self.lbl_patch.setText(os.path.basename(path))
        self._load_patch_info(path)
        event.acceptProposedAction()

    def _try_dev_unlock(self):
        if self._dev_mode:
            return
        pwd, ok = QInputDialog.getText(
            self, "开发者验证", "请输入开发者密码:", QLineEdit.Password)
        if ok and pwd == DEV_PASSWORD:
            self._dev_mode = True
            self.tab_make_idx = self.tabs.addTab(self.tab_make, "制作补丁")
            MessageBox.information(self, "已解锁", "开发者模式已开启，切换到\"制作补丁\"标签页。")
        elif ok:
            MessageBox.warning(self, "错误", "密码错误。")

    # --- 应用补丁 ---
    def _browse_install_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择软件安装目录", self.install_dir)
        if d:
            if _is_dev_marker_dir(d):
                MessageBox.warning(self, "提示", "该目录是开发环境，不能作为安装目录应用补丁。")
                return
            if os.path.exists(os.path.join(d, "start.pyw")):
                self.install_dir = d
                self.lbl_dir.setText(d)
            else:
                MessageBox.warning(self, "提示", "该目录下未找到 start.pyw，可能不是有效的安装目录。")

    def _browse_patch(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择补丁包", "", "补丁包 (*.zip);;所有文件 (*.*)")
        if path:
            self.patch_path = path
            self.lbl_patch.setText(os.path.basename(path))
            self._load_patch_info(path)

    def _load_patch_info(self, path):
        try:
            with zipfile.ZipFile(path, "r") as zf:
                if "manifest.json" not in zf.namelist():
                    self.patch_info.setPlainText("错误：补丁包中缺少 manifest.json")
                    self.btn_apply.setEnabled(False)
                    return
                manifest = json.loads(zf.read("manifest.json"))
                ver = manifest.get("patch_version", "未知")
                desc = manifest.get("description", "无")
                created = manifest.get("created_date", "未知")
                files = manifest.get("files", [])

                info = f"补丁版本: v{ver}\n"
                info += f"创建日期: {created}\n"
                info += f"说明: {desc}\n"
                info += f"包含文件 ({len(files)} 个):\n"
                for f in files:
                    info += f"  • {f}\n"

                # use（仅识别器）安装模式提示：预览将被跳过的训练器/导入器文件
                if self.install_dir and _is_use_mode(self.install_dir):
                    skip_preview = [f for f in files if _norm_path(f) in _USE_SKIP_FILES]
                    if skip_preview:
                        info += f"\n（当前为仅识别器安装，将跳过 {len(skip_preview)} 个训练器/导入器相关文件）"

                self.patch_info.setPlainText(info)

                # 智能定向：补丁包携带 target_app_name 时，若当前未定位到安装目录，
                # 优先按目标名搜索 4 个标准位置，找不到再全盘扫描
                if not self.install_dir or not os.path.isfile(
                        os.path.join(self.install_dir, "start.pyw")):
                    # 优先用补丁包声明的目标名，没有则用默认 INSTALL_DIR_NAMES
                    target_names = []
                    if manifest.get("target_app_name"):
                        target_names.append(manifest["target_app_name"])
                    if manifest.get("target_app_aliases"):
                        for n in manifest["target_app_aliases"]:
                            if n and n not in target_names:
                                target_names.append(n)
                    if not target_names:
                        target_names = list(INSTALL_DIR_NAMES)
                    # 先用 find_install_dir 的标准搜索
                    found = find_install_dir()
                    if not found and target_names:
                        # 全盘搜索（只扫描盘符根目录下一级，约 1-2 秒）
                        found = _scan_all_drives_for_app(target_names)
                    if found:
                        self.install_dir = found
                        self.lbl_dir.setText(found)

                self.btn_apply.setEnabled(bool(self.install_dir))
        except Exception as e:
            self.patch_info.setPlainText(f"读取补丁包失败: {e}")
            self.btn_apply.setEnabled(False)

    def _apply_patch(self):
        if not self.install_dir or not os.path.exists(os.path.join(self.install_dir, "start.pyw")):
            MessageBox.warning(self, "错误", "请先选择有效的软件安装目录")
            return
        if not self.patch_path:
            MessageBox.warning(self, "错误", "请先选择补丁包")
            return

        # 检测软件是否正在运行
        if _is_software_running():
            MessageBox.warning(self, "软件正在运行",
                                "检测到旗帜逆向套件正在运行。\n请先关闭软件后再应用补丁，否则文件替换会失败。")
            return

        reply = MessageBox.question(
            self, "确认",
            f"即将应用补丁到:\n{self.install_dir}\n\n原文件将自动备份。是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return

        self.btn_apply.setEnabled(False)
        self.progress.setValue(0)
        self.worker = ApplyPatchThread(self.patch_path, self.install_dir)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_signal.connect(self._on_apply_done)
        self.worker.start()

    def _on_progress(self, pct, msg):
        self.progress.setValue(pct)
        self.progress_label.setText(msg)

    def _on_apply_done(self, ok, msg):
        self.btn_apply.setEnabled(True)
        if ok:
            MessageBox.information(self, "成功", msg)
        else:
            MessageBox.critical(self, "失败", msg)

    # --- 制作补丁 ---
    def _browse_src(self):
        d = QFileDialog.getExistingDirectory(self, "选择软件源目录（开发目录）")
        if d:
            self.lbl_src.setText(d)
            self._refresh_tree()

    def _add_single_file(self):
        """允许用户手动选择单个或多个文件添加到打包列表，不限于 PROGRAM_FILES 预设列表。"""
        src = self.lbl_src.text()
        start_dir = src if src and os.path.isdir(src) else os.path.expanduser("~")
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择要打包的文件", start_dir,
            "所有文件 (*);;Python 文件 (*.pyw *.py);;压缩包 (*.zip *.7z)")
        if not files:
            return
        # 找到或创建"手动添加"分组
        manual_item = None
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.text(0) == "手动添加的文件":
                manual_item = it
                break
        if manual_item is None:
            manual_item = QTreeWidgetItem()
            manual_item.setText(0, "手动添加的文件")
            manual_item.setFlags(manual_item.flags() | Qt.ItemIsUserCheckable)
            manual_item.setCheckState(1, Qt.Checked)
            self.tree.addTopLevelItem(manual_item)
            self.tree.expandItem(manual_item)
        # 逐个添加文件（记录绝对路径和目标相对路径到 data(0)）
        for fpath in files:
            # 计算相对路径：源目录内用相对路径（保留层级），源目录外弹输入框
            rel = None
            if src and os.path.isdir(src):
                try:
                    candidate = os.path.relpath(fpath, src)
                    if not candidate.startswith(".."):
                        rel = _norm_path(candidate)
                except Exception:
                    pass
            if rel is None:
                # 源目录外或没选源目录：弹输入框让用户指定目标路径（保留层级）
                default_rel = os.path.basename(fpath)
                rel, ok = QInputDialog.getText(
                    self, "指定目标路径",
                    f"文件不在源目录内，请输入它在补丁包中的相对路径\n（如 utils/foo.py 保留层级）:",
                    QLineEdit.Normal, default_rel)
                if not ok or not rel.strip():
                    continue
                rel = _norm_path(rel.strip())
            child = QTreeWidgetItem()
            child.setText(0, rel)  # 显示相对路径（保留层级）
            child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
            child.setCheckState(1, Qt.Checked)
            # 存 (绝对路径, 目标相对路径) 元组
            child.setData(0, Qt.UserRole, (fpath, rel))
            manual_item.addChild(child)
        self.btn_build.setEnabled(True)

    def _import_existing_patch(self):
        """导入已有补丁包：解析 manifest，预填版本/说明，预勾选文件，
        支持增减后重新打包。源目录里同名的文件会用新版本替换（默认勾选），
        源目录里没有但补丁包里有的文件会归入"原补丁包保留文件"分组，
        生成补丁时从原包直接抽取。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择要导入的已有补丁包", "", "补丁包 (*.zip);;所有文件 (*.*)")
        if not path:
            return
        try:
            with zipfile.ZipFile(path, "r") as zf:
                if "manifest.json" not in zf.namelist():
                    MessageBox.warning(self, "错误", "该 zip 不是有效补丁包：缺少 manifest.json")
                    return
                manifest = json.loads(zf.read("manifest.json"))
                ver = manifest.get("patch_version", "")
                desc = manifest.get("description", "")
                files = manifest.get("files", [])
                target_name = manifest.get("target_app_name", "")
                target_aliases = manifest.get("target_app_aliases", [])
        except Exception as e:
            MessageBox.critical(self, "错误", f"读取补丁包失败: {e}")
            return

        # 记录导入信息（_build_patch 据此抽取保留文件、沿用 target_app_name）
        self._imported_patch_path = path
        self._imported_files = [_norm_path(f) for f in files]
        self._imported_target_name = target_name
        self._imported_target_aliases = target_aliases

        # 预填版本号和说明（版本号建议自动 +1 patch 位，方便迭代）
        if ver:
            suggested = ver
            # 尝试把最后一段数字 +1（如 1.0.3 → 1.0.4），失败则原样保留
            try:
                parts = ver.split(".")
                parts[-1] = str(int(parts[-1]) + 1)
                suggested = ".".join(parts)
            except Exception:
                pass
            self.txt_version.setText(suggested)
        if desc:
            self.txt_desc.setPlainText(desc)

        src = self.lbl_src.text()
        has_src = bool(src and os.path.isdir(src))

        # 上方树（patch_tree）：原补丁包所有文件，默认全勾选（保留），用户可取消来移除
        self.patch_tree.clear()
        for rel in sorted(self._imported_files):
            child = QTreeWidgetItem()
            child.setText(0, rel)
            child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
            child.setCheckState(1, Qt.Checked)
            # 标记为原补丁包文件，生成时从原包抽取
            child.setData(0, Qt.UserRole, ("__imported__", rel))
            self.patch_tree.addTopLevelItem(child)
        self.gp_patch_files.setVisible(True)
        self.gp_patch_files.setTitle(
            f"原补丁包文件（保留/移除）— 共 {len(self._imported_files)} 个")

        # 下方树（tree）：开发目录文件，预勾选同名文件（替换为新版本）
        matched = 0
        if has_src:
            self._refresh_tree()       # 列出源目录所有文件（默认全勾选）
            self._set_all_checks(Qt.Unchecked)  # 全部取消
            # 建立 text(0) → item 索引
            index = {}
            def _index(item):
                t = item.text(0)
                if t:
                    index[t] = item
                for i in range(item.childCount()):
                    _index(item.child(i))
            for i in range(self.tree.topLevelItemCount()):
                _index(self.tree.topLevelItem(i))
            # 勾选补丁包里在源目录存在的文件（同名替换）
            for rel in self._imported_files:
                if rel in index:
                    index[rel].setCheckState(1, Qt.Checked)
                    matched += 1
        else:
            self.tree.clear()

        self.btn_build.setEnabled(True)
        retained = len(self._imported_files) - matched
        msg = (f"已导入补丁包：{os.path.basename(path)}\n"
               f"共 {len(self._imported_files)} 个文件：源目录匹配 {matched} 个，"
               f"保留原文件 {retained} 个。\n\n"
               f"版本号/说明已自动填充（版本号已 +1 建议）。\n"
               f"上方树：原补丁包文件（勾选=保留，取消=移除）\n"
               f"下方树：开发目录文件（勾选=新增/替换）\n"
               f"可在树上勾选/取消勾选来增减文件，重新生成补丁包。")
        MessageBox.information(self, "导入成功", msg)

    def _refresh_tree(self):
        src = self.lbl_src.text()
        if not src or not os.path.isdir(src):
            return
        self.tree.clear()
        for name in PROGRAM_FILES:
            full = os.path.join(src, name)
            if not os.path.exists(full):
                continue
            item = QTreeWidgetItem()
            item.setText(0, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(1, Qt.Checked)
            if os.path.isdir(full):
                for sub in sorted(os.listdir(full)):
                    sub_full = os.path.join(full, sub)
                    if os.path.isfile(sub_full):
                        child = QTreeWidgetItem()
                        child.setText(0, f"{name}/{sub}")
                        child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                        child.setCheckState(1, Qt.Checked)
                        item.addChild(child)
                    elif os.path.isdir(sub_full):
                        self._add_dir_children(item, f"{name}/{sub}", sub_full)
            self.tree.addTopLevelItem(item)
            self.tree.expandItem(item)
        self.btn_build.setEnabled(True)

    def _add_dir_children(self, parent, prefix, dirpath):
        for sub in sorted(os.listdir(dirpath)):
            sub_full = os.path.join(dirpath, sub)
            rel = f"{prefix}/{sub}"
            if os.path.isfile(sub_full):
                child = QTreeWidgetItem()
                child.setText(0, rel)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(1, Qt.Checked)
                parent.addChild(child)
            elif os.path.isdir(sub_full):
                child = QTreeWidgetItem()
                child.setText(0, rel)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(1, Qt.Checked)
                parent.addChild(child)
                self._add_dir_children(child, rel, sub_full)

    def _set_all_checks(self, state):
        """递归设置两个树中所有条目的勾选状态。"""
        def _recurse(item):
            for i in range(item.childCount()):
                child = item.child(i)
                if child.flags() & Qt.ItemIsUserCheckable:
                    child.setCheckState(1, state)
                _recurse(child)
        for tree in (self.tree, self.patch_tree):
            for i in range(tree.topLevelItemCount()):
                it = tree.topLevelItem(i)
                if it.flags() & Qt.ItemIsUserCheckable:
                    it.setCheckState(1, state)
                _recurse(it)

    def _build_patch(self):
        src = self.lbl_src.text()
        has_src = bool(src and os.path.isdir(src))
        # 没选源目录时，必须已导入原补丁包（否则没有文件来源）
        if not has_src and not self._imported_patch_path:
            MessageBox.warning(self, "错误", "请先选择源目录，或导入已有补丁包")
            return

        ver = self.txt_version.text().strip()
        if not ver:
            MessageBox.warning(self, "错误", "请填写补丁版本号")
            return

        desc = self.txt_desc.toPlainText().strip()
        if not desc:
            MessageBox.warning(self, "错误", "请填写补丁说明")
            return

        selected = []
        # 下方树（开发目录文件）：磁盘文件（新增/替换）
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            self._collect_checked(item, selected, src if has_src else None)
        # 收集磁盘文件路径集合，用于上方树去重（同名文件优先用磁盘新版本）
        disk_rels = set(rel for rel, full in selected if full is not None)
        # 上方树（原补丁包文件）：保留文件，跳过已在下方树中的同名文件
        patch_selected = []
        for i in range(self.patch_tree.topLevelItemCount()):
            item = self.patch_tree.topLevelItem(i)
            self._collect_checked(item, patch_selected, None)
        for rel, full in patch_selected:
            if rel not in disk_rels:
                selected.append((rel, full))

        if not selected:
            MessageBox.warning(self, "错误", "请至少选择一个文件")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存补丁包", f"patch_v{ver}.zip", "补丁包 (*.zip)")
        if not save_path:
            return

        # 区分磁盘文件和从原补丁包抽取的保留文件
        disk_files = [(rel, full) for rel, full in selected if full is not None]
        retained_files = [rel for rel, full in selected if full is None]

        # target_app_name/target_app_aliases：优先沿用导入的原补丁包，没有则用默认
        target_name = getattr(self, "_imported_target_name", "") or "旗帜编织逆向器"
        target_aliases = getattr(self, "_imported_target_aliases", []) or INSTALL_DIR_NAMES

        try:
            manifest = {
                "patch_version": ver,
                "description": desc,
                "created_date": datetime.datetime.now().strftime("%Y-%m-%d"),
                "files": [rel for rel, _ in selected],
                # 目标安装目录名（应用补丁时按此名字精准搜索安装位置）
                "target_app_name": target_name,
                "target_app_aliases": target_aliases,
            }

            # 先读取原补丁包中保留文件的内容到内存
            # （避免 save_path 覆盖原文件后无法读取）
            retained_data = {}
            if retained_files and self._imported_patch_path:
                try:
                    with zipfile.ZipFile(self._imported_patch_path, "r") as src_zf:
                        available = set(src_zf.namelist())
                        for rel in retained_files:
                            zip_name = f"files/{rel}"
                            if zip_name in available:
                                retained_data[zip_name] = src_zf.read(zip_name)
                except Exception as e:
                    MessageBox.warning(self, "错误", f"读取原补丁包失败: {e}")
                    return

            with zipfile.ZipFile(save_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                # 磁盘文件（源目录新版/手动添加）
                for rel, full in disk_files:
                    zf.write(full, f"files/{rel}")
                # 从原补丁包抽取的保留文件（已在内存中）
                for zip_name, data in retained_data.items():
                    zf.writestr(zip_name, data)

            MessageBox.information(
                self, "成功",
                f"补丁包已生成:\n{save_path}\n\n包含 {len(selected)} 个文件"
                f"（源目录 {len(disk_files)} 个，保留原文件 {len(retained_files)} 个）\n版本: v{ver}")
        except Exception as e:
            MessageBox.critical(self, "错误", f"生成补丁包失败: {e}")

    def _collect_checked(self, item, result, src_dir):
        name = item.text(0)
        stored_path = item.data(0, Qt.UserRole)
        # 增量补丁保留文件：stored_path 是 ("__imported__", rel_path) 元组，
        # full=None 标记生成时从原补丁包抽取，不依赖磁盘文件存在
        if isinstance(stored_path, tuple) and stored_path and stored_path[0] == "__imported__":
            rel = stored_path[1]
            if item.checkState(1) == Qt.Checked:
                result.append((_norm_path(rel), None))
        else:
            if stored_path:
                # 手动添加的文件：stored_path 可能是 (abs_path, rel_path) 元组
                if isinstance(stored_path, tuple) and len(stored_path) == 2:
                    full, rel = stored_path
                else:
                    full = stored_path
                    # 计算相对路径：在源目录内用相对路径，在源目录外用文件名
                    try:
                        rel = os.path.relpath(full, src_dir) if src_dir else os.path.basename(full)
                        if rel.startswith(".."):
                            rel = os.path.basename(full)
                    except Exception:
                        rel = os.path.basename(full)
            else:
                full = os.path.join(src_dir, name) if src_dir else name
                rel = name
            if item.checkState(1) == Qt.Checked:
                if os.path.isfile(full):
                    result.append((_norm_path(rel), full))
        for i in range(item.childCount()):
            self._collect_checked(item.child(i), result, src_dir)


def main():
    # 软件渲染（必须在 QApplication 创建前设置）：保证 agent 截图稳定可识别
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
    app = QApplication(sys.argv)

    # 单实例控制：防止重复打开补丁工具（Mutex 名与 start.pyw 检测一致）
    import ctypes
    _PATCH_MUTEX = "Global\\BannerToolPatchToolSingleInstance"
    _mtx = ctypes.windll.kernel32.CreateMutexW(None, False, _PATCH_MUTEX)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.kernel32.CloseHandle(_mtx)
        MessageBox.warning(None, "提示", "补丁工具已在运行，请先关闭已有的窗口。")
        return 0
    main._mtx = _mtx  # 保持引用防止 GC 释放

    scale = _detect_scale()
    # 应用全局主题（与主程序一致）：从 config.json 读取深浅色，原生对话框/标题栏跟随
    _startup_theme = resolve_theme(SettingsManager().get("theme", "light"))
    apply_theme(app, _startup_theme)
    app.setStyleSheet(_qss(scale, _startup_theme == "dark"))
    # 支持命令行参数 --install-dir=xxx（由 .cmd 启动器从注册表读出后传入，避免重复查找）
    prefilled_dir = None
    for arg in sys.argv:
        if arg.startswith("--install-dir="):
            prefilled_dir = arg.split("=", 1)[1].strip('"').strip("'")
            break
    win = PatchTool(scale)
    if prefilled_dir and os.path.exists(os.path.join(prefilled_dir, "start.pyw")):
        # 覆盖 find_install_dir 的结果（可能查不到注册表的旧版），用 .cmd 传入的更准
        win.install_dir = prefilled_dir
        if hasattr(win, "ed_install"):
            win.ed_install.setText(prefilled_dir)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
