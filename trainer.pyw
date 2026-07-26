import os
import sys
import time
import ctypes
import random
import subprocess
import tempfile
import uuid
import glob
import configparser
import traceback

# 在 import torch 之前写入初始进度（torch 加载需 5-15 秒，避免进度条空等）
if "--session-dir" in sys.argv:
    _sd_idx = sys.argv.index("--session-dir")
    if _sd_idx + 1 < len(sys.argv):
        try:
            _pfile = os.path.join(sys.argv[_sd_idx + 1], ".trainer_progress")
            with open(_pfile, "w", encoding="utf-8") as _f:
                _f.write("0.05\n正在加载PyTorch深度学习框架...")
        except Exception:
            pass

# torch 必须在 PyQt5 之前 import，否则 c10.dll 与 PyQt5 的 DLL 冲突 (WinError 1114)
import torch

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSpinBox, QGroupBox, QAction,
    QGridLayout, QMessageBox, QProgressBar,
    QListWidget, QFileDialog, QSizePolicy,
    QScrollArea, QCheckBox, QFrame, QDialog, QRadioButton, QButtonGroup,
    QSplitter, QTabWidget, QComboBox, QTextEdit, QListWidgetItem
)
from PyQt5.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QFont, QIcon, QConicalGradient, QPainterPath, QBrush
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, QThread, pyqtSignal, QFileSystemWatcher, QSize

from utils.banner_utils import generate_banner_image, color_name, type as banner_type, type_zh, color
from utils.mbtl_utils import load_banners_from_file, write_mbtl
from utils.settings_manager import SettingsManager, apply_theme, HardwareDetectThread, grade_gpu_memory, grade_system_memory, load_hardware_cache, save_hardware_cache, resolve_theme, load_workspace, save_workspace_section, clear_workspace_window, apply_dwm_dark_mode, compute_resource_allocation, build_arch_cache, resolve_app_path


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


_MAX_INSTANCES = 1


def _get_max_instances():
    return _MAX_INSTANCES


