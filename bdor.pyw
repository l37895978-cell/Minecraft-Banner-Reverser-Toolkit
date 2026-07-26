import os
import sys
import json
import time
import ctypes
import glob
import tempfile

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
import torchvision.transforms as transforms
import numpy as np
import cv2
from PIL import Image

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QMessageBox, QGroupBox,
    QGridLayout, QComboBox, QScrollArea, QSizePolicy, QAction, QTextBrowser,
    QDialog, QTextEdit
)
from PyQt5.QtGui import QPixmap, QImage, QFont, QIcon
from PyQt5.QtCore import Qt, QSize, QBuffer, QTimer
from io import BytesIO

from utils.banner_utils import color_name, type, type_zh, generate_banner_image
from utils.settings_manager import apply_theme, apply_dwm_dark_mode, resolve_theme, report_error


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


def _check_trainer_importer_running():
    """检查训练器/导入器是否在运行（互斥阻拦）。"""
    lock_files = glob.glob(os.path.join(tempfile.gettempdir(), _TRAINER_LOCK_PATTERN))
    for lf in lock_files:
        try:
            with open(lf, "r") as f:
                pid = int(f.read().strip())
            if _is_pid_alive(pid):
                return True
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


class ThemedMessageBox(QDialog):
    """适配分辨率、深浅色模式、长文本滚动的消息对话框。

    msg_type: "error" / "warning" / "info"
    长文本（超过 _SCROLL_THRESHOLD 字符）自动启用可滚动文本区域。
    窗口固定大小，禁止缩放。
    """

    _SCROLL_THRESHOLD = 120

    def __init__(self, parent, title, text, msg_type="warning"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._msg_type = msg_type

        # 从父窗口获取缩放和主题
        self._scale = getattr(parent, "_scale", 1.0) if parent else 1.0
        self._theme = getattr(parent, "_theme", "light") if parent else "light"
        if self._scale <= 0:
            self._scale = 1.0

        s = self._scale
        base_fs = max(int(14 * s), 13)
        btn_fs = max(int(14 * s), 14)
        title_fs = max(int(16 * s), 15)
        is_dark = (self._theme == "dark")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(20 * s), int(18 * s), int(20 * s), int(14 * s))
        layout.setSpacing(int(10 * s))

        # 顶部：图标 + 标题行
        header_row = QHBoxLayout()
        header_row.setSpacing(int(10 * s))

        icon_label = QLabel()
        icon_size = int(32 * s)
        icons = {
            "error": ("✕", "#f44336"),
            "warning": ("⚠", "#ff9800"),
            "info": ("ℹ", "#1a73e8"),
        }
        icon_char, icon_color = icons.get(msg_type, icons["warning"])
        icon_label.setText(f"<span style='font-size:{int(28*s)}px; color:{icon_color};'>{icon_char}</span>")
        icon_label.setTextFormat(Qt.RichText)
        icon_label.setFixedSize(icon_size, icon_size)
        icon_label.setAlignment(Qt.AlignCenter)
        header_row.addWidget(icon_label, 0, Qt.AlignTop)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: {title_fs}px; font-weight: bold;")
        header_row.addWidget(title_label, 1, Qt.AlignVCenter)
        layout.addLayout(header_row)

        # 文本区域
        if len(text) > self._SCROLL_THRESHOLD:
            # 长文本：用 QTextEdit + 滚动
            self._text_edit = QTextEdit()
            self._text_edit.setReadOnly(True)
            self._text_edit.setPlainText(text)
            layout.addWidget(self._text_edit, 1)
            # 固定尺寸：宽 560，高 380（按缩放）
            dlg_w = int(560 * s)
            dlg_h = int(380 * s)
        else:
            # 短文本：直接用 QLabel
            self._text_edit = None
            text_label = QLabel(text)
            text_label.setWordWrap(True)
            text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(text_label, 1)
            # 固定尺寸：宽 460，高按内容自适应
            dlg_w = int(460 * s)
            dlg_h = 0  # 稍后用 sizeHint 计算

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setMinimumHeight(int(34 * s))
        ok_btn.setMinimumWidth(int(96 * s))
        ok_btn.setCursor(Qt.PointingHandCursor)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        self._apply_style(is_dark, s, base_fs, btn_fs)

        # 固定窗口大小（禁止缩放）
        if dlg_h == 0:
            dlg_h = self.sizeHint().height()
        self.setFixedSize(dlg_w, dlg_h)

    def _apply_style(self, is_dark, s, base_fs, btn_fs):
        if is_dark:
            bg = "#1e1e1e"
            fg = "#e0e0e0"
            border = "#3c3c3c"
            primary_bg = "#1a73e8"
            primary_hover = "#1557b0"
            edit_bg = "#2a2a2a"
            scroll_handle = "#555555"
            scroll_hover = "#666666"
        else:
            bg = "#ffffff"
            fg = "#1a1a1a"
            border = "#cccccc"
            primary_bg = "#1a73e8"
            primary_hover = "#1557b0"
            edit_bg = "#f9f9f9"
            scroll_handle = "#c0c0c0"
            scroll_hover = "#999999"

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; color: {fg}; }}
            QLabel {{ color: {fg}; background: transparent; }}
            QTextEdit {{
                background-color: {edit_bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: {max(int(8*s),6)}px;
                font-size: {base_fs}px;
            }}
            QPushButton {{
                background-color: {primary_bg};
                color: white;
                border: none;
                border-radius: 6px;
                padding: {max(int(8*s),6)}px {max(int(28*s),20)}px;
                font-size: {btn_fs}px;
            }}
            QPushButton:hover {{ background-color: {primary_hover}; }}
            /* 现代化滚动条 */
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 10px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {scroll_handle};
                border-radius: 5px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {scroll_hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
                border: none;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)


def _show_message(parent, title, text, msg_type="warning"):
    """显示适配分辨率/深浅色/滚轮的消息对话框（替代 QMessageBox）。

    错误类型（msg_type="error"）统一走 report_error → error_reporter.pyw，
    不再弹出独立的 ThemedMessageBox，与训练器/导入器的错误处理保持一致。
    """
    if msg_type == "error":
        try:
            report_error(title, text, "逆向器")
        except Exception:
            pass
        return  # 错误统一由 error_reporter.pyw 显示（含导出日志功能）
    dlg = ThemedMessageBox(parent, title, text, msg_type)
    dlg.exec_()


class BannerRecognizer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("旗帜印染逆向器")
        self.model = None
        self.device = 'cpu'
        self.current_image = None
        self.current_result = None
        self._force_quit = False
        self._settings_process = None

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
            self._auto_load_model = _cfg.get("reverser_auto_load_model", False)
            self._default_device = _cfg.get("reverser_default_device", "auto")
        except Exception:
            self._auto_load_model = False
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
        base_w = max(int(self._sw * 0.6), 1000)
        base_h = max(int(self._sh * 0.82), 720)
        self._min_w = max(int(self._sw * 0.45), 880)
        self._min_h = max(int(self._sh * 0.62), 600)
        self.setMinimumSize(self._min_w, self._min_h)
        self.resize(base_w, base_h)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(int(12 * s))

        base_fs = max(int(16 * s), 14)
        btn_fs = max(int(16 * s), 14)
        title_fs = max(int(18 * s), 16)

        # 模型加载组
        model_group = QGroupBox("模型加载")
        model_layout = QHBoxLayout(model_group)

        self.model_label = QLabel("未加载模型")
        self.model_label.setStyleSheet(f"font-size: {base_fs}px;")
        model_layout.addWidget(self.model_label, 1)

        self.device_combo = QComboBox()
        self.device_combo.addItem("CPU")
        has_cuda = torch.cuda.is_available()
        if has_cuda:
            self.device_combo.addItem("CUDA (GPU)")
        # 根据 _default_device 设置默认选择
        if self._default_device == "cpu":
            self.device_combo.setCurrentIndex(0)
        elif self._default_device == "cuda" and has_cuda:
            self.device_combo.setCurrentIndex(1)
        elif self._default_device == "auto" and has_cuda:
            self.device_combo.setCurrentIndex(1)
        model_layout.addWidget(self.device_combo)

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
        base_fs = max(int(16 * s), 14)
        btn_fs = max(int(16 * s), 14)

        if is_dark:
            bg = "#1e1e1e"
            bg_alt = "#2a2a2a"
            fg = "#e0e0e0"
            group_border = "#3c3c3c"
            input_bg = "#2a2a2a"
            btn_bg = "#3a3a3a"
            btn_hover = "#4a4a4a"
            btn_pressed = "#2e2e2e"
            btn_disabled_bg = "#333333"
            btn_disabled_fg = "#666666"
            primary_bg = "#1a73e8"
            primary_hover = "#1557b0"
            border_dash = "#555555"
            menubar_sel = "#1a73e8"
            scroll_handle = "#555555"
            scroll_hover = "#666666"
            scroll_pressed = "#777777"
            tooltip_bg = "#2d2d30"
            tooltip_border = "#555555"
            tooltip_fg = "#e0e0e0"
            combo_arrow = "#cccccc"
        else:
            bg = "#ffffff"
            bg_alt = "#f5f5f5"
            fg = "#1a1a1a"
            group_border = "#cccccc"
            input_bg = "#ffffff"
            btn_bg = "#f0f0f0"
            btn_hover = "#e0e0e0"
            btn_pressed = "#d0d0d0"
            btn_disabled_bg = "#f5f5f5"
            btn_disabled_fg = "#aaaaaa"
            primary_bg = "#4CAF50"
            primary_hover = "#388E3C"
            border_dash = "#aaaaaa"
            menubar_sel = "#e0e0e0"
            scroll_handle = "#c0c0c0"
            scroll_hover = "#a0a0a0"
            scroll_pressed = "#909090"
            tooltip_bg = "#ffffff"
            tooltip_border = "#cccccc"
            tooltip_fg = "#1a1a1a"
            combo_arrow = "#666666"

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
            QPushButton {{
                background-color: {btn_bg};
                color: {fg};
                border: 1px solid {group_border};
                border-radius: 4px;
                padding: {max(int(6*s),5)}px {max(int(16*s),12)}px;
                font-size: {btn_fs}px;
                min-height: {max(int(22*s),18)}px;
            }}
            QPushButton:hover {{ background-color: {btn_hover}; border-color: {btn_pressed}; }}
            QPushButton:pressed {{ background-color: {btn_pressed}; }}
            QPushButton:disabled {{ background-color: {btn_disabled_bg}; color: {btn_disabled_fg}; border-color: {group_border}; }}
            QPushButton#primaryButton {{
                background-color: {primary_bg};
                color: white;
                border: none;
                font-size: {max(int(18*s),16)}px;
                padding: {max(int(10*s),8)}px {max(int(24*s),20)}px;
            }}
            QPushButton#primaryButton:hover {{ background-color: {primary_hover}; }}
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
            QMenuBar {{ font-size: {btn_fs}px; background-color: {bg}; color: {fg}; }}
            QMenuBar::item:selected {{ background-color: {menubar_sel}; }}
            QMenuBar::item:disabled {{ color: {btn_disabled_fg}; }}
            QMenu {{
                font-size: {base_fs}px;
                background-color: {bg};
                color: {fg};
                border: 1px solid {group_border};
            }}
            QMenu::item {{ padding: {max(int(6*s),5)}px {max(int(24*s),20)}px; }}
            QMenu::item:selected {{ background-color: {menubar_sel}; }}
            QMenu::item:disabled {{ color: {btn_disabled_fg}; }}
            QMenu::separator {{ height: 1px; background-color: {group_border}; margin: {max(int(4*s),3)}px {max(int(8*s),6)}px; }}
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
        """启动独立设置程序（子进程），与训练器/导入器保持一致的打开方式。"""
        import subprocess

        # 单例：已有进程在跑则不重复打开
        existing = getattr(self, "_settings_process", None)
        if existing is not None and existing.poll() is None:
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

    def _menu_show_help(self):
        """打开使用说明窗口（子进程），与训练器/导入器保持一致。"""
        import subprocess
        app_dir = os.path.dirname(os.path.abspath(__file__))
        help_script = os.path.join(app_dir, "help.pyw")
        if os.path.exists(help_script):
            try:
                subprocess.Popen([sys.executable, help_script, "--scale", str(self._scale)])
            except Exception:
                pass

    def _menu_about(self):
        _show_message(self, "关于", "旗帜印染逆向器 v0.5 beta1\n\n基于Vision Transformer的旗帜图片逆向识别工具。", "info")

    def _clear_image(self):
        self.current_image = None
        self.input_label.clear()
        self.input_label.setText("请导入旗帜图片")

    def _clear_result(self):
        self.current_result = None
        self.result_preview.clear()
        self.result_preview.setText("逆向结果预览")
        self.result_text.setText("")

    def _get_device(self):
        idx = self.device_combo.currentIndex()
        if idx == 1 and torch.cuda.is_available():
            return 'cuda'
        return 'cpu'

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

    def _load_model(self):
        model_dir = self._get_model_dir()
        model_path, _ = QFileDialog.getOpenFileName(
            self, "选择模型文件", model_dir,
            "模型文件 (*.pth *.pt);;所有文件 (*)"
        )
        if not model_path:
            return
        self._do_load_model(model_path)

    def _auto_load_model(self):
        model_path = self._find_latest_model()
        if model_path is None:
            model_dir = self._get_model_dir()
            _show_message(self, "警告", f"默认模型目录中没有模型文件:\n{model_dir}\n请先训练模型或手动选择模型文件。", "warning")
            return
        self._do_load_model(model_path)

    def _do_load_model(self, model_path):
        try:
            from models.structures.vit_model import ViT
            self.device = self._get_device()
            checkpoint = torch.load(model_path, map_location=self.device, weights_only=False)

            # 读取架构信息，用正确架构创建 ViT（防止架构不匹配）
            if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint:
                arch = checkpoint.get('model_arch', 'vit_b_16')
                self.model = ViT(model_arch=arch)
                self.model.load_state_dict(checkpoint['model_state_dict'])
            else:
                # 旧格式：直接是 state_dict，使用默认架构
                self.model = ViT()
                self.model.load_state_dict(checkpoint)

            self.model.to(self.device)
            self.model.eval()
            self.model_label.setText(f"已加载: {os.path.basename(model_path)} ({self.device})")
            is_dark = (self._theme == "dark")
            ok_color = "#4fc3f7" if is_dark else "#4CAF50"
            self.model_label.setStyleSheet(f"font-size: {max(int(16*self._scale),14)}px; color: {ok_color};")
            _show_message(self, "成功", f"模型加载成功\n设备: {self.device}", "info")
        except Exception as e:
            import traceback
            err_detail = f"模型加载失败:\n{str(e)}\n\n--- 详细错误 ---\n{traceback.format_exc()}"
            _show_message(self, "错误", err_detail, "error")
            self.model = None
            self.model_label.setText("模型加载失败")
            is_dark = (self._theme == "dark")
            err_color = "#f44336" if is_dark else "#f44336"
            self.model_label.setStyleSheet(f"font-size: {max(int(16*self._scale),14)}px; color: {err_color};")

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
        if self.model is None:
            _show_message(self, "警告", "请先加载模型", "warning")
            return
        if self.current_image is None:
            _show_message(self, "警告", "请先导入旗帜图片", "warning")
            return

        try:
            self.device = self._get_device()
            self.model.to(self.device)

            img_rgb = cv2.cvtColor(self.current_image, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)

            transform = transforms.Compose([
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
            ])

            input_tensor = transform(pil_img).unsqueeze(0).to(self.device)

            with torch.no_grad():
                bg_pred, pattern_preds = self.model(input_tensor)

            bg_color_idx = torch.argmax(bg_pred, dim=1).item()

            patterns = []
            for i in range(8):
                p_type_idx = torch.argmax(pattern_preds[2*i], dim=1).item()
                p_color_idx = torch.argmax(pattern_preds[2*i+1], dim=1).item()
                if p_type_idx > 0:
                    patterns.append((p_type_idx, p_color_idx))

            banner_data = [bg_color_idx]
            for p_type, p_color in patterns:
                banner_data.extend([p_type, p_color])

            self.current_result = banner_data

            result_img = generate_banner_image(banner_data, size=(200, 400))
            self._set_image_to_label(self.result_preview, result_img)

            seq_parts = []
            bg_name = color_name[bg_color_idx] if bg_color_idx < len(color_name) else f"?{bg_color_idx}"
            seq_parts.append(bg_name)

            for p_type, p_color in patterns:
                t_name = type[p_type] if p_type < len(type) else f"?{p_type}"
                c_name = color_name[p_color] if p_color < len(color_name) else f"?{p_color}"
                seq_parts.append(f"{t_name}_{c_name}")

            seq_str = " > ".join(seq_parts)

            detail_lines = [f"序列: {seq_str}", f"数据: {banner_data}", ""]
            detail_lines.append(f"背景: {bg_name}")
            if patterns:
                for idx, (p_type, p_color) in enumerate(patterns):
                    t_zh = type_zh[p_type] if p_type < len(type_zh) else f"?{p_type}"
                    c_zh = color_name[p_color] if p_color < len(color_name) else f"?{p_color}"
                    detail_lines.append(f"图案{idx+1}: {t_zh} / {c_zh}")
            else:
                detail_lines.append("无图案")

            self.result_text.setText("\n".join(detail_lines))

        except Exception as e:
            import traceback
            err_detail = f"逆向失败:\n{str(e)}\n\n--- 详细错误 ---\n{traceback.format_exc()}"
            _show_message(self, "错误", err_detail, "error")


