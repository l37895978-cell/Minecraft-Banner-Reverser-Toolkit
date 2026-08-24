"""我的世界旗帜逆向套件 — 使用说明窗口

独立运行的帮助窗口，展示使用教程。
支持深浅色模式（读取 config/config.json 的 theme 设置）。
支持与设置窗口一致的缩放机制（--scale 参数或屏幕自动检测）。
可从训练器、导入器、识别器、启动器的"帮助 → 使用说明"菜单打开。
通过 --section 参数跳转到对应章节（trainer/importer/reverser/overview）。
单实例模式：若已有窗口，则通过临时文件通知已有窗口跳转到对应章节。
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

import json
import argparse
import ctypes
import tempfile

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTextBrowser, QVBoxLayout, QWidget,
    QPushButton, QHBoxLayout, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from utils.settings_manager import apply_dwm_dark_mode, apply_theme, resolve_theme


# 单实例通知文件（用于传递 --section 给已运行的实例）
_INSTANCE_NOTIFY_FILE = os.path.join(tempfile.gettempdir(), "banner_help_section_notify.txt")


def _ensure_single_instance():
    """用全局 Mutex 保证 help 窗口只能打开一个。返回 True 表示是首个实例。"""
    mutex_name = "Global\\BannerToolHelpSingleInstance"
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    already_exists = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    if already_exists:
        kernel32.CloseHandle(mutex)
        return False
    # 保持 mutex 引用，防止 GC 释放
    _ensure_single_instance._mutex = mutex
    return True


def _notify_existing_instance(section):
    """通知已运行的实例跳转到指定章节（通过临时文件）。"""
    try:
        with open(_INSTANCE_NOTIFY_FILE, "w", encoding="utf-8") as f:
            f.write(section or "overview")
    except Exception:
        pass


def _consume_notify_section():
    """读取并清除通知文件，返回章节名或 None。"""
    try:
        if os.path.exists(_INSTANCE_NOTIFY_FILE):
            with open(_INSTANCE_NOTIFY_FILE, "r", encoding="utf-8") as f:
                section = f.read().strip()
            os.remove(_INSTANCE_NOTIFY_FILE)
            return section if section else None
    except Exception:
        pass
    return None


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
            return data.get("theme", "light")
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


# 章节锚点定义（--section 值 → HTML 锚点 id）
SECTION_ANCHORS = {
    "overview": "sec-overview",
    "startup": "sec-startup",
    "importer": "sec-importer",
    "trainer": "sec-trainer",
    "reverser": "sec-reverser",
    "mbtl": "sec-mbtl",
    "mbtlx": "sec-mbtlx",
    "installer": "sec-installer",
    "diagnostic": "sec-diagnostic",
    "faq": "sec-faq",
}


def _build_stylesheet(is_dark, scale):
    """根据主题和缩放生成全局样式表（字号公式与 settings 一致）。"""
    base_fs = max(int(13 * scale), 13)
    btn_fs = max(int(14 * scale), 14)
    pad_v = max(int(8 * scale), 6)
    pad_h = max(int(24 * scale), 18)
    text_pad_v = max(int(20 * scale), 14)
    text_pad_h = max(int(30 * scale), 20)

    if is_dark:
        bg = "#2d2d30"
        fg = "#eeeeee"
        border = "#555555"
        link = "#4fc3f7"
        btn_hover = "#1e3a5f"
        code_bg = "#3c3c3c"
        scroll_handle = "#555555"
        scroll_hover = "#666666"
    else:
        bg = "#ffffff"
        fg = "#1a1a1a"
        border = "#cccccc"
        link = "#1a73e8"
        btn_hover = "#e8f1fb"
        code_bg = "#f5f5f5"
        scroll_handle = "#c0c0c0"
        scroll_hover = "#999999"

    return f"""
        QMainWindow {{ background-color: {bg}; }}
        QTextBrowser {{
            background-color: {bg};
            color: {fg};
            border: none;
            font-size: {base_fs}px;
            line-height: 1.8;
            padding: {text_pad_v}px {text_pad_h}px;
        }}
        QPushButton {{
            background-color: transparent;
            color: {link};
            border: 1px solid {link};
            border-radius: 6px;
            padding: {pad_v}px {pad_h}px;
            font-size: {btn_fs}px;
            min-height: {max(int(20 * scale), 18)}px;
        }}
        QPushButton:hover {{
            background-color: {btn_hover};
        }}
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
        QScrollBar:add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
            border: none;
            background: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
    """


def _build_html(is_dark, scale):
    """构建帮助内容HTML（字号随缩放比例缩放）。"""
    h1_fs = max(int(28 * scale), 24)
    h2_fs = max(int(22 * scale), 18)
    h3_fs = max(int(18 * scale), 15)
    body_fs = max(int(15 * scale), 14)
    small_fs = max(int(14 * scale), 12)
    tiny_fs = max(int(13 * scale), 11)
    code_fs = max(int(13 * scale), 11)
    cell_pad = max(int(8 * scale), 6)

    if is_dark:
        title_color = "#ffffff"
        h2_color = "#4fc3f7"
        h3_color = "#81c784"
        code_bg = "#3c3c3c"
        code_fg = "#ffb74d"
        note_bg = "#1a2a1a"
        note_border = "#4a7a4a"
        warn_bg = "#3a2a1a"
        warn_border = "#7a5a3a"
        text_color = "#eeeeee"
    else:
        title_color = "#1a1a1a"
        h2_color = "#1a73e8"
        h3_color = "#2e7d32"
        code_bg = "#f5f5f5"
        code_fg = "#c62828"
        note_bg = "#e8f5e9"
        note_border = "#4caf50"
        warn_bg = "#fff3e0"
        warn_border = "#ff9800"
        text_color = "#333333"

    return f"""
    <html><body style="color:{text_color}; line-height:1.8; font-family: 'Microsoft YaHei UI', sans-serif; font-size:{body_fs}px;">

    <h1 id="sec-overview" style="color:{title_color}; text-align:center; font-size:{h1_fs}px; margin-bottom:5px;">我的世界旗帜逆向套件 — 使用说明</h1>
    <p style="text-align:center; color:#888; font-size:{small_fs}px;">版本 v0.5 beta1 (1.0.8)</p>

    <hr style="border:none; border-top:1px solid {code_bg}; margin:20px 0;"/>

    <h2 style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">一、项目概述</h2>
    <p>我的世界旗帜逆向套件是一套 Minecraft 风格旗帜的创建、训练与 AI 逆向识别系统，包含四个组件：</p>
    <ul>
        <li><b>启动器</b> — 统一入口，四宫格界面启动各模块</li>
        <li><b>旗帜训练导入器</b> — 旗帜图案编辑器，用于创建和编辑旗帜</li>
        <li><b>旗帜训练器</b> — AI 训练引擎，基于 ViT 架构进行旗帜学习</li>
        <li><b>旗帜印染逆向器</b> — 旗帜图片逆向识别工具（识别器）</li>
    </ul>
    <p>训练器和导入器联动运行：关闭任一窗口，另一个自动关闭。识别器独立运行，但与训练工具互斥（避免资源冲突）。</p>

    <h2 id="sec-startup" style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">二、启动方式</h2>
    <table style="width:100%; border-collapse:collapse; margin:10px 0; font-size:{body_fs}px;">
        <tr style="background-color:{code_bg};">
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};"><b>方式</b></td>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};"><b>说明</b></td>
        </tr>
        <tr>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">双击 start.pyw</td>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">启动器四宫格，选择要进入的模块</td>
        </tr>
        <tr>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">双击 trainer.pyw</td>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">训练器(左) + 导入器(右) 联动启动</td>
        </tr>
        <tr>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">双击 importer.pyw</td>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">同上，从导入器启动</td>
        </tr>
        <tr>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">双击 bdor.pyw</td>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">独立运行旗帜识别器</td>
        </tr>
        <tr>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">双击 .mbtl 文件</td>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">需训练工具已启动，导入器自动加载</td>
        </tr>
    </table>

    <h2 id="sec-importer" style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">三、旗帜训练导入器</h2>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">3.1 编辑旗帜</h3>
    <ul>
        <li><b>背景颜色</b>：16 种标准颜色（索引 0~15）</li>
        <li><b>图案添加</b>：选择图案类型和颜色后点击添加</li>
        <li><b>图案层管理</b>：选中已添加的图案可上移/下移/删除</li>
        <li>每面旗帜最多 16 层图案，图案类型索引 0~43</li>
    </ul>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">3.2 批量生成</h3>
    <p>随机生成区域包含两个标签页：</p>
    <ul>
        <li><b>普通生成</b>：设置生成数量、颜色数范围、图案数范围</li>
        <li><b>纠偏生成</b>：
            <ul>
                <li>颜色纠偏：基于已有旗帜，通过控制变量法生成对比数据</li>
                <li>图案纠偏：随机替换图案类型，颜色不变</li>
            </ul>
        </li>
    </ul>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">3.3 保存与导出</h3>
    <ul>
        <li><b>保存旗帜</b>：编辑完成后点击"保存"，旗帜加入序列列表</li>
        <li><b>导出到训练器</b>：数据自动传输至旗帜训练器</li>
        <li><b>导出序列文件</b>：将序列保存为 .mbtl 文件</li>
    </ul>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">3.4 序列图组导入</h3>
    <p>切换到「序列图组导入」标签页，可以导入真实图片并为每张图片标记对应的旗帜数据，用于训练识别器。</p>
    <ul>
        <li>导入图片后，在右侧编辑旗帜数据（背景色 + 图案层）</li>
        <li>点击「导出标记」保存为 <code>.mbtlx</code> 文件（图片自包含）</li>
        <li>可在「序列图组训练」标签页中导入 .mbtlx 进行训练</li>
    </ul>

    <h2 id="sec-trainer" style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">四、旗帜训练器</h2>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">4.1 训练参数</h3>
    <ul>
        <li><b>训练轮数</b>：1~100（默认 10）</li>
        <li><b>批次大小</b>：1~32（默认 8）</li>
        <li><b>学习率</b>：0.001 / 0.0001 / 0.00001（默认 0.0001）</li>
    </ul>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">4.2 两阶段训练</h3>
    <ul>
        <li><b>冻结阶段</b>（前 1/3 轮）：冻结 ViT backbone，只训练分类头</li>
        <li><b>微调阶段</b>（后 2/3 轮）：解冻 ViT 最后 4 层，降低学习率微调</li>
    </ul>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">4.3 模型保存与加载</h3>
    <ul>
        <li>模型保存在 models/model_file/ 目录，文件名带时间戳（如 banner_vit_model_20250101_120000.pth）</li>
        <li>点击"保存模型"手动保存当前模型权重</li>
        <li>点击"继续训练"加载已有模型继续训练</li>
        <li>识别器点击"加载默认模型"自动加载目录中最新的 .pth 文件</li>
        <li>模型文件包含架构信息（model_arch），防止架构不匹配</li>
    </ul>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">4.4 序列图组训练（Tab2）</h3>
    <p>切换到「序列图组训练」标签页，使用真实图片数据进行训练：</p>
    <ol>
        <li>点击"导入 .mbtlx"加载标记文件</li>
        <li>设置训练参数（训练轮数、批次大小、学习率）</li>
        <li>点击"开始训练"启动训练过程</li>
        <li>训练完成后点击"保存模型"保存权重</li>
    </ol>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">4.5 训练加速模式</h3>
    <p>训练器支持三种计算后端，在「设置 → 训练环境」中选择：</p>
    <ul>
        <li><b>CUDA</b>（NVIDIA 独显，RTX 20 系及以上，含 RTX 50 系）：速度最快，推荐 NVIDIA 用户优先使用。需 NVIDIA 驱动 ≥570（CUDA 13.0 要求）。GTX 10 系及以下不支持 CUDA，请用 CPU 模式。</li>
        <li><b>DirectML</b>（实验性·AMD / Intel 显卡通用加速）：让无 NVIDIA 独显的玩家也能用上 GPU 加速。速度约为 CUDA 的 1/3~1/5，但比纯 CPU 快 2~5 倍。</li>
        <li><b>CPU</b>：任何电脑均可运行，速度极慢，作为兜底方案。</li>
    </ul>
    <div style="background-color:{warn_bg}; border-left:4px solid {warn_border}; padding:10px 15px; margin:10px 0;">
        <p><b>关于 DirectML（实验性）：</b></p>
        <ul>
            <li>torch-directml 是微软发布的<b>预览版</b>（尚未推出正式版），可能存在偶发问题。</li>
            <li>个别运算不支持 GPU 时会自动回退 CPU 执行，此时速度骤降属正常现象。</li>
            <li>长时间训练可能因显存碎片出现"显存不足"提示——本软件已内置定期清理机制缓解，仍触发时会弹出错误窗口，降低批次大小后重试即可。</li>
            <li><b>不会损坏电脑</b>：最坏情况是训练任务失败，关闭软件后显存自动释放，不影响显卡、文件或系统。</li>
        </ul>
    </div>
    <p><b>GPU 加速说明：</b>DirectML 模式专为 AMD / Intel 核显设计，无 NVIDIA 独显时同样可获得 GPU 加速。有 NVIDIA 独显请优先使用 CUDA；无独显时使用 DirectML；追求稳定可选用 CPU。</p>

    <h2 id="sec-reverser" style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">五、旗帜印染逆向器</h2>

    <p>旗帜印染逆向器（识别器）是基于 Vision Transformer 的旗帜图片逆向识别工具，能从 Minecraft 旗帜图片中还原出旗帜的染色序列（背景色 + 图案层）。</p>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">5.1 界面介绍</h3>
    <ul>
        <li><b>模型区域</b>（左上）：加载/管理 AI 模型，显示当前模型状态</li>
        <li><b>输入区域</b>（右上）：导入旗帜图片，显示待识别图片预览</li>
        <li><b>结果区域</b>（下方）：显示识别结果，包括序列信息和还原预览图</li>
    </ul>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">5.2 使用流程</h3>
    <ol>
        <li><b>加载模型</b>：
            <ul>
                <li>点击「加载默认模型」自动加载 models/model_file/ 下最新的 .pth 文件</li>
                <li>或点击「选择模型文件」手动选择模型</li>
                <li>可在设置中开启"启动时自动加载默认模型"</li>
            </ul>
        </li>
        <li><b>导入旗帜图片</b>：
            <ul>
                <li>点击「从文件导入」选择本地图片文件</li>
                <li>或点击「从剪贴板导入」直接粘贴截图</li>
                <li>支持的格式：PNG / JPG / JPEG / BMP</li>
            </ul>
        </li>
        <li><b>执行识别</b>：点击「逆向印染」按钮开始识别</li>
        <li><b>查看结果</b>：
            <ul>
                <li>序列信息区显示识别出的背景色和图案层（带中文颜色名）</li>
                <li>还原预览区显示根据识别结果重新渲染的旗帜图片</li>
                <li>可复制序列数据或导出为 .mbtl 文件</li>
            </ul>
        </li>
    </ol>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">5.3 推理设备</h3>
    <ul>
        <li><b>自动</b>（默认）：优先使用 CUDA（NVIDIA 显卡），其次 DirectML（AMD/Intel），无 GPU 时回退到 CPU</li>
        <li><b>CUDA</b>：强制使用 NVIDIA GPU 推理（需 RTX 20 系及以上 + CUDA 环境）</li>
        <li><b>DirectML</b>：使用 AMD/Intel GPU 推理（实验性，需 torch-directml）</li>
        <li><b>CPU</b>：强制使用 CPU 推理（兼容性最好，速度最慢）</li>
        <li>可在设置 → 识别器设置中修改默认推理设备</li>
    </ul>
    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>硬件兼容性：</b>识别器与训练器共享 GPU 兼容性检测。
        <ul>
            <li>NVIDIA：需 RTX 20 系及以上，6GB+ 显存</li>
            <li>Intel 核显：需 Iris Xe（11代+）、UHD 770（12代+）或 Arc 独显</li>
            <li>AMD 核显：需 Vega 7+、Radeon 660M+ 或 RDNA2/3 iGPU（780M/890M 等）</li>
            <li>不满足最低要求时会提示并建议使用 CPU 模式</li>
        </ul>
    </div>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">5.4 注意事项</h3>
    <div style="background-color:{warn_bg}; border-left:4px solid {warn_border}; padding:10px 15px; margin:10px 0;">
        <ul>
            <li>识别器与训练工具互斥：训练器/导入器运行时无法启动识别器，反之亦然</li>
            <li>识别准确度取决于训练数据的质量和数量，建议每种颜色至少 20 个样本</li>
            <li>输入图片应为清晰的旗帜截图，背景尽量干净</li>
            <li>首次使用需先训练并保存模型（保存到 models/model_file/ 目录）</li>
        </ul>
    </div>

    <h2 id="sec-mbtl" style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">六、数据格式（MBTL）</h2>
    <p><b>MBTL</b> 全称 <b>Minecraft Banner Train List</b>（我的世界旗帜训练列表），是本软件自定义的旗帜序列数据格式。<br/>
    文件扩展名为 <code>.mbtl</code>，用于保存一组旗帜的完整数据（背景色 + 图案层），供训练器批量加载训练。<br/>
    <b>防撞车提示</b>：此格式为本软件专属，与其他软件的 .mbtl 文件（如有）不兼容。</p>
    <div style="background-color:{code_bg}; padding:12px; border-radius:6px; font-family:Consolas,monospace; font-size:{code_fs}px; color:{code_fg};">
        魔数(4B): "MBTL"<br/>
        版本(2B): 0x0001<br/>
        数量(4B): N<br/>
        每面旗帜: 背景色(1B) + 图案层数(1B) + [图案类型(1B) + 图案颜色(1B)] × 层数
    </div>

    <h2 id="sec-mbtlx" style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">七、序列图组标记格式（MBTLX）</h2>

    <p><b>MBTLX</b> 全称 <b>Minecraft Banner Train List eXtreme</b>（我的世界旗帜训练列表·扩展版），<br/>
    在 MBTL 基础上增加了图片自包含能力——图片数据直接打包进文件，不依赖外部路径。<br/>
    文件扩展名为 <code>.mbtlx</code>，用于保存一组「图片—旗帜」的对应关系。<br/>
    <b>核心原则：一张图片对应一面旗帜</b>，与普通训练一致，只是数据来源为用户标记的真实图片而非程序生成的旗帜图。<br/>
    <b>防撞车提示</b>：.mbtlx 实际是 ZIP 压缩包，但内部结构为本软件专属，不可当普通 ZIP 使用。</p>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">7.1 文件结构（ZIP 格式）</h3>
    <p>.mbtlx 实际是一个 ZIP 压缩包，自包含所有图片和标记数据，结构如下：</p>
    <div style="background-color:{code_bg}; padding:12px; border-radius:6px; font-family:Consolas,monospace; font-size:{code_fs}px; color:{code_fg};">
        banner.mbtlx (ZIP)<br/>
        ├── marks.json&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;标记数据<br/>
        └── images/<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;├── 0001.png&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;图片1<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;├── 0002.png&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;图片2<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;└── ...
    </div>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">7.2 marks.json 格式</h3>
    <div style="background-color:{code_bg}; padding:12px; border-radius:6px; font-family:Consolas,monospace; font-size:{code_fs}px; color:{code_fg};">
        {{<br/>
        &nbsp;&nbsp;"version": "2.0",<br/>
        &nbsp;&nbsp;"items": [<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;{{<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"image": "images/0001.png",<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"original_path": "C:\\\\banners\\\\banner1.png",<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"banners": [<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{{<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"x": null, "y": null, "w": null, "h": null,<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"data": [5, 3, 7, 1, 2]<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;}}<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;]<br/>
        &nbsp;&nbsp;&nbsp;&nbsp;}}<br/>
        &nbsp;&nbsp;]<br/>
        }}
    </div>
    <p>字段说明：</p>
    <ul>
        <li><b>image</b>：ZIP 内的图片相对路径</li>
        <li><b>original_path</b>：导出时的原始图片路径（仅记录，导入时使用 ZIP 内图片）</li>
        <li><b>banners</b>：旗帜标记数组（当前 1:1 模式下只有 1 个，未来支持多对多）
            <ul>
                <li><b>x/y/w/h</b>：旗帜在图片中的区域坐标（当前为 null，未来多对多时使用）</li>
                <li><b>data</b>：旗帜数据数组 <code>[背景色, 图案类型1, 图案颜色1, 图案类型2, 图案颜色2, ...]</code></li>
            </ul>
        </li>
    </ul>

    <h3 style="color:{h3_color}; font-size:{h3_fs}px;">7.3 创建与使用流程</h3>
    <ol>
        <li>在<b>旗帜训练导入器</b>中切换到「序列图组导入」标签页</li>
        <li>导入图片后，为每张图片标记对应的旗帜数据（背景色 + 图案层）</li>
        <li>点击「导出标记」按钮，保存为 <code>.mbtlx</code> 文件（图片会打包进文件）</li>
        <li>在<b>旗帜训练器</b>中切换到「序列图组训练」标签页</li>
        <li>导入 <code>.mbtlx</code> 文件，开始批量训练</li>
    </ol>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>提示：</b>新格式 .mbtlx 自包含图片，移动或删除原图片不影响使用。<br/>
        颜色编号（0~15）和图案类型编号（0~43）与普通旗帜数据一致，详见导入器中的颜色/图案列表。
    </div>

    <div style="background-color:{warn_bg}; border-left:4px solid {warn_border}; padding:10px 15px; margin:10px 0;">
        <b>注意：</b>序列图组训练仍遵循「一张图片对应一面旗帜」的原则，并非在一张图片中识别多面旗帜。<br/>
        <b>向后兼容：</b>导入器仍支持旧版文本格式 .mbtlx（每行 <code>图片路径|背景色;颜色-类型/...</code>），但导出始终使用新 ZIP 格式。
    </div>

    <h2 id="sec-installer" style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">八、安装程序</h2>
    <p>安装程序（demo_installer.pyw）提供完整的安装向导，包含硬件检测、安装路径选择、组件安装等流程。</p>
    <ul>
        <li><b>安装流程</b>：初始化检测 → 欢迎 → 使用声明 → 使用目的 → 功能选择 → 模型架构 → 库路径 → 安装进度 → 完成</li>
        <li><b>维护模式</b>：已安装时进入维护页面，可管理模型、文件修复或卸载</li>
        <li><b>文件修复</b>：诊断文件完整性（哈希校验），一键修复损坏或丢失的文件</li>
        <li><b>演示模式</b>：当环境模拟器（visualcondition.pyw）存在时自动启用，可模拟不同设备环境</li>
    </ul>
    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>演示模式独立化：</b>安装程序本身是标准安装器。将演示模式文件（visualcondition.pyw）放入 installer/ 目录后，
        启动时会自动进入演示模式，可选择模拟设备并自定义问题。不放入则直接扫描本机真实环境。
    </div>

    <h2 id="sec-diagnostic" style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">九、诊断工具</h2>
    <p>诊断工具（test.pyw）用于自动化测试所有功能模块，发现潜在问题。</p>
    <ul>
        <li><b>16 类测试</b>：依赖库检查、项目模块导入、配置管理、硬件检测、资源分配、模型架构、MBTL 文件 IO、旗帜图像生成、模型创建与推理（慢）、错误处理、文件关联、工作区布局、硬件兼容性检测、DirectML 子进程协议、文档与帮助系统、安装与快捷方式</li>
        <li><b>测试失败 → 修复入口</b>：检测到问题时，结果窗口显示「进入修复界面」按钮，一键启动安装程序的修复页</li>
        <li><b>模拟环境支持</b>：读取演示模式配置，在模拟环境下检测硬件兼容性问题</li>
        <li><b>文档校验</b>：检测帮助文档（help.pyw / 使用说明.txt）与安装程序、演示模式文件的可导入性</li>
        <li>运行方式：双击 test.pyw 或命令行 <code>python test.pyw --cli</code></li>
    </ul>

    <h2 id="sec-faq" style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">十、常见问题</h2>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 训练后颜色识别不准？</b><br/>
        A: 确保训练数据量充足（每种颜色至少 20 个样本），使用纠偏生成的颜色纠偏模式补充混淆颜色对。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 训练进行中无法导入新数据？</b><br/>
        A: 这是防破坏机制，请先停止训练再导入。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 旗帜识别器找不到模型？</b><br/>
        A: 先在训练器中训练并保存模型，默认保存到 models/model_file/ 目录。识别器点击「加载默认模型」会自动查找该目录下最新的 .pth 文件。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 识别器启动时提示"训练工具正在运行"？</b><br/>
        A: 识别器与训练工具互斥，请先关闭训练器和导入器，再启动识别器。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 识别结果偏差较大？</b><br/>
        A: 1) 确认模型已充分训练；2) 输入图片应为清晰的旗帜截图，背景干净；3) 尝试使用序列图组训练（Tab2）用真实图片训练以提升准确度。
    </div>

    <div style="background-color:{warn_bg}; border-left:4px solid {warn_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 双击 .mbtl 文件提示"请先启动旗帜训练工具"？</b><br/>
        A: 需要先启动训练工具，再双击 .mbtl 文件。导入器启动后会自动检测并加载文件。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: DirectML 训练时提示"显存不足"？</b><br/>
        A: DirectML 无法限制显存上限，长时间训练可能因碎片化触发。降低批次大小（如 4 或 2），或定期暂停让软件自动清理缓存。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 我的显卡支持训练吗？</b><br/>
        A: NVIDIA 需 RTX 20 系及以上（6GB+ 显存）。Intel 核显需 Iris Xe（11代+）或 UHD 770（12代+）。
        AMD 核显需 Vega 7+ 或 RDNA2/3 iGPU（780M/890M 等）。不满足时建议使用 CPU 模式或升级硬件。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 诊断工具检测到问题怎么办？</b><br/>
        A: 在测试结果窗口点击「进入修复界面」按钮，启动安装程序的修复页面，可一键修复损坏或丢失的文件。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 如何启动安装程序？</b><br/>
        A: 双击 <code>installer/demo_installer.pyw</code> 即可启动安装向导。首次安装时会依次进行硬件检测、使用声明、功能选择、模型架构与库路径配置；已安装时进入维护页面，可管理模型、修复文件或卸载。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 演示模式和真实安装有什么区别？如何启用演示模式？</b><br/>
        A: 演示模式用于在不改动本机环境的前提下，模拟不同设备（2014~2026 年各类型机型）的安装流程。<br/>
        启用方式：将 <code>visualcondition.pyw</code> 文件放入 <code>installer/</code> 目录，启动安装程序时会自动进入演示模式，先选择模拟设备并自定义问题，再走完整安装流程。<br/>
        不放入该文件则直接扫描本机真实环境，进行真实安装。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 演示模式中可以自定义哪些问题？</b><br/>
        A: 在环境模拟器第三步可勾选要模拟的问题，包括：<br/>
        bdor.pyw 损坏、预训练权重缺失、config.json 损坏、硬件缓存过期、trainer.pyw 损坏、图标目录缺失、模型架构文件损坏、.mbtl 旗帜文件格式不兼容等。<br/>
        勾选后这些问题会写入 <code>banner_sim_config.json</code>，安装程序的修复界面会据此生成诊断结果与修复步骤。
    </div>

    <div style="background-color:{warn_bg}; border-left:4px solid {warn_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 安装程序提示"硬件不兼容"怎么办？</b><br/>
        A: 硬件不达标时会给出具体原因（如显存不足、核显型号过旧、系统版本过低等）。<br/>
        - 显存不足：降低训练批次大小，或退选 CUDA/DirectML 改用 CPU 模式；<br/>
        - 核显过旧：Intel 需 Iris Xe（11代+）/ UHD 770（12代+），AMD 需 Vega 7+ 或 RDNA2/3 iGPU；<br/>
        - 系统版本过低：需 Windows 10 1903+ 或 Windows 11，旧版本请先升级系统。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: .mbtl 和 .mbtlx 文件有什么区别？</b><br/>
        A: <code>.mbtl</code> 是二进制旗帜序列文件，体积小，仅保存旗帜数据（背景色 + 图案层），用于训练器和导入器之间传递旗帜序列。<br/>
        <code>.mbtlx</code> 是 ZIP 压缩包格式，自包含图片和标记数据，用于「序列图组训练」时导入真实图片。两者用途不同，互不替代。
    </div>

    <div style="background-color:{warn_bg}; border-left:4px solid {warn_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 训练器异常退出，显示返回码是什么意思？</b><br/>
        A: 返回码是 Windows 进程退出时的状态码，常见类型：<br/>
        <table style="border-collapse:collapse; width:100%; font-size:{small_fs}px;">
        <tr style="background-color:{code_bg};"><th style="border:1px solid #555; padding:4px;">返回码</th><th style="border:1px solid #555; padding:4px;">十六进制</th><th style="border:1px solid #555; padding:4px;">含义</th><th style="border:1px solid #555; padding:4px;">常见原因</th></tr>
        <tr><td style="border:1px solid #555; padding:4px;">3221225477</td><td style="border:1px solid #555; padding:4px;">0xC0000005</td><td style="border:1px solid #555; padding:4px;">内存访问违规</td><td style="border:1px solid #555; padding:4px;">PyTorch 或 CUDA 驱动 bug、显存损坏、DLL 版本不匹配</td></tr>
        <tr><td style="border:1px solid #555; padding:4px;">3221226505</td><td style="border:1px solid #555; padding:4px;">0xC0000409</td><td style="border:1px solid #555; padding:4px;">栈缓冲区溢出</td><td style="border:1px solid #555; padding:4px;">PyTorch C++ 扩展内部 bug、CUDA 内核崩溃、内存损坏</td></tr>
        <tr><td style="border:1px solid #555; padding:4px;">3221225725</td><td style="border:1px solid #555; padding:4px;">0xC00000FD</td><td style="border:1px solid #555; padding:4px;">栈溢出</td><td style="border:1px solid #555; padding:4px;">递归过深、模型层数过多导致内存耗尽</td></tr>
        <tr><td style="border:1px solid #555; padding:4px;">3221225485</td><td style="border:1px solid #555; padding:4px;">0xC000001D</td><td style="border:1px solid #555; padding:4px;">非法指令</td><td style="border:1px solid #555; padding:4px;">CPU 不支持某些指令集（如 AVX）、DLL 架构不匹配</td></tr>
        <tr><td style="border:1px solid #555; padding:4px;">3221225616</td><td style="border:1px solid #555; padding:4px;">0xC0000135</td><td style="border:1px solid #555; padding:4px;">DLL 缺失</td><td style="border:1px solid #555; padding:4px;">缺少 VC++ 运行库或 CUDA DLL</td></tr>
        <tr><td style="border:1px solid #555; padding:4px;">3221225474</td><td style="border:1px solid #555; padding:4px;">0xC0000002</td><td style="border:1px solid #555; padding:4px;">DLL 初始化失败</td><td style="border:1px solid #555; padding:4px;">DLL 加载时初始化失败，通常是依赖项版本冲突</td></tr>
        </table>
        <br/>
        <b>处理建议：</b><br/>
        1. 返回码 0xC0000005 / 0xC0000409：通常是 PyTorch 或 GPU 驱动的底层 bug。尝试更新显卡驱动、降低批次大小、或切换 CPU 模式；<br/>
        2. 返回码 0xC00000FD：模型过大或内存不足，减少模型层数或增加物理内存；<br/>
        3. 返回码 0xC000001D：CPU 指令集不支持，安装对应版本的 PyTorch（CPU 版）；<br/>
        4. 返回码 0xC0000135：安装或修复 VC++ 运行库（2015-2022 x64）；<br/>
        5. 若频繁崩溃且返回码固定，请将错误日志反馈给开发者。
    </div>

    <div style="background-color:{note_bg}; border-left:4px solid {note_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 提示"QThread: Destroyed while thread is still running"怎么办？</b><br/>
        A: 这表示后台线程（通常是模型加载线程）尚未结束时窗口被关闭。本版本已改进线程生命周期管理（线程不再随窗口自动销毁，关闭时会等待最多 15 秒）。<br/>
        <b>注意</b>：此提示常与返回码 <code>3221226505</code>（0xC0000409 栈缓冲区溢出）同时出现——这说明是 PyTorch/CUDA 底层崩溃导致进程退出，QThread 警告只是附带症状。请按上方返回码处理建议排查根本原因（更新显卡驱动、切换 CPU 模式等）。
    </div>

    <hr style="border:none; border-top:1px solid {code_bg}; margin:20px 0;"/>
    <p style="text-align:center; color:#888; font-size:{tiny_fs}px;">如遇其他问题请反馈。本版本为 v0.5 beta1 (1.0.8)。</p>

    </body></html>
    """


class HelpWindow(QMainWindow):
    def __init__(self, scale=None, section=None):
        super().__init__()
        self.setWindowTitle("使用说明 — 我的世界旗帜逆向套件")

        # 缩放比例：优先用传入值，否则从屏幕检测
        if scale is None or scale <= 0:
            scale = _detect_scale()
        self._scale = max(scale, 1.0)

        # 窗口尺寸与 settings 一致：720x560 * scale，最大宽度 900 * scale
        w = int(720 * self._scale)
        h = int(560 * self._scale)
        self.setMinimumSize(w, h)
        self.setMaximumWidth(int(900 * self._scale))
        self.resize(w, h)

        # 读取主题
        self._theme = resolve_theme(_get_theme())
        self._is_dark = (self._theme == "dark")
        try:
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "config", "config.json"
            )
            self._config_mtime = os.path.getmtime(config_path)
        except Exception:
            self._config_mtime = 0

        # 中央部件
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 帮助内容
        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        self.text_browser.setHtml(_build_html(self._is_dark, self._scale))
        layout.addWidget(self.text_browser, 1)

        # 底部按钮栏
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(int(15 * self._scale), int(10 * self._scale), int(15 * self._scale), int(10 * self._scale))
        btn_bar.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_bar.addWidget(close_btn)
        layout.addLayout(btn_bar)

        # 应用样式
        self.setStyleSheet(_build_stylesheet(self._is_dark, self._scale))
        apply_dwm_dark_mode(self, self._is_dark)

        # 初始跳转到指定章节
        if section:
            QTimer.singleShot(50, lambda: self._scroll_to_section(section))

        # 主题同步定时器（与主窗口一致的 mtime 检测）
        self._theme_timer = QTimer(self)
        self._theme_timer.timeout.connect(self._sync_theme)
        self._theme_timer.start(1000)

        # 单实例通知检测定时器（检测其他进程发来的 --section 跳转请求）
        self._notify_timer = QTimer(self)
        self._notify_timer.timeout.connect(self._check_notify_section)
        self._notify_timer.start(500)

        # 居中显示
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.x() + (geo.width() - self.width()) // 2,
                geo.y() + (geo.height() - self.height()) // 2
            )

    def _scroll_to_section(self, section):
        """滚动到指定章节锚点。"""
        anchor = SECTION_ANCHORS.get(section, "sec-overview")
        self.text_browser.scrollToAnchor(anchor)

    def _check_notify_section(self):
        """检测其他进程发来的 --section 跳转请求。"""
        section = _consume_notify_section()
        if section:
            self._scroll_to_section(section)
            # 激活并置顶窗口
            self.raise_()
            self.activateWindow()
            self.showNormal()

    def _sync_theme(self):
        """定时检查 config.json 主题变化（mtime优化，与主窗口同步）。"""
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

            new_theme = resolve_theme(_get_theme())
            if new_theme != self._theme:
                self._theme = new_theme
                self._is_dark = (new_theme == "dark")
                self.text_browser.setHtml(_build_html(self._is_dark, self._scale))
                self.setStyleSheet(_build_stylesheet(self._is_dark, self._scale))
                apply_dwm_dark_mode(self, self._is_dark)
        except Exception:
            pass


def main():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, default=0.0)
    parser.add_argument("--section", type=str, default="",
                        help="跳转章节：overview/startup/importer/trainer/reverser/mbtl/mbtlx/installer/diagnostic/faq")
    args = parser.parse_args()

    # 单实例限制：若已有窗口，则通过临时文件通知跳转
    if not _ensure_single_instance():
        _notify_existing_instance(args.section)
        ctypes.windll.user32.MessageBoxW(
            0, "帮助窗口已经打开，已跳转到对应章节。",
            "提示", 64  # MB_ICONINFORMATION
        )
        return

    # 软件渲染（必须在 QApplication 创建前设置）：保证 agent 截图稳定可识别
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", app.font().pointSize()))

    # 应用全局调色板（让原生元素跟随深浅色主题）
    apply_theme(app, resolve_theme(_get_theme()))

    scale = args.scale if args.scale > 0 else None
    window = HelpWindow(scale, section=args.section if args.section else None)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
