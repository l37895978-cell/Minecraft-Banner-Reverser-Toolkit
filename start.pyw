"""我的世界旗帜逆向套件启动器

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
# 软件渲染：强制 Qt 走 CPU 软件渲染，兼容自动化 agent（截图/OCR/坐标点击）
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
# pythonw.exe 启动时 stdout/stderr 为 None，必须最早修复，否则任何 print/write 都会崩溃
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
# 防污染系统 Python：优先从安装目录的 Lib/site-packages 加载包
# 安装器用 pip install --target 把包装到这里，不碰系统 site-packages
# torch 优先级：安装目录有 torch 时用安装目录的（用户选择的具体版本）；
#               安装目录无 torch 时回退到系统 Python 的（如用户自己装的 CUDA 版本）
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
    _has_vendor_torch = os.path.isdir(os.path.join(_VENDOR_PKGS, "torch"))
    if _has_vendor_torch:
        # 安装目录有 torch（安装器按用户选择装的），优先用安装目录的
        sys.path.insert(0, _VENDOR_PKGS)
    else:
        # 安装目录无 torch（用户系统已有匹配的 torch，安装器跳过了）
        # 让系统 Python 的 torch 优先
        sys.path.append(_VENDOR_PKGS)

# Qt 平台插件引导：原版 DATA_start.pyw 真实搜索顺序（先 vendor → 再 site-packages 官方位置）
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

import json
import glob
import time
import ctypes
import tempfile
import subprocess

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QPushButton,
    QVBoxLayout, QHBoxLayout, QLabel, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon

from utils.settings_manager import apply_dwm_dark_mode, apply_theme, resolve_theme, report_error, MessageBox


# ===== 路径工具 =====
def _app_dir():
    """返回程序根目录（外部文件所在目录）。

    打包后（PyInstaller onefile）：__file__ 在 sys._MEIPASS 临时解压目录，
    而外部文件（dml_env、trainer.pyw、bdor.pyw 等）在 exe 同目录。
    非打包模式：__file__ 的上级目录即程序根目录。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _resource_path(*parts):
    """定位只读资源（images 等），先查 exe 同目录，再查 _MEIPASS。"""
    # 1. exe 同目录（外置资源）
    ext = os.path.join(_app_dir(), *parts)
    if os.path.exists(ext):
        return ext
    # 2. _MEIPASS（打包内置资源）
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            mp = os.path.join(meipass, *parts)
            if os.path.exists(mp):
                return mp
    # 3. 回退到 exe 同目录路径（即使不存在，保持原行为）
    return ext


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
_PATCH_MUTEX_NAME = "Global\\BannerToolPatchToolSingleInstance"
_TEST_SHM_NAME = "BannerWeaveReverser_Test_Mutex"  # test.pyw 的 QSharedMemory 单实例名


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


def _check_patch_tool_running():
    """检查补丁工具是否在运行（patch_tool.pyw 持有同名 Mutex）。"""
    return _check_mutex_exists(_PATCH_MUTEX_NAME)


def _check_test_running():
    """检查系统测试是否在运行（test.pyw 持有 QSharedMemory 单实例）。"""
    try:
        from PyQt5.QtCore import QSharedMemory
        shm = QSharedMemory(_TEST_SHM_NAME)
        attached = shm.attach()
        if attached:
            shm.detach()
        return attached
    except Exception:
        return False


def _minimize_help_windows():
    """最小化所有帮助窗口（通过枚举窗口查找标题匹配的窗口）。"""
    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    SW_MINIMIZE = 6
    help_titles = ["我的世界旗帜逆向套件", "旗帜训练工具 — 使用说明", "旗帜训练工具 - 使用说明"]

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


def _cleanup_stale_locks():
    """启动时清理所有过期的锁文件（进程已死但锁文件残留）。"""
    for pattern in (_TRAINER_LOCK_PATTERN, _REVERSER_LOCK_PREFIX + "*.lock"):
        lock_files = glob.glob(os.path.join(tempfile.gettempdir(), pattern))
        for lf in lock_files:
            try:
                with open(lf, "r") as f:
                    content = f.read()
                pid, create_time = _parse_lock_content(content)
                if pid <= 0:
                    os.remove(lf)
                    continue
                if not _is_process_alive_with_create_time(pid, create_time):
                    os.remove(lf)
            except Exception:
                try:
                    os.remove(lf)
                except Exception:
                    pass


def _kill_stale_trainer_processes():
    """杀死残留的训练器/导入器进程（上次崩溃留下的僵尸进程）。

    用 taskkill /F /T 强杀进程树（trainer + importer 子进程），
    然后清理对应的锁文件。
    """
    for _ in range(5):  # 最多尝试 5 次，防止多个残留实例
        running, pid = _check_trainer_running()
        if not running or not pid:
            break
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10, capture_output=True)
        except Exception:
            pass
        # 清理该 PID 的锁文件
        lock_pattern = os.path.join(tempfile.gettempdir(), f"banner_group_lock_{pid}.lock")
        for lf in glob.glob(lock_pattern):
            try:
                os.remove(lf)
            except Exception:
                pass
        time.sleep(0.15)
    # 最终清理所有过期锁文件
    _cleanup_stale_locks()


