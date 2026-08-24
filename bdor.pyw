import os
import sys
# 软件渲染：强制 Qt 走 CPU 软件渲染，兼容自动化 agent（截图/OCR/坐标点击）
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
# pythonw.exe 启动时 stdout/stderr 为 None，必须最早修复
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
# 防污染系统 Python：优先从安装目录的 Lib/site-packages 加载包
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
# dml_env Python 3.10 检测：用 dml_env 的 site-packages 避免 cp313 包冲突
_dml_sp = os.path.join(_APP_DIR, "dml_env", "Lib", "site-packages")
if sys.version_info[:2] == (3, 10) and os.path.isdir(os.path.join(_dml_sp, "PyQt5")):
    _VENDOR_PKGS = _dml_sp  # python310._pth 已将 dml_env/Lib/site-packages 加入 sys.path
else:
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
_crash_reported = False  # 防止同一崩溃被 _early_crash_handler 和 _global_excepthook 重复报告

def _early_crash_handler(exc_type, exc_value, exc_tb):
    global _crash_reported
    _crash_reported = True
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

import json
import time
import ctypes
import glob
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 读取训练模式：DirectML 模式下主进程不加载 torch（推理走 dml_env 子进程），
# 与训练器/导入器一致；只有 CUDA/CPU 模式才在主进程加载 torch。
# 注意：CUDA/CPU 的 torch 必须在 PyQt5 之前 import，否则 c10.dll 与 PyQt5 DLL 冲突。
_ARCH = "cpu"
try:
    _cfg_path = os.path.join(_APP_DIR, "config", "config.json")
    if os.path.exists(_cfg_path):
        with open(_cfg_path, "r", encoding="utf-8") as _f:
            _ARCH = (json.load(_f) or {}).get("train_arch", "cpu")
except Exception:
    pass
if _ARCH != "directml":
    try:
        import torch
    except Exception:
        torch = None  # 主环境 torch 缺失/损坏：后续 UI 显示友好提示
else:
    torch = None  # DirectML 模式：主进程不需要 torch，推理由 dml_env 子进程完成
import numpy as np
import cv2
from PIL import Image

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QGroupBox,
    QGridLayout, QComboBox, QScrollArea, QSizePolicy, QAction
)
from PyQt5.QtGui import QPixmap, QImage, QFont, QIcon
from PyQt5.QtCore import Qt, QSize, QBuffer, QTimer
from io import BytesIO

from utils.banner_utils import color_name, type, type_zh, generate_banner_image
from utils.settings_manager import apply_theme, apply_dwm_dark_mode, resolve_theme, report_error, resolve_app_path, show_about_dialog, MessageBox


def _cv2_imread_unicode(path):
    try:
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None


def _get_theme_from_config():
    """读取 config/config.json 的 theme 设置。"""
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "config", "config.json"
        )
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("theme", "light")
    except Exception:
        pass
    return "light"


# 单实例限制（旗帜印染逆向器独立计数，与训练器/导入器互不干扰）
_MAX_INSTANCES = 1
_REVERSER_LOCK_PREFIX = "banner_reverser_lock_"
_REVERSER_MUTEX_NAME = "Global\\banner_reverser_instance_mutex"
_TRAINER_LOCK_PATTERN = "banner_group_lock_*.lock"


def _is_pid_alive(pid):
    """检查指定 PID 的进程是否存活。"""
    try:
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            exit_code = ctypes.c_ulong()
            alive = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return alive and exit_code.value == STILL_ACTIVE
    except Exception:
        pass
    return False


def _parse_lock_content(content):
    """解析锁文件内容，返回 (pid, create_time)。支持旧格式（纯PID）和新格式（PID|create_time）。"""
    content = content.strip()
    if "|" in content:
        parts = content.split("|")
        try:
            pid = int(parts[0])
            ct_str = parts[1].strip("()")
            ct_parts = ct_str.split(", ")
            if len(ct_parts) == 2:
                return pid, (int(ct_parts[0]), int(ct_parts[1]))
            return pid, (0, 0)
        except Exception:
            return 0, (0, 0)
    else:
        try:
            return int(content), (0, 0)
        except Exception:
            return 0, (0, 0)


def _is_process_alive_with_create_time(pid, create_time):
    """检查进程是否存活，并通过创建时间验证是否为同一进程实例（防止 PID 复用）。"""
    try:
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        alive = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        if not alive or exit_code.value != STILL_ACTIVE:
            ctypes.windll.kernel32.CloseHandle(handle)
            return False
        if create_time != (0, 0):
            import ctypes.wintypes as wt
            creation = wt.FILETIME()
            exit_t = wt.FILETIME()
            kernel = wt.FILETIME()
            user = wt.FILETIME()
            ok = ctypes.windll.kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_t), ctypes.byref(kernel), ctypes.byref(user))
            ctypes.windll.kernel32.CloseHandle(handle)
            if not ok:
                return False
            actual_ct = (creation.dwLowDateTime, creation.dwHighDateTime)
            return actual_ct == create_time
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


def _check_trainer_importer_running():
    """检查训练器/导入器是否在运行（互斥阻拦）。
    通过 PID + 进程创建时间双重验证，防止 PID 复用导致的误判。
    """
    lock_files = glob.glob(os.path.join(tempfile.gettempdir(), _TRAINER_LOCK_PATTERN))
    for lf in lock_files:
        try:
            with open(lf, "r") as f:
                content = f.read()
            pid, create_time = _parse_lock_content(content)
            if pid <= 0:
                continue
            if _is_process_alive_with_create_time(pid, create_time):
                return True
            else:
                # 进程已死或 PID 被复用，清理残留锁文件
                try:
                    os.remove(lf)
                except Exception:
                    pass
        except Exception:
            try:
                os.remove(lf)
            except Exception:
                pass
    return False


