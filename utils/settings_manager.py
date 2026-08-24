import json
import os
import sys
import ctypes
import tempfile
from copy import deepcopy

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QDialog


class SettingsManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._callbacks = {}
        self._settings = self._default_settings()
        self._load()
        # 首次启动（磁盘尚无 config.json）时，按 install_components.json 的已安装
        # 架构推断默认 train_arch，避免默认 "cuda" 与实际安装（DirectML/CPU）不符，
        # 导致训练器/识别器一启动就报"CUDA 模式但无显卡/无 CUDA torch"。
        if not os.path.exists(self._config_file()):
            _arch = self._infer_installed_arch()
            if _arch:
                self._settings["train_arch"] = _arch

    @staticmethod
    def _infer_installed_arch():
        """按 install_components.json 的 archs 推断训练架构；读不到返回 None。"""
        try:
            comp = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "install_components.json")
            if not os.path.isfile(comp):
                return None
            with open(comp, encoding="utf-8-sig") as f:
                data = json.load(f) or {}
            archs = data.get("archs") or []
            for a in ("directml", "cuda", "cpu"):
                if a in archs:
                    return a
        except Exception:
            pass
        return None

    def _default_settings(self):
        return {
            # 通用
            "theme": "light",
            "auto_layout": True,
            "minimize_others": True,
            "restore_layout": True,
            # 吸附
            "snap_enabled": True,
            "snap_threshold": 10,
            "snap_grid": True,
            # 系统/日志
            "log_level": "info",
            "log_system": True,
            "log_operation": False,
            "log_data": True,
            "log_performance": False,
            "log_path": "default",
            "auto_save_interval": 10,
            # 训练环境
            "train_mode": "normal",
            "train_arch": "cuda",
            "debug_mode": False,
            "model_arch": "vit_b_16",
            "dropout": 0.2,
            "lora_rank": 8,
            "gpu_memory": "auto",
            "sys_memory": "auto",
            "mixed_precision": "fp16",
            "auto_resource_alloc": True,
            "perf_level": "balanced",
            "compute_backend": "auto",        # auto / discrete / integrated / cpu
            "dml_device_index": 0,            # DirectML 挂载卡选择索引
            "gpu_temp_protection": 80,
            "grad_accum": 1,
            "num_workers": "auto",
            "log_training": True,
            "log_model": True,
            "log_error": True,
            # 训练器设置
            "save_format": "pth",   # 旧版单值，仅用于兼容迁移
            # 导入器设置
            "import_min_size_kb": 200,
            "import_max_size_mb": 5,
            "auto_preview_import": True,
            # 保存格式（按模块分配：训练器定时保存仅 .mbtl/.mbtlx，.pth 由训练完成时自动保存）
            "trainer_auto_save_formats": ["mbtl", "mbtlx"],
            "trainer_save_formats": ["pth", "mbtl", "mbtlx"],
            "importer_auto_save_formats": ["mbtl", "mbtlx"],
            "importer_save_formats": ["mbtl", "mbtlx"],
            # 保存路径（相对程序根目录）
            "auto_save_trainer_path": "saves/auto_save/trainer",
            "auto_save_loader_path": "saves/auto_save/loader",
            "manual_save_trainer_path": "saves/manual_save/trainer",
            "manual_save_loader_path": "saves/manual_save/loader",
        }

    def _config_file(self):
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_dir = os.path.join(app_dir, "config")
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "config.json")

    @property
    def config_path(self):
        return self._config_file()

    def _legacy_config_files(self):
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_dir = os.path.join(app_dir, "config")
        return [
            # 旧的根目录配置文件
            os.path.join(app_dir, "config.json"),
            os.path.join(app_dir, "config_trainer.json"),
            os.path.join(app_dir, "config_importer.json"),
            # config/ 目录下的旧分拆文件
            os.path.join(config_dir, "config_trainer.json"),
            os.path.join(config_dir, "config_importer.json"),
        ]

    def _load(self):
        path = self._config_file()

        # 迁移旧配置
        if not os.path.exists(path):
            merged = {}
            for legacy_path in self._legacy_config_files():
                if os.path.exists(legacy_path):
                    try:
                        with open(legacy_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if isinstance(data, dict):
                            merged.update(data)
                    except Exception:
                        pass
            if merged:
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(merged, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                defaults = self._default_settings()
                for k, v in defaults.items():
                    if k in data:
                        self._settings[k] = data[k]
                # 迁移旧版统一保存格式（save_formats / auto_save_formats）到分模块配置
                old_unified_mfmts = data.get("save_formats")
                old_unified_afmts = data.get("auto_save_formats")
                if old_unified_mfmts and isinstance(old_unified_mfmts, list):
                    # 统一格式拆分到训练器（含pth）和导入器（仅mbtl/mbtlx）
                    self._settings["trainer_save_formats"] = list(old_unified_mfmts)
                    self._settings["importer_save_formats"] = [
                        f for f in old_unified_mfmts if f in ("mbtl", "mbtlx")
                    ] or ["mbtl", "mbtlx"]
                if old_unified_afmts and isinstance(old_unified_afmts, list):
                    # 训练器定时自动保存不含.pth（.pth 由训练完成时自动保存）
                    self._settings["trainer_auto_save_formats"] = [
                        f for f in old_unified_afmts if f in ("mbtl", "mbtlx")
                    ] or ["mbtl", "mbtlx"]
                    self._settings["importer_auto_save_formats"] = [
                        f for f in old_unified_afmts if f in ("mbtl", "mbtlx")
                    ] or ["mbtl", "mbtlx"]
            except Exception:
                pass

    def save(self):
        path = self._config_file()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def reload(self):
        """强制重新从磁盘读取配置文件（用于跨进程同步）。"""
        self._settings = self._default_settings()
        self._load()

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def set(self, key, value):
        old = self._settings.get(key)
        self._settings[key] = value
        if old != value and key in self._callbacks:
            for cb in self._callbacks[key]:
                try:
                    cb(value)
                except Exception:
                    pass

    def get_all(self):
        return deepcopy(self._settings)

    def set_all(self, data):
        for k, v in data.items():
            self.set(k, v)

    def on_change(self, key, callback):
        if key not in self._callbacks:
            self._callbacks[key] = []
        self._callbacks[key].append(callback)


def resolve_app_path(relative_path):
    """将相对路径解析为相对于程序根目录的绝对路径。

    传入 "default" 或空值时返回程序根目录。
    传入绝对路径时原样返回。

    打包后（PyInstaller）：可写数据目录 = exe 所在目录，
    只读资源目录 = sys._MEIPASS（临时解压目录）。
    log/config 等可写路径用 exe 目录，images 等只读路径用 _MEIPASS。
    """
    if getattr(sys, 'frozen', False):
        # 打包模式：exe 所在目录（可写数据优先）
        app_dir = os.path.dirname(sys.executable)
    else:
        # 开发模式：utils/ 的上级目录
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not relative_path or relative_path == "default":
        return app_dir
    if os.path.isabs(relative_path):
        return relative_path
    p = os.path.join(app_dir, relative_path)
    # 打包后（onefile/onedir）：只读资源（images 等）实际在 _MEIPASS，
    # exe 目录没有时回退到 _MEIPASS，避免图标等资源路径失效
    if not os.path.exists(p) and getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            pm = os.path.join(meipass, relative_path)
            if os.path.exists(pm):
                return pm
    return p


# 模块级硬件检测缓存，避免多次 import torch/psutil
_HARDWARE_CACHE = {}


def _get_physical_memory_gb():
    """返回 (标称内存GB, 系统识别总内存GB, 系统提交限制GB)。

    标称内存 = 出厂规格（GetPhysicallyInstalledSystemMemory），如 64GB
    系统识别总内存 = OS 可见总量（GlobalMemoryStatusEx.ullTotalPhys），如 63.1GB
    """
    if sys.platform == "win32":
        try:
            installed_kb = ctypes.c_ulonglong()
            installed_gb = None
            try:
                if ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(installed_kb)):
                    installed_gb = int(round(installed_kb.value / (1024 ** 2)))
            except Exception:
                pass

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            recognized_gb = round(mem.ullTotalPhys / (1024 ** 3), 1)
            virt_total_gb = int(round(mem.ullTotalPageFile / (1024 ** 3)))
            if installed_gb is None:
                installed_gb = int(round(recognized_gb))
            return installed_gb, recognized_gb, virt_total_gb
        except Exception:
            pass
    try:
        import psutil
        total = psutil.virtual_memory().total / (1024 ** 3)
        return int(round(total)), round(total, 1), int(round(total))
    except Exception:
        return 8, 8.0, 8


def _get_cpu_name():
    """通过 PowerShell CIM 获取 CPU 型号名称，无需第三方库。

    优先 Get-CimInstance Win32_Processor（Win8+），回退 wmic（旧系统）。
    """
    if sys.platform == "win32":
        # 方式1: PowerShell Get-CimInstance（推荐，wmic 在 Win11 已弃用）
        try:
            import subprocess
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().splitlines()[0].strip()
        except Exception:
            pass
        # 方式2: wmic 回退（旧系统）
        try:
            import subprocess
            r = subprocess.run(
                ["wmic", "cpu", "get", "name"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            lines = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
            if len(lines) >= 2:
                return lines[1]
        except Exception:
            pass
    return "未知CPU"


# SMBIOS Memory Type 字段映射（参考 DMTF DSP0134 规范）
_SMBIOS_MEM_TYPE_MAP = {
    18: "DDR", 19: "DDR2", 20: "DDR2 FB-DIMM",
    24: "DDR3", 26: "DDR4",
    27: "LPDDR", 28: "LPDDR2", 29: "LPDDR3",
    30: "LPDDR4", 31: "LPDDR4X",
    34: "DDR5", 35: "LPDDR5", 36: "LPDDR5X",
}


def _guess_ram_type_by_cpu(cpu_name, ram_gb):
    """根据 CPU 型号推测内存代际类型（WMI 无法读取时的回退）。"""
    cl = (cpu_name or "").lower()
    # Intel Core Ultra HX 系列使用 DDR5 SO-DIMM
    if "core ultra" in cl and "hx" in cl:
        return "DDR5"
    if "ryzen ai" in cl or "core ultra" in cl or "ryzen 9 89" in cl or "ryzen 7 88" in cl:
        return "LPDDR5X" if ram_gb >= 32 else "LPDDR5"
    if "ryzen ai 9" in cl or "ryzen 7 7840" in cl or "ryzen 7 8840" in cl:
        return "LPDDR5"
    if any(k in cl for k in ("i9-14", "i9-13", "i7-14", "i7-13", "i5-14", "i5-13",
                             "ryzen 7 780", "ryzen 9 79", "ryzen 5 76")):
        return "DDR5"
    if any(k in cl for k in ("i3-81", "i5-82", "i3-71", "i5-42", "i3-32", "i5-10")):
        return "DDR4"
    if ram_gb >= 32:
        return "DDR5"
    return "DDR4"


def _get_memory_info(cpu_name=""):
    """获取内存类型信息，返回 (mem_type_str, total_gb)。

    优先通过 WMI 读取 Win32_PhysicalMemory 的 SMBIOSMemoryType；
    失败时根据 CPU 型号推测。
    """
    if sys.platform == "win32":
        try:
            import subprocess
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_PhysicalMemory | "
                 "Select-Object SMBIOSMemoryType, Capacity | ConvertTo-Json"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if r.returncode == 0 and r.stdout.strip():
                import json
                data = json.loads(r.stdout.strip())
                if isinstance(data, dict):
                    data = [data]
                if isinstance(data, list) and data:
                    total_bytes = 0
                    mem_types = set()
                    for stick in data:
                        if not isinstance(stick, dict):
                            continue
                        cap = stick.get("Capacity")
                        if cap:
                            try:
                                total_bytes += int(cap)
                            except (ValueError, TypeError):
                                pass
                        smbios_type = stick.get("SMBIOSMemoryType")
                        if smbios_type and smbios_type in _SMBIOS_MEM_TYPE_MAP:
                            mem_types.add(_SMBIOS_MEM_TYPE_MAP[smbios_type])
                    total_gb = round(total_bytes / (1024 ** 3), 1) if total_bytes > 0 else 0
                    if len(mem_types) == 1:
                        return next(iter(mem_types)), total_gb
                    if len(mem_types) > 1:
                        return "/".join(sorted(mem_types)), total_gb
        except Exception:
            pass
    return "未知", 0


def detect_hardware(skip_gpu=False):
    """检测 GPU 型号/显存、CPU 型号/核心数、内存信息，失败时返回安全默认值。

    返回字段:
      gpu_name, gpu_total_gb       — GPU 型号与显存
      cpu_name, cpu_cores          — CPU 型号与逻辑核心数
      mem_nominal_gb               — 出厂标称内存（如 64）
      mem_recognized_gb            — 系统识别总内存（如 63.1）
      mem_available_gb             — 缓存时刻的可用内存（后续用 psutil 实时读）
      virtual_total_gb             — 页面文件限制

    Args:
        skip_gpu: 为 True 时跳过 import torch 的 GPU 检测，用于导入器快速启动。
    """
    global _HARDWARE_CACHE
    nominal_gb, recognized_gb, virt_gb = _get_physical_memory_gb()
    info = {
        "gpu_name": "未检测到",
        "gpu_total_gb": 0,
        "gpu_type": "none",              # nvidia / amd / intel / none
        "gpu_vendor": "",                # GPU 厂商
        "is_integrated_gpu": False,      # 是否为核显
        "compute_backend": "cpu",        # cuda / directml / cpu
        "cpu_name": "未知CPU",
        "cpu_cores": 4,
        "mem_nominal_gb": nominal_gb,
        "mem_recognized_gb": recognized_gb,
        "mem_total_gb": nominal_gb,        # 兼容旧字段
        "mem_available_gb": recognized_gb,  # 兼容旧字段（系统识别总量）
        "mem_type": "未知",                  # 内存类型（DDR4/DDR5/LPDDR5 等）
        "virtual_total_gb": virt_gb,
        "os_version": "",                  # 操作系统版本
        "os_build": 0,                     # 操作系统 build 号
    }
    # 操作系统版本
    try:
        os_ver, os_build = get_windows_version()
        info["os_version"] = os_ver
        info["os_build"] = os_build
    except Exception:
        pass
    # CPU 型号
    info["cpu_name"] = _get_cpu_name()
    # CPU 核心数
    try:
        import multiprocessing
        info["cpu_cores"] = multiprocessing.cpu_count()
    except Exception:
        pass
    # 内存类型：优先 WMI 读取 SMBIOSMemoryType，失败时按 CPU 型号推测
    try:
        mem_type, _wmi_total = _get_memory_info(info["cpu_name"])
        if mem_type == "未知" or not mem_type:
            mem_type = _guess_ram_type_by_cpu(info["cpu_name"], nominal_gb)
        info["mem_type"] = mem_type
    except Exception:
        info["mem_type"] = _guess_ram_type_by_cpu(info["cpu_name"], nominal_gb)
    # 实时可用内存
    try:
        import psutil
        info["mem_available_gb"] = round(psutil.virtual_memory().available / (1024 ** 3), 1)
    except Exception:
        pass
    if not skip_gpu:
        # 优先用 torch 检测；若 torch 因 DLL 冲突（如 PyQt5 先导入）加载失败，回退到 nvidia-smi
        gpu_found = False
        try:
            import torch
            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                info["gpu_name"] = props.name
                info["gpu_total_gb"] = int(round(props.total_memory / (1024 ** 3)))
                gpu_found = True
        except Exception:
            pass
        if not gpu_found:
            # 回退：通过 nvidia-smi 命令行检测 NVIDIA GPU
            try:
                import subprocess
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if r.returncode == 0 and r.stdout.strip():
                    line = r.stdout.strip().split("\n")[0]
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 2:
                        info["gpu_name"] = parts[0]
                        info["gpu_total_gb"] = max(1, round(int(parts[1]) / 1024))
                        gpu_found = True
            except Exception:
                pass
        # CUDA 不可用时，检测 AMD/Intel 核显
        if not gpu_found:
            try:
                from utils.device_backend import detect_gpu_type, is_directml_available, get_compute_backend
                gpu_info = detect_gpu_type()
                if gpu_info["vendor"] != "none":
                    info["gpu_name"] = gpu_info["name"]
                    info["gpu_vendor"] = gpu_info["vendor"]
                    info["gpu_type"] = gpu_info["vendor"]
                    info["is_integrated_gpu"] = gpu_info["is_integrated"]
                    if gpu_info["vram_gb"] > 0:
                        info["gpu_total_gb"] = gpu_info["vram_gb"]
                    gpu_found = True
            except Exception:
                pass
        # 确定计算后端
        try:
            from utils.device_backend import get_compute_backend
            info["compute_backend"] = get_compute_backend()
        except Exception:
            pass
    _HARDWARE_CACHE = info
    return info


def get_hardware_cache():
    """返回缓存的硬件信息；缓存为空时尝试从磁盘加载，不执行同步检测。"""
    if not _HARDWARE_CACHE:
        load_hardware_cache()
    return _HARDWARE_CACHE or {}


def get_gpu_memory_usage():
    """获取 GPU 显存实时使用情况（GB），返回 (total, free, usage_pct)。

    通过 nvidia-smi 查询，失败时返回 (0, 0, 0)。
    """
    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = [p.strip() for p in r.stdout.strip().split(",")]
            if len(parts) >= 2:
                total = round(int(parts[0]) / 1024, 1)
                free = round(int(parts[1]) / 1024, 1)
                pct = int((total - free) / total * 100) if total > 0 else 0
                return total, free, pct
    except Exception:
        pass
    return 0, 0, 0


# Windows 版本 build 号映射表（按 build 号升序）
_WIN_BUILD_MAP = [
    (7600, "Windows 7"),
    (7601, "Windows 7 SP1"),
    (9200, "Windows 8"),
    (9600, "Windows 8.1"),
    (10240, "Windows 10 1507"),
    (10586, "Windows 10 1511"),
    (14393, "Windows 10 1607"),
    (15063, "Windows 10 1703"),
    (16299, "Windows 10 1709"),
    (17134, "Windows 10 1803"),
    (17763, "Windows 10 1809"),
    (18362, "Windows 10 1903"),
    (18363, "Windows 10 1909"),
    (19041, "Windows 10 2004"),
    (19042, "Windows 10 20H2"),
    (19043, "Windows 10 21H1"),
    (19044, "Windows 10 21H2"),
    (19045, "Windows 10 22H2"),
    (22000, "Windows 11 21H2"),
    (22621, "Windows 11 22H2"),
    (22631, "Windows 11 23H2"),
    (26100, "Windows 11 24H2"),
    (26200, "Windows 11 25H2"),
]


def get_windows_version():
    """获取详细的 Windows 版本信息，如 'Windows 11 25H2 (Build 26200)'。

    兼容 Windows 7~Windows 11 最新版本。
    返回 (version_string, build_number) 元组，非 Windows 返回 (platform.platform(), 0)。
    """
    if sys.platform != "win32":
        import platform
        return (platform.platform(), 0)
    try:
        build = sys.getwindowsversion().build
        # 查找 build 号对应的版本名（取 <= 当前 build 的最大条目）
        name = f"Windows (Build {build})"
        for b, n in _WIN_BUILD_MAP:
            if build >= b:
                name = n
            else:
                break
        return (f"{name} (Build {build})", build)
    except Exception:
        import platform
        return (platform.platform(), 0)


def report_error(title, message, source="程序", scale=None):
    """集中错误处理：写入临时文件并调用 error_reporter.pyw 弹窗。

    Args:
        title: 错误标题
        message: 错误详情（含 traceback），为空时自动获取当前 traceback
        source: 错误来源标识（如 '训练器'/'导入器'）
        scale: 可选，调用方主窗口的 UI _scale 值；若未传，则尝试从
               QApplication.topLevelWidgets 中找具备 _scale 属性的主窗口继承。
               传入 error_reporter 后跳过自动公式，保证错误窗口与主窗口视觉比例完全一致。
    """
    import traceback as _tb
    err_file = os.path.join(tempfile.gettempdir(), f"banner_tool_error_{source}_{os.getpid()}.txt")
    try:
        if message and message.strip():
            full_msg = message
        else:
            tb = _tb.format_exc()
            # format_exc() 在无异常时返回 "NoneType: None\n"，需要识别
            if tb.strip() and tb.strip() != "NoneType: None":
                full_msg = tb
            else:
                full_msg = f"[{source}] {title}\n（无详细错误信息）"
        with open(err_file, "w", encoding="utf-8") as f:
            f.write(full_msg)
    except Exception:
        pass
    reporter_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "error_reporter.pyw"
    )
    # 传入安装目录的 log/ 路径：error_reporter.pyw 作为独立子进程运行时，
    # __file__ 指向 _MEIPASS 临时目录，无法自行解析安装目录的 log/
    log_dir = resolve_app_path("log")

    # 自动推断主窗口 scale（若未显式传入）：
    # 在 UI 线程里 report_error 调用时通常存在 QApplication 实例，
    # 遍历 topLevelWidgets 找第一个带 _scale 属性的主窗口（trainer/importer/bdor/...）。
    if scale is None or not isinstance(scale, (int, float)) or scale <= 0:
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                for w in app.topLevelWidgets():
                    s = getattr(w, "_scale", None)
                    if s is not None and isinstance(s, (int, float)) and 0.3 < s < 10:
                        scale = float(s)
                        break
        except Exception:
            scale = None

    try:
        import subprocess
        cmd = [sys.executable, reporter_path, err_file, title, source, log_dir]
        if scale is not None and 0.3 < float(scale) < 10:
            cmd += ["--scale", f"{float(scale):.4f}"]
        subprocess.Popen(
            cmd,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        )
    except Exception:
        pass


def _hardware_cache_file():
    """硬件缓存文件路径（config/ 目录下）。"""
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_dir = os.path.join(app_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "hardware_cache.json")


def save_hardware_cache(hw_info):
    """将硬件检测结果保存到磁盘，避免下次启动重复检测。"""
    try:
        with open(_hardware_cache_file(), "w", encoding="utf-8") as f:
            json.dump(hw_info, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_hardware_cache():
    """从磁盘读取硬件缓存；不存在或字段缺失时返回 None 以触发重新检测。"""
    global _HARDWARE_CACHE
    path = _hardware_cache_file()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            info = json.load(f)
        # 必须包含所有必需字段，否则视为陈旧缓存
        required = {"cpu_cores", "cpu_name", "mem_nominal_gb", "mem_recognized_gb", "compute_backend"}
        if isinstance(info, dict) and required.issubset(info.keys()):
            _HARDWARE_CACHE = info
            return info
    except Exception:
        pass
    return None


def grade_gpu_memory(total_gb):
    """根据消费级显存容量返回推荐的 GPU 限制（GB），保留足够系统余量。"""
    if total_gb <= 0:
        return 2
    if total_gb <= 4:
        return 2
    if total_gb <= 6:
        return 4
    if total_gb <= 8:
        return 4
    if total_gb <= 12:
        return 8
    if total_gb <= 16:
        return 12
    if total_gb <= 24:
        return 16
    return 32


def grade_integrated_gpu_memory(sys_total_gb):
    """核显共享内存推荐分配（取系统内存的 25%~40%）。

    核显无独立显存，与 CPU 共享系统 RAM，需保留更多给 OS。
    """
    if sys_total_gb <= 8:
        return 2
    if sys_total_gb <= 16:
        return 4
    if sys_total_gb <= 32:
        return 8
    return 12


def grade_system_memory(total_gb):
    """根据消费级内存容量返回推荐的系统内存上限（GB），约占总内存 50%。"""
    if total_gb <= 4:
        return 4
    if total_gb <= 8:
        return 4
    if total_gb <= 16:
        return 8
    if total_gb <= 32:
        return 16
    if total_gb <= 64:
        return 32
    return 64


def compute_resource_allocation(gpu_total_gb, sys_total_gb,
                                model_arch="vit_b_16", mixed_precision=True,
                                level="balanced", is_integrated=False):
    """根据设备总显存、总内存和实时 CPU/内存使用率计算训练资源分配。

    原则：
      独显 — 保留 OS/桌面合成器比例 + 5%碎片安全余量，
             剩余给 PyTorch 缓存分配器，比例限制在 50%~85%。
      核显 — 共享系统 RAM，从可用内存中按比例划分，
             batch_size 更保守，保留更多给 OS。
      内存 — 基于实时可用内存（psutil），按每 worker ≈0.5GB 估算上限。
      CPU  — 实时读取 CPU 使用率，高负载时减少 workers 数量。
      batch_size — 可用显存减去模型基础占用后，按每样本估算（保守值）。

    Args:
        gpu_total_gb: GPU 总显存（GB），0 表示无 GPU。核显时为分配的共享内存。
        sys_total_gb: 系统标称总内存（GB），用作上限参考。
        model_arch: 模型架构键名。
        mixed_precision: 是否使用混合精度（影响每样本显存估算）。
        level: 性能挡位 — "light"(轻量), "balanced"(均衡), "extreme"(极致)。
        is_integrated: 是否为核显（共享系统内存）。

    Returns:
        dict: gpu_fraction, batch_size, num_workers,
              gpu_reserved_gb, usable_gpu_gb, usable_sys_gb,
              cpu_usage_pct, mem_usage_pct
    """
    import multiprocessing

    # 挡位参数
    if level == "light":
        gpu_reserve_ratio = 0.20
        sys_reserve_ratio = 0.60
        max_workers = 4
    elif level == "extreme":
        gpu_reserve_ratio = 0.10
        sys_reserve_ratio = 0.40
        max_workers = 8
    else:  # balanced
        gpu_reserve_ratio = 0.15
        sys_reserve_ratio = 0.50
        max_workers = 8

    # === 实时读取 CPU 和内存使用率 ===
    cpu_usage_pct = 0
    mem_usage_pct = 0
    mem_recognized_gb = sys_total_gb
    mem_avail_now = sys_total_gb * (1 - sys_reserve_ratio)
    try:
        import psutil
        vm = psutil.virtual_memory()
        mem_recognized_gb = round(vm.total / (1024 ** 3), 1)
        mem_avail_now = round(vm.available / (1024 ** 3), 1)
        mem_usage_pct = int(vm.percent)
        # psutil.cpu_percent(interval=None) 首次调用返回 0.0，需要短间隔
        cpu_usage_pct = int(psutil.cpu_percent(interval=0.1))
    except Exception:
        pass

    # === 显存分配 ===
    if is_integrated:
        # 核显：共享系统 RAM，不使用 gpu_fraction（DirectML 不支持 set_per_process_memory_fraction）
        # 从可用内存中按比例划分给 GPU 使用
        igpu_ratio = 0.35 if level == "balanced" else (0.25 if level == "light" else 0.45)
        usable_gpu_gb = max(0.5, mem_avail_now * igpu_ratio) if mem_avail_now > 0 else max(0.5, sys_total_gb * igpu_ratio)
        gpu_reserved_gb = 0.0  # 核显无独立保留概念
        gpu_fraction = 0.0     # DirectML 不支持此 API
    elif gpu_total_gb <= 0:
        gpu_fraction = 0.0
        gpu_reserved_gb = 0.0
        usable_gpu_gb = 0.0
    else:
        # 独显：OS/桌面合成器/浏览器等保留
        gpu_reserved_gb = max(0.5, min(gpu_total_gb * gpu_reserve_ratio, 2.0))
        # 碎片安全余量
        safety_gb = gpu_total_gb * 0.05
        usable_gpu_gb = gpu_total_gb - gpu_reserved_gb - safety_gb
        gpu_fraction = max(0.5, min(usable_gpu_gb / gpu_total_gb, 0.85))

    # === batch_size 推荐 ===
    # 各架构参数量与显存估算（fp16 参数+梯度+AdamW 状态）:
    #   vit_b_16:  86M  → 基础 ~0.8GB, 每样本 ~0.15GB(fp16)/0.25GB(fp32)
    #   vit_l_16:  304M → 基础 ~1.6GB, 每样本 ~0.25GB(fp16)/0.40GB(fp32)
    #   vit_b_32:  88M  → 基础 ~0.8GB, 每样本 ~0.10GB(fp16)/0.18GB(fp32)（patch 更大，激活更少）
    #   vit_l_32:  306M → 基础 ~1.6GB, 每样本 ~0.18GB(fp16)/0.30GB(fp32)
    #   deit_b_16: 86M  → 同 vit_b_16（DeiT-Base 与 ViT-B 参数量相当）
    #   deit_s_16: 22M  → 基础 ~0.3GB, 每样本 ~0.06GB(fp16)/0.10GB(fp32)
    #   deit_t_16: 5M   → 基础 ~0.15GB, 每样本 ~0.03GB(fp16)/0.05GB(fp32)
    _ARCH_MEM = {
        "vit_b_16":  (0.8,  0.15, 0.25),
        "vit_l_16":  (1.6,  0.25, 0.40),
        "vit_b_32":  (0.8,  0.10, 0.18),
        "vit_l_32":  (1.6,  0.18, 0.30),
        "vit_h_14":  (2.5,  0.35, 0.55),
        "deit_b_16": (0.8,  0.15, 0.25),
        "deit_s_16": (0.3,  0.06, 0.10),
        "deit_t_16": (0.15, 0.03, 0.05),
    }
    if model_arch in _ARCH_MEM:
        model_base_gb, per_fp16, per_fp32 = _ARCH_MEM[model_arch]
        per_sample_gb = per_fp16 if mixed_precision else per_fp32
    else:
        model_base_gb = 0.8
        per_sample_gb = 0.15 if mixed_precision else 0.25

    if usable_gpu_gb > model_base_gb:
        batch_size = max(1, min(int((usable_gpu_gb - model_base_gb) / per_sample_gb), 32))
    else:
        batch_size = 1

    # 核显：带宽远低于独显，batch_size 上限更保守
    if is_integrated:
        batch_size = min(batch_size, 8 if level != "light" else 4)

    # === num_workers 推荐（同时考虑内存和CPU） ===
    cpu_cores = multiprocessing.cpu_count()
    if mem_recognized_gb <= 0:
        num_workers = max(1, cpu_cores - 1)
        usable_sys_gb = 0.0
    else:
        # 基于实时可用内存，再扣除挡位保留比例对应的余量
        usable_sys_gb = min(mem_avail_now, mem_recognized_gb * (1 - sys_reserve_ratio))
        max_by_mem = max(1, int(usable_sys_gb / 0.5))
        # CPU 可用核心：总核心减去当前已被占用的等效核心数
        # 例如 8核 CPU 当前占用 50% → 已用 4 核 → 可用 4 核 → workers 最多 3
        busy_cores = cpu_cores * cpu_usage_pct / 100.0
        avail_cores = max(1, cpu_cores - int(round(busy_cores)) - 1)
        max_by_cpu = max(1, min(avail_cores, cpu_cores - 1))
        num_workers = min(max_by_mem, max_by_cpu, max_workers)

    return {
        "gpu_fraction": gpu_fraction,
        "gpu_reserved_gb": gpu_reserved_gb,
        "usable_gpu_gb": usable_gpu_gb,
        "usable_sys_gb": usable_sys_gb,
        "batch_size": batch_size,
        "num_workers": num_workers,
        "cpu_usage_pct": cpu_usage_pct,
        "mem_usage_pct": mem_usage_pct,
    }


# === 模型架构可用性检测 ===

# 架构列表（与 models/structures/vit_model.py 的 _ARCH_CONFIG 对应）
MODEL_ARCHS = [
    "vit_b_16", "vit_l_16", "vit_b_32", "vit_l_32", "vit_h_14",
    "deit_b_16", "deit_s_16", "deit_t_16",
]

# 架构显示名
ARCH_DISPLAY = {
    "vit_b_16":  "ViT-B/16",
    "vit_l_16":  "ViT-L/16",
    "vit_b_32":  "ViT-B/32",
    "vit_l_32":  "ViT-L/32",
    "vit_h_14":  "ViT-H/14",
    "deit_b_16": "DeiT-B/16（轻量化）",
    "deit_s_16": "DeiT-S/16（轻量化）",
    "deit_t_16": "DeiT-T/16（轻量化）",
}

# 所有架构键列表
ALL_ARCH_KEYS = list(ARCH_DISPLAY.keys())


def _arch_cache_path():
    """返回架构可用性缓存文件路径。"""
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(app_dir, "config", "arch_cache.json")


def _check_arch_raw(arch):
    """实际检测模型架构是否可用（不读缓存）。

    检查 models/structures/ 和 torch 缓存目录，避免 import torchvision（DLL冲突下极慢）。
    """
    import os as _os
    import glob as _glob

    # 安装目录的 models/structures/ 路径
    _structures_dir = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "models", "structures"
    )
    # torch hub 缓存目录（ViT 通过 torchvision 下载时缓存）
    _cache_dir = _os.path.expanduser("~/.cache/torch/hub/checkpoints")

    # DeiT 模型：检查 models/structures/ 下的独立 .pth（不复用 ViT 权重）
    if arch in ("deit_b_16", "deit_s_16", "deit_t_16"):
        _deit_pth = _os.path.join(_structures_dir, f"{arch}.pth")
        if _os.path.isfile(_deit_pth) and _os.path.getsize(_deit_pth) > 1024:
            return True, "预训练权重已下载"
        # 权重文件不存在
        return False, "权重未下载"

    # ViT 模型：检查 models/structures/ 和 torch 缓存
    patterns = {
        "vit_b_16": "*vit_b_16*.pth",
        "vit_l_16": "*vit_l_16*.pth",
        "vit_b_32": "*vit_b_32*.pth",
        "vit_l_32": "*vit_l_32*.pth",
        "vit_h_14": "*vit_h_14*.pth",
    }
    pat = patterns.get(arch)
    if not pat:
        return False, "未知架构"
    # 1. 检查 models/structures/{arch}.pth
    _local_pth = _os.path.join(_structures_dir, f"{arch}.pth")
    if _os.path.isfile(_local_pth) and _os.path.getsize(_local_pth) > 1024:
        return True, "权重已下载"
    # 2. 检查 torch hub 缓存
    if _glob.glob(_os.path.join(_cache_dir, pat)):
        return True, "权重已缓存"
    return False, "权重未下载"


def build_arch_cache():
    """检测所有架构可用性并写入缓存文件，返回缓存 dict。

    供训练器/导入器启动时调用，设置窗口直接读缓存以提高速度。
    """
    cache = {}
    for arch in ALL_ARCH_KEYS:
        available, reason = _check_arch_raw(arch)
        cache[arch] = {"available": available, "reason": reason}
    try:
        path = _arch_cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return cache


def load_arch_cache():
    """读取架构可用性缓存文件，返回 dict（无缓存时返回空 dict）。"""
    path = _arch_cache_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def check_arch_available(arch):
    """检测模型架构是否可用（优先读缓存，无缓存则实际检测并写入缓存）。

    Returns:
        (available: bool, reason: str)
    """
    # 优先读缓存
    cache = load_arch_cache()
    if arch in cache:
        entry = cache[arch]
        return bool(entry.get("available", False)), entry.get("reason", "")
    # 无缓存：实际检测并补写缓存
    available, reason = _check_arch_raw(arch)
    try:
        # 读取已有缓存并合并（避免覆盖其他架构的记录）
        existing = load_arch_cache()
        existing[arch] = {"available": available, "reason": reason}
        path = _arch_cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return available, reason


def load_and_apply_auto_hardware_config():
    """启动时检测硬件；若配置为 auto，则写入推荐值并返回检测结果与更新项。"""
    hw = detect_hardware()
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
    return {"hw": hw, "updates": updates}


class HardwareDetectThread(QThread):
    """后台线程执行硬件检测，避免 import 重型模块阻塞 GUI 启动。"""
    result_ready = pyqtSignal(dict)

    def __init__(self, skip_gpu=False, parent=None):
        super().__init__(parent)
        self.skip_gpu = skip_gpu

    def run(self):
        self.result_ready.emit(detect_hardware(skip_gpu=self.skip_gpu))


def _install_dwm_titlebar_filter(app, is_dark):
    """对应用内所有顶层对话框（含原生 QMessageBox）强制标题栏深色/浅色。

    SetPreferredAppMode 在部分系统不可靠，这里用事件过滤器在窗口 Show 时
    逐个调用 DWM 深色，保证任何弹窗（QMessageBox/QDialog）标题栏都跟随主题。
    """
    from PyQt5.QtCore import QObject, QEvent
    from PyQt5.QtWidgets import QDialog, QMainWindow
    flt = getattr(app, "_dwm_titlebar_filter", None)
    if flt is None:
        class _DwmFilter(QObject):
            dark = False

            def eventFilter(self, obj, event):
                if (self.dark and event.type() == QEvent.Show and obj is not None
                        and isinstance(obj, (QDialog, QMainWindow)) and obj.isWindow()):
                    try:
                        apply_dwm_dark_mode(obj, True)
                    except Exception:
                        pass
                return False

        flt = _DwmFilter(app)
        app._dwm_titlebar_filter = flt
        app.installEventFilter(flt)
    flt.dark = is_dark


def _set_native_titlebar_dark(is_dark):
    """让本进程的原生对话框（QMessageBox/文件选择器等）标题栏跟随深浅色。

    深色模式调用 uxtheme.SetPreferredAppMode(1)，浅色模式恢复(0)。
    仅 Windows 10 1903+ 有效，失败静默（不影响主窗口，主窗口走 DWM）。
    """
    if sys.platform != "win32":
        return
    try:
        uxtheme = ctypes.windll.uxtheme
        try:
            uxtheme.SetPreferredAppMode(1 if is_dark else 0)
        except Exception:
            # 旧版 Windows 10：通过 uxtheme 导出序号 135（深色）/ 138（浅色）调用
            handle = ctypes.windll.kernel32.GetModuleHandleW("uxtheme.dll")
            if handle:
                proc = ctypes.windll.kernel32.GetProcAddress(handle, 135 if is_dark else 138)
                if proc:
                    func_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int)
                    func = func_type(proc)
                    func(1 if is_dark else 0)
    except Exception:
        pass


def apply_theme(app, theme_name):
    """根据主题名称设置应用调色板；返回实际应用的主题名（light/dark）。"""
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QPalette, QColor
    from PyQt5.QtCore import Qt

    if theme_name == "dark":
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(45, 45, 48))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(30, 30, 30))
        palette.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(45, 45, 48))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Highlight, QColor(26, 115, 232))
        palette.setColor(QPalette.HighlightedText, Qt.white)
        # Disabled 组：深色模式用"幽灵化"策略——背景与正常一致，文字极暗
        palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(74, 74, 74))
        palette.setColor(QPalette.Disabled, QPalette.Text, QColor(74, 74, 74))
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(74, 74, 74))
        palette.setColor(QPalette.Disabled, QPalette.Base, QColor(60, 60, 60))
        palette.setColor(QPalette.Disabled, QPalette.Button, QColor(45, 45, 48))
        palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor(60, 60, 65))
        app.setPalette(palette)
        app.setStyle("Fusion")
        _set_native_titlebar_dark(True)
        _install_dwm_titlebar_filter(app, True)
        return "dark"

    if theme_name == "system":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return apply_theme(app, "dark" if value == 0 else "light")
        except Exception:
            return apply_theme(app, "light")

    # light 或未知值：恢复默认浅色调色板
    app.setPalette(QApplication.style().standardPalette())
    _set_native_titlebar_dark(False)
    _install_dwm_titlebar_filter(app, False)
    return "light"