def _check_trainer_running():
    """检查训练器/导入器是否在运行（PID + 创建时间双重验证，防止 PID 复用误判）。"""
    lock_files = glob.glob(os.path.join(tempfile.gettempdir(), _TRAINER_LOCK_PATTERN))
    for lf in lock_files:
        try:
            with open(lf, "r") as f:
                content = f.read()
            pid, create_time = _parse_lock_content(content)
            if pid <= 0:
                continue
            if _is_process_alive_with_create_time(pid, create_time):
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
    """检查旗帜识别器是否在运行（PID + 创建时间双重验证，防止 PID 复用误判）。"""
    lock_files = glob.glob(os.path.join(tempfile.gettempdir(), _REVERSER_LOCK_PREFIX + "*.lock"))
    for lf in lock_files:
        try:
            with open(lf, "r") as f:
                content = f.read()
            pid, create_time = _parse_lock_content(content)
            if pid <= 0:
                continue
            if _is_process_alive_with_create_time(pid, create_time):
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
        config_path = os.path.join(_app_dir(), "config", "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return resolve_theme(data.get("theme", "light"))
    except Exception:
        pass
    return "light"


def _detect_scale():
    """原版 DATA_start.pyw 真实缩放算法：ui_scale 下限 = 1.0（不是 0.85）。"""
    screen = QApplication.primaryScreen()
    geo = screen.availableGeometry() if screen else None
    sw = geo.width() if geo else 1920
    sh = geo.height() if geo else 1080
    ui_scale = max(min(sw / 1920, sh / 1080), 1.0)
    return min(ui_scale * 1.25, 2.5)


def _find_pythonw():
    """定位系统 pythonw.exe（外壳用，只需 PyQt5）。

    查找顺序：
    0. sys.executable — 当前运行 start.pyw 的 Python（已验证能加载 PyQt5，最可靠）
    1. PATH 中的 pythonw/python（跳过 WindowsApps 桩文件，验证 PyQt5）
    2. 注册表扫描（官方安装器写入，覆盖 PATH 未配置场景，验证 PyQt5）
    3. 常见安装路径（验证 PyQt5）
    4. sys.executable 兜底
    """
    base = _app_dir()
    _vendor = os.path.join(base, "Lib", "site-packages")

    def _pyqt5_ok(exe):
        """验证指定解释器能加载 PyQt5（vendor 优先，回退系统 site-packages）。"""
        try:
            r = subprocess.run(
                [exe, "-c",
                 f"import sys; sys.path.insert(0, r'{_vendor}'); "
                 f"from PyQt5.QtWidgets import QApplication; print('ok')"],
                capture_output=True, text=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW)
            return r.returncode == 0 and 'ok' in r.stdout
        except Exception:
            return False

    # 0. 优先使用当前运行的 Python（start.pyw 能启动说明此 Python 已成功加载 PyQt5）
    cur = sys.executable
    if cur and os.path.isfile(cur) and "WindowsApps" not in cur:
        if os.path.basename(cur).lower() == "python.exe":
            pw = os.path.join(os.path.dirname(cur), "pythonw.exe")
            if os.path.exists(pw):
                return pw
        return cur
    # 1. 系统 pythonw.exe（跳过 Windows Store 的 WindowsApps 桩文件，验证 PyQt5）
    import shutil
    sys_py = shutil.which("pythonw") or shutil.which("python")
    if sys_py and "WindowsApps" not in sys_py and _pyqt5_ok(sys_py):
        return sys_py
    # 2. 注册表扫描（官方安装器写入，覆盖 PATH 未配置场景，验证 PyQt5）
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                core = winreg.OpenKey(hive, r"Software\Python\PythonCore")
                i = 0
                while True:
                    try:
                        ver = winreg.EnumKey(core, i)
                        i += 1
                        if not ver.startswith("3."):
                            continue
                        try:
                            ik = winreg.OpenKey(core, ver + r"\InstallPath")
                            try:
                                exe_path, _ = winreg.QueryValueEx(ik, "ExecutablePath")
                            except OSError:
                                exe_path, _ = winreg.QueryValueEx(ik, None)
                            winreg.CloseKey(ik)
                        except OSError:
                            continue
                        if exe_path:
                            pw_dir = os.path.dirname(exe_path) if os.path.isfile(exe_path) else exe_path
                            pw = os.path.join(pw_dir, "pythonw.exe")
                            if os.path.exists(pw) and _pyqt5_ok(pw):
                                return pw
                    except OSError:
                        break
                winreg.CloseKey(core)
            except OSError:
                pass
    except Exception:
        pass
    # 3. 常见安装路径（覆盖 3.10~3.13，按版本降序优先取高版本，验证 PyQt5）
    la = os.environ.get("LOCALAPPDATA", "")
    for ver_code in ("Python313", "Python312", "Python311", "Python310"):
        for base_dir in (
            os.path.join(la, "Programs", "Python", ver_code, "pythonw.exe"),
            fr"C:\{ver_code}\pythonw.exe",
        ):
            if os.path.exists(base_dir) and _pyqt5_ok(base_dir):
                return base_dir
    # 4. 回退到 sys.executable（开发模式）
    return sys.executable


def _find_pythonw_for_torch():
    """为需要 torch 的程序（bdor/trainer/importer）选择正确的 pythonw.exe。

    【双环境隔离原则：UI 渲染固定由主 Python 环境（3.13+）执行】
    三种硬件模式下，启动 UI 程序的解释器永不改变：统一用【主环境 pythonw】
    （主环境安装 PyQt5 + CUDA/CPU 版 Torch；DirectML 模式下 AI 运算在程序内
    通过 subprocess 调用 dml_env/python.exe 执行，UI 层依然由主环境渲染）。

    => 本函数直接等价于 _find_pythonw()。train_arch 设置仅用于程序内部决定
    AI 运算走哪套 Torch（CUDA/CPU 直接 import；DirectML spawn 子进程），
    不再决定 pythonw.exe 的选择——防止用 dml_env 的 Python 3.10 去启动 UI。
    """
    return _find_pythonw()


def _auto_repair_train_arch():
    """启动时自动修正 train_arch 与已安装架构不一致的问题。

    背景：早期安装包不写 config.json，train_arch 沿用 settings_manager 默认
    "cuda"；装了 DirectML/CPU 的用户 config 却仍是 cuda → 训练器/识别器
    一启动就报"CUDA 模式但无显卡/无 CUDA torch"，且设置打不开时用户无法自救。
    这里检测：train_arch 不在 install_components.json 声明的 archs 中时，
    自动改为 archs 中优先级最高的（directml > cuda > cpu）并写回 config.json
    （只改 train_arch 一个字段，保留用户其余设置）。
    """
    try:
        base = _app_dir()
        comp = os.path.join(base, "install_components.json")
        if not os.path.isfile(comp):
            return
        with open(comp, encoding="utf-8-sig") as f:
            data = json.load(f) or {}
        archs = data.get("archs") or []
        if not archs:
            return
        cfg = os.path.join(base, "config", "config.json")
        if not os.path.isfile(cfg):
            return  # 尚无 config，settings_manager 首次推断会处理
        with open(cfg, encoding="utf-8-sig") as f:
            cdata = json.load(f) or {}
        cur = cdata.get("train_arch", "")
        if cur in archs:
            return  # 当前架构已在已安装列表中，无需修正
        pick = next((a for a in ("directml", "cuda", "cpu") if a in archs), archs[0])
        cdata["train_arch"] = pick
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump(cdata, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _check_selected_arch_ready():
    """根据当前 config.json 的 train_arch 设置，检查对应后端是否已就绪。

    返回 (ok: bool, msg: str)：
      - ok=True：后端就绪，可以启动训练器/识别器
      - ok=False：后端缺失，msg 是给用户看的中文错误提示
    """
    # 1. 读取当前选择的架构
    train_arch = "cpu"
    try:
        config_path = os.path.join(_app_dir(), "config", "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            train_arch = data.get("train_arch", "cpu")
    except Exception:
        pass

    base = _app_dir()
    # 2. CUDA / CPU 模式：必须主环境内有 Torch
    if train_arch in ("cuda", "cpu"):
        has_torch = False
        try:
            import importlib.util as _ils
            has_torch = _ils.find_spec("torch") is not None
        except Exception:
            has_torch = False
        if not has_torch:
            has_torch = os.path.isdir(os.path.join(base, "Lib", "site-packages", "torch"))
        if not has_torch:
            hint = "CUDA 版 torch" if train_arch == "cuda" else "CPU 版 torch"
            return False, (
                f"当前选择的是【{train_arch.upper()} 模式】，但主环境未安装 {hint}。\n\n"
                f"解决方案（任选其一）：\n"
                f"1. 运行安装包 → 维护模式 → 安装库 → 安装对应 Torch；\n"
                f"2. 打开【设置】→ 切换到【DirectML】模式（使用解压好的 dml_env 便携环境）。"
            )
        # CUDA 模式额外检查是否有 NVIDIA 显卡
        if train_arch == "cuda":
            try:
                import subprocess as _sp
                _r = _sp.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                             capture_output=True, timeout=5,
                             creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
                if _r.returncode != 0 or not _r.stdout.strip():
                    return False, (
                        "当前选择的是【CUDA 模式】，但未检测到 NVIDIA 显卡。\n\n"
                        "请打开【设置】→ 切换到【CPU】或【DirectML】模式。"
                    )
            except Exception:
                pass
        return True, ""

    # 3. DirectML 模式：必须 dml_env/python.exe 存在
    if train_arch == "directml":
        dml_py = os.path.join(base, "dml_env", "python.exe")
        if not os.path.isfile(dml_py):
            return False, (
                "当前选择的是【DirectML 模式】，但未检测到 dml_env 便携环境。\n\n"
                "解决方案：\n"
                "运行安装包 → 维护模式 → 安装库 → 安装 DirectML 便携环境（1.8GB）。"
            )
        return True, ""

    # 4. 未知架构：提示重进设置
    return False, (
        f"当前 train_arch = {train_arch!r} 不是合法值。\n\n"
        f"请打开【设置】→ 重新选择训练架构（CUDA / DirectML / CPU）。"
    )


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
        icon_size = int(64 * scale)
        layout.setSpacing(int(6 * scale))
        layout.setContentsMargins(int(16 * scale), int(20 * scale),
                                  int(16 * scale), int(16 * scale))

        # 占位符图标
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(icon_size, icon_size)
        icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        accent = '#4fc3f7' if is_dark else '#1a73e8'
        icon_label.setText(icon_char)
        icon_label.setStyleSheet(f"font-size: {icon_size}px; color: {accent}; background: transparent; border: none;")
        layout.addWidget(icon_label)
        self._icon_label = icon_label

        # 标题（TileButton.title = 二级 section 标题，比正文大 → 15→17）
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        title_label.setStyleSheet(f"font-size: {max(int(15 * scale), 13)}px; font-weight: bold; color: {'#e0e0e0' if is_dark else '#1a1a1a'}; background: transparent; border: none;")
        layout.addWidget(title_label)
        self._title_label = title_label

        # 副标题（TileButton.subtitle = 描述级，应最小 → 11→10）
        sub_label = QLabel(subtitle)
        sub_label.setAlignment(Qt.AlignCenter)
        sub_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        sub_label.setStyleSheet(f"font-size: {max(int(11 * scale), 10)}px; color: {'#888888' if is_dark else '#666666'}; background: transparent; border: none;")
        layout.addWidget(sub_label)
        self._sub_label = sub_label

        self._apply_style()

    def _set_dark(self, is_dark):
        """主题切换后刷新本按钮的全部颜色（图标/标题/副标题/边框背景）。"""
        self._is_dark = is_dark
        scale = self._scale
        accent = '#4fc3f7' if is_dark else '#1a73e8'
        self._icon_label.setStyleSheet(
            f"font-size: {int(56 * scale)}px; color: {accent}; background: transparent; border: none;")
        self._title_label.setStyleSheet(
            f"font-size: {max(int(15 * scale), 13)}px; font-weight: bold; "
            f"color: {'#e0e0e0' if is_dark else '#1a1a1a'}; background: transparent; border: none;")
        self._sub_label.setStyleSheet(
            f"font-size: {max(int(11 * scale), 10)}px; "
            f"color: {'#888888' if is_dark else '#666666'}; background: transparent; border: none;")
        self._apply_style()

    def _apply_style(self):
        s = self._scale
        radius = int(10 * s)
        if self._is_dark:
            bg = "#2d2d2d"
            bg_hover = "#383838"
            border = "#404040"
            border_hover = "#4fc3f7"
            bg_disabled = "#252525"
            color_disabled = "#666666"
            border_disabled = "#2a2a2a"
        else:
            bg = "#ffffff"
            bg_hover = "#f0f6ff"
            border = "#d0d0d0"
            border_hover = "#1a73e8"
            bg_disabled = "#f0f0f0"
            color_disabled = "#aaaaaa"
            border_disabled = "#e0e0e0"
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
            QPushButton:disabled {{
                background-color: {bg_disabled};
                color: {color_disabled};
                border: 1px solid {border_disabled};
            }}
        """)


class StartWindow(QMainWindow):
    """启动器主窗口。"""

    def __init__(self, scale, theme):
        super().__init__()
        self._scale = scale
        self._theme = theme
        self._is_dark = (theme == "dark")

        self.setWindowTitle("我的世界旗帜逆向套件")

        # 窗口图标（与桌面快捷方式一致，使用 tookit.ico）
        _icon_path = _resource_path("images", "icons", "tookit.ico")
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))

        # 窗口尺寸
        win_w = int(580 * scale)
        win_h = int(690 * scale)
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
        title_label = QLabel("我的世界旗帜逆向套件")
        title_label.setAlignment(Qt.AlignCenter)
        # 用户反馈 start.pyw "主次感有问题"：拉大级差
        #   H1 主标题 24（保持最突出）
        title_label.setStyleSheet(f"font-size: {max(int(24 * scale), 20)}px; font-weight: bold; color: {'#e0e0e0' if self._is_dark else '#1a1a1a'}; background: transparent;")
        main_layout.addWidget(title_label)
        self._title_label = title_label

        sub_label = QLabel("选择要启动的功能")
        sub_label.setAlignment(Qt.AlignCenter)
        # 副标题 13→12（降一级，明显次之于 H1）
        sub_label.setStyleSheet(f"font-size: {max(int(13 * scale), 12)}px; color: {'#888888' if self._is_dark else '#666666'}; background: transparent;")
        main_layout.addWidget(sub_label)
        self._sub_label = sub_label

        main_layout.addSpacing(int(8 * scale))

        # 四宫格
        grid_container = QWidget()
        grid_layout = QGridLayout(grid_container)
        grid_layout.setSpacing(int(12 * scale))
        grid_layout.setContentsMargins(0, 0, 0, 0)

        tiles_config = [
            ("旗帜训练器", "训练 AI 模型", "☰", self._launch_trainer, 0, 0, "_tile_trainer"),
            ("旗帜识别器", "逆向识别旗帜", "◎", self._launch_recognizer, 0, 1, "_tile_recognizer"),
            ("设置", "配置工具参数", "⚙", self._launch_settings, 1, 0, "_tile_settings"),
            ("帮助", "查看使用说明", "?", self._launch_help, 1, 1, "_tile_help"),
        ]

        for title, subtitle, icon_char, callback, row, col, attr_name in tiles_config:
            tile = _TileButton(title, subtitle, icon_char, scale, self._is_dark)
            tile.clicked.connect(callback)
            setattr(self, attr_name, tile)
            grid_layout.addWidget(tile, row, col)

        # 组件检测：缺失则置灰对应按钮（设置和帮助始终可用）
        base = _app_dir()
        installed = {
            "trainer": os.path.exists(os.path.join(base, "trainer.pyw")),
            "recognizer": os.path.exists(os.path.join(base, "bdor.pyw")),
        }
        # 读取 install_components.json 的 purpose（旧适配：json 可能过时，
        # 如记 use 但磁盘已有 trainer.pyw，此时以磁盘文件为准，不禁用训练器；
        # 仅当 trainer.pyw 确实不存在时，json purpose=use 才作兜底禁用）
        _comp_path = os.path.join(base, "install_components.json")
        if not installed["trainer"]:
            if os.path.exists(_comp_path):
                try:
                    import json as _json
                    with open(_comp_path, encoding="utf-8") as _f:
                        _comp = _json.load(_f)
                    if _comp.get("purpose") == "use":
                        installed["trainer"] = False
                except Exception:
                    pass
        # 开发模式下读取 Demo 安装器的配置（模拟选择性安装，同样磁盘文件优先）
        dev_cfg_path = os.path.join(base, "config", "dev_install_config.json")
        if not installed["trainer"]:
            if os.path.exists(dev_cfg_path):
                try:
                    import json as _json
                    with open(dev_cfg_path, encoding="utf-8") as _f:
                        _dev_cfg = _json.load(_f)
                    if _dev_cfg.get("purpose") == "use":
                        installed["trainer"] = False  # 模拟未安装训练器
                except Exception:
                    pass
        if not installed["trainer"]:
            self._tile_trainer.setEnabled(False)
            self._tile_trainer.setToolTip("未安装训练器组件")
        if not installed["recognizer"]:
            self._tile_recognizer.setEnabled(False)
            self._tile_recognizer.setToolTip("未安装识别器组件")

        main_layout.addWidget(grid_container, 1)

        # 常用工具（四宫格下方小按钮：补丁工具 / 系统测试）
        self._tool_buttons = []
        tool_row = QHBoxLayout()
        tool_row.setSpacing(int(10 * scale))
        tool_row.addStretch()
        self._btn_patch_tool = self._make_tool_button("补丁工具", "✚", self._launch_patch_tool, scale)
        self._btn_test = self._make_tool_button("系统测试", "✔", self._launch_test, scale)
        tool_row.addWidget(self._btn_patch_tool)
        tool_row.addWidget(self._btn_test)
        tool_row.addStretch()
        main_layout.addLayout(tool_row)

        # 组件检测：补丁工具/测试按钮缺失则置灰
        if not os.path.exists(os.path.join(base, "patch_tool.pyw")):
            self._btn_patch_tool.setEnabled(False)
            self._btn_patch_tool.setToolTip("未安装补丁工具组件")
        if not os.path.exists(os.path.join(base, "test.pyw")):
            self._btn_test.setEnabled(False)
            self._btn_test.setToolTip("未安装测试组件")

        # 底部提示（辅助说明级 → 最小 11→9）
        hint_label = QLabel("启动后本窗口最小化，关闭程序后可恢复")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setStyleSheet(f"font-size: {max(int(11 * scale), 10)}px; color: {'#666666' if self._is_dark else '#999999'}; background: transparent;")
        main_layout.addWidget(hint_label)
        self._hint_label = hint_label

        # 应用窗口样式
        self._apply_window_style()

        # 轮询设置保存后的主题变更信号（设置点确定 → start 立即跟随深浅色）
        from PyQt5.QtCore import QTimer
        self._theme_timer = QTimer(self)
        self._theme_timer.timeout.connect(self._check_theme_signal)
        self._theme_timer.start(500)

    def _check_theme_signal(self):
        """检测设置保存后写入的主题信号文件，刷新本窗口深浅色。"""
        try:
            sig_path = os.path.join(tempfile.gettempdir(), "_banner_theme_changed")
            if not os.path.exists(sig_path):
                return
            with open(sig_path, "r", encoding="utf-8") as f:
                theme_val = f.read().strip()
            os.remove(sig_path)
        except Exception:
            return
        if theme_val:
            from utils.settings_manager import resolve_theme
            self._refresh_theme(resolve_theme(theme_val))

    def _refresh_theme(self, theme):
        """应用新主题到主窗口：全局调色板 + 背景 + 四宫格 + 底部提示 + 标题栏。"""
        if theme == self._theme:
            return
        self._theme = theme
        self._is_dark = (theme == "dark")
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        self._apply_window_style()
        # 主标题/副标题跟随主题变色（避免深背景深字/浅背景浅字导致不可见）
        s = self._scale
        tl = getattr(self, "_title_label", None)
        if tl is not None:
            tl.setStyleSheet(
                f"font-size: {max(int(24 * s), 20)}px; font-weight: bold; "
                f"color: {'#e0e0e0' if self._is_dark else '#1a1a1a'}; background: transparent;")
        sl = getattr(self, "_sub_label", None)
        if sl is not None:
            sl.setStyleSheet(
                f"font-size: {max(int(13 * s), 12)}px; "
                f"color: {'#888888' if self._is_dark else '#666666'}; background: transparent;")
        for _attr in ("_tile_trainer", "_tile_recognizer", "_tile_settings", "_tile_help"):
            _tile = getattr(self, _attr, None)
            if _tile is not None:
                _tile._set_dark(self._is_dark)
        for _tb in getattr(self, "_tool_buttons", []):
            self._apply_tool_style(_tb)
        _hl = getattr(self, "_hint_label", None)
        if _hl is not None:
            _hl.setStyleSheet(
                f"font-size: {max(int(11 * self._scale), 10)}px; "
                f"color: {'#666666' if self._is_dark else '#999999'}; background: transparent;")
        apply_dwm_dark_mode(self, self._is_dark)

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

    def _make_tool_button(self, text, icon_char, callback, scale):
        """创建常用工具小按钮（与四宫格同配色体系：蓝色图标 + 文字，更矮小）。"""
        btn = QPushButton()
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(int(34 * scale))
        btn.setMinimumWidth(int(110 * scale))
        # 图标 + 文字 水平布局（与四宫格一致的 accent 色图标）
        lay = QHBoxLayout(btn)
        lay.setContentsMargins(int(12 * scale), 0, int(12 * scale), 0)
        lay.setSpacing(int(5 * scale))
        lay.setAlignment(Qt.AlignCenter)
        ic = QLabel(icon_char)
        ic.setAlignment(Qt.AlignCenter)
        ic.setAttribute(Qt.WA_TransparentForMouseEvents)
        btn._icon = ic
        lay.addWidget(ic)
        tl = QLabel(text)
        tl.setAlignment(Qt.AlignCenter)
        tl.setAttribute(Qt.WA_TransparentForMouseEvents)
        btn._tlabel = tl
        lay.addWidget(tl)
        btn.clicked.connect(callback)
        self._tool_buttons.append(btn)
        self._apply_tool_style(btn)
        return btn

    def _apply_tool_style(self, btn):
        """应用工具按钮样式（深色/浅色自适应，随主题刷新）。"""
        s = self._scale
        if self._is_dark:
            bg, bg_hover, border, border_hover = "#2d2d2d", "#383838", "#404040", "#4fc3f7"
            fg, accent = "#e0e0e0", "#4fc3f7"
            bg_disabled, fg_disabled, border_disabled = "#252525", "#666666", "#2a2a2a"
        else:
            bg, bg_hover, border, border_hover = "#ffffff", "#f0f6ff", "#d0d0d0", "#1a73e8"
            fg, accent = "#1a1a1a", "#1a73e8"
            bg_disabled, fg_disabled, border_disabled = "#f0f0f0", "#aaaaaa", "#e0e0e0"
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {int(8 * s)}px;
            }}
            QPushButton:hover {{
                background-color: {bg_hover};
                border: 1px solid {border_hover};
            }}
            QPushButton:pressed {{
                background-color: {bg_hover};
                border: 1px solid {border_hover};
            }}
            QPushButton:focus {{
                border: 1px solid {border_hover};
            }}
            QPushButton:disabled {{
                background-color: {bg_disabled};
                border: 1px solid {border_disabled};
            }}
        """)
        ic = getattr(btn, "_icon", None)
        if ic is not None:
            ic.setStyleSheet(
                f"font-size: {max(int(14 * s), 12)}px; color: {accent}; "
                f"background: transparent; border: none;")
        tl = getattr(btn, "_tlabel", None)
        if tl is not None:
            tl.setStyleSheet(
                f"font-size: {max(int(12 * s), 11)}px; color: {fg}; "
                f"background: transparent; border: none;")

    def _ensure_other_closed(self, other_name, check_func):
        """确保另一个程序已关闭。如果在运行则提示用户确认关闭。

        返回 True 表示可以继续启动，False 表示取消。
        """
        running, pid = check_func()
        if not running:
            return True

        reply = MessageBox.question(self, "程序互斥",
            f"{other_name}正在运行。\n启动新程序前需要先关闭 {other_name}（关闭前会弹出保存确认）。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return False

        # 关闭另一个程序
        success = _close_program_by_pid(pid, timeout=60)
        if not success:
            MessageBox.warning(self, "关闭失败",
                f"等待 {other_name} 关闭超时。\n请手动关闭后重试。")
            return False

        # 再确认一次已经关闭
        running2, _ = check_func()
        if running2:
            MessageBox.warning(self, "关闭失败",
                f"{other_name} 仍在运行，无法启动新程序。")
            return False

        return True

    def _launch_trainer(self):
        """启动旗帜训练器（会自动联动导入器）。"""
        # 互斥检查：设置在运行则提醒
        if _check_settings_running():
            MessageBox.information(self, "请先完成设置",
                "设置窗口正在运行。\n请完成设置后再启动训练器。")
            return
        # 维护工具互斥：补丁/测试会改动程序文件，运行中则提醒先关闭
        if _check_patch_tool_running():
            MessageBox.information(self, "程序互斥",
                "补丁工具正在运行。\n请先关闭补丁工具后再启动训练器。")
            return
        if _check_test_running():
            MessageBox.information(self, "程序互斥",
                "系统测试正在运行。\n请先关闭系统测试后再启动训练器。")
            return
        # 杀死残留的训练器/导入器进程（上次崩溃留下的僵尸进程）
        _kill_stale_trainer_processes()
        # 互斥检查：识别器在运行则先关闭
        if not self._ensure_other_closed("旗帜识别器", _check_recognizer_running):
            return

        # 最小化帮助窗口（防止对加载的干扰）
        _minimize_help_windows()

        trainer_path = os.path.join(_app_dir(), "trainer.pyw")
        try:
            # 启动前最终校验：所选架构是否已就绪
            arch_ok, arch_msg = _check_selected_arch_ready()
            if not arch_ok:
                report_error("无法启动训练器", arch_msg, "启动器")
                return
            _pyw = _find_pythonw_for_torch()
            if not _pyw:
                report_error("无法启动训练器",
                    "未检测到可用的训练环境。\n\n"
                    "请在设置中选择已安装的训练架构（CUDA/DirectML/CPU），\n"
                    "或重新运行安装程序安装训练组件。", "启动器")
                return
            subprocess.Popen([_pyw, trainer_path, "--parent-pid", str(os.getpid())],
                             cwd=_app_dir())
            self.showMinimized()  # 启动后最小化
        except Exception as e:
            import traceback as _tb
            report_error("启动训练器失败",
                         f"{str(e)}\n\n--- Traceback ---\n{_tb.format_exc()}", "启动器")

    def _launch_recognizer(self):
        """启动旗帜识别器。"""
        # 互斥检查：设置在运行则提醒
        if _check_settings_running():
            MessageBox.information(self, "请先完成设置",
                "设置窗口正在运行。\n请完成设置后再启动识别器。")
            return
        # 维护工具互斥：补丁/测试会改动程序文件，运行中则提醒先关闭
        if _check_patch_tool_running():
            MessageBox.information(self, "程序互斥",
                "补丁工具正在运行。\n请先关闭补丁工具后再启动识别器。")
            return
        if _check_test_running():
            MessageBox.information(self, "程序互斥",
                "系统测试正在运行。\n请先关闭系统测试后再启动识别器。")
            return
        # 互斥检查：训练器在运行则先关闭
        if not self._ensure_other_closed("旗帜训练器", _check_trainer_running):
            return

        # 最小化帮助窗口（防止对加载的干扰）
        _minimize_help_windows()

        bdor_path = os.path.join(_app_dir(), "bdor.pyw")
        try:
            # 启动前最终校验：所选架构是否已就绪
            arch_ok, arch_msg = _check_selected_arch_ready()
            if not arch_ok:
                report_error("无法启动识别器", arch_msg, "启动器")
                return
            _pyw = _find_pythonw_for_torch()
            if not _pyw:
                report_error("无法启动识别器",
                    "未检测到可用的识别环境。\n\n"
                    "请在设置中选择已安装的训练架构（CUDA/DirectML/CPU），\n"
                    "或重新运行安装程序安装识别组件。", "启动器")
                return
            subprocess.Popen([_pyw, bdor_path], cwd=_app_dir())
            self.showMinimized()  # 启动后最小化
        except Exception as e:
            import traceback as _tb
            report_error("启动识别器失败",
                         f"{str(e)}\n\n--- Traceback ---\n{_tb.format_exc()}", "启动器")

    def _launch_settings(self):
        """启动设置窗口（单实例：已运行则恢复并跳转到通用页）。"""
        settings_path = os.path.join(_app_dir(), "utils", "settings_dialog.py")
        try:
            subprocess.Popen([_find_pythonw(), settings_path,
                              "--caller", "start", "--scale", str(self._scale)],
                             cwd=_app_dir())
        except Exception as e:
            import traceback as _tb
            report_error("启动设置失败",
                         f"{str(e)}\n\n--- Traceback ---\n{_tb.format_exc()}", "启动器")

    def _launch_help(self):
        """启动帮助窗口（特例：可与任何程序共存），跳转到概述章节。"""
        help_path = os.path.join(_app_dir(), "help.pyw")
        try:
            subprocess.Popen([_find_pythonw(), help_path, "--scale", str(self._scale), "--section", "overview"],
                             cwd=_app_dir())
        except Exception as e:
            import traceback as _tb
            report_error("启动帮助失败",
                         f"{str(e)}\n\n--- Traceback ---\n{_tb.format_exc()}", "启动器")

    def _launch_patch_tool(self):
        """启动补丁工具（patch_tool.pyw）。

        维护类工具互斥：会改动程序文件，需先关闭训练器/识别器，
        且与系统测试（同为文件操作）互斥。
        """
        if not self._ensure_other_closed("旗帜识别器", _check_recognizer_running):
            return
        if not self._ensure_other_closed("旗帜训练器", _check_trainer_running):
            return
        if _check_test_running():
            MessageBox.information(self, "程序互斥",
                "系统测试正在运行。\n请先关闭系统测试后再启动补丁工具。")
            return
        patch_path = os.path.join(_app_dir(), "patch_tool.pyw")
        try:
            subprocess.Popen([_find_pythonw(), patch_path], cwd=_app_dir())
        except Exception as e:
            import traceback as _tb
            report_error("启动补丁工具失败",
                         f"{str(e)}\n\n--- Traceback ---\n{_tb.format_exc()}", "启动器")

    def _launch_test(self):
        """启动系统测试（test.pyw GUI 诊断）。

        维护类工具互斥：会改动程序文件，需先关闭训练器/识别器，
        且与补丁工具（同为文件操作）互斥。
        """
        if not self._ensure_other_closed("旗帜识别器", _check_recognizer_running):
            return
        if not self._ensure_other_closed("旗帜训练器", _check_trainer_running):
            return
        if _check_patch_tool_running():
            MessageBox.information(self, "程序互斥",
                "补丁工具正在运行。\n请先关闭补丁工具后再启动系统测试。")
            return
        test_path = os.path.join(_app_dir(), "test.pyw")
        try:
            subprocess.Popen([_find_pythonw(), test_path], cwd=_app_dir())
        except Exception as e:
            import traceback as _tb
            report_error("启动系统测试失败",
                         f"{str(e)}\n\n--- Traceback ---\n{_tb.format_exc()}", "启动器")


def _start_error_monitor():
    """启动 error_reporter 后台监控进程，监控所有子程序的崩溃错误。"""
    try:
        _reporter = os.path.join(_app_dir(), "scripts", "error_reporter.pyw")
        _log_dir = os.path.join(_app_dir(), "log")
        if not os.path.isfile(_reporter):
            return
        subprocess.Popen(
            [_find_pythonw(), _reporter, "--monitor", "--parent-pid", str(os.getpid()), _log_dir],
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            cwd=_app_dir())
    except Exception:
        pass


def _ensure_shortcuts():
    """检测桌面/开始菜单快捷方式缺失时自动补全（路径自适应）。

    适用于整合包/免安装场景：套件解压到任意位置后首次运行本程序时，
    以自身所在目录为准创建正确路径的快捷方式；已存在则直接跳过。
    """
    try:
        import ctypes as _ct
        _b1 = _ct.create_unicode_buffer(260)
        _ct.windll.shell32.SHGetFolderPathW(None, 0x00, None, 0, _b1)  # CSIDL_DESKTOP
        desktop = _b1.value
        _b2 = _ct.create_unicode_buffer(260)
        _ct.windll.shell32.SHGetFolderPathW(None, 0x02, None, 0, _b2)  # CSIDL_PROGRAMS
        start_menu = _b2.value
    except Exception:
        return
    shortcut_dir = os.path.join(start_menu, "我的世界旗帜逆向套件")
    targets = [
        os.path.join(shortcut_dir, "我的世界旗帜逆向套件.lnk"),
        os.path.join(desktop, "我的世界旗帜逆向套件.lnk"),
    ]
    if all(os.path.isfile(t) for t in targets):
        return  # 快捷方式已存在，无需处理
    try:
        pythonw = _find_pythonw()
    except Exception:
        return
    if not pythonw or not os.path.isfile(pythonw):
        return
    app_dir = _app_dir()
    target_py = os.path.join(app_dir, "start.pyw")
    icon = os.path.join(app_dir, "images", "icons", "tookit.ico")
    if not os.path.isfile(target_py):
        return

    def _q(p):
        return "'" + str(p).replace("'", "''") + "'"

    try:
        if not os.path.isdir(shortcut_dir):
            os.makedirs(shortcut_dir, exist_ok=True)
        _icon_loc = _q(icon + ",0") if os.path.isfile(icon) else _q(pythonw + ",0")
        for lnk in targets:
            ps = ("$w=New-Object -ComObject WScript.Shell;"
                  "$s=$w.CreateShortcut(" + _q(lnk) + ");"
                  "$s.TargetPath=" + _q(pythonw) + ";"
                  "$s.Arguments=" + _q(target_py) + ";"
                  "$s.WorkingDirectory=" + _q(app_dir) + ";"
                  "$s.IconLocation=" + _icon_loc + ";"
                  "$s.Description='我的世界旗帜逆向套件';"
                  "$s.Save()")
            subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                            "-Command", ps],
                           creationflags=subprocess.CREATE_NO_WINDOW,
                           capture_output=True, timeout=15)
    except Exception:
        pass


def main():
    # 启动时清理过期锁文件（防止残留锁文件导致误判）
    _cleanup_stale_locks()
    # 自动修正 train_arch 与已安装架构不一致（旧安装包不写 config.json 的遗留问题）
    _auto_repair_train_arch()

    # 单实例限制
    if not _ensure_single_instance():
        ctypes.windll.user32.MessageBoxW(
            0, "我的世界旗帜逆向套件已经在运行，请先关闭已有的窗口。",
            "提示", 64  # MB_ICONINFORMATION
        )
        return

    # 启动 error_reporter 后台监控（监控所有子程序崩溃，套件退出后自动关闭）
    _start_error_monitor()

    # 软件渲染（必须在 QApplication 创建前设置）：保证 agent 截图稳定可识别
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
    app = QApplication(sys.argv)
    app.setApplicationName("我的世界旗帜逆向套件")
    app.setFont(QFont("Microsoft YaHei UI", app.font().pointSize()))

    # 统一弹窗图标：QMessageBox 系统弹窗图标 64px（250% 放大规律，与 error_reporter 等自定义弹窗一致）
    from PyQt5.QtWidgets import QProxyStyle, QStyle as _QStyle
    class _MsgBoxIconStyle(QProxyStyle):
        def pixelMetric(self, metric, option=None, widget=None):
            if metric == _QStyle.PM_MessageBoxIconSize:
                return 64
            return super().pixelMetric(metric, option, widget)
    app.setStyle(_MsgBoxIconStyle(app.style()))

    scale = _detect_scale()
    theme = _get_theme()
    apply_theme(app, theme)

    window = StartWindow(scale, theme)
    apply_dwm_dark_mode(window, theme == "dark")
    window.show()

    # 快捷方式缺失时自动补全（整合包/免安装场景；已存在则跳过，零开销）
    QTimer.singleShot(800, _ensure_shortcuts)

    exit_code = app.exec_()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
