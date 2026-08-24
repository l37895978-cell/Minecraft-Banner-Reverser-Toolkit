"""我的世界旗帜逆向套件 — 安装程序

参照 Python 官方安装包（.exe）样式：左侧侧图 + 右侧内容 + 底部按钮栏。

流程：
  初始化（硬件/软件环境检测 + 安装状态检测）
    ├─ 未安装 → 欢迎 → 使用声明 → 使用目的 → 库选择 → 安装 → 结束
    └─ 已安装 → 维护页（安装训练工具 / 文件修复 / 卸载）

侧图预留：images/banner/installer_banner.png（可替换为实际图片）

运行：python installer/real_installer.pyw
"""
import sys
import os
# 注意：不调用 SetProcessDpiAwareness/SetProcessDPIAware，交由系统处理 DPI 缩放，
# 所有 UI 尺寸/字体仅随分辨率 scale 变化，杜绝 DPI 对大小的二次放大。
# pythonw.exe 启动时 stdout/stderr 为 None，必须最早修复
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
import re
import json
import time
import zipfile
import shutil
import subprocess
import tempfile
import urllib.request

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 软件渲染：强制 Qt 走 CPU 软件渲染，兼容自动化 agent（截图/OCR/坐标点击）。
# 硬件加速合成时部分截图工具抓不到窗口内容（黑屏/花屏），软件渲染可保证内容稳定可识别。
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

# Qt 平台插件引导：确保 pythonw.exe 启动时能找到 qwindows.dll 和 Qt5Core.dll 等
_VENDOR_PKGS = os.path.join(_PROJECT_ROOT, "Lib", "site-packages")
_qt5_dir = os.path.join(_VENDOR_PKGS, "PyQt5", "Qt5")
if os.path.isdir(_qt5_dir):
    _qt_bin = os.path.join(_qt5_dir, "bin")
    _qt_plugins = os.path.join(_qt5_dir, "plugins")
    if os.path.isdir(_qt_bin) and _qt_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _qt_bin + os.pathsep + os.environ.get("PATH", "")
    if os.path.isdir(_qt_plugins):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(_qt_plugins, "platforms")
        os.environ.setdefault("QT_PLUGIN_PATH", _qt_plugins)
# 应用目录优先加载依赖
if os.path.isdir(_VENDOR_PKGS) and _VENDOR_PKGS not in sys.path:
    sys.path.insert(0, _VENDOR_PKGS)

# 早期异常捕获：在 PyQt5 等第三方库导入前生效，捕获导入/启动阶段的致命错误
def _early_crash_handler(exc_type, exc_value, exc_tb):
    import traceback as _tb_mod
    import subprocess as _sp_mod
    tb_str = "".join(_tb_mod.format_exception(exc_type, exc_value, exc_tb))
    _src = "安装器"
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

from PyQt5.QtWidgets import (
    QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QCheckBox, QRadioButton, QLineEdit, QFileDialog,
    QProgressBar, QFrame, QGroupBox, QTextEdit, QScrollArea, QMessageBox,
    QButtonGroup, QSizePolicy, QLayout, QComboBox, QSplashScreen, QProgressDialog
)

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRect, QTimer, QSize, QProcess
from PyQt5.QtGui import QFont, QPainter, QColor, QLinearGradient, QPixmap, QIcon


# ===== 调试日志（临时，定位问题后删除）=====
import datetime as _dt
def _dbg(msg):
    try:
        p = os.path.join(os.environ.get('TEMP', os.getcwd()), 'installer_debug.log')
        with open(p, 'a', encoding='utf-8') as f:
            f.write(f"{_dt.datetime.now().strftime('%H:%M:%S')} | {msg}\n")
    except Exception:
        pass

_dbg(f"脚本启动: frozen={getattr(sys, 'frozen', False)}, exe={sys.executable}")


# ===== 缩放 =====
# 与解码版 real_installer.pyw（exe 原版）100% 一致的双公式：
#   raw        = min(sw / 1920, sh / 1080)
#   win_scale  = min(max(raw, 1.0) * 1.25, 2.5)   # 窗口/控件几何缩放
#   font_scale = max(min(raw, 1.4) * 1.1, 0.85)   # 字体缩放（与 win_scale 不同）
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


def _is_system_dark():
    """检测系统是否为深色模式（读注册表）。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except Exception:
        return False


def _apply_dwm_dark(hwnd, is_dark):
    """设置窗口标题栏深色/浅色（DWM API）。"""
    try:
        if not hwnd:
            return
        import ctypes as _ct
        _ct.windll.dwmapi.DwmSetWindowAttribute(
            int(hwnd), 20, _ct.byref(_ct.c_int(1 if is_dark else 0)), _ct.sizeof(_ct.c_int()))
    except Exception:
        pass


def _show_43_dialog(parent, title, text, icon_type="info", buttons=None, half=False):
    """统一风格的信息/确认弹窗：1:1 固定比例（基准 240×240），与「升级到新版本」确认框一致的原生样式。

    所有安装器小弹窗统一使用：标题在窗口标题栏、标准图标（加大 48）+ 消息文本
    （超长可滚动，Win11 滚动条）、底部按钮右对齐（Win11 样式：主蓝 #4a90d9 /
    次级灰），固定浅色（无深色模式残留）。文字/按钮沿用应用默认字号，
    与「升级到新版本」确认框的大小关系一致。
    icon_type: "info" / "warning" / "critical"
    buttons: None=仅「确认」按钮，返回 None；("否", "是")=双按钮确认框，返回 True/False。
    half: 兼容旧调用参数（保留，统一按 240×240 基准显示）。
    """
    from PyQt5.QtWidgets import QTextBrowser, QStyle
    app = QApplication.instance()
    win_scale, font_scale = _ui_scales(app)

    # 按钮/背景/主色均沿用安装器界面样式（#1a73e8）；内容文字 24px、图标 56（×font_scale）；滚轮 Win11 风格保留。

    dlg = QDialog(parent)
    dlg.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
    dlg.setWindowTitle(title)
    # 固定浅色标题栏（视觉统一，无深色残留）
    _apply_dwm_dark(int(dlg.winId()), False)
    # 安装界面样式：浅灰背景（与安装向导页面一致）
    dlg.setStyleSheet("QDialog { background-color: #f5f5f5; }")

    # 1:1 固定比例（基准 240×240，随分辨率等比放大）
    w = int(240 * win_scale)
    h = int(240 * win_scale)
    dlg.setFixedSize(w, h)

    layout = QVBoxLayout(dlg)
    margin = int(16 * win_scale)
    layout.setContentsMargins(margin, int(14 * win_scale), margin, int(14 * win_scale))
    layout.setSpacing(int(12 * win_scale))

    # 消息行：标准图标 + 文本（图标加大）
    msg_row = QHBoxLayout()
    msg_row.setSpacing(int(12 * win_scale))
    icon_size = max(int(56 * font_scale), 40)
    icon_lbl = QLabel()
    style = app.style()
    if style:
        sp = QStyle.SP_MessageBoxInformation if icon_type == "info" else (
            QStyle.SP_MessageBoxWarning if icon_type == "warning" else QStyle.SP_MessageBoxCritical)
        pm = style.standardIcon(sp).pixmap(icon_size, icon_size)
        if pm:
            icon_lbl.setPixmap(pm)
    icon_lbl.setFixedSize(icon_size, icon_size)
    msg_row.addWidget(icon_lbl, 0, Qt.AlignTop)

    # 可滚动文本：内容文字 24px（×font_scale），透明边框，Win11 风格滚动条
    text_fs = max(int(24 * font_scale), 17)
    text_browser = QTextBrowser()
    text_browser.setPlainText(text)
    text_browser.setReadOnly(True)
    text_browser.setLineWrapMode(QTextBrowser.WidgetWidth)
    text_browser.setFrameShape(QFrame.NoFrame)
    text_browser.setStyleSheet(f"""
        QTextBrowser {{
            background: transparent; border: none; font-size: {text_fs}px;
            selection-background-color: #cce4f7; selection-color: #1a1a1a;
        }}
        QScrollBar:vertical {{
            background: transparent; width: {max(int(8 * win_scale), 6)}px;
            margin: {max(int(2 * win_scale), 1)}px; border: none;
        }}
        QScrollBar::handle:vertical {{
            background: #c1c1c1; border-radius: {max(int(4 * win_scale), 3)}px;
            min-height: 20px; margin: 0px {max(int(1 * win_scale), 1)}px;
        }}
        QScrollBar::handle:vertical:hover {{ background: #9e9e9e; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px; background: none; border: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    """)
    msg_row.addWidget(text_browser, 1)
    layout.addLayout(msg_row, 1)

    # 按钮：底部右对齐，浅色现代样式（不填充主色，Windows 11 风格按钮）
    btn_layout = QHBoxLayout()
    btn_layout.addStretch()
    _result = [False]
    _btn_h = max(int(28 * win_scale), 24)
    _btn_w = max(int(96 * win_scale), 84)
    _btn_qss = (
        "QPushButton { background: #fafafa; color: #1a1a1a;"
        " border: 1px solid #d9d9d9; border-radius: 6px; padding: 6px 16px; }"
        "QPushButton:hover { background: #f0f0f0; }"
        "QPushButton:pressed { background: #e5e5e5; }"
    )
    if buttons is None:
        btn_ok = QPushButton("确认")
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setMinimumHeight(_btn_h)
        btn_ok.setMinimumWidth(_btn_w)
        btn_ok.setStyleSheet(_btn_qss)
        btn_ok.clicked.connect(dlg.accept)
        btn_layout.addWidget(btn_ok)
    else:
        btn_no = QPushButton(buttons[0])
        btn_yes = QPushButton(buttons[1])
        btn_no.setCursor(Qt.PointingHandCursor)
        btn_yes.setCursor(Qt.PointingHandCursor)
        btn_no.setMinimumHeight(_btn_h)
        btn_no.setMinimumWidth(_btn_w)
        btn_yes.setMinimumHeight(_btn_h)
        btn_yes.setMinimumWidth(_btn_w)
        btn_no.setStyleSheet(_btn_qss)
        btn_yes.setStyleSheet(_btn_qss)
        btn_no.clicked.connect(lambda: (_result.__setitem__(0, False), dlg.accept()))
        btn_yes.clicked.connect(lambda: (_result.__setitem__(0, True), dlg.accept()))
        btn_layout.addWidget(btn_no)
        btn_layout.addWidget(btn_yes)
    layout.addLayout(btn_layout)

    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    # Win32 强制置顶
    try:
        import ctypes as _ct
        hwnd = int(dlg.winId())
        _ct.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040)
        _ct.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    dlg.exec_()
    return _result[0] if buttons else None


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


def _find_icon_path(ico_name):
    """查找图标文件路径，兼容 frozen 与开发模式。

    frozen (onefile) 状态：
      1) 先查 exe 同目录（外置资源）
      2) 再查 sys._MEIPASS（打包内置资源）
    开发模式：
      从项目根目录的 images/icons/ 下查找。
    """
    rel = os.path.join("images", "icons", ico_name)
    if getattr(sys, 'frozen', False):
        ext = os.path.join(os.path.dirname(sys.executable), rel)
        if os.path.exists(ext):
            return ext
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            mp = os.path.join(meipass, rel)
            if os.path.exists(mp):
                return mp
        return ext
    return os.path.join(_PROJECT_ROOT, rel)


# ===== 安装状态检测 =====
# 老名称（兼容旧版用户）
_OLD_DIR_NAME = "旗帜编织逆向器"
# 新名称（新用户默认）
_DIR_NAME = "我的世界旗帜逆向套件"

_DEFAULT_INSTALL_PATHS = [
    # 默认安装位置（仅新名称；老名称=开发环境，不纳入）
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), _DIR_NAME),
    # 桌面/文档（路径选择页提供这两个常用位置，必须纳入固定检测）
    os.path.join(os.path.expanduser("~"), "Desktop", _DIR_NAME),
    os.path.join(os.path.expanduser("~"), "Documents", _DIR_NAME),
    r"C:\Program Files\\" + _DIR_NAME,
]
_COMPONENTS_FILE = "install_components.json"
_APP_VERSION = "1.0.8"                # 内部版本号（写入 install_components.json / 注册表 / version_info.txt）
_UI_VERSION = "v0.5 beta1 (1.0.8)"   # 界面显示版本（1.0.8 为 0.5 beta1 的子版本号，与窗口标题/训练器一致）
# 开发环境特征：单一隐藏目录 .dev_marker/identity.json
# 集中存放开发者身份标记，避免散落在根目录的多个文件被误删/误改
# 卸载流程只删除安装目录，不会触碰开发目录的 .dev_marker/
_DEV_MARKER_DIR = ".dev_marker"
_DEV_MARKER_FILE = "identity.json"


def _is_dev_marker_dir(directory):
    """判断 directory 是否为开发环境（含 .dev_marker/identity.json 且 JSON 合法）。"""
    if not directory:
        return False
    marker_path = os.path.join(directory, _DEV_MARKER_DIR, _DEV_MARKER_FILE)
    if not os.path.isfile(marker_path):
        return False
    try:
        with open(marker_path, encoding="utf-8") as f:
            data = json.load(f) or {}
        # 验证 role 字段为 developer，避免任意 JSON 误判
        return data.get("role") == "developer"
    except Exception:
        return False


def _is_valid_install_dir(path):
    """多层验证：判断一个目录是否是本软件的真实安装目录。

    验证层（全部通过才返回 True）：
    1) 目录存在且不是根目录/系统目录
    2) 不含开发环境特征文件（downloader.spec / installer/ / bdor.pyw）
    3) 含 install_components.json（唯一锚定文件，安装步骤6创建）
    4) install_components.json 是有效 JSON 且 name 字段是我们的软件名
    """
    if not path or not os.path.isdir(path):
        return False

    # 层1：排除根目录、系统目录、过短路径
    abs_path = os.path.abspath(path)
    if len(abs_path) <= 3:  # 如 C:\
        return False
    for forbidden in (r"C:\Windows", r"C:\Program Files", r"C:\Program Files (x86)"):
        if abs_path.lower() == forbidden.lower():
            return False

    # 层2：排除开发目录（含 .dev_marker/identity.json 标记）
    if _is_dev_marker_dir(abs_path):
        return False

    # 层3：含 install_components.json（唯一锚定文件）
    comp_path = os.path.join(abs_path, _COMPONENTS_FILE)
    if not os.path.isfile(comp_path):
        return False

    # 层4：install_components.json 是有效 JSON 且 name 字段是我们的软件名
    try:
        with open(comp_path, encoding="utf-8-sig") as f:
            data = json.load(f) or {}
        if data.get("name") != _DIR_NAME:
            return False
    except Exception:
        return False

    return True

# 身份标记文件名（放目录根，内容如 "role=dev"）
_BUILD_TAG_FILE = "build_tag.txt"

# 目标安装目录名集合（用于全盘扫描匹配；老名称=开发环境，不纳入）
_TARGET_DIR_NAMES = {_DIR_NAME}


