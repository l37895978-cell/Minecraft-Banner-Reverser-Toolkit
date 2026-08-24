"""我的世界旗帜逆向套件 — 安装程序

参照 Python 官方安装包（.exe）样式：左侧侧图 + 右侧内容 + 底部按钮栏。

流程：
  初始化（硬件/软件环境检测 + 安装状态检测）
    ├─ 未安装 → 欢迎 → 使用声明 → 使用目的 → 库选择 → 安装 → 结束
    └─ 已安装 → 维护页（安装训练工具 / 文件修复 / 卸载）

侧图预留：images/banner/installer_banner.png（可替换为实际图片）

运行：python installer/demo_installer.pyw
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
# 早期异常捕获：在 PyQt5 等第三方库导入前生效，捕获导入/启动阶段的致命错误
def _early_crash_handler(exc_type, exc_value, exc_tb):
    import traceback as _tb_mod
    import subprocess as _sp_mod
    tb_str = "".join(_tb_mod.format_exception(exc_type, exc_value, exc_tb))
    _src = os.path.splitext(os.path.basename(__file__))[0]
    _err = os.path.join(os.environ.get('TEMP', _PROJECT_ROOT), f"banner_tool_error_{_src}_{os.getpid()}.txt")
    try:
        with open(_err, "w", encoding="utf-8") as f:
            f.write(f"程序发生致命错误:\n\n{tb_str}")
    except Exception:
        pass
    _reporter = os.path.join(_PROJECT_ROOT, "scripts", "error_reporter.pyw")
    try:
        _sp_mod.Popen([sys.executable, _reporter, _err, "程序异常", _src],
                       creationflags=_sp_mod.CREATE_NO_WINDOW | _sp_mod.DETACHED_PROCESS)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)
sys.excepthook = _early_crash_handler
import json
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PyQt5.QtWidgets import (
    QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QCheckBox, QRadioButton, QLineEdit, QFileDialog,
    QProgressBar, QFrame, QGroupBox, QTextEdit, QScrollArea, QMessageBox,
    QButtonGroup, QSizePolicy, QLayout, QComboBox
)

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRect, QTimer, QSize, QProcess
from PyQt5.QtGui import QFont, QPainter, QColor, QLinearGradient, QPixmap


# ===== 缩放 =====
# 分辨率适配：与 real_installer.pyw 的 _ui_scales 完全一致（窗口 + 字号同一套公式）
#   raw        = min(sw / 1920, sh / 1080)
#   win_scale  = min(max(raw, 1.0) * 1.25, 2.5)   —— 窗口 4:3 大小
#   font_scale = max(min(raw, 1.4) * 1.1, 0.85)   —— 字号 / 控件 / 间距
def _ui_scales(app):
    screen = app.primaryScreen()
    geo = screen.availableGeometry() if screen else None
    sw = geo.width() if geo else 1920
    sh = geo.height() if geo else 1080
    raw = min(sw / 1920, sh / 1080)
    win_scale = min(max(raw, 1.0) * 1.25, 2.5)
    font_scale = max(min(raw, 1.4) * 1.1, 0.85)
    return win_scale, font_scale


def _ask_yes_no(parent, title, text, default_no=True):
    """中文「是/否」确认框（替代 QMessageBox 英文 Yes/No 标准按钮）。

    Returns: True=是, False=否
    """
    box = QMessageBox(QMessageBox.Question, title, text, parent=parent)
    btn_yes = QPushButton("是")
    btn_no = QPushButton("否")
    box.addButton(btn_no, QMessageBox.NoRole)
    box.addButton(btn_yes, QMessageBox.YesRole)
    box.setDefaultButton(btn_no if default_no else btn_yes)
    box.exec_()
    return box.clickedButton() == btn_yes


# ===== 侧图路径（预留位） =====
# 打包后 __file__ 在 sys._MEIPASS 内，需要用 _MEIPASS 定位资源
_BANNER_DIR = os.path.join(
    sys._MEIPASS if getattr(sys, 'frozen', False) else _PROJECT_ROOT,
    "images", "banner")
_BANNER_CANDIDATES = ["installer_banner.png", "installer_banner.jpg",
                      "installer_banner.bmp", "banner.png", "banner.jpg",
                      "installer_banner .png", "installer_banner .jpg"]


def _find_banner_image():
    """在 images/banner/ 中查找侧图，返回路径或 None。
    支持文件名含/不含空格容错（如 'installer_banner .png'）。
    """
    if not os.path.isdir(_BANNER_DIR):
        return None
    # 1) 优先匹配预设文件名
    for name in _BANNER_CANDIDATES:
        p = os.path.join(_BANNER_DIR, name)
        if os.path.exists(p):
            return p
    # 2) 回退：扫描目录下任意图片文件
    try:
        for fn in sorted(os.listdir(_BANNER_DIR)):
            low = fn.lower()
            if low.endswith((".png", ".jpg", ".jpeg", ".bmp")):
                return os.path.join(_BANNER_DIR, fn)
    except Exception:
        pass
    return None


# ===== 安装状态检测 =====
# 老名称（兼容旧版用户）
_OLD_DIR_NAME = "旗帜编织逆向器"
# 新名称（新用户默认）
_DIR_NAME = "我的世界旗帜逆向套件"

_DEFAULT_INSTALL_PATHS = [
    # 默认安装位置（仅新名称；老名称=开发环境，不纳入）
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), _DIR_NAME),
    r"C:\Program Files\\" + _DIR_NAME,
]
_COMPONENTS_FILE = "install_components.json"
_UI_VERSION = "v0.5 beta1 (1.0.8)"   # 界面显示版本（与窗口标题/训练器一致；内部 json/注册表记 1.0.8）


def detect_install_state():
    """检测电脑是否已安装本软件，返回安装情况。

    Returns: dict {installed, path, version, components}
    """
    state = {"installed": False, "path": None, "version": None, "components": []}

    # 1) 注册表卸载项
    try:
        import winreg
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(
                    root,
                    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MinecraftBannerReverser")
                state["path"], _ = winreg.QueryValueEx(key, "InstallLocation")
                state["version"], _ = winreg.QueryValueEx(key, "DisplayVersion")
                state["installed"] = True
                winreg.CloseKey(key)
                break
            except FileNotFoundError:
                continue
    except Exception:
        pass

    # 2) 默认路径回退（注册表缺失时）
    if not state["installed"]:
        for p in _DEFAULT_INSTALL_PATHS:
            if os.path.exists(os.path.join(p, "trainer.pyw")):
                state["installed"] = True
                state["path"] = p
                break

    # 3) 组件清单
    if state["installed"] and state["path"]:
        comp_file = os.path.join(state["path"], _COMPONENTS_FILE)
        if os.path.exists(comp_file):
            try:
                with open(comp_file, encoding="utf-8") as f:
                    state["components"] = json.load(f).get("components", [])
            except Exception:
                pass

    return state


# ===== Windows API 硬件检测 =====
def _w32_get_os():
    """通过 kernel32 获取 Windows 版本。"""
    try:
        import ctypes
        class OSVERSIONINFOEXW(ctypes.Structure):
            _fields_ = [("dwOSVersionInfoSize", ctypes.c_ulong),
                        ("dwMajorVersion", ctypes.c_ulong),
                        ("dwMinorVersion", ctypes.c_ulong),
                        ("dwBuildNumber", ctypes.c_ulong),
                        ("dwPlatformId", ctypes.c_ulong),
                        ("szCSDVersion", ctypes.c_wchar * 128),
                        ("wServicePackMajor", ctypes.c_ushort),
                        ("wServicePackMinor", ctypes.c_ushort),
                        ("wSuiteMask", ctypes.c_ushort),
                        ("wProductType", ctypes.c_byte),
                        ("wReserved", ctypes.c_byte)]
        osvi = OSVERSIONINFOEXW()
        osvi.dwOSVersionInfoSize = ctypes.sizeof(OSVERSIONINFOEXW)
        ctypes.windll.ntdll.RtlGetVersion(ctypes.byref(osvi))
        # Windows 10/11 判断：build >= 22000 为 Win11
        ver_name = "Windows 11" if osvi.dwBuildNumber >= 22000 else "Windows 10"
        return f"{ver_name} (Build {osvi.dwBuildNumber})"
    except Exception:
        try:
            import platform
            return f"Windows {platform.release()}"
        except Exception:
            return "Windows 版本未知"


def _w32_get_python():
    """检测系统安装的 Python 运行时。

    返回 dict:
      - current: 当前运行时版本（如 "Python 3.13.14"）
      - system: 系统已安装的 Python 版本列表（通过注册表检测）
      - has_python: 系统是否安装了 Python 3.10.11+
    """
    v = sys.version_info
    current = f"Python {v.major}.{v.minor}.{v.micro}"

    # 通过注册表检测系统安装的 Python
    system_versions = []
    try:
        import winreg
        # 检测 HKCU 和 HKLM 下的 Python 注册表项
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(hive, r"Software\Python\PythonCore")
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        i += 1
                        if subkey_name.startswith("3."):
                            system_versions.append(subkey_name)
                    except OSError:
                        break
                winreg.CloseKey(key)
            except OSError:
                pass
    except Exception:
        pass

    # 自适应最低门槛：>= 3.10.11（与 real_installer 的 PYTHON_VERSION_MIN 一致；主代码以 3.13.14 为基准）
    def _v_tuple(s):
        try:
            p = tuple(int(x) for x in s.split(".")[:3])
            return p + (0,) * (3 - len(p))
        except Exception:
            return (0, 0, 0)

    has_python_ok = any(_v_tuple(x) >= (3, 10, 11) for x in system_versions) or \
        (v.major, v.minor, v.micro) >= (3, 10, 11)

    return {
        "current": current,
        "system": sorted(set(system_versions)),
        "has_python_ok": has_python_ok,
    }


def _w32_get_cpu():
    """通过 CIM (Win32_Processor) 获取 CPU 名称，优先 PowerShell，回退 wmic。"""
    try:
        import subprocess
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10).decode("utf-8", errors="ignore").strip()
        if out:
            return out.splitlines()[0].strip()
    except Exception:
        pass
    try:
        import subprocess
        out = subprocess.check_output(
            ["wmic", "cpu", "get", "name"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10).decode("utf-8", errors="ignore")
        lines = [l.strip() for l in out.strip().splitlines()
                 if l.strip() and "name" not in l.lower()]
        if lines:
            return lines[0]
    except Exception:
        pass
    return "未知"


def _w32_get_ram_gb():
    """通过 GlobalMemoryStatusEx 获取总内存（GB）。"""
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return round(stat.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        return 0.0


# SMBIOSMemoryType → 内存类型名映射（Win32_PhysicalMemory）
_SMBIOS_MEM_TYPE = {
    20: "DDR", 21: "DDR2", 22: "DDR2 FB-DIMM", 24: "DDR3",
    26: "DDR4", 27: "DDR4E", 28: "LPDDR3", 29: "LPDDR4",
    30: "LPDDR4X", 34: "DDR5", 35: "LPDDR5", 36: "LPDDR5X",
    31: "DDR3L", 32: "DDR3E",
}


def _smbios_to_ram_name(code):
    """将 SMBIOSMemoryType 数值转为内存类型名。"""
    return _SMBIOS_MEM_TYPE.get(int(code), "")


def _w32_get_ram_info():
    """通过 Windows API 获取内存详情（标称/系统识别/可用三分量）。

    Returns: (nominal_gb, recognized_gb, avail_gb, ram_type)
      - nominal_gb   : 出厂标称内存（GetPhysicallyInstalledSystemMemory），如 64
      - recognized_gb: 系统识别总内存（GlobalMemoryStatusEx.ullTotalPhys），如 63.1
      - avail_gb     : 当前可用内存（ullAvailPhys），如 27
      - ram_type     : Win32_PhysicalMemory.SMBIOSMemoryType 检测的内存代际（如 DDR5/LPDDR5）
    """
    nominal_gb = recognized_gb = avail_gb = 0.0
    ram_type = ""
    try:
        import ctypes
        # 1) 出厂标称内存（与任务管理器「安装的内存」一致）
        try:
            installed_kb = ctypes.c_ulonglong()
            if ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(
                    ctypes.byref(installed_kb)):
                nominal_gb = int(round(installed_kb.value / (1024 ** 2)))
        except Exception:
            pass
        # 2) 系统识别总内存 + 当前可用内存
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        recognized_gb = round(stat.ullTotalPhys / (1024 ** 3), 1)
        avail_gb = round(stat.ullAvailPhys / (1024 ** 3), 1)
        if nominal_gb <= 0:
            nominal_gb = int(round(recognized_gb))
    except Exception:
        pass
    # 内存类型（SMBIOSMemoryType）
    try:
        import subprocess
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_PhysicalMemory | "
             "Select-Object -ExpandProperty SMBIOSMemoryType"],
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=10
        ).decode("utf-8", errors="ignore").strip()
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                name = _smbios_to_ram_name(int(line))
                if name:
                    ram_type = name
                    break
    except Exception:
        pass
    return nominal_gb, recognized_gb, avail_gb, ram_type


def _w32_get_disk_free_gb(drive_letter="C"):
    """通过 GetDiskFreeSpaceEx 获取磁盘可用空间（GB）。"""
    try:
        import ctypes
        free_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(f"{drive_letter}:\\"), None, None, ctypes.byref(free_bytes))
        return round(free_bytes.value / (1024 ** 3), 1)
    except Exception:
        return 0.0


_NVIDIA_PREFIXES = ("geforce", "nvidia", "quadro", "tesla", "rtx", "gtx", "titan")
_AMD_PREFIXES = ("amd", "radeon", "firepro")
_INTEL_PREFIXES = ("intel", "iris", "uhd", "hd graphics", "arc")

# NVIDIA RTX 20 系列及以上（按名称关键字判断最低代数）
_RTX_20PLUS = ("rtx 20", "rtx 30", "rtx 40", "rtx 50", "rtx a", "a100", "a6000",
               "quadro rtx", "tesla t4", "tesla a", "l4", "h100", "a10", "a40")
# Intel 支持的核显白名单
_INTEL_GPU_WHITELIST = ("iris xe", "iris plus", "uhd 770", "uhd 730", "arc")
# AMD 支持的核显/独显关键字（按型号匹配）
_AMD_GPU_SUPPORTED = ("vega 7", "vega 8", "vega 10", "vega 11",
                      "radeon 6", "radeon 7", "radeon rx",
                      "radeon(tm) 7", "radeon(tm) 8",  # RDNA2/RDNA3 核显: 780M/880M/890M
                      "rdna", "gfx10", "gfx11")

def _w32_get_nvidia_vram_gb():
    """通过 nvidia-smi 获取 NVIDIA GPU 真实显存（GB），避免 WMI uint32 溢出。"""
    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode == 0 and r.stdout.strip():
            mib = int(r.stdout.strip().split("\n")[0].strip())
            return max(1, round(mib / 1024))
    except Exception:
        pass
    return 0


def _w32_get_gpu_info():
    """通过 CIM (Win32_VideoController) 获取所有显卡信息。

    Returns: dict {
        discrete: {vendor, name, vram_gb, is_integrated} or None,
        integrated: {vendor, name, vram_gb, is_integrated} or None,
        all: [list of GPU dicts],
    }
    """
    raw_gpus = []
    try:
        import subprocess
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | "
             "ForEach-Object { $_.Name + '|' + $_.AdapterRAM }"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15).decode("utf-8", errors="ignore").strip()
        for line in out.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            name_part, vram_part = line.split("|", 1)
            gname = name_part.strip()
            if not gname or any(skip in gname.lower() for skip in (
                    "orayidd", "microsoft remote", "basic display",
                    "virtual", "indirect display", "usb display",
                    "miracast", "windows virtual display")):
                continue
            vram = 0
            try:
                vram = int(vram_part.strip()) if vram_part.strip() else 0
            except ValueError:
                vram = 0
            raw_gpus.append((gname, vram))
    except Exception:
        pass

    # wmic 回退
    if not raw_gpus:
        try:
            import subprocess
            out = subprocess.check_output(
                ["wmic", "path", "win32_videocontroller",
                 "get", "name,AdapterRAM"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10).decode("utf-8", errors="ignore")
            for line in out.strip().splitlines():
                line = line.strip()
                if not line or "adapterram" in line.lower():
                    continue
                tokens = line.rsplit(None, 1)
                if len(tokens) == 2:
                    gname, vram_str = tokens
                    try:
                        vram = int(vram_str)
                    except ValueError:
                        vram = 0
                else:
                    gname, vram = line.strip(), 0
                gl = gname.lower()
                if gname and "microsoft" not in gl:
                    raw_gpus.append((gname, vram))
        except Exception:
            pass

    def _detect_integrated(gname):
        gl = gname.lower()
        if any(p in gl for p in ("intel", "uhd", "iris", "hd graphics")):
            return True
        if "arc" in gl and "intel" in gl:
            return False  # Intel Arc 独显
        if "amd" in gl or "radeon" in gl:
            amd_igpu_kw = ("vega 3", "vega 7", "vega 8", "vega 10", "vega 11",
                           " 780m", " 760m", " 680m", " 660m",
                           " 880m", " 890m", " 860m", " 840m",
                           "radeon(tm)", "radeon graphics", "ryzen")
            if any(kw in gl for kw in amd_igpu_kw):
                return True
            if any(kw in gl for kw in ("rx ", "pro ", "firepro", "instinct")):
                return False
        return False

    def _identify_vendor(gname):
        gl = gname.lower()
        if any(p in gl for p in _NVIDIA_PREFIXES):
            return "nvidia"
        if any(p in gl for p in _AMD_PREFIXES):
            return "amd"
        if any(p in gl for p in _INTEL_PREFIXES):
            return "intel"
        return "unknown"

    # 构建 GPU dict 列表
    all_gpus = []
    for gname, gram in raw_gpus:
        gl = gname.lower()
        is_igpu = _detect_integrated(gname)
        vendor = _identify_vendor(gname)
        vram_gb = round(gram / (1024 ** 3), 1) if gram > 0 else 0
        # NVIDIA 独显：用 nvidia-smi 获取真实显存（CIM AdapterRAM uint32 溢出）
        if vendor == "nvidia" and not is_igpu:
            smi_vram = _w32_get_nvidia_vram_gb()
            if smi_vram > 0:
                vram_gb = smi_vram
        # 核显共享内存：报告系统内存的 25% 作为分配显存
        if is_igpu and vram_gb < 1:
            vram_gb = round(_w32_get_ram_gb() * 0.25, 1)
        all_gpus.append({
            "vendor": vendor, "name": gname,
            "vram_gb": round(vram_gb, 1), "is_integrated": is_igpu,
        })

    if not all_gpus:
        return {"discrete": None, "integrated": None,
                "all": [], "vendor": "none", "name": "", "vram_gb": 0, "is_integrated": False}

    # 分类：独显和核显
    discrete = None
    integrated = None
    for g in all_gpus:
        if g["is_integrated"]:
            if integrated is None:
                integrated = g
        else:
            if discrete is None or g["vram_gb"] > discrete["vram_gb"]:
                discrete = g

    # 兼容旧接口：返回最佳 GPU 作为顶层字段
    best = discrete or integrated or all_gpus[0]
    return {
        "discrete": discrete,
        "integrated": integrated,
        "all": all_gpus,
        "vendor": best["vendor"], "name": best["name"],
        "vram_gb": best["vram_gb"], "is_integrated": best["is_integrated"],
    }


def _w32_check_gpu_requirement(gpu_info, ram_gb):
    """根据 GPU 信息判断是否满足训练最低要求。

    支持双 GPU（独显+核显），返回每种 GPU 的检查结果（分项，便于换行显示）。

    Returns: (ok: bool, reasons: list[(text, per_ok)])
      - ok: 是否任一 GPU 满足训练要求
      - reasons: 每个 GPU 一项 (说明文本, 该项是否可用)，调用方按需换行输出
    """
    discrete = gpu_info.get("discrete")
    integrated = gpu_info.get("integrated")

    if not discrete and not integrated:
        return False, [("未检测到 GPU，仅能使用 CPU 模式", False)]

    reasons = []
    any_ok = False

    if discrete:
        vendor = discrete.get("vendor", "none")
        name_lower = discrete.get("name", "").lower()
        vram = discrete.get("vram_gb", 0)
        if vendor == "nvidia":
            if not any(kw in name_lower for kw in _RTX_20PLUS):
                reasons.append((f"独显 {discrete['name']}：需 RTX 20 系及以上", False))
            elif vram < 6:
                reasons.append((f"独显 {discrete['name']}：显存 {vram}GB 不足（需 ≥6GB）", False))
            else:
                reasons.append((f"独显 {discrete['name']}（{vram}GB）：CUDA 可用，DirectML 也可选", True))
                any_ok = True
        elif vendor in ("amd", "intel"):
            if vram >= 4:
                reasons.append((f"独显 {discrete['name']}（{vram}GB）：DirectML 可用", True))
                any_ok = True
            else:
                reasons.append((f"独显 {discrete['name']}：显存 {vram}GB 不足", False))

    if integrated:
        vendor = integrated.get("vendor", "none")
        name_lower = integrated.get("name", "").lower()
        if vendor == "intel":
            if not any(kw in name_lower for kw in _INTEL_GPU_WHITELIST):
                reasons.append((f"核显 {integrated['name']}：需 Iris Xe / Arc / UHD 770+", False))
            elif ram_gb < 16:
                reasons.append((f"核显 {integrated['name']}：系统内存 {ram_gb}GB 不足（需 ≥16GB）", False))
            else:
                reasons.append((f"核显 {integrated['name']}：DirectML 可用", True))
                any_ok = True
        elif vendor == "amd":
            if not any(kw in name_lower for kw in _AMD_GPU_SUPPORTED):
                reasons.append((f"核显 {integrated['name']}：需 Vega 7+ 或 RDNA2+", False))
            elif ram_gb < 16:
                reasons.append((f"核显 {integrated['name']}：系统内存 {ram_gb}GB 不足（需 ≥16GB）", False))
            else:
                reasons.append((f"核显 {integrated['name']}：DirectML 可用", True))
                any_ok = True

    return any_ok, reasons


# ===== 初始化检测线程 =====
class _InitThread(QThread):
    """硬件/软件环境检测 + 安装状态检测，全部使用 Windows API。"""
    line = pyqtSignal(str, bool)
    finished_all = pyqtSignal(dict)

    def run(self):
        info = {
            "os": "", "python": "", "cpu": "", "ram_gb": 0.0,
            "gpu": {}, "gpu_ok": False, "gpu_reason": "",
            "disk_free_gb": 0.0,
            "install_state": {"installed": False, "path": None, "version": None, "components": []},
        }

        STEP_DELAY = 0.3

        # 操作系统
        try:
            info["os"] = _w32_get_os()
            self.line.emit(f"操作系统：{info['os']}", True)
        except Exception:
            self.line.emit("操作系统：检测失败", False)
        time.sleep(STEP_DELAY)

        # Python
        try:
            py_info = _w32_get_python()
            info["python"] = py_info["current"]
            info["python_has_ok"] = py_info["has_python_ok"]
            if py_info["has_python_ok"]:
                self.line.emit(f"Python 运行时：{py_info['current']}", True)
            else:
                sys_versions = ", ".join(py_info["system"]) if py_info["system"] else "未检测到"
                self.line.emit(
                    f"Python 运行时：{py_info['current']}（系统: {sys_versions}，需要 3.10.11+）",
                    False)
        except Exception:
            self.line.emit("Python 运行时：检测失败", False)
        time.sleep(STEP_DELAY)

        # CPU
        try:
            info["cpu"] = _w32_get_cpu()
            self.line.emit(f"CPU：{info['cpu']}", True)
        except Exception:
            self.line.emit("CPU：检测失败", False)
        time.sleep(STEP_DELAY)

        # 内存（标称 + 系统识别 + 可用 + 类型）
        try:
            nominal_gb, recognized_gb, avail_gb, ram_type = _w32_get_ram_info()
            info["ram_gb"] = nominal_gb          # 标称内存（兼容旧字段，判定用）
            info["ram_recognized_gb"] = recognized_gb
            info["ram_avail_gb"] = avail_gb
            info["ram_type"] = ram_type
            if ram_type:
                self.line.emit(
                    f"内存：标称 {nominal_gb} GB {ram_type}（当前可用 {avail_gb} GB）",
                    nominal_gb >= 8)
            else:
                self.line.emit(
                    f"内存：标称 {nominal_gb} GB（当前可用 {avail_gb} GB）",
                    nominal_gb >= 8)
        except Exception:
            self.line.emit("内存：检测失败", False)
        time.sleep(STEP_DELAY)

        # GPU（Windows API 检测，支持双 GPU）
        try:
            info["gpu"] = _w32_get_gpu_info()
            info["gpu_ok"], reasons = _w32_check_gpu_requirement(
                info["gpu"], info["ram_gb"])
            # gpu_reason: 旧字段（兼容，拼接单行）
            info["gpu_reason"] = "；".join(t for t, _ in reasons)
            info["gpu_reasons"] = reasons  # [(text, per_ok)]
            # 按 GPU 0/1/... 编号输出（独显优先，核显次之）
            gpus_ordered = []
            discrete = info["gpu"].get("discrete")
            integrated = info["gpu"].get("integrated")
            if discrete:
                gpus_ordered.append((discrete, "独显"))
            if integrated:
                gpus_ordered.append((integrated, "核显"))
            if gpus_ordered:
                for idx, (g, kind) in enumerate(gpus_ordered):
                    v = g.get("vram_gb", 0)
                    share = "共享" if g.get("is_integrated") else ""
                    self.line.emit(
                        f"GPU {idx}：{g['name']} {share}{v}GB（{kind}）", v >= 1)
            else:
                self.line.emit("GPU：未检测到独立/集成显卡", False)
            # 汇总（CUDA/DirectML 分项换行显示）
            ok_text = "满足训练要求" if info["gpu_ok"] else "不满足训练要求"
            self.line.emit(f"GPU 适配：{ok_text}", info["gpu_ok"])
            for r_text, r_ok in reasons:
                self.line.emit(f"    {r_text}", r_ok)
        except Exception as e:
            self.line.emit(f"GPU：检测失败 ({e})", False)
        time.sleep(STEP_DELAY)

        # 磁盘空间检测已移至「安装路径选择」页（按所选盘符实时检测）

        # 已安装状态
        state = detect_install_state()
        info["install_state"] = state
        if state["installed"]:
            ver = state["version"] or "未知版本"
            comps = len(state["components"])
            self.line.emit(
                f"已安装状态：已安装（{ver}，{comps} 个组件，路径：{state['path']}）", True)
        else:
            self.line.emit("已安装状态：未安装（将进行全新安装）", True)

        time.sleep(STEP_DELAY * 0.6)
        self.finished_all.emit(info)


# ===== 各模式安装步骤文本 =====
_STEPS = {
    "install": [
        (3,   "正在检测系统环境..."),
        (8,   "正在下载 Python 3.13.14 安装包（27MB）..."),
        (15,  "正在安装 Python 3.13.14..."),
        (22,  "正在配置 pip 包管理器..."),
        (30,  "正在下载并安装核心组件 (torch, torchvision)..."),
        (40,  "正在安装 GUI 框架 (PyQt5)..."),
        (48,  "正在安装图像处理库 (cv2, PIL, numpy)..."),
        (55,  "正在安装辅助库 (matplotlib, psutil, pynvml)..."),
        (62,  "正在写入模型结构文件 (models/structures/)..."),
        (70,  "正在写入工具模块 (utils/)..."),
        (78,  "正在写入脚本 (scripts/)..."),
        (85,  "正在注册文件关联 (.mbtl, .mbtlx)..."),
        (93,  "正在创建快捷方式..."),
        (100, "安装完成！"),
    ],
    "manage_components": [
        (8,  "正在分析已安装组件..."),
        (25, "正在下载新勾选的模型架构..."),
        (45, "正在安装训练工具与依赖库..."),
        (62, "正在卸载已取消勾选的组件..."),
        (80, "正在更新组件注册信息..."),
        (95, "正在创建/删除快捷方式..."),
        (100, "组件管理完成！"),
    ],
    "uninstall": [
        (10,  "正在停止相关进程..."),
        (25,  "正在删除程序文件..."),
        (45,  "正在删除模型文件..."),
        (62,  "正在清理注册表文件关联..."),
        (78,  "正在删除快捷方式..."),
        (90,  "正在清理用户配置..."),
        (100, "卸载完成！"),
    ],
}

_MODE_TITLE = {
    "install": "正在安装",
    "uninstall": "正在卸载",
    "manage_components": "正在管理组件",
}


class _FakeInstallThread(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, mode, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._cancel = False

    def cancel(self):
        """请求取消安装，线程会在下一个进度步退出。"""
        self._cancel = True

    def run(self):
        prev = 0
        for target, text in _STEPS[self._mode]:
            while prev < target:
                if self._cancel:
                    self.cancelled.emit()
                    return
                step = max(1, (target - prev) // 5)
                prev = min(prev + step, target)
                self.progress.emit(prev, text)
                time.sleep(0.07 + (target - prev) * 0.002)
            if self._cancel:
                self.cancelled.emit()
                return
            time.sleep(0.12)
        self.finished_ok.emit()


# ===== 左侧 Banner（从 images/banner/ 加载，失败则绘制占位） =====
class _BannerWidget(QWidget):
    def __init__(self, us, parent=None):
        super().__init__(parent)
        self._us = us
        self.setFixedWidth(max(int(180 * us), 150))
        self._pixmap = None
        banner_path = _find_banner_image()
        if banner_path:
            self._pixmap = QPixmap(banner_path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if self._pixmap and not self._pixmap.isNull():
            # 加载预留位图片：等比缩放填充（可能裁剪）
            scaled = self._pixmap.scaled(
                w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (w - scaled.width()) // 2
            y = (h - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            # 占位绘制：白底 + 渐变 + logo + 预留路径提示
            painter.fillRect(0, 0, w, h, QColor("#ffffff"))
            grad = QLinearGradient(0, 0, 0, int(h * 0.45))
            grad.setColorAt(0.0, QColor("#eaf3fb"))
            grad.setColorAt(1.0, QColor("#ffffff"))
            painter.fillRect(0, 0, w, int(h * 0.45), grad)

            us = self._us
            r = max(int(44 * us), 36)
            cx, cy = w // 2, int(h * 0.24)
            painter.setBrush(QColor("#0078d4"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Segoe UI Emoji", max(int(26 * us), 20)))
            painter.drawText(QRect(cx - r, cy - r, r * 2, r * 2), Qt.AlignCenter, "🚩")

            painter.setPen(QColor("#333333"))
            f = QFont("Segoe UI", max(int(10 * us), 8))
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(QRect(0, h - max(int(56 * us), 46), w, max(int(20 * us), 16)),
                             Qt.AlignCenter, "我的世界旗帜逆向套件")
            painter.setPen(QColor("#888888"))
            painter.setFont(QFont("Segoe UI", max(int(8 * us), 7)))
            painter.drawText(QRect(0, h - max(int(36 * us), 30), w, max(int(16 * us), 13)),
                             Qt.AlignCenter, "for Windows")

        # 右侧分隔线
        painter.setPen(QColor("#d8d8d8"))
        painter.drawLine(w - 1, 0, w - 1, h)


# ===== 页面基类 =====
class _FixedScrollArea(QScrollArea):
    """sizeHint 固定，不基于内部 widget。

    QScrollArea 在 setWidgetResizable(True) 时，sizeHint() 会返回内部 widget 的
    sizeHint（声明正文可达 12528px），这会把 QStackedWidget/页面 layout 的 sizeHint
    撑大，导致 show() 时 Qt 用 sizeHint 覆盖 setFixedSize（4:3→1:1 比例丢失的根源）。
    重写 sizeHint 返回固定值，让滚动区域只占据合理空间。
    """
    def __init__(self, us, parent=None):
        super().__init__(parent)
        self._us = us

    def sizeHint(self):
        return QSize(max(int(400 * self._us), 320), max(int(400 * self._us), 320))

    def minimumSizeHint(self):
        return QSize(max(int(200 * self._us), 160), max(int(200 * self._us), 160))


class _PageBase(QWidget):
    def __init__(self, us, parent=None):
        super().__init__(parent)
        self._us = us
        self._m = max(int(24 * us), 18)
        # 字号与 real_installer 完全一致：pt 单位，基准 10/8/7，随 us 缩放
        self._fs_title = max(int(10 * us), 10)
        self._fs_body  = max(int(8 * us), 8)
        self._fs_hint  = max(int(7 * us), 7)
        # 兼容旧的 _fs_*_px 引用（值为 pt）
        self._fs_title_px = self._fs_title
        self._fs_body_px  = self._fs_body
        self._fs_hint_px  = self._fs_hint

    def _title(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        f = lbl.font()
        f.setPointSize(self._fs_title)
        f.setBold(True)
        lbl.setFont(f)
        return lbl

    def _desc(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        f = lbl.font()
        f.setPointSize(self._fs_body)
        lbl.setFont(f)
        return lbl

    def _hint(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        f = lbl.font()
        f.setPointSize(self._fs_hint)
        lbl.setFont(f)
        lbl.setStyleSheet("color: #666;")
        return lbl

    def sizeHint(self):
        # 限制 sizeHint 高度，防止 QScrollArea 内部长文本把 QStackedWidget 的
        # sizeHint 撑大，导致 show() 时 Qt 用 sizeHint 覆盖 setFixedSize（1:1 比例 bug 根源）
        sh = super().sizeHint()
        return QSize(sh.width(), min(sh.height(), max(int(400 * self._us), 320)))

    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        return QSize(sh.width(), min(sh.height(), max(int(300 * self._us), 240)))


# ===== 页面 0：初始化检测 =====
class _InitPage(_PageBase):
    def __init__(self, us, parent=None):
        super().__init__(us, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(8 * us), 6))

        layout.addWidget(self._title("正在初始化"))
        layout.addWidget(self._desc("安装程序正在检测您的软硬件环境，请稍候。"))

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QTextEdit.WidgetWidth)
        self.text.setStyleSheet(
            "background: #f8f8f8; border: 1px solid #ddd; padding: 6px; "
            "font-family: Consolas, monospace;")
        layout.addWidget(self.text, 1)

        self.status = QLabel("检测中...")
        self.status.setStyleSheet("color: #666;")
        layout.addWidget(self.status)

        self._info = None
        self._thread = None

    def start(self):
        self.text.clear()
        self.status.setText("检测中...")
        self._thread = _InitThread(self)
        self._thread.line.connect(self._on_line)
        self._thread.finished_all.connect(self._on_done)
        self._thread.start()

    def _on_line(self, text, ok):
        mark = "✓" if ok else "✗"
        color = "#2e7d32" if ok else "#c62828"
        self.text.append(f'<span style="color:{color}">{mark}</span> {text}')

    def _show_sim_results(self, info):
        """从模拟配置填充检测结果文本（替代真实检测线程的 line 信号）。"""
        self.text.clear()
        def _emit(text, ok):
            mark = "✓" if ok else "✗"
            color = "#2e7d32" if ok else "#c62828"
            self.text.append(f'<span style="color:{color}">{mark}</span> {text}')

        os_ver = info.get("os", "")
        _emit(f"操作系统：{os_ver}", bool(os_ver))

        py = info.get("python", "")
        if py:
            _emit(f"Python 运行时：{py}", True)

        cpu = info.get("cpu", "")
        _emit(f"CPU：{cpu}", bool(cpu))

        # 内存：标称 + 当前可用 + 类型
        ram = info.get("ram_gb", 0)
        ram_type = info.get("ram_type", "")
        ram_avail = info.get("ram_avail_gb", 0)
        if ram_type:
            _emit(f"内存：标称 {ram} GB {ram_type}（当前可用 {ram_avail} GB）", ram >= 8)
        else:
            _emit(f"内存：标称 {ram} GB（当前可用 {ram_avail} GB）", ram >= 8)

        # GPU 按 GPU 0/1/... 编号输出（独显优先，核显次之；纯独显/纯核显只显示存在的）
        gpu = info.get("gpu", {})
        discrete = gpu.get("discrete")
        integrated = gpu.get("integrated")
        gpus_ordered = []
        if discrete:
            gpus_ordered.append((discrete, "独显"))
        if integrated:
            gpus_ordered.append((integrated, "核显"))
        if gpus_ordered:
            for idx, (g, kind) in enumerate(gpus_ordered):
                v = g.get("vram_gb", 0)
                share = "共享" if g.get("is_integrated") else ""
                _emit(f"GPU {idx}：{g['name']} {share}{v}GB（{kind}）", v >= 1)
        else:
            _emit("GPU：未检测到独立/集成显卡", False)

        gpu_ok = info.get("gpu_ok", False)
        gpu_reasons = info.get("gpu_reasons", [])
        gpu_reason = info.get("gpu_reason", "")
        ok_text = "满足训练要求" if gpu_ok else "不满足训练要求"
        _emit(f"GPU 适配：{ok_text}", gpu_ok)
        # CUDA / DirectML 分项换行显示
        if gpu_reasons:
            for r_text, r_ok in gpu_reasons:
                _emit(f"    {r_text}", r_ok)
        elif gpu_reason:
            _emit(f"    {gpu_reason}", gpu_ok)

        # 磁盘空间检测已移至「安装路径选择」页

        state = info.get("install_state", {})
        if state.get("installed"):
            ver = state.get("version", "未知版本")
            comps = len(state.get("components", []))
            path = state.get("path", "")
            _emit(f"已安装状态：已安装（{ver}，{comps} 个组件，路径：{path}）", True)
        else:
            _emit("已安装状态：未安装（将进行全新安装）", True)

    def _on_done(self, info):
        self._info = info
        # 如果文本区域为空（模拟模式），填充检测结果
        if not self.text.toPlainText().strip():
            self._show_sim_results(info)
        state = info.get("install_state", {})
        if state.get("installed"):
            self.status.setText("检测到已安装，点击「下一步」进入维护模式。")
        else:
            self.status.setText("初始化完成，点击「下一步」进入欢迎界面。")

    def set_blocked(self, msg):
        """环境不支持时在文本区域和状态栏显示拦截信息（不弹窗）。"""
        self.text.append(f'\n<span style="color:#c62828;font-weight:bold">⚠ {msg}</span>')
        self.status.setText("⚠ 环境不兼容，无法继续安装。")
        self.status.setStyleSheet("color: #c62828;")

    def get_info(self):
        return self._info


# ===== 页面 1：欢迎 =====
class _WelcomePage(_PageBase):
    maintenance_clicked = pyqtSignal()

    def __init__(self, us, parent=None):
        super().__init__(us, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(8 * us), 6))

        layout.addWidget(self._title("欢迎使用我的世界旗帜逆向套件安装向导"))
        layout.addWidget(self._desc(
            "此向导将引导您完成我的世界旗帜逆向套件的安装。\n"
            "建议在安装前关闭其他正在运行的应用程序。\n"
            "点击「下一步」继续。"))

        # 硬件检测摘要（初始化完成后填入）
        self._hw_frame = QFrame()
        self._hw_frame.setFrameShape(QFrame.StyledPanel)
        self._hw_frame.setStyleSheet(
            "QFrame { background: #f0f6ff; border: 1px solid #c0d8f0; border-radius: 6px; }")
        hw_layout = QVBoxLayout(self._hw_frame)
        hw_layout.setContentsMargins(max(int(12 * us), 10), max(int(8 * us), 6),
                                     max(int(12 * us), 10), max(int(8 * us), 6))
        hw_layout.setSpacing(max(int(2 * us), 2))
        self._hw_title = QLabel("系统检测结果：")
        f = self._hw_title.font()
        f.setPointSize(self._fs_hint_px)
        f.setBold(True)
        self._hw_title.setFont(f)
        self._hw_title.setStyleSheet("color: #0078d4;")
        hw_layout.addWidget(self._hw_title)
        self._hw_info = QLabel("初始化中...")
        f2 = self._hw_info.font()
        f2.setPointSize(self._fs_hint_px)
        self._hw_info.setFont(f2)
        self._hw_info.setWordWrap(True)
        self._hw_info.setStyleSheet("color: #333;")
        hw_layout.addWidget(self._hw_info)
        layout.addWidget(self._hw_frame)

        layout.addStretch()

        btn_maint = QPushButton("已安装？修改 / 修复 / 卸载（演示入口）")
        btn_maint.setFlat(True)
        btn_maint.setCursor(Qt.PointingHandCursor)
        btn_maint.setStyleSheet(
            "QPushButton { color: #0078d4; text-align: left; border: none; }"
            "QPushButton:hover { text-decoration: underline; }")
        btn_maint.clicked.connect(self.maintenance_clicked)
        layout.addWidget(btn_maint)

        layout.addWidget(self._hint("※ 演示模式：不会在计算机上产生任何文件或修改系统设置。"))

    def set_hw_info(self, info):
        """根据初始化检测结果填充系统摘要。"""
        gpu = info.get("gpu", {})
        gpu_ok = info.get("gpu_ok", False)
        gpu_reason = info.get("gpu_reason", "")
        discrete = gpu.get("discrete")
        integrated = gpu.get("integrated")
        state = info.get("install_state", {})

        lines = [
            f"操作系统：{info.get('os', '未知')}",
            f"CPU：{info.get('cpu', '未知')}",
        ]
        # 内存：标称 + 当前可用 + 类型
        ram = info.get("ram_gb", 0)
        ram_type = info.get("ram_type", "")
        ram_avail = info.get("ram_avail_gb", 0)
        if ram_type:
            lines.append(f"内存：标称 {ram} GB {ram_type}（当前可用 {ram_avail} GB）")
        else:
            lines.append(f"内存：标称 {ram} GB（当前可用 {ram_avail} GB）")
        # GPU 按 GPU 0/1/... 编号（独显优先；纯独显/纯核显只显示存在的）
        gpus_ordered = []
        if discrete:
            gpus_ordered.append((discrete, "独显"))
        if integrated:
            gpus_ordered.append((integrated, "核显"))
        if gpus_ordered:
            for idx, (g, kind) in enumerate(gpus_ordered):
                v = g.get("vram_gb", 0)
                share = "共享" if g.get("is_integrated") else ""
                lines.append(f"GPU {idx}：{g['name']} {share}{v}GB（{kind}）")
        else:
            lines.append("GPU：未检测到独立/集成显卡")
        # GPU 适配总结 + 分项（CUDA/DirectML 各占一行）
        gpu_reasons = info.get("gpu_reasons", [])
        gpu_reason = info.get("gpu_reason", "")
        ok_text = "✓ 满足训练要求" if gpu_ok else "⚠ 不满足训练要求"
        lines.append(f"GPU 适配：{ok_text}")
        if gpu_reasons:
            for r_text, r_ok in gpu_reasons:
                lines.append(f"    {'✓' if r_ok else '✗'} {r_text}")
        elif gpu_reason:
            lines.append(f"    {gpu_reason}")
        if state.get("installed"):
            lines.append(f"安装状态：已安装 {state.get('version', '')} → 将进入维护模式")
        else:
            lines.append("安装状态：未安装 → 将进行全新安装")
        self._hw_info.setText("\n".join(lines))


# ===== 使用声明文本 =====
_LICENSE_TEXT = """\
我的世界旗帜逆向套件 使用声明
最后更新：2026年7月31日