def _check_instance_limit():
    """检查当前存活的逆向器实例数是否已达上限。"""
    max_instances = _MAX_INSTANCES
    if max_instances <= 0:
        return True
    lock_files = glob.glob(os.path.join(tempfile.gettempdir(), _REVERSER_LOCK_PREFIX + "*.lock"))
    alive_count = 0
    for lf in lock_files:
        try:
            with open(lf, "r") as f:
                pid = int(f.read().strip())
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                alive = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                ctypes.windll.kernel32.CloseHandle(handle)
                if alive and exit_code.value == STILL_ACTIVE:
                    alive_count += 1
                else:
                    try:
                        os.remove(lf)
                    except Exception:
                        pass
            else:
                try:
                    os.remove(lf)
                except Exception:
                    pass
        except Exception:
            try:
                os.remove(lf)
            except Exception:
                pass
    return alive_count < max_instances


def _create_instance_lock():
    """创建当前进程的锁文件。"""
    lock_file = os.path.join(tempfile.gettempdir(), f"{_REVERSER_LOCK_PREFIX}{os.getpid()}.lock")
    try:
        with open(lock_file, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass
    return lock_file


def _acquire_instance_slot():
    """原子地检查实例限制并创建锁文件（用Mutex避免竞态条件）。

    返回 lock_file 路径（成功）或 None（失败）。
    """
    max_instances = _MAX_INSTANCES
    if max_instances <= 0:
        return _create_instance_lock()

    WAIT_OBJECT_0 = 0
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, _REVERSER_MUTEX_NAME)
    if not mutex:
        return None
    wait_result = ctypes.windll.kernel32.WaitForSingleObject(mutex, 5000)
    try:
        if wait_result != WAIT_OBJECT_0:
            return None
        # 持有 Mutex，原子地检查+创建
        if not _check_instance_limit():
            return None
        return _create_instance_lock()
    finally:
        try:
            ctypes.windll.kernel32.ReleaseMutex(mutex)
        except Exception:
            pass
        ctypes.windll.kernel32.CloseHandle(mutex)


def _remove_instance_lock(lock_file):
    """删除锁文件。"""
    try:
        if lock_file and os.path.exists(lock_file):
            os.remove(lock_file)
    except Exception:
        pass


def _show_message(parent, title, text, msg_type="warning"):
    """操作类提示统一走 PyQt 自定义小窗（MessageBox，透明线框按钮，与训练器/导入器一致），
    错误统一走 report_error → error_reporter.pyw（固定大窗）。
    """
    if msg_type == "error":
        try:
            report_error(title, text, "逆向器")
        except Exception:
            pass
        return  # 错误统一由 error_reporter.pyw 显示（含导出日志功能）
    if msg_type == "info":
        MessageBox.information(parent, title, text)
    else:
        MessageBox.warning(parent, title, text)


