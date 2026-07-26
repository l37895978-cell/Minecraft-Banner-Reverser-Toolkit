"""旗帜训练工具 — 使用说明窗口

独立运行的帮助窗口，展示使用教程。
支持深浅色模式（读取 config/config.json 的 theme 设置）。
支持与设置窗口一致的缩放机制（--scale 参数或屏幕自动检测）。
可从训练器、导入器、识别器的"帮助 → 使用说明"菜单打开。
"""

import os
import sys
import json
import argparse
import ctypes

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTextBrowser, QVBoxLayout, QWidget,
    QPushButton, QHBoxLayout, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from utils.settings_manager import apply_dwm_dark_mode, apply_theme, resolve_theme


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


def _build_stylesheet(is_dark, scale):
    """根据主题和缩放生成全局样式表（字号公式与 settings 一致）。"""
    base_fs = max(int(13 * scale), 13)
    btn_fs = max(int(14 * scale), 14)
    pad_v = max(int(8 * scale), 6)
    pad_h = max(int(24 * scale), 18)
    text_pad_v = max(int(20 * scale), 14)
    text_pad_h = max(int(30 * scale), 20)

    if is_dark:
        bg = "#1e1e1e"
        fg = "#e0e0e0"
        border = "#3c3c3c"
        link = "#4fc3f7"
        code_bg = "#2a2a2a"
        scroll_handle = "#555555"
        scroll_hover = "#666666"
    else:
        bg = "#ffffff"
        fg = "#1a1a1a"
        border = "#cccccc"
        link = "#1a73e8"
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
            background-color: {code_bg};
            color: {fg};
            border: 1px solid {border};
            border-radius: 4px;
            padding: {pad_v}px {pad_h}px;
            font-size: {btn_fs}px;
            min-height: {max(int(20 * scale), 18)}px;
        }}
        QPushButton:hover {{
            border-color: {link};
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
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
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
        code_bg = "#2a2a2a"
        code_fg = "#ffb74d"
        note_bg = "#1a2a1a"
        note_border = "#4a7a4a"
        warn_bg = "#3a2a1a"
        warn_border = "#7a5a3a"
        text_color = "#e0e0e0"
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

    <h1 style="color:{title_color}; text-align:center; font-size:{h1_fs}px; margin-bottom:5px;">旗帜训练工具 — 使用说明</h1>
    <p style="text-align:center; color:#888; font-size:{small_fs}px;">版本 v0.5 beta1</p>

    <hr style="border:none; border-top:1px solid {code_bg}; margin:20px 0;"/>

    <h2 style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">一、项目概述</h2>
    <p>旗帜训练工具是一套 Minecraft 风格旗帜的创建、导入与 AI 训练系统，包含三个组件：</p>
    <ul>
        <li><b>旗帜训练导入器</b> — 旗帜图案编辑器，用于创建和编辑旗帜</li>
        <li><b>旗帜训练器</b> — AI 训练引擎，基于 ViT 架构进行旗帜学习</li>
        <li><b>旗帜印染逆向器</b> — 旗帜图片逆向识别工具（BannerDyeOrderReverser）</li>
    </ul>
    <p>训练器和导入器联动运行：关闭任一窗口，另一个自动关闭。</p>

    <h2 style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">二、启动方式</h2>
    <table style="width:100%; border-collapse:collapse; margin:10px 0; font-size:{body_fs}px;">
        <tr style="background-color:{code_bg};">
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};"><b>方式</b></td>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};"><b>说明</b></td>
        </tr>
        <tr>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">双击 trainer.pyw</td>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">选择训练模式 → 加载界面 → 训练器(左) + 导入器(右)</td>
        </tr>
        <tr>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">双击 importer.pyw</td>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">同上，从导入器启动</td>
        </tr>
        <tr>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">双击 BannerDyeOrderReverser/bdor.pyw</td>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">独立运行旗帜识别器</td>
        </tr>
        <tr>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">双击 .mbtl 文件</td>
            <td style="padding:{cell_pad}px; border:1px solid {code_bg};">需训练工具已启动，导入器自动加载</td>
        </tr>
    </table>

    <h2 style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">三、旗帜训练导入器</h2>

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

    <h2 style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">四、旗帜训练器</h2>

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
        <li>模型保存路径：models/model_file/banner_vit_model.pth</li>
        <li>点击"保存模型"手动保存当前模型权重</li>
        <li>点击"继续训练"加载已有模型继续训练</li>
    </ul>

    <h2 style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">五、旗帜印染逆向器</h2>
    <ol>
        <li>加载模型（点击"加载默认模型"或"选择模型文件"）</li>
        <li>导入旗帜图片（从文件或剪贴板）</li>
        <li>点击"逆向印染"</li>
        <li>查看识别结果：序列信息 + 还原预览图</li>
    </ol>

    <h2 style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">六、数据格式（MBTL）</h2>
    <div style="background-color:{code_bg}; padding:12px; border-radius:6px; font-family:Consolas,monospace; font-size:{code_fs}px; color:{code_fg};">
        魔数(4B): "MBTL"<br/>
        版本(2B): 0x0001<br/>
        数量(4B): N<br/>
        每面旗帜: 背景色(1B) + 图案层数(1B) + [图案类型(1B) + 图案颜色(1B)] × 层数
    </div>

    <h2 style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">七、序列图组标记格式（MBTLX）</h2>

    <p><b>.mbtlx</b> 是序列图组训练专用的标记文件，用于保存一组「图片—旗帜」的对应关系。<br/>
    <b>核心原则：一张图片对应一面旗帜</b>，与普通训练一致，只是数据来源为用户标记的真实图片而非程序生成的旗帜图。</p>

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
        <li>在<b>旗帜训练器</b>中切换到「序列图组训练」标签页（开发中）</li>
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

    <h2 style="color:{h2_color}; font-size:{h2_fs}px; border-bottom:2px solid {h2_color}; padding-bottom:5px;">八、常见问题</h2>

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
        A: 先在训练器中训练并保存模型，默认保存到 models/model_file/ 目录。
    </div>

    <div style="background-color:{warn_bg}; border-left:4px solid {warn_border}; padding:10px 15px; margin:10px 0;">
        <b>Q: 双击 .mbtl 文件提示"请先启动旗帜训练工具"？</b><br/>
        A: 需要先启动训练工具，再双击 .mbtl 文件。导入器启动后会自动检测并加载文件。
    </div>

    <hr style="border:none; border-top:1px solid {code_bg}; margin:20px 0;"/>
    <p style="text-align:center; color:#888; font-size:{tiny_fs}px;">如遇其他问题请反馈。本版本为 v0.5 beta1，功能持续完善中。</p>

    </body></html>
    """


class HelpWindow(QMainWindow):
    def __init__(self, scale=None):
        super().__init__()
        self.setWindowTitle("使用说明 — 旗帜训练工具")

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

        # 主题同步定时器（与主窗口一致的 mtime 检测）
        self._theme_timer = QTimer(self)
        self._theme_timer.timeout.connect(self._sync_theme)
        self._theme_timer.start(1000)

        # 居中显示
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.x() + (geo.width() - self.width()) // 2,
                geo.y() + (geo.height() - self.height()) // 2
            )

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

    # 单实例限制
    if not _ensure_single_instance():
        ctypes.windll.user32.MessageBoxW(
            0, "帮助窗口已经打开，请先关闭已有的帮助窗口。",
            "提示", 64  # MB_ICONINFORMATION
        )
        return

    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, default=0.0)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", app.font().pointSize()))

    # 应用全局调色板（让原生元素跟随深浅色主题）
    apply_theme(app, resolve_theme(_get_theme()))

    scale = args.scale if args.scale > 0 else None
    window = HelpWindow(scale)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