点击「我接受此声明」即表示您已阅读并同意以下全部条款。如需了解代码内容，可联系作者。

一、软件概述
本工具基于 ViT/DeiT 技术实现 Minecraft 旗帜图案逆向识别，含旗帜识别器与训练器两大模块。由 路过的小朋友（GitHub: IDclc001）独立开发。当前 Beta1 为闭源测试版本，自 Beta2 起依据 GPL v3 许可证开源。

二、系统要求
1. 操作系统：Windows 10（1909+）或 Windows 11，更低版本无法正常训练。
2. 运行内存：建议 16GB 及以上，低于 8GB 可能内存溢出、闪退。
3. 磁盘空间：根据所选架构约 1~3 GB（CUDA 模式约 3GB，DirectML/CPU 约 1GB）。

三、显卡与训练模式
1. CUDA（NVIDIA 独显，RTX 20 系及以上，显存 6GB+）：速度最快，推荐。
2. DirectML（实验性·AMD / Intel 显卡通用加速）：支持无 NVIDIA 独显的设备进行 GPU 加速。速度约为 CUDA 的 1/3~1/5，但比纯 CPU 快 2~5 倍。torch-directml 为微软预览版，偶发运算回退 CPU（速度骤降属正常），长时训练可能提示显存不足——软件已内置定期清理机制，触发时降低批次大小重试即可。
3. 纯 CPU：任何电脑均可运行，速度极慢，仅用于功能验证或无 GPU 环境。
NVIDIA 独显建议优先 CUDA；无 NVIDIA 独显时使用 DirectML，追求稳定可选 CPU。

