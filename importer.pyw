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
# 【双环境隔离】UI 渲染固定由主 Python 环境（3.13+）执行。
# dml_env（3.10）只负责 AI 数据处理，绝不参与 UI 启动，不读取其 site-packages。
_VENDOR_PKGS = os.path.join(_APP_DIR, "Lib", "site-packages")
if os.path.isdir(_VENDOR_PKGS):
    sys.path.insert(0, _VENDOR_PKGS)

# Qt 平台插件引导：确保 pythonw.exe 启动时能找到 qwindows.dll 和 Qt5Core.dll 等
# 优先 vendor 目录（安装器通过 pip --target 落地的 PyQt5），找不到就回退到系统级 site-packages。
# 这样无论开发环境还是发布后安装目录，都不会出现 "no Qt platform plugin could be initialized"。
_qt5_dir = os.path.join(_VENDOR_PKGS, "PyQt5", "Qt5")
if not os.path.isdir(_qt5_dir):
    for _sp in sys.path:
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
                       creationflags=_sp_mod.CREATE_NO_WINDOW | _sp_mod.DETACHED_PROCESS,
                       cwd=_APP_DIR)
    except Exception:
        try:
            import ctypes as _ct_fb
            _ct_fb.windll.user32.MessageBoxW(0,
                f"【导入器崩溃】\n{tb_str[:1500]}\n\n完整日志:\n{_err}",
                "我的世界旗帜逆向套件 - 导入器崩溃", 16)
        except Exception:
            pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)
sys.excepthook = _early_crash_handler

import time
import random
import subprocess
import ctypes
import glob
import tempfile
import uuid
import configparser
import traceback
import json
import zipfile
import shutil

# PyQt5 导入硬保护
try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QSpinBox, QGroupBox, QAction,
        QGridLayout, QMessageBox,
        QListWidget, QFileDialog, QSizePolicy,
        QScrollArea, QTreeWidget, QTreeWidgetItem, QCheckBox,
        QFrame, QDialog, QRadioButton, QButtonGroup,
        QSplitter, QTabWidget, QComboBox, QTextEdit, QListWidgetItem, QLineEdit
    )
    from PyQt5.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QFont, QIcon, QKeySequence
    from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, QFileSystemWatcher, QEvent
except Exception as _e_pyqt:
    _VENDOR = os.path.join(_APP_DIR, "Lib", "site-packages")
    _msg = (
        "【导入器无法启动】缺少 UI 运行库 PyQt5。\n\n"
        f"详细错误: {type(_e_pyqt).__name__}: {_e_pyqt}\n\n"
        f"工作目录: {os.getcwd()}\n"
        f"安装目录(APP_DIR): {_APP_DIR}\n"
        f"vendor PyQt5: {os.path.join(_VENDOR, 'PyQt5')}\n"
        "vendor目录是否存在: " + ("是" if os.path.isdir(_VENDOR) else "否") + "\n\n"
        "修复建议:\n"
        "1. 请通过启动器(start.pyw)启动本套件，勿直接双击本文件；\n"
        "2. 或重新运行安装程序，确认完成「主Python+PyQt5」组件安装。"
    )
    try:
        import ctypes as _ct
        _ct.windll.user32.MessageBoxW(0, _msg, "我的世界旗帜逆向套件 - 启动失败", 16)
    except Exception:
        print(_msg, file=sys.stderr)
    sys.exit(1)

from utils.banner_utils import (
    color, color_name, type as banner_type, type_zh,
    generate_banner_image
)
from utils.mbtl_utils import write_mbtl, load_banners_from_file
from utils.mbtlx_utils import export_mbtlx, import_mbtlx
from utils.settings_manager import SettingsManager, apply_theme, HardwareDetectThread, grade_gpu_memory, grade_system_memory, load_hardware_cache, save_hardware_cache, resolve_theme, load_workspace, save_workspace_section, clear_workspace_window, apply_dwm_dark_mode, build_arch_cache, resolve_app_path, report_error, show_about_dialog, MessageBox


class _win_POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class _win_RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

class _win_MINMAXINFO(ctypes.Structure):
    _fields_ = [
        ("ptReserved", _win_POINT),
        ("ptMaxSize", _win_POINT),
        ("ptMaxPosition", _win_POINT),
        ("ptMinTrackSize", _win_POINT),
        ("ptMaxTrackSize", _win_POINT),
    ]


def _double_snap(hwnd, direction):
    user32 = ctypes.windll.user32
    vk = 0x25 if direction == "left" else 0x27
    import winreg
    import time
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
    saved_flyout = 1
    reg_ok = False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                             winreg.KEY_READ | winreg.KEY_WRITE)
        try:
            saved_flyout, _ = winreg.QueryValueEx(key, "EnableSnapAssistFlyout")
        except OSError:
            pass
        if saved_flyout != 0:
            winreg.SetValueEx(key, "EnableSnapAssistFlyout", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            shell_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
            if shell_hwnd:
                user32.SendMessageW(shell_hwnd, 0x001A, 0, 0)
            time.sleep(0.03)
            reg_ok = True
        else:
            winreg.CloseKey(key)
    except OSError:
        pass
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x5B, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)
    user32.keybd_event(0x5B, 0, 2, 0)
    time.sleep(0.02)
    user32.keybd_event(0x1B, 0, 0, 0)
    user32.keybd_event(0x1B, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x5B, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)
    user32.keybd_event(0x5B, 0, 2, 0)
    if reg_ok:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "EnableSnapAssistFlyout", 0, winreg.REG_DWORD, saved_flyout)
            winreg.CloseKey(key)
            shell_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
            if shell_hwnd:
                user32.SendMessageW(shell_hwnd, 0x001A, 0, 0)
        except OSError:
            pass


def _force_activate(hwnd, window):
    user32 = ctypes.windll.user32
    user32.SetForegroundWindow(hwnd)
    window.raise_()
    window.activateWindow()
    if not window.isActiveWindow():
        user32.SetForegroundWindow(hwnd)
        window.raise_()
        window.activateWindow()


def _is_window_snapped(hwnd):
    """判断窗口当前是否处于 Windows snap 半屏状态。"""
    try:
        from PyQt5.QtWidgets import QApplication
        user32 = ctypes.windll.user32
        rect = ctypes.wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        wx, wy, ww, wh = rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        screen = QApplication.primaryScreen()
        if screen is None:
            return False
        vg = screen.availableGeometry()
        sw, sh = vg.width(), vg.height()
        sx, sy = vg.left(), vg.top()
        # 半屏宽度/高度（允许 10px 误差）
        half_w = sw // 2
        is_half_width = abs(ww - half_w) <= 10
        is_full_height = abs(wh - sh) <= 10
        is_left = abs(wx - sx) <= 10
        is_right = abs(wx - (sx + half_w)) <= 10
        return is_half_width and is_full_height and (is_left or is_right)
    except Exception:
        return False


def _check_reverser_running():
    """检查旗帜印染逆向器是否在运行（互斥阻拦）。"""
    import glob
    lock_files = glob.glob(os.path.join(tempfile.gettempdir(), "banner_reverser_lock_*.lock"))
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
                    return True
            else:
                try:
                    os.remove(lf)
                except Exception:
                    pass
        except Exception:
            pass
    return False


def _get_process_create_time(pid):
    """获取进程创建时间（FILETIME 格式），用于唯一标识进程实例。"""
    try:
        handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        if not handle:
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            import ctypes.wintypes as wt
            creation = wt.FILETIME()
            exit_t = wt.FILETIME()
            kernel = wt.FILETIME()
            user = wt.FILETIME()
            ok = ctypes.windll.kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_t), ctypes.byref(kernel), ctypes.byref(user))
            ctypes.windll.kernel32.CloseHandle(handle)
            if ok:
                return (creation.dwLowDateTime, creation.dwHighDateTime)
    except Exception:
        pass
    return (0, 0)


def _parse_lock_content(content):
    """解析锁文件内容，返回 (pid, create_time)。
    支持旧格式（纯PID）和新格式（PID|create_time）。
    """
    content = content.strip()
    if "|" in content:
        parts = content.split("|")
        try:
            pid = int(parts[0])
            # 解析 (low, high) 元组字符串
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
        # 如果锁文件中有创建时间，验证进程创建时间是否匹配
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


def _is_pid_alive(pid):
    """检查指定 PID 的进程是否存活（用于父进程存活监控）。"""
    try:
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        alive = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(alive and exit_code.value == STILL_ACTIVE)
    except Exception:
        return False


def _minimize_existing_windows():
    import glob
    lock_dir = os.environ.get("TEMP", os.environ.get("TMP", ""))
    if not lock_dir:
        return
    lock_files = glob.glob(os.path.join(lock_dir, "banner_group_lock_*.lock"))
    own_pid = os.getpid()
    app_pids = {own_pid}
    for lf in lock_files:
        try:
            with open(lf, "r") as f:
                content = f.read()
            pid, create_time = _parse_lock_content(content)
            if pid <= 0:
                continue
            if _SYS_COMPAT["is_windows"]:
                if _is_process_alive_with_create_time(pid, create_time):
                    app_pids.add(pid)
                else:
                    # 进程已死或 PID 复用，清理残留锁文件
                    try:
                        os.remove(lf)
                    except Exception:
                        pass
        except Exception:
            pass
    # 预读 explorer.exe 的 PID（Windows 外壳，管理任务栏和开始菜单）
    # 文件管理器窗口（CabinetWClass）会被最小化，但开始菜单/任务栏等不会
    explorer_pids = set()
    try:
        import subprocess
        r = subprocess.run(
            ["tasklist", "/fi", "imagename eq explorer.exe", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        for line in r.stdout.strip().split("\n"):
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2 and parts[0].lower() == "explorer.exe":
                try:
                    explorer_pids.add(int(parts[1]))
                except ValueError:
                    pass
    except Exception:
        pass
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_long)
    # 系统窗口类名列表，跳过这些窗口
    _skip_classes = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman",
                     "WorkerW", "WindowsDashboard", "Xaml_WindowedPopupClass"}
    def enum_cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        # 检查窗口类名，跳过任务栏/桌面等系统窗口
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        if class_name.value in _skip_classes:
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        # 跳过本应用的窗口
        if pid.value in app_pids:
            return True
        # explorer.exe 的窗口：只最小化文件管理器（CabinetWClass），跳过开始菜单等
        if pid.value in explorer_pids:
            if class_name.value == "CabinetWClass":
                user32.ShowWindow(hwnd, 6)
            return True
        user32.ShowWindow(hwnd, 6)
        return True
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)



def _detect_system_compat():
    info = {
        "os": "unknown",
        "os_version": (0, 0, 0),
        "is_windows": False,
        "is_win7_plus": False,
        "is_win10_plus": False,
        "is_win11_plus": False,
        "compat_mode": False,
        "python_version": sys.version_info[:3],
        "min_python": (3, 8, 0),
        "min_os": "Windows 7",
    }
    try:
        if sys.platform == "win32":
            info["is_windows"] = True
            ver = sys.getwindowsversion()
            major, minor, build = ver.major, ver.minor, ver.build
            release_id = ""
            if major >= 10:
                try:
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
                    reg_build = int(winreg.QueryValueEx(key, "CurrentBuildNumber")[0])
                    release_id = str(winreg.QueryValueEx(key, "ReleaseId")[0])
                    winreg.CloseKey(key)
                    if reg_build > build:
                        build = reg_build
                except Exception:
                    pass
            info["os_version"] = (major, minor, build)
            # Windows 11 的构建号 >= 22000，但 major.minor 仍可能是 10.0
            if build >= 22000:
                info["os"] = f"Windows 11 ({build})"
            else:
                info["os"] = f"Windows {major}.{minor}.{build}"
            if release_id:
                info["os"] += f" ({release_id})"
            if (major >= 6 and minor >= 1) or major >= 10:
                info["is_win7_plus"] = True
            if major >= 10:
                info["is_win10_plus"] = True
                if build >= 22000:
                    info["is_win11_plus"] = True
            if not info["is_win7_plus"]:
                info["compat_mode"] = True
    except Exception as e:
        pass
    py = info["python_version"]
    if py < info["min_python"]:
        info["compat_mode"] = True

    lib_info = []
    try:
        import numpy
        lib_info.append(f"numpy={numpy.__version__}")
    except ImportError:
        pass
    try:
        import cv2
        lib_info.append(f"opencv={cv2.__version__}")
    except ImportError:
        pass
    try:
        from PyQt5.Qt import PYQT_VERSION_STR
        lib_info.append(f"PyQt5={PYQT_VERSION_STR}")
    except ImportError:
        pass

    info["_lib_info"] = lib_info

    return info

_SYS_COMPAT = _detect_system_compat()


def _show_error_popup(title, message, source="导入器"):
    from utils.settings_manager import report_error
    report_error(title, message, source)


