"""独立退出确认 / 恢复提示程序。

用法:
  exit.pyw exit    <source> <session_dir> <info_file> [can_save]
  exit.pyw restore <source> <session_dir> <restore_info_file>

exit 模式:
  - 显示退出确认窗口（可选"退出前保存"复选框）
  - 确认后写 .exit_confirmed（内容: save=0 或 save=1）
  - 取消后写 .exit_cancelled

restore 模式:
  - 显示恢复提示窗口（列出可恢复的自动保存文件）
  - 确认后写 .restore_confirmed（内容: file=<路径>）
  - 取消后写 .restore_cancelled

特性:
  1. Global Mutex 保证只弹一个窗口
  2. PyQt5 实现，支持深色/浅色主题
  3. 预留识别器等未来程序
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
else:
    # vendor 不存在（开发环境/源码运行）：回退到系统级安装的 PyQt5
    # 遍历 sys.path 查找 site-packages/PyQt5/Qt5，兼容 Python313 等不同版本路径
    for _sp in sys.path:
        if not _sp or not os.path.isdir(_sp):
            continue
        _sys_qt5 = os.path.join(_sp, "PyQt5", "Qt5")
        if os.path.isdir(_sys_qt5):
            _sys_qt_bin = os.path.join(_sys_qt5, "bin")
            _sys_qt_plugins = os.path.join(_sys_qt5, "plugins")
            _sys_qt_plat = os.path.join(_sys_qt_plugins, "platforms")
            if os.path.isdir(_sys_qt_bin) and _sys_qt_bin not in os.environ.get("PATH", ""):
                os.environ["PATH"] = _sys_qt_bin + os.pathsep + os.environ.get("PATH", "")
            if os.path.isdir(_sys_qt_plat):
                os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _sys_qt_plat
            if os.path.isdir(_sys_qt_plugins):
                os.environ.setdefault("QT_PLUGIN_PATH", _sys_qt_plugins)
            break
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
import ctypes


def _resolve_theme():
    """从 config.json 读取主题设置，返回 'dark' 或 'light'。"""
    try:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(app_dir, "config", "config.json")
        if not os.path.exists(config_path):
            return "light"
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        theme = data.get("theme", "light")
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
        return theme if theme in ("dark", "light") else "light"
    except Exception:
        return "light"


def _apply_dwm_dark_mode(hwnd, is_dark):
    """设置窗口标题栏深浅模式（DWM API）。"""
    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1 if is_dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


def _get_scale(app):
    """与主程序 _get_auto_scale 一致的缩放计算。"""
    screen = app.primaryScreen()
    if screen:
        sg = screen.availableGeometry()
        sw, sh = sg.width(), sg.height()
        ui_scale = max(min(sw / 1920, sh / 1080), 0.85)
        scale = min(ui_scale * 1.25, 2.5)
        return scale, sg
    return 1.25, None


def main():
    if len(sys.argv) < 4:
        return

    mode = sys.argv[1]          # "exit" 或 "restore"
    source = sys.argv[2]        # 程序名称：训练器 / 导入器 / 识别器
    session_dir = sys.argv[3]   # 信号文件目录
    info_file = sys.argv[4]     # 信息文件路径
    can_save = len(sys.argv) > 5 and sys.argv[5] == "1"

    # Global Mutex：保证同时只弹一个窗口
    mutex_name = "Global\\BannerToolExitDialog"
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(mutex)
        return

    is_dark = _resolve_theme() == "dark"

    from PyQt5.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
        QHBoxLayout, QCheckBox, QListWidget, QListWidgetItem,
        QSizePolicy
    )
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QFont, QPalette, QColor

    # 软件渲染（必须在 QApplication 创建前设置）：保证 agent 截图稳定可识别
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
    app = QApplication(sys.argv)
    app.setApplicationName("我的世界旗帜逆向套件对话框")

    if is_dark:
        pal = app.palette()
        pal.setColor(QPalette.Window, QColor(45, 45, 48))
        pal.setColor(QPalette.WindowText, Qt.white)
        pal.setColor(QPalette.Text, Qt.white)
        pal.setColor(QPalette.Button, QColor(55, 55, 58))
        pal.setColor(QPalette.ButtonText, Qt.white)
        pal.setColor(QPalette.Base, QColor(37, 37, 40))
        pal.setColor(QPalette.AlternateBase, QColor(50, 50, 53))
        pal.setColor(QPalette.Highlight, QColor(42, 130, 218))
        app.setPalette(pal)
        app.setStyle("Fusion")

    scale, sg = _get_scale(app)

    if mode == "restore":
        _run_restore(app, source, session_dir, info_file, is_dark, scale, sg,
                     kernel32, mutex)
    else:
        _run_exit(app, source, session_dir, info_file, can_save, is_dark, scale, sg,
                  kernel32, mutex)


def _run_exit(app, source, session_dir, info_file, can_save,
              is_dark, scale, sg, kernel32, mutex):
    """退出确认模式。"""
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QCheckBox,
        QSizePolicy
    )
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QFont

    # 读取退出信息
    message = "确定要退出吗？"
    try:
        if os.path.exists(info_file):
            with open(info_file, "r", encoding="utf-8") as f:
                message = f.read().strip() or message
    except Exception:
        pass

    win = QWidget()
    win.setWindowTitle(f"{source}退出确认")
    win.setWindowFlags(
        Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint |
        Qt.WindowStaysOnTopHint
    )

    # 基准窗口：340×150（宽度 340 不变，高度按用户要求压到 150，紧凑矮窗）
    w = int(340 * scale)
    h = int(150 * scale)
    if sg:
        win.setGeometry(
            sg.x() + (sg.width() - w) // 2,
            sg.y() + (sg.height() - h) // 2,
            w, h
        )
    else:
        win.resize(w, h)

    layout = QVBoxLayout(win)
    layout.setContentsMargins(int(16 * scale), int(12 * scale), int(16 * scale), int(10 * scale))
    layout.setSpacing(int(8 * scale))

    title_label = QLabel(f"【{source}】退出确认")
    title_font = QFont("Microsoft YaHei UI")
    title_font.setPixelSize(max(int(24 * scale), 17))
    title_font.setBold(True)
    title_label.setFont(title_font)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)

    msg_label = QLabel(message)
    msg_font = QFont("Microsoft YaHei UI")
    msg_font.setPixelSize(max(int(17 * scale), 13))
    msg_label.setFont(msg_font)
    msg_label.setWordWrap(True)
    msg_label.setAlignment(Qt.AlignCenter)
    msg_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    layout.addWidget(msg_label, 1)

    # 退出前保存复选框
    save_checkbox = None
    if can_save:
        save_checkbox = QCheckBox("退出前保存当前文件")
        save_cb_font = QFont("Microsoft YaHei UI")
        save_cb_font.setPixelSize(max(int(17 * scale), 13))
        save_checkbox.setFont(save_cb_font)
        save_checkbox.setChecked(True)
        layout.addWidget(save_checkbox, 0, Qt.AlignCenter)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(int(10 * scale))
    btn_row.addStretch(1)

    confirm_btn = QPushButton("确定退出")
    confirm_btn.setMinimumWidth(int(90 * scale))
    confirm_btn.setMinimumHeight(int(30 * scale))
    blue_brd = "#0078D4"
    blue_hover_bg = "#1e3a5f" if is_dark else "#e8f1fb"
    confirm_btn.setStyleSheet(
        f"QPushButton {{ background-color: transparent; color: {blue_brd}; "
        f"border: 1px solid {blue_brd}; border-radius: 4px; "
        f"padding: 6px {int(20 * scale)}px; "
        f"font-size: {max(int(14 * scale), 12)}px; }}"
        f"QPushButton:hover {{ background-color: {blue_hover_bg}; }}"
    )

    cancel_btn = QPushButton("取消")
    cancel_btn.setMinimumWidth(int(76 * scale))
    cancel_btn.setMinimumHeight(int(30 * scale))
    if is_dark:
        gray_brd, gray_fg, gray_hover = "#888888", "#eeeeee", "#2a2a2e"
    else:
        gray_brd, gray_fg, gray_hover = "#c8c8c8", "#333333", "#f0f6ff"
    cancel_btn.setStyleSheet(
        f"QPushButton {{ background-color: transparent; color: {gray_fg}; "
        f"border: 1px solid {gray_brd}; border-radius: 4px; "
        f"padding: 6px {int(20 * scale)}px; "
        f"font-size: {max(int(14 * scale), 12)}px; }}"
        f"QPushButton:hover {{ background-color: {gray_hover}; }}"
    )

    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(confirm_btn)
    btn_row.addStretch(1)
    layout.addLayout(btn_row)

    win.show()
    _apply_dwm_dark_mode(int(win.winId()), is_dark)

    confirmed_file = os.path.join(session_dir, ".exit_confirmed")
    cancelled_file = os.path.join(session_dir, ".exit_cancelled")

    def _confirm():
        save = "1" if (save_checkbox and save_checkbox.isChecked()) else "0"
        try:
            with open(confirmed_file, "w") as f:
                f.write(f"save={save}")
        except Exception:
            pass
        win.close()

    def _cancel():
        try:
            with open(cancelled_file, "w") as f:
                f.write(source)
        except Exception:
            pass
        win.close()

    confirm_btn.clicked.connect(_confirm)
    cancel_btn.clicked.connect(_cancel)
    win.closeEvent = lambda e: _cancel()

    app.exec_()

    try:
        if os.path.exists(info_file):
            os.remove(info_file)
    except Exception:
        pass
    kernel32.CloseHandle(mutex)


def _run_restore(app, source, session_dir, info_file,
                 is_dark, scale, sg, kernel32, mutex):
    """恢复提示模式：列出自动保存文件供用户选择恢复。"""
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
        QListWidget, QListWidgetItem, QSizePolicy
    )
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QFont

    # 读取恢复信息（JSON: {"files": [{"path":..., "label":...}, ...]}）
    files = []
    try:
        if os.path.exists(info_file):
            with open(info_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            files = data.get("files", [])
    except Exception:
        pass

    if not files:
        kernel32.CloseHandle(mutex)
        return

    win = QWidget()
    win.setWindowTitle(f"{source}恢复自动保存")
    win.setWindowFlags(
        Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint |
        Qt.WindowStaysOnTopHint
    )

    w = int(520 * scale)
    h = int(390 * scale)
    # ← 恢复提示小窗按 520×390 基准（文件列表内容较多，保留较大尺寸）
    if sg:
        win.setGeometry(
            sg.x() + (sg.width() - w) // 2,
            sg.y() + (sg.height() - h) // 2,
            w, h
        )
    else:
        win.resize(w, h)

    layout = QVBoxLayout(win)
    layout.setContentsMargins(int(22 * scale), int(20 * scale), int(22 * scale), int(20 * scale))
    layout.setSpacing(int(14 * scale))

    title_label = QLabel("检测到自动保存的文件")
    title_font = QFont("Microsoft YaHei UI")
    title_font.setPixelSize(max(int(18 * scale), 15))
    title_font.setBold(True)
    title_label.setFont(title_font)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)

    hint_label = QLabel("是否恢复以下文件？")
    hint_font = QFont("Microsoft YaHei UI")
    hint_font.setPixelSize(max(int(14 * scale), 12))
    hint_label.setFont(hint_font)
    hint_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(hint_label)

    list_widget = QListWidget()
    list_font = QFont("Microsoft YaHei UI")
    list_font.setPixelSize(max(int(14 * scale), 12))
    list_widget.setFont(list_font)
    for item_info in files:
        item = QListWidgetItem(item_info.get("label", item_info.get("path", "")))
        item.setData(Qt.UserRole, item_info.get("path", ""))
        list_widget.addItem(item)
    list_widget.setCurrentRow(0)
    layout.addWidget(list_widget, 1)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(int(10 * scale))
    btn_row.addStretch(1)

    # 透明线框按钮（与设置窗口一致）：OK 蓝、全部恢复绿、删除全部红、跳过灰
    if is_dark:
        _blue_brd, _blue_hover = "#0078D4", "#1e3a5f"
        _green_brd, _green_hover = "#34a853", "#1e3325"
        _red_brd, _red_hover = "#ea4335", "#3a1f1d"
        _gray_brd, _gray_fg, _gray_hover = "#888888", "#eeeeee", "#2a2a2e"
    else:
        _blue_brd, _blue_hover = "#0078D4", "#e8f1fb"
        _green_brd, _green_hover = "#34a853", "#e8f5ec"
        _red_brd, _red_hover = "#ea4335", "#fdecea"
        _gray_brd, _gray_fg, _gray_hover = "#c8c8c8", "#333333", "#f0f6ff"
    _wire = "QPushButton {{ background-color: transparent; color: {fg}; " \
            "border: 1px solid {brd}; border-radius: 4px; " \
            "padding: 4px {pad}px; font-size: {fs}px; }} " \
            "QPushButton:hover {{ background-color: {hov}; }}"

    restore_btn = QPushButton("恢复选中")
    restore_btn.setMinimumWidth(int(90 * scale))
    restore_btn.setMinimumHeight(int(30 * scale))
    restore_btn.setStyleSheet(
        _wire.format(fg=_blue_brd, brd=_blue_brd, hov=_blue_hover,
                     pad=int(14 * scale), fs=max(int(14 * scale), 14))
    )

    restore_all_btn = QPushButton("全部恢复")
    restore_all_btn.setMinimumWidth(int(90 * scale))
    restore_all_btn.setMinimumHeight(int(30 * scale))
    restore_all_btn.setStyleSheet(
        _wire.format(fg=_green_brd, brd=_green_brd, hov=_green_hover,
                     pad=int(14 * scale), fs=max(int(14 * scale), 14))
    )

    skip_btn = QPushButton("跳过")
    skip_btn.setMinimumWidth(int(76 * scale))
    skip_btn.setMinimumHeight(int(30 * scale))
    skip_btn.setStyleSheet(
        _wire.format(fg=_gray_fg, brd=_gray_brd, hov=_gray_hover,
                     pad=int(14 * scale), fs=max(int(14 * scale), 14))
    )

    # 删除全部自动保存按钮（防止自动保存过度堆积）
    delete_all_btn = QPushButton("删除全部")
    delete_all_btn.setMinimumWidth(int(76 * scale))
    delete_all_btn.setMinimumHeight(int(30 * scale))
    delete_all_btn.setStyleSheet(
        _wire.format(fg=_red_brd, brd=_red_brd, hov=_red_hover,
                     pad=int(14 * scale), fs=max(int(14 * scale), 14))
    )

    btn_row.addWidget(skip_btn)
    btn_row.addWidget(delete_all_btn)
    btn_row.addWidget(restore_all_btn)
    btn_row.addWidget(restore_btn)
    btn_row.addStretch(1)
    layout.addLayout(btn_row)

    win.show()
    _apply_dwm_dark_mode(int(win.winId()), is_dark)

    confirmed_file = os.path.join(session_dir, ".restore_confirmed")
    cancelled_file = os.path.join(session_dir, ".restore_cancelled")

    def _restore_selected():
        item = list_widget.currentItem()
        if item:
            path = item.data(Qt.UserRole)
            try:
                with open(confirmed_file, "w", encoding="utf-8") as f:
                    f.write(f"file={path}")
            except Exception:
                pass
        win.close()

    def _restore_all():
        all_paths = []
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            all_paths.append(item.data(Qt.UserRole))
        try:
            with open(confirmed_file, "w", encoding="utf-8") as f:
                f.write("file=" + "|".join(all_paths))
        except Exception:
            pass
        win.close()

    def _skip():
        try:
            with open(cancelled_file, "w", encoding="utf-8") as f:
                f.write(source)
        except Exception:
            pass
        win.close()

    def _delete_all():
        """删除全部自动保存文件夹（含 auto 标记文件所在的日期文件夹），然后正常进入。"""
        from PyQt5.QtWidgets import QMessageBox as _QMsg
        import shutil
        # 确认对话框
        confirm = _QMsg(win)
        confirm.setWindowTitle("确认删除")
        confirm.setText("将删除全部自动保存文件夹（含 auto 标记），此操作不可撤销。")
        confirm.setStandardButtons(_QMsg.Yes | _QMsg.No)
        confirm.setDefaultButton(_QMsg.No)
        _apply_dwm_dark_mode(int(confirm.winId()), is_dark)
        if confirm.exec_() != _QMsg.Yes:
            return
        # 收集含 'auto' 文件所在的日期文件夹，去重后整文件夹删除
        deleted_dirs = set()
        for item_info in files:
            fp = item_info.get("path", "")
            fname = os.path.basename(fp)
            if fp and 'auto' in fname:
                parent = os.path.dirname(fp)
                if parent and parent not in deleted_dirs:
                    deleted_dirs.add(parent)
                    try:
                        shutil.rmtree(parent)
                    except Exception:
                        pass
        # 写 cancelled 让训练器正常进入
        try:
            with open(cancelled_file, "w", encoding="utf-8") as f:
                f.write(source)
        except Exception:
            pass
        win.close()

    restore_btn.clicked.connect(_restore_selected)
    restore_all_btn.clicked.connect(_restore_all)
    skip_btn.clicked.connect(_skip)
    delete_all_btn.clicked.connect(_delete_all)
    win.closeEvent = lambda e: _skip()

    app.exec_()

    try:
        if os.path.exists(info_file):
            os.remove(info_file)
    except Exception:
        pass
    kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