def resolve_theme(theme):
    """将 'system' 解析为实际的 light/dark。"""
    if theme == "system":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "dark" if value == 0 else "light"
        except Exception:
            return "light"
    return theme


def apply_dwm_dark_mode(window, is_dark):
    """设置 Windows 窗口标题栏为深色/浅色模式（DWM API）。

    适用于主窗口、加载条窗口、设置窗口等所有顶层窗口。
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1 if is_dark else 0)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def show_about_dialog(parent, title, text):
    """显示关于对话框（自定义紧凑窗口，非 QMessageBox）。

    训练器/导入器/识别器的「关于」统一走此函数。用自定义 QDialog + 自定义
    QPushButton，规避 QMessageBox 标准按钮对 QSS 边框/背景渲染不稳定的问题；
    窗口紧凑自适应内容（与原 QMessageBox 尺寸相近），线框蓝按钮 + 深浅色 + 随父窗口缩放。
    """
    from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                 QPushButton, QStyle, QApplication)
    from PyQt5.QtCore import Qt
    _s = getattr(parent, "_scale", 1.0) if parent is not None else 1.0
    try:
        _theme = SettingsManager().get("theme", "light")
    except Exception:
        _theme = "light"
    is_dark = _theme == "dark"

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)

    bg = "#2d2d30" if is_dark else "#f5f5f5"
    fg = "#eeeeee" if is_dark else "#1a1a1a"
    bbrd, bhov = "#0078D4", ("#1e3a5f" if is_dark else "#e8f1fb")
    dlg.setStyleSheet(f"""
        QDialog {{ background-color: {bg}; }}
        QLabel {{ border: none; }}
        QPushButton {{ font-size: {max(int(15 * _s), 12)}px;
                       padding: {max(int(5 * _s), 4)}px {max(int(18 * _s), 14)}px;
                       min-height: {max(int(26 * _s), 22)}px;
                       border: 1px solid {bbrd}; border-radius: 6px;
                       background: transparent; color: {bbrd}; }}
        QPushButton:hover {{ background: {bhov}; }}
    """)

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(int(18 * _s), int(14 * _s), int(18 * _s), int(12 * _s))
    layout.setSpacing(int(8 * _s))

    # 标题行：图标 + 标题
    header = QHBoxLayout()
    header.setSpacing(int(10 * _s))
    icon_lbl = QLabel()
    _app = QApplication.instance()
    _style = _app.style() if _app else None
    if _style:
        _pm = _style.standardIcon(QStyle.SP_MessageBoxInformation).pixmap(80, 80)  # 系统图标上限 80×80
        icon_lbl.setPixmap(_pm)
    icon_lbl.setFixedSize(80, 80)
    header.addWidget(icon_lbl, 0, Qt.AlignVCenter)
    title_lbl = QLabel(title)
    title_lbl.setStyleSheet(f"font-size: {max(int(18 * _s), 15)}px; font-weight: bold; color: {fg};")
    header.addWidget(title_lbl, 1, Qt.AlignVCenter)
    layout.addLayout(header)

    # 内容文本
    text_lbl = QLabel(text)
    text_lbl.setWordWrap(True)
    text_lbl.setAlignment(Qt.AlignTop)
    text_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    text_lbl.setStyleSheet(f"font-size: {max(int(13 * _s), 12)}px; color: {fg};")
    layout.addWidget(text_lbl, 1)

    # 按钮行：线框蓝「确定」
    btn_row = QHBoxLayout()
    btn_row.addStretch()
    ok_btn = QPushButton("确定")
    ok_btn.setMinimumWidth(max(int(88 * _s), 72))
    ok_btn.setCursor(Qt.PointingHandCursor)
    ok_btn.clicked.connect(dlg.accept)
    btn_row.addWidget(ok_btn)
    btn_row.addStretch()
    layout.addLayout(btn_row)

    # 紧凑自适应内容尺寸（与原 QMessageBox 尺寸相近）
    dlg.setMinimumWidth(max(int(340 * _s), 300))
    dlg.adjustSize()

    # 居中到父窗口
    if parent is not None:
        try:
            dlg.move(parent.frameGeometry().center() - dlg.rect().center())
        except Exception:
            pass
    try:
        apply_dwm_dark_mode(dlg, is_dark)
    except Exception:
        pass
    dlg.exec_()


class MessageBox(QDialog):
    """统一操作提示小窗：PyQt 自定义 + 透明线框按钮 + 紧凑尺寸。

    三程序（训练器/导入器/识别器）的操作提示（信息/警告/确认）统一走这里：
    复刻 QMessageBox 小窗观感（图标+标题+正文+右下按钮），规避 QMessageBox
    标准按钮对 QSS 边框/背景渲染不稳定的问题（即「有的改成功有的没改成功」）。
    报错仍走 error_reporter 固定大窗，Windows 原生样式只保留给报错。

    兼容两种用法：
      MessageBox.warning(parent, title, text) / MessageBox.question(...) -> QMessageBox.Yes/No
      MessageBox(QMessageBox.Question, title, text, QMessageBox.Yes | QMessageBox.No, parent).exec_()
    """

    def __init__(self, icon, title, text, buttons=1, parent=None, theme=None):
        super().__init__(parent)
        from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                                     QStyle, QApplication, QMessageBox as _MB)
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QFont, QFontMetrics

        # 缩放：优先继承父窗口 _scale，否则按屏幕自适应
        _s = getattr(parent, "_scale", None) if parent is not None else None
        if not _s:
            _app = QApplication.instance()
            _sc = _app.primaryScreen() if _app else None
            _geo = _sc.availableGeometry() if _sc else None
            _sw = _geo.width() if _geo else 1920
            _sh = _geo.height() if _geo else 1080
            _s = max(min(_sw / 1920, _sh / 1080), 0.85)
        if _s <= 0:
            _s = 1.0
        if theme is None:
            try:
                _theme = SettingsManager().get("theme", "light")
            except Exception:
                _theme = "light"
        else:
            _theme = theme
        is_dark = _theme == "dark"

        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        bg = "#2d2d30" if is_dark else "#f5f5f5"
        fg = "#eeeeee" if is_dark else "#1a1a1a"
        bbrd, bhov = "#0078D4", ("#1e3a5f" if is_dark else "#e8f1fb")
        # 次按钮（否/取消）：深色 = 发白浅灰线框；浅色 = 偏深灰线框（与设置窗配色一致）
        if is_dark:
            gbrd, gfg, ghov = "#8a8a8a", "#c8c8c8", "#3f3f46"
        else:
            gbrd, gfg, ghov = "#b5b5b5", "#5f5f5f", "#ececec"
        # 字号与设置窗口一致：标题 17 / 正文 13 / 按钮 14（×scale）
        title_fs = max(int(17 * _s), 14)
        body_fs = max(int(13 * _s), 12)
        btn_fs = max(int(14 * _s), 13)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ border: none; }}
            QPushButton {{ font-size: {btn_fs}px;
                           padding: {max(int(5 * _s), 4)}px {max(int(16 * _s), 13)}px;
                           min-height: {max(int(28 * _s), 24)}px;
                           border: 1px solid {bbrd}; border-radius: 6px;
                           background: transparent; color: {bbrd}; }}
            QPushButton:hover {{ background: {bhov}; }}
            QPushButton#btn_secondary {{
                border-color: {gbrd}; color: {gfg};
            }}
            QPushButton#btn_secondary:hover {{ background: {ghov}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(16 * _s), int(12 * _s), int(16 * _s), int(10 * _s))
        layout.setSpacing(int(8 * _s))

        # 内容行：图标（左）+ 标题/正文（右），与 QMessageBox 布局一致
        content = QHBoxLayout()
        content.setSpacing(int(12 * _s))
        icon_size = 80  # 系统图标实际上限 80×80；请求更大仍返回 80，占位一致无空隙
        icon_lbl = QLabel()
        _app = QApplication.instance()
        _style = _app.style() if _app else None
        if _style:
            _sp = {
                _MB.Information: QStyle.SP_MessageBoxInformation,
                _MB.Warning: QStyle.SP_MessageBoxWarning,
                _MB.Critical: QStyle.SP_MessageBoxCritical,
                _MB.Question: QStyle.SP_MessageBoxQuestion,
            }.get(icon, QStyle.SP_MessageBoxInformation)
            icon_lbl.setPixmap(_style.standardIcon(_sp).pixmap(icon_size, icon_size))
        icon_lbl.setFixedSize(icon_size, icon_size)
        content.addWidget(icon_lbl, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(int(2 * _s))
        title_lbl = QLabel(title)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(f"font-size: {title_fs}px; font-weight: bold; color: {fg};")
        text_col.addWidget(title_lbl)
        text_lbl = QLabel(text)
        text_lbl.setWordWrap(True)
        text_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_lbl.setStyleSheet(f"font-size: {body_fs}px; color: {fg};")
        text_col.addWidget(text_lbl)
        content.addLayout(text_col, 1)
        layout.addLayout(content)

        # 按钮行：右下角（是/否 或 确定）
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        _has_yes = bool(buttons & _MB.Yes) if buttons else False
        _btn_w = max(int(88 * _s), 72)
        if _has_yes:
            _by = QPushButton("是")
            _by.setObjectName("btn_primary")
            _by.setMinimumWidth(_btn_w)
            _by.setCursor(Qt.PointingHandCursor)
            _by.clicked.connect(lambda: self.done(_MB.Yes))
            btn_row.addWidget(_by)
            _bn = QPushButton("否")
            _bn.setObjectName("btn_secondary")  # 次按钮：灰色线框（可选）
            _bn.setMinimumWidth(_btn_w)
            _bn.setCursor(Qt.PointingHandCursor)
            _bn.clicked.connect(lambda: self.done(_MB.No))
            btn_row.addWidget(_bn)
        else:
            _ok = QPushButton("确定")
            _ok.setMinimumWidth(_btn_w)
            _ok.setCursor(Qt.PointingHandCursor)
            _ok.clicked.connect(lambda: self.done(_MB.Ok))
            btn_row.addWidget(_ok)
        layout.addLayout(btn_row)

        # 紧凑小窗：宽度按内容估算（封顶），高度由布局自适应
        _fm = QFontMetrics(QFont("Microsoft YaHei UI"))
        _char_w = max(_fm.horizontalAdvance("国"), 8)
        _text_px = max((max((len(l) for l in text.split("\n")), default=0) * _char_w),
                       (max((len(l) for l in title.split("\n")), default=0) * _char_w * 1.2))
        _text_w = min(max(int(_text_px) + int(30 * _s), int(220 * _s)), int(400 * _s))
        self.setMinimumWidth(int(_text_w) + icon_size + int(12 * _s) + int(32 * _s))
        self.adjustSize()

        # 居中到父窗口
        if parent is not None:
            try:
                self.move(parent.frameGeometry().center() - self.rect().center())
            except Exception:
                pass
        try:
            apply_dwm_dark_mode(self, is_dark)
        except Exception:
            pass
        self._is_dark = is_dark

    def showEvent(self, event):
        """窗口显示时重新应用 DWM 标题栏深浅色，避免系统主题覆盖导致错色。"""
        super().showEvent(event)
        try:
            apply_dwm_dark_mode(self, getattr(self, "_is_dark", False))
        except Exception:
            pass

    @staticmethod
    def information(parent, title, text):
        from PyQt5.QtWidgets import QMessageBox as _MB
        return MessageBox(_MB.Information, title, text, _MB.Ok, parent).exec_()

    @staticmethod
    def warning(parent, title, text):
        from PyQt5.QtWidgets import QMessageBox as _MB
        return MessageBox(_MB.Warning, title, text, _MB.Ok, parent).exec_()

    @staticmethod
    def critical(parent, title, text):
        from PyQt5.QtWidgets import QMessageBox as _MB
        return MessageBox(_MB.Critical, title, text, _MB.Ok, parent).exec_()

    @staticmethod
    def question(parent, title, text, buttons=None, default=None):
        from PyQt5.QtWidgets import QMessageBox as _MB
        if buttons is None:
            buttons = _MB.Yes | _MB.No
        return MessageBox(_MB.Question, title, text, buttons, parent).exec_()


# ===== 工作区布局文件（跨进程共享） =====

def _workspace_file():
    """工作区布局文件路径（config/ 目录下）。"""
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_dir = os.path.join(app_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "workspace_layout.json")


def load_workspace():
    """读取整个工作区布局文件，返回嵌套 dict。
    结构: {"trainer": {layout: {splitter_name: [sizes]}},
           "importer": {layout: {tab: {splitter_name: [sizes]}}}}
    """
    try:
        path = _workspace_file()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_workspace_section(program, layout, section_data, tab=None):
    """原子写入工作区文件的某个分区。

    Args:
        program: "trainer" 或 "importer"
        layout: "wide" / "narrow" / "ultra_wide"
        section_data: dict，如 {"main": [...], "right": [...]}
        tab: 仅 importer 使用，如 "tab1" / "tab2"；trainer 不传
    """
    try:
        data = load_workspace()
        if program not in data or not isinstance(data[program], dict):
            data[program] = {}
        prog = data[program]
        if layout not in prog or not isinstance(prog[layout], dict):
            prog[layout] = {}
        if tab is not None:
            # importer: program -> layout -> tab -> section
            if tab not in prog[layout] or not isinstance(prog[layout][tab], dict):
                prog[layout][tab] = {}
            prog[layout][tab].update(section_data)
        else:
            # trainer: program -> layout -> section
            prog[layout].update(section_data)
        # 原子写入：先写临时文件，再 rename
        path = _workspace_file()
        _atomic_write_json(path, data)
    except Exception:
        pass


def _atomic_write_json(path, data):
    """把 data 原子写入 JSON 文件。"""
    try:
        tmp_dir = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(dir=tmp_dir, suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    except Exception:
        pass


def clear_workspace_window(program):
    """清空工作区文件中指定程序的窗口位置记录。"""
    try:
        data = load_workspace()
        if program in data and isinstance(data[program], dict):
            data[program].pop("window", None)
            _atomic_write_json(_workspace_file(), data)
    except Exception:
        pass