四、AI 辅助开发与稳定性
本工具部分代码由 AI 辅助生成，已多轮调试但无法保证所有设备 100% 稳定。遇到菜单丢失、卡死、无响应等异常，请按软件指引导出运行日志并发送给开发者。

五、安装与依赖
依赖 PyTorch、PyQt5 等开源库（体积约 2-5GB），安装时自动通过 pip 下载。CUDA 模式需 NVIDIA 驱动 525+；DirectML 模式需 torch-directml 运行时。安装中断可重试，已下载依赖会缓存。游戏兼容性：针对 Minecraft Java 1.8~26.3 / 基岩版 1.2.0~26.50 旗帜系统设计。

六、数据与隐私
硬件信息（CPU、内存、GPU 等）仅用于判断兼容性与推荐组件，不上传服务器，不收集个人隐私。训练日志保存在本地，仅在您主动导出时才离开设备。

七、模型与知识产权
1. 内置 Beta1 测试模型仅供功能测试，不得商用或重新分发。
2. 用户自行训练的模型归用户所有，自行承担使用与分发责任。
3. Minecraft 资产版权归 Mojang Studios / Microsoft 所有，本工具不打包、不分发游戏资产，仅基于用户截图辅助识别。

八、风险提示
1. 硬件风险：训练使 GPU/CPU 长时间高负载，注意散热，避免满载过热。
2. 数据风险：异常中断可能丢失进度，建议定期保存检查点并备份重要数据。
3. 账号风险：本工具为第三方软件，与 Mojang/Microsoft 无关联，在多人服务器使用可能违反服务器规则或 EULA，后果自负。
4. 兼容性风险：Beta 阶段无法保证所有设备均能正常工作。
5. 识别准确性：结果基于模型推断，仅供参考，开发者不作保证。

九、使用限制
1. 严禁用于违反 Minecraft EULA 或所在地法律法规的行为。
2. 识别结果仅供参考，不得作为正式或法律依据。

十、开源许可证（GNU General Public License v3.0）
自 Beta2 起依据 GPL v3 许可证开源。当前 Beta1 闭源测试，源代码暂不公开，如需了解代码内容可联系作者。GPL v3 完整文本自开源之日起生效，详见随附的 LICENSE 文件：

  Copyright (C) 2026 路过的小朋友（GitHub: IDclc001）

  本程序是自由软件：你可以依据自由软件基金会发布的 GNU 通用公共许可证第三版（或你自行选择的更高版本）的条款重新分发和/或修改本程序。

  本程序的分发是希望它能有用，但不含任何担保；甚至不包括适销性或特定用途适用性的暗示担保。详见 GNU 通用公共许可证。

  你应当随本程序收到一份 GNU 通用公共许可证的副本。如果没有，见 <https://www.gnu.org/licenses/>。

十一、免责声明
在适用法律允许的最大范围内，开发者不对因使用本软件产生的任何直接、间接、附带、特殊、衍生或惩罚性损害承担责任，使用者应自行承担使用本软件的全部风险。

如果您不同意以上任何条款，请点击「我不接受此声明」并退出安装。