def _minimize_existing_windows():
    import glob
    lock_dir = tempfile.gettempdir()
    lock_files = glob.glob(os.path.join(lock_dir, "banner_group_lock_*.lock"))
    own_pid = os.getpid()
    app_pids = {own_pid}
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
                    app_pids.add(pid)
        except Exception:
            pass
    # 预读 explorer.exe 的 PID（Windows 外壳，管理任务栏和开始菜单）
    # 文件管理器窗口（CabinetWClass）会被最小化，但开始菜单/任务栏等不会
    explorer_pids = set()
    try:
        import subprocess
        r = subprocess.run(
            ["tasklist", "/fi", "imagename eq explorer.exe", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=5
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



def _check_instance_limit():
    max_instances = _get_max_instances()
    if max_instances <= 0:
        return True
    import glob
    lock_dir = tempfile.gettempdir()
    lock_files = glob.glob(os.path.join(lock_dir, "banner_group_lock_*.lock"))
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


def _acquire_instance_slot():
    """原子地检查实例限制并创建锁文件（用Mutex避免竞态条件）。

    返回 lock_file 路径（成功）或 None（失败）。
    """
    max_instances = _get_max_instances()
    if max_instances <= 0:
        return _create_instance_lock()

    # 用 Windows Mutex 序列化 check-and-create，防止点击过快导致多实例
    mutex_name = "Global\\banner_trainer_instance_mutex"
    WAIT_OBJECT_0 = 0
    WAIT_TIMEOUT = 0x102
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
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
        ctypes.windll.kernel32.ReleaseMutex(mutex)
        ctypes.windll.kernel32.CloseHandle(mutex)


def _create_instance_lock():
    lock_dir = tempfile.gettempdir()
    lock_file = os.path.join(lock_dir, f"banner_group_lock_{os.getpid()}.lock")
    try:
        with open(lock_file, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass
    return lock_file


def _remove_instance_lock(lock_file):
    try:
        if os.path.exists(lock_file):
            os.remove(lock_file)
    except Exception:
        pass


def _get_ui_scale(app):
    screen = app.primaryScreen()
    geo = screen.availableGeometry() if screen else None
    sw = geo.width() if geo else 1920
    sh = geo.height() if geo else 1080
    raw = max(min(sw / 1920, sh / 1080), 1.0)
    return min(raw, 1.4) * 1.1


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
    except Exception:
        pass
    try:
        import cv2
        lib_info.append(f"opencv={cv2.__version__}")
    except Exception:
        pass
    try:
        from PyQt5.Qt import PYQT_VERSION_STR
        lib_info.append(f"PyQt5={PYQT_VERSION_STR}")
    except Exception:
        pass

    info["_lib_info"] = lib_info

    return info

_SYS_COMPAT = _detect_system_compat()
_training_error_suppressed = False


def _show_error_popup(title, message, source="训练器"):
    from utils.settings_manager import report_error
    report_error(title, message, source)


def _print_model_tree(model, prefix="", is_last=True, is_root=True):
    if is_root:
        name = model.__class__.__name__
        params = sum(p.numel() for p in model.parameters())
        print(f"{name} ({params:,} params)")
        prefix = ""
    children = list(model.named_children())
    for i, (child_name, child_module) in enumerate(children):
        last = (i == len(children) - 1)
        connector = "└── " if last else "├── "
        child_prefix = "    " if last else "│   "
        params = sum(p.numel() for p in child_module.parameters())
        cls = child_module.__class__.__name__
        detail = ""
        if hasattr(child_module, 'in_features') and hasattr(child_module, 'out_features'):
            detail = f" [{child_module.in_features}→{child_module.out_features}]"
        elif hasattr(child_module, 'kernel_size'):
            detail = f" [kernel={child_module.kernel_size}]"
        elif hasattr(child_module, 'p'):
            detail = f" [p={child_module.p}]"
        sub_children = list(child_module.named_children())
        if sub_children:
            print(f"{prefix}{connector}{child_name}: {cls} ({params:,} params)")
            _print_model_tree(child_module, prefix + child_prefix, last, is_root=False)
        else:
            print(f"{prefix}{connector}{child_name}: {cls}{detail} ({params:,} params)")


class BannerLabel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._progress = 0.0
        self._show_progress = False
        self._checkmark = False

    def _is_dark_theme(self):
        win = self.window()
        if win is not None and hasattr(win, "_current_theme"):
            return win._current_theme == "dark"
        return False

    def setPixmap(self, pixmap):
        self._pixmap = pixmap
        self.update()

    def set_progress(self, value, show=True, checkmark=False):
        self._progress = max(0.0, min(1.0, value))
        self._show_progress = show
        self._checkmark = checkmark
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        s = getattr(self, '_scale', 1.0)
        pen_width = max(int(5 * s), 4)
        margin = pen_width / 2 + 1
        rect = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)

        is_dark = self._is_dark_theme()
        border_color = QColor("#555555") if is_dark else QColor("#dddddd")
        bg_color = QColor("#3c3c3c") if is_dark else QColor("#f8f8f8")
        progress_track = QColor("#2e5a30") if is_dark else QColor("#c8e6c9")

        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRect(rect)

        if self._pixmap:
            inner_margin = pen_width + 2
            inner_w = w - 2 * inner_margin
            inner_h = h - 2 * inner_margin
            if inner_w > 0 and inner_h > 0:
                target_w, target_h = inner_w, inner_w * 2
                if target_h > inner_h:
                    target_h = inner_h
                    target_w = inner_h // 2
                target_w = max(target_w, 1)
                target_h = max(target_h, 1)
                scaled = self._pixmap.scaled(int(target_w), int(target_h), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                x = inner_margin + (inner_w - scaled.width()) // 2
                y = inner_margin + (inner_h - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)

        painter.setPen(QPen(border_color, max(int(2 * s), 1), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

        if self._show_progress and self._progress > 0:
            painter.setPen(QPen(progress_track, pen_width, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
            painter.drawRect(rect)

            grad_color1 = QColor("#66bb6a") if is_dark else QColor("#2e7d32")
            grad_color2 = QColor("#43a047") if is_dark else QColor("#1b5e20")

            gradient = QConicalGradient(rect.center(), 90)
            gradient.setColorAt(0, grad_color1)
            gradient.setColorAt(0.5, grad_color2)
            gradient.setColorAt(1, grad_color1)

            pen = QPen(QBrush(gradient), pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)

            total_perimeter = 2 * (rect.width() + rect.height())
            draw_length = total_perimeter * self._progress

            path_points = []
            corners = [
                (rect.topLeft(), rect.topRight()),
                (rect.topRight(), rect.bottomRight()),
                (rect.bottomRight(), rect.bottomLeft()),
                (rect.bottomLeft(), rect.topLeft()),
            ]

            remaining = draw_length
            current_pos = rect.topLeft()
            for start, end in corners:
                side_length = abs(end.x() - start.x()) if abs(end.x() - start.x()) > 0.01 else abs(end.y() - start.y())
                if remaining <= 0:
                    break
                if remaining >= side_length:
                    path_points.append((current_pos, end))
                    remaining -= side_length
                    current_pos = end
                else:
                    dx = end.x() - start.x()
                    dy = end.y() - start.y()
                    ratio = remaining / side_length if side_length > 0 else 0
                    stop = QPointF(start.x() + dx * ratio, start.y() + dy * ratio)
                    path_points.append((current_pos, stop))
                    remaining = 0
                    break

            if path_points:
                pp = QPainterPath()
                pp.moveTo(path_points[0][0])
                for _, end_pt in path_points:
                    pp.lineTo(end_pt)
                painter.drawPath(pp)

            if self._checkmark:
                check_size = max(int(18 * s), 14)
                check_color = QColor("#66bb6a") if is_dark else QColor("#1b5e20")
                painter.setPen(QPen(check_color, max(int(3 * s), 2), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                cx = rect.right() - check_size - 2
                cy = rect.top() + 4
                pp2 = QPainterPath()
                pp2.moveTo(cx, cy + check_size * 0.5)
                pp2.lineTo(cx + check_size * 0.3, cy + check_size * 0.8)
                pp2.lineTo(cx + check_size, cy + check_size * 0.15)
                painter.drawPath(pp2)
            else:
                painter.setPen(QPen(QColor("#333"), 1))
                pct_fs = max(int(14 * s), 11)
                painter.setFont(QFont("Microsoft YaHei UI", pct_fs, QFont.Bold))
                pct_text = f"{int(self._progress * 100)}%"
                painter.drawText(rect, Qt.AlignTop | Qt.AlignRight, pct_text)

        painter.end()


class BannerGridWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.banner_labels = []
        self._compact_cols = 4
        self._info_text = ""
        for _ in range(8):
            label = BannerLabel(self)
            self.banner_labels.append(label)

    def _is_dark_theme(self):
        win = self.window()
        if win is not None and hasattr(win, "_current_theme"):
            return win._current_theme == "dark"
        return False

    def setInfoText(self, text):
        """设置空状态提示文字（传入空串则恢复旗帜显示）。"""
        self._info_text = text
        for label in self.banner_labels:
            label.setVisible(not text)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        margin = 2
        rect = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)
        is_dark = self._is_dark_theme()
        bg_color = QColor("#3c3c3c") if is_dark else QColor("#f5f5f5")
        border_color = QColor("#555555") if is_dark else QColor("#cccccc")
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 4, 4)
        # 空状态文字（与导入器 BannerPreviewWidget 风格一致）
        if self._info_text:
            info_color = QColor("#aaaaaa") if is_dark else QColor("#666666")
            s = getattr(self, '_scale', 1.0)
            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(max(int(16 * s), 13))
            painter.setFont(font)
            painter.setPen(info_color)
            painter.drawText(rect, Qt.AlignCenter, self._info_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_banners()

    def _layout_banners(self):
        if self._info_text:
            return  # 空状态不布局旗帜
        w = self.width()
        h = self.height()
        if w < 10 or h < 10:
            return

        s = getattr(self, '_scale', 1.0)
        spacing = max(int(8 * s), 6)

        cols = self._compact_cols
        rows = 8 // cols

        cell_w = (w - (cols - 1) * spacing) // cols
        cell_h = cell_w * 2

        total_h_needed = rows * cell_h + (rows - 1) * spacing
        if total_h_needed > h:
            cell_h = (h - (rows - 1) * spacing) // rows
            cell_w = cell_h // 2

        total_w = cols * cell_w + (cols - 1) * spacing
        total_h = rows * cell_h + (rows - 1) * spacing
        x_offset = max(0, (w - total_w) // 2)
        y_offset = max(0, (h - total_h) // 2)

        for i, label in enumerate(self.banner_labels):
            row = i // cols
            col = i % cols
            x = x_offset + col * (cell_w + spacing)
            y = y_offset + row * (cell_h + spacing)
            label.setGeometry(x, y, cell_w, cell_h)


class _ImportProgressWindow(QWidget):
    def __init__(self, parent=None, total=0):
        super().__init__(None)
        self._progress = 0.0
        self._status_text = "正在准备导入..."
        self._total = total
        self._done = False
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        sw = geo.width() if geo else 1920
        sh = geo.height() if geo else 1080
        lw = max(int(sw * 0.28), 400)
        lh = max(int(sh * 0.16), 140)
        self._s = min(sw / 1920, sh / 1080, 1.05)
        self.setFixedSize(lw, lh)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        if parent:
            pg = parent.geometry()
            self.move(pg.x() + (pg.width() - lw) // 2, pg.y() + (pg.height() - lh) // 2)

    def closeEvent(self, event):
        if not self._done:
            event.ignore()

    def update_progress(self, current, text=""):
        if self._total > 0:
            self._progress = min(current / self._total, 1.0)
        if text:
            self._status_text = text
        self.update()
        QApplication.processEvents()

    def finish(self):
        self._done = True
        self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        s = self._s

        if _SYS_COMPAT["is_win11_plus"]:
            bg_color = QColor("#fafbff")
            border_color = QColor("#c7d2fe")
            title_color = QColor("#312e81")
            bar_bg = QColor("#e0e7ff")
            bar_fill = QColor("#6366f1")
            status_color = QColor("#6b7280")
        elif _SYS_COMPAT["is_win10_plus"]:
            bg_color = QColor("#f5f9ff")
            border_color = QColor("#b3d4fc")
            title_color = QColor("#003580")
            bar_bg = QColor("#dbeafe")
            bar_fill = QColor("#0078D4")
            status_color = QColor("#888888")
        else:
            bg_color = QColor("#f0f0f0")
            border_color = QColor("#e0e0e0")
            title_color = QColor("#333333")
            bar_bg = QColor("#d0d0d0")
            bar_fill = QColor("#4a90d9")
            status_color = QColor("#888888")

        painter.fillRect(0, 0, w, h, bg_color)
        painter.setPen(QPen(border_color, 2))
        painter.drawRect(1, 1, w - 2, h - 2)

        title_fs = max(int(13 * s), 11)
        status_fs = max(int(10 * s), 9)

        painter.setPen(title_color)
        painter.setFont(QFont("Microsoft YaHei UI", title_fs, QFont.Bold))
        painter.drawText(QRectF(0, int(h * 0.06), w, int(h * 0.18)), Qt.AlignCenter, "正在导入旗帜数据")

        bar_margin = int(w * 0.10)
        bar_y = int(h * 0.38)
        bar_w = w - 2 * bar_margin
        bar_h = max(int(20 * s), 16)

        painter.setPen(Qt.NoPen)
        painter.setBrush(bar_bg)
        painter.drawRoundedRect(bar_margin, bar_y, bar_w, bar_h, 4, 4)

        fill_w = int(bar_w * self._progress)
        if fill_w > 0:
            painter.setBrush(bar_fill)
            painter.drawRoundedRect(bar_margin, bar_y, fill_w, bar_h, 4, 4)

        painter.setPen(title_color)
        pct_fs = max(int(12 * s), 10)
        painter.setFont(QFont("Microsoft YaHei UI", pct_fs, QFont.Bold))
        pct_text = f"{int(self._progress * 100)}%"
        painter.drawText(QRectF(bar_margin, bar_y, bar_w, bar_h), Qt.AlignCenter, pct_text)

        painter.setPen(status_color)
        painter.setFont(QFont("Microsoft YaHei UI", status_fs))
        painter.drawText(QRectF(int(w * 0.05), bar_y + bar_h + int(5 * s), int(w * 0.90), int(h * 0.25)),
                         Qt.AlignCenter | Qt.TextWordWrap, self._status_text)

        painter.end()


class _LossChartWidget(QWidget):
    def __init__(self, losses, parent=None):
        super().__init__(parent)
        self.losses = losses
        self._scale = getattr(parent, '_scale', 1.0) if parent else 1.0
        # 读取主题：优先从父窗口链向上查找 _current_theme，找不到则从配置读取
        _theme = "light"
        _p = parent
        while _p is not None:
            if hasattr(_p, "_current_theme"):
                _theme = _p._current_theme
                break
            _p = _p.parent() if hasattr(_p, "parent") else None
        else:
            _theme = SettingsManager().get("theme", "light")
        _theme = resolve_theme(_theme)
        self._is_dark = _theme == "dark"
        self.setMinimumSize(600, 380)

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QPainterPath
        from PyQt5.QtCore import QRectF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        s = min(self._scale, 1.2)
        margin_l, margin_r, margin_t, margin_b = int(70 * s), int(20 * s), int(45 * s), int(45 * s)
        plot_w = w - margin_l - margin_r
        plot_h = h - margin_t - margin_b

        is_dark = self._is_dark
        bg_color = QColor(45, 45, 48) if is_dark else QColor(255, 255, 255)
        grid_color = QColor(80, 80, 80) if is_dark else QColor(200, 200, 200)
        text_color = QColor(200, 200, 200) if is_dark else QColor(100, 100, 100)
        anno_color = QColor(140, 170, 230) if is_dark else QColor(30, 80, 180)
        last_anno_color = QColor(230, 140, 140) if is_dark else QColor(180, 30, 30)

        painter.fillRect(self.rect(), bg_color)

        min_loss = min(self.losses)
        max_loss = max(self.losses)
        loss_range = max_loss - min_loss if max_loss > min_loss else 1.0
        n = len(self.losses)

        painter.setPen(QPen(grid_color, 1))
        num_grid_y = 5
        grid_fs = max(int(9 * s), 8)
        for i in range(num_grid_y + 1):
            y = margin_t + plot_h - (i / num_grid_y) * plot_h
            painter.drawLine(margin_l, int(y), margin_l + plot_w, int(y))
            val = min_loss + (i / num_grid_y) * loss_range
            painter.setPen(QPen(text_color, 1))
            painter.setFont(QFont("Microsoft YaHei UI", grid_fs))
            painter.drawText(0, int(y) - 10, margin_l - 8, 20, Qt.AlignRight | Qt.AlignVCenter, f"{val:.4f}")
            painter.setPen(QPen(grid_color, 1))

        num_grid_x = min(n, 10)
        for i in range(num_grid_x + 1):
            x = margin_l + (i / num_grid_x) * plot_w
            painter.drawLine(int(x), margin_t, int(x), margin_t + plot_h)
            epoch_val = int(1 + (i / num_grid_x) * (n - 1)) if n > 1 else 1
            painter.setPen(QPen(text_color, 1))
            painter.setFont(QFont("Microsoft YaHei UI", grid_fs))
            painter.drawText(int(x) - 20, margin_t + plot_h + 5, 40, 20, Qt.AlignCenter, str(epoch_val))
            painter.setPen(QPen(grid_color, 1))

        label_fs = max(int(10 * s), 9)
        title_fs = max(int(12 * s), 10)
        anno_fs = max(int(8 * s), 7)

        painter.setPen(QPen(text_color, 1))
        painter.setFont(QFont("Microsoft YaHei UI", label_fs))
        painter.drawText(margin_l + plot_w // 2 - 30, h - 28, 60, 20, Qt.AlignCenter, "Epoch")
        painter.save()
        painter.translate(15, margin_t + plot_h // 2)
        painter.rotate(-90)
        painter.drawText(-25, 0, 50, 20, Qt.AlignCenter, "Loss")
        painter.restore()

        painter.setPen(QPen(text_color, 1))
        painter.setFont(QFont("Microsoft YaHei UI", title_fs, QFont.Bold))
        painter.drawText(w // 2 - 60, 8, 120, 25, Qt.AlignCenter, "Training Loss")

        painter.setPen(QPen(grid_color, 1))
        painter.drawRect(margin_l, margin_t, plot_w, plot_h)

        path = QPainterPath()
        points = []
        for i, loss in enumerate(self.losses):
            x = margin_l + (i / (n - 1)) * plot_w if n > 1 else margin_l + plot_w / 2
            y = margin_t + plot_h - ((loss - min_loss) / loss_range) * plot_h
            points.append((x, y))
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        painter.setPen(QPen(QColor(66, 133, 244), 2))
        painter.setBrush(QColor(66, 133, 244, 40))
        painter.drawPath(path)

        fill_path = QPainterPath(path)
        fill_path.lineTo(margin_l + plot_w, margin_t + plot_h)
        fill_path.lineTo(margin_l, margin_t + plot_h)
        fill_path.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(66, 133, 244, 30))
        painter.drawPath(fill_path)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(66, 133, 244))
        dot_r = 3
        for x, y in points:
            painter.drawEllipse(QRectF(x - dot_r, y - dot_r, dot_r * 2, dot_r * 2))

        max_labels = 8
        step = max(1, n // max_labels)
        painter.setPen(QPen(anno_color, 1))
        painter.setFont(QFont("Microsoft YaHei UI", anno_fs))
        for i in range(0, n, step):
            x, y = points[i]
            painter.drawText(QRectF(x - 30, y - 22, 60, 16),
                             Qt.AlignCenter, f"{self.losses[i]:.4f}")
        if n > 0 and (n - 1) % step != 0:
            x, y = points[-1]
            painter.setPen(QPen(last_anno_color, 1))
            painter.drawText(QRectF(x - 30, y - 22, 60, 16),
                             Qt.AlignCenter, f"{self.losses[-1]:.4f}")

        painter.end()


class TrainingThread(QThread):
    progress_update = pyqtSignal(int)
    progress_detail = pyqtSignal(str)
    banner_progress = pyqtSignal(int, int, int, int, float, float)
    training_complete = pyqtSignal()
    training_error = pyqtSignal(str)

    def __init__(self, trainer, dataloader, epochs, val_dataloader=None):
        super().__init__()
        self.trainer = trainer
        self.dataloader = dataloader
        self.val_dataloader = val_dataloader
        self.epochs = epochs
        self.epoch_losses = []

    def run(self):
        try:
            self.progress_detail.emit("正在准备数据...")
            self.progress_update.emit(5)

            def on_banner(banner_idx, total_banners, epoch, epochs, loss):
                try:
                    within = (banner_idx + 1) / total_banners if total_banners > 0 else 1.0
                    self.banner_progress.emit(banner_idx, total_banners, epoch, epochs, within, loss)
                    total_progress = int(5 + ((epoch + within) / epochs) * 85)
                    self.progress_update.emit(min(total_progress, 90))
                    self.progress_detail.emit(f"Epoch {epoch+1}/{epochs} - 旗帜 {banner_idx+1}/{total_banners} | Loss: {loss:.4f}")
                except Exception as cb_err:
                    print(f"[训练器] banner_callback异常: {cb_err}")

            self.trainer.train(self.dataloader, self.epochs, self.val_dataloader, banner_callback=on_banner)

            self.epoch_losses = list(self.trainer.epoch_loss_history) if hasattr(self.trainer, 'epoch_loss_history') else []

            self.progress_detail.emit("正在完成最后处理...")
            self.progress_update.emit(95)
            import time as _time
            _time.sleep(0.5)
            self.progress_update.emit(100)
            self.progress_detail.emit("训练完成！")
            self.training_complete.emit()
        except Exception as e:
            import traceback as _tb
            tb_str = "".join(_tb.format_exception(type(e), e, e.__traceback__))
            try:
                print(f"训练过程中发生错误: {str(e)}\n{tb_str[-500:]}")
            except Exception:
                pass
            self.progress_detail.emit(f"训练失败: {str(e)}")
            self.progress_detail.emit(f"训练失败: {str(e)}")
            self.progress_update.emit(0)
            self.training_error.emit(str(e))


class ModelLoadThread(QThread):
    """在子线程中加载模型（import torch / ViT 等），避免 dll 初始化阻塞 GUI。

    通过信号通知主线程进度和结果，所有 GUI 操作由主线程在回调中执行。
    """
    progress_update = pyqtSignal(float, str)
    model_ready = pyqtSignal(object, object)  # model, trainer
    load_failed = pyqtSignal(str)

    def __init__(self, training_mode="normal", model_arch="vit_b_16", dropout=0.2, parent=None):
        super().__init__(parent)
        self.training_mode = training_mode
        self.model_arch = model_arch
        self.dropout = dropout

    def run(self):
        try:
            self.progress_update.emit(0.15, "正在初始化PyTorch深度学习框架...")
            # torch 已在模块顶部全局 import（必须在 PyQt5 之前）
            self.progress_update.emit(0.25, "正在构建ViT视觉Transformer网络结构...")
            from models.structures.vit_model import ViT, BannerTrainer
            model = ViT(model_arch=self.model_arch, dropout=self.dropout)
            _arch_display = {
                "vit_b_16": "ViT-B/16", "vit_l_16": "ViT-L/16",
                "vit_b_32": "ViT-B/32", "vit_l_32": "ViT-L/32",
                "vit_h_14": "ViT-H/14",
                "dvit_b_16": "D-ViT-B/16", "dvit_s_16": "D-ViT-S/16",
                "dvit_t_16": "D-ViT-T/16",
            }
            print(f"[训练器] 模型加载完成: {_arch_display.get(self.model_arch, self.model_arch)}")
            _print_model_tree(model)
            total_params = sum(p.numel() for p in model.parameters())
            trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
            print(f"[训练器] 总参数量: {total_params:,} | 可训练参数量: {trainable_params:,}")
            self.progress_update.emit(0.35, "正在分析模型参数({:,}万参数)...".format(total_params // 10000))
            if self.training_mode == "peft":
                try:
                    from peft import LoraConfig, get_peft_model
                    self.progress_update.emit(0.40, "正在配置PEFT微调适配器...")
                    lora_config = LoraConfig(
                        r=8, lora_alpha=16,
                        target_modules=["mlp.0", "mlp.3"],
                        lora_dropout=0.1, bias="none"
                    )
                    model = get_peft_model(model, lora_config)
                    print("[训练器] PEFT模型创建成功")
                except ValueError as e:
                    print(f"[训练器] PEFT配置错误: {e}")
            self.progress_update.emit(0.50, "正在编译训练器优化器与损失函数...")
            # 设置显存使用上限（必须在 CUDA 上下文初始化之前，即 model.to(device) 之前）
            if torch.cuda.is_available():
                sm = SettingsManager()
                gpu_mem = sm.get("gpu_memory", 0)
                sys_mem = sm.get("sys_memory", 0)
                if not isinstance(gpu_mem, (int, float)):
                    gpu_mem = 0
                if not isinstance(sys_mem, (int, float)):
                    sys_mem = 0
                mixed_prec = sm.get("mixed_precision", "fp16") == "fp16"
                alloc = compute_resource_allocation(gpu_mem, sys_mem, "vit_b_16", mixed_prec, sm.get("perf_level", "balanced"))
                if alloc["gpu_fraction"] > 0:
                    try:
                        torch.cuda.set_per_process_memory_fraction(alloc["gpu_fraction"])
                        print(f"[训练器] 显存分配: {alloc['gpu_fraction']:.0%}（总{gpu_mem}GB，保留{alloc['gpu_reserved_gb']:.1f}GB给系统）")
                    except Exception as e:
                        print(f"[训练器] 显存限制设置失败（已忽略）: {e}")
            trainer = BannerTrainer(model)
            self.progress_update.emit(0.58, "模型加载完成，等待导入旗帜数据")
            self.model_ready.emit(model, trainer)
            print("[训练器] 初始化完成")
        except Exception as e:
            print(f"[训练器] 模型加载失败: {e}")
            self.load_failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self, training_mode="normal", session_dir=None):
        super().__init__()
        self.setWindowTitle("旗帜训练器 v0.5 beta1")
        self.training_mode = training_mode
        self._session_dir = session_dir
        self._scale_override = None

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        sw = geo.width() if geo else 1920
        sh = geo.height() if geo else 1080
        if sh < 480:
            QMessageBox.critical(None, "分辨率过低",
                f"系统可用高度 {sh}px 过低，无法正常显示。\n"
                f"请将屏幕分辨率设置为 720P 或以上。")
            sys.exit(1)
        sx = geo.x() if geo else 0
        sy = geo.y() if geo else 0
        ui_scale = max(min(sw / 1920, sh / 1080), 1.0)
        dpi_scale = (screen.logicalDotsPerInch() / 96.0) if screen else 1.0
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
        if "--left-half" in sys.argv:
            tx = sx + (sw // 2 - base_w) // 2
        else:
            tx = sx + (sw - base_w) // 2
        self.setGeometry(tx, sy + (sh - base_h - ch) // 2, base_w, base_h)

        base_fs = max(int(10 * self._scale), 9)
        btn_fs = max(int(11 * self._scale), 10)
        bg = "#f0f0f0"
        fg = "#000000"
        group_border = "#cccccc"
        input_bg = "#ffffff"
        arrow_color = "#666666"
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: #f0f0f0; }}
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
            QGroupBox {{ font-size: {btn_fs}px; font-weight: bold; border: 1px solid #ccc; border-radius: 6px; margin-top: 8px; padding-top: 16px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
            QListWidget {{ font-size: {base_fs}px; }}
            QTabWidget::pane {{ font-size: {base_fs}px; border: none; }}
            QTabBar {{ background-color: {bg}; }}
            QTabBar::tab {{ font-size: {btn_fs}px; padding: {max(int(4*self._scale),3)}px {max(int(10*self._scale),8)}px; color: {fg}; background-color: {bg}; border: 1px solid {group_border}; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; }}
            QTabBar::tab:selected {{ background-color: {input_bg}; }}
            QTabBar::tab:!selected {{ color: {arrow_color}; }}
            QMenuBar {{ font-size: {btn_fs}px; }}
            QMenu {{ font-size: {base_fs}px; }}
            QProgressBar {{ font-size: {base_fs}px; }}
            QSplitter {{ background-color: #f5f5f5; }}
            QSplitter::handle {{ background-color: #ddd; }}
            QScrollArea {{ border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; border: none; }}
            QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; border: none; }}
            QScrollBar::handle {{ background: #c0c0c0; border-radius: 5px; min-height: 30px; min-width: 30px; }}
            QScrollBar::handle:hover {{ background: #a0a0a0; }}
            QScrollBar::handle:pressed {{ background: #909090; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ border: none; background: none; width: 0; height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        """)

        icon_path = os.path.join("images", "icons", "trainer.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 消除窗口移动时的白色残影
        self.setAutoFillBackground(True)

        self.training_images = []
        self.preview_banner = None
        self.current_display_mode = None
        self._layout_applying = False
        self._current_page = 0
        self._page_size = 8
        self._is_training = False
        self._training_done = False
        self._model_trained = False  # 区分"模型架构已加载"和"模型已训练"，控制保存按钮
        self._completed_banners = set()
        self._force_quit = False
        self._close_blocked = False
        self._exit_process = None
        self._exit_timer = None
        self._splitter_adjusting = False
        # Tab2 序列图组训练数据：[[img_path, banner_data], ...]
        self._tab2_graphic_marks = []
        # 工作区布局文件：持久化训练器 splitter 位置
        self._workspace_data = load_workspace()

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

        self.init_ui()
        self._apply_theme_to_window(self._current_theme)
        self.model = None
        self.trainer = None
        self._update_button_states()
        self._session_dir = session_dir
        self._write_progress(0.10, "训练器UI初始化完成")
        print("[训练器] 窗口初始化完成，模型将延迟加载")
        self._start_watchers()
        QTimer.singleShot(100, self._load_model_async)
        self._setup_auto_save()

    def _write_progress(self, value, status=""):
        if not self._session_dir:
            return
        try:
            pfile = os.path.join(self._session_dir, ".trainer_progress")
            with open(pfile, "w", encoding="utf-8") as f:
                f.write(f"{value}\n{status}")
        except Exception:
            pass

    def _load_model_async(self):
        self.status_label.setText("正在加载模型...")
        # 使用子线程加载模型，避免 import torch 的 dll 初始化阻塞 GUI
        sm = SettingsManager()
        _arch = sm.get("model_arch", "vit_b_16")
        _dropout = float(sm.get("dropout", 0.2))
        self._model_load_thread = ModelLoadThread(self.training_mode, _arch, _dropout, parent=self)
        self._model_load_thread.progress_update.connect(self._on_model_load_progress)
        self._model_load_thread.model_ready.connect(self._on_model_load_ready)
        self._model_load_thread.load_failed.connect(self._on_model_load_failed)
        self._model_load_thread.start()

    def _on_model_load_progress(self, value, status):
        self._write_progress(value, status)
        if value < 0.58:
            self.status_label.setText("正在加载模型...")

    def _on_model_load_ready(self, model, trainer):
        self.model = model
        self.trainer = trainer
        self.status_label.setText("模型加载完成，等待数据导入")
        sm = SettingsManager()
        if sm.get("auto_resource_alloc", True):
            # 自动分配 batch_size（根据显存/内存直接计算）
            gpu_mem = sm.get("gpu_memory", 0)
            sys_mem = sm.get("sys_memory", 0)
            if not isinstance(gpu_mem, (int, float)):
                gpu_mem = 0
            if not isinstance(sys_mem, (int, float)):
                sys_mem = 0
            mixed_prec = sm.get("mixed_precision", "fp16") == "fp16"
            alloc = compute_resource_allocation(gpu_mem, sys_mem, "vit_b_16", mixed_prec, sm.get("perf_level", "balanced"))
            self.batch_spin.setValue(alloc["batch_size"])
            print(f"[训练器] 自动分配 batch_size={alloc['batch_size']} num_workers={alloc['num_workers']}（可用显存{alloc['usable_gpu_gb']:.1f}GB）")
        else:
            self.batch_spin.setEnabled(True)
        self._update_button_states()
        cb = getattr(self, "_after_model_loaded", None)
        if cb:
            self._after_model_loaded = None
            try:
                cb()
            except Exception:
                pass

    def _on_model_load_failed(self, err_msg):
        self.status_label.setText("模型加载失败")
        _show_error_popup("模型加载失败", err_msg)
        try:
            cb = getattr(self, "_after_model_loaded", None)
            if cb:
                self._after_model_loaded = None
                cb()
        except Exception:
            pass
        finally:
            # 确保 save_button 和 _act_save_model 一定被禁用
            if hasattr(self, "save_button"):
                self.save_button.setEnabled(False)
            if hasattr(self, "_act_save_model"):
                self._act_save_model.setEnabled(False)
            self._update_button_states()

    def _update_button_states(self):
        """根据当前状态更新按钮启用/禁用：没序列时禁用清空，没模型时禁用保存。"""
        has_seq = bool(getattr(self, "training_images", None))
        # 保存模型需要"模型已训练"（不是仅加载了随机权重的架构）
        has_model = getattr(self, "model", None) is not None and getattr(self, "_model_trained", False)
        is_training = getattr(self, "_is_training", False)
        if hasattr(self, "clear_seq_button"):
            self.clear_seq_button.setEnabled(has_seq)
        if hasattr(self, "save_button"):
            self.save_button.setEnabled(has_model)
        if hasattr(self, "_act_save_model"):
            self._act_save_model.setEnabled(has_model)

    def _create_menu_bar(self):
        bar = self.menuBar()

        # ===== 文件 =====
        file_menu = bar.addMenu("文件(&F)")
        act_import = QAction("导入 .mbtl...", self)
        act_import.setShortcut("Ctrl+I")
        act_import.triggered.connect(self._menu_import_banners)
        file_menu.addAction(act_import)

        act_import_mbtlx = QAction("导入 .mbtlx...", self)
        act_import_mbtlx.triggered.connect(self._tab2_import_mbtlx)
        file_menu.addAction(act_import_mbtlx)

        file_menu.addSeparator()
        act_save_model = QAction("保存模型...", self)
        act_save_model.setShortcut("Ctrl+S")
        act_save_model.triggered.connect(self._menu_save_model)
        act_save_model.setEnabled(False)  # 初始无模型时禁用
        file_menu.addAction(act_save_model)
        self._act_save_model = act_save_model

        act_load_model = QAction("加载模型...", self)
        act_load_model.triggered.connect(self._menu_load_model)
        file_menu.addAction(act_load_model)

        file_menu.addSeparator()
        act_exit = QAction("退出", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # ===== 编辑 =====
        edit_menu = bar.addMenu("编辑(&E)")
        act_start = QAction("开始训练", self)
        act_start.setShortcut("F5")
        act_start.triggered.connect(self._menu_start_train)
        edit_menu.addAction(act_start)

        act_stop = QAction("停止训练", self)
        act_stop.setShortcut("F6")
        act_stop.triggered.connect(self._menu_stop_train)
        edit_menu.addAction(act_stop)

        edit_menu.addSeparator()
        act_config = QAction("训练配置...", self)
        act_config.triggered.connect(self._menu_train_config)
        edit_menu.addAction(act_config)

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
        act_loss = QAction("查看Loss曲线", self)
        act_loss.triggered.connect(self._menu_show_loss)
        view_menu.addAction(act_loss)

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
        ui_scale = max(min(sw / 1920, sh / 1080), 1.0)
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
        bg = "#2d2d30" if is_dark else "#f0f0f0"
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
        scroll_handle = "#555555" if is_dark else "#c0c0c0"
        scroll_handle_hover = "#666666" if is_dark else "#a0a0a0"
        scroll_handle_pressed = "#777777" if is_dark else "#909090"
        input_bg = "#3c3c3c" if is_dark else "#ffffff"
        input_border = "#555555" if is_dark else "#cccccc"
        spin_hover = "#4a4a4a" if is_dark else "#e8e8e8"
        arrow_color = "#cccccc" if is_dark else "#666666"
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {bg}; color: {fg}; }}
            QDialog {{ background-color: {bg}; color: {fg}; }}
            QPushButton {{ font-size: {btn_fs}px; min-height: {max(int(26 * self._scale), 22)}px; padding: {max(int(6 * self._scale), 4)}px {max(int(14 * self._scale), 10)}px; background-color: {btn_bg}; color: {btn_fg}; border: 1px solid {btn_border}; border-radius: 8px; }}
            QPushButton:hover {{ background-color: {btn_hover}; border: 1px solid {btn_border}; }}
            QPushButton:pressed {{ background-color: {btn_pressed}; border: 1px solid {btn_border_pressed}; }}
            QPushButton:disabled {{ background-color: {btn_disabled}; color: {btn_disabled_fg}; border: 1px solid {btn_disabled_border}; }}
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
            QGroupBox {{ font-size: {btn_fs}px; font-weight: bold; border: 1px solid {group_border}; border-radius: 6px; margin-top: 8px; padding-top: 16px; color: {fg}; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
            QListWidget {{ font-size: {base_fs}px; color: {fg}; }}
            QTabWidget::pane {{ font-size: {base_fs}px; border: none; }}
            QTabBar {{ background-color: {bg}; }}
            QTabBar::tab {{ font-size: {btn_fs}px; padding: {max(int(4*self._scale),3)}px {max(int(10*self._scale),8)}px; color: {fg}; background-color: {bg}; border: 1px solid {group_border}; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; }}
            QTabBar::tab:selected {{ background-color: {input_bg}; }}
            QTabBar::tab:!selected {{ color: {arrow_color}; }}
            QMenuBar {{ font-size: {btn_fs}px; }}
            QMenu {{ font-size: {base_fs}px; }}
            QProgressBar {{ font-size: {base_fs}px; color: {fg}; }}
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

    def _menu_import_banners(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入旗帜序列", "", "旗帜序列文件 (*.bsq *.json *.mbtl);;所有文件 (*.*)")
        if path:
            self._load_banner_file(path)

    def _menu_save_model(self):
        if hasattr(self, 'save_button') and self.save_button.isEnabled():
            self.save_button.click()

    def _menu_load_model(self):
        default_dir = resolve_app_path("models/model_file")
        path, _ = QFileDialog.getOpenFileName(self, "加载模型", default_dir, "模型文件 (*.pth);;所有文件 (*.*)")
        if path and hasattr(self, 'trainer') and self.trainer:
            try:
                self.trainer.load_model(path)
                QMessageBox.information(self, "成功", f"模型已加载:\n{os.path.basename(path)}")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"加载失败: {str(e)}")

    def _menu_start_train(self):
        if hasattr(self, 'start_btn'):
            self.start_btn.click()

    def _menu_stop_train(self):
        if hasattr(self, 'stop_btn') and self.stop_btn.isEnabled():
            self.stop_btn.click()

    def _menu_show_loss(self):
        if hasattr(self, '_show_loss_chart'):
            self._show_loss_chart()

    def _menu_about(self):
        QMessageBox.about(self, "关于", "旗帜训练器 v0.5 beta1\n\n基于Vision Transformer的旗帜识别模型训练工具。")

    def _menu_show_help(self):
        """打开使用说明窗口（子进程）。"""
        import subprocess
        app_dir = os.path.dirname(os.path.abspath(__file__))
        help_script = os.path.join(app_dir, "help.pyw")
        if os.path.exists(help_script):
            try:
                subprocess.Popen([sys.executable, help_script, "--scale", str(self._scale)])
            except Exception:
                pass

    def _menu_train_config(self):
        pass

    def _menu_save_layout(self):
        """保存当前工作区位置：记录窗口几何信息但不触发 snap。"""
        self._save_window_geometry()
        self._flush_trainer_to_disk()

    def _menu_reset_layout(self):
        """重置工作区布局：清空保存的窗口位置并 snap 到默认左侧。"""
        clear_workspace_window("trainer")
        # 同步清除内存中的 window 数据
        trainer_data = self._workspace_data.get("trainer", {})
        if isinstance(trainer_data, dict):
            trainer_data.pop("window", None)
        if _SYS_COMPAT["is_win10_plus"]:
            hwnd = int(self.winId())
            _minimize_existing_windows()
            _double_snap(hwnd, "left")
            _force_activate(hwnd, self)

    def _menu_open_settings(self):
        """启动独立设置程序（子进程），同时控制训练器和导入器的主题。"""
        import subprocess

        # 单例：已有进程在跑则不重复打开
        existing = getattr(self, "_settings_process", None)
        if existing is not None and existing.poll() is None:
            return

        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "settings_dialog.py")
        try:
            proc = subprocess.Popen(
                [sys.executable, script_path, "--caller", "trainer", "--scale", str(self._scale)],
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
        # 写关闭和退出信号，让导入器检测到并退出
        self._write_closing_signal()
        self._write_quit_signal()
        self._cleanup_group_lock()

        # 从 config.json 读取最新的 train_mode 和 debug_mode
        # 避免保留旧的 --training-mode/--debug 命令行参数导致新配置不生效
        sm = SettingsManager()
        sm.reload()
        new_train_mode = sm.get("train_mode") or "normal"
        new_debug = bool(sm.get("debug_mode", False))

        # 重启时启动训练器主入口（不带 --left-half），让它重新启动训练器子进程和导入器子进程
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
        restart_argv = [sys.argv[0], "--restart"] + filtered
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

        # 同步全局样式表（缩放/边框/按钮等）到新主题
        self._reapply_stylesheet()

        # Windows 标题栏深浅模式
        apply_dwm_dark_mode(self, is_dark)

        # 同步训练器旗帜网格预览区主题（背景/边框/空状态文字由 paintEvent 绘制，与导入器一致）
        if getattr(self, "banner_grid_widget", None) is not None:
            self.banner_grid_widget.update()
        if getattr(self, "progress_detail", None) is not None:
            detail_color = "#aaaaaa" if is_dark else "#666666"
            s = self._scale
            detail_fs = max(int(12 * s), 10)
            self.progress_detail.setStyleSheet(f"font-size: {detail_fs}px; color: {detail_color};")
        # Tab2 占位文字深浅色适配
        ph_color = "#aaaaaa" if is_dark else "#666666"
        ph_fs = max(int(14 * self._scale), 12)
        for w in [getattr(self, "_tab2_thumb_label", None), getattr(self, "_tab2_banner_render_label", None)]:
            if w is not None and getattr(w, "property", None) and w.property("placeholderText"):
                w.setStyleSheet(f"color: {ph_color}; font-size: {ph_fs}px;")
        # Tab2 进度详情颜色
        if getattr(self, "_tab2_progress_detail", None) is not None:
            detail_color = "#aaaaaa" if is_dark else "#666666"
            s = self._scale
            detail_fs = max(int(12 * s), 10)
            self._tab2_progress_detail.setStyleSheet(f"font-size: {detail_fs}px; color: {detail_color};")
        if getattr(self, "banner_labels", None) is not None:
            for lbl in self.banner_labels:
                lbl.update()

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
        """自动保存：旗帜数据→training_datas/auto_save/trainer/，模型权重→models/auto_save/。

        仅在有文件时保存；自动保存文件夹总数不超过 10 个，超限删除最旧。
        """
        from datetime import datetime
        try:
            formats = SettingsManager().get("auto_save_formats", ["pth"])
        except Exception:
            formats = ["pth"]
        if not isinstance(formats, list):
            formats = ["pth"]
        # "all" 展开为全部格式
        if "all" in formats:
            formats = ["mbtl", "mbtlx", "pth"]
        # 仅在有文件时保存
        has_banners = bool(getattr(self, 'training_images', None))
        has_model = self.model is not None
        if not has_banners and not has_model:
            return
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        sm = SettingsManager()
        saved_names = []
        # 旗帜数据保存到 training_datas/auto_save/trainer/<日期>/
        if "mbtl" in formats and has_banners:
            try:
                from utils.mbtl_utils import write_mbtl
                data_base = resolve_app_path(sm.get("auto_save_trainer_path", "training_datas/auto_save/trainer"))
                data_dir = os.path.join(data_base, ts)
                os.makedirs(data_dir, exist_ok=True)
                mbtl_path = os.path.join(data_dir, "banner_auto.mbtl")
                raw_banners = [item['banner_data'] for item in self.training_images]
                write_mbtl(mbtl_path, raw_banners)
                saved_names.append(os.path.basename(mbtl_path))
                self._cleanup_auto_saves(data_base, max_count=10)
            except Exception:
                pass
        # 模型权重保存到 models/auto_save/<日期>/
        if "pth" in formats and has_model:
            try:
                import torch
                model_base = resolve_app_path(sm.get("auto_save_trainer_model_path", "models/auto_save"))
                model_dir = os.path.join(model_base, ts)
                os.makedirs(model_dir, exist_ok=True)
                model_path = os.path.join(model_dir, "banner_vit_model_auto.pth")
                torch.save(self.model.state_dict(), model_path)
                saved_names.append(os.path.basename(model_path))
                self._cleanup_auto_saves(model_base, max_count=10)
            except Exception:
                pass
        if saved_names:
            self._flash_reminder(f"已自动保存到 {ts}/\n" + "\n".join(saved_names))

    def _cleanup_auto_saves(self, base_dir, max_count=10):
        """自动保存日期文件夹总数超过 max_count 时，删除最旧的文件夹。"""
        import shutil
        try:
            folders = []
            for name in os.listdir(base_dir):
                full = os.path.join(base_dir, name)
                if os.path.isdir(full):
                    folders.append((full, os.path.getmtime(full)))
            folders.sort(key=lambda x: x[1])  # 按修改时间升序（最旧在前）
            while len(folders) > max_count:
                oldest = folders.pop(0)
                try:
                    shutil.rmtree(oldest[0])
                except Exception:
                    pass
        except Exception:
            pass

    def _check_auto_save_restore(self):
        """启动后检测自动保存文件夹是否有可恢复的文件。"""
        import json as _json
        sm = SettingsManager()
        files = []
        # 扫描旗帜数据自动保存 (training_datas/auto_save/trainer/)
        data_base = resolve_app_path(sm.get("auto_save_trainer_path", "training_datas/auto_save/trainer"))
        if os.path.isdir(data_base):
            for folder_name in os.listdir(data_base):
                folder_path = os.path.join(data_base, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                for name in sorted(os.listdir(folder_path)):
                    full = os.path.join(folder_path, name)
                    if not os.path.isfile(full):
                        continue
                    if name.endswith('.mbtl'):
                        files.append({"path": full, "label": f"[旗帜] {folder_name}/{name}", "_sort": folder_name})
                    elif name.endswith('.mbtlx'):
                        files.append({"path": full, "label": f"[旗帜X] {folder_name}/{name}", "_sort": folder_name})
        # 扫描模型权重自动保存 (models/auto_save/)
        model_base = resolve_app_path(sm.get("auto_save_trainer_model_path", "models/auto_save"))
        if os.path.isdir(model_base):
            for folder_name in os.listdir(model_base):
                folder_path = os.path.join(model_base, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                for name in sorted(os.listdir(folder_path)):
                    full = os.path.join(folder_path, name)
                    if not os.path.isfile(full):
                        continue
                    if name.endswith('.pth'):
                        files.append({"path": full, "label": f"[模型] {folder_name}/{name}", "_sort": folder_name})
        if not files:
            return
        # 按日期降序排列（最新在前）
        files.sort(key=lambda x: x.get("_sort", ""), reverse=True)
        for f in files:
            f.pop("_sort", None)
        # 写入恢复信息文件
        import tempfile
        info_file = os.path.join(tempfile.gettempdir(), f"restore_info_{os.getpid()}.txt")
        try:
            with open(info_file, "w", encoding="utf-8") as f:
                _json.dump({"files": files}, f, ensure_ascii=False)
        except Exception:
            return
        # 启动 exit.pyw restore 模式
        exit_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "exit.pyw")
        session_dir = self._session_dir or tempfile.gettempdir()
        try:
            self._restore_process = subprocess.Popen(
                [sys.executable, exit_path, "restore", "训练器", session_dir, info_file],
            )
        except Exception:
            return
        from PyQt5.QtCore import QTimer
        self._restore_timer = QTimer(self)
        self._restore_timer.timeout.connect(self._check_restore_result)
        self._restore_timer.start(100)

    def _check_restore_result(self):
        """定时器回调：检查 exit.pyw restore 模式的信号。"""
        import tempfile
        session_dir = self._session_dir or tempfile.gettempdir()
        confirmed_file = os.path.join(session_dir, ".restore_confirmed")
        cancelled_file = os.path.join(session_dir, ".restore_cancelled")

        if os.path.exists(confirmed_file):
            file_paths = []
            try:
                with open(confirmed_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content.startswith("file="):
                        file_paths = content[5:].split("|")
            except Exception:
                pass
            try:
                os.remove(confirmed_file)
            except Exception:
                pass
            self._restore_timer.stop()
            self._restore_timer = None
            self._restore_process = None
            # 加载选中的文件
            for fp in file_paths:
                if not fp:
                    continue
                try:
                    if fp.endswith('.pth'):
                        import torch
                        self.model.load_state_dict(torch.load(fp, map_location='cpu'))
                        self._flash_reminder(f"已恢复模型\n{os.path.basename(fp)}")
                    elif fp.endswith('.mbtl'):
                        from utils.mbtl_utils import read_mbtl
                        banners = read_mbtl(fp)
                        self.training_images = [{"banner_data": b} for b in banners]
                        self._update_training_view()
                        self._flash_reminder(f"已恢复旗帜数据\n{os.path.basename(fp)}")
                except Exception:
                    pass
        elif os.path.exists(cancelled_file):
            try:
                os.remove(cancelled_file)
            except Exception:
                pass
            self._restore_timer.stop()
            self._restore_timer = None
            self._restore_process = None

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

    def _update_training_view(self):
        has_data = bool(getattr(self, 'training_images', None))
        if has_data:
            self.banner_grid_widget.setInfoText("")
        else:
            self.banner_grid_widget.setInfoText("训练你的第一幅旗帜")
        self.page_nav_widget.setVisible(has_data)

    def init_ui(self):
        main_widget = QWidget()

        self.model_group = QGroupBox("模型设置")
        self.model_group.setStyleSheet("QGroupBox { padding-top: 16px; }")
        self.model_group.setMinimumWidth(0)
        model_layout = QGridLayout()
        model_layout.setSpacing(4)

        model_layout.addWidget(QLabel("训练轮数:"), 0, 0)
        self.epoch_spin = QSpinBox()
        self.epoch_spin.setRange(1, 100)
        self.epoch_spin.setValue(10)
        model_layout.addWidget(self.epoch_spin, 0, 1)

        model_layout.addWidget(QLabel("批次大小:"), 1, 0)
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 32)
        self.batch_spin.setValue(8)
        model_layout.addWidget(self.batch_spin, 1, 1)

        model_layout.addWidget(QLabel("学习率:"), 2, 0)
        self.lr_combo = QComboBox()
        self.lr_combo.addItems(["0.001", "0.0001", "0.00001"])
        self.lr_combo.setCurrentIndex(1)
        model_layout.addWidget(self.lr_combo, 2, 1)

        self.train_button = QPushButton("导入 .mbtl")
        self.train_button.clicked.connect(self.import_banner)
        self.train_button.setEnabled(True)
        model_layout.addWidget(self.train_button, 3, 0, 1, 2)

        self.clear_seq_button = QPushButton("清空序列")
        self.clear_seq_button.clicked.connect(self.clear_sequence)
        self.clear_seq_button.setEnabled(True)
        model_layout.addWidget(self.clear_seq_button, 4, 0, 1, 2)

        self.stop_button = QPushButton("停止训练")
        self.stop_button.clicked.connect(self.stop_training)
        self.stop_button.setEnabled(False)
        model_layout.addWidget(self.stop_button, 5, 0, 1, 2)

        self.save_button = QPushButton("保存模型")
        self.save_button.clicked.connect(self.save_model)
        self.save_button.setEnabled(False)  # 初始无模型时禁用
        model_layout.addWidget(self.save_button, 6, 0)

        self.load_button = QPushButton("继续训练")
        self.load_button.clicked.connect(self.load_model)
        model_layout.addWidget(self.load_button, 6, 1)

        self.loss_chart_button = QPushButton("查看Loss")
        self.loss_chart_button.clicked.connect(self._show_loss_chart)
        self.loss_chart_button.setEnabled(False)
        model_layout.addWidget(self.loss_chart_button, 7, 0, 1, 2)

        self.model_group.setLayout(model_layout)

        self.status_group = QGroupBox("总进度")
        self.status_group.setStyleSheet("QGroupBox { padding-top: 16px; }")
        self.status_group.setMinimumWidth(0)
        status_layout = QVBoxLayout()
        status_layout.setSpacing(2)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(max(int(20 * self._scale), 18))
        self.progress_bar.setMinimumWidth(0)
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        status_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("就绪")
        s = self._scale
        self.status_label.setStyleSheet(f"font-size: {max(int(12 * s), 10)}px;")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(0)
        status_layout.addWidget(self.status_label)

        self.progress_detail = QLabel("")
        self.progress_detail.setStyleSheet(f"color: #666; font-size: {max(int(12 * self._scale), 10)}px;")
        self.progress_detail.setWordWrap(True)
        self.progress_detail.setMinimumWidth(0)
        status_layout.addWidget(self.progress_detail)

        self.status_group.setLayout(status_layout)

        self.training_group = QGroupBox("当前训练中旗帜")
        self.training_group.setStyleSheet("QGroupBox { padding-top: 20px; }")
        self.training_group.setMinimumWidth(0)
        group_layout = QVBoxLayout()
        group_layout.setContentsMargins(4, 4, 4, 4)

        self.banner_grid_widget = BannerGridWidget()
        self.banner_grid_widget._scale = self._scale
        for bl in self.banner_grid_widget.banner_labels:
            bl._scale = self._scale
        self.banner_labels = self.banner_grid_widget.banner_labels
        group_layout.addWidget(self.banner_grid_widget, 1)

        self.training_group.setLayout(group_layout)

        self.page_nav_widget = QWidget()
        page_nav = QHBoxLayout(self.page_nav_widget)
        page_nav.setContentsMargins(0, 0, 0, 0)
        self.prev_page_btn = QPushButton("◀ 上一页")
        self.prev_page_btn.clicked.connect(self._prev_page)
        self.prev_page_btn.setEnabled(False)
        page_nav.addWidget(self.prev_page_btn)

        self.page_info_label = QLabel("")
        self.page_info_label.setAlignment(Qt.AlignCenter)
        page_nav.addWidget(self.page_info_label)

        self.next_page_btn = QPushButton("下一页 ▶")
        self.next_page_btn.clicked.connect(self._next_page)
        self.next_page_btn.setEnabled(False)
        page_nav.addWidget(self.next_page_btn)

        group_layout.addWidget(self.page_nav_widget)

        self.seq_group = QGroupBox("序列列表")
        self.seq_group.setStyleSheet("QGroupBox { padding-top: 16px; }")
        self.seq_group.setMinimumWidth(0)
        seq_layout = QVBoxLayout()

        self.seq_list = QListWidget()
        self.seq_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.seq_list.currentRowChanged.connect(self.on_seq_selection_changed)
        seq_layout.addWidget(self.seq_list)
        self.seq_group.setLayout(seq_layout)

        self.elem_group = QGroupBox("当前旗帜图案组成")
        self.elem_group.setMinimumWidth(0)
        self.elem_group.setStyleSheet("QGroupBox { padding-top: 16px; }")
        elem_layout = QVBoxLayout()

        self.elem_list = QListWidget()
        elem_layout.addWidget(self.elem_list)
        self.elem_group.setLayout(elem_layout)

        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(0)

        self._create_menu_bar()

        self._left_widget = QWidget()
        self._left_widget.setMinimumWidth(0)
        left_inner = QVBoxLayout(self._left_widget)
        left_inner.setContentsMargins(0, 0, 0, 0)
        left_inner.setSpacing(2)
        left_inner.addWidget(self.model_group)
        left_inner.addWidget(self.status_group)

        self._main_splitter = QSplitter(Qt.Horizontal)
        self._main_splitter.setChildrenCollapsible(False)
        self._main_splitter.setHandleWidth(6)
        self._right_splitter = QSplitter(Qt.Vertical)
        self._right_splitter.setChildrenCollapsible(False)
        self._right_splitter.setHandleWidth(6)
        self._content_splitter = QSplitter(Qt.Vertical)
        self._content_splitter.setChildrenCollapsible(False)
        self._content_splitter.setHandleWidth(6)
        self._list_splitter = QSplitter(Qt.Horizontal)
        self._list_splitter.setChildrenCollapsible(False)
        self._list_splitter.setHandleWidth(6)
        self._main_splitter.splitterMoved.connect(self._on_main_splitter_moved)
        self._right_splitter.splitterMoved.connect(self._on_right_v_splitter_moved)
        self._content_splitter.splitterMoved.connect(self._on_content_v_splitter_moved)
        self._list_splitter.splitterMoved.connect(self._on_list_splitter_moved)

        # Tab 容器：序列训练（当前训练窗口）+ 序列图组训练（占位）
        self._training_tabs = QTabWidget()
        self._training_tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._tab1_widget = QWidget()
        self._tab1_widget.setMinimumWidth(0)
        self._tab1_layout = QVBoxLayout(self._tab1_widget)
        self._tab1_layout.setContentsMargins(0, 0, 0, 0)
        self._tab1_layout.setSpacing(0)
        self._tab1_layout.addWidget(self._main_splitter)
        self._training_tabs.addTab(self._tab1_widget, "序列训练")

        self._tab2_widget = QWidget()
        self._tab2_widget.setMinimumWidth(0)

        # ===== Tab2 模型设置组（对应 Tab1 model_group）=====
        self._tab2_model_group = QGroupBox("模型设置")
        self._tab2_model_group.setStyleSheet("QGroupBox { padding-top: 16px; }")
        self._tab2_model_group.setMinimumWidth(0)
        tab2_model_grid = QGridLayout()
        tab2_model_grid.setSpacing(4)

        # 继承 Tab1 参数复选框
        self._tab2_inherit_check = QCheckBox("继承 Tab1 参数")
        self._tab2_inherit_check.setChecked(True)
        self._tab2_inherit_check.toggled.connect(self._tab2_on_inherit_toggled)
        tab2_model_grid.addWidget(self._tab2_inherit_check, 0, 0, 1, 2)

        tab2_model_grid.addWidget(QLabel("训练轮数:"), 1, 0)
        self._tab2_epoch_spin = QSpinBox()
        self._tab2_epoch_spin.setRange(1, 100)
        self._tab2_epoch_spin.setValue(10)
        self._tab2_epoch_spin.setEnabled(False)
        tab2_model_grid.addWidget(self._tab2_epoch_spin, 1, 1)

        tab2_model_grid.addWidget(QLabel("批次大小:"), 2, 0)
        self._tab2_batch_spin = QSpinBox()
        self._tab2_batch_spin.setRange(1, 32)
        self._tab2_batch_spin.setValue(8)
        self._tab2_batch_spin.setEnabled(False)
        tab2_model_grid.addWidget(self._tab2_batch_spin, 2, 1)

        tab2_model_grid.addWidget(QLabel("学习率:"), 3, 0)
        self._tab2_lr_combo = QComboBox()
        self._tab2_lr_combo.addItems(["0.001", "0.0001", "0.00001"])
        self._tab2_lr_combo.setCurrentIndex(1)
        self._tab2_lr_combo.setEnabled(False)
        tab2_model_grid.addWidget(self._tab2_lr_combo, 3, 1)

        self._tab2_import_button = QPushButton("导入 .mbtlx")
        self._tab2_import_button.clicked.connect(self._tab2_import_mbtlx)
        tab2_model_grid.addWidget(self._tab2_import_button, 4, 0, 1, 2)

        self._tab2_clear_button = QPushButton("清空数据")
        self._tab2_clear_button.clicked.connect(self._tab2_clear_data)
        tab2_model_grid.addWidget(self._tab2_clear_button, 5, 0, 1, 2)

        self._tab2_train_button = QPushButton("开始训练")
        self._tab2_train_button.clicked.connect(self._tab2_start_training)
        tab2_model_grid.addWidget(self._tab2_train_button, 6, 0, 1, 2)

        self._tab2_stop_button = QPushButton("停止训练")
        self._tab2_stop_button.setEnabled(False)
        self._tab2_stop_button.clicked.connect(self._tab2_stop_training)
        tab2_model_grid.addWidget(self._tab2_stop_button, 7, 0, 1, 2)

        self._tab2_save_button = QPushButton("保存模型")
        self._tab2_save_button.setEnabled(False)
        self._tab2_save_button.clicked.connect(self._tab2_save_model)
        tab2_model_grid.addWidget(self._tab2_save_button, 8, 0)

        self._tab2_load_button = QPushButton("继续训练")
        self._tab2_load_button.clicked.connect(self._tab2_load_model)
        tab2_model_grid.addWidget(self._tab2_load_button, 8, 1)

        self._tab2_model_group.setLayout(tab2_model_grid)

        # ===== Tab2 总进度组（对应 Tab1 status_group）=====
        self._tab2_status_group = QGroupBox("总进度")
        self._tab2_status_group.setStyleSheet("QGroupBox { padding-top: 16px; }")
        self._tab2_status_group.setMinimumWidth(0)
        tab2_status_layout = QVBoxLayout()
        tab2_status_layout.setSpacing(2)

        self._tab2_progress_bar = QProgressBar()
        self._tab2_progress_bar.setValue(0)
        self._tab2_progress_bar.setFixedHeight(max(int(20 * self._scale), 18))
        self._tab2_progress_bar.setMinimumWidth(0)
        self._tab2_progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tab2_status_layout.addWidget(self._tab2_progress_bar)

        self._tab2_status_label = QLabel("就绪")
        self._tab2_status_label.setWordWrap(True)
        self._tab2_status_label.setMinimumWidth(0)
        tab2_status_layout.addWidget(self._tab2_status_label)

        self._tab2_progress_detail = QLabel("")
        self._tab2_progress_detail.setWordWrap(True)
        self._tab2_progress_detail.setMinimumWidth(0)
        tab2_status_layout.addWidget(self._tab2_progress_detail)

        self._tab2_status_group.setLayout(tab2_status_layout)

        # ===== Tab2 左侧面板（对应 Tab1 _left_widget）=====
        self._tab2_left_widget = QWidget()
        self._tab2_left_widget.setMinimumWidth(0)
        tab2_left_inner = QVBoxLayout(self._tab2_left_widget)
        tab2_left_inner.setContentsMargins(0, 0, 0, 0)
        tab2_left_inner.setSpacing(2)
        tab2_left_inner.addWidget(self._tab2_model_group)
        tab2_left_inner.addWidget(self._tab2_status_group)

        # ===== Tab2 当前训练中图片（对应 Tab1 training_group）=====
        self._tab2_training_group = QGroupBox("当前训练中图片")
        self._tab2_training_group.setStyleSheet("QGroupBox { padding-top: 20px; }")
        self._tab2_training_group.setMinimumWidth(0)
        tab2_train_layout = QVBoxLayout()
        tab2_train_layout.setContentsMargins(4, 4, 4, 4)

        # 并排显示：上传识别图 + 旗帜渲染图
        tab2_preview_row = QHBoxLayout()
        tab2_preview_row.setSpacing(4)

        # 上传识别图
        tab2_img_col = QVBoxLayout()
        tab2_img_col.setSpacing(0)
        tab2_img_title = QLabel("上传识别图")
        tab2_img_title.setAlignment(Qt.AlignCenter)
        tab2_img_col.addWidget(tab2_img_title)
        self._tab2_thumb_label = QLabel("（暂无训练图片）")
        self._tab2_thumb_label.setAlignment(Qt.AlignCenter)
        self._tab2_thumb_label.setProperty("placeholderText", True)
        self._tab2_thumb_label.setMinimumHeight(120)
        tab2_img_col.addWidget(self._tab2_thumb_label, 1)
        tab2_preview_row.addLayout(tab2_img_col, 1)

        # 旗帜渲染图
        tab2_render_col = QVBoxLayout()
        tab2_render_col.setSpacing(0)
        tab2_render_title = QLabel("旗帜渲染图")
        tab2_render_title.setAlignment(Qt.AlignCenter)
        tab2_render_col.addWidget(tab2_render_title)
        self._tab2_banner_render_label = QLabel("（未选择）")
        self._tab2_banner_render_label.setAlignment(Qt.AlignCenter)
        self._tab2_banner_render_label.setProperty("placeholderText", True)
        self._tab2_banner_render_label.setMinimumHeight(120)
        tab2_render_col.addWidget(self._tab2_banner_render_label, 1)
        tab2_preview_row.addLayout(tab2_render_col, 1)

        tab2_train_layout.addLayout(tab2_preview_row, 1)

        self._tab2_training_group.setLayout(tab2_train_layout)

        # ===== Tab2 数据列表组（对应 Tab1 seq_group）=====
        self._tab2_seq_group = QGroupBox("数据列表")
        self._tab2_seq_group.setStyleSheet("QGroupBox { padding-top: 16px; }")
        self._tab2_seq_group.setMinimumWidth(0)
        tab2_seq_layout = QVBoxLayout()

        self._tab2_data_info = QLabel("未导入数据")
        self._tab2_data_info.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tab2_seq_layout.addWidget(self._tab2_data_info)

        self._tab2_data_list = QListWidget()
        self._tab2_data_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._tab2_data_list.currentRowChanged.connect(self._tab2_on_data_selection)
        tab2_seq_layout.addWidget(self._tab2_data_list, 1)

        self._tab2_seq_group.setLayout(tab2_seq_layout)

        # ===== Tab2 当前旗帜图案组成（对应 Tab1 elem_group）=====
        self._tab2_elem_group = QGroupBox("当前旗帜图案组成")
        self._tab2_elem_group.setStyleSheet("QGroupBox { padding-top: 16px; }")
        self._tab2_elem_group.setMinimumWidth(0)
        tab2_elem_layout = QVBoxLayout()

        self._tab2_elem_list = QListWidget()
        tab2_elem_layout.addWidget(self._tab2_elem_list)

        self._tab2_elem_group.setLayout(tab2_elem_layout)

        # ===== Tab2 splitters =====
        self._tab2_main_splitter = QSplitter(Qt.Horizontal)
        self._tab2_main_splitter.setChildrenCollapsible(False)
        self._tab2_main_splitter.setHandleWidth(6)
        self._tab2_right_splitter = QSplitter(Qt.Vertical)
        self._tab2_right_splitter.setChildrenCollapsible(False)
        self._tab2_right_splitter.setHandleWidth(6)
        self._tab2_content_splitter = QSplitter(Qt.Vertical)
        self._tab2_content_splitter.setChildrenCollapsible(False)
        self._tab2_content_splitter.setHandleWidth(6)
        self._tab2_list_splitter = QSplitter(Qt.Horizontal)
        self._tab2_list_splitter.setChildrenCollapsible(False)
        self._tab2_list_splitter.setHandleWidth(6)
        self._tab2_main_splitter.splitterMoved.connect(self._tab2_on_main_splitter_moved)
        self._tab2_right_splitter.splitterMoved.connect(self._tab2_on_right_v_splitter_moved)
        self._tab2_content_splitter.splitterMoved.connect(self._tab2_on_content_v_splitter_moved)
        self._tab2_list_splitter.splitterMoved.connect(self._tab2_on_list_splitter_moved)

        # ===== Tab2 layout =====
        self._tab2_layout = QVBoxLayout(self._tab2_widget)
        self._tab2_layout.setContentsMargins(0, 0, 0, 0)
        self._tab2_layout.setSpacing(0)
        # 初始用 wide 布局
        self._tab2_layout.addWidget(self._tab2_main_splitter)

        self._training_tabs.addTab(self._tab2_widget, "序列图组训练")

        self._training_tabs.currentChanged.connect(self._on_training_tab_changed)
        self._prev_training_tab = 0

        self.main_layout.addWidget(self._training_tabs)

        main_widget.setLayout(self.main_layout)
        self.setCentralWidget(main_widget)

        self.apply_wide_layout()
        self._update_training_view()
        QTimer.singleShot(50, self._apply_layout)

    def _session_file(self, name):
        if self._session_dir:
            return os.path.join(self._session_dir, name)
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)

    def _start_watchers(self):
        self._watcher_timer = QTimer()
        self._watcher_timer.timeout.connect(self._check_signals)
        self._watcher_timer.start(100)

    def _check_signals(self):
        self._check_importer_export()
        self._check_importer_quit()
        self._check_importer_closing()

    def _check_importer_closing(self):
        if self._session_dir:
            signal_file = os.path.join(self._session_dir, ".importer_closing")
            if os.path.exists(signal_file):
                self._close_blocked = True
            else:
                if self._close_blocked:
                    self._close_blocked = False

    def _write_closing_signal(self):
        if self._session_dir:
            signal_file = os.path.join(self._session_dir, ".trainer_closing")
            try:
                with open(signal_file, "w") as f:
                    f.write("closing")
            except Exception:
                pass

    def _remove_closing_signal(self):
        if self._session_dir:
            signal_file = os.path.join(self._session_dir, ".trainer_closing")
            try:
                if os.path.exists(signal_file):
                    os.remove(signal_file)
            except Exception:
                pass

    def _check_other_closing(self):
        if self._session_dir:
            signal_file = os.path.join(self._session_dir, ".importer_closing")
            return os.path.exists(signal_file)
        return False

    def _check_importer_export(self):
        signal_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".importer_export")
        if not os.path.exists(signal_file):
            return
        try:
            with open(signal_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            os.remove(signal_file)
            if content:
                self.train_button.setEnabled(False)
                self.status_label.setText("正在从导入器接收旗帜数据...")
                QApplication.processEvents()
                banners = self._parse_banner_content(content)
                if banners:
                    self._setup_dataloader(banners)
                    self.status_label.setText(f"成功加载 {len(banners)} 个旗帜数据")
                else:
                    QMessageBox.warning(self, "警告", "没有加载到有效的旗帜数据")
                    self.train_button.setEnabled(True)
            else:
                pass
        except Exception as e:
            print(f"导入数据失败: {e}")
            import traceback
            traceback.print_exc()

    def _check_importer_quit(self):
        signal_file = self._session_file(".importer_quit")
        if os.path.exists(signal_file):
            try:
                os.remove(signal_file)
            except Exception:
                pass
            self._close_blocked = False
            self._force_quit = True
            # 若 exit.pyw 在运行，先终止子进程及其定时器
            if self._exit_process is not None:
                try:
                    self._exit_process.terminate()
                except Exception:
                    pass
                self._exit_process = None
            if self._exit_timer is not None:
                try:
                    self._exit_timer.stop()
                except Exception:
                    pass
                self._exit_timer = None
            self.close()

    def _write_quit_signal(self):
        if self._session_dir:
            signal_file = os.path.join(self._session_dir, ".trainer_quit")
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

    def _total_pages(self):
        if not self.training_images:
            return 1
        return max(1, (len(self.training_images) + self._page_size - 1) // self._page_size)

    def _update_page_info(self):
        total = self._total_pages()
        self.page_info_label.setText(f"第 {self._current_page + 1} / {total} 页")
        self.prev_page_btn.setEnabled(self._current_page > 0)
        self.next_page_btn.setEnabled(self._current_page < total - 1)

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self.update_training_banners()

    def _next_page(self):
        if self._current_page < self._total_pages() - 1:
            self._current_page += 1
            self.update_training_banners()

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

    def _on_training_tab_changed(self, index):
        """Tab 切换时：训练中需确认停止；保存旧Tab布局、恢复新Tab布局。"""
        if index == self._prev_training_tab:
            return
        # 训练中切换Tab：弹出确认
        if getattr(self, "_is_training", False):
            reply = QMessageBox.question(
                self, "训练进行中",
                "训练正在进行中，切换标签页将停止训练。\n是否停止训练并切换？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                # 取消切换：回到原来的Tab
                self._training_tabs.blockSignals(True)
                self._training_tabs.setCurrentIndex(self._prev_training_tab)
                self._training_tabs.blockSignals(False)
                return
            # 停止训练（不弹第二次确认框）
            if hasattr(self, 'training_thread') and self.training_thread.isRunning():
                self.training_thread.terminate()
                if not self.training_thread.wait(5000):
                    print("训练线程停止超时")
                del self.training_thread
            self._is_training = False
            self._banner_queue.clear()
            self._animating_banner = -1
            self.status_label.setText("训练已停止")
            self.progress_detail.setText("")
            self.train_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            if hasattr(self, 'banner_labels'):
                for label in self.banner_labels:
                    label.set_progress(0, show=False)
            self._update_button_states()
        # 保存旧Tab布局到工作区并刷写磁盘
        if self._prev_training_tab == 0:
            self._save_trainer_to_workspace(tab_index=self._prev_training_tab)
            self._flush_trainer_to_disk()
        elif self._prev_training_tab == 1:
            self._save_trainer_to_workspace(tab_index=self._prev_training_tab)
            self._flush_trainer_to_disk()
        self._prev_training_tab = index
        # 恢复新Tab布局
        if index == 0:
            # 切回 Tab1：延迟到 Qt 完成布局后再强制约束
            # 使用重试机制确保 splitter 获得实际尺寸后再约束
            def _retry_enforce(attempt=0):
                self._apply_layout()
                # 检查 splitter 是否已获得实际尺寸
                if self.current_display_mode == "narrow":
                    has_size = self._content_splitter.height() > 0
                elif self.current_display_mode == "ultra_wide":
                    has_size = self._main_splitter.width() > 0
                else:
                    has_size = self._main_splitter.width() > 0
                self._enforce_splitter_bounds()
                if has_size:
                    self._restore_trainer_or_default()
                elif attempt < 5:
                    # splitter 尺寸仍为0，延迟重试
                    QTimer.singleShot(30, lambda: _retry_enforce(attempt + 1))
                else:
                    # 超过重试次数，直接恢复
                    self._restore_trainer_or_default()
            QTimer.singleShot(0, _retry_enforce)
        elif index == 1:
            # 切到 Tab2：应用布局并约束 splitter
            def _retry_enforce_tab2(attempt=0):
                self._apply_layout()
                self._tab2_enforce_splitter_bounds()
                if attempt < 5:
                    QTimer.singleShot(30, lambda: _retry_enforce_tab2(attempt + 1))
            QTimer.singleShot(0, _retry_enforce_tab2)

    def _apply_layout(self):
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return
        if self._layout_applying:
            return
        target = "narrow" if w / h < 1.0 else ("ultra_wide" if w / h > 33 / 9 else "wide")

        # Tab2：独立应用布局
        if self._training_tabs.currentIndex() == 1:
            # 检查 Tab2 splitter 是否需要重新应用布局（首次切换或模式不匹配）
            _expected_counts = {"narrow": 2, "wide": 3, "ultra_wide": 4}
            _tab2_count = self._tab2_main_splitter.count()
            _tab2_needs_layout = (
                _tab2_count == 0
                or _tab2_count != _expected_counts.get(target, 0)
                or target != self.current_display_mode
            )
            if _tab2_needs_layout:
                self._layout_applying = True
                self.setUpdatesEnabled(False)
                self.current_display_mode = target
                try:
                    if target == "narrow":
                        self._tab2_apply_narrow_layout()
                    elif target == "ultra_wide":
                        self._tab2_apply_ultra_wide_layout()
                    else:
                        self._tab2_apply_wide_layout()
                finally:
                    self.setUpdatesEnabled(True)
                    self._layout_applying = False
            else:
                self._tab2_enforce_splitter_bounds()
            return

        # Tab1：原有逻辑
        if target != self.current_display_mode:
            self._layout_applying = True
            self.setUpdatesEnabled(False)
            self.current_display_mode = target
            try:
                if target == "narrow":
                    self.apply_narrow_layout()
                elif target == "ultra_wide":
                    self.apply_ultra_wide_layout()
                else:
                    self.apply_wide_layout()
            finally:
                self.setUpdatesEnabled(True)
                self._layout_applying = False
        else:
            # 模式未变但窗口尺寸变了（或 Tab 切回后需重新约束）：强制 splitter 约束
            self._enforce_splitter_bounds()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_layout()

    def showEvent(self, event):
        super().showEvent(event)

    def apply_ultra_wide_layout(self):
        """超宽模式：4个工作区水平并列。"""
        # 4个工作区直接添加到 main_splitter（addWidget 自动 reparent）
        self._main_splitter.addWidget(self._left_widget)
        self._main_splitter.addWidget(self.training_group)
        self._main_splitter.addWidget(self.seq_group)
        self._main_splitter.addWidget(self.elem_group)

        # 不使用 right_splitter, list_splitter, content_splitter
        self._right_splitter.setParent(None)
        self._list_splitter.setParent(None)
        self._content_splitter.setParent(None)

        if self._tab1_layout.indexOf(self._content_splitter) >= 0:
            self._tab1_layout.removeWidget(self._content_splitter)
        if self._tab1_layout.indexOf(self._main_splitter) < 0:
            self._tab1_layout.addWidget(self._main_splitter)

        for i in range(4):
            self._main_splitter.setStretchFactor(i, 1)

        w = self.width()
        if w > 0:
            q = w // 4
            self._main_splitter.setSizes([q, q, q, w - 3 * q])

        self.current_display_mode = "ultra_wide"
        self._enforce_splitter_bounds()
        QTimer.singleShot(0, self._restore_trainer_or_default)

    def apply_wide_layout(self):
        self._right_splitter.addWidget(self.seq_group)
        self._right_splitter.addWidget(self.elem_group)

        self._main_splitter.addWidget(self._left_widget)
        self._main_splitter.addWidget(self.training_group)
        self._main_splitter.addWidget(self._right_splitter)

        self._list_splitter.setParent(None)
        self._content_splitter.setParent(None)

        if self._tab1_layout.indexOf(self._main_splitter) < 0:
            self._tab1_layout.addWidget(self._main_splitter)

        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 2)
        self._main_splitter.setStretchFactor(2, 1)
        self._right_splitter.setStretchFactor(0, 1)
        self._right_splitter.setStretchFactor(1, 1)

        w = self.width()
        h = self.height()
        if w > 0:
            self._main_splitter.setSizes([int(w / 4), int(w / 2), int(w / 4)])
        if h > 0:
            self._right_splitter.setSizes([int(h / 2), int(h / 2)])

        self.current_display_mode = "wide"
        self._enforce_splitter_bounds()
        # 优先从工作区文件恢复 splitter 位置
        QTimer.singleShot(0, self._restore_trainer_or_default)

    def apply_narrow_layout(self):
        self._list_splitter.addWidget(self.seq_group)
        self._list_splitter.addWidget(self.elem_group)

        self._main_splitter.addWidget(self._left_widget)
        self._main_splitter.addWidget(self.training_group)
        self._right_splitter.setParent(None)

        self._content_splitter.addWidget(self._main_splitter)
        self._content_splitter.addWidget(self._list_splitter)

        if self._tab1_layout.indexOf(self._main_splitter) >= 0:
            self._tab1_layout.removeWidget(self._main_splitter)
        if self._tab1_layout.indexOf(self._content_splitter) < 0:
            self._tab1_layout.addWidget(self._content_splitter)

        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 2)
        self._list_splitter.setStretchFactor(0, 1)
        self._list_splitter.setStretchFactor(1, 2)
        self._content_splitter.setStretchFactor(0, 2)
        self._content_splitter.setStretchFactor(1, 1)

        w = self.width()
        h = self.height()
        if w > 0:
            self._main_splitter.setSizes([int(w / 3), int(w * 2 / 3)])
            self._list_splitter.setSizes([int(w / 3), int(w * 2 / 3)])
        if h > 0:
            self._content_splitter.setSizes([int(h * 2 / 3), int(h / 3)])

        self.current_display_mode = "narrow"
        self._enforce_splitter_bounds()
        # 优先从工作区文件恢复 splitter 位置
        QTimer.singleShot(0, self._restore_trainer_or_default)

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

    def _on_main_splitter_moved(self, pos, index):
        if self._splitter_adjusting or self._layout_applying:
            return
        if self.current_display_mode == "narrow":
            if self._snap_to_other(self._main_splitter, self._list_splitter):
                self._save_trainer_to_workspace()
                return
        self._enforce_splitter_bounds()
        self._save_trainer_to_workspace()

    def _on_right_v_splitter_moved(self, pos, index):
        if self._splitter_adjusting or self._layout_applying:
            return
        self._enforce_splitter_bounds()
        self._save_trainer_to_workspace()

    def _on_content_v_splitter_moved(self, pos, index):
        if self._splitter_adjusting or self._layout_applying:
            return
        self._enforce_splitter_bounds()
        self._save_trainer_to_workspace()

    def _on_list_splitter_moved(self, pos, index):
        if self._splitter_adjusting or self._layout_applying:
            return
        if self.current_display_mode == "narrow":
            if self._snap_to_other(self._list_splitter, self._main_splitter):
                self._save_trainer_to_workspace()
                return
        self._enforce_splitter_bounds()
        self._save_trainer_to_workspace()

    def _tab2_on_main_splitter_moved(self, pos, index):
        if self._splitter_adjusting or self._layout_applying:
            return
        if self.current_display_mode == "narrow":
            if self._snap_to_other(self._tab2_main_splitter, self._tab2_list_splitter):
                self._save_trainer_to_workspace()
                return
        self._tab2_enforce_splitter_bounds()
        self._save_trainer_to_workspace()

    def _tab2_on_right_v_splitter_moved(self, pos, index):
        if self._splitter_adjusting or self._layout_applying:
            return
        self._tab2_enforce_splitter_bounds()
        self._save_trainer_to_workspace()

    def _tab2_on_content_v_splitter_moved(self, pos, index):
        if self._splitter_adjusting or self._layout_applying:
            return
        self._tab2_enforce_splitter_bounds()
        self._save_trainer_to_workspace()

    def _tab2_on_list_splitter_moved(self, pos, index):
        if self._splitter_adjusting or self._layout_applying:
            return
        if self.current_display_mode == "narrow":
            if self._snap_to_other(self._tab2_list_splitter, self._tab2_main_splitter):
                self._save_trainer_to_workspace()
                return
        self._tab2_enforce_splitter_bounds()
        self._save_trainer_to_workspace()

    # ===== 工作区布局持久化 =====

    def _capture_trainer_sizes(self):
        """捕获当前训练器 splitter sizes，返回 dict。"""
        data = {"main": list(self._main_splitter.sizes())}
        if self.current_display_mode == "wide":
            if self._right_splitter.count() > 0:
                data["right"] = list(self._right_splitter.sizes())
        elif self.current_display_mode == "narrow":
            if self._list_splitter.count() > 0:
                data["list"] = list(self._list_splitter.sizes())
            if self._content_splitter.count() > 0:
                data["content"] = list(self._content_splitter.sizes())
        return data

    def _apply_trainer_sizes(self, sizes_dict):
        """从 dict 恢复训练器 splitter 位置。"""
        if not isinstance(sizes_dict, dict):
            return False
        try:
            applied = False
            main = sizes_dict.get("main", [])
            if len(main) == self._main_splitter.count() and sum(main) > 0:
                self._main_splitter.setSizes(main)
                applied = True
            if self.current_display_mode == "wide":
                right = sizes_dict.get("right", [])
                if self._right_splitter.count() > 0 and len(right) == self._right_splitter.count() and sum(right) > 0:
                    self._right_splitter.setSizes(right)
                    applied = True
            elif self.current_display_mode == "narrow":
                lst = sizes_dict.get("list", [])
                if self._list_splitter.count() > 0 and len(lst) == self._list_splitter.count() and sum(lst) > 0:
                    self._list_splitter.setSizes(lst)
                    applied = True
                content = sizes_dict.get("content", [])
                if self._content_splitter.count() > 0 and len(content) == self._content_splitter.count() and sum(content) > 0:
                    self._content_splitter.setSizes(content)
                    applied = True
            return applied
        except Exception:
            return False

    def _save_trainer_to_workspace(self, tab_index=None):
        """保存训练器 splitter 位置到工作区内存（区分Tab）。

        Args:
            tab_index: 指定Tab索引（Tab切换时传旧Tab索引）；None则用当前Tab。
        """
        if self.current_display_mode:
            if tab_index is None:
                tab_index = self._training_tabs.currentIndex()
            tab_name = f"tab{tab_index + 1}"
            self._workspace_data.setdefault("trainer", {}).setdefault(self.current_display_mode, {})
            self._workspace_data["trainer"][self.current_display_mode][tab_name] = self._capture_trainer_sizes()
            # Tab2 保存
            if tab_index is None or tab_index == 1:
                if hasattr(self, '_tab2_main_splitter'):
                    self._workspace_data["trainer"][self.current_display_mode]["tab2"] = self._tab2_capture_sizes()

    def _flush_trainer_to_disk(self):
        """把训练器工作区数据原子写入文件。
        只写 trainer 自己的 window 和各布局 splitter 数据，不整体覆写。"""
        trainer_data = self._workspace_data.get("trainer", {})
        # 保存窗口位置
        window_data = trainer_data.get("window")
        if isinstance(window_data, dict) and window_data:
            try:
                data = load_workspace()
                if "trainer" not in data or not isinstance(data["trainer"], dict):
                    data["trainer"] = {}
                data["trainer"]["window"] = window_data
                from utils.settings_manager import _atomic_write_json, _workspace_file
                _atomic_write_json(_workspace_file(), data)
            except Exception:
                pass
        # 逐 layout 保存 splitter 数据（含tab层）
        for layout_name, layout_sec in trainer_data.items():
            if not isinstance(layout_sec, dict) or layout_name == "window":
                continue
            for tab_name, tab_sec in layout_sec.items():
                if isinstance(tab_sec, dict) and tab_sec:
                    save_workspace_section("trainer", layout_name, tab_sec, tab=tab_name)

    def _restore_trainer_or_default(self):
        """恢复训练器 splitter 位置：优先工作区文件，无记录则保持当前默认。"""
        layout_name = self.current_display_mode
        if not layout_name:
            return
        tab_name = f"tab{self._training_tabs.currentIndex() + 1}"
        try:
            layout_sec = self._workspace_data.get("trainer", {}).get(layout_name, {})
            # 兼容旧格式：无tab层时直接使用
            if tab_name in layout_sec:
                saved = layout_sec[tab_name]
            elif "main" in layout_sec:
                saved = layout_sec  # 旧格式
            else:
                saved = None
        except Exception:
            saved = None
        if saved and self._apply_trainer_sizes(saved):
            self._enforce_splitter_bounds()
        # Tab2 恢复
        if self._training_tabs.currentIndex() == 1 and hasattr(self, '_tab2_main_splitter'):
            try:
                layout_sec = self._workspace_data.get("trainer", {}).get(layout_name, {})
                if "tab2" in layout_sec:
                    self._tab2_apply_sizes(layout_sec["tab2"])
            except Exception:
                pass

    def _save_window_geometry(self):
        """保存窗口位置和大小到工作区内存。"""
        if SettingsManager().get("restore_layout", True):
            return  # 恢复默认工作区模式：不保存窗口位置
        geo = self.geometry()
        self._workspace_data.setdefault("trainer", {})["window"] = {
            "x": geo.x(), "y": geo.y(), "w": geo.width(), "h": geo.height()
        }

    def _restore_window_geometry(self):
        """从工作区文件恢复窗口位置和大小（检查屏幕有效性）。返回 True 表示已恢复。"""
        try:
            win = self._workspace_data.get("trainer", {}).get("window", {})
            if not win:
                return False
            x, y, w, h = win.get("x", 0), win.get("y", 0), win.get("w", 0), win.get("h", 0)
            if w <= 0 or h <= 0:
                return False
            # 检查窗口是否在可见屏幕范围内
            from PyQt5.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen is not None:
                vg = screen.virtualGeometry()
                if not vg.intersects(__import__('PyQt5').QtCore.QRect(x, y, w, h)):
                    return False  # 不在任何屏幕上，放弃恢复
            self.setGeometry(x, y, w, h)
            return True
        except Exception:
            return False

    def _enforce_splitter_bounds(self):
        if self._splitter_adjusting or self._layout_applying:
            return
        if self.current_display_mode == "wide":
            total_m = self._main_splitter.width()
            if total_m > 0:
                sizes = self._main_splitter.sizes()
                if len(sizes) == 3:
                    left, mid, right = sizes
                    min_pane = int(total_m / 4)
                    max_pane = int(total_m / 2)
                    new_left = max(min_pane, min(left, max_pane))
                    new_right = max(min_pane, min(right, max_pane))
                    remaining = total_m - new_left - new_right
                    if remaining < min_pane:
                        if new_left > min_pane:
                            new_left = max(min_pane, new_left - (min_pane - remaining))
                            remaining = total_m - new_left - new_right
                        if remaining < min_pane and new_right > min_pane:
                            new_right = max(min_pane, new_right - (min_pane - remaining))
                            remaining = total_m - new_left - new_right
                    if new_left != left or new_right != right or mid != remaining:
                        self._splitter_adjusting = True
                        self._main_splitter.setSizes([new_left, max(min_pane, remaining), new_right])
                        self._splitter_adjusting = False
                    new_cols = 2 if remaining * 3 < total_m else 4
                    if self.banner_grid_widget._compact_cols != new_cols:
                        self.banner_grid_widget._compact_cols = new_cols
                        self.banner_grid_widget._layout_banners()
            total_r = self._right_splitter.height()
            if total_r > 0:
                sizes = self._right_splitter.sizes()
                if len(sizes) == 2:
                    top = sizes[0]
                    min_top = int(total_r / 3)
                    max_top = int(total_r * 2 / 3)
                    new_top = max(min_top, min(top, max_top))
                    if new_top != top:
                        self._splitter_adjusting = True
                        self._right_splitter.setSizes([new_top, total_r - new_top])
                        self._splitter_adjusting = False
        elif self.current_display_mode == "ultra_wide":
            total_m = self._main_splitter.width()
            if total_m > 0:
                sizes = self._main_splitter.sizes()
                if len(sizes) == 4:
                    min_pane = int(total_m / 6)
                    max_pane = int(total_m / 3)
                    new_sizes = [max(min_pane, min(s, max_pane)) for s in sizes]
                    diff = total_m - sum(new_sizes)
                    if diff != 0:
                        max_idx = new_sizes.index(max(new_sizes))
                        new_sizes[max_idx] = max(min_pane, new_sizes[max_idx] + diff)
                    if new_sizes != sizes:
                        self._splitter_adjusting = True
                        self._main_splitter.setSizes(new_sizes)
                        self._splitter_adjusting = False
                    new_cols = 2
                    if self.banner_grid_widget._compact_cols != new_cols:
                        self.banner_grid_widget._compact_cols = new_cols
                        self.banner_grid_widget._layout_banners()
        elif self.current_display_mode == "narrow":
            total_c = self._content_splitter.height()
            if total_c > 0:
                sizes = self._content_splitter.sizes()
                if len(sizes) == 2:
                    top = sizes[0]
                    min_top = int(total_c / 3)
                    max_top = int(total_c * 2 / 3)
                    new_top = max(min_top, min(top, max_top))
                    if new_top != top:
                        self._splitter_adjusting = True
                        self._content_splitter.setSizes([new_top, total_c - new_top])
                        self._splitter_adjusting = False
            total_l = self._list_splitter.width()
            if total_l > 0:
                sizes = self._list_splitter.sizes()
                if len(sizes) == 2:
                    left = sizes[0]
                    min_left = int(total_l / 3)
                    max_left = int(total_l * 2 / 3)
                    new_left = max(min_left, min(left, max_left))
                    if new_left != left:
                        self._splitter_adjusting = True
                        self._list_splitter.setSizes([new_left, total_l - new_left])
                        self._splitter_adjusting = False
            total_m = self._main_splitter.width()
            if total_m > 0:
                sizes = self._main_splitter.sizes()
                if len(sizes) == 2:
                    left = sizes[0]
                    min_left = int(total_m / 3)
                    max_left = int(total_m * 2 / 3)
                    new_left = max(min_left, min(left, max_left))
                    if new_left != left:
                        self._splitter_adjusting = True
                        self._main_splitter.setSizes([new_left, total_m - new_left])
                        self._splitter_adjusting = False

    # ===== Tab2 序列图组训练：布局与工具方法 =====

    def _tab2_apply_narrow_layout(self):
        """窄模式：2×2 网格。"""
        self._tab2_list_splitter.addWidget(self._tab2_seq_group)
        self._tab2_list_splitter.addWidget(self._tab2_elem_group)

        self._tab2_main_splitter.addWidget(self._tab2_left_widget)
        self._tab2_main_splitter.addWidget(self._tab2_training_group)
        self._tab2_right_splitter.setParent(None)

        self._tab2_content_splitter.addWidget(self._tab2_main_splitter)
        self._tab2_content_splitter.addWidget(self._tab2_list_splitter)

        if self._tab2_layout.indexOf(self._tab2_main_splitter) >= 0:
            self._tab2_layout.removeWidget(self._tab2_main_splitter)
        if self._tab2_layout.indexOf(self._tab2_content_splitter) < 0:
            self._tab2_layout.addWidget(self._tab2_content_splitter)

        self._tab2_main_splitter.setStretchFactor(0, 1)
        self._tab2_main_splitter.setStretchFactor(1, 2)
        self._tab2_list_splitter.setStretchFactor(0, 1)
        self._tab2_list_splitter.setStretchFactor(1, 2)
        self._tab2_content_splitter.setStretchFactor(0, 2)
        self._tab2_content_splitter.setStretchFactor(1, 1)

        w = self.width()
        h = self.height()
        if w > 0:
            self._tab2_main_splitter.setSizes([int(w / 3), int(w * 2 / 3)])
            self._tab2_list_splitter.setSizes([int(w / 3), int(w * 2 / 3)])
        if h > 0:
            self._tab2_content_splitter.setSizes([int(h * 2 / 3), int(h / 3)])

        self._tab2_enforce_splitter_bounds()

    def _tab2_apply_wide_layout(self):
        """宽模式：3 列。"""
        self._tab2_right_splitter.addWidget(self._tab2_seq_group)
        self._tab2_right_splitter.addWidget(self._tab2_elem_group)

        self._tab2_main_splitter.addWidget(self._tab2_left_widget)
        self._tab2_main_splitter.addWidget(self._tab2_training_group)
        self._tab2_main_splitter.addWidget(self._tab2_right_splitter)

        self._tab2_list_splitter.setParent(None)
        self._tab2_content_splitter.setParent(None)

        if self._tab2_layout.indexOf(self._tab2_main_splitter) < 0:
            self._tab2_layout.addWidget(self._tab2_main_splitter)

        self._tab2_main_splitter.setStretchFactor(0, 1)
        self._tab2_main_splitter.setStretchFactor(1, 2)
        self._tab2_main_splitter.setStretchFactor(2, 1)
        self._tab2_right_splitter.setStretchFactor(0, 1)
        self._tab2_right_splitter.setStretchFactor(1, 1)

        w = self.width()
        h = self.height()
        if w > 0:
            self._tab2_main_splitter.setSizes([int(w / 4), int(w / 2), int(w / 4)])
        if h > 0:
            self._tab2_right_splitter.setSizes([int(h / 2), int(h / 2)])

        self._tab2_enforce_splitter_bounds()

    def _tab2_apply_ultra_wide_layout(self):
        """超宽模式：4 列等宽。"""
        self._tab2_main_splitter.addWidget(self._tab2_left_widget)
        self._tab2_main_splitter.addWidget(self._tab2_training_group)
        self._tab2_main_splitter.addWidget(self._tab2_seq_group)
        self._tab2_main_splitter.addWidget(self._tab2_elem_group)

        self._tab2_right_splitter.setParent(None)
        self._tab2_list_splitter.setParent(None)
        self._tab2_content_splitter.setParent(None)

        if self._tab2_layout.indexOf(self._tab2_main_splitter) < 0:
            self._tab2_layout.addWidget(self._tab2_main_splitter)

        for i in range(4):
            self._tab2_main_splitter.setStretchFactor(i, 1)

        w = self.width()
        if w > 0:
            q = w // 4
            self._tab2_main_splitter.setSizes([q, q, q, w - 3 * q])

        self._tab2_enforce_splitter_bounds()

    def _tab2_enforce_splitter_bounds(self):
        if self._splitter_adjusting or self._layout_applying:
            return
        if self.current_display_mode == "wide":
            total_m = self._tab2_main_splitter.width()
            if total_m > 0:
                sizes = self._tab2_main_splitter.sizes()
                if len(sizes) == 3:
                    left, mid, right = sizes
                    min_pane = int(total_m / 4)
                    max_pane = int(total_m / 2)
                    new_left = max(min_pane, min(left, max_pane))
                    new_right = max(min_pane, min(right, max_pane))
                    remaining = total_m - new_left - new_right
                    if remaining < min_pane:
                        if new_left > min_pane:
                            new_left = max(min_pane, new_left - (min_pane - remaining))
                            remaining = total_m - new_left - new_right
                        if remaining < min_pane and new_right > min_pane:
                            new_right = max(min_pane, new_right - (min_pane - remaining))
                            remaining = total_m - new_left - new_right
                    if new_left != left or new_right != right or mid != remaining:
                        self._splitter_adjusting = True
                        self._tab2_main_splitter.setSizes([new_left, max(min_pane, remaining), new_right])
                        self._splitter_adjusting = False
            total_r = self._tab2_right_splitter.height()
            if total_r > 0:
                sizes = self._tab2_right_splitter.sizes()
                if len(sizes) == 2:
                    top = sizes[0]
                    min_top = int(total_r / 3)
                    max_top = int(total_r * 2 / 3)
                    new_top = max(min_top, min(top, max_top))
                    if new_top != top:
                        self._splitter_adjusting = True
                        self._tab2_right_splitter.setSizes([new_top, total_r - new_top])
                        self._splitter_adjusting = False
        elif self.current_display_mode == "ultra_wide":
            total_m = self._tab2_main_splitter.width()
            if total_m > 0:
                sizes = self._tab2_main_splitter.sizes()
                if len(sizes) == 4:
                    min_pane = int(total_m / 6)
                    max_pane = int(total_m / 3)
                    new_sizes = [max(min_pane, min(s, max_pane)) for s in sizes]
                    diff = total_m - sum(new_sizes)
                    if diff != 0:
                        max_idx = new_sizes.index(max(new_sizes))
                        new_sizes[max_idx] = max(min_pane, new_sizes[max_idx] + diff)
                    if new_sizes != sizes:
                        self._splitter_adjusting = True
                        self._tab2_main_splitter.setSizes(new_sizes)
                        self._splitter_adjusting = False
        elif self.current_display_mode == "narrow":
            total_c = self._tab2_content_splitter.height()
            if total_c > 0:
                sizes = self._tab2_content_splitter.sizes()
                if len(sizes) == 2:
                    top = sizes[0]
                    min_top = int(total_c / 3)
                    max_top = int(total_c * 2 / 3)
                    new_top = max(min_top, min(top, max_top))
                    if new_top != top:
                        self._splitter_adjusting = True
                        self._tab2_content_splitter.setSizes([new_top, total_c - new_top])
                        self._splitter_adjusting = False
            total_l = self._tab2_list_splitter.width()
            if total_l > 0:
                sizes = self._tab2_list_splitter.sizes()
                if len(sizes) == 2:
                    left = sizes[0]
                    min_left = int(total_l / 3)
                    max_left = int(total_l * 2 / 3)
                    new_left = max(min_left, min(left, max_left))
                    if new_left != left:
                        self._splitter_adjusting = True
                        self._tab2_list_splitter.setSizes([new_left, total_l - new_left])
                        self._splitter_adjusting = False
            total_m = self._tab2_main_splitter.width()
            if total_m > 0:
                sizes = self._tab2_main_splitter.sizes()
                if len(sizes) == 2:
                    left = sizes[0]
                    min_left = int(total_m / 3)
                    max_left = int(total_m * 2 / 3)
                    new_left = max(min_left, min(left, max_left))
                    if new_left != left:
                        self._splitter_adjusting = True
                        self._tab2_main_splitter.setSizes([new_left, total_m - new_left])
                        self._splitter_adjusting = False

    def _tab2_capture_sizes(self):
        data = {"main": list(self._tab2_main_splitter.sizes())}
        if self.current_display_mode == "wide":
            if self._tab2_right_splitter.count() > 0:
                data["right"] = list(self._tab2_right_splitter.sizes())
        elif self.current_display_mode == "narrow":
            if self._tab2_list_splitter.count() > 0:
                data["list"] = list(self._tab2_list_splitter.sizes())
            if self._tab2_content_splitter.count() > 0:
                data["content"] = list(self._tab2_content_splitter.sizes())
        return data

    def _tab2_apply_sizes(self, sizes_dict):
        if not isinstance(sizes_dict, dict):
            return False
        try:
            applied = False
            main = sizes_dict.get("main", [])
            if len(main) == self._tab2_main_splitter.count() and sum(main) > 0:
                self._tab2_main_splitter.setSizes(main)
                applied = True
            if self.current_display_mode == "wide":
                right = sizes_dict.get("right", [])
                if self._tab2_right_splitter.count() > 0 and len(right) == self._tab2_right_splitter.count() and sum(right) > 0:
                    self._tab2_right_splitter.setSizes(right)
                    applied = True
            elif self.current_display_mode == "narrow":
                lst = sizes_dict.get("list", [])
                if self._tab2_list_splitter.count() > 0 and len(lst) == self._tab2_list_splitter.count() and sum(lst) > 0:
                    self._tab2_list_splitter.setSizes(lst)
                    applied = True
                content = sizes_dict.get("content", [])
                if self._tab2_content_splitter.count() > 0 and len(content) == self._tab2_content_splitter.count() and sum(content) > 0:
                    self._tab2_content_splitter.setSizes(content)
                    applied = True
            return applied
        except Exception:
            return False

    def _tab2_import_mbtlx(self):
        """导入 .mbtlx 标记文件。"""
        import zipfile
        import json
        filepath, _ = QFileDialog.getOpenFileName(
            self, "导入 .mbtlx 标记文件", "", "标记文件 (*.mbtlx);;所有文件 (*)"
        )
        if not filepath:
            return
        try:
            self._tab2_graphic_marks = []

            # 检测格式：ZIP（新格式）还是文本（旧格式）
            is_zip = False
            with open(filepath, 'rb') as f:
                magic = f.read(2)
            if magic == b'PK':
                is_zip = True

            count = 0
            if is_zip:
                extract_dir = os.path.join(tempfile.gettempdir(), f"mbtlx_{uuid.uuid4().hex[:8]}")
                with zipfile.ZipFile(filepath, 'r') as zf:
                    zf.extractall(extract_dir)
                marks_path = os.path.join(extract_dir, "marks.json")
                if not os.path.exists(marks_path):
                    QMessageBox.warning(self, "导入失败", "文件缺少 marks.json")
                    return
                with open(marks_path, 'r', encoding='utf-8') as f:
                    marks_data = json.load(f)
                for item in marks_data.get("items", []):
                    img_rel = item.get("image", "")
                    img_path = os.path.join(extract_dir, img_rel) if img_rel else ""
                    banners = item.get("banners", [])
                    if not banners:
                        continue
                    banner_data = list(banners[0].get("data", [0]))
                    self._tab2_graphic_marks.append([img_path, banner_data])
                    count += 1
            else:
                # 旧格式：文本行解析
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or '|' not in line:
                            continue
                        img_path, data_str = line.split('|', 1)
                        parts = data_str.split(';')
                        bg = int(parts[0])
                        banner_data = [bg]
                        if len(parts) > 1:
                            for pat_str in parts[1].split('/'):
                                if '-' in pat_str:
                                    ci, pi = pat_str.split('-', 1)
                                    banner_data.extend([int(pi), int(ci)])
                        self._tab2_graphic_marks.append([img_path, banner_data])
                        count += 1

            # 刷新数据列表
            self._tab2_refresh_data_list()
            self._tab2_data_info.setText(f"共 {count} 条 | {os.path.basename(filepath)}")
            self._tab2_status_label.setText(f"已导入 {count} 条数据")
            QMessageBox.information(self, "导入成功", f"已导入 {count} 条标记")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _tab2_refresh_data_list(self):
        """刷新 Tab2 数据列表（带旗帜渲染缩略图）。"""
        self._tab2_data_list.clear()
        self._tab2_data_list.setIconSize(QSize(40, 40))
        for i, (img_path, banner_data) in enumerate(self._tab2_graphic_marks):
            bg_name = color_name[banner_data[0]] if banner_data[0] < len(color_name) else "?"
            n_patterns = (len(banner_data) - 1) // 2
            text = f"{i+1}. {os.path.basename(img_path)} | {bg_name} | {n_patterns}层图案"
            item = QListWidgetItem(text)
            # 生成旗帜渲染缩略图
            try:
                bgr_img = generate_banner_image(banner_data, size=(40, 40))
                if bgr_img is not None:
                    import numpy as np
                    rgb_img = bgr_img[:, :, ::-1].copy()  # BGR → RGB
                    qimg = QImage(rgb_img.data, rgb_img.shape[1], rgb_img.shape[0],
                                  rgb_img.strides[0], QImage.Format_RGB888)
                    item.setIcon(QIcon(QPixmap.fromImage(qimg)))
            except Exception:
                pass
            self._tab2_data_list.addItem(item)

    def _tab2_on_data_selection(self, row):
        """数据列表选中项变化时，更新 training_group（图片+渲染图）和 elem_group（图案组成列表）。"""
        if row < 0 or row >= len(self._tab2_graphic_marks):
            self._tab2_thumb_label.setText("（未选择数据）")
            self._tab2_thumb_label.setProperty("placeholderText", True)
            self._tab2_banner_render_label.setText("（未选择）")
            self._tab2_banner_render_label.setProperty("placeholderText", True)
            self._tab2_elem_list.clear()
            return
        img_path, banner_data = self._tab2_graphic_marks[row]

        # 在 training_group 左侧显示上传识别图
        try:
            import cv2
            import numpy as np
            data = np.fromfile(img_path, dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is not None:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                h, w = img.shape[:2]
                max_size = 300
                if max(h, w) > max_size:
                    scale = max_size / max(h, w)
                    img = cv2.resize(img, (int(w * scale), int(h * scale)))
                qimg = QImage(img.data, img.shape[1], img.shape[0], img.strides[0], QImage.Format_RGB888)
                self._tab2_thumb_label.setPixmap(QPixmap.fromImage(qimg))
                self._tab2_thumb_label.setProperty("placeholderText", False)
            else:
                self._tab2_thumb_label.setText("（图片加载失败）")
                self._tab2_thumb_label.setProperty("placeholderText", True)
        except Exception:
            self._tab2_thumb_label.setText("（图片不可用）")
            self._tab2_thumb_label.setProperty("placeholderText", True)

        # 在 training_group 右侧显示旗帜渲染图
        try:
            bgr_img = generate_banner_image(banner_data, size=(200, 400))
            if bgr_img is not None:
                import numpy as np
                rgb_img = bgr_img[:, :, ::-1].copy()  # BGR → RGB
                qimg = QImage(rgb_img.data, rgb_img.shape[1], rgb_img.shape[0],
                              rgb_img.strides[0], QImage.Format_RGB888)
                self._tab2_banner_render_label.setPixmap(QPixmap.fromImage(qimg))
                self._tab2_banner_render_label.setProperty("placeholderText", False)
            else:
                self._tab2_banner_render_label.setText("（渲染失败）")
                self._tab2_banner_render_label.setProperty("placeholderText", True)
        except Exception:
            self._tab2_banner_render_label.setText("（渲染失败）")
            self._tab2_banner_render_label.setProperty("placeholderText", True)

        # 在 elem_group 显示图案组成列表（与 Tab1 一致）
        self._tab2_elem_list.clear()
        bg_name = color_name[banner_data[0]] if banner_data[0] < len(color_name) else "?"
        self._tab2_elem_list.addItem(f"背景色: {bg_name}")
        for j in range(1, len(banner_data), 2):
            if j + 1 < len(banner_data):
                pi = banner_data[j]
                ci = banner_data[j + 1]
                p_name = type_zh[pi] if pi < len(type_zh) else "?"
                c_name = color_name[ci] if ci < len(color_name) else "?"
                layer = (j - 1) // 2 + 1
                self._tab2_elem_list.addItem(f"第{layer}层: {c_name} - {p_name}")

    def _tab2_on_inherit_toggled(self, checked):
        """继承 Tab1 参数复选框状态变化。"""
        self._tab2_epoch_spin.setEnabled(not checked)
        self._tab2_batch_spin.setEnabled(not checked)
        self._tab2_lr_combo.setEnabled(not checked)
        if checked:
            # 立即同步一次
            self._tab2_sync_inherited_params()

    def _tab2_sync_inherited_params(self):
        """从 Tab1 同步参数到 Tab2（继承模式下）。"""
        if self._tab2_inherit_check.isChecked():
            self._tab2_epoch_spin.setValue(self.epoch_spin.value())
            self._tab2_batch_spin.setValue(self.batch_spin.value())
            self._tab2_lr_combo.setCurrentIndex(self.lr_combo.currentIndex())

    def _tab2_start_training(self):
        """开始 Tab2 训练（占位）。"""
        if not self._tab2_graphic_marks:
            QMessageBox.warning(self, "提示", "请先导入 .mbtlx 数据")
            return
        if self.model is None or self.trainer is None:
            QMessageBox.warning(self, "警告", "模型尚未加载完成，请稍候")
            return
        if getattr(self, "_is_training", False):
            QMessageBox.warning(self, "提示", "Tab1 正在训练中，请先停止")
            return
        # TODO: 实现训练逻辑
        QMessageBox.information(self, "提示", "训练功能开发中")

    def _tab2_stop_training(self):
        """停止 Tab2 训练（占位）。"""
        pass

    def _tab2_clear_data(self):
        """清空 Tab2 导入的数据。"""
        if not self._tab2_graphic_marks:
            QMessageBox.information(self, "提示", "当前没有数据可清空")
            return
        reply = QMessageBox.question(
            self, "确认清空",
            f"将清空 {len(self._tab2_graphic_marks)} 条数据，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.No:
            return
        self._tab2_graphic_marks = []
        self._tab2_data_list.clear()
        self._tab2_data_info.setText("未导入数据")
        self._tab2_status_label.setText("就绪")
        self._tab2_thumb_label.setText("（暂无训练图片）")
        self._tab2_thumb_label.setProperty("placeholderText", True)
        self._tab2_banner_render_label.setText("（未选择）")
        self._tab2_banner_render_label.setProperty("placeholderText", True)
        self._tab2_elem_list.clear()

    def _tab2_save_model(self):
        """保存 Tab2 训练的模型（占位）。"""
        QMessageBox.information(self, "提示", "保存模型功能开发中")

    def _tab2_load_model(self):
        """加载模型继续 Tab2 训练（占位）。"""
        QMessageBox.information(self, "提示", "继续训练功能开发中")

    def start_training(self):
        if not hasattr(self, 'dataloader') or self.dataloader is None:
            QMessageBox.warning(self, "警告", "请先导入旗帜数据")
            return
        if self.model is None or self.trainer is None:
            QMessageBox.warning(self, "警告", "模型尚未加载完成，请稍候")
            return

        import torch

        self.train_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.loss_chart_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self._is_training = True
        self._training_done = False
        self._update_button_states()
        _training_error_suppressed = True

        lr = float(self.lr_combo.currentText())
        self.trainer.optimizer = torch.optim.Adam(self.trainer.model.parameters(), lr=lr)

        epochs = self.epoch_spin.value()
        val_loader = getattr(self, 'val_dataloader', None)

        print(f"[训练器] 开始训练: epochs={epochs}, lr={lr}, 数据量={len(self.training_images)}, batch_size={self.batch_spin.value()}")
        self.training_thread = TrainingThread(self.trainer, self.dataloader, epochs, val_loader)
        self.training_thread.progress_update.connect(self.update_progress)
        self.training_thread.progress_detail.connect(self.update_progress_detail)
        self.training_thread.banner_progress.connect(self._on_banner_progress)
        self.training_thread.training_complete.connect(self.training_completed)
        self.training_thread.training_error.connect(self.training_failed)
        self.training_thread.start()

        self.status_label.setText("训练中...\n正在初始化...")
        self.progress_detail.setText("")
        self._current_epoch = 0
        self._total_epochs = epochs
        self._completed_banners = set()
        self._animating_banner = -1
        self._animating_value = 0.0
        self._animating_epoch = -1
        self._banner_queue = []

    def _on_banner_progress(self, banner_idx, total_banners, epoch, epochs, within, loss):
        try:
            if epoch != self._current_epoch:
                self._current_epoch = epoch
                self._completed_banners.clear()
                self._banner_queue.clear()
                self._animating_banner = -1
                for label in self.banner_labels:
                    label.set_progress(0, show=False)
                print(f"[训练器] === Epoch {epoch+1}/{epochs} ===")

            if banner_idx % max(1, total_banners // 10) == 0 or banner_idx == total_banners - 1:
                print(f"[训练器] Epoch {epoch+1}/{epochs} | 旗帜 {banner_idx+1}/{total_banners} | Loss: {loss:.4f}")

            self._banner_queue.append(banner_idx)
            if self._animating_banner < 0:
                self._start_next_banner_animation()
        except Exception as bp_err:
            print(f"[训练器] banner_progress异常: {bp_err}")

    def _start_next_banner_animation(self):
        if not self._banner_queue:
            return
        banner_idx = self._banner_queue.pop(0)
        self._animating_banner = banner_idx
        self._animating_value = 0.0
        self._animating_epoch = self._current_epoch
        target_page = banner_idx // self._page_size
        if target_page != self._current_page:
            self._current_page = target_page
            self.update_training_banners()
        self._animate_current_banner()

    def _animate_current_banner(self):
        if not self._is_training:
            return
        banner_idx = self._animating_banner
        if banner_idx < 0:
            return

        self._animating_value = min(self._animating_value + 0.08, 1.0)

        start_idx = self._current_page * self._page_size
        for i in range(self._page_size):
            data_idx = start_idx + i
            if data_idx >= len(self.training_images):
                self.banner_labels[i].set_progress(0, show=False)
            elif data_idx == banner_idx:
                self.banner_labels[i].set_progress(self._animating_value, show=True)
            elif data_idx in self._completed_banners:
                self.banner_labels[i].set_progress(1.0, show=True, checkmark=True)
            else:
                self.banner_labels[i].set_progress(0, show=False)

        if self._animating_value >= 1.0:
            self._completed_banners.add(banner_idx)
            self._animating_banner = -1
            start_idx = self._current_page * self._page_size
            for i in range(self._page_size):
                data_idx = start_idx + i
                if data_idx < len(self.training_images) and data_idx in self._completed_banners:
                    self.banner_labels[i].set_progress(1.0, show=True, checkmark=True)
            if self._banner_queue:
                self._start_next_banner_animation()
        else:
            QTimer.singleShot(30, self._animate_current_banner)

    def update_progress(self, value):
        try:
            self.progress_bar.setValue(value)
        except Exception:
            pass

    def update_progress_detail(self, detail_text):
        try:
            self.status_label.setText(f"训练中...\n{detail_text}")
            self.progress_detail.setText("")
        except Exception:
            pass

    def stop_training(self):
        if hasattr(self, 'training_thread') and self.training_thread.isRunning():
            dlg = QMessageBox(QMessageBox.Question, "停止训练", "确定要停止训练吗？",
                QMessageBox.Yes | QMessageBox.No, self)
            reply = dlg.exec_()

            if reply == QMessageBox.Yes:
                self.training_thread.terminate()
                if not self.training_thread.wait(5000):
                    print("训练线程停止超时")

                del self.training_thread
                self._is_training = False
                _training_error_suppressed = False
                self._banner_queue.clear()
                self._animating_banner = -1

                self.status_label.setText("训练已停止")
                self._update_button_states()
                self.progress_detail.setText("")
                self.train_button.setEnabled(True)
                self.stop_button.setEnabled(False)

                for label in self.banner_labels:
                    label.set_progress(0, show=False)

                QMessageBox.information(self, "提示", "训练已停止")

    def clear_sequence(self):
        if self._is_training:
            reply = QMessageBox.question(self, "确认", "训练正在进行中，清空序列将停止训练。是否继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            # 停止训练（不弹第二次确认框）
            if hasattr(self, 'training_thread') and self.training_thread.isRunning():
                self.training_thread.terminate()
                if not self.training_thread.wait(5000):
                    print("训练线程停止超时")
                del self.training_thread
            self._is_training = False
            self._banner_queue.clear()
            self._animating_banner = -1
            self.status_label.setText("训练已停止")
            self.progress_detail.setText("")
            self.train_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            for label in self.banner_labels:
                label.set_progress(0, show=False)
        if not self.training_images:
            QMessageBox.information(self, "提示", "当前没有已加载的序列数据")
            return

        dlg = QMessageBox(QMessageBox.Question, "确认清空", "确定要清空所有已加载的旗帜序列数据吗？",
            QMessageBox.Yes | QMessageBox.No, self)
        reply = dlg.exec_()
        if reply != QMessageBox.Yes:
            return

        self.training_images = []
        if hasattr(self, 'dataloader'):
            del self.dataloader
        self._current_page = 0

        for label in self.banner_labels:
            label._pixmap = None
            label.set_progress(0, show=False)
            label.update()

        self.seq_list.clear()
        self.elem_list.clear()
        self._update_training_view()
        self.progress_bar.setValue(0)
        self.status_label.setText("就绪")
        self.progress_detail.setText("")
        self.train_button.setText("导入 .mbtl")
        try:
            self.train_button.disconnect()
        except Exception:
            pass
        self.train_button.clicked.connect(self.import_banner)
        self.train_button.setEnabled(True)
        self._update_page_info()
        self._update_button_states()

    def closeEvent(self, event):
        # 关闭独立设置子进程（如有）
        proc = getattr(self, "_settings_process", None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

        # 关闭前保存当前训练器工作区位置到磁盘
        self._save_trainer_to_workspace()
        # snap 状态下不保存窗口位置（未脱离 snap）；脱离 snap 才保存
        try:
            _hwnd = int(self.winId())
        except Exception:
            _hwnd = 0
        if _hwnd and _is_window_snapped(_hwnd):
            # snap 状态：清除内存中的 window 数据，避免 _flush 写回旧记录
            _trainer_data = self._workspace_data.get("trainer", {})
            if isinstance(_trainer_data, dict):
                _trainer_data.pop("window", None)
        else:
            self._save_window_geometry()
        self._flush_trainer_to_disk()

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

        has_training = hasattr(self, 'training_thread') and getattr(self.training_thread, 'isRunning', lambda: False)()
        has_data = len(self.training_images) > 0

        if not has_training and not has_data:
            self._remove_closing_signal()
            self._write_quit_signal()
            self._cleanup_group_lock()
            event.accept()
            return

        # 启动独立退出确认窗口（exit.pyw），不阻塞 UI
        msg = "旗帜训练工具即将关闭，训练器与导入器将同时退出。\n\n"
        if has_training:
            msg += "• 训练正在进行中，关闭后训练将停止。\n"
        if has_data:
            msg += "• 已加载的旗帜数据将丢失。\n"
        msg += "\n确定要退出吗？"
        self._launch_exit_confirmation("训练器", msg, has_training, has_data)
        event.ignore()

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
        has_training = getattr(self, "_exit_has_training", False)
        has_data = getattr(self, "_exit_has_data", False)
        save_requested = getattr(self, "_exit_save_requested", False)
        if has_training:
            self.training_thread.terminate()
            if not self.training_thread.wait(5000):
                print("训练线程停止超时")
            self._is_training = False
            self._banner_queue.clear()
            self._animating_banner = -1
        if save_requested:
            # 用户勾选"退出前保存"：根据 save_formats 多格式保存到手动保存文件夹
            from datetime import datetime
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            try:
                save_fmts = SettingsManager().get("save_formats", ["pth"])
            except Exception:
                save_fmts = ["pth"]
            if not isinstance(save_fmts, list):
                save_fmts = [save_fmts]
            if "all" in save_fmts:
                save_fmts = ["pth", "mbtl", "mbtlx"]
            sm = SettingsManager()
            # 旗帜数据存 training_datas/，模型权重存 models/
            data_base = resolve_app_path(sm.get("manual_save_trainer_path", "training_datas/manual_save/trainer"))
            data_dir = os.path.join(data_base, ts)
            os.makedirs(data_dir, exist_ok=True)
            model_base = resolve_app_path(sm.get("manual_save_trainer_model_path", "models/manual_save"))
            model_dir = os.path.join(model_base, ts)
            os.makedirs(model_dir, exist_ok=True)
            # 保存旗帜数据 (.mbtl / .mbtlx)
            if has_data and ("mbtl" in save_fmts or "mbtlx" in save_fmts):
                try:
                    from utils.mbtl_utils import write_mbtl
                    raw_banners = [item['banner_data'] for item in self.training_images]
                    if "mbtl" in save_fmts:
                        write_mbtl(os.path.join(data_dir, "banner.mbtl"), raw_banners)
                    if "mbtlx" in save_fmts:
                        write_mbtl(os.path.join(data_dir, "banner.mbtlx"), raw_banners)
                except Exception:
                    pass
            # 保存模型权重 (.pth)
            if has_training and "pth" in save_fmts:
                try:
                    import torch
                    model_path = os.path.join(model_dir, "banner_vit_model.pth")
                    torch.save({'model_state_dict': self.model.state_dict(),
                                'model_arch': getattr(self.model, 'model_arch', 'vit_b_16')}, model_path)
                except Exception:
                    pass
        elif has_data:
            # 未勾选保存：仍写备份（兼容旧行为）
            try:
                from utils.mbtl_utils import write_mbtl
                mbtl_path = os.path.join(resolve_app_path("training_datas"), "training_backup.mbtl")
                os.makedirs(os.path.dirname(mbtl_path), exist_ok=True)
                raw_banners = [item['banner_data'] for item in self.training_images]
                write_mbtl(mbtl_path, raw_banners)
            except Exception:
                pass
        self._remove_closing_signal()
        self._write_quit_signal()
        self._cleanup_group_lock()
        self._force_quit = True
        self._initiated_quit = True  # 主动退出，不清理 session_dir（接收方需要读取信号）
        self.close()

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

    def training_completed(self):
        self._is_training = False
        self._training_done = True
        self._model_trained = True  # 训练完成，允许保存模型
        self._update_button_states()
        _training_error_suppressed = False
        self._banner_queue.clear()
        self._animating_banner = -1
        print(f"[训练器] 训练完成！共 {self._total_epochs} 个epoch")
        if hasattr(self, 'training_thread') and self.training_thread.epoch_losses:
            print(f"[训练器] 最终Loss: {self.training_thread.epoch_losses[-1]:.4f}")
        self.status_label.setText("训练完成！")
        self.progress_detail.setText("")
        self.train_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        start_idx = self._current_page * self._page_size
        for i in range(self._page_size):
            data_idx = start_idx + i
            if data_idx < len(self.training_images):
                self.banner_labels[i].set_progress(1.0, show=True, checkmark=True)
            else:
                self.banner_labels[i].set_progress(0, show=False)

        if hasattr(self, 'training_thread') and self.training_thread.epoch_losses:
            self.loss_chart_button.setEnabled(True)

        try:
            import torch
            from datetime import datetime
            save_dir = resolve_app_path("models/model_file")
            os.makedirs(save_dir, exist_ok=True)
            model_path = os.path.join(save_dir, f"banner_vit_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pth")
            torch.save({'model_state_dict': self.model.state_dict(),
                        'model_arch': getattr(self.model, 'model_arch', 'vit_b_16')}, model_path)
            print(f"[训练器] 模型已自动保存到 {model_path}")
            self.status_label.setText(f"训练完成！模型已保存")
        except Exception:
            pass

    def _show_loss_chart(self):
        losses = self.training_thread.epoch_losses if hasattr(self, 'training_thread') else []
        if not losses:
            QMessageBox.information(self, "提示", "没有可用的训练Loss数据")
            return
        s = self._scale
        dlg_w = max(int(960 * s), 860)
        dlg_h = max(int(700 * s), 630)

        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt

            screen_dpi = self.logicalDpiX() if hasattr(self, 'logicalDpiX') else 96
            dpi_scale = screen_dpi / 96.0
            dpi_factor = min(dpi_scale ** 0.4, 1.3) if dpi_scale > 1.0 else 1.0
            mpl_dpi = max(int(96 * dpi_factor), 96)

            font_scale = min(dpi_factor, 1.2)
            xlabel_fs = max(int(11 * font_scale), 10)
            ylabel_fs = max(int(11 * font_scale), 10)
            title_fs = max(int(13 * font_scale), 12)
            tick_fs = max(int(9 * font_scale), 8)
            anno_fs = max(int(8 * font_scale), 7)

            fig_w = max(10 * s, 8.5)
            fig_h = max(7 * s, 5.8)
            fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=mpl_dpi)
            ax.plot(range(1, len(losses) + 1), losses, 'b-o', markersize=5, linewidth=1.5)
            ax.set_xlabel('Epoch', fontsize=xlabel_fs)
            ax.set_ylabel('Loss', fontsize=ylabel_fs)
            ax.set_title('Training Loss', fontsize=title_fs)
            ax.tick_params(labelsize=tick_fs)
            ax.grid(True, alpha=0.3)

            n = len(losses)
            max_labels = 8
            step = max(1, n // max_labels)
            for i in range(0, n, step):
                epoch = i + 1
                loss_val = losses[i]
                ax.annotate(f'{loss_val:.4f}', xy=(epoch, loss_val),
                            xytext=(0, 10), textcoords='offset points',
                            ha='center', va='bottom', fontsize=anno_fs,
                            color='darkblue', alpha=0.85)
            if n > 0 and (n - 1) % step != 0:
                ax.annotate(f'{losses[-1]:.4f}', xy=(n, losses[-1]),
                            xytext=(0, 10), textcoords='offset points',
                            ha='center', va='bottom', fontsize=anno_fs,
                            color='darkred', alpha=0.9)

            fig.tight_layout(pad=2.0)

            buf = os.path.join(os.environ.get('TEMP', os.environ.get('TMP', '.')), '_banner_loss_chart.png')
            fig.savefig(buf, bbox_inches='tight', dpi=mpl_dpi, pad_inches=0.25)
            plt.close(fig)

            dlg = QDialog(self)
            dlg.setWindowTitle("训练Loss变化")
            dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
            dlg.setFixedSize(dlg_w, dlg_h)
            layout = QVBoxLayout(dlg)
            pixmap = QPixmap(buf)
            label = QLabel()
            label.setPixmap(pixmap.scaled(dlg_w - 20, dlg_h - 60, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            layout.addWidget(label)
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(dlg.accept)
            layout.addWidget(close_btn)
            dlg.exec_()
            try:
                os.remove(buf)
            except Exception:
                pass
        except ImportError:
            self._show_loss_chart_qt(losses)
        except Exception as e:
            QMessageBox.warning(self, "图表生成失败", f"无法生成Loss图表:\n{str(e)}")

    def _show_loss_chart_qt(self, losses):
        s = self._scale
        dlg_w = max(int(700 * s), 640)
        dlg_h = max(int(520 * s), 480)
        dlg = QDialog(self)
        dlg.setWindowTitle("训练Loss变化")
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dlg.setFixedSize(dlg_w, dlg_h)
        layout = QVBoxLayout(dlg)

        chart = _LossChartWidget(losses, dlg)
        layout.addWidget(chart)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)
        dlg.exec_()

    def training_failed(self, error_msg):
        self._is_training = False
        self._update_button_states()
        _training_error_suppressed = False
        self._banner_queue.clear()
        self._animating_banner = -1
        try:
            print(f"[训练器] 训练失败: {error_msg}")
        except Exception:
            pass
        self.status_label.setText(f"训练失败\n{error_msg}")
        self.progress_detail.setText("")
        self.train_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        for label in self.banner_labels:
            label.set_progress(0, show=False)

    def save_model(self):
        if getattr(self, "model", None) is None or not getattr(self, "_model_trained", False):
            QMessageBox.warning(self, "提示", "模型尚未训练，无法保存")
            return
        import torch
        from datetime import datetime
        try:
            default_dir = resolve_app_path("models/model_file")
            os.makedirs(default_dir, exist_ok=True)
            default_path = os.path.join(default_dir, f"banner_vit_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pth")
            model_path, _ = QFileDialog.getSaveFileName(
                self, "保存模型", default_path,
                "模型文件 (*.pth);;所有文件 (*)"
            )
            if not model_path:
                return
            torch.save({'model_state_dict': self.model.state_dict(),
                        'model_arch': getattr(self.model, 'model_arch', 'vit_b_16')}, model_path)
            QMessageBox.information(self, "成功", f"模型已保存到 {model_path}")
            self.status_label.setText(f"模型已保存到 {os.path.basename(model_path)}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存模型失败: {str(e)}")

    def load_model(self):
        import torch
        try:
            default_dir = resolve_app_path("models/model_file")
            model_path, _ = QFileDialog.getOpenFileName(
                self, "选择训练数据文件", default_dir,
                "模型文件 (*.pth *.pt);;所有文件 (*)"
            )
            if not model_path:
                return
            if not model_path.endswith(('.pth', '.pt')):
                QMessageBox.warning(self, "警告", "请选择 .pth 或 .pt 格式的模型文件")
                return

            use_peft = False
            if self.training_mode == "peft":
                try:
                    from peft import PeftModel
                    use_peft = True
                except ImportError:
                    pass

            if use_peft and self.training_mode == "peft":
                from peft import PeftModel
                self.trainer.load_model(model_path)
            else:
                checkpoint = torch.load(model_path, weights_only=False)
                if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint:
                    self.model.load_state_dict(checkpoint['model_state_dict'])
                else:
                    self.model.load_state_dict(checkpoint)

            QMessageBox.information(self, "成功", "继续训练数据已加载")
            self.status_label.setText("已加载训练数据，可以继续训练")
            self._model_trained = True  # 加载的是已训练权重，允许保存
            self._update_button_states()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"继续训练失败: {str(e)}")

    @staticmethod
    def _parse_banner_content(content):
        if not content or not content.strip():
            return []
        banner_strings = content.strip().split("|")
        banners = []
        for banner_str in banner_strings:
            if not banner_str:
                continue
            parts = banner_str.split(";")
            if len(parts) < 2:
                continue
            bg_color = int(parts[0])
            pattern_str = parts[1]
            pattern_parts = pattern_str.split("/")
            banner_data = [bg_color]
            for pattern in pattern_parts:
                if not pattern:
                    continue
                pattern_details = pattern.split("-")
                if len(pattern_details) == 2:
                    color_idx = int(pattern_details[0])
                    pattern_idx = int(pattern_details[1])
                    banner_data.extend([pattern_idx, color_idx])
            banners.append(banner_data)
        return banners

    def _setup_dataloader(self, banners):
        import torch
        from torch.utils.data import DataLoader
        from models.structures.vit_model import BannerDataset

        self._training_done = False
        total = len(banners)
        pw = _ImportProgressWindow(self, total)
        pw.show()
        QApplication.processEvents()
        pw.update_progress(0, f"正在处理 {total} 个旗帜...")

        self.training_images = []
        for i, banner_data in enumerate(banners):
            if i % max(total // 20, 1) == 0:
                pw.update_progress(i, f"正在处理旗帜 ({i+1}/{total})...")
            bg_color_val = banner_data[0]
            bg_name = color_name[bg_color_val] if isinstance(color_name, list) and bg_color_val < len(color_name) else str(bg_color_val)
            description = f"旗帜色: {bg_name}, 图案数: {len(banner_data)//2}"
            self.training_images.append({
                'index': i + 1,
                'banner_data': banner_data,
                'description': description
            })

        raw_banners = [item['banner_data'] for item in self.training_images]
        pw.update_progress(total, "正在构建训练数据集...")
        dataset = BannerDataset(raw_banners)
        use_cuda = torch.cuda.is_available()
        dl_kwargs = dict(
            batch_size=self.batch_spin.value(),
            shuffle=True,
            pin_memory=use_cuda
        )
        if use_cuda:
            sm = SettingsManager()
            if sm.get("auto_resource_alloc", True):
                gpu_mem = sm.get("gpu_memory", 0)
                sys_mem = sm.get("sys_memory", 0)
                if not isinstance(gpu_mem, (int, float)):
                    gpu_mem = 0
                if not isinstance(sys_mem, (int, float)):
                    sys_mem = 0
                alloc = compute_resource_allocation(gpu_mem, sys_mem, "vit_b_16", sm.get("mixed_precision", "fp16") == "fp16", sm.get("perf_level", "balanced"))
                nw = alloc["num_workers"]
            else:
                nw = sm.get("num_workers", 4)
                if nw == "auto" or not isinstance(nw, (int, float)) or nw <= 0:
                    nw = 4
            dl_kwargs.update(num_workers=int(nw), prefetch_factor=2)
        self.dataloader = DataLoader(dataset, **dl_kwargs)

        self._current_page = 0
        self.update_training_banners()
        self.seq_list.clear()
        self.elem_list.clear()
        for img_info in self.training_images:
            item = QListWidgetItem(f"旗帜 {img_info['index']}: {img_info['description']}")
            self.seq_list.addItem(item)
        if self.seq_list.count() > 0:
            self.seq_list.setCurrentRow(0)

        self.seq_list.updateGeometry()
        self.seq_list.verticalScrollBar().updateGeometry()

        self._update_training_view()
        self.train_button.setText("开始训练")
        try:
            self.train_button.disconnect()
        except Exception:
            pass
        self.train_button.clicked.connect(self.start_training)
        self.train_button.setEnabled(True)
        pw.finish()

    def load_data_from_file(self, data_file):
        try:
            self.train_button.setEnabled(False)
            self.status_label.setText("正在从导入器接收旗帜数据...")
            QApplication.processEvents()
            with open(data_file, "r", encoding="utf-8") as f:
                content = f.read().strip()

            if not content:
                QMessageBox.warning(self, "警告", "没有加载到旗帜数据")
                self.status_label.setText("就绪")
                self.train_button.setEnabled(True)
                return

            banners = self._parse_banner_content(content)

            if not banners:
                QMessageBox.warning(self, "警告", "没有加载到有效的旗帜数据")
                self.status_label.setText("就绪")
                self.train_button.setEnabled(True)
                return

            self._setup_dataloader(banners)

            self.status_label.setText(f"成功加载 {len(banners)} 个旗帜数据")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载数据失败: {str(e)}")
        finally:
            if os.path.exists(data_file):
                try:
                    os.remove(data_file)
                except OSError:
                    pass

    def import_banner(self):
        sm = SettingsManager()
        _auto_path = resolve_app_path(sm.get("auto_save_trainer_path", "training_datas/auto_save/trainer"))
        training_dir = os.path.dirname(os.path.dirname(_auto_path))
        file_paths, _ = QFileDialog.getOpenFileNames(self, "导入 .mbtl", training_dir, "旗帜序列文件 (*.mbtl);;所有文件 (*)")

        if not file_paths:
            return

        try:
            self.training_images = []
            self.train_button.setEnabled(False)
            self.status_label.setText("正在导入旗帜数据...")
            QApplication.processEvents()

            all_banners = []
            total_files = len(file_paths)
            for fi, file_path in enumerate(file_paths):
                self.status_label.setText(f"正在导入 ({fi+1}/{total_files})...")
                QApplication.processEvents()
                try:
                    loaded = load_banners_from_file(file_path)
                except Exception as load_err:
                    print(f"[训练器] 导入文件失败 {file_path}: {load_err}")
                    continue
                all_banners.extend(loaded)

            if not all_banners:
                QMessageBox.warning(self, "警告", "没有成功导入任何旗帜数据")
                self.train_button.setEnabled(True)
                self.status_label.setText("就绪")
                self._update_training_view()
                return

            self._setup_dataloader(all_banners)

            self.status_label.setText(f"成功导入 {len(all_banners)} 个旗帜")
            self._update_button_states()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败: {str(e)}")
            self._update_button_states()

    def on_seq_selection_changed(self, index):
        if index >= 0 and index < len(self.training_images):
            image_info = self.training_images[index]
            self.preview_banner = image_info['banner_data']
            self._update_elem_list(image_info['banner_data'])

            page = index // self._page_size
            if page != self._current_page:
                self._current_page = page
                self.update_training_banners()

    def _update_elem_list(self, banner_data):
        self.elem_list.clear()
        bg_color_idx = banner_data[0]
        bg_name = color_name[bg_color_idx] if bg_color_idx < len(color_name) else f"颜色{bg_color_idx}"
        item = QListWidgetItem(f"旗帜色: {bg_name} ({bg_color_idx})")
        self.elem_list.addItem(item)

        for i in range(1, len(banner_data), 2):
            if i + 1 < len(banner_data):
                pattern_idx = banner_data[i]
                color_idx = banner_data[i + 1]
                color_name_str = color_name[color_idx] if color_idx < len(color_name) else f"颜色{color_idx}"
                pattern_type = banner_type[pattern_idx] if pattern_idx < len(banner_type) else f"图案{pattern_idx}"
                item = QListWidgetItem(f"图案{i//2+1}: {color_name_str}-{pattern_type} ({color_idx}-{pattern_idx})")
                self.elem_list.addItem(item)

    def update_training_banners(self):
        import cv2
        for label in self.banner_labels:
            label._pixmap = None
            label.set_progress(0, show=False)
            label.update()

        start_idx = self._current_page * self._page_size
        for i in range(self._page_size):
            data_idx = start_idx + i
            if data_idx < len(self.training_images):
                image_info = self.training_images[data_idx]
                try:
                    bgr_image = generate_banner_image(image_info['banner_data'], size=(100, 200))
                    image_rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
                    qimage = QImage(image_rgb.data, image_rgb.shape[1], image_rgb.shape[0], image_rgb.shape[1] * 3, QImage.Format_RGB888)
                    pixmap = QPixmap.fromImage(qimage)
                    self.banner_labels[i].setPixmap(pixmap)
                except Exception as e:
                    print(f"显示旗帜 {data_idx+1} 失败: {e}")

        if self._is_training or self._training_done:
            for i in range(self._page_size):
                data_idx = start_idx + i
                if data_idx < len(self.training_images) and data_idx in self._completed_banners:
                    self.banner_labels[i].set_progress(1.0, show=True, checkmark=True)
                elif self._training_done:
                    self.banner_labels[i].set_progress(1.0, show=True, checkmark=True)

        self._update_page_info()


def _show_mode_dialog(app):
    screen = app.primaryScreen()
    geo = screen.availableGeometry() if screen else None
    sw = geo.width() if geo else 1920
    sh = geo.height() if geo else 1080
    ui_scale = max(min(sw / 1920, sh / 1080), 1.0)
    s = min(ui_scale, 1.4) * 1.1

    dlg_w = max(int(sw * 0.32), 420)
    dlg_h = max(int(sh * 0.32), 300)

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

    dlg = QDialog()
    dlg.setWindowTitle("旗帜训练工具 v0.5 beta1")
    dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
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
    layout.addLayout(btn_row)

    if dlg.exec_() == QDialog.Accepted:
        return (train_mode, debug_mode)
    return None


class LoadingWidget(QWidget):
    def __init__(self, training_mode, ui_scale):
        super().__init__()
        self._progress = 0.0
        self._status_text = "正在初始化..."
        self._title_text = "旗帜训练工具"
        self._mode_text = "普通模式" if training_mode == "normal" else "PEFT模式"
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
        title_font_obj.setPixelSize(title_fs)
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


def _show_loading_screen(app, session_dir, training_mode, lock_file=None, debug_mode=False):
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
    if debug_mode:
        cmd.append("--debug")
        # 强制创建新控制台窗口，确保命令提示符可见
        proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        proc = subprocess.Popen(cmd, stderr=open(err_log, "w", encoding="utf-8"))

    if lock_file:
        try:
            with open(lock_file, "w") as f:
                f.write(str(proc.pid))
        except Exception:
            pass

    s = _get_ui_scale(app)

    screen = app.primaryScreen()
    geo = screen.availableGeometry() if screen else None
    sw = geo.width() if geo else 1920
    sh = geo.height() if geo else 1080

    lw = max(int(sw * 0.45), 600)
    lh = max(int(sh * 0.4), 400)

    loader = QWidget()
    loader.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    loader.setGeometry((sw - lw) // 2, (sh - lh) // 2, lw, lh)
    loader.closeEvent = lambda e: e.ignore()
    loader.setAutoFillBackground(True)

    # 加载条窗口也应用 DWM 深色标题栏（虽然是 FramelessWindowHint，但保险起见）
    _startup_theme = resolve_theme(SettingsManager().get("theme", "light"))
    apply_dwm_dark_mode(loader, _startup_theme == "dark")

    loader_layout = QVBoxLayout(loader)
    loader_layout.setContentsMargins(0, 0, 0, 0)

    circular_progress = LoadingWidget(training_mode, s)
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

    def _read_progress():
        tp = os.path.join(session_dir, ".trainer_progress")
        ip = os.path.join(session_dir, ".importer_progress")
        tval, tstatus = 0.0, ""
        ival, istatus = 0.0, ""
        try:
            if os.path.exists(tp):
                with open(tp, "r", encoding="utf-8") as f:
                    lines = f.read().strip().split("\n")
                    tval = float(lines[0])
                    if len(lines) > 1:
                        tstatus = lines[1]
        except Exception:
            pass
        try:
            if os.path.exists(ip):
                with open(ip, "r", encoding="utf-8") as f:
                    lines = f.read().strip().split("\n")
                    ival = float(lines[0])
                    if len(lines) > 1:
                        istatus = lines[1]
        except Exception:
            pass
        combined = max(tval, ival)
        status = tstatus if tval >= ival else istatus
        return combined, status

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

        if proc.poll() is not None and proc.returncode != 0 and not ready_detected[0]:
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
            _remove_instance_lock(lock_file)
            msg = f"训练器进程异常退出（返回码: {proc.returncode}）"
            if err_msg:
                msg += f"\n\n错误信息:\n{err_msg}"
            _show_error_popup("启动失败", msg)
            sys.exit(1)
            return

        trainer_ready_file = os.path.join(session_dir, ".trainer_ready")
        importer_ready_file = os.path.join(session_dir, ".importer_ready")
        if os.path.exists(trainer_ready_file) and os.path.exists(importer_ready_file):
            ready_detected[0] = True

        real_progress, real_status = _read_progress()

        if ready_detected[0]:
            if ready_time[0] is None:
                ready_time[0] = time.time()
            ready_elapsed = time.time() - ready_time[0]
            progress = min(max(real_progress, 0.70) + ready_elapsed / 0.3 * 0.30, 1.0)
            if progress >= 1.0:
                loader_done[0] = True
                try:
                    with open(os.path.join(session_dir, ".loading_done"), "w") as f:
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
            try:
                with open(os.path.join(session_dir, ".loading_done"), "w") as f:
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
        proc.wait()
    _remove_instance_lock(lock_file)
    sys.exit(0)


def main():
    # 非 debug 模式下把 stdout 重定向到 log 目录日志文件
    # .pyw 模式下 stdout 为 None，print 会报 OSError
    if "--debug" not in sys.argv:
        try:
            _app_dir = os.path.dirname(os.path.abspath(__file__))
            _log_dir = os.path.join(_app_dir, "log")
            os.makedirs(_log_dir, exist_ok=True)
            sys.stdout = open(os.path.join(_log_dir, "trainer_stdout.log"),
                              "a", encoding="utf-8", buffering=1)
        except Exception:
            try:
                sys.stdout = open(os.devnull, "w")
            except Exception:
                pass

    _startup_theme = SettingsManager().get("theme", "light")

    app = QApplication(sys.argv)
    app.setApplicationName("训练工具 v0.5 beta1")
    app.setDesktopFileName("训练工具 v0.5 beta1")
    app.setFont(QFont("Microsoft YaHei UI", app.font().pointSize()))

    apply_theme(app, _startup_theme)

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
        hw_thread = HardwareDetectThread()
        hw_thread.result_ready.connect(lambda hw: _on_startup_hw_detected(hw, from_cache=False))
        hw_thread.start()

    def _global_excepthook(exc_type, exc_value, exc_tb):
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        if not _training_error_suppressed:
            _show_error_popup("程序异常", f"旗帜训练工具发生未处理的错误:\n\n{tb_str[-800:]}")
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _global_excepthook

    training_mode = "normal"
    session_dir = None

    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--training-mode" and i + 1 < len(sys.argv):
            training_mode = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--session-dir" and i + 1 < len(sys.argv):
            session_dir = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--data" and i + 1 < len(sys.argv):
            i += 2
        else:
            i += 1

    if "--left-half" in sys.argv:
        _create_instance_lock()
        debug_mode = "--debug" in sys.argv
        window = MainWindow(training_mode=training_mode, session_dir=session_dir)
        print(f"[训练器] session_dir = {session_dir}")

        if training_mode == "peft":
            window.status_label.setText("当前模式: PEFT（参数高效微调）")
        else:
            window.status_label.setText("当前模式: 普通（全量训练）")

        if "--data" in sys.argv:
            data_idx = sys.argv.index("--data")
            if data_idx + 1 < len(sys.argv):
                window.load_data_from_file(sys.argv[data_idx + 1])

        # 延迟到模型加载完成（或失败）后再显示窗口 + snap + 启动导入器
        # 避免窗口过早显示导致 snap 自动布局被破坏
        def _after_model_loaded():
            window._apply_layout()
            # restore_layout 开启时不恢复保存的位置（用默认左半最小尺寸）
            restore_layout = SettingsManager().get("restore_layout", True)
            restored = (not restore_layout) and window._restore_window_geometry()
            window.show()
            QApplication.processEvents()

            hwnd = int(window.winId())
            # 自动布局开启时总是 snap 到左侧；
            # 自动布局关闭时：restore_layout 关闭且已恢复保存位置用保存位置，否则左半中心最小尺寸
            auto_layout = SettingsManager().get("auto_layout", True)
            if auto_layout:
                _minimize_existing_windows()
                window.resize(window.minimumSize())
                _double_snap(hwnd, "left")
                _force_activate(hwnd, window)
            elif restored and not _is_window_snapped(hwnd):
                _force_activate(hwnd, window)
            else:
                # 非snap模式：窗口放屏幕左半中心，使用最小尺寸
                _minimize_existing_windows()
                screen = QApplication.primaryScreen()
                if screen:
                    sg = screen.availableGeometry()
                    min_sz = window.minimumSize()
                    half_w = sg.width() // 2
                    x = sg.x() + max(0, (half_w - min_sz.width()) // 2)
                    y = sg.y() + max(0, (sg.height() - min_sz.height()) // 2)
                    window.resize(min_sz)
                    window.move(x, y)
                _force_activate(hwnd, window)

            if session_dir:
                window._write_progress(0.65, "正在调整训练器窗口布局...")
                ready_file = os.path.join(session_dir, ".trainer_ready")
                try:
                    with open(ready_file, "w") as f:
                        f.write("ready")
                except Exception:
                    pass

            ctypes.windll.user32.AllowSetForegroundWindow(-1)

            script_dir = os.path.dirname(os.path.abspath(__file__))
            importer_path = os.path.join(script_dir, "importer.pyw")
            # 调试模式下将 pythonw.exe 转为 python.exe，让导入器继承训练器的控制台（共用一个命令提示符）
            importer_exe = sys.executable
            if debug_mode:
                exe_lower = importer_exe.lower()
                if exe_lower.endswith("pythonw.exe"):
                    importer_exe = importer_exe[:-5] + ".exe"
                elif exe_lower.endswith("pythonw"):
                    importer_exe = importer_exe[:-1]
            cmd = [
                importer_exe, importer_path,
                "--training-mode", training_mode,
                "--right-half"
            ]
            if session_dir:
                cmd.extend(["--session-dir", session_dir])
            if debug_mode:
                cmd.append("--debug")
            # 不创建新控制台：调试模式下导入器继承训练器的控制台，共用一个命令提示符
            subprocess.Popen(cmd)
            # 启动导入器后立即写入进度，填补导入器 UI 初始化期间的空白
            if session_dir:
                window._write_progress(0.72, "正在启动导入器模块...")

        window._after_model_loaded = _after_model_loaded

        # 启动后检测自动保存文件：等待两个窗口都布局完成后再弹窗
        from PyQt5.QtCore import QTimer as _QTimer
        def _wait_both_windows_ready():
            """轮询等待训练器和导入器窗口都就绪后再检测自动保存。"""
            _sd = getattr(window, "_session_dir", None)
            if _sd:
                _tr = os.path.join(_sd, ".trainer_ready")
                _ir = os.path.join(_sd, ".importer_ready")
                if os.path.exists(_tr) and os.path.exists(_ir):
                    # 两窗口都就绪，再等 500ms 让窗口渲染完成
                    _QTimer.singleShot(500, window._check_auto_save_restore)
                    return
            # 未就绪，继续轮询
            _QTimer.singleShot(200, _wait_both_windows_ready)
        _wait_both_windows_ready()

        sys.exit(app.exec_())

    is_restart = "--restart" in sys.argv

    # 互斥检查：逆向器运行中则阻拦
    if _check_reverser_running():
        QMessageBox.critical(None, "启动限制",
            "旗帜印染逆向器正在运行\n请先关闭后再启动旗帜训练工具")
        sys.exit(0)

    if not is_restart:
        lock_file = _acquire_instance_slot()
        if lock_file is None:
            max_inst = _get_max_instances()
            QMessageBox.critical(None, "启动限制",
                f"旗帜训练工具已达到最大启动数量限制（{max_inst}个实例）\n请先关闭已运行的实例后再试")
            sys.exit(0)
    else:
        lock_file = _create_instance_lock()

    _minimize_existing_windows()

    if is_restart:
        # 重启模式：直接从参数获取模式
        debug_mode = "--debug" in sys.argv
        if training_mode not in ("normal", "peft"):
            training_mode = "normal"
    else:
        # 直接进入加载条，跳过模式选择界面
        # 从配置读取 debug_mode（start.pyw 不会传递 --debug 参数）
        debug_mode = "--debug" in sys.argv or bool(SettingsManager().get("debug_mode", False))
        if training_mode not in ("normal", "peft"):
            training_mode = "normal"

    session_dir = os.path.join(tempfile.gettempdir(), f"banner_trainer_{uuid.uuid4().hex[:8]}")
    os.makedirs(session_dir, exist_ok=True)

    _show_loading_screen(app, session_dir, training_mode, lock_file, debug_mode)


if __name__ == "__main__":
    main()