def _read_identity(directory):
    """读取 directory/build_tag.txt 的 role 字段，返回 dev/tester/user/None。"""
    if not directory:
        return None
    tag = os.path.join(directory, _BUILD_TAG_FILE)
    if not os.path.isfile(tag):
        return None
    try:
        with open(tag, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("role="):
                    return line[5:].strip().lower() or None
    except Exception:
        pass
    return None


def _detect_dev_env():
    """检测当前是否运行在开发源文件目录，返回开发根路径或 None。

    识别机制（单一特征）：开发根目录下含 .dev_marker/identity.json 文件
    且 JSON 内 role 字段为 "developer"。

    非打包运行：_PROJECT_ROOT 指向 installer 父目录（开发根），直接检查。
    打包运行：_PROJECT_ROOT 指向 _MEIPASS 临时目录（无 .dev_marker/），
              需从 sys.executable 向上查找——开发者通常在 dist/ 或 exe/ 子目录跑 exe，
              其父目录即为开发根；普通用户把 exe 复制到别处则不会误判。

    检测策略：向上 3 级查找 + 扫描 exe 同目录的子文件夹（1 级深度）。
    覆盖场景：exe 在项目 exe/ 子目录、exe 在项目根目录、
              exe 在桌面而项目文件夹也在桌面（同级兄弟目录）。
    单一特征 + role=developer 验证，普通用户目录不会有此文件，不会误判。
    """
    if _is_dev_marker_dir(_PROJECT_ROOT):
        return _PROJECT_ROOT
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        # 1) exe 所在目录 → 父目录 → 祖父目录（最多向上 3 级）
        d = exe_dir
        for _ in range(3):
            if _is_dev_marker_dir(d):
                return d
            parent = os.path.dirname(d)
            if not parent or parent == d:
                break
            d = parent
        # 2) exe 同目录的子文件夹（1 级深度）——exe 在桌面、项目在桌面子文件夹的场景
        try:
            for sub in os.listdir(exe_dir):
                sub_path = os.path.join(exe_dir, sub)
                if os.path.isdir(sub_path) and _is_dev_marker_dir(sub_path):
                    return sub_path
        except Exception:
            pass
    return None


def _scan_for_install_dir(timeout=8.0, validator=None):
    """全盘扫描查找已安装目录（兜底，注册表/固定路径都找不到时用）。

    扫描范围：桌面、用户目录、文档、C/D/E 盘根、C:/Users、D:/Users
    限制深度 2 层 + 超时保护，避免卡死。返回找到的安装目录路径或 None。
    validator: 目录验证函数（默认 _is_valid_install_dir；残留检测传 _is_leftover_dir）
    """
    import time
    check = validator or _is_valid_install_dir
    home = os.path.expanduser("~")
    scan_roots = [
        os.path.join(home, "Desktop"),
        home,
        os.path.join(home, "Documents"),
        "C:\\",
        "D:\\",
        "E:\\",
        "C:\\Users",
        "D:\\Users",
    ]
    start = time.time()
    for root in scan_roots:
        if not os.path.isdir(root):
            continue
        try:
            for entry in os.scandir(root):
                if time.time() - start > timeout:
                    return None
                if not entry.is_dir(follow_symlinks=False):
                    continue
                # 深度1：直接匹配目标目录名
                if entry.name in _TARGET_DIR_NAMES:
                    if check(entry.path):
                        return entry.path
                # 深度2：在子目录里找（如 C:\Users\<user>\旗帜编织逆向器）
                try:
                    for sub in os.scandir(entry.path):
                        if time.time() - start > timeout:
                            return None
                        if sub.is_dir(follow_symlinks=False) and sub.name in _TARGET_DIR_NAMES:
                            if check(sub.path):
                                return sub.path
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            continue
    return None


def _is_leftover_dir(path):
    """判断是否为卸载残留目录（锚定文件已丢失但目录名匹配）。

    场景：上次卸载时个别文件被占用（如 trainer 日志句柄），锚定文件已被删除、
    目录壳残留 → _is_valid_install_dir 永远返回 False，
    导致残留目录再也无法被卸载器识别和清理（表现为"假卸载"）。

    安全层（与 _is_valid_install_dir 对齐）：
      1) 不是根目录/系统目录
      2) 目录名必须是目标安装名（我的世界旗帜逆向套件/旗帜编织逆向器）
      3) 不含开发环境特征文件
    """
    if not path or not os.path.isdir(path):
        return False
    abs_path = os.path.abspath(path)
    if len(abs_path) <= 3:  # 如 C:\
        return False
    for forbidden in (r"C:\Windows", r"C:\Program Files", r"C:\Program Files (x86)"):
        if abs_path.lower() == forbidden.lower():
            return False
    if os.path.basename(abs_path) not in _TARGET_DIR_NAMES:
        return False
    # 排除开发目录（含 .dev_marker/identity.json）
    if _is_dev_marker_dir(abs_path):
        return False
    return True


def _find_leftover_dir(timeout=8.0):
    """查找卸载残留目录：固定路径优先，全盘扫描兜底。返回路径或 None。"""
    for p in _DEFAULT_INSTALL_PATHS:
        if _is_leftover_dir(p):
            return p
    return _scan_for_install_dir(timeout=timeout, validator=_is_leftover_dir)


def _quick_detect_install():
    """毫秒级快速检测：只检查注册表 + 固定路径 + 桌面路径。
    已安装时直接返回，避免显示检测页。不做全盘扫描和开发者身份检测。
    """
    state = {"installed": False, "path": None, "version": None,
             "components": [], "archs": [], "models": [],
             "identity": None, "dev_path": None, "leftover": False}

    # 1) 注册表
    try:
        import winreg
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(
                    root,
                    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MinecraftBannerReverser")
                reg_path, _ = winreg.QueryValueEx(key, "InstallLocation")
                reg_ver, _ = winreg.QueryValueEx(key, "DisplayVersion")
                winreg.CloseKey(key)
                if _is_valid_install_dir(reg_path):
                    state["path"] = reg_path
                    state["version"] = reg_ver
                    state["installed"] = True
                    return state
            except FileNotFoundError:
                continue
    except Exception:
        pass

    # 2) 固定路径 + 桌面路径
    home = os.path.expanduser("~")
    quick_paths = list(_DEFAULT_INSTALL_PATHS)
    quick_paths.append(os.path.join(home, "Desktop", _DIR_NAME))
    for p in quick_paths:
        if _is_valid_install_dir(p):
            state["installed"] = True
            state["path"] = p
            return state

    return state


def detect_install_state():
    """检测电脑是否已安装本软件 + 识别运行身份，返回综合状态。

    身份三档次（优先级 dev > tester > user）：
        dev    : 高级开发者/作者（开发源文件目录，build_tag.txt 标 dev）
        tester : 测试人员（作者分发测试包时 exe 同目录附 build_tag.txt 标 tester）
        user   : 普通用户（安装完成后自动生成 build_tag.txt 标 user）

    Returns: dict {installed, path, version, components, archs, models,
                   identity, dev_path}
    """
    state = {"installed": False, "path": None, "version": None,
             "components": [], "archs": [], "models": [],
             "identity": None, "dev_path": None, "leftover": False}

    # 0) 作者环境：检测到开发根即视为 dev 身份（build_tag.txt 可选）
    #    _detect_dev_env 通过 .dev_marker/identity.json 单一特征 + role=developer 验证，
    #    无需 build_tag.txt 额外验证——开发者目录必然含此标记文件。
    dev_path = _detect_dev_env()
    if dev_path:
        state["identity"] = "dev"
        state["dev_path"] = dev_path
        # 作者环境也尝试读已安装状态（可能在 LOCALAPPDATA 装过）

    # 1) 注册表卸载项（命中后必须二次验证——防止注册表残留导致"显示已安装但实际没安装"）
    try:
        import winreg
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(
                    root,
                    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MinecraftBannerReverser")
                reg_path, _ = winreg.QueryValueEx(key, "InstallLocation")
                reg_ver, _ = winreg.QueryValueEx(key, "DisplayVersion")
                winreg.CloseKey(key)
                if _is_valid_install_dir(reg_path):
                    state["path"] = reg_path
                    state["version"] = reg_ver
                    state["installed"] = True
                    break
                else:
                    # 注册表残留但目录无效（文件被删/不完整）：清理残留项，视为未安装
                    _dbg(f"注册表残留但目录无效，清理: {reg_path}")
                    try:
                        winreg.DeleteKey(
                            root,
                            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MinecraftBannerReverser")
                    except Exception:
                        pass
                    continue
            except FileNotFoundError:
                continue
    except Exception:
        pass

    # 2) 固定路径回退（多层验证，避免误判开发目录）
    if not state["installed"]:
        for p in _DEFAULT_INSTALL_PATHS:
            if _is_valid_install_dir(p):
                state["installed"] = True
                state["path"] = p
                break

    # 3) 全盘扫描兜底（注册表 + 固定路径都找不到时）
    #    扫描范围含桌面/文档/各盘根——桌面等自定义安装位置依赖此检测。
    #    dev 环境也扫描：开发目录含开发标记，_is_valid_install_dir 会安全排除。
    if not state["installed"]:
        scanned = _scan_for_install_dir()
        if scanned:
            state["installed"] = True
            state["path"] = scanned

    # 3.5) 卸载残留兜底：锚定文件已丢但目录名匹配的目录（上次卸载未删干净），
    #      仍允许进入维护模式执行卸载清理，否则残留目录永远无法被卸载器识别
    if not state["installed"]:
        leftover = _find_leftover_dir()
        if leftover:
            state["installed"] = True
            state["path"] = leftover
            # 只有真正没有 install_components.json 的目录才算"卸载残留"
            # 有效安装目录（有锚定文件）不显示"卸载残留"文案
            if not _is_valid_install_dir(leftover):
                state["leftover"] = True

    # 4) 读取组件清单
    if state["installed"] and state["path"]:
        comp_file = os.path.join(state["path"], _COMPONENTS_FILE)
        if os.path.exists(comp_file):
            try:
                with open(comp_file, encoding="utf-8-sig") as f:
                    data = json.load(f) or {}
                    state["components"] = data.get("components", []) or []
                    state["archs"] = data.get("archs", []) or []
                    state["models"] = data.get("models", []) or []
            except Exception:
                pass

    # 5) 身份识别（非 dev 时）：exe 同目录 build_tag.txt → 安装目录 build_tag.txt
    #    dev 也可从安装目录识别（_detect_dev_env 失败时兜底，dev_path=安装目录）
    if state["identity"] != "dev":
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
            else os.path.dirname(os.path.abspath(__file__))
        # 优先：exe 同目录的 build_tag.txt（作者分发测试包时附带）
        role = _read_identity(exe_dir)
        if role in ("tester", "user"):
            state["identity"] = role
        elif state["installed"] and state["path"]:
            # 其次：安装目录的 build_tag.txt（安装后生成）
            role = _read_identity(state["path"])
            if role in ("dev", "tester", "user"):
                state["identity"] = role
                if role == "dev":
                    state["dev_path"] = state["path"]
            else:
                state["identity"] = "tester"  # 已安装但无标记 = 测试人员（默认）
        # 否则 identity 保持 None（未安装）

    return state


# ===== Windows API 硬件检测 =====
def _w32_get_os():
    """通过 kernel32 获取 Windows 版本（带 Build 号的可读名称）。"""
    try:
        build = _w32_get_os_build()
        ver_name = "Windows 11" if build >= 22000 else "Windows 10"
        return f"{ver_name} (Build {build})"
    except Exception:
        try:
            import platform
            return f"Windows {platform.release()}"
        except Exception:
            return "Windows 版本未知"


def _w32_get_os_build():
    """获取 Windows Build 号（纯整数，失败时返回 0）。

    用于判断系统是否满足最低版本要求：
      - Windows 10 1909 = Build 18363
      - Windows 11 = Build 22000+
    """
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
        return int(osvi.dwBuildNumber or 0)
    except Exception:
        return 0


def _w32_get_python():
    """检测系统安装的 Python 运行时。

    返回 dict:
      - current: 当前运行时版本（如 "Python 3.13.14"）
      - system: 系统已安装的 Python 版本列表（通过注册表检测）
      - has_python: 系统是否安装了 Python 3.10.11+（含 3.10.11/3.11/3.12/3.13）
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

    # 检查是否有 >= 3.10.11 的 Python（3.10.11/3.11/3.12/3.13+）
    has_python = False
    for sv in system_versions:
        parts = sv.split(".")
        if len(parts) >= 2:
            try:
                if int(parts[0]) == 3 and int(parts[1]) >= 10:
                    has_python = True
                    break
            except ValueError:
                pass
    if not has_python:
        has_python = (v.major == 3 and v.minor >= 10)

    return {
        "current": current,
        "system": sorted(set(system_versions)),
        "has_python": has_python,
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


def _norm_gpu(name):
    """归一化 GPU 名称：去除 (R)/(TM)/(C) 商标标记，压缩空白，转小写。
    使 "Intel(R) Iris(R) Xe Graphics" → "intel iris xe graphics"，
    确保白名单关键词 "iris xe" 能正确匹配。
    """
    import re as _re
    s = _re.sub(r'\s*\((?:tm|r|c)\)\s*', ' ', (name or '').lower())
    return _re.sub(r'\s+', ' ', s).strip()


# NVIDIA RTX 20 系列及以上（按名称关键字判断最低代数）
_RTX_20PLUS = ("rtx 20", "rtx 30", "rtx 40", "rtx 50", "rtx a", "a100", "a6000",
               "quadro rtx", "tesla t4", "tesla a", "l4", "h100", "a10", "a40")

# ── GPU 白名单（与 utils/device_backend.py 保持一致，归一化后匹配）──
# 关键词已去除 (R)/(TM) 标记，因为 _norm_gpu() 会对 GPU 名称做同样处理

# Intel 核显/独显 黑名单（性能不足，不支持 DirectML）
_INTEL_BLACKLIST = (
    "uhd graphics 730",   # Alder Lake 24EU
    "uhd graphics 750",   # Rocket Lake 32EU
    "uhd graphics 32",    # Alder Lake 32EU 版本
)

# Intel 核显/独显 白名单
_INTEL_GPU_WHITELIST = (
    "iris xe", "iris xe max",           # 11代+ Iris Xe / DG1
    "uhd graphics 770",                 # 12/13代桌面
    "arc graphics", "arc 7", "arc 8",   # Meteor Lake 集成
    "arc 140v", "arc 130v",            # Lunar Lake
    "arc a", "arc b",                   # Arc 独显 A310~A770, B570~B580
)

# AMD 核显 黑名单
_AMD_BLACKLIST = (
    "radeon graphics",  # Ryzen 7000 桌面核显（仅 2 CU RDNA2）
)

# AMD 核显/独显 白名单（按具体型号匹配）
_AMD_GPU_SUPPORTED = (
    "vega 7", "vega 8", "vega 10", "vega 11",           # Ryzen 2000-5000 APU
    "radeon 660m", "radeon 680m",                        # RDNA2 Ryzen 6000
    "radeon 760m", "radeon 780m",                        # RDNA3 Ryzen 7000
    "radeon 840m", "radeon 860m", "radeon 880m", "radeon 890m",  # RDNA3.5 Ryzen 8000/9000
    "radeon 8040s", "radeon 8050s", "radeon 8060s",    # Ryzen AI Max
    "radeon rx",                                         # AMD 独显全系列
)


def _gpu_supports_dml(gpu_entry):
    """检查 GPU 是否支持 DirectML（仅看黑名单，不要求满足训练性能要求）。

    与 _w32_check_gpu_requirement 的区别：
    - _w32_check_gpu_requirement 判断「是否满足训练最低要求」（含内存/白名单）
    - _gpu_supports_dml 判断「GPU 是否支持 DirectML 运行时」（仅排除黑名单中过旧型号）

    内存不足或型号不在白名单中不影响 DirectML 可用性，只影响训练速度。
    """
    if not gpu_entry:
        return False
    vendor = gpu_entry.get("vendor", "")
    name_lower = _norm_gpu(gpu_entry.get("name", ""))
    if vendor == "intel":
        return not any(kw in name_lower for kw in _INTEL_BLACKLIST)
    if vendor == "amd":
        return not any(kw in name_lower for kw in _AMD_BLACKLIST)
    if vendor == "nvidia":
        return True
    return False


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


def _w32_get_nvidia_driver_version():
    """通过 nvidia-smi 获取 NVIDIA 驱动版本号（如 "551.61"）。

    返回 (major, minor) 元组，如 (551, 61)。失败返回 (0, 0)。
    用于判断驱动是否支持 CUDA 12.4（需要 >= 551.61）。
    """
    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode == 0 and r.stdout.strip():
            ver_str = r.stdout.strip().split("\n")[0].strip()
            parts = ver_str.split(".")
            if len(parts) >= 2:
                return (int(parts[0]), int(parts[1]))
    except Exception:
        pass
    return (0, 0)


# CUDA 13.0 最低 NVIDIA 驱动版本（Windows）：570.0
# 来源：https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html
# RTX 20系及以上显卡（Turing+）升级到最新驱动后都能支持 CUDA 13.0
# cu130 支持 sm_75~sm_120（RTX 20~50 系全覆盖）
_NVIDIA_DRIVER_MIN_FOR_CU130 = (570, 0)
# 向后兼容：旧名保留（指向新常量，避免遗漏引用）
_NVIDIA_DRIVER_MIN_FOR_CU124 = _NVIDIA_DRIVER_MIN_FOR_CU130


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
        nvidia_driver = (0, 0)
        if vendor == "nvidia" and not is_igpu:
            smi_vram = _w32_get_nvidia_vram_gb()
            if smi_vram > 0:
                vram_gb = smi_vram
            nvidia_driver = _w32_get_nvidia_driver_version()
        # 核显共享内存：报告系统内存的 25% 作为分配显存
        if is_igpu and vram_gb < 1:
            vram_gb = round(_w32_get_ram_gb() * 0.25, 1)
        all_gpus.append({
            "vendor": vendor, "name": gname,
            "vram_gb": round(vram_gb, 1), "is_integrated": is_igpu,
            "nvidia_driver": nvidia_driver,
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
        name_lower = _norm_gpu(discrete.get("name", ""))
        vram = discrete.get("vram_gb", 0)
        if vendor == "nvidia":
            if not any(kw in name_lower for kw in _RTX_20PLUS):
                reasons.append((f"独显 {discrete['name']}：需 RTX 20 系及以上", False))
            elif vram < 6:
                reasons.append((f"独显 {discrete['name']}：显存 {vram}GB 不足（需 ≥6GB）", False))
            else:
                # 检查 NVIDIA 驱动版本是否支持 CUDA 13.0（torch 2.9.1+cu130）
                drv = discrete.get("nvidia_driver", (0, 0))
                drv_str = f"{drv[0]}.{drv[1]}" if drv[0] > 0 else "未知"
                if drv >= _NVIDIA_DRIVER_MIN_FOR_CU130:
                    reasons.append((f"独显 {discrete['name']}（{vram}GB，驱动 {drv_str}）：CUDA 可用，DirectML 也可选", True))
                    any_ok = True
                else:
                    reasons.append((f"独显 {discrete['name']}（{vram}GB，驱动 {drv_str}）："
                                   f"驱动版本过低，需升级到 {_NVIDIA_DRIVER_MIN_FOR_CU130[0]}.{_NVIDIA_DRIVER_MIN_FOR_CU130[1]}+ 才能用 CUDA，"
                                   f"可先用 CPU 模式或 DirectML", True))
                    any_ok = True
        elif vendor in ("amd", "intel"):
            if vram >= 4:
                reasons.append((f"独显 {discrete['name']}（{vram}GB）：DirectML 可用", True))
                any_ok = True
            else:
                reasons.append((f"独显 {discrete['name']}：显存 {vram}GB 不足", False))

    if integrated:
        vendor = integrated.get("vendor", "none")
        name_lower = _norm_gpu(integrated.get("name", ""))
        if vendor == "intel":
            # 先查黑名单
            if any(kw in name_lower for kw in _INTEL_BLACKLIST):
                reasons.append((f"核显 {integrated['name']}：型号过旧，不支持 DirectML", False))
            elif not any(kw in name_lower for kw in _INTEL_GPU_WHITELIST):
                reasons.append((f"核显 {integrated['name']}：需 Iris Xe / Arc / UHD 770+", False))
            elif ram_gb < 15:
                reasons.append((f"核显 {integrated['name']}：系统内存 {ram_gb}GB 不足（需 ≥16GB）", False))
            else:
                reasons.append((f"核显 {integrated['name']}：DirectML 可用", True))
                any_ok = True
        elif vendor == "amd":
            # 先查黑名单
            if any(kw in name_lower for kw in _AMD_BLACKLIST):
                reasons.append((f"核显 {integrated['name']}：型号过旧，不支持 DirectML", False))
            elif not any(kw in name_lower for kw in _AMD_GPU_SUPPORTED):
                reasons.append((f"核显 {integrated['name']}：需 Vega 7+ 或 RDNA2+", False))
            elif ram_gb < 15:
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
            "os": "", "os_build": 0, "python": "", "cpu": "", "ram_gb": 0.0,
            "gpu": {}, "gpu_ok": False, "gpu_reason": "",
            "disk_free_gb": 0.0,
            "install_state": {"installed": False, "path": None, "version": None,
                              "components": [], "archs": [], "models": [],
                              "identity": None, "dev_path": None},
        }
        _dbg("InitThread.run() 开始")
        try:
            self._run_impl(info)
        except Exception as e:
            _dbg(f"InitThread 异常: {e}")
            try:
                self.line.emit(f"检测过程中出现异常: {e}", False)
            except Exception:
                pass
        finally:
            _dbg(f"InitThread 结束: identity={info['install_state'].get('identity')}, "
                 f"dev_path={info['install_state'].get('dev_path')}, "
                 f"installed={info['install_state'].get('installed')}")
            self.finished_all.emit(info)

    def _run_impl(self, info):
        STEP_DELAY = 0.3

        # ★ 安装状态检测放最前面——即使后续硬件检测崩溃，identity 也能正确传递
        try:
            state = detect_install_state()
        except Exception as e:
            state = {"installed": False, "path": None, "version": None,
                     "components": [], "archs": [], "models": [],
                     "identity": None, "dev_path": None}
            self.line.emit(f"已安装状态：检测异常 ({e})", False)
        info["install_state"] = state
        ident = state.get("identity")
        if ident == "dev":
            self.line.emit(
                f"已安装状态：开发环境（作者）- 源文件目录：{state.get('dev_path', '')}", True)
        elif state.get("installed"):
            ver = state.get("version") or "未知版本"
            comps = len(state.get("components", []))
            tag = {"tester": "测试版本", "user": "已安装"}.get(ident, "已安装")
            self.line.emit(
                f"已安装状态：{tag}（{ver}，{comps} 个组件，路径：{state.get('path')}）", True)
            # ★ 已安装：跳过硬件检测，直接进入维护模式（提速 ~2 秒）
            self.line.emit("进入维护模式...", True)
            return
        elif ident == "tester":
            self.line.emit("已安装状态：测试版本（未安装，将进行全新安装）", True)
        else:
            self.line.emit("已安装状态：未安装（将进行全新安装）", True)

        # 操作系统
        try:
            info["os"] = _w32_get_os()
            info["os_build"] = _w32_get_os_build()
            self.line.emit(f"操作系统：{info['os']}", True)
        except Exception:
            self.line.emit("操作系统：检测失败", False)
        time.sleep(STEP_DELAY)

        # Python
        try:
            if getattr(sys, 'frozen', False):
                # 安装包模式：DirectML 环境（dml_env）改为安装时在线构建（不再内嵌 1.2GB），
                # 系统 Python 仅在 CUDA/CPU 模式需要，初始化阶段不作硬性要求
                sys_py_list = []
                try:
                    import winreg
                    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                        try:
                            key = winreg.OpenKey(hive, r"Software\Python\PythonCore")
                            i = 0
                            while True:
                                try:
                                    sn = winreg.EnumKey(key, i)
                                    i += 1
                                    if sn.startswith("3."):
                                        sys_py_list.append(sn)
                                except OSError:
                                    break
                            winreg.CloseKey(key)
                        except OSError:
                            pass
                except Exception:
                    pass
                info["python"] = "内置环境就绪"
                info["python_has_ok"] = any(
                    True for v in sys_py_list
                    if v.startswith("3.") and int(v.split(".")[1]) >= 10
                )
                if info["python_has_ok"]:
                    self.line.emit(
                        "Python 运行时：内置环境就绪（系统 Python " +
                        "/".join(sorted(set(sys_py_list))) + "，CUDA 模式可用）", True)
                else:
                    self.line.emit(
                        "Python 运行时：内置环境就绪（DirectML 模式直接可用；CUDA 模式安装时可自动配置）",
                        True)
            else:
                py_info = _w32_get_python()
                info["python"] = py_info["current"]
                info["python_has_ok"] = py_info["has_python"]
                if py_info["has_python"]:
                    self.line.emit(f"Python 运行时：{py_info['current']}", True)
                else:
                    sys_versions = ", ".join(py_info["system"]) if py_info["system"] else "未检测到"
                    self.line.emit(
                        f"Python 运行时：{py_info['current']}（系统: {sys_versions}，需要 {PYTHON_VERSION_MIN_STR}+）",
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

        time.sleep(STEP_DELAY * 0.6)


# ===== 真实安装常量 =====
# 主程序（UI：trainer/importer/bdor/start/help/settings）支持 Python 3.10~3.13+
# 检测到系统已安装 3.10.11+ 时直接使用，依赖通过 --target 隔离到应用目录
# 仅在系统无 Python 时才下载 Python 3.13.14 官方安装器并静默安装到用户系统
# 选 3.13.14：3.13 系列最新维护版（2026-06-10 发布），所有依赖库 wheel 齐全
# 不再使用 embed 便携版 / venv 虚拟环境（DirectML 例外，用独立 dml_env）
PYTHON_VERSION = "3.13.14"         # 兜底安装版本（官方安装器）
PYTHON_VERSION_MIN = (3, 10, 11)    # 最低版本要求：3.10.11（含），低于此版本视为未装
PYTHON_VERSION_MIN_STR = "3.10.11"  # 用于提示文本
# Python 3.13.14 官方安装器下载地址（.exe 静默安装，自带 pip，无需 get-pip.py 引导）
# 实测（2026-08）：腾讯云 mirrors.cloud.tencent.com/python/ 目录为空（无安装器镜像），已移除；
# 官方 + 华为云 均为有效可下载源。
PYTHON_INSTALLER_MIRRORS = [
    "https://www.python.org/ftp/python/3.13.14/python-3.13.14-amd64.exe",
    "https://mirrors.huaweicloud.com/python/3.13.14/python-3.13.14-amd64.exe",
]
PYTHON_INSTALLER_SIZE_MB = 26      # 官方安装器体积（约 26MB）

# pip 源：默认走官方源（pypi.org），失败时按顺序自动回退多个国内镜像源重试。
# 不同网络（校园网/公司网/家宽）对不同镜像的可达性不同，多镜像覆盖更广。
# 注意：不依赖单一镜像站兜底（镜像站可能因成本压力随时关停/限流）——
# 已弃用长期停更的豆瓣镜像（pypi.douban.com），改用中科大（USTC）。
# 可用性实测（2026-08 HTTP）：清华/阿里云/腾讯云/中科大均为国内常用稳定镜像。
PIP_MIRROR_ARGS = []  # 官方源（空列表 = pip 默认）
# 自动回退镜像链（逐个尝试，谁通谁成功）
PIP_MIRROR_FALLBACKS = [
    ("清华镜像", ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                 "--trusted-host", "pypi.tuna.tsinghua.edu.cn"]),
    ("阿里云镜像", ["-i", "https://mirrors.aliyun.com/pypi/simple",
                  "--trusted-host", "mirrors.aliyun.com"]),
    ("腾讯云镜像", ["-i", "https://mirrors.cloud.tencent.com/pypi/simple",
                  "--trusted-host", "mirrors.cloud.tencent.com"]),
    ("中科大镜像", ["-i", "https://mirrors.ustc.edu.cn/pypi/web/simple",
                  "--trusted-host", "mirrors.ustc.edu.cn"]),
]
PIP_INSTALL_HINT = (
    "已自动尝试官方源与多个国内镜像，全部失败说明当前网络无法访问 pip 源。\n"
    "请更换网络（如手机热点）、关闭代理/加速器后重试，"
    "或开启科学上网后再次运行安装程序。"
)

# DirectML 精简环境（dml_env）在线重建参数
# —— 组件版本与本项目实测环境严格一致（embeddable Python 3.10.11 + torch 2.4.1 + torch-directml 0.2.5.dev240914）
# 安装包不再内嵌 1.2GB dml_env：安装时在线下载重建（约 290MB），安装包从 ~550MB 瘦身到 ~40MB。
# 多源容灾：任何单一镜像（清华等）停服/限流都不影响安装——python 运行时多镜像回退、
# pip 依赖走官方+四镜像自动回退链、get-pip 失败再从镜像链装 pip wheel 兜底。
# 离线兜底：用户将现成 dml_env 文件夹放在安装包同目录时仍走本地复制（step_build_dml_env 逻辑）。
_DML_EMBED_PYTHON_MIRRORS = [
    "https://mirrors.huaweicloud.com/python/3.10.11/python-3.10.11-embed-amd64.zip",
    "https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip",
]
_DML_GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
_DML_PIP_PACKAGES = [
    "torch==2.4.1",
    "torch-directml==0.2.5.dev240914",
    "torchvision==0.19.1",
    "numpy==2.2.6",
    "opencv-python-headless==5.0.0.93",
    "pillow==12.3.0",
    "matplotlib==3.10.9",
    "psutil==7.2.2",
]

ARCH_PIP_PACKAGES = {
    "cuda": [
        # torch 2.9.1+cu130 统一支持 Python 3.10~3.13 和 RTX 20~50 系（sm_75~sm_120）
        # cu130 是 PyTorch 2.12+ 的稳定 CUDA 版本（cu128 已弃用、cu124 不支持 RTX 50 系）
        ("torch==2.9.1+cu130 torchvision==0.24.1+cu130",
         ["--index-url", "https://download.pytorch.org/whl/cu130"]),
        "PyQt5==5.15.11",
        "numpy==2.5.1",
        "opencv-python==4.14.0.94",
        "Pillow==12.3.0",
        "matplotlib==3.11.1",
        "psutil==7.2.2",
        # 控温库：PyPI 包名是 nvidia-ml-py（import 名仍为 pynvml）
        # 用 12.x 最新稳定版（不追 13.x，避免 breaking changes）
        "nvidia-ml-py==12.575.51",
    ],
    "cpu": [
        # Windows CPU 版本只在 PyPI 发布（/whl/cpu/ 目录无 cp313 wheel）
        # PyPI 上的 torch==2.9.1 在 Windows 上默认是 CPU 版本（不带 +cpu 后缀）
        ("torch==2.9.1 torchvision==0.24.1", []),
        "PyQt5==5.15.11",
        "numpy==2.5.1",
        "opencv-python==4.14.0.94",
        "Pillow==12.3.0",
        "matplotlib==3.11.1",
        "psutil==7.2.2",
    ],
    "directml": [
        # 【双环境隔离：DirectML 模式】
        # 主环境（3.13+）：只装 UI 渲染 + 基础图像处理库。
        #   绝对不装 torch——AI 运算通过 subprocess 调用 dml_env 自带 Python 3.10 执行。
        # dml_env（3.10.11）：只负责 AI 数据处理，自带 torch-2.4.1 + torchvision +
        #   torch-directml 全套依赖，绝不装 PyQt5、绝不参与 UI 绘制。
        "PyQt5==5.15.11",
        "numpy==2.5.1",
        "opencv-python==4.14.0.94",
        "Pillow==12.3.0",
        "matplotlib==3.11.1",
        "psutil==7.2.2",
    ],
}


# Python 版本专属包覆盖（优先于 ARCH_PIP_PACKAGES 默认值）
# 化繁为简：torch 2.9.1+cu130 统一支持 Python 3.10~3.13，所有依赖版本完全统一
# 保留覆盖结构是为了 3.14+ 版本向前兼容（若未来需要差异化配置）
_PY313_PIP_OVERRIDE = {
    "cuda": [
        ("torch==2.9.1+cu130 torchvision==0.24.1+cu130",
         ["--index-url", "https://download.pytorch.org/whl/cu130"]),
        "PyQt5==5.15.11",
        "numpy==2.5.1",
        "opencv-python==4.14.0.94",
        "Pillow==12.3.0",
        "matplotlib==3.11.1",
        "psutil==7.2.2",
        "nvidia-ml-py==12.575.51",
    ],
    "cpu": [
        ("torch==2.9.1 torchvision==0.24.1", []),
        "PyQt5==5.15.11",
        "numpy==2.5.1",
        "opencv-python==4.14.0.94",
        "Pillow==12.3.0",
        "matplotlib==3.11.1",
        "psutil==7.2.2",
    ],
    "directml": [
        # 【双环境隔离】与 ARCH_PIP_PACKAGES["directml"] 同步
        # 主环境不装 torch/torchvision（AI 走 dml_env 子进程自带 Torch）
        "PyQt5==5.15.11",
        "numpy==2.5.1",
        "opencv-python==4.14.0.94",
        "Pillow==12.3.0",
        "matplotlib==3.11.1",
        "psutil==7.2.2",
    ],
}

# Python 3.12 与 3.10/3.11 共用默认包（torch 2.9.1+cu130 统一兼容 3.10~3.13）


def get_pip_packages(arch, py_version_str):
    """按架构和 Python 版本返回 pip 包列表。

    参数:
      arch: "cuda" / "cpu" / "directml"
      py_version_str: 形如 "3.10.11"、"3.13.0"

    返回: [(pkg_str, extra_args), ...]

    版本路由（详见 版本兼容性矩阵.md）:
      - 3.10 / 3.11 / 3.12: 用 ARCH_PIP_PACKAGES（torch 2.9.1+cu130 + numpy 2.5.1）
      - 3.13+: 用 _PY313_PIP_OVERRIDE（torch 2.9.1+cu130 + numpy 2.5.1 + Pillow 12.3.0）
      - 3.14+ 或未知版本: 回退到 3.13 配置（向前兼容）
      - 注：torch 2.9.1+cu130 统一支持 Python 3.10~3.13 和 RTX 20~50 系显卡
    """
    if arch not in ARCH_PIP_PACKAGES:
        return []
    # 解析主.次 版本号
    try:
        parts = py_version_str.split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return ARCH_PIP_PACKAGES.get(arch, [])

    # Python 3.13+ 使用专属覆盖配置
    if major == 3 and minor >= 13:
        return _PY313_PIP_OVERRIDE.get(arch, [])
    # 3.10~3.12 使用默认配置
    return ARCH_PIP_PACKAGES.get(arch, [])

_PROGRAM_FILES = [
    "start.pyw", "trainer.pyw", "importer.pyw",
    "bdor.pyw", "help.pyw", "test.pyw", "patch_tool.pyw",
    "utils", "scripts", "models", "images",
    "LICENSE",
]
# config 目录不打包也不复制：软件首次启动时由 settings_manager._default_settings() 自动生成

DEFAULT_INSTALL_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), _DIR_NAME)


# ===== 路径工具 =====
def _get_meipass():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return _PROJECT_ROOT

def _get_portable_python_exe(install_path):
    return os.path.join(install_path, "python", "python.exe")

def _get_dml_python_exe(install_path):
    return os.path.join(install_path, "dml_env", "python.exe")

def _get_dml_env_dir(install_path):
    return os.path.join(install_path, "dml_env")


# ===== 系统Python检测 =====
_PY_VER_SCRIPT = "import sys; print(sys.executable); print('.'.join(map(str, sys.version_info[:3])))"


def _ver_tuple(ver_str):
    """将版本字符串 '3.13.14' 转为元组 (3, 13, 14)，解析失败返回 (0,0,0)。"""
    try:
        parts = [int(x) for x in ver_str.split(".")]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])
    except Exception:
        return (0, 0, 0)


def _is_compatible_python(ver_str):
    """判断版本字符串是否满足最低要求（>= 3.10.11）。

    3.10.11 之前的版本（如 3.10.10、3.9.x）视为不兼容，触发下载官方安装器。
    3.10.11 / 3.11.x / 3.12.x / 3.13.x 都视为兼容，直接复用。
    """
    vt = _ver_tuple(ver_str)
    return vt >= PYTHON_VERSION_MIN


def _pythonw_from_exe(python_exe):
    """从 python.exe 路径推导 pythonw.exe 路径。"""
    d = os.path.dirname(python_exe)
    return os.path.join(d, "pythonw.exe")


def _resolve_launch_pythonw(install_path):
    """解析启动套件用的系统 pythonw（与安装时装包版本严格一致）。

    安装时 step_register_install 会把实际使用的 python.exe 写入
    install_components.json 的 python_exe 字段；这里读取它并推导同目录的
    pythonw.exe。若记录缺失或文件不存在，返回 None（调用方回退到 which/注册表）。
    这样避免用户系统同时装有多个 Python（3.10/3.11/3.12/3.13）时，
    用错版本导致 start.pyw 加载不了对应版本扩展（如 cp313 的 numpy/cv2）。
    """
    if not install_path:
        return None
    try:
        comp_file = os.path.join(install_path, _COMPONENTS_FILE)
        if not os.path.exists(comp_file):
            return None
        with open(comp_file, encoding="utf-8-sig") as f:
            data = json.load(f) or {}
        py_exe = data.get("python_exe") or ""
        if not py_exe or not os.path.isfile(py_exe):
            return None
        pyw = _pythonw_from_exe(py_exe)
        if os.path.isfile(pyw):
            return pyw
    except Exception:
        pass
    return None


def _scan_system_python():
    """扫描已安装的系统 Python（3.10.11+），返回 [(python_exe, version_str), ...]，版本从高到低排序。

    来源（按优先级）：
      1. py launcher（-3 → 默认；-3.12 / -3.11 / -3.10 精确尝试）
      2. PATH 中的 python / pythonw
      3. 注册表 HKCU/HKLM Software\\Python\\PythonCore（官方安装器写入）
      4. 常见安装路径（%LOCALAPPDATA%\\Programs\\Python、C:\\Python3x）

    覆盖 PATH 未配置、py launcher 未安装的场景（如卸载重装后），
    避免"系统已装 Python 却报不存在"。
    """
    found = []

    def _probe(exe):
        """探测一个解释器的真实路径与版本，返回 (exe, ver) 或 None。"""
        try:
            r = subprocess.run([exe, "-c", _PY_VER_SCRIPT],
                               capture_output=True, text=True, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode == 0 and r.stdout.strip():
                lines = r.stdout.strip().splitlines()
                if len(lines) >= 2:
                    real_exe, ver = lines[0].strip(), lines[1].strip()
                    if _is_compatible_python(ver):
                        return real_exe, ver
        except Exception:
            pass
        return None

    # 1) py launcher：先尝试 -3（最新 3.x），再精确尝试各版本
    for args in (["py", "-3"], ["py", "-3.13"], ["py", "-3.12"], ["py", "-3.11"], ["py", "-3.10"], ["py"]):
        info = _probe(args)
        if info:
            found.append(info)

    # 2) PATH 中的 python / pythonw
    for name in ("python", "pythonw"):
        p = shutil.which(name)
        if p:
            # pythonw.exe 无法直接 -c 执行，用同目录的 python.exe
            probe_exe = p if not p.endswith("pythonw.exe") else _pythonw_from_exe(p).replace("pythonw.exe", "python.exe")
            info = _probe(probe_exe)
            if info:
                found.append(info)
            else:
                # pythonw 探测失败但路径存在，尝试用同目录 python.exe 推出版本
                py_exe = os.path.join(os.path.dirname(p), "python.exe")
                if os.path.isfile(py_exe):
                    info2 = _probe(py_exe)
                    if info2:
                        found.append(info2)

    # 3) 注册表（官方安装器写入 InstallPath\\ExecutablePath）
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
                        if not _is_compatible_python(ver):
                            continue
                        try:
                            ik = winreg.OpenKey(core, ver + r"\InstallPath")
                            exe_path, _ = winreg.QueryValueEx(ik, "ExecutablePath")
                            winreg.CloseKey(ik)
                        except OSError:
                            continue
                        if exe_path and os.path.isfile(exe_path):
                            info = _probe(exe_path)
                            if info:
                                found.append(info)
                            else:
                                # 注册表指向的 exe 存在但探测失败，仍记录（可能是 pythonw.exe）
                                pw = _pythonw_from_exe(exe_path)
                                if os.path.isfile(pw):
                                    found.append((pw, ver))
                    except OSError:
                        break
                winreg.CloseKey(core)
            except OSError:
                pass
    except Exception:
        pass

    # 4) 常见安装路径（用户目录 + C 盘根目录，覆盖 3.10~3.13）
    la = os.environ.get("LOCALAPPDATA", "")
    candidates = []
    for ver_str in ("313", "312", "311", "310"):
        candidates.append(os.path.join(la, "Programs", "Python", f"Python{ver_str}", "python.exe"))
        candidates.append(fr"C:\Python{ver_str}\python.exe")
    for cand in candidates:
        if os.path.isfile(cand):
            info = _probe(cand)
            if info:
                found.append(info)

    # 去重（同一 exe 只保留第一次探测到的版本）
    seen, uniq = set(), []
    for exe, ver in found:
        key = os.path.normcase(os.path.abspath(exe))
        if key not in seen:
            seen.add(key)
            # 确保返回 pythonw.exe 路径（UI 程序需要无控制台窗口）
            if exe.endswith("python.exe"):
                pw = _pythonw_from_exe(exe)
                if os.path.isfile(pw):
                    exe = pw
            uniq.append((exe, ver))

    # 按版本号从高到低排序（3.13 > 3.12 > 3.11 > 3.10）
    uniq.sort(key=lambda x: _ver_tuple(x[1]), reverse=True)
    return uniq


def _scan_legacy_python():
    """扫描系统中安装的旧版 Python（3.0 <= version < 3.10.11），用于安装前提示用户。

    仅扫描注册表和常见安装路径（不调用 py launcher 的多次 subprocess），避免 UI 卡顿。
    返回 [(python_exe, version_str), ...]，去重后的列表（可能为空）。

    用途：安装新版 Python 3.13.14 之前，让用户知情——旧版 Python 不会被自动卸载，
    保留在系统中。让用户主动选择是否继续。
    """
    found = []

    # 1) 注册表（官方安装器写入 InstallPath\ExecutablePath）
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
                        if _is_compatible_python(ver):
                            continue  # 3.10.11+，不算旧版
                        try:
                            ik = winreg.OpenKey(core, ver + r"\InstallPath")
                            exe_path, _ = winreg.QueryValueEx(ik, "ExecutablePath")
                            winreg.CloseKey(ik)
                        except OSError:
                            continue
                        if exe_path and os.path.isfile(exe_path):
                            found.append((exe_path, ver))
                    except OSError:
                        break
                winreg.CloseKey(core)
            except OSError:
                pass
    except Exception:
        pass

    # 2) 常见安装路径（3.0~3.9 系列 + 3.10.0~3.10.10）
    la = os.environ.get("LOCALAPPDATA", "")
    candidates = []
    # 3.0~3.9 系列
    for ver_str in ("39", "38", "37", "36", "35", "34", "33", "32", "31", "30"):
        candidates.append(os.path.join(la, "Programs", "Python", f"Python{ver_str}", "python.exe"))
        candidates.append(fr"C:\Python{ver_str}\python.exe")
    # 3.10 系列（可能是 3.10.0~3.10.10，注册表版本号可能写成 "3.10" 不带 micro）
    candidates.append(os.path.join(la, "Programs", "Python", "Python310", "python.exe"))
    candidates.append(r"C:\Python310\python.exe")
    for cand in candidates:
        if not os.path.isfile(cand):
            continue
        # 探测真实版本（注册表里没记但路径存在的旧版）
        try:
            r = subprocess.run([cand, "-c", _PY_VER_SCRIPT],
                               capture_output=True, text=True, timeout=5,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode == 0 and r.stdout.strip():
                lines = r.stdout.strip().splitlines()
                if len(lines) >= 2:
                    ver = lines[1].strip()
                    if ver.startswith("3.") and not _is_compatible_python(ver):
                        found.append((cand, ver))
        except Exception:
            pass

    # 去重（同一 exe 只保留第一次探测到的版本）
    seen, uniq = set(), []
    for exe, ver in found:
        key = os.path.normcase(os.path.abspath(exe))
        if key not in seen:
            seen.add(key)
            uniq.append((exe, ver))
    # 按版本从高到低排序
    uniq.sort(key=lambda x: _ver_tuple(x[1]), reverse=True)
    return uniq


def detect_system_python():
    """检测系统已安装的兼容 Python（>= 3.10.11），返回最佳 (pythonw_exe, version_str) 或 (None, None)。

    优先返回最高版本（3.13 > 3.12 > 3.11 > 3.10），返回 pythonw.exe 路径（UI 程序无控制台）。
    """
    results = _scan_system_python()
    if results:
        return results[0]  # 已按版本降序排列，第一个就是最高版本
    return None, None


# 兼容旧名称
detect_system_python311 = detect_system_python


# ===== 下载工具 =====
def _download_file(url, dest_path, on_progress=None, cancel_check=None):
    """下载文件，支持断点续传和超时重试。

    断点续传：若 dest_path 已存在部分数据，发送 Range 请求从断点继续，
    服务器不支持 Range 时自动从头下载（覆盖）。
    单次 socket 读超时 120 秒（适配慢速网络），
    下载整体不设上限（由 cancel_check 控制取消）。
    on_progress(downloaded, total, speed_str, eta_str) 包含速度和预估剩余时间。
    """
    # 已有部分文件 → 从断点续传
    resume = 0
    if os.path.isfile(dest_path):
        resume = os.path.getsize(dest_path)
    headers = {"User-Agent": "Mozilla/5.0"}
    if resume > 0:
        headers["Range"] = f"bytes={resume}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        # 206 = 服务器支持续传；200 = 不支持，从头下载
        if resp.status == 206:
            mode, start = "ab", resume
        else:
            mode, start = "wb", 0
        total = start + int(resp.headers.get("Content-Length", 0))
        downloaded = start
        chunk = 1024 * 256
        start_time = time.time()
        last_update = 0
        with open(dest_path, mode) as f:
            while True:
                if cancel_check and cancel_check():
                    raise InterruptedError("用户取消下载")
                buf = resp.read(chunk)
                if not buf:
                    break
                f.write(buf)
                downloaded += len(buf)
                now = time.time()
                if on_progress and (now - last_update >= 0.5 or downloaded >= total):
                    elapsed = now - start_time
                    speed = downloaded / max(elapsed, 0.1)
                    speed_str = f"{speed / 1024 / 1024:.1f} MB/s" if speed > 1024 * 1024 \
                        else f"{speed / 1024:.0f} KB/s"
                    if total > 0 and speed > 0:
                        remaining = (total - downloaded) / speed
                        if remaining < 60:
                            eta_str = f"剩余 {remaining:.0f} 秒"
                        elif remaining < 3600:
                            eta_str = f"剩余 {remaining / 60:.1f} 分钟"
                        else:
                            eta_str = f"剩余 {remaining / 3600:.1f} 小时"
                    else:
                        eta_str = "计算中..."
                    on_progress(downloaded, total, speed_str, eta_str)
                    last_update = now


# ===== 真实安装步骤 =====
def step_extract_program_files(install_path, on_progress, cancel_check=None, purpose="train"):
    """从 _MEIPASS 展开程序文件到安装目录。

    purpose: "train" = 安装全部文件（训练器+识别器）
             "use"   = 仅安装识别器，跳过 trainer.pyw / importer.pyw
    """
    _dbg(f"step_extract: frozen={getattr(sys, 'frozen', False)}, install_path={install_path}, purpose={purpose}")
    on_progress(0, "正在展开程序文件...")
    if not getattr(sys, 'frozen', False):
        on_progress(100, "开发模式：程序文件已就位")
        return
    src_root = _get_meipass()
    os.makedirs(install_path, exist_ok=True)
    _dbg(f"step_extract: 创建目录 {install_path}, src_root={src_root}")

    # 识别器模式跳过的文件（训练器专用）
    _SKIP_FOR_USE = {"trainer.pyw", "importer.pyw"} if purpose == "use" else set()

    files_to_copy = [f for f in _PROGRAM_FILES if f not in _SKIP_FOR_USE]
    total = len(files_to_copy)
    missing = []
    for i, name in enumerate(files_to_copy):
        if cancel_check and cancel_check():
            raise InterruptedError("用户取消安装")
        src = os.path.join(src_root, name)
        dst = os.path.join(install_path, name)
        if not os.path.exists(src):
            missing.append(name)
            continue
        on_progress(int(i * 100 / total), f"正在写入 {name}...")
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
    if missing:
        # 程序文件缺失会导致安装出的软件无法运行——必须报错而非静默成功
        raise RuntimeError(
            f"安装包缺少 {len(missing)} 个程序文件：{', '.join(missing)}\n"
            f"安装包可能已损坏，请重新下载。")
    _dbg(f"step_extract: 完成，{total} 项全部复制到 {install_path}")
    # 创建运行时必需的空目录（模型权重、训练数据）
    for _d in ("models/model_file", "saves/auto_save/trainer",
               "saves/auto_save/loader", "saves/manual_save/trainer",
               "saves/manual_save/loader"):
        os.makedirs(os.path.join(install_path, _d), exist_ok=True)
    on_progress(100, "程序文件展开完成")


def step_resolve_python311(install_path, on_progress, cancel_check=None):
    """获取兼容 Python（>= 3.10.11）：检测系统 → 直接使用 / 下载官方版安装，返回 python.exe 路径。

    策略：
      1. 兼容旧版本：检测之前装过的便携版 Python（install_path/python/python.exe），有则复用
      2. 检测系统 Python（3.10.11+）：找到则直接返回（依赖通过 --target 隔离到应用目录）
      3. 系统无 Python：下载 Python 3.13.14 官方安装器，静默安装到用户系统后再次检测

    不创建 venv 虚拟环境（除 DirectML 用独立 dml_env 外）；
    不污染系统 Python 的 site-packages（pip install --target 隔离，在 step_install_pip_packages 中处理）；
    卸载本软件时只删应用目录，绝不删用户系统 Python。
    """
    # 兼容旧版本：如果之前装过便携版 Python（embed），继续使用，避免破坏已安装用户的环境
    portable_py = _get_portable_python_exe(install_path)
    if os.path.exists(portable_py):
        on_progress(100, "检测到旧版本便携 Python，继续复用")
        return portable_py

    # 步骤 1：检测系统 Python
    on_progress(10, "正在检测系统 Python...")
    sys_py, sys_ver = detect_system_python()
    if sys_py:
        # detect_system_python 返回 pythonw.exe，pip 安装需要 python.exe
        sys_py_exe = sys_py.replace("pythonw.exe", "python.exe") if sys_py.endswith("pythonw.exe") else sys_py
        if not os.path.isfile(sys_py_exe):
            sys_py_exe = sys_py  # 回退
        on_progress(100, f"检测到系统 Python {sys_ver}，将直接使用并通过 --target 隔离依赖")
        return sys_py_exe

    # 步骤 2：系统无 Python，下载 Python 3.13.14 官方安装器并静默安装
    on_progress(15, f"未检测到 Python {PYTHON_VERSION_MIN_STR}+，开始下载官方安装器...")
    return _install_official_python(on_progress, cancel_check)


def _install_official_python(on_progress, cancel_check=None):
    """下载 Python 3.13.14 官方安装器并静默安装到用户系统。

    静默安装参数与从 python.org 官网下载双击安装的默认行为完全一致，
    不主动排除任何组件（不传 Include_test / Include_doc），保持与官网手动安装一致：

      /quiet                     静默安装（无 UI）
      InstallAllUsers=0           仅当前用户（不需要 UAC 提权）
      PrependPath=1               自动加入 PATH（用户级）
      InstallLauncherAllUsers=0   py launcher 仅当前用户
      SimpleInstall=1             简化安装（不写卸载日志详情）

    安装完成后重新检测系统 Python，应能从注册表/常见路径找到（无需 PATH 刷新）。
    返回 python.exe 路径。
    """
    installer_path = os.path.join(tempfile.gettempdir(), f"python-{PYTHON_VERSION}-amd64.exe")
    on_progress(20, f"正在下载 Python {PYTHON_VERSION} 官方安装器（约 {PYTHON_INSTALLER_SIZE_MB}MB）...")

    def _dl_prog(done, total, speed_str="", eta_str=""):
        if cancel_check and cancel_check():
            raise InterruptedError("用户取消下载")
        pct = 20 + int(done * 30 / max(total, 1))  # 20~50%
        msg = f"下载 Python 安装器... {done // (1024*1024)}MB / {total // (1024*1024)}MB"
        if speed_str:
            msg += f"  |  {speed_str}  {eta_str}"
        on_progress(pct, msg)

    last_err = None
    for url in PYTHON_INSTALLER_MIRRORS:
        try:
            on_progress(20, f"下载 Python 安装器（{url.split('/')[2]}）...")
            _download_file(url, installer_path, _dl_prog, cancel_check)
            last_err = None
            break
        except Exception as e:
            last_err = e
            continue
    if last_err is not None:
        raise RuntimeError(f"所有镜像下载失败：{last_err}")

    # 静默安装（用户级，无需管理员权限）
    # 参数与从 python.org 官网下载双击安装的默认行为完全一致：
    #   - InstallAllUsers=0：仅当前用户（不需要 UAC 提权）
    #   - PrependPath=1：自动加入用户 PATH
    #   - InstallLauncherAllUsers=0：py launcher 仅当前用户
    #   - SimpleInstall=1：简化安装（不写卸载日志详情）
    # 不主动排除任何组件（不传 Include_test / Include_doc），保持与官网手动安装完全一致
    on_progress(55, f"正在静默安装 Python {PYTHON_VERSION} 到用户系统...")
    try:
        result = subprocess.run(
            [installer_path, "/quiet",
             "InstallAllUsers=0",
             "PrependPath=1",
             "InstallLauncherAllUsers=0",
             "SimpleInstall=1"],
            capture_output=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', errors='replace')[:300] if result.stderr else ""
            raise RuntimeError(f"Python 静默安装失败（返回码 {result.returncode}）：{stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Python 安装超时（5 分钟未完成），请重试或手动安装 Python {PYTHON_VERSION}")
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"Python 静默安装失败：{e}")
    finally:
        try:
            os.remove(installer_path)
        except OSError:
            pass

    # 重新检测系统 Python（应能从注册表或常见路径找到，不依赖当前进程 PATH 刷新）
    on_progress(90, "正在验证 Python 安装...")
    sys_py, sys_ver = detect_system_python()
    if not sys_py:
        raise RuntimeError(
            f"Python {PYTHON_VERSION} 已完成静默安装，但未能自动检测到。"
            f"请重启电脑后再次运行本安装器；如仍失败，请手动从 python.org 安装 Python {PYTHON_VERSION}。"
        )

    sys_py_exe = sys_py.replace("pythonw.exe", "python.exe") if sys_py.endswith("pythonw.exe") else sys_py
    if not os.path.isfile(sys_py_exe):
        sys_py_exe = sys_py

    # 验证 pip 可用（官方安装器默认带 pip，这里仅校验）
    pip_check = subprocess.run([sys_py_exe, "-m", "pip", "--version"],
                                capture_output=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    if pip_check.returncode != 0:
        raise RuntimeError("Python 安装完成但 pip 不可用，请通过 Windows 设置 → 应用 → Python → 修复")

    on_progress(100, f"Python {sys_ver} 安装完成")
    return sys_py_exe


def _find_dml_env_src():
    """查找 dml_env 源目录：_MEIPASS（向后兼容）→ exe 同目录（外置）→ 开发根。"""
    if getattr(sys, 'frozen', False):
        # 1) _MEIPASS（dml_env 打包在内，向后兼容）
        p = os.path.join(_get_meipass(), "dml_env")
        if os.path.isdir(p):
            return p
        # 2) exe 同目录（dml_env 外置，避免 onefile 解压 1.2GB 空窗期）
        p = os.path.join(os.path.dirname(sys.executable), "dml_env")
        if os.path.isdir(p):
            return p
    # 3) 开发根（开发环境直接用源文件）
    p = os.path.join(_PROJECT_ROOT, "dml_env")
    if os.path.isdir(p):
        return p
    return None


def step_build_dml_env(install_path, on_progress, cancel_check=None):
    """准备 DirectML 环境（dml_env）。

    优先级：
      1. 目标安装目录已有 dml_env → 跳过
      2. 本地存在 dml_env 源（exe 同目录外置 / 开发根 / 旧版 _MEIPASS）→ 直接复制（离线兜底）
      3. 在线构建精简环境：下载 embeddable Python 3.10.11（华为云）→ pip 装锁定版本依赖
         （官方源 + 国内镜像自动回退）→ 删除 torch/lib 静态库 .lib（运行时仅需 DLL，可省 ~740MB）
    """
    on_progress(0, "正在准备 DirectML 环境...")
    dst = _get_dml_env_dir(install_path)
    # 完整性校验：必须 python.exe 与 torch_directml 都在才算已装好
    # （避免上次在线构建中途失败留下"只有 python.exe 没有 torch"的半成品被误跳过）
    if (os.path.exists(_get_dml_python_exe(install_path))
            and os.path.isdir(os.path.join(dst, "Lib", "site-packages", "torch_directml"))):
        on_progress(100, "DirectML 环境已存在，跳过构建")
        return
    # 本地源兜底（离线场景：用户把现成 dml_env 放在安装包同目录）
    src = _find_dml_env_src()
    if src:
        on_progress(10, "发现本地 DirectML 环境，直接复制（离线模式）...")
        shutil.copytree(src, dst, dirs_exist_ok=True)
        on_progress(100, "DirectML 环境就绪")
        return
    # 在线构建（默认路径）
    try:
        _build_dml_env_online(dst, on_progress, cancel_check)
    except InterruptedError:
        raise
    except Exception as e:
        # 构建失败必须清掉半成品，否则下次安装会因"python.exe 已存在"误跳过
        try:
            shutil.rmtree(dst, ignore_errors=True)
        except Exception:
            pass
        raise RuntimeError(
            "DirectML 环境在线构建失败。\n"
            f"原因：{e}\n\n"
            "请检查网络后重试；或将现成的 dml_env 文件夹放在安装包同目录后重新安装。")
    on_progress(100, "DirectML 环境就绪")


def _bootstrap_dml_pip(dml_py, tmp, cancel_check=None):
    """初始化 dml_env 的 pip。

    优先 get-pip.py（bootstrap.pypa.io，清华/官方索引进 pip 引导）；
    get-pip.py 不可达时兜底：从 PyPI 镜像链（官方/清华/阿里云/腾讯云/中科大）
    逐个下载 pip wheel 解压，用 PYTHONPATH 方式启用后安装 pip/setuptools/wheel。
    任一来源成功即返回；全部失败抛错。
    """
    gp = os.path.join(tmp, "get-pip.py")
    try:
        _download_file(_DML_GET_PIP_URL, gp, cancel_check=cancel_check)
        _gp_ok = os.path.isfile(gp) and os.path.getsize(gp) > 50_000
    except Exception:
        _gp_ok = False
    if _gp_ok:
        for _extra in (["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"], []):
            _r = subprocess.run([dml_py, gp] + _extra, capture_output=True, text=True,
                                timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
            if _r.returncode == 0:
                return
        raise RuntimeError("pip 引导失败（get-pip）: " + ((_r.stderr or "")[-300:]))

    # 兜底：镜像链装 pip wheel（get-pip.py 被墙/不可达场景）
    import zipfile as _z
    import re as _re
    _indexes = [
        ("官方",   "https://pypi.org/simple", []),
        ("清华",   "https://pypi.tuna.tsinghua.edu.cn/simple",
         ["--trusted-host", "pypi.tuna.tsinghua.edu.cn"]),
        ("阿里云", "https://mirrors.aliyun.com/pypi/simple", []),
        ("腾讯云", "https://mirrors.cloud.tencent.com/pypi/simple", []),
        ("中科大", "https://mirrors.ustc.edu.cn/pypi/web/simple", []),
    ]
    _last_err = ""
    for _name, _index, _trust in _indexes:
        try:
            _html = urllib.request.urlopen(_index + "/pip/", timeout=30).read().decode("utf-8", "replace")
            _hrefs = _re.findall(r'href="([^"]*?pip-[\d.]+-py3-none-any\.whl)[^"]*"', _html)
            if not _hrefs:
                continue
            _whl = os.path.join(tmp, "pip_bootstrap.whl")
            urllib.request.urlretrieve(urllib.parse.urljoin(_index + "/pip/", _hrefs[-1]), _whl)
            _ex = os.path.join(tmp, "pip_bootstrap")
            with _z.ZipFile(_whl) as _zf:
                _zf.extractall(_ex)
            _env = dict(os.environ)
            _env["PYTHONPATH"] = _ex + os.pathsep + _env.get("PYTHONPATH", "")
            _r = subprocess.run(
                [dml_py, "-m", "pip", "install", "--no-cache-dir", "--timeout", "120",
                 "pip", "setuptools", "wheel", "-i", _index] + _trust,
                capture_output=True, text=True, timeout=600,
                env=_env, creationflags=subprocess.CREATE_NO_WINDOW)
            if _r.returncode == 0:
                return
            _last_err = (f"[{_name}] " + ((_r.stderr or "")[-200:]))
        except Exception as _e:
            _last_err = f"[{_name}] {_e}"
            continue
    raise RuntimeError("pip 引导失败（get-pip.py 不可达且镜像均失败）: " + (_last_err or "无可用来源"))


def _build_dml_env_online(dst, on_progress, cancel_check=None):
    """在线重建精简 dml_env：embeddable Python 3.10.11 + 锁定版本依赖 + 精简 torch。"""
    import zipfile as _zipfile
    os.makedirs(dst, exist_ok=True)
    tmp = os.path.join(dst, "_build_tmp")
    os.makedirs(tmp, exist_ok=True)

    # 1. 下载 embeddable Python 3.10.11（多镜像回退：华为云 → 官方 python.org）
    on_progress(15, "正在下载 Python 3.10.11 精简运行时（约 8MB）...")
    py_zip = os.path.join(tmp, "python-3.10.11-embed-amd64.zip")
    _downloaded = False
    _last_err = ""
    for _u in _DML_EMBED_PYTHON_MIRRORS:
        try:
            _download_file(_u, py_zip, cancel_check=cancel_check)
            if os.path.isfile(py_zip) and os.path.getsize(py_zip) > 1_000_000:
                _downloaded = True
                break
        except Exception as _e:
            _last_err = str(_e)
        try:
            if os.path.exists(py_zip):
                os.remove(py_zip)
        except Exception:
            pass
    if not _downloaded:
        raise RuntimeError("Python 3.10.11 运行时下载失败: " + (_last_err or "所有镜像均不可达"))
    if cancel_check and cancel_check():
        raise InterruptedError("用户取消安装")

    # 2. 解压
    on_progress(25, "正在解压 Python 运行时...")
    with _zipfile.ZipFile(py_zip) as z:
        z.extractall(dst)

    # 3. 配置 python310._pth（启用 site，识别 Lib/site-packages）
    pth = os.path.join(dst, "python310._pth")
    with open(pth, "w", encoding="utf-8") as f:
        f.write("python310.zip\n.\n\nimport site\n")

    dml_py = os.path.join(dst, "python.exe")
    if not os.path.exists(dml_py):
        raise RuntimeError("embeddable Python 解压失败，缺少 python.exe")

    # 4. pip 引导（多源兜底）
    on_progress(35, "正在初始化 pip...")
    _bootstrap_dml_pip(dml_py, tmp, cancel_check)

    # 5. 安装锁定版本依赖（官方源 + 国内镜像自动回退，约 300MB）
    on_progress(45, "正在下载并安装 DirectML 组件（约 300MB，可能需要几分钟）...")
    _rc, _detail = _pip_run(dml_py, list(_DML_PIP_PACKAGES), [], timeout=7200)
    if _rc != 0:
        raise RuntimeError("DirectML 组件安装失败: " + (_detail or str(_rc)))

    # 6. 精简 torch：删除静态库 .lib（运行时仅需 DLL，可省 ~740MB）
    torch_lib = os.path.join(dst, "Lib", "site-packages", "torch", "lib")
    _removed = 0
    if os.path.isdir(torch_lib):
        for _fn in os.listdir(torch_lib):
            if _fn.lower().endswith(".lib"):
                try:
                    os.remove(os.path.join(torch_lib, _fn))
                    _removed += 1
                except Exception:
                    pass
    on_progress(90, f"正在验证 DirectML 环境（已精简 {_removed} 个静态库文件）...")

    # 7. 验证 torch_directml 可用
    _verify = subprocess.run(
        [dml_py, "-c", "import torch, torch_directml; assert torch_directml.device_count() >= 0"],
        capture_output=True, text=True, timeout=300,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if _verify.returncode != 0:
        raise RuntimeError("torch_directml 验证失败: " + ((_verify.stderr or "")[-300:]))

    # 清理临时文件
    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass


def _pip_run(python_exe, cmd_base, mirror_args, timeout=7200, show_console=False, max_retries=None):
    """执行 pip install，按经验召回最佳实践做重试与成功判定。

    重试策略（默认全部尝试，任一成功即返回）：
      1) 官方源，基础命令
      2) + 国内镜像逐个回退（清华/阿里云/腾讯云/中科大，任一可用即成功）
      3) + --force-reinstall + 镜像（下载到一半损坏/元数据不完整时强制重装）
    每步 pip 均带 --timeout 120，避免默认 15s 连接超时误判。

    成功判定：不单纯依赖 exit code 0，而是 stdout/stderr 中必须包含
    "Successfully installed" 或 "already satisfied" / "Requirement already satisfied"。
    避免 exit 0 但实际模块未落盘导致后续 import 失败。
    """
    _has_custom_idx = any(a in ("-i", "--index-url", "--extra-index-url") for a in cmd_base + mirror_args)
    attempts = []
    # 尝试 1: 官方源
    attempts.append(("官方源", [python_exe, "-m", "pip", "install",
                                "--no-cache-dir", "--progress-bar", "raw",
                                "--timeout", "120"] + cmd_base + mirror_args))
    # 尝试 2+: 逐个国内镜像（仅当用户未自定义 -i 时）
    if not _has_custom_idx:
        for _mn, _ma in PIP_MIRROR_FALLBACKS:
            attempts.append((_mn,
                             [python_exe, "-m", "pip", "install",
                              "--no-cache-dir", "--progress-bar", "raw",
                              "--timeout", "120"]
                             + cmd_base + mirror_args + _ma))
    # 尝试 3: force-reinstall + 镜像（解决部分下载/校验和残留问题）
    if "--force-reinstall" not in cmd_base:
        fr_base = list(cmd_base)
        if "--no-deps" in fr_base:
            fr_base.remove("--no-deps")
        if not _has_custom_idx:
            for _mn, _ma in PIP_MIRROR_FALLBACKS:
                attempts.append((f"force-reinstall + {_mn}",
                                 [python_exe, "-m", "pip", "install",
                                  "--force-reinstall", "--no-cache-dir",
                                  "--progress-bar", "raw",
                                  "--timeout", "120"] + fr_base + mirror_args + _ma))

    last_err = ""
    # 默认尝试全部源（官方 + 全镜像 + force-reinstall 兜底）；max_retries 指定时截断
    _chosen = attempts if max_retries is None else attempts[:max_retries]
    for attempt_idx, (src_name, cmd) in enumerate(_chosen, start=1):
        try:
            if show_console:
                result = subprocess.run(cmd, timeout=timeout,
                                        creationflags=subprocess.CREATE_NEW_CONSOLE)
                out_text, err_text = "", ""
            else:
                result = subprocess.run(cmd, capture_output=True, timeout=timeout,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                out_text = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
                err_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            combined = out_text + "\n" + err_text
            success_markers = ("Successfully installed",
                               "Requirement already satisfied",
                               "already satisfied")
            marker_ok = any(m in combined for m in success_markers)
            last_err = err_text[-400:] if err_text else ""
            if result.returncode == 0 and marker_ok:
                return 0, ""
            # 最后一次也失败：返回实际信息
            if attempt_idx == len(_chosen):
                detail = last_err or (f"pip 返回码 {result.returncode}"
                                      + ("（未检测到 Successfully installed/already satisfied 标记）"
                                         if not marker_ok else ""))
                return result.returncode or 99, detail
        except subprocess.TimeoutExpired:
            last_err = f"pip 安装超时（>{timeout//3600}h），建议检查网络后重试。"
            continue
        except Exception as e:
            last_err = f"[{src_name}] pip 执行异常: {e}"
            continue
    return 98, last_err or ("pip 多次重试均失败，建议手动执行后重试安装")


def _write_progress_wrapper():
    """写通用进度 wrapper 脚本到临时目录，返回路径。

    wrapper 功能：
    1. 读取 JSON 配置（mode / commands / cwd）
    2. 启动子进程，用 os.read(4096) 逐块读取 stdout+stderr
    3. 原样转发到 sys.stdout（包括 \r，CMD 中原生进度条正确刷新）
    4. 根据 mode 解析进度百分比写入 progress_file
       - "tqdm": 匹配 (\\d+)%（torchvision 等 tqdm 格式）
       - "pip":  匹配 数字/数字 MB 格式，结合已完成命令数算总进度
    """
    import tempfile
    wrapper_code = r'''import sys, os, subprocess, json, re

# CREATE_NO_WINDOW 防止子进程弹出额外控制台窗口
_CREATE_NO_WINDOW = 0x08000000

# ANSI 转义序列过滤（CMD 不启用 VT 模式时这些字节会显示成乱码）
# 匹配: \x1b[ 后跟参数(数字;?) 再跟字母结尾（如 \x1b[?25l \x1b[0m \x1b[2K）
_ANSI_ESCAPE_RE = re.compile(rb'\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][AB012]')

def clean_for_cmd(chunk):
    """过滤 ANSI 转义序列，保留可见字符、\r、\n。"""
    if b'\x1b' not in chunk:
        return chunk
    return _ANSI_ESCAPE_RE.sub(b'', chunk)

def parse_pip_line(line):
    """解析 pip raw 进度行，返回子进度 0.0~1.0 或 None。
    pip --progress-bar raw 格式: "Progress 12345 of 67890"
    raw 格式不依赖 rich，在 stdout 重定向到 PIPE 时也能正常输出进度。
    """
    m = re.search(r'Progress\s+(\d+)\s+of\s+(\d+)', line)
    if m:
        cur = float(m.group(1))
        total = float(m.group(2))
        if total > 0:
            return min(1.0, cur / total)
    return None

def write_pct(path, pct):
    try:
        with open(path, 'w') as f:
            f.write(str(int(pct)))
    except:
        pass

def write_pid(pid_file, pid):
    if not pid_file:
        return
    try:
        with open(pid_file, 'w') as f:
            f.write(str(pid))
    except:
        pass

def main():
    config_path = sys.argv[1]
    progress_file = sys.argv[2]
    pid_file = sys.argv[3] if len(sys.argv) > 3 else None
    # 先记录自身 PID：CMD 窗口被关闭时 wrapper 随之终止，主进程可据此补杀残留
    write_pid(pid_file, os.getpid())
    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    mode = cfg.get("mode", "tqdm")
    commands = cfg.get("commands", [])
    work_dir = cfg.get("cwd") or None
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    # 强制 pip/torch 子进程用 UTF-8 输出，避免中文路径在 CMD（chcp 65001）里乱码
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    if mode == "tqdm":
        cmd = commands[0] if commands else []
        if not cmd:
            write_pct(progress_file, -1)
            sys.exit(1)
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, cwd=work_dir, env=env,
            creationflags=_CREATE_NO_WINDOW)
        write_pid(pid_file, proc.pid)
        fd = proc.stdout.fileno()
        last_pct = 0
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            chunk = clean_for_cmd(chunk)
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            text = chunk.decode('utf-8', errors='replace')
            m = re.search(r'(\d+)%', text)
            if m:
                pct = int(m.group(1))
                if pct > last_pct:
                    last_pct = pct
                    write_pct(progress_file, pct)
        proc.wait()
        write_pct(progress_file, 100 if proc.returncode == 0 else -1)
        sys.exit(proc.returncode or 0)

    elif mode == "pip":
        total_cmds = len(commands)
        completed = 0
        last_pct = 0
        write_pct(progress_file, 0)
        # 官方源 → 多个国内镜像逐个回退 → force-reinstall 兜底（覆盖不同网络可达性）
        # 注意：不依赖单一镜像站兜底（镜像站可能随时关停/限流），豆瓣已弃用改用中科大
        _MIRRORS = [
            ("清华镜像", ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                        "--trusted-host", "pypi.tuna.tsinghua.edu.cn"]),
            ("阿里云镜像", ["-i", "https://mirrors.aliyun.com/pypi/simple",
                          "--trusted-host", "mirrors.aliyun.com"]),
            ("腾讯云镜像", ["-i", "https://mirrors.cloud.tencent.com/pypi/simple",
                          "--trusted-host", "mirrors.cloud.tencent.com"]),
            ("中科大镜像", ["-i", "https://mirrors.ustc.edu.cn/pypi/web/simple",
                          "--trusted-host", "mirrors.ustc.edu.cn"]),
        ]
        _SUCCESS_MARKERS = ("Successfully installed",
                            "Requirement already satisfied",
                            "already satisfied")
        for ci, cmd in enumerate(commands):
            attempts = [(cmd, "官方源")]
            _is_install = len(cmd) >= 3 and "pip" in cmd[1:3] and "install" in cmd[2:5]
            _has_custom_idx = any(a in ("-i", "--index-url", "--extra-index-url") for a in cmd)
            if _is_install and _has_custom_idx:
                # CUDA torch 等自定义源包：wheel 托管在 download.pytorch.org 境外 CDN，
                # 国内直连实测仅 ~0.12MB/s（1.77GB 需 4 小时+）。
                # 首选阿里云 pytorch-wheels 直连文件镜像（实测 ~2MB/s，约 15 分钟下完），
                # 依赖走阿里云 PyPI；失败再回退官方源、上海交大索引代理。
                try:
                    _idx_pos = cmd.index("--index-url") + 1
                except ValueError:
                    _idx_pos = None
                if _idx_pos is not None:
                    _cu = cmd[_idx_pos].rstrip("/").rsplit("/", 1)[-1] or "cu130"
                    _aliyun_url = "https://mirrors.aliyun.com/pytorch-wheels/" + _cu
                    _a = [c for i, c in enumerate(cmd)
                          if i != _idx_pos and not (i == _idx_pos - 1 and cmd[i] == "--index-url")]
                    _a += ["-f", _aliyun_url,
                           "-i", "https://mirrors.aliyun.com/pypi/simple/",
                           "--trusted-host", "mirrors.aliyun.com"]
                    attempts.insert(0, (_a, "阿里云 pytorch-wheels 直连镜像"))
                    _sjtu_url = "https://mirror.sjtu.edu.cn/pytorch-wheels/" + _cu
                    _c = list(cmd)
                    _c[_idx_pos] = _sjtu_url
                    attempts.append((_c, "上海交大 pytorch-wheels"))
            if _is_install and not _has_custom_idx:
                for _mn, _ma in _MIRRORS:
                    attempts.append((list(cmd) + _ma, _mn))
            # force-reinstall 兜底重试（仅 install 场景，且未指定 --force-reinstall 本身）
            # 逐个镜像尝试，避免清华单点：清华废弃时仍可走其他镜像兜底
            if _is_install and "--force-reinstall" not in cmd:
                _fr_cmd = list(cmd)
                if "--no-deps" in _fr_cmd:
                    _fr_cmd.remove("--no-deps")
                if "install" in _fr_cmd:
                    _insert = _fr_cmd.index("install") + 1
                    _fr_cmd[_insert:_insert] = ["--force-reinstall"]
                else:
                    _fr_cmd = ["--force-reinstall"] + _fr_cmd
                if not _has_custom_idx:
                    for _mn, _ma in _MIRRORS:
                        attempts.append((_fr_cmd + _ma, f"force-reinstall + {_mn}"))
            rc = None
            ok = False
            for ai, (try_cmd, src_name) in enumerate(attempts):
                if ai > 0:
                    print(f"\n=== [包 {ci+1}/{total_cmds}] {src_name} 重试 ===\n", flush=True)
                proc = subprocess.Popen(
                    try_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    bufsize=0, cwd=work_dir, env=env,
                    creationflags=_CREATE_NO_WINDOW)
                write_pid(pid_file, proc.pid)
                fd = proc.stdout.fileno()
                tail = b""
                while True:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    chunk = clean_for_cmd(chunk)
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                    tail += chunk
                    if len(tail) > 65536:
                        tail = tail[-8192:]
                    text = tail.decode('utf-8', errors='replace')
                    last_cr = max(text.rfind('\r'), text.rfind('\n'))
                    cur_line = text[last_cr+1:] if last_cr >= 0 else text
                    sub = parse_pip_line(cur_line)
                    if sub is not None:
                        overall = int((completed + sub) / total_cmds * 100)
                        if overall != last_pct:
                            last_pct = overall
                            write_pct(progress_file, overall)
                proc.wait()
                rc = proc.returncode
                tail_text = tail.decode('utf-8', errors='replace')
                marker_ok = any(m in tail_text for m in _SUCCESS_MARKERS)
                if rc == 0 and marker_ok:
                    ok = True
                    break
                if ai == len(attempts) - 1:
                    # 所有尝试耗尽，区分：returncode 非零 vs 假成功(rc=0 但无 installed 标记)
                    if not marker_ok:
                        print("\nERROR: pip 返回码为 0，但输出中未检测到 "
                              "'Successfully installed' / 'Requirement already satisfied' 标记，"
                              "视为安装失败（通常是部分下载、缓存损坏或静默中断）。", flush=True)
                    write_pct(progress_file, -1)
                    sys.exit(rc if rc != 0 else 97)
            if not ok:
                write_pct(progress_file, -1)
                sys.exit(rc if (rc is not None and rc != 0) else 97)
            completed += 1
            overall = int(completed / total_cmds * 100)
            if overall != last_pct:
                last_pct = overall
                write_pct(progress_file, overall)
        write_pct(progress_file, 100)
        sys.exit(0)
    else:
        write_pct(progress_file, -1)
        sys.exit(1)

if __name__ == "__main__":
    main()
'''
    wrapper_path = os.path.join(tempfile.gettempdir(), "_banner_progress_wrapper.py")
    with open(wrapper_path, "w", encoding="utf-8") as f:
        f.write(wrapper_code)
    return wrapper_path


def _run_in_cmd(wrapper_py, runner_py, mode, commands, progress_file, title,
                cwd=None, cancel_check=None, on_pct=None):
    """在新 CMD 窗口中运行 wrapper，wrapper 转发 pip/tqdm 原始输出到 CMD + 解析百分比到文件。

    返回 returncode（0=成功）。
    - wrapper_py: wrapper 脚本路径
    - runner_py: 执行 wrapper 的 python.exe
    - mode: "pip" / "tqdm"
    - commands: 命令列表
    - progress_file: 进度文件路径
    - title: CMD 窗口标题
    - on_pct: 回调 on_pct(pct_int_0_100)
    """
    import tempfile, json
    config = {"mode": mode, "commands": commands, "cwd": cwd}
    cfg_path = os.path.join(tempfile.gettempdir(), "_banner_cmd_cfg.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f)

    try:
        with open(progress_file, "w") as f:
            f.write("0")
    except Exception:
        pass

    # 记录 wrapper/pip 子进程 PID：用户关闭 CMD 窗口后，wrapper 随窗口终止，
    # 但 pip（CREATE_NO_WINDOW 挂在隐藏控制台）会变孤儿进程继续下载，
    # 主进程凭此文件补杀，确保"关窗后结果确定"。
    pid_file = progress_file + ".pid"
    try:
        with open(pid_file, "w") as f:
            f.write("")
    except Exception:
        pass

    bat_lines = [
        "@echo off",
        "chcp 65001 >nul",
        f'"{runner_py}" "{wrapper_py}" "{cfg_path}" "{progress_file}" "{pid_file}"',
        "if errorlevel 1 (",
        "    echo.",
        "    echo 执行完毕（如有错误请查看上方信息）。",
        "    pause",
        ") else (",
        "    timeout /t 3 >nul",
        ")",
    ]
    bat_path = os.path.join(tempfile.gettempdir(), "_banner_cmd_run.bat")
    # 用 UTF-8 with BOM 保存，确保 CMD（chcp 65001）能正确解析中文 echo
    with open(bat_path, "w", encoding="utf-8-sig") as f:
        f.write("\r\n".join(bat_lines))

    # 用 CREATE_NEW_CONSOLE 替代 start /wait：proc.kill 可杀整个进程树
    proc = subprocess.Popen(
        [bat_path],
        creationflags=subprocess.CREATE_NEW_CONSOLE)

    last_pct = -1
    while proc.poll() is None:
        if cancel_check and cancel_check():
            # taskkill /F /T 杀掉整个进程树（CMD窗口 + wrapper + pip 子进程）
            try:
                subprocess.run(
                    f'taskkill /F /T /PID {proc.pid}',
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    capture_output=True, timeout=10)
            except Exception:
                pass
            proc.wait()
            raise InterruptedError("用户取消安装")
        time.sleep(1)
        try:
            with open(progress_file, "r") as pf:
                raw = pf.read().strip()
                pct = int(raw) if raw else -1
        except Exception:
            pct = -1
        if pct == -1:
            continue
        pct = max(0, min(100, pct))
        if pct != last_pct:
            last_pct = pct
            if on_pct:
                on_pct(pct)

    rc = proc.returncode
    # 用户可能直接关闭了 CMD 窗口：wrapper 随窗口终止，但 pip 子进程用
    # CREATE_NO_WINDOW 启动、挂在隐藏控制台，可能变孤儿进程继续下载/写入。
    # 补杀 cmd + wrapper + pip 全进程树，杜绝"关窗后后台还在偷偷下载"的
    # 悬空状态，让安装结果确定（成败以安装后实际检测为准）。
    if rc != 0:
        _pids = [proc.pid]
        try:
            with open(pid_file, "r") as _pf:
                _pids += [int(_x) for _x in _pf.read().split()
                          if _x.strip().lstrip("-").isdigit()]
        except Exception:
            pass
        for _pid in dict.fromkeys(_pids):
            try:
                subprocess.run(
                    f'taskkill /F /T /PID {_pid}',
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    capture_output=True, timeout=10)
            except Exception:
                pass
    # 清理所有临时文件：配置、批处理、进度文件、PID 文件、wrapper 脚本
    for tmp in (cfg_path, bat_path, progress_file, pid_file, wrapper_py):
        try:
            os.remove(tmp)
        except Exception:
            pass
    return rc


def step_install_pip_packages(archs, python_exe, on_progress, cancel_check=None, purpose="train", install_dir=None, selected_features=None):
    """按架构安装 pip 依赖。CMD 窗口显示原生 pip 进度条，UI 读取真实百分比。

    防污染策略：当 python_exe 是系统 Python（非 embed、非 dml_env）时，
    所有 pip install 命令添加 --target=install_dir\\Lib\\site-packages，
    包安装到安装目录而非系统 site-packages，避免污染用户系统 Python 环境。

    双环境隔离原则：
      主 Python 环境（3.13+）：负责全部 UI 渲染（PyQt5），CUDA/CPU 模式下 Torch 也装在此。
      DML 便携环境（3.10.11）：只负责 AI 运算，自带 Torch 全套依赖，绝不装 PyQt5，绝不参与 UI 绘制。
      => 本函数只给主环境装包；dml_env 不做任何注入。

    selected_features: set[str] - 用户在库选择页勾选的组件 key（如 {"thermal", "psutil"}）。
        None 表示按旧逻辑（purpose/archs 过滤）安装（兼容管理组件/修复模式）。
        当 purpose=="use" 且 selected_features 不含 "thermal" 时，跳过温度监控库安装。
        psutil 在 _REQUIRED_PKGS 中始终安装。
    """
    _SKIP_PIP_FOR_USE = {"matplotlib"} if purpose == "use" else set()
    # ===== 温度监控库按用户选择过滤（仅 use 模式可选） =====
    # use 模式且用户没勾选 thermal → 跳过 nvidia-ml-py/pyadl/intel-thermal/cpu-temp
    if (purpose == "use" and selected_features is not None
            and "thermal" not in selected_features):
        _SKIP_PIP_FOR_USE.update({"nvidia-ml-py", "pyadl", "intel-thermal", "cpu-temp"})
    _dbg(f"step_install_pip_packages: _SKIP_PIP_FOR_USE={_SKIP_PIP_FOR_USE}, features={selected_features}")
    # 判断是否为系统 Python（需要 --target 隔离）
    # embed Python: 安装目录\python\python.exe（自带隔离 site-packages）
    # dml_env Python: 安装目录\dml_env\python.exe（独立环境）
    # 系统 Python: 其他情况（需要 --target 避免污染）
    _is_system_python = True
    if install_dir:
        install_dir_norm = os.path.normpath(install_dir).lower()
        py_norm = os.path.normpath(python_exe).lower()
        if py_norm.startswith(os.path.join(install_dir_norm, "python")):
            _is_system_python = False  # embed Python
        elif py_norm.startswith(os.path.join(install_dir_norm, "dml_env")):
            _is_system_python = False  # dml_env Python
    # --target 目录（仅系统 Python 需要）
    _target_dir = None
    if _is_system_python and install_dir:
        _target_dir = os.path.join(install_dir, "Lib", "site-packages")
        os.makedirs(_target_dir, exist_ok=True)
    # 获取 Python 实际版本，按版本动态选择 pip 包配置
    py_version = "3.11.0"
    try:
        ver_r = subprocess.run(
            [python_exe, "-c", _PY_VER_SCRIPT],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if ver_r.returncode == 0:
            lines = ver_r.stdout.strip().splitlines()
            if len(lines) >= 2:
                py_version = lines[1].strip()
    except Exception:
        pass
    packages = []
    seen = set()
    for arch in archs:
        for item in get_pip_packages(arch, py_version):
            if isinstance(item, tuple):
                pkg_str, extra_args = item
            else:
                pkg_str, extra_args = item, []
            pkg_name = pkg_str.split("==")[0].split()[0]
            if pkg_name in _SKIP_PIP_FOR_USE:
                continue
            if pkg_str not in seen:
                seen.add(pkg_str)
                packages.append((pkg_str, extra_args))
    if not packages:
        on_progress(100, "无需 pip 安装（DirectML 依赖已预装）")
        return
    if not os.path.exists(python_exe):
        raise RuntimeError(f"Python 未找到: {python_exe}")

    # 检查 pip 是否需要升级
    _pip_need_upgrade = True
    try:
        ver_check = subprocess.run(
            [python_exe, "-m", "pip", "--version"],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        cur_ver = ver_check.stdout.strip()
        if "23." in cur_ver or "24." in cur_ver or "25." in cur_ver:
            _pip_need_upgrade = False
    except Exception:
        pass

    on_progress(5, "正在准备 pip 依赖安装...")

    # 断点恢复：pip 缓存位于 %LOCALAPPDATA%\BannerWeaveReverser\pip_cache
    # （安装成功即清理；失败/中断后重跑安装器时，已完整下载的 wheel 命中缓存，
    #  无需重新下载 1.8GB 的 CUDA torch）
    _pip_cache_dir = None
    if install_dir:
        # 缓存放 %LOCALAPPDATA% 而非安装目录：安装失败/取消时安装目录会被整体
        # 清理删除，放里面会让已完整下载的 wheel 一并丢失，重试又得重新下载
        # （CUDA torch 1.8GB）。放应用数据目录，失败重试可直接命中缓存续传。
        _pip_cache_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", tempfile.gettempdir()),
            "BannerWeaveReverser", "pip_cache")
        _cache_flag = ["--cache-dir", _pip_cache_dir]
    else:
        _cache_flag = ["--no-cache-dir"]
    all_cmds = []
    if _pip_need_upgrade:
        # pip 升级也加 --target，避免覆盖系统 pip 版本
        upgrade_cmd = [python_exe, "-m", "pip", "install", "--upgrade", "pip",
                       "--retries", "5", "--timeout", "120"] + _cache_flag
        if _target_dir:
            upgrade_cmd.extend(["--target", _target_dir])
        all_cmds.append(upgrade_cmd + PIP_MIRROR_ARGS)
    for pkg_str, extra_args in packages:
        if cancel_check and cancel_check():
            raise InterruptedError("用户取消安装")
        pkg_name = pkg_str.split("==")[0].split()[0]
        required_version = pkg_str.split("==")[1].split()[0] if "==" in pkg_str else None
        # ===== 按用户决策树处理 =====
        # 1. 判断必装/可选
        is_required = pkg_name in _REQUIRED_PKGS
        # 2. 可选组件：判断用户是否选择
        if not is_required:
            # torch/torchvision：CUDA/CPU 模式装到主环境；DirectML 模式主环境不装 torch
            # （AI 运算通过 subprocess 调用 dml_env 自带 Torch，绝不跨环境混用）
            if pkg_name in ("torch", "torchvision"):
                if "directml" in archs and "cuda" not in archs and "cpu" not in archs:
                    _dbg(f"step_install_pip_packages: directml-only, skip main env {pkg_name}")
                    continue
                if _torch_matches_user_choice(python_exe, archs):
                    _dbg(f"step_install_pip_packages: reuse system {pkg_name} (matches user choice)")
                    continue
            # nvidia-ml-py：仅 CUDA 模式
            if pkg_name == "nvidia-ml-py" and "cuda" not in archs:
                continue
            # matplotlib：仅训练器模式
            if pkg_name == "matplotlib" and purpose == "use":
                continue
        # 3. 必装组件 + 已选择的可选组件：检测系统版本
        sys_ver = _pip_get_version(python_exe, pkg_name, target_dir=None)
        if sys_ver and required_version:
            sys_base = sys_ver.split("+")[0]
            req_base = required_version.split("+")[0]
            if sys_base == req_base:
                _dbg(f"step_install_pip_packages: reuse system {pkg_name}=={sys_ver}")
                continue
            _dbg(f"step_install_pip_packages: system {pkg_name}=={sys_ver}, need {required_version}, install to target")
        elif sys_ver and not required_version:
            _dbg(f"step_install_pip_packages: reuse system {pkg_name}=={sys_ver}")
            continue
        # 4. 系统无或不匹配：检查安装目录
        # 对 torch/torchvision：还要校验应用目录版本的模式是否匹配用户选择
        # （防止：用户选 CUDA，但应用目录有 CPU 版 torch 被误判为"已安装"）
        if _pip_is_installed(python_exe, pkg_name, target_dir=_target_dir):
            if pkg_name in ("torch", "torchvision"):
                # DirectML-only：主环境不装 torch，已有也跳（防止误判断）
                if "directml" in archs and "cuda" not in archs and "cpu" not in archs:
                    _dbg(f"step_install_pip_packages: directml-only, skip main env {pkg_name} target check")
                    continue
                target_ver = _pip_get_version(python_exe, pkg_name, target_dir=_target_dir)
                if target_ver:
                    target_is_cuda = "cu" in target_ver
                    user_wants_cuda = "cuda" in archs
                    user_wants_cpu = "cpu" in archs
                    # 模式不匹配 → 不跳过，强制重装（覆盖旧版本）
                    if (user_wants_cuda and not target_is_cuda) or (user_wants_cpu and target_is_cuda):
                        _dbg(f"step_install_pip_packages: target {pkg_name}=={target_ver} mode mismatch (user wants {'cuda' if user_wants_cuda else 'cpu'}), reinstall")
                    else:
                        _dbg(f"step_install_pip_packages: skip already installed in target: {pkg_name}=={target_ver}")
                        continue
                else:
                    _dbg(f"step_install_pip_packages: skip already installed in target: {pkg_name}")
                    continue
            else:
                _dbg(f"step_install_pip_packages: skip already installed in target: {pkg_name}")
                continue
        # 5. 在线安装到安装目录
        # torch/torchvision 模式不匹配时强制覆盖旧版本（--upgrade --force-reinstall）
        # 否则 pip 看到 --target 已有同包会跳过下载
        cmd = [python_exe, "-m", "pip", "install", "--progress-bar", "raw",
               "--retries", "5", "--timeout", "120"] + _cache_flag
        if pkg_name in ("torch", "torchvision"):
            # 检查是否为模式切换重装（与第4步逻辑一致）
            _target_ver_for_upgrade = _pip_get_version(python_exe, pkg_name, target_dir=_target_dir) if _target_dir else None
            if _target_ver_for_upgrade:
                _target_is_cuda = "cu" in _target_ver_for_upgrade
                _user_cuda = "cuda" in archs
                _user_cpu = "cpu" in archs
                if (_user_cuda and not _target_is_cuda) or (_user_cpu and _target_is_cuda):
                    cmd.extend(["--upgrade", "--force-reinstall"])
        if _target_dir:
            cmd.extend(["--target", _target_dir])
        cmd.extend(pkg_str.split())
        if extra_args:
            cmd.extend(extra_args)
        else:
            cmd.extend(PIP_MIRROR_ARGS)
        all_cmds.append(cmd)

    if not all_cmds:
        on_progress(100, "无需 pip 安装")
        return

    wrapper_py = _write_progress_wrapper()
    progress_file = os.path.join(tempfile.gettempdir(), "_banner_pip_progress.txt")

    # CUDA torch 体积大：安装前明示预期，避免用户误以为卡死。
    # 已优先走阿里云国内直连镜像（实测约 2MB/s，约 15 分钟下完 1.8GB）
    _need_cuda_torch = any(
        ("torch" in pkg_str or "torchvision" in pkg_str) and "+cu" in pkg_str
        for pkg_str, _ in packages)
    if _need_cuda_torch:
        on_progress(8, "即将下载 CUDA 版 PyTorch（约 1.8GB）。已通过阿里云国内镜像加速下载，"
                       "通常 10~20 分钟完成；若长时间无进度可关闭 CMD 窗口后点「重试」。")

    on_progress(8, "正在启动 pip 安装窗口，请查看命令提示符中的原生进度条...")

    _rc = _run_in_cmd(wrapper_py, python_exe, "pip", all_cmds, progress_file,
                      "旗帜逆向套件 - pip 依赖安装", cancel_check=cancel_check,
                      on_pct=lambda p: on_progress(p, f"正在安装 pip 依赖... {p}%"))

    if _rc != 0:
        # 安装窗口被关闭 / pip 报错：主界面立即给出明确反馈，随后以实际检测
        # 判定成败（不再让用户"关窗后不知道是成功还是失败"）；已下载内容
        # 保留在缓存目录，重试可续传
        on_progress(45, "安装窗口已关闭或 pip 报错，正在验证已安装组件...")
    else:
        on_progress(95, "pip 命令执行完毕，正在验证安装结果...")

    # 检查关键依赖是否安装成功（系统已有或安装目录有都算成功）
    _failed_pkgs = []
    for pkg_str, _ in packages:
        pkg_name = pkg_str.split("==")[0].split()[0]
        # 先检查安装目录，再检查系统 Python
        if not _pip_is_installed(python_exe, pkg_name, target_dir=_target_dir):
            if not _pip_is_installed(python_exe, pkg_name, target_dir=None):
                _failed_pkgs.append(pkg_name)

    if _failed_pkgs:
        # 失败：保留 pip 缓存（已下载的 wheel 供下次重跑续传复用），不清理
        _torch_hint = ""
        if any(p in ("torch", "torchvision") for p in _failed_pkgs):
            _torch_hint = (
                "\n\n[PyTorch 专项提示]\n"
                "CUDA 版 PyTorch（torch==2.9.1+cu130）约 1.8GB。安装器已优先使用阿里云国内"
                "镜像（mirrors.aliyun.com/pytorch-wheels）加速，若仍失败通常是网络波动或"
                "镜像临时不可用。\n"
                "建议：1) 点「重试」（已下载的 wheel 会从缓存续传，不重复下载）；"
                "2) 改用 CPU 或 DirectML 模式安装（不需要 CUDA torch）；"
                "3) 开启代理/加速器后重试。")
        raise RuntimeError(
            f"以下依赖包安装失败：{', '.join(_failed_pkgs)}\n\n"
            f"请查看 CMD 窗口中的错误信息，或重试安装。\n{PIP_INSTALL_HINT}"
            + _torch_hint)

    # 安装成功：清理 .pip_cache，不残留磁盘负担
    if _pip_cache_dir and os.path.isdir(_pip_cache_dir):
        shutil.rmtree(_pip_cache_dir, ignore_errors=True)

    on_progress(100, "pip 依赖安装完成")


# pip 包名 → import 名映射（用于检测是否已装）
_PKG_IMPORT_MAP = {
    "torch": "torch", "torchvision": "torchvision",
    "PyQt5": "PyQt5", "numpy": "numpy",
    "opencv-python": "cv2", "Pillow": "PIL",
    "matplotlib": "matplotlib", "psutil": "psutil",
    "pynvml": "pynvml", "nvidia-ml-py": "pynvml", "pyadl": "pyadl",
}

# 必装组件（不管用户选什么模式都要检测和安装）
_REQUIRED_PKGS = {"PyQt5", "numpy", "opencv-python", "Pillow", "psutil"}


def _pip_is_installed(python_exe, pkg_name, target_dir=None):
    """检查包是否已安装。返回 True/False。

    target_dir 不为空时（--target 安装模式），用 PYTHONPATH 让 find_spec
    能找到安装目录中的包；否则按系统 site-packages 检查。
    """
    imp = _PKG_IMPORT_MAP.get(pkg_name, pkg_name)
    try:
        env = os.environ.copy()
        if target_dir:
            env["PYTHONPATH"] = target_dir
        result = subprocess.run(
            [python_exe, "-c", f"import importlib.util; print(importlib.util.find_spec('{imp}') is not None)"],
            capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW, env=env)
        return b"True" in result.stdout
    except Exception:
        return False


def _pip_get_version(python_exe, pkg_name, target_dir=None):
    """获取包的已安装版本。返回版本字符串（如 "2.9.1+cu130"），未安装返回 None。"""
    try:
        env = os.environ.copy()
        if target_dir:
            env["PYTHONPATH"] = target_dir
        result = subprocess.run(
            [python_exe, "-c",
             f"import importlib.metadata as m; print(m.version('{pkg_name}'))"],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW, env=env)
        if result.returncode == 0:
            ver = result.stdout.strip()
            if ver and not ver.startswith("Traceback"):
                return ver
    except Exception:
        pass
    return None


def _torch_matches_user_choice(python_exe, archs):
    """检测系统 Python 的 torch 是否匹配用户选择的模式与版本。

    返回 True 表示可以复用系统 torch（不装到安装目录）。
    - 用户选 CUDA + 系统有 torch≥2.9.1+cu130 → True
    - 用户选 CPU + 系统有 torch≥2.9.1（CPU 版）→ True
    - 版本 < 2.9.1 或 CUDA 版本非 cu130 → False（装到安装目录）
    """
    sys_torch_ver = _pip_get_version(python_exe, "torch", target_dir=None)
    if not sys_torch_ver:
        return False
    # 版本必须 >= 2.9.1（cu130 支持 RTX 20~50 系，旧版本不支持 RTX 50 系）
    try:
        ver_base = sys_torch_ver.split("+")[0]
        parts = [int(x) for x in ver_base.split(".")[:3]]
        if parts < [2, 9, 1]:
            return False
    except Exception:
        return False
    is_cuda_torch = "cu" in sys_torch_ver
    user_wants_cuda = "cuda" in archs
    user_wants_cpu = "cpu" in archs
    # DirectML-only：主环境不装 torch，系统有也不复用（AI 走 dml_env 子进程）
    if "directml" in archs and not user_wants_cuda and not user_wants_cpu:
        return False
    # CUDA 模式：必须 cu130（支持 RTX 20~50 系，cu124 不支持 RTX 50 系）
    if user_wants_cuda and is_cuda_torch and "cu130" in sys_torch_ver:
        return True
    if user_wants_cpu and not is_cuda_torch:
        return True
    return False


def _get_special_folder(csidl):
    """通过 shell32 API 获取特殊文件夹路径（不依赖 pywin32）。

    csidl 常用值：
      CSIDL_DESKTOP = 0x00     — 桌面
      CSIDL_PROGRAMS = 0x02    — 开始菜单程序目录
    """
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return buf.value


def _ps_quote(s):
    """将字符串转义为 PowerShell 单引号字符串（单引号转义为两个单引号）。"""
    return "'" + s.replace("'", "''") + "'"


def _create_lnk_ps(lnk_path, target_path, working_dir, icon_path=None, description="", arguments=None):
    """通过 PowerShell 创建快捷方式（不依赖 pywin32）。

    使用 WScript.Shell COM 对象，与 pywin32 效果完全一致。
    """
    parts = [
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(lnk_path)})",
        f"$s.TargetPath = {_ps_quote(target_path)}",
        f"$s.WorkingDirectory = {_ps_quote(working_dir)}",
    ]
    if icon_path and os.path.exists(icon_path):
        parts.append(f"$s.IconLocation = {_ps_quote(icon_path)}")
    if description:
        parts.append(f"$s.Description = {_ps_quote(description)}")
    if arguments:
        parts.append(f"$s.Arguments = {_ps_quote(arguments)}")
    parts.append("$s.Save()")
    ps_script = "; ".join(parts)
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception:
        pass


def step_create_shortcuts(install_path, on_progress, python_exe=None):
    """创建开始菜单和桌面快捷方式。

    python_exe: 安装/管理实际使用的系统 Python（python.exe 路径）。
        传入时优先用其同目录 pythonw 作为快捷方式目标，确保启动版本与
        安装时装包版本一致（避免用户多版本 Python 时用错）。
        未传入则回退 which/注册表查找。
    """
    on_progress(0, "正在创建快捷方式...")
    try:
        # CSIDL_PROGRAMS=0x02, CSIDL_DESKTOP=0x00
        start_menu = _get_special_folder(0x02)
        desktop = _get_special_folder(0x00)
        shortcut_dir = os.path.join(start_menu, "我的世界旗帜逆向套件")
        os.makedirs(shortcut_dir, exist_ok=True)
        # 快捷方式图标：tookit.ico（7 层完整图标，与 start 窗口图标一致）
        icon_path = os.path.join(install_path, "images", "icons", "tookit.ico")
        # 快捷方式目标：用系统 pythonw.exe（有 PyQt5）启动 start.pyw。
        # dml_env（3.10.11）只有 torch-directml，没有 PyQt5，不能启动 UI 程序。
        # 找不到系统 pythonw 时回退到 .pyw 直接关联（由系统默认 Python 打开）。
        sys_pythonw = None
        # 优先使用安装时实际用的系统 Python（与 pip 装包版本严格一致）
        if python_exe and os.path.isfile(python_exe):
            _pw = _pythonw_from_exe(python_exe)
            if os.path.isfile(_pw):
                sys_pythonw = _pw
        import shutil as _shutil
        # 刷新当前进程的 PATH（Python 安装器用 PrependPath=1 添加的路径不会自动反映到当前进程）。
        # 只有注册表里的用户 PATH 与当前进程 PATH 确实不同（即本安装器刚装过 Python）才广播
        # WM_SETTINGCHANGE，避免每次建快捷方式都强制 Explorer 刷新桌面、重绘图标（图标会短暂描边）。
        try:
            import ctypes
            import winreg as _wr
            _user_path = ""
            with _wr.OpenKey(_wr.HKEY_CURRENT_USER, r"Environment") as _ek:
                _user_path, _ = _wr.QueryValueEx(_ek, "Path")
            _sys_path = os.environ.get("PATH", "")
            if _user_path and _user_path.strip() not in _sys_path:
                HWND_BROADCAST = 0xFFFF
                WM_SETTINGCHANGE = 0x001A
                ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 0x2, 5000, None)
                os.environ["PATH"] = _user_path + os.pathsep + _sys_path
        except Exception:
            pass
        if not sys_pythonw:
            sys_pythonw = _shutil.which("pythonw")
        if not sys_pythonw:
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
                                    # 先查 ExecutablePath，再回退到 (Default) 安装目录
                                    try:
                                        exe_path, _ = winreg.QueryValueEx(ik, "ExecutablePath")
                                    except OSError:
                                        exe_path, _ = winreg.QueryValueEx(ik, None)
                                    winreg.CloseKey(ik)
                                except OSError:
                                    continue
                                if exe_path:
                                    # exe_path 可能是 python.exe 的完整路径，也可能是安装目录
                                    if os.path.isfile(exe_path):
                                        pw_dir = os.path.dirname(exe_path)
                                    else:
                                        pw_dir = exe_path
                                    pw = os.path.join(pw_dir, "pythonw.exe")
                                    if os.path.exists(pw):
                                        sys_pythonw = pw
                                        break
                            except OSError:
                                break
                        winreg.CloseKey(core)
                    except OSError:
                        pass
                    if sys_pythonw:
                        break
            except Exception:
                pass

        if sys_pythonw:
            target = sys_pythonw
            arguments = os.path.join(install_path, "start.pyw")
        else:
            # 回退：直接指向 start.pyw（由系统 .pyw 关联打开）
            target = os.path.join(install_path, "start.pyw")
            arguments = None
        for lnk_path in [
            os.path.join(shortcut_dir, "我的世界旗帜逆向套件.lnk"),
            os.path.join(desktop, "我的世界旗帜逆向套件.lnk"),
        ]:
            _create_lnk_ps(lnk_path, target, install_path,
                           icon_path=icon_path,
                           description="启动我的世界旗帜逆向套件",
                           arguments=arguments)
        on_progress(100, "快捷方式创建完成")
    except Exception as e:
        on_progress(100, f"快捷方式创建跳过（{e}）")


def step_register_install(install_path, archs, on_progress, cancel_check=None, models=None, purpose="train", python_exe=None):
    """注册安装信息：创建组件清单 + 注册表卸载项。

    这样 detect_install_state() 在下次运行安装包时能检测到已安装状态，
    自动进入维护模式而非重新安装。

    Args:
        archs: 后端架构列表（cuda/directml/cpu），install 模式必填
        models: 模型架构 key 列表（vit_b_16/deit_b_16 等），维护模式必填；
                install 模式可不传（保持向后兼容，清单不含 models 字段）
        python_exe: 本次安装/管理实际使用的系统 Python（python.exe 路径）。
                记录到清单，供快捷方式与"安装完成自动启动"精确复用同版本
                pythonw（避免 which/注册表找到用户旧版本 3.10/3.11/3.12，
                导致 start.pyw 加载不了对应版本扩展）。
    """
    on_progress(0, "正在注册安装信息...")

    # 1) 创建组件清单文件（合并旧数据，避免覆盖 models 等已有字段）
    comp_file = os.path.join(install_path, _COMPONENTS_FILE)
    old_data = {}
    if os.path.exists(comp_file):
        try:
            with open(comp_file, encoding="utf-8-sig") as f:
                old_data = json.load(f) or {}
        except Exception:
            pass
    comp_data = {
        "name": "我的世界旗帜逆向套件",
        "version": "1.0.8",
        "install_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "install_path": install_path,
        "archs": archs,
        "purpose": purpose,
        "components": list(_PROGRAM_FILES) + [a for a in archs if a not in _PROGRAM_FILES],
        # 库键名（供 test.pyw 按安装情况过滤检测项）
        "libraries": [
            "torch", "pyqt5", "numpy_cv2", "pillow", "psutil",
        ] + (["matplotlib", "pynvml"] if purpose == "train" else []),
        # 安装/管理实际使用的系统 Python（启动套件与快捷方式精确复用同版本）
        "python_exe": python_exe or "",
    }
    # 保留旧的 models 字段（维护模式记录的）；本次有传入则覆盖
    if models is not None:
        comp_data["models"] = list(models)
    elif "models" in old_data:
        comp_data["models"] = old_data["models"]
    try:
        with open(comp_file, "w", encoding="utf-8") as f:
            json.dump(comp_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # 锚定文件必须写入成功——否则下次启动检测不到已安装状态，
        # 会出现"安装完成但重装时又走全新安装"的不一致
        raise RuntimeError(f"组件清单写入失败：{comp_file}\n{e}")
    # 写入后立即读回校验
    if not _is_valid_install_dir(install_path):
        raise RuntimeError(f"组件清单校验失败：{comp_file} 写入后无法通过有效性检查")

    # 1.5) 同步 config.json 的训练架构：按实际安装的 archs 写入 train_arch，
    #      避免首次启动时 settings_manager 默认 "cuda" 与实际安装架构不符
    #      （装了 DirectML/CPU 却默认 CUDA → 训练器/识别器一启动就报错）。
    try:
        _arch_rank = ["directml", "cuda", "cpu"]
        _chosen = next((a for a in _arch_rank if a in (archs or [])), "cpu")
        _config_dir = os.path.join(install_path, "config")
        _cfg = os.path.join(_config_dir, "config.json")
        _cfg_data = {}
        if os.path.exists(_cfg):
            try:
                with open(_cfg, encoding="utf-8-sig") as f:
                    _cfg_data = json.load(f) or {}
            except Exception:
                _cfg_data = {}
        _cfg_data["train_arch"] = _chosen
        try:
            os.makedirs(_config_dir, exist_ok=True)
            with open(_cfg, "w", encoding="utf-8") as f:
                json.dump(_cfg_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # config 写失败不阻断安装（首次启动时 settings_manager 默认值兜底）
    except Exception:
        pass

    # 2) 注册表卸载项（HKCU，无需管理员权限）
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MinecraftBannerReverser"
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "我的世界旗帜逆向套件")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "1.0.8")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_path)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "")
        # 记录安装包 exe 路径（打包后 sys.executable 即安装包，开发环境留空）
        # 供 test.pyw 的"进入修复界面"读取并启动安装包进入维护/修复模式
        _installer_exe = sys.executable if getattr(sys, 'frozen', False) else ""
        winreg.SetValueEx(key, "InstallSource", 0, winreg.REG_SZ, _installer_exe)
        winreg.CloseKey(key)
    except Exception as e:
        # 注册表失败不阻断安装（固定路径/全盘扫描仍可检测），但要让用户知道并留痕
        _dbg(f"注册表写入失败: {type(e).__name__}: {e}")
        on_progress(90, f"警告：注册表写入失败（{e}），不影响使用")

    on_progress(100, "安装信息注册完成")


def run_install(archs, install_path, on_progress, cancel_check=None, models=None, purpose="train", selected_features=None):
    """执行完整安装流程（真实进度）。

    进度分配：
        0-10%   展开程序文件
        10-50%  获取 Python 运行时（检测系统/下载安装）
        50-70%  复制 DirectML 环境
        70-85%  pip 安装依赖
        85-93%  下载模型权重（ViT/DeiT 在线模型）
        93-96%  创建快捷方式
        96-100% 注册安装信息

    purpose: "train" = 安装训练器+识别器全部文件
             "use"   = 仅安装识别器，跳过 trainer.pyw/importer.pyw/matplotlib
    selected_features: set[str] - 用户勾选的库组件，传给 step_install_pip_packages 做精细过滤

    返回 None 表示完全成功；返回字符串表示部分模型下载失败（软件本体已装好），
    调用方应如实告知用户，不得伪装成完全成功。
    """
    archs = archs or ["cpu"]
    needs_py = bool(set(archs) & {"cuda", "cpu", "directml"})
    needs_dml = "directml" in archs

    # 步骤 1：展开程序文件 (0-10%)
    def _p1(pct, text):
        on_progress(int(pct * 0.10), text)
    step_extract_program_files(install_path, _p1, cancel_check, purpose=purpose)

    # 步骤 2：Python 运行时 (10-50%)
    python_exe = None
    if needs_py:
        def _p2(pct, text):
            on_progress(10 + int(pct * 0.40), text)
        python_exe = step_resolve_python311(install_path, _p2, cancel_check)
    else:
        on_progress(50, "无需系统 Python（仅 DirectML 模式）")

    # 步骤 3：DirectML 环境 (50-70%)
    if needs_dml:
        def _p3(pct, text):
            on_progress(50 + int(pct * 0.20), text)
        step_build_dml_env(install_path, _p3, cancel_check)
    else:
        on_progress(70, "无需 DirectML 环境")

    # 步骤 4：pip 依赖 (70-85%)
    def _p4(pct, text):
        on_progress(70 + int(pct * 0.15), text)
    if python_exe:
        step_install_pip_packages(archs, python_exe, _p4, cancel_check, purpose=purpose,
                                  install_dir=install_path, selected_features=selected_features)
    else:
        on_progress(85, "无需 pip 安装")

    # 步骤 4.5：模型权重下载 (85-93%)
    # 所有模型（ViT/DeiT）均通过 torchvision 在线下载预训练权重。
    # 下载失败不阻断安装（可事后用维护模式"管理组件"补下），但必须如实记录并告知
    failed_models = []
    dl_models = models or []
    if dl_models:
        models_dir = os.path.join(install_path, "models")
        os.makedirs(os.path.join(models_dir, "structures"), exist_ok=True)
        for i, m in enumerate(dl_models):
            if cancel_check and cancel_check():
                raise InterruptedError("用户取消安装")
            base = 85 + int(i * 8 / len(dl_models))
            span = max(int(8 / len(dl_models)), 1)
            ok, msg = _download_model_pth(
                m, models_dir, python_exe=python_exe,
                on_progress=lambda p, t, b=base, s=span: on_progress(b + int(p * s / 100), t),
                cancel_check=cancel_check)
            if not ok:
                failed_models.append((m, msg))
                _dbg(f"模型 {m} 下载失败: {msg}")
    else:
        on_progress(93, "无需下载模型权重（未勾选模型）")

    # 步骤 5：快捷方式 (93-96%)
    def _p5(pct, text):
        on_progress(93 + int(pct * 0.03), text)
    step_create_shortcuts(install_path, _p5, python_exe=python_exe)

    # 步骤 6：注册安装信息 (96-100%)，同时记录已选模型清单
    def _p6(pct, text):
        on_progress(96 + int(pct * 0.04), text)
    step_register_install(install_path, archs, _p6, cancel_check, models=models,
                          purpose=purpose, python_exe=python_exe)

    # 步骤 7：写入身份标记文件（继承 exe 同目录的 tester，否则 user）
    _write_build_tag(install_path)

    # 最终自校验：确保"显示安装成功 = 安装真实存在"
    # （防止任何步骤静默失败后仍提示成功，导致下次启动状态不一致）
    if not _is_valid_install_dir(install_path):
        raise RuntimeError(
            f"安装自校验失败：{install_path} 未通过有效性检查\n"
            f"（缺少 {_COMPONENTS_FILE} 或内容无效）\n"
            f"安装未完成，请重试。")
    _dbg(f"run_install: 自校验通过 {install_path}")

    on_progress(100, "安装完成！")

    # 模型下载失败不静默：如实返回失败清单，由调用方告知用户
    if failed_models:
        return ("软件本体已安装成功，但以下模型权重下载失败：\n\n" +
                "\n".join(f"· {m}：{msg}" for m, msg in failed_models) +
                "\n\n可重新运行本安装器，进入「维护模式 → 管理模型与训练组件」重新下载。")
    return None


def _write_build_tag(install_path):
    """安装完成后在安装目录写 build_tag.txt。

    身份继承规则：
      - 若 exe 同目录有 build_tag.txt（作者分发测试包时附带），继承其 role
      - 否则标记为 tester（测试阶段，普通用户身份暂未开放）
    """
    try:
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
            else os.path.dirname(os.path.abspath(__file__))
        role = _read_identity(exe_dir) or "tester"
        if role not in ("dev", "tester", "user"):
            role = "tester"
        tag_path = os.path.join(install_path, _BUILD_TAG_FILE)
        with open(tag_path, "w", encoding="utf-8") as f:
            f.write(f"# 旗帜逆向套件 身份标识\nrole={role}\n")
    except Exception:
        pass


def _launch_demo_installer(dev_path):
    """启动开发目录下的 demo_installer.pyw（演示模式）。

    仅作者（dev 身份）可用——demo_installer.pyw 不打包进 exe，
    只有开发源文件目录存在。返回 True 表示已启动。
    """
    import shutil
    demo_path = os.path.join(dev_path, "installer", "demo_installer.pyw")
    if not os.path.isfile(demo_path):
        return False
    # 找 Python 解释器：优先系统已装（注册表/PATH），回退 py launcher
    py_exe = None
    for exe, _ver in _scan_system_python():
        if os.path.basename(exe).lower().startswith("python"):
            py_exe = exe
            break
    if not py_exe:
        import shutil
        py_exe = shutil.which("py")
    if not py_exe:
        return False
    try:
        # py launcher 需要先传 -3 参数
        cmd = [py_exe] if os.path.basename(py_exe).lower().startswith("python") \
            else [py_exe, "-3"]
        cmd += [demo_path]
        # 用干净环境启动：demo_installer 是独立 PyQt 程序，若继承安装器的
        # QT_PLUGIN_PATH 会从安装器 _MEI 临时目录加载 Qt 插件并锁住它们，
        # 导致安装器退出时清理 _MEI 失败弹警告
        subprocess.Popen(cmd, cwd=dev_path,
                         env=_clean_launch_env(),
                         creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except Exception:
        return False


def _is_pth_complete(pth_path, model_key):
    """检查 .pth 是否存在且大小合理（非残缺文件）。

    下载中断会留下残缺的 .pth（例如 vit_h_14 预期 2.5GB，断线时只下了 500MB），
    仅用 os.path.exists 会误判为"已安装"，导致下次不重下、训练时加载失败。
    这里按 _MODEL_ARCHS 中的预期大小做 85% 阈值校验。
    """
    if not os.path.exists(pth_path):
        return False
    size = os.path.getsize(pth_path)
    if size <= 1024:
        return False
    for item in _MODEL_ARCHS:
        if item[0] == model_key:
            expected = int(item[4] * 1024 * 1024 * 1024)  # pth_dl_gb → 字节（先取整避免浮点误差）
            return size >= int(expected * 0.85)  # 85% 阈值，容忍版本差异
    return True  # 未知模型，存在且非空即视为完整


def _download_model_pth(model_key, models_dir, python_exe=None, on_progress=None, cancel_check=None):
    """下载模型 .pth 权重文件（ViT/DeiT 均为在线下载）。"""
    arch_info = None
    for item in _MODEL_ARCHS:
        if item[0] == model_key:
            arch_info = item
            break
    if not arch_info:
        return False, "未知模型架构"

    # models_dir = 安装目录/models → app_root = 安装目录
    app_root = os.path.dirname(models_dir)

    # Python 选择优先级：
    #   1. 传入的 python_exe（系统 Python）— 如果能 import torch 则直接用
    #   2. dml_env python — DML-only 用户系统 Python 没 torch，必须用 dml_env 处理权重
    #   3. 目录内独立安装的 embed Python
    if not python_exe:
        sys_py, _ver = detect_system_python311()
        if sys_py:
            python_exe = sys_py
    if not python_exe:
        embed_py = os.path.join(app_root, "python", "python.exe")
        if os.path.isfile(embed_py):
            python_exe = embed_py
    if not python_exe:
        return False, "未找到 Python 解释器，请先安装 Python"

    # 检测 python_exe 是否能 import torch；不能则切换到 dml_env python
    _has_torch = False
    try:
        _r = subprocess.run(
            [python_exe, "-c", "import torch; print('ok')"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        _has_torch = _r.returncode == 0 and 'ok' in _r.stdout
    except Exception:
        pass
    if not _has_torch:
        dml_py = os.path.join(app_root, "dml_env", "python.exe")
        if os.path.isfile(dml_py):
            python_exe = dml_py

    # pythonw.exe 无 stdout，CMD 下载进度需要 python.exe（有控制台输出）
    if python_exe.lower().endswith("pythonw.exe"):
        py_console = os.path.join(os.path.dirname(python_exe), "python.exe")
        if os.path.isfile(py_console):
            python_exe = py_console

    # 所有模型统一从 hf-mirror.com 下载 transformers 格式 + 转换为 torchvision 格式
    # 不用 torch.hub.load_state_dict_from_url（缓存机制会导致文件下载错误，如 deit_s_16 下载成 deit_b_16）
    # 用 urllib 直接下载到临时文件，避免缓存冲突
    _HF_URLS = {
        "vit_b_16": "https://hf-mirror.com/google/vit-base-patch16-224/resolve/main/pytorch_model.bin",
        "vit_l_16": "https://hf-mirror.com/google/vit-large-patch16-224/resolve/main/pytorch_model.bin",
        "vit_h_14": "https://hf-mirror.com/google/vit-huge-patch14-224-in21k/resolve/main/pytorch_model.bin",
        "deit_b_16": "https://hf-mirror.com/facebook/deit-base-patch16-224/resolve/main/pytorch_model.bin",
        "deit_s_16": "https://hf-mirror.com/facebook/deit-small-patch16-224/resolve/main/pytorch_model.bin",
        "deit_t_16": "https://hf-mirror.com/facebook/deit-tiny-patch16-224/resolve/main/pytorch_model.bin",
    }
    _HF_LAYERS = {
        "vit_b_16": 12, "vit_l_16": 24, "vit_h_14": 32,
        "deit_b_16": 12, "deit_s_16": 12, "deit_t_16": 12,
    }
    hf_url = _HF_URLS.get(model_key)
    num_layers = _HF_LAYERS.get(model_key)
    if not hf_url or not num_layers:
        return False, f"不支持的模型: {model_key}"
    pth_path = os.path.join(models_dir, "structures", f"{model_key}.pth")
    # is satisfied: .pth 已存在且大小达标（非残缺）才跳过下载
    if _is_pth_complete(pth_path, model_key):
        if on_progress:
            on_progress(100, f"{model_key}.pth 已存在，跳过下载（is satisfied）")
        return True, "已存在，跳过下载"

    try:
        import tempfile as _tf
        progress_file = os.path.join(_tf.gettempdir(), f"_banner_dl_progress_{model_key}.txt")
        # 确保 models/structures/ 目录存在
        os.makedirs(os.path.join(models_dir, "structures"), exist_ok=True)

        # 应用目录已装的 torchvision 优先加载（系统 Python 无 torchvision 时必需）
        # 根据实际使用的 Python 解释器查找正确的 site-packages 路径
        vendor_pkgs = _get_site_packages_for_python(python_exe, app_root)
        if not vendor_pkgs:
            vendor_pkgs = os.path.join(app_root, "Lib", "site-packages")

        # 统一下载脚本：从 hf-mirror.com 用 urllib 下载 .bin → 转换 key → 保存为 .pth
        # 不用 torch.hub（缓存机制会导致 deit_s_16 下载成 deit_b_16 的权重）
        # urllib 带 timeout=600，避免 urlopen 无限等待；3 次重试
        _tmp_bin = os.path.join(_tf.gettempdir(), f"_banner_hf_{model_key}.bin")
        dl_script = (
            f"import sys, os, time, urllib.request, ssl\n"
            f"_vp = r'{vendor_pkgs}'\n"
            f"sys.path.insert(0, _vp)\n"
            f"os.environ['PYTHONPATH'] = _vp + os.pathsep + os.environ.get('PYTHONPATH', '')\n"
            f"if hasattr(os, 'add_dll_directory'):\n"
            f"    os.add_dll_directory(_vp)\n"
            f"    _tl = os.path.join(_vp, 'torch', 'lib')\n"
            f"    if os.path.isdir(_tl):\n"
            f"        os.add_dll_directory(_tl)\n"
            f"        os.environ['PATH'] = _tl + os.pathsep + os.environ.get('PATH', '')\n"
            f"import torch\n"
            f"_url = r'{hf_url}'\n"
            f"_tmp_bin = r'{_tmp_bin}'\n"
            f"_num_layers = {num_layers}\n"
            f"_ctx = ssl.create_default_context()\n"
            f"_ctx.check_hostname = False\n"
            f"_ctx.verify_mode = ssl.CERT_NONE\n"
            f"# 断点续传：已有临时文件则从断点继续（服务器支持 Range 时）\n"
            f"_have = os.path.getsize(_tmp_bin) if os.path.isfile(_tmp_bin) else 0\n"
            f"_down_ok = False   # 标记本次下载是否完整（转换失败时删除重下，网络中断时保留断点）\n"
            f"for _attempt in range(5):\n"
            f"    try:\n"
            f"        _headers = {{'User-Agent': 'Mozilla/5.0'}}\n"
            f"        if _have > 0:\n"
            f"            _headers['Range'] = f'bytes={{_have}}-'\n"
            f"        _req = urllib.request.Request(_url, headers=_headers)\n"
            f"        with urllib.request.urlopen(_req, timeout=600, context=_ctx) as _resp:\n"
            f"            _status = getattr(_resp, 'status', 200)\n"
            f"            if _status == 206:\n"
            f"                _mode = 'ab'          # 服务器支持断点续传，追加写\n"
            f"            else:\n"
            f"                _mode = 'wb'          # 不支持续传，从头下载\n"
            f"                _have = 0\n"
            f"            _total = _have + int(_resp.headers.get('Content-Length', 0))\n"
            f"            _done = _have\n"
            f"            with open(_tmp_bin, _mode) as _f:\n"
            f"                while True:\n"
            f"                    _chunk = _resp.read(8192*1024)\n"
            f"                    if not _chunk:\n"
            f"                        break\n"
            f"                    _f.write(_chunk)\n"
            f"                    _done += len(_chunk)\n"
            f"                    if _total > 0:\n"
            f"                        _pct = min(100, int(_done * 100 / _total))\n"
            f"                        print(f'\\r{{_pct}}%', end='', flush=True)\n"
            f"            _down_ok = True   # 读流结束，下载完整\n"
            f"        _src = torch.load(_tmp_bin, map_location='cpu', weights_only=False)\n"
            f"        # 兼容嵌套字典：部分 HuggingFace 权重包在 state_dict/model 里\n"
            f"        if isinstance(_src, dict) and not any(k.endswith('cls_token') for k in _src):\n"
            f"            for _wrap in ('state_dict', 'model', 'model_state_dict'):\n"
            f"                if _wrap in _src and isinstance(_src[_wrap], dict):\n"
            f"                    _src = _src[_wrap]\n"
            f"                    break\n"
            f"        # 检测 key 前缀（'vit.' 或空）\n"
            f"        _pfx = 'vit.' if ('vit.embeddings.cls_token' in _src) else ''\n"
            f"        _cls_key = _pfx + 'embeddings.cls_token'\n"
            f"        if not isinstance(_src, dict) or _cls_key not in _src:\n"
            f"            _keys = list(_src.keys())[:10] if isinstance(_src, dict) else str(type(_src))\n"
            f"            raise RuntimeError(f'权重格式不符，前10个key: {{_keys}}')\n"
            f"        _new = {{}}\n"
            f"        _new['class_token'] = _src[_pfx + 'embeddings.cls_token']\n"
            f"        _new['encoder.pos_embedding'] = _src[_pfx + 'embeddings.position_embeddings']\n"
            f"        _new['conv_proj.weight'] = _src[_pfx + 'embeddings.patch_embeddings.projection.weight']\n"
            f"        _new['conv_proj.bias'] = _src[_pfx + 'embeddings.patch_embeddings.projection.bias']\n"
            f"        _new['encoder.ln.weight'] = _src[_pfx + 'layernorm.weight']\n"
            f"        _new['encoder.ln.bias'] = _src[_pfx + 'layernorm.bias']\n"
            f"        if (_pfx + 'classifier.weight') in _src:\n"
            f"            _new['heads.head.weight'] = _src[_pfx + 'classifier.weight']\n"
            f"            _new['heads.head.bias'] = _src[_pfx + 'classifier.bias']\n"
            f"        for _L in range(_num_layers):\n"
            f"            _sp = _pfx + 'encoder.layer.' + str(_L)\n"
            f"            _tp = 'encoder.layers.encoder_layer_' + str(_L)\n"
            f"            _new[_tp + '.self_attention.in_proj_weight'] = torch.cat([_src[_sp + '.attention.attention.query.weight'], _src[_sp + '.attention.attention.key.weight'], _src[_sp + '.attention.attention.value.weight']], dim=0)\n"
            f"            _new[_tp + '.self_attention.in_proj_bias'] = torch.cat([_src[_sp + '.attention.attention.query.bias'], _src[_sp + '.attention.attention.key.bias'], _src[_sp + '.attention.attention.value.bias']], dim=0)\n"
            f"            _new[_tp + '.self_attention.out_proj.weight'] = _src[_sp + '.attention.output.dense.weight']\n"
            f"            _new[_tp + '.self_attention.out_proj.bias'] = _src[_sp + '.attention.output.dense.bias']\n"
            f"            _new[_tp + '.ln_1.weight'] = _src[_sp + '.layernorm_before.weight']\n"
            f"            _new[_tp + '.ln_1.bias'] = _src[_sp + '.layernorm_before.bias']\n"
            f"            _new[_tp + '.ln_2.weight'] = _src[_sp + '.layernorm_after.weight']\n"
            f"            _new[_tp + '.ln_2.bias'] = _src[_sp + '.layernorm_after.bias']\n"
            f"            _new[_tp + '.mlp.0.weight'] = _src[_sp + '.intermediate.dense.weight']\n"
            f"            _new[_tp + '.mlp.0.bias'] = _src[_sp + '.intermediate.dense.bias']\n"
            f"            _new[_tp + '.mlp.3.weight'] = _src[_sp + '.output.dense.weight']\n"
            f"            _new[_tp + '.mlp.3.bias'] = _src[_sp + '.output.dense.bias']\n"
            f"        torch.save(_new, r'{pth_path}')\n"
            f"        try: os.remove(_tmp_bin)\n"
            f"        except OSError: pass\n"
            f"        print('\\n转换完成')\n"
            f"        break\n"
            f"    except Exception:\n"
            f"        if _down_ok:\n"
            f"            # 下载完整但转换失败（文件损坏）：删除重下，避免 Range=全文 卡 416\n"
            f"            try: os.remove(_tmp_bin)\n"
            f"            except OSError: pass\n"
            f"            _have = 0\n"
            f"        # 网络中断：保留已下载临时文件，下次重试从断点继续\n"
            f"        if _attempt == 4:\n"
            f"            raise\n"
            f"        time.sleep(3 * (_attempt + 1))\n"
        )
        script_path = os.path.join(_tf.gettempdir(), f"_banner_dl_{model_key}.py")
        with open(script_path, "w", encoding="utf-8") as _f:
            _f.write(dl_script)

        # 使用统一 wrapper：原样输出 tqdm 到 CMD，同时解析 xx% 到进度文件
        wrapper_py = _write_progress_wrapper()
        dl_cmd = [python_exe, script_path]

        if on_progress:
            on_progress(0, f"正在下载 {model_key} 预训练权重（约 {arch_info[4]:.1f} GB）")

        _run_in_cmd(wrapper_py, python_exe, "tqdm", [dl_cmd], progress_file,
                    f"下载 {model_key} 预训练权重",
                    cancel_check=cancel_check,
                    on_pct=lambda p: on_progress(p, f"正在下载 {model_key}... {p}%") if on_progress else None)

        # 清理临时文件：成功才删除 .bin（断点续传：失败保留断点供下次续传）
        if _is_pth_complete(pth_path, model_key):
            for _tmp in (script_path, progress_file, _tmp_bin):
                try:
                    os.remove(_tmp)
                except Exception:
                    pass
            return True, "下载成功"
        # 失败：保留 _tmp_bin（断点），下次安装/管理组件时从断点续传
        for _tmp in (script_path, progress_file):
            try:
                os.remove(_tmp)
            except Exception:
                pass
        return False, "模型下载失败（文件残缺或不完整，已保留断点）"
    except InterruptedError:
        raise
    except Exception as e:
        return False, f"下载异常: {e}"


def run_manage_components(archs, models, install_path, on_progress, cancel_check=None, purpose="train"):
    """维护模式：管理模型与训练组件（含 pip 库安装/卸载）。

    流程：
        1. 读取已安装组件清单 install_components.json
        2. 计算 archs 和 models 的增减
        3. 卸载取消选择的 pip 包（pip uninstall）
        4. 删除取消选择的 .pth 模型文件
        5. 安装新勾选的 pip 包（弹 CMD 窗口，与首次安装一致）
        6. 下载新勾选的 .pth 模型权重
        7. 更新快捷方式与组件清单

    进度分配：
        0-5%    读取分析
        5-20%   卸载取消的 pip 包
        20-35%  删除取消的 .pth 文件
        35-75%  安装新增 pip 包（CMD 窗口）
        75-90%  下载新增 .pth 模型权重
        90-95%  更新快捷方式
        95-100% 更新组件清单
    """
    archs = archs or []
    models = models or []

    # 提取训练器勾选状态（_trainer 为伪模型，用于表示是否要带训练器/导入器）
    want_trainer = "_trainer" in models
    models = [m for m in models if m != "_trainer"]

    on_progress(2, "正在读取已安装组件清单...")

    # 1) 读取旧配置
    comp_file = os.path.join(install_path, _COMPONENTS_FILE)
    old_models = []
    old_archs = []
    old_purpose = "train"  # 升级历史兼容：老版本未记录 purpose 时按 train 处理
    old_had_trainer = False  # 旧版本是否带训练器（trainer.pyw 存在判定 + old_purpose == train）
    if os.path.exists(comp_file):
        try:
            with open(comp_file, encoding="utf-8-sig") as f:
                data = json.load(f) or {}
                old_models = data.get("models", []) or []
                old_archs = data.get("archs", []) or []
                old_purpose = data.get("purpose", old_purpose)
                components = data.get("components", []) or []
                # 训练器标志：旧配置中 trainer 组件存在 或 purpose==train
                if "trainer" in components or old_purpose == "train":
                    old_had_trainer = True
        except Exception:
            pass
    # 存在性双重校验（防老版本未记录）
    if not old_had_trainer and os.path.exists(os.path.join(install_path, "trainer.pyw")):
        old_had_trainer = True

    old_arch_set = set(old_archs)
    new_arch_set = set(archs)
    added_archs = [a for a in archs if a not in old_arch_set]
    removed_archs = [a for a in old_archs if a not in new_arch_set]

    old_model_set = set(old_models)
    new_model_set = set(models)
    # added_models：新增的 + 配置说有但 .pth 文件实际缺失的（需重新下载）
    models_dir = os.path.join(install_path, "models")
    added_models = []
    for m in models:
        if m not in old_model_set:
            added_models.append(m)
        else:
            # 配置说已装，但 .pth 文件可能不存在或残缺（下载中断场景）
            pth_path = os.path.join(models_dir, "structures", f"{m}.pth")
            if not _is_pth_complete(pth_path, m):
                added_models.append(m)
    removed_models = [m for m in old_models if m not in new_model_set]

    on_progress(5, (
        f"架构变更：+{added_archs or []} / -{removed_archs or []}  |  "
        f"模型变更：+{added_models or []} / -{removed_models or []}"
    ))

    # 1.5) 补全训练器文件
    if want_trainer:
        on_progress(3, "正在安装训练器文件 (trainer.pyw + importer.pyw)...")
        meipass = _get_meipass()
        for fname in ("trainer.pyw", "importer.pyw"):
            src = os.path.join(meipass, fname)
            dst = os.path.join(install_path, fname)
            if os.path.exists(src):
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass
        on_progress(5, "训练器文件安装完成")

    # 2) 卸载取消选择的 pip 包（removed_archs）
    if removed_archs:
        # 拆分卸载：CUDA/CPU 从主环境卸载，DirectML 从 dml_env 卸载
        _rm_cuda_cpu = [a for a in removed_archs if a in ("cuda", "cpu")]
        _rm_dml = [a for a in removed_archs if a == "directml"]

        if _rm_cuda_cpu:
            on_progress(8, f"正在卸载 CUDA/CPU 库：{', '.join(_rm_cuda_cpu)}...")
            py_main = _find_installed_python(install_path, _rm_cuda_cpu)
            if py_main and os.path.exists(py_main):
                _pip_uninstall_arch_packages(_rm_cuda_cpu, py_main, install_path,
                                             on_progress, cancel_check, start_pct=8, end_pct=14)
            else:
                on_progress(14, "未找到 Python 解释器，跳过 CUDA/CPU pip 卸载")

        if _rm_dml:
            on_progress(14, f"正在卸载 DirectML 库：{', '.join(_rm_dml)}...")
            py_dml = _find_installed_python(install_path, ["directml"])
            if py_dml and os.path.exists(py_dml):
                _pip_uninstall_arch_packages(_rm_dml, py_dml, install_path,
                                             on_progress, cancel_check, start_pct=14, end_pct=20)
            else:
                on_progress(20, "未找到 dml_env Python，跳过 DirectML pip 卸载")
    else:
        on_progress(20, "无需卸载的库")

    # 2.5) 降级/卸载：取消训练器 → 删除 trainer.pyw + importer.pyw
    #               取消 DirectML 架构 → 删除整个 dml_env（1.2GB，省空间）
    removed_files_msg = []
    if old_had_trainer and not want_trainer:
        on_progress(21, "正在卸载训练器/导入器文件...")
        import shutil as _sh
        for fname in ("trainer.pyw", "importer.pyw"):
            fpath = os.path.join(install_path, fname)
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                    removed_files_msg.append(fname)
                except Exception:
                    pass
        on_progress(22, f"已卸载训练器相关文件: {', '.join(removed_files_msg) or '无'}")

    if "directml" in removed_archs:
        on_progress(22, "正在删除 DirectML 环境（dml_env，约 1.2GB，可能需要几秒）...")
        import shutil as _sh
        dml_env_path = os.path.join(install_path, "dml_env")
        if os.path.isdir(dml_env_path):
            try:
                _sh.rmtree(dml_env_path, ignore_errors=True)
                # 双重确认：目录删不净的情况再强制
                if os.path.isdir(dml_env_path):
                    try:
                        for _root, _dirs, _files in os.walk(dml_env_path, topdown=False):
                            for _fn in _files:
                                try:
                                    os.remove(os.path.join(_root, _fn))
                                except Exception:
                                    pass
                            for _dn in _dirs:
                                try:
                                    os.rmdir(os.path.join(_root, _dn))
                                except Exception:
                                    pass
                        os.rmdir(dml_env_path)
                    except Exception:
                        pass
            except Exception:
                pass
        if not os.path.isdir(dml_env_path):
            removed_files_msg.append("dml_env")
            on_progress(23, "已卸载 DirectML 环境（约 1.2GB 空间已释放）")
        else:
            on_progress(23, "DirectML 环境未完全删除，稍后请手动删除 dml_env 目录")

    # 3) 删除取消选择的 .pth 文件
    models_dir = os.path.join(install_path, "models")
    if removed_models:
        total = len(removed_models)
        for i, m in enumerate(removed_models):
            if cancel_check and cancel_check():
                raise InterruptedError("用户取消操作")
            pct = 23 + int(i * 12 / max(total, 1))
            on_progress(pct, f"正在删除 {m}.pth...")
            pth_path = os.path.join(models_dir, "structures", f"{m}.pth")
            if os.path.exists(pth_path):
                try:
                    os.remove(pth_path)
                except Exception:
                    pass
        on_progress(35, f"已删除 {len(removed_models)} 个模型文件")
    else:
        on_progress(35, "无需删除的模型文件")

    # 4) 安装新增 pip 包（弹 CMD 窗口，与首次安装一致）
    if added_archs:
        # 拆分安装：CUDA/CPU 用系统 Python（装到主环境），DirectML 用 dml_env Python
        _cuda_cpu_archs = [a for a in added_archs if a in ("cuda", "cpu")]
        _dml_archs = [a for a in added_archs if a == "directml"]

        if _cuda_cpu_archs:
            on_progress(37, f"正在安装 CUDA/CPU 库：{', '.join(_cuda_cpu_archs)}...")
            py_main = _find_installed_python(install_path, _cuda_cpu_archs)
            if py_main and os.path.exists(py_main):
                def _p_pip_main(pct, text):
                    on_progress(37 + int(pct * 0.19), text)
                step_install_pip_packages(_cuda_cpu_archs, py_main, _p_pip_main, cancel_check,
                                         purpose=purpose, install_dir=install_path)
                on_progress(56, "CUDA/CPU pip 依赖安装完成")
            else:
                on_progress(56, "未找到系统 Python，跳过 CUDA/CPU pip 安装")

        if _dml_archs:
            on_progress(56, f"正在安装 DirectML 库：{', '.join(_dml_archs)}...")
            py_dml = _find_installed_python(install_path, ["directml"])
            if py_dml and os.path.exists(py_dml):
                def _p_pip_dml(pct, text):
                    on_progress(56 + int(pct * 0.19), text)
                step_install_pip_packages(_dml_archs, py_dml, _p_pip_dml, cancel_check,
                                         purpose=purpose, install_dir=install_path)
                on_progress(75, "DirectML pip 依赖安装完成")
            else:
                on_progress(75, "未找到 dml_env Python，跳过 DirectML pip 安装")
    else:
        on_progress(75, "无新增库需要安装")

    # 5) 下载新增 .pth 模型权重（所有模型均在线下载）
    # 获取下载用 Python（与 pip 安装逻辑一致：CUDA/CPU 用系统 Python，DirectML 用 dml_env Python）
    _dl_py = _find_installed_python(install_path, archs)
    if added_models:
        total = len(added_models)
        os.makedirs(os.path.join(models_dir, "structures"), exist_ok=True)
        restored, failed = [], []
        for i, m in enumerate(added_models):
            if cancel_check and cancel_check():
                raise InterruptedError("用户取消操作")
            base = 75 + int(i * 15 / total)
            span = max(int(15 / total), 1)
            on_progress(base, f"正在检查 {m}.pth...")
            pth_path = os.path.join(models_dir, "structures", f"{m}.pth")
            if _is_pth_complete(pth_path, m):
                continue
            ok, msg = _download_model_pth(
                m, models_dir, python_exe=_dl_py,
                on_progress=lambda p, t, b=base, s=span, _m=m: on_progress(b + int(p * s / 100), f"[{_m}] {t}"),
                cancel_check=cancel_check)
            if ok:
                restored.append(m)
            else:
                failed.append((m, msg))
        parts = []
        if restored:
            parts.append(f"已下载模型：{', '.join(restored)}")
        if failed:
            parts.append(f"{len(failed)} 个下载失败：{', '.join(m for m, _ in failed)}")
        on_progress(90, "；".join(parts) if parts else "新增模型文件均已就位")
    else:
        on_progress(90, "无新增模型")

    # 6) 更新快捷方式
    def _ps(pct, text):
        on_progress(90 + int(pct * 0.05), text)
    _py_for_lnk = _find_installed_python(install_path, archs)
    step_create_shortcuts(install_path, _ps, python_exe=_py_for_lnk)

    # 7) 更新组件清单（archs 和 models 均更新为最新勾选）
    def _pr(pct, text):
        on_progress(95 + int(pct * 0.05), text)
    _py_for_reg = _find_installed_python(install_path, archs)
    step_register_install(install_path, archs, _pr, cancel_check,
                          models=models, purpose=purpose, python_exe=_py_for_reg)

    on_progress(100, "组件管理完成！")


def _find_installed_python(install_path, archs=None):
    """在已安装目录中查找 Python 解释器。

    根据 archs 选择正确的 Python：
    - 仅 directml → dml_env Python（DirectML 专用环境，不可被 CUDA/CPU 污染）
    - 含 cuda 或 cpu → 优先系统 Python（装到 install_path/Lib/site-packages），
      其次 embed Python，最后才回退 dml_env Python
    """
    archs = archs or []
    has_cuda_or_cpu = "cuda" in archs or "cpu" in archs
    only_directml = "directml" in archs and not has_cuda_or_cpu

    # 仅 DirectML：用 dml_env Python
    if only_directml:
        dml_py = os.path.join(install_path, "dml_env", "python.exe")
        if os.path.exists(dml_py):
            return dml_py

    # CUDA/CPU 模式：优先系统 Python，其次 embed Python
    if has_cuda_or_cpu or not only_directml:
        # 系统 Python 查找候选列表（按优先级排序）
        import glob as _glob
        import shutil as _shutil
        sys_py_candidates = []
        # 0. 安装时记录的 python_exe（与 pip 装包版本严格一致）。
        #    多版本用户（3.10/3.11/3.12/3.13 共存）时，which/注册表可能找到别的版本，
        #    导致 pip 新装 wheel 的 cp 标识与启动用的记录版本不符，加载失败。
        _comp_file = os.path.join(install_path, _COMPONENTS_FILE)
        if os.path.exists(_comp_file):
            try:
                with open(_comp_file, encoding="utf-8-sig") as _f:
                    _rec_py = (json.load(_f) or {}).get("python_exe") or ""
                if _rec_py and os.path.isfile(_rec_py) \
                        and _rec_py not in sys_py_candidates:
                    sys_py_candidates.append(_rec_py)
            except Exception:
                pass
        # 1. shutil.which("python") — 可能返回 WindowsApps 别名（不一定可用）
        _which_py = _shutil.which("python")
        if _which_py:
            sys_py_candidates.append(_which_py)
        # 2. 固定安装路径：%LOCALAPPDATA%\Programs\Python\Python3*\python.exe
        _local_app = os.environ.get("LOCALAPPDATA", "")
        if _local_app:
            for py_dir in sorted(_glob.glob(os.path.join(_local_app, "Programs", "Python", "Python3*")), reverse=True):
                py_exe = os.path.join(py_dir, "python.exe")
                if os.path.exists(py_exe) and py_exe not in sys_py_candidates:
                    sys_py_candidates.append(py_exe)
        # 逐个验证候选（需版本 >= 3.10.11，且能正常执行）
        for sys_py in sys_py_candidates:
            try:
                r = subprocess.run(
                    [sys_py, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode == 0:
                    ver = r.stdout.strip()
                    parts = ver.split(".")
                    if len(parts) >= 3:
                        major, minor, micro = int(parts[0]), int(parts[1]), int(parts[2])
                        if (major, minor, micro) >= (3, 10, 11):
                            return sys_py
            except Exception:
                pass
        # embed Python
        embed_py = os.path.join(install_path, "python", "python.exe")
        if os.path.exists(embed_py):
            return embed_py

    # 回退：dml_env Python（最后手段，仅当没有其他选择时）
    dml_py = os.path.join(install_path, "dml_env", "python.exe")
    if os.path.exists(dml_py):
        return dml_py
    return None


def _get_site_packages_for_python(python_exe, install_path):
    """根据 Python 解释器路径返回对应的 site-packages 目录。

    - dml_env Python → install_path/dml_env/Lib/site-packages
    - embed Python → install_path/python/Lib/site-packages
    - 系统 Python → install_path/Lib/site-packages（--target 安装位置）
    """
    if not python_exe or not install_path:
        return None
    py_norm = os.path.normpath(python_exe).lower()
    inst_norm = os.path.normpath(install_path).lower()

    # dml_env Python
    dml_dir = os.path.join(inst_norm, "dml_env")
    if py_norm.startswith(dml_dir):
        sp = os.path.join(install_path, "dml_env", "Lib", "site-packages")
        return sp if os.path.isdir(sp) else None

    # embed Python
    py_dir = os.path.join(inst_norm, "python")
    if py_norm.startswith(py_dir):
        sp = os.path.join(install_path, "python", "Lib", "site-packages")
        if os.path.isdir(sp):
            return sp
        # embed Python 可能直接用 install_path/Lib/site-packages
        sp2 = os.path.join(install_path, "Lib", "site-packages")
        return sp2 if os.path.isdir(sp2) else None

    # 系统 Python（--target 安装到 install_path/Lib/site-packages）
    sp = os.path.join(install_path, "Lib", "site-packages")
    return sp if os.path.isdir(sp) else None


def _detect_install_state(install_path):
    """检测安装目录的实际安装状态（不依赖配置文件，检查磁盘真实情况）。

    返回 {"models": [...], "archs": [...], "purpose": "train"/"use",
           "torchvision_ok": bool, "torch_ok": bool, "pyqt5_ok": bool}
    """
    result = {"models": [], "archs": [], "purpose": "train",
              "torchvision_ok": False, "torch_ok": False, "pyqt5_ok": False}

    # 读取 purpose
    comp_file = os.path.join(install_path, _COMPONENTS_FILE)
    if os.path.exists(comp_file):
        try:
            with open(comp_file, encoding="utf-8-sig") as f:
                data = json.load(f) or {}
                result["purpose"] = data.get("purpose", "train")
        except Exception:
            pass

    # 查找 Python 解释器
    python_exe = _find_installed_python(install_path)

    # 获取正确的 site-packages 目录（区分 dml_env/embed/系统 Python）
    site_packages = _get_site_packages_for_python(python_exe, install_path)

    # 构建子进程环境：PYTHONPATH + DLL search path（torch/lib）
    # 系统 Python 3.13 加载 torch C 扩展时需要 DLL search path
    def _make_detect_env():
        env = os.environ.copy()
        if site_packages:
            env["PYTHONPATH"] = site_packages
            # 将 torch/lib 加入 PATH，使系统 Python 能找到 CUDA DLL
            torch_lib = os.path.join(site_packages, "torch", "lib")
            if os.path.isdir(torch_lib):
                env["PATH"] = torch_lib + os.pathsep + env.get("PATH", "")
        return env

    # 检测 torchvision 和 torch 是否可用
    if python_exe and os.path.exists(python_exe):
        try:
            r = subprocess.run(
                [python_exe, "-c",
                 "import importlib.util; "
                 "tv = importlib.util.find_spec('torchvision') is not None; "
                 "tc = importlib.util.find_spec('torch') is not None; "
                 "pq = importlib.util.find_spec('PyQt5') is not None; "
                 "print(f'{tv} {tc} {pq}')"],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW, env=_make_detect_env())
            if r.returncode == 0:
                parts = r.stdout.strip().split()
                if len(parts) >= 2:
                    result["torchvision_ok"] = parts[0] == "True"
                    result["torch_ok"] = parts[1] == "True"
                if len(parts) >= 3:
                    result["pyqt5_ok"] = parts[2] == "True"
        except Exception:
            pass

    # 检测已安装的模型（检查 .pth 文件存在且大小达标，排除残缺文件）
    models_dir = os.path.join(install_path, "models")
    for key, name, *_ in _MODEL_ARCHS:
        pth_path = os.path.join(models_dir, "structures", f"{key}.pth")
        if _is_pth_complete(pth_path, key):
            result["models"].append(key)

    # 检测已安装的架构（cuda/cpu/directml）
    dml_env = os.path.join(install_path, "dml_env")
    if os.path.isdir(dml_env):
        result["archs"].append("directml")

    if python_exe and os.path.exists(python_exe):
        try:
            r = subprocess.run(
                [python_exe, "-c",
                 "import torch; print(torch.version.cuda or 'cpu')"],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW, env=_make_detect_env())
            if r.returncode == 0:
                cuda_ver = r.stdout.strip()
                if cuda_ver and cuda_ver != "cpu" and cuda_ver != "None":
                    result["archs"].append("cuda")
                else:
                    result["archs"].append("cpu")
        except Exception:
            pass

    return result


def _pip_uninstall_arch_packages(removed_archs, python_exe, install_dir,
                                  on_progress, cancel_check, start_pct=0, end_pct=20):
    """卸载已取消选择的架构对应的 pip 包。"""
    _is_system_python = True
    if install_dir:
        install_dir_norm = os.path.normpath(install_dir).lower()
        py_norm = os.path.normpath(python_exe).lower()
        if py_norm.startswith(os.path.join(install_dir_norm, "python")):
            _is_system_python = False
        elif py_norm.startswith(os.path.join(install_dir_norm, "dml_env")):
            _is_system_python = False

    _target_dir = None
    if _is_system_python and install_dir:
        _target_dir = os.path.join(install_dir, "Lib", "site-packages")

    # 获取 Python 版本
    py_version = "3.11.0"
    try:
        ver_r = subprocess.run(
            [python_exe, "-c", _PY_VER_SCRIPT],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if ver_r.returncode == 0:
            lines = ver_r.stdout.strip().splitlines()
            if len(lines) >= 2:
                py_version = lines[1].strip()
    except Exception:
        pass

    # 收集要卸载的包名
    pkgs_to_uninstall = set()
    for arch in removed_archs:
        for item in get_pip_packages(arch, py_version):
            if isinstance(item, tuple):
                pkg_str = item[0]
            else:
                pkg_str = item
            pkg_name = pkg_str.split("==")[0].split()[0]
            pkgs_to_uninstall.add(pkg_name)

    if not pkgs_to_uninstall:
        on_progress(end_pct, "无需卸载的 pip 包")
        return

    total = len(pkgs_to_uninstall)
    for i, pkg_name in enumerate(sorted(pkgs_to_uninstall)):
        if cancel_check and cancel_check():
            raise InterruptedError("用户取消操作")
        pct = start_pct + int(i * (end_pct - start_pct) / total)
        on_progress(pct, f"正在卸载 {pkg_name}...")

        if _target_dir:
            # 系统 Python：pip uninstall 不支持 --target，直接删除应用目录中的包文件
            import shutil
            pkg_dir_name = pkg_name.replace("-", "_").lower()
            removed = False
            for item in os.listdir(_target_dir):
                item_lower = item.lower()
                if item_lower == pkg_dir_name or item_lower.startswith(pkg_dir_name + "-"):
                    full_path = os.path.join(_target_dir, item)
                    try:
                        if os.path.isdir(full_path):
                            shutil.rmtree(full_path, ignore_errors=True)
                        elif os.path.isfile(full_path):
                            os.remove(full_path)
                        removed = True
                    except Exception:
                        pass
            if not removed:
                on_progress(pct, f"{pkg_name} 未在应用目录中找到，跳过")
        else:
            # dml_env/embed Python：pip uninstall 正常工作
            cmd = [python_exe, "-m", "pip", "uninstall", "-y", pkg_name]
            try:
                subprocess.run(cmd, capture_output=True, timeout=120,
                              creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass

    on_progress(end_pct, f"已卸载 {total} 个 pip 包")


def run_repair(install_path, on_progress, cancel_check=None):
    """真实文件修复：检测安装目录完整性，缺失文件从安装包恢复。

    检测项（只检测必须存在于安装目录内的文件）：
    1. 程序文件（_PROGRAM_FILES）：始终检测
    2. dml_env 目录：仅当安装记录含 directml 架构时检测
    3. 模型 .pth 文件：检测所有在线模型（ViT/DeiT）的 .pth 权重

    修复：
    - 缺失的程序文件/dml_env → 从 _MEIPASS 复制
    - 缺失的模型 .pth → 提示用组件管理重新下载
    """
    meipass = _get_meipass()
    diagnoses = []
    fixed = []

    # 先读取安装配置，获取 archs 和 models（install_components.json 在安装目录根目录）
    cfg_path = os.path.join(install_path, _COMPONENTS_FILE)
    installed_archs = []
    installed_models = []
    cfg = {}  # 必须初始化，避免文件不存在时 cfg 未定义导致 NameError
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8-sig") as fh:
                cfg = json.load(fh)
            installed_archs = cfg.get("archs", [])
            installed_models = cfg.get("models", [])
        except Exception:
            diagnoses.append((_COMPONENTS_FILE, "损坏", "JSON 解析失败", "重置为默认"))
            cfg = {}

    # 1. 检测程序文件（始终必需；但 trainer/importer 在识别器模式下不检测）
    # 旧适配：json purpose 可能过时（记 use 但磁盘已有 trainer.pyw），以磁盘文件为准
    repair_purpose = cfg.get("purpose", "train")
    repair_use = (repair_purpose == "use") and not os.path.isfile(
        os.path.join(install_path, "trainer.pyw"))
    skip_if_use = {"trainer.pyw", "importer.pyw"} if repair_use else set()
    on_progress(5, "正在检测程序文件完整性...")
    for f in _PROGRAM_FILES:
        if f in skip_if_use:
            continue
        if cancel_check and cancel_check():
            raise InterruptedError("用户取消修复")
        dst = os.path.join(install_path, f)
        if not os.path.exists(dst):
            diagnoses.append((f, "丢失", f"{f} 不存在", "从安装包恢复"))

    # 2. 检测 dml_env（仅 DirectML 模式才需要）
    if "directml" in installed_archs:
        on_progress(20, "正在检测 DirectML 环境...")
        dml_dst = os.path.join(install_path, "dml_env")
        if not os.path.exists(dml_dst):
            diagnoses.append(("dml_env", "丢失", "DirectML 环境目录缺失", "从安装包恢复"))

    # 3. 检测模型 .pth（所有模型均为 online，均需 .pth）
    on_progress(40, "正在检测模型文件...")
    for m in installed_models:
        if cancel_check and cancel_check():
            raise InterruptedError("用户取消修复")
        pth_path = os.path.join(install_path, "models", "structures", f"{m}.pth")
        if not _is_pth_complete(pth_path, m):
            diagnoses.append((f"models/{m}.pth", "丢失", f"{m} 权重文件缺失或残缺", "用组件管理重新下载"))

    # 3.5 检测 Python 库（CUDA/CPU 模式主环境需要 torch；DirectML-only 主环境不装 torch，AI 走 dml_env）
    on_progress(50, "正在检测 Python 库...")
    detected = _detect_install_state(install_path)
    # 读取 archs 判断是否为 directml-only
    _repair_archs = []
    _repair_comp = os.path.join(install_path, _COMPONENTS_FILE)
    if os.path.isfile(_repair_comp):
        try:
            with open(_repair_comp, encoding="utf-8-sig") as _f:
                _repair_archs = (json.load(_f) or {}).get("archs", []) or []
        except Exception:
            pass
    _is_dml_only = ("directml" in _repair_archs and "cuda" not in _repair_archs and "cpu" not in _repair_archs)
    if not _is_dml_only:
        # CUDA/CPU 或混合模式：主环境必须有 torch
        if not detected.get("torch_ok"):
            diagnoses.append(("torch", "缺失", "PyTorch 未安装或不可用", "用组件管理重新安装库"))
        if not detected.get("torchvision_ok"):
            diagnoses.append(("torchvision", "缺失", "torchvision 未安装或不可用", "用组件管理重新安装库"))
    if not detected.get("pyqt5_ok"):
        diagnoses.append(("PyQt5", "缺失", "PyQt5 未安装或不可用", "pip 安装到 vendor"))

    # 3.6 读取 test.pyw 诊断结果（功能级检测：文件存在但功能异常）
    # 仅识别器（json use 且磁盘无 trainer.pyw）跳过训练器/导入器相关文件
    _REPAIR_SKIP_FILES = set()
    if repair_use:
        _REPAIR_SKIP_FILES = {
            "trainer.pyw", "importer.pyw",
            "utils/mbtl_reader.py", "utils/mbtl_writer.py", "utils/mbtl_utils.py",
            "utils/screenshot_dataset.py", "scripts/dml_worker.py",
        }
    on_progress(55, "正在读取功能诊断结果...")
    test_result = os.path.join(os.environ.get("TEMP", ""), "banner_test_result.json")
    if os.path.exists(test_result):
        try:
            with open(test_result, encoding="utf-8") as f:
                test_data = json.load(f)
            seen_files = set()
            for item in test_data.get("failed_items", []):
                if cancel_check and cancel_check():
                    raise InterruptedError("用户取消修复")
                for fpath in item.get("files", []):
                    if fpath in seen_files:
                        continue
                    # use 模式跳过训练器/导入器相关文件
                    if fpath in _REPAIR_SKIP_FILES:
                        continue
                    seen_files.add(fpath)
                    dst = os.path.join(install_path, fpath)
                    if os.path.exists(dst):
                        diagnoses.append((fpath, "异常",
                            f"功能检测失败: {item['name']}",
                            "从安装包替换"))
        except InterruptedError:
            raise
        except Exception:
            pass

    if not diagnoses:
        on_progress(100, "无需修复，所有组件完整")
        return [], []

    # 4. 修复
    on_progress(60, f"正在修复 {len(diagnoses)} 个问题...")
    for i, (comp, status, issue, action) in enumerate(diagnoses):
        if cancel_check and cancel_check():
            raise InterruptedError("用户取消修复")
        pct = 60 + int(i * 30 / max(len(diagnoses), 1))
        on_progress(pct, f"正在修复 {comp}...")
        # PyQt5 不在安装包里，用 pip install --target 装到 vendor（不碰系统 site-packages）
        # 注意：必须用系统/embed Python（非 dml_env），且 target 固定 install_path/Lib/site-packages
        # （与所有入口顶部的 _VENDOR_PKGS 一致），避免装到 dml_env 的 3.10 .pyd 在系统 3.13 加载失败
        if comp == "PyQt5":
            _py = _find_installed_python(install_path)
            _sp_dir = os.path.join(install_path, "Lib", "site-packages")
            os.makedirs(_sp_dir, exist_ok=True)
            if not _py:
                fixed.append((comp, "需手动处理", "未找到可用的 Python 解释器"))
                continue
            # 官方源失败时逐个国内镜像回退（不依赖单一镜像站，镜像可能随时关停/限流）
            _fixed = False
            _err = ""
            for _mn, _ma in [("官方源", [])] + PIP_MIRROR_FALLBACKS:
                _r = subprocess.run(
                    [_py, "-m", "pip", "install", "--target", _sp_dir, "PyQt5==5.15.11"]
                    + PIP_MIRROR_ARGS + _ma,
                    capture_output=True, text=True, timeout=600,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                if _r.returncode == 0:
                    _fixed = True
                    break
                _err = (_r.stderr or "")[:200]
            if _fixed:
                fixed.append((comp, "已修复", "pip 安装 PyQt5 到 vendor 完成"))
            else:
                fixed.append((comp, "需手动处理", f"pip 安装失败：{_err}"))
            continue
        # torch/torchvision：DML 模式下在 dml_env 内（随 dml_env 恢复），不单独处理
        if comp in ("torch", "torchvision") and "directml" in installed_archs:
            _dml_pkg = os.path.join(install_path, "dml_env", "Lib", "site-packages", comp)
            if os.path.isdir(_dml_pkg):
                fixed.append((comp, "已修复", "已随 dml_env 恢复"))
            else:
                fixed.append((comp, "需手动处理", action))
            continue
        src = os.path.join(meipass, comp)
        dst = os.path.join(install_path, comp)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            fixed.append((comp, "已修复", f"{action}完成"))
        elif os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            fixed.append((comp, "已修复", f"{action}完成"))
        else:
            # 模型 .pth 等无法从安装包恢复的
            fixed.append((comp, "需手动处理", action))

    on_progress(95, "正在校验修复结果...")

    # 5. 检测并修复快捷方式（桌面 + 开始菜单）
    desktop = _get_special_folder(0x00)
    start_menu = _get_special_folder(0x02)
    shortcut_dir = os.path.join(start_menu, "我的世界旗帜逆向套件")
    for lnk in [
        os.path.join(shortcut_dir, "我的世界旗帜逆向套件.lnk"),
        os.path.join(desktop, "我的世界旗帜逆向套件.lnk"),
    ]:
        if not os.path.exists(lnk):
            diagnoses.append((lnk, "缺失", "快捷方式不存在", "重新创建"))
    if any(d[1] == "缺失" and d[0].endswith(".lnk") for d in diagnoses):
        on_progress(97, "正在重建快捷方式...")
        step_create_shortcuts(install_path, lambda p, t: None)
        for d in diagnoses[:]:
            if d[1] == "缺失" and d[0].endswith(".lnk"):
                fixed.append((d[0], "已修复", "快捷方式已重建"))
                diagnoses.remove(d)

    on_progress(100, f"修复完成，共处理 {len(fixed)} 个问题")
    return diagnoses, fixed


def run_upgrade(install_path, on_progress, cancel_check=None):
    """升级：用安装包内的最新文件强制覆盖安装目录的所有程序文件。

    覆盖范围：_PROGRAM_FILES 中的所有 .pyw 文件和 utils/scripts/images/models 目录。
    不覆盖：config/（用户设置）、Lib/site-packages/（pip 库）、dml_env/（独立环境）、
            log/（日志）、模型 .pth 权重文件。
    """
    import shutil as _shutil
    meipass = _get_meipass()
    results = []

    # 读取当前安装配置
    cfg_path = os.path.join(install_path, _COMPONENTS_FILE)
    old_cfg = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8-sig") as f:
                old_cfg = json.load(f) or {}
        except Exception:
            pass

    old_version = old_cfg.get("version", "未知")
    new_version = _APP_VERSION
    purpose = old_cfg.get("purpose", "train")

    # 升级范围：按用途过滤（识别器用户不复制 trainer/importer）
    _skip = {"trainer.pyw", "importer.pyw"} if purpose == "use" else set()

    # 检测被补丁工具修改过的文件（patches/ 目录和旧版 _backup_* 目录）
    # 这些文件在升级时跳过覆盖，保留补丁版本
    patched_files = set()
    if os.path.isdir(install_path):
        # 新版：patches/<timestamp>/
        patches_dir = os.path.join(install_path, "patches")
        if os.path.isdir(patches_dir):
            for name in os.listdir(patches_dir):
                pdir = os.path.join(patches_dir, name)
                if not os.path.isdir(pdir):
                    continue
                for root, dirs, files in os.walk(pdir):
                    for f in files:
                        if f in ("patch_meta.json", "patch.zip"):
                            continue
                        rel = os.path.relpath(os.path.join(root, f), pdir)
                        patched_files.add(rel.replace("\\", "/"))
        # 旧版兼容：_backup_*
        for name in os.listdir(install_path):
            if not name.startswith("_backup_"):
                continue
            bdir = os.path.join(install_path, name)
            if not os.path.isdir(bdir):
                continue
            for root, dirs, files in os.walk(bdir):
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), bdir)
                    patched_files.add(rel.replace("\\", "/"))

    upgrade_files = [f for f in _PROGRAM_FILES if f not in _skip]

    total = len(upgrade_files)
    for i, fname in enumerate(upgrade_files):
        if cancel_check and cancel_check():
            raise InterruptedError("用户取消升级")
        pct = int(i * 90 / max(total, 1))
        # 被补丁修改过的文件 → 跳过，保留补丁
        if fname.replace("\\", "/") in patched_files:
            results.append((fname, "保留补丁", "已被补丁工具修改，跳过覆盖"))
            on_progress(pct, f"保留补丁: {fname}")
            continue
        on_progress(pct, f"正在更新 {fname}...")
        src = os.path.join(meipass, fname)
        dst = os.path.join(install_path, fname)
        try:
            if os.path.isdir(src):
                _shutil.copytree(src, dst, dirs_exist_ok=True)
                results.append((fname, "已更新", None))
            elif os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                _shutil.copy2(src, dst)
                results.append((fname, "已更新", None))
            else:
                # 安装包里没有的文件（如 patch_tool.pyw 可能已移除）→ 跳过
                results.append((fname, "跳过", "安装包中无此文件"))
        except Exception as e:
            results.append((fname, "失败", str(e)))

    # 更新 install_components.json 版本号
    on_progress(92, "正在更新版本信息...")
    old_cfg["version"] = new_version
    old_cfg["install_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(old_cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 重建快捷方式
    on_progress(95, "正在更新快捷方式...")
    try:
        step_create_shortcuts(install_path, lambda p, t: None)
    except Exception:
        pass

    on_progress(100, f"升级完成：{old_version} → {new_version}")
    return results


def _kill_processes_in(directory):
    """终止 exe 路径位于 directory 内的所有进程（纯 ctypes，无第三方依赖）。

    卸载前必须调用：训练器/Python 子进程持有日志等文件句柄时，
    rmtree 会删不掉这些文件，而锚定文件已被删 → 目录壳残留 → "假卸载"。
    返回被终止的进程 exe 路径列表。
    """
    import ctypes
    from ctypes import wintypes
    killed = []
    if not directory:
        return killed
    directory = os.path.abspath(directory).lower()
    kernel32 = ctypes.windll.kernel32

    TH32CS_SNAPPROCESS = 0x2
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_TERMINATE = 0x0001

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),  # ULONG_PTR，32/64 位通用
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),     # MAX_PATH
        ]

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return killed
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return killed
        while True:
            pid = entry.th32ProcessID
            if pid and pid != os.getpid():
                h = kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE, False, pid)
                if h:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(1024)
                        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                            exe_path = buf.value.lower()
                            # 只杀安装目录内的进程（便携 Python / dml_env / start.exe / 训练器）
                            if exe_path.startswith(directory + os.sep):
                                kernel32.TerminateProcess(h, 1)
                                killed.append(exe_path)
                    finally:
                        kernel32.CloseHandle(h)
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snap)

    # 由系统 pythonw/python 启动的套件进程（exe 不在安装目录内，但运行脚本在
    # 安装目录内）：例如快捷方式指向系统 Python 运行 start.pyw/trainer 等，
    # 它们同样持有目录内文件句柄，按 exe 路径判定杀不掉 → 卸载残留。
    # 这里按"命令行包含安装目录路径"补充击杀（PowerShell CIM 查询）。
    try:
        import subprocess as _sp
        _esc = directory.replace("'", "''")
        _ps = _sp.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" + _esc + "*' } "
             "| ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=15,
            creationflags=_sp.CREATE_NO_WINDOW)
        for _line in (_ps.stdout or "").splitlines():
            _pid_s = _line.strip()
            if not _pid_s.isdigit():
                continue
            _pid = int(_pid_s)
            if _pid and _pid != os.getpid():
                _h = kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE, False, _pid)
                if _h:
                    kernel32.TerminateProcess(_h, 1)
                    kernel32.CloseHandle(_h)
                    killed.append("pid:%d" % _pid)
    except Exception:
        pass
    return killed


def _rmtree_robust(path):
    """删除目录树：只读文件自动去属性；文件被占用时终止占用进程后重试；
    ACL 权限拒绝（winerror=5"拒绝访问"）时尝试用 icacls 重置权限后重删。

    返回 True 表示目录已完全消失，False 表示仍有文件残留。
    """
    def _del_once(p):
        def _onerror(func, fpath, exc_info):
            try:
                os.chmod(fpath, 0o777)
                func(fpath)
            except Exception:
                pass
        try:
            shutil.rmtree(p, onerror=_onerror)
        except Exception:
            pass

    _del_once(path)
    if not os.path.exists(path):
        return True
    # 有文件被占用：杀掉安装目录内的进程（训练器/Python 持有的日志句柄等），等句柄释放后重试
    for _ in range(3):
        _kill_processes_in(path)
        time.sleep(1.0)
        _del_once(path)
        if not os.path.exists(path):
            return True
    # 仍失败：大概率是 ACL 权限拒绝（卸载器非管理员运行时无法删除所有权被夺的目录），
    # 尝试用 icacls 重置继承并授予 Users 完全控制后重删（需要管理员权限）。
    try:
        import subprocess as _sp
        for _ in range(2):
            _sp.run(["icacls", path, "/reset", "/t", "/c", "/q"],
                    capture_output=True, timeout=30,
                    creationflags=_sp.CREATE_NO_WINDOW)
            _sp.run(["icacls", path, "/grant",
                     "*S-1-5-32-545:(OI)(CI)F", "/t", "/c", "/q"],
                    capture_output=True, timeout=30,
                    creationflags=_sp.CREATE_NO_WINDOW)
            _del_once(path)
            if not os.path.exists(path):
                return True
    except Exception:
        pass
    return not os.path.exists(path)


def run_uninstall(install_path, on_progress, cancel_check=None):
    """卸载：删除安装目录 + 注册表项 + 快捷方式。

    返回 None 表示完全成功；返回字符串表示部分完成（有文件被占用未删除），
    调用方应如实告知用户，不得伪装成完全成功。
    """
    import glob

    # 1) 删除快捷方式
    on_progress(10, "正在删除快捷方式...")
    try:
        # CSIDL_PROGRAMS=0x02, CSIDL_DESKTOP=0x00
        start_menu = _get_special_folder(0x02)
        desktop = _get_special_folder(0x00)
        # 同时清理新旧名称的快捷方式
        for lnk in [os.path.join(start_menu, "我的世界旗帜逆向套件"),
                    os.path.join(start_menu, "旗帜逆向套件"),
                    os.path.join(desktop, "我的世界旗帜逆向套件.lnk"),
                    os.path.join(desktop, "旗帜逆向套件.lnk")]:
            try:
                if os.path.isfile(lnk):
                    os.remove(lnk)
                elif os.path.isdir(lnk):
                    shutil.rmtree(lnk, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass

    # 2) 删除注册表项（HKCU + HKLM 双路径，兼容新旧版本写入位置）
    on_progress(30, "正在清除注册表...")
    try:
        import winreg
        # 同时清理历史版本可能写入的旧卸载项（BannerWeaveReverser*），
        # 否则控制面板卸载列表会残留"我的世界旗帜逆向套件"旧条目
        for key_path in (
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MinecraftBannerReverser",
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\BannerWeaveReverser",
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\BannerWeaveReverser_is1",
        ):
            for _hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    winreg.DeleteKey(_hive, key_path)
                except Exception:
                    pass
    except Exception:
        pass

    # 3) 删除安装目录（卸载前再次验证，防止误删；卸载残留目录也允许清理）
    on_progress(50, "正在删除安装文件...")
    valid = _is_valid_install_dir(install_path)
    leftover = (not valid) and _is_leftover_dir(install_path)
    if install_path and (valid or leftover):
        # 先终止安装目录内的进程——训练器/Python 占用日志等文件句柄时
        # rmtree 删不掉这些文件，而锚定文件已被删 → 目录壳残留 → "假卸载"
        _kill_processes_in(install_path)
        if _rmtree_robust(install_path):
            on_progress(100, "卸载完成！")
            return None
        # 仍有文件被占用/权限拒绝（如被安装目录外的程序打开、ACL 权限被夺）：
        # 如实报告，不假装成功
        on_progress(100, "卸载部分完成：存在无法删除的文件")
        return ("卸载部分完成：以下目录未能完全删除：\n"
                f"{install_path}\n\n"
                "可能原因与处理：\n"
                "1) 文件被其他程序占用（如资源管理器窗口/后台进程）：\n"
                "   请关闭相关窗口后重试，或重启电脑后手动删除该目录。\n"
                "2) 目录权限被拒绝（提示\"拒绝访问\"）：\n"
                "   请右键本安装包 → 以管理员身份运行 → 重新卸载；\n"
                "   或管理员 CMD 执行：rd /s /q \"%s\"" % install_path)
    # 目录未通过安全验证：只清理了快捷方式/注册表
    on_progress(100, "卸载完成（安装目录未通过安全验证，已跳过删除目录步骤）")
    return None


_MODE_TITLE = {
    "install": "正在安装",
    "uninstall": "正在卸载",
    "manage_components": "正在管理组件",
}


class _RealInstallThread(QThread):
    """真实安装线程：调用 run_install() 执行实际下载安装。"""
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, archs, install_path, mode="install", parent=None, models=None, purpose="train", selected_features=None):
        super().__init__(parent)
        self._archs = archs
        self._install_path = install_path
        self._mode = mode
        self._cancel = False
        self._models = models  # 安装模式：选中的模型架构 key（vit_b_16 等）
        self._purpose = purpose  # "train" 或 "use"
        self._selected_features = selected_features  # set[str]，用户勾选的库组件
        self.result_msg = None  # 部分完成警告（None=完全成功）

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            if self._mode == "install":
                self.result_msg = run_install(
                    self._archs, self._install_path,
                    lambda pct, text: self.progress.emit(pct, text),
                    lambda: self._cancel,
                    models=self._models,
                    purpose=self._purpose,
                    selected_features=self._selected_features,
                )
            elif self._mode == "manage_components":
                # 维护模式：增量安装/卸载组件（含 pip 库 + 模型文件）
                run_manage_components(
                    self._archs, self._models, self._install_path,
                    lambda pct, text: self.progress.emit(pct, text),
                    lambda: self._cancel,
                    purpose=self._purpose,
                )
            elif self._mode == "uninstall":
                self.result_msg = run_uninstall(
                    self._install_path,
                    lambda pct, text: self.progress.emit(pct, text),
                    lambda: self._cancel,
                )
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(str(e))


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
            # 【原版字节码精确值】emoji字号 = max(int(26*us), 20)
            _ef = QFont("Segoe UI Emoji"); _ef.setPointSize(max(int(26 * us), 20))
            painter.setFont(_ef)
            painter.drawText(QRect(cx - r, cy - r, r * 2, r * 2), Qt.AlignCenter, "🚩")

            painter.setPen(QColor("#333333"))
            # 【原版字节码精确值】产品名字号 = max(int(10*us), 8)，通过QFont构造器设置
            f = QFont("Segoe UI"); f.setPointSize(max(int(10 * us), 8))
            f.setBold(True)
            painter.setFont(f)
            # 【原版字节码精确值】rect = QRect(0, h-max(int(56*us),46), w, max(int(20*us),16))
            painter.drawText(QRect(0, h - max(int(56 * us), 46), w, max(int(20 * us), 16)),
                             Qt.AlignCenter, "我的世界旗帜逆向套件")
            painter.setPen(QColor("#888888"))
            # 【原版字节码精确值】副标题字号 = max(int(8*us), 7)
            fh = QFont("Segoe UI"); fh.setPointSize(max(int(8 * us), 7))
            painter.setFont(fh)
            # 【原版字节码精确值】rect = QRect(0, h-max(int(36*us),30), w, max(int(16*us),13))
            painter.drawText(QRect(0, h - max(int(36 * us), 30), w, max(int(16 * us), 13)),
                             Qt.AlignCenter, "for Windows")

        # 右侧分隔线
        painter.setPen(QColor("#d8d8d8"))
        painter.drawLine(w - 1, 0, w - 1, h)


# ===== 页面基类 =====
class _FixedScrollArea(QScrollArea):
    """原版字节码 100% 还原：__init__ 只有 super + _us，无滚动条策略、无QSS。"""
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
        self._fs_title = max(int(10 * us), 10)
        self._fs_body = max(int(8 * us), 8)
        self._fs_hint = max(int(7 * us), 7)
        # 兼容旧的 _fs_title_px / _fs_body_px / _fs_hint_px 引用
        self._fs_title_px = self._fs_title
        self._fs_body_px = self._fs_body
        self._fs_hint_px = self._fs_hint

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

    def _widget_font_body(self, *widgets):
        for w in widgets:
            f = w.font()
            f.setPointSize(self._fs_body)
            w.setFont(f)

    def _widget_font_hint(self, *widgets):
        for w in widgets:
            f = w.font()
            f.setPointSize(self._fs_hint)
            w.setFont(f)

    def sizeHint(self):
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

        # 不确定进度的滚动条（Windows 安装样式），检测完成时填满
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # marquee 模式：不确定进度，自动滚动
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(max(int(18 * us), 14))
        layout.addWidget(self.progress)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QTextEdit.WidgetWidth)
        # 只读文本可选取复制：保留默认文本光标（I-beam），不改为抓取手势
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
        self.progress.setRange(0, 0)  # 重置为 marquee 模式
        self._thread = _InitThread(self)
        self._thread.line.connect(self._on_line)
        self._thread.finished_all.connect(self._on_done)
        self._thread.start()

    def _on_line(self, text, ok):
        mark = "✓" if ok else "✗"
        color = "#2e7d32" if ok else "#c62828"
        self.text.append(f'<span style="color:{color}">{mark}</span> {text}')

    def _show_results_fallback(self, info):
        """检测结果兜底显示：当线程未逐行输出时，一次性填充所有检测结果。"""
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
        ident = state.get("identity")
        if ident == "dev":
            _emit(f"已安装状态：开发环境（作者）- 源文件目录：{state.get('dev_path', '')}", True)
        elif state.get("installed"):
            ver = state.get("version", "未知版本")
            comps = len(state.get("components", []))
            path = state.get("path", "")
            tag = {"tester": "测试版本", "user": "已安装"}.get(ident, "已安装")
            _emit(f"已安装状态：{tag}（{ver}，{comps} 个组件，路径：{path}）", True)
        elif ident == "tester":
            _emit("已安装状态：测试版本（未安装，将进行全新安装）", True)
        else:
            _emit("已安装状态：未安装（将进行全新安装）", True)

    def _on_done(self, info):
        self._info = info
        # 进度条填满，结束 marquee 滚动
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        # 如果文本区域为空（线程未逐行输出），填充检测结果
        if not self.text.toPlainText().strip():
            self._show_results_fallback(info)
        state = info.get("install_state", {})
        ident = state.get("identity")
        _dbg(f"_on_done: identity={ident}, dev_path={state.get('dev_path')}, "
             f"installed={state.get('installed')}")
        if ident == "dev":
            # 作者环境：询问是否进入演示模式（启动 demo_installer.pyw）
            dev_path = state.get("dev_path") or ""
            if not dev_path:
                # 防御：dev_path 为空时（_detect_dev_env 未找到开发根）跳过弹窗
                self.status.setText("检测到开发环境标记，但未找到开发目录，点击「下一步」继续。")
            else:
                demo_path = os.path.join(dev_path, "installer", "demo_installer.pyw")
                if os.path.isfile(demo_path):
                    # 4:3 固定比例确认框（半尺寸，浅色统一；是=演示模式 / 否=正式安装）
                    if _show_43_dialog(
                            self, "检测到开发环境",
                            f"检测到开发环境：{dev_path}\n\n"
                            f"「是」= 演示模式（模拟安装，不下载文件，不弹 CMD）\n"
                            f"「否」= 正式安装（真实下载 + pip 安装 + 弹出 CMD 窗口）",
                            "info", buttons=("否", "是"), half=True):
                        ok = _launch_demo_installer(dev_path)
                        if ok:
                            QApplication.instance().quit()
                            return
                        else:
                            QMessageBox.warning(
                                self, "启动失败",
                                "演示模式启动失败（未找到 Python 解释器）。\n将进入正式安装向导。")
                self.status.setText("检测到开发环境（作者），点击「下一步」继续。")
        elif state.get("installed"):
            self.status.setText("检测到已安装，点击「下一步」进入维护模式。")
        elif ident == "tester":
            self.status.setText("检测到测试版本（未安装），点击「下一步」开始安装。")
        else:
            self.status.setText("初始化完成，点击「下一步」进入欢迎界面。")

    def set_blocked(self, msg):
        """环境不支持时在文本区域和状态栏显示拦截信息（不弹窗）。"""
        # 拦截时停止进度条滚动
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
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
        # 原版（桌面反编译 real_installer.pyw L2690）：分标题用 _fs_hint(7) 加粗
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

        btn_maint = QPushButton("已安装？修改 / 修复 / 卸载")
        btn_maint.setFlat(True)
        btn_maint.setCursor(Qt.PointingHandCursor)
        btn_maint.setStyleSheet(
            "QPushButton { color: #0078d4; text-align: left; border: none; }"
            "QPushButton:hover { text-decoration: underline; }")
        btn_maint.clicked.connect(self.maintenance_clicked)
        layout.addWidget(btn_maint)


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
        ident = state.get("identity")
        if ident == "dev":
            lines.append(f"安装状态：开发环境（作者）→ 将进行全新安装")
        elif state.get("installed"):
            tag = "测试版本" if ident == "tester" else "已安装"
            # 显示实际安装版本（内部 json/注册表记子版本号，界面补全主版本格式），
            # 不使用 _UI_VERSION——那是安装包自身版本，混淆会误导用户
            _ver_raw = state.get("version")
            _v = ("v0.5 beta1 (%s)" % _ver_raw) if _ver_raw else ""
            lines.append(f"安装状态：{tag} {_v} → 将进入维护模式")
        elif ident == "tester":
            lines.append("安装状态：测试版本（未安装）→ 将进行全新安装")
        else:
            lines.append("安装状态：未安装 → 将进行全新安装")
        self._hw_info.setText("\n".join(lines))


# ===== 使用声明文本 =====
_LICENSE_TEXT = """\
我的世界旗帜逆向套件 使用声明
最后更新：2026年8月4日

点击「我接受此声明」即表示您已阅读并同意以下全部条款。如需了解代码内容，可联系作者。

一、软件概述
本工具基于 ViT/DeiT 技术实现 Minecraft 旗帜图案逆向识别，含旗帜识别器与训练器两大模块。由 路过的小朋友（GitHub: IDclc001）独立开发。当前 Beta1 为闭源测试版本，自 Beta2 起依据 GPL v3 许可证开源。

二、系统要求
1. 操作系统：Windows 10（1909+）或 Windows 11，更低版本无法正常训练。
2. 运行内存：建议 16GB 及以上，低于 6GB 可能内存溢出、闪退。
3. 磁盘空间：根据所选架构约 3~8 GB（含 PyTorch 依赖与模型权重，CUDA 模式约 8GB，DirectML/CPU 约 3GB）。

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
发布日期：2026年8月4日
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
        f.setPointSize(self._fs_body)
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
        self.rb_accept.setCursor(Qt.PointingHandCursor)
        self.rb_decline = QRadioButton("我不接受此声明(&D)")
        self.rb_decline.setCursor(Qt.PointingHandCursor)
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
        self.rb_use.setCursor(Qt.PointingHandCursor)
        self.rb_train = QRadioButton("我要训练自己的逆向模型")
        self.rb_train.setCursor(Qt.PointingHandCursor)
        self.rb_use.setChecked(True)
        self._group.addButton(self.rb_use, 0)
        self._group.addButton(self.rb_train, 1)
        for rb in (self.rb_use, self.rb_train):
            f = rb.font()
            # 选择用途选项放大（用户偏好：比原版 body(8) 大一级，便于阅读）
            f.setPointSize(max(int(9 * us), 9))
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
            # 与选项放大配套：描述由 hint(7) 升为 body(8)
            f.setPointSize(self._fs_body_px)
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
        # NVIDIA 独显 → CUDA（也可选 DirectML），CUDA 需满足训练要求
        has_nv_discrete = bool(discrete and discrete.get("vendor") == "nvidia" and gpu_ok)
        # DirectML 可用性：基于 GPU 是否支持 DirectML 运行时（仅排除黑名单中过旧型号）
        # 不要求满足训练性能要求（内存/白名单），核显不在黑名单中即可选
        has_directml = (_gpu_supports_dml(discrete) or _gpu_supports_dml(integrated))

        is_train = purpose == "train"

        # 判断是否选择了大模型（需更大显存，作提示用）
        _LARGE_ARCHS = {"vit_h_14", "vit_l_16"}
        has_large_arch = bool(set(selected_archs) & _LARGE_ARCHS)

        # DirectML 不可用时的具体原因（仅当 has_directml 为 False 时显示）
        if not has_directml:
            if not discrete and not integrated:
                _dml_reason = "未检测到 GPU"
            else:
                _gpu_name = ""
                if discrete and not _gpu_supports_dml(discrete):
                    _gpu_name = discrete.get("name", "未知")
                elif integrated and not _gpu_supports_dml(integrated):
                    _gpu_name = integrated.get("name", "未知")
                _dml_reason = (f"GPU 型号过旧（{_gpu_name}），不支持 DirectML"
                               if _gpu_name else "未检测到支持 DirectML 的 GPU")
        else:
            _dml_reason = ""

        # psutil：无论什么模式都必装（识别器/训练器都需要硬件检测）
        # thermal（温度监控库）：仅 train 模式必装且锁定；use 模式识别器完全不需要（不做长时间训练，GPU 不会满载升温）→ 直接禁用+取消勾选，不给用户选的机会
        # (key, 名称, 描述, 默认勾选, 锁定, 可用, 不可用原因)
        features = [
            ("torch",     "torch + torchvision",   "深度学习核心框架（必装）",   True, True, True, ""),
            ("pyqt5",     "PyQt5",                 "GUI 图形界面框架（必装）",  True, True, True, ""),
            ("numpy_cv2", "numpy + opencv-python", "数值计算与图像处理（必装）",True, True, True, ""),
            ("pillow",    "Pillow (PIL)",          "图像 IO 读写库（必装）",   True, True, True, ""),
            ("matplotlib", "matplotlib",           "训练 Loss 曲线图表绘制",
             is_train, False, is_train, "仅训练模型时需要" if not is_train else ""),
            ("psutil",    "psutil",                "硬件检测与监控（必装）",   True, True, True, ""),
            ("thermal",  "pynvml",                ("GPU 温度监控库（必装，按架构自动切换）" if is_train
                                                   else "GPU 温度监控库"),
             is_train, True, is_train, "仅训练模型时需要（识别器推理无长时间GPU满载，无需温度保护）" if not is_train else ""),
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
                "images/ — 图标与横幅资源",
            ]

        scroll = _FixedScrollArea(us)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, max(int(8 * us), 6), 0)
        rows.setSpacing(max(int(4 * us), 3))

        # ===== 架构选择（CUDA / DirectML / 纯CPU），多选至少 1 个最多 3 个 =====
        arch_box = QGroupBox("架构选择（可多选，至少选 1 个）")
        arch_box.setStyleSheet(
            "QGroupBox{border:1px solid #ccc; border-radius:6px; margin-top:8px; padding-top:16px;}"
            "QGroupBox::title{subcontrol-origin:margin; left:10px; padding:0 4px;}")
        # 原版（桌面反编译 L2915）：GroupBox 标题不设字体，继承默认
        arch_inner = QVBoxLayout(arch_box)
        arch_inner.setSpacing(max(int(6 * us), 4))
        arch_inner.setContentsMargins(12, 8, 12, 8)

        arch_row = QHBoxLayout()
        arch_row.setSpacing(max(int(12 * us), 8))
        # 多选：QRadioButton → QCheckBox（不再互斥，至少选1个最多3个）
        self.rb_cuda = QCheckBox("CUDA")
        self.rb_cuda.setCursor(Qt.PointingHandCursor)
        self.rb_directml = QCheckBox("DirectML（实验性）")
        self.rb_directml.setCursor(Qt.PointingHandCursor)
        self.rb_cpu = QCheckBox("纯 CPU")
        self.rb_cpu.setCursor(Qt.PointingHandCursor)
        # 原版（桌面反编译 L2926）：架构 checkbox 用 _fs_body(8)
        self._widget_font_body(self.rb_cuda, self.rb_directml, self.rb_cpu)
        for rb in (self.rb_cuda, self.rb_directml, self.rb_cpu):
            arch_row.addWidget(rb)
        arch_row.addStretch()
        arch_inner.addLayout(arch_row)

        # 架构选择变更时，联动 DirectML 厂商下拉与控温库
        self.rb_cuda.toggled.connect(self._on_arch_changed)
        self.rb_directml.toggled.connect(self._on_arch_changed)
        self.rb_cpu.toggled.connect(self._on_arch_changed)

        # DirectML 厂商下拉（仅展示当前设备检测到的 GPU 厂商）
        self._dml_container = QWidget()
        dml_row = QHBoxLayout(self._dml_container)
        dml_row.setContentsMargins(0, 0, 0, 0)
        dml_row.setSpacing(max(int(8 * us), 4))
        dml_lbl = QLabel("DirectML 设备:")
        # 原版（桌面反编译 L2940）：DirectML 标签用 _fs_body(8)
        self._widget_font_body(dml_lbl)
        self.cb_dml_vendor = QComboBox()
        self.cb_dml_vendor.setCursor(Qt.PointingHandCursor)
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
        # 若未检测到任何 DirectML 设备（CPU-only / 不支持），保留全部3个选项供用户选择
        if not self._dml_vendor_keys:
            for vkey, vlabel in _VENDOR_LABELS:
                self.cb_dml_vendor.addItem(vlabel)
                self._dml_vendor_keys.append(vkey)
        self.cb_dml_vendor.setMinimumWidth(int(180 * us))
        dml_row.addWidget(dml_lbl)
        dml_row.addWidget(self.cb_dml_vendor, 1)
        dml_row.addStretch()
        arch_inner.addWidget(self._dml_container)

        arch_hint = QLabel(
            "无论选择何种使用目的，均需选择计算架构。\n"
            "  · CUDA：NVIDIA 独显专用，速度最快（推荐）；\n"
            "  · DirectML：NVIDIA / AMD / Intel 通用 GPU 加速；\n"
            "  · 纯 CPU：无 GPU 加速，速度极慢。\n"
            "NVIDIA 独显建议优先 CUDA。")
        arch_hint.setWordWrap(True)
        arch_hint.setStyleSheet("color: #666;")
        # 原版（桌面反编译 L2966）：架构说明用 _fs_hint(7)
        self._widget_font_hint(arch_hint)
        arch_inner.addWidget(arch_hint)
        rows.addWidget(arch_box)

        # 根据硬件自动选择默认架构 + DirectML 厂商
        self._apply_default_arch(discrete, integrated, gpu_ok)
        # DirectML 厂商切换时联动控温库（架构变更由 _on_arch_changed 统一处理）
        self.cb_dml_vendor.currentIndexChanged.connect(self._update_thermal_lib)

        for key, name, desc_text, default, locked, enabled, reason in features:
            if not enabled:
                continue
            cb = QCheckBox(name)
            cb.setCursor(Qt.PointingHandCursor)
            cb.setChecked(default)
            if locked:
                cb.setEnabled(False)
            # 原版（桌面反编译 L2973）：组件名不设字体，继承默认
            desc_lbl = QLabel(desc_text)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("color: #666;")
            # 原版（桌面反编译 L2981）：组件描述用 _fs_hint(7)
            self._widget_font_hint(desc_lbl)

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(cb)
            row.addWidget(desc_lbl, 1)
            wrap = QWidget()
            wrap.setLayout(row)
            rows.addWidget(wrap)
            self._feature_cbs[key] = cb
            if key == "thermal":
                self._thermal_cb = cb
                self._thermal_desc_lbl = desc_lbl

        # thermal 引用就绪后，立即按当前架构初始化库名
        self._update_thermal_lib()

        # 程序文件清单
        sep = QLabel("程序文件")
        sep.setStyleSheet(f"color: #888; font-weight: bold; padding-top: {max(int(8 * us), 6)}px;")
        # 原版（桌面反编译 L2998）：分标题用 _fs_body(8) 随 us 缩放
        self._widget_font_body(sep)
        rows.addWidget(sep)
        for fn in file_list:
            fl = QLabel("  " + fn)
            fl.setStyleSheet("color: #666;")
            # 原版（桌面反编译 L3005）：文件列表项用 _fs_hint(7) 随 us 缩放
            self._widget_font_hint(fl)
            rows.addWidget(fl)

        rows.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        if purpose == "use":
            layout.addWidget(self._hint("仅使用模型时，训练相关组件已自动禁用。"))

    def _apply_default_arch(self, discrete, integrated, gpu_ok):
        """根据硬件自动选择默认架构与 DirectML 厂商。

        优先级：NVIDIA 独显 → CUDA；其余支持 DirectML 的 GPU → DirectML；无 GPU → 纯CPU。
        DirectML 厂商下拉按检测到的显卡厂商自动推荐：
          NVIDIA → N 卡；AMD → A 卡；Intel → I 卡。
        """
        has_nv_discrete = bool(discrete and discrete.get("vendor") == "nvidia" and gpu_ok)
        # DirectML 可用性：基于 GPU 是否支持 DirectML 运行时（仅排除黑名单中过旧型号）
        has_directml = (_gpu_supports_dml(discrete) or _gpu_supports_dml(integrated))

        # ===== 按硬件情况置灰不可用的架构（可见但不可选） =====
        # CUDA：仅 NVIDIA 独显（且驱动满足最低版本 gpu_ok=True）时可选
        if not has_nv_discrete:
            self.rb_cuda.setEnabled(False)
            _disable_tooltip = ""
            if not discrete:
                _disable_tooltip = "未检测到 NVIDIA 独显，CUDA 不可用"
            elif discrete.get("vendor") != "nvidia":
                _disable_tooltip = f"当前独显为 {discrete.get('name','未知')}，CUDA 仅支持 NVIDIA"
            else:
                _disable_tooltip = ("NVIDIA 驱动版本过低，需升级到 570.00+ 才能使用 CUDA，"
                                    "建议使用 DirectML 或纯 CPU 模式")
            self.rb_cuda.setToolTip(_disable_tooltip)
            self.rb_cuda.setChecked(False)
        # DirectML：GPU 不在黑名单时才可勾选
        if not has_directml:
            self.rb_directml.setEnabled(False)
            if not discrete and not integrated:
                _dml_rsn = "未检测到 GPU"
            else:
                _gn = ""
                if discrete and not _gpu_supports_dml(discrete):
                    _gn = discrete.get("name", "未知")
                elif integrated and not _gpu_supports_dml(integrated):
                    _gn = integrated.get("name", "未知")
                _dml_rsn = (f"GPU 型号过旧（{_gn}），不支持 DirectML"
                            if _gn else "未检测到支持 DirectML 的 GPU")
            self.rb_directml.setToolTip(_dml_rsn)
            self.rb_directml.setChecked(False)

        # 默认勾选优先级：NVIDIA 独显 → CUDA；其余有 GPU → DirectML；无 GPU → 纯CPU
        # （用户仍可手动勾选 DirectML 作为 N 卡的备选后端）
        if has_nv_discrete and self.rb_cuda.isEnabled():
            self.rb_cuda.setChecked(True)
        elif has_directml and self.rb_directml.isEnabled():
            self.rb_directml.setChecked(True)
        else:
            self.rb_cpu.setChecked(True)

        # DirectML 厂商自动推荐（按当前下拉可选项的索引）
        def _vendor_idx(vendor):
            return self._dml_vendor_keys.index(vendor) if vendor in self._dml_vendor_keys else 0

        if discrete and discrete.get("vendor") == "amd":
            self.cb_dml_vendor.setCurrentIndex(_vendor_idx("amd"))
        elif integrated and integrated.get("vendor") == "amd":
            self.cb_dml_vendor.setCurrentIndex(_vendor_idx("amd"))
        elif integrated and integrated.get("vendor") == "intel":
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

    def get_selected_features(self):
        """返回用户勾选的库组件 key 集合。
        必装项（锁定勾选）始终包含；可选项只在用户勾选时包含。
        """
        result = set()
        for key, cb in self._feature_cbs.items():
            if cb.isChecked():
                result.add(key)
        return result

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
        if not getattr(self, "_thermal_cb", None) or not getattr(self, "_thermal_desc_lbl", None):
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
#   ViT/DeiT 系列权重均来自 torchvision 官方下载，预训练权重加速收敛
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
    def __init__(self, us, hw_info=None, maintenance=False, parent=None, install_path=None):
        super().__init__(us, parent)
        self._hw_info = hw_info or {}
        self._arch_checks = {}
        self._maintenance = maintenance
        self._install_path = install_path or ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(8 * us), 6))

        # 检测是否缺少训练器（仅识别器模式）
        trainer_missing = (maintenance and self._install_path
                           and not os.path.exists(os.path.join(self._install_path, "trainer.pyw")))

        if maintenance:
            layout.addWidget(self._title("管理模型与训练组件"))
            if trainer_missing:
                layout.addWidget(self._desc(
                    "当前安装为「仅识别器」模式。如需训练自定义旗帜模型，请先勾选下方「安装训练器」。"
                    "训练器需要预训练权重文件，勾选模型架构后会自动下载。"))
            else:
                layout.addWidget(self._desc(
                    "勾选要安装/保留的模型架构与训练器，取消勾选已安装的组件并点击「应用」即卸载。"
                    "ViT/DeiT 系列均从 torchvision 在线下载预训练权重。"))
        else:
            layout.addWidget(self._title("选择模型架构文件"))
            layout.addWidget(self._desc(
                "选择需要下载/安装的模型架构。ViT/DeiT 系列均从 torchvision 在线下载预训练权重。"))

        # 滚动区域
        scroll = _FixedScrollArea(us)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, max(int(8 * us), 6), 0)
        scroll_layout.setSpacing(max(int(4 * us), 3))

        gpu = self._hw_info.get("gpu", {})
        discrete = gpu.get("discrete")
        vram = 0
        if discrete:
            vram = discrete.get("vram_gb", 0)

        # 训练器选择卡片（维护模式恒显示：已装=可取消勾选卸载，未装=可勾选安装）
        if maintenance:
            scroll_layout.addWidget(self._make_trainer_card(installed=not trainer_missing))

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
        btn_select_all.setCursor(Qt.PointingHandCursor)
        btn_select_all.clicked.connect(lambda: self._toggle_all(True))
        btn_deselect_all = QPushButton("全不选")
        btn_deselect_all.setCursor(Qt.PointingHandCursor)
        btn_deselect_all.clicked.connect(lambda: self._toggle_all(False))
        btn_row.addWidget(btn_select_all)
        btn_row.addWidget(btn_deselect_all)
        btn_row.addStretch()
        lbl_total = QLabel()
        lbl_total.setStyleSheet(f"color: #666;")
        f = lbl_total.font()
        f.setPointSize(self._fs_hint)
        lbl_total.setFont(f)
        self._lbl_total = lbl_total
        btn_row.addWidget(lbl_total)
        layout.addLayout(btn_row)

        # 默认选择
        self._select_defaults(vram)

    def _make_trainer_card(self, installed=False):
        """创建训练器选择卡片（维护模式恒显示）。

        installed=True ：训练器已装 → 显示「选择训练器」，取消勾选并点「应用」即卸载该模块；
        installed=False：训练器未装 → 显示「安装训练器」，勾选后随模型一起安装。
        """
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ border: 2px solid #0078d4; border-radius: 6px; "
            f"background: #f0f7ff; padding: {max(int(4 * self._us), 3)}px; }}")
        cl = QVBoxLayout(card)
        m = max(int(6 * self._us), 4)
        cl.setContentsMargins(m, m, m, m)
        cl.setSpacing(max(int(3 * self._us), 2))

        if installed:
            cb_text = "选择旗帜训练器 (trainer.pyw + importer.pyw)"
            desc_text = ("训练器用于训练自定义旗帜模型，识别器仅用于识别。\n"
                         "取消勾选并点击「应用」将卸载训练器与导入器模块。")
        else:
            cb_text = "安装旗帜训练器 (trainer.pyw + importer.pyw)"
            desc_text = ("训练器用于训练自定义旗帜模型，识别器仅用于识别。\n"
                         "安装训练器后，请在下方选择模型架构并下载预训练权重。")
        cb = QCheckBox(cb_text)
        cb.setCursor(Qt.PointingHandCursor)
        f = cb.font()
        f.setPointSize(self._fs_body)
        f.setBold(True)
        cb.setFont(f)
        cb.setChecked(installed)  # 仅已装时默认勾选（仅识别器用户不勾，避免误装训练器）
        self._arch_checks["_trainer"] = cb
        cb.stateChanged.connect(lambda _: self._update_total())
        cl.addWidget(cb)

        desc_lbl = QLabel(desc_text)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #555;")
        cl.addWidget(desc_lbl)
        return card

    def _make_arch_card(self, key, name, params, vram_gb, pth_dl_gb,
                        dl_method, desc, depends, vram):
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
        cb.setCursor(Qt.PointingHandCursor)
        f = cb.font()
        f.setPointSize(self._fs_body)
        f.setBold(True)
        cb.setFont(f)
        cb.stateChanged.connect(lambda _: self._update_total())
        self._arch_checks[key] = cb
        row1.addWidget(cb)

        # 显存适配标记（基于训练显存需求，非下载大小）
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
            ff.setPointSize(self._fs_hint)
            fit_lbl.setFont(ff)
            row1.addWidget(fit_lbl)

        row1.addStretch()

        dl_lbl = QLabel(_DOWNLOAD_LABELS.get(dl_method, dl_method))
        dl_lbl.setStyleSheet("color: #1a73e8;")
        fd = dl_lbl.font()
        fd.setPointSize(self._fs_hint)
        dl_lbl.setFont(fd)
        row1.addWidget(dl_lbl)

        # 下载大小显示：用实际 .pth 文件大小，非训练显存
        if dl_method != "arch" and pth_dl_gb > 0:
            size_lbl = QLabel(f"下载 ~{pth_dl_gb:.1f} GB")
            size_lbl.setStyleSheet("color: #666;")
            fs = size_lbl.font()
            fs.setPointSize(self._fs_hint)
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
        fi.setPointSize(self._fs_hint)
        info.setFont(fi)
        info.setWordWrap(True)
        row2.addWidget(info, 1)
        cl.addLayout(row2)

        # 依赖提示
        if depends:
            dep_lbl = QLabel(f"  ⚠ 依赖 {_dep_name(depends)}，将自动一并下载")
            dep_lbl.setStyleSheet("color: #e67e22;")
            fd2 = dep_lbl.font()
            fd2.setPointSize(self._fs_hint)
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
            # 维护模式：全选（假设已安装，取消勾选=卸载）；跳过 _trainer——
            # 其默认状态由 _make_trainer_card(installed=...) 决定，未装训练器时保持未勾选
            for k, cb in self._arch_checks.items():
                if k == "_trainer":
                    continue
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
    """选择安装盘符与路径，并检测该盘可用空间。

    枚举真实盘符并实时检测可用空间，切换盘符时有短暂加载延迟。
    """

    space_checked = pyqtSignal()  # 空间检测完成（用于刷新下一步按钮）

    def __init__(self, us, parent=None):
        super().__init__(us, parent)
        self._hw_info = None
        self._install_state = None
        self._locations = []
        self._is_real = False
        self._load_timer = None
        self._required_gb = 10.0  # 默认值，populate 时按勾选架构动态更新

        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(8 * us), 6))

        layout.addWidget(self._title("选择安装位置"))
        layout.addWidget(self._desc("选择软件要安装到的位置（如桌面），程序将在该位置下创建软件文件夹。"))

        # 位置选择（常用位置 + 盘符 + 自定义）
        drive_row = QHBoxLayout()
        drive_row.setSpacing(max(int(8 * us), 4))
        lbl_drive = QLabel("安装位置:")
        # 原版（桌面反编译 L3324）：标签不设字体，继承默认
        self.cb_drive = QComboBox()
        self.cb_drive.setCursor(Qt.PointingHandCursor)
        self.cb_drive.setMinimumWidth(int(240 * us))
        self.cb_drive.currentIndexChanged.connect(self._on_drive_changed)
        drive_row.addWidget(lbl_drive)
        drive_row.addWidget(self.cb_drive, 1)
        # 浏览其他位置（选择父目录，最终路径 = 父目录 + 软件文件夹名）
        btn_browse = QPushButton("浏览其他位置...")
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.clicked.connect(self._on_browse)
        drive_row.addWidget(btn_browse)
        layout.addLayout(drive_row)

        # 文件夹名输入
        path_row = QHBoxLayout()
        path_row.setSpacing(max(int(8 * us), 4))
        lbl_path = QLabel("软件文件夹名:")
        # 原版（桌面反编译 L3338）：标签不设字体，继承默认
        self.txt_path = QLineEdit("我的世界旗帜逆向套件")
        self.txt_path.setMinimumWidth(int(260 * us))
        self.txt_path.textChanged.connect(self._update_full_path)
        path_row.addWidget(lbl_path)
        path_row.addWidget(self.txt_path, 1)
        layout.addLayout(path_row)

        # 完整路径预览
        self.lbl_full = QLabel("")
        self.lbl_full.setWordWrap(True)
        self.lbl_full.setStyleSheet("color: #888; padding: 2px 2px;")
        f = self.lbl_full.font(); f.setPointSize(self._fs_hint); self.lbl_full.setFont(f)
        layout.addWidget(self.lbl_full)

        # 空间信息
        self.lbl_space = QLabel("")
        self.lbl_space.setWordWrap(True)
        self.lbl_space.setStyleSheet("color: #444; padding: 4px 2px;")
        f = self.lbl_space.font(); f.setPointSize(self._fs_body); self.lbl_space.setFont(f)
        layout.addWidget(self.lbl_space)

        layout.addStretch()
        self._hint_label = self._hint(
            f"安装所需至少 {self._required_gb:.1f} GB 可用空间（已安装的组件会自动跳过）。"
            "请选择有足够空间的盘符。")
        layout.addWidget(self._hint_label)

    def populate(self, hw_info, install_state=None, archs=None, models=None, purpose="train"):
        """进入页面时填充位置列表（常用位置 + 各盘根目录）。

        Args:
            archs: 用户在库选择页勾选的架构列表，用于动态计算所需磁盘空间。
            models: 用户在模型架构页勾选的模型 key（ViT 在线权重计入所需空间）。
            purpose: "train" 或 "use"，影响空间估算（跳过训练专用包）。
        """
        self._hw_info = hw_info or {}
        self._install_state = install_state or {}
        self._purpose = purpose
        # 根据勾选架构动态计算所需空间（传入 hw_info 检测 Python 是否已装）
        self._required_gb = _compute_required_gb(archs, models, hw_info=self._hw_info, purpose=purpose)
        self._hint_label.setText(
            f"安装所需至少 {self._required_gb:.1f} GB 可用空间（已安装的组件会自动跳过）。"
            "请选择有足够空间的位置。")
        self._is_real = True
        self._locations = self._build_locations()

        self.cb_drive.blockSignals(True)
        self.cb_drive.clear()
        for loc in self._locations:
            self.cb_drive.addItem(loc["display"])
        self.cb_drive.blockSignals(False)

        # 已安装则预填：解析出父位置与文件夹名并选中对应项
        if self._install_state.get("installed"):
            inst_path = self._install_state.get("path", "") or ""
            if inst_path:
                parent_dir = os.path.dirname(inst_path.rstrip("\\/"))
                folder_name = os.path.basename(inst_path.rstrip("\\/"))
                if folder_name:
                    self.txt_path.setText(folder_name)
                for i, loc in enumerate(self._locations):
                    if os.path.normcase(loc["path"]) == os.path.normcase(parent_dir):
                        self.cb_drive.setCurrentIndex(i)
                        break
                else:
                    # 父位置不在常用列表 → 追加为自定义项
                    self._add_custom_location(parent_dir)
        self._on_drive_changed(self.cb_drive.currentIndex())
        self._update_full_path()

    def _build_locations(self):
        """构建常用位置列表：默认位置 / 桌面 / 文档 / 各盘根目录。"""
        locations = []
        local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        documents = os.path.join(os.path.expanduser("~"), "Documents")
        for name, path in (("默认位置（推荐）", local_appdata),
                           ("桌面", desktop),
                           ("文档", documents)):
            if os.path.isdir(path):
                locations.append({
                    "name": name, "path": path,
                    "letter": path[:1].upper(),
                    "display": f"{name}  —  {path}",
                })
        # 各盘根目录
        import string
        for ch in string.ascii_uppercase:
            root = f"{ch}:\\"
            if os.path.exists(root):
                locations.append({
                    "name": f"{ch}: 盘根目录", "path": root.rstrip("\\"),
                    "letter": ch,
                    "display": f"{ch}: 盘根目录  —  {root}",
                })
        return locations

    def _add_custom_location(self, path):
        """把自定义父位置追加到下拉框并选中。"""
        if not path or not os.path.isdir(path):
            return
        for i, loc in enumerate(self._locations):
            if os.path.normcase(loc["path"]) == os.path.normcase(path):
                self.cb_drive.setCurrentIndex(i)
                return
        loc = {"name": "自定义位置", "path": path,
               "letter": path[:1].upper(),
               "display": f"自定义位置  —  {path}"}
        self._locations.append(loc)
        self.cb_drive.blockSignals(True)
        self.cb_drive.addItem(loc["display"])
        self.cb_drive.setCurrentIndex(len(self._locations) - 1)
        self.cb_drive.blockSignals(False)

    def _on_drive_changed(self, idx):
        if idx < 0 or not self._locations or idx >= len(self._locations):
            self.lbl_space.setText("无可选位置")
            self._update_full_path()
            self.space_checked.emit()
            return
        # 短暂延迟后检测磁盘空间（避免频繁查询）
        self.lbl_space.setText("正在检测磁盘空间...")
        self.lbl_space.setStyleSheet("color: #666; padding: 4px 2px;")
        if self._load_timer:
            self._load_timer.stop()
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(lambda: self._show_space(idx))
        self._load_timer.start(300)
        self._update_full_path()

    def _show_space(self, idx):
        loc = self._locations[idx]
        letter = loc.get("letter", "C")
        free = _w32_get_disk_free_gb(letter)
        loc["free_gb"] = free
        enough = free >= self._required_gb
        writable, wr_err = self._check_writable(loc["path"])
        loc["writable"] = writable
        info = f"所在 {letter}: 盘 · 可用 {free} GB"
        status = "（空间充足）" if enough else f"（不足！需 {self._required_gb:.1f} GB）"
        color = "#2e7d32" if enough else "#c62828"
        if not writable:
            status = f"（该位置不可写：{wr_err}）"
            color = "#c62828"
        self.lbl_space.setText(info + "  " + status)
        self.lbl_space.setStyleSheet(f"color: {color}; padding: 4px 2px; font-weight: bold;")
        self.space_checked.emit()

    @staticmethod
    def _check_writable(path):
        """检测位置是否可写（创建临时文件测试），返回 (可写, 错误信息)。"""
        try:
            test = os.path.join(path, ".write_test_tmp")
            with open(test, "w") as f:
                f.write("t")
            os.remove(test)
            return True, ""
        except PermissionError:
            return False, "需要管理员权限"
        except Exception as e:
            return False, str(e)

    def _update_full_path(self):
        self.lbl_full.setText(f"软件将安装到：{self.get_install_path()}")

    def _on_browse(self):
        """浏览选择父位置——最终安装目录 = 所选位置 + 软件文件夹名。"""
        start_dir = self._locations[self.cb_drive.currentIndex()]["path"] \
            if 0 <= self.cb_drive.currentIndex() < len(self._locations) \
            else os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(
            self, "选择要安装到的位置（将在其下创建软件文件夹）", start_dir)
        if not chosen:
            return
        self._add_custom_location(os.path.normpath(chosen))

    def is_space_enough(self):
        idx = self.cb_drive.currentIndex()
        if idx < 0 or idx >= len(self._locations):
            return False
        loc = self._locations[idx]
        if not loc.get("writable", True):
            return False
        return loc.get("free_gb", 0) >= self._required_gb

    def get_install_path(self):
        idx = self.cb_drive.currentIndex()
        if 0 <= idx < len(self._locations):
            base = self._locations[idx]["path"]
        else:
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        sub = self.txt_path.text().strip() or "我的世界旗帜逆向套件"
        return os.path.join(base, sub)