class CircularProgressWidget(QWidget):
    def __init__(self, parent=None, ui_scale=1.0):
        super().__init__(parent)
        self._progress = 0.0
        self._status_text = "正在初始化..."
        self._title_text = "旗帜训练工具"
        self._mode_text = ""
        self._s = min(max(ui_scale, 1.0), 1.4)
        # 读取主题
        _theme = resolve_theme(SettingsManager().get("theme", "light"))
        self._is_dark = _theme == "dark"

    def setProgress(self, value):
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def setStatusText(self, text):
        self._status_text = text
        self.update()

    def setModeText(self, text):
        self._mode_text = text
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        s = self._s
        is_dark = self._is_dark

        # 现代化配色（与主窗口深色模式同步，使用灰色调避免蓝色）
        if is_dark:
            bg_color = QColor("#2d2d30")
            title_color = QColor("#eeeeee")
            mode_color = QColor("#cccccc")
            progress_bg = QColor("#3c3c3c")
            progress_color = QColor("#cccccc")
            status_color = QColor("#aaaaaa")
            glow_color = QColor(204, 204, 204, 40)
        else:
            bg_color = QColor("#f0f0f0")
            title_color = QColor("#000000")
            mode_color = QColor("#555555")
            progress_bg = QColor("#e0e0e0")
            progress_color = QColor("#555555")
            status_color = QColor("#666666")
            glow_color = QColor(85, 85, 85, 40)

        painter.fillRect(0, 0, w, h, bg_color)

        title_fs = max(int(44 * s), 36)
        mode_fs = max(int(20 * s), 16)
        status_fs = max(int(18 * s), 14)

        painter.setPen(title_color)
        title_font_obj = QFont("Microsoft YaHei UI", title_fs, QFont.Bold)
        title_font_obj.setPixelSize(title_fs)  # 像素体系：仅随分辨率 scale，杜绝 DPI 放大（与训练器加载界面一致）
        painter.setFont(title_font_obj)
        painter.drawText(QRectF(0, h * 0.05, w, int(h * 0.12)), Qt.AlignCenter, self._title_text)

        painter.setPen(mode_color)
        mode_font_obj = QFont("Microsoft YaHei UI", mode_fs)
        mode_font_obj.setPixelSize(mode_fs)
        painter.setFont(mode_font_obj)
        painter.drawText(QRectF(0, h * 0.15, w, int(h * 0.08)), Qt.AlignCenter, self._mode_text)

        cy = h * 0.52
        cx = w / 2
        r = min(w, h) * 0.20
        ring_width = max(int(10 * s), 8)

        # 外圈光晕（3层半透明圆环）
        for i in range(3):
            alpha = 40 - i * 12
            glow = QColor(glow_color)
            glow.setAlpha(alpha)
            painter.setPen(QPen(glow, max(int(2 * s), 1)))
            painter.setBrush(Qt.NoBrush)
            glow_r = r + ring_width + max(int(8 * s), 6) - i * max(int(3 * s), 2)
            painter.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        # 背景圆环
        painter.setPen(QPen(progress_bg, ring_width, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # 进度圆环
        angle = self._progress * 360
        painter.setPen(QPen(progress_color, ring_width, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(int(cx - r), int(cy - r), int(2 * r), int(2 * r),
                        int(90 * 16), int(-angle * 16))

        # 百分比文字
        painter.setPen(title_color)
        pct_fs = max(int(42 * s), 32)
        pct_font_obj = QFont("Microsoft YaHei UI", pct_fs, QFont.Bold)
        pct_font_obj.setPixelSize(pct_fs)
        painter.setFont(pct_font_obj)
        painter.drawText(QRectF(cx - r * 0.8, cy - r * 0.4, r * 1.6, r * 0.8), Qt.AlignCenter,
                         f"{int(self._progress * 100)}%")

        # 状态文字
        painter.setPen(status_color)
        status_font_obj = QFont("Microsoft YaHei UI", status_fs)
        status_font_obj.setPixelSize(status_fs)
        painter.setFont(status_font_obj)
        status_y = cy + r + int(20 * s)
        status_h = int(h * 0.12)
        painter.drawText(QRectF(int(w * 0.08), status_y,
                                int(w * 0.84), status_h),
                        Qt.AlignCenter | Qt.TextWordWrap,
                        self._status_text)

        painter.end()


class BannerPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._info_text = ""
        self._recipe_text = ""
        self._scroll_offset = 0
        self._max_scroll = 0
        self._click_link_rect = None
        self._detail_callback = None
        self.setMinimumSize(80, 160)
        self.setMouseTracking(True)
        self._hover_link = False
        self._scale = 1.0

    def _is_dark_theme(self):
        win = self.window()
        if win is not None and hasattr(win, "_current_theme"):
            return win._current_theme == "dark"
        return False

    def setPixmap(self, pixmap):
        self._pixmap = pixmap
        self._info_text = ""
        self._recipe_text = ""
        self._scroll_offset = 0
        self._click_link_rect = None
        self._detail_callback = None
        self.update()

    def setPixmapWithRecipe(self, pixmap, recipe_text):
        self._pixmap = pixmap
        self._info_text = ""
        self._recipe_text = recipe_text
        self._scroll_offset = 0
        self._click_link_rect = None
        self._detail_callback = None
        self.update()

    def setInfoText(self, text, detail_callback=None):
        self._info_text = text
        self._pixmap = None
        self._recipe_text = ""
        self._scroll_offset = 0
        self._detail_callback = detail_callback
        self._click_link_rect = None
        self.update()

    def clear(self):
        self._pixmap = None
        self._info_text = ""
        self._recipe_text = ""
        self._scroll_offset = 0
        self._click_link_rect = None
        self._detail_callback = None
        self.update()

    def wheelEvent(self, event):
        if self._info_text or self._recipe_text:
            delta = event.angleDelta().y()
            step = max(delta // 2, -60) if delta < 0 else min(delta // 2, 60)
            self._scroll_offset -= step
            self._scroll_offset = max(0, min(self._scroll_offset, self._max_scroll))
            self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._click_link_rect and self._click_link_rect.contains(event.pos()):
            if not self._hover_link:
                self._hover_link = True
                self.setCursor(Qt.PointingHandCursor)
                self.update()
        else:
            if self._hover_link:
                self._hover_link = False
                self.setCursor(Qt.ArrowCursor)
                self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._click_link_rect and self._click_link_rect.contains(event.pos()):
            if self._detail_callback:
                self._detail_callback()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        margin = 2
        rect = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)

        is_dark = self._is_dark_theme()
        bg_color = QColor("#3c3c3c") if is_dark else QColor("#f5f5f5")
        line_color = QColor("#555555") if is_dark else QColor("#cccccc")
        recipe_text_color = QColor("#eeeeee") if is_dark else QColor("#333333")
        info_text_color = QColor("#eeeeee") if is_dark else QColor("#333333")
        info_short_color = QColor("#aaaaaa") if is_dark else QColor("#666666")
        link_bg_hover = QColor("#1e3a5f") if is_dark else QColor("#d0e8ff")
        link_bg_normal = QColor("#4a4a4a") if is_dark else QColor("#e0e0e0")
        link_text_hover = QColor("#4a9eff") if is_dark else QColor("#0066cc")
        link_text_normal = QColor("#7ab8ff") if is_dark else QColor("#336699")
        scroll_alpha = 60 if is_dark else 40

        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(rect, 4, 4)

        if self._pixmap and self._recipe_text:
            inner_margin = 7
            inner_w = w - 2 * inner_margin
            banner_h = int(h * 0.72)
            recipe_y_start = banner_h + inner_margin

            if inner_w > 0 and banner_h > 0:
                target_w, target_h = inner_w, inner_w * 2
                if target_h > banner_h - inner_margin:
                    target_h = banner_h - inner_margin
                    target_w = target_h // 2
                target_w = max(target_w, 1)
                target_h = max(target_h, 1)
                scaled = self._pixmap.scaled(int(target_w), int(target_h),
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
                x = inner_margin + (inner_w - scaled.width()) // 2
                y = inner_margin + (banner_h - inner_margin - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)

            painter.setPen(QPen(line_color, 1))
            painter.drawLine(QPointF(inner_margin, recipe_y_start - inner_margin // 2),
                             QPointF(w - inner_margin, recipe_y_start - inner_margin // 2))

            recipe_h = h - recipe_y_start - inner_margin
            recipe_w = inner_w
            if recipe_h > 10 and recipe_w > 10:
                font = QFont("Microsoft YaHei UI")
                font.setPixelSize(max(int(w * 0.018), 6))
                painter.setFont(font)
                fm = painter.fontMetrics()
                line_h = fm.height()

                lines = self._recipe_text.split('\n')
                total_text_h = line_h * len(lines)
                self._max_scroll = max(0, total_text_h - recipe_h)

                painter.save()
                painter.setClipRect(QRectF(inner_margin, recipe_y_start, recipe_w, recipe_h))
                painter.setPen(recipe_text_color)
                y_pos = recipe_y_start - self._scroll_offset
                for line in lines:
                    if y_pos + line_h > recipe_y_start and y_pos < recipe_y_start + recipe_h:
                        painter.drawText(QRectF(inner_margin, y_pos, recipe_w, line_h),
                                         Qt.AlignLeft | Qt.AlignVCenter, line)
                    y_pos += line_h
                painter.restore()

                if self._max_scroll > 0:
                    scroll_ratio = self._scroll_offset / self._max_scroll if self._max_scroll > 0 else 0
                    bar_h_thumb = max(15, recipe_h * (recipe_h / total_text_h))
                    bar_y = recipe_y_start + scroll_ratio * (recipe_h - bar_h_thumb)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(255, 255, 255, scroll_alpha) if is_dark else QColor(0, 0, 0, scroll_alpha))
                    painter.drawRoundedRect(QRectF(w - inner_margin - 5, bar_y, 4, bar_h_thumb), 2, 2)

        elif self._pixmap:
            inner_margin = 7
            inner_w = w - 2 * inner_margin
            inner_h = h - 2 * inner_margin
            if inner_w > 0 and inner_h > 0:
                target_w, target_h = inner_w, inner_w * 2
                if target_h > inner_h:
                    target_h = inner_h
                    target_w = inner_h // 2
                target_w = max(target_w, 1)
                target_h = max(target_h, 1)
                scaled = self._pixmap.scaled(int(target_w), int(target_h),
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
                x = inner_margin + (inner_w - scaled.width()) // 2
                y = inner_margin + (inner_h - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)

        if self._info_text:
            text_margin = 10
            text_w = w - 2 * text_margin
            text_h = h - 2 * text_margin
            if text_w < 10 or text_h < 10:
                painter.end()
                return

            font = QFont("Microsoft YaHei UI")
            lines = self._info_text.split('\n')
            line_count = len(lines)
            max_line_chars = max(len(l) for l in lines) if lines else 10

            max_font = int(12 * self._scale)
            min_font = max(int(9 * self._scale), 8)
            font_by_height = text_h / (line_count * 1.35) if line_count > 0 else max_font
            font_by_width = text_w / (max_line_chars * 0.55) if max_line_chars > 0 else max_font
            font_size = int(min(font_by_height, font_by_width, max_font))
            font_size = max(font_size, min_font)
            font.setPixelSize(font_size)
            painter.setFont(font)

            fm = painter.fontMetrics()
            line_h = fm.height()
            total_h = line_h * line_count
            self._max_scroll = max(0, total_h - text_h)

            single_line_short = line_count == 1 and not self._detail_callback and max_line_chars <= 12
            if single_line_short:
                short_fs = max(int(16 * self._scale), 13)
                font.setPixelSize(short_fs)
                painter.setFont(font)
                painter.setPen(info_short_color)
            else:
                painter.setPen(info_text_color)
            painter.save()
            painter.setClipRect(QRectF(text_margin, text_margin, text_w, text_h))
            if single_line_short:
                painter.drawText(QRectF(text_margin, text_margin, text_w, text_h),
                                 Qt.AlignCenter, self._info_text)
            else:
                painter.drawText(QRectF(text_margin, text_margin - self._scroll_offset, text_w, total_h),
                                 Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self._info_text)
            painter.restore()

            if self._max_scroll > 0:
                scroll_ratio = self._scroll_offset / self._max_scroll if self._max_scroll > 0 else 0
                bar_h_total = text_h
                bar_h_thumb = max(20, bar_h_total * (text_h / total_h))
                bar_y = text_margin + scroll_ratio * (bar_h_total - bar_h_thumb)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 255, 255, scroll_alpha) if is_dark else QColor(0, 0, 0, scroll_alpha))
                painter.drawRoundedRect(QRectF(w - text_margin - 5, bar_y, 4, bar_h_thumb), 2, 2)

            if self._detail_callback:
                link_text = "▼ 点击查看更多旗帜序列信息"
                link_font = QFont("Microsoft YaHei UI")
                link_font.setPixelSize(max(font_size - 1, min_font))
                painter.setFont(link_font)
                link_fm = painter.fontMetrics()
                link_w = link_fm.horizontalAdvance(link_text) + 16
                link_h = link_fm.height() + 8
                link_x = (w - link_w) / 2
                link_y = h - link_h - text_margin

                self._click_link_rect = QRectF(link_x, link_y, link_w, link_h)

                painter.setPen(Qt.NoPen)
                bg_color = link_bg_hover if self._hover_link else link_bg_normal
                painter.setBrush(bg_color)
                painter.drawRoundedRect(self._click_link_rect, 4, 4)

                painter.setPen(link_text_hover if self._hover_link else link_text_normal)
                painter.setFont(link_font)
                painter.drawText(self._click_link_rect, Qt.AlignCenter, link_text)

        painter.end()


class ColorButton(QPushButton):
    def __init__(self, color_hex, idx, scale=1.0, parent=None):
        super().__init__(parent)
        self.color_idx = idx
        self._color_hex = color_hex
        self._scale = scale
        self._apply_size()
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._apply_style(False, True)
        self._selected = False

    def _apply_size(self):
        sz = max(int(56 * self._scale / 2.5), 20)
        self.setFixedSize(sz, sz)

    def set_scale(self, scale):
        if abs(self._scale - scale) < 0.01:
            return
        self._scale = scale
        self._apply_size()

    def sizeHint(self):
        return self.size()

    def _apply_style(self, selected, enabled):
        border = "3px solid #0066ff" if selected else ("2px solid #666" if enabled else "1px solid #bbb")
        opacity = "1.0" if enabled else "0.5"
        self.setStyleSheet(
            f"background-color: {self._color_hex}; border: {border}; border-radius: 0px; opacity: {opacity};"
            f"min-height: 0; min-width: 0; padding: 0; margin: 0;"
        )

    def set_selected(self, sel):
        self._selected = sel
        self._apply_style(sel, self.isEnabled())

    def set_enabled(self, enabled):
        self.setEnabled(enabled)
        self._apply_style(self._selected, enabled)


class BannerImportWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("旗帜训练导入器 v0.5 beta1 (1.0.8)")

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        sw = geo.width() if geo else 1920
        sh = geo.height() if geo else 1080
        if sh < 480:
            MessageBox.critical(None, "分辨率过低",
                f"系统可用高度 {sh}px 过低，无法正常显示。\n"
                f"请将屏幕分辨率设置为 720P 或以上。")
            sys.exit(1)
        sx = geo.x() if geo else 0
        sy = geo.y() if geo else 0
        ui_scale = max(min(sw / 1920, sh / 1080), 0.85)
        # 按需求：文字大小仅随分辨率，不考虑DPI；dpi_scale 固定为 1.0
        dpi_scale = 1.0
        self._scale = min(ui_scale * 1.25, 2.5)
        ch = int(39 * dpi_scale)
        self._chrome_h = ch
        self._min_h = int((sh - 2 * ch) * 0.5)
        screen_ratio = sw / sh
        if screen_ratio < 2.0:
            self._min_w = int(sw / 3)
        else:
            self._min_w = int(sw / 4)
        self.setMinimumSize(self._min_w, self._min_h)
        base_w = max(int(sw * 0.33), 600)
        base_h = int((sh - 2 * ch) * 0.5)
        tx = sx + sw // 2 + (sw // 2 - base_w) // 2
        self.setGeometry(tx, sy + (sh - base_h - ch) // 2, base_w, base_h)

        base_fs = max(int(10 * self._scale), 9)
        btn_fs = max(int(11 * self._scale), 10)
        bg = "#f0f0f0"
        fg = "#000000"
        group_border = "#cccccc"
        input_bg = "#ffffff"
        arrow_color = "#666666"
        self.setStyleSheet(f"""
            QPushButton {{ font-size: {btn_fs}px; min-height: {max(int(26 * self._scale), 22)}px; padding: {max(int(6 * self._scale), 4)}px {max(int(14 * self._scale), 10)}px; background-color: #0078D4; color: white; border: 1px solid #005A9E; border-radius: 8px; }}
            QPushButton:hover {{ background-color: #106EBE; border: 1px solid #005A9E; }}
            QPushButton:pressed {{ background-color: #005A9E; border: 1px solid #004578; }}
            QPushButton:disabled {{ background-color: #CCCCCC; color: #888888; border: 1px solid #BBBBBB; }}
            QLabel {{ font-size: {base_fs}px; }}
            QCheckBox {{ font-size: {base_fs}px; }}
            QSpinBox {{ font-size: {base_fs}px; min-height: {max(int(22 * self._scale), 20)}px; color: #000000; background: #ffffff; border: 1px solid #cccccc; border-radius: 4px; padding: 2px {max(int(4 * self._scale), 3)}px; }}
            QSpinBox::up-button, QSpinBox::down-button {{ background: transparent; border: none; width: {max(int(16 * self._scale), 14)}px; }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: #e8e8e8; border-radius: 3px; }}
            QSpinBox::up-arrow {{ width: 8px; height: 8px; }}
            QSpinBox::down-arrow {{ width: 8px; height: 8px; }}
            QComboBox {{ font-size: {base_fs}px; min-height: {max(int(22 * self._scale), 20)}px; color: #000000; background: #ffffff; border: 1px solid #cccccc; border-radius: 4px; padding: 2px {max(int(6 * self._scale), 4)}px; }}
            QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: {max(int(20 * self._scale), 16)}px; border: none; }}
            QComboBox QAbstractItemView {{ border: 1px solid #cccccc; border-radius: 4px; background: #ffffff; color: #000000; selection-background-color: #0078D4; selection-color: white; outline: none; }}
            QSlider::groove:horizontal {{ height: 4px; background: #dddddd; border-radius: 2px; }}
            QSlider::handle:horizontal {{ width: {max(int(14 * self._scale), 12)}px; height: {max(int(14 * self._scale), 12)}px; margin: -{max(int(5 * self._scale), 4)}px 0; background: #0078D4; border-radius: {max(int(7 * self._scale), 6)}px; }}
            QSlider::handle:horizontal:hover {{ background: #106EBE; }}
            QGroupBox {{ font-size: {btn_fs}px; }}
            QListWidget {{ font-size: {base_fs}px; padding-right: 4px; border: 1px solid #a0a0a0; border-radius: 4px; }}
            QTabWidget::pane {{ font-size: {base_fs}px; border: none; }}
            QTabBar {{ background-color: {bg}; }}
            QTabBar::tab {{ font-size: {btn_fs}px; padding: {max(int(4*self._scale),3)}px {max(int(10*self._scale),8)}px; color: {fg}; background-color: {bg}; border: 1px solid {group_border}; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-left: 3px; margin-right: 3px; }}
            QTabBar::tab:selected {{ background-color: {input_bg}; }}
            QTabBar::tab:!selected {{ color: {arrow_color}; }}
            QMenuBar {{ font-size: {btn_fs}px; }}
            QMenu {{ font-size: {base_fs}px; }}
            QScrollArea {{ border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; border: none; }}
            QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; border: none; }}
            QScrollBar::handle {{ background: #c0c0c0; border-radius: 5px; min-height: 30px; min-width: 30px; }}
            QScrollBar::handle:hover {{ background: #a0a0a0; }}
            QScrollBar::handle:pressed {{ background: #909090; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ border: none; background: none; width: 0; height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        """)

        icon_path = resolve_app_path("images/icons/importer.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 消除窗口移动时的白色残影
        self.setAutoFillBackground(True)

        self.banners = []
        self.current_banner = [0]
        self._banner_touched = False
        self._graphic_banner_touched = False
        self._edit_locked = False
        self._editing_index = -1
        self._selected_banner_index = -1
        self._inhibit_list_events = False
        self._workspace_draft = None
        self._workspace_draft_pc = None
        self._image_cache = {}
        self._image_cache_max = 64
        self._bg_selected_idx = 16
        self._pc_selected_idx = 1
        self._rand_batch_size = 1
        self._rand_min_colors = 1
        self._rand_max_colors = 5
        self._rand_min_patterns = 0
        self._rand_max_patterns = 6
        self._rand_avoid_dup_color = False
        self._rand_avoid_dup = False
        self._force_quit = False
        self._exit_process = None
        self._exit_timer = None
        self._close_blocked = False
        self.current_layout = None
        self._layout_applying = False
        self._session_dir = None
        self._max_display_count = 6
        self._last_multiple_indices = None
        self._splitter_adjusting = False
        self._layout_switching = False
        self._scale_override = None
        # 工作区布局文件：持久化 Tab2 的 4 个 splitter 位置，跨 Tab 切换和跨重启保留
        self._workspace_data = self._load_workspace()

        # 通用设置从配置读取
        _sm = SettingsManager()
        self._snap_enabled = _sm.get("snap_enabled", True)
        self._snap_threshold = _sm.get("snap_threshold", 10)
        self._snap_grid = _sm.get("snap_grid", True)
        self._current_theme = _sm.get("theme", "light")

        # 监听配置文件变化，实现导入器/训练器主题跨进程同步
        config_path = _sm.config_path
        self._config_watcher = QFileSystemWatcher([config_path], self)
        self._config_watcher.fileChanged.connect(self._on_config_changed)

        # 记录配置文件 mtime，定时轮询时仅在文件变化才 reload（避免每秒 IO）
        try:
            self._config_mtime = os.path.getmtime(config_path)
        except Exception:
            self._config_mtime = 0

        # 定时轮询作为文件监听的兜底，确保主题变更可靠同步
        self._theme_sync_timer = QTimer(self)
        self._theme_sync_timer.timeout.connect(self._sync_theme_from_config)
        self._theme_sync_timer.start(1000)

        # 图标延迟到首次渲染时再加载，避免启动时阻塞
        # load_icons() 由 generate_banner_image 在需要时自动调用

        self._create_widgets()
        self._apply_theme_to_window(self._current_theme)
        self.apply_narrow_layout()
        QTimer.singleShot(50, self._apply_layout)
        QTimer.singleShot(100, self._highlight_bg_color)
        QTimer.singleShot(100, self._highlight_pattern_color)
        QTimer.singleShot(200, self._update_edit_btn_visibility)
        QTimer.singleShot(50, self._init_preview_text)

        self._open_file_timer = QTimer(self)
        self._open_file_timer.timeout.connect(self._check_open_file_signal)
        self._open_file_timer.start(500)

        for w in (self.saved_list, self.exp_saved_list, self.selected_list, self.pattern_tree):
            w.installEventFilter(self)
        self.edit_group.installEventFilter(self)
        for child in self.edit_group.findChildren(QWidget):
            child.installEventFilter(self)

        self._setup_auto_save()

    def _create_menu_bar(self):
        bar = self.menuBar()

        # ===== 文件 =====
        file_menu = bar.addMenu("文件(&F)")
        act_import = QAction("导入旗帜文件...", self)
        act_import.setShortcut("Ctrl+O")
        act_import.triggered.connect(self.import_banners)
        file_menu.addAction(act_import)

        act_export = QAction("导出旗帜文件...", self)
        act_export.setShortcut("Ctrl+S")
        act_export.triggered.connect(self.export_file)
        file_menu.addAction(act_export)

        file_menu.addSeparator()
        act_to_trainer = QAction("发送到训练器", self)
        act_to_trainer.triggered.connect(self.export_to_trainer)
        file_menu.addAction(act_to_trainer)

        file_menu.addSeparator()
        act_exit = QAction("退出", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # ===== 编辑 =====
        edit_menu = bar.addMenu("编辑(&E)")
        act_del_sel = QAction("删除选中", self)
        act_del_sel.setShortcut("Delete")
        act_del_sel.triggered.connect(self._delete_selected)
        edit_menu.addAction(act_del_sel)

        act_del_all = QAction("删除全部", self)
        act_del_all.triggered.connect(self._delete_all)
        edit_menu.addAction(act_del_all)

        # ===== 查看 =====
        view_menu = bar.addMenu("查看(&V)")
        self._scale_actions = {}

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
        preset_scales = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0]
        for s in preset_scales:
            label = f"{int(s*100)}%"
            act = QAction(label, self, checkable=True)
            act.triggered.connect(lambda checked, sv=s: self._menu_set_scale_absolute(sv))
            scale_menu.addAction(act)
            self._scale_actions[s] = act

        scale_menu.addSeparator()
        act_auto = QAction("自适应（默认）", self, checkable=True)
        act_auto.triggered.connect(lambda: self._menu_set_scale_auto())
        scale_menu.addAction(act_auto)
        self._scale_auto_action = act_auto

        scale_menu.addSeparator()
        self._scale_current_action = QAction("", self)
        self._scale_current_action.setEnabled(False)
        scale_menu.addAction(self._scale_current_action)
        self._update_scale_menu_check()

        view_menu.addSeparator()
        act_save_layout = QAction("保存当前工作区位置", self)
        act_save_layout.triggered.connect(self._menu_save_layout)
        view_menu.addAction(act_save_layout)
        act_reset = QAction("重置工作区布局", self)
        act_reset.triggered.connect(self._menu_reset_layout)
        view_menu.addAction(act_reset)

        # ===== 设置 =====
        act_settings = QAction("设置(&S)", self)
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self._menu_open_settings)
        bar.addAction(act_settings)

        # ===== 帮助 =====
        help_menu = bar.addMenu("帮助(&H)")
        act_help = QAction("使用说明", self)
        act_help.setShortcut("F1")
        act_help.triggered.connect(self._menu_show_help)
        help_menu.addAction(act_help)

        help_menu.addSeparator()
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._menu_about)
        help_menu.addAction(act_about)

    def _get_auto_scale(self):
        screen = QApplication.primaryScreen()
        sw = screen.availableGeometry().width() if screen else 1920
        sh = screen.availableGeometry().height() if screen else 1080
        ui_scale = max(min(sw / 1920, sh / 1080), 0.85)
        return min(ui_scale * 1.25, 2.5)

    def _menu_zoom(self, factor):
        self._scale_override = self._scale * factor
        self._apply_scale_override()

    def _menu_set_scale_absolute(self, value):
        self._scale_override = value
        self._apply_scale_override()

    def _menu_set_scale_auto(self):
        self._scale_override = None
        self._scale = self._get_auto_scale()
        self._reapply_stylesheet()
        self._update_scale_menu_check()

    def _apply_scale_override(self):
        self._scale = max(0.5, min(self._scale_override, 4.0))
        self._reapply_stylesheet()
        self._update_scale_menu_check()

    def _reapply_stylesheet(self):
        base_fs = max(int(10 * self._scale), 9)
        btn_fs = max(int(11 * self._scale), 10)
        is_dark = getattr(self, "_current_theme", "light") == "dark"
        bg = "#2d2d30" if is_dark else "#f5f5f5"
        fg = "#eeeeee" if is_dark else "#000000"
        group_border = "#555555" if is_dark else "#cccccc"
        handle_bg = "#555555" if is_dark else "#dddddd"
        btn_bg = "#4FC3F7" if is_dark else "#0078D4"
        btn_hover = "#29B6F6" if is_dark else "#106EBE"
        btn_pressed = "#0288D1" if is_dark else "#005A9E"
        btn_disabled = "#555555" if is_dark else "#CCCCCC"
        btn_fg = "#1a1a1a" if is_dark else "white"
        btn_border = "#0277BD" if is_dark else "#005A9E"
        btn_border_pressed = "#01579B" if is_dark else "#004578"
        btn_disabled_fg = "#999999" if is_dark else "#888888"
        btn_disabled_border = "#444444" if is_dark else "#BBBBBB"
        # 随机生成按钮强调色（推荐按钮仅作颜色区分，深浅色各一套）
        rand_bg = "#7C6CF0" if is_dark else "#6366f1"
        rand_hover = "#6B5BE6" if is_dark else "#4f46e5"
        rand_pressed = "#5A4AD6" if is_dark else "#4338ca"
        rand_border = "#7C6CF0" if is_dark else "#6366f1"
        scroll_handle = "#555555" if is_dark else "#c0c0c0"
        scroll_handle_hover = "#666666" if is_dark else "#a0a0a0"
        scroll_handle_pressed = "#777777" if is_dark else "#909090"
        input_bg = "#3c3c3c" if is_dark else "#ffffff"
        input_border = "#555555" if is_dark else "#cccccc"
        # 列表边框：浅色统一调暗（避免刺眼），暗色沿用深灰
        list_border = "#555555" if is_dark else "#a0a0a0"
        spin_hover = "#4a4a4a" if is_dark else "#e8e8e8"
        arrow_color = "#cccccc" if is_dark else "#666666"
        group_style = f'border: 1px solid {group_border}; border-radius: 6px;' if is_dark else ''
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {bg}; color: {fg}; }}
            QDialog {{ background-color: {bg}; color: {fg}; }}
            QPushButton {{ font-size: {btn_fs}px; min-height: {max(int(26 * self._scale), 22)}px; padding: {max(int(6 * self._scale), 4)}px {max(int(14 * self._scale), 10)}px; background-color: {btn_bg}; color: {btn_fg}; border: 1px solid {btn_border}; border-radius: 8px; }}
            QPushButton:hover {{ background-color: {btn_hover}; border: 1px solid {btn_border}; }}
            QPushButton:pressed {{ background-color: {btn_pressed}; border: 1px solid {btn_border_pressed}; }}
            QPushButton:disabled {{ background-color: {btn_disabled}; color: {btn_disabled_fg}; border: 1px solid {btn_disabled_border}; }}
            QPushButton#rand_gen_btn {{ background-color: {rand_bg}; border: 1px solid {rand_border}; border-radius: 6px; }}
            QPushButton#rand_gen_btn:hover {{ background-color: {rand_hover}; border: 1px solid {rand_hover}; }}
            QPushButton#rand_gen_btn:pressed {{ background-color: {rand_pressed}; border: 1px solid {rand_pressed}; }}
            QLabel {{ font-size: {base_fs}px; color: {fg}; }}
            QCheckBox {{ font-size: {base_fs}px; color: {fg}; }}
            QSpinBox {{ font-size: {base_fs}px; min-height: {max(int(22 * self._scale), 20)}px; color: {fg}; background: {input_bg}; border: 1px solid {input_border}; border-radius: 4px; padding: 2px {max(int(4 * self._scale), 3)}px; }}
            QSpinBox::up-button, QSpinBox::down-button {{ background: transparent; border: none; width: {max(int(16 * self._scale), 14)}px; }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {spin_hover}; border-radius: 3px; }}
            QSpinBox::up-arrow {{ width: 8px; height: 8px; }}
            QSpinBox::down-arrow {{ width: 8px; height: 8px; }}
            QComboBox {{ font-size: {base_fs}px; min-height: {max(int(22 * self._scale), 20)}px; color: {fg}; background: {input_bg}; border: 1px solid {input_border}; border-radius: 4px; padding: 2px {max(int(6 * self._scale), 4)}px; }}
            QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: {max(int(20 * self._scale), 16)}px; border: none; }}
            QComboBox QAbstractItemView {{ border: 1px solid {input_border}; border-radius: 4px; background: {input_bg}; color: {fg}; selection-background-color: {btn_bg}; selection-color: {btn_fg}; outline: none; }}
            QSlider::groove:horizontal {{ height: 4px; background: {handle_bg}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ width: {max(int(14 * self._scale), 12)}px; height: {max(int(14 * self._scale), 12)}px; margin: -{max(int(5 * self._scale), 4)}px 0; background: {btn_bg}; border-radius: {max(int(7 * self._scale), 6)}px; }}
            QSlider::handle:horizontal:hover {{ background: {btn_hover}; }}
            QGroupBox {{ font-size: {btn_fs}px; font-weight: bold; {group_style} margin-top: 8px; padding-top: 16px; color: {fg}; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
            QListWidget {{ font-size: {base_fs}px; color: {fg}; padding-right: 4px; border: 1px solid {list_border}; border-radius: 4px; }}
            QTabWidget::pane {{ font-size: {base_fs}px; border: none; }}
            QTabBar {{ background-color: {bg}; }}
            QTabBar::tab {{ font-size: {btn_fs}px; padding: {max(int(4*self._scale),3)}px {max(int(10*self._scale),8)}px; color: {fg}; background-color: {bg}; border: 1px solid {group_border}; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-left: 3px; margin-right: 3px; }}
            QTabBar::tab:selected {{ background-color: {input_bg}; }}
            QTabBar::tab:!selected {{ color: {arrow_color}; }}
            QMenuBar {{ font-size: {btn_fs}px; }}
            QMenu {{ font-size: {base_fs}px; }}
            QSplitter {{ background-color: {bg}; }}
            QSplitter::handle {{ background-color: {handle_bg}; }}
            QScrollArea {{ border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; border: none; }}
            QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; border: none; }}
            QScrollBar::handle {{ background: {scroll_handle}; border-radius: 5px; min-height: 30px; min-width: 30px; }}
            QScrollBar::handle:hover {{ background: {scroll_handle_hover}; }}
            QScrollBar::handle:pressed {{ background: {scroll_handle_pressed}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ border: none; background: none; width: 0; height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        """)
        # Tab1 面板按钮：QGroupBox 局部 QSS 遮蔽了主窗口 QSS 的 QPushButton:disabled
        # 规则，导致禁用边框回退 Qt 默认浅灰 #bbbbbb，与训练器深灰 #444444 不一致。
        # 直接给按钮自身补 disabled 边框（自身 QSS 优先，不影响正常态蓝色）。
        _tab1_disable_qss = f"QPushButton:disabled {{ border: 1px solid {btn_disabled_border}; }}"
        for _btn in (getattr(self, "_compact_del_btn", None),
                     getattr(self, "_compact_undo_btn", None),
                     getattr(self, "_exp_del_all_btn", None),
                     getattr(self, "_exp_del_range_btn", None),
                     getattr(self, "_exp_del_sel_btn", None),
                     getattr(self, "_exp_del_btn", None),
                     getattr(self, "_exp_undo_btn", None),
                     getattr(self, "delete_pattern_btn", None),
                     getattr(self, "clear_patterns_btn", None),
                     getattr(self, "_graphic_delete_pattern_btn", None),
                     getattr(self, "_graphic_clear_patterns_btn", None)):
            if _btn is not None:
                _btn.setStyleSheet(_tab1_disable_qss)
        for btns in (self.bg_color_btns, self.pattern_color_btns,
                     self._graphic_bg_color_btns, self._graphic_pattern_color_btns):
            for btn in btns:
                btn.set_scale(self._scale)
        self._enforce_splitter_bounds()

    def _update_scale_menu_check(self):
        if not hasattr(self, '_scale_actions'):
            return
        for s, act in self._scale_actions.items():
            act.setChecked(abs(self._scale - s) / s < 0.05)
        if hasattr(self, '_scale_auto_action'):
            self._scale_auto_action.setChecked(self._scale_override is None)
        if hasattr(self, '_scale_current_action'):
            pct = int(round(self._scale * 100))
            self._scale_current_action.setText(f"当前: {pct}%")

    def _menu_about(self):
        show_about_dialog(self, "关于", "旗帜训练导入器 v0.5 beta1 (1.0.8)\n\n用于旗帜序列的编辑、标记与训练数据导入。")

    def _menu_show_help(self):
        """打开使用说明窗口（子进程），跳转到导入器章节。"""
        import subprocess
        app_dir = os.path.dirname(os.path.abspath(__file__))
        help_script = os.path.join(app_dir, "help.pyw")
        if os.path.exists(help_script):
            try:
                subprocess.Popen([sys.executable, help_script, "--scale", str(self._scale), "--section", "importer"])
            except Exception:
                pass

    def _menu_save_layout(self):
        """保存当前工作区位置：记录窗口几何信息但不触发 snap。"""
        self._save_window_geometry()
        self._flush_workspace_to_disk()

    def _menu_reset_layout(self):
        """重置工作区布局：清空保存的窗口位置并 snap 到默认右侧。"""
        clear_workspace_window("importer")
        # 同步清除内存中的 window 数据
        importer_data = self._workspace_data.get("importer", {})
        if isinstance(importer_data, dict):
            importer_data.pop("window", None)
        if _SYS_COMPAT["is_win10_plus"]:
            hwnd = int(self.winId())
            _minimize_existing_windows()
            _double_snap(hwnd, "right")
            self._apply_layout()
            _force_activate(hwnd, self)

    def _write_importer_progress(self, value, status=""):
        if not getattr(self, "_session_dir", None):
            return
        try:
            pfile = os.path.join(self._session_dir, ".importer_progress")
            with open(pfile, "w", encoding="utf-8") as f:
                f.write(f"{value}\n{status}")
        except Exception:
            pass

    def _menu_open_settings(self):
        """启动独立设置程序（子进程），已运行则恢复并跳转到导入器设置页。"""
        import subprocess

        # 已有进程在跑：写命令文件通知跳转，不重复启动
        existing = getattr(self, "_settings_process", None)
        if existing is not None and existing.poll() is None:
            try:
                import tempfile
                cmd_file = os.path.join(tempfile.gettempdir(), "_banner_settings_cmd")
                with open(cmd_file, "w", encoding="utf-8") as f:
                    f.write("importer")
            except Exception:
                pass
            return

        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "settings_dialog.py")
        try:
            proc = subprocess.Popen(
                [sys.executable, script_path, "--caller", "importer", "--scale", str(self._scale)],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self._settings_process = proc
            self._poll_settings_exit()
        except Exception as e:
            _show_error_popup("无法打开设置", str(e))

    def _poll_settings_exit(self):
        """轮询设置子进程是否退出，处理重启请求。"""
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
        import subprocess
        self._force_quit = True
        # 写关闭和退出信号，让训练器检测到并退出
        self._write_closing_signal()
        self._write_quit_signal()

        # 从 config.json 读取最新的 train_mode 和 debug_mode
        # 避免保留旧的 --training-mode/--debug 命令行参数导致新配置不生效
        sm = SettingsManager()
        sm.reload()
        new_train_mode = sm.get("train_mode") or "normal"
        new_debug = bool(sm.get("debug_mode", False))

        # 重启时启动训练器主入口（不带 --right-half），让它重新启动训练器子进程和导入器子进程
        # 过滤掉所有旧参数，完全用新值重建命令行
        filtered = []
        skip_next = False
        for a in sys.argv[1:]:
            if skip_next:
                skip_next = False
                continue
            if a in ("--left-half", "--right-half", "--restart", "--debug"):
                continue
            if a == "--training-mode":
                skip_next = True
                continue
            if a in ("--session-dir", "--data"):
                skip_next = True
                continue
            filtered.append(a)
        # 用新值构建命令行
        filtered.extend(["--training-mode", new_train_mode])
        if new_debug:
            filtered.append("--debug")
        trainer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trainer.pyw")
        restart_argv = [trainer_path, "--restart"] + filtered
        QApplication.quit()
        subprocess.Popen([sys.executable] + restart_argv, creationflags=subprocess.CREATE_NO_WINDOW)
        sys.exit(0)

    def _on_config_changed(self, path):
        """配置文件被外部修改时，实时同步主题等动态生效项。"""
        self._sync_theme_from_config()

    def _sync_theme_from_config(self):
        """从配置文件读取运行时可生效的设置并应用（文件监听 + 定时轮询共用）。

        覆盖：主题、吸附设置。其他设置需重启生效。
        """
        try:
            sm = SettingsManager()
            # mtime 检查：文件未修改则跳过 reload，避免每秒 IO
            config_path = sm.config_path
            try:
                current_mtime = os.path.getmtime(config_path)
            except Exception:
                current_mtime = 0
            if current_mtime == getattr(self, "_config_mtime", 0):
                return  # 文件未变化，直接返回
            self._config_mtime = current_mtime
            sm.reload()  # 文件已修改，重新读取磁盘配置

            # 主题
            theme = sm.get("theme", "light")
            if theme != getattr(self, "_current_theme", None):
                app = QApplication.instance()
                if app is not None:
                    theme = apply_theme(app, theme) or theme
                self._apply_theme_to_window(theme)

            # 吸附设置（仅在值变化时更新，避免拖动过程中被打断）
            new_snap = sm.get("snap_enabled", True)
            if new_snap != getattr(self, "_snap_enabled", True):
                self._snap_enabled = new_snap
            new_threshold = sm.get("snap_threshold", 10)
            if new_threshold != getattr(self, "_snap_threshold", 10):
                self._snap_threshold = new_threshold
            new_snap_grid = sm.get("snap_grid", True)
            if new_snap_grid != getattr(self, "_snap_grid", True):
                self._snap_grid = new_snap_grid

            # 自动保存间隔（变化时重建定时器）
            interval = sm.get("auto_save_interval", 0)
            old_timer = getattr(self, "_auto_save_timer", None)
            old_interval = old_timer.interval() // (60 * 1000) if old_timer is not None else 0
            if isinstance(interval, int) and interval > 0 and interval != old_interval:
                if old_timer is not None:
                    old_timer.stop()
                    old_timer.deleteLater()
                self._auto_save_timer = QTimer(self)
                self._auto_save_timer.timeout.connect(self._do_auto_save)
                self._auto_save_timer.start(interval * 60 * 1000)
            elif (not isinstance(interval, int) or interval <= 0) and old_timer is not None:
                old_timer.stop()
                old_timer.deleteLater()
                self._auto_save_timer = None
        except Exception:
            pass

    def _apply_theme_to_window(self, theme):
        """把主题应用到主窗口：标题栏、背景、分割线、菜单栏。"""
        # 解析 "system/auto" 为实际 light/dark，保证主窗口内按钮（删除/撤销等）
        # 的置灰边框颜色与训练器一致（深色 #444444 / 浅色 #BBBBBB）
        theme = resolve_theme(theme)
        self._current_theme = theme
        is_dark = theme == "dark"
        bg = "#2d2d30" if is_dark else "#f5f5f5"
        fg = "#eeeeee" if is_dark else "#000000"
        handle_bg = "#555555" if is_dark else "#dddddd"

        # 主窗口背景和文字颜色（子控件未显式设置颜色时会继承）
        central = self.centralWidget()
        if central is not None:
            central.setStyleSheet(f"background-color: {bg}; color: {fg};")

        # 分割线颜色
        splitter_style = f"QSplitter {{ background-color: {bg}; }} QSplitter::handle {{ background-color: {handle_bg}; }}"
        for splitter in self.findChildren(QSplitter):
            splitter.setStyleSheet(splitter_style)

        # 菜单栏颜色
        menubar = self.menuBar()
        if menubar is not None:
            menubar.setStyleSheet(
                f"QMenuBar {{ background-color: {bg}; color: {fg}; }}"
                f"QMenuBar::item:selected {{ background-color: {'#1a73e8' if is_dark else '#e0e0e0'}; }}"
                f"QMenu {{ background-color: {bg}; color: {fg}; }}"
                f"QMenu::item:selected {{ background-color: {'#1a73e8' if is_dark else '#e0e0e0'}; }}"
            )

        # 随机生成区 Tab（普通生成/纠偏生成）：嵌套容器局部 QSS 会阻断主 QSS
        # 的 QTabBar 规则，这里显式补上与主窗口一致的深色/浅色样式
        if getattr(self, "_rand_tabs", None) is not None:
            self._rand_tabs.tabBar().setStyleSheet(
                f"QTabBar {{ background-color: {bg}; }}"
                f"QTabBar::tab {{ color: {fg}; background-color: {bg};"
                f" border: 1px solid {'#555555' if is_dark else '#cccccc'}; border-bottom: none;"
                f" border-top-left-radius: 4px; border-top-right-radius: 4px;"
                f" margin-left: 3px; margin-right: 3px; }}"
                f"QTabBar::tab:selected {{ background-color: {'#3c3c3c' if is_dark else '#ffffff'}; }}"
                f"QTabBar::tab:!selected {{ color: {'#cccccc' if is_dark else '#666666'}; }}"
            )

        # 列表（序列/图案/图组标记）：QSplitter 局部 QSS 会阻断主 QSS 的
        # QListWidget 规则继承，导致深色下选中高亮与边框仍为浅色。
        # 这里显式补齐深色/浅色样式，保证选中态在所有尺寸模式一致。
        _list_qss = (
            f"QListWidget {{ background-color: {'#3c3c3c' if is_dark else '#ffffff'};"
            f" color: {fg}; border: 1px solid {'#555555' if is_dark else '#a0a0a0'};"
            f" border-radius: 4px; padding-right: 4px; }}"
            f"QListWidget::item {{ padding: 2px; border-radius: 3px; }}"
            f"QListWidget::item:selected {{ background-color: {'#4FC3F7' if is_dark else '#0078D4'};"
            f" color: {'#1a1a1a' if is_dark else 'white'}; }}"
            f"QListWidget::item:hover:!selected {{ background-color: {'#555555' if is_dark else '#dddddd'}; }}"
        )
        for _lst in self.findChildren(QListWidget):
            _lst.setStyleSheet(_list_qss)

        # 同步全局样式表（缩放/边框/按钮等）到新主题
        self._reapply_stylesheet()

        # Windows 标题栏深浅模式
        apply_dwm_dark_mode(self, is_dark)

        self._update_preview_styles()

    def _update_preview_styles(self):
        """同步预览区（旗帜预览、图片预览）的主题色。"""
        is_dark = getattr(self, "_current_theme", "light") == "dark"
        bg = "#3c3c3c" if is_dark else "#ffffff"
        fg = "#aaaaaa" if is_dark else "#999999"
        border = "#555555" if is_dark else "#dddddd"
        tip_fs = max(int(16 * self._scale), 13)
        sub_color = "#aaaaaa" if is_dark else "#666666"
        sub_fs = max(int(12 * self._scale), 10)

        if getattr(self, "_graphic_image_label", None) is not None:
            self._graphic_image_label.setStyleSheet(
                f"background-color: {bg}; color: {fg}; border: 1px solid {border}; "
                f"font-family: 'Microsoft YaHei UI'; font-size: {tip_fs}px;"
            )

        if getattr(self, "_exp_corr_source_label", None) is not None:
            self._exp_corr_source_label.setStyleSheet(f"color: {sub_color}; font-size: {sub_fs}px;")

        for preview in (getattr(self, "preview_widget", None),
                        getattr(self, "_graphic_banner_preview", None)):
            if preview is not None:
                preview.update()

    def _setup_auto_save(self):
        try:
            interval = SettingsManager().get("auto_save_interval")
        except Exception:
            interval = 0
        if not isinstance(interval, int) or interval <= 0:
            return
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.timeout.connect(self._do_auto_save)
        self._auto_save_timer.start(interval * 60 * 1000)

    def _do_auto_save(self):
        """自动保存到 auto_save_loader_path/<日期>/，根据 importer_auto_save_formats 多格式保存旗帜数据，总数不超过 10 个。"""
        if not getattr(self, "banners", None):
            return
        try:
            from datetime import datetime
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            try:
                formats = SettingsManager().get("importer_auto_save_formats", ["mbtl", "mbtlx"])
            except Exception:
                formats = ["mbtl", "mbtlx"]
            if not isinstance(formats, list):
                formats = [formats]
            if "all" in formats:
                formats = ["mbtl", "mbtlx"]
            sm = SettingsManager()
            base_dir = resolve_app_path(sm.get("auto_save_loader_path", "saves/auto_save/loader"))
            save_dir = os.path.join(base_dir, ts)
            os.makedirs(save_dir, exist_ok=True)
            saved_names = []
            # .mbtl：纯旗帜数据（始终可保存）
            if "mbtl" in formats:
                save_path = os.path.join(save_dir, "banner_auto.mbtl")
                write_mbtl(save_path, self.banners)
                saved_names.append(os.path.basename(save_path))
            # .mbtlx：含图片的标记文件（有序列图组数据时才保存）
            if "mbtlx" in formats and getattr(self, "_graphic_marks", None):
                mbtlx_path = os.path.join(save_dir, "banner_auto.mbtlx")
                if export_mbtlx(mbtlx_path, self._graphic_marks) > 0:
                    saved_names.append(os.path.basename(mbtlx_path))
            # 清理超限的自动保存文件夹
            self._cleanup_auto_saves(base_dir, max_count=10)
            if saved_names:
                self._flash_reminder(f"已自动保存到 {ts}/\n" + "\n".join(saved_names))
        except Exception:
            pass

    def _cleanup_auto_saves(self, base_dir, max_count=10):
        """自动保存日期文件夹总数超过 max_count 时，删除最旧的文件夹。"""
        import shutil
        try:
            folders = []
            for name in os.listdir(base_dir):
                full = os.path.join(base_dir, name)
                if os.path.isdir(full):
                    folders.append((full, os.path.getmtime(full)))
            folders.sort(key=lambda x: x[1])
            while len(folders) > max_count:
                oldest = folders.pop(0)
                try:
                    shutil.rmtree(oldest[0])
                except Exception:
                    pass
        except Exception:
            pass

    def _flash_reminder(self, message):
        try:
            hwnd = int(self.winId())
            class FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p),
                            ("dwFlags", ctypes.c_uint), ("uCount", ctypes.c_uint),
                            ("dwTimeout", ctypes.c_uint)]
            FLASHW_TRAY = 0x00000002
            FLASHW_TIMERNOFG = 0x0000000C
            fwi = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, FLASHW_TRAY | FLASHW_TIMERNOFG, 3, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(fwi))
        except Exception:
            pass
        tip = QLabel(message)
        tip.setAlignment(Qt.AlignCenter)
        tip.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        tip.setStyleSheet(f"""
            QLabel {{
                background-color: #1a73e8;
                color: white;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: {max(int(12 * self._scale), 11)}px;
            }}
        """)
        tip.adjustSize()
        geo = self.geometry()
        tip.move(geo.x() + (geo.width() - tip.width()) // 2, geo.y() + 40)
        tip.show()
        QTimer.singleShot(2000, tip.close)

    def _create_widgets(self):
        central = QWidget()
        self.setCentralWidget(central)
        self._outer_layout = QVBoxLayout(central)
        self._outer_layout.setContentsMargins(5, 5, 5, 5)
        self._outer_layout.setSpacing(0)

        self._create_menu_bar()

        self._create_preview_area()
        self._create_edit_area()
        self._create_right_panel()

        self._main_splitter = QSplitter(Qt.Horizontal)
        self._main_splitter.setHandleWidth(6)  # 与训练器一致：统一工作区间隙宽度
        self._main_splitter.setChildrenCollapsible(False)
        self._main_splitter.splitterMoved.connect(self._on_main_splitter_moved)
        self._right_splitter = QSplitter(Qt.Vertical)
        self._right_splitter.setHandleWidth(6)
        self._right_splitter.setChildrenCollapsible(False)
        self._right_splitter.splitterMoved.connect(self._on_right_splitter_moved)

        self._main_tabs = QTabWidget()
        self._main_tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        seq_import_widget = QWidget()
        seq_import_widget.setMinimumWidth(0)
        seq_import_layout = QVBoxLayout(seq_import_widget)
        seq_import_layout.setContentsMargins(0, 0, 0, 0)
        seq_import_layout.addWidget(self._main_splitter)
        self._main_tabs.addTab(seq_import_widget, "序列导入")

        self._create_graphic_edit_area()
        self._create_graphic_image_area()
        self._create_graphic_banner_preview()
        self._create_graphic_save_panel()

        self._graphic_splitter = QSplitter(Qt.Vertical)
        self._graphic_splitter.setHandleWidth(6)
        self._graphic_splitter.setChildrenCollapsible(False)
        self._graphic_splitter.splitterMoved.connect(self._on_graphic_splitter_moved)
        self._graphic_sub1 = QSplitter(Qt.Horizontal)
        self._graphic_sub1.setHandleWidth(6)
        self._graphic_sub1.setChildrenCollapsible(False)
        self._graphic_sub1.splitterMoved.connect(self._on_graphic_splitter_moved)
        self._graphic_sub2 = QSplitter(Qt.Horizontal)
        self._graphic_sub2.setHandleWidth(6)
        self._graphic_sub2.setChildrenCollapsible(False)
        self._graphic_sub2.splitterMoved.connect(self._on_graphic_splitter_moved)

        seq_graphic_widget = QWidget()
        seq_graphic_widget.setMinimumWidth(0)
        seq_graphic_layout = QVBoxLayout(seq_graphic_widget)
        seq_graphic_layout.setContentsMargins(0, 0, 0, 0)
        seq_graphic_layout.addWidget(self._graphic_splitter)
        self._main_tabs.addTab(seq_graphic_widget, "序列图组导入")
        self._main_tabs.currentChanged.connect(self._on_tab_changed)

        self._outer_layout.addWidget(self._main_tabs)

        self._right_splitter.addWidget(self.preview_group)
        self._right_splitter.addWidget(self.right_group)
        self._main_splitter.addWidget(self.edit_group)
        self._main_splitter.addWidget(self._right_splitter)

    def _graphic_refresh_narrow_sizes(self):
        """兼容旧调用：恢复或默认五五开。"""
        self._graphic_restore_or_default()

    def _graphic_force_relayout(self, attempt=0):
        """Tab2 刚显示时按真实宽度重新布局 graphic splitter。

        Tab 隐藏时（处于 Tab1）graphic_splitter 只有初始小宽度，布局 sizes 按错误宽度生成；
        切到 Tab2 后若 sizes 与实际宽度明显不匹配，重新按当前宽度分配，避免控件缩成一团。
        """
        if self._main_tabs.currentIndex() != 1:
            return
        gw = self._graphic_splitter.width()
        win_w = self.width()
        # 宽度未稳定（Tab 切换布局进行中）时延迟重试
        if gw < win_w * 0.7 and attempt < 6:
            QTimer.singleShot(50, lambda: self._graphic_force_relayout(attempt + 1))
            return
        sizes = self._graphic_splitter.sizes()
        if sizes and sum(sizes) > 0 and gw > 0:
            if abs(sum(sizes) - gw) / gw < 0.3:
                # 宽度已匹配（用户有合理布局），直接恢复工作区
                self._graphic_restore_or_default()
                return
        layout = self.current_layout
        w = self.width()
        if gw <= 0:
            gw = max(w - 20, 400)
        if layout == "narrow":
            total_h = self._graphic_splitter.height()
            if total_h <= 0:
                total_h = max(self.height(), 300)
            self._graphic_splitter.setSizes([total_h // 2, total_h // 2])
            for sub in (self._graphic_sub1, self._graphic_sub2):
                th = sub.height()
                if th <= 0:
                    th = max(total_h // 2, 200)
                n = sub.count()
                if n > 0:
                    sub.setSizes([th // n] * n)
        elif layout == "wide":
            self._graphic_splitter.setSizes([gw // 4, gw // 3, gw - gw // 4 - gw // 3])
            self._graphic_update_wide_minmax(gw)
        elif layout == "ultra_wide":
            self._graphic_splitter.setSizes([gw // 4] * 4)
            self._graphic_update_ultra_wide_minmax(gw)
        self._enforce_splitter_bounds()
        # 之后恢复工作区（用户自定义位置优先）
        self._graphic_restore_or_default()

    def _graphic_restore_or_default(self):
        """恢复 Tab2 splitter 位置：优先工作区文件，未恢复的 splitter 按面板数等分。

        在 layout 应用后的下一事件循环执行，确保 splitter 已有正确尺寸。
        """
        if self._main_tabs.currentIndex() != 1:
            return
        layout_name = self.current_layout
        saved = self._get_workspace_section("importer", layout_name, "tab2")
        applied = self._apply_graphic_sizes(saved) if saved else set()
        # 对未恢复的 splitter 补充默认等分
        def _do_default():
            if self._main_tabs.currentIndex() != 1:
                return
            # 检查 splitter 是否已获得实际尺寸，否则重试
            tw = self._graphic_splitter.width()
            if tw <= 0:
                tw = max(self.width() - 20, 200)
            if "main" not in applied:
                n = self._graphic_splitter.count()
                if n > 0:
                    self._graphic_splitter.setSizes([tw // n] * n)
            if "sub1" not in applied:
                th1 = self._graphic_sub1.height()
                if th1 <= 0:
                    th1 = max(self.height() // 2, 200)
                n1 = self._graphic_sub1.count()
                if n1 > 0 and th1 > 0:
                    self._graphic_sub1.setSizes([th1 // n1] * n1)
            if "sub2" not in applied:
                th2 = self._graphic_sub2.height()
                if th2 <= 0:
                    th2 = max(self.height() // 2, 200)
                n2 = self._graphic_sub2.count()
                if n2 > 0 and th2 > 0:
                    self._graphic_sub2.setSizes([th2 // n2] * n2)
            self._enforce_splitter_bounds()
        QTimer.singleShot(80, _do_default)
        # 已恢复的 splitter 也需要强制约束
        if applied:
            self._enforce_splitter_bounds()
            QTimer.singleShot(50, self._enforce_splitter_bounds)

    def _load_workspace(self):
        """加载整个工作区文件（跨进程共享）。"""
        return load_workspace()

    def _save_workspace(self):
        """兼容旧调用：当前使用 save_workspace_section 原子写入，此处无需整体保存。"""
        pass

    def _get_workspace_section(self, program, layout, tab=None):
        """从工作区数据中读取指定分区。"""
        try:
            data = self._workspace_data
            sec = data.get(program, {}).get(layout, {})
            if tab is not None:
                sec = sec.get(tab, {})
            return sec if isinstance(sec, dict) else None
        except Exception:
            return None

    def _capture_graphic_sizes(self):
        """捕获当前 Tab2 的 splitter sizes，返回 dict。"""
        return {
            "main": list(self._graphic_splitter.sizes()),
            "sub1": list(self._graphic_sub1.sizes()) if self._graphic_sub1.count() > 0 else [],
            "sub2": list(self._graphic_sub2.sizes()) if self._graphic_sub2.count() > 0 else [],
        }

    def _capture_tab1_sizes(self):
        """捕获当前 Tab1 的 splitter sizes，返回 dict。"""
        return {
            "main": list(self._main_splitter.sizes()),
            "right": list(self._right_splitter.sizes()) if self._right_splitter.count() > 0 else [],
        }

    def _apply_graphic_sizes(self, sizes_dict):
        """从 dict 恢复 Tab2 的 splitter 位置（仅当子项数和尺寸有效时）。

        返回 set，包含成功恢复的 splitter 名称（"main"/"sub1"/"sub2"）。
        """
        if not isinstance(sizes_dict, dict):
            return set()
        applied = set()
        try:
            main = sizes_dict.get("main", [])
            sub1 = sizes_dict.get("sub1", [])
            sub2 = sizes_dict.get("sub2", [])
            # 主 splitter：子项数必须与当前一致
            if len(main) == self._graphic_splitter.count() and sum(main) > 0:
                self._graphic_splitter.setSizes(main)
                applied.add("main")
            # sub1：仅当当前有子项时恢复
            if self._graphic_sub1.count() > 0 and len(sub1) == self._graphic_sub1.count() and sum(sub1) > 0:
                self._graphic_sub1.setSizes(sub1)
                applied.add("sub1")
            # sub2：仅当当前有子项时恢复
            if self._graphic_sub2.count() > 0 and len(sub2) == self._graphic_sub2.count() and sum(sub2) > 0:
                self._graphic_sub2.setSizes(sub2)
                applied.add("sub2")
        except Exception:
            pass
        return applied

    def _apply_tab1_sizes(self, sizes_dict):
        """从 dict 恢复 Tab1 的 splitter 位置（仅当子项数和尺寸有效时）。"""
        if not isinstance(sizes_dict, dict):
            return False
        try:
            applied = False
            main = sizes_dict.get("main", [])
            right = sizes_dict.get("right", [])
            if len(main) == self._main_splitter.count() and sum(main) > 0:
                self._main_splitter.setSizes(main)
                applied = True
            if self._right_splitter.count() > 0 and len(right) == self._right_splitter.count() and sum(right) > 0:
                self._right_splitter.setSizes(right)
                applied = True
            return applied
        except Exception:
            return False

    def _restore_tab1_or_default(self):
        """恢复 Tab1 splitter 位置：优先工作区文件，无记录则保持当前默认。"""
        if self._main_tabs.currentIndex() != 0:
            return
        layout_name = self.current_layout
        saved = self._get_workspace_section("importer", layout_name, "tab1")
        if saved and self._apply_tab1_sizes(saved):
            self._enforce_splitter_bounds()

    def _restore_current_tab_workspace(self):
        """统一恢复当前 Tab 的工作区位置（layout 切换后调用）。"""
        idx = self._main_tabs.currentIndex()
        if idx == 0:
            self._restore_tab1_or_default()
        elif idx == 1:
            self._graphic_restore_or_default()

    def _save_window_geometry(self):
        """保存窗口位置和大小到工作区内存。"""
        if SettingsManager().get("restore_layout", True):
            return  # 恢复默认工作区模式：不保存窗口位置
        geo = self.geometry()
        self._workspace_data.setdefault("importer", {})["window"] = {
            "x": geo.x(), "y": geo.y(), "w": geo.width(), "h": geo.height()
        }

    def _restore_window_geometry(self):
        """从工作区文件恢复窗口位置和大小（检查屏幕有效性）。返回 True 表示已恢复。"""
        try:
            win = self._workspace_data.get("importer", {}).get("window", {})
            if not win:
                return False
            x, y, w, h = win.get("x", 0), win.get("y", 0), win.get("w", 0), win.get("h", 0)
            if w <= 0 or h <= 0:
                return False
            from PyQt5.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen is not None:
                vg = screen.virtualGeometry()
                if not vg.intersects(__import__('PyQt5').QtCore.QRect(x, y, w, h)):
                    return False
            self.setGeometry(x, y, w, h)
            return True
        except Exception:
            return False

    def _graphic_clear_splitters(self):
        for w in [self._graphic_sub1, self.graphic_banner_group, self.graphic_image_group,
                  self.graphic_edit_group, self.graphic_save_group]:
            w.setMinimumWidth(0)
            w.setMaximumWidth(16777215)
            w.setMinimumHeight(0)
            w.setMaximumHeight(16777215)
        for s in [self._graphic_splitter, self._graphic_sub1, self._graphic_sub2]:
            while s.count() > 0:
                s.widget(0).setParent(None)

    def apply_narrow_layout(self):
        self._right_splitter.setOrientation(Qt.Vertical)

        # 从 Tab1 超宽 4 栏恢复为 2 栏（编辑 + 右侧预览/操作）
        self._tab1_split_ultra_wide(False)
        self._reset_tab1_ultra_wide_minmax()
        for w in [self._uw_list_group, self._uw_gen_group, self.preview_group]:
            if self._main_splitter.indexOf(w) >= 0:
                w.setParent(None)
        if self._right_splitter.indexOf(self.preview_group) < 0:
            self._right_splitter.insertWidget(0, self.preview_group)
        if self._main_splitter.indexOf(self._right_splitter) < 0:
            self._main_splitter.addWidget(self._right_splitter)

        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 1)
        self._right_splitter.setStretchFactor(0, 2)
        self._right_splitter.setStretchFactor(1, 1)

        w = self.width()
        h = self.height()
        if w > 0:
            self._main_splitter.setSizes([w // 2, w // 2])
        if h > 0:
            self._right_splitter.setSizes([2 * h // 3, h // 3])

        self._right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._expanded_widget.hide()
        self._compact_widget.show()

        self._graphic_clear_splitters()
        self._graphic_splitter.setOrientation(Qt.Horizontal)
        self._graphic_sub1.setOrientation(Qt.Vertical)
        self._graphic_sub2.setOrientation(Qt.Vertical)

        self._graphic_sub1.addWidget(self.graphic_edit_group)
        self._graphic_sub1.addWidget(self.graphic_save_group)
        self._graphic_sub2.addWidget(self.graphic_banner_group)
        self._graphic_sub2.addWidget(self.graphic_image_group)
        self._graphic_splitter.addWidget(self._graphic_sub1)
        self._graphic_splitter.addWidget(self._graphic_sub2)

        self._graphic_splitter.setStretchFactor(0, 1)
        self._graphic_splitter.setStretchFactor(1, 1)
        self._graphic_sub1.setStretchFactor(0, 1)
        self._graphic_sub1.setStretchFactor(1, 1)
        self._graphic_sub2.setStretchFactor(0, 1)
        self._graphic_sub2.setStretchFactor(1, 1)

        gw = self._graphic_splitter.width()
        if gw <= 0:
            gw = max(w // 2, 200) if w > 0 else 400
        gh = max(h // 2, 200) if h > 0 else 300
        self._graphic_splitter.setSizes([gw // 2, gw // 2])
        self._graphic_sub1.setSizes([gh // 2, gh // 2])
        self._graphic_sub2.setSizes([gh // 2, gh // 2])

        self._graphic_save_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._graphic_expanded_save.hide()
        self._graphic_compact_save.show()

        self.current_layout = "narrow"
        self._enforce_splitter_bounds()
        # 优先从工作区文件恢复当前 Tab 的 splitter 位置
        QTimer.singleShot(0, self._restore_current_tab_workspace)

    def apply_wide_layout(self):
        self._right_splitter.setOrientation(Qt.Horizontal)

        # 从 Tab1 超宽 4 栏恢复为 2 栏（编辑 + 右侧预览/操作）
        self._tab1_split_ultra_wide(False)
        self._reset_tab1_ultra_wide_minmax()
        for w in [self._uw_list_group, self._uw_gen_group, self.preview_group]:
            if self._main_splitter.indexOf(w) >= 0:
                w.setParent(None)
        if self._right_splitter.indexOf(self.preview_group) < 0:
            self._right_splitter.insertWidget(0, self.preview_group)
        if self._main_splitter.indexOf(self._right_splitter) < 0:
            self._main_splitter.addWidget(self._right_splitter)

        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 2)
        self._right_splitter.setStretchFactor(0, 1)
        self._right_splitter.setStretchFactor(1, 1)

        w = self.width()
        h = self.height()
        if w > 0:
            self._main_splitter.setSizes([w // 3, 2 * w // 3])
        if h > 0:
            self._right_splitter.setSizes([h // 2, h // 2])

        self._right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._compact_widget.hide()
        self._expanded_widget.show()

        self._graphic_clear_splitters()
        self._graphic_splitter.setOrientation(Qt.Horizontal)
        self._graphic_sub1.setOrientation(Qt.Vertical)

        self._graphic_sub1.addWidget(self.graphic_edit_group)
        self._graphic_sub1.addWidget(self.graphic_save_group)
        self._graphic_splitter.addWidget(self._graphic_sub1)
        self._graphic_splitter.addWidget(self.graphic_banner_group)
        self._graphic_splitter.addWidget(self.graphic_image_group)
        for i in range(3):
            self._graphic_splitter.setStretchFactor(i, 1)

        gw = self._graphic_splitter.width()
        if gw <= 0:
            gw = max(w * 3 // 4, 400) if w > 0 else 800
        gh = max(h, 200) if h > 0 else 300
        self._graphic_sub1.setSizes([gh // 2, gh // 2])
        self._graphic_splitter.setSizes([gw // 4, gw // 3, gw - gw // 4 - gw // 3])
        self._graphic_update_wide_minmax(gw)

        self._graphic_save_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._graphic_compact_save.hide()
        self._graphic_expanded_save.show()

        self.current_layout = "wide"
        self._enforce_splitter_bounds()
        # 优先从工作区文件恢复当前 Tab 的 splitter 位置
        QTimer.singleShot(0, self._restore_current_tab_workspace)

    def apply_ultra_wide_layout(self):
        self._right_splitter.setOrientation(Qt.Horizontal)

        # Tab1 超宽 4 栏：旗帜编辑 / 旗帜预览 / 带染色的旗帜列表 / 自然生成·纠偏生成
        self._tab1_split_ultra_wide(True)
        if self._main_splitter.indexOf(self._right_splitter) >= 0:
            self._right_splitter.setParent(None)
        if self._right_splitter.indexOf(self.preview_group) >= 0:
            self.preview_group.setParent(None)
        for w in [self.edit_group, self.preview_group, self._uw_list_group, self._uw_gen_group]:
            if self._main_splitter.indexOf(w) < 0:
                self._main_splitter.addWidget(w)
        for i in range(4):
            self._main_splitter.setStretchFactor(i, 1)

        w = self.width()
        h = self.height()
        if w > 0:
            self._main_splitter.setSizes([w // 4] * 4)
            self._update_tab1_ultra_wide_minmax(w)
        if h > 0:
            self._right_splitter.setSizes([h // 2, h // 2])

        self._right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._compact_widget.hide()
        self._expanded_widget.hide()

        self._graphic_clear_splitters()
        self._graphic_splitter.setOrientation(Qt.Horizontal)

        self._graphic_splitter.addWidget(self.graphic_edit_group)
        self._graphic_splitter.addWidget(self.graphic_save_group)
        self._graphic_splitter.addWidget(self.graphic_banner_group)
        self._graphic_splitter.addWidget(self.graphic_image_group)
        for i in range(4):
            self._graphic_splitter.setStretchFactor(i, 1)

        gw = self._graphic_splitter.width()
        if gw <= 0:
            gw = w if w > 0 else max(self.sizeHint().width(), 800)
        self._graphic_splitter.setSizes([gw // 4, gw // 4, gw // 4, gw // 4])
        self._graphic_update_ultra_wide_minmax(gw)

        self._graphic_save_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._graphic_compact_save.hide()
        self._graphic_expanded_save.show()

        self.current_layout = "ultra_wide"
        self._enforce_splitter_bounds()
        QTimer.singleShot(50, self._enforce_splitter_bounds)
        # 优先从工作区文件恢复当前 Tab 的 splitter 位置
        QTimer.singleShot(0, self._restore_current_tab_workspace)

    def _create_preview_area(self):
        self.preview_group = QGroupBox("旗帜预览")
        self.preview_group.setStyleSheet("QGroupBox { border: none; padding-top: 16px; }")
        self.preview_group.setMinimumWidth(0)
        preview_layout = QVBoxLayout(self.preview_group)
        self.preview_widget = BannerPreviewWidget()
        self.preview_widget._scale = self._scale
        preview_layout.addWidget(self.preview_widget)

    def _create_edit_area(self):
        self.edit_group = QGroupBox("旗帜编辑")
        self.edit_group.setStyleSheet("QGroupBox { border: none; padding-top: 16px; }")
        self.edit_group.setMinimumWidth(0)
        edit_outer = QVBoxLayout(self.edit_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        edit_inner = QWidget()
        edit_layout = QVBoxLayout(edit_inner)
        edit_layout.setContentsMargins(3, 3, 3, 3)

        bg_label = QLabel("旗帜颜色")
        edit_layout.addWidget(bg_label)

        bg_grid = QWidget()
        bg_grid_layout = QGridLayout(bg_grid)
        bg_grid_layout.setSpacing(1)
        bg_grid_layout.setSizeConstraint(QGridLayout.SetFixedSize)
        self.bg_color_btns = []
        row, col = 0, 0
        for i, name in enumerate(color_name):
            if name == "none":
                continue
            rgb = color[name]
            hex_color = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            btn = ColorButton(hex_color, i, self._scale)
            btn.clicked.connect(lambda checked, idx=i: self.set_background(idx))
            bg_grid_layout.addWidget(btn, row, col)
            self.bg_color_btns.append(btn)
            col += 1
            if col >= 8:
                col = 0
                row += 1
        edit_layout.addWidget(bg_grid)

        pattern_group = QGroupBox("图案选择")
        pattern_layout = QHBoxLayout(pattern_group)

        self.pattern_tree = QTreeWidget()
        self.pattern_tree.setHeaderLabels(["图案"])
        self.pattern_tree.setColumnCount(1)
        for i, pattern in enumerate(banner_type):
            if pattern != 'no':
                zh_name = type_zh[i] if i < len(type_zh) else pattern
                item = QTreeWidgetItem([zh_name])
                item.setData(0, Qt.UserRole, i)
                self.pattern_tree.addTopLevelItem(item)
        self.pattern_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.pattern_tree.itemSelectionChanged.connect(self._limit_pattern_selection)
        pattern_layout.addWidget(self.pattern_tree, 3)

        color_outer = QWidget()
        color_outer_layout = QVBoxLayout(color_outer)
        color_outer_layout.setContentsMargins(0, 0, 0, 0)
        color_label = QLabel("图案颜色")
        color_outer_layout.addWidget(color_label)

        color_grid = QWidget()
        color_grid_layout = QGridLayout(color_grid)
        color_grid_layout.setSpacing(1)
        color_grid_layout.setSizeConstraint(QGridLayout.SetFixedSize)
        self.pattern_color_btns = []
        row, col = 0, 0
        for i, name in enumerate(color_name):
            if name == "none":
                continue
            rgb = color[name]
            hex_color = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            btn = ColorButton(hex_color, i, self._scale)
            btn.clicked.connect(lambda checked, idx=i: self._select_pattern_color(idx))
            color_grid_layout.addWidget(btn, row, col)
            self.pattern_color_btns.append(btn)
            row += 1
            if row >= 8:
                row = 0
                col += 1
        color_outer_layout.addWidget(color_grid)
        color_outer_layout.addStretch()
        pattern_layout.addWidget(color_outer, 1)

        edit_layout.addWidget(pattern_group)

        btn_row = QWidget()
        btn_row_layout = QHBoxLayout(btn_row)
        btn_row_layout.setContentsMargins(0, 0, 0, 0)
        self.add_pattern_btn = QPushButton("添加图案")
        self.add_pattern_btn.clicked.connect(self.add_pattern)
        btn_row_layout.addWidget(self.add_pattern_btn)
        self.insert_seq_btn = QPushButton("插入序列>>")
        self.insert_seq_btn.clicked.connect(self.insert_to_sequence)
        btn_row_layout.addWidget(self.insert_seq_btn)
        self.cancel_edit_btn = QPushButton("取消编辑")
        self.cancel_edit_btn.clicked.connect(self._cancel_edit_mode)
        self.cancel_edit_btn.hide()
        btn_row_layout.addWidget(self.cancel_edit_btn)
        edit_layout.addWidget(btn_row)

        selected_group = QGroupBox("已选择的图案")
        selected_layout = QVBoxLayout(selected_group)
        self.selected_list = QListWidget()
        self.selected_list.setSelectionMode(QListWidget.ExtendedSelection)
        selected_layout.addWidget(self.selected_list)
        sel_btn_row = QWidget()
        sel_btn_row_layout = QHBoxLayout(sel_btn_row)
        sel_btn_row_layout.setContentsMargins(0, 0, 0, 0)
        self.delete_pattern_btn = QPushButton("删除选中图案")
        self.delete_pattern_btn.clicked.connect(self.delete_pattern)
        sel_btn_row_layout.addWidget(self.delete_pattern_btn)
        self.clear_patterns_btn = QPushButton("清空图案")
        self.clear_patterns_btn.clicked.connect(self.clear_patterns)
        sel_btn_row_layout.addWidget(self.clear_patterns_btn)
        selected_layout.addWidget(sel_btn_row)
        edit_layout.addWidget(selected_group)

        scroll.setWidget(edit_inner)
        edit_outer.addWidget(scroll)

        self._edit_buttons = [self.add_pattern_btn, self.insert_seq_btn,
                              self.delete_pattern_btn, self.clear_patterns_btn]
        self._color_buttons = self.bg_color_btns + self.pattern_color_btns

    def _create_right_panel(self):
        self.right_group = QGroupBox("序列与操作")
        self.right_group.setStyleSheet("QGroupBox { border: none; padding-top: 16px; }")
        self.right_group.setMinimumWidth(0)
        right_outer = QVBoxLayout(self.right_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(0)
        self._right_scroll = scroll
        right_inner = QWidget()
        right_inner.setMinimumWidth(0)
        self._right_layout = QVBoxLayout(right_inner)
        self._right_layout.setContentsMargins(3, 3, 3, 3)

        self._compact_widget = QWidget()
        self._compact_widget.setMinimumWidth(0)
        self._expanded_widget = QWidget()
        self._expanded_widget.setMinimumWidth(0)
        self._create_compact_panel()
        self._create_expanded_panel()

        self._right_layout.addWidget(self._compact_widget)
        self._right_layout.addWidget(self._expanded_widget)
        self._expanded_widget.hide()

        scroll.setWidget(right_inner)
        right_outer.addWidget(scroll)

    def _create_graphic_edit_area(self):
        self.graphic_edit_group = QGroupBox("旗帜标记编辑")
        self.graphic_edit_group.setStyleSheet("QGroupBox { border: none; padding-top: 16px; }")
        self.graphic_edit_group.setMinimumWidth(0)
        edit_outer = QVBoxLayout(self.graphic_edit_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        edit_inner = QWidget()
        edit_layout = QVBoxLayout(edit_inner)
        edit_layout.setContentsMargins(3, 3, 3, 3)

        bg_label = QLabel("旗帜颜色")
        edit_layout.addWidget(bg_label)

        bg_grid = QWidget()
        bg_grid_layout = QGridLayout(bg_grid)
        bg_grid_layout.setSpacing(1)
        bg_grid_layout.setSizeConstraint(QGridLayout.SetFixedSize)
        self._graphic_bg_color_btns = []
        row, col = 0, 0
        for i, name in enumerate(color_name):
            if name == "none":
                continue
            rgb = color[name]
            hex_color = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            btn = ColorButton(hex_color, i, self._scale)
            btn.clicked.connect(lambda checked, idx=i: self._graphic_set_background(idx))
            bg_grid_layout.addWidget(btn, row, col)
            self._graphic_bg_color_btns.append(btn)
            col += 1
            if col >= 8:
                col = 0
                row += 1
        edit_layout.addWidget(bg_grid)

        pattern_group = QGroupBox("图案选择")
        pattern_layout = QHBoxLayout(pattern_group)

        self._graphic_pattern_tree = QTreeWidget()
        self._graphic_pattern_tree.setHeaderLabels(["图案"])
        self._graphic_pattern_tree.setColumnCount(1)
        for i, pattern in enumerate(banner_type):
            if pattern != 'no':
                zh_name = type_zh[i] if i < len(type_zh) else pattern
                item = QTreeWidgetItem([zh_name])
                item.setData(0, Qt.UserRole, i)
                self._graphic_pattern_tree.addTopLevelItem(item)
        self._graphic_pattern_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self._graphic_pattern_tree.itemSelectionChanged.connect(self._graphic_limit_pattern_selection)
        pattern_layout.addWidget(self._graphic_pattern_tree, 3)

        color_outer = QWidget()
        color_outer_layout = QVBoxLayout(color_outer)
        color_outer_layout.setContentsMargins(0, 0, 0, 0)
        color_label = QLabel("图案颜色")
        color_outer_layout.addWidget(color_label)

        color_grid = QWidget()
        color_grid_layout = QGridLayout(color_grid)
        color_grid_layout.setSpacing(1)
        color_grid_layout.setSizeConstraint(QGridLayout.SetFixedSize)
        self._graphic_pattern_color_btns = []
        row, col = 0, 0
        for i, name in enumerate(color_name):
            if name == "none":
                continue
            rgb = color[name]
            hex_color = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            btn = ColorButton(hex_color, i, self._scale)
            btn.clicked.connect(lambda checked, idx=i: self._graphic_select_pattern_color(idx))
            color_grid_layout.addWidget(btn, row, col)
            self._graphic_pattern_color_btns.append(btn)
            row += 1
            if row >= 8:
                row = 0
                col += 1
        color_outer_layout.addWidget(color_grid)
        color_outer_layout.addStretch()
        pattern_layout.addWidget(color_outer, 1)

        edit_layout.addWidget(pattern_group)

        btn_row = QWidget()
        btn_row_layout = QHBoxLayout(btn_row)
        btn_row_layout.setContentsMargins(0, 0, 0, 0)
        self._graphic_add_pattern_btn = QPushButton("添加图案")
        self._graphic_add_pattern_btn.clicked.connect(self._graphic_add_pattern)
        btn_row_layout.addWidget(self._graphic_add_pattern_btn)
        self._graphic_mark_btn = QPushButton("标记到图片>>")
        self._graphic_mark_btn.clicked.connect(self._graphic_mark_to_image)
        btn_row_layout.addWidget(self._graphic_mark_btn)
        self._graphic_cancel_edit_btn = QPushButton("取消编辑")
        self._graphic_cancel_edit_btn.clicked.connect(self._graphic_cancel_edit)
        self._graphic_cancel_edit_btn.hide()
        btn_row_layout.addWidget(self._graphic_cancel_edit_btn)
        edit_layout.addWidget(btn_row)

        selected_group = QGroupBox("已选择的图案")
        selected_layout = QVBoxLayout(selected_group)
        self._graphic_selected_list = QListWidget()
        self._graphic_selected_list.setSelectionMode(QListWidget.ExtendedSelection)
        _row_h = max(int(18 * self._scale), 16)
        self._graphic_selected_list.setMinimumHeight(_row_h * 6 + 4)
        selected_layout.addWidget(self._graphic_selected_list)
        sel_btn_row = QWidget()
        sel_btn_row_layout = QHBoxLayout(sel_btn_row)
        sel_btn_row_layout.setContentsMargins(0, 0, 0, 0)
        self._graphic_delete_pattern_btn = QPushButton("删除选中图案")
        self._graphic_delete_pattern_btn.clicked.connect(self._graphic_delete_pattern)
        sel_btn_row_layout.addWidget(self._graphic_delete_pattern_btn)
        self._graphic_clear_patterns_btn = QPushButton("清空图案")
        self._graphic_clear_patterns_btn.clicked.connect(self._graphic_clear_patterns)
        sel_btn_row_layout.addWidget(self._graphic_clear_patterns_btn)
        selected_layout.addWidget(sel_btn_row)
        edit_layout.addWidget(selected_group)

        scroll.setWidget(edit_inner)
        edit_outer.addWidget(scroll)

        self._graphic_bg_color = 0
        self._graphic_pattern_color = None
        self._graphic_current_banner = [0]

    def _create_graphic_image_area(self):
        self.graphic_image_group = QGroupBox("原图展示")
        self.graphic_image_group.setStyleSheet("QGroupBox { border: none; padding-top: 16px; }")
        self.graphic_image_group.setMinimumWidth(0)
        layout = QVBoxLayout(self.graphic_image_group)

        nav_row = QWidget()
        nav_layout = QHBoxLayout(nav_row)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        self._graphic_import_img_btn = QPushButton("导入图片")
        self._graphic_import_img_btn.clicked.connect(self._graphic_import_images)
        nav_layout.addWidget(self._graphic_import_img_btn)
        self._graphic_prev_img_btn = QPushButton("◀")
        self._graphic_prev_img_btn.clicked.connect(self._graphic_prev_image)
        nav_layout.addWidget(self._graphic_prev_img_btn)
        self._graphic_img_index_label = QLabel("0 / 0")
        self._graphic_img_index_label.setAlignment(Qt.AlignCenter)
        nav_layout.addWidget(self._graphic_img_index_label)
        self._graphic_next_img_btn = QPushButton("▶")
        self._graphic_next_img_btn.clicked.connect(self._graphic_next_image)
        nav_layout.addWidget(self._graphic_next_img_btn)
        self._graphic_clear_img_btn = QPushButton("清空图片")
        self._graphic_clear_img_btn.clicked.connect(self._graphic_clear_images)
        nav_layout.addWidget(self._graphic_clear_img_btn)
        layout.addWidget(nav_row)

        self._graphic_image_label = QLabel("导入你的第一张图片")
        self._graphic_image_label.setAlignment(Qt.AlignCenter)
        self._graphic_image_label.setMinimumSize(80, 160)
        self._graphic_image_label.setObjectName("graphic_image_label")
        layout.addWidget(self._graphic_image_label, 1)

        self._graphic_image_files = []
        self._graphic_current_img_idx = -1

    def _create_graphic_banner_preview(self):
        self.graphic_banner_group = QGroupBox("旗帜预览")
        self.graphic_banner_group.setStyleSheet("QGroupBox { border: none; padding-top: 16px; }")
        self.graphic_banner_group.setMinimumWidth(0)
        layout = QVBoxLayout(self.graphic_banner_group)
        self._graphic_banner_preview = BannerPreviewWidget()
        self._graphic_banner_preview._scale = self._scale
        layout.addWidget(self._graphic_banner_preview)

    def _create_graphic_save_panel(self):
        self.graphic_save_group = QGroupBox("标记与保存")
        self.graphic_save_group.setStyleSheet("QGroupBox { border: none; padding-top: 16px; }")
        self.graphic_save_group.setMinimumWidth(0)
        outer_layout = QVBoxLayout(self.graphic_save_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(0)
        self._graphic_save_scroll = scroll
        inner = QWidget()
        inner.setMinimumWidth(0)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(3, 3, 3, 3)

        self._graphic_compact_save = QWidget()
        self._graphic_compact_save.setMinimumWidth(0)
        self._graphic_expanded_save = QWidget()
        self._graphic_expanded_save.setMinimumWidth(0)

        compact_layout = QVBoxLayout(self._graphic_compact_save)
        compact_layout.setContentsMargins(0, 0, 0, 0)
        self._graphic_compact_del_btn = QPushButton("删除标记")
        self._graphic_compact_del_btn.clicked.connect(self._graphic_delete_mark)
        self._graphic_compact_del_btn.setEnabled(False)
        compact_layout.addWidget(self._graphic_compact_del_btn)
        self._graphic_compact_undo_btn = QPushButton("撤销删除")
        self._graphic_compact_undo_btn.clicked.connect(self._undo_delete)
        self._graphic_compact_undo_btn.setEnabled(False)
        compact_layout.addWidget(self._graphic_compact_undo_btn)
        self._graphic_marked_list = QListWidget()
        self._graphic_marked_list.setSelectionMode(QListWidget.ExtendedSelection)
        self._graphic_marked_list.itemSelectionChanged.connect(self._graphic_on_mark_selection)
        compact_layout.addWidget(self._graphic_marked_list, 1)
        compact_bottom = QWidget()
        compact_bottom_layout = QVBoxLayout(compact_bottom)
        compact_bottom_layout.setContentsMargins(0, 0, 0, 0)
        self._graphic_compact_export_btn = QPushButton("导出标记文件")
        self._graphic_compact_export_btn.clicked.connect(self._graphic_export_marks)
        compact_bottom_layout.addWidget(self._graphic_compact_export_btn)
        self._graphic_compact_import_marks_btn = QPushButton("导入标记文件")
        self._graphic_compact_import_marks_btn.clicked.connect(self._graphic_import_marks)
        compact_bottom_layout.addWidget(self._graphic_compact_import_marks_btn)
        compact_layout.addWidget(compact_bottom)

        expanded_layout = QVBoxLayout(self._graphic_expanded_save)
        expanded_layout.setContentsMargins(0, 0, 0, 0)
        exp_btn_row = QWidget()
        exp_btn_row_layout = QHBoxLayout(exp_btn_row)
        exp_btn_row_layout.setContentsMargins(0, 0, 0, 0)
        self._graphic_exp_del_btn = QPushButton("删除标记")
        self._graphic_exp_del_btn.clicked.connect(self._graphic_delete_mark)
        self._graphic_exp_del_btn.setEnabled(False)
        exp_btn_row_layout.addWidget(self._graphic_exp_del_btn)
        self._graphic_exp_undo_btn = QPushButton("撤销删除")
        self._graphic_exp_undo_btn.clicked.connect(self._undo_delete)
        self._graphic_exp_undo_btn.setEnabled(False)
        exp_btn_row_layout.addWidget(self._graphic_exp_undo_btn)
        self._graphic_exp_edit_btn = QPushButton("<<编辑标记")
        self._graphic_exp_edit_btn.clicked.connect(self._graphic_edit_mark)
        self._graphic_exp_edit_btn.hide()
        exp_btn_row_layout.addWidget(self._graphic_exp_edit_btn)
        expanded_layout.addWidget(exp_btn_row)
        self._graphic_exp_marked_list = QListWidget()
        self._graphic_exp_marked_list.setSelectionMode(QListWidget.ExtendedSelection)
        self._graphic_exp_marked_list.itemSelectionChanged.connect(self._graphic_on_mark_selection)
        expanded_layout.addWidget(self._graphic_exp_marked_list, 1)
        exp_bottom = QWidget()
        exp_bottom_layout = QVBoxLayout(exp_bottom)
        exp_bottom_layout.setContentsMargins(0, 0, 0, 0)
        exp_btn_row2 = QWidget()
        exp_btn_row2_layout = QHBoxLayout(exp_btn_row2)
        exp_btn_row2_layout.setContentsMargins(0, 0, 0, 0)
        self._graphic_exp_export_btn = QPushButton("导出标记文件")
        self._graphic_exp_export_btn.clicked.connect(self._graphic_export_marks)
        exp_btn_row2_layout.addWidget(self._graphic_exp_export_btn)
        self._graphic_exp_import_marks_btn = QPushButton("导入标记文件")
        self._graphic_exp_import_marks_btn.clicked.connect(self._graphic_import_marks)
        exp_btn_row2_layout.addWidget(self._graphic_exp_import_marks_btn)
        exp_bottom_layout.addWidget(exp_btn_row2)
        expanded_layout.addWidget(exp_bottom)

        inner_layout.addWidget(self._graphic_compact_save)
        inner_layout.addWidget(self._graphic_expanded_save)
        self._graphic_expanded_save.hide()

        scroll.setWidget(inner)
        outer_layout.addWidget(scroll)

        self._graphic_marks = []

    def _create_compact_panel(self):
        layout = QVBoxLayout(self._compact_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        btn_row = QWidget()
        btn_row_layout = QHBoxLayout(btn_row)
        btn_row_layout.setContentsMargins(0, 0, 0, 0)
        self._compact_del_btn = QPushButton("删除")
        self._compact_del_btn.clicked.connect(self._compact_delete)
        self._compact_del_btn.setEnabled(False)
        btn_row_layout.addWidget(self._compact_del_btn)
        self._compact_undo_btn = QPushButton("撤销删除")
        self._compact_undo_btn.clicked.connect(self._undo_delete)
        self._compact_undo_btn.setEnabled(False)
        btn_row_layout.addWidget(self._compact_undo_btn)
        self._compact_edit_btn = QPushButton("<<编辑该旗帜")
        self._compact_edit_btn.clicked.connect(self.edit_saved_banner)
        self._compact_edit_btn.hide()
        btn_row_layout.addWidget(self._compact_edit_btn)
        layout.addWidget(btn_row)

        self.saved_list = QListWidget()
        self.saved_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.saved_list.itemSelectionChanged.connect(self._on_saved_list_selection)
        self.saved_list.itemSelectionChanged.connect(lambda: self._limit_list_selection(self.saved_list, 4000))
        _row_h = max(int(18 * self._scale), 16)
        self.saved_list.setMinimumHeight(_row_h * 6 + 4)
        layout.addWidget(self.saved_list, 1)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        row1 = QWidget()
        row1_layout = QHBoxLayout(row1)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        self._compact_import_btn = QPushButton("导入序列文件")
        self._compact_import_btn.clicked.connect(self.import_banners)
        row1_layout.addWidget(self._compact_import_btn)
        bottom_layout.addWidget(row1)

        self._compact_random_btn = QPushButton("随机旗帜生成")
        self._compact_random_btn.setObjectName("rand_gen_btn")
        self._compact_random_btn.clicked.connect(self.open_random_settings)
        bottom_layout.addWidget(self._compact_random_btn)

        row2 = QWidget()
        row2_layout = QHBoxLayout(row2)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        self._compact_export_txt_btn = QPushButton("导出序列文件")
        self._compact_export_txt_btn.clicked.connect(self.export_file)
        row2_layout.addWidget(self._compact_export_txt_btn)
        self._compact_export_trainer_btn = QPushButton("导入到训练器")
        self._compact_export_trainer_btn.clicked.connect(self.export_to_trainer)
        row2_layout.addWidget(self._compact_export_trainer_btn)
        bottom_layout.addWidget(row2)

        layout.addWidget(bottom)

        self._seq_buttons = [
            self._compact_del_btn, self._compact_undo_btn, self._compact_edit_btn,
            self._compact_import_btn, self._compact_random_btn,
            self._compact_export_txt_btn, self._compact_export_trainer_btn
        ]

    def _create_expanded_panel(self):
        layout = QVBoxLayout(self._expanded_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        btn_row = QWidget()
        btn_row_layout = QHBoxLayout(btn_row)
        btn_row_layout.setContentsMargins(0, 0, 0, 0)
        self._exp_btn_row = btn_row
        self._exp_del_sel_btn = QPushButton("删除选中")
        self._exp_del_sel_btn.clicked.connect(self._delete_selected)
        self._exp_del_sel_btn.hide()
        btn_row_layout.addWidget(self._exp_del_sel_btn)
        self._exp_del_all_btn = QPushButton("全部删除")
        self._exp_del_all_btn.clicked.connect(self._delete_all)
        self._exp_del_all_btn.setEnabled(False)
        btn_row_layout.addWidget(self._exp_del_all_btn)
        self._exp_del_range_btn = QPushButton("区间删除")
        self._exp_del_range_btn.clicked.connect(self.open_delete_dialog)
        self._exp_del_range_btn.setEnabled(False)
        btn_row_layout.addWidget(self._exp_del_range_btn)
        self._exp_del_btn = QPushButton("删除")
        self._exp_del_btn.clicked.connect(self._delete_selected)
        self._exp_del_btn.hide()
        btn_row_layout.addWidget(self._exp_del_btn)
        self._exp_undo_btn = QPushButton("撤销删除")
        self._exp_undo_btn.clicked.connect(self._undo_delete)
        self._exp_undo_btn.setEnabled(False)
        btn_row_layout.addWidget(self._exp_undo_btn)
        layout.addWidget(btn_row)

        self._exp_edit_btn = QPushButton("<<编辑该旗帜")
        self._exp_edit_btn.clicked.connect(self.edit_saved_banner)
        self._exp_edit_btn.hide()
        layout.addWidget(self._exp_edit_btn)

        self.exp_saved_list = QListWidget()
        self.exp_saved_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.exp_saved_list.itemSelectionChanged.connect(self._on_saved_list_selection)
        self.exp_saved_list.itemSelectionChanged.connect(lambda: self._limit_list_selection(self.exp_saved_list, 4000))
        _row_h = max(int(18 * self._scale), 16)
        self.exp_saved_list.setMinimumHeight(_row_h * 6 + 4)
        layout.addWidget(self.exp_saved_list, 1)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        self._exp_bottom = bottom

        row1 = QWidget()
        row1_layout = QHBoxLayout(row1)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        self._exp_import_btn = QPushButton("导入序列文件")
        self._exp_import_btn.clicked.connect(self.import_banners)
        row1_layout.addWidget(self._exp_import_btn)
        self._exp_export_txt_btn = QPushButton("导出序列文件")
        self._exp_export_txt_btn.clicked.connect(self.export_file)
        row1_layout.addWidget(self._exp_export_txt_btn)
        bottom_layout.addWidget(row1)

        self._exp_export_trainer_btn = QPushButton("导入到训练器")
        self._exp_export_trainer_btn.clicked.connect(self.export_to_trainer)
        bottom_layout.addWidget(self._exp_export_trainer_btn)

        rand_tabs = QTabWidget()
        self._rand_tabs = rand_tabs
        rand_tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        rand_tabs.tabBar().setExpanding(False)
        rand_tabs.setMinimumWidth(0)

        rand_tab_normal = QWidget()
        rand_layout = QGridLayout(rand_tab_normal)
        r = 0
        rand_layout.addWidget(QLabel("数量"), r, 0)
        self._exp_batch_spin = QSpinBox()
        self._exp_batch_spin.setRange(1, 100000)
        self._exp_batch_spin.setValue(self._rand_batch_size)
        rand_layout.addWidget(self._exp_batch_spin, r, 1)

        r += 1
        rand_layout.addWidget(QLabel("配色数"), r, 0)
        color_range = QWidget()
        cr_layout = QHBoxLayout(color_range)
        cr_layout.setContentsMargins(0, 0, 0, 0)
        cr_layout.addWidget(QLabel("最少"))
        self._exp_min_colors_spin = QSpinBox()
        self._exp_min_colors_spin.setRange(1, 16)
        self._exp_min_colors_spin.setValue(self._rand_min_colors)
        cr_layout.addWidget(self._exp_min_colors_spin)
        cr_layout.addWidget(QLabel("最多"))
        self._exp_max_colors_spin = QSpinBox()
        self._exp_max_colors_spin.setRange(1, 16)
        self._exp_max_colors_spin.setValue(self._rand_max_colors)
        self._exp_min_colors_spin.valueChanged.connect(self._exp_max_colors_spin.setMinimum)
        cr_layout.addWidget(self._exp_max_colors_spin)
        rand_layout.addWidget(color_range, r, 1)

        r += 1
        rand_layout.addWidget(QLabel("图案数"), r, 0)
        pattern_range = QWidget()
        pr_layout = QHBoxLayout(pattern_range)
        pr_layout.setContentsMargins(0, 0, 0, 0)
        pr_layout.addWidget(QLabel("最少"))
        self._exp_min_patterns_spin = QSpinBox()
        self._exp_min_patterns_spin.setRange(0, 16)
        self._exp_min_patterns_spin.setValue(self._rand_min_patterns)
        pr_layout.addWidget(self._exp_min_patterns_spin)
        pr_layout.addWidget(QLabel("最多"))
        self._exp_max_patterns_spin = QSpinBox()
        self._exp_max_patterns_spin.setRange(0, 16)
        self._exp_max_patterns_spin.setValue(self._rand_max_patterns)
        self._exp_min_patterns_spin.valueChanged.connect(self._exp_max_patterns_spin.setMinimum)
        pr_layout.addWidget(self._exp_max_patterns_spin)
        rand_layout.addWidget(pattern_range, r, 1)

        def _exp_update_max_colors_limit(v):
            limit = min(self._exp_max_patterns_spin.value() + 1, 16)
            min_limit = min(self._exp_min_patterns_spin.value() + 1, 16)
            self._exp_max_colors_spin.setMaximum(limit)
            self._exp_min_colors_spin.setMaximum(min_limit)
            if self._exp_max_colors_spin.value() > limit:
                self._exp_max_colors_spin.setValue(limit)
            if self._exp_min_colors_spin.value() > min_limit:
                self._exp_min_colors_spin.setValue(min_limit)
        self._exp_max_patterns_spin.valueChanged.connect(_exp_update_max_colors_limit)
        self._exp_min_patterns_spin.valueChanged.connect(lambda v: _exp_update_max_colors_limit(self._exp_max_patterns_spin.value()))
        _exp_update_max_colors_limit(self._exp_max_patterns_spin.value())

        r += 1
        opt_row = QWidget()
        or_layout = QHBoxLayout(opt_row)
        or_layout.setContentsMargins(0, 0, 0, 0)
        self._exp_dup_color_cb = QCheckBox("避免重复旗帜底色")
        self._exp_dup_color_cb.setChecked(self._rand_avoid_dup_color)
        or_layout.addWidget(self._exp_dup_color_cb)
        self._exp_dup_cb = QCheckBox("避免重复旗帜")
        self._exp_dup_cb.setChecked(self._rand_avoid_dup)
        or_layout.addWidget(self._exp_dup_cb)
        rand_layout.addWidget(opt_row, r, 0, 1, 2)

        r += 1
        gen_btn = QPushButton("▶ 生成随机旗帜")
        gen_btn.setObjectName("rand_gen_btn")
        gen_btn.clicked.connect(self._generate_from_expanded)
        rand_layout.addWidget(gen_btn, r, 0, 1, 2)
        rand_tabs.addTab(rand_tab_normal, "普通生成")

        rand_tab_correction = QWidget()
        corr_scroll = QScrollArea()
        corr_scroll.setWidgetResizable(True)
        corr_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        corr_scroll.setFrameShape(QFrame.NoFrame)
        corr_inner = QWidget()
        corr_layout = QGridLayout(corr_inner)
        cr = 0
        corr_layout.addWidget(QLabel("纠偏类型"), cr, 0)
        self._exp_corr_type_combo = QComboBox()
        self._exp_corr_type_combo.addItems(["颜色纠偏", "图案纠偏"])
        corr_layout.addWidget(self._exp_corr_type_combo, cr, 1)

        cr += 1
        self._exp_corr_source_label = QLabel("来源：列表中选中的旗帜（最多50个）")
        self._exp_corr_source_label.setWordWrap(True)
        _is_dark = getattr(self, "_current_theme", "light") == "dark"
        _src_color = "#aaaaaa" if _is_dark else "#666"
        self._exp_corr_source_label.setStyleSheet(f"color: {_src_color}; font-size: {max(int(12 * self._scale), 10)}px;")
        corr_layout.addWidget(self._exp_corr_source_label, cr, 0, 1, 2)

        cr += 1
        self._exp_corr_color_group = QGroupBox("颜色纠偏选项")
        color_gl = QGridLayout(self._exp_corr_color_group)
        self._exp_corr_vary_bg_cb = QCheckBox("变化旗帜色")
        self._exp_corr_vary_bg_cb.setChecked(True)
        color_gl.addWidget(self._exp_corr_vary_bg_cb, 0, 0)
        self._exp_corr_vary_pc_cb = QCheckBox("变化图案颜色")
        self._exp_corr_vary_pc_cb.setChecked(False)
        color_gl.addWidget(self._exp_corr_vary_pc_cb, 0, 1)
        corr_layout.addWidget(self._exp_corr_color_group, cr, 0, 1, 2)

        cr += 1
        self._exp_corr_pattern_group = QGroupBox("图案纠偏选项")
        pattern_gl = QGridLayout(self._exp_corr_pattern_group)
        pattern_gl.addWidget(QLabel("图案类型范围"), 0, 0)
        self._exp_corr_pmin_spin = QSpinBox()
        self._exp_corr_pmin_spin.setRange(1, 42)
        self._exp_corr_pmin_spin.setValue(1)
        pattern_gl.addWidget(self._exp_corr_pmin_spin, 0, 1)
        pattern_gl.addWidget(QLabel("~"), 0, 2)
        self._exp_corr_pmax_spin = QSpinBox()
        self._exp_corr_pmax_spin.setRange(1, 42)
        self._exp_corr_pmax_spin.setValue(42)
        pattern_gl.addWidget(self._exp_corr_pmax_spin, 0, 3)
        corr_layout.addWidget(self._exp_corr_pattern_group, cr, 0, 1, 2)

        cr += 1
        corr_layout.addWidget(QLabel("每组重复"), cr, 0)
        self._exp_corr_repeat_spin = QSpinBox()
        self._exp_corr_repeat_spin.setRange(1, 100)
        self._exp_corr_repeat_spin.setValue(1)
        corr_layout.addWidget(self._exp_corr_repeat_spin, cr, 1)

        cr += 1
        self._exp_corr_no_dup_color_cb = QCheckBox("避免重复旗帜底色")
        self._exp_corr_no_dup_color_cb.setChecked(False)
        corr_layout.addWidget(self._exp_corr_no_dup_color_cb, cr, 0, 1, 2)

        cr += 1
        self._exp_corr_no_dup_banner_cb = QCheckBox("避免重复旗帜")
        self._exp_corr_no_dup_banner_cb.setChecked(True)
        corr_layout.addWidget(self._exp_corr_no_dup_banner_cb, cr, 0, 1, 2)

        cr += 1
        corr_gen_btn = QPushButton("▶ 生成纠偏旗帜")
        corr_gen_btn.clicked.connect(self._generate_correction_from_expanded)
        corr_layout.addWidget(corr_gen_btn, cr, 0, 1, 2)

        corr_scroll.setWidget(corr_inner)
        corr_tab_layout = QVBoxLayout(rand_tab_correction)
        corr_tab_layout.setContentsMargins(0, 0, 0, 0)
        corr_tab_layout.addWidget(corr_scroll)
        rand_tabs.addTab(rand_tab_correction, "纠偏生成")

        def _update_corr_ui(idx):
            self._exp_corr_color_group.setVisible(idx == 0)
            self._exp_corr_pattern_group.setVisible(idx == 1)
        self._exp_corr_type_combo.currentIndexChanged.connect(_update_corr_ui)
        _update_corr_ui(0)

        bottom_layout.addWidget(rand_tabs)
        layout.addWidget(bottom)

        self._seq_buttons.extend([
            self._exp_del_sel_btn, self._exp_del_all_btn, self._exp_del_range_btn,
            self._exp_del_btn, self._exp_undo_btn, self._exp_edit_btn, self._exp_import_btn,
            self._exp_export_txt_btn, self._exp_export_trainer_btn, gen_btn, corr_gen_btn
        ])

        # 超宽模式（Tab1）独立模块：带染色的旗帜列表 / 自然生成·纠偏生成
        self._uw_list_group = QGroupBox("带染色的旗帜列表")
        self._uw_list_group.setStyleSheet("QGroupBox { border: none; padding-top: 16px; }")
        self._uw_list_group.setMinimumWidth(0)
        self._uw_list_group.setLayout(QVBoxLayout())
        self._uw_list_group.layout().setContentsMargins(8, 8, 8, 8)
        self._uw_gen_group = QGroupBox("自然生成 / 纠偏生成")
        self._uw_gen_group.setStyleSheet("QGroupBox { border: none; padding-top: 16px; }")
        self._uw_gen_group.setMinimumWidth(0)
        self._uw_gen_group.setLayout(QVBoxLayout())
        self._uw_gen_group.layout().setContentsMargins(8, 8, 8, 8)
        self._uw_list_group.hide()
        self._uw_gen_group.hide()

    def eventFilter(self, obj, event):
        if event.type() == event.FocusOut:
            if obj in (self.saved_list, self.exp_saved_list):
                if not self._layout_switching and not self._edit_locked:
                    self._deselect_lists()
        if event.type() == event.MouseButtonPress and self._edit_locked:
            if obj is self.edit_group or self.edit_group.isAncestorOf(obj):
                self._deselect_lists()
                return True
        # 支持 Ctrl+C 复制 QListWidget 选中项文本
        if event.type() == QEvent.KeyPress and event.matches(QKeySequence.Copy):
            if isinstance(obj, QListWidget):
                selected = obj.selectedItems()
                if selected:
                    text = "\n".join(it.text() for it in selected)
                    QApplication.clipboard().setText(text)
                    return True
        return super().eventFilter(obj, event)

    def _limit_pattern_selection(self):
        selected = self.pattern_tree.selectedItems()
        if len(selected) > 4:
            for item in selected[4:]:
                item.setSelected(False)

    def _limit_list_selection(self, list_widget, max_count):
        selected = list_widget.selectedItems()
        if len(selected) > max_count:
            for item in selected[max_count:]:
                item.setSelected(False)

    def _on_tab_changed(self, index):
        prev = getattr(self, "_prev_tab_index", 0)
        # 离开当前 Tab 时保存 splitter 位置到内存，并 flush 到磁盘
        if prev == 1 and index != 1:
            self._save_graphic_to_workspace()
            self._flush_workspace_to_disk()
        elif prev == 0 and index != 0:
            self._save_tab1_to_workspace()
            self._flush_workspace_to_disk()
        self._prev_tab_index = index
        if index == 0:
            # 进入 Tab1：从工作区文件恢复
            QTimer.singleShot(0, self._restore_tab1_or_default)
        elif index == 1:
            self._graphic_refresh_preview()
            # 进入 Tab2：Tab2 刚显示，graphic_splitter 才获得真实宽度。
            # 强制按当前宽度重新布局，避免沿用 Tab 隐藏时的错误尺寸（控件缩成一团）
            QTimer.singleShot(0, self._graphic_force_relayout)

    def _tab1_split_ultra_wide(self, active):
        """Tab1 超宽模式：把"带染色的旗帜列表"和"自然生成/纠偏生成"拆为两个独立模块。
        active=True 拆分到 _uw_list_group/_uw_gen_group；False 恢复回 _expanded_widget。"""
        exp_lay = self._expanded_widget.layout()
        list_lay = self._uw_list_group.layout()
        gen_lay = self._uw_gen_group.layout()
        bottom_lay = self._exp_bottom.layout()
        list_widgets = [self._exp_btn_row, self._exp_edit_btn, self.exp_saved_list, self._exp_bottom]
        if active:
            # 从 bottom 中移出生成区，归入独立生成模块
            bottom_lay.removeWidget(self._rand_tabs)
            self._rand_tabs.setParent(self._uw_gen_group)
            gen_lay.addWidget(self._rand_tabs)
            # 列表相关控件归入独立列表模块
            for w in list_widgets:
                exp_lay.removeWidget(w)
                w.setParent(self._uw_list_group)
                list_lay.addWidget(w)
            self._uw_list_group.show()
            self._uw_gen_group.show()
        else:
            # 列表控件放回 _expanded_widget（保持原顺序）
            for w in list_widgets:
                list_lay.removeWidget(w)
                w.setParent(self._expanded_widget)
                exp_lay.addWidget(w)
            # 生成区放回 bottom
            gen_lay.removeWidget(self._rand_tabs)
            self._rand_tabs.setParent(self._exp_bottom)
            bottom_lay.addWidget(self._rand_tabs)
            self._uw_list_group.hide()
            self._uw_gen_group.hide()

    def _update_tab1_ultra_wide_minmax(self, total_w):
        """Tab1 超宽模式：用 Qt 原生 min/max 约束 4 栏在 [1/6, 1/3]（与 Tab2/导入器一致）。"""
        if total_w <= 0:
            return
        min_w = total_w // 6
        max_w = total_w // 3
        for w in [self.edit_group, self.preview_group, self._uw_list_group, self._uw_gen_group]:
            w.setMinimumWidth(min_w)
            w.setMaximumWidth(max_w)

    def _reset_tab1_ultra_wide_minmax(self):
        """清除 Tab1 超宽模式的 min/max 约束（切回宽/窄模式时调用）。"""
        for w in [self.edit_group, self.preview_group, self._uw_list_group, self._uw_gen_group]:
            w.setMinimumWidth(0)
            w.setMaximumWidth(16777215)

    def _apply_layout(self):
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return
        if self._layout_applying:
            return
        ratio = w / h
        if ratio <= 1.0:
            target = "narrow"
        elif ratio <= 16 / 5:
            target = "wide"
        else:
            target = "ultra_wide"
        if target != self.current_layout:
            self._layout_applying = True
            self.setUpdatesEnabled(False)
            try:
                self._layout_switching = True
                old_active = self._get_active_list()
                rows = [old_active.row(item) for item in old_active.selectedItems()] if old_active else []
                if target == "narrow":
                    self.apply_narrow_layout()
                elif target == "wide":
                    self.apply_wide_layout()
                else:
                    self.apply_ultra_wide_layout()
                if rows:
                    new_active = self._get_active_list()
                    self._inhibit_list_events = True
                    for r in rows:
                        item = new_active.item(r)
                        if item:
                            item.setSelected(True)
                    QTimer.singleShot(0, self._release_inhibit)
                self._layout_switching = False
                QTimer.singleShot(50, self._refresh_preview)
            finally:
                self.setUpdatesEnabled(True)
                self._layout_applying = False
        else:
            # 模式不变时也要同步 min/max（窗口 resize 后面板宽度限制需更新）
            self._enforce_splitter_bounds()

    def _on_main_splitter_moved(self, pos, index):
        if self._splitter_adjusting or self._layout_applying:
            return
        self._enforce_splitter_bounds()
        # 用户手动拖动 Tab1 splitter 后，保存到工作区内存（切 Tab 时写文件）
        if self._main_tabs.currentIndex() == 0:
            self._save_tab1_to_workspace()

    def _on_right_splitter_moved(self, pos, index):
        if self._splitter_adjusting or self._layout_applying:
            return
        self._enforce_splitter_bounds()
        if self._right_splitter.orientation() == Qt.Vertical:
            preview_h = self._right_splitter.sizes()[0]
            new_count = min(6, max(1, (preview_h - 40) // 80))
            if new_count != self._max_display_count:
                self._max_display_count = new_count
                if self._last_multiple_indices is not None:
                    self._show_multiple_info(self._last_multiple_indices)
        # 用户手动拖动 Tab1 splitter 后，保存到工作区内存（切 Tab 时写文件）
        if self._main_tabs.currentIndex() == 0:
            self._save_tab1_to_workspace()

    def _snap_to_other(self, src, dst):
        if not getattr(self, "_snap_enabled", True):
            return False
        if src.count() != 2 or dst.count() != 2:
            return False
        src_sizes = src.sizes()
        dst_sizes = dst.sizes()
        src_total = sum(src_sizes)
        dst_total = sum(dst_sizes)
        if src_total <= 0 or dst_total <= 0:
            return False
        src_pos = src_sizes[0]
        dst_ratio = dst_sizes[0] / dst_total
        target_pos = int(dst_ratio * src_total)
        threshold = getattr(self, "_snap_threshold", 10)
        snap_dist = max(int(threshold * self._scale), 8)
        if abs(src_pos - target_pos) < snap_dist and abs(src_pos - target_pos) > 0:
            clamped = max(int(src_total / 3), min(target_pos, int(src_total * 2 / 3)))
            if clamped != src_pos:
                self._splitter_adjusting = True
                src.setSizes([clamped, src_total - clamped])
                self._splitter_adjusting = False
                return True
        return False

    def _on_graphic_splitter_moved(self, pos, index):
        if self._splitter_adjusting or self._layout_applying:
            self._enforce_splitter_bounds()
            return
        sender = self.sender()
        if self.current_layout == "narrow":
            if sender is self._graphic_sub1 and self._snap_to_other(self._graphic_sub1, self._graphic_sub2):
                self._save_graphic_to_workspace()
                return
            if sender is self._graphic_sub2 and self._snap_to_other(self._graphic_sub2, self._graphic_sub1):
                self._save_graphic_to_workspace()
                return
        self._enforce_splitter_bounds()
        # 用户手动拖动后，保存当前 splitter 位置到工作区内存（切 Tab 时写文件）
        self._save_graphic_to_workspace()

    def _save_graphic_to_workspace(self):
        """将当前 Tab2 splitter 位置保存到工作区内存（仅当前在 Tab2 时）。
        切 Tab 或关闭时由调用方写文件。"""
        if self._main_tabs.currentIndex() == 1 and self.current_layout:
            self._workspace_data.setdefault("importer", {}).setdefault(self.current_layout, {})
            self._workspace_data["importer"][self.current_layout]["tab2"] = self._capture_graphic_sizes()

    def _save_tab1_to_workspace(self):
        """将当前 Tab1 splitter 位置保存到工作区内存（仅当前在 Tab1 时）。"""
        if self._main_tabs.currentIndex() == 0 and self.current_layout:
            self._workspace_data.setdefault("importer", {}).setdefault(self.current_layout, {})
            self._workspace_data["importer"][self.current_layout]["tab1"] = self._capture_tab1_sizes()

    def _flush_workspace_to_disk(self):
        """把当前内存中的工作区数据原子写入文件（切 Tab/关闭时调用）。
        只写 importer 自己的 window 和各布局 splitter 数据，不整体覆写。"""
        importer_data = self._workspace_data.get("importer", {})
        # 保存窗口位置
        window_data = importer_data.get("window")
        if isinstance(window_data, dict) and window_data:
            try:
                data = load_workspace()
                if "importer" not in data or not isinstance(data["importer"], dict):
                    data["importer"] = {}
                data["importer"]["window"] = window_data
                from utils.settings_manager import _atomic_write_json, _workspace_file
                _atomic_write_json(_workspace_file(), data)
            except Exception:
                pass
        # 逐 section 保存各布局下的 splitter 数据
        for layout_name, layout_sec in importer_data.items():
            if not isinstance(layout_sec, dict) or layout_name == "window":
                continue
            for tab_name, tab_sec in layout_sec.items():
                if isinstance(tab_sec, dict) and tab_sec:
                    save_workspace_section("importer", layout_name, tab_sec, tab=tab_name)

    def _graphic_update_wide_minmax(self, total_w):
        if total_w <= 0:
            return
        min_w = total_w // 4
        max_w = total_w // 2
        for w in [self._graphic_sub1, self.graphic_banner_group, self.graphic_image_group]:
            w.setMinimumWidth(min_w)
            w.setMaximumWidth(max_w)

    def _graphic_update_ultra_wide_minmax(self, total_w):
        if total_w <= 0:
            return
        min_w = total_w // 6
        max_w = total_w // 3
        for w in [self.graphic_edit_group, self.graphic_save_group,
                  self.graphic_banner_group, self.graphic_image_group]:
            w.setMinimumWidth(min_w)
            w.setMaximumWidth(max_w)

    def _enforce_splitter_bounds(self):
        if self._splitter_adjusting or self._layout_applying:
            return
        total_m = self._main_splitter.width()
        if total_m > 0:
            if self.current_layout == "narrow":
                min_pos = int(total_m / 3)
                max_pos = int(total_m * 2 / 3)
            else:
                min_pos = int(total_m / 4)
                max_pos = int(total_m / 2)
            sizes = self._main_splitter.sizes()
            if len(sizes) == 2:
                left = sizes[0]
                clamped = max(min_pos, min(left, max_pos))
                if left != clamped:
                    self._splitter_adjusting = True
                    self._main_splitter.setSizes([clamped, total_m - clamped])
                    self._splitter_adjusting = False
        total_r = self._right_splitter.width() if self._right_splitter.orientation() == Qt.Horizontal else self._right_splitter.height()
        if total_r > 0:
            if self._right_splitter.orientation() == Qt.Vertical:
                min_pos = int(total_r / 3)
                max_pos = int(total_r * 2 / 3)
            else:
                min_area = int(total_m / 4)
                max_area = int(total_m / 2)
                min_pos = max(min_area, total_r - max_area)
                max_pos = min(max_area, total_r - min_area)
            sizes = self._right_splitter.sizes()
            if len(sizes) == 2:
                first = sizes[0]
                clamped = max(min_pos, min(first, max_pos))
                if first != clamped:
                    self._splitter_adjusting = True
                    self._right_splitter.setSizes([clamped, total_r - clamped])
                    self._splitter_adjusting = False

        if self._graphic_splitter.count() > 0:
            if self.current_layout == "narrow":
                total_h = self._graphic_splitter.width()
                if total_h > 0:
                    min_p = int(total_h / 3)
                    max_p = int(total_h * 2 / 3)
                    sizes = self._graphic_splitter.sizes()
                    if len(sizes) == 2:
                        clamped = max(min_p, min(sizes[0], max_p))
                        if clamped != sizes[0]:
                            self._splitter_adjusting = True
                            self._graphic_splitter.setSizes([clamped, total_h - clamped])
                            self._splitter_adjusting = False
                for sub in [self._graphic_sub1, self._graphic_sub2]:
                    total_v = sub.height()
                    if total_v > 0:
                        min_p = int(total_v / 3)
                        max_p = int(total_v * 2 / 3)
                        sizes = sub.sizes()
                        if len(sizes) == 2:
                            clamped = max(min_p, min(sizes[0], max_p))
                            if clamped != sizes[0]:
                                self._splitter_adjusting = True
                                sub.setSizes([clamped, total_v - clamped])
                                self._splitter_adjusting = False
            elif self.current_layout == "wide":
                total_h = self._graphic_splitter.width()
                if total_h > 0:
                    self._graphic_update_wide_minmax(total_h)
                total_v = self._graphic_sub1.height()
                if total_v > 0:
                    min_p = int(total_v / 3)
                    max_p = int(total_v * 2 / 3)
                    sizes = self._graphic_sub1.sizes()
                    if len(sizes) == 2:
                        clamped = max(min_p, min(sizes[0], max_p))
                        if clamped != sizes[0]:
                            self._splitter_adjusting = True
                            self._graphic_sub1.setSizes([clamped, total_v - clamped])
                            self._splitter_adjusting = False
            elif self.current_layout == "ultra_wide":
                # Tab1 超宽 4 栏：min/max 约束 + 极端兜底均分
                total_m = self._main_splitter.width()
                if total_m > 0:
                    self._update_tab1_ultra_wide_minmax(total_m)
                    sizes_m = self._main_splitter.sizes()
                    nm = len(sizes_m)
                    if nm > 0 and any(s <= 0 or s < total_m // 7 for s in sizes_m):
                        self._splitter_adjusting = True
                        self._main_splitter.setSizes([total_m // nm] * nm)
                        self._splitter_adjusting = False
                total_u = self._graphic_splitter.width()
                if total_u > 0:
                    self._graphic_update_ultra_wide_minmax(total_u)
                    sizes = self._graphic_splitter.sizes()
                    n = len(sizes)
                    if n > 0:
                        quarter = total_u // n
                        # 如果任何面板宽度为 0 或明显小于 1/6，强制均分
                        if any(s <= 0 or s < total_u // 7 for s in sizes):
                            self._splitter_adjusting = True
                            self._graphic_splitter.setSizes([quarter] * n)
                            self._splitter_adjusting = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_layout()
        if self._graphic_current_img_idx >= 0:
            self._graphic_show_current_image()

    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, '_first_show_done'):
            self._first_show_done = True
            self._enforce_splitter_bounds()
            # 初始刷新删除/撤销按钮状态（无数据时删除按钮置灰）
            self._update_undo_btn_state()

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            try:
                msg = ctypes.wintypes.MSG.from_address(message.__int__())
                if msg.message == 0x0024 and int(msg.lParam) != 0:
                    mmi = _win_MINMAXINFO.from_address(int(msg.lParam))
                    self._min_w = max(self._min_w, mmi.ptMinTrackSize.x)
                    self._min_h = max(self._min_h, mmi.ptMinTrackSize.y)
                    mmi.ptMinTrackSize.x = self._min_w
                    mmi.ptMinTrackSize.y = self._min_h
                    return False, 0
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    def _render_banner_pixmap(self, banner_data):
        cache_key = tuple(banner_data)
        if cache_key in self._image_cache:
            base_image = self._image_cache[cache_key]
        else:
            import numpy as np
            import cv2
            image = generate_banner_image(banner_data, size=(200, 400))
            border_size = 2
            new_w, new_h = 200 + 2 * border_size, 400 + 2 * border_size
            new_image = np.ones((new_h, new_w, 3), dtype=np.uint8) * 240
            new_image[border_size:border_size+400, border_size:border_size+200] = image
            cv2.rectangle(new_image, (border_size-1, border_size-1),
                         (new_w-border_size, new_h-border_size), (255,255,255), 2)
            cv2.rectangle(new_image, (border_size, border_size),
                         (new_w-border_size-1, new_h-border_size-1), (0,0,0), 1)
            image_rgb = cv2.cvtColor(new_image, cv2.COLOR_BGR2RGB)
            h_img, w_img = image_rgb.shape[:2]
            bytes_per_line = w_img * 3
            qimg = QImage(image_rgb.data, w_img, h_img, bytes_per_line, QImage.Format_RGB888)
            base_image = QPixmap.fromImage(qimg)
            if len(self._image_cache) >= self._image_cache_max:
                oldest_key = next(iter(self._image_cache))
                del self._image_cache[oldest_key]
            self._image_cache[cache_key] = base_image

        return base_image

    def _refresh_preview(self):
        if self._edit_locked and 0 <= self._selected_banner_index < len(self.banners):
            self._show_preview_of(self.banners[self._selected_banner_index])
        else:
            self.update_preview()

    def update_preview(self):
        self._last_multiple_indices = None
        if not self._banner_touched and self.current_banner == [0]:
            self.preview_widget.setInfoText("导入你的第一幅旗帜")
            return
        pixmap = self._render_banner_pixmap(self.current_banner)
        self.preview_widget.setPixmap(pixmap)

    def _show_preview_of(self, banner_data):
        self._last_multiple_indices = None
        pixmap = self._render_banner_pixmap(banner_data)
        self.preview_widget.setPixmap(pixmap)

    def _graphic_set_background(self, idx):
        self._graphic_bg_color = idx
        for btn in self._graphic_bg_color_btns:
            btn.set_selected(btn.color_idx == idx)
        self._graphic_current_banner[0] = idx
        self._graphic_refresh_preview()

    def _graphic_select_pattern_color(self, idx):
        self._graphic_pattern_color = idx
        for btn in self._graphic_pattern_color_btns:
            btn.set_selected(btn.color_idx == idx)

    def _graphic_limit_pattern_selection(self):
        selected = self._graphic_pattern_tree.selectedItems()
        if len(selected) > 6:
            for item in selected[6:]:
                item.setSelected(False)

    def _graphic_add_pattern(self):
        selected = self._graphic_pattern_tree.selectedItems()
        if not selected:
            MessageBox.warning(self, "提示", "请先选择图案")
            return
        if self._graphic_pattern_color is None:
            MessageBox.warning(self, "提示", "请先选择图案颜色")
            return
        if (len(self._graphic_current_banner) - 1) // 2 >= 16:
            MessageBox.warning(self, "提示", "图案层数已达上限(16层)")
            return
        for item in selected:
            if (len(self._graphic_current_banner) - 1) // 2 >= 16:
                break
            pattern_idx = item.data(0, Qt.UserRole)
            self._graphic_current_banner.extend([pattern_idx, self._graphic_pattern_color])
        self._graphic_refresh_selected_list()
        self._graphic_refresh_preview()

    def _graphic_delete_pattern(self):
        selected = self._graphic_selected_list.selectedItems()
        if not selected:
            return
        self._snapshot_before_delete()
        indices = sorted([self._graphic_selected_list.row(item) for item in selected], reverse=True)
        for idx in indices:
            del self._graphic_current_banner[1 + idx * 2:3 + idx * 2]
        self._graphic_refresh_selected_list()
        self._graphic_refresh_preview()
        self._update_undo_btn_state()

    def _graphic_clear_patterns(self):
        self._snapshot_before_delete()
        self._graphic_current_banner = [self._graphic_current_banner[0]]
        self._graphic_refresh_selected_list()
        self._graphic_refresh_preview()
        self._update_undo_btn_state()

    def _graphic_refresh_selected_list(self):
        self._graphic_selected_list.clear()
        layer = 0
        for i in range(1, len(self._graphic_current_banner), 2):
            if i + 1 < len(self._graphic_current_banner):
                pi = self._graphic_current_banner[i]
                ci = self._graphic_current_banner[i + 1]
                if pi == 0:
                    continue  # 过滤"无"图案
                layer += 1
                zh = type_zh[pi] if pi < len(type_zh) else f"图案{pi}"
                cn = color_name[ci] if ci < len(color_name) else "?"
                self._graphic_selected_list.addItem(f"L{layer}: {zh} - {cn}")
        self._update_undo_btn_state()

    def _graphic_refresh_preview(self):
        if len(self._graphic_current_banner) < 1:
            return
        if not self._graphic_banner_touched and self._graphic_current_banner == [0]:
            self._graphic_banner_preview.setInfoText("导入你的第一幅旗帜")
            return
        banner_data = list(self._graphic_current_banner)
        pixmap = self._render_banner_pixmap(banner_data)
        self._graphic_banner_preview.setPixmap(pixmap)

    def _graphic_mark_to_image(self):
        if self._graphic_current_img_idx < 0:
            MessageBox.warning(self, "提示", "请先导入并选择图片")
            return
        if len(self._graphic_current_banner) < 1:
            MessageBox.warning(self, "提示", "请先编辑旗帜数据")
            return
        img_path = self._graphic_image_files[self._graphic_current_img_idx]
        banner_data = list(self._graphic_current_banner)
        for mark in self._graphic_marks:
            if mark[0] == img_path:
                mark[1] = banner_data
                self._graphic_refresh_marked_list()
                return
        self._graphic_marks.append([img_path, banner_data])
        self._graphic_refresh_marked_list()

    def _graphic_cancel_edit(self):
        self._graphic_cancel_edit_btn.hide()
        self._graphic_exp_edit_btn.hide()
        self._graphic_mark_btn.setText("标记到图片>>")
        self._graphic_current_banner = [0]
        self._graphic_bg_color = 0
        self._graphic_pattern_color = None
        for btn in self._graphic_bg_color_btns:
            btn.set_selected(btn.color_idx == 16)
        for btn in self._graphic_pattern_color_btns:
            btn.set_selected(False)
        self._graphic_refresh_selected_list()
        self._graphic_refresh_preview()

    def _graphic_import_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;所有文件 (*)"
        )
        if not files:
            return
        sm = SettingsManager()
        min_kb = sm.get("import_min_size_kb")
        max_mb = sm.get("import_max_size_mb")
        min_size = min_kb * 1024
        max_size = max_mb * 1024 * 1024
        valid_files = []
        skipped = []
        for fp in files:
            try:
                fsize = os.path.getsize(fp)
                if fsize < min_size:
                    skipped.append(f"{os.path.basename(fp)}: 太小({fsize//1024}KB < {min_kb}KB)")
                elif fsize > max_size:
                    skipped.append(f"{os.path.basename(fp)}: 太大({fsize//(1024*1024)}MB > {max_mb}MB)")
                else:
                    valid_files.append(fp)
            except Exception as e:
                skipped.append(f"{os.path.basename(fp)}: {str(e)}")
        if skipped:
            MessageBox.warning(self, "部分文件被跳过",
                                  f"以下文件因大小限制({min_kb}KB~{max_mb}MB)被跳过:\n" + "\n".join(skipped[:10]))
        if not valid_files:
            return
        self._graphic_image_files.extend(valid_files)
        if self._graphic_current_img_idx < 0:
            self._graphic_current_img_idx = 0
        self._graphic_show_current_image()

    def _graphic_prev_image(self):
        if self._graphic_current_img_idx > 0:
            self._graphic_current_img_idx -= 1
            self._graphic_show_current_image()

    def _graphic_next_image(self):
        if self._graphic_current_img_idx < len(self._graphic_image_files) - 1:
            self._graphic_current_img_idx += 1
            self._graphic_show_current_image()

    def _graphic_clear_images(self):
        self._graphic_image_files.clear()
        self._graphic_current_img_idx = -1
        self._graphic_image_label.setText("导入你的第一张图片")
        self._graphic_img_index_label.setText("0 / 0")

    def _graphic_show_current_image(self):
        total = len(self._graphic_image_files)
        if total == 0 or self._graphic_current_img_idx < 0:
            self._graphic_image_label.setText("导入你的第一张图片")
            self._graphic_img_index_label.setText("0 / 0")
            return
        idx = self._graphic_current_img_idx
        self._graphic_img_index_label.setText(f"{idx + 1} / {total}")
        path = self._graphic_image_files[idx]
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._graphic_image_label.setText("无法加载图片")
            return
        self._graphic_image_label.setPixmap(
            pixmap.scaled(self._graphic_image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _graphic_on_mark_selection(self):
        active_list = self._graphic_exp_marked_list if self._graphic_expanded_save.isVisible() else self._graphic_marked_list
        selected = active_list.selectedItems()
        if selected:
            idx = active_list.row(selected[0])
            if 0 <= idx < len(self._graphic_marks):
                self._graphic_current_banner = list(self._graphic_marks[idx][1])
                self._graphic_bg_color = self._graphic_current_banner[0]
                for btn in self._graphic_bg_color_btns:
                    btn.set_selected(btn.color_idx == self._graphic_bg_color)
                self._graphic_pattern_color = None
                for btn in self._graphic_pattern_color_btns:
                    btn.set_selected(False)
                self._graphic_refresh_selected_list()
                self._graphic_refresh_preview()
                self._graphic_cancel_edit_btn.show()
                self._graphic_exp_edit_btn.show()
                self._graphic_mark_btn.setText("更新标记>>")

    def _graphic_delete_mark(self):
        active_list = self._graphic_exp_marked_list if self._graphic_expanded_save.isVisible() else self._graphic_marked_list
        selected = active_list.selectedItems()
        if not selected:
            return
        self._snapshot_before_delete()
        indices = sorted([active_list.row(item) for item in selected], reverse=True)
        for idx in indices:
            if 0 <= idx < len(self._graphic_marks):
                del self._graphic_marks[idx]
        self._graphic_refresh_marked_list()
        self._update_undo_btn_state()

    def _graphic_edit_mark(self):
        self._graphic_on_mark_selection()

    def _graphic_refresh_marked_list(self):
        self._graphic_marked_list.clear()
        self._graphic_exp_marked_list.clear()
        for i, (img_path, banner_data) in enumerate(self._graphic_marks):
            fname = os.path.basename(img_path)
            recipe = self._format_banner_recipe(banner_data)
            text = f"{fname}: {recipe.replace(chr(10), ', ')}"
            self._graphic_marked_list.addItem(text)
            self._graphic_exp_marked_list.addItem(text)
        self._update_undo_btn_state()

    def _graphic_export_marks(self):
        if not self._graphic_marks:
            MessageBox.warning(self, "提示", "没有可导出的标记")
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出标记文件", "", "标记文件 (*.mbtlx);;所有文件 (*)"
        )
        if not save_path:
            return
        if not save_path.endswith('.mbtlx'):
            save_path += '.mbtlx'
        try:
            # MBTLX 拆分模块统一打包（ZIP：images/ + marks.json）
            count = export_mbtlx(save_path, self._graphic_marks)
            MessageBox.information(self, "导出成功", f"已导出 {count} 条标记（含图片）")
        except Exception as e:
            import traceback as _tb
            report_error("导出失败",
                         f"{str(e)}\n\n--- Traceback ---\n{_tb.format_exc()}", "导入器")

    def _graphic_import_marks(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "导入标记文件", "", "标记文件 (*.mbtlx);;所有文件 (*)"
        )
        if not filepath:
            return
        try:
            # MBTLX 拆分模块统一导入（自动识别 ZIP / 旧文本格式）
            result, _extract_dir = import_mbtlx(filepath)
            self._graphic_marks.extend(result)
            count = len(result)
            self._graphic_refresh_marked_list()
            MessageBox.information(self, "导入成功", f"已导入 {count} 条标记")
        except Exception as e:
            import traceback as _tb
            report_error("导入失败",
                         f"{str(e)}\n\n--- Traceback ---\n{_tb.format_exc()}", "导入器")

    def _format_banner_recipe(self, banner_data):
        bg_name = color_name[banner_data[0]] if banner_data[0] < len(color_name) else "?"
        lines = [f"旗帜色: {bg_name}"]
        pc = len(banner_data) // 2
        if pc > 0:
            layer = 0
            for j in range(1, len(banner_data), 2):
                if j + 1 < len(banner_data):
                    pi = banner_data[j]
                    ci = banner_data[j + 1]
                    if pi == 0:
                        continue  # 过滤"无"图案
                    layer += 1
                    zh = type_zh[pi] if pi < len(type_zh) else f"图案{pi}"
                    cn = color_name[ci] if ci < len(color_name) else "?"
                    lines.append(f"L{layer}: {zh} - {cn}")
        return '\n'.join(lines)

    def _highlight_bg_color(self):
        for btn in self.bg_color_btns:
            btn.set_selected(btn.color_idx == self._bg_selected_idx)

    def _highlight_pattern_color(self):
        for btn in self.pattern_color_btns:
            btn.set_selected(btn.color_idx == self._pc_selected_idx)

    def _select_pattern_color(self, idx):
        self._pc_selected_idx = idx
        self._highlight_pattern_color()

    def set_background(self, color_idx):
        self.current_banner[0] = color_idx
        self._bg_selected_idx = color_idx
        self._highlight_bg_color()
        self.update_preview()

    def add_pattern(self):
        selected = self.pattern_tree.selectedItems()
        if not selected:
            return
        current_layers = (len(self.current_banner) - 1) // 2
        if current_layers >= 16:
            return
        for item in selected[:4]:
            if (len(self.current_banner) - 1) // 2 >= 16:
                break
            pattern_idx = item.data(0, Qt.UserRole)
            color_idx = self._pc_selected_idx
            self.current_banner.extend([pattern_idx, color_idx])
            zh_name = type_zh[pattern_idx] if pattern_idx < len(type_zh) else banner_type[pattern_idx]
            c_name = color_name[color_idx]
            self.selected_list.addItem(f"{zh_name} - {c_name}")
        self.update_preview()
        self._update_undo_btn_state()

    def delete_pattern(self):
        selected = self.selected_list.selectedItems()
        if not selected:
            return
        self._snapshot_before_delete()
        rows = sorted([self.selected_list.row(item) for item in selected], reverse=True)
        for idx in rows:
            del self.current_banner[1 + idx*2 : 1 + (idx+1)*2]
        self._rebuild_selected_list(self.current_banner)
        self.update_preview()
        self._update_undo_btn_state()

    def clear_patterns(self):
        self._snapshot_before_delete()
        self.current_banner = [self.current_banner[0]]
        self.selected_list.clear()
        self.update_preview()
        self._update_undo_btn_state()

    def insert_to_sequence(self):
        if self._editing_index >= 0:
            return
        if len(self.current_banner) <= 1:
            return
        banner_copy = self.current_banner.copy()
        self.banners.append(banner_copy)
        desc = f"旗帜{len(self.banners)},旗帜色={color_name[banner_copy[0]]},图案数={len(banner_copy)//2}"
        self.saved_list.addItem(desc)
        self.exp_saved_list.addItem(desc)
        self._update_data_signal()
        self._update_undo_btn_state()

    def _rebuild_selected_list(self, banner_data):
        self.selected_list.clear()
        for i in range(1, len(banner_data), 2):
            if i+1 < len(banner_data):
                pattern_idx = banner_data[i]
                color_idx = banner_data[i+1]
                if pattern_idx == 0:
                    continue  # 过滤"无"图案
                zh_name = type_zh[pattern_idx] if pattern_idx < len(type_zh) else banner_type[pattern_idx]
                c_name = color_name[color_idx] if color_idx < len(color_name) else "?"
                self.selected_list.addItem(f"{zh_name} - {c_name}")
        self._update_undo_btn_state()

    def _on_saved_list_selection(self):
        if self._inhibit_list_events:
            return
        # 编辑阶段锁定列表，防止选择其他旗帜丢失编辑内容
        if self._editing_index >= 0:
            return
        active = self._get_active_list()
        if active is None:
            return
        selection = active.selectedItems()
        if not selection:
            if self._edit_locked:
                self._deselect_lists()
            return
        rows = sorted([active.row(item) for item in selection])

        if len(rows) == 1:
            index = rows[0]
            if index < len(self.banners):
                if len(self.current_banner) > 1:
                    self._workspace_draft = self.current_banner.copy()
                    self._workspace_draft_pc = self._pc_selected_idx
                banner_data = self.banners[index]
                self._show_preview_of(banner_data)
                # 更新"已选择的图案"列表显示该旗帜的图案
                self._rebuild_selected_list(banner_data)
                # 高亮背景颜色按钮
                self._bg_selected_idx = banner_data[0]
                self._highlight_bg_color()
                # 图案颜色：单个选中时高亮第一个图案的颜色
                if len(banner_data) > 2:
                    self._pc_selected_idx = banner_data[2]
                else:
                    self._pc_selected_idx = -1
                self._highlight_pattern_color()
                self._disable_edit_area()
                self._edit_locked = True
                self._selected_banner_index = index
        elif len(rows) > 1:
            if len(self.current_banner) > 1:
                self._workspace_draft = self.current_banner.copy()
                self._workspace_draft_pc = self._pc_selected_idx
            self._show_multiple_info(rows)
            # 多个旗帜：清空"已选择的图案"列表，清除颜色高亮
            self.selected_list.clear()
            self._bg_selected_idx = -1
            self._highlight_bg_color()
            self._pc_selected_idx = -1
            self._highlight_pattern_color()
            self._disable_edit_area()
            self._edit_locked = True
            self._selected_banner_index = -1

        self._update_edit_btn_visibility()
        self._update_del_sel_btn_visibility()

    def _get_active_list(self):
        if self.current_layout in ("wide", "ultra_wide"):
            return self.exp_saved_list
        return self.saved_list

    def _show_multiple_info(self, indices):
        self._last_multiple_indices = indices
        info_text = f"选中 {len(indices)} 个旗帜：\n\n"
        display_count = min(len(indices), self._max_display_count)
        for idx in indices[:display_count]:
            if idx < len(self.banners):
                banner_data = self.banners[idx]
                bg_name = color_name[banner_data[0]] if banner_data[0] < len(color_name) else "?"
                pc = len(banner_data) // 2
                info_text += f"#{idx+1} 旗帜色:{bg_name}"
                if pc > 0:
                    info_text += "\n"
                    show_p = min(pc, 3)
                    for j in range(1, min(len(banner_data), show_p * 2 + 1), 2):
                        if j+1 < len(banner_data):
                            pi = banner_data[j]
                            ci = banner_data[j+1]
                            zh = type_zh[pi] if pi < len(type_zh) else f"图案{pi}"
                            cn = color_name[ci] if ci < len(color_name) else "?"
                            info_text += f"  {zh}-{cn}"
                    if pc > show_p:
                        info_text += f" 等{pc}个"
                info_text += "\n\n"
        if len(indices) > display_count:
            info_text += f"...共{len(indices)}个"
        callback = (lambda: self._show_detail_dialog(indices)) if len(indices) > self._max_display_count else None
        self.preview_widget.setInfoText(info_text, detail_callback=callback)

    def _show_detail_dialog(self, indices):
        s = self._scale
        is_dark = getattr(self, "_current_theme", "light") == "dark"
        dlg = QDialog(self, Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        dlg.setWindowTitle(f"旗帜序列详情（共{len(indices)}个）")
        # 标题栏深浅色适配（与主窗口一致）
        apply_dwm_dark_mode(dlg, is_dark)
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        sw = geo.width() if geo else 1920
        sh = geo.height() if geo else 1080
        dlg_w = max(int(sw * 0.40), 500)
        # 4:3 固定比例窗口
        dlg_h = int(dlg_w * 3 / 4)
        dlg.setFixedSize(dlg_w, dlg_h)

        # 主题色
        dlg_bg = "#2d2d30" if is_dark else "#ffffff"
        dlg_fg = "#eeeeee" if is_dark else "#000000"
        frame_bg = "#3c3c3c" if is_dark else "#f8f8f8"
        frame_border = "#555555" if is_dark else "#ddd"
        header_color = "#eeeeee" if is_dark else "#333"
        pat_color = "#cccccc" if is_dark else "#444"
        color_box_border = "#777777" if is_dark else "#999"

        dlg.setStyleSheet(f"QDialog {{ background-color: {dlg_bg}; color: {dlg_fg}; }}")

        layout = QVBoxLayout(dlg)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet(f"background-color: {dlg_bg};")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(int(12 * s))

        for idx in indices:
            if idx >= len(self.banners):
                continue
            banner_data = self.banners[idx]
            bg_name = color_name[banner_data[0]] if banner_data[0] < len(color_name) else "?"
            pc = len(banner_data) // 2

            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setStyleSheet(f"QFrame {{ background-color: {frame_bg}; border: 1px solid {frame_border}; border-radius: 8px; padding: 4px; }}")
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(int(14 * s), int(10 * s), int(14 * s), int(10 * s))
            frame_layout.setSpacing(int(4 * s))

            header = QLabel(f"旗帜 #{idx+1}  旗帜色: {bg_name}  图案数: {pc}")
            header.setStyleSheet(f"font-weight: bold; font-size: {max(int(16 * s), 13)}px; color: {header_color};")
            frame_layout.addWidget(header)

            if pc > 0:
                for j in range(1, len(banner_data), 2):
                    if j+1 < len(banner_data):
                        pi = banner_data[j]
                        ci = banner_data[j+1]
                        zh = type_zh[pi] if pi < len(type_zh) else f"图案{pi}"
                        cn = color_name[ci] if ci < len(color_name) else "?"
                        rgb = color[color_name[ci]] if ci < len(color_name) and color_name[ci] in color else (128, 128, 128)
                        hex_c = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}" if isinstance(rgb, (list, tuple)) and len(rgb) >= 3 else "#808080"

                        row = QWidget()
                        row_layout = QHBoxLayout(row)
                        row_layout.setContentsMargins(0, 0, 0, 0)
                        row_layout.setSpacing(int(10 * s))

                        color_box = QLabel()
                        csz = max(int(28 * s), 20)
                        color_box.setFixedSize(csz, csz)
                        color_box.setStyleSheet(f"background-color: {hex_c}; border: 1px solid {color_box_border}; border-radius: 4px;")
                        row_layout.addWidget(color_box)

                        pat_label = QLabel(f"{zh} - {cn}")
                        pat_label.setStyleSheet(f"font-size: {max(int(15 * s), 12)}px; color: {pat_color};")
                        row_layout.addWidget(pat_label)
                        row_layout.addStretch()

                        frame_layout.addWidget(row)

            inner_layout.addWidget(frame)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)

        dlg.exec_()

    def _sync_lists_selection(self):
        active = self._get_active_list()
        inactive = self.exp_saved_list if active == self.saved_list else self.saved_list
        rows = [active.row(item) for item in active.selectedItems()]
        self._inhibit_list_events = True
        inactive.clearSelection()
        for r in rows:
            item = inactive.item(r)
            if item:
                item.setSelected(True)
        QTimer.singleShot(0, self._release_inhibit)

    def _release_inhibit(self):
        self._inhibit_list_events = False

    def _deselect_lists(self):
        self._inhibit_list_events = True
        self._last_multiple_indices = None
        self.saved_list.clearSelection()
        self.exp_saved_list.clearSelection()
        QTimer.singleShot(0, self._release_inhibit)
        self._edit_locked = False
        self._selected_banner_index = -1
        self._editing_index = -1
        if self._workspace_draft is not None:
            self._restore_draft(self._workspace_draft)
        else:
            self._reset_editor()
        self._enable_edit_area()
        self._enable_sequence_area()
        self._restore_import_btn()
        self._update_edit_btn_visibility()
        self._update_del_sel_btn_visibility()

    def _restore_draft(self, draft):
        self.current_banner = draft.copy()
        self._rebuild_selected_list(draft)
        self._bg_selected_idx = draft[0]
        self._highlight_bg_color()
        if self._workspace_draft_pc is not None:
            self._pc_selected_idx = self._workspace_draft_pc
            self._highlight_pattern_color()
        self.update_preview()
        self._workspace_draft = None
        self._workspace_draft_pc = None

    def _reset_editor(self):
        self.current_banner = [0]
        self.selected_list.clear()
        self._bg_selected_idx = 16
        self._highlight_bg_color()
        self._pc_selected_idx = 1
        self._highlight_pattern_color()

    def _enable_edit_area(self):
        for btn in self._color_buttons:
            btn.set_enabled(True)
        self.pattern_tree.setEnabled(True)
        self.selected_list.setEnabled(True)
        for btn in self._edit_buttons:
            btn.setEnabled(True)
        # 删除/清空图案按钮按选中列表内容纠正状态
        self._update_undo_btn_state()

    def _disable_edit_area(self):
        for btn in self._color_buttons:
            btn.set_enabled(False)
        self.pattern_tree.setEnabled(False)
        self.selected_list.setEnabled(False)
        for btn in self._edit_buttons:
            btn.setEnabled(False)

    def _enable_sequence_area(self):
        self.right_group.setEnabled(True)
        for btn in self._seq_buttons:
            btn.setEnabled(True)
        # 删除/撤销按钮的状态由 _update_undo_btn_state 统一管理（有数据才可删/撤销）
        self._update_undo_btn_state()
        self.saved_list.setEnabled(True)
        self.exp_saved_list.setEnabled(True)

    def _disable_sequence_area(self):
        self.right_group.setEnabled(False)
        for btn in self._seq_buttons:
            if btn not in (self.insert_seq_btn, self.cancel_edit_btn):
                btn.setEnabled(False)
        self.saved_list.setEnabled(False)
        self.exp_saved_list.setEnabled(False)

    def _init_preview_text(self):
        self.preview_widget.setInfoText("导入你的第一幅旗帜")
        self._graphic_banner_preview.setInfoText("导入你的第一幅旗帜")

    def _update_edit_btn_visibility(self):
        if self._editing_index >= 0:
            self._exp_edit_btn.show()
            self._compact_edit_btn.show()
            return
        active = self._get_active_list()
        if not active.isEnabled():
            self._exp_edit_btn.hide()
            self._compact_edit_btn.hide()
            return
        rows = [active.row(item) for item in active.selectedItems()]
        if len(rows) == 1 and rows[0] < len(self.banners):
            self._exp_edit_btn.show()
            self._compact_edit_btn.show()
        else:
            self._exp_edit_btn.hide()
            self._compact_edit_btn.hide()

    def _update_del_sel_btn_visibility(self):
        active = self._get_active_list()
        has_selection = bool(active.selectedItems())
        self._exp_del_sel_btn.setVisible(False)
        if has_selection:
            self._exp_del_all_btn.hide()
            self._exp_del_range_btn.hide()
            self._exp_del_btn.show()
        else:
            self._exp_del_all_btn.show()
            self._exp_del_range_btn.show()
            self._exp_del_btn.hide()

    def edit_saved_banner(self):
        active = self._get_active_list()
        rows = [active.row(item) for item in active.selectedItems()]
        if not rows:
            MessageBox.warning(self, "警告", "请先选择要编辑的旗帜")
            return
        if len(rows) > 1:
            MessageBox.warning(self, "警告", "只能编辑单个旗帜，请选择一个旗帜")
            return
        idx = rows[0]
        if idx >= len(self.banners):
            return
        self._do_edit_banner(idx)

    def _do_edit_banner(self, idx):
        # 仅在 draft 未保存时保存（避免覆盖 _on_saved_list_selection 中已保存的正确 draft）
        if len(self.current_banner) > 1 and self._workspace_draft is None:
            self._workspace_draft = self.current_banner.copy()
            self._workspace_draft_pc = self._pc_selected_idx
        self._edit_locked = False
        self._editing_index = idx
        self._selected_banner_index = idx
        self._enable_edit_area()
        banner_data = self.banners[idx]
        self.current_banner = banner_data.copy()
        self._rebuild_selected_list(banner_data)
        self._bg_selected_idx = banner_data[0]
        self._highlight_bg_color()
        self.update_preview()
        self._disable_sequence_area()
        self._switch_import_btn_to_save()
        self._update_edit_btn_visibility()
        self._inhibit_list_events = True
        self.saved_list.item(idx).setSelected(True)
        self.exp_saved_list.item(idx).setSelected(True)
        self.saved_list.updateGeometry()
        self.exp_saved_list.updateGeometry()
        self.saved_list.verticalScrollBar().updateGeometry()
        self.exp_saved_list.verticalScrollBar().updateGeometry()
        QTimer.singleShot(0, self._release_inhibit)

    def _switch_import_btn_to_save(self):
        self.insert_seq_btn.setText("保存修改>>")
        self.insert_seq_btn.clicked.disconnect()
        self.insert_seq_btn.clicked.connect(self._save_edit_changes)
        if self._editing_index >= 0:
            self.cancel_edit_btn.show()

    def _restore_import_btn(self):
        self.insert_seq_btn.setText("插入序列>>")
        self.insert_seq_btn.clicked.disconnect()
        self.insert_seq_btn.clicked.connect(self.insert_to_sequence)
        self.cancel_edit_btn.hide()

    def _save_edit_changes(self):
        if self._editing_index < 0 or self._editing_index >= len(self.banners):
            return
        self.banners[self._editing_index] = self.current_banner.copy()
        idx = self._editing_index
        self._enable_sequence_area()
        self._restore_import_btn()
        self._inhibit_list_events = True
        self.saved_list.clear()
        self.exp_saved_list.clear()
        for i, b in enumerate(self.banners):
            desc = f"旗帜{i+1},旗帜色={color_name[b[0]]},图案数={len(b)//2}"
            self.saved_list.addItem(desc)
            self.exp_saved_list.addItem(desc)
        self.saved_list.item(idx).setSelected(True)
        self.exp_saved_list.item(idx).setSelected(True)
        QTimer.singleShot(0, self._release_inhibit)
        # 回到查看状态：显示保存后的旗帜，编辑区置灰
        banner_data = self.banners[idx]
        self._show_preview_of(banner_data)
        self._rebuild_selected_list(banner_data)
        self._bg_selected_idx = banner_data[0]
        self._highlight_bg_color()
        if len(banner_data) > 2:
            self._pc_selected_idx = banner_data[2]
        else:
            self._pc_selected_idx = -1
        self._highlight_pattern_color()
        self._disable_edit_area()
        self._edit_locked = True
        self._editing_index = -1
        self._selected_banner_index = idx
        self._update_edit_btn_visibility()
        self._update_del_sel_btn_visibility()

    def _cancel_edit_mode(self):
        if self._editing_index >= 0:
            saved_idx = self._editing_index
            if self._workspace_draft is not None:
                self._restore_draft(self._workspace_draft)
                self._edit_locked = False
                self._editing_index = -1
                self._selected_banner_index = -1
                self._enable_edit_area()
                self._enable_sequence_area()
                self._restore_import_btn()
                self._inhibit_list_events = True
                self.saved_list.clearSelection()
                self.exp_saved_list.clearSelection()
                QTimer.singleShot(0, self._release_inhibit)
            else:
                self._reset_editor()
                self._edit_locked = True
                self._editing_index = -1
                self._selected_banner_index = saved_idx
                self._disable_edit_area()
                self._enable_sequence_area()
                self._restore_import_btn()
                self._inhibit_list_events = True
                self.saved_list.clearSelection()
                self.exp_saved_list.clearSelection()
                QTimer.singleShot(0, self._release_inhibit)
                QTimer.singleShot(10, lambda: self._restore_selection(saved_idx))
        else:
            self._deselect_lists()
        self._update_edit_btn_visibility()

    def _restore_selection(self, idx):
        if 0 <= idx < len(self.banners):
            item1 = self.saved_list.item(idx)
            item2 = self.exp_saved_list.item(idx)
            if item1:
                item1.setSelected(True)
            if item2:
                item2.setSelected(True)
            self._show_preview_of(self.banners[idx])

    def update_saved_list_display(self):
        self.saved_list.clear()
        self.exp_saved_list.clear()

        dup_map = {}
        for i, banner_data in enumerate(self.banners):
            key = tuple(banner_data)
            if key not in dup_map:
                dup_map[key] = []
            dup_map[key].append(i)

        for i, banner_data in enumerate(self.banners):
            key = tuple(banner_data)
            is_dup = len(dup_map[key]) > 1
            dup_info = f"[×{len(dup_map[key])}] " if is_dup else ""
            desc = f"{dup_info}旗帜{i+1},旗帜色={color_name[banner_data[0]]},图案数={len(banner_data)//2}"
            item_s = QListWidgetItem(desc)
            item_e = QListWidgetItem(desc)
            if is_dup:
                item_s.setForeground(QColor("#c62828"))
                item_e.setForeground(QColor("#c62828"))
                font = item_s.font()
                font.setBold(True)
                item_s.setFont(font)
                item_e.setFont(font)
            self.saved_list.addItem(item_s)
            self.exp_saved_list.addItem(item_e)

        self.saved_list.updateGeometry()
        self.exp_saved_list.updateGeometry()
        self.saved_list.verticalScrollBar().updateGeometry()
        self.exp_saved_list.verticalScrollBar().updateGeometry()
        if self._right_scroll is not None:
            self._right_scroll.updateGeometry()

    # ---- 删除撤销：快照 + 恢复，统一序列/图案/图组标记与各尺寸模式 ----
    def _snapshot_before_delete(self):
        """删除前快照数据（序列、当前编辑图案、图组标记），供撤销恢复。"""
        self._banners_backup = [list(b) for b in self.banners]
        self._current_banner_backup = (
            list(self.current_banner) if getattr(self, "current_banner", None) else None)
        self._graphic_cb_backup = (
            list(self._graphic_current_banner) if getattr(self, "_graphic_current_banner", None) else None)
        self._graphic_marks_backup = [list(m) for m in self._graphic_marks]
        self._update_undo_btn_state()

    def _undo_delete(self):
        """撤销最近一次删除，恢复全部快照并刷新各列表。"""
        if not (getattr(self, "_banners_backup", None) or
                getattr(self, "_current_banner_backup", None) or
                getattr(self, "_graphic_cb_backup", None) or
                getattr(self, "_graphic_marks_backup", None)):
            MessageBox.information(self, "撤销删除", "没有可撤销的删除操作")
            return
        if getattr(self, "_banners_backup", None) is not None:
            self.banners = [list(b) for b in self._banners_backup]
        if getattr(self, "_current_banner_backup", None) is not None:
            self.current_banner = list(self._current_banner_backup)
        if getattr(self, "_graphic_cb_backup", None) is not None:
            self._graphic_current_banner = list(self._graphic_cb_backup)
        if getattr(self, "_graphic_marks_backup", None) is not None:
            self._graphic_marks = [list(m) for m in self._graphic_marks_backup]
        self._banners_backup = None
        self._current_banner_backup = None
        self._graphic_cb_backup = None
        self._graphic_marks_backup = None
        self._after_delete()
        self._graphic_refresh_marked_list()
        self._graphic_refresh_selected_list()
        self._rebuild_selected_list(self.current_banner)
        self.update_preview()
        self._update_undo_btn_state()

    def _update_undo_btn_state(self):
        """所有尺寸模式的删除/撤销按钮可用状态。
        撤销按钮：有快照时可撤销；删除按钮：有旗帜数据时可删除。"""
        has_backup = bool(getattr(self, "_banners_backup", None) or
                          getattr(self, "_current_banner_backup", None) or
                          getattr(self, "_graphic_cb_backup", None) or
                          getattr(self, "_graphic_marks_backup", None))
        for btn_name in ("_compact_undo_btn", "_exp_undo_btn",
                         "_graphic_compact_undo_btn", "_graphic_exp_undo_btn"):
            btn = getattr(self, btn_name, None)
            if btn is not None:
                btn.setEnabled(has_backup)
        # 删除按钮：有数据才可删除（图形标记区按 _graphic_marks，序列区按 banners）
        has_banners = bool(getattr(self, "banners", None))
        has_graphic_marks = bool(getattr(self, "_graphic_marks", None))
        for btn_name in ("_compact_del_btn", "_exp_del_all_btn", "_exp_del_range_btn"):
            btn = getattr(self, btn_name, None)
            if btn is not None:
                btn.setEnabled(has_banners)
        for btn_name in ("_graphic_compact_del_btn", "_graphic_exp_del_btn"):
            btn = getattr(self, btn_name, None)
            if btn is not None:
                btn.setEnabled(has_graphic_marks)
        # 图案编辑区：有已选图案才可删除/清空（Tab1 + Tab2 图组编辑）
        has_selected = bool(getattr(self, "selected_list", None)
                            and self.selected_list.count() > 0)
        has_graphic_selected = bool(getattr(self, "_graphic_selected_list", None)
                                    and self._graphic_selected_list.count() > 0)
        for btn_name in ("delete_pattern_btn", "clear_patterns_btn"):
            btn = getattr(self, btn_name, None)
            if btn is not None:
                btn.setEnabled(has_selected)
        for btn_name in ("_graphic_delete_pattern_btn", "_graphic_clear_patterns_btn"):
            btn = getattr(self, btn_name, None)
            if btn is not None:
                btn.setEnabled(has_graphic_selected)

    def _after_delete(self):
        self.update_saved_list_display()
        self.selected_list.clear()
        self._edit_locked = False
        self._editing_index = -1
        self._selected_banner_index = -1
        if not self.banners:
            # 工作区无旗帜：回到新建初始状态，预览显示"导入你的第一幅旗帜"
            self._reset_editor()
            self._enable_edit_area()
            self._enable_sequence_area()
            self._restore_import_btn()
            self._update_edit_btn_visibility()
            self._update_del_sel_btn_visibility()
            self._update_data_signal()
            self.update_preview()
        else:
            # 仍有旗帜：清空选择回到新建状态
            self._deselect_lists()
            self._update_data_signal()
        self._update_undo_btn_state()

    def _delete_selected(self):
        active = self._get_active_list()
        rows = sorted([active.row(item) for item in active.selectedItems()])
        if not rows:
            MessageBox.warning(self, "警告", "请先选择要删除的旗帜")
            return
        # 革命性优化：删除选中免确认，随时可用「撤销删除」恢复
        self._snapshot_before_delete()
        for idx in reversed(rows):
            if idx < len(self.banners):
                del self.banners[idx]
        self._after_delete()

    def _delete_all(self):
        if not self.banners:
            return
        if MessageBox.question(self, "确认删除", f"确定要删除全部 {len(self.banners)} 个旗帜吗？") == QMessageBox.Yes:
            self._snapshot_before_delete()
            self.banners.clear()
            self._after_delete()

    def _compact_delete(self):
        self.open_delete_dialog()

    def open_delete_dialog(self):
        if not self.banners:
            MessageBox.warning(self, "警告", "没有可删除的旗帜")
            return
        active = self._get_active_list()
        rows = [active.row(item) for item in active.selectedItems()]

        dlg = QDialog(self, Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        dlg.setWindowTitle("删除旗帜")
        # 4:3 固定比例窗口
        dlg.setFixedSize(int(400 * self._scale), int(300 * self._scale))
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel(f"当前共有 {len(self.banners)} 个旗帜"))

        if rows:
            if len(rows) == 1:
                info = f"已选中: 旗帜 {rows[0]+1}"
            else:
                info = f"已选中 {len(rows)} 个旗帜"
            layout.addWidget(QLabel(info))

            def delete_selected():
                self._snapshot_before_delete()
                for idx in reversed(rows):
                    if idx < len(self.banners):
                        del self.banners[idx]
                self._after_delete()
                dlg.accept()
            btn = QPushButton("删除选中")
            btn.clicked.connect(delete_selected)
            layout.addWidget(btn)

            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            layout.addWidget(line)

        def delete_all():
            if MessageBox.question(dlg, "确认删除", f"确定要删除全部 {len(self.banners)} 个旗帜吗？") == QMessageBox.Yes:
                self._snapshot_before_delete()
                self.banners.clear()
                self._after_delete()
                dlg.accept()
                MessageBox.information(self, "删除成功", "已删除全部旗帜")
        btn2 = QPushButton("全部删除")
        btn2.clicked.connect(delete_all)
        layout.addWidget(btn2)

        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        layout.addWidget(line2)

        range_row = QWidget()
        rr_layout = QHBoxLayout(range_row)
        rr_layout.setContentsMargins(0, 0, 0, 0)
        rr_layout.addWidget(QLabel("范围"))
        range_input = QLineEdit()
        range_input.setPlaceholderText(f"例如：1~12,20~31（共{len(self.banners)}面）")
        rr_layout.addWidget(range_input)
        layout.addWidget(range_row)

        def delete_range():
            text = range_input.text().strip()
            if not text:
                MessageBox.critical(dlg, "错误", "请输入要删除的范围，例如：1~12,20~31")
                return
            # 解析多区间输入（逗号分隔，每个区间用~连接起止）
            indices = set()
            parts = text.split(",")
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if "~" in part:
                    s_str, e_str = part.split("~", 1)
                    try:
                        s, e = int(s_str.strip()), int(e_str.strip())
                    except ValueError:
                        MessageBox.critical(dlg, "错误", f"无法解析范围：{part}")
                        return
                else:
                    try:
                        s = e = int(part)
                    except ValueError:
                        MessageBox.critical(dlg, "错误", f"无法解析：{part}")
                        return
                if s < 1 or e > len(self.banners) or s > e:
                    MessageBox.critical(dlg, "错误", f"范围无效：{part}（有效范围：1~{len(self.banners)}）")
                    return
                for i in range(s, e + 1):
                    indices.add(i - 1)
            cnt = len(indices)
            if cnt == 0:
                MessageBox.critical(dlg, "错误", "未指定任何有效范围")
                return
            if MessageBox.question(dlg, "确认删除", f"确定要删除 {text} 共{cnt}个旗帜吗？") == QMessageBox.Yes:
                self._snapshot_before_delete()
                for idx in sorted(indices, reverse=True):
                    if idx < len(self.banners):
                        del self.banners[idx]
                self._after_delete()
                dlg.accept()
                MessageBox.information(self, "删除成功", f"已删除{cnt}个旗帜")
        btn3 = QPushButton("区间删除")
        btn3.clicked.connect(delete_range)
        layout.addWidget(btn3)

        dlg.exec_()

    def open_random_settings(self):
        dlg = QDialog(self, Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        dlg.setWindowTitle("随机生成设置")
        # 4:3 固定比例窗口
        dlg.setFixedSize(int(520 * self._scale), int(390 * self._scale))
        dlg_layout = QVBoxLayout(dlg)

        tabs = QTabWidget()

        normal_tab = QWidget()
        layout = QGridLayout(normal_tab)

        layout.addWidget(QLabel("生成旗帜数量:"), 0, 0)
        batch_spin = QSpinBox()
        batch_spin.setRange(1, 100000)
        batch_spin.setValue(self._rand_batch_size)
        layout.addWidget(batch_spin, 0, 1)

        layout.addWidget(QLabel("最少配色数:"), 1, 0)
        min_c_spin = QSpinBox()
        min_c_spin.setRange(1, 16)
        min_c_spin.setValue(self._rand_min_colors)
        layout.addWidget(min_c_spin, 1, 1)

        layout.addWidget(QLabel("最多配色数:"), 2, 0)
        max_c_spin = QSpinBox()
        max_c_spin.setRange(1, 16)
        max_c_spin.setValue(self._rand_max_colors)
        min_c_spin.valueChanged.connect(max_c_spin.setMinimum)
        layout.addWidget(max_c_spin, 2, 1)

        layout.addWidget(QLabel("最少图案数:"), 3, 0)
        min_p_spin = QSpinBox()
        min_p_spin.setRange(0, 16)
        min_p_spin.setValue(self._rand_min_patterns)
        layout.addWidget(min_p_spin, 3, 1)

        layout.addWidget(QLabel("最多图案数:"), 4, 0)
        max_p_spin = QSpinBox()
        max_p_spin.setRange(0, 16)
        max_p_spin.setValue(self._rand_max_patterns)
        min_p_spin.valueChanged.connect(max_p_spin.setMinimum)
        layout.addWidget(max_p_spin, 4, 1)

        def _update_max_colors_limit(v):
            limit = min(max_p_spin.value() + 1, 16)
            min_limit = min(min_p_spin.value() + 1, 16)
            max_c_spin.setMaximum(limit)
            min_c_spin.setMaximum(min_limit)
            if max_c_spin.value() > limit:
                max_c_spin.setValue(limit)
            if min_c_spin.value() > min_limit:
                min_c_spin.setValue(min_limit)
        max_p_spin.valueChanged.connect(_update_max_colors_limit)
        min_p_spin.valueChanged.connect(lambda v: _update_max_colors_limit(max_p_spin.value()))
        _update_max_colors_limit(max_p_spin.value())

        dup_color_cb = QCheckBox("避免重复旗帜底色")
        dup_color_cb.setChecked(self._rand_avoid_dup_color)
        layout.addWidget(dup_color_cb, 5, 0, 1, 2)

        dup_cb = QCheckBox("避免重复旗帜")
        dup_cb.setChecked(self._rand_avoid_dup)
        layout.addWidget(dup_cb, 6, 0, 1, 2)

        def do_generate():
            batch = batch_spin.value()
            min_c = min_c_spin.value()
            max_c = max_c_spin.value()
            min_p = min_p_spin.value()
            max_p = max_p_spin.value()
            errors = self._validate_random_params(batch, min_c, max_c, min_p, max_p)
            if errors:
                MessageBox.critical(dlg, "参数错误", "\n".join(errors))
                return
            self._rand_batch_size = batch
            self._rand_min_colors = min_c
            self._rand_max_colors = max_c
            self._rand_min_patterns = min_p
            self._rand_max_patterns = max_p
            self._rand_avoid_dup_color = dup_color_cb.isChecked()
            self._rand_avoid_dup = dup_cb.isChecked()
            self.random_generate_banner()
            dlg.accept()

        gen_btn = QPushButton("生成随机旗帜")
        gen_btn.setObjectName("rand_gen_btn")
        gen_btn.clicked.connect(do_generate)
        layout.addWidget(gen_btn, 7, 0, 1, 2)
        tabs.addTab(normal_tab, "普通生成")

        corr_tab = QWidget()
        corr_scroll = QScrollArea()
        corr_scroll.setWidgetResizable(True)
        corr_scroll.setFrameShape(QFrame.NoFrame)
        corr_inner = QWidget()
        corr_layout = QGridLayout(corr_inner)
        cr = 0
        corr_layout.addWidget(QLabel("纠偏类型"), cr, 0)
        corr_type_combo = QComboBox()
        corr_type_combo.addItems(["颜色纠偏", "图案纠偏"])
        corr_layout.addWidget(corr_type_combo, cr, 1)

        cr += 1
        corr_source_label = QLabel("来源：列表中选中的旗帜（最多50个）")
        corr_source_label.setWordWrap(True)
        _is_dark = getattr(self, "_current_theme", "light") == "dark"
        _src_color = "#aaaaaa" if _is_dark else "#666"
        corr_source_label.setStyleSheet(f"color: {_src_color}; font-size: {max(int(12 * self._scale), 10)}px;")
        corr_layout.addWidget(corr_source_label, cr, 0, 1, 2)

        cr += 1
        corr_color_group = QGroupBox("颜色纠偏选项")
        color_gl = QGridLayout(corr_color_group)
        corr_vary_bg_cb = QCheckBox("变化旗帜色")
        corr_vary_bg_cb.setChecked(True)
        color_gl.addWidget(corr_vary_bg_cb, 0, 0)
        corr_vary_pc_cb = QCheckBox("变化图案颜色")
        corr_vary_pc_cb.setChecked(False)
        color_gl.addWidget(corr_vary_pc_cb, 0, 1)
        corr_layout.addWidget(corr_color_group, cr, 0, 1, 2)

        cr += 1
        corr_pattern_group = QGroupBox("图案纠偏选项")
        pattern_gl = QGridLayout(corr_pattern_group)
        pattern_gl.addWidget(QLabel("图案类型范围"), 0, 0)
        corr_pmin_spin = QSpinBox()
        corr_pmin_spin.setRange(1, 42)
        corr_pmin_spin.setValue(1)
        pattern_gl.addWidget(corr_pmin_spin, 0, 1)
        pattern_gl.addWidget(QLabel("~"), 0, 2)
        corr_pmax_spin = QSpinBox()
        corr_pmax_spin.setRange(1, 42)
        corr_pmax_spin.setValue(42)
        pattern_gl.addWidget(corr_pmax_spin, 0, 3)
        corr_layout.addWidget(corr_pattern_group, cr, 0, 1, 2)

        cr += 1
        corr_layout.addWidget(QLabel("每组重复"), cr, 0)
        corr_repeat_spin = QSpinBox()
        corr_repeat_spin.setRange(1, 100)
        corr_repeat_spin.setValue(1)
        corr_layout.addWidget(corr_repeat_spin, cr, 1)

        cr += 1
        corr_no_dup_color_cb = QCheckBox("避免重复旗帜底色")
        corr_no_dup_color_cb.setChecked(False)
        corr_layout.addWidget(corr_no_dup_color_cb, cr, 0, 1, 2)

        cr += 1
        corr_no_dup_banner_cb = QCheckBox("避免重复旗帜")
        corr_no_dup_banner_cb.setChecked(True)
        corr_layout.addWidget(corr_no_dup_banner_cb, cr, 0, 1, 2)

        cr += 1
        corr_gen_btn = QPushButton("▶ 生成纠偏旗帜")
        corr_gen_btn.setObjectName("rand_gen_btn")
        corr_layout.addWidget(corr_gen_btn, cr, 0, 1, 2)

        corr_scroll.setWidget(corr_inner)
        corr_tab_layout = QVBoxLayout(corr_tab)
        corr_tab_layout.setContentsMargins(0, 0, 0, 0)
        corr_tab_layout.addWidget(corr_scroll)
        tabs.addTab(corr_tab, "纠偏生成")

        def _narrow_update_corr_ui(idx):
            corr_color_group.setVisible(idx == 0)
            corr_pattern_group.setVisible(idx == 1)
        corr_type_combo.currentIndexChanged.connect(_narrow_update_corr_ui)
        _narrow_update_corr_ui(0)

        def do_corr_generate():
            source_banners = self._get_selected_source_banners()
            if source_banners is None:
                MessageBox.warning(self, "生成失败", "请先在旗帜列表中选中旗帜")
                return
            ct = corr_type_combo.currentIndex()
            vb = corr_vary_bg_cb.isChecked()
            vpc = corr_vary_pc_cb.isChecked()
            pmin = corr_pmin_spin.value()
            pmax = corr_pmax_spin.value()
            rep = corr_repeat_spin.value()
            nd = corr_no_dup_banner_cb.isChecked()
            adc = corr_no_dup_color_cb.isChecked()
            if ct == 0 and not vb and not vpc:
                MessageBox.warning(self, "参数错误", "颜色纠偏至少需要选择一个变化维度")
                return
            generated = self._do_correction_generate(
                source_banners, ct, vb, vpc, pmin, pmax, rep, nd, adc
            )
            self.update_saved_list_display()
            self._update_data_signal()
            mode_name = "颜色纠偏" if ct == 0 else "图案纠偏"
            print(f"[导入器] 纠偏生成完成: {generated} 个{mode_name}旗帜 (基于 {len(source_banners)} 个选中旗帜)")
            if generated > 0:
                MessageBox.information(self, "生成成功", f"已基于 {len(source_banners)} 个选中旗帜生成 {generated} 个{mode_name}旗帜")
            else:
                MessageBox.warning(self, "生成失败", "未能生成任何旗帜，请检查参数设置")
            dlg.accept()

        corr_gen_btn.clicked.connect(do_corr_generate)

        dlg_layout.addWidget(tabs)
        dlg.exec_()

    def _generate_from_expanded(self):
        batch = self._exp_batch_spin.value()
        min_c = self._exp_min_colors_spin.value()
        max_c = self._exp_max_colors_spin.value()
        min_p = self._exp_min_patterns_spin.value()
        max_p = self._exp_max_patterns_spin.value()
        errors = self._validate_random_params(batch, min_c, max_c, min_p, max_p)
        if errors:
            MessageBox.critical(self, "参数错误", "\n".join(errors))
            return
        self._rand_batch_size = batch
        self._rand_min_colors = min_c
        self._rand_max_colors = max_c
        self._rand_min_patterns = min_p
        self._rand_max_patterns = max_p
        self._rand_avoid_dup_color = self._exp_dup_color_cb.isChecked()
        self._rand_avoid_dup = self._exp_dup_cb.isChecked()
        self.random_generate_banner()

    def _do_correction_generate(self, source_banners, corr_type, vary_bg, vary_pattern_color, pattern_min, pattern_max, repeat, no_dup, avoid_dup_color=False):
        generated = 0
        existing_set = set()
        if no_dup:
            for b in self.banners:
                existing_set.add(tuple(b))
        if corr_type == 0:
            for banner in source_banners:
                pattern_layers = []
                for i in range(1, len(banner), 2):
                    if i + 1 < len(banner):
                        pattern_layers.append((banner[i], banner[i + 1]))
                bg_range = range(16) if vary_bg else [banner[0]]
                for bg in bg_range:
                    for _ in range(repeat):
                        new_banner = [bg]
                        used_colors = {bg}
                        for p_type, p_color in pattern_layers:
                            if avoid_dup_color:
                                available = [c for c in range(16) if c not in used_colors]
                                new_color = random.choice(available) if available else random.randint(0, 15)
                            else:
                                new_color = random.randint(0, 15) if vary_pattern_color else p_color
                            new_banner.extend([p_type, new_color])
                            used_colors.add(new_color)
                        if no_dup:
                            key = tuple(new_banner)
                            if key in existing_set:
                                continue
                            existing_set.add(key)
                        self.banners.append(new_banner)
                        generated += 1
        else:
            for banner in source_banners:
                pattern_layers = []
                for i in range(1, len(banner), 2):
                    if i + 1 < len(banner):
                        pattern_layers.append((banner[i], banner[i + 1]))
                for _ in range(repeat):
                    new_banner = [banner[0]]
                    used_colors = {banner[0]}
                    for _, p_color in pattern_layers:
                        new_type = random.randint(pattern_min, pattern_max)
                        if avoid_dup_color:
                            available = [c for c in range(16) if c not in used_colors]
                            final_color = random.choice(available) if available else p_color
                        else:
                            final_color = p_color
                        new_banner.extend([new_type, final_color])
                        used_colors.add(final_color)
                    if no_dup:
                        key = tuple(new_banner)
                        if key in existing_set:
                            continue
                        existing_set.add(key)
                    self.banners.append(new_banner)
                    generated += 1
        return generated

    def _get_selected_source_banners(self, max_count=50):
        active = self._get_active_list()
        if active is None:
            return None
        selection = active.selectedItems()
        if not selection:
            return None
        rows = sorted([active.row(item) for item in selection])
        if len(rows) > max_count:
            rows = rows[:max_count]
        source_banners = []
        for r in rows:
            if r < len(self.banners):
                source_banners.append(self.banners[r])
        return source_banners if source_banners else None

    def _generate_correction_from_expanded(self):
        source_banners = self._get_selected_source_banners()
        if source_banners is None:
            MessageBox.warning(self, "生成失败", "请先在旗帜列表中选中旗帜")
            return
        corr_type = self._exp_corr_type_combo.currentIndex()
        vary_bg = self._exp_corr_vary_bg_cb.isChecked()
        vary_pattern_color = self._exp_corr_vary_pc_cb.isChecked()
        pattern_min = self._exp_corr_pmin_spin.value()
        pattern_max = self._exp_corr_pmax_spin.value()
        repeat = self._exp_corr_repeat_spin.value()
        no_dup = self._exp_corr_no_dup_banner_cb.isChecked()
        avoid_dup_color = self._exp_corr_no_dup_color_cb.isChecked()
        if corr_type == 0 and not vary_bg and not vary_pattern_color:
            MessageBox.warning(self, "参数错误", "颜色纠偏至少需要选择一个变化维度")
            return
        generated = self._do_correction_generate(
            source_banners, corr_type, vary_bg, vary_pattern_color,
            pattern_min, pattern_max, repeat, no_dup, avoid_dup_color
        )
        self.update_saved_list_display()
        self._update_data_signal()
        mode_name = "颜色纠偏" if corr_type == 0 else "图案纠偏"
        print(f"[导入器] 纠偏生成完成: {generated} 个{mode_name}旗帜 (基于 {len(source_banners)} 个选中旗帜)")
        if generated > 0:
            MessageBox.information(self, "生成成功", f"已基于 {len(source_banners)} 个选中旗帜生成 {generated} 个{mode_name}旗帜")
        else:
            MessageBox.warning(self, "生成失败", "未能生成任何旗帜，请检查参数设置")

    def _validate_random_params(self, batch_size, min_c, max_c, min_p, max_p):
        errors = []
        if batch_size < 1:
            errors.append("生成数量必须 >= 1")
        if not (1 <= min_c <= 16):
            errors.append(f"最少配色数必须在 1~16 之间，当前: {min_c}")
        if not (1 <= max_c <= 16):
            errors.append(f"最多配色数必须在 1~16 之间，当前: {max_c}")
        if min_c > max_c:
            errors.append(f"最少配色数({min_c})不能大于最多配色数({max_c})")
        if not (0 <= min_p <= 16):
            errors.append(f"最少图案数必须在 0~16 之间，当前: {min_p}")
        if not (0 <= max_p <= 16):
            errors.append(f"最多图案数必须在 0~16 之间，当前: {max_p}")
        if min_p > max_p:
            errors.append(f"最少图案数({min_p})不能大于最多图案数({max_p})")
        if min_c > min_p + 1:
            errors.append(f"最少配色数({min_c})与最少图案数({min_p})不匹配（配色数≤图案数+1）")
        return errors

    def random_generate_banner(self):
        batch_size = self._rand_batch_size
        min_colors = self._rand_min_colors
        min_patterns = self._rand_min_patterns
        max_patterns = self._rand_max_patterns
        avoid_duplicate_color = self._rand_avoid_dup_color
        avoid_duplicate_banners = self._rand_avoid_dup

        generated_count = 0
        max_attempts = batch_size * 50
        attempts = 0
        dedup_mode = avoid_duplicate_banners

        existing_set = set()
        if avoid_duplicate_banners:
            for b in self.banners:
                existing_set.add(tuple(b))

        while generated_count < batch_size:
            attempts += 1
            if dedup_mode and attempts > max_attempts:
                dedup_mode = False
            if attempts % 50 == 0:
                QApplication.processEvents()
            bg_color = random.randint(0, 15)
            pattern_count = random.randint(min_patterns, max_patterns)
            banner_data = [bg_color]
            used_colors = {bg_color}

            for _ in range(pattern_count):
                pattern_type = random.randint(1, 42)
                if avoid_duplicate_color:
                    available_colors = [c for c in range(16) if c not in used_colors]
                    if available_colors:
                        pattern_color = random.choice(available_colors)
                    else:
                        pattern_color = random.choice(list(used_colors))
                else:
                    pattern_color = random.randint(0, 15)
                banner_data.extend([pattern_type, pattern_color])
                used_colors.add(pattern_color)

            auto_max_colors = min(pattern_count + 1, 16)
            if len(used_colors) < min_colors or len(used_colors) > auto_max_colors:
                continue

            if dedup_mode:
                key = tuple(banner_data)
                if key in existing_set:
                    continue
                existing_set.add(key)

            self.banners.append(banner_data)
            generated_count += 1

        self.update_saved_list_display()
        self._update_data_signal()
        self._update_undo_btn_state()

        print(f"[导入器] 随机生成完成: {generated_count}/{batch_size} 个旗帜 (尝试 {attempts} 次)")
        if generated_count > 0:
            if dedup_mode:
                MessageBox.information(self, "生成成功", f"已生成 {generated_count} 个旗帜（无重复）")
            elif avoid_duplicate_banners:
                MessageBox.information(self, "生成成功", f"已生成 {generated_count} 个旗帜（部分重复）")
            else:
                MessageBox.information(self, "生成成功", f"已生成 {generated_count} 个旗帜")

    def _check_open_file_signal(self):
        import tempfile as _tf
        signal_file = os.path.join(_tf.gettempdir(), "banner_importer_open_file.txt")
        if not os.path.exists(signal_file):
            return
        try:
            with open(signal_file, "r", encoding="utf-8") as f:
                filepath = f.read().strip()
            os.remove(signal_file)
        except Exception:
            return
        if not filepath or not os.path.isfile(filepath):
            return
        self._load_mbtl_file(filepath)

    def _load_mbtl_file(self, filepath):
        try:
            from utils.mbtl_utils import load_banners_from_file
            new_banners = load_banners_from_file(filepath)
        except Exception as e:
            import traceback as _tb
            report_error("打开失败",
                         f"文件格式无效:\n{str(e)}\n\n--- Traceback ---\n{_tb.format_exc()}", "导入器")
            return
        if not new_banners:
            MessageBox.warning(self, "打开失败", "文件中没有旗帜数据")
            return
        if self.banners:
            dlg = QDialog(self)
            dlg.setWindowTitle("导入方式")
            dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
            # 4:3 固定比例窗口
            dlg.setFixedSize(360, 270)
            layout = QVBoxLayout(dlg)
            layout.addWidget(QLabel(f"文件包含 {len(new_banners)} 个旗帜\n当前已有 {len(self.banners)} 个旗帜\n请选择导入方式:"))
            btn_layout = QHBoxLayout()
            merge_btn = QPushButton("合并")
            merge_btn.setDefault(True)
            replace_btn = QPushButton("替换")
            btn_layout.addWidget(merge_btn)
            btn_layout.addWidget(replace_btn)
            layout.addLayout(btn_layout)
            choice = [None]
            merge_btn.clicked.connect(lambda: (choice.__setitem__(0, "merge"), dlg.accept()))
            replace_btn.clicked.connect(lambda: (choice.__setitem__(0, "replace"), dlg.accept()))
            dlg.exec_()
            if choice[0] is None:
                return
            if choice[0] == "replace":
                self.banners.clear()
                self.saved_list.clear()
                self.exp_saved_list.clear()
                self.selected_list.clear()
                self.preview_widget.clear()
                self.current_banner = [0]
                self._edit_locked = False
                self._editing_index = -1
                self._selected_banner_index = -1
                self._enable_edit_area()
                self._update_edit_btn_visibility()
        for banner_data in new_banners:
            if banner_data:
                self.banners.append(banner_data)
        self.update_saved_list_display()
        self._update_data_signal()
        self._update_undo_btn_state()

        # 根据“导入时自动预览”设置决定是否自动选中并显示第一个旗帜
        try:
            auto_preview = SettingsManager().get("auto_preview_import", True)
        except Exception:
            auto_preview = True
        if new_banners and auto_preview:
            self.saved_list.setCurrentRow(0)
            self._on_saved_list_selection_changed()

        print(f"[导入器] 从文件导入 {len(new_banners)} 个旗帜: {os.path.basename(filepath)}")
        MessageBox.information(self, "导入完成", f"已从 {os.path.basename(filepath)} 导入 {len(new_banners)} 个旗帜")

    def import_banners(self):
        sm = SettingsManager()
        _auto_path = resolve_app_path(sm.get("auto_save_loader_path", "saves/auto_save/loader"))
        training_dir = os.path.dirname(os.path.dirname(_auto_path))
        filepaths, _ = QFileDialog.getOpenFileNames(self, "选择旗帜文件", training_dir, "旗帜序列文件 (*.mbtl);;所有文件 (*)")
        if not filepaths:
            return
        for filepath in filepaths:
            self._load_mbtl_file(filepath)

    def export_file(self):
        if not self.banners:
            MessageBox.warning(self, "警告", "请先保存旗帜")
            return
        sm = SettingsManager()
        _auto_path = resolve_app_path(sm.get("auto_save_loader_path", "saves/auto_save/loader"))
        training_dir = os.path.dirname(os.path.dirname(_auto_path))
        save_path, _ = QFileDialog.getSaveFileName(self, "导出文件", training_dir, "旗帜序列文件 (*.mbtl);;所有文件 (*)")
        if not save_path:
            return
        if not save_path.lower().endswith('.mbtl'):
            save_path += '.mbtl'
        write_mbtl(save_path, self.banners)
        print(f"[导入器] 导出完成: {len(self.banners)} 个旗帜 -> {save_path}")
        MessageBox.information(self, "导出成功", f"文件已导出至 {save_path}")

    def export_to_trainer(self):
        if not self.banners:
            MessageBox.warning(self, "警告", "请先保存旗帜")
            return
        formatted_data = self._format_banners_for_export()
        content = "|".join(formatted_data)
        signal_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".importer_export")
        try:
            with open(signal_file, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            import traceback as _tb
            report_error("导出失败",
                         f"写入信号文件失败: {str(e)}\n\n--- Traceback ---\n{_tb.format_exc()}", "导入器")
            return
        self._show_timed_tip(f"已发送 {len(self.banners)} 个旗帜到训练器")
        print(f"[导入器] 已发送 {len(self.banners)} 个旗帜到训练器")

    def _show_timed_tip(self, text):
        tip_w = max(int(self.width() * 0.3), 200)
        tip_h = max(int(self.height() * 0.12), 50)
        fs = max(int(min(tip_w, tip_h) * 0.12), 14)
        tip = QLabel(text, self)
        tip.setAlignment(Qt.AlignCenter)
        tip.setFixedSize(tip_w, tip_h)
        tip.setStyleSheet(
            f"background-color: rgba(76, 175, 80, 220); color: white; "
            f"font-size: {fs}px; padding: 10px 18px; border-radius: 10px;"
        )
        x = (self.width() - tip_w) // 2
        y = (self.height() - tip_h) // 2
        tip.move(x, y)
        tip.show()
        tip.raise_()
        QTimer.singleShot(2000, tip.close)

    def _format_banners_for_export(self):
        formatted_data = []
        for banner_data in self.banners:
            bg_color = banner_data[0]
            patterns = []
            for i in range(1, len(banner_data), 2):
                if i+1 < len(banner_data):
                    patterns.append(f"{banner_data[i+1]}-{banner_data[i]}")
            formatted_data.append(f"{bg_color};{'/'.join(patterns)}")
        return formatted_data

    def _update_data_signal(self):
        if self._session_dir:
            signal_file = os.path.join(self._session_dir, ".importer_has_data")
            try:
                if not os.path.exists(self._session_dir):
                    os.makedirs(self._session_dir, exist_ok=True)
                with open(signal_file, "w") as f:
                    f.write(str(len(self.banners)))
            except Exception:
                pass

    def _write_closing_signal(self):
        if self._session_dir:
            signal_file = os.path.join(self._session_dir, ".importer_closing")
            try:
                with open(signal_file, "w") as f:
                    f.write("closing")
            except Exception:
                pass

    def _remove_closing_signal(self):
        if self._session_dir:
            signal_file = os.path.join(self._session_dir, ".importer_closing")
            try:
                if os.path.exists(signal_file):
                    os.remove(signal_file)
            except Exception:
                pass

    def _check_other_closing(self):
        if self._session_dir:
            signal_file = os.path.join(self._session_dir, ".trainer_closing")
            return os.path.exists(signal_file)
        return False

    def _write_quit_signal(self):
        if self._session_dir:
            signal_file = os.path.join(self._session_dir, ".importer_quit")
            try:
                with open(signal_file, "w") as f:
                    f.write("quit")
            except Exception:
                pass

    def _cleanup_session(self):
        if self._session_dir and os.path.exists(self._session_dir):
            try:
                import shutil
                shutil.rmtree(self._session_dir, ignore_errors=True)
            except Exception:
                pass

    def _cleanup_group_lock(self):
        import glob
        lock_dir = os.environ.get("TEMP", os.environ.get("TMP", ""))
        if lock_dir:
            pattern = os.path.join(lock_dir, f"banner_group_lock_{os.getpid()}.lock")
            for lf in glob.glob(pattern):
                try:
                    os.remove(lf)
                except Exception:
                    pass

    def _start_parent_monitor(self):
        """启动父进程存活监控：父进程死亡时自动保存+报错+退出。"""
        self._parent_pid = 0
        for i, a in enumerate(sys.argv):
            if a == "--parent-pid" and i + 1 < len(sys.argv):
                try:
                    self._parent_pid = int(sys.argv[i + 1])
                except Exception:
                    pass
                break
        if self._parent_pid <= 0:
            return
        if not _is_pid_alive(self._parent_pid):
            return
        self._parent_died = False
        self._parent_monitor_timer = QTimer(self)
        self._parent_monitor_timer.timeout.connect(self._check_parent_alive)
        self._parent_monitor_timer.start(500)

    def _check_parent_alive(self):
        """定时检查父进程是否存活。"""
        if getattr(self, "_parent_died", False):
            return
        if self._parent_pid and not _is_pid_alive(self._parent_pid):
            self._parent_died = True
            self._parent_monitor_timer.stop()
            self._on_parent_died()

    def _on_parent_died(self):
        """父进程死亡：尝试保存工作区数据，通过报错程序通知用户，然后退出。"""
        # 尝试保存当前工作区数据（避免损失）
        try:
            if self.current_layout:
                if self._main_tabs.currentIndex() == 1:
                    self._save_graphic_to_workspace()
                elif self._main_tabs.currentIndex() == 0:
                    self._save_tab1_to_workspace()
            self._save_window_geometry()
            self._flush_workspace_to_disk()
        except Exception:
            pass
        # 清理锁文件
        try:
            self._cleanup_group_lock()
        except Exception:
            pass
        # 通过报错程序通知用户
        try:
            from utils.settings_manager import report_error
            report_error(
                "训练器已关闭",
                "训练器已关闭，导入器将自动退出。\n\n"
                "系统已尝试保存当前工作区数据，如需恢复请在下次启动时使用自动保存恢复功能。",
                "导入器"
            )
        except Exception:
            pass
        # 强制退出（跳过退出确认窗口）
        self._force_quit = True
        from PyQt5.QtCore import QCoreApplication
        QCoreApplication.quit()

    def closeEvent(self, event):
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

        # 关闭前保存当前 Tab 的工作区位置到磁盘
        if self.current_layout:
            if self._main_tabs.currentIndex() == 1:
                self._save_graphic_to_workspace()
            elif self._main_tabs.currentIndex() == 0:
                self._save_tab1_to_workspace()
        # snap 状态下不保存窗口位置（未脱离 snap）；脱离 snap 才保存
        try:
            _hwnd = int(self.winId())
        except Exception:
            _hwnd = 0
        if _hwnd and _is_window_snapped(_hwnd):
            # snap 状态：清除内存中的 window 数据，避免 _flush 写回旧记录
            _importer_data = self._workspace_data.get("importer", {})
            if isinstance(_importer_data, dict):
                _importer_data.pop("window", None)
        else:
            self._save_window_geometry()
        self._flush_workspace_to_disk()

        if self._force_quit:
            self._cleanup_group_lock()
            # 主动退出时跳过 session 清理（退出信号文件需要留给接收方检测）
            if not getattr(self, '_initiated_quit', False):
                self._cleanup_session()
            event.accept()
            return

        if self._close_blocked or self._check_other_closing():
            event.ignore()
            return

        if self._exit_process is not None:
            # 已有 exit.pyw 在运行，忽略本次关闭
            event.ignore()
            return

        self._write_closing_signal()

        # 直接关闭退出：不再弹 exit.pyw 确认窗口（杜绝"窗口关了进程残留"）
        # 关闭信号已通过 _write_quit_signal 发送，对方程序据此感知本程序已关闭
        self._remove_closing_signal()
        self._write_quit_signal()
        self._cleanup_group_lock()
        event.accept()
        return

    def _launch_exit_confirmation(self, source, msg, has_training, has_data):
        """启动 exit.pyw 子进程显示退出确认窗口，并用定时器轮询结果。"""
        import tempfile
        info_file = os.path.join(tempfile.gettempdir(), f"exit_info_{os.getpid()}.txt")
        try:
            with open(info_file, "w", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass

        exit_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "exit.pyw")
        session_dir = self._session_dir or tempfile.gettempdir()
        can_save = "1" if (has_training or has_data) else "0"
        try:
            self._exit_process = subprocess.Popen(
                [sys.executable, exit_path, "exit", source, session_dir, info_file, can_save],
            )
        except Exception:
            self._exit_process = None
            return

        self._exit_has_training = has_training
        self._exit_has_data = has_data
        from PyQt5.QtCore import QTimer
        self._exit_timer = QTimer(self)
        self._exit_timer.timeout.connect(self._check_exit_result)
        self._exit_timer.start(100)

    def _check_exit_result(self):
        """定时器回调：检查 exit.pyw 的确认/取消信号。"""
        import tempfile
        session_dir = self._session_dir or tempfile.gettempdir()
        confirmed_file = os.path.join(session_dir, ".exit_confirmed")
        cancelled_file = os.path.join(session_dir, ".exit_cancelled")

        if os.path.exists(confirmed_file):
            # 读取保存偏好
            save_requested = False
            try:
                with open(confirmed_file, "r") as f:
                    content = f.read().strip()
                    save_requested = "save=1" in content
            except Exception:
                pass
            try:
                os.remove(confirmed_file)
            except Exception:
                pass
            self._exit_timer.stop()
            self._exit_timer = None
            self._exit_process = None
            self._exit_save_requested = save_requested
            self._do_exit()
        elif os.path.exists(cancelled_file):
            try:
                os.remove(cancelled_file)
            except Exception:
                pass
            self._exit_timer.stop()
            self._exit_timer = None
            self._exit_process = None
            self._remove_closing_signal()

    def _do_exit(self):
        """用户确认退出后执行真正的退出流程。"""
        save_requested = getattr(self, "_exit_save_requested", False)
        has_data = getattr(self, "_exit_has_data", False)
        if save_requested and has_data:
            # 用户勾选"退出前保存"：根据 importer_save_formats 多格式保存旗帜数据到手动保存文件夹
            from datetime import datetime
            from utils.mbtl_utils import write_mbtl
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            try:
                save_fmts = SettingsManager().get("importer_save_formats", ["mbtl", "mbtlx"])
            except Exception:
                save_fmts = ["mbtl", "mbtlx"]
            if not isinstance(save_fmts, list):
                save_fmts = [save_fmts]
            if "all" in save_fmts:
                save_fmts = ["mbtl", "mbtlx"]
            sm = SettingsManager()
            manual_base = resolve_app_path(sm.get("manual_save_loader_path", "saves/manual_save/loader"))
            manual_dir = os.path.join(manual_base, ts)
            os.makedirs(manual_dir, exist_ok=True)
            try:
                # .mbtl：纯旗帜数据
                if "mbtl" in save_fmts:
                    write_mbtl(os.path.join(manual_dir, "banner.mbtl"), self.banners)
                # .mbtlx：含图片的标记文件（有序列图组数据时才保存）
                if "mbtlx" in save_fmts and getattr(self, "_graphic_marks", None):
                    export_mbtlx(os.path.join(manual_dir, "banner.mbtlx"), self._graphic_marks)
            except Exception:
                pass
        self._remove_closing_signal()
        self._write_quit_signal()
        self._cleanup_group_lock()
        self._force_quit = True
        self._initiated_quit = True  # 主动退出，不清理 session_dir（接收方需要读取信号）
        self.close()


def _show_launch_dialog(parent):
    screen = QApplication.primaryScreen()
    geo = screen.availableGeometry() if screen else None
    sw = geo.width() if geo else 1920
    sh = geo.height() if geo else 1080
    ui_scale = max(min(sw / 1920, sh / 1080), 0.85)
    dpi_scale = (screen.logicalDotsPerInch() / 96.0) if screen else 1.0
    s = min(ui_scale, 1.4) * 1.1

    dlg_w = max(int(sw * 0.32), 420)
    # 4:3 固定比例窗口
    dlg_h = int(dlg_w * 3 / 4)

    base_font = max(int(18 * s), 15)
    title_font = max(int(36 * s), 28)
    os_font = max(int(20 * s), 16)
    subtitle_font = max(int(19 * s), 15)
    desc_font = max(int(14 * s), 12)
    indicator_size = max(int(17 * s), 14)
    btn_padding = max(int(9 * s), 7)
    btn_font = max(int(16 * s), 13)
    debug_font = max(int(13 * s), 11)

    # 读取主题并解析
    _theme = resolve_theme(SettingsManager().get("theme", "light"))
    is_dark = _theme == "dark"

    if _SYS_COMPAT["is_win11_plus"]:
        dialog_bg = "#fafbff"
        btn_bg = "#6366f1"
        btn_hover = "#4f46e5"
    elif _SYS_COMPAT["is_win10_plus"]:
        dialog_bg = "#f5f9ff"
        btn_bg = "#0078D4"
        btn_hover = "#005A9E"
    else:
        dialog_bg = "#f0f0f0"
        btn_bg = "#4a90d9"
        btn_hover = "#3a7bc8"

    # 深色模式覆盖
    if is_dark:
        dialog_bg = "#2d2d30"
        btn_bg = "#4FC3F7"
        btn_hover = "#29B6F6"

    # 文字颜色根据主题
    text_color = "#eeeeee" if is_dark else "#333"
    sub_text_color = "#aaaaaa" if is_dark else "#888"
    desc_text_color = "#cccccc" if is_dark else "#444"
    desc_bg = "#3c3c3c" if is_dark else "#eee"
    cancel_btn_bg = "#555555" if is_dark else "#999"
    cancel_btn_hover = "#666666" if is_dark else "#888"

    dlg = QDialog(parent, Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint)
    dlg.setWindowTitle("旗帜训练工具 v0.5 beta1 (1.0.8)")
    dlg.setFixedSize(dlg_w, dlg_h)
    dlg.setStyleSheet(f"""
        QDialog {{ background-color: {dialog_bg}; }}
        QLabel {{ color: {text_color}; font-size: {base_font}px; }}
        QRadioButton {{ color: {text_color}; spacing: 10px; font-size: {base_font}px; }}
        QRadioButton::indicator {{ width: {indicator_size}px; height: {indicator_size}px; }}
        QPushButton {{ background-color: {btn_bg}; color: white; border: none; border-radius: 6px; padding: {btn_padding}px {btn_padding*3}px; font-size: {btn_font}px; min-height: {max(int(32*s),28)}px; }}
        QPushButton:hover {{ background-color: {btn_hover}; }}
        QPushButton#cancel_btn {{ background-color: {cancel_btn_bg}; }}
        QPushButton#cancel_btn:hover {{ background-color: {cancel_btn_hover}; }}
    """)

    layout = QVBoxLayout(dlg)
    layout.setSpacing(max(int(8 * s), 6))

    title = QLabel("旗帜训练工具")
    title.setAlignment(Qt.AlignCenter)
    title.setStyleSheet(f"font-size: {title_font}px; font-weight: bold; color: {text_color}; margin-top: {int(6 * s)}px;")
    layout.addWidget(title)

    if _SYS_COMPAT["is_win11_plus"]:
        os_info = f"当前系统：Windows 11"
        os_color = "#6366f1"
    elif _SYS_COMPAT["is_win10_plus"]:
        os_info = f"当前系统：Windows 10"
        os_color = "#0078D4"
    else:
        os_info = f"当前系统：{_SYS_COMPAT['os']}"
        os_color = "#aaaaaa" if is_dark else "#666"
    ver = _SYS_COMPAT.get("os_version", (0, 0, 0))
    if ver[2] > 0:
        os_info += f" (Build {ver[2]})"
    os_label = QLabel(os_info)
    os_label.setAlignment(Qt.AlignCenter)
    os_label.setStyleSheet(f"font-size: {os_font}px; color: {os_color}; font-weight: bold; margin-bottom: {int(1 * s)}px;")
    layout.addWidget(os_label)

    import importlib.util
    if importlib.util.find_spec('torch') is not None:
        mode_info = "启动模式：PyTorch已安装（训练时自动选择GPU/CPU）"
        mode_color = "#16a34a"
    else:
        mode_info = "启动模式：PyTorch未安装（训练功能不可用）"
        mode_color = "#dc2626"
    mode_label = QLabel(mode_info)
    mode_label.setAlignment(Qt.AlignCenter)
    mode_label.setStyleSheet(f"font-size: {desc_font}px; color: {mode_color}; margin-bottom: {int(2 * s)}px;")
    layout.addWidget(mode_label)

    sm = SettingsManager()
    train_mode = sm.get("train_mode") or "normal"
    debug_mode = bool(sm.get("debug_mode", False))
    mode_text = "普通模式（全量训练）" if train_mode == "normal" else "PEFT模式（参数高效微调）"

    subtitle = QLabel(f"当前训练模式：{mode_text}")
    subtitle.setAlignment(Qt.AlignCenter)
    subtitle.setStyleSheet(f"font-size: {subtitle_font}px; color: {sub_text_color}; margin-bottom: {int(3 * s)}px;")
    layout.addWidget(subtitle)

    desc_text = "普通模式：对所有模型参数进行训练，适合数据量充足时使用\nPEFT模式：仅微调少量参数，适合数据量较少或快速适配时使用"
    if debug_mode:
        desc_text += "\n调试模式：已启用（将显示命令提示符窗口）"
    desc_label = QLabel(desc_text)
    desc_label.setAlignment(Qt.AlignLeft)
    desc_label.setWordWrap(True)
    desc_label.setStyleSheet(f"font-size: {desc_font}px; color: {desc_text_color}; padding: {int(6*s)}px {int(8*s)}px; background-color: {desc_bg}; border-radius: 6px;")
    layout.addWidget(desc_label)

    layout.addSpacing(max(int(6 * s), 4))

    btn_row = QHBoxLayout()
    btn_row.setSpacing(max(int(10 * s), 8))
    btn_row.addStretch()
    ok_btn = QPushButton("▶ 启动训练")
    ok_btn.setMinimumWidth(max(int(180 * s), 140))
    ok_btn.setMinimumHeight(max(int(32 * s), 28))
    ok_btn.clicked.connect(dlg.accept)
    btn_row.addWidget(ok_btn)
    cancel_btn = QPushButton("取消")
    cancel_btn.setObjectName("cancel_btn")
    cancel_btn.setMinimumWidth(max(int(120 * s), 100))
    cancel_btn.setMinimumHeight(max(int(32 * s), 28))
    cancel_btn.clicked.connect(dlg.reject)
    btn_row.addWidget(cancel_btn)
    btn_row.addStretch()
    spacer = QWidget()
    spacer.setFixedWidth(max(int(100 * s), 80))
    btn_row.addWidget(spacer)
    layout.addLayout(btn_row)

    if dlg.exec_() == QDialog.Accepted:
        return (train_mode, debug_mode)
    return None


if __name__ == "__main__":
    # 非 debug 模式下把 stdout/stderr 重定向到 log 目录日志文件
    # .pyw 模式下 stdout/stderr 为 None，print 会报 OSError
    if "--debug" not in sys.argv:
        try:
            from utils.settings_manager import resolve_app_path
            _log_dir = resolve_app_path("log")
            os.makedirs(_log_dir, exist_ok=True)
            _log_fh = open(os.path.join(_log_dir, "importer_stdout.log"),
                           "a", encoding="utf-8", buffering=1)
            sys.stdout = _log_fh
            sys.stderr = _log_fh
            import atexit
            atexit.register(_log_fh.close)
        except Exception:
            try:
                _devnull = open(os.devnull, "w")
                sys.stdout = _devnull
                sys.stderr = _devnull
            except Exception:
                pass

    _startup_theme = SettingsManager().get("theme", "light")

    if "--open-file" in sys.argv:
        idx = sys.argv.index("--open-file")
        if idx + 1 < len(sys.argv):
            filepath = sys.argv[idx + 1]
            if not os.path.isfile(filepath):
                import ctypes as _ct
                _ct.windll.user32.MessageBoxW(0, f"文件不存在:\n{filepath}", "打开失败", 0x10)
                sys.exit(1)
            try:
                from utils.mbtl_utils import load_banners_from_file as _load
                _load(filepath)
            except Exception as e:
                import ctypes as _ct
                _ct.windll.user32.MessageBoxW(0, f"文件格式无效:\n{str(e)}", "打开失败", 0x10)
                sys.exit(1)
            import glob as _glob
            import tempfile as _tf
            lock_dir = _tf.gettempdir()
            alive = False
            for lf in _glob.glob(os.path.join(lock_dir, "banner_group_lock_*.lock")):
                try:
                    with open(lf, "r") as f:
                        content = f.read()
                    pid, create_time = _parse_lock_content(content)
                    if pid <= 0:
                        continue
                    if _is_process_alive_with_create_time(pid, create_time):
                        alive = True
                        break
                    else:
                        try:
                            os.remove(lf)
                        except Exception:
                            pass
                except Exception:
                    pass
            if not alive:
                import ctypes as _ct
                _ct.windll.user32.MessageBoxW(0, "请先启动旗帜训练工具，再双击打开.mbtl文件", "提示", 0x40)
                sys.exit(0)
            signal_file = os.path.join(lock_dir, "banner_importer_open_file.txt")
            try:
                with open(signal_file, "w", encoding="utf-8") as f:
                    f.write(filepath)
            except Exception:
                pass
            sys.exit(0)
        sys.exit(1)

    from PyQt5.QtCore import Qt
    # 软件渲染（必须在 QApplication 创建前设置）：保证 agent 截图稳定可识别
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
    app = QApplication(sys.argv)
    app.setApplicationName("旗帜训练工具 v0.5 beta1 (1.0.8)")
    app.setDesktopFileName("旗帜训练工具 v0.5 beta1 (1.0.8)")
    app.setFont(QFont("Microsoft YaHei UI", app.font().pointSize()))

    # 统一弹窗图标：QMessageBox 系统弹窗图标 64px（250% 放大规律，与 error_reporter 等自定义弹窗一致）
    from PyQt5.QtWidgets import QProxyStyle, QStyle as _QStyle
    class _MsgBoxIconStyle(QProxyStyle):
        def pixelMetric(self, metric, option=None, widget=None):
            if metric == _QStyle.PM_MessageBoxIconSize:
                return 64
            return super().pixelMetric(metric, option, widget)
    app.setStyle(_MsgBoxIconStyle(app.style()))

    def _global_excepthook(exc_type, exc_value, exc_tb):
        # 防重复：_early_crash_handler 已经报告过（顶层import阶段崩溃），此处跳过避免双弹
        if _crash_reported:
            return
        import traceback
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _show_error_popup("程序异常", f"旗帜训练工具发生未处理的错误:\n\n{tb_str}")
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _global_excepthook

    apply_theme(app, _startup_theme)
    # 解析 "system/auto" 为实际 light/dark，保证深色模式下图形面板按钮等 app 级样式正确置灰
    is_dark = resolve_theme(_startup_theme) == "dark"
    _g_bg = "#2d2d30" if is_dark else "#f0f0f0"
    _g_fg = "#eeeeee" if is_dark else "#000000"
    _g_border = "#555555" if is_dark else "#cccccc"
    _g_input_bg = "#3c3c3c" if is_dark else "#ffffff"
    _g_input_border = "#555555" if is_dark else "#cccccc"
    _g_handle_bg = "#555555" if is_dark else "#dddddd"
    app.setStyleSheet(f"""
        QGroupBox {{
            font-weight: bold;
            border: 1px solid {_g_border};
            border-radius: 6px;
            margin-top: 8px;
            padding-top: 16px;
            color: {_g_fg};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
        }}
        QPushButton {{
            background-color: {_g_input_bg};
            color: {_g_fg};
            border: 1px solid {_g_input_border};
            border-radius: 4px;
            padding: 6px 16px;
            min-height: 22px;
        }}
        QPushButton:hover {{
            background-color: {'#4a4a4a' if is_dark else '#e0e0e0'};
            border-color: {'#666666' if is_dark else '#aaaaaa'};
        }}
        QPushButton:pressed {{
            background-color: {'#333333' if is_dark else '#d0d0d0'};
        }}
        QPushButton:disabled {{
            background-color: {'#555555' if is_dark else '#CCCCCC'};
            color: {'#999999' if is_dark else '#888888'};
            border-color: {'#444444' if is_dark else '#BBBBBB'};
        }}
        QListWidget, QTreeWidget {{
            border: 1px solid {_g_input_border};
            border-radius: 4px;
            color: {_g_fg};
        }}
        QSpinBox, QComboBox {{
            border: 1px solid {_g_input_border};
            border-radius: 4px;
            padding: 4px;
            background: {_g_input_bg};
            color: {_g_fg};
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            background: transparent;
            border: none;
            width: 16px;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
            background: {'#4a4a4a' if is_dark else '#e8e8e8'};
            border-radius: 3px;
        }}
        QSpinBox::up-arrow, QSpinBox::down-arrow {{
            width: 8px;
            height: 8px;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: center right;
            width: 20px;
            border: none;
        }}
        QComboBox QAbstractItemView {{
            border: 1px solid {_g_input_border};
            border-radius: 4px;
            background: {_g_input_bg};
            color: {_g_fg};
            selection-background-color: {'#4FC3F7' if is_dark else '#0078D4'};
            selection-color: white;
            outline: none;
        }}
        QSlider::groove:horizontal {{
            height: 4px;
            background: {_g_handle_bg};
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            width: 14px;
            height: 14px;
            margin: -5px 0;
            background: {'#4FC3F7' if is_dark else '#0078D4'};
            border-radius: 7px;
        }}
        QSlider::handle:horizontal:hover {{
            background: {'#29B6F6' if is_dark else '#106EBE'};
        }}
        QSplitter {{
            background-color: {_g_bg};
        }}
        QSplitter::handle {{
            background-color: {_g_handle_bg};
        }}
        QScrollArea {{
            border: none;
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
            background: {'#555555' if is_dark else '#c0c0c0'};
            border-radius: 5px;
            min-height: 30px;
            min-width: 30px;
        }}
        QScrollBar::handle:hover {{
            background: {'#666666' if is_dark else '#a0a0a0'};
        }}
        QScrollBar::handle:pressed {{
            background: {'#777777' if is_dark else '#909090'};
        }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            border: none;
            background: none;
            width: 0;
            height: 0;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{
            background: transparent;
        }}
    """)

    def _on_startup_hw_detected(hw, from_cache=False):
        if not from_cache:
            gpu_text = f"{hw.get('gpu_name', '未检测到')} {hw['gpu_total_gb']}GB"
            mem_nominal = hw.get('mem_nominal_gb', hw.get('mem_total_gb', 0))
            mem_recognized = hw.get('mem_recognized_gb', mem_nominal)
            cpu_name = hw.get('cpu_name', '未知')
            print(f"系统配置: OS={_SYS_COMPAT['os']}, CPU={cpu_name}({hw['cpu_cores']}核), GPU={gpu_text}, 标称内存={mem_nominal}G, 系统识别={mem_recognized}G, 虚拟内存={hw.get('virtual_total_gb', 0)}G")
            save_hardware_cache(hw)  # 保存到磁盘，下次启动直接读取
        sm = SettingsManager()
        updates = {}
        if sm.get("gpu_memory") == "auto":
            gpu_val = grade_gpu_memory(hw["gpu_total_gb"])
            sm.set("gpu_memory", gpu_val)
            updates["gpu_memory"] = gpu_val
        if sm.get("sys_memory") == "auto":
            mem_val = grade_system_memory(hw["mem_total_gb"])
            sm.set("sys_memory", mem_val)
            updates["sys_memory"] = mem_val
        if sm.get("num_workers") == "auto":
            workers = max(1, hw["cpu_cores"] - 1)
            sm.set("num_workers", workers)
            updates["num_workers"] = workers
        if updates:
            sm.save()
            if not from_cache:
                print(f"自动配置已应用: {updates}")

    def _start_importer_hw_detect():
        hw_thread = HardwareDetectThread(skip_gpu=True)
        hw_thread.result_ready.connect(lambda hw: _on_startup_hw_detected(hw, from_cache=False))
        # 保持引用，避免线程未结束时被GC回收导致 "QThread: Destroyed while thread is still running" 闪退
        app = QApplication.instance()
        if app is not None:
            app._startup_hw_thread = hw_thread
        hw_thread.finished.connect(lambda: setattr(app, "_startup_hw_thread", None) if app is not None else None)
        hw_thread.start()

    # 启动时检测模型架构可用性并写入缓存，设置窗口直接读缓存以提高速度
    try:
        build_arch_cache()
    except Exception:
        pass

    # 优先使用磁盘缓存的硬件信息，避免每次启动都重复检测
    _cached_hw = load_hardware_cache()
    if _cached_hw is not None:
        _on_startup_hw_detected(_cached_hw, from_cache=True)
    else:
        # 延迟 300ms 再开始检测，让主窗口先完成首次渲染
        QTimer.singleShot(300, _start_importer_hw_detect)

    session_dir = None
    if "--session-dir" in sys.argv:
        idx = sys.argv.index("--session-dir")
        if idx + 1 < len(sys.argv):
            session_dir = sys.argv[idx + 1]

    is_restart = "--restart" in sys.argv
    training_mode = "normal"
    if "--training-mode" in sys.argv:
        idx = sys.argv.index("--training-mode")
        if idx + 1 < len(sys.argv):
            training_mode = sys.argv[idx + 1]
    debug_mode = "--debug" in sys.argv

    if "--right-half" not in sys.argv:
        # 互斥检查：逆向器运行中则阻拦
        if _check_reverser_running():
            MessageBox.critical(None, "启动限制",
                "旗帜印染逆向器正在运行\n请先关闭后再启动旗帜训练工具")
            sys.exit(0)

        import tempfile
        import uuid

        root_widget = QWidget()
        root_widget.hide()

        max_inst = 1

        # 用 Mutex 原子化检查+创建锁文件，防止点击过快导致多实例
        lock_file = None
        if not is_restart and max_inst > 0:
            import glob
            lock_dir = os.environ.get("TEMP", os.environ.get("TMP", ""))
            mutex_name = "Global\\banner_trainer_instance_mutex"
            mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
            if mutex:
                wait_result = ctypes.windll.kernel32.WaitForSingleObject(mutex, 5000)
                try:
                    if wait_result == 0:  # WAIT_OBJECT_0
                        # 持有 Mutex，原子地检查+创建
                        alive_count = 0
                        if lock_dir:
                            for lf in glob.glob(os.path.join(lock_dir, "banner_group_lock_*.lock")):
                                try:
                                    with open(lf, "r") as f:
                                        content = f.read()
                                    pid, create_time = _parse_lock_content(content)
                                    if pid <= 0:
                                        continue
                                    if _SYS_COMPAT["is_windows"]:
                                        if _is_process_alive_with_create_time(pid, create_time):
                                            alive_count += 1
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
                        if alive_count >= max_inst:
                            ctypes.windll.kernel32.ReleaseMutex(mutex)
                            ctypes.windll.kernel32.CloseHandle(mutex)
                            MessageBox.critical(None, "启动限制",
                                f"旗帜训练工具已达到最大启动数量限制（{max_inst}个实例）\n请先关闭已运行的实例后再试")
                            sys.exit(0)
                        # 检查通过，创建锁文件
                        lock_file = os.path.join(tempfile.gettempdir(), f"banner_group_lock_{os.getpid()}.lock")
                        try:
                            ct = _get_process_create_time(os.getpid())
                            with open(lock_file, "w") as f:
                                f.write(f"{os.getpid()}|{ct}")
                        except Exception:
                            lock_file = None
                finally:
                    try:
                        ctypes.windll.kernel32.ReleaseMutex(mutex)
                    except Exception:
                        pass
                    ctypes.windll.kernel32.CloseHandle(mutex)
        else:
            lock_file = os.path.join(tempfile.gettempdir(), f"banner_group_lock_{os.getpid()}.lock")
            try:
                ct = _get_process_create_time(os.getpid())
                with open(lock_file, "w") as f:
                    f.write(f"{os.getpid()}|{ct}")
            except Exception:
                lock_file = None

        _minimize_existing_windows()

        if not is_restart:
            # 直接进入加载条，跳过模式选择界面
            # 从配置读取 training_mode 和 debug_mode（与 trainer.pyw 保持一致）
            sm = SettingsManager()
            training_mode = sm.get("train_mode") or "normal"
            debug_mode = bool(sm.get("debug_mode", False))
        else:
            if training_mode not in ("normal", "peft"):
                training_mode = "normal"

        session_dir = os.path.join(tempfile.gettempdir(), f"banner_trainer_{uuid.uuid4().hex[:8]}")
        os.makedirs(session_dir, exist_ok=True)

        script_dir = os.path.dirname(os.path.abspath(__file__))
        trainer_path = os.path.join(script_dir, "trainer.pyw")

        err_log = os.path.join(session_dir, "trainer_stderr.log")
        exe = sys.executable
        if debug_mode:
            exe_lower = exe.lower()
            if exe_lower.endswith("pythonw.exe"):
                exe = exe[:-5] + ".exe"
            elif exe_lower.endswith("pythonw"):
                exe = exe[:-1]
        cmd = [
            exe, trainer_path,
            "--training-mode", training_mode,
            "--left-half",
            "--session-dir", session_dir
        ]
        # 将项目根目录加入 PYTHONPATH，确保训练子进程能正确导入 models/structures/vit_model 等模块
        env = os.environ.copy()
        env["PYTHONPATH"] = script_dir + os.pathsep + env.get("PYTHONPATH", "")
        if debug_mode:
            cmd.append("--debug")
            # 强制创建新控制台窗口，确保命令提示符可见
            trainer_proc = subprocess.Popen(cmd, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            trainer_proc = subprocess.Popen(cmd, env=env, stderr=open(err_log, "w", encoding="utf-8"))

        # 不改写锁文件内容：importer 保留自己的锁文件（importer_pid），
        # trainer（--left-half）会创建自己的锁文件（trainer_pid），
        # _minimize_existing_windows 通过 banner_group_lock_*.lock 识别同组成员

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        sw = geo.width() if geo else 1920
        sh = geo.height() if geo else 1080
        ui_scale = max(min(sw / 1920, sh / 1080), 0.85)
        dpi_scale = (screen.logicalDotsPerInch() / 96.0) if screen else 1.0
        s = min(ui_scale, 1.4) * 1.1
        lw = max(int(sw * 0.45), 600)
        lh = max(int(sh * 0.4), 400)

        loader = QWidget()
        loader.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        loader.setGeometry((sw - lw) // 2, (sh - lh) // 2, lw, lh)
        loader.setAutoFillBackground(True)

        loader.closeEvent = lambda e: e.ignore()

        # 加载条窗口也应用 DWM 深色标题栏
        _startup_theme = resolve_theme(SettingsManager().get("theme", "light"))
        apply_dwm_dark_mode(loader, _startup_theme == "dark")

        loader_layout = QVBoxLayout(loader)
        loader_layout.setContentsMargins(0, 0, 0, 0)

        circular_progress = CircularProgressWidget(ui_scale=s)
        circular_progress.setModeText("普通模式" if training_mode == "normal" else "PEFT模式")
        loader_layout.addWidget(circular_progress)

        loader.show()

        steps = [
            (0.00, "正在准备启动训练器..."),
            (0.08, "正在初始化训练器窗口界面..."),
            (0.15, "正在初始化PyTorch深度学习框架..."),
            (0.25, "正在构建ViT视觉Transformer网络结构..."),
            (0.35, "正在分析模型参数规模..."),
            (0.40, "正在配置PEFT微调适配器..."),
            (0.50, "正在编译训练器优化器与损失函数..."),
            (0.58, "模型加载完成，等待导入旗帜数据"),
            (0.65, "正在调整训练器窗口布局..."),
            (0.72, "正在启动导入器模块..."),
            (0.80, "导入器UI初始化完成..."),
            (0.92, "导入器准备就绪..."),
            (1.00, "全部启动完成"),
        ]

        min_duration = 0
        start_time = [time.time()]
        ready_detected = [False]
        ready_time = [None]
        loader_done = [False]
        loader_hwnd = int(loader.winId())
        last_progress = [0.0]
        last_status = [""]
        frame_count = [0]  # 用于降低 _keep_loader_foreground 调用频率

        def _read_trainer_progress():
            tp = os.path.join(session_dir, ".trainer_progress")
            tval, tstatus = 0.0, ""
            try:
                if os.path.exists(tp):
                    with open(tp, "r", encoding="utf-8") as f:
                        lines = f.read().strip().split("\n")
                        tval = float(lines[0])
                        if len(lines) > 1:
                            tstatus = lines[1]
            except Exception:
                pass
            return tval, tstatus

        def _keep_loader_foreground():
            if loader_done[0]:
                return
            try:
                fg = ctypes.windll.user32.GetForegroundWindow()
                if fg != loader_hwnd:
                    ctypes.windll.user32.SetForegroundWindow(loader_hwnd)
                    ctypes.windll.user32.ShowWindow(loader_hwnd, 9)
            except Exception:
                pass

        def animate():
            if loader_done[0]:
                return
            elapsed = time.time() - start_time[0]

            if trainer_proc.poll() is not None and trainer_proc.returncode != 0 and not ready_detected[0]:
                loader_done[0] = True
                err_msg = ""
                try:
                    if os.path.exists(err_log):
                        with open(err_log, "r", encoding="utf-8", errors="replace") as f:
                            err_msg = f.read().strip()[:500]
                except Exception:
                    pass
                loader.closeEvent = lambda e: e.accept()
                loader.close()
                if lock_file:
                    try:
                        os.remove(lock_file)
                    except Exception:
                        pass
                msg = f"训练器进程异常退出（返回码: {trainer_proc.returncode}）"
                if err_msg:
                    msg += f"\n\n错误信息:\n{err_msg}"
                _show_error_popup("启动失败", msg)
                sys.exit(1)
                return

            trainer_ready_file = os.path.join(session_dir, ".trainer_ready")
            if os.path.exists(trainer_ready_file):
                ready_detected[0] = True

            real_progress, real_status = _read_trainer_progress()

            if ready_detected[0]:
                if ready_time[0] is None:
                    ready_time[0] = time.time()
                ready_elapsed = time.time() - ready_time[0]
                progress = min(max(real_progress, 0.70) + ready_elapsed / 0.3 * 0.30, 1.0)
                if progress >= 1.0:
                    loader_done[0] = True
                    done_file = os.path.join(session_dir, ".loading_done")
                    try:
                        with open(done_file, "w") as f:
                            f.write("done")
                    except Exception:
                        pass
                    loader.closeEvent = lambda e: e.accept()
                    loader.close()
                    return
            else:
                progress = real_progress

            if progress > last_progress[0]:
                last_progress[0] = progress
                circular_progress.setProgress(progress)

            display_status = real_status if real_status else last_status[0]
            if not display_status:
                current_step = 0
                for i, (threshold, _) in enumerate(steps):
                    if progress >= threshold:
                        current_step = i
                display_status = steps[current_step][1]

            if ready_detected[0] and progress >= 0.70:
                new_status = "正在完成最后的启动检查..."
            elif real_status:
                new_status = real_status
            elif not display_status:
                current_step = 0
                for i, (threshold, _) in enumerate(steps):
                    if progress >= threshold:
                        current_step = i
                new_status = steps[current_step][1]
            else:
                new_status = display_status

            # 状态文本未变化时跳过 setStatusText，避免不必要的重绘
            if new_status != last_status[0]:
                last_status[0] = new_status
                circular_progress.setStatusText(new_status)

            # 前台窗口保持降频：每 5 帧调一次（约 400ms）
            frame_count[0] += 1
            if frame_count[0] % 5 == 0:
                _keep_loader_foreground()

            if elapsed > 60:
                loader_done[0] = True
                done_file = os.path.join(session_dir, ".loading_done")
                try:
                    with open(done_file, "w") as f:
                        f.write("done")
                except Exception:
                    pass
                loader.closeEvent = lambda e: e.accept()
                loader.close()
                return

            QTimer.singleShot(80, animate)

        QTimer.singleShot(80, animate)
        app.exec_()
        if debug_mode:
            trainer_proc.wait()
        # 强制退出：杜绝窗口关闭后进程残留（解释器退出会等待非守护线程）
        os._exit(0)

    # --right-half 模式：由训练器启动，创建自己的锁文件加入窗口组
    # 这样 _minimize_existing_windows 会把训练器和导入器识别为同组成员
    _right_half_lock = os.path.join(tempfile.gettempdir(), f"banner_group_lock_{os.getpid()}.lock")
    try:
        ct = _get_process_create_time(os.getpid())
        with open(_right_half_lock, "w") as f:
            f.write(f"{os.getpid()}|{ct}")
    except Exception:
        _right_half_lock = None

    # 记录父进程（训练器）PID，用于检测训练器崩溃后导入器自动退出
    # 训练器崩溃时来不及写 .trainer_quit 信号文件，导入器需主动检测父进程存活
    _parent_pid = os.getppid()

    # 导入器启动时立即写入进度，填补 UI 初始化期间的空白
    if session_dir:
        try:
            pfile = os.path.join(session_dir, ".importer_progress")
            with open(pfile, "w", encoding="utf-8") as f:
                f.write("0.72\n导入器正在启动...")
        except Exception:
            pass

    window = BannerImportWindow()
    window._session_dir = session_dir
    window._write_importer_progress(0.80, "导入器UI初始化完成")

    def _check_trainer_quit():
        if session_dir:
            closing_file = os.path.join(session_dir, ".trainer_closing")
            if os.path.exists(closing_file):
                window._close_blocked = True
            else:
                if window._close_blocked:
                    window._close_blocked = False

            quit_file = os.path.join(session_dir, ".trainer_quit")
            if os.path.exists(quit_file):
                try:
                    os.remove(quit_file)
                except Exception:
                    pass
                window._close_blocked = False
                window._force_quit = True
                # 若 exit.pyw 在运行，先终止子进程及其定时器
                if window._exit_process is not None:
                    try:
                        window._exit_process.terminate()
                    except Exception:
                        pass
                    window._exit_process = None
                if window._exit_timer is not None:
                    try:
                        window._exit_timer.stop()
                    except Exception:
                        pass
                    window._exit_timer = None
                window.close()
                return

        # 父进程（训练器）存活检测：训练器崩溃/被杀时来不及写 .trainer_quit，
        # 信号文件机制失效，导入器需主动检测父进程是否存活，否则成为孤儿进程，
        # 残留锁文件导致 start.pyw 误判"训练工具正在运行"及最大实例数限制误触发
        if _parent_pid > 0:
            try:
                STILL_ACTIVE = 259
                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, _parent_pid)
                if not handle:
                    raise OSError("parent gone")
                exit_code = ctypes.c_ulong()
                alive = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                ctypes.windll.kernel32.CloseHandle(handle)
                if not alive or exit_code.value != STILL_ACTIVE:
                    raise OSError("parent exited")
            except Exception:
                window._close_blocked = False
                window._force_quit = True
                if window._exit_process is not None:
                    try:
                        window._exit_process.terminate()
                    except Exception:
                        pass
                    window._exit_process = None
                if window._exit_timer is not None:
                    try:
                        window._exit_timer.stop()
                    except Exception:
                        pass
                    window._exit_timer = None
                window.close()
                return
        QTimer.singleShot(100, _check_trainer_quit)

    QTimer.singleShot(100, _check_trainer_quit)

    window.show()
    window.activateWindow()
    window.raise_()
    app.processEvents()
    # 启动父进程存活监控
    window._start_parent_monitor()

    # 自动布局开启时总是 snap 到右侧；
    # 自动布局关闭时：restore_layout 关闭且已恢复保存位置用保存位置，否则右半中心最小尺寸
    restore_layout = SettingsManager().get("restore_layout", True)
    restored = (not restore_layout) and window._restore_window_geometry()
    auto_layout = SettingsManager().get("auto_layout", True)
    if session_dir:
        window._write_importer_progress(0.85, "正在调整导入器窗口布局...")
    if _SYS_COMPAT["is_win10_plus"]:
        hwnd = int(window.winId())
        if auto_layout:
            _minimize_existing_windows()
            window.resize(window.minimumSize())
            _double_snap(hwnd, "right")
            window._apply_layout()
            _force_activate(hwnd, window)
        elif restored and not _is_window_snapped(hwnd):
            _force_activate(hwnd, window)
        else:
            # 非snap模式：窗口放屏幕右半中心，使用最小尺寸
            _minimize_existing_windows()
            screen = QApplication.primaryScreen()
            if screen:
                sg = screen.availableGeometry()
                min_sz = window.minimumSize()
                half_w = sg.width() // 2
                x = sg.x() + half_w + max(0, (half_w - min_sz.width()) // 2)
                y = sg.y() + max(0, (sg.height() - min_sz.height()) // 2)
                window.resize(min_sz)
                window.move(x, y)
                window._apply_layout()
            _force_activate(hwnd, window)

    if session_dir:
        window._write_importer_progress(0.92, "导入器准备就绪")
        ready_file = os.path.join(session_dir, ".importer_ready")
        try:
            with open(ready_file, "w") as f:
                f.write("ready")
        except Exception:
            pass

    app.exec_()
    # 强制退出：杜绝窗口关闭后进程残留（解释器退出会等待非守护线程）
    os._exit(0)