class BannerRecognizer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("旗帜印染逆向器")
        icon_path = resolve_app_path("images/icons/mbtlx.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.model = None
        self.device = 'cpu'
        self.current_image = None
        self.current_result = None
        self._force_quit = False
        self._settings_process = None
        self._exit_process = None   # exit.pyw 退出确认子进程
        self._exit_timer = None

        # UI 缩放（与训练器/导入器完全一致的公式）
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        self._sw = geo.width() if geo else 1920
        self._sh = geo.height() if geo else 1080
        ui_scale = max(min(self._sw / 1920, self._sh / 1080), 1.0)
        self._scale = min(ui_scale * 1.25, 2.5)

        # 读取识别器设置（保守：仅自动加载模型和默认设备）
        try:
            from utils.settings_manager import SettingsManager as _SM
            _cfg = _SM()
            self._auto_load_default = _cfg.get("reverser_auto_load_model", False)
            self._default_device = _cfg.get("reverser_default_device", "auto")
        except Exception:
            self._auto_load_default = False
            self._default_device = "auto"

        # 主题
        self._theme = _get_theme_from_config()
        try:
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "config", "config.json"
            )
            self._config_mtime = os.path.getmtime(config_path)
        except Exception:
            self._config_mtime = 0

        self._init_ui()
        self._setup_menu()
        self._reapply_stylesheet()
        apply_dwm_dark_mode(self, self._theme == "dark")

        # 主题同步定时器
        self._theme_timer = QTimer(self)
        self._theme_timer.timeout.connect(self._sync_theme_from_config)
        self._theme_timer.start(1000)

    def _init_ui(self):
        s = self._scale
        base_w = max(int(self._sw * 0.5), 900)
        base_h = max(int(self._sh * 0.7), 640)
        self._min_w = max(int(self._sw * 0.4), 760)
        self._min_h = max(int(self._sh * 0.55), 520)
        self.setMinimumSize(self._min_w, self._min_h)
        self.resize(base_w, base_h)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(int(12 * s))

        base_fs = max(int(10 * s), 9)   # 与训练器/导入器一致的基础字号
        btn_fs = max(int(11 * s), 10)
        title_fs = max(int(12 * s), 11)

        # 模型加载组
        model_group = QGroupBox("模型加载")
        model_layout = QHBoxLayout(model_group)

        self.model_label = QLabel("未加载模型")
        self.model_label.setStyleSheet(f"font-size: {base_fs}px;")
        self.model_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        model_layout.addWidget(self.model_label, 1)

        # 设备选择已移至设置窗口（识别器设置 → 默认推理设备）
        # 这里只显示当前设备，不允许在主界面切换
        self._device_label = QLabel(f"设备: {self._resolve_device_name()}")
        self._device_label.setStyleSheet(f"font-size: {max(int(13*s),12)}px; color: {'#888' if self._theme == 'light' else '#999'};")
        model_layout.addWidget(self._device_label)

        load_btn = QPushButton("选择模型文件")
        load_btn.clicked.connect(self._load_model)
        load_btn.setMinimumWidth(max(int(120 * s), 100))
        load_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        model_layout.addWidget(load_btn)

        auto_load_btn = QPushButton("加载默认模型")
        auto_load_btn.clicked.connect(self._auto_load_model)
        auto_load_btn.setMinimumWidth(max(int(120 * s), 100))
        auto_load_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        model_layout.addWidget(auto_load_btn)

        main_layout.addWidget(model_group)

        # 内容区
        content_layout = QHBoxLayout()
        content_layout.setSpacing(int(12 * s))

        # 输入图片组
        input_group = QGroupBox("输入旗帜图片")
        input_layout = QVBoxLayout(input_group)

        self.input_label = QLabel("请导入旗帜图片")
        self.input_label.setAlignment(Qt.AlignCenter)
        self.input_label.setMinimumSize(int(280 * s), int(400 * s))
        self.input_label.setStyleSheet(
            f"font-size: {base_fs}px; "
            "border: 2px dashed #aaa; border-radius: 4px;"
        )
        self.input_label.setScaledContents(False)
        input_layout.addWidget(self.input_label, 1)

        btn_row = QHBoxLayout()
        import_file_btn = QPushButton("从文件导入")
        import_file_btn.clicked.connect(self._import_from_file)
        import_file_btn.setMinimumWidth(max(int(120 * s), 100))
        import_file_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_row.addWidget(import_file_btn)

        import_clip_btn = QPushButton("从剪贴板粘贴")
        import_clip_btn.clicked.connect(self._import_from_clipboard)
        import_clip_btn.setMinimumWidth(max(int(120 * s), 100))
        import_clip_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_row.addWidget(import_clip_btn)

        input_layout.addLayout(btn_row)
        content_layout.addWidget(input_group, 1)

        # 结果组
        result_group = QGroupBox("逆向结果")
        result_layout = QVBoxLayout(result_group)

        self.result_preview = QLabel("逆向结果预览")
        self.result_preview.setAlignment(Qt.AlignCenter)
        self.result_preview.setMinimumSize(int(280 * s), int(400 * s))
        self.result_preview.setStyleSheet(
            f"font-size: {base_fs}px; "
            "border: 2px dashed #aaa; border-radius: 4px;"
        )
        result_layout.addWidget(self.result_preview, 1)

        self.result_text = QLabel("")
        self.result_text.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.result_text.setWordWrap(True)
        self.result_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.result_text.setStyleSheet(f"font-size: {title_fs}px; padding: {int(8*s)}px;")
        self.result_text.setMinimumHeight(int(100 * s))
        result_layout.addWidget(self.result_text)

        recognize_btn = QPushButton("逆向印染")
        recognize_btn.setObjectName("primaryButton")
        recognize_btn.clicked.connect(self._recognize)
        recognize_btn.setMinimumWidth(max(int(120 * s), 100))
        recognize_btn.setMinimumHeight(max(int(36 * s), 30))
        recognize_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        result_layout.addWidget(recognize_btn)

        content_layout.addWidget(result_group, 1)
        main_layout.addLayout(content_layout, 1)

    def _setup_menu(self):
        """创建完整菜单栏：文件/编辑/缩放/视图/设置/帮助。"""
        bar = self.menuBar()

        # 文件菜单
        file_menu = bar.addMenu("文件(&F)")
        act_import_file = QAction("从文件导入...", self)
        act_import_file.setShortcut("Ctrl+I")
        act_import_file.triggered.connect(self._import_from_file)
        file_menu.addAction(act_import_file)

        act_import_clip = QAction("从剪贴板粘贴...", self)
        act_import_clip.setShortcut("Ctrl+V")
        act_import_clip.triggered.connect(self._import_from_clipboard)
        file_menu.addAction(act_import_clip)

        file_menu.addSeparator()
        act_exit = QAction("退出", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # 编辑菜单
        edit_menu = bar.addMenu("编辑(&E)")
        act_clear_image = QAction("清除图片", self)
        act_clear_image.triggered.connect(self._clear_image)
        edit_menu.addAction(act_clear_image)

        act_clear_result = QAction("清除结果", self)
        act_clear_result.triggered.connect(self._clear_result)
        edit_menu.addAction(act_clear_result)

        # 缩放菜单（视图子菜单）
        view_menu = bar.addMenu("视图(&V)")
        scale_menu = view_menu.addMenu("界面缩放")

        act_zoom_in = QAction("放大", self)
        act_zoom_in.setShortcut("Ctrl++")
        act_zoom_in.triggered.connect(lambda: self._menu_zoom(1.25))
        scale_menu.addAction(act_zoom_in)

        act_zoom_out = QAction("缩小", self)
        act_zoom_out.setShortcut("Ctrl+-")
        act_zoom_out.triggered.connect(lambda: self._menu_zoom(0.8))
        scale_menu.addAction(act_zoom_out)

        scale_menu.addSeparator()
        self._scale_actions = {}
        preset_scales = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0]
        for sv in preset_scales:
            label = f"{int(sv*100)}%"
            act = QAction(label, self, checkable=True)
            act.triggered.connect(lambda checked, v=sv: self._menu_set_scale(v))
            scale_menu.addAction(act)
            self._scale_actions[sv] = act

        scale_menu.addSeparator()
        act_auto = QAction("自动", self)
        act_auto.triggered.connect(self._menu_scale_auto)
        scale_menu.addAction(act_auto)

        self._scale_current_action = QAction("", self)
        self._scale_current_action.setEnabled(False)
        scale_menu.addAction(self._scale_current_action)
        self._update_scale_menu_check()

        # 设置
        act_settings = QAction("设置(&S)", self)
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self._menu_open_settings)
        bar.addAction(act_settings)

        # 帮助菜单
        help_menu = bar.addMenu("帮助(&H)")
        act_help = QAction("使用说明", self)
        act_help.setShortcut("F1")
        act_help.triggered.connect(self._menu_show_help)
        help_menu.addAction(act_help)

        help_menu.addSeparator()
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._menu_about)
        help_menu.addAction(act_about)

    def _reapply_stylesheet(self):
        """根据当前主题应用全局样式表。"""
        is_dark = (self._theme == "dark")
        s = self._scale
        base_fs = max(int(10 * s), 9)   # 与训练器/导入器一致的基础字号
        btn_fs = max(int(11 * s), 10)

        if is_dark:
            bg = "#2d2d30"           # 与训练器/导入器深色一致
            bg_alt = "#3c3c3c"
            fg = "#eeeeee"
            group_border = "#555555"
            input_bg = "#3c3c3c"
            btn_disabled_fg = "#999999"
            border_dash = "#555555"
            menubar_sel = "#1a73e8"
            scroll_handle = "#555555"
            scroll_hover = "#666666"
            scroll_pressed = "#777777"
            tooltip_bg = "#2d2d30"
            tooltip_border = "#555555"
            tooltip_fg = "#eeeeee"
            combo_arrow = "#cccccc"
        else:
            bg = "#f5f5f5"
            bg_alt = "#ffffff"
            fg = "#000000"
            group_border = "#cccccc"
            input_bg = "#ffffff"
            btn_disabled_fg = "#888888"
            border_dash = "#aaaaaa"
            menubar_sel = "#e0e0e0"
            scroll_handle = "#c0c0c0"
            scroll_hover = "#a0a0a0"
            scroll_pressed = "#909090"
            tooltip_bg = "#ffffff"
            tooltip_border = "#cccccc"
            tooltip_fg = "#1a1a1a"
            combo_arrow = "#666666"

        # ===== 按钮样式：透明线框（可用=蓝边框蓝字，禁用=灰；与设置窗口 OK 按钮一致）=====
        _mh = max(int(26 * s), 22)
        _p1 = max(int(6 * s), 4)
        _p2 = max(int(14 * s), 10)
        if is_dark:
            _bbrd, _bfg, _bhov = "#0078D4", "#0078D4", "#1e3a5f"
            _dbrd, _dfg = "#3a3a3a", "#777777"
        else:
            _bbrd, _bfg, _bhov = "#0078D4", "#0078D4", "#e8f1fb"
            _dbrd, _dfg = "#cccccc", "#aaaaaa"
        _btn_qss = (
            "QPushButton { font-size: %dpx; min-height: %dpx; padding: %dpx %dpx; "
            "border: 1px solid " + _bbrd + "; border-radius: 6px; background: transparent; color: " + _bfg + "; } "
            "QPushButton:hover { background: " + _bhov + "; border-color: " + _bbrd + "; color: " + _bfg + "; } "
            "QPushButton:pressed { background: " + _bhov + "; border-color: " + _bbrd + "; color: " + _bfg + "; } "
            "QPushButton:disabled { background: transparent; color: " + _dfg + "; border-color: " + _dbrd + "; }"
        ) % (btn_fs, _mh, _p1, _p2)

        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {bg}; color: {fg}; }}
            QWidget {{ color: {fg}; }}
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {group_border};
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 16px;
                font-size: {base_fs}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
            QLabel {{ font-size: {base_fs}px; color: {fg}; }}
            {_btn_qss}
            QComboBox {{
                border: 1px solid {group_border};
                border-radius: 4px;
                padding: {max(int(4*s),3)}px;
                font-size: {base_fs}px;
                background-color: {input_bg};
                color: {fg};
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: {max(int(20*s),16)}px;
                border: none;
            }}
            QComboBox::down-arrow {{
                width: 10px; height: 10px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {input_bg};
                color: {fg};
                selection-background-color: {menubar_sel};
                border: 1px solid {group_border};
                outline: none;
            }}
            QToolTip {{
                background-color: {tooltip_bg};
                color: {tooltip_fg};
                border: 1px solid {tooltip_border};
                border-radius: 4px;
                padding: {max(int(4*s),3)}px;
                font-size: {base_fs}px;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 0;
                border: none;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 10px;
                margin: 0;
                border: none;
            }}
            QScrollBar::handle {{
                background: {scroll_handle};
                border-radius: 5px;
                min-height: 30px;
                min-width: 30px;
            }}
            QScrollBar::handle:hover {{ background: {scroll_hover}; }}
            QScrollBar::handle:pressed {{ background: {scroll_pressed}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{
                border: none;
                background: none;
                width: 0;
                height: 0;
            }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        """)

        # 更新虚线边框颜色
        for label in [self.input_label, self.result_preview]:
            label.setStyleSheet(
                f"font-size: {base_fs}px; "
                f"border: 2px dashed {border_dash}; border-radius: 4px;"
            )

        # 菜单栏颜色（与训练器/导入器一致：选中高亮蓝，深浅色适配）
        menubar = self.menuBar()
        if menubar is not None:
            menubar.setStyleSheet(
                f"QMenuBar {{ background-color: {bg}; color: {fg}; }}"
                f"QMenuBar::item:selected {{ background-color: {'#1a73e8' if is_dark else '#e0e0e0'}; }}"
                f"QMenu {{ background-color: {bg}; color: {fg}; }}"
                f"QMenu::item:selected {{ background-color: {'#1a73e8' if is_dark else '#e0e0e0'}; }}"
            )

        # 标题栏深浅色
        apply_dwm_dark_mode(self, self._theme == "dark")

    def _sync_theme_from_config(self):
        """定时检查 config.json 主题变化（mtime优化）。"""
        try:
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "config", "config.json"
            )
            try:
                current_mtime = os.path.getmtime(config_path)
            except Exception:
                current_mtime = 0
            if current_mtime == self._config_mtime:
                return
            self._config_mtime = current_mtime

            new_theme = _get_theme_from_config()
            if new_theme != self._theme:
                self._theme = new_theme
                # 同步全局调色板（让原生对话框跟随主题）
                app = QApplication.instance()
                if app is not None:
                    apply_theme(app, resolve_theme(new_theme))
                self._reapply_stylesheet()
        except Exception:
            pass

    def _menu_zoom(self, factor):
        self._scale = min(max(self._scale * factor, 0.5), 4.0)
        self._reapply_stylesheet()
        self._update_scale_menu_check()

    def _menu_set_scale(self, value):
        self._scale = value
        self._reapply_stylesheet()
        self._update_scale_menu_check()

    def _menu_scale_auto(self):
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        sw = geo.width() if geo else 1920
        sh = geo.height() if geo else 1080
        self._scale = max(min(min(sw / 1920, sh / 1080) * 1.25, 2.5), 1.0)
        self._reapply_stylesheet()
        self._update_scale_menu_check()

    def _update_scale_menu_check(self):
        for sv, act in self._scale_actions.items():
            act.setChecked(abs(sv - self._scale) < 0.01)
        self._scale_current_action.setText(f"当前: {int(self._scale*100)}%")

    def _menu_open_settings(self):
        """启动独立设置程序（子进程），已运行则恢复并跳转到识别器设置页。"""
        import subprocess

        # 已有进程在跑：写命令文件通知跳转，不重复启动
        existing = getattr(self, "_settings_process", None)
        if existing is not None and existing.poll() is None:
            try:
                import tempfile
                cmd_file = os.path.join(tempfile.gettempdir(), "_banner_settings_cmd")
                with open(cmd_file, "w", encoding="utf-8") as f:
                    f.write("reverser")
            except Exception:
                pass
            return

        app_dir = os.path.dirname(os.path.abspath(__file__))
        settings_script = os.path.join(app_dir, "utils", "settings_dialog.py")
        if not os.path.exists(settings_script):
            _show_message(self, "错误", f"找不到设置程序:\n{settings_script}", "error")
            return
        try:
            proc = subprocess.Popen(
                [sys.executable, settings_script, "--caller", "reverser", "--scale", str(self._scale)],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self._settings_process = proc
            self._poll_settings_exit()
        except Exception as e:
            _show_message(self, "错误", f"无法打开设置:\n{str(e)}", "error")

    def _poll_settings_exit(self):
        """轮询设置子进程是否退出，处理重启请求（exit_code 100 表示需要重启）。"""
        proc = getattr(self, "_settings_process", None)
        if proc is None:
            return
        if proc.poll() is not None:
            exit_code = proc.returncode
            self._settings_process = None
            if exit_code == 100:
                self._do_restart()
            return
        QTimer.singleShot(200, self._poll_settings_exit)

    def _do_restart(self):
        """重启识别器（独立程序，直接重启自身，无需通知其他进程）。"""
        import subprocess
        self._force_quit = True
        # 清理当前实例锁文件，避免新进程被单实例检查阻拦
        _lock = getattr(self, "_lock_file", None)
        if _lock:
            _remove_instance_lock(_lock)
        restart_argv = [sys.argv[0], "--restart"]
        QApplication.quit()
        subprocess.Popen([sys.executable] + restart_argv, creationflags=subprocess.CREATE_NO_WINDOW)
        sys.exit(0)

    # ---------- 退出确认（exit.pyw 独立进程，与训练器/导入器一致）----------
    def closeEvent(self, event):
        """窗口关闭：有数据时先走 exit.pyw 退出确认，无数据/强制退出则直接关闭。"""
        # 关闭独立设置子进程（如有）：发 close 信号，设置默认不保存退出
        proc = getattr(self, "_settings_process", None)
        if proc is not None and proc.poll() is None:
            try:
                import tempfile
                cmd_file = os.path.join(tempfile.gettempdir(), "_banner_settings_cmd")
                with open(cmd_file, "w", encoding="utf-8") as f:
                    f.write("close")
            except Exception:
                pass

        if self._force_quit:
            event.accept()
            return

        if getattr(self, "_exit_process", None) is not None:
            # 已有 exit.pyw 在运行，忽略本次关闭
            event.ignore()
            return

        # 无数据（未加载图片/模型结果）时直接退出，不弹确认窗
        has_data = (self.current_image is not None or self.current_result is not None)
        if not has_data:
            event.accept()
            return

        msg = "旗帜印染逆向器即将关闭。\n\n"
        if has_data:
            msg += "• 已加载的图片/识别结果将丢失。\n"
        msg += "\n确定要退出吗？"
        self._launch_exit_confirmation("识别器", msg)
        event.ignore()

    def _launch_exit_confirmation(self, source, msg):
        """启动 exit.pyw 子进程显示退出确认窗口，并用定时器轮询结果。"""
        import tempfile
        info_file = os.path.join(tempfile.gettempdir(), f"exit_info_{os.getpid()}.txt")
        try:
            with open(info_file, "w", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass

        import subprocess
        exit_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "exit.pyw")
        session_dir = tempfile.gettempdir()
        can_save = "0"  # 识别器无训练数据保存，仅确认退出
        try:
            self._exit_process = subprocess.Popen(
                [sys.executable, exit_path, "exit", source, session_dir, info_file, can_save],
            )
        except Exception:
            self._exit_process = None
            return

        from PyQt5.QtCore import QTimer
        self._exit_timer = QTimer(self)
        self._exit_timer.timeout.connect(self._check_exit_result)
        self._exit_timer.start(100)

    def _check_exit_result(self):
        """定时器回调：检查 exit.pyw 的确认/取消信号。"""
        import tempfile
        session_dir = tempfile.gettempdir()
        confirmed_file = os.path.join(session_dir, ".exit_confirmed")
        cancelled_file = os.path.join(session_dir, ".exit_cancelled")

        if os.path.exists(confirmed_file):
            try:
                os.remove(confirmed_file)
            except Exception:
                pass
            if self._exit_timer is not None:
                self._exit_timer.stop()
                self._exit_timer = None
            self._exit_process = None
            self._force_quit = True
            self.close()
        elif os.path.exists(cancelled_file):
            try:
                os.remove(cancelled_file)
            except Exception:
                pass
            if self._exit_timer is not None:
                self._exit_timer.stop()
                self._exit_timer = None
            self._exit_process = None

    def _menu_show_help(self):
        """打开使用说明窗口（子进程），跳转到识别器章节。"""
        import subprocess
        app_dir = os.path.dirname(os.path.abspath(__file__))
        help_script = os.path.join(app_dir, "help.pyw")
        if os.path.exists(help_script):
            try:
                subprocess.Popen([sys.executable, help_script, "--scale", str(self._scale), "--section", "reverser"])
            except Exception:
                pass

    def _menu_about(self):
        # 与训练器/导入器一致的关于窗口（深色模式同步深色标题栏）
        show_about_dialog(self, "关于",
                          "旗帜印染逆向器 v0.5 beta1 (1.0.8)\n\n基于Vision Transformer的旗帜图片逆向识别工具。")

    def _clear_image(self):
        self.current_image = None
        self.input_label.clear()
        self.input_label.setText("请导入旗帜图片")

    def _clear_result(self):
        self.current_result = None
        self.result_preview.clear()
        self.result_preview.setText("逆向结果预览")
        self.result_text.setText("")

    def _resolve_device_name(self):
        """根据 _default_device 设置和后端可用性，返回实际设备名。"""
        pref = getattr(self, "_default_device", "auto")
        from utils.device_backend import get_compute_backend, is_directml_available, is_cuda_available
        if pref == "cpu":
            return "cpu"
        elif pref == "cuda":
            return "cuda" if is_cuda_available() else "cpu (CUDA不可用)"
        elif pref == "directml":
            return "directml" if is_directml_available() else "cpu (DirectML不可用)"
        else:  # auto
            # 优先按用户选择的训练架构：DirectML 时推理走 dml_env 子进程，
            # 设备显示 directml（不能用 get_compute_backend，它在本进程
            # import torch_directml 必失败 → 永远返回 cpu）
            try:
                from utils.settings_manager import SettingsManager
                if SettingsManager().get("train_arch", "") == "directml":
                    return "directml"
            except Exception:
                pass
            backend = get_compute_backend()
            if backend == "cuda":
                return "cuda"
            elif backend == "directml":
                return "directml"
            return "cpu"

    def _get_device(self):
        """返回实际推理设备（从设置读取，auto模式下优先CUDA>DirectML>CPU）。"""
        name = self._resolve_device_name().split(" ")[0]
        if name == "directml":
            try:
                import torch_directml
                if torch_directml.is_available():
                    return torch_directml.device()
            except Exception:
                pass
            return "cpu"
        return name

    def _get_model_dir(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "model_file")

    def _find_latest_model(self):
        model_dir = self._get_model_dir()
        if not os.path.isdir(model_dir):
            return None
        pth_files = [f for f in os.listdir(model_dir) if f.endswith('.pth') or f.endswith('.pt')]
        if not pth_files:
            return None
        pth_files.sort(key=lambda f: os.path.getmtime(os.path.join(model_dir, f)), reverse=True)
        return os.path.join(model_dir, pth_files[0])

    def _list_models_by_time(self):
        """返回 models/model_file/ 下所有模型，按修改时间降序（最新在前）。"""
        from datetime import datetime
        model_dir = self._get_model_dir()
        if not os.path.isdir(model_dir):
            return []
        entries = []
        for f in os.listdir(model_dir):
            if not (f.endswith('.pth') or f.endswith('.pt')):
                continue
            full = os.path.join(model_dir, f)
            mtime = os.path.getmtime(full)
            ts_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            entries.append((full, f, ts_str, mtime))
        entries.sort(key=lambda x: x[3], reverse=True)  # 最新在前
        return entries

    def _load_model(self):
        """弹出模型选择对话框，按时间排序，可挑选。"""
        # DirectML 模式：模型由 dml_env 子进程在推理时自动加载，主进程无需加载
        if torch is None:
            _show_message(self, "提示",
                          "DirectML 模式下模型由推理引擎自动加载，\n直接导入旗帜图片点击「逆向」即可。", "info")
            return
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QListWidget, 
                                      QPushButton, QHBoxLayout, QLabel)
        entries = self._list_models_by_time()
        if not entries:
            model_dir = self._get_model_dir()
            _show_message(self, "提示", f"模型目录中没有模型文件:\n{model_dir}\n请先训练模型。", "info")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("选择模型")
        dlg.setMinimumWidth(480)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel(f"共 {len(entries)} 个模型（按时间最新在前）："))

        list_widget = QListWidget(dlg)
        for full_path, fname, ts_str, _ in entries:
            arch_hint = ""
            try:
                if torch is not None:
                    ck = torch.load(full_path, map_location='cpu', weights_only=False)
                    if isinstance(ck, dict) and 'model_arch' in ck:
                        arch_hint = f"  [{ck['model_arch']}]"
            except Exception:
                pass
            list_widget.addItem(f"{fname}    {ts_str}{arch_hint}")
        list_widget.setCurrentRow(0)
        layout.addWidget(list_widget)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("加载", dlg)
        cancel_btn = QPushButton("取消", dlg)
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            return
        row = list_widget.currentRow()
        if row < 0 or row >= len(entries):
            return
        self._do_load_model(entries[row][0])

    def _auto_load_model(self, silent=False):
        """自动加载默认模型。

        silent=True 时（启动时自动调用）：没找到模型不弹窗，只更新label状态（保护措施）。
        silent=False 时（手动点击按钮）：没找到模型弹info提示。
        """
        # DirectML 模式：主进程无 torch，模型由 dml_env 子进程在推理时自动加载
        if torch is None:
            if not silent:
                _show_message(self, "提示",
                              "DirectML 模式下模型由推理引擎自动加载，\n直接导入旗帜图片点击「逆向」即可。", "info")
            return
        model_path = self._find_latest_model()
        if model_path is None:
            if not silent:
                model_dir = self._get_model_dir()
                _show_message(self, "提示", f"默认模型目录中没有模型文件:\n{model_dir}\n请先训练模型或手动选择模型文件。", "info")
            else:
                # 启动时自动加载：静默处理，只更新label显示"未加载模型"
                pass
            return
        self._do_load_model(model_path)

    def _do_load_model(self, model_path):
        # 安全兜底：DirectML 模式主进程无 torch，模型加载由 dml_env 子进程完成
        if torch is None:
            self.model = None
            self.model_label.setText("未加载模型（DirectML 由引擎自动加载）")
            return
        try:
            from models.structures.vit_model import ViT
            self.device = self._get_device()
            checkpoint = torch.load(model_path, map_location=self.device, weights_only=False)

            # 读取架构信息，用正确架构创建 ViT（防止架构不匹配）
            if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint:
                arch = checkpoint.get('model_arch', 'vit_b_16')
                self.model = ViT(model_arch=arch)
                state = checkpoint['model_state_dict']
            else:
                # 旧格式：直接是 state_dict，使用默认架构
                self.model = ViT()
                state = checkpoint

            # strict=False 允许 pattern_classifiers 数量不匹配
            # （旧模型可能只有 8 个图层，当前模型有 16 个图层）
            missing, unexpected = self.model.load_state_dict(state, strict=False)
            if missing or unexpected:
                msg_parts = []
                if missing:
                    msg_parts.append(f"缺失 {len(missing)} 个键（随机初始化）")
                if unexpected:
                    msg_parts.append(f"多余 {len(unexpected)} 个键（已忽略）")
                load_warn = "（" + "，".join(msg_parts) + "）"
            else:
                load_warn = ""

            self.model.to(self.device)
            self.model.eval()
            self.model_label.setText(f"已加载: {os.path.basename(model_path)} ({self.device})")
            is_dark = (self._theme == "dark")
            ok_color = "#4fc3f7" if is_dark else "#4CAF50"
            self.model_label.setStyleSheet(f"font-size: {max(int(12*self._scale),11)}px; color: {ok_color};")
            # 同步更新设备显示
            if hasattr(self, "_device_label"):
                self._device_label.setText(f"设备: {self.device}")
            _show_message(self, "成功", f"模型加载成功\n设备: {self.device}{load_warn}", "info")
        except Exception as e:
            import traceback
            err_detail = f"模型加载失败:\n{str(e)}\n\n--- 详细错误 ---\n{traceback.format_exc()}"
            _show_message(self, "错误", err_detail, "error")
            self.model = None
            self.model_label.setText("模型加载失败")
            is_dark = (self._theme == "dark")
            err_color = "#f44336" if is_dark else "#f44336"
            self.model_label.setStyleSheet(f"font-size: {max(int(12*self._scale),11)}px; color: {err_color};")

    def _set_image_to_label(self, label, cv2_image, max_w=None, max_h=None):
        if cv2_image is None:
            return
        rgb = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)

        if max_w is None:
            max_w = label.width() - 10
        if max_h is None:
            max_h = label.height() - 10
        scaled = qimg.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(QPixmap.fromImage(scaled))

    def _import_from_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择旗帜图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif);;所有文件 (*)"
        )
        if not file_path:
            return
        img = _cv2_imread_unicode(file_path)
        if img is None:
            img = cv2.imread(file_path)
        if img is None:
            _show_message(self, "警告", "无法读取图片文件", "warning")
            return
        self.current_image = img
        self._set_image_to_label(self.input_label, img)
        self.result_preview.clear()
        self.result_preview.setText("逆向结果预览")
        self.result_text.setText("")

    def _import_from_clipboard(self):
        clipboard = QApplication.clipboard()
        pixmap = clipboard.pixmap()
        if pixmap.isNull():
            _show_message(self, "警告", "剪贴板中没有图片", "warning")
            return
        img = self._qimage_to_cv2(pixmap.toImage())
        if img is None:
            _show_message(self, "警告", "无法读取剪贴板图片", "warning")
            return
        self.current_image = img
        self._set_image_to_label(self.input_label, img)
        self.result_preview.clear()
        self.result_preview.setText("逆向结果预览")
        self.result_text.setText("")

    def _qimage_to_cv2(self, qimg):
        w = qimg.width()
        h = qimg.height()
        if w == 0 or h == 0:
            return None
        buffer = QBuffer()
        buffer.open(QBuffer.ReadWrite)
        qimg.save(buffer, "PNG")
        pil_img = Image.open(BytesIO(buffer.data()))
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    def _recognize(self):
        if self.current_image is None:
            _show_message(self, "警告", "请先导入旗帜图片", "warning")
            return

        try:
            # DirectML 模式：推理委托给 dml_env 子进程（主环境无 torch_directml，
            # 无法直接 DML 推理；子进程在 dml_env python 3.10 里完成加载+前向）
            # 判断依据：config 的 train_arch 明确选择 DirectML。
            # 注意不能用 get_compute_backend()——它在本进程 import torch_directml
            # 必然失败（DML 的 torch 只在 dml_env 3.10 里），会永远返回 cpu。
            _use_dml = False
            try:
                from utils.settings_manager import SettingsManager
                _use_dml = SettingsManager().get("train_arch", "") == "directml"
            except Exception:
                _use_dml = False
            if _use_dml:
                banner_data = self._recognize_via_dml_worker()
                if banner_data is None:
                    return
                self.current_result = banner_data
                self._render_result(banner_data)
                return

            if self.model is None:
                _show_message(self, "警告", "请先加载模型", "warning")
                return

            self.device = self._get_device()
            self.model.to(self.device)

            img_rgb = cv2.cvtColor(self.current_image, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)

            from models.structures.vit_model import get_transform
            transform = get_transform(for_pil=True)

            input_tensor = transform(pil_img).unsqueeze(0).to(self.device)

            with torch.no_grad():
                bg_pred, pattern_preds = self.model(input_tensor)

            bg_color_idx = torch.argmax(bg_pred, dim=1).item()

            patterns = []
            num_slots = getattr(self.model, 'num_pattern_slots', 16)
            for i in range(num_slots):
                p_type_idx = torch.argmax(pattern_preds[2*i], dim=1).item()
                p_color_idx = torch.argmax(pattern_preds[2*i+1], dim=1).item()
                if p_type_idx > 0:
                    patterns.append((p_type_idx, p_color_idx))

            banner_data = [bg_color_idx]
            for p_type, p_color in patterns:
                banner_data.extend([p_type, p_color])

            self.current_result = banner_data
            self._render_result(banner_data)

        except Exception as e:
            import traceback
            err_detail = f"逆向失败:\n{str(e)}\n\n--- 详细错误 ---\n{traceback.format_exc()}"
            _show_message(self, "错误", err_detail, "error")

    def _render_result(self, banner_data):
        """根据 banner_data 渲染结果预览图与文本（CPU/CUDA/DML 共用）。"""
        result_img = generate_banner_image(banner_data, size=(200, 400))
        self._set_image_to_label(self.result_preview, result_img)

        seq_parts = []
        bg_color_idx = banner_data[0]
        bg_name = color_name[bg_color_idx] if bg_color_idx < len(color_name) else f"?{bg_color_idx}"
        seq_parts.append(bg_name)

        rest = banner_data[1:]
        for i in range(0, len(rest) - 1, 2):
            p_type, p_color = rest[i], rest[i + 1]
            if p_type <= 0:
                continue
            t_name = type[p_type] if p_type < len(type) else f"?{p_type}"
            c_name = color_name[p_color] if p_color < len(color_name) else f"?{p_color}"
            seq_parts.append(f"{t_name}_{c_name}")

        seq_str = " > ".join(seq_parts)

        detail_lines = [f"序列: {seq_str}", f"数据: {banner_data}", ""]
        detail_lines.append(f"背景: {bg_name}")
        has_pattern = False
        for i in range(0, len(rest) - 1, 2):
            p_type, p_color = rest[i], rest[i + 1]
            if p_type <= 0:
                continue
            has_pattern = True
            t_zh = type_zh[p_type] if p_type < len(type_zh) else f"?{p_type}"
            c_zh = color_name[p_color] if p_color < len(color_name) else f"?{p_color}"
            detail_lines.append(f"图案{len([d for d in detail_lines if d.startswith('图案')]) + 1}: {t_zh} / {c_zh}")
        if not has_pattern:
            detail_lines.append("无图案")

        self.result_text.setText("\n".join(detail_lines))

    def _recognize_via_dml_worker(self):
        """DML 模式：把当前图片交给 dml_env 子进程推理，返回 banner_data 或 None。"""
        import subprocess
        import tempfile
        import json as _json
        try:
            dml_py = os.path.join(_APP_DIR, "dml_env", "python.exe")
            if not os.path.isfile(dml_py):
                _show_message(self, "错误",
                              "未找到 dml_env 便携环境，无法使用 DirectML 推理。\n"
                              "请用安装包维护模式安装 DirectML 环境后重试。", "error")
                return None
            model_path = self._find_latest_model()
            if model_path is None:
                _show_message(self, "提示", "模型目录中没有模型文件，请先训练模型或手动选择模型文件。", "info")
                return None
            # 保存当前图片为临时文件（子进程读取）
            fd, tmp_img = tempfile.mkstemp(suffix=".png", prefix="reverser_dml_")
            os.close(fd)
            try:
                cv2.imwrite(tmp_img, self.current_image)
                worker = os.path.join(_APP_DIR, "scripts", "reverser_dml_worker.py")
                proc = subprocess.run(
                    [dml_py, worker, "--image", tmp_img, "--model", model_path],
                    capture_output=True, text=True, encoding="utf-8",
                    cwd=_APP_DIR, timeout=120,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
                if proc.returncode != 0 or not lines:
                    err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or f"退出码 {proc.returncode}"
                    _show_message(self, "错误", f"DirectML 推理失败:\n{err}", "error")
                    return None
                data = _json.loads(lines[-1])
                if data.get("error"):
                    _show_message(self, "错误", f"DirectML 推理失败:\n{data['error']}", "error")
                    return None
                return data.get("banner_data")
            finally:
                try:
                    os.remove(tmp_img)
                except OSError:
                    pass
        except Exception as e:
            import traceback
            _show_message(self, "错误", f"DirectML 推理失败:\n{str(e)}\n\n{traceback.format_exc()}", "error")
            return None


def main():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    # 全局异常钩子：未捕获的异常自动写入日志
    def _global_excepthook(exc_type, exc_value, exc_tb):
        if _crash_reported:
            return  # 早期崩溃处理器已报告，不重复弹窗
        import traceback as _tb
        tb_str = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        try:
            report_error("程序异常", f"旗帜印染逆向器发生未处理的错误:\n\n{tb_str}", "逆向器")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _global_excepthook

    # 软件渲染（必须在 QApplication 创建前设置）：保证 agent 截图稳定可识别
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", app.font().pointSize()))

    # 统一弹窗图标：QMessageBox 系统弹窗图标 64px（250% 放大规律，与 error_reporter 等自定义弹窗一致）
    from PyQt5.QtWidgets import QProxyStyle, QStyle as _QStyle
    class _MsgBoxIconStyle(QProxyStyle):
        def pixelMetric(self, metric, option=None, widget=None):
            if metric == _QStyle.PM_MessageBoxIconSize:
                return 64
            return super().pixelMetric(metric, option, widget)
    app.setStyle(_MsgBoxIconStyle(app.style()))

    is_restart = "--restart" in sys.argv

    # 互斥检查：训练器/导入器运行中则阻拦（重启时也检查）
    if _check_trainer_importer_running():
        # 提醒性质：用信息提醒窗口（非报错），与 start.pyw 的互斥提醒风格一致
        MessageBox.information(None, "提示",
            "旗帜训练工具（训练器/导入器）正在运行\n请先关闭后再启动旗帜印染逆向器")
        # 用 os._exit 跳过 Qt 清理，避免 QApplication 未进入 exec_ 时退出导致的闪退
        os._exit(0)

    # 单实例检查（重启时跳过，直接创建锁文件，与训练器/导入器逻辑一致）
    if not is_restart:
        lock_file = _acquire_instance_slot()
        if lock_file is None:
            # 单实例阻拦：提醒性质，用信息提醒窗口（非报错）
            MessageBox.information(None, "提示",
                "旗帜印染逆向器已经在运行，请先关闭已有的窗口。")
            os._exit(0)
    else:
        lock_file = _create_instance_lock()

    # 应用全局调色板（让原生对话框/文件选择器跟随深浅色主题）
    _startup_theme = resolve_theme(_get_theme_from_config())
    apply_theme(app, _startup_theme)

    window = BannerRecognizer()
    window._lock_file = lock_file
    window.show()

    # 启动时自动加载默认模型（由设置控制，静默模式：没模型不弹窗）
    if getattr(window, "_auto_load_default", False):
        QTimer.singleShot(100, lambda: window._auto_load_model(silent=True))

    exit_code = app.exec_()
    _remove_instance_lock(lock_file)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