# ===== 按架构区分的库版本表（与 visualcondition._LIB_VERSIONS 一致）=====
_ARCH_LIBS = {
    "cuda": [
        ("torch",            "2.9.1+cu130",     "1.8GB"),
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
# 固定开销：Python 运行时 + pip + 程序文件
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


def _compute_required_gb(archs, models=None, hw_info=None, purpose="train"):
    """根据选中的架构列表计算预计所需新增磁盘空间(GB)。

    只计入实际需要下载/新建的内容：
    - 程序文件（必须解压到安装目录，~0.15 GB）
    - Python 运行时（仅 CUDA/CPU 模式且系统未安装 3.10.11+ 时才计入）
    - dml_env（仅 DirectML 模式，1.3 GB，已含 torch-directml 等 pip 包）
    - pip 依赖（仅 CUDA/CPU 模式；DirectML 的 pip 包已内置于 dml_env 不另计）
    - 模型权重（ViT/DeiT 在线下载，实际 .pth 下载大小）

    hw_info: 硬件检测结果 dict，用于判断 Python 3.10.11+ 是否已安装。
    purpose: "use" = 仅识别器，跳过 matplotlib（训练专用，~0.04 GB）
    """
    archs = archs or ["cpu"]
    needs_py = bool(set(archs) & {"cuda", "cpu", "directml"})
    needs_dml = "directml" in archs

    total = _BASE_OVERHEAD_GB  # 程序文件（start.exe + 源码 + config 等）

    # Python 官方安装器：仅 CUDA/CPU 模式且系统无 3.10.11+ 时才下载安装
    # Python 安装到用户系统目录（C:\Users\xxx\AppData\Local\Programs\Python\），
    # **不占用应用安装目录**，所以这里不计入应用目录的磁盘占用估算
    if needs_py:
        py_has_311 = (hw_info or {}).get("python_has_ok", False)
        if not py_has_311:
            pass  # Python 装到用户系统，不占用应用目录空间
    # dml_env：仅 DirectML 模式（自带 torch-directml/torchvision，不含 PyQt5——PyQt5 装主环境）
    if needs_dml:
        total += 1.3
    # pip 依赖：仅 CUDA/CPU 模式需要单独下载（DirectML 的已预装在 dml_env）
    if needs_py:
        # 识别器模式跳过训练专用包
        _skip_for_use = {"matplotlib"} if purpose == "use" else set()
        seen = set()
        for arch in archs:
            if arch == "directml":
                continue  # DirectML 的 pip 包已在 dml_env 内，不重复计算
            for lib_name, _lib_ver, lib_size in _ARCH_LIBS.get(arch, []):
                if lib_name in _skip_for_use:
                    continue
                if lib_name not in seen:
                    seen.add(lib_name)
                    total += _parse_size_to_gb(lib_size)
    # ViT 在线模型权重（实际下载大小，非训练显存）
    online_sizes = {a[0]: a[4] for a in _MODEL_ARCHS if a[5] == "online"}
    for m in (models or []):
        total += online_sizes.get(m, 0)
    # 最低 0.5 GB，保留 1 位小数
    return round(max(total, 0.5), 1)


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

        # 进度条 + ETA 水平布局（ETA 独立显示，避免被进度文字挤掉）
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
        f_eta.setPointSize(self._fs_hint)
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
        f.setPointSize(self._fs_hint)
        self.detail_label.setFont(f)
        layout.addWidget(self.detail_label)

        # 重试按钮：pip 超时/失败时显示，点击重试安装（已装的包自动跳过）
        self.btn_retry = QPushButton("重试（已安装的包会自动跳过）")
        self.btn_retry.setCursor(Qt.PointingHandCursor)
        self.btn_retry.setVisible(False)
        self.btn_retry.clicked.connect(self._on_retry)
        layout.addWidget(self.btn_retry)

        layout.addStretch()
        self._thread = None
        self._mode = "install"
        self._archs = ["cpu"]  # 默认架构，由主窗口在 start 前设置
        self._install_path = ""
        self._models = None

    def set_archs(self, archs):
        """设置选中的架构列表，用于动态显示安装库。"""
        self._archs = archs if archs else ["cuda"]

    def start(self, mode, archs=None, install_path=None, models=None, purpose="train", selected_features=None):
        self._mode = mode
        self._archs = archs if archs else ["cpu"]
        self._install_path = install_path or ""
        self._models = models
        self._purpose = purpose
        self._selected_features = selected_features

        # 安装前预检查：如果需要装 Python（CUDA/CPU 模式），先检测旧版 Python 并告知用户
        needs_py = bool(set(self._archs) & {"cuda", "cpu"})
        if needs_py:
            # 已有 3.10.11+ 的兼容 Python 吗？没有的话扫描旧版 Python
            sys_py, _sys_ver = detect_system_python()
            if not sys_py:
                legacy = _scan_legacy_python()
                if legacy:
                    # 列出旧版 Python（最多 5 个）
                    ver_list = "\n".join(
                        f"  • Python {v}  （路径：{os.path.dirname(e)}）"
                        for e, v in legacy[:5])
                    msg = (
                        f"检测到您的电脑里安装了旧版 Python：\n\n"
                        f"{ver_list}\n\n"
                        f"本软件需要 Python 3.10.11 或更高版本才能运行。\n"
                        f"点击「是」继续：将下载并静默安装 Python 3.13.14 官方版，"
                        f"旧版 Python 不会被卸载（保留在原位），但不会被本软件使用。\n"
                        f"点击「否」取消：建议您先手动卸载旧版 Python（Windows 设置 → 应用 → 卸载），"
                        f"再运行本安装器，避免多版本共存造成环境紊乱。"
                    )
                    if not _ask_yes_no(self, "检测到旧版 Python", msg, default_no=False):
                        # 用户选「否」，取消安装
                        self.status_label.setText("已取消安装 — 请先卸载旧版 Python 后再运行本安装器")
                        self.detail_label.setText(
                            "操作建议：\n"
                            "1. 按 Win+I 打开 Windows 设置 → 应用 → 安装的应用\n"
                            "2. 搜索「Python」，卸载所有旧版 Python 条目\n"
                            "3. 重启电脑后重新运行本安装器"
                        )
                        self.btn_retry.setVisible(False)
                        return

        self.btn_retry.setVisible(False)
        self.lbl_title.setText(_MODE_TITLE.get(mode, "正在安装"))
        self.progress.setValue(0)
        self.detail_label.setText("")
        self.status_label.setText("准备中...")
        self.eta_label.setText("")
        self._thread = _RealInstallThread(archs or ["cpu"], install_path or "", mode, self,
                                          models=models, purpose=purpose,
                                          selected_features=selected_features)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._on_done)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_retry(self):
        """重试安装：用相同参数重新跑，已装的包自动跳过。"""
        self.start(self._mode, self._archs, self._install_path, self._models,
                   purpose=self._purpose, selected_features=self._selected_features)

    def _on_failed(self, err_msg):
        self.status_label.setText("安装失败 — 可点击下方「重试」按钮重新安装")
        # manage_components 模式失败（不弹 4:3 独立对话框）：在详情区显示错误供用户参考
        # install 模式失败（主窗口会弹 4:3 对话框）：详情区留空，避免错误显示两处
        if getattr(self, "_mode", "install") == "manage_components":
            self.detail_label.setText(f"错误：{err_msg}")
        self.btn_retry.setVisible(True)

    def _on_progress(self, value, text):
        self.progress.setValue(value)
        # 提取 ETA 信息到独立标签（避免长文字被截断看不见）
        # 匹配格式：预计剩余 X 分钟 / 预计剩余 X 秒 / 预计剩余 X 小时 / 预计剩余计算中...
        eta_match = re.search(
            r'(预计剩余|剩余)\s*'
            r'(?:([\d.]+)\s*(秒|分钟|小时)|(计算中\.+))',
            text)
        if eta_match:
            if eta_match.group(4):  # "计算中..."
                eta_text = "预计剩余计算中..."
            else:
                eta_text = f"预计剩余 {eta_match.group(2)} {eta_match.group(3)}"
            # 从 status 文字中移除 ETA 部分，保持简洁
            clean_text = text.replace(eta_match.group(0), '').replace('  ', ' ').strip()
            self.status_label.setText(clean_text)
            self.eta_label.setText(eta_text)
        else:
            self.status_label.setText(text)
            # text 中不含 ETA 信息时，清空上次的残留（避免"预计剩余 0 秒"等脏数据）
            self.eta_label.setText("")
        verb = {"install": "正在安装", "uninstall": "正在删除",
                "manage_components": "正在管理"}.get(self._mode, "正在处理")

        if self._mode == "uninstall":
            # 卸载阶段：按实际 run_uninstall() 进度映射
            phases = [
                (10,  "终止运行中的程序"),
                (40,  "删除程序文件"),
                (70,  "删除 Python 环境 / dml_env"),
                (90,  "清理快捷方式"),
                (100, "清理注册表"),
            ]
            lines = []
            for end, label in phases:
                if value >= end:
                    mark = "✓"
                elif value >= end - 10:
                    mark = "→"
                else:
                    mark = " "
                lines.append(f"  {mark} {label}")
            self.detail_label.setText(f"{verb}:\n" + "\n".join(lines))
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

        # ===== install 模式：按 run_install() 实际进度阶段映射 =====
        # 进度区间与 run_install() 完全一致：
        #   0-10%   展开程序文件（识别器模式跳过 trainer.pyw/importer.pyw）
        #   10-50%  获取 Python 运行时（CUDA/CPU 模式；DirectML-only 跳过）
        #   50-70%  复制 DirectML 环境（DirectML 模式；非 DirectML 跳过）
        #   70-85%  pip 安装依赖（识别器模式跳过 matplotlib）
        #   85-93%  下载模型权重
        #   93-96%  创建快捷方式
        #   96-100% 注册安装信息
        archs = self._archs if self._archs else ["cpu"]
        purpose = getattr(self, '_purpose', 'train')
        needs_py = bool(set(archs) & {"cuda", "cpu", "directml"})
        needs_dml = "directml" in archs
        models = self._models or []
        model_names = {a[0]: a[1] for a in _MODEL_ARCHS}

        # 构建阶段列表（动态排除不适用的阶段）
        phases = []
        extract_label = "展开程序文件" if purpose == "train" else "展开程序文件（仅识别器）"
        phases.append((0, 10, extract_label))
        if needs_py:
            phases.append((10, 50, "获取 Python 运行时"))
        if needs_dml:
            phases.append((50, 70, "复制 DirectML 环境"))
        # pip 阶段：CUDA/CPU 模式才需要（DirectML 的已预装在 dml_env）
        if needs_py:
            pip_label = "安装 pip 依赖" if purpose == "train" else "安装 pip 依赖（跳过训练专用）"
            phases.append((70, 85, pip_label))
        # 模型下载阶段
        if models:
            phases.append((85, 93, "下载模型权重"))
        phases.append((93, 96, "创建快捷方式"))
        phases.append((96, 100, "注册安装信息"))

        lines = []
        for start, end, label in phases:
            if value >= end:
                mark = "✓"
            elif value >= start:
                mark = "→"
            else:
                mark = " "
            lines.append(f"  {mark} {label}")
            # 模型下载阶段：展开每个模型
            if label == "下载模型权重" and value >= start:
                model_span = (end - start) / max(len(models), 1)
                for i, m in enumerate(models):
                    m_start = start + int(model_span * i)
                    m_end = start + int(model_span * (i + 1))
                    m_name = model_names.get(m, m)
                    if value >= m_end:
                        m_mark = "✓"
                    elif value >= m_start:
                        m_mark = "→"
                    else:
                        m_mark = " "
                    lines.append(f"    {m_mark} {m_name} 预训练权重")

        self.detail_label.setText(f"{verb}:\n" + "\n".join(lines))

    def _on_done(self):
        self.status_label.setText("安装完成！")


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
        self.cb_launch.setCursor(Qt.PointingHandCursor)
        self.cb_launch.setChecked(True)
        # 原版（桌面反编译 L3732）：不设字体，继承默认
        layout.addWidget(self.cb_launch)

        layout.addStretch()


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

        # 左侧色条（4px 宽，随卡片高度自然延伸）
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
        tf.setPointSize(max(int(9 * us), 9))
        tf.setBold(True)
        title_lbl.setFont(tf)
        title_lbl.setStyleSheet(
            f"color: {self._accent if danger else '#1a1a1a'}; border: none; background: transparent;")
        text_box.addWidget(title_lbl)
        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        df = desc_lbl.font()
        df.setPointSize(max(int(7 * us), 7))
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


# ===== 页面：升级到新版本（含补丁节点回退） =====
class _UpgradePage(_PageBase):
    """升级页面：上半部分升级到新版本，下半部分补丁节点管理（回退）。

    顶部：显示当前/目标版本，点击「开始升级」覆盖程序文件。
    底部：列出已应用的补丁节点，可回退到某个节点（撤销该补丁及其后的全部补丁）。
    导航：与其它选项窗一致，用底部统一「< 上一步」返回维护页（无页内「返回」按钮）。
    """
    upgrade_clicked = pyqtSignal()

    def __init__(self, us, install_path=None, parent=None):
        super().__init__(us, parent)
        self._us = us
        self._install_path = install_path or ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._m, self._m, self._m, self._m)
        layout.setSpacing(max(int(6 * us), 4))

        layout.addWidget(self._title("升级到新版本"))

        # ===== 上半部分：版本升级 =====
        self._ver_label = QLabel("正在读取版本信息...")
        self._ver_label.setWordWrap(True)
        f = self._ver_label.font()
        f.setPointSize(self._fs_body)
        self._ver_label.setFont(f)
        layout.addWidget(self._ver_label)

        self._upgrade_btn = QPushButton("开始升级")
        self._upgrade_btn.setCursor(Qt.PointingHandCursor)
        self._upgrade_btn.clicked.connect(self.upgrade_clicked.emit)
        up_row = QHBoxLayout()
        up_row.setContentsMargins(0, 0, 0, 0)
        up_row.addWidget(self._upgrade_btn)
        up_row.addStretch()
        layout.addLayout(up_row)

        # ===== 分隔线 =====
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #d0d0d0;")
        layout.addWidget(sep)

        # ===== 下半部分：补丁节点管理 =====
        node_title = QLabel("补丁节点（可回退）")
        nf = node_title.font()
        nf.setPointSize(self._fs_body)
        nf.setBold(True)
        node_title.setFont(nf)
        layout.addWidget(node_title)

        self._info = QLabel("正在扫描...")
        sf = self._info.font()
        sf.setPointSize(self._fs_hint)
        self._info.setFont(sf)
        self._info.setStyleSheet("color: #666;")
        layout.addWidget(self._info)

        from PyQt5.QtWidgets import QListWidget, QListWidgetItem
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget { background: #fff; border: 1px solid #d0d0d0; border-radius: 6px; "
            "padding: 4px; }"
            "QListWidget::item { padding: 6px; border-bottom: 1px solid #eee; }"
            "QListWidget::item:selected { background: #e8f0fe; color: #1a73e8; }")
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget, 1)

        # 操作按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(max(int(8 * us), 6))

        self.btn_rollback = QPushButton("回退到此节点")
        self.btn_rollback.setMinimumHeight(max(int(32 * us), 28))
        self.btn_rollback.setCursor(Qt.PointingHandCursor)
        self.btn_rollback.setStyleSheet(
            "QPushButton { background: #fff; color: #d93025; border: 1px solid #d93025; "
            "border-radius: 6px; padding: 4px 14px; }"
            "QPushButton:hover { background: #fce8e6; }"
            "QPushButton:disabled { color: #aaa; border-color: #e0e0e0; }")

        self.btn_rollback.clicked.connect(self._rollback_to_node)

        btn_row.addWidget(self.btn_rollback)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 补丁数据
        self._patches = []
        self._selected_idx = -1
        self._scan_patches()

    def set_version_info(self, old_ver, new_ver):
        """设置版本信息显示。"""
        self._ver_label.setText(
            f"当前版本：{old_ver}    →    目标版本：{new_ver}\n"
            f"覆盖程序文件（.pyw / utils / scripts），不影响模型、设置和 pip 库。")

    def _scan_patches(self):
        """扫描 patches/ 目录和旧版 _backup_* 目录（按时间正序排列）。"""
        self._patches = []
        if not self._install_path or not os.path.isdir(self._install_path):
            self._fill_list()
            return

        # 新版：patches/<timestamp>/
        patches_dir = os.path.join(self._install_path, "patches")
        if os.path.isdir(patches_dir):
            for name in sorted(os.listdir(patches_dir)):
                pdir = os.path.join(patches_dir, name)
                if not os.path.isdir(pdir):
                    continue
                meta = None
                meta_path = os.path.join(pdir, "patch_meta.json")
                if os.path.isfile(meta_path):
                    try:
                        with open(meta_path, encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        pass
                file_count = sum(1 for r, d, fs in os.walk(pdir)
                                 for fn in fs if fn not in ("patch_meta.json", "patch.zip"))
                self._patches.append((pdir, meta, False, name, file_count))

        # 旧版兼容：_backup_*
        for name in sorted(os.listdir(self._install_path)):
            if not name.startswith("_backup_"):
                continue
            bdir = os.path.join(self._install_path, name)
            if not os.path.isdir(bdir):
                continue
            file_count = sum(1 for r, d, fs in os.walk(bdir) for fn in fs)
            ts = name.replace("_backup_", "")
            self._patches.append((bdir, None, True, ts, file_count))

        self._fill_list()

    def _fill_list(self):
        """渲染补丁列表（倒序显示：最新在最上方）。"""
        from PyQt5.QtWidgets import QListWidgetItem
        self.list_widget.clear()
        if not self._patches:
            self._info.setText("暂无已应用的补丁节点。")
            self.btn_rollback.setEnabled(False)
            return

        self._info.setText(
            f"共 {len(self._patches)} 个补丁节点。选中一个节点后点击「回退到此节点」"
            f"可撤销该补丁及其后的全部补丁。")
        # 倒序显示：最新补丁在最上方，方便用户选择最近的回退点
        for display_i, idx in enumerate(range(len(self._patches) - 1, -1, -1)):
            _, meta, legacy, ts, fc = self._patches[idx]
            ver = meta.get("patch_version", "未知") if meta else "未知"
            desc = meta.get("description", "") if meta else ""
            text = f"[{display_i+1}] {ts}  |  v{ver}  |  {fc}个文件"
            if desc:
                text += f"  |  {desc[:30]}"
            item = QListWidgetItem(text)
            # item data 存储实际索引（正序）
            item.setData(Qt.UserRole, idx)
            self.list_widget.addItem(item)
        self._selected_idx = -1
        self.btn_rollback.setEnabled(False)

    def _on_item_clicked(self, item):
        self._selected_idx = item.data(Qt.UserRole)
        self.btn_rollback.setEnabled(True)

    def _rollback_to_node(self):
        """回退到选中的补丁节点：撤销该补丁及其后的全部补丁，删除对应备份。

        patches 列表按时间正序排列（旧→新）。
        选中索引 idx 表示回退到 patches[idx] 之前的状态：
          1. 从最新到 idx 依次还原备份文件（逆序保证旧备份覆盖新备份的同名文件）
          2. 删除 patches[idx] 及之后的所有备份目录
        """
        if self._selected_idx < 0 or self._selected_idx >= len(self._patches):
            return
        nodes_to_undo = self._patches[self._selected_idx:]
        _, meta_target, _, ts_target, _ = self._patches[self._selected_idx]
        ver_target = meta_target.get("patch_version", "未知") if meta_target else ts_target
        after_count = len(nodes_to_undo) - 1
        msg = (f"确定要回退到补丁 v{ver_target} 之前的状态吗？\n\n"
               f"这将撤销补丁 v{ver_target}")
        if after_count > 0:
            msg += f" 及其后的 {after_count} 个补丁"
        msg += f"，\n并删除这些补丁的备份节点。\n\n此操作不可撤销。"
        if not _ask_yes_no(self, "回退补丁节点", msg, default_no=True):
            return

        # 1. 逆序还原备份文件（最新→最旧，保证旧备份覆盖新备份的同名文件）
        restored = 0
        for pdir, _, _, _, _ in reversed(nodes_to_undo):
            for root, dirs, files in os.walk(pdir):
                for fn in files:
                    if fn in ("patch_meta.json", "patch.zip"):
                        continue
                    src = os.path.join(root, fn)
                    rel = os.path.relpath(src, pdir)
                    dst = os.path.join(self._install_path, rel)
                    try:
                        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                        shutil.copy2(src, dst)
                        restored += 1
                    except Exception:
                        pass

        # 2. 删除已撤销的备份目录
        deleted = 0
        for pdir, _, _, _, _ in nodes_to_undo:
            try:
                shutil.rmtree(pdir, ignore_errors=True)
                deleted += 1
            except Exception:
                pass

        _show_43_dialog(
            self, "回退完成",
            f"已撤销 {len(nodes_to_undo)} 个补丁，\n"
            f"还原 {restored} 个文件，删除 {deleted} 个备份节点。", "info")
        self._selected_idx = -1
        self._scan_patches()


# ===== 页面 7：维护模式 =====
class _MaintenancePage(_PageBase):
    repair_clicked = pyqtSignal()
    uninstall_clicked = pyqtSignal()
    manage_components_clicked = pyqtSignal()
    upgrade_clicked = pyqtSignal()

    def __init__(self, us, install_state=None, identity=None, parent=None):
        super().__init__(us, parent)
        self._install_state = install_state or {}
        self._identity = identity
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
        btn_repair = _CardButton("扫描检修与文件修复",
                                 "扫描安装目录文件完整性，自动修复损坏或丢失的文件", us)
        btn_upgrade = _CardButton("升级到新版本",
                                  "覆盖程序文件到最新版本，管理补丁节点回退", us)
        btn_uninstall = _CardButton("卸载",
                                    "从计算机中移除我的世界旗帜逆向套件",
                                    us, danger=True)
        self.btn_manage, self.btn_repair, self.btn_upgrade, self.btn_uninstall = \
            btn_manage, btn_repair, btn_upgrade, btn_uninstall
        for btn, sig in ((btn_manage, self.manage_components_clicked),
                         (btn_repair, self.repair_clicked),
                         (btn_upgrade, self.upgrade_clicked),
                         (btn_uninstall, self.uninstall_clicked)):
            btn.clicked.connect(sig)
            layout.addWidget(btn)

        layout.addStretch()


    def _refresh_info(self, state):
        """根据检测结果更新维护页信息。"""
        self._install_state = state or {}
        path = state.get("path", "未知路径") if state else "未知路径"
        if state and state.get("leftover"):
            # 卸载残留：锚定文件已丢，组件管理/文件修复无意义，仅提供卸载清理
            self._info_label.setText(
                f"检测到卸载残留（上次卸载未完全清理）\n"
                f"残留路径：{path}\n\n"
                "请点击「卸载」彻底清理：")
            self.btn_manage.setEnabled(False)
            self.btn_repair.setEnabled(False)
            self.btn_upgrade.setEnabled(False)
            return
        self.btn_manage.setEnabled(True)
        self.btn_repair.setEnabled(True)
        self.btn_upgrade.setEnabled(True)
        # 显示实际安装版本（内部 json/注册表记子版本号，界面补全主版本格式），
        # 不使用 _UI_VERSION——那是安装包自身版本，混淆会误导用户
        _ver_raw = state.get("version") if state else None
        ver = ("v0.5 beta1 (%s)" % _ver_raw) if _ver_raw else "未知版本"
        comps = len(state.get("components", [])) if state else 0
        self._info_label.setText(
            f"检测到已安装：{ver}，{comps} 个组件\n"
            f"安装路径：{path}\n\n"
            "请选择要执行的操作：")


# ===== 页面 8：文件修复（诊断→修复→完成） =====
class _RepairThread(QThread):
    """真实修复线程：调用 run_repair 执行文件检测与修复。"""
    progress = pyqtSignal(int, str)
    finished_repair = pyqtSignal(list, list)  # (diagnoses, fixed)

    def __init__(self, install_path, parent=None):
        super().__init__(parent)
        self._install_path = install_path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            diag, fixed = run_repair(
                self._install_path,
                lambda p, t: self.progress.emit(p, t),
                lambda: self._cancel)
            self.finished_repair.emit(diag, fixed)
        except Exception as e:
            self.finished_repair.emit([], [("__error__", "错误", str(e))])


class _RepairPage(_PageBase):
    """文件修复页面（真实检测 + 真实修复）。

    流程：
      1. 进入页面时真实检测安装目录文件完整性
      2. 点击「开始修复」用 QThread 跑 run_repair
      3. 修复完成后展示修复报告
    """
    repair_done = pyqtSignal()

    def __init__(self, us, install_path=None, parent=None):
        super().__init__(us, parent)
        self._us = us
        self._repaired = False
        self._install_path = install_path or ""
        # 真实检测安装目录完整性
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
        # 只读文本可选取复制：保留默认文本光标（I-beam），不改为抓取手势
        self.diag_text.setMinimumHeight(max(int(140 * us), 100))
        self.diag_text.setStyleSheet(
            "QTextEdit { background: #fff; border: 1px solid #d0d0d0; border-radius: 6px; "
            "padding: 8px; }")
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

        # 修复按钮
        self.btn_repair = QPushButton("开始修复")
        self.btn_repair.setCursor(Qt.PointingHandCursor)
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
        # 只读文本可选取复制：保留默认文本光标（I-beam），不改为抓取手势
        self.report_text.setMinimumHeight(max(int(140 * us), 100))
        self.report_text.setStyleSheet(
            "QTextEdit { background: #fff; border: 1px solid #d0d0d0; border-radius: 6px; "
            "padding: 8px; }")
        layout.addWidget(self.report_text)

        layout.addStretch()

        # 修复线程（真实修复，由 _RepairThread 驱动）
        self._repair_thread = None

    def _load_diagnoses(self):
        """真实检测安装目录文件完整性。返回 [(component, status, issue, action), ...]

        只检测必须存在于安装目录内的文件：
        - 程序文件（_PROGRAM_FILES）：始终检测
        - dml_env：仅当安装记录含 directml 架构时检测
        - 模型 .pth：检测所有在线模型（ViT/DeiT）的权重
        """
        if not self._install_path:
            return []
        diagnoses = []
        # 读取安装配置，获取 archs 和 models（install_components.json 在安装目录根目录）
        cfg_path = os.path.join(self._install_path, _COMPONENTS_FILE)
        installed_archs = []
        installed_models = []
        cfg_valid = False
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, encoding="utf-8-sig") as fh:
                    cfg = json.load(fh)
                installed_archs = cfg.get("archs", [])
                installed_models = cfg.get("models", [])
                cfg_valid = True
            except Exception:
                diagnoses.append((_COMPONENTS_FILE, "损坏", "JSON 解析失败", "重置为默认"))
                cfg = {}

        # 1. 检测程序文件（始终必需；但 trainer/importer 在识别器模式下不检测）
        # 旧适配：json purpose 可能过时（记 use 但磁盘已有 trainer.pyw），以磁盘文件为准
        purpose = cfg.get("purpose", "train") if cfg_valid else "train"
        purpose_use = (purpose == "use") and not os.path.isfile(
            os.path.join(self._install_path, "trainer.pyw"))
        skip_if_use = {"trainer.pyw", "importer.pyw"} if purpose_use else set()
        for f in _PROGRAM_FILES:
            if f in skip_if_use:
                continue
            dst = os.path.join(self._install_path, f)
            if not os.path.exists(dst):
                diagnoses.append((f, "丢失", f"{f} 不存在", "从安装包恢复"))
        # 2. 检测 dml_env（仅 DirectML 模式才需要）
        if "directml" in installed_archs:
            dml_dst = os.path.join(self._install_path, "dml_env")
            if not os.path.exists(dml_dst):
                diagnoses.append(("dml_env", "丢失", "DirectML 环境目录缺失", "从安装包恢复"))
        # 3. 检测模型 .pth（所有模型均为 online，均需 .pth）
        for m in installed_models:
            pth_path = os.path.join(self._install_path, "models", "structures", f"{m}.pth")
            if not _is_pth_complete(pth_path, m):
                diagnoses.append((f"models/{m}.pth", "丢失", f"{m} 权重文件缺失或残缺", "用组件管理重新下载"))
        # 4. 检测 torch/torchvision/PyQt5 是否可用
        detected = _detect_install_state(self._install_path)
        if not detected.get("torch_ok"):
            diagnoses.append(("torch", "缺失", "PyTorch 未安装或不可用", "用组件管理重新安装库"))
        if not detected.get("torchvision_ok"):
            diagnoses.append(("torchvision", "缺失", "torchvision 未安装或不可用", "用组件管理重新安装库"))
        if not detected.get("pyqt5_ok"):
            diagnoses.append(("PyQt5", "缺失", "PyQt5 未安装或不可用", "pip 安装到 vendor"))
        # 5. 读取 test.pyw 诊断结果（功能级检测：文件存在但功能异常）
        # 仅识别器（json use 且磁盘无 trainer.pyw）跳过训练器/导入器相关文件（与 run_repair 保持一致）
        _SKIP_FILES = set()
        if purpose_use:
            _SKIP_FILES = {
                "trainer.pyw", "importer.pyw",
                "utils/mbtl_reader.py", "utils/mbtl_writer.py", "utils/mbtl_utils.py",
                "utils/screenshot_dataset.py", "scripts/dml_worker.py",
            }
        test_result = os.path.join(os.environ.get("TEMP", ""), "banner_test_result.json")
        if os.path.exists(test_result):
            try:
                with open(test_result, encoding="utf-8") as f:
                    test_data = json.load(f)
                seen_files = set()
                for item in test_data.get("failed_items", []):
                    for fpath in item.get("files", []):
                        if fpath in seen_files:
                            continue
                        if fpath in _SKIP_FILES:
                            continue
                        seen_files.add(fpath)
                        dst = os.path.join(self._install_path, fpath)
                        if os.path.exists(dst):
                            diagnoses.append((fpath, "异常",
                                f"功能检测失败: {item['name']}",
                                "从安装包替换"))
            except Exception:
                pass
        return diagnoses

    def _build_repair_steps(self):
        """保留用于兼容（QThread 接管后不再使用 QTimer 推进）。"""
        return []

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
        """启动真实修复（QThread）。"""
        if self._repaired:
            return
        self.btn_repair.setEnabled(False)
        self.btn_repair.setText("修复中...")
        self.progress.setValue(0)
        self._repair_thread = _RepairThread(self._install_path, self)
        self._repair_thread.progress.connect(self._on_repair_progress)
        self._repair_thread.finished_repair.connect(self._on_repair_finished)
        self._repair_thread.start()

    def _on_repair_progress(self, pct, msg):
        """修复进度回调。"""
        self.progress.setValue(pct)
        self.lbl_progress.setText(msg)

    def _on_repair_finished(self, diagnoses, fixed):
        """修复完成，填充报告。"""
        self._repaired = True
        self.btn_repair.setText("修复已完成")
        self.lbl_progress.setText("✓ 修复完成")
        self.lbl_progress.setStyleSheet("color: #2e7d32; font-weight: bold;")
        html = ["<table style='border-collapse: collapse;' cellspacing='6'>",
                "<tr style='background:#e8f5e9; font-weight:bold;'>"
                "<td>组件</td><td>修复结果</td><td>说明</td></tr>"]
        if not fixed:
            html.append("<tr><td colspan='3' style='color:#2e7d32;'>无需修复，所有组件完整</td></tr>")
        else:
            for item in fixed:
                if len(item) == 3:
                    comp, result, note = item
                else:
                    comp, result = item[0], item[1]
                    note = ""
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
class RealInstaller(QDialog):
    PG_INIT, PG_WELCOME, PG_LICENSE, PG_PURPOSE, PG_FEATURES, PG_MODEL, \
        PG_PATH, PG_PROGRESS, PG_COMPLETE, PG_MAINT, PG_REPAIR, PG_UPGRADE = range(12)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setWindowTitle("我的世界旗帜逆向套件 v0.5 beta1 (1.0.8) Setup")

        app = QApplication.instance() or QApplication(sys.argv)
        win_scale, us = _ui_scales(app)
        self._us = us
        self._win_scale = win_scale

        self._mode = "install"
        self._purpose = "use"
        self._hw_info = None
        self._install_state = {}
        self._selected_archs = []
        self._install_path = DEFAULT_INSTALL_DIR
        self._cancelled = False

        self._fixed_w = int(640 * win_scale)
        self._fixed_h = int(480 * win_scale)

        self._build_ui(us, win_scale)
        self.setFixedSize(self._fixed_w, self._fixed_h)

    def showEvent(self, event):
        super().showEvent(event)
        # 与解码版一致：show 时再次强制固定尺寸，防止 layout sizeHint 覆盖 4:3 比例
        if hasattr(self, '_fixed_w'):
            self.setFixedSize(self._fixed_w, self._fixed_h)

    def _build_ui(self, us, win_scale):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.setSizeConstraint(QLayout.SetNoConstraint)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        banner = _BannerWidget(win_scale)
        body.addWidget(banner, 0)

        self.stack = QStackedWidget()

        self.page_init = _InitPage(us)
        self.page_welcome = _WelcomePage(us)
        self.page_license = _LicensePage(us)
        self.page_purpose = _PurposePage(us)
        self.page_features = _FeaturesPage(us)
        self.page_model = _ModelArchPage(us)
        self.page_path = _InstallPathPage(us)
        self.page_progress = _ProgressPage(us)
        self.page_complete = _CompletePage(us)
        self.page_maint = _MaintenancePage(us, identity=self._install_state.get("identity"))
        self.page_repair = _RepairPage(us, install_path=self._install_state.get("path") or self._install_path)
        self.page_upgrade = _UpgradePage(us, install_path=self._install_state.get("path") or self._install_path)
        for p in (self.page_init, self.page_welcome, self.page_license,
                  self.page_purpose, self.page_features, self.page_model,
                  self.page_path, self.page_progress, self.page_complete,
                  self.page_maint, self.page_repair, self.page_upgrade):
            self.stack.addWidget(p)

        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        bottom = QFrame()
        bottom.setFixedHeight(max(int(44 * us), 36))
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(max(int(12 * us), 10), 0,
                              max(int(12 * us), 10), max(int(6 * us), 4))
        bl.setSpacing(max(int(6 * us), 4))

        self.btn_back = QPushButton("< 上一步")
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.clicked.connect(self._go_back)

        self.btn_next = QPushButton("下一步 >")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.setDefault(True)
        self.btn_next.clicked.connect(self._go_next)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self._confirm_cancel)

        bl.addWidget(self.btn_back)
        bl.addStretch()
        bl.addWidget(self.btn_next)
        bl.addWidget(self.btn_cancel)
        root.addWidget(bottom)

        # 信号
        self.page_welcome.maintenance_clicked.connect(self._goto_maintenance)
        self.page_license.rb_accept.toggled.connect(lambda _: self._update_buttons())
        self.page_path.space_checked.connect(self._update_buttons)
        self.page_maint.repair_clicked.connect(self._maint_repair)
        self.page_repair.repair_done.connect(self._on_repair_done)
        self.page_maint.uninstall_clicked.connect(self._maint_uninstall)
        self.page_maint.manage_components_clicked.connect(self._maint_manage_components)
        self.page_maint.upgrade_clicked.connect(self._maint_upgrade)
        self.page_upgrade.upgrade_clicked.connect(self._run_upgrade)

        # 启动初始化
        self.stack.setCurrentIndex(self.PG_INIT)
        self._update_buttons()
        QTimer.singleShot(300, self._start_init)

    # ---------- 初始化 ----------
    def _start_init(self):
        _dbg("_start_init: 开始")
        # ★ 快速检测：注册表 + 固定路径 + 桌面路径（毫秒级）
        # 已安装时直接进入维护模式，不显示检测页
        state = _quick_detect_install()
        _dbg(f"_start_init: quick_detect installed={state.get('installed')}")
        if state.get("installed"):
            # 读取 install_components.json 补全信息
            comp_file = os.path.join(state["path"], _COMPONENTS_FILE)
            if os.path.exists(comp_file):
                try:
                    with open(comp_file, encoding="utf-8-sig") as f:
                        data = json.load(f) or {}
                        state["version"] = data.get("version", state.get("version"))
                        state["archs"] = data.get("archs", [])
                        state["models"] = data.get("models", [])
                        state["components"] = data.get("components", [])
                        state["purpose"] = data.get("purpose", "train")
                except Exception:
                    pass
            self._install_state = state
            self._hw_info = {"install_state": state}
            self.page_maint._refresh_info(state)
            self._goto(self.PG_MAINT)
            return
        # 未安装：启动检测线程做完整检测（含全盘扫描 + 硬件检测）
        _dbg("_start_init: 启动 _InitThread")
        self.page_init.start()
        self.page_init._thread.finished_all.connect(self._on_init_done)

    def _on_init_done(self, info):
        _dbg(f"_on_init_done: installed={info.get('install_state', {}).get('installed')}")
        self._hw_info = info
        self._install_state = info.get("install_state", {})
        # 环境拦截：检查是否支持安装（不弹窗，直接在初始化页显示）
        block_msg = self._check_env_blocked(info)
        if block_msg:
            self._env_blocked = True
            self.page_init.set_blocked(block_msg)
        else:
            self._env_blocked = False
            # ★ 已安装：自动跳转维护模式，跳过检测页（不需要用户点"下一步"）
            if self._install_state.get("installed"):
                self.page_maint._refresh_info(self._install_state)
                self._goto(self.PG_MAINT)
                return
        # 未安装：填充欢迎页摘要（从 Next 进入即可看到）
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
        os_lower = os_name.lower()
        if "windows 7" in os_lower or "windows 8" in os_lower or "macos" in os_lower or "linux" in os_lower or "ubuntu" in os_lower:
            return f"当前系统 {os_name} 不支持安装。\n\n需要 Windows 10 1909（Build 18363）及以上版本。"
        # 数字 Build 号拦截：Win10 < 18363（1909） 或 未知 Build
        os_build = info.get("os_build", 0) or 0
        if os_build and os_build < 18363:
            return (f"当前系统 {os_name} 版本过低。\n\n"
                    f"当前 Build 号：{os_build}\n"
                    f"最低要求：Build 18363（Windows 10 1909）\n\n"
                    f"请升级 Windows 系统后再安装本软件。")
        # GPU 检查：使用统一白名单（与 _w32_check_gpu_requirement 一致）
        gpu_norm = _norm_gpu(gpu_name)
        if gpu_name and gpu_name != "未知":
            has_nvidia_rtx = any(k in gpu_norm for k in _RTX_20PLUS)
            # 先查黑名单
            in_blacklist = (any(k in gpu_norm for k in _INTEL_BLACKLIST) or
                            any(k in gpu_norm for k in _AMD_BLACKLIST))
            if in_blacklist:
                return f"显卡 {gpu_name} 型号过旧，不支持 DirectML。\n\n请使用 RTX 20 系及以上、Intel Iris Xe/Arc 或 AMD Vega 7+。"
            has_intel_ok = any(k in gpu_norm for k in _INTEL_GPU_WHITELIST)
            has_amd_ok = any(k in gpu_norm for k in _AMD_GPU_SUPPORTED)
            if not (has_nvidia_rtx or has_intel_ok or has_amd_ok):
                return f"显卡 {gpu_name} 不满足最低要求。\n\n需要 RTX 20 系及以上、Intel Iris Xe/Arc 或 AMD Vega 7+。"
        return None

    # ---------- 导航 ----------
    def _update_buttons(self):
        pg = self.stack.currentIndex()
        show_back, show_next = True, True
        back_on, next_on = True, True
        next_text = "下一步 >"
        self.btn_cancel.setText("取消")

        if pg == self.PG_INIT:
            show_back = False
            next_on = self._hw_info is not None and not getattr(self, '_env_blocked', False)
            # 已安装（含 dev 作者）→ 维护模式入口
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
            next_text = "确认"
        elif pg == self.PG_MAINT:
            show_back, show_next = False, False
        elif pg == self.PG_REPAIR:
            show_next = False
            self.btn_cancel.setText("取消")
        elif pg == self.PG_UPGRADE:
            # 与其他选项窗一致：显示底部「< 上一步」回维护页，不用页内自定义「返回」
            show_back = True
            show_next = False
            self.btn_cancel.setText("关闭")

        self.btn_back.setVisible(show_back)
        self.btn_back.setEnabled(back_on)
        self.btn_next.setVisible(show_next)
        self.btn_next.setEnabled(next_on)
        self.btn_next.setText(next_text)
        self.btn_cancel.setVisible(pg not in (self.PG_COMPLETE,))

    def _go_next(self):
        pg = self.stack.currentIndex()
        if pg == self.PG_INIT:
            # 已安装（含 dev 作者）→ 维护模式；未安装 → 正式安装向导
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
                self.page_path.populate(self._hw_info, self._install_state, _archs,
                                        models=getattr(self, "_selected_archs", None),
                                        purpose=getattr(self, "_purpose", "train"))
                self._goto(self.PG_PATH)
        elif pg == self.PG_MODEL:
            if self._mode == "manage_components":
                # 管理组件：模型选完后进入库选择（像首次安装一样）
                self._selected_archs = self.page_model.get_selected()
                self._rebuild_features(self._purpose, "manage_components", self._selected_archs)
                # 回显已安装的库勾选状态（基于检测结果 + 配置文件备份）
                detected_archs = getattr(self, "_detected_archs", []) or []
                if hasattr(self.page_features, "rb_cuda"):
                    # 先全部取消，再勾选已安装的（避免默认勾选残留导致误装/误卸）
                    self.page_features.rb_cuda.setChecked(False)
                    self.page_features.rb_directml.setChecked(False)
                    self.page_features.rb_cpu.setChecked(False)
                    if "cuda" in detected_archs:
                        self.page_features.rb_cuda.setChecked(True)
                    if "directml" in detected_archs:
                        self.page_features.rb_directml.setChecked(True)
                    if "cpu" in detected_archs:
                        self.page_features.rb_cpu.setChecked(True)
                    # 触发联动更新
                    if hasattr(self.page_features, "_on_arch_changed"):
                        self.page_features._on_arch_changed()
                # 回显 features 列表中的组件复选框（管理组件模式下反映已安装状态）
                if hasattr(self.page_features, "_feature_cbs"):
                    _feat_cbs = self.page_features._feature_cbs
                    # 从已安装组件清单 + 磁盘真实存在情况联合判断勾选状态
                    _installed_comps = set()
                    # 1. 读 install_components.json 组件清单
                    _comp_path = os.path.join(self._install_path, _COMPONENTS_FILE)
                    if os.path.exists(_comp_path):
                        try:
                            with open(_comp_path, encoding="utf-8-sig") as _fc:
                                _cfg_comps = json.load(_fc).get("components", []) or []
                                _installed_comps.update(_cfg_comps)
                        except Exception:
                            pass
                    # 2. 磁盘真实检测（比配置文件更准确，避免误卸载）
                    _vend = os.path.join(self._install_path, "Lib", "site-packages")
                    if os.path.isdir(_vend):
                        _subdirs = set(d.lower() for d in os.listdir(_vend))
                        # numpy_cv2
                        if "numpy" in _subdirs and ("cv2" in _subdirs or "opencv_python" in _subdirs):
                            _installed_comps.add("numpy_cv2")
                        if "pil" in _subdirs or "pillow" in _subdirs:
                            _installed_comps.add("pillow")
                        if "matplotlib" in _subdirs:
                            _installed_comps.add("matplotlib")
                        if "psutil" in _subdirs:
                            _installed_comps.add("psutil")
                        # thermal：任意一个热监控库即认为已安装
                        if "pynvml" in _subdirs or "pyadl" in _subdirs:
                            _installed_comps.add("thermal")
                        if "pyqt5" in _subdirs:
                            _installed_comps.add("pyqt5")
                        if "torch" in _subdirs:
                            _installed_comps.add("torch")
                    # 3. 回填 checkbox：先全取消，再按已安装状态勾选（避免首次安装默认值残留）
                    for _key, _cb in _feat_cbs.items():
                        # 必装/锁定项不要强制取消，保留锁定状态
                        if not _cb.isEnabled():
                            continue
                        _cb.setChecked(_key in _installed_comps)
                self._goto(self.PG_FEATURES)
            else:
                self._selected_archs = self.page_model.get_selected()
                # 模型架构已选，重建库选择页（依据架构调整可选项）
                _mode = "install"
                self._rebuild_features(self._purpose, _mode, self._selected_archs)
                self._goto(self.PG_FEATURES)
        elif pg == self.PG_PATH:
            self._install_path = self.page_path.get_install_path()
            # 安全检查：目标目录已是有效安装 → 禁止覆盖安装，引导到维护模式
            if _is_valid_install_dir(self._install_path):
                if _ask_yes_no(
                    self, "该位置已有安装",
                    f"检测到以下目录已经安装了本软件：\n\n{self._install_path}\n\n"
                    "是否改为进入「维护模式」（管理组件/修复/卸载）？\n\n"
                    "（选择「否」将停留在当前页面，可重新选择安装位置。）",
                    default_no=False
                ):
                    # 重新检测该目录的安装状态，跳转到维护页
                    self._install_state = {
                        "installed": True,
                        "path": self._install_path,
                        "leftover": False,
                    }
                    self._install_state.update(_detect_install_state(self._install_path) or {})
                    self.page_maint._refresh_info(self._install_state)
                    self._goto(self.PG_MAINT)
                return  # 阻止进入安装流程
            self._start_progress(self._mode)
        elif pg == self.PG_COMPLETE:
            # 安装完成：勾选了「立即启动」→ 启动套件（等同双击快捷方式）
            if (self._mode == "install"
                    and self.page_complete.cb_launch.isChecked()):
                self._launch_after_install()
            self.accept()

    def _launch_after_install(self):
        """安装完成后启动套件（延迟启动，避免退出时序竞争）。

        关键：安装器是 PyInstaller onefile，退出时 bootloader 要删除临时解压
        目录（%TEMP%\\_MEIxxxx）。若安装器进程内直接 spawn start.pyw 子进程，
        子进程会继承 _MEIPASS 环境变量/临时目录句柄，导致 bootloader 清理失败
        并弹 "Failed to remove temporary directory" 警告（PyInstaller #202）。
        因此这里通过独立的延迟进程（系统 pythonw 运行 launch 脚本）启动：
        安装器完全退出、bootloader 清理完成后，再启动套件。
        """
        import tempfile as _tf
        inst_path = self._install_path or ""
        start_py = os.path.join(inst_path, "start.pyw")
        if not os.path.isfile(start_py):
            return
        # 优先复用安装时记录的系统 Python（与 pip 装包版本严格一致），
        # 避免 which/注册表找到用户其他版本（3.10/3.11/3.12）导致加载不了扩展
        sys_pythonw = _resolve_launch_pythonw(inst_path)
        if not sys_pythonw:
            try:
                import shutil as _sh
                sys_pythonw = _sh.which("pythonw")
                if not sys_pythonw:
                    import winreg as _wr
                    for hive in (_wr.HKEY_CURRENT_USER, _wr.HKEY_LOCAL_MACHINE):
                        try:
                            core = _wr.OpenKey(hive, r"Software\Python\PythonCore")
                            i = 0
                            while True:
                                try:
                                    ver = _wr.EnumKey(core, i)
                                    i += 1
                                    if not ver.startswith("3."):
                                        continue
                                    try:
                                        ik = _wr.OpenKey(core, ver + r"\InstallPath")
                                        try:
                                            exe_path, _ = _wr.QueryValueEx(ik, "ExecutablePath")
                                        except OSError:
                                            exe_path, _ = _wr.QueryValueEx(ik, None)
                                        _wr.CloseKey(ik)
                                    except OSError:
                                        continue
                                    if exe_path:
                                        pw_dir = (os.path.dirname(exe_path)
                                                  if os.path.isfile(exe_path) else exe_path)
                                        pw = os.path.join(pw_dir, "pythonw.exe")
                                        if os.path.exists(pw):
                                            sys_pythonw = pw
                                            break
                                except OSError:
                                    break
                            _wr.CloseKey(core)
                        except OSError:
                            pass
                        if sys_pythonw:
                            break
            except Exception:
                pass

        if not sys_pythonw:
            # 无系统 pythonw：直接交给文件关联（os.startfile 由 explorer 派生，
            # 不继承安装器进程环境，不会阻塞 bootloader 清理）
            try:
                os.startfile(start_py)
            except Exception:
                pass
            return

        # 写独立延迟启动脚本：等安装器进程真正退出后再启动 start.pyw。
        # 不用固定 sleep：用 WaitForSingleObject 等父进程（安装器）退出，
        # 保证 bootloader 开始清理 _MEI 时，本脚本已不再持有任何临时目录句柄。
        try:
            launch_py = os.path.join(_tf.gettempdir(), "_banner_launch_app.py")
            _parent_pid = os.getpid()
            with open(launch_py, "w", encoding="utf-8") as _f:
                _f.write(
                    "# -*- coding: utf-8 -*-\n"
                    "import os, subprocess, ctypes\n"
                    f"_parent_pid = {_parent_pid}\n"
                    "# 等待安装器进程完全退出（其 bootloader 随后清理临时目录）\n"
                    "_h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, _parent_pid)\n"
                    "if _h:\n"
                    "    ctypes.windll.kernel32.WaitForSingleObject(_h, 15000)\n"
                    "    ctypes.windll.kernel32.CloseHandle(_h)\n"
                    "# 启动套件时剔除所有指向安装器 _MEI 临时目录的 Qt/Python 变量，\n"
                    "# 否则套件会从安装器临时目录加载 Qt 插件（qwindowsvistastyle/qico）\n"
                    "# 并把它们锁住，导致安装器退出时清理 _MEI 失败弹警告\n"
                    "env = {k: v for k, v in os.environ.items()\n"
                    "          if k not in ('_MEIPASS', 'QT_PLUGIN_PATH',\n"
                    "                        'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_PLATFORM',\n"
                    "                        'QT_OPENGL', 'QT_QUICK_BACKEND',\n"
                    "                        'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP')}\n"
                    "env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'\n"
                    f"subprocess.Popen([r'{sys_pythonw}', r'{start_py}'],\n"
                    f"                 cwd=r'{inst_path}', env=env,\n"
                    "                 creationflags=0x08000000 | 0x00000008)\n"
                )
            # launch 脚本由系统 pythonw 运行：不加载安装器 _MEI 的 DLL、不继承
            # _MEIPASS/Qt 插件路径（用 _clean_launch_env 剔除），CWD 指定在
            # Python 安装目录，全程不触碰临时目录，bootloader 清理必然成功
            _launch_env = _clean_launch_env()
            _launch_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            subprocess.Popen([sys_pythonw, launch_py],
                             cwd=os.path.dirname(sys_pythonw),
                             env=_launch_env,
                             creationflags=subprocess.CREATE_NO_WINDOW
                             | subprocess.DETACHED_PROCESS)
        except Exception:
            pass

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
        elif pg == self.PG_UPGRADE:
            self._goto(self.PG_MAINT)

    def _goto(self, idx):
        self.stack.setCurrentIndex(idx)
        self._update_buttons()

    # ---------- 欢迎页动作 ----------
    def _goto_maintenance(self):
        # 已安装入口：直接进入维护页
        self.page_maint._refresh_info(self._install_state)
        self._goto(self.PG_MAINT)

    # ---------- 维护模式动作 ----------
    def _maint_repair(self):
        """修复流程：直接启动 test.pyw GUI，关闭后自动带检测结果进入修复。"""
        inst_path = self._install_state.get("path") or self._install_path or ""
        self._test_done = False

        # 1. 定位 test.pyw
        test_path = os.path.join(inst_path, "test.pyw") if inst_path else ""
        if not os.path.exists(test_path):
            meipass = getattr(sys, '_MEIPASS', None)
            if meipass:
                test_path = os.path.join(meipass, "test.pyw")
        if not os.path.exists(test_path):
            self._enter_repair_page(inst_path)
            return

        # 2. 查找 pythonw.exe
        #    优先使用安装时记录的系统 Python（与 pip 装包版本严格一致），
        #    避免 which/注册表找到用户其他版本（3.10/3.11/3.12）导致 test.pyw
        #    加载不了对应版本扩展（如 cp313 的 numpy/cv2）。
        import shutil as _shutil
        pythonw = _resolve_launch_pythonw(inst_path)
        # 【双环境隔离】UI 渲染固定由主 Python 环境（3.13+）执行。
        # dml_env（3.10）只负责 AI 运算（通过 subprocess 调用），绝不参与启动 UI 程序。
        # => 无论任何架构，一律用系统 pythonw（有 PyQt5）启动。
        if not pythonw:
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
            QMessageBox.warning(self, "提示",
                "未找到 Python 解释器，无法运行诊断测试。\n将直接进入文件修复模式。")
            self._enter_repair_page(inst_path)
            return

        # 3. 读 purpose
        _test_purpose = getattr(self, '_purpose', 'train')
        if inst_path:
            _comp_file = os.path.join(inst_path, 'install_components.json')
            if os.path.exists(_comp_file):
                try:
                    import json as _json
                    with open(_comp_file, encoding='utf-8') as _f:
                        _test_purpose = _json.load(_f).get('purpose', _test_purpose)
                except Exception:
                    pass

        # 4. 直接启动 test.pyw GUI（不弹中间对话框）
        self._test_proc = QProcess(self)
        if inst_path and os.path.isdir(inst_path):
            self._test_proc.setWorkingDirectory(inst_path)
        self._test_proc.finished.connect(
            lambda *_: self._on_test_finished(inst_path))
        self._test_proc.start(pythonw, [
            test_path, f"--purpose={_test_purpose}", "--from-installer"
        ])

        # 5. 定时检查 test.pyw 是否关闭
        self._test_check_timer = QTimer(self)
        self._test_check_timer.timeout.connect(
            lambda: self._check_test_proc(inst_path))
        self._test_check_timer.start(2000)

    def _check_test_proc(self, inst_path):
        """定时检查 test.pyw 进程状态，退出后自动进入修复页面。"""
        if not hasattr(self, '_test_proc') or self._test_proc is None:
            self._test_check_timer.stop()
            return
        if self._test_proc.state() == QProcess.NotRunning:
            self._test_check_timer.stop()
            self._on_test_finished(inst_path)

    def _on_test_finished(self, inst_path):
        """test.pyw 关闭后，读取检测结果 + 文件完整性检测，自动进入修复。

        - 检测无问题 → 提示"一切正常"，返回维护页
        - 检测有问题 → 进入修复界面
        
        【鲁棒性】包裹 try/except：早期版本此处会因 QMessageBox C/C++ 对象已被删除
        （Python 层仍持有引用但底层 Qt 对象已析构）导致二次崩溃。现在即使内部逻辑异常，
        也至少跳回维护页而不是直接崩。
        """
        try:
            if hasattr(self, '_test_done') and self._test_done:
                return
            self._test_done = True
            if hasattr(self, '_test_check_timer'):
                self._test_check_timer.stop()
            # 读取诊断结果 + 文件完整性检测
            self.page_repair._install_path = inst_path
            self.page_repair._diagnoses = self.page_repair._load_diagnoses()
            if self.page_repair._diagnoses:
                self._enter_repair_page(inst_path)
            else:
                try:
                    # 修复/检测完成提示（半尺寸，浅色统一）
                    _show_43_dialog(self, "诊断完成", "所有检测项通过，未发现需要修复的问题。", "info", half=True)
                except Exception:
                    # 极端情况：4:3对话框本身创建失败（如Qt状态异常），直接跳维护页
                    pass
                self._goto(self.PG_MAINT)
        except Exception as _e_inner:
            try:
                import traceback as _tb
                _dbg(f"_on_test_finished 异常捕获: {_e_inner}\n{_tb.format_exc()}")
            except Exception:
                pass
            # 任何异常都强制跳回维护页，保证流程不中断
            try:
                self._goto(self.PG_MAINT)
            except Exception:
                pass

    def _enter_repair_page(self, inst_path):
        """进入修复页面：填充诊断结果，启用修复按钮。"""
        self.page_repair._install_path = inst_path
        if not self.page_repair._diagnoses:
            self.page_repair._diagnoses = self.page_repair._load_diagnoses()
        self.page_repair._fill_diagnosis()
        if self.page_repair._diagnoses:
            self.page_repair.btn_repair.setEnabled(True)
            self.page_repair.btn_repair.setText("开始修复")
        else:
            self.page_repair.btn_repair.setEnabled(False)
            self.page_repair.btn_repair.setText("无需修复")
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
        # 升级页点「关闭」回维护页
        if pg == self.PG_UPGRADE:
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
        # 安装进行中取消：停止线程 + 清理残留文件
        if pg == self.PG_PROGRESS:
            if not _ask_yes_no(self, "取消安装",
                               "确定要取消安装吗？\n已下载的文件将被清理。"):
                return
            self._cancelled = True
            self.btn_cancel.setEnabled(False)
            self.page_progress.status_label.setText("正在取消，请稍候...")
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
        # 必须使用检测到的真实安装路径——否则卸载会作用在默认路径上，
        # 真实安装目录（如桌面）纹丝不动，表现为"假卸载"
        inst_path = self._install_state.get("path") or ""
        if not inst_path:
            QMessageBox.warning(self, "卸载", "未检测到安装路径，无法卸载。")
            return
        if self._install_state.get("leftover"):
            msg = (f"检测到上次卸载未完全清理的残留文件。\n"
                   f"残留路径：{inst_path}\n\n"
                   f"确定要彻底删除该目录吗？")
        else:
            msg = (f"确定要从计算机中移除我的世界旗帜逆向套件吗？\n"
                   f"安装路径：{inst_path}")
        if _ask_yes_no(self, "卸载", msg):
            self._install_path = inst_path
            self._mode = "uninstall"
            self._start_progress("uninstall")

    def _maint_upgrade(self):
        """升级到新版本：进入升级页面（含补丁节点回退）。"""
        inst_path = self._install_state.get("path") or self._install_path or ""
        if not inst_path or not os.path.isdir(inst_path):
            QMessageBox.warning(self, "升级", "未检测到有效的安装路径，无法升级。")
            return

        # 读取当前版本
        cfg_path = os.path.join(inst_path, _COMPONENTS_FILE)
        old_ver = "未知"
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, encoding="utf-8-sig") as f:
                    old_ver = (json.load(f) or {}).get("version", "未知")
            except Exception:
                pass
        # 显示实际安装版本；读取失败时显示"未知"，不冒充安装包自身版本（_UI_VERSION）
        old_ver = ("v0.5 beta1 (%s)" % old_ver) if old_ver and old_ver != "未知" else "未知"

        # 刷新升级页面
        self.page_upgrade._install_path = inst_path
        self.page_upgrade.set_version_info(old_ver, _UI_VERSION)
        self.page_upgrade._scan_patches()
        self._goto(self.PG_UPGRADE)

    def _run_upgrade(self):
        """执行升级：用安装包内文件强制覆盖所有程序文件（QThread + 进度对话框）。"""
        inst_path = self._install_state.get("path") or self._install_path or ""
        if not inst_path or not os.path.isdir(inst_path):
            QMessageBox.warning(self, "升级", "未检测到有效的安装路径，无法升级。")
            return

        # 读取当前版本（用于结果汇总）
        cfg_path = os.path.join(inst_path, _COMPONENTS_FILE)
        old_ver = "未知"
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, encoding="utf-8-sig") as f:
                    old_ver = (json.load(f) or {}).get("version", "未知")
            except Exception:
                pass
        # 显示实际安装版本；读取失败时显示"未知"，不冒充安装包自身版本（_UI_VERSION）
        old_ver = ("v0.5 beta1 (%s)" % old_ver) if old_ver and old_ver != "未知" else "未知"

        # 检测补丁备份（新版 patches/ 目录 + 旧版 _backup_* 目录）
        patch_note = ""
        if os.path.isdir(inst_path):
            patch_count = 0
            patches_dir = os.path.join(inst_path, "patches")
            if os.path.isdir(patches_dir):
                patch_count += sum(1 for d in os.listdir(patches_dir)
                                   if os.path.isdir(os.path.join(patches_dir, d)))
            patch_count += sum(1 for d in os.listdir(inst_path)
                               if d.startswith("_backup_") and os.path.isdir(os.path.join(inst_path, d)))
            if patch_count:
                patch_note = f"\n检测到 {patch_count} 个补丁备份，已被补丁修改的文件将保留（不覆盖）。\n"

        msg = (
            f"即将将程序文件升级到新版本。\n\n"
            f"当前版本：{old_ver}\n"
            f"目标版本：{_UI_VERSION}\n"
            f"安装路径：{inst_path}\n\n"
            f"将覆盖所有程序文件（.pyw / utils / scripts 等），\n"
            f"不影响：模型权重、设置、pip 库、dml_env。{patch_note}\n"
            f"确定要升级吗？"
        )
        # 与所有安装器小弹窗统一（升级确认框同步更新）
        if not _show_43_dialog(self, "升级到新版本", msg, "info", buttons=("否", "是")):
            return

        # 用 QProgressDialog + QThread 执行升级
        from PyQt5.QtCore import QThread, pyqtSignal as _Sig

        class _UpgradeThread(QThread):
            progress = _Sig(int, str)
            finished_ok = _Sig(list)
            failed = _Sig(str)

            def __init__(self, install_path, parent=None):
                super().__init__(parent)
                self._install_path = install_path
                self._cancel = False

            def cancel(self):
                self._cancel = True

            def run(self):
                try:
                    results = run_upgrade(
                        self._install_path,
                        lambda p, t: self.progress.emit(p, t),
                        cancel_check=lambda: self._cancel,
                    )
                    self.finished_ok.emit(results)
                except InterruptedError:
                    self.failed.emit("用户取消升级")
                except Exception as e:
                    self.failed.emit(str(e))

        dlg = QProgressDialog("正在升级...", "取消", 0, 100, self)
        dlg.setWindowTitle("升级到新版本")
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)

        thread = _UpgradeThread(inst_path, self)
        self._upgrade_thread = thread  # 防止 GC

        def _on_prog(pct, text):
            dlg.setValue(pct)
            dlg.setLabelText(text)

        def _on_done(results):
            dlg.close()
            # 汇总结果
            ok = sum(1 for r in results if r[1] == "已更新")
            fail = sum(1 for r in results if r[1] == "失败")
            skip = sum(1 for r in results if r[1] == "跳过")
            patched = [r for r in results if r[1] == "保留补丁"]
            summary = f"升级完成：{old_ver} → {_APP_VERSION}\n\n"
            summary += f"已更新 {ok} 个文件"
            if skip:
                summary += f"，跳过 {skip} 个"
            if patched:
                summary += f"，保留补丁 {len(patched)} 个"
            if fail:
                summary += f"，失败 {fail} 个"
                summary += "\n\n失败详情："
                for name, status, issue in results:
                    if status == "失败":
                        summary += f"\n  • {name}: {issue}"
            else:
                summary += "\n\n所有程序文件已更新到最新版本。"
            if patched:
                summary += "\n\n保留补丁的文件（未被覆盖）："
                for name, _, _ in patched:
                    summary += f"\n  • {name}"
            # 刷新维护页信息
            self._install_state.update(_detect_install_state(inst_path) or {})
            # 升级后版本号已由 run_upgrade 写入 install_components.json，
            # 而 _detect_install_state 不返回 version 字段，需重新读取，否则维护页仍显示旧版本
            try:
                with open(os.path.join(inst_path, _COMPONENTS_FILE), encoding="utf-8-sig") as _f:
                    _new_ver = (json.load(_f) or {}).get("version")
                if _new_ver:
                    self._install_state["version"] = _new_ver
            except Exception:
                pass
            self.page_maint._refresh_info(self._install_state)
            _show_43_dialog(self, "升级完成", summary, "info")
            self._goto(self.PG_MAINT)

        def _on_fail(err):
            dlg.close()
            _show_43_dialog(self, "升级失败", err, "critical")
            self._goto(self.PG_MAINT)

        def _on_cancel():
            thread.cancel()

        thread.progress.connect(_on_prog)
        thread.finished_ok.connect(_on_done)
        thread.failed.connect(_on_fail)
        dlg.canceled.connect(_on_cancel)
        thread.start()

    def _maint_manage_components(self):
        """管理组件：进入模型架构管理页面，回显已安装模型，勾选=保留/新增，取消=删除。"""
        self._mode = "manage_components"
        # 维护模式必须基于已检测到的安装路径
        self._install_path = self._install_state.get("path") or ""
        # 真实检测安装状态（不依赖配置文件，检查磁盘真实情况）
        detected = _detect_install_state(self._install_path)
        self._purpose = detected.get("purpose", "train")
        self._detected_models = detected.get("models", []) or []
        self._detected_archs = detected.get("archs", []) or []
        self._torchvision_ok = detected.get("torchvision_ok", False)
        self._torch_ok = detected.get("torch_ok", False)
        # ★ 读取 install_components.json 作为备份，防止磁盘检测失败导致已装组件被误取消
        # 磁盘检测和配置文件取并集：检测不到但配置说有 → 也勾选（避免误卸载）
        comp_file = os.path.join(self._install_path, _COMPONENTS_FILE)
        if os.path.exists(comp_file):
            try:
                with open(comp_file, encoding="utf-8-sig") as f:
                    cfg_data = json.load(f) or {}
                # archs 取并集（pip 包检测可能失败，配置文件备份防止误卸载）
                # models 不取并集（.pth 文件可明确检测，配置文件可能记录了已删的模型）
                for a in (cfg_data.get("archs", []) or []):
                    if a not in self._detected_archs:
                        self._detected_archs.append(a)
            except Exception:
                pass
        # 保险：如果磁盘检测漏了 DirectML，但 dml_env 目录存在，手动添加
        _dml_env_path = os.path.join(self._install_path, "dml_env")
        if os.path.isdir(_dml_env_path) and "directml" not in self._detected_archs:
            self._detected_archs.append("directml")
        self._rebuild_model_page(maintenance=True)
        # 回显已安装的模型勾选状态（基于真实检测结果）
        if hasattr(self.page_model, "_arch_checks"):
            # 先全不选（跳过 _trainer 训练器复选框），再勾选实际已安装的
            for k, cb in self.page_model._arch_checks.items():
                if k != "_trainer":
                    cb.setChecked(False)
            for m in self._detected_models:
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
        self.page_model = _ModelArchPage(self._us, self._hw_info, maintenance=maintenance,
                                        install_path=self._install_path)
        self.stack.insertWidget(self.PG_MODEL, self.page_model)

    def _start_progress(self, mode):
        self._mode = mode
        # 收集用户勾选的库组件（仅首次安装模式传递；管理组件由 run_manage_components 处理）
        selected_features = None
        if mode == "install" and hasattr(self, 'page_features') and hasattr(self.page_features, 'get_selected_features'):
            selected_features = self.page_features.get_selected_features()
        if mode == "manage_components":
            # 管理组件：archs 来自库选择页，models 来自模型架构页
            archs = self.page_features.get_selected_archs() if hasattr(self, 'page_features') else []
            models = self.page_model.get_selected() if hasattr(self, 'page_model') else []
        else:
            archs = self.page_features.get_selected_archs() if hasattr(self, 'page_features') else ["cuda"]
        # CUDA 模式：检查 NVIDIA 驱动版本是否支持 CUDA 13.0
        if "cuda" in archs and mode == "install":
            gpu = self._hw_info.get("discrete") if self._hw_info else None
            if gpu and gpu.get("vendor") == "nvidia":
                drv = gpu.get("nvidia_driver", (0, 0))
                if drv[0] > 0 and drv < _NVIDIA_DRIVER_MIN_FOR_CU130:
                    drv_str = f"{drv[0]}.{drv[1]}"
                    min_str = f"{_NVIDIA_DRIVER_MIN_FOR_CU130[0]}.{_NVIDIA_DRIVER_MIN_FOR_CU130[1]}"
                    ret = QMessageBox.warning(
                        self, "NVIDIA 驱动版本过低",
                        f"你的 NVIDIA 驱动版本为 {drv_str}，\n"
                        f"使用 CUDA 加速需要驱动版本 ≥ {min_str}（CUDA 13.0）。\n\n"
                        f"请到 NVIDIA 官网（www.nvidia.cn/Download）下载并更新显卡驱动，\n"
                        f"更新后即可使用 CUDA 加速。\n\n"
                        f"点击「确定」继续安装（CUDA 将无法调用 GPU，但可安装完成后用 CPU 模式），\n"
                        f"点击「取消」返回选择其他模式。",
                        QMessageBox.Ok | QMessageBox.Cancel,
                        QMessageBox.Ok)
                    if ret != QMessageBox.Ok:
                        return  # 返回功能选择页
        self.page_progress.set_archs(archs)
        self._goto(self.PG_PROGRESS)
        if mode == "manage_components":
            # 管理组件：models 已从 page_model 获取，purpose 从已安装配置读取
            purpose = getattr(self, "_purpose", "train")
        else:
            # 安装模式：把模型架构页选中的模型 key（vit_b_16 等）传给安装线程
            models = getattr(self, "_selected_archs", None)
            purpose = getattr(self, "_purpose", "train")
        self.page_progress.start(mode, archs, self._install_path,
                                 models=models, purpose=purpose,
                                 selected_features=selected_features)
        self.page_progress._thread.finished_ok.connect(self._on_progress_done)
        self.page_progress._thread.failed.connect(self._on_progress_failed)

    def _on_progress_failed(self, err_msg):
        """安装失败后返回功能选择页；用户取消时清理残留并关闭。

        失败时也调用 _cleanup_cancelled_install 清理残缺文件：
        - 首次安装失败：删除整个安装目录（包括装了一半的残缺包）
        - 覆盖安装失败：保留原 install_components.json 对应的有效安装，
          但本次新增/覆写的残缺包可能残留（下次重试时由 _pip_is_installed 检测）
        - 管理组件失败：不清理安装目录（已有有效安装，不能误删）
        """
        if getattr(self, "_cancelled", False):
            # 用户主动取消：清理已创建的安装目录，然后关闭
            # 管理组件模式下不清理（保留已有安装）
            if self._mode != "manage_components":
                self._cleanup_cancelled_install()
            self.reject()
            return
        # 管理组件失败：不清理安装目录，只弹错误提示
        if self._mode == "manage_components":
            _show_43_dialog(self, "操作失败", err_msg, "critical")
            self._goto(self.PG_MAINT)
            return
        # 安装失败：先清理残缺文件，再弹错误对话框，最后退回功能选择页
        self._cleanup_cancelled_install()
        _show_43_dialog(self, "安装失败", err_msg, "critical")
        self._goto(self.PG_FEATURES)

    def _cleanup_cancelled_install(self):
        """取消安装后清理残留文件：删除未完成的安装目录和临时文件。

        安全策略（逐层检查，比 _is_valid_install_dir 更宽松——因为我们确信
        这是本次安装创建/正在写入的目录，只需防止误删开发目录和系统目录即可）：
        1. 路径存在、非根目录、非系统目录
        2. 不含开发环境标记（.dev_marker/identity.json）
        3. 如果目录已存在 install_components.json 且是有效安装（不是本次新建），
           不删除——说明是覆盖安装取消，保留原安装
        """
        install_path = self._install_path or ""
        if install_path and os.path.isdir(install_path):
            abs_path = os.path.abspath(install_path)
            # 层1：排除根目录、系统目录
            if len(abs_path) > 3:
                is_system = False
                for forbidden in (r"C:\Windows", r"C:\Program Files", r"C:\Program Files (x86)"):
                    if abs_path.lower().startswith(forbidden.lower()):
                        is_system = True
                        break
                if not is_system:
                    # 层2：排除开发目录（单一特征 .dev_marker/identity.json）
                    is_dev = _is_dev_marker_dir(abs_path)
                    # 层3：如果已有有效安装记录（非本次新建），保留原安装
                    has_valid_install = _is_valid_install_dir(abs_path)
                    if not is_dev and not has_valid_install:
                        _rmtree_robust(abs_path)
            # 清理 Python 安装器临时文件（下载到 %TEMP% 的）
            try:
                tmp_installer = os.path.join(tempfile.gettempdir(), f"python-{PYTHON_VERSION}-amd64.exe")
                if os.path.isfile(tmp_installer):
                    os.remove(tmp_installer)
            except Exception:
                pass
            # 清理 pip 临时目录（%TEMP%\pip-*）和进度文件
            try:
                for item in os.listdir(tempfile.gettempdir()):
                    if item.startswith("pip-") or item.startswith("_banner_"):
                        _p = os.path.join(tempfile.gettempdir(), item)
                        if os.path.isdir(_p):
                            _rmtree_robust(_p)
                        elif os.path.isfile(_p):
                            os.remove(_p)
            except Exception:
                pass

    def _on_progress_done(self):
        # 部分完成（模型下载失败/文件被占用）时如实告知，不伪装成完全成功
        msg = getattr(self.page_progress._thread, "result_msg", None)
        if msg:
            title = "卸载未完成" if self._mode == "uninstall" else "安装提示"
            _show_43_dialog(self, title, msg, "warning")
        # 安装/卸载完成后清理 %TEMP% 下的 pip 缓存和 _banner_* 临时文件
        if self._mode in ("install", "uninstall"):
            try:
                for item in os.listdir(tempfile.gettempdir()):
                    if item.startswith("pip-") or item.startswith("_banner_"):
                        _p = os.path.join(tempfile.gettempdir(), item)
                        if os.path.isdir(_p):
                            _rmtree_robust(_p)
                        elif os.path.isfile(_p):
                            os.remove(_p)
            except Exception:
                pass
        self.page_complete.set_result(self._mode)
        self._goto(self.PG_COMPLETE)

    def closeEvent(self, event):
        """关闭按钮（X）与取消按钮行为一致。

        安装进行中（PG_PROGRESS）弹出取消确认；其余页面（含安装完成 PG_COMPLETE）
        均允许关闭，等价于点击取消按钮。
        """
        pg = self.stack.currentIndex()
        if pg == self.PG_PROGRESS:
            # 安装进行中点 X：触发取消流程（线程停止 + 清理残留）
            if _ask_yes_no(self, "取消安装",
                           "确定要取消安装吗？\n已下载的文件将被清理。"):
                self._cancelled = True
                if self.page_progress._thread:
                    self.page_progress._thread.cancel()
                event.accept()
            else:
                event.ignore()
            return
        # 安装完成页与其他页面：允许直接关闭（等价于取消）
        event.accept()