def main():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    # 全局异常钩子：未捕获的异常自动写入日志
    def _global_excepthook(exc_type, exc_value, exc_tb):
        import traceback as _tb
        tb_str = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        try:
            report_error("程序异常", f"旗帜印染逆向器发生未处理的错误:\n\n{tb_str}", "逆向器")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _global_excepthook

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", app.font().pointSize()))

    is_restart = "--restart" in sys.argv

    # 互斥检查：训练器/导入器运行中则阻拦（重启时也检查）
    if _check_trainer_importer_running():
        QMessageBox.critical(None, "启动限制",
            "旗帜训练工具（训练器/导入器）正在运行\n请先关闭后再启动旗帜印染逆向器")
        sys.exit(0)

    # 单实例检查（重启时跳过，直接创建锁文件，与训练器/导入器逻辑一致）
    if not is_restart:
        lock_file = _acquire_instance_slot()
        if lock_file is None:
            # 单实例阻拦时无父窗口，用原生 QMessageBox（此时还没有主窗口主题）
            QMessageBox.critical(None, "启动限制",
                "旗帜印染逆向器已在运行，请勿重复启动\n如需启动新实例，请先关闭已运行的实例")
            sys.exit(0)
    else:
        lock_file = _create_instance_lock()

    # 应用全局调色板（让原生对话框/文件选择器跟随深浅色主题）
    _startup_theme = resolve_theme(_get_theme_from_config())
    apply_theme(app, _startup_theme)

    window = BannerRecognizer()
    window._lock_file = lock_file
    window.show()

    # 启动时自动加载默认模型（由设置控制）
    if getattr(window, "_auto_load_model", False):
        QTimer.singleShot(100, window._auto_load_model)

    exit_code = app.exec_()
    _remove_instance_lock(lock_file)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
