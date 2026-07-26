"""旗帜工具启动器

统一入口，四宫格布局，启动各功能模块：
  - 旗帜训练器（trainer.pyw，自动联动导入器）
  - 旗帜识别器（bdor.pyw）
  - 设置（utils/settings_dialog.py）
  - 帮助（help.pyw）

支持深浅色模式和自适应缩放。
单实例限制。
程序互斥：训练器与识别器不可同时运行，启动一方时会关闭另一方。
特例：帮助和设置可与任何程序共存。
"""

import os
import sys
import json
import glob
import time
import ctypes
import tempfile
import subprocess

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QPushButton,
    QVBoxLayout, QLabel, QMessageBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from utils.settings_manager import apply_dwm_dark_mode, apply_theme, resolve_theme


# ===== 单实例限制 =====
_START_MUTEX_NAME = "Global\\BannerToolStartSingleInstance"


def _ensure_single_instance():
    """用全局 Mutex 保证 start 窗口只能打开一个。返回 True 表示是首个实例。"""
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, _START_MUTEX_NAME)
    already_exists = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    if already_exists:
        kernel32.CloseHandle(mutex)
        return False
    _ensure_single_instance._mutex = mutex  # 保持引用防止 GC 释放
    return True


# ===== 程序互斥检查 =====
_TRAINER_LOCK_PATTERN = "banner_group_lock_*.lock"
_REVERSER_LOCK_PREFIX = "banner_reverser_lock_"
_SETTINGS_MUTEX_NAME = "Global\\BannerToolSettingsSingleInstance"
_HELP_MUTEX_NAME = "Global\\BannerToolHelpSingleInstance"


def _check_mutex_exists(mutex_name):
    """检查指定名称的全局 Mutex 是否存在。"""
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    already_exists = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    kernel32.CloseHandle(mutex)
    return already_exists


def _check_settings_running():
    """检查设置窗口是否在运行。"""
    return _check_mutex_exists(_SETTINGS_MUTEX_NAME)


def _check_help_running():
    """检查帮助窗口是否在运行。"""
    return _check_mutex_exists(_HELP_MUTEX_NAME)


def _minimize_help_windows():
    """最小化所有帮助窗口（通过枚举窗口查找标题匹配的窗口）。"""
    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    SW_MINIMIZE = 6
    help_titles = ["旗帜训练工具 — 使用说明", "旗帜训练工具 - 使用说明"]

    def _enum_callback(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if any(t in title for t in help_titles):
                    user32.ShowWindow(hwnd, SW_MINIMIZE)
        return True

    user32.EnumWindows(EnumWindowsProc(_enum_callback), 0)


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


def _check_trainer_running():
    """检查训练器/导入器是否在运行。"""
    lock_files = glob.glob(os.path.join(tempfile.gettempdir(), _TRAINER_LOCK_PATTERN))
    for lf in lock_files:
        try:
            with open(lf, "r") as f:
                pid = int(f.read().strip())
            if _is_pid_alive(pid):
                return True, pid
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
    return False, None


def _check_recognizer_running():
    """检查旗帜识别器是否在运行。"""
    lock_files = glob.glob(os.path.join(tempfile.gettempdir(), _REVERSER_LOCK_PREFIX + "*.lock"))
    for lf in lock_files:
        try:
            with open(lf, "r") as f:
                pid = int(f.read().strip())
            if _is_pid_alive(pid):
                return True, pid
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
    return False, None


def _close_program_by_pid(pid, timeout=30):
    """通过发送 WM_CLOSE 关闭指定进程，等待最多 timeout 秒。"""
    WM_CLOSE = 0x0010
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # 枚举所有窗口，找到属于该 PID 的窗口并发送 WM_CLOSE
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    found_hwnd = []

    def _enum_callback(hwnd, lparam):
        pid_buf = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
        if pid_buf.value == pid and user32.IsWindowVisible(hwnd):
            found_hwnd.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(_enum_callback), 0)

    for hwnd in found_hwnd:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

    # 等待进程退出
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not _is_pid_alive(pid):
            return True
        time.sleep(0.3)
    return not _is_pid_alive(pid)


def _get_theme():
    """读取 config/config.json 的 theme 设置，返回 'dark' 或 'light'。"""
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "config", "config.json"
        )
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return resolve_theme(data.get("theme", "light"))
    except Exception:
        pass
    return "light"


def _detect_scale():
    """从屏幕分辨率检测缩放比例（与训练器/导入器完全一致的算法）。"""
    screen = QApplication.primaryScreen()
    geo = screen.availableGeometry() if screen else None
    sw = geo.width() if geo else 1920
    sh = geo.height() if geo else 1080
    ui_scale = max(min(sw / 1920, sh / 1080), 1.0)
    return min(ui_scale * 1.25, 2.5)


