"""我的世界旗帜逆向工具箱 稳固性测试程序

目的：自动化测试所有功能模块，发现潜在问题，验证软件稳定性。
运行：python test.pyw 或双击运行；python test.pyw --cli 跑命令行模式

测试覆盖：
  1. 依赖库检查（torch/torchvision/PyQt5/numpy/cv2/PIL/matplotlib/psutil）
  2. 项目模块导入（utils.* / models.* / ScreenshotDataset）
  3. 配置管理（SettingsManager 读写、迁移、回调、路径解析）
  4. 硬件检测（CPU/GPU/内存、Windows版本、缓存）
  5. 资源分配（compute_resource_allocation 各挡位）
  6. 模型架构（_ARCH_CONFIG、check_arch_available、权重文件磁盘检测、权重加载不崩溃）
  7. MBTL 文件读写（往返、边界、错误格式）
  8. 旗帜图像生成（load_icons、不同尺寸、16层满载）
  9. 模型创建与推理（ViT实例化、forward、save/load、predict）【慢】
 10. 错误处理（report_error、临时文件）
 11. 文件关联（图标资源完整性）
 12. 工作区布局（load/save/clear workspace）
 13. 硬件兼容性检测（GPU 类型/后端选择/NVIDIA·Intel·AMD 白名单·RDNA2/3 iGPU）
 14. Tab2 训练数据集（ScreenshotDataset 实例化、标签构造、图片加载）
 15. DirectML 子进程协议（dml_worker stdout JSON/argparse 参数）
 16. 文档与帮助系统（help.pyw 结构/章节锚点）

UI：Windows 11 风格，左侧分类导航 + 右侧测试列表 + 底部状态栏。
测试在后台线程运行，不阻塞 UI。支持运行全部/运行选中/停止/导出报告。
"""
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
# 优先用工作目录（real_installer 通过 setWorkingDirectory 设置为安装目录），
# 回退到 __file__ 目录（开发模式或 _MEIPASS）
_cwd = os.getcwd()
if (os.path.exists(os.path.join(_cwd, "install_components.json")) or
    os.path.exists(os.path.join(_cwd, "start.pyw")) or
    os.path.exists(os.path.join(_cwd, "bdor.pyw"))):
    _APP_DIR = _cwd
else:
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

import time
import json
import traceback
import tempfile
import io
from contextlib import contextmanager

# 在 PyQt5 之前 import torch，避免 PyQt5 的 DLL 冲突导致 c10.dll 加载失败
try:
    import torch  # noqa: F401
except Exception:
    pass

import PyQt5
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QLabel,
    QPushButton, QProgressBar, QStatusBar, QMessageBox,
    QAbstractItemView, QHeaderView, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSharedMemory
from PyQt5.QtGui import QFont, QColor, QBrush

# ===== 测试结果状态枚举 =====
PENDING = "pending"
RUNNING = "running"
PASS = "pass"
FAIL = "fail"
WARN = "warn"
SKIP = "skip"

STATUS_ICON = {
    PENDING: "○",
    RUNNING: "◐",
    PASS:    "✓",
    FAIL:    "✗",
    WARN:    "!",
    SKIP:    "—",
}

STATUS_COLOR = {
    PENDING: "#888888",
    RUNNING: "#1a73e8",
    PASS:    "#2e7d32",
    FAIL:    "#c62828",
    WARN:    "#ef6c00",
    SKIP:    "#9e9e9e",
}


# ===== 测试异常 =====
class TestFailure(Exception):
    """测试失败（断言失败）。"""
    pass


class TestWarning(Exception):
    """测试警告（非致命问题）。"""
    pass


# ===== 断言工具 =====
def check(cond, msg=""):
    if not cond:
        raise TestFailure(msg or "断言失败")


def check_eq(a, b, msg=""):
    if a != b:
        raise TestFailure(msg or f"期望 {b!r}，实际 {a!r}")


def check_in(item, container, msg=""):
    if item not in container:
        raise TestFailure(msg or f"{item!r} 不在容器中")


def warn_if(cond, msg):
    if cond:
        raise TestWarning(msg)


@contextmanager
def capture_stdout():
    """临时捕获 print 输出（torch 加载时的进度信息）。"""
    buf = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = buf
    sys.stderr = buf
    try:
        yield buf
    finally:
        sys.stdout = old_out
        sys.stderr = old_err