def _release_qt_on_exit(app, dlg):
    """退出前释放 Qt 资源，帮助 PyInstaller bootloader 删除 onefile 临时目录。

    onefile 模式下，bootloader 在 Python 进程退出后清理 %TEMP%\\_MEIxxxx。
    若 Qt DLL 句柄未释放/子进程仍引用临时目录，删除会失败并弹
    "Failed to remove temporary directory" 警告。这里主动释放 UI 对象、
    强制处理事件并短暂等待，让 bootloader 的重试能成功删除。
    """
    try:
        if dlg is not None:
            dlg.deleteLater()
        app.processEvents()
        # 销毁可见的顶层控件，释放 Qt 组件持有的 DLL 引用
        app.closeAllWindows()
        app.processEvents()
    except Exception:
        pass
    # 给 bootloader 清理留出时间窗口（其重试间隔约 1 秒）
    time.sleep(1.0)


def _clean_launch_env():
    """构建启动套件的干净环境变量。

    安装器是 PyInstaller onefile，运行时会向环境注入指向自身临时目录
    (_MEIxxxx) 的 Qt/Python 变量：QT_PLUGIN_PATH、QT_QPA_PLATFORM_PLUGIN_PATH、
    以及 PATH 中的 _MEI\\PyQt5\\Qt5\\bin 等。若把这份环境原样传给 start.pyw，
    start.pyw 会从安装器的临时目录加载 Qt 插件（qwindowsvistastyle.dll /
    qico.dll），把这两个 DLL 锁住 → 安装器退出时 bootloader 删不掉 _MEI →
    必弹 "Failed to remove temporary directory" 警告（这正是"点确认必报错、
    点关闭不报错"的根因）。
    这里剔除所有相关变量，让套件像"双击快捷方式"一样以干净环境启动。
    """
    _mei = getattr(sys, '_MEIPASS', '')
    _drop = {
        '_MEIPASS', 'PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP',
        'PYINSTALLER_RESET_ENVIRONMENT', '_PYI_ARCHIVE_FILE',
        '_PYI_PARENT_PROCESS_LEVEL', '_PYI_APPLICATION_HOME_DIR',
        'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH',
        'QT_QPA_PLATFORM', 'QT_OPENGL', 'QT_QUICK_BACKEND',
    }
    _env = {k: v for k, v in os.environ.items() if k not in _drop}
    if _mei:
        _mei_l = _mei.lower()
        _env['PATH'] = os.pathsep.join(
            p for p in _env.get('PATH', '').split(os.pathsep)
            if p and not p.lower().startswith(_mei_l))
    return _env