class _TileButton(QPushButton):
    """四宫格按钮，图标在上、文字在下。"""

    def __init__(self, title, subtitle, icon_char, scale, is_dark, parent=None):
        super().__init__(parent)
        self._scale = scale
        self._is_dark = is_dark
        self.setFixedSize(int(240 * scale), int(200 * scale))
        self.setCursor(Qt.PointingHandCursor)

        # 布局：图标 + 标题 + 副标题
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        icon_size = int(56 * scale)
        layout.setSpacing(int(6 * scale))
        layout.setContentsMargins(int(16 * scale), int(20 * scale),
                                  int(16 * scale), int(16 * scale))

        # 占位符图标
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(icon_size, icon_size)
        accent = '#4fc3f7' if is_dark else '#1a73e8'
        icon_label.setText(icon_char)
        icon_label.setStyleSheet(f"font-size: {icon_size}px; color: {accent}; background: transparent; border: none;")
        layout.addWidget(icon_label)

        # 标题
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(f"font-size: {max(int(15 * scale), 13)}px; font-weight: bold; color: {'#e0e0e0' if is_dark else '#1a1a1a'}; background: transparent; border: none;")
        layout.addWidget(title_label)

        # 副标题
        sub_label = QLabel(subtitle)
        sub_label.setAlignment(Qt.AlignCenter)
        sub_label.setStyleSheet(f"font-size: {max(int(11 * scale), 10)}px; color: {'#888888' if is_dark else '#666666'}; background: transparent; border: none;")
        layout.addWidget(sub_label)

        self._apply_style()

    def _apply_style(self):
        s = self._scale
        radius = int(10 * s)
        if self._is_dark:
            bg = "#2d2d2d"
            bg_hover = "#383838"
            border = "#404040"
            border_hover = "#4fc3f7"
        else:
            bg = "#ffffff"
            bg_hover = "#f0f6ff"
            border = "#d0d0d0"
            border_hover = "#1a73e8"
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
                text-align: center;
            }}
            QPushButton:hover {{
                background-color: {bg_hover};
                border: 2px solid {border_hover};
            }}
            QPushButton:pressed {{
                background-color: {bg_hover};
                border: 1px solid {border_hover};
            }}
        """)


class StartWindow(QMainWindow):
    """启动器主窗口。"""

    def __init__(self, scale, theme):
        super().__init__()
        self._scale = scale
        self._theme = theme
        self._is_dark = (theme == "dark")

        self.setWindowTitle("旗帜工具")

        # 窗口尺寸
        win_w = int(580 * scale)
        win_h = int(620 * scale)
        self.setFixedSize(win_w, win_h)
        self.setMinimumSize(win_w, win_h)

        # 居中显示
        self._center_on_screen()

        # 中央部件
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(int(24 * scale), int(24 * scale),
                                       int(24 * scale), int(24 * scale))
        main_layout.setSpacing(int(16 * scale))

        # 标题
        title_label = QLabel("旗帜工具")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(f"font-size: {max(int(24 * scale), 20)}px; font-weight: bold; color: {'#e0e0e0' if self._is_dark else '#1a1a1a'}; background: transparent;")
        main_layout.addWidget(title_label)

        sub_label = QLabel("选择要启动的功能")
        sub_label.setAlignment(Qt.AlignCenter)
        sub_label.setStyleSheet(f"font-size: {max(int(13 * scale), 12)}px; color: {'#888888' if self._is_dark else '#666666'}; background: transparent;")
        main_layout.addWidget(sub_label)

        main_layout.addSpacing(int(8 * scale))

        # 四宫格
        grid_container = QWidget()
        grid_layout = QGridLayout(grid_container)
        grid_layout.setSpacing(int(12 * scale))
        grid_layout.setContentsMargins(0, 0, 0, 0)

        tiles_config = [
            ("旗帜训练器", "训练 AI 模型", "⚙", self._launch_trainer, 0, 0),
            ("旗帜识别器", "逆向识别旗帜", "◎", self._launch_recognizer, 0, 1),
            ("设置", "配置工具参数", "☰", self._launch_settings, 1, 0),
            ("帮助", "查看使用说明", "?", self._launch_help, 1, 1),
        ]

        for title, subtitle, icon_char, callback, row, col in tiles_config:
            tile = _TileButton(title, subtitle, icon_char, scale, self._is_dark)
            tile.clicked.connect(callback)
            grid_layout.addWidget(tile, row, col)

        main_layout.addWidget(grid_container, 1)

        # 底部提示
        hint_label = QLabel("启动后本窗口最小化，关闭程序后可恢复")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setStyleSheet(f"font-size: {max(int(11 * scale), 10)}px; color: {'#666666' if self._is_dark else '#999999'}; background: transparent;")
        main_layout.addWidget(hint_label)

        # 应用窗口样式
        self._apply_window_style()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)

    def _apply_window_style(self):
        if self._is_dark:
            bg = "#1e1e1e"
        else:
            bg = "#f5f5f5"
        self.setStyleSheet(f"QMainWindow {{ background-color: {bg}; }}")

    def _ensure_other_closed(self, other_name, check_func):
        """确保另一个程序已关闭。如果在运行则提示用户确认关闭。

        返回 True 表示可以继续启动，False 表示取消。
        """
        running, pid = check_func()
        if not running:
            return True

        reply = QMessageBox.question(
            self, "程序互斥",
            f"{other_name}正在运行。\n启动新程序前需要先关闭 {other_name}（关闭前会弹出保存确认）。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return False

        # 关闭另一个程序
        success = _close_program_by_pid(pid, timeout=60)
        if not success:
            QMessageBox.warning(self, "关闭失败",
                f"等待 {other_name} 关闭超时。\n请手动关闭后重试。")
            return False

        # 再确认一次已经关闭
        running2, _ = check_func()
        if running2:
            QMessageBox.warning(self, "关闭失败",
                f"{other_name} 仍在运行，无法启动新程序。")
            return False

        return True

    def _launch_trainer(self):
        """启动旗帜训练器（会自动联动导入器）。"""
        # 互斥检查：设置在运行则提醒
        if _check_settings_running():
            QMessageBox.information(self, "请先完成设置",
                "设置窗口正在运行。\n请完成设置后再启动训练器。")
            return
        # 互斥检查：识别器在运行则先关闭
        if not self._ensure_other_closed("旗帜识别器", _check_recognizer_running):
            return

        # 最小化帮助窗口（防止对加载的干扰）
        _minimize_help_windows()

        trainer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trainer.pyw")
        try:
            subprocess.Popen([sys.executable, trainer_path])
            self.showMinimized()  # 启动后最小化
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"启动训练器失败:\n{e}")

    def _launch_recognizer(self):
        """启动旗帜识别器。"""
        # 互斥检查：设置在运行则提醒
        if _check_settings_running():
            QMessageBox.information(self, "请先完成设置",
                "设置窗口正在运行。\n请完成设置后再启动识别器。")
            return
        # 互斥检查：训练器在运行则先关闭
        if not self._ensure_other_closed("旗帜训练器", _check_trainer_running):
            return

        # 最小化帮助窗口（防止对加载的干扰）
        _minimize_help_windows()

        bdor_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bdor.pyw")
        try:
            subprocess.Popen([sys.executable, bdor_path])
            self.showMinimized()  # 启动后最小化
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"启动识别器失败:\n{e}")

    def _launch_settings(self):
        """启动设置窗口。"""
        # 互斥检查：训练器/识别器在运行则提醒
        trainer_running, _ = _check_trainer_running()
        if trainer_running:
            QMessageBox.information(self, "请先关闭训练器",
                "旗帜训练器正在运行。\n请先关闭训练器后再打开设置。")
            return
        recognizer_running, _ = _check_recognizer_running()
        if recognizer_running:
            QMessageBox.information(self, "请先关闭识别器",
                "旗帜识别器正在运行。\n请先关闭识别器后再打开设置。")
            return

        settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "settings_dialog.py")
        try:
            subprocess.Popen([sys.executable, settings_path,
                              "--caller", "trainer", "--scale", str(self._scale)])
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"启动设置失败:\n{e}")

    def _launch_help(self):
        """启动帮助窗口（特例：可与任何程序共存）。"""
        help_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "help.pyw")
        try:
            subprocess.Popen([sys.executable, help_path, "--scale", str(self._scale)])
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"启动帮助失败:\n{e}")


def main():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    # 单实例限制
    if not _ensure_single_instance():
        ctypes.windll.user32.MessageBoxW(
            0, "旗帜工具已经在运行，请先关闭已有的窗口。",
            "提示", 64  # MB_ICONINFORMATION
        )
        return

    app = QApplication(sys.argv)
    app.setApplicationName("旗帜工具")
    app.setFont(QFont("Microsoft YaHei UI", app.font().pointSize()))

    scale = _detect_scale()
    theme = _get_theme()
    apply_theme(app, theme)

    window = StartWindow(scale, theme)
    apply_dwm_dark_mode(window, theme == "dark")
    window.show()

    exit_code = app.exec_()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
