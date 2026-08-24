"""设置对话框模块。

既可作为模块被其他程序 import（SettingsDialog 类），
也可作为独立程序运行：python utils/settings_dialog.py --caller trainer --scale 2.5

独立运行退出码：
  0   = 用户取消
  1   = 用户确定保存（无需重启）
  100 = 用户确定保存且需要重启父进程
"""
import os
import sys
import ctypes
import tempfile

# 软件渲染：强制 Qt 走 CPU 软件渲染，兼容自动化 agent（截图/OCR/坐标点击）
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
# pythonw.exe 启动时 stdout/stderr 为 None，必须最早修复
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# 早期异常捕获：在 PyQt5 等第三方库导入前生效，捕获导入/启动阶段的致命错误，
# 避免 pythonw 静默崩溃（设置窗口"打不开"却无任何报错，用户无从排查）。
# 崩溃时写入 %TEMP% 日志并尝试调起 error_reporter 展示真实原因。
_SD_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _early_crash_handler(exc_type, exc_value, exc_tb):
    import traceback as _tb_mod
    import subprocess as _sp_mod
    tb_str = "".join(_tb_mod.format_exception(exc_type, exc_value, exc_tb))
    _err = os.path.join(os.environ.get("TEMP", _SD_APP_DIR),
                        f"banner_tool_error_settings_{os.getpid()}.txt")
    try:
        with open(_err, "w", encoding="utf-8") as f:
            f.write(f"设置窗口启动失败:\n\n{tb_str}")
    except Exception:
        pass
    _reporter = os.path.join(_SD_APP_DIR, "scripts", "error_reporter.pyw")
    try:
        _sp_mod.Popen([sys.executable, _reporter, _err, "设置窗口启动失败", "设置"],
                      creationflags=_sp_mod.CREATE_NO_WINDOW | _sp_mod.DETACHED_PROCESS)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _early_crash_handler

# 把项目根目录加入 sys.path，以便独立运行时也能 import utils.xxx
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 与各入口一致的 vendor 引导：安装器用 pip install --target 把依赖装到
# 应用目录 Lib/site-packages（不碰系统 site-packages）。本窗口作为独立子进程
# 启动，必须自行把 vendor 加入 sys.path，否则系统 Python 没有 PyQt5 时会找不到。
_VENDOR_PKGS = os.path.join(_PROJECT_ROOT, "Lib", "site-packages")
if os.path.isdir(_VENDOR_PKGS) and _VENDOR_PKGS not in sys.path:
    sys.path.insert(0, _VENDOR_PKGS)

# Qt 平台插件引导（与 start.pyw 一致）：vendor PyQt5 的 DLL 依赖同目录 plugins，
# 不在 PATH / QT_PLUGIN_PATH 中时 Qt 会报 "could not find Qt platform plugin"。
import site as _site
_qt5_dir = os.path.join(_VENDOR_PKGS, "PyQt5", "Qt5")
if not os.path.isdir(_qt5_dir):
    for _sp in _site.getsitepackages():
        _cand = os.path.join(_sp, "PyQt5", "Qt5")
        if os.path.isdir(_cand) and os.path.isdir(os.path.join(_cand, "plugins", "platforms")):
            _qt5_dir = _cand
            break
if os.path.isdir(_qt5_dir):
    _qt_bin = os.path.join(_qt5_dir, "bin")
    _qt_plugins = os.path.join(_qt5_dir, "plugins")
    if os.path.isdir(_qt_bin) and _qt_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _qt_bin + os.pathsep + os.environ.get("PATH", "")
    if os.path.isdir(_qt_plugins):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(_qt_plugins, "platforms")
        os.environ.setdefault("QT_PLUGIN_PATH", _qt_plugins)

from PyQt5.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QComboBox, QCheckBox, QSlider, QPushButton, QSpinBox,
    QGroupBox, QLineEdit, QFileDialog, QMessageBox, QScrollArea, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt5.QtGui import QFont, QIcon

from utils.settings_manager import SettingsManager, HardwareDetectThread, get_hardware_cache, grade_gpu_memory, grade_system_memory, load_hardware_cache, save_hardware_cache, resolve_theme, apply_dwm_dark_mode, apply_theme, compute_resource_allocation, check_arch_available, build_arch_cache, ARCH_DISPLAY, get_gpu_memory_usage, resolve_app_path


# 退出码约定（独立运行模式）
EXIT_CANCEL = 0      # 用户取消
EXIT_OK = 1          # 确定保存（无需重启）
EXIT_RESTART = 100   # 确定保存且需要重启

# 单实例命令文件路径（用于已运行时接收跳转指令）
_SETTINGS_CMD_FILE = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()), "_banner_settings_cmd")

# caller → 导航列表索引映射
_CALLER_SECTION_MAP = {
    "start": 0,      # 启动器 → 通用
    "trainer": 2,    # 训练器 → 训练器设置
    "importer": 3,   # 导入器 → 导入器设置
    "reverser": 4,   # 识别器 → 识别器设置
}


def main():
    """独立设置程序入口。"""
    import argparse
    import ctypes

    parser = argparse.ArgumentParser()
    parser.add_argument("--caller", default="start", choices=["start", "trainer", "importer", "reverser"])
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args()

    # 单实例限制
    mutex_name = "Global\\BannerToolSettingsSingleInstance"
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    already_exists = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    if already_exists:
        kernel32.CloseHandle(mutex)
        # 已有实例运行：写命令文件通知它恢复+跳转，然后退出
        try:
            with open(_SETTINGS_CMD_FILE, "w", encoding="utf-8") as f:
                f.write(args.caller)
        except Exception:
            pass
        return

    from PyQt5.QtWidgets import QApplication
    # 软件渲染（必须在 QApplication 创建前设置）：保证 agent 截图稳定可识别
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)

    app = QApplication(sys.argv)
    # 设置应用调色板，让原生 QMessageBox/QFileDialog 等跟随主题
    sm = SettingsManager()
    _theme = resolve_theme(sm.get("theme", "light"))
    apply_theme(app, _theme)
    dialog = SettingsDialog(None, args.caller, args.scale)
    apply_dwm_dark_mode(dialog, _theme == "dark")
    exit_code = dialog.exec_()
    kernel32.CloseHandle(mutex)
    # 退出时清理命令文件
    try:
        if os.path.exists(_SETTINGS_CMD_FILE):
            os.remove(_SETTINGS_CMD_FILE)
    except Exception:
        pass
    sys.exit(exit_code)