def _load_error_reporter():
    """动态加载 scripts/error_reporter.pyw 为模块（不执行 main）。"""
    import importlib.util
    reporter_path = os.path.join(
        _APP_DIR,
        "scripts", "error_reporter.pyw"
    )
    spec = importlib.util.spec_from_file_location("error_reporter", reporter_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gen_long_traceback(lines=300):
    """生成模拟真实 Python 超长 traceback 的文本（足够长以触发滚动条）。"""
    parts = ["Traceback (most recent call last):"]
    for i in range(lines // 3):
        parts.append(f'  File "trainer.pyw", line {100+i*5}, in train_epoch')
        parts.append(f'    loss = self._compute_loss(batch, epoch={i})')
        parts.append(f'  File "trainer.pyw", line {200+i*3}, in _compute_loss')
        parts.append(f'    outputs = self.model(images)  # forward pass')
        parts.append(f'  File "models/structures/vit_model.py", line {75+i*2}, in forward')
        parts.append(f'    features = self.vit(x)')
        parts.append(f'RuntimeError: CUDA out of memory. Tried to allocate {256+i*10}.00 MiB '
                     f'(GPU 0; {8+i%4}.00 GiB total capacity; {5+i%3}.20 GiB already allocated; '
                     f'{128+i*5} MiB free; {6+i%2}.30 GiB reserved in total by PyTorch)')
        parts.append("")
    parts.append("Exception ignored in: <bound method BannerTrainer.__del__ of <BannerTrainer object at 0x000002>>")
    parts.append("Traceback (most recent call last):")
    parts.append('  File "models/structures/vit_model.py", line 1, in <module>')
    parts.append("    import torch")
    parts.append("ModuleNotFoundError: No module named 'torch'")
    parts.append("")
    parts.append("--- End of error report ---")
    return "\n".join(parts)


def _run_error_reporter_subprocess(test_file, title, timeout=15, expect_export=True):
    """通过子进程启动 error_reporter.pyw（与正式报错流程一致），
    传入 --auto 自动导出日志，返回结果。

    返回: (success: bool, export_path: str or None, error: str or None, stderr: str)
    """
    import subprocess
    import tempfile
    reporter_path = os.path.join(
        _APP_DIR,
        "scripts", "error_reporter.pyw"
    )
    export_file = os.path.join(tempfile.gettempdir(), "testerror_export.txt")
    if os.path.exists(export_file):
        try:
            os.unlink(export_file)
        except Exception:
            pass
    proc = subprocess.Popen(
        [sys.executable, reporter_path, test_file, title, "--auto"],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    stderr = ""
    error = None
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return False, None, "子进程超时未退出", ""
    if expect_export:
        if os.path.exists(export_file):
            return True, export_file, None, ""
        return False, None, f"导出文件不存在 (exit={proc.returncode})", ""
    return proc.returncode == 0, None, None, ""


# ===== 单个测试项 =====
class TestItem:
    def __init__(self, name, func, slow=False, description=""):
        self.name = name
        self.func = func
        self.slow = slow
        self.description = description
        self.status = PENDING
        self.elapsed_ms = 0
        self.message = ""
        self.traceback = ""
        self.category = ""

    def run(self):
        self.status = RUNNING
        start = time.perf_counter()
        try:
            self.func()
            self.status = PASS
            self.message = "通过"
        except TestWarning as e:
            self.status = WARN
            self.message = str(e) or "警告"
            self.traceback = traceback.format_exc()
        except TestFailure as e:
            self.status = FAIL
            self.message = str(e) or "失败"
            self.traceback = traceback.format_exc()
        except Exception as e:
            self.status = FAIL
            self.message = f"{type(e).__name__}: {e}"
            self.traceback = traceback.format_exc()
        finally:
            self.elapsed_ms = int((time.perf_counter() - start) * 1000)


# ===== 测试集合注册（基于全局 pending 栈）=====
_TEST_CATEGORIES = []   # [(category_name, [TestItem, ...]), ...]
_pending_items = []     # 临时栈：@category 调用 func 期间，@item 注册到这里

# 安装目的（由 real_installer 修复功能通过 --purpose= 传入）
# "use" 模式（仅识别器）跳过训练相关测试分类
_PURPOSE = "train"
_USE_SKIP_CATEGORIES = {
    "5. 资源分配",
    "7. MBTL 文件 IO",
    "9. 模型创建与推理（慢）",
    "12. 工作区布局",
    "14. DirectML 子进程协议",
}
# use 模式（仅识别器）跳过的训练相关检测项（分类内有 use 需要的项，不能整个跳过）
_USE_SKIP_ITEMS = {
    "matplotlib",                 # 训练用 Loss 曲线绘制
    "ScreenshotDataset 类",        # 训练数据集
    "generate_random_banner",      # 训练数据随机生成
    "generate_random_banner 参数约束",  # 训练数据生成参数
    "pynvml (温度监控)",           # 训练 GPU 温度保护
    "utils.mbtl_utils",            # 导入器 MBTL 文件读写
    "utils.mbtlx_utils",           # 导入器/训练器 MBTLX 标记包读写
}


def _detect_install_form():
    """识别安装形态（json purpose + 磁盘文件结合，任一显示有训练器即按全量检测）。

    解决旧安装遗留问题：install_components.json 的 purpose 可能过时（如 json 记
    "use" 但磁盘上 trainer.pyw 已存在），仅看 json 会导致训练相关检测被误跳过、
    库与用途对应错位。这里以磁盘文件为准、json 作兜底：
      - 磁盘存在 trainer.pyw（或 json purpose 为 train）→ 含训练器，全量检测
      - 磁盘无 trainer.pyw 且 json purpose 为 use → 仅识别器，跳过训练相关项

    返回 dict：purpose / has_trainer / has_bdor / use_mode / form
    """
    has_trainer = os.path.isfile(os.path.join(_APP_DIR, "trainer.pyw"))
    has_bdor = os.path.isfile(os.path.join(_APP_DIR, "bdor.pyw"))
    purpose = _PURPOSE
    use_mode = (purpose == "use") and not has_trainer
    if has_trainer:
        form = "训练+识别器" if has_bdor else "仅训练（含训练器）"
    elif purpose == "use":
        form = "仅识别器"
    else:
        form = "训练+识别器（按配置）"
    return {"purpose": purpose, "has_trainer": has_trainer, "has_bdor": has_bdor,
            "use_mode": use_mode, "form": form}


def _is_use_mode():
    """是否按「仅识别器」模式检测（跳过训练相关检测项）。"""
    return _detect_install_form()["use_mode"]


def category(name):
    """分类装饰器：调用被装饰函数，收集其体内 @item 注册的测试项。"""
    def deco(func):
        global _pending_items
        _pending_items = []
        func()  # 触发函数体执行，期间 @item 会注册到 _pending_items
        items = list(_pending_items)
        _pending_items = []
        _TEST_CATEGORIES.append((name, items))
        return func
    return deco


def item(name, slow=False, description=""):
    """测试项装饰器：在函数定义时立即注册到 pending 栈（函数本身不会被调用）。"""
    def deco(func):
        ti = TestItem(name, func, slow=slow, description=description)
        _pending_items.append(ti)
        return func
    return deco


# ========================================================================
# 测试用例定义
# ========================================================================

# ---------- 路径工具 ----------
def _app_dir():
    """返回应用根目录（安装目录或开发目录）。"""
    return _APP_DIR


# ---------- 已安装组件检测（用于按安装情况调整检测项） ----------
_COMPONENTS_FILE = os.path.join(_app_dir(), "install_components.json")


def _installed_components():
    """读取已安装组件（库键名集合）。返回空集合表示无清单（开发模式，全量检测）。

    修复旧安装遗留问题：老版 install_components.json 只有 components 字段（记录的是
    程序文件名 + archs，不含库键名），或字段不全/过时，导致库与用途对应错位、
    已装的库被误判"未安装"而跳过/误报。这里三重合并：
      1) json 的 libraries 字段（新格式，库键名）
      2) json 的 components 字段（旧格式，兼容）
      3) 磁盘 site-packages 真实检测（最可靠：Lib/site-packages + dml_env/Lib/site-packages）
    """
    comps = set()
    if os.path.exists(_COMPONENTS_FILE):
        try:
            with open(_COMPONENTS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            libs = data.get("libraries")
            if libs is not None:
                comps.update(libs)
            comps.update(data.get("components", []))
        except Exception:
            pass
    # 磁盘真实检测：主环境 Lib/site-packages + dml_env（directml 的 torch 在 dml_env 里）
    for _sp in (_VENDOR_PKGS, _dml_sp):
        if not os.path.isdir(_sp):
            continue
        try:
            _sub = {d.lower() for d in os.listdir(_sp)}
        except Exception:
            continue
        if "torch" in _sub:
            comps.add("torch")
        if "torchvision" in _sub:
            comps.add("torchvision")
        if "pyqt5" in _sub:
            comps.add("pyqt5")
        if "numpy" in _sub:
            comps.add("numpy_cv2")
        if "cv2" in _sub or "opencv_python" in _sub or "opencv_python_headless" in _sub:
            comps.add("numpy_cv2")
        if "pil" in _sub or "pillow" in _sub:
            comps.add("pillow")
        if "matplotlib" in _sub:
            comps.add("matplotlib")
        if "psutil" in _sub:
            comps.add("psutil")
        if "pynvml" in _sub:
            comps.add("pynvml")
    return comps if comps else None


# 组件 key → 关联的测试项名称（这些测试项依赖对应库）
_COMPONENT_TESTS = {
    "torch":     {"torch", "torch.cuda 可用性", "torchvision"},
    "pyqt5":     {"PyQt5"},
    "numpy_cv2": {"numpy", "opencv-python (cv2)"},
    "pillow":    {"Pillow (PIL)"},
    "matplotlib": {"matplotlib"},
    "psutil":    {"psutil"},
    "pynvml":    {"pynvml (温度监控)"},
}


def _filter_by_components(items):
    """根据已安装组件过滤测试项：未安装组件的关联测试标记为 SKIP。"""
    comps = _installed_components()
    if comps is None:
        return items  # 无清单，全量检测
    for it in items:
        for comp_key, test_names in _COMPONENT_TESTS.items():
            if it.name in test_names and comp_key not in comps:
                it.status = SKIP
                it.message = f"组件 {comp_key} 未安装，跳过"
                break
    return items


def _main_has_torch():
    """主进程（UI 用 3.13）能否直接 import torch。directml 安装时 torch 在 dml_env，
    主进程无 torch 属正常，识别/训练均通过 dml_env 子进程执行。"""
    try:
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def _dml_run(code):
    """用 dml_env python 执行 code 验证模块可用（主进程无 torch 时的回退）。

    返回 (ok: bool|None, output: str)：None 表示 dml_env 不存在/执行异常。
    dml_env 的 python 带 python310._pth 隔离配置，cwd 不在 sys.path，
    需显式把 _APP_DIR 注入 sys.path 才能 import models/utils 等应用模块。
    """
    import subprocess as _sp
    dml_py = os.path.join(_APP_DIR, "dml_env", "python.exe")
    if not os.path.isfile(dml_py):
        return None, "dml_env\\python.exe 不存在"
    try:
        boot = "import sys; sys.path.insert(0, %r)\n" % _APP_DIR
        r = _sp.run([dml_py, "-c", boot + code], capture_output=True, text=True,
                    encoding="utf-8", cwd=_APP_DIR, timeout=120,
                    creationflags=_sp.CREATE_NO_WINDOW)
        return r.returncode == 0, (r.stderr or r.stdout or "").strip()
    except Exception as e:
        return None, str(e)


def _pkg_in_env(pkg):
    """验证指定包（torch/torchvision）在正确环境中可用（避免误报）。

    directml 安装的 torch/torchvision 装在 dml_env（Python 3.10），
    主环境（UI 用的 3.13）无法直接加载；若只查当前环境会误报"未安装"。
    当前环境能 import 时直接成功，否则试 dml_env 的 python。
    """
    try:
        if pkg == "torch":
            import torch  # noqa: F401
        else:
            import torchvision  # noqa: F401
        return True
    except Exception:
        pass
    import subprocess as _sp
    dml_py = os.path.join(_APP_DIR, "dml_env", "python.exe")
    if os.path.isfile(dml_py):
        try:
            r = _sp.run([dml_py, "-c", f"import {pkg}"],
                        capture_output=True, timeout=60)
            return r.returncode == 0
        except Exception:
            pass
    return False


# ---------- 1. 依赖库检查 ----------
@category("1. 依赖库检查")
def _cat_deps():

    @item("Python 版本", description="检查 Python >= 3.10.11（自适应最低门槛，主代码以 3.13.14 为基准）")
    def _t():
        v = sys.version_info
        check(v >= (3, 10, 11), f"Python {v.major}.{v.minor}.{v.micro} 过低，需要 3.10.11+")

    @item("torch", description="深度学习框架，模型训练核心依赖（directml 安装自动查 dml_env）")
    def _t():
        check(_pkg_in_env("torch"), "torch 未安装（已检查当前环境与 dml_env）")

    @item("torch.cuda 可用性", description="检测 CUDA，影响训练速度（DirectML 模式无 CUDA 属正常）")
    def _t():
        if not _pkg_in_env("torch"):
            raise TestWarning("torch 未安装，跳过 CUDA 检测")
        try:
            import torch
        except Exception:
            raise TestWarning("DirectML 模式（torch 在 dml_env），无 CUDA 属正常")
        if not torch.cuda.is_available():
            # 区分：有 NVIDIA 卡但未启用 CUDA（没装 CUDA 版 torch / 驱动不匹配）
            gpu_vendor = "unknown"
            try:
                from utils.device_backend import detect_gpu_type
                gpu_vendor = detect_gpu_type().get("vendor", "unknown")
            except Exception:
                pass
            if gpu_vendor == "nvidia":
                raise TestWarning("检测到 NVIDIA 显卡，但当前 torch 未启用 CUDA（未安装 CUDA 版 torch 或驱动不匹配），将使用 CPU 模式")
            raise TestWarning("未检测到 NVIDIA 显卡，将使用 CPU 模式")

    @item("torchvision", description="视觉模型库，提供 ViT 预训练权重（directml 安装自动查 dml_env）")
    def _t():
        check(_pkg_in_env("torchvision"), "torchvision 未安装（已检查当前环境与 dml_env）")

    @item("PyQt5", description="GUI 框架，所有窗口界面基础")
    def _t():
        check(PyQt5.__file__, "PyQt5 未安装")

    @item("numpy", description="数值计算库，图像数组处理")
    def _t():
        import numpy as np
        check(np.__version__, "numpy 未安装")

    @item("opencv-python (cv2)", description="图像处理库，图标加载与变换")
    def _t():
        import cv2
        check(cv2.__version__, "cv2 未安装")

    @item("Pillow (PIL)", description="图像 IO 库，PNG 读写")
    def _t():
        from PIL import Image
        check(Image.__version__, "PIL 未安装")

    @item("matplotlib", description="图表库，Loss 曲线绘制")
    def _t():
        import matplotlib
        check(matplotlib.__version__, "matplotlib 未安装")

    @item("psutil", description="系统监控库，内存/CPU 实时检测")
    def _t():
        try:
            import psutil
            check(psutil.__version__, "psutil 未安装")
        except ImportError:
            raise TestWarning("psutil 未安装，硬件检测将回退到 ctypes")

    @item("CPU 型号检测 (CIM)", description="通过 PowerShell CIM 获取 CPU 名称")
    def _t():
        from utils.settings_manager import _get_cpu_name
        name = _get_cpu_name()
        check(name and name != "未知CPU", f"CPU 名称: {name}")

    @item("pynvml (温度监控)", description="NVIDIA 管理库，GPU 温度监控")
    def _t():
        try:
            import pynvml
        except ImportError:
            raise TestWarning("pynvml 未安装，训练温度保护将无法生效")


# ---------- 2. 项目模块导入 ----------
@category("2. 项目模块导入")
def _cat_modules():

    @item("utils.settings_manager", description="配置管理与硬件检测核心")
    def _t():
        from utils import settings_manager
        check(hasattr(settings_manager, "SettingsManager"))

    @item("utils.settings_dialog", description="设置对话框 GUI")
    def _t():
        from utils import settings_dialog
        check(hasattr(settings_dialog, "SettingsDialog"))

    @item("utils.banner_utils", description="旗帜图像生成与图标管理")
    def _t():
        from utils import banner_utils
        check(hasattr(banner_utils, "generate_banner_image"))

    @item("utils.mbtl_utils", description="MBTL 文件读写")
    def _t():
        from utils import mbtl_utils
        check(hasattr(mbtl_utils, "read_mbtl") and hasattr(mbtl_utils, "write_mbtl"))

    @item("utils.mbtlx_utils", description="MBTLX 标记包读写")
    def _t():
        from utils import mbtlx_utils
        check(hasattr(mbtlx_utils, "export_mbtlx") and hasattr(mbtlx_utils, "import_mbtlx")
              and hasattr(mbtlx_utils, "is_mbtlx"))

    @item("models.structures.vit_model", description="ViT 模型与训练器")
    def _t():
        if not _main_has_torch():
            # directml 安装：torch 在 dml_env，主进程无法导入属正常，回退子进程验证
            ok, out = _dml_run(
                "from models.structures import vit_model\n"
                "assert hasattr(vit_model, 'ViT') and hasattr(vit_model, 'BannerTrainer')")
            if ok is None:
                check(False, f"主进程无 torch 且 {out}")
            else:
                check(ok, f"dml_env 导入失败: {out}")
            return
        from models.structures import vit_model
        check(hasattr(vit_model, "ViT") and hasattr(vit_model, "BannerTrainer"))

    @item("models.structures.__init__", description="模型结构包初始化")
    def _t():
        from models import structures
        check(structures is not None)

    @item("utils.device_backend", description="计算后端抽象层（CUDA/DirectML/CPU）")
    def _t():
        from utils import device_backend
        check(hasattr(device_backend, "get_compute_backend"))
        check(hasattr(device_backend, "get_device"))
        check(hasattr(device_backend, "detect_gpu_type"))

    @item("ScreenshotDataset 类", description="Tab2 截图训练数据集")
    def _t():
        from models.structures.vit_model import ScreenshotDataset
        check(ScreenshotDataset is not None)

    @item("scripts.error_reporter 可达性", description="独立报错程序文件存在性")
    def _t():
        reporter = os.path.join(
            _APP_DIR,
            "scripts", "error_reporter.pyw"
        )
        check(os.path.exists(reporter), f"找不到 {reporter}")

    @item("scripts.exit 可达性", description="退出程序文件存在性")
    def _t():
        exit_p = os.path.join(
            _APP_DIR,
            "scripts", "exit.pyw"
        )
        check(os.path.exists(exit_p), f"找不到 {exit_p}")


# ---------- 3. 配置管理 ----------
@category("3. 配置管理")
def _cat_config():

    @item("SettingsManager 单例", description="验证全局唯一实例")
    def _t():
        from utils.settings_manager import SettingsManager
        a = SettingsManager()
        b = SettingsManager()
        check(a is b, "SettingsManager 不是单例")

    @item("默认配置完整性", description="检查所有必需配置键存在")
    def _t():
        from utils.settings_manager import SettingsManager
        sm = SettingsManager()
        defaults = sm._default_settings()
        required = ["theme", "auto_layout", "snap_enabled", "snap_threshold",
                    "train_mode", "model_arch", "gpu_memory", "sys_memory",
                    "auto_resource_alloc", "perf_level", "gpu_temp_protection",
                    "import_min_size_kb", "import_max_size_mb",
                    "auto_save_trainer_path", "manual_save_trainer_path",
                    "auto_save_loader_path", "manual_save_loader_path",
                    "importer_save_formats", "importer_auto_save_formats"]
        for k in required:
            check_in(k, defaults, f"默认配置缺少键: {k}")

    @item("get/set/get_all/set_all", description="读写接口基本功能")
    def _t():
        from utils.settings_manager import SettingsManager
        sm = SettingsManager()
        old = sm.get("theme")
        new_val = "dark" if old != "dark" else "light"
        sm.set("theme", new_val)
        check_eq(sm.get("theme"), new_val)
        sm.set("theme", old)  # 恢复
        all_data = sm.get_all()
        check(isinstance(all_data, dict) and "theme" in all_data)

    @item("save + reload 一致性", description="持久化后重新加载值不变")
    def _t():
        from utils.settings_manager import SettingsManager
        sm = SettingsManager()
        old_val = sm.get("log_level")
        sm.set("log_level", "debug")
        sm.save()
        sm.reload()
        check_eq(sm.get("log_level"), "debug")
        # 恢复
        sm.set("log_level", old_val)
        sm.save()
        sm.reload()

    @item("on_change 回调机制", description="配置变更时回调触发")
    def _t():
        from utils.settings_manager import SettingsManager
        sm = SettingsManager()
        triggered = []
        sm.on_change("snap_threshold", lambda v: triggered.append(v))
        old = sm.get("snap_threshold")
        sm.set("snap_threshold", old + 1)
        check(len(triggered) == 1, f"回调未触发，触发次数={len(triggered)}")
        check_eq(triggered[0], old + 1)
        sm.set("snap_threshold", old)  # 恢复

    @item("resolve_app_path 路径解析", description="相对路径转绝对路径")
    def _t():
        from utils.settings_manager import resolve_app_path
        app_dir = _APP_DIR
        check_eq(resolve_app_path("default"), app_dir)
        check_eq(resolve_app_path(""), app_dir)
        check_eq(resolve_app_path(None), app_dir)
        check_eq(resolve_app_path("config"), os.path.join(app_dir, "config"))
        abs_p = r"C:\some\abs\path"
        check_eq(resolve_app_path(abs_p), abs_p)

    @item("配置文件路径", description="config/config.json 路径正确")
    def _t():
        from utils.settings_manager import SettingsManager
        sm = SettingsManager()
        p = sm.config_path
        check(p.endswith(os.path.join("config", "config.json")), f"路径异常: {p}")
        check(os.path.exists(os.path.dirname(p)), "config 目录不存在")

    @item("旧配置迁移（仿真）", description="旧配置文件列表可识别")
    def _t():
        from utils.settings_manager import SettingsManager
        sm = SettingsManager()
        legacy = sm._legacy_config_files()
        check(isinstance(legacy, list) and len(legacy) >= 3,
              f"legacy 文件列表异常: {legacy}")


# ---------- 4. 硬件检测 ----------
@category("4. 硬件检测")
def _cat_hw():

    @item("_get_physical_memory_gb", description="内存标称/识别/虚拟三项")
    def _t():
        from utils.settings_manager import _get_physical_memory_gb
        nominal, recognized, virt = _get_physical_memory_gb()
        check(nominal >= 1, f"内存标称异常: {nominal}")
        check(recognized >= 1, f"内存识别异常: {recognized}")
        check(virt >= 1, f"虚拟内存异常: {virt}")
        warn_if(nominal < 8, f"系统内存较低: {nominal}GB")

    @item("_get_cpu_name", description="CPU 型号名称获取")
    def _t():
        from utils.settings_manager import _get_cpu_name
        name = _get_cpu_name()
        check(name and len(name) > 0, "CPU 名称为空")
        warn_if(name == "未知CPU", "CPU 名称回退到默认值")

    @item("detect_hardware (skip_gpu=True)")
    def _t():
        from utils.settings_manager import detect_hardware
        info = detect_hardware(skip_gpu=True)
        required = {"cpu_name", "cpu_cores", "mem_nominal_gb",
                    "mem_recognized_gb", "mem_available_gb",
                    "virtual_total_gb", "os_version", "os_build"}
        missing = required - set(info.keys())
        check(not missing, f"缺少字段: {missing}")
        check(info["cpu_cores"] >= 1, "CPU 核心数异常")
        check(info["mem_nominal_gb"] >= 1, "内存异常")

    @item("detect_hardware (含 GPU)", description="完整硬件检测含 GPU")
    def _t():
        from utils.settings_manager import detect_hardware
        info = detect_hardware(skip_gpu=False)
        check("gpu_name" in info and "gpu_total_gb" in info)
        if info["gpu_name"] == "未检测到":
            raise TestWarning("未检测到 GPU")
        check(info["gpu_total_gb"] >= 1, f"显存异常: {info['gpu_total_gb']}")

    @item("get_hardware_cache 缓存命中", description="缓存结果可重复读取")
    def _t():
        from utils.settings_manager import get_hardware_cache
        info = get_hardware_cache()
        check(isinstance(info, dict) and "cpu_name" in info)

    @item("save/load_hardware_cache 往返", description="硬件缓存持久化往返")
    def _t():
        from utils.settings_manager import (save_hardware_cache, load_hardware_cache,
                                            detect_hardware)
        info = detect_hardware(skip_gpu=True)
        save_hardware_cache(info)
        loaded = load_hardware_cache()
        check(loaded is not None, "缓存读取失败")
        check_eq(loaded.get("cpu_name"), info["cpu_name"])

    @item("get_windows_version", description="Windows 版本号与 build")
    def _t():
        from utils.settings_manager import get_windows_version
        v, b = get_windows_version()
        check(v and len(v) > 0, "版本字符串为空")
        check(b >= 0, "build 号异常")
        warn_if(b < 10240, f"Windows 版本较旧: {v}")

    @item("grade_gpu_memory 各挡位", description="显存分级 2/4/8/16/32")
    def _t():
        from utils.settings_manager import grade_gpu_memory
        check_eq(grade_gpu_memory(0), 2)
        check_eq(grade_gpu_memory(4), 2)
        check_eq(grade_gpu_memory(8), 4)
        check_eq(grade_gpu_memory(12), 8)
        check_eq(grade_gpu_memory(24), 16)
        check_eq(grade_gpu_memory(32), 32)

    @item("grade_system_memory 各挡位", description="内存分级 4/8/16/32")
    def _t():
        from utils.settings_manager import grade_system_memory
        check_eq(grade_system_memory(4), 4)
        check_eq(grade_system_memory(8), 4)
        check_eq(grade_system_memory(16), 8)
        check_eq(grade_system_memory(32), 16)
        check_eq(grade_system_memory(64), 32)

    @item("get_gpu_memory_usage", description="GPU 显存实时占用率")
    def _t():
        from utils.settings_manager import get_gpu_memory_usage
        total, free, pct = get_gpu_memory_usage()
        check(total >= 0 and free >= 0 and 0 <= pct <= 100,
              f"显存使用率异常: total={total} free={free} pct={pct}")
        if total == 0:
            raise TestWarning("无 NVIDIA GPU 或 nvidia-smi 不可用")


# ---------- 5. 资源分配 ----------
@category("5. 资源分配")
def _cat_resource():

    @item("compute_resource_allocation balanced", description="均衡模式资源分配")
    def _t():
        from utils.settings_manager import compute_resource_allocation
        r = compute_resource_allocation(8, 16, model_arch="vit_b_16",
                                        mixed_precision=True, level="balanced")
        for k in ["gpu_fraction", "batch_size", "num_workers",
                  "gpu_reserved_gb", "usable_gpu_gb", "usable_sys_gb",
                  "cpu_usage_pct", "mem_usage_pct"]:
            check_in(k, r, f"缺少字段 {k}")
        check(0 <= r["gpu_fraction"] <= 0.85, f"gpu_fraction 异常: {r['gpu_fraction']}")
        check(r["batch_size"] >= 1, f"batch_size 异常: {r['batch_size']}")
        check(r["num_workers"] >= 1, f"num_workers 异常: {r['num_workers']}")

    @item("compute_resource_allocation light/extreme", description="轻量/极限模式")
    def _t():
        from utils.settings_manager import compute_resource_allocation
        for lvl in ["light", "extreme"]:
            r = compute_resource_allocation(8, 16, level=lvl)
            check(r["batch_size"] >= 1, f"{lvl} batch_size={r['batch_size']}")

    @item("无 GPU 情况 (gpu_total_gb=0)", description="无 GPU 时降级为 CPU")
    def _t():
        from utils.settings_manager import compute_resource_allocation
        r = compute_resource_allocation(0, 16)
        check_eq(r["gpu_fraction"], 0.0)
        check_eq(r["gpu_reserved_gb"], 0.0)
        check_eq(r["usable_gpu_gb"], 0.0)
        check(r["batch_size"] >= 1)

    @item("不同模型架构", description="各架构资源分配合理")
    def _t():
        from utils.settings_manager import compute_resource_allocation
        for arch in ["vit_b_16", "vit_l_16", "deit_b_16", "deit_s_16", "deit_t_16"]:
            r = compute_resource_allocation(8, 16, model_arch=arch)
            check(r["batch_size"] >= 1, f"{arch} batch_size={r['batch_size']}")

    @item("mixed_precision 切换", description="FP16 比 FP32 批量更大")
    def _t():
        from utils.settings_manager import compute_resource_allocation
        r_fp16 = compute_resource_allocation(8, 16, mixed_precision=True)
        r_fp32 = compute_resource_allocation(8, 16, mixed_precision=False)
        check(r_fp32["batch_size"] <= r_fp16["batch_size"],
              f"fp32 batch_size={r_fp32['batch_size']} > fp16={r_fp16['batch_size']}")


# ---------- 6. 模型架构 ----------
@category("6. 模型架构")
def _cat_arch():

    @item("_ARCH_CONFIG 完整性")
    def _t():
        if not _main_has_torch():
            ok, out = _dml_run(
                "from models.structures.vit_model import ViT\n"
                "required = ['vit_b_16', 'vit_l_16', 'vit_b_32', 'vit_l_32',\n"
                "            'vit_h_14', 'deit_b_16', 'deit_s_16', 'deit_t_16']\n"
                "for a in required:\n"
                "    assert a in ViT._ARCH_CONFIG, f'缺少架构 {a}'\n"
                "    assert 'type' in ViT._ARCH_CONFIG[a]\n"
                "    assert 'hidden_dim' in ViT._ARCH_CONFIG[a]\n"
                "    assert 'is_deit' in ViT._ARCH_CONFIG[a]")
            if ok is None:
                check(False, f"主进程无 torch 且 {out}")
            else:
                check(ok, f"dml_env 检查失败: {out}")
            return
        from models.structures.vit_model import ViT
        required_archs = ["vit_b_16", "vit_l_16", "vit_b_32", "vit_l_32",
                          "vit_h_14", "deit_b_16", "deit_s_16", "deit_t_16"]
        for a in required_archs:
            check_in(a, ViT._ARCH_CONFIG, f"缺少架构 {a}")
            cfg = ViT._ARCH_CONFIG[a]
            check_in("type", cfg)
            check_in("hidden_dim", cfg)
            check_in("is_deit", cfg)

    @item("check_arch_available 各架构", description="架构可用性检测返回元组")
    def _t():
        from utils.settings_manager import check_arch_available
        for a in ["vit_b_16", "vit_l_16", "vit_b_32", "deit_b_16",
                  "deit_s_16", "deit_t_16"]:
            # 实际返回 (available: bool, reason: str)
            result = check_arch_available(a)
            check(isinstance(result, tuple) and len(result) == 2,
                  f"{a} 返回类型异常: {type(result)}")
            check(isinstance(result[0], bool), f"{a} available 非 bool: {result[0]}")
            check(isinstance(result[1], str), f"{a} reason 非 str: {result[1]}")

    @item("load_arch_cache 函数可调用", description="架构缓存读取")
    def _t():
        from utils.settings_manager import load_arch_cache, build_arch_cache
        result = load_arch_cache()
        check(result is None or isinstance(result, dict))

    @item("ARCH_DISPLAY 字典", description="架构显示名映射表")
    def _t():
        try:
            from utils.settings_manager import ARCH_DISPLAY
            check(isinstance(ARCH_DISPLAY, dict) and len(ARCH_DISPLAY) > 0)
        except ImportError:
            raise TestWarning("未定义 ARCH_DISPLAY")

    @item("models/structures 权重文件检测", description="磁盘 .pth 存在性与完整度校验（按已装架构 + 预期大小 85% 阈值）")
    def _t():
        _structures_dir = os.path.join(_APP_DIR, "models", "structures")
        # 与安装器 _MODEL_ARCHS 的 pth_dl_gb 保持一致（GB）
        _expected_gb = {
            "vit_b_16": 0.34, "vit_l_16": 1.20, "vit_h_14": 2.50,
            "deit_b_16": 0.33, "deit_s_16": 0.09, "deit_t_16": 0.02,
        }
        # 已装架构：install_components.json 的 models 字段 + 磁盘实际存在的 .pth（并集，兼容旧安装）
        _installed = set()
        try:
            with open(_COMPONENTS_FILE, encoding="utf-8") as _f:
                _cfg = json.load(_f)
            _installed.update(_cfg.get("models", []) or [])
        except Exception:
            pass
        if os.path.isdir(_structures_dir):
            for _fname in os.listdir(_structures_dir):
                _stem = _fname[:-4] if _fname.endswith(".pth") else ""
                if _stem in _expected_gb:
                    _installed.add(_stem)
        # 无任何已装架构：提示而非失败（可从维护模式补下，或从零训练）
        if not _installed:
            raise TestWarning("未安装任何模型权重（可从安装器维护模式下载，或将从头训练）")
        _bad = []
        for _arch in sorted(_installed):
            _p = os.path.join(_structures_dir, f"{_arch}.pth")
            if not os.path.exists(_p):
                _bad.append(f"{_arch}:文件缺失")
                continue
            _size = os.path.getsize(_p)
            _expect = int(_expected_gb[_arch] * 1024 * 1024 * 1024)
            if _size <= 1024:
                _bad.append(f"{_arch}:文件为空/残缺（{_size}B）")
            elif _size < int(_expect * 0.85):
                _bad.append(f"{_arch}:大小不足（实际 {_size/1048576:.0f}MB / 预期 {_expect/1048576:.0f}MB）")
        check(not _bad, "权重完整度异常：\n" + "\n".join(_bad))

    @item("ViT 权重加载不崩溃", slow=True, description="strict=False + weights_only=False 生效")
    def _t():
        import torch
        from models.structures.vit_model import ViT
        with capture_stdout():
            model = ViT(model_arch="vit_b_16")
        # 验证模型能正常创建且不因权重缺失崩溃
        check(hasattr(model, "vit"), "ViT 模型未创建")

    @item("DeiT 独立权重逻辑", slow=True, description="DeiT 使用独立权重，不回退 ViT")
    def _t():
        from models.structures.vit_model import ViT
        with capture_stdout():
            model = ViT(model_arch="deit_b_16")
        check(model.is_deit is True, "DeiT 标志未设置")


# ---------- 7. MBTL 文件 IO ----------
@category("7. MBTL 文件 IO")
def _cat_mbtl():

    @item("write/read 往返（单层）", description="单层旗帜数据读写一致")
    def _t():
        from utils.mbtl_utils import write_mbtl, read_mbtl
        banners = [[1, 5, 2]]
        with tempfile.NamedTemporaryFile(suffix=".mbtl", delete=False) as f:
            path = f.name
        try:
            write_mbtl(path, banners)
            loaded = read_mbtl(path)
            check_eq(loaded, banners, f"往返不一致: {loaded} vs {banners}")
        finally:
            os.unlink(path)

    @item("write/read 往返（16层满载）", description="16 层满载数据读写一致")
    def _t():
        from utils.mbtl_utils import write_mbtl, read_mbtl
        flat = [0]
        for i in range(16):
            flat.extend([i % 42 + 1, i % 17])
        banners = [flat]
        with tempfile.NamedTemporaryFile(suffix=".mbtl", delete=False) as f:
            path = f.name
        try:
            write_mbtl(path, banners)
            loaded = read_mbtl(path)
            check_eq(loaded, banners)
        finally:
            os.unlink(path)

    @item("多 banner 读写", description="多条旗帜记录读写")
    def _t():
        from utils.mbtl_utils import write_mbtl, read_mbtl
        banners = [[1, 5, 2], [3, 10, 7, 20, 15], [0]]
        with tempfile.NamedTemporaryFile(suffix=".mbtl", delete=False) as f:
            path = f.name
        try:
            write_mbtl(path, banners)
            loaded = read_mbtl(path)
            check_eq(loaded, banners)
        finally:
            os.unlink(path)

    @item("空 banner 列表", description="空列表读写不报错")
    def _t():
        from utils.mbtl_utils import write_mbtl, read_mbtl
        with tempfile.NamedTemporaryFile(suffix=".mbtl", delete=False) as f:
            path = f.name
        try:
            write_mbtl(path, [])
            loaded = read_mbtl(path)
            check_eq(loaded, [])
        finally:
            os.unlink(path)

    @item("错误魔数识别", description="非法文件头抛出 ValueError")
    def _t():
        from utils.mbtl_utils import read_mbtl
        with tempfile.NamedTemporaryFile(suffix=".mbtl", delete=False) as f:
            f.write(b"XXXX" + b"\x00\x01\x00\x00\x00\x00")
            path = f.name
        try:
            try:
                read_mbtl(path)
                raise TestFailure("未抛出 ValueError")
            except ValueError as e:
                check("MBTL" in str(e) or "魔数" in str(e))
        finally:
            os.unlink(path)

    @item("pattern_type=0 过滤", description="无图案层读取时过滤")
    def _t():
        from utils.mbtl_utils import write_mbtl, read_mbtl
        banners = [[1, 0, 5, 10, 7]]  # (0,5) 应被过滤
        with tempfile.NamedTemporaryFile(suffix=".mbtl", delete=False) as f:
            path = f.name
        try:
            write_mbtl(path, banners)
            loaded = read_mbtl(path)
            check_eq(loaded, [[1, 10, 7]])
        finally:
            os.unlink(path)

    @item("load_banners_from_file 别名", description="别名函数与 read_mbtl 一致")
    def _t():
        from utils.mbtl_utils import write_mbtl, load_banners_from_file
        banners = [[1, 5, 2]]
        with tempfile.NamedTemporaryFile(suffix=".mbtl", delete=False) as f:
            path = f.name
        try:
            write_mbtl(path, banners)
            loaded = load_banners_from_file(path)
            check_eq(loaded, banners)
        finally:
            os.unlink(path)

    @item("MBTL_MAGIC / VERSION 常量", description="魔数 MBTL 与版本号")
    def _t():
        from utils.mbtl_utils import MBTL_MAGIC, MBTL_VERSION
        check_eq(MBTL_MAGIC, b"MBTL")
        check(MBTL_VERSION >= 1)

    @item("mbtlx 导出/导入往返（单条）", description="mbtlx_utils.export_mbtlx + import_mbtlx 单条往返")
    def _t():
        import tempfile, shutil
        from utils.banner_utils import generate_banner_image
        from PIL import Image
        from utils.mbtlx_utils import export_mbtlx, import_mbtlx, is_mbtlx, cleanup
        tmp_dir = tempfile.mkdtemp()
        try:
            img_path = os.path.join(tmp_dir, "test_banner.png")
            img = generate_banner_image([1, 10, 7], size=(200, 400))
            Image.fromarray(img).save(img_path)
            mbtlx_path = os.path.join(tmp_dir, "test.mbtlx")
            banner_data = [1, 10, 7]
            n = export_mbtlx(mbtlx_path, [(img_path, banner_data)])
            check_eq(n, 1, "导出条数应为 1")
            check(is_mbtlx(mbtlx_path), "ZIP 格式应被识别")
            result, extract_dir = import_mbtlx(mbtlx_path)
            check_eq(len(result), 1, "导入条数应为 1")
            read_img, read_data = result[0]
            check_eq(list(read_data), banner_data, "banner_data 往返不一致")
            check(os.path.exists(read_img), "解压图片应存在")
            cleanup(extract_dir)
            check(not os.path.exists(extract_dir), "解压目录应已清理")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @item("mbtlx 多条标记往返", description="多条 export/import 一致")
    def _t():
        import tempfile, shutil
        from utils.banner_utils import generate_banner_image
        from PIL import Image
        from utils.mbtlx_utils import export_mbtlx, import_mbtlx, cleanup
        tmp_dir = tempfile.mkdtemp()
        try:
            banners_list = [[1, 10, 7], [2, 20, 5], [3, 15, 8, 25, 2]]
            marks = []
            for i, bd in enumerate(banners_list):
                img_path = os.path.join(tmp_dir, f"img_{i}.png")
                img = generate_banner_image(bd, size=(100, 200))
                Image.fromarray(img).save(img_path)
                marks.append((img_path, bd))
            mbtlx_path = os.path.join(tmp_dir, "multi.mbtlx")
            n = export_mbtlx(mbtlx_path, marks)
            check_eq(n, len(banners_list), "导出条数不一致")
            result, extract_dir = import_mbtlx(mbtlx_path)
            check_eq(len(result), len(banners_list), "导入条数不一致")
            for i, (orig, (_, read_data)) in enumerate(zip(banners_list, result)):
                check_eq(list(read_data), orig, f"第 {i} 条数据不一致")
            cleanup(extract_dir)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @item("mbtlx 旧文本格式导入", description="'|' 分隔旧格式向后兼容")
    def _t():
        import tempfile, shutil
        from utils.mbtlx_utils import import_mbtlx, is_mbtlx
        tmp_dir = tempfile.mkdtemp()
        try:
            txt_path = os.path.join(tmp_dir, "text.mbtlx")
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write("img_a.png|1;10-7\nimg_b.png|2;20-5/30-3\n")
            check(not is_mbtlx(txt_path), "文本文件不应有 PK 头")
            result, extract_dir = import_mbtlx(txt_path)
            check_eq(len(result), 2, "文本行数不一致")
            check_eq(list(result[0][1]), [1, 7, 10], "第 1 行解析不一致")
            check_eq(list(result[1][1]), [2, 5, 20, 3, 30], "第 2 行解析不一致")
            check(extract_dir is None, "文本格式无解压目录")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @item("mbtlx 格式检测（ZIP vs 文本）", description="is_mbtlx 识别 b'PK' 头")
    def _t():
        import tempfile, shutil, zipfile
        from utils.mbtlx_utils import is_mbtlx
        tmp_dir = tempfile.mkdtemp()
        try:
            zip_path = os.path.join(tmp_dir, "zip.mbtlx")
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr("test.txt", "hello")
            check(is_mbtlx(zip_path), "ZIP 文件应识别为 mbtlx")
            txt_path = os.path.join(tmp_dir, "text.mbtlx")
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write("img|1\n")
            check(not is_mbtlx(txt_path), "文本文件不应识别为 mbtlx")
            check(not is_mbtlx(os.path.join(tmp_dir, "no_such.mbtlx")), "缺失文件返回 False")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------- 8. 旗帜图像生成 ----------
@category("8. 旗帜图像生成")
def _cat_banner():

    @item("load_icons 加载图标", description="图案图标字典加载")
    def _t():
        from utils import banner_utils
        banner_utils.load_icons()
        check(banner_utils.icon != {}, "icon 字典为空")
        check(banner_utils._shade_map is not None, "shade_map 为 None")
        loaded_count = len(banner_utils.icon)
        warn_if(loaded_count < 20, f"仅加载 {loaded_count} 个图标")

    @item("color 字典完整", description="16 色 + none 颜色定义")
    def _t():
        from utils.banner_utils import color, color_name, color_name_order
        check(len(color_name_order) == 16, f"color_name_order 长度异常: {len(color_name_order)}")
        check(len(color_name) == 17, f"color_name 长度异常: {len(color_name)}")
        for name in color_name:
            check_in(name, color, f"color 缺少 {name}")
            c = color[name]
            check(len(c) == 3, f"{name} RGB 异常: {c}")

    @item("type 列表完整", description="43 种图案类型定义")
    def _t():
        from utils.banner_utils import type, type_zh
        check(len(type) == 43, f"type 长度异常: {len(type)}")
        check(len(type_zh) == 43, f"type_zh 长度异常: {len(type_zh)}")
        check(type[0] == "no", f"type[0] 应为 'no'，实际 {type[0]!r}")

    @item("generate_banner_image 默认尺寸", description="默认 200x400 图像生成")
    def _t():
        import numpy as np
        from utils.banner_utils import generate_banner_image
        img = generate_banner_image([1, 5, 2], size=(200, 400))
        check(isinstance(img, np.ndarray), "返回类型异常")
        check_eq(img.shape, (400, 200, 3))
        check(img.dtype == np.uint8, f"dtype 异常: {img.dtype}")

    @item("generate_banner_image 不同尺寸", description="多种尺寸图像生成")
    def _t():
        from utils.banner_utils import generate_banner_image
        for sz in [(100, 200), (224, 224), (50, 100), (500, 1000)]:
            img = generate_banner_image([2, 10, 5], size=sz)
            check_eq(img.shape, (sz[1], sz[0], 3))

    @item("generate_banner_image 空图案", description="仅背景色图像生成")
    def _t():
        from utils.banner_utils import generate_banner_image
        img = generate_banner_image([3])
        check_eq(img.shape, (400, 200, 3))

    @item("generate_banner_image 16层满载", description="16 层满载图像生成")
    def _t():
        from utils.banner_utils import generate_banner_image
        flat = [0]
        for i in range(16):
            flat.extend([i % 42 + 1, i % 17])
        img = generate_banner_image(flat, size=(200, 400))
        check_eq(img.shape, (400, 200, 3))

    @item("generate_random_banner", description="随机旗帜数据生成")
    def _t():
        from utils.banner_utils import generate_random_banner
        for _ in range(20):
            b = generate_random_banner()
            check(isinstance(b, list))
            check(len(b) >= 1)
            check(0 <= b[0] < 17)

    @item("generate_random_banner 参数约束", description="颜色/图案数量约束")
    def _t():
        from utils.banner_utils import generate_random_banner
        b = generate_random_banner(min_colors=1, max_colors=1,
                                    min_patterns=5, max_patterns=5)
        check_eq(len(b), 11)


# ---------- 9. 模型创建与推理（慢） ----------
@category("9. 模型创建与推理（慢）")
def _cat_model():

    @item("ViT 实例化 (vit_b_16)", slow=True, description="标准 ViT-B/16 模型创建")
    def _t():
        from models.structures.vit_model import ViT
        with capture_stdout():
            model = ViT(model_arch="vit_b_16")
        check(hasattr(model, "vit"))
        check(hasattr(model, "bg_classifier"))
        check(len(model.pattern_classifiers) == 16)

    @item("ViT forward 一次", slow=True, description="前向推理输出形状正确")
    def _t():
        import torch
        from models.structures.vit_model import ViT
        with capture_stdout():
            model = ViT(model_arch="vit_b_16")
        model.eval()
        x = torch.randn(1, 3, 224, 224)
        with torch.no_grad():
            bg_pred, pat_preds = model(x)
        check(bg_pred.shape == (1, 17), f"bg_pred shape 异常: {bg_pred.shape}")
        check(len(pat_preds) == 32, f"pat_preds 长度异常: {len(pat_preds)}")

    @item("ViT 实例化 (deit_b_16)", slow=True, description="DeiT-B/16 轻量模型创建")
    def _t():
        from models.structures.vit_model import ViT
        with capture_stdout():
            model = ViT(model_arch="deit_b_16")
        check(model.is_deit is True)

    @item("ViT 实例化 (deit_s_16)", slow=True, description="DeiT-S/16 小型模型创建")
    def _t():
        from models.structures.vit_model import ViT
        with capture_stdout():
            model = ViT(model_arch="deit_s_16")
        check(model.is_deit is True)

    @item("ViT 实例化 (deit_t_16)", slow=True, description="DeiT-T/16 极小模型创建")
    def _t():
        from models.structures.vit_model import ViT
        with capture_stdout():
            model = ViT(model_arch="deit_t_16")
        check(model.is_deit is True)

    @item("BannerTrainer 创建", slow=True)
    def _t():
        from models.structures.vit_model import ViT, BannerTrainer
        with capture_stdout():
            model = ViT(model_arch="vit_b_16")
        trainer = BannerTrainer(model, device='cpu')
        check(hasattr(trainer, "optimizer"))
        check(hasattr(trainer, "scheduler"))
        check(hasattr(trainer, "criterion"))

    @item("save_model + load_model 往返", slow=True, description="模型保存与加载一致")
    def _t():
        from models.structures.vit_model import ViT, BannerTrainer
        with capture_stdout():
            model = ViT(model_arch="vit_b_16")
        trainer = BannerTrainer(model, device='cpu')
        with tempfile.NamedTemporaryFile(suffix=".pth", delete=False) as f:
            path = f.name
        try:
            with capture_stdout():
                trainer.save_model(path)
                check(os.path.exists(path) and os.path.getsize(path) > 0)
                trainer.load_model(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @item("predict 推理一张图", slow=True)
    def _t():
        import torch
        from models.structures.vit_model import ViT, BannerTrainer
        with capture_stdout():
            model = ViT(model_arch="vit_b_16")
        trainer = BannerTrainer(model, device='cpu')
        img = torch.randn(1, 3, 224, 224)
        with capture_stdout():
            result = trainer.predict(img)
        check(isinstance(result, list))
        check(len(result) >= 1)


# ---------- 10. 错误处理 ----------
@category("10. 错误处理")
def _cat_error():

    @item("report_error 函数可调用", description="错误文件生成到临时目录（不弹持久GUI）")
    def _t():
        """通过子进程脚本验证 report_error 能写入错误文件，不弹出持久GUI窗口。
        子进程脚本中 patch subprocess.Popen 以阻止 error_reporter GUI 启动。"""
        import tempfile
        import subprocess
        test_script = os.path.join(tempfile.gettempdir(), "_test_report_error_call.py")
        err_pattern = os.path.join(tempfile.gettempdir(), "banner_tool_error_calltest_*.txt")
        with open(test_script, "w", encoding="utf-8") as f:
            f.write("""import sys, os
sys.path.insert(0, r'""" + _APP_DIR.replace("\\", "\\\\") + """')
# Patch subprocess.Popen before importing settings_manager to block GUI launch
import subprocess as _sp
_orig_popen = _sp.Popen
def _fake_popen(*args, **kwargs):
    # Don't launch the error_reporter GUI, just return a mock
    class _MockProc:
        pid = 0
        def wait(self, *a, **kw): return 0
        def poll(self): return 0
    return _MockProc()
_sp.Popen = _fake_popen
from utils.settings_manager import report_error
report_error("测试错误标题", "这是测试错误内容", "calltest")
""")
        import glob as _glob
        for old in _glob.glob(err_pattern):
            try: os.unlink(old)
            except: pass
        try:
            result = subprocess.run(
                [sys.executable, test_script],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            import time as _time
            _time.sleep(0.5)
            err_files = _glob.glob(err_pattern)
            check(len(err_files) > 0, "report_error 未生成错误文件")
            err_f = err_files[0]
            with open(err_f, "r", encoding="utf-8") as f:
                content = f.read()
            check("这是测试错误内容" in content, f"错误文件内容不正确: {content[:200]}")
            # 清理：用 --auto 方式启动 error_reporter 消费此文件（自动关闭）
            try:
                _run_error_reporter_subprocess(err_f, "清理calltest", timeout=10)
            except Exception:
                pass
            # 清理可能残留的导出文件
            export_file = os.path.join(tempfile.gettempdir(), "testerror_export.txt")
            try: os.unlink(export_file)
            except: pass
        finally:
            for f in [test_script] + _glob.glob(err_pattern):
                try: os.unlink(f)
                except: pass

    @item("error_reporter.pyw 文件完整", description="单实例与错误读取逻辑")
    def _t():
        reporter = os.path.join(
            _APP_DIR,
            "scripts", "error_reporter.pyw"
        )
        check(os.path.exists(reporter))
        with open(reporter, "r", encoding="utf-8") as f:
            content = f.read()
        check("Mutex" in content or "mutex" in content.lower(), "缺少单实例逻辑")
        check("_read_all_errors" in content, "缺少错误读取函数")

    @item("长文本截断处理", description="_truncate_for_native 按行数+行宽截断")
    def _t():
        """验证 _truncate_for_native 对超长文本进行截断，并提示完整日志路径。"""
        mod = _load_error_reporter()
        check(callable(mod._read_all_errors), "_read_all_errors 不可调用")
        check(callable(mod._show_native_error), "_show_native_error 不可调用")
        check(callable(mod._truncate_for_native), "_truncate_for_native 不可调用")
        # 截断函数应有 max_lines 和 max_chars_per_line 参数
        import inspect
        sig = inspect.signature(mod._truncate_for_native)
        check("max_lines" in sig.parameters, "缺少 max_lines 参数")
        check("max_chars_per_line" in sig.parameters, "缺少 max_chars_per_line 参数")
        # 实际测试截断
        long_text = "\n".join(f"行 {i} " + "x" * 100 for i in range(50))
        truncated, was_truncated = mod._truncate_for_native(long_text, max_lines=10, max_chars_per_line=58)
        check(was_truncated, "50行文本应触发截断")
        check(len(truncated.split("\n")) <= 10, "截断后行数应 <= max_lines")

    @item("原生消息框无 PyQt5 依赖", description="原生回退不依赖 PyQt5，OOM 安全")
    def _t():
        """验证 error_reporter 原生回退使用 Win32 API，不依赖 PyQt5。

        注意：PyQt5 弹窗（优先模式）会 import PyQt5，但原生回退不应依赖。
        """
        mod = _load_error_reporter()
        reporter = os.path.join(
            _APP_DIR,
            "scripts", "error_reporter.pyw"
        )
        with open(reporter, "r", encoding="utf-8") as f:
            content = f.read()
        # 原生回退函数应存在（仅两层：PyQt 大窗 + MessageBoxW 兜底）
        check(hasattr(mod, "_show_native_error"), "应有 _show_native_error")
        check(hasattr(mod, "_show_message_box_fallback"), "应有 _show_message_box_fallback (MessageBox 回退)")
        # 应使用 MessageBoxW 作为回退（TaskDialog 在本机 ctypes 下不稳定，已移除）
        check("MessageBoxW" in content, "应使用 MessageBoxW 作为回退")
        check("ctypes.windll" in content, "应通过 ctypes 调用 Win32 API")

    @item("超长文本日志完整性", description="_save_log 保存完整文本（非截断）")
    def _t():
        """验证 _save_log 保存完整错误文本（_show_native_error 仅截断显示，日志保留全文）。"""
        import tempfile
        mod = _load_error_reporter()
        long_text = "错误行 " + "\n错误行 ".join(str(i) for i in range(500))
        saved = mod._save_log(long_text, auto_save=True)
        check(saved is not None and os.path.exists(saved), "日志文件未保存")
        with open(saved, "r", encoding="utf-8") as f:
            saved_content = f.read()
        check(saved_content == long_text, "日志内容应完整保留（非截断）")
        try:
            os.unlink(saved)
        except Exception:
            pass

    @item("error_reporter 测试模式检测", description="testerror/--auto 触发测试模式")
    def _t():
        """验证 error_reporter 能识别 testerror 文件名，且 _read_all_errors 返回正确结构。"""
        import tempfile
        mod = _load_error_reporter()
        check(hasattr(mod, "_test_mode"), "缺少 _test_mode 标志")
        test_file = os.path.join(tempfile.gettempdir(), "testerror.txt")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("测试错误内容")
        try:
            mod._test_mode = False
            combined, all_files = mod._read_all_errors(test_file)
            check(mod._test_mode is True, "testerror 文件名未触发测试模式")
            check(combined is not None, "combined 为 None")
            check("测试错误内容" in combined, "错误内容未被读取")
            check("【测试】" in combined, "测试模式来源标记异常")
            check(isinstance(all_files, list), "all_files 应为 list")
        finally:
            try:
                os.unlink(test_file)
            except Exception:
                pass

    @item("error_reporter 短文本流程", slow=True, description="子进程短文本错误自动导出")
    def _t():
        """子进程启动 error_reporter.pyw 测试短文本错误：--auto自动导出并验证内容。"""
        import tempfile
        test_file = os.path.join(tempfile.gettempdir(), "testerror_short.txt")
        short_msg = "这是一条短文本错误消息，用于测试非滚动模式。"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(short_msg)
        export_file = os.path.join(tempfile.gettempdir(), "testerror_export.txt")
        try:
            success, export_path, error, stderr = _run_error_reporter_subprocess(
                test_file, "短文本测试", timeout=15
            )
            check(success, f"短文本子进程失败: {error}")
            check(export_path is not None and os.path.exists(export_path), "导出文件不存在")
            with open(export_path, "r", encoding="utf-8") as f:
                exported = f.read()
            check(short_msg in exported, "导出内容缺少短文本消息")
        finally:
            for f in [test_file, export_file]:
                try:
                    os.unlink(f)
                except Exception:
                    pass

    @item("error_reporter 超长文本子进程", slow=True, description="子进程300行traceback→自动导出→验证完整性")
    def _t():
        """通过子进程启动 error_reporter.pyw，使用300行超长traceback，
        验证长文本滚动、自动导出日志、内容完整性、清理。"""
        import tempfile
        test_file = os.path.join(tempfile.gettempdir(), "testerror_long.txt")
        long_error = _gen_long_traceback(300)
        check("Traceback (most recent call last)" in long_error, "模拟traceback缺少Traceback头")
        check("CUDA out of memory" in long_error, "模拟traceback缺少CUDA OOM信息")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(long_error)
        export_file = os.path.join(tempfile.gettempdir(), "testerror_export.txt")
        try:
            success, export_path, error, stderr = _run_error_reporter_subprocess(
                test_file, "超长文本测试", timeout=20
            )
            check(success, f"子进程失败: {error}")
            check(export_path is not None, "导出路径为 None")
            check(os.path.exists(export_path), "导出文件不存在")
            with open(export_path, "r", encoding="utf-8") as f:
                exported = f.read()
            check(long_error in exported, "导出内容缺少原始错误文本")
            check("Traceback" in exported, "导出内容缺少 Traceback")
            check("CUDA out of memory" in exported, "导出内容缺少关键错误信息")
        finally:
            for f in [test_file, export_file]:
                try:
                    os.unlink(f)
                except Exception:
                    pass

    @item("error_reporter 深色模式超长文本", slow=True, description="深色模式200行traceback子进程，主题正确恢复")
    def _t():
        """深色主题下通过子进程测试超长文本流程，验证深色窗口正确显示且主题恢复。"""
        import tempfile
        from utils.settings_manager import SettingsManager
        sm = SettingsManager()
        old_theme = sm.get("theme")
        sm.set("theme", "dark")
        sm.save()
        test_file = os.path.join(tempfile.gettempdir(), "testerror_dark.txt")
        long_error = _gen_long_traceback(200)
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(long_error)
        export_file = os.path.join(tempfile.gettempdir(), "testerror_export.txt")
        try:
            success, export_path, error, stderr = _run_error_reporter_subprocess(
                test_file, "深色超长文本测试", timeout=20
            )
            check(success, f"深色模式子进程失败: {error}")
            check(export_path is not None, "深色模式导出路径为 None")
            check(os.path.exists(export_path), "深色模式导出文件不存在")
            with open(export_path, "r", encoding="utf-8") as f:
                exported = f.read()
            check(long_error in exported, "深色模式导出内容不完整")
            check("Traceback" in exported, "深色模式导出缺少Traceback")
        finally:
            sm.set("theme", old_theme)
            sm.save()
            restored = sm.get("theme")
            check(restored == old_theme, f"主题未正确恢复: {restored} != {old_theme}")
            for f in [test_file, export_file]:
                try:
                    os.unlink(f)
                except Exception:
                    pass

    @item("report_error 空消息保护（子进程）", slow=True, description="空消息时写入默认信息，不弹空窗口")
    def _t():
        """通过子进程验证 report_error 空消息场景：patch Popen阻止GUI启动，
        应写入默认消息而非NoneType:None，然后用--auto子进程验证正常读取显示。"""
        import tempfile
        import subprocess
        test_script = os.path.join(tempfile.gettempdir(), "_test_report_error.py")
        err_file_pattern = os.path.join(tempfile.gettempdir(), "banner_tool_error_reptest_*.txt")
        with open(test_script, "w", encoding="utf-8") as f:
            f.write("""import sys, os
sys.path.insert(0, r'""" + _APP_DIR.replace("\\", "\\\\") + """')
# Patch subprocess.Popen 阻止 error_reporter GUI 启动
import subprocess as _sp
def _fake_popen(*args, **kwargs):
    class _MockProc:
        pid = 0
        def wait(self, *a, **kw): return 0
        def poll(self): return 0
    return _MockProc()
_sp.Popen = _fake_popen
from utils.settings_manager import report_error
report_error("空消息测试", "", "reptest")
""")
        export_file = os.path.join(tempfile.gettempdir(), "testerror_export.txt")
        import glob as _glob
        for old in _glob.glob(err_file_pattern):
            try: os.unlink(old)
            except: pass
        try:
            result = subprocess.run(
                [sys.executable, test_script],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            import time as _time
            _time.sleep(0.5)
            err_files = _glob.glob(err_file_pattern)
            check(len(err_files) > 0, "report_error 未生成错误文件")
            err_f = err_files[0]
            with open(err_f, "r", encoding="utf-8") as f:
                content = f.read()
            check(content.strip(), "错误文件内容为空")
            check("NoneType: None" not in content, f"出现NoneType:None: {content[:200]}")
            check("reptest" in content, f"缺少来源标识: {content[:200]}")
            success, export_path, error, stderr = _run_error_reporter_subprocess(
                err_f, "空消息保护测试", timeout=15
            )
            check(success, f"空消息子进程失败: {error}")
        finally:
            for f in [test_script, export_file] + _glob.glob(err_file_pattern):
                try: os.unlink(f)
                except: pass

    @item("error_reporter 原生窗口无帮助按钮", description="MessageBoxW 回退无？按钮")
    def _t():
        """验证 error_reporter 原生回退 MessageBoxW 无帮助按钮。"""
        reporter = os.path.join(
            _APP_DIR,
            "scripts", "error_reporter.pyw"
        )
        with open(reporter, "r", encoding="utf-8") as f:
            content = f.read()
        # MessageBoxW 回退：是/否 + 导出报告提示文案
        check("导出报告" in content, "应有「导出报告」提示文案")
        check("_MB_YESNO" in content, "回退应使用 MB_YESNO 标志（无帮助按钮）")
        check("MB_HELP" not in content, "不应包含 MB_HELP 标志")
        check("_MB_ICONERROR" in content, "应使用 MB_ICONERROR 错误图标")
        # X 关闭 = 否 = 不导出日志
        check("IDCANCEL" in content, "应处理 X 关闭（IDCANCEL）等同「否」")

    @item("error_reporter 超长文本完整性", slow=True, description="子进程导出包含完整traceback（非截断）")
    def _t():
        """验证超长文本经子进程导出后，日志包含完整traceback内容（_save_log 保留全文）。"""
        import tempfile
        test_file = os.path.join(tempfile.gettempdir(), "testerror_longcheck.txt")
        long_error = _gen_long_traceback(300)
        long_line_count = len(long_error.split("\n"))
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(long_error)
        export_file = os.path.join(tempfile.gettempdir(), "testerror_export.txt")
        try:
            success, export_path, error, stderr = _run_error_reporter_subprocess(
                test_file, "长文本完整性测试", timeout=20
            )
            check(success, f"子进程失败: {error}")
            check(os.path.exists(export_path), "导出文件不存在")
            with open(export_path, "r", encoding="utf-8") as f:
                exported = f.read()
            exported_lines = exported.split("\n")
            # _save_log 保存完整文本（非截断），行数应不少于原始
            check(len(exported_lines) >= long_line_count,
                  f"导出文件行数 {len(exported_lines)} 少于原始行数 {long_line_count}")
            check("CUDA out of memory" in exported, "导出内容缺少CUDA OOM信息")
            check("ModuleNotFoundError" in exported, "导出内容缺少尾部异常信息")
        finally:
            for f in [test_file, export_file]:
                try:
                    os.unlink(f)
                except Exception:
                    pass

    @item("error_reporter 杜绝空combined", description="文件存在时不返回None")
    def _t():
        """验证 _read_all_errors 在文件为空时返回默认消息，而非 None。"""
        import tempfile
        mod = _load_error_reporter()
        empty_file = os.path.join(tempfile.gettempdir(), "testerror_empty.txt")
        with open(empty_file, "w", encoding="utf-8") as f:
            f.write("")
        try:
            mod._test_mode = False
            combined, all_files = mod._read_all_errors(empty_file)
            check(combined is not None, "combined 为 None")
        finally:
            try:
                os.unlink(empty_file)
            except Exception:
                pass

    @item("error_reporter 原生主题适配", description="MessageBoxW + 深色模式")
    def _t():
        """验证 error_reporter 原生回退尝试适配系统主题。"""
        mod = _load_error_reporter()
        check(hasattr(mod, "_show_native_error"), "应有 _show_native_error")
        check(hasattr(mod, "_try_dark_mode"), "应有 _try_dark_mode 深色模式尝试")
        check(hasattr(mod, "_is_system_dark"), "应有 _is_system_dark 系统主题检测")

    @item("error_reporter 原生截断长度", description="分辨率自适应行数截断防止占满屏幕")
    def _t():
        """验证 _truncate_for_native 按分辨率动态截断，并提示详细信息路径。"""
        mod = _load_error_reporter()
        check(hasattr(mod, "_get_native_limits"), "应有 _get_native_limits 分辨率自适应函数")
        check(hasattr(mod, "_truncate_for_native"), "应有 _truncate_for_native 截断函数")
        # _get_native_limits 返回 (max_lines, max_chars)
        limits = mod._get_native_limits()
        check(isinstance(limits, tuple) and len(limits) == 2, "_get_native_limits 应返回 (max_lines, max_chars)")
        max_lines, max_chars = limits
        check(max_lines >= 6, f"max_lines 应 >= 6，实际 {max_lines}")
        check(max_chars >= 40, f"max_chars 应 >= 40，实际 {max_chars}")
        # 源码中应有截断提示
        reporter = os.path.join(
            _APP_DIR,
            "scripts", "error_reporter.pyw"
        )
        with open(reporter, "r", encoding="utf-8") as f:
            content = f.read()
        check("已截断" in content, "缺少截断提示文案")
        check("详细信息见" in content, "截断后应提示「详细信息见」路径")

    @item("error_reporter PyQt5 对话框", description="PyQt5 弹窗：图标+滚动条+4:3+DPI+深浅色")
    def _t():
        """验证 PyQt5 错误对话框的完整功能。"""
        mod = _load_error_reporter()
        check(hasattr(mod, "_show_pyqt_error"), "应有 _show_pyqt_error PyQt5 弹窗函数")
        check(hasattr(mod, "_get_error_icon"), "应有 _get_error_icon 错误图标获取函数")
        check(hasattr(mod, "_is_system_dark"), "应有 _is_system_dark 系统主题检测")
        check(hasattr(mod, "_apply_dwm_dark_mode"), "应有 _apply_dwm_dark_mode DWM 深色标题栏")
        # 源码中应有 4:3 比例、滚动条、分辨率自适应
        reporter = os.path.join(
            _APP_DIR,
            "scripts", "error_reporter.pyw"
        )
        with open(reporter, "r", encoding="utf-8") as f:
            content = f.read()
        check("setFixedSize" in content, "PyQt5 对话框应固定窗口大小（4:3）")
        check("QTextBrowser" in content, "应使用 QTextBrowser 可滚动文本区域")
        check("QScrollBar" in content, "应有自定义滚动条样式")
        check("win_scale" in content, "应有分辨率自适应（win_scale）")
        check("font_scale" in content, "应有字体自适应（font_scale）")
        check("导出报告" in content, "应有「导出报告」按钮")

    @item("error_reporter MessageBoxW 回退按钮", description="是=导出报告；X/否=不导出")
    def _t():
        """验证 MessageBoxW 回退：仅「是」导出报告，X/否均不导出日志。"""
        mod = _load_error_reporter()
        check(hasattr(mod, "_IDYES"), "应有 _IDYES 常量")
        check(hasattr(mod, "_MB_YESNO"), "应有 _MB_YESNO 标志")
        check(hasattr(mod, "_MB_ICONERROR"), "应有 _MB_ICONERROR 错误图标")
        check(hasattr(mod, "_IDNO"), "应有 _IDNO 常量（否 = 不导出）")



# ---------- 11. 文件关联 ----------
@category("11. 文件关联")
def _cat_install():

    @item("图标资源完整", description="icons 目录资源齐全")
    def _t():
        icons_dir = os.path.join(
            _APP_DIR,
            "images", "icons"
        )
        check(os.path.exists(icons_dir), f"icons 目录不存在: {icons_dir}")
        required = ["mbtl.ico", "mbtlx.ico", "importer.ico", "trainer.ico"]
        for fn in required:
            p = os.path.join(icons_dir, fn)
            check(os.path.exists(p), f"缺少图标: {fn}")

    @item("base_and_patterns 资源完整", description="图案 PNG 资源齐全")
    def _t():
        patterns_dir = os.path.join(
            _APP_DIR,
            "images", "base_and_patterns"
        )
        check(os.path.exists(patterns_dir))
        check(os.path.exists(os.path.join(patterns_dir, "base.png")))
        pngs = [f for f in os.listdir(patterns_dir) if f.endswith(".png")]
        warn_if(len(pngs) < 40, f"图案 png 数量较少: {len(pngs)}")


# ---------- 12. 工作区布局 ----------
@category("12. 工作区布局")
def _cat_workspace():

    @item("load_workspace 返回结构")
    def _t():
        from utils.settings_manager import load_workspace
        ws = load_workspace()
        check(isinstance(ws, dict), f"返回类型异常: {type(ws)}")

    @item("save/load workspace_section 往返", description="分区保存与读取一致")
    def _t():
        from utils.settings_manager import save_workspace_section, load_workspace
        test_data = {"splitter_sizes": [100, 200], "mode": "wide"}
        save_workspace_section("test_program", "wide", test_data)
        ws = load_workspace()
        check("test_program" in ws, "保存后未找到 program")
        check("wide" in ws["test_program"], "未找到 layout 节点")
        # section_data 被合并到 layout 节点下
        for k, v in test_data.items():
            check_eq(ws["test_program"]["wide"].get(k), v, f"{k} 不一致")

    @item("save_workspace_section 支持 tab 参数", description="Tab 维度数据保存")
    def _t():
        from utils.settings_manager import save_workspace_section, load_workspace
        save_workspace_section("test_program", "wide",
                               {"data": 1}, tab="tab1")
        ws = load_workspace()
        prog = ws.get("test_program", {})
        check("wide" in prog, f"未找到 wide 节点: {prog}")
        check("tab1" in prog["wide"], f"未找到 tab1 数据: {prog['wide']}")
        check_eq(prog["wide"]["tab1"].get("data"), 1)

    @item("clear_workspace_window 清理 window 键", description="清理窗口位置记录")
    def _t():
        from utils.settings_manager import (clear_workspace_window, load_workspace,
                                            _workspace_file, _atomic_write_json)
        # 直接写入 window 子键
        data = load_workspace()
        data.setdefault("test_program", {})["window"] = {"x": 1, "y": 2}
        _atomic_write_json(_workspace_file(), data)
        clear_workspace_window("test_program")
        ws = load_workspace()
        check("window" not in ws.get("test_program", {}),
              f"清理后 window 仍存在: {ws.get('test_program')}")
        # 清理整个 test_program 避免污染
        data = load_workspace()
        data.pop("test_program", None)
        _atomic_write_json(_workspace_file(), data)

    @item("workspace 文件路径", description="workspace_layout.json 路径")
    def _t():
        from utils.settings_manager import _workspace_file
        p = _workspace_file()
        check(p.endswith("workspace_layout.json"), f"路径异常: {p}")
        check(os.path.exists(os.path.dirname(p)), "目录不存在")


# ---------- 13. 硬件兼容性检测 ----------
@category("13. 硬件兼容性检测")
def _cat_hw_compat():

    @item("detect_gpu_type 返回结构", description="返回 dict 含 vendor/name/is_integrated/vram_gb")
    def _t():
        from utils.device_backend import detect_gpu_type
        info = detect_gpu_type()
        check(isinstance(info, dict), f"返回类型异常: {type(info)}")
        for k in ("vendor", "name", "is_integrated", "vram_gb"):
            check_in(k, info, f"缺少键: {k}")
        check_in(info["vendor"], ("nvidia", "amd", "intel", "unknown", "none"),
                 f"vendor 值异常: {info['vendor']}")

    @item("get_compute_backend 返回值", description="后端为 cuda/directml/cpu 之一")
    def _t():
        from utils.device_backend import get_compute_backend
        backend = get_compute_backend()
        check_in(backend, ("cuda", "directml", "cpu"), f"未知后端: {backend}")

    @item("get_device 返回 torch.device", description="设备对象类型正确")
    def _t():
        if not _main_has_torch():
            ok, out = _dml_run(
                "import torch\n"
                "from utils.device_backend import get_device\n"
                "assert isinstance(get_device(), torch.device)")
            if ok is None:
                check(False, f"主进程无 torch 且 {out}")
            else:
                check(ok, f"dml_env 检查失败: {out}")
            return
        import torch
        from utils.device_backend import get_device
        dev = get_device()
        check(isinstance(dev, torch.device), f"返回类型异常: {type(dev)}")

    @item("supports_* 系列 API", description="AMP/pin_memory/memory_fraction/temp_monitoring 接口")
    def _t():
        from utils.device_backend import (
            supports_mixed_precision, supports_pin_memory,
            supports_memory_fraction, supports_gpu_temp_monitoring
        )
        for fn in (supports_mixed_precision, supports_pin_memory,
                   supports_memory_fraction, supports_gpu_temp_monitoring):
            r = fn()
            check(isinstance(r, bool), f"{fn.__name__} 应返回 bool")

    @item("get_backend_display_name", description="后端显示名映射")
    def _t():
        from utils.device_backend import get_backend_display_name
        check(get_backend_display_name("cuda") == "CUDA (NVIDIA GPU)")
        check(get_backend_display_name("directml") == "DirectML (AMD/Intel GPU)")
        check(get_backend_display_name("cpu") == "CPU")

# ---------- 14. DirectML 子进程协议（dml_worker） ----------
@category("14. DirectML 子进程协议")
def _cat_dml_worker():

    @item("dml_worker _emit 输出JSON", description="_emit 输出合法 JSON 行")
    def _t():
        import importlib.util
        worker_path = os.path.join(
            _APP_DIR,
            "scripts", "dml_worker.py"
        )
        # dml_worker 顶层 import torch/torch_directml，可能不可用，用 source 解析
        import ast
        with open(worker_path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        # 验证 _emit 函数存在且输出 json.dumps
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        check_in("_emit", func_names, "dml_worker 应有 _emit 函数")
        check_in("main", func_names, "dml_worker 应有 main 函数")

    @item("dml_worker stdout JSON 协议字段", description="info/progress/banner/complete/error 类型")
    def _t():
        import ast
        worker_path = os.path.join(
            _APP_DIR,
            "scripts", "dml_worker.py"
        )
        with open(worker_path, encoding="utf-8") as f:
            source = f.read()
        # 验证源码中包含各协议类型
        for proto in ('"type": "info"', '"type": "progress"', '"type": "complete"', '"type": "error"'):
            check(proto in source, f"dml_worker 源码应含 {proto}")

    @item("dml_worker argparse 参数", description="--banners-file/--epochs/--save-path 等参数")
    def _t():
        worker_path = os.path.join(
            _APP_DIR,
            "scripts", "dml_worker.py"
        )
        with open(worker_path, encoding="utf-8") as f:
            source = f.read()
        for arg in ("--banners-file", "--epochs", "--lr", "--arch",
                    "--save-path", "--device-index", "--train-mode"):
            check(arg in source, f"dml_worker 应支持参数 {arg}")


# ---------- 16. 文档与帮助系统 ----------
@category("15. 文档与帮助系统")
def _cat_docs():

    @item("help.pyw 可导入", description="帮助窗口模块可被导入")
    def _t():
        import importlib.util
        hp = os.path.join(
            _APP_DIR, "help.pyw"
        )
        check(os.path.exists(hp), f"找不到 help.pyw: {hp}")
        spec = importlib.util.spec_from_file_location("help", hp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        check(hasattr(mod, "HelpWindow"), "help 应有 HelpWindow 类")
        check(hasattr(mod, "SECTION_ANCHORS"), "help 应有 SECTION_ANCHORS 映射")

    @item("help.pyw SECTION_ANCHORS 锚点完整", description="章节锚点覆盖核心模块")
    def _t():
        import importlib.util
        hp = os.path.join(
            _APP_DIR, "help.pyw"
        )
        spec = importlib.util.spec_from_file_location("help", hp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        anchors = getattr(mod, "SECTION_ANCHORS", {})
        # 必需锚点：覆盖各核心模块 + 安装程序/诊断工具/FAQ
        required = ["overview", "startup", "importer", "trainer", "reverser",
                    "mbtl", "mbtlx", "installer", "diagnostic", "faq"]
        for key in required:
            check_in(key, anchors, f"SECTION_ANCHORS 缺少锚点: {key}")
            check(anchors[key].startswith("sec-"), f"锚点 {key} 值应以 sec- 开头")

    @item("help.pyw 含安装程序与诊断章节", description="HTML 内容覆盖新功能")
    def _t():
        import importlib.util
        hp = os.path.join(
            _APP_DIR, "help.pyw"
        )
        spec = importlib.util.spec_from_file_location("help", hp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # 触发 HTML 生成（浅色 + 1.0 缩放）
        html = mod._build_html(is_dark=False, scale=1.0)
        # 必需关键字：安装程序、诊断工具、演示模式、DirectML、硬件兼容性
        for kw in ("安装程序", "诊断工具", "演示模式", "DirectML", "硬件兼容性"):
            check(kw in html, f"help HTML 缺少关键字: {kw}")
        # 必需章节锚点
        for anchor in ("sec-installer", "sec-diagnostic", "sec-faq"):
            check(anchor in html, f"help HTML 缺少章节锚点: {anchor}")


@category("16. 安装与快捷方式")
def _cat_install():

    @item("start.pyw 存在", description="套件启动器文件存在")
    def _t():
        app_dir = _APP_DIR
        check(os.path.isfile(os.path.join(app_dir, "start.pyw")), "start.pyw 不存在")

    @item("核心程序文件完整", description="trainer/importer/bdor 存在性检测")
    def _t():
        app_dir = _APP_DIR
        # 按实际安装形态检测：仅识别器只查 bdor，含训练器查 trainer/importer/bdor
        files = ("trainer.pyw", "importer.pyw", "bdor.pyw") if not _is_use_mode() else ("bdor.pyw",)
        missing = [f for f in files if not os.path.isfile(os.path.join(app_dir, f))]
        check(not missing, f"核心文件缺失: {missing}")

    @item("pythonw.exe 可定位", description="系统 Python 无窗口解释器")
    def _t():
        import shutil
        pw = shutil.which("pythonw")
        if not pw:
            # 注册表查找
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
                                    if os.path.exists(pw):
                                        break
                            except OSError:
                                break
                        winreg.CloseKey(core)
                    except OSError:
                        pass
                    if pw:
                        break
            except Exception:
                pass
        check(pw and os.path.exists(pw), f"系统 pythonw.exe 未找到")

    @item("桌面快捷方式存在", description="用户桌面有软件快捷方式")
    def _t():
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0, None, 0, buf)
        desktop = buf.value
        lnk = os.path.join(desktop, "我的世界旗帜逆向套件.lnk")
        if not os.path.exists(lnk):
            # 备选名称
            lnk = os.path.join(desktop, "旗帜逆向套件.lnk")
        check(os.path.exists(lnk), f"桌面快捷方式不存在: {lnk}")

    @item("开始菜单快捷方式存在", description="开始菜单有软件快捷方式")
    def _t():
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        # CSIDL_PROGRAMS = 0x02
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x02, None, 0, buf)
        programs = buf.value
        shortcut_dir = os.path.join(programs, "我的世界旗帜逆向套件")
        lnk = os.path.join(shortcut_dir, "我的世界旗帜逆向套件.lnk")
        check(os.path.exists(lnk), f"开始菜单快捷方式不存在: {lnk}")


# ========================================================================
# 测试运行线程
# ========================================================================
class TestRunner(QThread):
    progress = pyqtSignal(int, int)
    item_done = pyqtSignal(object)
    all_done = pyqtSignal(int, int, int, int)

    def __init__(self, items, run_slow=True, parent=None):
        super().__init__(parent)
        self._items = items
        self._run_slow = run_slow
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        # 保存原始配置（测试后恢复，避免污染用户配置）
        _original_settings = None
        try:
            from utils.settings_manager import SettingsManager
            sm = SettingsManager()
            _original_settings = sm.get_all()
        except Exception:
            pass

        total = len(self._items)
        done = 0
        n_pass = n_fail = n_warn = n_skip = 0
        for it in self._items:
            if self._stop:
                if it.status == PENDING:
                    it.status = SKIP
                    it.message = "已停止"
                self.item_done.emit(it)
                n_skip += 1
                done += 1
                self.progress.emit(done, total)
                continue
            if it.slow and not self._run_slow:
                it.status = SKIP
                it.message = "跳过慢测试"
                self.item_done.emit(it)
                n_skip += 1
                done += 1
                self.progress.emit(done, total)
                continue
            if it.status == SKIP:
                # 已被组件过滤标记为跳过（未安装的库）
                self.item_done.emit(it)
                n_skip += 1
                done += 1
                self.progress.emit(done, total)
                continue
            it.run()
            self.item_done.emit(it)
            if it.status == PASS: n_pass += 1
            elif it.status == FAIL: n_fail += 1
            elif it.status == WARN: n_warn += 1
            else: n_skip += 1
            done += 1
            self.progress.emit(done, total)

        # 收拾残局：恢复原始配置并保存
        if _original_settings is not None:
            try:
                from utils.settings_manager import SettingsManager
                sm = SettingsManager()
                sm.set_all(_original_settings)
                sm.save()
            except Exception:
                pass

        self.all_done.emit(n_pass, n_fail, n_warn, n_skip)


# ========================================================================
# 主窗口
# ========================================================================
class TestWindow(QMainWindow):
    def __init__(self, scale=1.0):
        super().__init__()
        self.setWindowTitle("我的世界旗帜逆向工具箱 稳固性测试")

        # 分辨率适配（与 trainer.pyw 一致：ui_scale 基于 screen 逻辑尺寸）
        self._scale = max(scale, 1.0)
        self._base_fs = max(int(13 * self._scale), 13)
        self._btn_fs = max(int(14 * self._scale), 14)
        self._title_fs = max(int(18 * self._scale), 16)
        self._small_fs = max(int(12 * self._scale), 11)
        self._tiny_fs = max(int(11 * self._scale), 10)

        # 窗口尺寸限制（规整尺寸：避免过高）
        w = int(1100 * self._scale)
        h = int(660 * self._scale)
        min_w = int(900 * self._scale)
        min_h = int(540 * self._scale)
        self.setMinimumSize(min_w, min_h)
        self.setMaximumWidth(int(1400 * self._scale))
        self.setMaximumHeight(int(900 * self._scale))
        self.resize(w, h)

        self._all_items = []
        self._flat_items = []
        self._runner = None
        self._run_slow = True

        self._init_ui()
        self._load_tests()
        self._apply_style()

    def _center_on_screen(self, screen):
        """窗口居中到指定屏幕（修复位置识别问题）。"""
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(max(geo.x(), x), max(geo.y(), y))

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 顶部标题栏
        header = QWidget()
        header.setFixedHeight(int(56 * self._scale))
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(int(20 * self._scale), int(8 * self._scale),
                                          int(20 * self._scale), int(8 * self._scale))
        title = QLabel("我的世界旗帜逆向工具箱 稳固性测试")
        title.setStyleSheet(f"font-size: {self._title_fs}px; font-weight: 600; color: #1a1a1a;")
        subtitle = QLabel("自动化验证所有功能模块的稳定性")
        subtitle.setStyleSheet(f"font-size: {self._small_fs}px; color: #666;")
        header_layout.addWidget(title)
        header_layout.addSpacing(int(8 * self._scale))
        header_layout.addWidget(subtitle)
        header_layout.addStretch()
        self._summary_label = QLabel("共 0 项测试")
        self._summary_label.setStyleSheet(f"font-size: {self._base_fs}px; color: #444;")
        header_layout.addWidget(self._summary_label)
        outer.addWidget(header)

        # 分隔线
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #e0e0e0;")
        outer.addWidget(sep)

        # 主体：左侧分类 + 右侧测试列表
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)

        self._nav_list = QListWidget()
        self._nav_list.setMinimumWidth(int(220 * self._scale))
        self._nav_list.setMaximumWidth(int(300 * self._scale))
        self._nav_list.itemClicked.connect(self._on_nav_clicked)
        splitter.addWidget(self._nav_list)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["测试项", "状态", "耗时", "说明"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        self._tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        splitter.addWidget(self._tree)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([int(240 * self._scale), int(860 * self._scale)])
        outer.addWidget(splitter, 1)

        # 底部控制栏
        bottom = QWidget()
        bottom.setFixedHeight(int(64 * self._scale))
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(int(16 * self._scale), int(8 * self._scale),
                                          int(16 * self._scale), int(8 * self._scale))
        bottom_layout.setSpacing(4)

        self._progress = QProgressBar()
        _init_total = sum(len(items) for _, items in _TEST_CATEGORIES)
        self._progress.setRange(0, _init_total)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("就绪 %v/%m")
        bottom_layout.addWidget(self._progress)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(int(8 * self._scale))
        self._btn_run_all = QPushButton("运行全部")
        self._btn_run_all.clicked.connect(self._run_all)
        self._btn_run_selected = QPushButton("运行选中")
        self._btn_run_selected.clicked.connect(self._run_selected)
        self._btn_stop = QPushButton("停止")
        self._btn_stop.clicked.connect(self._stop_test)
        self._btn_stop.setEnabled(False)
        self._chk_slow = QPushButton("包含慢测试")
        self._chk_slow.setCheckable(True)
        self._chk_slow.setChecked(True)
        self._chk_slow.toggled.connect(self._on_slow_toggled)
        self._btn_export = QPushButton("导出报告")
        self._btn_export.clicked.connect(self._export_report)
        self._btn_clear = QPushButton("重置状态")
        self._btn_clear.clicked.connect(self._reset_status)

        self._btn_run_all.setObjectName("btn_primary")
        btn_row.addWidget(self._btn_run_all)
        btn_row.addWidget(self._btn_run_selected)
        btn_row.addWidget(self._btn_stop)
        btn_row.addSpacing(int(12 * self._scale))
        btn_row.addWidget(self._chk_slow)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_clear)
        btn_row.addWidget(self._btn_export)
        bottom_layout.addLayout(btn_row)

        outer.addWidget(bottom)

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("就绪")

    def _apply_style(self):
        s = self._scale
        bfs = self._base_fs
        sfs = self._small_fs
        tfs = self._tiny_fs
        self.setStyleSheet(f"""
            QMainWindow {{ background: #f5f5f5; }}
            QListWidget {{
                background: #fafafa;
                border: none;
                border-right: 1px solid #e0e0e0;
                padding-top: {int(8 * s)}px;
                font-size: {bfs}px;
            }}
            QListWidget::item {{
                padding: {int(8 * s)}px {int(16 * s)}px;
                border: none;
            }}
            QListWidget::item:selected {{
                background: #e8f0fe;
                color: #1a73e8;
            }}
            QListWidget::item:hover {{
                background: #f0f0f0;
            }}
            QTreeWidget {{
                background: #fff;
                border: none;
                font-size: {bfs}px;
            }}
            QTreeWidget::item {{
                padding: {int(4 * s)}px 0;
                border-bottom: 1px solid #f0f0f0;
            }}
            QTreeWidget::item:selected {{
                background: #e8f0fe;
                color: #1a73e8;
            }}
            QHeaderView::section {{
                background: #fafafa;
                color: #555;
                padding: {int(6 * s)}px {int(8 * s)}px;
                border: none;
                border-bottom: 1px solid #e0e0e0;
                font-size: {sfs}px;
                font-weight: 600;
            }}
            QProgressBar {{
                background: #e8e8e8;
                border: none;
                border-radius: 4px;
                height: {int(16 * s)}px;
                text-align: center;
                font-size: {tfs}px;
                color: #333;
            }}
            QProgressBar::chunk {{
                background: #1a73e8;
                border-radius: 4px;
            }}
            QPushButton {{
                background: #fff;
                color: #333;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: {int(6 * s)}px {int(16 * s)}px;
                font-size: {bfs}px;
                min-height: {int(18 * s)}px;
            }}
            QPushButton:hover {{
                background: #f5f7fa;
                border-color: #1a73e8;
                color: #1a73e8;
            }}
            QPushButton:pressed {{
                background: #e8f0fe;
            }}
            QPushButton:disabled {{
                background: #f5f5f5;
                color: #aaa;
                border-color: #e0e0e0;
            }}
            QPushButton#btn_primary {{
                background: #1a73e8;
                color: white;
                border: 1px solid #1a73e8;
            }}
            QPushButton#btn_primary:hover {{
                background: #1557b0;
                border-color: #1557b0;
                color: white;
            }}
            QPushButton#btn_primary:pressed {{
                background: #0d47a1;
                border-color: #0d47a1;
            }}
            QPushButton:checked {{
                background: #e8f0fe;
                color: #1a73e8;
                border-color: #1a73e8;
            }}
            QStatusBar {{
                background: #fafafa;
                color: #555;
                border-top: 1px solid #e0e0e0;
                font-size: {sfs}px;
            }}
        """)

    def _load_tests(self):
        # 按安装形态过滤：仅识别器（磁盘无 trainer.pyw 且 json purpose=use）跳过训练相关测试分类
        if _is_use_mode():
            self._all_items = [(n, its) for n, its in _TEST_CATEGORIES
                               if n not in _USE_SKIP_CATEGORIES]
            # use 模式跳过分类内训练相关检测项（分类内有 use 需要的项，不能整个跳过）
            for n, items in self._all_items:
                for it in items:
                    if it.name in _USE_SKIP_ITEMS:
                        it.status = SKIP
                        it.message = "use 模式（仅识别器）跳过训练相关测试"
        else:
            self._all_items = list(_TEST_CATEGORIES)
        self._flat_items = []
        for cat_name, items in self._all_items:
            for it in items:
                it.category = cat_name
                self._flat_items.append(it)

        self._nav_list.clear()
        total_all = len(self._flat_items)
        summary_item = QListWidgetItem(f" 全部测试  ({total_all})")
        summary_item.setData(Qt.UserRole, "__all__")
        self._nav_list.addItem(summary_item)
        for cat_name, items in self._all_items:
            li = QListWidgetItem(f" {cat_name}  ({len(items)})")
            li.setData(Qt.UserRole, cat_name)
            self._nav_list.addItem(li)
        self._nav_list.setCurrentRow(0)

        self._populate_tree("__all__")
        total = len(self._flat_items)
        slow_count = sum(1 for it in self._flat_items if it.slow)
        form = _detect_install_form()
        # 显示检测到的安装形态（解决"识别不出训练/训练+识别器/仅识别器"的问题）
        form_note = "，安装形态：%s" % form["form"] if form.get("form") else ""
        use_note = "（已跳过训练相关检测）" if form.get("use_mode") else ""
        self._summary_label.setText(
            f"共 {total} 项测试（含 {slow_count} 项慢测试）{form_note}{use_note}"
        )
        # 同步进度条总数（use 模式下为过滤后的数量，不是全量 149）
        self._progress.setRange(0, total)
        self._progress.setValue(0)
        self._progress.setFormat("就绪 %v/%m")

    def _populate_tree(self, filter_key):
        self._tree.clear()
        if filter_key == "__all__":
            cats = self._all_items
        else:
            cats = [(n, its) for n, its in self._all_items if n == filter_key]

        for cat_name, items in cats:
            cat_item = QTreeWidgetItem(self._tree)
            cat_item.setText(0, cat_name)
            cat_item.setText(1, "")
            cat_item.setText(2, "")
            cat_item.setText(3, f"{len(items)} 项")
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            cat_item.setBackground(0, QBrush(QColor("#fafafa")))

            for it in items:
                child = QTreeWidgetItem(cat_item)
                child.setText(0, it.name)
                child.setText(1, STATUS_ICON[it.status])
                child.setText(2, "")
                child.setText(3, it.description)
                child.setForeground(1, QBrush(QColor(STATUS_COLOR[it.status])))
                child.setData(0, Qt.UserRole, it)
            cat_item.setExpanded(True)

        self._tree.resizeColumnToContents(1)
        self._tree.resizeColumnToContents(2)

    def _on_nav_clicked(self, item):
        key = item.data(Qt.UserRole)
        self._populate_tree(key)

    def _on_item_double_clicked(self, item, column):
        it = item.data(0, Qt.UserRole)
        if it is None:
            return
        if self._runner and self._runner.isRunning():
            QMessageBox.information(self, "提示", "测试正在运行，请先停止")
            return
        self._run_items([it])

    def _on_slow_toggled(self, checked):
        self._run_slow = checked

    def closeEvent(self, event):
        """关闭窗口时停止测试线程，确保进程退出。"""
        if self._runner and self._runner.isRunning():
            self._runner.stop()
            self._runner.wait(5000)
        event.accept()

    def _run_all(self):
        if self._runner and self._runner.isRunning():
            return
        self._nav_list.setCurrentRow(0)
        self._populate_tree("__all__")
        self._run_items(list(self._flat_items))

    def _run_selected(self):
        if self._runner and self._runner.isRunning():
            return
        selected_items = self._tree.selectedItems()
        targets = []
        for ti in selected_items:
            data = ti.data(0, Qt.UserRole)
            if data is not None:
                targets.append(data)
            else:
                for i in range(ti.childCount()):
                    child = ti.child(i)
                    d = child.data(0, Qt.UserRole)
                    if d is not None:
                        targets.append(d)
        if not targets:
            QMessageBox.information(self, "提示", "请先在列表中选择测试项")
            return
        self._run_items(targets)

    def _run_items(self, items):
        for it in items:
            it.status = PENDING
            it.message = ""
            it.traceback = ""
            it.elapsed_ms = 0
        # 按已安装组件过滤（无清单时全量检测）
        _filter_by_components(items)
        self._refresh_tree_items(items)

        self._btn_run_all.setEnabled(False)
        self._btn_run_selected.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_export.setEnabled(False)
        self._progress.setRange(0, len(items))
        self._progress.setValue(0)
        self._progress.setFormat("运行中 %v/%m")
        self._status.showMessage(f"正在运行 {len(items)} 项测试...")

        self._runner = TestRunner(items, run_slow=self._run_slow, parent=None)
        self._runner.progress.connect(self._on_progress)
        self._runner.item_done.connect(self._on_item_done)
        self._runner.all_done.connect(self._on_all_done)
        self._runner.start()

    def _stop_test(self):
        if self._runner and self._runner.isRunning():
            self._runner.stop()
            self._status.showMessage("正在停止...")

    def _on_progress(self, done, total):
        self._progress.setValue(done)

    def _on_item_done(self, item):
        self._refresh_tree_items([item])

    def _refresh_tree_items(self, items):
        item_set = set(id(i) for i in items)
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                it = child.data(0, Qt.UserRole)
                if it is not None and id(it) in item_set:
                    child.setText(1, STATUS_ICON[it.status])
                    child.setText(2, f"{it.elapsed_ms}ms" if it.elapsed_ms > 0 else "")
                    msg = it.message
                    child.setForeground(1, QBrush(QColor(STATUS_COLOR[it.status])))

    def _on_all_done(self, n_pass, n_fail, n_warn, n_skip):
        self._btn_run_all.setEnabled(True)
        self._btn_run_selected.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_export.setEnabled(True)
        total = n_pass + n_fail + n_warn + n_skip
        self._progress.setRange(0, total)
        self._progress.setValue(total)
        self._progress.setFormat(f"完成 {total}/{total}")

        # 输出失败项和对应文件到 JSON，供安装器修复功能读取
        _export_repair_result(self._flat_items)

        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            n_p = n_f = n_w = 0
            for j in range(top.childCount()):
                child = top.child(j)
                it = child.data(0, Qt.UserRole)
                if it is None:
                    continue
                if it.status == PASS: n_p += 1
                elif it.status == FAIL: n_f += 1
                elif it.status == WARN: n_w += 1
            if top.childCount() > 0:
                top.setText(1, f"✓{n_p} ✗{n_f} !{n_w}")
                top.setForeground(1, QBrush(QColor(
                    "#2e7d32" if n_f == 0 else "#c62828"
                )))

        msg = f"完成：通过 {n_pass}，失败 {n_fail}，警告 {n_warn}，跳过 {n_skip}"
        self._status.showMessage(msg, 8000)

        if n_fail > 0:
            self._show_result_dialog(
                "✗", "#c62828", "测试完成",
                f"{msg}\n\n有 {n_fail} 项测试失败，请查看列表中的 ✗ 项。\n"
                f"建议导出报告并修复问题。",
                show_repair=True
            )
        elif n_warn > 0:
            self._show_result_dialog(
                "!", "#ef6c00", "测试完成",
                f"{msg}\n\n无致命失败，但有 {n_warn} 项警告，建议关注。"
            )
        else:
            self._show_result_dialog(
                "✓", "#2e7d32", "测试完成",
                f"{msg}\n\n所有测试通过，软件稳固性良好！"
            )

    def _show_result_dialog(self, icon, color, title, text, show_repair=False):
        """4:3 固定比例的测试结果提示窗口（避免 QMessageBox 窄高挤压文本）。

        show_repair=True 时显示「进入修复界面」按钮，启动 real_installer 修复页。
        """
        from PyQt5.QtWidgets import QDialog
        s = self._scale
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        sw, sh = geo.width(), geo.height()
        dlg_w = min(int(400 * s), int(sw * 0.5))
        dlg_h = int(dlg_w * 3 / 4)
        max_h = int(sh * 0.6)
        if dlg_h > max_h:
            dlg_h = max_h
            dlg_w = int(dlg_h * 4 / 3)
        dlg.setFixedSize(dlg_w, dlg_h)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(int(20 * s), int(16 * s), int(20 * s), int(12 * s))
        layout.setSpacing(int(12 * s))

        row = QHBoxLayout()
        row.setSpacing(int(14 * s))
        icon_lbl = QLabel(icon)
        icon_lbl.setAlignment(Qt.AlignTop)
        icon_lbl.setStyleSheet(
            f"font-size: {max(int(36 * s), 28)}px; font-weight: bold; color: {color};")
        row.addWidget(icon_lbl, 0)
        msg_lbl = QLabel(text)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(f"font-size: {self._base_fs}px;")
        row.addWidget(msg_lbl, 1)
        layout.addLayout(row, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        if show_repair:
            btn_repair = QPushButton("进入修复界面")
            btn_repair.setMinimumWidth(int(110 * s))
            btn_repair.setMinimumHeight(int(30 * s))
            btn_repair.setObjectName("btn_primary")
            btn_repair.clicked.connect(lambda: self._launch_repair(dlg))
            btn_row.addWidget(btn_repair)
            btn_row.addSpacing(int(8 * s))
        ok = QPushButton("OK")
        ok.setMinimumWidth(int(90 * s))
        ok.setMinimumHeight(int(30 * s))
        ok.setDefault(True)
        ok.clicked.connect(dlg.accept)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

        dlg.exec_()

    def _launch_repair(self, parent_dlg):
        """启动安装包修复界面。

        如果 test.pyw 是被安装器启动的（--from-installer），
        直接关闭自身即可——安装器在等待 test.pyw 退出后自动进入修复页面。

        独立运行时（非安装器启动），从注册表查找安装包路径并启动 --repair。
        """
        # 被安装器启动 → 直接关闭，安装器会自动进入修复
        if "--from-installer" in sys.argv:
            parent_dlg.accept()
            return

        import subprocess

        # 独立运行 → 从注册表读取安装包路径
        installer_exe = ""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall\BannerWeaveReverser"
            )
            installer_exe, _ = winreg.QueryValueEx(key, "InstallSource")
            winreg.CloseKey(key)
        except Exception:
            pass

        # 2. 回退：开发环境找 installer/real_installer.pyw
        if not installer_exe or not os.path.exists(installer_exe):
            dev_path = os.path.join(
                _APP_DIR,
                "installer", "real_installer.pyw"
            )
            if os.path.exists(dev_path):
                installer_exe = dev_path
            else:
                installer_exe = ""

        # 3. 找不到，提示用户运行桌面安装包
        if not installer_exe:
            QMessageBox.information(self, "提示",
                "未找到安装程序。\n\n"
                "请运行桌面上的「我的世界旗帜逆向套件」安装程序，\n"
                "进入维护模式 → 文件修复。")
            return

        parent_dlg.accept()
        try:
            if installer_exe.lower().endswith(".pyw"):
                subprocess.Popen(
                    [sys.executable, installer_exe, "--repair"],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                subprocess.Popen(
                    [installer_exe, "--repair"],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"无法启动修复界面:\n{e}")

    def _reset_status(self):
        if self._runner and self._runner.isRunning():
            QMessageBox.information(self, "提示", "测试正在运行，请先停止")
            return
        for it in self._flat_items:
            it.status = PENDING
            it.message = ""
            it.traceback = ""
            it.elapsed_ms = 0
        current_key = "__all__" if self._nav_list.currentRow() == 0 \
            else self._nav_list.currentItem().data(Qt.UserRole)
        self._populate_tree(current_key)
        self._progress.setRange(0, len(self._flat_items))
        self._progress.setValue(0)
        self._progress.setFormat("就绪 %v/%m")
        self._status.showMessage("已重置")

    def _export_report(self):
        default_name = f"test_report_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出测试报告", default_name, "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            lines = []
            lines.append("=" * 70)
            lines.append("我的世界旗帜逆向工具箱 稳固性测试报告")
            lines.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("=" * 70)
            lines.append("")

            total_p = total_f = total_w = total_s = 0
            for cat_name, items in self._all_items:
                lines.append(f"【{cat_name}】")
                n_p = n_f = n_w = 0
                for it in items:
                    icon = STATUS_ICON[it.status]
                    elapsed = f"{it.elapsed_ms}ms" if it.elapsed_ms > 0 else "-"
                    line = f"  [{icon}] {it.name:<40s} {elapsed:>8s}  {it.message}"
                    lines.append(line)
                    if it.status == PASS:
                        n_p += 1; total_p += 1
                    elif it.status == FAIL:
                        n_f += 1; total_f += 1
                        if it.traceback:
                            for tb_line in it.traceback.split("\n"):
                                lines.append(f"        {tb_line}")
                    elif it.status == WARN:
                        n_w += 1; total_w += 1
                    else:
                        total_s += 1
                lines.append(f"  小计: 通过 {n_p}，失败 {n_f}，警告 {n_w}")
                lines.append("")

            lines.append("=" * 70)
            total = total_p + total_f + total_w + total_s
            lines.append(f"总计: {total} 项 — 通过 {total_p}，失败 {total_f}，警告 {total_w}，跳过 {total_s}")
            lines.append("=" * 70)

            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            QMessageBox.information(self, "导出成功", f"报告已保存到:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"写入文件失败:\n{e}")


# ========================================================================
# 修复扫描：测试项→文件映射，失败项输出到 JSON 供 real_installer 修复读取
# ========================================================================

# 测试分类→对应文件映射（None 表示不在安装包内，如 pip 库/硬件）
_CATEGORY_FILE_MAP = {
    "1. 依赖库检查": None,                     # pip 安装的库，不在安装包内
    "2. 项目模块导入": ["utils", "models/structures"],
    "3. 配置管理": ["utils/settings_manager.py"],
    "4. 硬件检测": None,                       # 硬件相关，不涉及文件
    "5. 资源分配": ["utils/settings_manager.py"],
    "6. 模型架构": ["models/structures"],
    "7. MBTL 文件 IO": ["utils/mbtl_reader.py", "utils/mbtl_writer.py"],
    "8. 旗帜图像生成": ["utils/banner_generator.py", "images"],
    "9. 模型创建与推理（慢）": ["models/structures/vit_model.py"],
    "10. 错误处理": ["scripts/error_reporter.pyw"],
    "11. 文件关联": ["images"],
    "12. 工作区布局": ["utils/settings_manager.py"],
    "13. 硬件兼容性检测": ["utils/device_backend.py"],
    "14. DirectML 子进程协议": ["scripts/dml_worker.py"],
    "15. 文档与帮助系统": ["help.pyw"],
    "16. 安装与快捷方式": ["start.pyw", "bdor.pyw"],
}

# 修复扫描结果输出路径（%TEMP% 下，不算项目新文件）
_REPAIR_RESULT_FILE = os.path.join(
    os.environ.get("TEMP", _APP_DIR),
    "banner_test_result.json"
)


def _export_repair_result(items):
    """将失败的测试项和对应文件写入 JSON，供 real_installer 修复功能读取。

    格式: {
        "failed_items": [{"name": "...", "category": "...", "message": "...", "files": [...]}],
        "failed_files": ["utils/settings_manager.py", "models/structures/vit_model.py", ...]
    }
    """
    failed_items = []
    failed_files = set()
    for it in items:
        if it.status != FAIL:
            continue
        files = _CATEGORY_FILE_MAP.get(it.category)
        if files is None:
            continue  # 依赖库/硬件等不在安装包内的，跳过
        failed_items.append({
            "name": it.name,
            "category": it.category,
            "message": it.message,
            "files": files
        })
        for f in files:
            failed_files.add(f)
    result = {
        "failed_items": failed_items,
        "failed_files": sorted(failed_files)
    }
    # 无失败项时删除结果文件：防止陈旧的失败结果残留，
    # 导致 real_installer 维护页把已修复/已正常的文件误判为"异常/损坏"
    try:
        if not failed_items:
            if os.path.exists(_REPAIR_RESULT_FILE):
                os.remove(_REPAIR_RESULT_FILE)
            return result
        with open(_REPAIR_RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return result


# ========================================================================
# CLI 模式：不开 GUI，直接跑全部测试并打印结果（用于冒烟验证）
# ========================================================================
def run_cli(no_slow=False):
    """命令行模式：python test.pyw --cli [--no-slow]"""
    # GBK 控制台无法输出 ✓/✗ 等 Unicode 图标，直接按 UTF-8 重配输出避免 UnicodeEncodeError
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    root = _APP_DIR
    if root not in sys.path:
        sys.path.insert(0, root)

    # 创建 QApplication（部分测试需要 QTextEdit 等 Qt 控件）
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # 保存原始配置（测试后恢复，避免污染用户配置）
    _original_settings = None
    try:
        from utils.settings_manager import SettingsManager
        sm = SettingsManager()
        _original_settings = sm.get_all()
    except Exception:
        pass

    flat = []
    # 按安装形态过滤：仅识别器（磁盘无 trainer.pyw 且 json purpose=use）跳过训练相关分类和检测项
    cats = _TEST_CATEGORIES
    if _is_use_mode():
        cats = [(n, its) for n, its in _TEST_CATEGORIES if n not in _USE_SKIP_CATEGORIES]
    for cat_name, items in cats:
        for it in items:
            it.category = cat_name
            if _is_use_mode() and it.name in _USE_SKIP_ITEMS:
                it.status = SKIP
                it.message = "use 模式（仅识别器）跳过训练相关测试"
            flat.append(it)

    _form = _detect_install_form()
    print("=" * 70)
    print(f"我的世界旗帜逆向工具箱 稳固性测试 — CLI 模式（共 {len(flat)} 项）")
    print(f"安装形态：{_form.get('form', '未知')}"
          + ("（已跳过训练相关检测）" if _form.get("use_mode") else "（全量检测）"))
    print("=" * 70)

    n_pass = n_fail = n_warn = n_skip = 0
    cur_cat = ""
    for it in flat:
        if it.category != cur_cat:
            cur_cat = it.category
            print(f"\n【{cur_cat}】")
        if it.status == SKIP:
            print(f"  [—] {it.name:<40s}  跳过")
            n_skip += 1
            continue
        if it.slow and no_slow:
            it.status = SKIP
            it.message = "跳过慢测试"
            print(f"  [—] {it.name:<40s}  跳过")
            n_skip += 1
            continue
        it.run()
        icon = STATUS_ICON[it.status]
        elapsed = f"{it.elapsed_ms}ms"
        line = f"  [{icon}] {it.name:<40s}  {elapsed:>8s}  {it.message}"
        print(line)
        if it.status == PASS:
            n_pass += 1
        elif it.status == FAIL:
            n_fail += 1
            if it.traceback:
                for tb in it.traceback.split("\n"):
                    print(f"        {tb}")
        elif it.status == WARN:
            n_warn += 1
        else:
            n_skip += 1

    # 收拾残局：恢复原始配置并保存
    if _original_settings is not None:
        try:
            from utils.settings_manager import SettingsManager
            sm = SettingsManager()
            sm.set_all(_original_settings)
            sm.save()
            print("\n[清理] 已恢复原始配置")
        except Exception:
            pass

    print("\n" + "=" * 70)
    total = n_pass + n_fail + n_warn + n_skip
    print(f"总计: {total} 项 — 通过 {n_pass}，失败 {n_fail}，警告 {n_warn}，跳过 {n_skip}")
    print("=" * 70)

    # 输出失败项和对应文件到 JSON，供安装器修复功能读取
    _export_repair_result(flat)

    return 0 if n_fail == 0 else 1


# ========================================================================
# 入口
# ========================================================================
# 全局保活单实例互斥锁（避免 main 函数返回前被 GC/析构提前释放）
_TEST_SHM_HANDLE = None


def main():
    global _TEST_SHM_HANDLE
    # 单实例控制：防止重复打开 test.pyw
    # 关键：create() 成功后立即存全局，确保整个进程生命周期内不释放
    _shm = QSharedMemory("BannerWeaveReverser_Test_Mutex")
    if not _shm.create(1):
        # 已有实例在运行：先 attach 确认不是崩溃残留（create 失败但没人占？极端情况）
        if _shm.attach():
            _shm.detach()
            # attach 成功说明真有实例占着，提示并退出
            if "--cli" in sys.argv:
                print("测试程序已在运行，请勿重复打开。", file=sys.stderr)
                sys.exit(1)
            try:
                app = QApplication(sys.argv)
                QMessageBox.warning(None, "提示", "测试程序已在运行，请勿重复打开。")
                app.quit()
            except Exception:
                pass
            sys.exit(1)
        # attach 失败 = 上次崩溃留下的残留锁，清掉重来
        if not _shm.create(1):
            try:
                app = QApplication(sys.argv)
                QMessageBox.warning(None, "提示", "测试程序已在运行，请勿重复打开。")
                app.quit()
            except Exception:
                pass
            sys.exit(1)
    _TEST_SHM_HANDLE = _shm
    # 解析 --purpose= 参数（由 real_installer 修复功能传入，use 模式跳过训练相关测试）
    global _PURPOSE
    for arg in sys.argv:
        if arg.startswith("--purpose="):
            _PURPOSE = arg.split("=", 1)[1]
            break
    # 读取 test.pyw 所在目录的 install_components.json 作为用途兜底。
    # 只认 _APP_DIR（所在目录）的配置：磁盘文件为准、json 兜底，
    # 不读 cwd / 注册表 InstallLocation 的配置，避免跨目录误识别
    # （例如开发目录运行却按注册表指向的安装副本判定用途）。
    _components_file = os.path.join(_APP_DIR, "install_components.json")
    if os.path.exists(_components_file):
        try:
            with open(_components_file, encoding="utf-8") as f:
                _PURPOSE = json.load(f).get("purpose", _PURPOSE)
        except Exception:
            pass
    # CLI 模式：跳过 GUI，直接跑测试
    if "--cli" in sys.argv:
        no_slow = "--no-slow" in sys.argv
        sys.exit(run_cli(no_slow=no_slow))

    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    app = QApplication(sys.argv)
    app.setApplicationName("我的世界旗帜逆向工具箱测试")

    # 统一弹窗图标：QMessageBox 系统弹窗图标 56px（250% 放大规律，与 error_reporter 等自定义弹窗一致）
    from PyQt5.QtWidgets import QProxyStyle, QStyle as _QStyle
    class _MsgBoxIconStyle(QProxyStyle):
        def pixelMetric(self, metric, option=None, widget=None):
            if metric == _QStyle.PM_MessageBoxIconSize:
                return 56
            return super().pixelMetric(metric, option, widget)
    app.setStyle(_MsgBoxIconStyle(app.style()))

    # 使用 QApplication 获取屏幕逻辑尺寸（与 trainer.pyw 一致，避免 DPI 双重缩放）
    screen = app.primaryScreen()
    if screen:
        sw = screen.size().width()
        sh = screen.size().height()
        ui_scale = max(min(sw / 1920, sh / 1080), 1.0)
        scale = min(ui_scale * 1.25, 2.5)
    else:
        scale = 1.0

    app.setFont(QFont("Microsoft YaHei UI", max(int(9 * scale), 9)))

    root = _APP_DIR
    if root not in sys.path:
        sys.path.insert(0, root)

    window = TestWindow(scale=scale)
    window._center_on_screen(screen)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
