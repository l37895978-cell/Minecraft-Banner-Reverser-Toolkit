"""硬件环境检测与安装脚本

检测 GPU 类型，根据结果安装对应的 PyTorch 变体：
  - NVIDIA GPU → CUDA 版 PyTorch
  - AMD/Intel 核显 → CPU 版 PyTorch + torch-directml
  - 无 GPU → CPU 版 PyTorch

使用 PyQt5 提供友好 GUI 界面。
"""

import os
import sys
import subprocess

# 确保项目根目录在 sys.path 中
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)


def _detect_hardware():
    """检测硬件，返回 (gpu_vendor, gpu_name, is_integrated, recommended_backend, meets_requirement, reason, sys_ram_gb)。"""
    from utils.device_backend import detect_gpu_type, is_cuda_available, is_directml_available
    import psutil

    gpu_info = detect_gpu_type()
    vendor = gpu_info["vendor"]
    name = gpu_info["name"]
    is_integrated = gpu_info["is_integrated"]

    # 获取系统内存
    try:
        sys_ram_gb = round(psutil.virtual_memory().total / (1024 ** 3))
    except Exception:
        sys_ram_gb = 0

    # 检查 GPU 最低要求
    from utils.device_backend import check_gpu_requirement
    meets, reason, recommended = check_gpu_requirement(gpu_info, sys_ram_gb)

    if not meets:
        # 不满足要求，只能用 CPU
        return vendor, name, is_integrated, "cpu", False, reason, sys_ram_gb

    # 已满足要求，确定后端
    if is_cuda_available():
        recommended = "cuda"
    elif vendor in ("amd", "intel"):
        recommended = "directml"
    else:
        recommended = "cpu"

    return vendor, name, is_integrated, recommended, True, reason, sys_ram_gb


def _run_pip_install(args, log_callback=None):
    """执行 pip install，实时输出日志。"""
    cmd = [sys.executable, "-m", "pip", "install"] + args
    if log_callback:
        log_callback(f"> {' '.join(cmd)}\n")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in proc.stdout:
        if log_callback:
            log_callback(line)
    proc.wait()
    return proc.returncode == 0


def install_backend(backend, log_callback=None):
    """根据后端类型安装对应的 PyTorch 变体。

    Args:
        backend: "cuda" / "directml" / "cpu"
        log_callback: 日志回调函数
    Returns:
        (success: bool, message: str)
    """
    if log_callback:
        log_callback(f"=== 开始安装 {backend} 后端 ===\n")

    if backend == "cuda":
        # 先卸载 CPU 版 torch（如有）
        _run_pip_install(["torch", "torchvision", "--index-url",
                          "https://download.pytorch.org/whl/cu121"], log_callback)

    elif backend == "directml":
        # 安装 CPU 版 PyTorch
        _run_pip_install(["torch", "torchvision", "--index-url",
                          "https://download.pytorch.org/whl/cpu"], log_callback)
        # 安装 torch-directml
        _run_pip_install(["torch-directml"], log_callback)

    elif backend == "cpu":
        _run_pip_install(["torch", "torchvision", "--index-url",
                          "https://download.pytorch.org/whl/cpu"], log_callback)

    else:
        return False, f"未知后端: {backend}"

    # 验证安装
    if log_callback:
        log_callback("\n=== 验证安装 ===\n")
    try:
        import importlib
        importlib.invalidate_caches()
        import torch
        if log_callback:
            log_callback(f"torch 版本: {torch.__version__}\n")

        if backend == "cuda":
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                if log_callback:
                    log_callback(f"CUDA 可用: {name}\n")
                return True, f"CUDA 安装成功: {name}"
            else:
                if log_callback:
                    log_callback("警告: CUDA 不可用\n")
                return False, "PyTorch 已安装但 CUDA 不可用"

        elif backend == "directml":
            try:
                import torch_directml
                if torch_directml.is_available():
                    name = torch_directml.device_name(0)
                    if log_callback:
                        log_callback(f"DirectML 可用: {name}\n")
                    return True, f"DirectML 安装成功: {name}"
                else:
                    if log_callback:
                        log_callback("警告: DirectML 不可用\n")
                    return False, "torch-directml 已安装但不可用"
            except ImportError:
                if log_callback:
                    log_callback("错误: torch-directml 未安装\n")
                return False, "torch-directml 安装失败"

        else:  # cpu
            if log_callback:
                log_callback("CPU 后端就绪\n")
            return True, "CPU 后端安装成功"

    except Exception as e:
        if log_callback:
            log_callback(f"验证失败: {e}\n")
        return False, f"验证失败: {e}"


def save_backend_config(backend):
    """将后端配置写入 config.json 和 hardware_cache.json。"""
    try:
        from utils.settings_manager import SettingsManager, save_hardware_cache, detect_hardware
        sm = SettingsManager()
        sm.set("compute_backend", backend)

        # 重新检测硬件并更新缓存
        hw = detect_hardware()
        hw["compute_backend"] = backend
        save_hardware_cache(hw)
    except Exception as e:
        print(f"[setup_hardware] 保存配置失败: {e}")