class _SettingsScrollArea(QScrollArea):
    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self._dialog = dialog

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        bar = self.verticalScrollBar()
        # 仅在滚动到边界时切换节，其余情况直接操作滚动条
        if delta > 0 and bar.value() == 0:
            self._dialog._switch_section_by_direction(-1)
            event.accept()
        elif delta < 0 and bar.value() >= bar.maximum():
            self._dialog._switch_section_by_direction(1)
            event.accept()
        else:
            # 直接操作滚动条，避免 super().wheelEvent 不生效
            step = max(bar.singleStep() * 3, 30)
            bar.setValue(bar.value() - delta // 40 * step // 3)
            event.accept()


class SettingsDialog(QDialog):
    settings_applied = pyqtSignal(dict)
    restart_requested = pyqtSignal()

    RESTART_KEYS = {
        "train_mode", "train_arch", "debug_mode", "model_arch", "dropout", "lora_rank",
        "auto_resource_alloc", "perf_level",
        "gpu_memory", "sys_memory", "mixed_precision", "grad_accum", "num_workers",
        "gpu_temp_protection",
    }

    def __init__(self, parent=None, caller_name="importer", ui_scale=None):
        super().__init__(parent, Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.caller_name = caller_name
        self.sm = SettingsManager()
        self._temp = dict(self.sm.get_all())

        if ui_scale is None:
            ui_scale = 1.0
            if parent is not None:
                if hasattr(parent, "_scale") and parent._scale > 0:
                    ui_scale = parent._scale
                else:
                    try:
                        pf = parent.font()
                        pfs = pf.pointSize()
                        if pfs > 0:
                            ui_scale = pfs / 10.0
                    except Exception:
                        pass

        self._scale = max(ui_scale, 1.0)
        self._base_fs = max(int(13 * self._scale), 13)
        self._btn_fs = max(int(14 * self._scale), 14)

        self.setWindowTitle("设置")
        # 窗口图标（独立运行时也用 mbtlx.ico）
        _icon_path = os.path.join(_PROJECT_ROOT, "images", "icons", "mbtlx.ico")
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))
        w = int(720 * self._scale)
        h = int(560 * self._scale)
        self.setFixedSize(w, h)

        self._sections = []
        self._scroll_locked = False
        self._row_labels = []
        self._header_labels = []
        self._restart_hints = []
        self._tip_labels = []
        self._hw_detecting = False
        self._loading = True  # 初始化期间跳过耗时实时检测

        self._init_ui()
        # 优先从磁盘加载硬件缓存（由训练器/导入器启动时写入），避免设置窗口重复检测
        load_hardware_cache()
        self._load_settings()
        # 用加载后UI实际状态更新_temp基准，避免控件联动改变值后changed误报
        self._temp = self._collect_settings()
        self._apply_theme_to_dialog()
        # 初始化完成，直接执行检测（避免窗口显示后额外加载）
        self._loading = False
        self._update_auto_alloc_display()
        # 如果缓存中 GPU 信息为"未检测到"，自动触发重新检测
        _hw = get_hardware_cache()
        if _hw.get("gpu_name", "未检测到") == "未检测到" or _hw.get("gpu_total_gb", 0) == 0:
            QTimer.singleShot(100, self._on_recheck_hardware)

    def _init_ui(self):
        from PyQt5.QtWidgets import QHBoxLayout as QH

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QH()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        nav_w = int(180 * self._scale)
        self._nav_list = QListWidget()
        self._nav_list.setFixedWidth(nav_w)
        self._nav_list.setStyleSheet(f"""
            QListWidget {{
                background: #f5f5f5;
                border: none;
                border-right: 1px solid #e0e0e0;
                padding-top: 8px;
                font-size: {self._btn_fs}px;
            }}
            QListWidget::item {{
                padding: {int(self._btn_fs * 0.7)}px 20px;
                border: none;
            }}
            QListWidget::item:selected {{
                background: #e8f0fe;
                color: #1a73e8;
            }}
            QListWidget::item:hover {{
                background: #f0f0f0;
            }}
        """)

        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background: #fff;")
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(18, 12, 36, 8)
        self._content_layout.setSpacing(10)

        self._scroll = _SettingsScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._scroll.setWidget(self._content_widget)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: #fff; }")
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

        body.addWidget(self._nav_list)
        body.addWidget(self._scroll, 1)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 8, 16, 12)
        bottom_layout.setSpacing(4)

        btn_row = QH()
        btn_row.setSpacing(10)
        btn_row.addStretch()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_cancel.setMinimumHeight(int(self._base_fs * 1.3))
        self.btn_cancel.setMinimumWidth(int(90 * self._scale))
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setObjectName("btn_ok")
        self.btn_ok.clicked.connect(self._on_ok)
        self.btn_ok.setMinimumHeight(int(self._base_fs * 1.3))
        self.btn_ok.setMinimumWidth(int(90 * self._scale))
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)
        bottom_layout.addLayout(btn_row)

        outer.addWidget(bottom)

        self._group_style = f"""
            QGroupBox {{
                font-weight: bold;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 18px;
                font-size: {self._btn_fs}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #333;
            }}
        """
        self._label_style = f"font-size: {self._base_fs}px; color: #333;"
        self._label_style_disabled = f"font-size: {self._base_fs}px; color: #999;"
        self._val_style = f"font-size: {self._base_fs}px; background: #fff; color: #333; border: 1px solid #d0d0d0; border-radius: 6px;"
        self._val_style_disabled = f"font-size: {self._base_fs}px; background: #e8e8e8; color: #999; border: 1px solid #ccc; border-radius: 6px;"
        self._combo_style = f"font-size: {self._base_fs}px; background: #fff; color: #333; border: 1px solid #d0d0d0; border-radius: 6px;"
        self._combo_style_disabled = f"font-size: {self._base_fs}px; background: #e8e8e8; color: #999; border: 1px solid #ccc; border-radius: 6px;"
        label_min_w = int(130 * self._scale)
        self._label_min_w = label_min_w
        self._desc_style = f"font-size: {int(self._base_fs * 0.82)}px; color: #999; padding-left: {label_min_w + 12}px;"

        self._build_pages()
        self._nav_list.currentRowChanged.connect(self._scroll_to_section)

        # 根据 caller 跳转到对应 section
        init_idx = _CALLER_SECTION_MAP.get(self.caller_name, 0)
        self._nav_list.setCurrentRow(init_idx)

        # 启动命令文件轮询（接收来自其他进程的跳转/恢复指令）
        self._cmd_timer = QTimer(self)
        self._cmd_timer.timeout.connect(self._poll_settings_cmd)
        self._cmd_timer.start(500)  # 每500ms检查一次

        # 定期更新硬件信息（CPU/内存/GPU使用率）
        self._hw_update_timer = QTimer(self)
        self._hw_update_timer.timeout.connect(self._update_auto_alloc_display)
        self._hw_update_timer.start(2000)  # 每2秒更新一次

        self.setStyleSheet(f"""
            QLineEdit {{
                font-size: {self._base_fs}px;
                padding: 1px {int(10 * self._scale)}px;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                background: #fff;
            }}
            QLineEdit:hover {{
                border-color: #1a73e8;
            }}
            QLineEdit:focus {{
                border-color: #1a73e8;
            }}
            QComboBox {{
                font-size: {self._base_fs}px;
                padding: 1px {int(26 * self._scale)}px 1px {int(8 * self._scale)}px;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                background: #fff;
                color: #333;
            }}
            QComboBox:hover {{
                border-color: #1a73e8;
            }}
            QComboBox:focus {{
                border-color: #1a73e8;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: {int(22 * self._scale)}px;
                border: none;
            }}
            QComboBox QAbstractItemView {{
                font-size: {self._base_fs}px;
                selection-background-color: #e8f0fe;
                selection-color: #1a73e8;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                padding: 4px;
                outline: none;
            }}
            QCheckBox {{
                font-size: {self._base_fs}px;
                spacing: 6px;
            }}
            QLabel {{
                font-size: {self._base_fs}px;
            }}
            QSlider::groove:horizontal {{
                height: 4px;
                background: #e0e0e0;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
                background: #1a73e8;
            }}
            QSpinBox {{
                font-size: {self._base_fs}px;
                padding: 1px {int(10 * self._scale)}px;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                background: #fff;
            }}
            QSpinBox:hover {{
                border-color: #1a73e8;
            }}
            QSpinBox:focus {{
                border-color: #1a73e8;
            }}
        """)

    def _add_section(self, title):
        item = QListWidgetItem(f"  {title}")
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._nav_list.addItem(item)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 18)
        layout.setSpacing(12)

        header = QLabel(title)
        header.setStyleSheet(f"font-size: {int(self._btn_fs * 1.2)}px; font-weight: bold; color: #1a1a1a; padding: 4px 0;")
        self._header_labels.append(header)
        layout.addWidget(header)

        self._content_layout.addWidget(container)
        self._sections.append({"title": title, "item": item, "widget": container, "layout": layout})
        return layout

    def _add_group(self, layout, title):
        group = QGroupBox(title)
        group.setStyleSheet(self._group_style)
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(12)
        group_layout.setContentsMargins(12, 16, 12, 12)
        layout.addWidget(group)
        return group_layout

    def _add_restart_hint(self, layout):
        # start 单独打开时设置直接保存生效，不显示"需要重启生效"提示
        if self.caller_name == "start":
            return
        hint = QLabel("   需要重启生效")
        hint.setStyleSheet(f"font-size: {int(self._base_fs * 0.82)}px; color: #e67700; padding: 4px 0 0 0;")
        self._restart_hints.append(hint)
        layout.addWidget(hint)

    def _add_row(self, layout, label, widget):
        from PyQt5.QtWidgets import QHBoxLayout as QH
        row = QH()
        row.setSpacing(16)
        lab = QLabel(label)
        lab.setMinimumWidth(self._label_min_w)
        lab.setStyleSheet(self._label_style)
        self._row_labels.append(lab)
        row.addWidget(lab)
        row.addWidget(widget, 1)
        layout.addLayout(row)
        return lab

    def _bind_slider_input(self, slider, edit, unit, step):
        """双向绑定 Slider 和 QLineEdit：拖动滑块更新输入框，输入数值更新滑块。

        Args:
            slider: QSlider 控件
            edit: QLineEdit 控件
            unit: 显示单位（如 "GB"、"%"、""）
            step: 滑块步长，输入值会自动对齐到此步长
        """
        # 滑块 → 输入框
        def _on_slider_changed(v):
            edit.blockSignals(True)
            edit.setText(f"{v}{unit}")
            edit.blockSignals(False)
        slider.valueChanged.connect(_on_slider_changed)
        # 输入框 → 滑块（失焦或回车时触发）
        def _on_edit_done():
            text = edit.text().replace(unit, "").strip()
            try:
                val = int(text)
            except ValueError:
                # 回退到滑块当前值
                edit.setText(f"{slider.value()}{unit}")
                return
            # 范围校验 + 步长对齐
            val = max(slider.minimum(), min(val, slider.maximum()))
            if step > 1:
                val = round(val / step) * step
                val = max(slider.minimum(), min(val, slider.maximum()))
            slider.setValue(val)
            edit.setText(f"{val}{unit}")
        edit.editingFinished.connect(_on_edit_done)

    _SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024 * 1024, "GB": 1024 * 1024 * 1024}

    def _parse_size(self, text):
        """解析单个大小字符串（如 '200KB'）返回字节数，失败返回 None。"""
        text = text.strip().upper()
        for unit in ("GB", "MB", "KB", "B"):
            if text.endswith(unit):
                num_str = text[:-len(unit)].strip()
                try:
                    return int(float(num_str) * self._SIZE_UNITS[unit])
                except ValueError:
                    return None
        # 无单位，默认 KB
        try:
            return int(float(text) * 1024)
        except ValueError:
            return None

    def _parse_size_range(self, text):
        """解析范围字符串（如 '200KB~5MB'），返回 (min_kb, max_mb)。

        支持分隔符: ~ - 到
        失败时回退到默认 200KB~5MB。
        """
        text = text.strip()
        for sep in ("~", "-", "到", " TO ", " to "):
            if sep in text:
                parts = text.split(sep, 1)
                if len(parts) == 2:
                    min_bytes = self._parse_size(parts[0])
                    max_bytes = self._parse_size(parts[1])
                    if min_bytes and max_bytes and min_bytes < max_bytes:
                        return (max(1, round(min_bytes / 1024)),
                                max(1, round(max_bytes / (1024 * 1024))))
        return (200, 5)  # 默认值

    def _format_size_range(self, min_kb, max_mb):
        """将 (min_kb, max_mb) 格式化为显示字符串。"""
        min_bytes = min_kb * 1024
        max_bytes = max_mb * 1024 * 1024

        def _fmt(b):
            if b >= 1024 * 1024 * 1024:
                return f"{round(b / (1024 * 1024 * 1024))}GB"
            if b >= 1024 * 1024:
                return f"{round(b / (1024 * 1024))}MB"
            return f"{round(b / 1024)}KB"
        return f"{_fmt(min_bytes)}~{_fmt(max_bytes)}"

    def _validate_image_size(self):
        """校验图片大小输入，无效时回退到上次有效值并格式化显示。"""
        text = self.le_image_size.text().strip()
        min_kb, max_mb = self._parse_size_range(text)
        # 检查是否解析成功（非默认回退值 或 文本本就是默认值）
        # 简单策略：总是格式化回写，确保显示统一
        self.le_image_size.setText(self._format_size_range(min_kb, max_mb))

    def _build_pages(self):
        from PyQt5.QtWidgets import QHBoxLayout as QH

        def row(layout, label, widget):
            return self._add_row(layout, label, widget)

        # ── 1. 通用 ──
        p = self._add_section("通用")
        g = self._add_group(p, "外观")
        self.cb_theme = QComboBox()
        self.cb_theme.addItems(["浅色", "深色", "跟随系统"])
        row(g, "主题模式", self.cb_theme)

        g_snap = self._add_group(p, "吸附")
        self.chk_snap_grid = QCheckBox("开启")
        row(g_snap, "网格吸附", self.chk_snap_grid)
        snap_row = QH()
        snap_row.setSpacing(12)
        self.sl_snap = QSlider(Qt.Horizontal)
        self.sl_snap.setMinimum(1)
        self.sl_snap.setMaximum(50)
        self.sl_snap.setSingleStep(1)
        self.ed_snap_val = QLineEdit()
        self.ed_snap_val.setFixedWidth(int(60 * self._scale))
        self.ed_snap_val.setAlignment(Qt.AlignCenter)
        # 滑块 → 输入框
        self.sl_snap.valueChanged.connect(lambda v: self.ed_snap_val.setText(str(v)))
        # 输入框 → 滑块（失焦或回车时校验）
        def _on_snap_edit():
            try:
                v = int(self.ed_snap_val.text().replace("px", "").strip())
                v = max(1, min(50, v))
                self.sl_snap.blockSignals(True)
                self.sl_snap.setValue(v)
                self.sl_snap.blockSignals(False)
                self.ed_snap_val.setText(str(v))
            except ValueError:
                self.ed_snap_val.setText(str(self.sl_snap.value()))
        self.ed_snap_val.editingFinished.connect(_on_snap_edit)
        snap_row.addWidget(self.sl_snap, 1)
        snap_row.addWidget(self.ed_snap_val)
        snap_widget = QWidget()
        snap_widget.setLayout(snap_row)
        row(g_snap, "吸附阈值", snap_widget)

        g_layout = self._add_group(p, "布局")
        self.chk_autolayout = QCheckBox("开启")
        self.chk_autolayout.stateChanged.connect(self._on_autolayout_changed)
        row(g_layout, "窗口自动布局(snap)", self.chk_autolayout)
        self.chk_minimize = QCheckBox("开启")
        row(g_layout, "退出其他程序", self.chk_minimize)
        self.chk_restore = QCheckBox("开启")
        row(g_layout, "启动时恢复默认工作区布局", self.chk_restore)

        g_sys = self._add_group(p, "自动保存")
        self.cb_autosave = QComboBox()
        self.cb_autosave.addItems(["关闭", "5分钟", "10分钟", "30分钟"])
        row(g_sys, "定时保存间隔", self.cb_autosave)
        # 保存格式已拆分到训练器/导入器各自设置页（按模块分配）

        # ── 2. 训练环境 ──
        p2 = self._add_section("训练环境")

        # 训练架构选择（CUDA / DirectML / CPU）— 位于训练环境最前面
        g_arch_select = self._add_group(p2, "训练架构")
        self.cb_train_arch = QComboBox()
        # 检测库是否已安装（使用 find_spec 快速检查，不导入 torch）
        import importlib.util as _ils
        _has_torch = _ils.find_spec("torch") is not None
        # 回退：检查 Lib/site-packages/torch 目录是否存在（find_spec 可能因路径问题失败）
        if not _has_torch:
            _vendor_torch = os.path.join(resolve_app_path(""), "Lib", "site-packages", "torch")
            _has_torch = os.path.isdir(_vendor_torch)
        # DirectML 在 dml_env (Python 3.10) 中运行，需检测 dml_env 而非主进程
        _dml_python = os.path.join(resolve_app_path(""), "dml_env", "python.exe")
        _has_directml = False
        if os.path.isfile(_dml_python):
            try:
                import subprocess as _sp
                _r = _sp.run([_dml_python, "-E", "-c",
                              "import torch_directml; print(torch_directml.device_count())"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=_sp.CREATE_NO_WINDOW)
                _has_directml = _r.returncode == 0 and _r.stdout.strip().isdigit()
            except Exception:
                pass
        _has_nvidia = False
        _has_igpu = False  # 核显（Intel/AMD）
        try:
            import subprocess as _sp
            _r = _sp.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                         capture_output=True, text=True, timeout=5,
                         creationflags=_sp.CREATE_NO_WINDOW)
            _has_nvidia = _r.returncode == 0 and bool(_r.stdout.strip())
        except Exception:
            pass
        # 检测核显（Intel Iris/UHD/Arc 或 AMD Vega/Radeon）
        try:
            import subprocess as _sp
            _r = _sp.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=10,
                creationflags=_sp.CREATE_NO_WINDOW)
            if _r.returncode == 0:
                for line in _r.stdout.strip().splitlines():
                    gl = line.strip().lower()
                    if any(k in gl for k in ("intel", "iris", "uhd", "arc", "amd", "radeon", "vega")):
                        _has_igpu = True
                        break
        except Exception:
            pass
        _cuda_ok = _has_torch and _has_nvidia
        _cpu_ok = _has_torch  # CPU 模式同样需要主环境 torch（CUDA/CPU 模式共享主环境 Torch）
        # 构建选项列表
        _arch_items = []
        if _cuda_ok:
            _arch_items.append("CUDA（NVIDIA GPU 加速，已就绪）")
        else:
            if _has_nvidia:
                _arch_items.append("CUDA（未就绪：需要主环境安装 CUDA 版 torch）")
            else:
                _arch_items.append("CUDA（未就绪：需要 torch+CUDA 和 NVIDIA 显卡）")
        # DirectML：有核显或独显都可选，未安装库时标注但仍可选
        if _has_directml:
            _arch_items.append("DirectML（实验性·跨厂商 GPU 加速，已就绪）")
        elif _has_igpu:
            _arch_items.append("DirectML（实验性·检测到核显，未安装 torch-directml）")
        else:
            _arch_items.append("DirectML（实验性·未检测到支持的 GPU）")
        if _cpu_ok:
            _arch_items.append("CPU（无 GPU 加速）")
        else:
            _arch_items.append("CPU（未就绪：需要主环境安装 CPU 版 torch）")
        self.cb_train_arch.addItems(_arch_items)
        # 不可用的架构置灰：CUDA/CPU 均要求主环境安装对应版本的 Torch
        if not _cuda_ok:
            self.cb_train_arch.model().item(0).setEnabled(False)
        # DirectML index 1 始终允许用户先选（未安装库时可通过维护模式补装）
        if not _cpu_ok:
            self.cb_train_arch.model().item(2).setEnabled(False)
        row(g_arch_select, "训练架构", self.cb_train_arch)
        self._add_restart_hint(g_arch_select)

        g = self._add_group(p2, "训练模式")
        self.cb_train_mode = QComboBox()
        self.cb_train_mode.addItems(["普通训练", "PEFT微调"])
        row(g, "训练模式", self.cb_train_mode)
        self.chk_debug = QCheckBox("开启")
        row(g, "调试模式", self.chk_debug)

        # GPU 设备模式已合并到"训练架构"（CUDA/DirectML/CPU 三选一统一控制）
        # compute_backend 由 train_arch 自动推导，不再单独暴露

        # DirectML 挂载卡选择（单选，仅 DML 模式可见）
        self.cb_dml_device = QComboBox()
        self._dml_devices = []  # [(name, vendor, is_integrated), ...]
        self._gpu_mode = "cuda_fraction"  # cuda_fraction / dml_reserved / igpu_ratio
        self._gpu_unit = "GB"
        self._refresh_dml_devices()
        self._lbl_dml_device = row(g, "DML 挂载显卡", self.cb_dml_device)
        self._lbl_dml_device.setVisible(False)
        self.cb_dml_device.setVisible(False)
        # 训练架构切换时刷新 DML 设备列表和显存分配 UI
        self.cb_train_arch.currentIndexChanged.connect(self._on_train_arch_changed)
        self.cb_dml_device.currentIndexChanged.connect(self._on_dml_device_changed)

        # 温度保护：75~95°C 滑块 + 输入框
        temp_row = QH()
        temp_row.setSpacing(12)
        self.sl_temp = QSlider(Qt.Horizontal)
        self.sl_temp.setMinimum(75)
        self.sl_temp.setMaximum(95)
        self.sl_temp.setSingleStep(1)
        self.sl_temp.setPageStep(1)
        self.ed_temp_val = QLineEdit("80°C")
        self.ed_temp_val.setFixedWidth(int(64 * self._scale))
        self.ed_temp_val.setAlignment(Qt.AlignCenter)
        self._bind_slider_input(self.sl_temp, self.ed_temp_val, "°C", 1)
        temp_row.addWidget(self.sl_temp, 1)
        temp_row.addWidget(self.ed_temp_val)
        temp_widget = QWidget()
        temp_widget.setLayout(temp_row)
        row(g, "温度保护", temp_widget)
        # 高温风险提醒（≥85°C 时红色小字显示）
        self._lbl_temp_warn = QLabel("⚠ 温度设置过高可能导致显卡降频或硬件损坏，请谨慎设置！")
        self._lbl_temp_warn.setStyleSheet(
            f"font-size: {int(self._base_fs * 0.82)}px; color: #d32f2f; padding-left: {self._label_min_w + 12}px;"
        )
        self._lbl_temp_warn.setWordWrap(True)
        self._lbl_temp_warn.setVisible(False)
        g.addWidget(self._lbl_temp_warn)

        def _on_temp_changed(v):
            self._lbl_temp_warn.setVisible(v >= 85)
        self.sl_temp.valueChanged.connect(_on_temp_changed)

        self._add_restart_hint(g)

        g_arch = self._add_group(p2, "训练架构&内存配置")
        # 自动配置顶层开关（默认开启，关闭后可手动修改各项参数）
        self.chk_auto_alloc = QCheckBox("自动配置（根据设备自动分配显存/内存/工作数）")
        self.chk_auto_alloc.setChecked(True)
        self.chk_auto_alloc.stateChanged.connect(self._on_auto_alloc_changed)
        g_arch.addWidget(self.chk_auto_alloc)

        # 性能挡位 + 重新检测按钮
        perf_widget = QWidget()
        perf_layout = QH(perf_widget)
        perf_layout.setContentsMargins(0, 0, 0, 0)
        perf_layout.setSpacing(8)
        self.cb_perf_level = QComboBox()
        self.cb_perf_level.addItems(["轻量（保守分配，留更多资源给系统）",
                                     "均衡（推荐，自动平衡训练与系统）",
                                     "极致（最大化训练资源）"])
        self.cb_perf_level.setCurrentIndex(1)
        self.cb_perf_level.currentIndexChanged.connect(self._on_perf_level_changed)
        perf_layout.addWidget(self.cb_perf_level, 1)
        self.btn_recheck_hw = QPushButton("重新检测")
        self.btn_recheck_hw.clicked.connect(self._on_recheck_hardware)
        perf_layout.addWidget(self.btn_recheck_hw)
        self._lbl_perf = row(g_arch, "性能挡位", perf_widget)

        # 显卡/内存信息行（始终显示）
        def hidable_row(layout, label_text, content_widget):
            container = QWidget()
            r = QH(container)
            r.setContentsMargins(0, 0, 0, 0)
            r.setSpacing(16)
            lab = QLabel(label_text)
            lab.setMinimumWidth(self._label_min_w)
            lab.setStyleSheet(self._label_style)
            self._row_labels.append(lab)
            r.addWidget(lab)
            r.addWidget(content_widget, 1)
            layout.addWidget(container)
            return container

        self.lbl_gpu_info = QLabel("自动检测中...")
        self.lbl_gpu_info.setWordWrap(True)
        self.lbl_gpu_info.setStyleSheet(f"font-size: {self._base_fs}px;")
        self._gpu_info_row = hidable_row(g_arch, "GPU信息", self.lbl_gpu_info)

        self.lbl_cpu_info = QLabel("自动检测中...")
        self.lbl_cpu_info.setWordWrap(True)
        self.lbl_cpu_info.setStyleSheet(f"font-size: {self._base_fs}px;")
        self._cpu_info_row = hidable_row(g_arch, "CPU信息", self.lbl_cpu_info)

        self.lbl_mem_info = QLabel("自动检测中...")
        self.lbl_mem_info.setWordWrap(True)
        self.lbl_mem_info.setStyleSheet(f"font-size: {self._base_fs}px;")
        self._mem_info_row = hidable_row(g_arch, "内存分配", self.lbl_mem_info)

        self.cb_model = QComboBox()
        self._arch_keys = ["vit_b_16", "vit_l_16", "vit_h_14",
                           "deit_b_16", "deit_s_16", "deit_t_16"]
        for k in self._arch_keys:
            self.cb_model.addItem(ARCH_DISPLAY.get(k, k))
        self.cb_model.setMaximumWidth(int(280 * self._scale))
        self.cb_model.currentIndexChanged.connect(self._on_perf_level_changed)
        row(g_arch, "模型架构", self.cb_model)
        dp_row = QH()
        dp_row.setSpacing(12)
        self.sl_dropout = QSlider(Qt.Horizontal)
        self.sl_dropout.setMinimum(0)
        self.sl_dropout.setMaximum(50)
        self.ed_dropout = QLineEdit("20%")
        self.ed_dropout.setFixedWidth(int(56 * self._scale))
        self._bind_slider_input(self.sl_dropout, self.ed_dropout, "%", 1)
        dp_row.addWidget(self.sl_dropout, 1)
        dp_row.addWidget(self.ed_dropout)
        dp_widget = QWidget()
        dp_widget.setLayout(dp_row)
        row(g_arch, "Dropout率", dp_widget)
        self.cb_lora = QComboBox()
        self.cb_lora.addItems(["4", "8", "16", "32"])
        self._lbl_lora = row(g_arch, "LoRA秩(r)", self.cb_lora)

        gpu_row = QH()
        gpu_row.setSpacing(12)
        self.sl_gpu = QSlider(Qt.Horizontal)
        self.sl_gpu.setMinimum(2)
        self.sl_gpu.setMaximum(32)
        self.sl_gpu.setSingleStep(2)
        self.sl_gpu.setPageStep(2)
        self.ed_gpu_val = QLineEdit("4GB")
        self.ed_gpu_val.setFixedWidth(int(64 * self._scale))
        self._bind_slider_input(self.sl_gpu, self.ed_gpu_val, "GB", 2)
        gpu_row.addWidget(self.sl_gpu, 1)
        gpu_row.addWidget(self.ed_gpu_val)
        gpu_widget = QWidget()
        gpu_widget.setLayout(gpu_row)
        self._lbl_gpu = row(g_arch, "分配显存", gpu_widget)

        # DirectML 模式提示（CUDA/CPU 时隐藏）
        self._lbl_gpu_hint = QLabel("DirectML 无法限制显存上限，已自动启用定期清理机制；此处设置仅用于计算批次大小")
        self._lbl_gpu_hint.setStyleSheet(f"font-size: {int(self._base_fs * 0.82)}px; color: #e67700; padding: 2px 0 0 0;")
        self._lbl_gpu_hint.setWordWrap(True)
        self._lbl_gpu_hint.setVisible(False)
        g_arch.addWidget(self._lbl_gpu_hint)

        mem_row = QH()
        mem_row.setSpacing(12)
        self.sl_mem = QSlider(Qt.Horizontal)
        self.sl_mem.setMinimum(4)
        self.sl_mem.setMaximum(64)
        self.sl_mem.setSingleStep(4)
        self.sl_mem.setPageStep(4)
        self.ed_mem_val = QLineEdit("32GB")
        self.ed_mem_val.setFixedWidth(int(64 * self._scale))
        self._bind_slider_input(self.sl_mem, self.ed_mem_val, "GB", 4)
        mem_row.addWidget(self.sl_mem, 1)
        mem_row.addWidget(self.ed_mem_val)
        mem_widget = QWidget()
        mem_widget.setLayout(mem_row)
        self._lbl_mem = row(g_arch, "分配内存", mem_widget)

        self.cb_mixed = QComboBox()
        self.cb_mixed.addItems(["FP16", "FP32", "BF16"])
        self.cb_mixed.currentIndexChanged.connect(self._on_perf_level_changed)
        self._lbl_mixed = row(g_arch, "混合精度训练", self.cb_mixed)

        ga_row = QH()
        ga_row.setSpacing(12)
        self.sl_grad = QSlider(Qt.Horizontal)
        self.sl_grad.setMinimum(1)
        self.sl_grad.setMaximum(8)
        self.ed_grad_val = QLineEdit("1")
        self.ed_grad_val.setFixedWidth(int(48 * self._scale))
        self._bind_slider_input(self.sl_grad, self.ed_grad_val, "", 1)
        ga_row.addWidget(self.sl_grad, 1)
        ga_row.addWidget(self.ed_grad_val)
        ga_widget = QWidget()
        ga_widget.setLayout(ga_row)
        self._lbl_grad = row(g_arch, "梯度累积步数", ga_widget)

        nw_row = QH()
        nw_row.setSpacing(12)
        self.sl_workers = QSlider(Qt.Horizontal)
        self.sl_workers.setMinimum(1)
        self.sl_workers.setMaximum(8)
        self.ed_workers_val = QLineEdit("4")
        self.ed_workers_val.setFixedWidth(int(48 * self._scale))
        self._bind_slider_input(self.sl_workers, self.ed_workers_val, "", 1)
        nw_row.addWidget(self.sl_workers, 1)
        nw_row.addWidget(self.ed_workers_val)
        nw_widget = QWidget()
        nw_widget.setLayout(nw_row)
        self._lbl_workers = row(g_arch, "数据加载器工作数", nw_widget)
        self._add_restart_hint(g_arch)

        # ── 3. 训练器设置 ──
        p3 = self._add_section("训练器设置")
        g = self._add_group(p3, "训练保存")
        # 自动保存格式（训练器定时保存：.mbtl / .mbtlx；.pth 由训练完成时自动保存）
        afmt_widget = QWidget()
        afmt_layout = QHBoxLayout(afmt_widget)
        afmt_layout.setSpacing(int(10 * self._scale))
        self.chk_trainer_auto_mbtl = QCheckBox(".mbtl")
        self.chk_trainer_auto_mbtlx = QCheckBox(".mbtlx")
        self.chk_trainer_auto_all = QCheckBox("全部")
        for chk in (self.chk_trainer_auto_mbtl, self.chk_trainer_auto_mbtlx, self.chk_trainer_auto_all):
            chk.setStyleSheet(f"font-size: {self._base_fs}px;")
            afmt_layout.addWidget(chk)
        _ta_chks = (self.chk_trainer_auto_mbtl, self.chk_trainer_auto_mbtlx)
        def _on_trainer_auto_all(state):
            for chk in _ta_chks:
                chk.setChecked(state == Qt.Checked)
        self.chk_trainer_auto_all.stateChanged.connect(_on_trainer_auto_all)
        def _on_trainer_auto_fmt():
            self.chk_trainer_auto_all.blockSignals(True)
            self.chk_trainer_auto_all.setChecked(all(c.isChecked() for c in _ta_chks))
            self.chk_trainer_auto_all.blockSignals(False)
        for chk in _ta_chks:
            chk.stateChanged.connect(lambda _: _on_trainer_auto_fmt())
        row(g, "自动保存格式", afmt_widget)
        # 手动保存格式（训练器：.pth / .mbtl / .mbtlx）
        mfmt_widget = QWidget()
        mfmt_layout = QHBoxLayout(mfmt_widget)
        mfmt_layout.setSpacing(int(10 * self._scale))
        self.chk_manual_fmt_pth = QCheckBox(".pth")
        self.chk_manual_fmt_mbtl = QCheckBox(".mbtl")
        self.chk_manual_fmt_mbtlx = QCheckBox(".mbtlx")
        self.chk_manual_fmt_all = QCheckBox("全部")
        for chk in (self.chk_manual_fmt_pth, self.chk_manual_fmt_mbtl,
                    self.chk_manual_fmt_mbtlx, self.chk_manual_fmt_all):
            chk.setStyleSheet(f"font-size: {self._base_fs}px;")
            mfmt_layout.addWidget(chk)
        # "全部"联动
        _mfmt_chks = (self.chk_manual_fmt_pth, self.chk_manual_fmt_mbtl, self.chk_manual_fmt_mbtlx)
        def _on_manual_all_changed(state):
            checked = state == Qt.Checked
            for chk in _mfmt_chks:
                chk.setChecked(checked)
        self.chk_manual_fmt_all.stateChanged.connect(_on_manual_all_changed)
        def _on_manual_fmt_changed():
            all_checked = all(chk.isChecked() for chk in _mfmt_chks)
            self.chk_manual_fmt_all.blockSignals(True)
            self.chk_manual_fmt_all.setChecked(all_checked)
            self.chk_manual_fmt_all.blockSignals(False)
        for chk in _mfmt_chks:
            chk.stateChanged.connect(lambda _: _on_manual_fmt_changed())
        row(g, "手动保存格式", mfmt_widget)
        # 训练器自动保存路径
        auto_trainer_row = QH()
        auto_trainer_row.setSpacing(8)
        self.le_auto_save_trainer_path = QLineEdit()
        self.le_auto_save_trainer_path.setReadOnly(True)
        btn_auto_trainer = QPushButton("选择...")
        btn_auto_trainer.setMinimumWidth(int(70 * self._scale))
        btn_auto_trainer.clicked.connect(self._choose_auto_save_trainer_path)
        auto_trainer_row.addWidget(self.le_auto_save_trainer_path, 1)
        auto_trainer_row.addWidget(btn_auto_trainer)
        auto_trainer_widget = QWidget()
        auto_trainer_widget.setLayout(auto_trainer_row)
        row(g, "自动保存路径", auto_trainer_widget)
        # 训练器手动保存路径
        manual_trainer_row = QH()
        manual_trainer_row.setSpacing(8)
        self.le_manual_save_trainer_path = QLineEdit()
        self.le_manual_save_trainer_path.setReadOnly(True)
        btn_manual_trainer = QPushButton("选择...")
        btn_manual_trainer.setMinimumWidth(int(70 * self._scale))
        btn_manual_trainer.clicked.connect(self._choose_manual_save_trainer_path)
        manual_trainer_row.addWidget(self.le_manual_save_trainer_path, 1)
        manual_trainer_row.addWidget(btn_manual_trainer)
        manual_trainer_widget = QWidget()
        manual_trainer_widget.setLayout(manual_trainer_row)
        row(g, "手动保存路径", manual_trainer_widget)
        self._add_restart_hint(g)

        # ── 4. 导入器设置 ──
        p4 = self._add_section("导入器设置")
        g = self._add_group(p4, "导入设置")
        self.le_image_size = QLineEdit("200KB~5MB")
        self.le_image_size.setPlaceholderText("如 200KB~5MB")
        self.le_image_size.setFixedWidth(int(160 * self._scale))
        self.le_image_size.editingFinished.connect(self._validate_image_size)
        row(g, "图片大小限制", self.le_image_size)

        self.chk_auto_preview = QCheckBox("开启")
        row(g, "导入时自动预览", self.chk_auto_preview)

        # 导入器文件保存（.mbtlx 标记文件）
        g_imp_save = self._add_group(p4, "文件保存")
        # 自动保存格式（导入器：.mbtl / .mbtlx，无 .pth 模型权重）
        iafmt_widget = QWidget()
        iafmt_layout = QHBoxLayout(iafmt_widget)
        iafmt_layout.setSpacing(int(10 * self._scale))
        self.chk_imp_auto_mbtl = QCheckBox(".mbtl")
        self.chk_imp_auto_mbtlx = QCheckBox(".mbtlx")
        self.chk_imp_auto_all = QCheckBox("全部")
        for chk in (self.chk_imp_auto_mbtl, self.chk_imp_auto_mbtlx, self.chk_imp_auto_all):
            chk.setStyleSheet(f"font-size: {self._base_fs}px;")
            iafmt_layout.addWidget(chk)
        _ia_chks = (self.chk_imp_auto_mbtl, self.chk_imp_auto_mbtlx)
        def _on_imp_auto_all(state):
            for chk in _ia_chks:
                chk.setChecked(state == Qt.Checked)
        self.chk_imp_auto_all.stateChanged.connect(_on_imp_auto_all)
        def _on_imp_auto_fmt():
            self.chk_imp_auto_all.blockSignals(True)
            self.chk_imp_auto_all.setChecked(all(c.isChecked() for c in _ia_chks))
            self.chk_imp_auto_all.blockSignals(False)
        for chk in _ia_chks:
            chk.stateChanged.connect(lambda _: _on_imp_auto_fmt())
        row(g_imp_save, "自动保存格式", iafmt_widget)
        # 手动保存格式（导入器：.mbtl / .mbtlx）
        imfmt_widget = QWidget()
        imfmt_layout = QHBoxLayout(imfmt_widget)
        imfmt_layout.setSpacing(int(10 * self._scale))
        self.chk_imp_manual_mbtl = QCheckBox(".mbtl")
        self.chk_imp_manual_mbtlx = QCheckBox(".mbtlx")
        self.chk_imp_manual_all = QCheckBox("全部")
        for chk in (self.chk_imp_manual_mbtl, self.chk_imp_manual_mbtlx, self.chk_imp_manual_all):
            chk.setStyleSheet(f"font-size: {self._base_fs}px;")
            imfmt_layout.addWidget(chk)
        _im_chks = (self.chk_imp_manual_mbtl, self.chk_imp_manual_mbtlx)
        def _on_imp_manual_all(state):
            for chk in _im_chks:
                chk.setChecked(state == Qt.Checked)
        self.chk_imp_manual_all.stateChanged.connect(_on_imp_manual_all)
        def _on_imp_manual_fmt():
            self.chk_imp_manual_all.blockSignals(True)
            self.chk_imp_manual_all.setChecked(all(c.isChecked() for c in _im_chks))
            self.chk_imp_manual_all.blockSignals(False)
        for chk in _im_chks:
            chk.stateChanged.connect(lambda _: _on_imp_manual_fmt())
        row(g_imp_save, "手动保存格式", imfmt_widget)
        # 自动保存路径
        auto_loader_row = QH()
        auto_loader_row.setSpacing(8)
        self.le_auto_save_loader_path = QLineEdit()
        self.le_auto_save_loader_path.setReadOnly(True)
        btn_auto_loader = QPushButton("选择...")
        btn_auto_loader.setMinimumWidth(int(70 * self._scale))
        btn_auto_loader.clicked.connect(self._choose_auto_save_loader_path)
        auto_loader_row.addWidget(self.le_auto_save_loader_path, 1)
        auto_loader_row.addWidget(btn_auto_loader)
        auto_loader_widget = QWidget()
        auto_loader_widget.setLayout(auto_loader_row)
        row(g_imp_save, "自动保存路径", auto_loader_widget)

        # 手动保存路径
        manual_loader_row = QH()
        manual_loader_row.setSpacing(8)
        self.le_manual_save_loader_path = QLineEdit()
        self.le_manual_save_loader_path.setReadOnly(True)
        btn_manual_loader = QPushButton("选择...")
        btn_manual_loader.setMinimumWidth(int(70 * self._scale))
        btn_manual_loader.clicked.connect(self._choose_manual_save_loader_path)
        manual_loader_row.addWidget(self.le_manual_save_loader_path, 1)
        manual_loader_row.addWidget(btn_manual_loader)
        manual_loader_widget = QWidget()
        manual_loader_widget.setLayout(manual_loader_row)
        row(g_imp_save, "手动保存路径", manual_loader_widget)

        # ── 5. 识别器设置 ──
        p_rev = self._add_section("识别器设置")
        g_rev = self._add_group(p_rev, "模型加载")
        self.chk_rev_auto_load = QCheckBox("开启")
        row(g_rev, "启动时自动加载默认模型", self.chk_rev_auto_load)

        self.cb_rev_device = QComboBox()
        self.cb_rev_device.addItems(["自动", "CPU", "CUDA (NVIDIA GPU)", "DirectML (AMD/Intel GPU)"])
        row(g_rev, "默认推理设备", self.cb_rev_device)

        # ── 6. 日志 ──
        p5 = self._add_section("日志")
        g = self._add_group(p5, "日志")
        self.cb_log_level = QComboBox()
        self.cb_log_level.addItems(["关闭", "仅错误", "警告", "信息", "调试"])
        row(g, "日志级别", self.cb_log_level)
        self.chk_log_sys = QCheckBox("开启")
        row(g, "系统日志", self.chk_log_sys)
        self.chk_log_op = QCheckBox("开启")
        row(g, "操作日志", self.chk_log_op)
        self.chk_log_data = QCheckBox("开启")
        row(g, "数据日志", self.chk_log_data)
        self.chk_log_train = QCheckBox("开启")
        row(g, "训练日志", self.chk_log_train)
        self.chk_log_model = QCheckBox("开启")
        row(g, "模型日志", self.chk_log_model)
        self.chk_log_err = QCheckBox("开启")
        row(g, "错误日志", self.chk_log_err)
        self.chk_log_perf = QCheckBox("开启")
        row(g, "性能日志", self.chk_log_perf)

        log_path_row = QH()
        log_path_row.setSpacing(8)
        self.le_log_path = QLineEdit()
        self.le_log_path.setReadOnly(True)
        btn_log_path = QPushButton("选择...")
        btn_log_path.setMinimumWidth(int(70 * self._scale))
        btn_log_path.clicked.connect(self._choose_log_path)
        log_path_row.addWidget(self.le_log_path, 1)
        log_path_row.addWidget(btn_log_path)
        log_path_widget = QWidget()
        log_path_widget.setLayout(log_path_row)
        row(g, "日志文件路径", log_path_widget)

        tip_label = QLabel("提示：日志不会自动生成，点击下方按钮手动导出")
        tip_label.setStyleSheet(f"font-size: {int(self._base_fs * 0.82)}px; color: #e67700; padding: 2px 0 0 0;")
        self._tip_labels.append(tip_label)
        g.addWidget(tip_label)

        btn_gen_log = QPushButton("生成日志文件")
        btn_gen_log.setObjectName("btn_gen_log")
        btn_gen_log.setMinimumHeight(int(self._base_fs * 1.4))
        btn_gen_log.clicked.connect(self._generate_log_file)
        self._btn_gen_log = btn_gen_log
        g.addWidget(btn_gen_log)

        # 底部占位，确保最后一个分区可以完全滚动到视口顶部
        # 高度在 resizeEvent 中动态调整为 viewport 高度
        self._bottom_spacer = QWidget()
        self._bottom_spacer.setMinimumHeight(20)
        self._content_layout.addWidget(self._bottom_spacer)

        # 组件未安装时置灰对应设置页（可见但不可操作）
        self._apply_component_availability()

    def _apply_component_availability(self):
        """检测 trainer.pyw / importer.pyw 是否安装，未安装则置灰对应设置页。

        置灰后页面仍可见（用户可查看配置），但所有控件不可操作。
        """
        if getattr(sys, 'frozen', False):
            app_root = os.path.dirname(sys.executable)
        else:
            app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        has_trainer = os.path.isfile(os.path.join(app_root, "trainer.pyw"))
        has_importer = os.path.isfile(os.path.join(app_root, "importer.pyw"))
        # 供权重检测弹窗判断：仅训练器模式下提示"缺少权重"，识别器模式不弹
        self._has_trainer = has_trainer
        for sec in self._sections:
            title = sec["title"]
            if title == "训练器设置" and not has_trainer:
                sec["widget"].setEnabled(False)
                # 在标题旁标注未安装提示
                sec["item"].setText(f"  {title}（未安装）")
            elif title == "导入器设置" and not has_importer:
                sec["widget"].setEnabled(False)
                sec["item"].setText(f"  {title}（未安装）")

    def _on_autolayout_changed(self, state):
        enabled = state == Qt.Checked
        if enabled:
            self.chk_minimize.setChecked(True)
        self.chk_minimize.setEnabled(not enabled)

    def _update_model_availability(self):
        """检测各模型架构的预训练权重是否已缓存，禁用不可用的选项。"""
        # 先刷新缓存（用户可能刚通过安装器下载了权重）
        build_arch_cache()
        model = self.cb_model.model()
        first_available = -1
        any_available = False
        for i, arch_key in enumerate(self._arch_keys):
            available, reason = check_arch_available(arch_key)
            any_available = any_available or available
            item = model.item(i)
            if item:
                item.setEnabled(available)
                # 可用时显示完整名（含"轻量化"等特性描述）；不可用时显示"（未下载）"
                display = ARCH_DISPLAY.get(arch_key, arch_key)
                if not available:
                    # 去掉特性描述后缀（如"（轻量化）"），改为"（未下载）"
                    display = display.split("（")[0] + "（未下载）"
                item.setText(display)
                item.setToolTip(reason if not available else "")
            if available and first_available < 0:
                first_available = i
        # 全部不可用：提示用户安装权重（仅训练器模式；识别器模式无训练功能，
        # 模型架构选择已置灰，弹"再训练"警告不合理）
        if not any_available and getattr(self, "_has_trainer", False):
            QMessageBox.warning(self, "提示", "未检测到任何模型权重文件。\n请通过安装器的维护模式下载模型权重后再训练。")
        # 如果当前选中项被禁用，切换到第一个可用项
        if first_available >= 0:
            current_item = model.item(self.cb_model.currentIndex())
            if current_item and not current_item.isEnabled():
                self.cb_model.setCurrentIndex(first_available)

    def _on_auto_alloc_changed(self, state):
        """自动配置总开关：开启时置灰子级（模型架构除外）并显示算法分配值，关闭时启用手动输入。"""
        auto = state == Qt.Checked
        # 模型架构和Dropout始终可选（不置灰）；其他子级控件及标签置灰/启用
        sub_controls = (self.cb_lora, self.sl_gpu, self.sl_mem, self.cb_mixed,
                        self.sl_grad, self.sl_workers)
        sub_labels = (self._lbl_lora, self._lbl_gpu, self._lbl_mem, self._lbl_mixed,
                      self._lbl_grad, self._lbl_workers)
        for w, lab in zip(sub_controls, sub_labels):
            w.setEnabled(not auto)
            lab.setStyleSheet(self._label_style_disabled if auto else self._label_style)
        # 下拉框显式置灰样式（cb_lora, cb_mixed）
        for w in (self.cb_lora, self.cb_mixed):
            w.setStyleSheet(self._combo_style_disabled if auto else self._combo_style)
        # 值显示框置灰样式 + setEnabled 彻底防止修改
        for w in (self.ed_gpu_val, self.ed_mem_val, self.ed_grad_val, self.ed_workers_val):
            w.setEnabled(not auto)
            w.setStyleSheet(self._val_style_disabled if auto else self._val_style)
        # 挡位控件及标签：auto 时启用，非 auto 时置灰
        self.cb_perf_level.setEnabled(auto)
        self.cb_perf_level.setStyleSheet(self._combo_style if auto else self._combo_style_disabled)
        self._lbl_perf.setStyleSheet(self._label_style if auto else self._label_style_disabled)
        if auto:
            # 设置推荐值（模型架构和Dropout保持用户选择）
            self.cb_lora.setCurrentIndex(1)    # 8
            self.cb_mixed.setCurrentIndex(0)   # FP16
            self.sl_grad.setValue(1)
            self._update_auto_alloc_display()
        else:
            # 非 auto 时也显示设备信息（含实时内存和CPU使用率）
            hw = get_hardware_cache()
            gpu = hw.get("gpu_total_gb", 0)
            gpu_name = hw.get("gpu_name", "")
            is_igpu = hw.get("is_integrated_gpu", False)
            cpu_name = hw.get("cpu_name", "未知CPU")
            cores = hw.get("cpu_cores", 0)
            mem_nominal = hw.get("mem_nominal_gb", hw.get("mem_total_gb", 0))
            mem_recognized = hw.get("mem_recognized_gb", mem_nominal)
            mem_type = hw.get("mem_type", "")
            mem_avail = mem_recognized
            mem_usage_pct = 0
            cpu_usage_pct = 0
            if not self._loading:
                try:
                    import psutil
                    vm = psutil.virtual_memory()
                    mem_avail = round(vm.available / (1024 ** 3), 1)
                    mem_usage_pct = int(vm.percent)
                    cpu_usage_pct = int(psutil.cpu_percent(interval=0.1))
                except Exception:
                    mem_avail = hw.get("mem_available_gb", mem_recognized)
            # GPU 信息：从 _dml_devices 获取所有 GPU（含核显），按 GPU0/GPU1 换行显示
            if not hasattr(self, '_dml_devices') or not self._dml_devices:
                self._refresh_dml_devices()
            _gpu_lines = []
            for _idx, (_dn, _dv, _di) in enumerate(self._dml_devices):
                if _dn and _dn != "未检测到 GPU":
                    if _di:
                        _gpu_lines.append(f"GPU{_idx}: {_dn}（核显·共享{mem_nominal}G）")
                    elif _dv != "unknown":
                        _disp_vram = gpu if _dn == gpu_name else 0
                        if _dv == "nvidia" and not self._loading:
                            try:
                                _rt, _, _ = get_gpu_memory_usage()
                                if _rt > 0:
                                    _disp_vram = _rt
                            except Exception:
                                pass
                        if _disp_vram > 0:
                            _gpu_lines.append(f"GPU{_idx}: {_dn} {_disp_vram}G")
                        else:
                            _gpu_lines.append(f"GPU{_idx}: {_dn}")
            if _gpu_lines:
                self.lbl_gpu_info.setText("\n".join(_gpu_lines))
            elif gpu_name and gpu_name != "未检测到":
                if is_igpu:
                    self.lbl_gpu_info.setText(f"GPU0: {gpu_name}（核显·共享{mem_nominal}G）")
                elif gpu > 0:
                    self.lbl_gpu_info.setText(f"GPU0: {gpu_name} {gpu}G")
                else:
                    self.lbl_gpu_info.setText(f"GPU0: {gpu_name}")
            else:
                self.lbl_gpu_info.setText("未检测到")
            if cores > 0:
                self.lbl_cpu_info.setText(f"{cpu_name} ({cores}核)")
            else:
                self.lbl_cpu_info.setText("未检测到")
            # 内存分配：系统内存 + GPU 显存使用情况（核显不显示 GPU 行，共享系统内存）
            if not self._loading and gpu > 0 and not is_igpu:
                gpu_total_rt, gpu_free_rt, gpu_usage_pct = get_gpu_memory_usage()
            else:
                gpu_total_rt, gpu_free_rt, gpu_usage_pct = 0, 0, 0
            parts = []
            if mem_recognized > 0:
                mem_label = f"{mem_nominal}G {mem_type}" if mem_type and mem_type != "未知" else f"{mem_nominal}G"
                parts.append(f"内存：{mem_label}（{mem_usage_pct}% 当前可用{mem_avail}G）")
            if gpu > 0 and not is_igpu:
                gpu_total_disp = gpu_total_rt if gpu_total_rt > 0 else gpu
                gpu_free_disp = gpu_free_rt if gpu_total_rt > 0 else 0
                gpu_pct_disp = gpu_usage_pct if gpu_total_rt > 0 else 0
                parts.append(f"GPU：{gpu_total_disp}G（{gpu_pct_disp}% 当前可用{gpu_free_disp}G）")
            self.lbl_mem_info.setText("；".join(parts) if parts else "未检测到")
            # 非 auto 模式：根据 _gpu_mode 显示滑块值
            gpu_mode = getattr(self, "_gpu_mode", "cuda_fraction")
            gpu_unit = getattr(self, "_gpu_unit", "GB")
            arch_idx = self.cb_train_arch.currentIndex()
            if arch_idx == 2:  # CPU 模式
                self.ed_gpu_val.setText("—")
            else:
                self.ed_gpu_val.setText(f"{self.sl_gpu.value()}{gpu_unit}")
            self.ed_mem_val.setText(f"{self.sl_mem.value()}GB")
            self.ed_workers_val.setText(str(self.sl_workers.value()))

    def _update_auto_alloc_display(self):
        """根据硬件缓存和挡位更新显卡/CPU/内存信息及算法分配值。

        内存采用 psutil 实时检测；CPU 使用率实时读取。
        """
        hw = get_hardware_cache()
        gpu = hw.get("gpu_total_gb", 0)
        gpu_name = hw.get("gpu_name", "")
        gpu_vendor = hw.get("gpu_vendor", "")
        is_igpu = hw.get("is_integrated_gpu", False)
        cpu_name = hw.get("cpu_name", "未知CPU")
        cores = hw.get("cpu_cores", 0)
        mem_nominal = hw.get("mem_nominal_gb", hw.get("mem_total_gb", 0))
        mem_recognized = hw.get("mem_recognized_gb", mem_nominal)
        mem_type = hw.get("mem_type", "")
        # 实时检测当前可用内存和 CPU 使用率（初始化时跳过，避免卡顿）
        mem_avail = mem_recognized
        mem_usage_pct = 0
        cpu_usage_pct = 0
        if not self._loading:
            try:
                import psutil
                vm = psutil.virtual_memory()
                mem_avail = round(vm.available / (1024 ** 3), 1)
                mem_usage_pct = int(vm.percent)
                cpu_usage_pct = int(psutil.cpu_percent(interval=None))
            except Exception:
                mem_avail = hw.get("mem_available_gb", mem_recognized)
        # 显示 GPU 信息：从 _dml_devices 获取所有 GPU（含核显），按 GPU0/GPU1 换行显示
        if not hasattr(self, '_dml_devices') or not self._dml_devices:
            self._refresh_dml_devices()
        _gpu_lines = []
        for _idx, (_dn, _dv, _di) in enumerate(self._dml_devices):
            if _dn and _dn != "未检测到 GPU":
                if _di:
                    _gpu_lines.append(f"GPU{_idx}: {_dn}（核显·共享{mem_nominal}G）")
                elif _dv != "unknown":
                    # 独显显存：优先用 nvidia-smi 获取，回退到缓存
                    _disp_vram = gpu if _dn == gpu_name else 0
                    if _dv == "nvidia" and not self._loading:
                        try:
                            _rt, _, _ = get_gpu_memory_usage()
                            if _rt > 0:
                                _disp_vram = _rt
                        except Exception:
                            pass
                    if _disp_vram > 0:
                        _gpu_lines.append(f"GPU{_idx}: {_dn} {_disp_vram}G")
                    else:
                        _gpu_lines.append(f"GPU{_idx}: {_dn}")
        if _gpu_lines:
            self.lbl_gpu_info.setText("\n".join(_gpu_lines))
        elif gpu_name and gpu_name != "未检测到":
            if is_igpu:
                self.lbl_gpu_info.setText(f"GPU0: {gpu_name}（核显·共享{mem_nominal}G）")
            elif gpu > 0:
                self.lbl_gpu_info.setText(f"GPU0: {gpu_name} {gpu}G")
            else:
                self.lbl_gpu_info.setText(f"GPU0: {gpu_name}")
        else:
            self.lbl_gpu_info.setText("未检测到")
        # 显示 CPU 信息（仅型号 + 核心数）
        if cores > 0:
            self.lbl_cpu_info.setText(f"{cpu_name} ({cores}核)")
        else:
            self.lbl_cpu_info.setText("自动检测中...")
        # GPU 显存使用情况：实时检测（仅独显通过 nvidia-smi 检测；核显共享系统内存不单独显示）
        gpu_total_rt, gpu_free_rt, gpu_usage_pct = 0, 0, 0
        if not self._loading and gpu > 0 and not is_igpu:
            try:
                gpu_total_rt, gpu_free_rt, gpu_usage_pct = get_gpu_memory_usage()
            except Exception:
                pass
        parts = []
        if mem_recognized > 0:
            mem_label = f"{mem_nominal}G {mem_type}" if mem_type and mem_type != "未知" else f"{mem_nominal}G"
            parts.append(f"内存：{mem_label}（{mem_usage_pct}% 当前可用{mem_avail}G）")
        if gpu > 0 and not is_igpu:
            gpu_total_disp = gpu_total_rt if gpu_total_rt > 0 else gpu
            gpu_free_disp = gpu_free_rt if gpu_total_rt > 0 else 0
            gpu_pct_disp = gpu_usage_pct if gpu_total_rt > 0 else 0
            parts.append(f"GPU：{gpu_total_disp}G（{gpu_pct_disp}% 当前可用{gpu_free_disp}G）")
        self.lbl_mem_info.setText("；".join(parts) if parts else "自动检测中...")
        # 根据挡位计算分配值（传入当前选择的模型架构以获得准确估算）
        level = ["light", "balanced", "extreme"][self.cb_perf_level.currentIndex()]
        arch = self._arch_keys[self.cb_model.currentIndex()] if self.cb_model.currentIndex() < len(self._arch_keys) else "vit_b_16"
        mixed = ["fp16", "fp32", "bf16"][self.cb_mixed.currentIndex()] == "fp16"
        # 判断当前架构和 GPU 类型
        arch_idx = self.cb_train_arch.currentIndex()
        gpu_mode = getattr(self, "_gpu_mode", "cuda_fraction")
        gpu_unit = getattr(self, "_gpu_unit", "GB")
        # DML 模式下判断选中卡是否为核显
        is_integrated = False
        if arch_idx == 1:  # DirectML
            dml_idx = self.cb_dml_device.currentIndex() if self.cb_dml_device.count() > 0 else 0
            if dml_idx < len(self._dml_devices):
                _, _, is_integrated = self._dml_devices[dml_idx]
        is_cpu_mode = (arch_idx == 2)
        if is_cpu_mode:
            # CPU 模式：无 GPU 分配
            self.ed_gpu_val.setText("—")
            if mem_nominal > 0:
                alloc = compute_resource_allocation(0, mem_nominal, arch, mixed, level,
                                                   is_integrated=False)
                self.ed_mem_val.setText(f"{alloc['usable_sys_gb']:.1f}GB")
                self.ed_workers_val.setText(str(alloc["num_workers"]))
            else:
                self.ed_mem_val.setText("待检测")
                self.ed_workers_val.setText("待检测")
        elif gpu > 0 and mem_nominal > 0:
            alloc = compute_resource_allocation(gpu, mem_nominal, arch, mixed, level,
                                               is_integrated=is_integrated)
            if gpu_mode == "igpu_ratio":
                # 核显 DML：显示共享内存比例（百分比）
                igpu_ratio = 0.35 if level == "balanced" else (0.25 if level == "light" else 0.45)
                self.ed_gpu_val.setText(f"{int(igpu_ratio * 100)}%")
            elif gpu_mode == "dml_reserved":
                # 独显 DML：显示保留显存值
                self.ed_gpu_val.setText(f"{alloc['gpu_reserved_gb']:.1f}GB")
            else:
                # CUDA：显示可用显存
                self.ed_gpu_val.setText(f"{alloc['usable_gpu_gb']:.1f}GB")
            self.ed_mem_val.setText(f"{alloc['usable_sys_gb']:.1f}GB")
            self.ed_workers_val.setText(str(alloc["num_workers"]))
        else:
            self.ed_gpu_val.setText("未知")
            self.ed_mem_val.setText("未知")
            self.ed_workers_val.setText("未知")
        # 缓存缺少关键字段（CPU/内存任一为空）时启动后台检测
        # 注意：GPU 为 0/未检测到 不再触发自动重扫——集显机器（如 AMD Radeon）
        # torch 检测不到独立 GPU，每次打开设置都重复 import torch 扫描耗时 2-5 秒
        # 用户需要重新检测 GPU 时，手动点击"重新检测"按钮即可
        need_detect = (not hw) or (hw.get("cpu_cores", 0) <= 0) or (hw.get("mem_nominal_gb", 0) <= 0)
        if need_detect and not self._hw_detecting:
            self._hw_detecting = True
            thread = HardwareDetectThread(skip_gpu=False, parent=self)
            thread.result_ready.connect(self._on_hw_detect_auto)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda: setattr(self, "_hw_detecting", False))
            thread.start()

    def _on_perf_level_changed(self):
        """挡位变化时重新计算分配值。"""
        if self.chk_auto_alloc.isChecked():
            self._update_auto_alloc_display()

    def _refresh_dml_devices(self):
        """检测系统 GPU 并填充 DML 挂载卡下拉框（单选）。"""
        from utils.device_backend import _identify_vendor, _is_integrated_gpu
        self._dml_devices = []
        try:
            import subprocess as _sp
            _r = _sp.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=5,
                creationflags=_sp.CREATE_NO_WINDOW)
            if _r.returncode == 0:
                for line in _r.stdout.strip().splitlines():
                    name = line.strip()
                    if not name:
                        continue
                    # 过滤虚拟显示器驱动（如 OrayIddDriver、Microsoft Basic Render Driver 等）
                    gl = name.lower()
                    if any(kw in gl for kw in ("idddriver", "basic render", "microsoft display",
                                               "remote display", "teamviewer", "anydesk",
                                               "mirage", "parsec")):
                        continue
                    vendor = _identify_vendor(name)
                    is_integrated = _is_integrated_gpu(name)
                    self._dml_devices.append((name, vendor, is_integrated))
        except Exception:
            pass
        # 如果未检测到，提供默认选项
        if not self._dml_devices:
            self._dml_devices = [("未检测到 GPU", "unknown", False)]

        self.cb_dml_device.blockSignals(True)
        self.cb_dml_device.clear()
        for name, vendor, igpu in self._dml_devices:
            tag = ""
            if igpu:
                tag = "（核显）"
            elif vendor != "unknown":
                tag = "（独显）"
            self.cb_dml_device.addItem(f"{name}{tag}")
        self.cb_dml_device.blockSignals(False)

    def _on_train_arch_changed(self):
        """训练架构切换时：刷新 DML 设备列表、动态修改显存分配行。"""
        arch_idx = self.cb_train_arch.currentIndex()
        # 0=CUDA, 1=DirectML, 2=CPU
        is_dml = (arch_idx == 1)
        is_cpu = (arch_idx == 2)

        # DML 挂载卡选择：仅 DML 模式可见
        self._lbl_dml_device.setVisible(is_dml)
        self.cb_dml_device.setVisible(is_dml)
        if is_dml:
            self._refresh_dml_devices()

        # 动态修改"分配显存"行
        if is_cpu:
            # CPU 模式：隐藏 GPU 分配行
            self._lbl_gpu.setVisible(False)
            self.sl_gpu.setVisible(False)
            self.ed_gpu_val.setVisible(False)
        elif is_dml:
            # DML 模式：判断选中卡是否为核显
            dml_idx = self.cb_dml_device.currentIndex() if self.cb_dml_device.count() > 0 else 0
            if dml_idx < len(self._dml_devices):
                _, _, is_igpu = self._dml_devices[dml_idx]
            else:
                is_igpu = False
            if is_igpu:
                # 核显 DML：共享内存比例（10-60%，步进5）
                self._lbl_gpu.setText("共享内存比例")
                self.sl_gpu.setMinimum(10)
                self.sl_gpu.setMaximum(60)
                self.sl_gpu.setSingleStep(5)
                self.sl_gpu.setPageStep(5)
                self._gpu_unit = "%"
                self._gpu_mode = "igpu_ratio"
                self._rebind_gpu_slider(5)
            else:
                # 独显 DML：保留显存（1-8GB，步进1）
                self._lbl_gpu.setText("保留显存（给系统）")
                self.sl_gpu.setMinimum(1)
                self.sl_gpu.setMaximum(8)
                self.sl_gpu.setSingleStep(1)
                self.sl_gpu.setPageStep(1)
                self._gpu_unit = "GB"
                self._gpu_mode = "dml_reserved"
                self._rebind_gpu_slider(1)
            self._lbl_gpu.setVisible(True)
            self.sl_gpu.setVisible(True)
            self.ed_gpu_val.setVisible(True)
        else:
            # CUDA 模式：分配显存（2-32GB，步进2）
            self._lbl_gpu.setText("分配显存")
            self.sl_gpu.setMinimum(2)
            self.sl_gpu.setMaximum(32)
            self.sl_gpu.setSingleStep(2)
            self.sl_gpu.setPageStep(2)
            self._gpu_unit = "GB"
            self._gpu_mode = "cuda_fraction"
            self._rebind_gpu_slider(2)
            self._lbl_gpu.setVisible(True)
            self.sl_gpu.setVisible(True)
            self.ed_gpu_val.setVisible(True)

        # DirectML 提示文字显隐
        self._lbl_gpu_hint.setVisible(is_dml)

        # 触发分配值重新计算
        if self.chk_auto_alloc.isChecked():
            self._update_auto_alloc_display()

    def _rebind_gpu_slider(self, step):
        """重新绑定 GPU 滑块与输入框（架构切换后 unit/step 变化）。"""
        try:
            self.sl_gpu.valueChanged.disconnect()
        except Exception:
            pass
        try:
            self.ed_gpu_val.editingFinished.disconnect()
        except Exception:
            pass
        self._bind_slider_input(self.sl_gpu, self.ed_gpu_val, self._gpu_unit, step)

    def _on_dml_device_changed(self):
        """DML 挂载卡切换时：根据核显/独显动态修改显存分配行。"""
        self._on_train_arch_changed()  # 复用架构切换逻辑（会根据当前选中卡更新 UI）

    def _on_hw_detect_auto(self, hw):
        """硬件检测完成回调：更新设备信息和算法分配值。"""
        if self.chk_auto_alloc.isChecked():
            # 复用 _update_auto_alloc_display 的实时内存检测逻辑
            self._update_auto_alloc_display()

    def _on_recheck_hardware(self):
        """手动触发硬件重新检测（仅检测硬件环境，不检测内存分配）。"""
        if self._hw_detecting:
            return
        self._hw_detecting = True
        self.btn_recheck_hw.setEnabled(False)
        self.lbl_gpu_info.setText("检测中...")
        self.lbl_cpu_info.setText("检测中...")
        self.lbl_mem_info.setText("检测中...")
        thread = HardwareDetectThread(skip_gpu=False, parent=self)
        thread.result_ready.connect(self._on_hw_detect_recheck)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: setattr(self, "_hw_detecting", False))
        thread.finished.connect(lambda: self.btn_recheck_hw.setEnabled(True))
        thread.start()

    def _on_hw_detect_recheck(self, hw):
        """手动检测完成回调：更新设备信息和分配值。"""
        save_hardware_cache(hw)
        self._update_auto_alloc_display()

    def _choose_log_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择日志保存路径")
        if path:
            self.le_log_path.setText(path)

    def _choose_auto_save_trainer_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择训练器自动保存路径")
        if path:
            self.le_auto_save_trainer_path.setText(path)

    def _choose_manual_save_trainer_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择训练器手动保存路径")
        if path:
            self.le_manual_save_trainer_path.setText(path)

    def _choose_auto_save_loader_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择导入器自动保存路径")
        if path:
            self.le_auto_save_loader_path.setText(path)

    def _choose_manual_save_loader_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择导入器手动保存路径")
        if path:
            self.le_manual_save_loader_path.setText(path)

    def _section_tops(self):
        tops = []
        for sec in self._sections:
            tops.append(sec["widget"].mapTo(self._content_widget, sec["widget"].rect().topLeft()).y())
        return tops

    def _current_section_index(self):
        tops = self._section_tops()
        current = self._scroll.verticalScrollBar().value()
        maximum = self._scroll.verticalScrollBar().maximum()
        # 滚动到底部时强制选中最后一个区域
        if tops and current >= maximum - 5:
            return len(tops) - 1
        idx = 0
        for i, top in enumerate(tops):
            if top <= current + 5:
                idx = i
            else:
                break
        return idx

    def _poll_settings_cmd(self):
        """轮询命令文件：收到跳转指令时恢复窗口并跳转；收到 close 时默认不保存退出。"""
        try:
            if not os.path.exists(_SETTINGS_CMD_FILE):
                return
            with open(_SETTINGS_CMD_FILE, "r", encoding="utf-8") as f:
                caller = f.read().strip()
            os.remove(_SETTINGS_CMD_FILE)
        except Exception:
            return

        # 关闭指令：训练器/导入器/识别器关闭时发来，默认不保存直接退出
        if caller == "close":
            self.done(EXIT_CANCEL)
            return

        # 恢复窗口（取消最小化）+ 带到前台
        try:
            import ctypes
            user32 = ctypes.windll.user32
            SW_RESTORE = 9
            hwnd = int(self.winId())
            if self.isMinimized():
                user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
        except Exception:
            self.showNormal()
            self.raise_()
            self.activateWindow()

        # 跳转到对应 section
        idx = _CALLER_SECTION_MAP.get(caller, 0)
        if 0 <= idx < len(self._sections):
            self._nav_list.setCurrentRow(idx)

    def _scroll_to_section(self, index):
        if self._scroll_locked:
            return
        if not (0 <= index < len(self._sections)):
            return
        self._scroll_locked = True
        tops = self._section_tops()
        self._scroll.verticalScrollBar().setValue(tops[index])
        self._nav_list.blockSignals(True)
        self._nav_list.setCurrentRow(index)
        self._nav_list.blockSignals(False)
        QTimer.singleShot(200, lambda: setattr(self, "_scroll_locked", False))

    def _switch_section_by_direction(self, direction):
        idx = self._current_section_index() + direction
        if 0 <= idx < len(self._sections):
            self._scroll_to_section(idx)

    def _on_scroll_changed(self, value):
        if self._scroll_locked:
            return
        idx = self._current_section_index()
        self._nav_list.blockSignals(True)
        self._nav_list.setCurrentRow(idx)
        self._nav_list.blockSignals(False)

    def _resolve_theme(self, theme):
        """将 'system' 解析为实际的 light/dark。"""
        return resolve_theme(theme)

    def _apply_theme_to_dialog(self):
        """把主题应用到设置对话框全部控件：背景、导航、内容区、文字、输入框、按钮、标题栏。"""
        theme = self._resolve_theme(self._temp.get("theme", "light"))
        is_dark = theme == "dark"
        bg = "#2d2d30" if is_dark else "#ffffff"
        fg = "#eeeeee" if is_dark else "#000000"
        nav_bg = "#252528" if is_dark else "#f5f5f5"
        nav_border = "#444444" if is_dark else "#e0e0e0"
        nav_sel = "#1e3a5f" if is_dark else "#e8f0fe"
        nav_sel_text = "#ffffff" if is_dark else "#1a73e8"
        nav_hover = "#333333" if is_dark else "#f0f0f0"
        group_border = "#555555" if is_dark else "#e0e0e0"
        input_bg = "#3c3c3c" if is_dark else "#ffffff"
        input_border = "#555555" if is_dark else "#d0d0d0"
        input_focus = "#4a9eff" if is_dark else "#1a73e8"
        btn_bg = "#6a6a70" if is_dark else "#ffffff"
        btn_hover = "#7d7d83" if is_dark else "#f5f7fa"
        # 取消按钮文字颜色与确认按钮一致（白色），浅色模式用深色保持可读
        cancel_text = "#ffffff" if is_dark else "#000000"
        btn_disabled_bg = "#2d2d30" if is_dark else "#f5f5f5"
        btn_disabled_fg = "#777777" if is_dark else "#aaaaaa"
        # 禁用控件样式：背景明显变暗以区分启用状态，文字保持可读的灰色
        if is_dark:
            disabled_bg = "#252526"          # 深色：背景明显比input_bg(#3c3c3c)暗
            disabled_fg = "#888888"          # 深色：可读灰字，与亮色#eeeeee明显区分
            disabled_border = "#3a3a3a"      # 深色：边框可见但内敛
            slider_disabled_groove = "#1e1e1e"
            slider_disabled_handle = "#505050"
        else:
            disabled_bg = "#e8e8e8"          # 浅色：背景明显比白色暗
            disabled_fg = "#999999"          # 浅色：可读灰字
            disabled_border = "#cccccc"      # 浅色：边框可见
            slider_disabled_groove = "#d8d8d8"
            slider_disabled_handle = "#b0b0b0"
        slider_groove = "#555555" if is_dark else "#e0e0e0"
        scroll_handle = "#666666" if is_dark else "#c0c0c0"
        scroll_handle_hover = "#777777" if is_dark else "#a0a0a0"
        scroll_handle_pressed = "#888888" if is_dark else "#909090"

        # 内容区与滚动区
        self._content_widget.setStyleSheet(f"background-color: {bg}; color: {fg};")
        self._scroll.setStyleSheet(f"QScrollArea {{ border: none; background-color: {bg}; }}")
        bottom_widget = self.btn_cancel.parentWidget()
        if bottom_widget is not None:
            # bottom_widget 设置自身背景即可，不要阻断子控件的 QSS 级联
            bottom_widget.setStyleSheet(f"QWidget {{ background-color: {bg}; }}")
        # 按钮统一线框型：无底色、仅边框描边 + 文字色（深浅色适配）
        # 取消/其他按钮：灰边框；确定/生成日志：蓝边框（主操作）
        if is_dark:
            line_brd, line_fg, line_hover_bg = "#888888", "#eeeeee", "#2a2a2e"
            blue_brd, blue_fg, blue_hover_bg = "#0078D4", "#0078D4", "#1e3a5f"
        else:
            line_brd, line_fg, line_hover_bg = "#c8c8c8", "#333333", "#f0f6ff"
            blue_brd, blue_fg, blue_hover_bg = "#0078D4", "#0078D4", "#e8f1fb"
        line_style = f"""
            QPushButton {{
                font-size: {self._base_fs}px;
                padding: {int(6 * self._scale)}px {int(16 * self._scale)}px;
                min-height: {int(self._base_fs * 1.5)}px;
                border: 1px solid {line_brd};
                border-radius: 6px;
                background: transparent;
                color: {line_fg};
            }}
            QPushButton:hover {{ background: {line_hover_bg}; border-color: {blue_brd}; color: {blue_fg}; }}
            QPushButton:pressed {{ background: {line_hover_bg}; border-color: {blue_brd}; color: {blue_fg}; }}
            QPushButton:disabled {{
                background: transparent;
                color: {btn_disabled_fg};
                border-color: {disabled_border};
            }}
        """
        blue_style = f"""
            QPushButton {{
                font-size: {self._base_fs}px;
                padding: {int(6 * self._scale)}px {int(16 * self._scale)}px;
                min-height: {int(self._base_fs * 1.5)}px;
                border: 1px solid {blue_brd};
                border-radius: 6px;
                background: transparent;
                color: {blue_fg};
            }}
            QPushButton:hover {{ background: {blue_hover_bg}; border-color: {blue_brd}; color: {blue_fg}; }}
            QPushButton:pressed {{ background: {blue_hover_bg}; border-color: {blue_brd}; color: {blue_fg}; }}
            QPushButton:disabled {{
                background: transparent;
                color: {btn_disabled_fg};
                border-color: {disabled_border};
            }}
        """
        self.btn_cancel.setStyleSheet(line_style)
        self.btn_ok.setStyleSheet(blue_style)
        # 其余按钮（选择…/重新检测等）线框型灰边框（避免深色下白色平铺）
        for _b in self.findChildren(QPushButton):
            if _b in (self.btn_cancel, self.btn_ok, self._btn_gen_log):
                continue
            _b.setStyleSheet(line_style)
        # "生成日志文件"保持蓝色线框主按钮（与确认同款）
        self._btn_gen_log.setStyleSheet(blue_style)

        # 导航栏
        self._nav_list.setStyleSheet(f"""
            QListWidget {{
                background: {nav_bg};
                border: none;
                border-right: 1px solid {nav_border};
                padding-top: 8px;
                font-size: {self._btn_fs}px;
            }}
            QListWidget::item {{
                padding: {int(self._btn_fs * 0.7)}px 20px;
                border: none;
                color: {fg};
            }}
            QListWidget::item:selected {{
                background: {nav_sel};
                color: {nav_sel_text};
            }}
            QListWidget::item:hover {{
                background: {nav_hover};
            }}
        """)

        # 全局控件样式（覆盖 _init_ui 中的浅色默认值）
        self.setStyleSheet(f"""
            QLineEdit {{
                font-size: {self._base_fs}px;
                padding: 1px {int(10 * self._scale)}px;
                border: 1px solid {input_border};
                border-radius: 6px;
                background: {input_bg};
                color: {fg};
            }}
            QLineEdit:hover {{ border-color: {input_focus}; }}
            QLineEdit:focus {{ border-color: {input_focus}; }}
            QLineEdit:disabled {{
                background: {disabled_bg};
                color: {disabled_fg};
                border-color: {disabled_border};
            }}
            QComboBox {{
                font-size: {self._base_fs}px;
                padding: 1px {int(26 * self._scale)}px 1px {int(8 * self._scale)}px;
                border: 1px solid {input_border};
                border-radius: 6px;
                background: {input_bg};
                color: {fg};
            }}
            QComboBox:hover {{ border-color: {input_focus}; }}
            QComboBox:focus {{ border-color: {input_focus}; }}
            QComboBox:disabled {{
                background: {disabled_bg};
                color: {disabled_fg};
                border-color: {disabled_border};
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: {int(22 * self._scale)}px;
                border: none;
            }}
            QComboBox:disabled::drop-down {{ background: {disabled_bg}; }}
            QComboBox QAbstractItemView {{
                font-size: {self._base_fs}px;
                selection-background-color: {nav_sel};
                selection-color: {nav_sel_text};
                background: {input_bg};
                color: {fg};
                border: 1px solid {input_border};
                border-radius: 4px;
                padding: 4px;
                outline: none;
            }}
            QCheckBox {{
                font-size: {self._base_fs}px;
                spacing: 6px;
                color: {fg};
            }}
            QCheckBox:disabled {{ color: {disabled_fg}; }}
            QLabel {{ font-size: {self._base_fs}px; color: {fg}; }}
            QLabel:disabled {{ color: {disabled_fg}; }}
            QSlider::groove:horizontal {{
                height: 4px;
                background: {slider_groove};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
                background: #1a73e8;
            }}
            QSlider::groove:horizontal:disabled {{ background: {slider_disabled_groove}; }}
            QSlider::handle:horizontal:disabled {{
                background: {slider_disabled_handle};
                border: none;
            }}
            QPushButton {{
                font-size: {self._base_fs}px;
                padding: {int(6 * self._scale)}px {int(16 * self._scale)}px;
                min-height: {int(self._base_fs * 1.5)}px;
                border: 1px solid {input_border};
                border-radius: 6px;
                background: {btn_bg};
                color: {fg};
            }}
            QPushButton:hover {{
                background: {btn_hover};
                border-color: {input_focus};
                color: {input_focus};
            }}
            QPushButton:pressed {{
                background: {nav_sel};
                border-color: {input_focus};
            }}
            QPushButton:disabled {{
                background: {btn_disabled_bg};
                color: {btn_disabled_fg};
                border-color: {disabled_border};
            }}
            /* 主操作按钮（确定、生成日志）：蓝色主色调，结构与全局按钮一致 */
            QPushButton#btn_ok, QPushButton#btn_gen_log {{
                background: #1a73e8;
                color: white;
                border: 1px solid #1a73e8;
            }}
            QPushButton#btn_ok:hover, QPushButton#btn_gen_log:hover {{
                background: #1557b0;
                border-color: #1557b0;
                color: white;
            }}
            QPushButton#btn_ok:pressed, QPushButton#btn_gen_log:pressed {{
                background: #0d47a1;
                border-color: #0d47a1;
            }}
            QSpinBox {{
                font-size: {self._base_fs}px;
                padding: 1px {int(10 * self._scale)}px;
                border: 1px solid {input_border};
                border-radius: 6px;
                background: {input_bg};
                color: {fg};
            }}
            QSpinBox:hover {{ border-color: {input_focus}; }}
            QSpinBox:focus {{ border-color: {input_focus}; }}
            QSpinBox:disabled {{
                background: {disabled_bg};
                color: {disabled_fg};
                border-color: {disabled_border};
            }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; border: none; }}
            QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; border: none; }}
            QScrollBar::handle {{ background: {scroll_handle}; border-radius: 5px; min-height: 30px; min-width: 30px; }}
            QScrollBar::handle:hover {{ background: {scroll_handle_hover}; }}
            QScrollBar::handle:pressed {{ background: {scroll_handle_pressed}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ border: none; background: none; width: 0; height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        """)

        # GroupBox 统一边框与标题颜色
        self._group_style = f"""
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {group_border};
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 18px;
                font-size: {self._btn_fs}px;
                color: {fg};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: {fg};
            }}
        """
        for group in self.findChildren(QGroupBox):
            group.setStyleSheet(self._group_style)

        # 行标签、区标题、提示文字
        info_fg = "#aaaaaa" if is_dark else "#666666"
        self._label_style = f"font-size: {self._base_fs}px; color: {fg};"
        for lab in self._row_labels:
            lab.setStyleSheet(self._label_style)
        for header in self._header_labels:
            header.setStyleSheet(f"font-size: {int(self._btn_fs * 1.2)}px; font-weight: bold; color: {fg}; padding: 4px 0;")
        for hint in self._restart_hints:
            hint.setStyleSheet(f"font-size: {int(self._base_fs * 0.82)}px; color: #e67700; padding: 4px 0 0 0;")
        for tip in self._tip_labels:
            tip.setStyleSheet(f"font-size: {int(self._base_fs * 0.82)}px; color: #e67700; padding: 2px 0 0 0;")
        # 温度警告标签：深色模式用亮红色，浅色模式用深红色
        if hasattr(self, "_lbl_temp_warn"):
            temp_warn_color = "#ff6b6b" if is_dark else "#d32f2f"
            self._lbl_temp_warn.setStyleSheet(
                f"font-size: {int(self._base_fs * 0.82)}px; color: {temp_warn_color}; padding-left: {self._label_min_w + 12}px;"
            )
        # 设备信息标签（显卡/CPU/内存）使用和行标签一致的前景色
        for lbl in (self.lbl_gpu_info, self.lbl_cpu_info, self.lbl_mem_info):
            lbl.setStyleSheet(f"font-size: {self._base_fs}px; color: {fg};")
        # 描述文字也适配
        self._desc_style = f"font-size: {int(self._base_fs * 0.82)}px; color: {info_fg}; padding-left: {self._label_min_w + 12}px;"

        # 更新行标签样式（深浅模式）并重新应用
        self._label_style = f"font-size: {self._base_fs}px; color: {fg};"
        self._label_style_disabled = f"font-size: {self._base_fs}px; color: {disabled_fg};"
        # 数值显示框样式（深浅模式 + 置灰）
        self._val_style = f"font-size: {self._base_fs}px; background: {input_bg}; color: {fg}; border: 1px solid {input_border}; border-radius: 6px;"
        self._val_style_disabled = f"font-size: {self._base_fs}px; background: {disabled_bg}; color: {disabled_fg}; border: 1px solid {disabled_border}; border-radius: 6px;"
        # 下拉框样式（深浅模式 + 置灰）
        self._combo_style = f"font-size: {self._base_fs}px; background: {input_bg}; color: {fg}; border: 1px solid {input_border}; border-radius: 6px;"
        self._combo_style_disabled = f"font-size: {self._base_fs}px; background: {disabled_bg}; color: {disabled_fg}; border: 1px solid {disabled_border}; border-radius: 6px;"
        auto = self.chk_auto_alloc.isChecked()
        auto_labels = {self._lbl_lora, self._lbl_gpu, self._lbl_mem,
                       self._lbl_mixed, self._lbl_grad, self._lbl_workers}
        for lab in self._row_labels:
            if lab in auto_labels:
                lab.setStyleSheet(self._label_style_disabled if auto else self._label_style)
            elif lab is self._lbl_perf:
                lab.setStyleSheet(self._label_style if auto else self._label_style_disabled)
            else:
                lab.setStyleSheet(self._label_style)
        # 数值显示框和下拉框同步置灰
        for w in (self.ed_gpu_val, self.ed_mem_val, self.ed_grad_val, self.ed_workers_val):
            w.setStyleSheet(self._val_style_disabled if auto else self._val_style)
        for w in (self.cb_lora, self.cb_mixed):
            w.setStyleSheet(self._combo_style_disabled if auto else self._combo_style)
        self.cb_perf_level.setStyleSheet(self._combo_style if auto else self._combo_style_disabled)

        # Windows 标题栏深浅模式
        if sys.platform == "win32" and self.winId():
            try:
                hwnd = int(self.winId())
                dwm = ctypes.windll.dwmapi
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                value = ctypes.c_int(1 if is_dark else 0)
                dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))
            except Exception:
                pass

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            self.move(parent.frameGeometry().center() - self.rect().center())
        else:
            screen = self.screen() if hasattr(self, "screen") else None
            if screen is None:
                from PyQt5.QtWidgets import QApplication
                screen = QApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                self.move(geo.center() - self.rect().center())
        # __init__ 里已应用过主题，showEvent 仅调整底部 spacer（避免重复主题应用导致加载缓慢）
        self._update_bottom_spacer()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 窗口大小变化时更新底部spacer，确保最后一项可完全滚到顶部
        self._update_bottom_spacer()

    def _update_bottom_spacer(self):
        """动态调整底部spacer高度，使最后一个section标题刚好能顶到视口顶部。

        spacer = viewport_height - last_section_height - offset
        offset 使标题位置略微调低，滚轮范围缩短一点点。
        """
        if not hasattr(self, "_bottom_spacer") or not self._sections:
            return
        vh = self._scroll.viewport().height()
        if vh <= 0:
            return
        last_widget = self._sections[-1]["widget"]
        last_h = last_widget.height()
        if last_h <= 0:
            last_h = last_widget.sizeHint().height()
        # offset=30 使日志标题位置略微调低，滚轮缩短一点点
        spacer_h = max(vh - last_h - 30, 0)
        self._bottom_spacer.setFixedHeight(spacer_h)

    def _generate_log_file(self):
        import datetime, time

        log_dir = self.le_log_path.text()
        if not log_dir or log_dir == "default":
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            log_dir = os.path.join(app_dir, "log")
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "生成失败", f"无法创建日志目录:\n{str(e)}")
                return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"{self.caller_name}_log_{ts}.txt")

        try:
            now = datetime.datetime.now()
            lines = []
            lines.append("┌" + "─" * 48 + "┐")
            lines.append("│  我的世界旗帜逆向套件 · 系统诊断报告" + " " * 15 + "│")
            lines.append("├" + "─" * 48 + "┤")
            lines.append(f"│  生成时间  {now.strftime('%Y-%m-%d %H:%M:%S')}" + " " * 20 + "│")
            lines.append(f"│  配置类型  {self.caller_name}" + " " * (34 - len(self.caller_name)) + "│")
            lines.append("└" + "─" * 48 + "┘")
            lines.append("")

            lines.append("▌ 01  配置总览")
            lines.append("─" * 46)
            s = self._collect_settings()
            sections = {
                "通用": ["theme", "auto_layout", "minimize_others",
                        "snap_enabled", "snap_threshold", "snap_grid", "restore_layout"],
                "训练": ["train_mode", "debug_mode", "model_arch", "dropout", "lora_rank",
                        "auto_resource_alloc", "perf_level",
                        "gpu_memory", "sys_memory", "mixed_precision",
                        "grad_accum", "num_workers", "auto_save_interval",
                        "trainer_auto_save_formats", "trainer_save_formats"],
                "日志": ["log_level", "log_system", "log_operation", "log_data", "log_performance",
                       "log_path", "log_training", "log_model", "log_error"],
                "存储": ["auto_save_trainer_path", "manual_save_trainer_path",
                        "auto_save_loader_path", "manual_save_loader_path",
                        "import_min_size_kb", "import_max_size_mb",
                        "auto_preview_import",
                        "importer_auto_save_formats", "importer_save_formats"],
            }
            labels = {
                "theme": "界面主题", "auto_layout": "自动布局",
                "minimize_others": "最小化其他窗口", "snap_enabled": "吸附对齐",
                "snap_threshold": "吸附阈值", "snap_grid": "网格吸附",
                "restore_layout": "恢复布局", "train_mode": "训练模式",
                "debug_mode": "调试模式",
                "model_arch": "模型架构",
                "dropout": "Dropout比率", "lora_rank": "LoRA秩",
                "auto_resource_alloc": "自动配置", "perf_level": "性能挡位",
                "gpu_memory": "分配显存", "sys_memory": "分配内存",
                "mixed_precision": "混合精度", "grad_accum": "梯度累积步数",
                "num_workers": "数据加载器工作数", "auto_save_interval": "自动保存(分钟)",
                "trainer_auto_save_formats": "训练器自动保存格式",
                "trainer_save_formats": "训练器手动保存格式",
                "importer_auto_save_formats": "导入器自动保存格式",
                "importer_save_formats": "导入器手动保存格式",
                "log_level": "日志级别", "log_system": "系统日志",
                "log_operation": "操作日志", "log_data": "数据日志",
                "log_performance": "性能日志", "log_path": "日志保存路径",
                "log_training": "训练日志", "log_model": "模型日志",
                "log_error": "错误日志",
                "auto_save_trainer_path": "训练器自动保存路径",
                "manual_save_trainer_path": "训练器手动保存路径",
                "auto_save_loader_path": "导入器自动保存路径",
                "manual_save_loader_path": "导入器手动保存路径",
                "import_min_size_kb": "图片大小限制(最小KB)",
                "import_max_size_mb": "图片大小限制(最大MB)",
                "auto_preview_import": "导入时自动预览",
            }
            level_map = {"0": "关闭", "1": "仅错误", "2": "警告", "3": "信息", "4": "调试"}
            theme_map = {"light": "浅色", "dark": "深色", "system": "系统"}

            for sec, keys in sections.items():
                items = []
                for k in keys:
                    if k in s:
                        v = s[k]
                        if k == "log_level":
                            v = level_map.get(str(v), str(v))
                        elif k == "theme":
                            v = theme_map.get(v, v)
                        elif isinstance(v, bool):
                            v = "是" if v else "否"
                        elif isinstance(v, list):
                            v = ", ".join(v) if v else "无"
                        items.append((labels.get(k, k), v))
                if items:
                    lines.append(f"  [{sec}]")
                    max_label = max(len(k) for k, _ in items)
                    for k, v in items:
                        lines.append(f"    {k}  {'·' * (max_label - len(k) + 2)}  {v}")
            lines.append("")

            lines.append("▌ 02  系统信息")
            lines.append("─" * 46)
            try:
                from utils.settings_manager import get_windows_version
                os_ver, os_build = get_windows_version()
                lines.append(f"  操作系统      {os_ver}")
            except Exception:
                lines.append(f"  操作系统      {os.name}")
            lines.append(f"  Python版本    {sys.version.split()[0]}")
            try:
                import platform
                lines.append(f"  系统平台      {platform.platform()}")
                proc_name = platform.processor()
                if proc_name:
                    lines.append(f"  处理器        {proc_name}")
            except Exception:
                pass
            lines.append("")

            lines.append("▌ 03  硬件状态")
            lines.append("─" * 46)
            hardware_issues = []

            lines.append("  [内存]")
            mem_ok = False
            try:
                from utils.settings_manager import _get_physical_memory_gb
                phys_gb, phys_avail_gb, virt_gb = _get_physical_memory_gb()
                lines.append(f"    安装内存  {phys_gb} GB")
                lines.append(f"    Windows可用物理内存  {phys_avail_gb} GB")
                lines.append(f"    虚拟内存(提交限制)  {virt_gb} GB")
                try:
                    import psutil
                    mem = psutil.virtual_memory()
                    lines.append(f"    已用  {mem.used / (1024**3):.1f} GB")
                    lines.append(f"    可用  {mem.available / (1024**3):.1f} GB")
                    lines.append(f"    使用率  {mem.percent}%")
                    mem_ok = True
                    if mem.percent > 90:
                        lines.append("    可用内存严重不足，建议关闭其他程序")
                        hardware_issues.append("可用内存不足")
                    elif mem.percent > 75:
                        lines.append("    内存使用率较高")
                except Exception:
                    pass
            except Exception:
                lines.append("    无法获取")
            lines.append("")

            lines.append("  [CPU]")
            try:
                import psutil
                cpu_count = psutil.cpu_count(logical=True)
                cpu_phys = psutil.cpu_count(logical=False)
                cpu_percent = psutil.cpu_percent(interval=0.3)
                lines.append(f"    逻辑核心  {cpu_count}")
                if cpu_phys:
                    lines.append(f"    物理核心  {cpu_phys}")
                lines.append(f"    当前占用  {cpu_percent}%")
                if cpu_percent > 80:
                    lines.append("    CPU占用过高，可能影响训练速度")
                    hardware_issues.append("CPU占用过高")
            except Exception:
                lines.append("    无法获取")
            lines.append("")

            lines.append("  [GPU]")
            gpu_ok = False
            gpu_issues = []
            try:
                import torch
                if torch.cuda.is_available():
                    gpu_ok = True
                    gpu_count = torch.cuda.device_count()
                    lines.append(f"    设备数  {gpu_count}")
                    for i in range(gpu_count):
                        name = torch.cuda.get_device_name(i)
                        prop = torch.cuda.get_device_properties(i)
                        mem_total = prop.total_memory / (1024 ** 3)
                        mem_alloc = torch.cuda.memory_allocated(i) / (1024 ** 3)
                        lines.append(f"    GPU{i}  {name}")
                        lines.append(f"        显存  {mem_total:.1f} GB  已分配 {mem_alloc:.2f} GB")
                        if mem_alloc > mem_total * 0.9:
                            gpu_issues.append(f"GPU{i} 显存几乎耗尽")
                else:
                    lines.append("    CUDA不可用 — 将使用CPU训练（速度较慢）")
                    hardware_issues.append("无可用GPU")
            except Exception:
                pass
            if not gpu_ok:
                try:
                    import subprocess
                    result = subprocess.run(
                        ["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
                         "--format=csv,noheader,nounits"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=5, text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                    if result.returncode == 0 and result.stdout.strip():
                        gpu_ok = True
                        for i, line in enumerate(result.stdout.strip().split("\n")):
                            parts = [p.strip() for p in line.split(",")]
                            if len(parts) >= 3:
                                lines.append(f"    GPU{i}  {parts[0]}")
                                lines.append(f"        显存  {int(parts[1])} MB  已用 {int(parts[2])} MB")
                except Exception:
                    pass
            if not gpu_ok:
                lines.append("    无法获取")
            lines.append("")

            lines.append("  [磁盘]")
            try:
                import psutil
                p = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                disk = psutil.disk_usage(p)
                lines.append(f"    总量  {disk.total / (1024**3):.1f} GB")
                lines.append(f"    已用  {disk.used / (1024**3):.1f} GB")
                lines.append(f"    可用  {disk.free / (1024**3):.1f} GB")
                lines.append(f"    使用率  {disk.percent}%")
                if disk.percent > 90:
                    hardware_issues.append("磁盘空间不足")
                    lines.append("    磁盘可用空间不足，建议清理")
            except Exception:
                lines.append("    无法获取")
            lines.append("")

            lines.append("▌ 04  进程信息")
            lines.append("─" * 46)
            lines.append(f"  PID  {os.getpid()}")
            try:
                import psutil
                proc = psutil.Process(os.getpid())
                lines.append(f"  内存占用  {proc.memory_info().rss / (1024**2):.1f} MB")
                create_time = datetime.datetime.fromtimestamp(proc.create_time())
                uptime = datetime.datetime.now() - create_time
                h, rem = divmod(int(uptime.total_seconds()), 3600)
                m, sec = divmod(rem, 60)
                lines.append(f"  启动时间  {create_time.strftime('%Y-%m-%d %H:%M:%S')}")
                lines.append(f"  已运行    {h}小时{m}分{sec}秒")
                lines.append(f"  线程数    {proc.num_threads()}")
            except Exception:
                lines.append("  详细进程信息无法获取")
            lines.append("")

            lines.append("▌ 05  优化建议")
            lines.append("─" * 46)
            if not gpu_ok:
                lines.append("  未检测到可用GPU，训练速度会较慢")
                lines.append("    建议：安装CUDA版PyTorch以启用GPU加速")
            if hardware_issues:
                for issue in hardware_issues:
                    ct = {
                        "可用内存不足": "关闭不必要的应用程序释放内存",
                        "CPU占用过高": "检查后台进程，降低CPU负载",
                        "磁盘空间不足": "清理临时文件和旧日志释放磁盘空间",
                        "无可用GPU": "安装CUDA版PyTorch以启用GPU加速",
                    }
                    lines.append(f"  {ct.get(issue, issue)}")
            if gpu_ok and gpu_issues:
                for gi in gpu_issues:
                    lines.append(f"  {gi}，训练可能因显存不足而失败")
                    lines.append("    建议：减小batch_size或模型尺寸，或使用gradient checkpointing")
            if not hardware_issues and not gpu_issues and gpu_ok:
                lines.append("  系统状态正常，未发现明显瓶颈。")
            train_mode = s.get("train_mode", "normal")
            if train_mode == "peft":
                lines.append("  当前使用PEFT微调模式，显存占用较小")
            else:
                lines.append("  当前使用全参数训练模式，显存占用较大")
                lines.append("    如显存不足可切换至PEFT微调模式")
            lines.append("")

            lines.append("─" * 46)
            lines.append(f"报告生成完毕 · {self.caller_name}")
            lines.append("")

            with open(log_file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            QMessageBox.information(self, "生成成功",
                f"日志文件已生成:\n{log_file}")
        except Exception as e:
            import traceback
            err_detail = traceback.format_exc()
            QMessageBox.warning(self, "生成失败",
                f"生成日志文件失败:\n{str(e)}\n\n详细信息:\n{err_detail[-500:]}")

    def _load_settings(self):
        s = self._temp

        theme_map = {"light": 0, "dark": 1, "system": 2}
        self.cb_theme.setCurrentIndex(theme_map.get(s.get("theme", "light"), 0))
        self.chk_autolayout.setChecked(s.get("auto_layout", True))
        self.chk_snap_grid.setChecked(s.get("snap_grid", True))
        _snap_val = s.get("snap_threshold", 10)
        self.sl_snap.setValue(_snap_val)
        self.ed_snap_val.setText(str(_snap_val))
        self.chk_minimize.setChecked(s.get("minimize_others", True))
        self._on_autolayout_changed(Qt.Checked if self.chk_autolayout.isChecked() else Qt.Unchecked)

        self.chk_restore.setChecked(s.get("restore_layout", True))

        tm_map = {"normal": 0, "peft": 1}
        self.cb_train_mode.setCurrentIndex(tm_map.get(s.get("train_mode", "normal"), 0))
        # 训练架构
        ta_map = {"cuda": 0, "directml": 1, "cpu": 2}
        _ta_idx = ta_map.get(s.get("train_arch", "cuda"), 0)
        # 如果选中的架构不可用（被禁用），回退到 CPU
        if not self.cb_train_arch.model().item(_ta_idx).isEnabled():
            _ta_idx = 2
        self.cb_train_arch.setCurrentIndex(_ta_idx)
        self.chk_debug.setChecked(s.get("debug_mode", False))

        # GPU 设备模式已合并到训练架构，compute_backend 由 train_arch 推导

        # DML 挂载卡选择（保存索引）
        _dml_idx = int(s.get("dml_device_index", 0))
        if _dml_idx < self.cb_dml_device.count():
            self.cb_dml_device.setCurrentIndex(_dml_idx)
        # 触发架构切换以更新 UI（标签/范围/单位）
        self._on_train_arch_changed()

        # 温度保护
        temp_val = int(s.get("gpu_temp_protection", 80))
        temp_val = max(75, min(95, temp_val))
        self.sl_temp.setValue(temp_val)
        self.ed_temp_val.setText(f"{temp_val}°C")
        self._lbl_temp_warn.setVisible(temp_val >= 85)

        m_map = {"vit_b_16": 0, "vit_l_16": 1, "vit_h_14": 2,
                 "deit_b_16": 3, "deit_s_16": 4, "deit_t_16": 5}
        self.cb_model.blockSignals(True)
        self.cb_model.setCurrentIndex(m_map.get(s.get("model_arch", "vit_b_16"), 0))
        self._update_model_availability()
        self.cb_model.blockSignals(False)
        self.sl_dropout.setValue(int(s.get("dropout", 0.2) * 100))
        self.cb_lora.setCurrentText(str(s.get("lora_rank", 8)))

        from utils.settings_manager import get_hardware_cache
        hw_cache = get_hardware_cache()

        # 自动配置总开关
        auto_alloc = s.get("auto_resource_alloc", True)
        self.chk_auto_alloc.blockSignals(True)
        self.chk_auto_alloc.setChecked(auto_alloc)
        self.chk_auto_alloc.blockSignals(False)

        # 性能挡位
        perf_level = s.get("perf_level", "balanced")
        level_map = {"light": 0, "balanced": 1, "extreme": 2}
        self.cb_perf_level.blockSignals(True)
        self.cb_perf_level.setCurrentIndex(level_map.get(perf_level, 1))
        self.cb_perf_level.blockSignals(False)

        # 手动值（从配置恢复 Slider 值，auto 时由联动逻辑禁用）
        gpu_val = s.get("gpu_memory", "auto")
        if gpu_val not in ("auto", None):
            self.sl_gpu.setValue(int(gpu_val))
        mem_val = s.get("sys_memory", "auto")
        if mem_val not in ("auto", None):
            self.sl_mem.setValue(int(mem_val))
        nw_val = s.get("num_workers", "auto")
        if nw_val not in ("auto", None):
            self.sl_workers.setValue(int(nw_val))

        # 触发联动（设置启用/禁用状态和标签文本）
        self._on_auto_alloc_changed(Qt.Checked if auto_alloc else Qt.Unchecked)

        mp_map = {"fp16": 0, "fp32": 1, "bf16": 2}
        self.cb_mixed.blockSignals(True)
        self.cb_mixed.setCurrentIndex(mp_map.get(s.get("mixed_precision", "fp16"), 0))
        self.cb_mixed.blockSignals(False)
        self.sl_grad.setValue(s.get("grad_accum", 1))

        # 训练器自动保存格式（.mbtl / .mbtlx；.pth 由训练完成时自动保存）
        t_afmts = s.get("trainer_auto_save_formats", ["mbtl", "mbtlx"])
        if not isinstance(t_afmts, list):
            t_afmts = ["mbtl", "mbtlx"]
        self._temp["trainer_auto_save_formats"] = t_afmts
        if "all" in t_afmts:
            self.chk_trainer_auto_all.setChecked(True)
            self.chk_trainer_auto_mbtl.setChecked(True)
            self.chk_trainer_auto_mbtlx.setChecked(True)
        else:
            self.chk_trainer_auto_mbtl.setChecked("mbtl" in t_afmts)
            self.chk_trainer_auto_mbtlx.setChecked("mbtlx" in t_afmts)
            self.chk_trainer_auto_all.setChecked(
                self.chk_trainer_auto_mbtl.isChecked() and
                self.chk_trainer_auto_mbtlx.isChecked()
            )
        # 训练器手动保存格式（.pth / .mbtl / .mbtlx）；兼容旧版 save_format 单值
        mfmts = s.get("trainer_save_formats")
        if not isinstance(mfmts, list):
            old_sf = s.get("save_format", "pth")
            mfmts = [old_sf] if old_sf else ["pth", "mbtl", "mbtlx"]
        self._temp["trainer_save_formats"] = mfmts
        if "all" in mfmts:
            self.chk_manual_fmt_all.setChecked(True)
            for chk in (self.chk_manual_fmt_pth, self.chk_manual_fmt_mbtl, self.chk_manual_fmt_mbtlx):
                chk.setChecked(True)
        else:
            self.chk_manual_fmt_pth.setChecked("pth" in mfmts)
            self.chk_manual_fmt_mbtl.setChecked("mbtl" in mfmts)
            self.chk_manual_fmt_mbtlx.setChecked("mbtlx" in mfmts)
            self.chk_manual_fmt_all.setChecked(
                self.chk_manual_fmt_pth.isChecked() and
                self.chk_manual_fmt_mbtl.isChecked() and
                self.chk_manual_fmt_mbtlx.isChecked()
            )
        # 训练器保存路径
        auto_trainer_p = s.get("auto_save_trainer_path", "saves/auto_save/trainer")
        self.le_auto_save_trainer_path.setText(auto_trainer_p)
        manual_trainer_p = s.get("manual_save_trainer_path", "saves/manual_save/trainer")
        self.le_manual_save_trainer_path.setText(manual_trainer_p)

        _min_kb = s.get("import_min_size_kb", 200)
        _max_mb = s.get("import_max_size_mb", 5)
        self.le_image_size.setText(self._format_size_range(_min_kb, _max_mb))
        # 导入器保存路径
        auto_loader_p = s.get("auto_save_loader_path", "saves/auto_save/loader")
        self.le_auto_save_loader_path.setText(auto_loader_p)
        manual_loader_p = s.get("manual_save_loader_path", "saves/manual_save/loader")
        self.le_manual_save_loader_path.setText(manual_loader_p)
        self.chk_auto_preview.setChecked(s.get("auto_preview_import", True))
        # 导入器自动保存格式（.mbtl / .mbtlx）
        i_afmts = s.get("importer_auto_save_formats", ["mbtl", "mbtlx"])
        if not isinstance(i_afmts, list):
            i_afmts = ["mbtl", "mbtlx"]
        self._temp["importer_auto_save_formats"] = i_afmts
        if "all" in i_afmts:
            self.chk_imp_auto_all.setChecked(True)
            self.chk_imp_auto_mbtl.setChecked(True)
            self.chk_imp_auto_mbtlx.setChecked(True)
        else:
            self.chk_imp_auto_mbtl.setChecked("mbtl" in i_afmts)
            self.chk_imp_auto_mbtlx.setChecked("mbtlx" in i_afmts)
            self.chk_imp_auto_all.setChecked(
                self.chk_imp_auto_mbtl.isChecked() and
                self.chk_imp_auto_mbtlx.isChecked()
            )
        # 导入器手动保存格式（.mbtl / .mbtlx）
        i_mfmts = s.get("importer_save_formats", ["mbtl", "mbtlx"])
        if not isinstance(i_mfmts, list):
            i_mfmts = ["mbtl", "mbtlx"]
        self._temp["importer_save_formats"] = i_mfmts
        if "all" in i_mfmts:
            self.chk_imp_manual_all.setChecked(True)
            self.chk_imp_manual_mbtl.setChecked(True)
            self.chk_imp_manual_mbtlx.setChecked(True)
        else:
            self.chk_imp_manual_mbtl.setChecked("mbtl" in i_mfmts)
            self.chk_imp_manual_mbtlx.setChecked("mbtlx" in i_mfmts)
            self.chk_imp_manual_all.setChecked(
                self.chk_imp_manual_mbtl.isChecked() and
                self.chk_imp_manual_mbtlx.isChecked()
            )

        # 识别器设置
        self.chk_rev_auto_load.setChecked(s.get("reverser_auto_load_model", False))
        dev_map = {"auto": 0, "cpu": 1, "cuda": 2, "directml": 3}
        self.cb_rev_device.setCurrentIndex(dev_map.get(s.get("reverser_default_device", "auto"), 0))

        ll_map = {"off": 0, "error": 1, "warning": 2, "info": 3, "debug": 4}
        self.cb_log_level.setCurrentIndex(ll_map.get(s.get("log_level", "info"), 3))
        self.chk_log_sys.setChecked(s.get("log_system", True))
        self.chk_log_op.setChecked(s.get("log_operation", False))
        self.chk_log_data.setChecked(s.get("log_data", True))
        self.chk_log_train.setChecked(s.get("log_training", True))
        self.chk_log_model.setChecked(s.get("log_model", True))
        self.chk_log_err.setChecked(s.get("log_error", True))
        self.chk_log_perf.setChecked(s.get("log_performance", False))

        log_p = s.get("log_path", "default")
        if log_p == "default":
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            log_p = os.path.join(app_dir, "log")
        self.le_log_path.setText(log_p)

        asv_map = {0: 0, 5: 1, 10: 2, 30: 3}
        val = s.get("auto_save_interval", 10)
        self.cb_autosave.setCurrentIndex(asv_map.get(val, 2) if isinstance(val, int) else 0)
        # 保存格式已拆分到训练器/导入器各自设置页

    def _collect_settings(self):
        theme_map = ["light", "dark", "system"]
        result = {
            "theme": theme_map[self.cb_theme.currentIndex()],
            "auto_layout": self.chk_autolayout.isChecked(),
            "minimize_others": self.chk_minimize.isChecked(),
            "restore_layout": self.chk_restore.isChecked(),
            "snap_enabled": self.chk_autolayout.isChecked(),
            "snap_threshold": self.sl_snap.value(),
            "snap_grid": self.chk_snap_grid.isChecked(),
            "train_mode": ["normal", "peft"][self.cb_train_mode.currentIndex()],
            "train_arch": ["cuda", "directml", "cpu"][self.cb_train_arch.currentIndex()],
            "debug_mode": self.chk_debug.isChecked(),
            # compute_backend 由训练架构自动推导（GPU设备已合并）
            "compute_backend": {"cuda": "discrete", "directml": "integrated", "cpu": "cpu"}[
                ["cuda", "directml", "cpu"][self.cb_train_arch.currentIndex()]
            ],
            "dml_device_index": self.cb_dml_device.currentIndex(),
            "gpu_temp_protection": self.sl_temp.value(),
            "model_arch": self._arch_keys[self.cb_model.currentIndex()] if self.cb_model.currentIndex() < len(self._arch_keys) else "vit_b_16",
            "dropout": self.sl_dropout.value() / 100.0,
            "lora_rank": int(self.cb_lora.currentText()),
            "auto_resource_alloc": self.chk_auto_alloc.isChecked(),
            "perf_level": ["light", "balanced", "extreme"][self.cb_perf_level.currentIndex()],
            "gpu_memory": "auto" if self.chk_auto_alloc.isChecked() else self.sl_gpu.value(),
            "sys_memory": "auto" if self.chk_auto_alloc.isChecked() else self.sl_mem.value(),
            "mixed_precision": ["fp16", "fp32", "bf16"][self.cb_mixed.currentIndex()],
            "grad_accum": self.sl_grad.value(),
            "num_workers": "auto" if self.chk_auto_alloc.isChecked() else self.sl_workers.value(),
            "log_training": self.chk_log_train.isChecked(),
            "log_model": self.chk_log_model.isChecked(),
            "log_error": self.chk_log_err.isChecked(),
            # 训练器自动保存格式（.mbtl / .mbtlx；.pth 由训练完成时自动保存）
            "trainer_auto_save_formats": [fmt for fmt, chk in (
                ("mbtl", self.chk_trainer_auto_mbtl),
                ("mbtlx", self.chk_trainer_auto_mbtlx),
            ) if chk.isChecked()] or ["mbtl"],
            # 训练器手动保存格式（.pth / .mbtl / .mbtlx）
            "trainer_save_formats": [fmt for fmt, chk in (
                ("pth", self.chk_manual_fmt_pth),
                ("mbtl", self.chk_manual_fmt_mbtl),
                ("mbtlx", self.chk_manual_fmt_mbtlx),
            ) if chk.isChecked()] or ["pth"],
            # 导入器自动保存格式（.mbtl / .mbtlx）
            "importer_auto_save_formats": [fmt for fmt, chk in (
                ("mbtl", self.chk_imp_auto_mbtl),
                ("mbtlx", self.chk_imp_auto_mbtlx),
            ) if chk.isChecked()] or ["mbtl"],
            # 导入器手动保存格式（.mbtl / .mbtlx）
            "importer_save_formats": [fmt for fmt, chk in (
                ("mbtl", self.chk_imp_manual_mbtl),
                ("mbtlx", self.chk_imp_manual_mbtlx),
            ) if chk.isChecked()] or ["mbtl"],
            "import_min_size_kb": self._parse_size_range(self.le_image_size.text())[0],
            "import_max_size_mb": self._parse_size_range(self.le_image_size.text())[1],
            "auto_preview_import": self.chk_auto_preview.isChecked(),
            "reverser_auto_load_model": self.chk_rev_auto_load.isChecked(),
            "reverser_default_device": ["auto", "cpu", "cuda", "directml"][self.cb_rev_device.currentIndex()],
        }

        # 保存路径
        result["auto_save_trainer_path"] = self.le_auto_save_trainer_path.text().strip() or "saves/auto_save/trainer"
        result["manual_save_trainer_path"] = self.le_manual_save_trainer_path.text().strip() or "saves/manual_save/trainer"
        result["auto_save_loader_path"] = self.le_auto_save_loader_path.text().strip() or "saves/auto_save/loader"
        result["manual_save_loader_path"] = self.le_manual_save_loader_path.text().strip() or "saves/manual_save/loader"

        ll_map = ["off", "error", "warning", "info", "debug"]
        result["log_level"] = ll_map[self.cb_log_level.currentIndex()]
        result["log_system"] = self.chk_log_sys.isChecked()
        result["log_operation"] = self.chk_log_op.isChecked()
        result["log_data"] = self.chk_log_data.isChecked()
        result["log_performance"] = self.chk_log_perf.isChecked()
        log_p = self.le_log_path.text() or "default"
        default_data = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "log")
        result["log_path"] = "default" if log_p == default_data else log_p

        asv_vals = [0, 5, 10, 30]
        result["auto_save_interval"] = asv_vals[self.cb_autosave.currentIndex()]
        # 保存格式已拆分到训练器/导入器各自设置项
        return result

    def _on_ok(self):
        new_settings = self._collect_settings()
        self.sm.set_all(new_settings)
        self.sm.save()
        # 通知启动器：主题已保存，start 主窗口立即跟随刷新（无需重启）
        try:
            sig = os.path.join(tempfile.gettempdir(), "_banner_theme_changed")
            with open(sig, "w", encoding="utf-8") as f:
                f.write(str(new_settings.get("theme", "light")))
        except Exception:
            pass

        changed = []
        for k in self.RESTART_KEYS:
            old_v = self._temp.get(k)
            new_v = new_settings.get(k)
            if str(old_v) != str(new_v):
                changed.append(k)

        # start 单独打开时：修改直接保存，无需重启提示（重启仅针对训练器/导入器/识别器场景）
        if changed and self.caller_name != "start":
            labels = {
                "train_mode": "训练模式", "train_arch": "训练架构", "debug_mode": "调试模式",
                "model_arch": "模型架构", "dropout": "Dropout率",
                "lora_rank": "LoRA秩(r)", "gpu_memory": "分配显存",
                "sys_memory": "分配内存", "mixed_precision": "混合精度训练",
                "grad_accum": "梯度累积步数", "num_workers": "数据加载器工作数",
                "gpu_temp_protection": "温度保护",
            }
            changed_names = [labels.get(k, k) for k in changed]
            msg = "以下设置需要重启才能生效：\n\n  " + "\n  ".join(changed_names)
            msg += "\n\n要现在立即重启吗？"
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Question)
            msg_box.setWindowTitle("需要重启")
            msg_box.setText(msg)
            msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg_box.setDefaultButton(QMessageBox.Yes)
            msg_box.show()
            _theme = self._resolve_theme(self._temp.get("theme", "light"))
            apply_dwm_dark_mode(msg_box, _theme == "dark")
            reply = msg_box.exec_()
            if reply == QMessageBox.Yes:
                # 退出码 100 = 请求父进程重启
                self.done(EXIT_RESTART)
                return
            else:
                # 选 No：回滚 RESTART_KEYS 的修改，恢复旧值
                for k in changed:
                    self.sm.set(k, self._temp.get(k))
                self.sm.save()

        self.done(EXIT_OK)


if __name__ == "__main__":
    main()
