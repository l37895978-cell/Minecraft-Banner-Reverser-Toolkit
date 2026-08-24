"""环境模拟器 — 独立辅助工具

启动安装向导前先运行此程序，选择模拟的软硬件配置组合。
选择完成后返回配置 dict（可被 demo_installer.pyw 直接 import 使用）。

窗口固定 4:3 比例。

运行：python installer/visualcondition.pyw
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
import tempfile

from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QWidget, QComboBox,
    QStackedWidget, QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QFrame, QTextEdit, QScrollArea, QCheckBox, QGroupBox
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QColor

_CONFIG_FILE = os.path.join(tempfile.gettempdir(), "banner_sim_config.json")


# ===== 可模拟的问题定义（第三步自定义报错） =====
# (key, component, status, issue, action, default_checked)
# 注意：安装包内含 Python 运行时和依赖库，不模拟其丢失
_SIM_PROBLEM_DEFS = [
    # ── 文件级问题 ──
    ("bdor_corrupt", "bdor.pyw", "损坏", "文件哈希不匹配，可能被修改", "重新下载并替换", True),
    ("weights_missing", "models/vit_b_16.pth", "丢失", "预训练权重文件缺失", "从 GitHub Release 重新下载", True),
    ("config_corrupt", "config/config.json", "损坏", "JSON 解析失败，配置项缺失", "重置为默认配置", False),
    ("hw_cache_stale", "config/hardware_cache.json", "过期", "硬件缓存与实际硬件不匹配", "清除缓存并重新检测", False),
    ("trainer_corrupt", "trainer.pyw", "损坏", "训练器主程序文件损坏", "重新下载并替换", False),
    ("banner_missing", "images/banner/", "丢失", "图标资源目录缺失", "从安装包恢复", False),
    ("vit_model_corrupt", "models/structures/vit_model.py", "损坏", "模型架构文件语法错误", "重新下载并替换", False),
    ("mbtl_format_error", ".mbtl 旗帜文件", "损坏", "旗帜数据格式版本不兼容", "迁移至最新格式", False),
    ("mbtlx_corrupt", ".mbtlx 标记文件", "损坏", "ZIP 解压失败，marks.json 不完整", "重新导出或修复标记文件", False),
    # ── 运行时问题（可预料/不可预料）──
    ("oom_error", "训练过程", "运行错误", "显存或内存不足（OOM），训练中断", "降低批次大小并重试", False),
    ("gpu_init_fail", "GPU 初始化", "运行错误", "CUDA/DirectML 初始化失败，无法加载计算后端", "更新显卡驱动或切换至 CPU 模式", False),
    ("disk_full", "磁盘空间", "异常", "保存路径磁盘空间不足，无法写入模型", "清理磁盘空间或更换保存路径", False),
    ("unknown_crash", "程序运行", "崩溃", "发生未知异常，程序意外退出", "查看错误日志并联系开发者", False),
]


# ===== 缩放 =====
# 分辨率适配：与 real_installer.pyw 的 _ui_scales 完全一致（窗口 + 字号同一套公式）
#   raw        = min(sw / 1920, sh / 1080)
#   win_scale  = min(max(raw, 1.0) * 1.25, 2.5)   —— 窗口 4:3 大小
#   font_scale = max(min(raw, 1.4) * 1.1, 0.85)   —— 字号 / 控件 / 间距
# 不使用 demo_installer 传入的统一 scale（4K 下 =2.5），否则字会被撑得比 real_installer 大。
def _ui_scales(app):
    screen = app.primaryScreen()
    geo = screen.availableGeometry() if screen else None
    sw = geo.width() if geo else 1920
    sh = geo.height() if geo else 1080
    raw = min(sw / 1920, sh / 1080)
    win_scale = min(max(raw, 1.0) * 1.25, 2.5)
    font_scale = max(min(raw, 1.4) * 1.1, 0.85)
    return win_scale, font_scale


# ===== 固定配置组合 =====
# 真实机型配置（2014-2026年），含年份标注
# 每项: (分类, 名称, os, cpu, ram_gb, discrete_spec, integrated_spec, disk_gb, installed, 允许模式)
# 允许模式: "本机" / "CUDA" / "DirectML" / "CPU" / "不支持"
_PRESETS = [
    # ── 本机（默认选中）──
    ("本机", "使用本机真实设备探测",
     "", "", 0, None, None, 0, False, "本机"),

    # ── 创作本（2025年真实机型）──
    ("创作本", "华硕ProArt创16 2025 · RTX 5090（2025·CUDA）",
     "Windows 11 (Build 22631)", "AMD Ryzen AI 9 HX 370", 64.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 5090 Laptop", "vram_gb": 24.0, "is_integrated": False},
     {"vendor": "amd", "name": "AMD Radeon 890M Graphics", "vram_gb": 16.0, "is_integrated": True},
     2000.0, False, "CUDA"),
    ("创作本", "华硕ProArt创16 2025 · RTX 5070（2025·CUDA）",
     "Windows 11 (Build 22631)", "AMD Ryzen AI 9 HX 370", 64.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 5070 Laptop", "vram_gb": 8.0, "is_integrated": False},
     {"vendor": "amd", "name": "AMD Radeon 890M Graphics", "vram_gb": 16.0, "is_integrated": True},
     2000.0, False, "CUDA"),
    ("创作本", "ThinkBook 16p 2025 · RTX 5070（2025·CUDA）",
     "Windows 11 (Build 22631)", "Intel Core Ultra 9 275HX", 32.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 5070 Laptop", "vram_gb": 8.0, "is_integrated": False},
     None,  # HX系列无核显
     2000.0, False, "CUDA"),
    ("创作本", "旧款创作本 · GTX 1070（2018·CUDA·旧款）",
     "Windows 10 (Build 19045)", "Intel Core i7-8750H", 16.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce GTX 1070 Laptop", "vram_gb": 8.0, "is_integrated": False},
     {"vendor": "intel", "name": "Intel UHD Graphics 630", "vram_gb": 8.0, "is_integrated": True},
     512.0, False, "CUDA"),  # 512GB SSD

    # ── 游戏本（2024-2025年真实机型）──
    ("游戏本", "联想拯救者Y9000P 2025 AI元启 · RTX 5060（2025·CUDA）",
     "Windows 11 (Build 22631)", "Intel Core Ultra 9 275HX", 32.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 5060 Laptop", "vram_gb": 8.0, "is_integrated": False},
     None,  # HX系列无核显
     2000.0, False, "CUDA"),  # 2TB (1TB+1TB 双M.2)
    ("游戏本", "联想拯救者Y9000P 2024 · RTX 4070（2024·CUDA）",
     "Windows 11 (Build 22631)", "Intel Core i9-14900HX", 32.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 4070 Laptop", "vram_gb": 8.0, "is_integrated": False},
     {"vendor": "intel", "name": "Intel UHD Graphics", "vram_gb": 16.0, "is_integrated": True},
     1000.0, False, "CUDA"),  # 1TB SSD
    ("游戏本", "华硕天选5 Pro · RTX 4070（2024·CUDA）",
     "Windows 11 (Build 22631)", "Intel Core i9-14900HX", 16.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 4070 Laptop", "vram_gb": 8.0, "is_integrated": False},
     {"vendor": "intel", "name": "Intel UHD Graphics", "vram_gb": 16.0, "is_integrated": True},
     1000.0, False, "CUDA"),  # 1TB SSD
    ("游戏本", "联想拯救者Y9000P 2022 · RTX 3060（2022·CUDA·旧款）",
     "Windows 11 (Build 22000)", "Intel Core i7-12700H", 16.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 3060 Laptop", "vram_gb": 6.0, "is_integrated": False},
     {"vendor": "intel", "name": "Intel UHD Graphics", "vram_gb": 8.0, "is_integrated": True},
     512.0, False, "CUDA"),  # 512GB SSD
    ("游戏本", "联想拯救者Y7000 · GTX 1060（2018·CUDA·旧款）",
     "Windows 10 (Build 19045)", "Intel Core i5-8300H", 16.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce GTX 1060 Laptop", "vram_gb": 6.0, "is_integrated": False},
     {"vendor": "intel", "name": "Intel UHD Graphics 630", "vram_gb": 8.0, "is_integrated": True},
     512.0, False, "CUDA"),  # 512GB SSD
    ("游戏本", "联想拯救者R720 · GTX 1050Ti（2016·CUDA·旧款）",
     "Windows 10 (Build 14393)", "Intel Core i5-7300HQ", 8.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce GTX 1050Ti Laptop", "vram_gb": 4.0, "is_integrated": False},
     {"vendor": "intel", "name": "Intel HD Graphics 630", "vram_gb": 4.0, "is_integrated": True},
     256.0, False, "CUDA"),  # 256GB SSD

    # ── 办公本 / 轻薄本（2024-2025年真实机型）──
    ("办公本", "联想小新Pro16 2025锐龙版 · AMD核显（2025·DirectML）",
     "Windows 11 (Build 22631)", "AMD Ryzen 7 H 255", 24.0,
     None,
     {"vendor": "amd", "name": "AMD Radeon 780M Graphics", "vram_gb": 4.0, "is_integrated": True},
     1000.0, False, "DirectML"),  # 1TB SSD
    ("办公本", "联想小新Pro16 2025酷睿版 · Intel核显（2025·DirectML）",
     "Windows 11 (Build 22631)", "Intel Core Ultra 5 225H", 32.0,
     None,
     {"vendor": "intel", "name": "Intel ARC Graphics", "vram_gb": 4.0, "is_integrated": True},
     1000.0, False, "DirectML"),  # 1TB SSD
    ("办公本", "联想小新Pro16 2024 · Intel核显（2024·DirectML）",
     "Windows 11 (Build 22621)", "Intel Core Ultra 5 125H", 32.0,
     None,
     {"vendor": "intel", "name": "Intel ARC Graphics", "vram_gb": 4.0, "is_integrated": True},
     1000.0, False, "DirectML"),  # 1TB SSD
    ("办公本", "旧款办公本 · AMD Vega 8 核显（2020·DirectML·旧款）",
     "Windows 10 (Build 19045)", "AMD Ryzen 5 4600U", 16.0,
     None,
     {"vendor": "amd", "name": "AMD Radeon RX Vega 8 Graphics", "vram_gb": 2.0, "is_integrated": True},
     512.0, False, "DirectML"),  # 512GB SSD
    ("办公本", "旧款办公本 · Intel UHD 核显（2019·CPU·旧款）",
     "Windows 10 (Build 18362)", "Intel Core i5-8265U", 8.0,
     None,
     {"vendor": "intel", "name": "Intel UHD Graphics 620", "vram_gb": 1.0, "is_integrated": True},
     256.0, False, "CPU"),  # 256GB SSD
    ("办公本", "旧款办公本 · Intel HD 620 核显（2017·CPU·旧款）",
     "Windows 10 (Build 19045)", "Intel Core i5-7200U", 8.0,
     None,
     {"vendor": "intel", "name": "Intel HD Graphics 620", "vram_gb": 1.0, "is_integrated": True},
     256.0, False, "CPU"),  # 256GB SSD
    ("办公本", "旧款轻薄本 · Intel HD 520 核显（2016·CPU·旧款）",
     "Windows 10 (Build 14393)", "Intel Core i5-6200U", 8.0,
     None,
     {"vendor": "intel", "name": "Intel HD Graphics 520", "vram_gb": 1.0, "is_integrated": True},
     120.0, False, "CPU"),  # 120GB SSD

    # ── 台式机（2024-2025年真实机型）──
    ("台式机", "联想GeekPro 2025 Ultra9 · RTX 5060 Ti（2025·CUDA）",
     "Windows 11 (Build 22631)", "Intel Core Ultra 9 275HX", 32.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 5060 Ti", "vram_gb": 8.0, "is_integrated": False},
     None, 1000.0, False, "CUDA"),  # 1TB SSD
    ("台式机", "联想GeekPro 2024 i7 · RTX 4060 Ti（2024·CUDA）",
     "Windows 11 (Build 22631)", "Intel Core i7-14700F", 32.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 4060 Ti", "vram_gb": 8.0, "is_integrated": False},
     None, 1000.0, False, "CUDA"),  # 1TB SSD
    ("台式机", "联想GeekPro 2024 i5 · RTX 4060（2024·CUDA）",
     "Windows 11 (Build 22631)", "Intel Core i5-14400F", 16.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 4060", "vram_gb": 8.0, "is_integrated": False},
     None, 1000.0, False, "CUDA"),  # 1TB SSD
    ("台式机", "联想GeekPro 2024 AMD · RX 7600（2024·DirectML）",
     "Windows 11 (Build 22631)", "Intel Core i5-14400F", 16.0,
     {"vendor": "amd", "name": "AMD Radeon RX 7600", "vram_gb": 8.0, "is_integrated": False},
     None, 512.0, False, "DirectML"),  # 512GB SSD
    ("台式机", "旧款台式机 · GTX 1650（2020·CPU·旧款）",
     "Windows 10 (Build 19045)", "Intel Core i5-10400", 16.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce GTX 1650", "vram_gb": 4.0, "is_integrated": False},
     None, 512.0, False, "CPU"),  # 512GB SSD
    ("台式机", "旧款台式机 · GTX 1050Ti（2017·CPU·旧款）",
     "Windows 10 (Build 19045)", "Intel Core i5-7400", 8.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce GTX 1050Ti", "vram_gb": 4.0, "is_integrated": False},
     None, 256.0, False, "CPU"),  # 256GB SSD

    # ── 硬件落后 · 仅 CPU（2019年旧款）──  # 覆盖2014-2026年机型
    ("仅CPU", "旧款核显本 · UHD 620（2019·CPU 模式）",
     "Windows 10 (Build 18362)", "Intel Core i5-8250U", 8.0,
     None,
     {"vendor": "intel", "name": "Intel UHD Graphics 620", "vram_gb": 1.0, "is_integrated": True},
     256.0, False, "CPU"),  # 256GB SSD
    ("仅CPU", "老旧独显 · GTX 1050（2019·CPU 模式）",
     "Windows 10 (Build 18362)", "Intel Core i5-8400", 8.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce GTX 1050", "vram_gb": 2.0, "is_integrated": False},
     None, 256.0, False, "CPU"),  # 256GB SSD
    ("仅CPU", "AMD Vega 3 核显本（2019·CPU 模式）",
     "Windows 10 (Build 18362)", "AMD Ryzen 3 3200U", 8.0,
     None,
     {"vendor": "amd", "name": "AMD Radeon RX Vega 3 Graphics", "vram_gb": 1.0, "is_integrated": True},
     256.0, False, "CPU"),  # 256GB SSD

    # ── 硬件不达标 ──
    ("不达标", "极低配老电脑（不支持）",
     "Windows 10 (Build 19045)", "Intel Core i3-7100", 4.0,
     None,
     {"vendor": "intel", "name": "Intel HD Graphics 630", "vram_gb": 1.0, "is_integrated": True},
     120.0, False, "不支持"),  # 120GB SSD
    ("不达标", "旧款办公本 · HD 4400（2014·不支持）",
     "Windows 8.1 (Build 9600)", "Intel Core i3-4010U", 4.0,
     None,
     {"vendor": "intel", "name": "Intel HD Graphics 4400", "vram_gb": 1.0, "is_integrated": True},
     80.0, False, "不支持"),  # 80GB SSD
    ("不达标", "旧款台式机 · HD 530（2015·不支持）",
     "Windows 10 (Build 14393)", "Intel Core i3-6100", 4.0,
     None,
     {"vendor": "intel", "name": "Intel HD Graphics 530", "vram_gb": 1.0, "is_integrated": True},
     60.0, False, "不支持"),  # 60GB SSD

    # ── 软件不兼容（硬件可能达标）──
    ("系统不兼容", "Windows 10 早期版本 · 1909 前（不支持）",
     "Windows 10 (Build 17763)", "Intel Core i7-10700", 16.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 3070", "vram_gb": 8.0, "is_integrated": False},
     None, 512.0, False, "不支持"),
    ("系统不兼容", "Windows 8.1（不支持）",
     "Windows 8.1 (Build 9600)", "Intel Core i5-4200U", 8.0,
     None,
     {"vendor": "intel", "name": "Intel HD Graphics 4400", "vram_gb": 1.0, "is_integrated": True},
     120.0, False, "不支持"),
    ("系统不兼容", "Windows 7（不支持）",
     "Windows 7 (Build 7601)", "Intel Core i3-3220", 4.0,
     None,
     {"vendor": "intel", "name": "Intel HD Graphics 2500", "vram_gb": 1.0, "is_integrated": True},
     80.0, False, "不支持"),
    ("系统不兼容", "macOS Sonoma（不支持）",
     "macOS 14 Sonoma", "Apple M2 Pro", 16.0,
     None,
     {"vendor": "apple", "name": "Apple M2 Pro 集成显卡", "vram_gb": 16.0, "is_integrated": True},
     256.0, False, "不支持"),
    ("系统不兼容", "Ubuntu 22.04 Linux（不支持）",
     "Ubuntu 22.04 LTS", "AMD Ryzen 5 5600", 16.0,
     {"vendor": "amd", "name": "AMD Radeon RX 6600", "vram_gb": 8.0, "is_integrated": False},
     None, 512.0, False, "不支持"),

    # ── 已安装（维护模式）──
    ("已安装", "已安装 · 维护模式",
     "Windows 11 (Build 22631)", "Intel Core i7-12700K", 32.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 3070", "vram_gb": 8.0, "is_integrated": False},
     None, 1000.0, True, "CUDA"),  # 1TB SSD

    # ── 已安装 · 诊断修复（演示诊断完成后进入修复界面）──
    ("已安装", "已安装 · 诊断修复（演示修复流程）",
     "Windows 11 (Build 22631)", "Intel Core i7-12700K", 32.0,
     {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 3070", "vram_gb": 8.0, "is_integrated": False},
     None, 1000.0, True, "CUDA"),  # 1TB SSD
]


# ===== 库版本对应表（按架构，与 demo_installer 进度页一致） =====
_LIB_VERSIONS = {
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
        ("numpy",            "1.26.4",          "18MB"),
        ("opencv-python",    "4.10.0.84",       "60MB"),
        ("Pillow",           "10.4.0",          "5MB"),
        ("matplotlib",       "3.9.2",           "40MB"),
        ("psutil",           "6.0.0",           "500KB"),
    ],
    "cpu": [
        ("torch",            "2.4.0+cpu",       "200MB"),
        ("torchvision",      "0.19.0+cpu",      "30MB"),
        ("PyQt5",            "5.15.11",         "120MB"),
        ("numpy",            "1.26.4",          "18MB"),
        ("opencv-python",    "4.10.0.84",       "60MB"),
        ("Pillow",           "10.4.0",          "5MB"),
        ("matplotlib",       "3.9.2",           "40MB"),
        ("psutil",           "6.0.0",           "500KB"),
    ],
}


# ===== Python 安装包信息（与 real_installer 兜底版本 3.13.14 一致） =====
_PYTHON_DOWNLOAD = {
    "version": "3.13.14",
    "url": "https://www.python.org/ftp/python/3.13.14/python-3.13.14-amd64.exe",
    "size": "27MB",
}


def _gen_ram_type(cpu, ram_gb):
    """根据 CPU 型号推测内存代际类型。"""
    cl = (cpu or "").lower()
    # Intel Core Ultra HX 系列（Arrow Lake-HX 桌面级移动版）使用 DDR5 SO-DIMM，非 LPDDR5X
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


def _gen_ram_avail(ram_gb):
    """可用内存（约为总量的 98.5%）。"""
    return round(ram_gb * 0.985, 1)


def _calc_disk_free(total, scenario, h):
    """根据空间选项计算硬盘可用空间。

    Args:
        total: 硬盘总容量 GB
        scenario: "default" / "abundant" / "tight" / "scarce"
        h: 配置名哈希（用于确定性随机化）
    """
    if scenario == "abundant":
        return round(total * (0.60 + (h % 31) / 100), 1)  # 60~90%
    elif scenario == "tight":
        return round(11 + (h % 90) / 10, 1)  # 11~19.9 GB
    elif scenario == "scarce":
        return round(2 + (h % 80) / 10, 1)  # 2~9.9 GB
    else:  # default
        return round(total * (0.40 + (h % 41) / 100), 1)  # 40~80%


def _gen_disks(cat, disk_gb, name, cpu="", space_scenario="default"):
    """生成模拟盘符列表。

    硬盘组成按真实机型配置（disk_gb 为 C 盘容量，不含数据盘）：
      - 创作本 2TB：ThinkBook 16p 双M.2 → C盘 1TB SSD + D盘 1TB SSD
                   ProArt创16 → 单盘 2TB SSD
      - 游戏本 2TB：Y9000P 2025 双M.2 → C盘 1TB SSD + D盘 1TB SSD
      - 游戏本 1TB：单盘 1TB SSD
      - 办公本 1TB：单盘 1TB SSD
      - 台式机 1TB：单盘 1TB SSD（可扩展 HDD）
      - 台式机 512GB：单盘 512GB SSD
      - 旧款：单盘（SSD 或 HDD）

    系统盘类型按 CPU/核显综合判断：
      - 2014-2016 极老平台（HD 4xx/5xx 核显、i3-3xxx/4xxx/6xxx、i5-6200U 等）→ HDD
      - 2017+ 机型（含 GTX 1050/1060 旧款游戏本）→ SSD

    可用空间按空间选项（space_scenario）：
      - default:  40~80% 总容量
      - abundant: 60~90% 总容量
      - tight:    11~19.9 GB（刚好超过 10GB 最低要求）
      - scarce:   2~9.9 GB（低于 10GB，安装按钮禁用）
    """
    import hashlib
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)

    c_total = int(disk_gb) if disk_gb and disk_gb > 0 else 512
    name_lower = name.lower()
    # 仅 2014-2016 极老平台系统盘为 HDD（综合 CPU + 名称关键字判断）
    cl = ((cpu or "") + " " + name).lower()
    hdd_marks = ("hd 4400", "hd 4600", "hd 530", "hd 520", "hd 2500",
                 "i3-4010", "i3-6100", "i3-3220", "i5-6200u", "i3-7100",
                 "极低配", "windows 7")
    if any(kw in cl for kw in hdd_marks):
        c_type = "HDD"
    else:
        c_type = "SSD"

    c_free = _calc_disk_free(c_total, space_scenario, h)
    disks = [{"letter": "C", "label": "系统盘",
              "total_gb": c_total, "free_gb": c_free, "type": c_type}]

    # 数据盘：仅双M.2机型有 D 盘，容量不超过 C 盘
    has_dual_m2 = any(kw in name for kw in ("ThinkBook 16p", "Y9000P 2025", "双M.2"))
    if has_dual_m2 and c_total >= 2000:
        # 双M.2：C盘和D盘各占一半
        d_total = c_total // 2
        c_total = c_total - d_total
        c_free = _calc_disk_free(c_total, space_scenario, h)
        disks[0]["total_gb"] = c_total
        disks[0]["free_gb"] = c_free
        d_free = _calc_disk_free(d_total, space_scenario, h)
        disks.append({"letter": "D", "label": "数据盘",
                      "total_gb": d_total, "free_gb": d_free, "type": "SSD"})
    elif cat == "台式机" and c_total >= 512 and "旧款" not in name:
        # 台式机可扩展 HDD（模拟用户自行加装）
        d_total = 1000  # 1TB HDD
        d_free = _calc_disk_free(d_total, space_scenario, h)
        disks.append({"letter": "D", "label": "数据盘",
                      "total_gb": d_total, "free_gb": d_free, "type": "HDD"})
    # 仅CPU/不达标：不配数据盘（性能不足，无法有效训练）
    return disks


def _detect_os_type(os_str):
    """根据 OS 字符串判断系统类型。

    返回: "windows" / "linux" / "macos" / "unknown"
    """
    os_lower = (os_str or "").lower()
    if "windows" in os_lower:
        return "windows"
    if "ubuntu" in os_lower or "linux" in os_lower or "debian" in os_lower \
       or "fedora" in os_lower or "centos" in os_lower or "arch" in os_lower:
        return "linux"
    if "macos" in os_lower or "mac os" in os_lower or "sonoma" in os_lower \
       or "ventura" in os_lower or "monterey" in os_lower or "big sur" in os_lower:
        return "macos"
    return "unknown"


def _config_to_json(cfg, space_scenario="default"):
    """将配置元组转为 info dict（与 demo_installer 的 _InitThread 输出格式一致）。

    Args:
        cfg: _PRESETS 中的配置元组
        space_scenario: 空间选项（同时影响内存可用量与硬盘可用空间）
            - "default"  默认（内存约为总量 98.5%，硬盘 40~80%）
            - "abundant" 充足（内存可用 90%，硬盘 60~90%）
            - "tight"    刚好（内存可用 50%，硬盘 11~19.9 GB）
            - "scarce"   不足（内存可用 15%，硬盘 2~9.9 GB）
    """
    cat, name, os_ver, cpu, ram, disc, igpu, disk, installed, allow = cfg
    all_gpus = []
    if disc:
        all_gpus.append(disc)
    if igpu:
        all_gpus.append(igpu)
    if all_gpus:
        best = disc or igpu
        gpu = {"discrete": disc, "integrated": igpu, "all": all_gpus,
               "vendor": best["vendor"], "name": best["name"],
               "vram_gb": best["vram_gb"], "is_integrated": best["is_integrated"]}
    else:
        gpu = {"discrete": None, "integrated": None, "all": [],
               "vendor": "none", "name": "", "vram_gb": 0, "is_integrated": False}
    install_state = {"installed": False, "path": None, "version": None, "components": []}
    if installed:
        install_state = {"installed": True,
                         "path": r"C:\Program Files\我的世界旗帜逆向套件",
                         "version": "v0.5 beta1",
                         "components": ["torch", "pyqt5", "bdor"]}
    # 模拟多盘列表 + 内存类型/可用内存（均受空间选项控制）
    disks = _gen_disks(cat, disk, name, cpu, space_scenario)
    ram_type = _gen_ram_type(cpu, ram)
    if space_scenario == "abundant":
        ram_avail = round(ram * 0.90, 1)
    elif space_scenario == "tight":
        ram_avail = round(ram * 0.50, 1)
    elif space_scenario == "scarce":
        ram_avail = round(ram * 0.15, 1)
    else:  # default
        ram_avail = _gen_ram_avail(ram)
    # gpu_reasons：按硬件与 allow 拆分为分项（CUDA/DirectML 各占一行）
    allow = allow.upper()
    gpu_reasons = []
    if "CUDA" in allow:
        gpu_reasons.append(("CUDA 可用", True))
    if "DIRECTML" in allow:
        gpu_reasons.append(("DirectML 可用", True))
    # 双 GPU（独显 CUDA + 核显）：核显也支持 DirectML，追加一行
    if igpu and "CUDA" in allow and "DIRECTML" not in allow:
        iv = igpu.get("vendor", "")
        if iv in ("amd", "intel"):
            gpu_reasons.append(("DirectML 可用（核显）", True))
    if not gpu_reasons:
        gpu_reasons = [("仅 CPU 模式", False)]
    gpu_reason = "；".join(t for t, _ in gpu_reasons)
    os_type = _detect_os_type(os_ver)
    return {
        "os": os_ver, "os_type": os_type, "python": "", "cpu": cpu, "ram_gb": ram,
        "ram_type": ram_type, "ram_avail_gb": ram_avail,
        "gpu": gpu, "gpu_ok": allow in ("CUDA", "DIRECTML") or "/" in allow,
        "gpu_reason": f"允许模式：{allow}",
        "gpu_reasons": gpu_reasons,
        "disk_free_gb": disks[0]["free_gb"] if disks else 0.0,
        "disks": disks,
        "install_state": install_state,
        "_sim_allow": allow,
    }


# 允许模式对应的颜色标签
_ALLOW_COLORS = {
    "本机": "#1a73e8",
    "CUDA": "#27ae60",
    "DirectML": "#2980b9",
    "CPU": "#e67e22",
    "不支持": "#c0392b",
}


class _ConfigItemWidget(QWidget):
    """多行配置项 widget，防止比例崩坏。"""

    def __init__(self, cfg, us, parent=None):
        super().__init__(parent)
        self._us = us
        cat, name, os_ver, cpu, ram, disc, igpu, disk, installed, allow = cfg

        layout = QVBoxLayout(self)
        m = max(int(6 * us), 5)
        layout.setContentsMargins(m, m, m, m)
        layout.setSpacing(max(int(3 * us), 2))

        fs1 = max(int(8 * us), 8)
        fs2 = max(int(7 * us), 7)

        # 第一行：分类标签 + 配置名称 + 允许模式
        row1 = QHBoxLayout()
        row1.setSpacing(max(int(4 * us), 3))

        cat_lbl = QLabel(cat)
        cat_lbl.setMinimumWidth(max(int(70 * us), 55))
        cat_lbl.setAlignment(Qt.AlignCenter)
        cat_color = _ALLOW_COLORS.get(allow, "#888")
        cat_lbl.setStyleSheet(
            f"background: {cat_color}; color: white; border-radius: 3px; "
            f"font-size: {fs2}pt; padding: 1px 2px;")
        row1.addWidget(cat_lbl)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"font-size: {fs1}pt; font-weight: bold; color: #333;")
        row1.addWidget(name_lbl, 1)

        allow_lbl = QLabel(f"[{allow}]")
        allow_lbl.setStyleSheet(
            f"font-size: {fs2}pt; font-weight: bold; color: {cat_color};")
        row1.addWidget(allow_lbl)
        layout.addLayout(row1)

        # 本机特殊处理：不显示硬件详情
        if allow == "本机":
            hint_lbl = QLabel("将使用 Windows API 真实探测本机硬件和系统信息")
            hint_lbl.setStyleSheet(f"font-size: {fs2}pt; color: #666; font-style: italic;")
            layout.addLayout(_wrap_h(hint_lbl))
        else:
            # 第二行：CPU + 内存 + 磁盘
            gpu_name = "无 GPU"
            if disc:
                gpu_name = f"{disc['name']}({disc['vram_gb']}G)"
            elif igpu:
                gpu_name = igpu["name"]

            detail = f"CPU: {cpu}  |  RAM: {ram}G  |  磁盘: {disk}G  |  GPU: {gpu_name}"
            detail_lbl = QLabel(detail)
            detail_lbl.setStyleSheet(f"font-size: {fs2}pt; color: #666;")
            layout.addLayout(_wrap_h(detail_lbl))

            # 第三行：系统
            os_lbl = QLabel(f"系统: {os_ver}")
            os_lbl.setStyleSheet(f"font-size: {fs2}pt; color: #888;")
            layout.addLayout(_wrap_h(os_lbl))

    def sizeHint(self):
        sh = super().sizeHint()
        min_h = max(int(58 * self._us), 48)
        return QSize(sh.width(), max(sh.height(), min_h))


def _wrap_h(widget):
    """将 widget 包裹进 HBoxLayout，防止水平溢出。"""
    h = QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(0)
    h.addWidget(widget, 1)
    return h


class _EnvDetailPage(QScrollArea):
    """第二页：环境细节模拟（硬件配置详情 + 硬盘占用 + 库安装 + Python 环境）。

    外层 QScrollArea 兜底：内容超出窗口高度时滚动查看，避免被裁剪遮挡。
    """

    def __init__(self, us, parent=None):
        super().__init__(parent)
        self._us = us
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        fs_title = max(int(10 * us), 10)
        fs_body = max(int(8 * us), 8)
        fs_small = max(int(7 * us), 7)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        m = max(int(8 * us), 6)
        layout.setContentsMargins(m, m, m, m)
        layout.setSpacing(max(int(6 * us), 4))

        # ===== 0. 硬件配置详情（与 demo_installer 初始化页格式一致） =====
        hw_title = QLabel("硬件配置详情")
        f = hw_title.font()
        f.setPointSize(fs_title)
        f.setBold(True)
        hw_title.setFont(f)
        layout.addWidget(hw_title)

        self.hw_detail = QTextEdit()
        self.hw_detail.setReadOnly(True)
        self.hw_detail.setStyleSheet(
            f"QTextEdit{{font-size:{fs_body}pt; border:1px solid #ccc; "
            f"border-radius:4px; background:#fafcff;}}")
        self.hw_detail.setFixedHeight(max(int(150 * us), 120))
        layout.addWidget(self.hw_detail)

        # ===== 1. 硬盘占用情况 =====
        disk_title = QLabel("硬盘占用情况")
        f = disk_title.font()
        f.setPointSize(fs_title)
        f.setBold(True)
        disk_title.setFont(f)
        layout.addWidget(disk_title)

        self.disk_table = QTableWidget(0, 5)
        self.disk_table.setHorizontalHeaderLabels(["盘符", "类型", "总量", "可用", "占用率"])
        self.disk_table.verticalHeader().setVisible(False)
        self.disk_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.disk_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.disk_table.setSelectionMode(QTableWidget.NoSelection)
        self.disk_table.setStyleSheet(
            f"QTableWidget{{font-size:{fs_small}pt; border:1px solid #ccc; border-radius:4px;}}"
            f"QHeaderView::section{{background:#f0f0f0; padding:4px; border:none; "
            f"border-bottom:1px solid #ccc; font-size:{fs_small}pt;}}")
        self.disk_table.setFixedHeight(max(int(100 * us), 80))
        layout.addWidget(self.disk_table)

        self.disk_scenario_lbl = QLabel("")
        self.disk_scenario_lbl.setStyleSheet(
            f"font-size:{fs_small}pt; color:#888; padding:2px 0;")
        layout.addWidget(self.disk_scenario_lbl)

        # ===== 2. 库安装情况模拟 =====
        lib_title = QLabel("库安装情况模拟（按架构）")
        f = lib_title.font()
        f.setPointSize(fs_title)
        f.setBold(True)
        lib_title.setFont(f)
        layout.addWidget(lib_title)

        self.lib_arch_lbl = QLabel("")
        self.lib_arch_lbl.setStyleSheet(f"font-size:{fs_small}pt; color:#888;")
        layout.addWidget(self.lib_arch_lbl)

        self.lib_table = QTableWidget(0, 3)
        self.lib_table.setHorizontalHeaderLabels(["库名", "版本", "大小"])
        self.lib_table.verticalHeader().setVisible(False)
        self.lib_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.lib_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.lib_table.setSelectionMode(QTableWidget.NoSelection)
        self.lib_table.setStyleSheet(
            f"QTableWidget{{font-size:{fs_small}pt; border:1px solid #ccc; border-radius:4px;}}"
            f"QHeaderView::section{{background:#f0f0f0; padding:4px; border:none; "
            f"border-bottom:1px solid #ccc; font-size:{fs_small}pt;}}")
        layout.addWidget(self.lib_table, 1)

        # 库总大小
        self.lib_total_lbl = QLabel("")
        self.lib_total_lbl.setStyleSheet(
            f"font-size:{fs_small}pt; color:#666; padding:2px 0;")
        layout.addWidget(self.lib_total_lbl)

        # ===== 3. Python 环境 =====
        py_title = QLabel("Python 环境")
        f = py_title.font()
        f.setPointSize(fs_title)
        f.setBold(True)
        py_title.setFont(f)
        layout.addWidget(py_title)

        self.py_info_lbl = QLabel("")
        self.py_info_lbl.setStyleSheet(f"font-size:{fs_body}pt;")
        self.py_info_label_word_wrap = True
        self.py_info_lbl.setWordWrap(True)
        layout.addWidget(self.py_info_lbl)

        self.setWidget(inner)

    def update_content(self, sim_info):
        """根据所选配置的 sim_info 更新页面内容。"""
        if not sim_info:
            self._update_hw_detail(None)
            self._update_disk_table([])
            self.disk_scenario_lbl.setText("本机模式：使用真实设备探测")
            self.lib_arch_lbl.setText("本机模式：架构由硬件检测决定")
            self._update_lib_table("cuda", "本机")
            self.py_info_lbl.setText(
                f"Python {_PYTHON_DOWNLOAD['version']}（若未安装，安装流程将自动下载）")
            return

        # 硬件配置详情
        self._update_hw_detail(sim_info)

        # 硬盘信息
        disks = sim_info.get("disks", [])
        self._update_disk_table(disks)

        # 硬盘场景标签
        if disks:
            free = disks[0].get("free_gb", 0)
            if free >= 20:
                scenario = "充足"
                color = "#27ae60"
            elif free >= 10:
                scenario = "刚好（略高于 10GB 最低要求）"
                color = "#f39c12"
            else:
                scenario = "不足（低于 10GB，安装将受限）"
                color = "#c0392b"
            self.disk_scenario_lbl.setStyleSheet(
                f"font-size:{max(int(7 * self._us), 7)}pt; color:{color}; padding:2px 0;")
            self.disk_scenario_lbl.setText(f"场景：{scenario}")

        # 库安装情况
        allow = sim_info.get("_sim_allow", "CPU").upper()
        if "CUDA" in allow:
            arch_key = "cuda"
            arch_label = "CUDA（NVIDIA 独显）"
        elif "DIRECTML" in allow:
            arch_key = "directml"
            arch_label = "DirectML（AMD/Intel GPU）"
        else:
            arch_key = "cpu"
            arch_label = "纯 CPU"
        self.lib_arch_lbl.setText(f"架构：{arch_label}")
        self._update_lib_table(arch_key, arch_label)

        # Python 环境
        installed = sim_info.get("install_state", {}).get("installed", False)
        if installed:
            self.py_info_lbl.setText(
                f"Python {_PYTHON_DOWNLOAD['version']}（已安装，仅更新库）")
        else:
            self.py_info_lbl.setText(
                f"Python {_PYTHON_DOWNLOAD['version']}（未安装，安装流程将自动下载 {_PYTHON_DOWNLOAD['size']}）")

    def _update_hw_detail(self, sim_info):
        """填充硬件配置详情（与 demo_installer 初始化页格式一致）。

        本机模式显示提示；模拟模式按系统/CPU/内存/GPU/适配理由分行展示，
        每行带 ✓/✗ 颜色标记。
        """
        fs = max(int(8 * self._us), 8)
        if not sim_info:
            self.hw_detail.setHtml(
                f'<div style="color:#666;font-size:{fs}pt;">'
                '本机模式：将使用 Windows API 真实探测系统、CPU、内存、GPU 等硬件信息。'
                '<br>选择上方具体机型可查看其完整模拟配置详情。'
                '</div>')
            return

        lines = []

        def _emit(text, ok=True):
            mark = "✓" if ok else "✗"
            color = "#2e7d32" if ok else "#c62828"
            lines.append(
                f'<span style="color:{color};">{mark}</span> '
                f'<span style="font-size:{fs}pt;">{text}</span><br>')

        # 操作系统
        os_ver = sim_info.get("os", "")
        os_type = sim_info.get("os_type", "unknown")
        os_ok = os_type == "windows" and bool(os_ver)
        _emit(f"操作系统：{os_ver}", os_ok)

        # CPU
        cpu = sim_info.get("cpu", "")
        _emit(f"CPU：{cpu}", bool(cpu))

        # 内存（含类型/可用）
        ram = sim_info.get("ram_gb", 0)
        ram_type = sim_info.get("ram_type", "")
        ram_avail = sim_info.get("ram_avail_gb", 0)
        if ram_type:
            _emit(f"内存：{ram} GB {ram_type}（可用 {ram_avail} GB）", ram >= 8)
        else:
            _emit(f"内存：{ram} GB", ram >= 8)

        # GPU（独显优先，核显次之，按 GPU 0/1 编号）
        gpu = sim_info.get("gpu", {})
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

        # GPU 适配结论 + 分项理由
        gpu_ok = sim_info.get("gpu_ok", False)
        gpu_reasons = sim_info.get("gpu_reasons", [])
        ok_text = "✓ 满足训练要求" if gpu_ok else "⚠ 不满足训练要求"
        _emit(f"GPU 适配：{ok_text}", gpu_ok)
        for r_text, r_ok in gpu_reasons:
            sub_mark = "✓" if r_ok else "✗"
            sub_color = "#2e7d32" if r_ok else "#c62828"
            lines.append(
                f'&nbsp;&nbsp;&nbsp;&nbsp;<span style="color:{sub_color};">{sub_mark}</span> '
                f'<span style="font-size:{fs}pt;">{r_text}</span><br>')

        # 允许模式（与 _sim_allow 一致）
        allow = sim_info.get("_sim_allow", "")
        if allow:
            _emit(f"允许模式：{allow}", allow != "不支持")

        # 已安装状态
        state = sim_info.get("install_state", {})
        if state.get("installed"):
            ver = state.get("version", "未知版本")
            comps = len(state.get("components", []))
            path = state.get("path", "")
            _emit(f"已安装状态：已安装（{ver}，{comps} 个组件，路径：{path}）", True)
        else:
            _emit("已安装状态：未安装（将进行全新安装）", True)

        self.hw_detail.setHtml("".join(lines))

    def _update_disk_table(self, disks):
        self.disk_table.setRowCount(len(disks))
        for i, disk in enumerate(disks):
            letter = disk.get("letter", "?")
            dtype = disk.get("type", "SSD")
            total = disk.get("total_gb", 0)
            free = disk.get("free_gb", 0)
            used_pct = round((1 - free / total) * 100, 1) if total > 0 else 0

            self.disk_table.setItem(i, 0, QTableWidgetItem(f"{letter}:"))
            self.disk_table.setItem(i, 1, QTableWidgetItem(dtype))
            self.disk_table.setItem(i, 2, QTableWidgetItem(f"{total} GB"))
            self.disk_table.setItem(i, 3, QTableWidgetItem(f"{free} GB"))

            # 占用率用进度条展示
            bar = QProgressBar()
            bar.setValue(int(used_pct))
            bar.setFormat(f"{used_pct}%")
            bar.setFixedHeight(max(int(16 * self._us), 14))
            bar.setStyleSheet(
                "QProgressBar{border:1px solid #ccc; border-radius:3px; text-align:center;}"
                "QProgressBar::chunk{background:#3498db; border-radius:2px;}")
            self.disk_table.setCellWidget(i, 4, bar)

    def _update_lib_table(self, arch_key, arch_label):
        libs = _LIB_VERSIONS.get(arch_key, _LIB_VERSIONS["cpu"])
        self.lib_table.setRowCount(len(libs))
        for i, (name, ver, size) in enumerate(libs):
            self.lib_table.setItem(i, 0, QTableWidgetItem(name))
            self.lib_table.setItem(i, 1, QTableWidgetItem(ver))
            self.lib_table.setItem(i, 2, QTableWidgetItem(size))

        self.lib_total_lbl.setText(f"共 {len(libs)} 个库（{arch_label}）")


# ===== 第 3 页：自定义模拟问题 =====
class _ProblemSelectPage(QScrollArea):
    """第三步：自定义模拟哪些文件/组件出问题。

    用户勾选后，所选问题写入 sim_config 的 _sim_problems 字段，
    test.pyw 检测到这些问题后可进入修复界面。
    """

    def __init__(self, us, parent=None):
        super().__init__(parent)
        self._us = us
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(max(int(8 * us), 6))

        title = QLabel("自定义模拟问题")
        tf = title.font()
        tf.setPointSize(max(int(10 * us), 10))
        tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet("color: #1a1a1a; border: none;")
        layout.addWidget(title)

        desc = QLabel("勾选要模拟的文件/组件问题。修复界面将显示这些问题并模拟修复流程。")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: #888; font-size: {max(int(7 * us), 7)}pt; border: none;")
        layout.addWidget(desc)

        # 问题勾选区
        group = QGroupBox("可模拟的问题")
        gf = group.font()
        gf.setPointSize(max(int(9 * us), 9))
        gf.setBold(True)
        group.setFont(gf)
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(max(int(6 * us), 4))
        m = max(int(8 * us), 6)
        group_layout.setContentsMargins(m, m, m, m)

        self._checkboxes = {}
        for key, comp, status, issue, action, default in _SIM_PROBLEM_DEFS:
            cb = QCheckBox(f"{comp} — {status}：{issue}")
            cf = cb.font()
            cf.setPointSize(max(int(8 * us), 8))
            cb.setFont(cf)
            cb.setChecked(default)
            cb.setStyleSheet("border: none;")
            cb.stateChanged.connect(self._update_summary)
            self._checkboxes[key] = cb
            group_layout.addWidget(cb)

        layout.addWidget(group)

        # 全选/全不选按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(max(int(6 * us), 4))
        btn_all = QPushButton("全选")
        btn_all.setStyleSheet(
            f"QPushButton {{ border: 1px solid #ccc; border-radius: 4px; "
            f"padding: {max(int(4 * us), 3)}px {max(int(12 * us), 8)}px; "
            f"font-size: {max(int(7 * us), 7)}pt; }}")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton("全不选")
        btn_none.setStyleSheet(
            f"QPushButton {{ border: 1px solid #ccc; border-radius: 4px; "
            f"padding: {max(int(4 * us), 3)}px {max(int(12 * us), 8)}px; "
            f"font-size: {max(int(7 * us), 7)}pt; }}")
        btn_none.clicked.connect(lambda: self._set_all(False))
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 选中摘要
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(
            f"color: #555; font-size: {max(int(7 * us), 7)}pt; "
            f"background: #f5f9ff; border: 1px solid #d0e0f0; border-radius: 4px; "
            f"padding: {max(int(6 * us), 4)}px; border: none;")
        layout.addWidget(self._summary)
        self._update_summary()

        layout.addStretch()
        self.setWidget(container)

    def _set_all(self, checked):
        for cb in self._checkboxes.values():
            cb.setChecked(checked)
        self._update_summary()

    def _update_summary(self):
        selected = []
        for key, comp, status, issue, action, _ in _SIM_PROBLEM_DEFS:
            if self._checkboxes[key].isChecked():
                selected.append(comp)
        if selected:
            self._summary.setText(f"已选 {len(selected)} 项问题：{', '.join(selected)}")
        else:
            self._summary.setText("未选择任何问题（修复界面将显示无问题）")

    def get_selected_problems(self):
        """返回选中的问题列表，每项为 (component, status, issue, action)。"""
        result = []
        for key, comp, status, issue, action, _ in _SIM_PROBLEM_DEFS:
            if self._checkboxes[key].isChecked():
                result.append((comp, status, issue, action))
        return result


class VisualConditionDialog(QDialog):
    """环境模拟主窗口：4:3 比例。

    非维护模式：两页（设备选择 + 环境细节）。
    维护模式：三页（设备选择 + 环境细节 + 自定义问题）。
    """

    def __init__(self, win_scale, us, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        # 分辨率适配与 real_installer 完全一致：窗口大小与字号都用同一套公式，
        # 忽略 demo_installer 传入的统一 scale（4K 下 =2.5，会把窗口/字撑得过大）
        _app = QApplication.instance()
        if _app is not None:
            win_scale, us = _ui_scales(_app)
        self._us = us
        self._win_scale = win_scale
        self._sim_info = None
        self._applied = False
        self.setWindowTitle("环境模拟 — 选择设备条件")

        # 4:3 窗口（win_scale 控制窗口大小，us 控制字体）
        _w, _h = int(640 * win_scale), int(480 * win_scale)

        layout = QVBoxLayout(self)
        m = max(int(12 * us), 10)
        layout.setContentsMargins(m, m, m, m)
        layout.setSpacing(max(int(6 * us), 5))

        # ===== 页面容器（QStackedWidget） =====
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        # ----- 第 1 页：设备条件选择 -----
        page1 = QWidget()
        p1_layout = QVBoxLayout(page1)
        p1_layout.setContentsMargins(0, 0, 0, 0)
        p1_layout.setSpacing(max(int(6 * us), 5))

        lbl = QLabel("选择模拟的设备条件：")
        f = lbl.font()
        f.setPointSize(max(int(9 * us), 9))
        f.setBold(True)
        lbl.setFont(f)
        p1_layout.addWidget(lbl)

        desc = QLabel("用于模拟不同软硬件环境下的安装流程。默认选中本机真实设备。")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: #888; font-size: {max(int(7 * us), 7)}pt;")
        p1_layout.addWidget(desc)

        # 空间选项（同时影响内存可用量与硬盘可用空间）
        mem_row = QHBoxLayout()
        mem_row.setSpacing(max(int(6 * us), 4))
        self.mem_lbl = QLabel("空间选项：")
        f = self.mem_lbl.font()
        f.setPointSize(max(int(8 * us), 8))
        self.mem_lbl.setFont(f)
        mem_row.addWidget(self.mem_lbl)

        self.cb_mem = QComboBox()
        self.cb_mem.addItems([
            "默认（内存 98.5%，硬盘 40~80%）",
            "充足（内存 90%，硬盘 60~90%）",
            "刚好（内存 50%，硬盘 11~20 GB）",
            "不足（内存 15%，硬盘 2~10 GB）",
        ])
        self.cb_mem.setMinimumWidth(int(280 * us))
        f = self.cb_mem.font()
        f.setPointSize(max(int(8 * us), 8))
        self.cb_mem.setFont(f)
        mem_row.addWidget(self.cb_mem)
        mem_row.addStretch()
        p1_layout.addLayout(mem_row)

        # 维护模式选项（勾选后进入第三页自定义模拟问题）
        self.cb_maintenance = QCheckBox("维护模式 — 模拟文件损坏/运行错误（用于测试修复流程）")
        f = self.cb_maintenance.font()
        f.setPointSize(max(int(8 * us), 8))
        self.cb_maintenance.setFont(f)
        self.cb_maintenance.setStyleSheet("border: none;")
        p1_layout.addWidget(self.cb_maintenance)

        # 配置列表
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"font-size: {max(int(7 * us), 7)}pt;")
        for cfg in _PRESETS:
            item = QListWidgetItem()
            widget = _ConfigItemWidget(cfg, us)
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.UserRole, cfg)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)
        # 选中项变化时，本机模式隐藏空间选项
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        p1_layout.addWidget(self.list_widget, 1)
        self.stack.addWidget(page1)

        # ----- 第 2 页：环境细节模拟 -----
        self.page2 = _EnvDetailPage(us)
        self.stack.addWidget(self.page2)

        # ----- 第 3 页：自定义模拟问题 -----
        self.page3 = _ProblemSelectPage(us)
        self.stack.addWidget(self.page3)

        # 默认显示第 1 页
        self.stack.setCurrentIndex(0)

        # 默认选中第一项（本机）
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

        # ===== 底部按钮 =====
        btn_row = QHBoxLayout()
        btn_row.setSpacing(max(int(8 * us), 6))

        # 上一步（仅第 2 页可见）
        self.btn_prev = QPushButton("< 上一步")
        self.btn_prev.setStyleSheet(
            f"QPushButton {{ border: 1px solid #ccc; border-radius: 4px; "
            f"padding: {max(int(6 * us), 5)}px {max(int(16 * us), 12)}px; "
            f"font-size: {max(int(8 * us), 8)}pt; }}"
            f"QPushButton:hover {{ background: #f0f0f0; }}")
        self.btn_prev.clicked.connect(self._on_prev)
        self.btn_prev.setVisible(False)
        btn_row.addWidget(self.btn_prev)

        btn_row.addStretch()

        # 下一步（仅第 1 页可见）
        self.btn_next = QPushButton("下一步 >")
        self.btn_next.setObjectName("btn_next")
        self.btn_next.setStyleSheet(
            f"QPushButton#btn_next {{ background: #1a73e8; color: white; "
            f"border: 1px solid #1a73e8; border-radius: 4px; "
            f"padding: {max(int(6 * us), 5)}px {max(int(16 * us), 12)}px; "
            f"font-size: {max(int(8 * us), 8)}pt; }}"
            f"QPushButton#btn_next:hover {{ background: #1557b0; }}")
        self.btn_next.clicked.connect(self._on_next)
        btn_row.addWidget(self.btn_next)

        # 应用模拟并继续（仅第 2 页可见）
        self.btn_apply = QPushButton("应用模拟并继续")
        self.btn_apply.setObjectName("btn_ok")
        self.btn_apply.setStyleSheet(
            f"QPushButton#btn_ok {{ background: #27ae60; color: white; "
            f"border: 1px solid #27ae60; border-radius: 4px; "
            f"padding: {max(int(6 * us), 5)}px {max(int(16 * us), 12)}px; "
            f"font-size: {max(int(8 * us), 8)}pt; }}"
            f"QPushButton#btn_ok:hover {{ background: #1e8449; }}")
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_apply.setVisible(False)
        btn_row.addWidget(self.btn_apply)

        layout.addLayout(btn_row)

        # setFixedSize 在布局完成后调用，确保 4:3
        self.setFixedSize(_w, _h)

    def _on_next(self):
        """第 1 页 → 第 2 页（或第 2 页 → 第 3 页）。"""
        cur = self.stack.currentIndex()
        if cur == 0:
            # 第 1 页 → 第 2 页：生成 sim_info 并更新第 2 页内容
            self._generate_sim_info()
            self.page2.update_content(self._sim_info)
            self.stack.setCurrentIndex(1)
            self.btn_prev.setVisible(True)
            # 维护模式：第 2 页显示「下一步」进入第 3 页
            # 非维护模式：第 2 页直接显示「应用模拟并继续」，跳过第 3 页
            if self.cb_maintenance.isChecked():
                self.btn_next.setVisible(True)
                self.btn_apply.setVisible(False)
            else:
                self.btn_next.setVisible(False)
                self.btn_apply.setVisible(True)
        elif cur == 1:
            # 第 2 页 → 第 3 页：自定义模拟问题（仅维护模式可达）
            self.stack.setCurrentIndex(2)
            self.btn_next.setVisible(False)
            self.btn_apply.setVisible(True)

    def _on_prev(self):
        """返回上一页（第 3 页 → 第 2 页，或第 2 页 → 第 1 页）。"""
        cur = self.stack.currentIndex()
        if cur == 2:
            # 第 3 页 → 第 2 页
            self.stack.setCurrentIndex(1)
            self.btn_next.setVisible(True)
            self.btn_apply.setVisible(False)
        elif cur == 1:
            # 第 2 页 → 第 1 页
            self.stack.setCurrentIndex(0)
            self.btn_prev.setVisible(False)
            self.btn_next.setVisible(True)
            self.btn_apply.setVisible(False)

    def _on_selection_changed(self, row):
        """选中项变化时，本机模式隐藏空间选项。"""
        is_real = True
        if 0 <= row < len(_PRESETS):
            cfg = _PRESETS[row]
            is_real = (cfg[9] == "本机")
        self.mem_lbl.setVisible(not is_real)
        self.cb_mem.setVisible(not is_real)

    def _generate_sim_info(self):
        """根据当前选择生成 sim_info（不关闭窗口）。"""
        row = self.list_widget.currentRow()
        if 0 <= row < len(_PRESETS):
            cfg = _PRESETS[row]
            allow = cfg[9]
            if allow == "本机":
                self._sim_info = None
            else:
                space_idx = self.cb_mem.currentIndex() if hasattr(self, "cb_mem") else 0
                space_scenario = ["default", "abundant", "tight", "scarce"][space_idx]
                self._sim_info = _config_to_json(cfg, space_scenario)

    def get_sim_info(self):
        """返回选择的模拟配置 dict。

        - 模拟设备模式：含硬件信息 + _sim_problems
        - 本机模式：含 _use_real_hardware=True + _sim_problems
        - 非维护模式：_sim_problems 为空列表（无模拟问题）
        - 维护模式：_sim_problems 为用户勾选的问题列表
        - 未应用（关闭窗口）：返回 None
        """
        return self._sim_info

    def _on_apply(self):
        """应用模拟并继续：保存 sim_info + _sim_problems 到配置文件。"""
        self._generate_sim_info()
        # 构造最终 sim_info
        if self._sim_info:
            # 模拟设备模式：sim_info 已含硬件信息
            sim_info = self._sim_info
        else:
            # 本机模式：标记使用真实硬件检测，但仍保留 _sim_problems
            sim_info = {"_use_real_hardware": True}
        # 维护模式：收集第三步选中的问题；非维护模式：空列表（无模拟问题）
        if self.cb_maintenance.isChecked():
            problems = self.page3.get_selected_problems()
        else:
            problems = []
        sim_info["_sim_problems"] = [
            {"component": c, "status": s, "issue": i, "action": a}
            for c, s, i, a in problems
        ]
        try:
            with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(sim_info, f, ensure_ascii=False)
        except Exception:
            pass
        # 更新返回值
        self._sim_info = sim_info
        self._applied = True
        self.accept()

    def closeEvent(self, event):
        """关闭窗口 = 取消，清除模拟配置。"""
        if not self._applied:
            self._sim_info = None
        super().closeEvent(event)


def main():
    from PyQt5.QtCore import Qt
    # 软件渲染（必须在 QApplication 创建前设置）：保证 agent 截图稳定可识别
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 9))
    win_scale, us = _ui_scales(app)
    dlg = VisualConditionDialog(win_scale, us)
    dlg.exec_()
    # 独立运行时写入配置文件供 demo_installer 读取
    sim_info = dlg.get_sim_info()
    if sim_info:
        try:
            with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(sim_info, f, ensure_ascii=False)
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