# ===== GUI =====

def main_gui():
    """启动 GUI 安装界面。"""
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QTextEdit, QProgressBar, QGroupBox, QRadioButton
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal
    from PyQt5.QtGui import QFont

    class InstallThread(QThread):
        log_signal = pyqtSignal(str)
        finished_signal = pyqtSignal(bool, str)

        def __init__(self, backend):
            super().__init__()
            self.backend = backend

        def run(self):
            success, msg = install_backend(
                self.backend,
                log_callback=lambda s: self.log_signal.emit(s)
            )
            if success:
                save_backend_config(self.backend)
            self.finished_signal.emit(success, msg)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = QMainWindow()
    window.setWindowTitle("硬件环境检测与安装")
    window.setMinimumSize(560, 480)

    central = QWidget()
    window.setCentralWidget(central)
    layout = QVBoxLayout(central)

    # 硬件检测结果
    layout.addWidget(QLabel("正在检测硬件..."))

    vendor, gpu_name, is_integrated, recommended, meets_req, req_reason, sys_ram = _detect_hardware()

    status_text = (
        f"检测到 GPU: {gpu_name}\n"
        f"厂商: {vendor}\n"
        f"类型: {'核显（集成显卡）' if is_integrated else '独显'}\n"
        f"系统内存: {sys_ram}GB\n"
    )

    if meets_req:
        status_text += f"要求检查: ✓ {req_reason}\n推荐后端: {recommended}"
    else:
        status_text += f"要求检查: ✗ {req_reason}\n该 GPU 不满足最低要求，仅可使用 CPU 后端"

    hw_label = QLabel(status_text)
    if meets_req:
        hw_label.setStyleSheet("padding: 8px; background: #e8f5e9; border-radius: 4px;")
    else:
        hw_label.setStyleSheet("padding: 8px; background: #ffebee; border-radius: 4px;")
    layout.addWidget(hw_label)

    # 后端选择
    backend_group = QGroupBox("选择计算后端")
    backend_layout = QVBoxLayout(backend_group)

    rb_cuda = QRadioButton("CUDA (NVIDIA GPU) — 需要 NVIDIA 显卡")
    rb_directml = QRadioButton("DirectML (AMD/Intel GPU) — 适用于核显")
    rb_cpu = QRadioButton("CPU — 无 GPU 加速")

    if not meets_req:
        # 不满足要求时禁用 GPU 选项
        rb_cuda.setEnabled(False)
        rb_directml.setEnabled(False)
        rb_cpu.setChecked(True)
    elif recommended == "cuda":
        rb_cuda.setChecked(True)
    elif recommended == "directml":
        rb_directml.setChecked(True)
    else:
        rb_cpu.setChecked(True)

    backend_layout.addWidget(rb_cuda)
    backend_layout.addWidget(rb_directml)
    backend_layout.addWidget(rb_cpu)
    layout.addWidget(backend_group)

    # 安装按钮
    btn_layout = QHBoxLayout()
    install_btn = QPushButton("开始安装")
    close_btn = QPushButton("关闭")
    btn_layout.addStretch()
    btn_layout.addWidget(install_btn)
    btn_layout.addWidget(close_btn)
    layout.addLayout(btn_layout)

    # 进度条
    progress = QProgressBar()
    progress.setVisible(False)
    layout.addWidget(progress)

    # 日志
    log_edit = QTextEdit()
    log_edit.setReadOnly(True)
    log_edit.setFont(QFont("Consolas", 9))
    log_edit.setMinimumHeight(150)
    layout.addWidget(log_edit)

    # 信号处理
    install_thread = [None]

    def on_install():
        if rb_cuda.isChecked():
            backend = "cuda"
        elif rb_directml.isChecked():
            backend = "directml"
        else:
            backend = "cpu"

        install_btn.setEnabled(False)
        progress.setVisible(True)
        progress.setRange(0, 0)  # 不确定进度

        install_thread[0] = InstallThread(backend)
        install_thread[0].log_signal.connect(log_edit.append)
        install_thread[0].finished_signal.connect(on_install_finished)
        install_thread[0].start()

    def on_install_finished(success, msg):
        progress.setVisible(False)
        install_btn.setEnabled(True)
        log_edit.append(f"\n=== {'成功' if success else '失败'}: {msg} ===\n")
        if success:
            log_edit.append("配置已保存，请重启程序使设置生效。")

    def on_close():
        if install_thread[0] and install_thread[0].isRunning():
            install_thread[0].terminate()
            install_thread[0].wait()
        window.close()

    install_btn.clicked.connect(on_install)
    close_btn.clicked.connect(on_close)

    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main_gui()