def _make_splash_pixmap(us, win_scale):
    """最朴实的启动画面：纯色背景 + 居中文字（无图片文件，Python 程序化生成）。

    dml_env 外置后 exe 体积小（~100MB），bootloader 解压快，
    Python 启动后立即显示此文本框，覆盖到主窗口出现前的间隙。
    """
    w = int(480 * win_scale)
    h = int(300 * win_scale)
    pix = QPixmap(w, h)
    pix.fill(QColor("#1a73e8"))  # 纯色背景，无渐变无图片
    p = QPainter(pix)
    p.setPen(QColor("white"))
    f = QFont('Microsoft YaHei', max(int(14 * us), 10))
    f.setBold(True)
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignCenter,
               "我的世界旗帜逆向套件\n\n安装程序正在加载...")
    p.end()
    return pix


def main():
    import traceback as _tb
    _log = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                        "banner_installer_debug.log")
    def _w(msg):
        try:
            with open(_log, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass
    try:
        _w("main start")
        # 单实例限制：用全局 Mutex + 窗口消息查找，重复启动时激活已运行窗口
        import ctypes
        _INSTALLER_MUTEX_NAME = "Global\\BannerToolInstallerSingleInstance"
        _INSTALLER_WINCLASS = "Qt5QWindowIcon"  # PyQt5 默认窗口类名
        _INSTALLER_WINNAME = "旗帜逆向套件下载器"
        ERROR_ALREADY_EXISTS = 183
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, _INSTALLER_MUTEX_NAME)
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            ctypes.windll.kernel32.CloseHandle(_mutex)
            # 查找并激活已运行的窗口，而不是弹框提示
            user32 = ctypes.windll.user32
            SW_RESTORE = 9
            HWND_TOPMOST = -1
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_SHOWWINDOW = 0x0040
            # 枚举所有顶层窗口，找匹配标题的窗口
            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            found_hwnd = ctypes.c_void_p(0)
            def _enum_cb(hwnd, _lparam):
                nonlocal found_hwnd
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buf, 256)
                title = buf.value
                # 匹配安装器主窗口：标题包含关键词且可见
                if (("旗帜逆向套件" in title or "BannerWeave" in title or
                     title == _INSTALLER_WINNAME or "安装" in title)
                        and user32.IsWindowVisible(hwnd)):
                    class_buf = ctypes.create_unicode_buffer(64)
                    user32.GetClassNameW(hwnd, class_buf, 64)
                    if class_buf.value == _INSTALLER_WINCLASS or "Qt" in class_buf.value:
                        found_hwnd.value = hwnd
                        return False  # 停止枚举
                return True
            user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
            if found_hwnd.value:
                hw = found_hwnd.value
                # 恢复最小化 + 置顶 + 激活
                user32.ShowWindow(hw, SW_RESTORE)
                user32.SetForegroundWindow(hw)
                user32.BringWindowToTop(hw)
                user32.SetWindowPos(hw, HWND_TOPMOST, 0, 0, 0, 0,
                                   SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
                user32.SetWindowPos(hw, -2, 0, 0, 0, 0,  # HWND_NOTOPMOST，取消永久置顶
                                   SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            sys.exit(0)
        # 保持 mutex 引用防止 GC 释放
        main._mutex = _mutex

        # 启动时更新注册表 InstallSource（让 test.pyw 能找到安装包路径）
        # 打包模式下，sys.executable 即安装包 exe 路径
        # 只在已安装（注册表 key 存在）时更新，未安装时跳过
        if getattr(sys, 'frozen', False):
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MinecraftBannerReverser",
                    0, winreg.KEY_SET_VALUE
                )
                winreg.SetValueEx(key, "InstallSource", 0, winreg.REG_SZ, sys.executable)
                winreg.CloseKey(key)
            except Exception:
                pass  # 未安装时无注册表 key，跳过

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
        # 设置应用图标（窗口标题栏 + 任务栏）
        # 方案1: Win32 API 从 exe 自身 PE 资源提取图标（最可靠，不依赖任何外部文件）
        # 方案2: 从 _MEIPASS 加载 .ico 文件（回退）
        _icon_set = False
        if getattr(sys, 'frozen', False):
            try:
                import ctypes
                hicon = ctypes.windll.shell32.ExtractIconW(0, sys.executable, 0)
                if hicon and hicon > 1:
                    try:
                        from PyQt5.QtWinExtras import QtWin
                        pixmap = QtWin.fromHICON(hicon)
                        if pixmap and not pixmap.isNull():
                            app.setWindowIcon(QIcon(pixmap))
                            _icon_set = True
                    except Exception:
                        pass
                    ctypes.windll.user32.DestroyIcon(hicon)
            except Exception:
                pass
        if not _icon_set:
            _dlg_icon = _find_icon_path("downloader.ico")
            if _dlg_icon and os.path.exists(_dlg_icon):
                app.setWindowIcon(QIcon(_dlg_icon))
        win_scale, us = _ui_scales(app)

        # 启动画面：Python 启动后立即显示，主窗口出现后关闭
        # （覆盖 exe 双击后到主窗口出现的加载间隙，避免误以为软件无响应）
        # 尺寸用 win_scale（与主窗口同比例），字体用 us
        splash = QSplashScreen(_make_splash_pixmap(us, win_scale))
        splash.show()
        app.processEvents()
        _w("splash shown")

        # --repair 参数：直接进入维护页 → 修复页
        if "--repair" in sys.argv:
            dlg = RealInstaller()
            dlg._goto_maintenance()
            dlg._maint_repair()
            dlg.show()
            splash.finish(dlg)
            dlg.exec_()
            _release_qt_on_exit(app, dlg)
            sys.exit(0)

        # 真实安装程序：直接进入安装向导
        dlg = RealInstaller()
        _w("RealInstaller created")
        dlg.show()
        splash.finish(dlg)
        _w("dlg shown, entering exec_")
        dlg.exec_()
        _w("exec_ returned")
        _release_qt_on_exit(app, dlg)
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        try:
            with open(_log, "a", encoding="utf-8") as f:
                f.write("EXCEPTION: " + _tb.format_exc() + "\n")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