————————————————————————————————
开发者：路过的小朋友（GitHub: IDclc001）
许可证：GNU General Public License v3.0
发布日期：2026年7月31日
"""


# ===== 页面 2：使用声明 =====

class _LicensePage(_PageBase):
    def __init__(self, us, parent=None):
        super().__init__(us, parent)
        self._us = us
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(8 * us), 6))

        layout.addWidget(self._title("使用声明"))
        layout.addWidget(self._desc("请阅读以下使用声明。必须接受才能继续安装。"))

        # ── 滚动区域：声明文本 + 接受/不接受选项都在内部 ──
        self.scroll_area = _FixedScrollArea(us)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.StyledPanel)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(max(int(10 * us), 8), max(int(10 * us), 8),
                              max(int(10 * us), 8), max(int(10 * us), 8))
        cl.setSpacing(max(int(10 * us), 8))

        # 声明正文 — QLabel + wordWrap 自动换行
        # Ignored 策略：让 QLabel 的 sizeHint 不参与 layout 计算，
        # 完全由 QScrollArea 的 viewport 控制实际显示尺寸（Qt 官方推荐做法）
        self.license_text = QLabel()
        self.license_text.setWordWrap(True)
        self.license_text.setText(_LICENSE_TEXT)
        self.license_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.license_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        f = self.license_text.font()
        f.setPointSize(self._fs_body_px)
        self.license_text.setFont(f)
        self.license_text.setStyleSheet("color: #333;")
        cl.addWidget(self.license_text)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #ccc; background: #ccc; max-height: 1px;")
        cl.addWidget(sep)

        # 接受/不接受选项（位于滚动区域内部底部）
        self.rb_accept = QRadioButton("我接受此声明(&A)")
        self.rb_decline = QRadioButton("我不接受此声明(&D)")
        self.rb_decline.setChecked(True)
        self.rb_accept.setEnabled(False)
        self.rb_decline.setEnabled(False)
        cl.addWidget(self.rb_accept)
        cl.addWidget(self.rb_decline)

        cl.addStretch()

        self.scroll_area.setWidget(content)
        layout.addWidget(self.scroll_area, 1)

        # 滚动提示标签（在滚动区域外部底部）
        self.scroll_hint = QLabel("↓ 请向下滚动阅读完整声明后，再进行选择 ↓")
        self.scroll_hint.setAlignment(Qt.AlignCenter)
        self.scroll_hint.setStyleSheet("color: #c0392b; font-weight: bold; padding: 2px;")
        layout.addWidget(self.scroll_hint)

        self._scrolled_to_bottom = False
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll)
        # 延迟检测：如果文本无需滚动就能全部显示，直接解锁
        QTimer.singleShot(100, self._check_no_scroll_needed)

    def _check_no_scroll_needed(self):
        """如果声明文本全部可见无需滚动，直接解锁选择。"""
        sb = self.scroll_area.verticalScrollBar()
        if sb.maximum() <= 0:
            self._on_scroll(sb.value())

    def _on_scroll(self, value):
        """滚动时检测是否到底部，解锁选择。"""
        if self._scrolled_to_bottom:
            return
        sb = self.scroll_area.verticalScrollBar()
        if sb.value() >= sb.maximum() - 2:
            self._scrolled_to_bottom = True
            self.rb_accept.setEnabled(True)
            self.rb_decline.setEnabled(True)
            self.scroll_hint.setText("请确认已完整阅读后，在上方选择是否接受")
            self.scroll_hint.setStyleSheet(
                "color: #27ae60; font-weight: bold; padding: 2px;")

    def is_accepted(self):
        return self.rb_accept.isChecked()


# ===== 页面 3：使用目的 =====
class _PurposePage(_PageBase):
    def __init__(self, us, parent=None):
        super().__init__(us, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(10 * us), 8))

        layout.addWidget(self._title("选择使用目的"))
        layout.addWidget(self._desc("请选择您的主要使用方式，安装程序将据此推荐组件。"))

        self._group = QButtonGroup(self)
        self.rb_use = QRadioButton("我只想使用逆向模型")
        self.rb_train = QRadioButton("我要训练自己的逆向模型")
        self.rb_use.setChecked(True)
        self._group.addButton(self.rb_use, 0)
        self._group.addButton(self.rb_train, 1)
        # 设置 radio button 字号
        for rb in (self.rb_use, self.rb_train):
            f = rb.font()
            f.setPointSize(self._fs_body_px)
            rb.setFont(f)

        # 卡片式布局
        for rb, desc in (
            (self.rb_use,  "仅安装识别器与基础依赖，占用空间最小，适合快速使用。"),
            (self.rb_train, "安装完整训练器与所有依赖，可自定义训练模型，占用空间较大。"),
        ):
            card = QFrame()
            card.setFrameShape(QFrame.StyledPanel)
            card.setStyleSheet(
                "QFrame { background: #f8f9fa; border: 1px solid #ddd; border-radius: 6px; }")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(max(int(12 * us), 10), max(int(10 * us), 8),
                                  max(int(12 * us), 10), max(int(10 * us), 8))
            cl.setSpacing(max(int(4 * us), 3))
            cl.addWidget(rb)
            d = QLabel(desc)
            d.setWordWrap(True)
            d.setStyleSheet("color: #666;")
            f = d.font()
            f.setPointSize(self._fs_hint_px)
            d.setFont(f)
            cl.addWidget(d)
            layout.addWidget(card)

        layout.addStretch()

    def purpose(self):
        """返回 'use' 或 'train'。"""
        return "train" if self.rb_train.isChecked() else "use"


# ===== 页面 4：库选择（根据初始化信息 + 使用目的 + 模型架构） =====
class _FeaturesPage(_PageBase):
    arch_changed = pyqtSignal()  # 架构选择变更信号（通知主窗口刷新按钮状态）

    def __init__(self, us, hw_info=None, purpose="use", mode="install",
                 selected_archs=None, parent=None):
        super().__init__(us, parent)
        self._feature_cbs = {}
        selected_archs = selected_archs or []
        hw_info = hw_info or {}
        gpu = hw_info.get("gpu", {})
        gpu_ok = hw_info.get("gpu_ok", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(8 * us), 6))

        if purpose == "train":
            layout.addWidget(self._title("选择安装组件"))
            layout.addWidget(self._desc(
                "您选择了「训练自己的逆向模型」，以下组件将被安装。灰色项表示硬件不支持。"))
        else:
            layout.addWidget(self._title("选择安装组件"))
            layout.addWidget(self._desc(
                "您选择了「使用逆向模型」，以下组件将被安装。训练相关组件已自动禁用。"))

        # 双 GPU 适配：独显和核显分别判断
        discrete = gpu.get("discrete")
        integrated = gpu.get("integrated")
        # NVIDIA 独显 → CUDA（也可选 DirectML）
        has_nv_discrete = bool(discrete and discrete.get("vendor") == "nvidia" and gpu_ok)
        # AMD/Intel 独显或核显 → DirectML
        has_igpu = bool(integrated and integrated.get("vendor") in ("amd", "intel") and gpu_ok)
        has_amd_discrete = bool(discrete and discrete.get("vendor") in ("amd", "intel") and gpu_ok)
        # DirectML 对所有 GPU 类型可用（含 NVIDIA，作为备选）
        has_directml = has_igpu or has_amd_discrete or has_nv_discrete

        is_train = purpose == "train"

        # 判断是否选择了大模型（需更大显存，作提示用）
        _LARGE_ARCHS = {"vit_h_14", "vit_l_16"}
        has_large_arch = bool(set(selected_archs) & _LARGE_ARCHS)

        # (key, 名称, 描述, 默认勾选, 锁定, 可用, 不可用原因)
        features = [
            ("torch",     "torch + torchvision",   "深度学习核心框架（必装）",   True, True, True, ""),
            ("pyqt5",     "PyQt5",                 "GUI 图形界面框架（必装）",  True, True, True, ""),
            ("numpy_cv2", "numpy + opencv-python", "数值计算与图像处理",       True, False, True, ""),
            ("pillow",    "Pillow (PIL)",          "图像 IO 读写库",          True, False, True, ""),
            ("matplotlib", "matplotlib",           "训练 Loss 曲线图表绘制",
             is_train, False, is_train, "仅训练模型时需要" if not is_train else ""),
            ("psutil",    "psutil",                "硬件检测与监控",
             is_train, False, True, ""),
            ("thermal",  "pynvml",                "GPU 温度监控库（必装，按架构自动切换）",
             True, True, True, ""),
            ("directml",  "DirectML 后端",         "GPU 加速支持·实验性（NVIDIA/AMD/Intel 均可选）",
             has_directml and is_train, False, has_directml,
             "需 GPU" if not has_directml else ""),
        ]

        # 程序文件列表（根据使用目的不同）
        if is_train:
            file_list = [
                "start.pyw — 套件启动器",
                "bdor.pyw — 旗帜识别器",
                "trainer.pyw — 旗帜训练器",
                "importer.pyw — 旗帜训练导入器",
                "help.pyw — 帮助文档",
                "utils/ — 公共工具模块",
                "scripts/ — 辅助脚本（错误报告、退出对话框、DirectML 训练子进程）",
                "models/ — 预训练模型与模型架构",
                "config/ — 默认配置文件",
                "images/ — 图标与横幅资源",
            ]
        else:
            file_list = [
                "start.pyw — 套件启动器",
                "bdor.pyw — 旗帜识别器",
                "help.pyw — 帮助文档",
                "utils/ — 公共工具模块",
                "scripts/ — 辅助脚本（错误报告、退出对话框、DirectML 训练子进程）",
                "models/ — 预训练模型与模型架构",
                "config/ — 默认配置文件",
                "images/ — 图标与横幅资源",
            ]

        scroll = _FixedScrollArea(us)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(max(int(4 * us), 3))

        # ===== 架构选择（CUDA / DirectML / 纯CPU），多选至少 1 个最多 3 个 =====
        arch_box = QGroupBox("架构选择（可多选，至少选 1 个）")
        arch_box.setStyleSheet(
            "QGroupBox{border:1px solid #ccc; border-radius:6px; margin-top:8px; padding-top:16px;}"
            "QGroupBox::title{subcontrol-origin:margin; left:10px; padding:0 4px;}")
        arch_inner = QVBoxLayout(arch_box)
        arch_inner.setSpacing(max(int(6 * us), 4))
        arch_inner.setContentsMargins(12, 8, 12, 8)

        arch_row = QHBoxLayout()
        arch_row.setSpacing(max(int(12 * us), 8))
        # 多选：QRadioButton → QCheckBox（不再互斥，至少选1个最多3个）
        self.rb_cuda = QCheckBox("CUDA")
        self.rb_directml = QCheckBox("DirectML（实验性）")
        self.rb_cpu = QCheckBox("纯 CPU")
        for rb in (self.rb_cuda, self.rb_directml, self.rb_cpu):
            f = rb.font()
            f.setPointSize(self._fs_body_px)
            rb.setFont(f)
            arch_row.addWidget(rb)
        arch_row.addStretch()
        arch_inner.addLayout(arch_row)

        # 架构选择变更时，联动 DirectML 厂商下拉与控温库
        self.rb_cuda.toggled.connect(self._on_arch_changed)
        self.rb_directml.toggled.connect(self._on_arch_changed)
        self.rb_cpu.toggled.connect(self._on_arch_changed)

        # DirectML 厂商下拉（仅展示当前设备检测到的 GPU 厂商）
        dml_row = QHBoxLayout()
        dml_row.setSpacing(max(int(8 * us), 4))
        dml_lbl = QLabel("DirectML 设备:")
        f = dml_lbl.font()
        f.setPointSize(self._fs_body_px)
        dml_lbl.setFont(f)
        self.cb_dml_vendor = QComboBox()
        # 按检测到的 GPU 厂商动态填充选项
        self._dml_vendor_keys = []  # 厂商 key 顺序（"nvidia" / "amd" / "intel"）
        _VENDOR_LABELS = [
            ("nvidia", "N 卡 (NVIDIA)"),
            ("amd", "A 卡 (AMD)"),
            ("intel", "I 卡 (Intel)"),
        ]
        _vendors_present = set()
        if discrete and discrete.get("vendor") in ("nvidia", "amd", "intel"):
            _vendors_present.add(discrete["vendor"])
        if integrated and integrated.get("vendor") in ("nvidia", "amd", "intel"):
            _vendors_present.add(integrated["vendor"])
        for vkey, vlabel in _VENDOR_LABELS:
            if vkey in _vendors_present:
                self.cb_dml_vendor.addItem(vlabel)
                self._dml_vendor_keys.append(vkey)
        # 若未检测到任何 DirectML 设备（CPU-only / 不支持），保留全部3个选项供演示
        if not self._dml_vendor_keys:
            for vkey, vlabel in _VENDOR_LABELS:
                self.cb_dml_vendor.addItem(vlabel)
                self._dml_vendor_keys.append(vkey)
        self.cb_dml_vendor.setMinimumWidth(int(180 * us))
        dml_row.addWidget(dml_lbl)
        dml_row.addWidget(self.cb_dml_vendor, 1)
        dml_row.addStretch()
        arch_inner.addLayout(dml_row)

        arch_hint = QLabel(
            "无论选择何种使用目的，均需选择计算架构。\n"
            "  · CUDA：NVIDIA 独显专用，速度最快（推荐）；\n"
            "  · DirectML：NVIDIA / AMD / Intel 通用 GPU 加速；\n"
            "  · 纯 CPU：无 GPU 加速，速度极慢。\n"
            "NVIDIA 独显建议优先 CUDA。")
        arch_hint.setWordWrap(True)
        arch_hint.setStyleSheet("color: #666;")
        f = arch_hint.font()
        f.setPointSize(self._fs_hint_px)
        arch_hint.setFont(f)
        arch_inner.addWidget(arch_hint)
        rows.addWidget(arch_box)

        # 根据硬件自动选择默认架构 + DirectML 厂商
        self._apply_default_arch(discrete, integrated, gpu_ok)
        # DirectML 厂商切换时联动控温库（架构变更由 _on_arch_changed 统一处理）
        self.cb_dml_vendor.currentIndexChanged.connect(self._update_thermal_lib)

        for key, name, desc_text, default, locked, enabled, reason in features:
            cb = QCheckBox(name)
            cb.setChecked(default)
            if locked or not enabled:
                cb.setEnabled(False)
                if not enabled:
                    cb.setChecked(False)
            text = desc_text + (f"（{reason}）" if (reason and not enabled) else "")
            desc_lbl = QLabel(text)
            desc_lbl.setStyleSheet(f"color: {'#999' if not enabled else '#666'};")
            f = desc_lbl.font()
            f.setPointSize(self._fs_hint_px)
            desc_lbl.setFont(f)

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(cb)
            row.addWidget(desc_lbl, 1)
            wrap = QWidget()
            wrap.setLayout(row)
            rows.addWidget(wrap)
            self._feature_cbs[key] = cb
            # 控温组件保存引用，供架构/厂商切换时动态更新库名与描述
            if key == "thermal":
                self._thermal_cb = cb
                self._thermal_desc_lbl = desc_lbl

        # thermal 引用就绪后，立即按当前架构初始化库名
        self._update_thermal_lib()

        # 程序文件清单（展示完整安装文件）
        sep = QLabel("程序文件")
        sep.setStyleSheet(
            f"color: #888; font-weight: bold; padding-top: {max(int(8 * us), 6)}px;")
        sf = sep.font()
        sf.setPointSize(self._fs_body_px)
        sep.setFont(sf)
        rows.addWidget(sep)
        for fn in file_list:
            fl = QLabel("  " + fn)
            fl.setStyleSheet("color: #666;")
            ff = fl.font()
            ff.setPointSize(self._fs_hint_px)
            fl.setFont(ff)
            rows.addWidget(fl)

        rows.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        if purpose == "use":
            layout.addWidget(self._hint("仅使用模型时，训练相关组件已自动禁用。"))

    def _apply_default_arch(self, discrete, integrated, gpu_ok):
        """根据硬件自动选择默认架构与 DirectML 厂商。

        优先级：NVIDIA 独显 → CUDA；AMD/Intel 独显或核显 → DirectML；其余 → 纯CPU。
        DirectML 厂商下拉按检测到的显卡厂商自动推荐：
          NVIDIA → N 卡；AMD → A 卡；Intel → I 卡。
        """
        has_nv_discrete = bool(discrete and discrete.get("vendor") == "nvidia" and gpu_ok)
        has_igpu = bool(integrated and integrated.get("vendor") in ("amd", "intel") and gpu_ok)
        has_amd_discrete = bool(discrete and discrete.get("vendor") in ("amd", "intel") and gpu_ok)
        # DirectML 对所有 GPU 类型可用（含 NVIDIA，作为备选）
        has_directml = has_igpu or has_amd_discrete or has_nv_discrete

        # 默认勾选优先级：NVIDIA 独显 → CUDA；其余有 GPU → DirectML；无 GPU → 纯CPU
        # （用户仍可手动勾选 DirectML 作为 N 卡的备选后端）
        if has_nv_discrete:
            self.rb_cuda.setChecked(True)
        elif has_directml:
            self.rb_directml.setChecked(True)
        else:
            self.rb_cpu.setChecked(True)

        # DirectML 厂商自动推荐（按当前下拉可选项的索引）
        def _vendor_idx(vendor):
            return self._dml_vendor_keys.index(vendor) if vendor in self._dml_vendor_keys else 0

        if has_amd_discrete or (integrated and integrated.get("vendor") == "amd"):
            self.cb_dml_vendor.setCurrentIndex(_vendor_idx("amd"))
        elif has_igpu and integrated and integrated.get("vendor") == "intel":
            self.cb_dml_vendor.setCurrentIndex(_vendor_idx("intel"))
        elif discrete and discrete.get("vendor") == "nvidia":
            self.cb_dml_vendor.setCurrentIndex(_vendor_idx("nvidia"))
        else:
            self.cb_dml_vendor.setCurrentIndex(0)

    def _on_arch_changed(self):
        """架构选择变更时统一联动：DirectML 厂商下拉状态 + 控温库。"""
        self._update_dml_vendor_state()
        self._update_thermal_lib()
        self.arch_changed.emit()  # 通知主窗口刷新下一步按钮状态

    def get_selected_archs(self):
        """返回选中的架构列表（CUDA/DirectML/CPU 至少选 1 个）。"""
        archs = []
        if self.rb_cuda.isChecked():
            archs.append("cuda")
        if self.rb_directml.isChecked():
            archs.append("directml")
        if self.rb_cpu.isChecked():
            archs.append("cpu")
        return archs

    def validate_archs(self):
        """验证至少选了 1 个架构，否则返回错误提示。"""
        if not (self.rb_cuda.isChecked() or self.rb_directml.isChecked() or self.rb_cpu.isChecked()):
            return "请至少选择一个架构（CUDA / DirectML / 纯 CPU）"
        return None

    def _update_dml_vendor_state(self):
        """DirectML 勾选时启用厂商下拉，其余禁用。"""
        is_dml = self.rb_directml.isChecked()
        self.cb_dml_vendor.setEnabled(is_dml)

    def _update_thermal_lib(self):
        """根据所选架构组合动态切换控温组件的库名与描述（支持多选）。

        控温组件必选（锁定勾选），实际安装的库随架构组合变化：
          - CUDA：pynvml（NVIDIA GPU 温度监控）
          - DirectML + N 卡：pynvml（NVIDIA）
          - DirectML + A 卡：pyadl（AMD GPU 温度监控）
          - DirectML + I 卡：intel-thermal（Intel 集显温度监控，通过 WMIC）
          - 纯 CPU：cpu-temp（CPU 温度监控，通过 psutil/wmi）
        多选时显示所有选中架构需要的库，用 " + " 连接（去重）。
        """
        if not getattr(self, "_thermal_cb", None) or not self._thermal_desc_lbl:
            return

        libs = []
        descs = []

        if self.rb_cuda.isChecked():
            libs.append("pynvml")
            descs.append("NVIDIA GPU 温度监控")

        if self.rb_directml.isChecked():
            idx = self.cb_dml_vendor.currentIndex()
            vendor = self._dml_vendor_keys[idx] if 0 <= idx < len(self._dml_vendor_keys) else "nvidia"
            if vendor == "amd":
                libs.append("pyadl")
                descs.append("AMD GPU 温度监控")
            elif vendor == "intel":
                libs.append("intel-thermal")
                descs.append("Intel 集显温度监控（WMIC）")
            else:  # nvidia
                libs.append("pynvml")
                descs.append("NVIDIA GPU 温度监控")

        if self.rb_cpu.isChecked():
            libs.append("cpu-temp")
            descs.append("CPU 温度监控（psutil/wmi）")

        # 去重（CUDA + DirectML+N 都需要 pynvml，只显示一次）
        seen = set()
        unique_libs = []
        unique_descs = []
        for lib, desc in zip(libs, descs):
            if lib not in seen:
                seen.add(lib)
                unique_libs.append(lib)
                unique_descs.append(desc)

        if not unique_libs:
            self._thermal_cb.setText("（请选择架构）")
            self._thermal_desc_lbl.setText("未选择架构，控温库待确定（必装）")
        else:
            self._thermal_cb.setText(" + ".join(unique_libs))
            self._thermal_desc_lbl.setText(" + ".join(unique_descs) + "（必装）")


# ===== 模型架构数据 =====
# 仅保留 patch=16 的模型（匹配旗帜16像素纹理）+ ViT-H/14（patch=14接近16）
# (key, 显示名, 参数量, 训练显存GB, .pth下载GB, 下载方式, 说明, 依赖)
# vram_gb：训练时所需显存（用于显存适配标记）
# pth_dl_gb：.pth 权重文件实际下载大小（用于磁盘空间估算和界面显示）
#   所有模型（ViT/DeiT）均通过 torchvision 在线下载预训练权重
_MODEL_ARCHS = [
    ("vit_b_16",  "ViT-B/16",      "86M",   0.8,  0.34, "online",
     "patch=16 匹配旗帜纹理，平衡精度与速度", None),
    ("vit_l_16",  "ViT-L/16",      "304M",  1.6,  1.20, "online",
     "patch=16，高精度但需更多显存", None),
    ("vit_h_14",  "ViT-H/14",      "~630M", 2.5,  2.50, "online",
     "patch=14 接近16，最强精度但需高端显卡", None),
    ("deit_b_16", "DeiT-B/16",    "86M",   0.8,  0.33, "online",
     "patch=16 匹配旗帜纹理，DeiT 数据增强策略提升小数据集泛化能力", None),
    ("deit_s_16", "DeiT-S/16",    "22M",   0.3,  0.09, "online",
     "轻量化 DeiT（patch=16），适合核显/CPU 训练与推理", None),
    ("deit_t_16", "DeiT-T/16",    "5M",    0.15, 0.02, "online",
     "超轻量 DeiT（patch=16），极速训练，预训练权重加速收敛", None),
]

_DOWNLOAD_LABELS = {
    "online": "在线下载（torchvision）",
}


# ===== 页面 5：模型架构选择 =====
class _ModelArchPage(_PageBase):
    def __init__(self, us, hw_info=None, maintenance=False, parent=None):
        super().__init__(us, parent)
        self._hw_info = hw_info or {}
        self._arch_checks = {}
        self._maintenance = maintenance

        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(8 * us), 6))

        if maintenance:
            layout.addWidget(self._title("管理模型与训练组件"))
            layout.addWidget(self._desc(
                "勾选要安装的模型架构与训练工具，取消勾选已安装的组件将卸载。"
                "ViT 系列可从在线仓库下载预训练权重，DeiT 系列为内置可训练架构（无需下载）。"))
        else:
            layout.addWidget(self._title("选择模型架构文件"))
            layout.addWidget(self._desc(
                "选择需要下载/安装的模型架构。ViT 系列可从在线仓库直接下载预训练权重，"
                "DeiT 系列为内置可训练架构，安装后可直接从零训练，无需下载权重。"))

        # 滚动区域
        scroll = _FixedScrollArea(us)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(max(int(4 * us), 3))

        gpu = self._hw_info.get("gpu", {})
        discrete = gpu.get("discrete")
        vram = 0
        if discrete:
            vram = discrete.get("vram_gb", 0)

        for key, name, params, vram_gb, pth_dl_gb, dl_method, desc, depends in _MODEL_ARCHS:
            card = self._make_arch_card(
                key, name, params, vram_gb, pth_dl_gb, dl_method, desc, depends, vram)
            scroll_layout.addWidget(card)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, 1)

        # 全选/全不选按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(max(int(8 * us), 6))
        btn_select_all = QPushButton("全选")
        btn_select_all.clicked.connect(lambda: self._toggle_all(True))
        btn_deselect_all = QPushButton("全不选")
        btn_deselect_all.clicked.connect(lambda: self._toggle_all(False))
        btn_row.addWidget(btn_select_all)
        btn_row.addWidget(btn_deselect_all)
        btn_row.addStretch()
        lbl_total = QLabel()
        lbl_total.setStyleSheet(f"color: #666;")
        f = lbl_total.font()
        f.setPointSize(self._fs_hint_px)
        lbl_total.setFont(f)
        self._lbl_total = lbl_total
        btn_row.addWidget(lbl_total)
        layout.addLayout(btn_row)

        # 默认选择
        self._select_defaults(vram)

    def _make_arch_card(self, key, name, params, vram_gb, pth_dl_gb, dl_method, desc, depends, vram):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ border: 1px solid #e0e0e0; border-radius: 6px; "
            f"background: #fff; padding: {max(int(4 * self._us), 3)}px; }}")
        cl = QVBoxLayout(card)
        m = max(int(6 * self._us), 4)
        cl.setContentsMargins(m, m, m, m)
        cl.setSpacing(max(int(3 * self._us), 2))

        row1 = QHBoxLayout()
        row1.setSpacing(max(int(6 * self._us), 4))

        cb = QCheckBox(name)
        f = cb.font()
        f.setPointSize(self._fs_body_px)
        f.setBold(True)
        cb.setFont(f)
        cb.stateChanged.connect(lambda _: self._update_total())
        self._arch_checks[key] = cb
        row1.addWidget(cb)

        # 显存适配标记
        if vram > 0:
            if vram_gb <= vram * 0.6:
                fit_lbl = QLabel("✓ 适配")
                fit_lbl.setStyleSheet("color: #27ae60;")
            elif vram_gb <= vram:
                fit_lbl = QLabel("⚠ 刚好")
                fit_lbl.setStyleSheet("color: #e67e22;")
            else:
                fit_lbl = QLabel("✗ 超出显存")
                fit_lbl.setStyleSheet("color: #c0392b;")
            ff = fit_lbl.font()
            ff.setPointSize(self._fs_hint_px)
            fit_lbl.setFont(ff)
            row1.addWidget(fit_lbl)

        row1.addStretch()

        dl_lbl = QLabel(_DOWNLOAD_LABELS.get(dl_method, dl_method))
        dl_lbl.setStyleSheet("color: #1a73e8;")
        fd = dl_lbl.font()
        fd.setPointSize(self._fs_hint_px)
        dl_lbl.setFont(fd)
        row1.addWidget(dl_lbl)

        # 下载大小显示：用实际 .pth 文件大小，非训练显存
        if dl_method != "arch" and pth_dl_gb > 0:
            size_lbl = QLabel(f"下载 ~{pth_dl_gb:.1f} GB")
            size_lbl.setStyleSheet("color: #666;")
            fs = size_lbl.font()
            fs.setPointSize(self._fs_hint_px)
            size_lbl.setFont(fs)
            row1.addWidget(size_lbl)

        cl.addLayout(row1)

        # 第二行：参数量 + 说明
        row2 = QHBoxLayout()
        row2.setSpacing(max(int(6 * self._us), 4))
        row2.addSpacing(max(int(20 * self._us), 16))

        info = QLabel(f"{params} · {desc}")
        info.setStyleSheet("color: #666;")
        fi = info.font()
        fi.setPointSize(self._fs_hint_px)
        info.setFont(fi)
        info.setWordWrap(True)
        row2.addWidget(info, 1)
        cl.addLayout(row2)

        # 依赖提示
        if depends:
            dep_lbl = QLabel(f"  ⚠ 依赖 {_dep_name(depends)}，将自动一并下载")
            dep_lbl.setStyleSheet("color: #e67e22;")
            fd2 = dep_lbl.font()
            fd2.setPointSize(self._fs_hint_px)
            dep_lbl.setFont(fd2)
            cl.addWidget(dep_lbl)

        return card

    def _toggle_all(self, checked):
        for cb in self._arch_checks.values():
            cb.setChecked(checked)
        self._update_total()

    def _select_defaults(self, vram):
        """根据硬件自动选择默认模型。"""
        if self._maintenance:
            # 维护模式：全选（假设已安装，取消勾选=卸载）
            for cb in self._arch_checks.values():
                cb.setChecked(True)
            self._update_total()
            return
        # 正常安装模式：DeiT-S/16 和 DeiT-T/16 始终推荐（轻量）
        # ViT-B/16 如果显存够也推荐
        self._arch_checks["deit_s_16"].setChecked(True)
        self._arch_checks["deit_t_16"].setChecked(True)
        if vram >= 4:
            self._arch_checks["vit_b_16"].setChecked(True)
            self._arch_checks["deit_b_16"].setChecked(True)
        if vram >= 8:
            self._arch_checks["vit_l_16"].setChecked(True)
        self._update_total()

    def _update_total(self):
        total = 0
        count = 0
        for key, cb in self._arch_checks.items():
            if cb.isChecked():
                for arch in _MODEL_ARCHS:
                    if arch[0] == key:
                        total += arch[4]  # pth_dl_gb：实际下载大小
                        count += 1
                        break
        parts = []
        if count:
            parts.append(f"可下载模型 {count} 个，共 ~{total:.1f} GB")
        self._lbl_total.setText("；".join(parts) if parts else "未选择任何模型")

    def get_selected(self):
        """返回选中的模型架构 key 列表。"""
        selected = []
        for key, cb in self._arch_checks.items():
            if cb.isChecked():
                selected.append(key)
        return selected


def _dep_name(key):
    """依赖模型的显示名。"""
    for arch in _MODEL_ARCHS:
        if arch[0] == key:
            return arch[1]
    return key


# ===== 页面 5.5：安装路径选择 =====
class _InstallPathPage(_PageBase):
    """选择安装盘符与路径，并检测该盘可用空间（含加载延迟模拟）。

    模拟环境：盘符列表与可用空间由 visualcondition 生成的 disks 提供，切换盘符时
    模拟约 0.6s 的检测延迟。本机模式：枚举真实盘符并实时检测可用空间。
    """

    space_checked = pyqtSignal()  # 空间检测完成（用于刷新下一步按钮）

    def __init__(self, us, parent=None):
        super().__init__(us, parent)
        self._hw_info = None
        self._install_state = None
        self._disks = []
        self._is_real = False
        self._load_timer = None
        self._required_gb = 10.0  # 默认值，populate 时按勾选架构动态更新

        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(8 * us), 6))

        layout.addWidget(self._title("选择安装位置"))
        layout.addWidget(self._desc("请选择安装盘符与文件夹，程序将检测该盘的可用空间。"))

        # 盘符选择
        drive_row = QHBoxLayout()
        drive_row.setSpacing(max(int(8 * us), 4))
        lbl_drive = QLabel("安装盘符:")
        f = lbl_drive.font(); f.setPointSize(self._fs_body_px); lbl_drive.setFont(f)
        self.cb_drive = QComboBox()
        self.cb_drive.setMinimumWidth(int(240 * us))
        self.cb_drive.currentIndexChanged.connect(self._on_drive_changed)
        drive_row.addWidget(lbl_drive)
        drive_row.addWidget(self.cb_drive, 1)
        drive_row.addStretch()
        layout.addLayout(drive_row)

        # 路径输入
        path_row = QHBoxLayout()
        path_row.setSpacing(max(int(8 * us), 4))
        lbl_path = QLabel("安装文件夹:")
        f = lbl_path.font(); f.setPointSize(self._fs_body_px); lbl_path.setFont(f)
        self.txt_path = QLineEdit("我的世界旗帜逆向套件")
        self.txt_path.setMinimumWidth(int(260 * us))
        self.txt_path.textChanged.connect(self._update_full_path)
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._on_browse)
        path_row.addWidget(lbl_path)
        path_row.addWidget(self.txt_path, 1)
        path_row.addWidget(btn_browse)
        layout.addLayout(path_row)

        # 完整路径预览
        self.lbl_full = QLabel("")
        self.lbl_full.setWordWrap(True)
        self.lbl_full.setStyleSheet("color: #888; padding: 2px 2px;")
        f = self.lbl_full.font(); f.setPointSize(self._fs_hint_px); self.lbl_full.setFont(f)
        layout.addWidget(self.lbl_full)

        # 空间信息
        self.lbl_space = QLabel("")
        self.lbl_space.setWordWrap(True)
        self.lbl_space.setStyleSheet("color: #444; padding: 4px 2px;")
        f = self.lbl_space.font(); f.setPointSize(self._fs_body_px); self.lbl_space.setFont(f)
        layout.addWidget(self.lbl_space)

        layout.addStretch()
        self._hint_label = self._hint(
            f"安装所需至少 {self._required_gb:.1f} GB 可用空间。演示模式下盘符与空间均为模拟值，"
            "切换盘符时模拟检测延迟。")
        layout.addWidget(self._hint_label)

    def populate(self, hw_info, install_state=None, archs=None):
        """进入页面时填充盘符列表。

        Args:
            archs: 用户在库选择页勾选的架构列表，用于动态计算所需磁盘空间。
        """
        self._hw_info = hw_info or {}
        self._install_state = install_state or {}
        # 根据勾选架构动态计算所需空间
        self._required_gb = _compute_required_gb(archs)
        self._hint_label.setText(
            f"安装所需至少 {self._required_gb:.1f} GB 可用空间。演示模式下盘符与空间均为模拟值，"
            "切换盘符时模拟检测延迟。")
        disks = self._hw_info.get("disks")
        sim_allow = self._hw_info.get("_sim_allow", "")
        self._is_real = (sim_allow in ("", "本机")) or not disks
        self._disks = disks if disks else self._enum_real_disks()

        self.cb_drive.blockSignals(True)
        self.cb_drive.clear()
        for d in self._disks:
            self.cb_drive.addItem(self._fmt_drive(d))
        self.cb_drive.blockSignals(False)

        # 已安装则预填路径并选中其盘符
        if self._install_state.get("installed"):
            inst_path = self._install_state.get("path", "") or ""
            if inst_path:
                letter = inst_path[:1].upper()
                sub = inst_path[3:] if len(inst_path) > 3 and inst_path[1:3] == ":\\" else inst_path
                self.txt_path.setText(sub or "我的世界旗帜逆向套件")
                for i, d in enumerate(self._disks):
                    if d.get("letter", "").upper() == letter:
                        self.cb_drive.setCurrentIndex(i)
                        break
        if self.cb_drive.count() == 0:
            self.cb_drive.addItem("C: (未知)")
            self._disks = [{"letter": "C", "label": "本地盘", "total_gb": 0, "free_gb": 0, "type": ""}]
        self._on_drive_changed(self.cb_drive.currentIndex())
        self._update_full_path()

    def _fmt_drive(self, d):
        letter = d.get("letter", "?")
        label = d.get("label", "")
        dtype = d.get("type", "")
        total = d.get("total_gb", 0)
        parts = [f"{letter}:"]
        if label:
            parts.append(f"〔{label}")
        if dtype:
            parts.append(f"· {dtype}")
        if total:
            parts.append(f"· {total}GB")
        if label:
            parts.append("〕")
        return " ".join(parts)

    def _enum_real_disks(self):
        """枚举本机真实可用盘符（A~Z）。"""
        import string
        result = []
        for ch in string.ascii_uppercase:
            drive = f"{ch}:"
            if os.path.exists(drive + os.sep):
                free = _w32_get_disk_free_gb(ch)
                result.append({"letter": ch, "label": "本地盘",
                               "total_gb": 0, "free_gb": free, "type": ""})
        return result or [{"letter": "C", "label": "本地盘", "total_gb": 0, "free_gb": 0, "type": ""}]

    def _on_drive_changed(self, idx):
        if idx < 0 or not self._disks or idx >= len(self._disks):
            self.lbl_space.setText("无可选盘符")
            self._update_full_path()
            self.space_checked.emit()
            return
        # 模拟加载延迟
        self.lbl_space.setText("正在检测磁盘空间...")
        self.lbl_space.setStyleSheet("color: #666; padding: 4px 2px;")
        if self._load_timer:
            self._load_timer.stop()
        delay = 600 if not self._is_real else 300
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(lambda: self._show_space(idx))
        self._load_timer.start(delay)
        self._update_full_path()

    def _show_space(self, idx):
        d = self._disks[idx]
        free = d.get("free_gb", 0)
        total = d.get("total_gb", 0)
        dtype = d.get("type", "")
        letter = d.get("letter", "?")
        enough = free >= self._required_gb
        if total:
            info = f"{letter}: 盘 {dtype} {total} GB 总容量 · 可用 {free} GB"
        else:
            info = f"{letter}: 盘 · 可用 {free} GB"
        status = "（空间充足）" if enough else f"（不足！需 {self._required_gb:.1f} GB）"
        color = "#2e7d32" if enough else "#c62828"
        self.lbl_space.setText(info + "  " + status)
        self.lbl_space.setStyleSheet(f"color: {color}; padding: 4px 2px; font-weight: bold;")
        self.space_checked.emit()

    def _update_full_path(self):
        idx = self.cb_drive.currentIndex()
        letter = self._disks[idx].get("letter", "C") if 0 <= idx < len(self._disks) else "C"
        sub = self.txt_path.text().strip() or "我的世界旗帜逆向套件"
        full = os.path.join(f"{letter}:", os.sep, sub)
        self.lbl_full.setText(f"完整路径：{full}")

    def _on_browse(self):
        start_dir = self.get_install_path()
        chosen = QFileDialog.getExistingDirectory(self, "选择安装文件夹", start_dir)
        if not chosen:
            return
        letter = chosen[:1].upper()
        sub = chosen[3:] if len(chosen) > 3 and chosen[1:3] == ":\\" else ""
        if sub:
            self.txt_path.setText(sub)
        for i, d in enumerate(self._disks):
            if d.get("letter", "").upper() == letter:
                self.cb_drive.setCurrentIndex(i)
                break

    def is_space_enough(self):
        idx = self.cb_drive.currentIndex()
        if idx < 0 or idx >= len(self._disks):
            return False
        return self._disks[idx].get("free_gb", 0) >= self._required_gb

    def get_install_path(self):
        idx = self.cb_drive.currentIndex()
        letter = self._disks[idx].get("letter", "C") if 0 <= idx < len(self._disks) else "C"
        sub = self.txt_path.text().strip() or "我的世界旗帜逆向套件"
        return os.path.join(f"{letter}:", os.sep, sub)


# ===== 按架构区分的库版本表（与 visualcondition._LIB_VERSIONS 一致）=====
_ARCH_LIBS = {
    "cuda": [
        ("torch",            "2.9.1+cu130",     "2.5GB"),
        ("torchvision",      "0.24.1+cu130",    "50MB"),
        ("PyQt5",            "5.15.11",         "120MB"),
        ("numpy",            "2.5.1",           "18MB"),
        ("opencv-python",    "4.14.0.94",       "60MB"),
        ("Pillow",           "12.3.0",          "5MB"),
        ("matplotlib",       "3.11.1",          "40MB"),
        ("psutil",           "7.2.2",           "500KB"),
        ("pynvml",           "12.575.51",       "50KB"),
    ],
    "directml": [
        ("torch-directml",   "0.2.5.dev240914", "200MB"),
        ("torchvision",      "0.18.1",          "7MB"),
        ("PyQt5",            "5.15.11",         "120MB"),
        ("numpy",            "2.5.1",           "18MB"),
        ("opencv-python",    "4.14.0.94",       "60MB"),
        ("Pillow",           "12.3.0",          "5MB"),
        ("matplotlib",       "3.11.1",          "40MB"),
        ("psutil",           "7.2.2",           "500KB"),
    ],
    "cpu": [
        ("torch",            "2.4.0+cpu",       "200MB"),
        ("torchvision",      "0.19.0+cpu",      "30MB"),
        ("PyQt5",            "5.15.11",         "120MB"),
        ("numpy",            "2.5.1",           "18MB"),
        ("opencv-python",    "4.14.0.94",       "60MB"),
        ("Pillow",           "12.3.0",          "5MB"),
        ("matplotlib",       "3.11.1",          "40MB"),
        ("psutil",           "7.2.2",           "500KB"),
    ],
}


# ===== 体积估算（根据勾选的架构与库动态计算所需磁盘空间） =====
# 固定开销：Python 3.13.14 运行时 + pip + 程序文件
_BASE_OVERHEAD_GB = 0.3


def _parse_size_to_gb(size_str):
    """解析体积文本为 GB 浮点数。如 '2.5GB'->2.5, '50MB'->0.049, '500KB'->0.0005"""
    s = (size_str or "").strip().upper()
    try:
        if s.endswith("GB"):
            return float(s[:-2].strip())
        if s.endswith("MB"):
            return float(s[:-2].strip()) / 1024.0
        if s.endswith("KB"):
            return float(s[:-2].strip()) / (1024.0 * 1024.0)
        return float(s)
    except (ValueError, IndexError):
        return 0.0


def _compute_required_gb(archs):
    """根据选中的架构列表计算预计所需磁盘空间(GB)。

    多架构共有的库（如 PyQt5/numpy）只计一次（去重）。
    """
    total = _BASE_OVERHEAD_GB
    seen = set()
    for arch in (archs or ["cpu"]):
        for lib_name, _lib_ver, lib_size in _ARCH_LIBS.get(arch, []):
            if lib_name not in seen:
                seen.add(lib_name)
                total += _parse_size_to_gb(lib_size)
    # DirectML 模式额外需要精简版 Python 3.10.11 环境（dml_env/，约 1.3GB）
    if "directml" in (archs or []):
        total += 1.3
    # 最低 1.0 GB，保留 1 位小数
    return round(max(total, 1.0), 1)


# ===== 页面 6：进度 =====
class _ProgressPage(_PageBase):
    def __init__(self, us, parent=None):
        super().__init__(us, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(8 * us), 6))

        self.lbl_title = self._title("正在安装")
        layout.addWidget(self.lbl_title)

        self.status_label = QLabel("准备中...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # 进度条 + ETA 水平布局（与真实安装器一致）
        prog_row = QHBoxLayout()
        prog_row.setSpacing(max(int(8 * us), 6))
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        prog_row.addWidget(self.progress, 1)
        self.eta_label = QLabel("")
        self.eta_label.setStyleSheet(
            "color: #1a73e8; font-weight: bold; padding-left: 4px;")
        f_eta = self.eta_label.font()
        f_eta.setPointSize(self._fs_hint_px)
        f_eta.setBold(True)
        self.eta_label.setFont(f_eta)
        self.eta_label.setMinimumWidth(max(int(120 * us), 100))
        self.eta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        prog_row.addWidget(self.eta_label)
        layout.addLayout(prog_row)

        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        self.detail_label.setMinimumHeight(max(int(90 * us), 72))
        self.detail_label.setStyleSheet(
            "background: #f8f8f8; border: 1px solid #ddd; padding: 6px; "
            "font-family: Consolas, monospace; color: #777;")
        f = self.detail_label.font()
        f.setPointSize(self._fs_hint_px)
        self.detail_label.setFont(f)
        layout.addWidget(self.detail_label)

        layout.addStretch()
        self._thread = None
        self._mode = "install"
        self._archs = ["cuda"]  # 默认架构，由主窗口在 start 前设置

    def set_archs(self, archs):
        """设置选中的架构列表，用于动态显示安装库。"""
        self._archs = archs if archs else ["cuda"]

    def _build_lib_details(self):
        """根据选中的架构列表构建合并去重的库列表。"""
        seen = set()
        result = []
        for arch in self._archs:
            for item in _ARCH_LIBS.get(arch, []):
                name = item[0]
                if name not in seen:
                    seen.add(name)
                    result.append(item)
        return result

    def start(self, mode, models=None, purpose="train"):
        self._mode = mode
        self._models = models or []
        self._purpose = purpose
        self.lbl_title.setText(_MODE_TITLE[mode])
        self.progress.setValue(0)
        self.detail_label.setText("")
        self.status_label.setText("准备中...")
        self._start_time = time.time()
        self._thread = _FakeInstallThread(mode, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._on_done)
        self._thread.start()

    def _on_progress(self, value, text):
        self.progress.setValue(value)
        # 模拟 ETA 估算：基于已耗时和进度百分比
        eta_str = ""
        if value > 0 and hasattr(self, '_start_time'):
            elapsed = time.time() - self._start_time
            total_est = elapsed / value * 100
            remaining = max(0, total_est - elapsed)
            if remaining < 60:
                eta_str = f" （预计剩余 {remaining:.0f} 秒）"
            elif remaining < 3600:
                eta_str = f"  （预计剩余 {remaining / 60:.1f} 分钟）"
            else:
                eta_str = f"  （预计剩余 {remaining / 3600:.1f} 小时）"
        self.status_label.setText(text + eta_str)
        verb = {"install": "正在安装", "uninstall": "正在删除",
                "manage_components": "正在管理"}.get(self._mode, "正在处理")

        # Python 下载安装步骤（仅 install 模式，0-22%）
        py_steps = [
            ("Python 3.13.14", "3.13.14", "27MB"),
            ("pip",            "24.2",    "8MB"),
        ]
        # 库细节：根据选中架构动态构建（合并去重）
        lib_details = self._build_lib_details()
        # 程序文件
        file_list = [
            "models\\structures\\vit_model.py",
            "utils\\device_backend.py",
            "utils\\mbtl_utils.py",
            "installer\\setup_hardware.py",
            "scripts\\error_reporter.pyw",
            "trainer.pyw",
            "importer.pyw",
        ]

        if self._mode == "uninstall":
            idx = min(int(value / 100 * len(file_list)), len(file_list) - 1)
            shown = file_list[:idx + 1]
            self.detail_label.setText(f"{verb}:\n" + "\n".join(f"  ✗ {f}" for f in shown))
            return

        if self._mode == "manage_components":
            # 管理组件：显示 pip 库增删 + 模型文件增删过程
            lines = []
            # 5-20%: 卸载取消的 pip 包
            if value >= 20:
                lines.append("  ✓ 卸载取消选择的库")
            elif value >= 5:
                lines.append("  → 卸载取消选择的库")
            else:
                lines.append("    卸载取消选择的库")
            # 20-35%: 删除取消的 .pth 文件
            if value >= 35:
                lines.append("  ✓ 删除取消选择的模型文件")
            elif value >= 20:
                lines.append("  → 删除取消选择的模型文件")
            else:
                lines.append("    删除取消选择的模型文件")
            # 35-75%: 安装新增 pip 包（CMD 窗口）
            if value >= 75:
                lines.append("  ✓ 安装新增库（pip 安装）")
            elif value >= 35:
                lines.append("  → 安装新增库（CMD 窗口中）")
            else:
                lines.append("    安装新增库（pip 安装）")
            # 75-90%: 下载新增 .pth 模型权重
            models = getattr(self, '_models', []) or []
            if models:
                if value >= 90:
                    lines.append("  ✓ 下载新增模型权重")
                elif value >= 75:
                    lines.append("  → 下载新增模型权重")
                else:
                    lines.append("    下载新增模型权重")
            # 90-95%: 更新快捷方式
            if value >= 95:
                lines.append("  ✓ 更新快捷方式")
            elif value >= 90:
                lines.append("  → 更新快捷方式")
            else:
                lines.append("    更新快捷方式")
            # 95-100%: 更新组件清单
            if value >= 100:
                lines.append("  ✓ 更新组件清单")
            elif value >= 95:
                lines.append("  → 更新组件清单")
            else:
                lines.append("    更新组件清单")
            self.detail_label.setText(f"{verb}:\n" + "\n".join(lines))
            return

        # install 模式：Python(0-22%) → 库(22-75%) → 文件(75-100%)
        # manage_components 模式：库(0-70%) → 文件(70-100%)
        if self._mode == "install":
            py_count = len(py_steps)
            lib_count = len(lib_details)
            file_count = len(file_list)
            # 比例分配：Python 占 22%，库占 53%，文件占 25%
            py_end = 22
            lib_end = 75
            lines = []

            # Python 部分（0-22%）
            for i, (name, ver, size) in enumerate(py_steps):
                py_progress = py_end * (i + 1) / py_count
                if value < py_progress:
                    if value >= py_end * i / py_count:
                        mark = "→"
                    else:
                        mark = " "
                else:
                    mark = "✓"
                lines.append(f"  {mark} {name:18} {ver:18} ({size})")

            # 库部分（22-75%）
            if value >= py_end:
                lines.append("")
                lib_span = lib_end - py_end
                for i, (name, ver, size) in enumerate(lib_details):
                    lib_progress = lib_end + lib_span * (i - lib_count) / lib_count
                    lib_start_i = py_end + lib_span * i / lib_count
                    if value < lib_start_i:
                        mark = " "
                    elif value < lib_end + lib_span * (i + 1) / lib_count:
                        mark = "→"
                    else:
                        mark = "✓"
                    lines.append(f"  {mark} {name:18} {ver:18} ({size})")

            # 文件部分（75-100%）
            if value >= lib_end:
                lines.append("")
                file_span = 100 - lib_end
                for i, f in enumerate(file_list):
                    file_start_i = lib_end + file_span * i / file_count
                    if value < file_start_i:
                        mark = " "
                    elif value < lib_end + file_span * (i + 1) / file_count:
                        mark = "→"
                    else:
                        mark = "✓"
                    lines.append(f"  {mark} {f}")

            self.detail_label.setText(f"{verb}:\n" + "\n".join(lines))
            return

        # manage_components / 其他模式：库(0-70%) → 文件(70-100%)
        lib_count = len(lib_details)
        file_count = len(file_list)
        total = lib_count + file_count
        current = min(int(value / 100 * total), total - 1)

        lines = []
        for i, (name, ver, size) in enumerate(lib_details):
            if i < current:
                mark = "✓"
            elif i == current:
                mark = "→"
            else:
                mark = " "
            lines.append(f"  {mark} {name:18} {ver:18} ({size})")

        if current >= lib_count:
            lines.append("")
            file_idx = current - lib_count
            for i, f in enumerate(file_list):
                if i < file_idx:
                    mark = "✓"
                elif i == file_idx:
                    mark = "→"
                else:
                    mark = " "
                lines.append(f"  {mark} {f}")

        self.detail_label.setText(f"{verb}:\n" + "\n".join(lines))

    def _on_done(self):
        self.status_label.setText(_STEPS[self._mode][-1][1])


# ===== 页面 6：结束 =====
class _CompletePage(_PageBase):
    def __init__(self, us, parent=None):
        super().__init__(us, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(10 * us), 8))

        self.lbl_title = self._title("安装成功")
        layout.addWidget(self.lbl_title)

        self.lbl_desc = self._desc("我的世界旗帜逆向套件已成功安装到您的计算机。")
        layout.addWidget(self.lbl_desc)

        self.cb_launch = QCheckBox("立即启动我的世界旗帜逆向套件")
        self.cb_launch.setChecked(True)
        layout.addWidget(self.cb_launch)

        layout.addStretch()

        layout.addWidget(self._hint("※ 演示模式：实际上没有进行任何操作。"))

    def set_result(self, mode):
        texts = {
            "install":           ("安装成功", "我的世界旗帜逆向套件已成功安装到您的计算机。"),
            "uninstall":         ("卸载成功", "我的世界旗帜逆向套件已从您的计算机移除。"),
            "manage_components": ("组件管理完成", "组件管理已完成，模型架构与训练工具已更新。"),
        }
        title, desc = texts.get(mode, texts["install"])
        self.lbl_title.setText(title)
        self.lbl_desc.setText(desc)
        # 卸载和管理组件模式不显示"立即启动"
        self.cb_launch.setVisible(mode not in ("uninstall", "manage_components"))


# ===== 可点击卡片按钮（Win11 风格：白底卡片 + 悬停高亮 + 左侧色条） =====
class _CardButton(QFrame):
    """维护页用的可点击卡片：标题(粗体) + 描述(灰)，整体可点击。

    danger=True 时用红色配色（用于"卸载"等危险操作）。
    """
    clicked = pyqtSignal()

    def __init__(self, title, desc, us, danger=False, parent=None):
        super().__init__(parent)
        self._us = us
        self._danger = danger
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self._accent = "#c62828" if danger else "#1a73e8"
        self._hover_bg = "#fdf2f2" if danger else "#f5f9ff"
        self._apply_style()

        layout = QHBoxLayout(self)
        m = max(int(14 * us), 11)
        layout.setContentsMargins(m, m, m, m)
        layout.setSpacing(max(int(12 * us), 9))

        # 左侧色条（4px 宽，强调主色）
        bar = QFrame()
        bar.setFixedWidth(max(int(4 * us), 3))
        bar.setStyleSheet(f"background: {self._accent}; border: none; border-radius: 2px;")
        layout.addWidget(bar, 0, Qt.AlignLeft)

        # 标题 + 描述纵向排列
        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(max(int(2 * us), 2))
        title_lbl = QLabel(title)
        tf = title_lbl.font()
        tf.setPointSize(max(int(9 * us), 9))  # 与 real_installer 卡片标题一致
        tf.setBold(True)
        title_lbl.setFont(tf)
        title_lbl.setStyleSheet(
            f"color: {self._accent if danger else '#1a1a1a'}; border: none; background: transparent;")
        text_box.addWidget(title_lbl)
        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        df = desc_lbl.font()
        df.setPointSize(max(int(7 * us), 7))  # 与 real_installer 卡片描述一致
        desc_lbl.setFont(df)
        desc_lbl.setStyleSheet("color: #666; border: none; background: transparent;")
        text_box.addWidget(desc_lbl)
        layout.addLayout(text_box, 1)

    def _apply_style(self):
        if self._hover:
            self.setStyleSheet(
                f"QFrame {{ background: {self._hover_bg}; "
                f"border: 1px solid {self._accent}; border-radius: 6px; }}")
        else:
            self.setStyleSheet(
                "QFrame { background: #fff; border: 1px solid #d0d0d0; border-radius: 6px; }")

    def enterEvent(self, e):
        self._hover = True
        self._apply_style()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._apply_style()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def sizeHint(self):
        sh = super().sizeHint()
        return QSize(sh.width(), max(sh.height(), max(int(60 * self._us), 50)))


# ===== 页面 7：维护模式 =====
class _MaintenancePage(_PageBase):
    repair_clicked = pyqtSignal()
    uninstall_clicked = pyqtSignal()
    manage_components_clicked = pyqtSignal()

    def __init__(self, us, install_state=None, parent=None):
        super().__init__(us, parent)
        self._install_state = install_state or {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(10 * us), 8))

        layout.addWidget(self._title("维护设置"))

        self._info_label = self._desc("正在加载安装信息...")
        layout.addWidget(self._info_label)

        layout.addSpacing(max(int(6 * us), 4))

        btn_manage = _CardButton("管理模型与训练组件",
                                 "勾选或取消模型架构与训练工具，下载缺失组件或卸载已装组件",
                                 us)
        btn_repair = _CardButton("文件修复",
                                 "检测并修复损坏或丢失的程序文件", us)
        btn_uninstall = _CardButton("卸载",
                                    "从计算机中移除我的世界旗帜逆向套件",
                                    us, danger=True)
        for btn, sig in ((btn_manage, self.manage_components_clicked),
                         (btn_repair, self.repair_clicked),
                         (btn_uninstall, self.uninstall_clicked)):
            btn.clicked.connect(sig)
            layout.addWidget(btn)

        layout.addStretch()
        layout.addWidget(self._hint("※ 演示模式：所有操作均为模拟，不会产生实际变更。"))

    def _refresh_info(self, state):
        """根据检测结果更新维护页信息。"""
        self._install_state = state or {}
        # 界面统一显示子版本号（内部 json 记 1.0.8 → 显示 v0.5 beta1 (1.0.8)）
        ver = (_UI_VERSION if state and state.get("version") else "未知版本")
        path = state.get("path", "未知路径") if state else "未知路径"
        comps = len(state.get("components", [])) if state else 0
        self._info_label.setText(
            f"检测到已安装：{ver}，{comps} 个组件\n"
            f"安装路径：{path}\n\n"
            "请选择要执行的操作：")


# ===== 页面 8：文件修复（演示模式：诊断→修复→完成） =====
class _RepairPage(_PageBase):
    """文件修复页面（演示模式）。

    流程：
      1. 进入页面时展示已诊断出的问题列表（来自模拟配置 _sim_problems）
      2. 点击「开始修复」启动模拟修复进度
      3. 修复完成后展示修复报告
    """
    repair_done = pyqtSignal()

    def __init__(self, us, sim_info=None, parent=None):
        super().__init__(us, parent)
        self._us = us
        self._repaired = False
        self._sim_info = sim_info or {}
        # 从模拟配置加载自定义问题（若无可选时回退默认）
        self._diagnoses = self._load_diagnoses()
        self._repair_steps = self._build_repair_steps()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(8 * us), 6))

        layout.addWidget(self._title("文件修复"))

        # 阶段1：诊断结果摘要
        lbl_stage = QLabel("阶段 1：诊断结果摘要")
        lbl_stage.setStyleSheet("font-weight: bold; color: #1a73e8;")
        layout.addWidget(lbl_stage)

        self.diag_text = QTextEdit()
        self.diag_text.setReadOnly(True)
        self.diag_text.setMinimumHeight(max(int(140 * us), 100))
        _diag_font_px = max(int(12 * us), 11)
        self.diag_text.setStyleSheet(
            f"QTextEdit {{ background: #fff; border: 1px solid #d0d0d0; border-radius: 6px; "
            f"padding: 8px; font-size: {_diag_font_px}px; }}")
        layout.addWidget(self.diag_text)
        self._fill_diagnosis()

        # 阶段2：修复进度
        lbl_fix = QLabel("阶段 2：修复进度")
        lbl_fix.setStyleSheet("font-weight: bold; color: #1a73e8;")
        layout.addWidget(lbl_fix)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(max(int(20 * us), 16))
        self.progress.setTextVisible(True)
        self.progress.setStyleSheet(
            "QProgressBar { background: #e8e8e8; border: none; border-radius: 4px; "
            "text-align: center; color: #333; }"
            "QProgressBar::chunk { background: #1a73e8; border-radius: 4px; }")
        layout.addWidget(self.progress)

        self.lbl_progress = QLabel("等待开始修复...")
        self.lbl_progress.setWordWrap(True)
        self.lbl_progress.setStyleSheet("color: #666;")
        layout.addWidget(self.lbl_progress)

        # 修复按钮（Win11 风格主按钮：蓝底白字、圆角）
        self.btn_repair = QPushButton("开始修复")
        self.btn_repair.setMinimumHeight(max(int(36 * us), 30))
        self.btn_repair.setCursor(Qt.PointingHandCursor)
        _btn_font_px = max(int(15 * us), 15)
        self.btn_repair.setStyleSheet(
            f"QPushButton {{ background: #1a73e8; color: white; border: 1px solid #1a73e8; "
            f"border-radius: 6px; padding: 6px 16px; font-size: {_btn_font_px}px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: #1557b0; border-color: #1557b0; }}"
            f"QPushButton:pressed {{ background: #0d47a1; border-color: #0d47a1; }}"
            f"QPushButton:disabled {{ background: #f0f0f0; color: #aaa; border-color: #e0e0e0; }}")
        self.btn_repair.clicked.connect(self._start_repair)
        layout.addWidget(self.btn_repair)
        # 无问题时禁用修复按钮
        if not self._diagnoses:
            self.btn_repair.setEnabled(False)
            self.btn_repair.setText("无需修复")

        # 阶段3：修复报告
        lbl_report = QLabel("阶段 3：修复报告")
        lbl_report.setStyleSheet("font-weight: bold; color: #1a73e8;")
        layout.addWidget(lbl_report)

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setMinimumHeight(max(int(140 * us), 100))
        _report_font_px = max(int(12 * us), 11)
        self.report_text.setStyleSheet(
            f"QTextEdit {{ background: #fff; border: 1px solid #d0d0d0; border-radius: 6px; "
            f"padding: 8px; font-size: {_report_font_px}px; }}")
        layout.addWidget(self.report_text)

        layout.addStretch()
        layout.addWidget(self._hint("※ 演示模式：诊断结果与修复过程均为模拟，不会产生实际文件变更。"))

        # 修复定时器（模拟修复进度，每 400ms 推进一步）
        self._repair_timer = QTimer(self)
        self._repair_timer.timeout.connect(self._tick_repair)
        self._repair_step = 0

    def _load_diagnoses(self):
        """从模拟配置加载诊断结果列表。

        返回 [(component, status, issue, action), ...]
        若无 _sim_problems，回退默认诊断。
        若 _sim_problems 为空列表（非维护模式），返回空列表。
        """
        problems = self._sim_info.get("_sim_problems") if self._sim_info else None
        # 若 sim_info 中无，尝试从配置文件读取
        if problems is None:
            try:
                import tempfile
                sim_path = os.path.join(tempfile.gettempdir(), "banner_sim_config.json")
                if os.path.exists(sim_path):
                    with open(sim_path, encoding="utf-8") as f:
                        cfg = json.load(f)
                    problems = cfg.get("_sim_problems")
            except Exception:
                problems = None
        if problems is None:
            # 回退默认诊断（与 visualcondition._SIM_PROBLEM_DEFS 默认项一致）
            return [
                ("bdor.pyw", "损坏", "文件哈希不匹配，可能被修改", "重新下载并替换"),
                ("models/vit_b_16.pth", "丢失", "预训练权重文件缺失", "用 torchvision 在线重新下载"),
                ("config/config.json", "损坏", "JSON 解析失败，配置项缺失", "重置为默认配置"),
                ("config/hardware_cache.json", "过期", "硬件缓存与实际硬件不匹配", "清除缓存并重新检测"),
                ("trainer.pyw", "损坏", "训练器主程序文件损坏", "重新下载并替换"),
                ("images/banner/", "丢失", "图标资源目录缺失", "从安装包恢复"),
                ("models/structures/vit_model.py", "损坏", "模型架构文件语法错误", "重新下载并替换"),
                (".mbtl 旗帜文件", "损坏", "旗帜数据格式版本不兼容", "迁移至最新格式"),
                (".mbtlx 标记文件", "损坏", "ZIP 解压失败，marks.json 不完整", "重新导出或修复标记文件"),
                ("训练过程", "运行错误", "显存或内存不足（OOM），训练中断", "降低批次大小并重试"),
                ("GPU 初始化", "运行错误", "CUDA/DirectML 初始化失败，无法加载计算后端", "更新显卡驱动或切换至 CPU 模式"),
                ("磁盘空间", "异常", "保存路径磁盘空间不足，无法写入模型", "清理磁盘空间或更换保存路径"),
                ("程序运行", "崩溃", "发生未知异常，程序意外退出", "查看错误日志并联系开发者"),
            ]
        # 从 dict 列表转为元组列表
        return [(p["component"], p["status"], p["issue"], p["action"]) for p in problems]

    def _build_repair_steps(self):
        """根据诊断结果动态生成修复步骤列表。

        返回 [(progress_pct, status_text), ...]
        """
        # 需修复的问题（排除"完整"状态）
        to_fix = [(c, a) for c, s, i, a in self._diagnoses
                  if s in ("损坏", "丢失", "过期", "运行错误", "异常", "崩溃")]
        n = len(to_fix)
        if n == 0:
            return [(100, "无需修复，所有组件完整")]
        steps = [(10, "正在备份原始文件...")]
        # 为每个问题分配进度区间（10~90）
        for i, (comp, action) in enumerate(to_fix):
            pct = 10 + int((i + 1) / n * 75)
            steps.append((pct, f"正在处理 {comp}（{action}）..."))
        steps.append((95, "正在校验文件哈希..."))
        steps.append((100, "修复完成"))
        return steps

    def _fill_diagnosis(self):
        """填充诊断结果摘要表。"""
        if not self._diagnoses:
            self.diag_text.setHtml(
                "<p style='color:#2e7d32; font-weight:bold; text-align:center;'>"
                "✓ 诊断完成，未发现任何问题，所有组件完整。</p>")
            return
        html = ["<table style='border-collapse: collapse;' cellspacing='6'>",
                "<tr style='background:#e8eef7; font-weight:bold;'>"
                "<td>组件</td><td>状态</td><td>问题</td><td>修复动作</td></tr>"]
        for comp, status, issue, action in self._diagnoses:
            color = "#c62828" if status in ("损坏", "丢失", "过期", "运行错误", "异常", "崩溃") else "#2e7d32"
            html.append(
                f"<tr><td>{comp}</td>"
                f"<td style='color:{color}; font-weight:bold;'>{status}</td>"
                f"<td>{issue}</td><td>{action}</td></tr>")
        html.append("</table>")
        self.diag_text.setHtml("\n".join(html))

    def _start_repair(self):
        """启动模拟修复进度。"""
        if self._repaired:
            return
        self.btn_repair.setEnabled(False)
        self.btn_repair.setText("修复中...")
        self._repair_step = 0
        self.progress.setValue(0)
        self._repair_timer.start(400)

    def _tick_repair(self):
        """模拟修复进度推进。"""
        if self._repair_step >= len(self._repair_steps):
            self._repair_timer.stop()
            return
        pct, msg = self._repair_steps[self._repair_step]
        self.progress.setValue(pct)
        self.lbl_progress.setText(msg)
        self._repair_step += 1
        if pct >= 100:
            self._repair_timer.stop()
            self._on_repair_done()

    def _on_repair_done(self):
        """修复完成，填充报告。"""
        self._repaired = True
        self.btn_repair.setText("修复已完成")
        self.lbl_progress.setText("✓ 全部问题已修复")
        self.lbl_progress.setStyleSheet("color: #2e7d32; font-weight: bold;")
        html = ["<table style='border-collapse: collapse;' cellspacing='6'>",
                "<tr style='background:#e8f5e9; font-weight:bold;'>"
                "<td>组件</td><td>修复结果</td><td>说明</td></tr>"]
        for comp, status, issue, action in self._diagnoses:
            if status in ("损坏", "丢失", "过期", "运行错误", "异常", "崩溃"):
                result, note = "已修复", f"{action}完成"
            else:
                result, note = "无需修复", "组件完整"
            color = "#2e7d32" if result in ("已修复", "无需修复") else "#c62828"
            html.append(
                f"<tr><td>{comp}</td>"
                f"<td style='color:{color}; font-weight:bold;'>{result}</td>"
                f"<td>{note}</td></tr>")
        html.append("</table>")
        html.append("<p style='color:#666; margin-top:8px;'>建议重启程序以应用所有修复。</p>")
        self.report_text.setHtml("\n".join(html))
        self.repair_done.emit()


# ===== 主窗口 =====
class InstallerDemo(QDialog):
    PG_INIT, PG_WELCOME, PG_LICENSE, PG_PURPOSE, PG_FEATURES, PG_MODEL, \
        PG_PATH, PG_PROGRESS, PG_COMPLETE, PG_MAINT, PG_REPAIR = range(11)

    def __init__(self, parent=None, sim_info=None):
        # Qt 官方标准 Window flag（移除消极的 MSWindowsFixedSizeDialogHint）
        super().__init__(parent, Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setWindowTitle("我的世界旗帜逆向套件 v0.5 beta1 Setup 【演示模式 - 模拟安装】")

        app = QApplication.instance() or QApplication(sys.argv)
        # 统一弹窗图标：QMessageBox 系统弹窗图标 56px（250% 放大规律，与 _show_43_dialog 等自定义弹窗一致）
        from PyQt5.QtWidgets import QProxyStyle, QStyle as _QStyle
        class _MsgBoxIconStyle(QProxyStyle):
            def pixelMetric(self, metric, option=None, widget=None):
                if metric == _QStyle.PM_MessageBoxIconSize:
                    return 56
                return super().pixelMetric(metric, option, widget)
        app.setStyle(_MsgBoxIconStyle(app.style()))
        win_scale, us = _ui_scales(app)
        self._us = us
        self._win_scale = win_scale

        self._mode = "install"
        self._purpose = "use"
        self._hw_info = None
        self._install_state = None
        self._sim_info = sim_info
        self._selected_archs = []
        self._install_path = None
        self._cancelled = False

        # 真·根源：预先精确计算子区域（Banner / Stack / Bottom）的几何，
        # 并分别给它们 setFixedSize + Fixed sizePolicy，
        # 这样 QStackedWidget 不会按各子页 sizeHint 最大值扩张 dialog。
        self._fixed_w = int(640 * win_scale)
        self._fixed_h = int(480 * win_scale)
        self._banner_w = max(int(180 * win_scale), 150)
        # 同步 real_installer V6-2：底部栏 52→64，按钮更大
        self._bottom_h = max(int(64 * win_scale), 56)
        self._stack_w = self._fixed_w - self._banner_w
        self._stack_h = self._fixed_h - self._bottom_h

        self._build_ui(us, win_scale)
        # Qt 官方单一 API：内部同时绑定 min/max/geometry。不再额外 setMin / setMax / setSizeGrip
        self.setFixedSize(self._fixed_w, self._fixed_h)

    def showEvent(self, event):
        super().showEvent(event)

    def _build_ui(self, us, win_scale):
        # 字号与 real_installer 完全一致：不再用全局 px 字号/字体族覆盖，
        # 继承 app 默认字体（Segoe UI 9pt），页面文字由 _PageBase 的 10/8/7(pt) 体系控制
        self.setStyleSheet(
            f"QScrollBar:vertical {{ width: {max(int(14*us),12)}px; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.setSizeConstraint(QLayout.SetNoConstraint)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        banner = _BannerWidget(win_scale)
        banner.setFixedSize(self._banner_w, self._stack_h)
        banner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        body.addWidget(banner, 0)

        self.stack = QStackedWidget()
        self.stack.setFixedSize(self._stack_w, self._stack_h)
        self.stack.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.page_init = _InitPage(us)
        self.page_welcome = _WelcomePage(us)
        self.page_license = _LicensePage(us)
        self.page_purpose = _PurposePage(us)
        self.page_features = _FeaturesPage(us)
        self.page_model = _ModelArchPage(us)
        self.page_path = _InstallPathPage(us)
        self.page_progress = _ProgressPage(us)
        self.page_complete = _CompletePage(us)
        self.page_maint = _MaintenancePage(us)
        self.page_repair = _RepairPage(us, sim_info=self._sim_info)
        for p in (self.page_init, self.page_welcome, self.page_license,
                  self.page_purpose, self.page_features, self.page_model,
                  self.page_path, self.page_progress, self.page_complete,
                  self.page_maint, self.page_repair):
            # 同步 V7：每页包 _FixedScrollArea，内容超出自动滚 → 字不再被截
            sa = _FixedScrollArea(us)
            sa.setWidgetResizable(True)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sa.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            sa.setFixedSize(self._stack_w, self._stack_h)
            sa.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            sa.setWidget(p)
            p.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            p.setMinimumSize(0, 0)
            p.setMaximumSize(16777215, 16777215)
            self.stack.addWidget(sa)

        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        bottom = QFrame()
        bottom.setFixedSize(self._fixed_w, self._bottom_h)
        bottom.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        bl = QHBoxLayout(bottom)
        # 同步 V6-4：由几何反推，保证按钮永远居中且不溢出
        _pad_lr = max(int(20 * us), 18)
        _pad_top = max(int(8 * us), 6)
        _pad_bottom = max(int(10 * us), 8)
        bl.setContentsMargins(_pad_lr, _pad_top, _pad_lr, _pad_bottom)
        bl.setSpacing(max(int(12 * us), 10))

        # 按钮高度 = bottom_h - 上 - 下 - 2px，宽度 clamp 到 1/3 栏宽以内
        _pad_x = max(int(36 * us), 32)
        _btn_h = max(self._bottom_h - _pad_top - _pad_bottom - max(int(2 * us), 2),
                     max(int(_btn_px * 2.2), 36))
        _max_btn_w = max(
            (self._fixed_w - 2 * _pad_lr - 2 * max(int(12 * us), 10)) // 3,
            100)
        def _btn_width(text, min_w):
            return max(min(_fm.horizontalAdvance(text) + _pad_x, _max_btn_w), min_w)

        self.btn_back = QPushButton("< 上一步")
        self.btn_back.clicked.connect(self._go_back)
        self.btn_back.setFont(_btn_font)
        self.btn_back.setMinimumHeight(_btn_h)
        self.btn_back.setMinimumWidth(_btn_width("< 上一步", 110))

        self.btn_next = QPushButton("下一步 >")
        self.btn_next.setDefault(True)
        self.btn_next.clicked.connect(self._go_next)
        self.btn_next.setFont(_btn_font)
        self.btn_next.setMinimumHeight(_btn_h)
        self.btn_next.setMinimumWidth(_btn_width("下一步 >", 116))

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self._confirm_cancel)
        self.btn_cancel.setFont(_btn_font)
        self.btn_cancel.setMinimumHeight(_btn_h)
        self.btn_cancel.setMinimumWidth(_btn_width("取消", 100))

        bl.addWidget(self.btn_back)
        bl.addStretch(1)
        bl.addWidget(self.btn_next)
        bl.addWidget(self.btn_cancel)
        root.addWidget(bottom, 0)

        # 信号
        self.page_welcome.maintenance_clicked.connect(self._goto_maintenance)
        self.page_license.rb_accept.toggled.connect(lambda _: self._update_buttons())
        self.page_path.space_checked.connect(self._update_buttons)
        self.page_maint.repair_clicked.connect(self._maint_repair)
        self.page_repair.repair_done.connect(self._on_repair_done)
        self.page_maint.uninstall_clicked.connect(self._maint_uninstall)
        self.page_maint.manage_components_clicked.connect(self._maint_manage_components)

        # 启动初始化
        self.stack.setCurrentIndex(self.PG_INIT)
        self._update_buttons()
        if self._sim_info and not self._sim_info.get("_use_real_hardware"):
            # 模拟设备模式：已由 visualcondition.pyw 提供模拟配置，跳过真实检测
            self.page_init._on_done(self._sim_info)
            self._on_init_done(self._sim_info)
        else:
            # 本机模式或 _use_real_hardware：执行真实硬件检测
            # （sim_info 中的 _sim_problems 仍会传给 _RepairPage）
            QTimer.singleShot(300, self._start_init)

    # ---------- 初始化 ----------
    def _start_init(self):
        self.page_init.start()
        self.page_init._thread.finished_all.connect(self._on_init_done)

    def _on_init_done(self, info):
        self._hw_info = info
        self._install_state = info.get("install_state", {})
        # 环境拦截：检查是否支持安装（不弹窗，直接在初始化页显示）
        block_msg = self._check_env_blocked(info)
        if block_msg:
            self._env_blocked = True
            self.page_init.set_blocked(block_msg)
        else:
            self._env_blocked = False
        # 填充欢迎页摘要（未安装时从 Next 进入即可看到）
        if not self._install_state.get("installed"):
            self.page_welcome.set_hw_info(info)
        self._update_buttons()

    def _check_env_blocked(self, info):
        """检查环境是否支持安装，返回阻塞消息或 None。"""
        if not info:
            return None
        # 已安装则不拦截（维护模式）
        if info.get("install_state", {}).get("installed"):
            return None
        # 检查模拟环境的 allow 标记
        allow = info.get("sim_allow", "") or info.get("_sim_allow", "")
        if allow == "不支持":
            os_name = info.get("os", "未知")
            gpu_name = info.get("gpu", {}).get("name", "未知") if isinstance(info.get("gpu"), dict) else "未知"
            return f"当前环境不支持安装：\n\n系统：{os_name}\nGPU：{gpu_name}\n\n请升级到 Windows 10 1909+ 并配备 RTX 20 系及以上显卡。"
        # 系统类型检查：非 Windows 系统直接拦截（Linux/macOS/Unix）
        os_type = info.get("os_type", "")
        if os_type and os_type != "windows":
            os_name = info.get("os", "未知")
            return f"当前系统不支持安装：\n\n系统：{os_name}\n类型：{os_type.upper()}\n\n本软件仅支持 Windows 10 1909 及以上版本。\nLinux/macOS 用户可通过 WSL2 或虚拟机运行 Windows 环境。"
        # 真实设备检测：检查 OS 和 GPU
        os_name = info.get("os", "")
        gpu = info.get("gpu", {})
        if isinstance(gpu, dict):
            gpu_name = gpu.get("name", "")
        else:
            gpu_name = str(gpu)
        # OS 检查：不支持 Windows 7/8/8.1 及非 Windows 系统
        if allow == "本机" or not allow:
            os_lower = os_name.lower()
            if "windows 7" in os_lower or "windows 8" in os_lower or "macos" in os_lower or "linux" in os_lower or "ubuntu" in os_lower:
                return f"当前系统 {os_name} 不支持安装。\n\n需要 Windows 10 1909 及以上版本。"
            # GPU 检查：至少需要 RTX 20 系或 Iris Xe 或 Vega 7
            gpu_lower = gpu_name.lower()
            if gpu_name and gpu_name != "未知":
                has_nvidia_rtx = any(k in gpu_lower for k in ("rtx 20", "rtx 30", "rtx 40", "rtx 50", "rtx a", "a100", "a6000"))
                has_intel_ok = any(k in gpu_lower for k in ("iris xe", "iris plus", "uhd 770", "uhd 730", "arc"))
                has_amd_ok = any(k in gpu_lower for k in ("vega 7", "vega 8", "vega 10", "vega 11", "radeon 6", "radeon 7", "radeon rx", "rdna", "780m", "880m"))
                if not (has_nvidia_rtx or has_intel_ok or has_amd_ok):
                    return f"显卡 {gpu_name} 不满足最低要求。\n\n需要 RTX 20 系及以上、Intel Iris Xe/Arc 或 AMD Vega 7+。"
        return None

    # ---------- 导航 ----------
    def _update_buttons(self):
        pg = self.stack.currentIndex()
        show_back, show_next = True, True
        back_on, next_on = True, True
        next_text = "下一步 >"

        if pg == self.PG_INIT:
            show_back = False
            next_on = self._hw_info is not None and not getattr(self, '_env_blocked', False)
            if self._install_state and self._install_state.get("installed"):
                next_text = "进入维护模式 >"
            else:
                next_text = "下一步 >"
        elif pg == self.PG_WELCOME:
            # 欢迎页：可 Back 返回初始化重新检测，Next 进入使用声明
            back_on, next_on = True, True
            next_text = "下一步 >"
        elif pg == self.PG_LICENSE:
            next_on = self.page_license.is_accepted()
        elif pg == self.PG_PURPOSE:
            pass
        elif pg == self.PG_FEATURES:
            # 管理组件：库页点「应用」才真正执行安装/卸载；其它流程保持「下一步」
            next_text = "应用" if self._mode == "manage_components" else "下一步 >"
            # 架构选择必选至少 1 个
            err = self.page_features.validate_archs()
            next_on = (err is None)
        elif pg == self.PG_MODEL:
            # 管理组件：模型页只做勾选，点「下一步」进入库页（「应用」在库页）
            next_text = "下一步 >"
        elif pg == self.PG_PATH:
            next_text = "安装"
            next_on = self.page_path.is_space_enough()
        elif pg == self.PG_PROGRESS:
            back_on, next_on = False, False
        elif pg == self.PG_COMPLETE:
            show_back = False
            next_text = "关闭"
        elif pg == self.PG_MAINT:
            show_back, show_next = False, False
        elif pg == self.PG_REPAIR:
            show_next = False
            self.btn_cancel.setText("取消")

        self.btn_back.setVisible(show_back)
        self.btn_back.setEnabled(back_on)
        self.btn_next.setVisible(show_next)
        self.btn_next.setEnabled(next_on)
        self.btn_next.setText(next_text)
        self.btn_cancel.setEnabled(pg not in (self.PG_COMPLETE,))

    def _go_next(self):
        pg = self.stack.currentIndex()
        if pg == self.PG_INIT:
            if self._install_state and self._install_state.get("installed"):
                self.page_maint._refresh_info(self._install_state)
                self._goto(self.PG_MAINT)
            else:
                self.page_welcome.set_hw_info(self._hw_info)
                self._goto(self.PG_WELCOME)
        elif pg == self.PG_WELCOME:
            # 欢迎页 Next → 使用声明
            self._mode = "install"
            self._goto(self.PG_LICENSE)
        elif pg == self.PG_LICENSE:
            self._goto(self.PG_PURPOSE)
        elif pg == self.PG_PURPOSE:
            self._purpose = self.page_purpose.purpose()
            if self._purpose == "train":
                # 训练模式：先选模型架构，再选库（库依赖模型架构）
                self._rebuild_model_page()
                self._goto(self.PG_MODEL)
            else:
                # 使用模式：识别器不需要选模型，直接进入库选择
                self._rebuild_features(self._purpose, "install")
                self._goto(self.PG_FEATURES)
        elif pg == self.PG_FEATURES:
            if self._mode == "manage_components":
                # 管理组件：库选完后直接启动进度（跳过路径选择，使用已有安装路径）
                self._start_progress("manage_components")
            else:
                # 首次安装：库选择完成 → 进入路径选择页
                _archs = self.page_features.get_selected_archs() if hasattr(self, 'page_features') else ["cuda"]
                self.page_path.populate(self._hw_info, self._install_state, _archs)
                self._goto(self.PG_PATH)
        elif pg == self.PG_MODEL:
            if self._mode == "manage_components":
                # 管理组件：模型选完后进入库选择（像首次安装一样）
                self._selected_archs = self.page_model.get_selected()
                self._rebuild_features(self._purpose, "install", self._selected_archs)
                self._goto(self.PG_FEATURES)
            else:
                self._selected_archs = self.page_model.get_selected()
                # 模型架构已选，重建库选择页（依据架构调整可选项）
                _mode = "install"
                self._rebuild_features(self._purpose, _mode, self._selected_archs)
                self._goto(self.PG_FEATURES)
        elif pg == self.PG_PATH:
            self._install_path = self.page_path.get_install_path()
            self._start_progress(self._mode)
        elif pg == self.PG_COMPLETE:
            self.accept()

    def _go_back(self):
        pg = self.stack.currentIndex()
        if pg == self.PG_WELCOME:
            # 欢迎页 Back → 重新初始化检测
            self._goto(self.PG_INIT)
            self._hw_info = None
            self._update_buttons()
            QTimer.singleShot(200, self._start_init)
        elif pg == self.PG_LICENSE:
            self._goto(self.PG_WELCOME)
        elif pg == self.PG_PURPOSE:
            self._goto(self.PG_LICENSE)
        elif pg == self.PG_FEATURES:
            # 库选择 ← 管理组件回模型架构；训练模式回模型架构；使用模式回使用目的
            if self._mode == "manage_components":
                self._goto(self.PG_MODEL)
            elif self._purpose == "train":
                self._goto(self.PG_MODEL)
            else:
                self._goto(self.PG_PURPOSE)
        elif pg == self.PG_MODEL:
            # 模型架构 ← 维护模式回维护页；安装模式回使用目的
            if self._mode == "manage_components":
                self._goto(self.PG_MAINT)
            else:
                self._goto(self.PG_PURPOSE)
        elif pg == self.PG_PATH:
            self._goto(self.PG_FEATURES)
        elif pg == self.PG_REPAIR:
            self._goto(self.PG_MAINT)

    def _goto(self, idx):
        self.stack.setCurrentIndex(idx)
        self._update_buttons()

    # ---------- 欢迎页动作 ----------
    def _goto_maintenance(self):
        # 演示入口：直接进入维护页
        self.page_maint._refresh_info(self._install_state)
        self._goto(self.PG_MAINT)

    # ---------- 维护模式动作 ----------
    def _maint_repair(self):
        """修复流程：先运行 test.pyw 诊断，诊断完成后进入修复页面。"""
        inst_path = self._install_state.get("path") or self._install_path or ""

        # 1. 定位 test.pyw（优先安装目录，回退到开发目录）
        test_path = os.path.join(inst_path, "test.pyw") if inst_path else ""
        if not os.path.exists(test_path):
            dev_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            test_path = os.path.join(dev_root, "test.pyw")
        if not os.path.exists(test_path):
            meipass = getattr(sys, '_MEIPASS', None)
            if meipass:
                test_path = os.path.join(meipass, "test.pyw")
        if not os.path.exists(test_path):
            self._enter_repair_page()
            return

        # 2. 查找 pythonw.exe
        import shutil as _shutil
        pythonw = _shutil.which("pythonw")
        if not pythonw:
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
                                    exe_path, _ = winreg.QueryValueEx(ik, "ExecutablePath")
                                    winreg.CloseKey(ik)
                                except OSError:
                                    continue
                                if exe_path:
                                    pw = os.path.join(os.path.dirname(exe_path), "pythonw.exe")
                                    if os.path.exists(pw):
                                        pythonw = pw
                                        break
                            except OSError:
                                break
                        winreg.CloseKey(core)
                    except OSError:
                        pass
                    if pythonw:
                        break
            except Exception:
                pass

        if not pythonw:
            self._enter_repair_page()
            return

        # 3. 显示提示对话框（非阻塞）
        self._test_msg = QMessageBox(self)
        self._test_msg.setWindowTitle("诊断测试")
        self._test_msg.setIcon(QMessageBox.Information)
        self._test_msg.setText(
            "正在运行诊断测试程序。\n\n"
            "请在测试程序中执行测试（可点击「全部运行」），\n"
            "测试完成后关闭测试程序，将自动进入修复模式。")
        self._test_msg.setStandardButtons(QMessageBox.NoButton)
        self._test_msg.show()

        # 4. 用 QProcess 启动 test.pyw，完成后自动进入修复页面
        self._test_proc = QProcess(self)
        if inst_path and os.path.isdir(inst_path):
            self._test_proc.setWorkingDirectory(inst_path)
        self._test_proc.finished.connect(
            lambda *_: self._on_test_finished())
        self._test_proc.start(pythonw, [test_path])

    def _on_test_finished(self):
        """test.pyw 诊断完成后，关闭提示并进入修复页面。"""
        if hasattr(self, '_test_msg'):
            self._test_msg.close()
        self._enter_repair_page()

    def _enter_repair_page(self):
        """进入修复页面。"""
        self._goto(self.PG_REPAIR)

    def _on_repair_done(self):
        """修复完成：底部按钮从「取消」变为「确认」。"""
        self.btn_cancel.setText("确认")

    def _confirm_cancel(self):
        """取消/确认按钮：根据当前页面智能处理。"""
        pg = self.stack.currentIndex()
        # 修复页修复后点「确认」回维护页
        if pg == self.PG_REPAIR and self.btn_cancel.text() == "确认":
            self.btn_cancel.setText("取消")
            self._goto(self.PG_MAINT)
            return
        # 修复页未修复时点「取消」回维护页
        if pg == self.PG_REPAIR:
            self._goto(self.PG_MAINT)
            return
        # 管理组件（模型选择页）点「取消」回维护页
        if pg == self.PG_MODEL and self._mode == "manage_components":
            self._goto(self.PG_MAINT)
            return
        # 管理组件（库选择页）点「取消」回维护页
        if pg == self.PG_FEATURES and self._mode == "manage_components":
            self._goto(self.PG_MAINT)
            return
        # 安装进行中取消：停止模拟线程后关闭
        if pg == self.PG_PROGRESS:
            if not _ask_yes_no(self, "取消安装", "确定要取消安装吗？"):
                return
            self._cancelled = True
            self.btn_cancel.setEnabled(False)
            self.page_progress.status_label.setText("正在取消...")
            if self.page_progress._thread:
                self.page_progress._thread.cancel()
            return
        # 维护模式页面：直接退出，不显示"取消安装"
        if pg == self.PG_MAINT:
            self.reject()
            return
        # 其他页面：确认退出
        if _ask_yes_no(self, "退出", "确定要退出安装向导吗？"):
            self.reject()

    def _maint_uninstall(self):
        if _ask_yes_no(
                self, "卸载",
                f"确定要从计算机中移除我的世界旗帜逆向套件吗？\n"
                f"安装路径：{self._install_state.get('path', '默认路径')}\n"
                f"（演示模式：无实际操作）"):
            self._mode = "uninstall"
            self._start_progress("uninstall")

    def _maint_manage_components(self):
        """管理组件：进入模型架构与训练工具管理页面，勾选=安装，取消勾选=卸载。"""
        self._mode = "manage_components"
        self._install_path = self._install_state.get("path") or ""
        # 读取已安装配置
        cfg_path = os.path.join(self._install_path, _COMPONENTS_FILE) if self._install_path else ""
        if cfg_path and os.path.exists(cfg_path):
            try:
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f) or {}
                self._purpose = cfg.get("purpose", "train")
            except Exception:
                self._purpose = "train"
        else:
            self._purpose = "train"
        self._rebuild_model_page(maintenance=True)
        # 回显已安装的模型勾选状态
        installed_models = self._install_state.get("models", []) or []
        if hasattr(self.page_model, "_arch_checks"):
            for k, cb in self.page_model._arch_checks.items():
                if k != "_trainer":
                    cb.setChecked(False)
            for m in installed_models:
                if m in self.page_model._arch_checks:
                    self.page_model._arch_checks[m].setChecked(True)
            if hasattr(self.page_model, "_update_total"):
                self.page_model._update_total()
        self._goto(self.PG_MODEL)

    # ---------- 工具 ----------
    def _rebuild_features(self, purpose, mode, selected_archs=None):
        self.stack.removeWidget(self.page_features)
        self.page_features.deleteLater()
        self.page_features = _FeaturesPage(self._us, self._hw_info, purpose, mode,
                                          selected_archs=selected_archs)
        # 架构选择变更时刷新下一步按钮（验证至少选1个）
        self.page_features.arch_changed.connect(self._update_buttons)
        self.stack.insertWidget(self.PG_FEATURES, self.page_features)

    def _rebuild_model_page(self, maintenance=False):
        """重建模型架构页（使用最新硬件信息）。"""
        self.stack.removeWidget(self.page_model)
        self.page_model.deleteLater()
        self.page_model = _ModelArchPage(self._us, self._hw_info, maintenance=maintenance)
        self.stack.insertWidget(self.PG_MODEL, self.page_model)

    def _start_progress(self, mode):
        self._mode = mode
        if mode == "manage_components":
            # 管理组件：archs 来自库选择页，models 来自模型架构页
            archs = self.page_features.get_selected_archs() if hasattr(self, 'page_features') else []
            models = self.page_model.get_selected() if hasattr(self, 'page_model') else []
        else:
            archs = self.page_features.get_selected_archs() if hasattr(self, 'page_features') else ["cuda"]
            models = getattr(self, "_selected_archs", None)
        self.page_progress.set_archs(archs)
        self._goto(self.PG_PROGRESS)
        purpose = getattr(self, "_purpose", "train")
        self.page_progress.start(mode, models=models, purpose=purpose)
        self.page_progress._thread.finished_ok.connect(self._on_progress_done)
        self.page_progress._thread.cancelled.connect(self._on_progress_cancelled)

    def _on_progress_cancelled(self):
        """模拟安装被用户取消后关闭对话框。"""
        self.reject()

    def _on_progress_done(self):
        # Demo 安装：写入开发环境配置文件，模拟选择性安装效果
        if self._mode == "install":
            purpose = getattr(self, "_purpose", "train")
            dev_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cfg_dir = os.path.join(dev_root, "config")
            os.makedirs(cfg_dir, exist_ok=True)
            cfg_file = os.path.join(cfg_dir, "dev_install_config.json")
            try:
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "purpose": purpose,
                        "mode": "demo",
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }, f, ensure_ascii=False, indent=2)
            except Exception:
                pass  # 写入失败不阻断 Demo 流程
        self.page_complete.set_result(self._mode)
        self._goto(self.PG_COMPLETE)

    def closeEvent(self, event):
        """关闭按钮（X）与取消按钮行为一致。

        安装进行中（PG_PROGRESS）弹出取消确认；其余页面（含安装完成 PG_COMPLETE）
        均允许关闭，等价于点击取消按钮。
        """
        pg = self.stack.currentIndex()
        if pg == self.PG_PROGRESS:
            if _ask_yes_no(self, "取消安装", "确定要取消安装吗？"):
                self._cancelled = True
                if self.page_progress._thread:
                    self.page_progress._thread.cancel()
                event.accept()
            else:
                event.ignore()
            return
        # 安装完成页与其他页面：允许直接关闭（等价于取消）
        event.accept()


def _run_visualcondition(app, win_scale, us):
    """在同一进程中显示环境模拟对话框，返回 (cancelled, sim_info)。

    cancelled=True 表示用户关闭窗口取消。
    cancelled=False 时 sim_info 始终为 dict：
      - 模拟设备模式：含完整硬件信息 + _sim_problems
      - 本机模式：含 _use_real_hardware=True + _sim_problems（执行真实检测）
    """
    import importlib.util
    vc_path = os.path.join(_PROJECT_ROOT, "installer", "visualcondition.pyw")
    if not os.path.exists(vc_path):
        return False, None
    spec = importlib.util.spec_from_file_location("visualcondition", vc_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dlg = mod.VisualConditionDialog(win_scale, us)
    dlg.exec_()
    cancelled = not dlg._applied
    sim_info = dlg.get_sim_info()
    # 清理：确保前一个对话框完全销毁，避免残留窗口状态影响后续 InstallerDemo 的布局
    dlg.deleteLater()
    app.processEvents()
    if cancelled:
        return True, None
    if sim_info and not sim_info.get("python"):
        sim_info["python"] = _w32_get_python()
    return False, sim_info


def main():
    # 软件渲染（必须在 QApplication 创建前设置）：保证 agent 截图稳定可识别
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 9))
    # 统一弹窗图标：QMessageBox 系统弹窗图标 56px（250% 放大规律，与 _show_43_dialog 等自定义弹窗一致）
    from PyQt5.QtWidgets import QProxyStyle, QStyle as _QStyle
    class _MsgBoxIconStyle(QProxyStyle):
        def pixelMetric(self, metric, option=None, widget=None):
            if metric == _QStyle.PM_MessageBoxIconSize:
                return 56
            return super().pixelMetric(metric, option, widget)
    app.setStyle(_MsgBoxIconStyle(app.style()))
    win_scale, us = _ui_scales(app)

    # --repair 参数：从测试程序进入修复界面（跳过环境模拟，直接到修复页）
    if "--repair" in sys.argv:
        # 读取模拟配置（若存在）
        sim_info = None
        try:
            import tempfile
            sim_path = os.path.join(tempfile.gettempdir(), "banner_sim_config.json")
            if os.path.exists(sim_path):
                with open(sim_path, encoding="utf-8") as f:
                    sim_info = json.load(f)
        except Exception:
            sim_info = None
        dlg = InstallerDemo(sim_info=sim_info)
        # 直接跳到维护页 → 修复页
        dlg._goto_maintenance()
        dlg._maint_repair()
        dlg.exec_()
        sys.exit(0)

    # 先显示环境模拟对话框（同一进程，避免 subprocess 问题）
    cancelled, sim_info = _run_visualcondition(app, win_scale, us)
    if cancelled:
        # 用户关闭窗口 = 取消，退出程序
        sys.exit(0)
    dlg = InstallerDemo(sim_info=sim_info)
    dlg.exec_()
    sys.exit(0)


if __name__ == "__main__":
    main()
