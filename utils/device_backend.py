"""计算后端抽象层

统一管理三种计算后端：cuda / directml / cpu。
提供 GPU 类型检测、后端选择、设备获取等功能。
"""

import os
import sys
import subprocess
import re


def _sp(msg):
    try:
        print(msg)
    except Exception:
        pass


def _get_nvidia_vram_gb():
    """通过 CUDA API 或 nvidia-smi 获取 NVIDIA GPU 准确显存（GB）。

    WMI 的 AdapterRAM 是 uint32，4GB+ 显卡会溢出，因此需要用其他方式获取。
    """
    # 方式1: torch.cuda
    try:
        import torch
        if torch.cuda.is_available():
            return max(1, round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)))
    except Exception:
        pass

    # 方式2: nvidia-smi
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if r.returncode == 0 and r.stdout.strip():
            mib = int(r.stdout.strip().split("\n")[0].strip())
            return max(1, round(mib / 1024))
    except Exception:
        pass

    return 0


# ===== GPU 类型检测 =====

def detect_gpu_type():
    """检测 GPU 类型，返回 {vendor, name, is_integrated, vram_gb}。

    通过 WMI 查询显卡信息：
    - vendor: "nvidia" / "amd" / "intel" / "none"
    - name: GPU 型号名称
    - is_integrated: 是否为核显（共享系统内存）
    - vram_gb: 显存大小（核显报告共享内存或 0）
    """
    result = {"vendor": "none", "name": "未检测到", "is_integrated": False, "vram_gb": 0}

    if not sys.platform.startswith("win"):
        return result

    # 方式1: PowerShell Get-CimInstance + ConvertTo-Json（获取完整信息）
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | "
             "Select-Object Name, AdapterRAM, VideoProcessor | ConvertTo-Json"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if r.returncode == 0 and r.stdout.strip():
            import json
            data = json.loads(r.stdout.strip())

            # 单个显卡返回 dict，多个返回 list
            if isinstance(data, dict):
                gpus = [data]
            elif isinstance(data, list):
                gpus = data
            else:
                gpus = []

            # 优先选择独立显卡
            best_gpu = None
            for gpu in gpus:
                if not isinstance(gpu, dict):
                    continue
                name = (gpu.get("Name") or "").strip()
                if not name:
                    continue

                vendor = _identify_vendor(name)
                is_integrated = _is_integrated_gpu(name)

                # 优先选择独显（NVIDIA > AMD 独显 > Intel 独显 > 核显）
                if vendor == "nvidia":
                    best_gpu = gpu
                    break
                elif best_gpu is None or (not _is_integrated_gpu(best_gpu.get("Name", "")) and is_integrated):
                    best_gpu = gpu

            if best_gpu is None and gpus:
                best_gpu = gpus[0]

            if best_gpu and isinstance(best_gpu, dict):
                name = (best_gpu.get("Name") or "").strip()
                result["name"] = name
                result["vendor"] = _identify_vendor(name)
                result["is_integrated"] = _is_integrated_gpu(name)
                # AdapterRAM 是 uint32，最大约 4GB，对 4GB+ 显卡会溢出
                # 优先使用 torch.cuda / nvidia-smi 获取准确显存
                adapter_ram = best_gpu.get("AdapterRAM") or 0
                vram_gb = 0
                if adapter_ram and adapter_ram > 0:
                    vram_gb = max(1, round(adapter_ram / (1024 ** 3)))

                # NVIDIA: 用 CUDA API 或 nvidia-smi 修正显存
                if result["vendor"] == "nvidia":
                    vram_gb = _get_nvidia_vram_gb() or vram_gb

                # 如果 WMI 报告 4GB（uint32 溢出），且无法通过其他方式获取，设为 0（跳过显存检查）
                if vram_gb == 4 and result["vendor"] == "nvidia" and not _is_integrated_gpu(name):
                    # 可能是溢出，尝试 nvidia-smi
                    smi_vram = _get_nvidia_vram_gb()
                    if smi_vram:
                        vram_gb = smi_vram
                    else:
                        vram_gb = 0  # 无法确定，跳过显存检查

                result["vram_gb"] = vram_gb

    except Exception as e:
        _sp(f"[device_backend] GPU检测(JSON模式)失败: {e}")

    # 方式2: 回退 — 如果方式1未检测到 GPU，用 -ExpandProperty Name 获取显卡名称
    if result["vendor"] == "none":
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if r.returncode == 0 and r.stdout.strip():
                for line in r.stdout.strip().splitlines():
                    name = line.strip()
                    if not name:
                        continue
                    vendor = _identify_vendor(name)
                    if vendor != "unknown":
                        result["name"] = name
                        result["vendor"] = vendor
                        result["is_integrated"] = _is_integrated_gpu(name)
                        break
        except Exception as e:
            _sp(f"[device_backend] GPU检测(回退模式)失败: {e}")

    return result


def _identify_vendor(name):
    """根据 GPU 名称识别厂商。"""
    name_lower = name.lower()
    if "nvidia" in name_lower or "geforce" in name_lower or "rtx" in name_lower or "gtx" in name_lower:
        return "nvidia"
    if "amd" in name_lower or "radeon" in name_lower:
        return "amd"
    if "intel" in name_lower:
        return "intel"
    return "unknown"


def _is_integrated_gpu(name):
    """判断是否为核显（集成显卡）。使用 _norm_gpu_name 归一化后匹配。"""
    name_lower = _norm_gpu_name(name)
    # Intel 核显系列
    intel_igpu_keywords = ["intel uhd", "intel iris", "intel hd graphics",
                           "intel graphics"]
    # AMD 核显系列（APU 集成显卡）
    amd_igpu_keywords = ["radeon graphics",
                         # RDNA2/3/3.5 iGPU 型号（780M/890M 等）
                         "radeon 7", "radeon 8",
                         "radeon 660m", "radeon 680m",
                         "radeon 760m", "radeon 780m",
                         "radeon 840m", "radeon 860m", "radeon 880m", "radeon 890m",
                         # Vega 全系列（Ryzen 2000-5000 APU, 含低端 Vega 2/3/5/6）
                         "vega 2", "vega 3", "vega 5", "vega 6",
                         "vega 7", "vega 8", "vega 10", "vega 11"]

    for kw in intel_igpu_keywords:
        if kw in name_lower:
            return True
    for kw in amd_igpu_keywords:
        if kw in name_lower:
            return True

    # Intel 核显通常不含独立型号名（如不含 "Arc"）
    if "intel" in name_lower and "arc" not in name_lower:
        return True

    # AMD APU 核显：名称含 "radeon" + "m" 后缀的型号（如 890M），且非 RX 独显
    if "radeon" in name_lower and "rx" not in name_lower:
        if re.search(r'\d+m\b', name_lower):
            return True

    return False


# ===== 后端检测 =====

def is_cuda_available():
    """检测 CUDA 是否可用。"""
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def is_directml_available():
    """检测 torch-directml 是否安装且可用。"""
    try:
        import torch_directml
        return torch_directml.is_available()
    except Exception:
        return False


def get_compute_backend(force=None):
    """返回当前计算后端：cuda / directml / cpu。

    Args:
        force: 强制后端模式。
            None / "auto" — 自动检测（cuda > directml > cpu）
            "discrete"    — 独显模式（NVIDIA→CUDA，AMD/Intel→DirectML）
            "integrated"  — 核显模式（DirectML）
            "cpu"         — CPU 模式

    优先级（force=None/auto）：cuda > directml > cpu
    """
    # 读取设置（如果未显式传参）
    if force is None:
        try:
            from utils.settings_manager import SettingsManager
            force = SettingsManager().get("compute_backend", "auto")
        except Exception:
            force = "auto"

    if force == "cpu":
        return "cpu"

    if force == "discrete":
        # 独显模式：NVIDIA → CUDA，其他 → DirectML
        if is_cuda_available():
            return "cuda"
        if is_directml_available():
            return "directml"
        return "cpu"

    if force == "integrated":
        # 核显模式：DirectML
        if is_directml_available():
            return "directml"
        return "cpu"

    # auto：自动检测
    if is_cuda_available():
        return "cuda"
    if is_directml_available():
        return "directml"
    return "cpu"


def get_device(backend=None):
    """返回对应的 torch.device。

    Args:
        backend: "cuda" / "directml" / "cpu" / None（自动检测）
    """
    import torch

    if backend is None:
        backend = get_compute_backend()

    if backend == "cuda":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    elif backend == "directml":
        try:
            import torch_directml
            if torch_directml.is_available():
                return torch_directml.device()
        except Exception:
            pass
        return torch.device("cpu")
    else:
        return torch.device("cpu")


def supports_mixed_precision(backend=None):
    """检测后端是否支持混合精度训练（CUDA AMP）。

    DirectML 和 CPU 不支持 CUDA AMP。
    """
    if backend is None:
        backend = get_compute_backend()
    return backend == "cuda"


def supports_pin_memory(backend=None):
    """检测后端是否支持 DataLoader pin_memory。

    pin_memory 是 CUDA 专属优化。
    """
    if backend is None:
        backend = get_compute_backend()
    return backend == "cuda"


def supports_memory_fraction(backend=None):
    """检测后端是否支持 set_per_process_memory_fraction。

    仅 CUDA 支持此 API。
    """
    if backend is None:
        backend = get_compute_backend()
    return backend == "cuda"


def supports_gpu_temp_monitoring(backend=None):
    """检测后端是否支持 GPU 温度监控（pynvml）。

    仅 CUDA (NVIDIA) 支持。
    """
    if backend is None:
        backend = get_compute_backend()
    return backend == "cuda"


def empty_cache_for_backend(backend=None):
    """按后端清理 GPU 缓存。

    CUDA: torch.cuda.empty_cache()
    DirectML: torch_directml.empty_cache()（若可用）+ gc.collect()
    CPU: gc.collect()

    DirectML 无法限制显存上限，长时训练需定期调用以压住峰值、缓解碎片化。
    """
    if backend is None:
        backend = get_compute_backend()
    try:
        if backend == "cuda":
            import torch
            torch.cuda.empty_cache()
        elif backend == "directml":
            try:
                import torch_directml
                if hasattr(torch_directml, "empty_cache"):
                    torch_directml.empty_cache()
            except Exception:
                pass
            import gc
            gc.collect()
        else:
            import gc
            gc.collect()
    except Exception:
        pass


def get_backend_display_name(backend=None):
    """返回后端的显示名称。"""
    if backend is None:
        backend = get_compute_backend()
    names = {
        "cuda": "CUDA (NVIDIA GPU)",
        "directml": "DirectML (AMD/Intel GPU)",
        "cpu": "CPU",
    }
    return names.get(backend, backend)


def get_directml_device_name():
    """返回 DirectML 设备名称（如检测到）。"""
    try:
        import torch_directml
        if torch_directml.is_available():
            return torch_directml.device_name(0)
    except Exception:
        pass
    return None


# ===== GPU 最低要求检测 =====

def _norm_gpu_name(name):
    """归一化 GPU 名称：去除商标标记 (tm)/(r)/(c)，压缩空白。

    使 "AMD Radeon(TM) 780M" 能匹配关键词 "radeon 780m"。
    """
    s = re.sub(r'\s*\((?:tm|r|c)\)\s*', ' ', (name or '').lower())
    return re.sub(r'\s+', ' ', s).strip()


# NVIDIA 最低要求
NVIDIA_MIN_ERA = 20        # RTX 20 系及以上
NVIDIA_MIN_VRAM_GB = 6     # 最低 6GB 显存

# 核显最低要求
IGPU_MIN_SYS_RAM_GB = 8    # 核显最低系统内存 8GB（共享显存需 2GB+OS 6GB）

# 不支持的 Intel 核显特殊型号（同年代 Xe 架构但 EU 数不足，其余不在白名单的默认淘汰）
_INTEL_BLACKLIST = [
    "intel(r) uhd graphics 730",  # Alder Lake 24EU，性能不足
    "intel(r) uhd graphics 750",  # Rocket Lake 32EU，性能不足
    "intel(r) uhd graphics 32",   # Alder Lake 32EU 版本
]

# 支持的 Intel 核显/独显关键词（白名单：完整列表，不在其中的一律不支持 DirectML）
_INTEL_IGPU_SUPPORTED = [
    # ── 11代+ Iris Xe（Tiger Lake, 2020+）── 80EU/96EU，Gen 12 Xe 架构
    "iris xe", "iris(r) xe",
    # ── Iris Xe MAX（DG1, 独立版 Iris Xe, 2021）──
    "iris xe max", "iris(r) xe max",
    # ── 12/13代 UHD 770（Alder Lake / Raptor Lake 桌面, 2022+）── 32EU
    "uhd graphics 770",
    # ── Meteor Lake Arc 集成（7+ cores, 2023+）──
    "arc graphics", "arc 7", "arc 8",
    # ── Lunar Lake Arc 140V/130V（2024+）──
    "arc 140v", "arc 130v",
    # ── Arc 独显系列（A310~A770, B570~B580, Laptop 版本同样适用）──
    "arc a", "arc b",
]

# 不支持的 AMD 核显特殊型号（名称含 "radeon" 但非具体型号，其余不在白名单的默认淘汰）
_AMD_BLACKLIST = [
    "radeon graphics",  # Ryzen 7000 桌面核显（仅 2 CU RDNA2）
]

# 支持的 AMD 核显/独显关键词（白名单：完整列表，不在其中的一律不支持 DirectML）
_AMD_IGPU_SUPPORTED = [
    # ── Vega 7/8/10/11（Ryzen 2000/3000/4000/5000 APU 移动端, 7+ CU, 2019-2021）──
    "vega 7", "vega 8", "vega 10", "vega 11",
    # ── RDNA2 iGPU（Ryzen 6000 移动端, 2022）──
    "radeon 660m", "radeon 680m",
    # ── RDNA3 iGPU（Ryzen 7000 移动端, 2023）──
    "radeon 760m", "radeon 780m",
    # ── RDNA3.5 iGPU（Ryzen 8000/9000 移动端, 2024+）──
    "radeon 840m", "radeon 860m", "radeon 880m", "radeon 890m",
    # ── Ryzen AI Max 系列（RDNA 3.5, 高核心数, 2025+）──
    "radeon 8040s", "radeon 8050s", "radeon 8060s",
    # ── AMD Radeon RX 独显（支持 DirectML, Laptop/桌面版本同样适用）──
    "radeon rx", "radeon(tm) rx",
]


def check_nvidia_requirement(name, vram_gb):
    """检查 NVIDIA GPU 是否满足最低要求（RTX 20系+，6GB+）。

    自动识别 Laptop GPU 和桌面 GPU，在返回信息中标注。

    Returns:
        (meets: bool, reason: str)
    """
    name_lower = name.lower()
    is_laptop = "laptop" in name_lower or "notebook" in name_lower
    gpu_type = "Laptop GPU" if is_laptop else "桌面 GPU"

    # 解析 RTX 代数
    rtx_match = re.search(r'rtx\s*(\d{2})', name_lower)
    if rtx_match:
        era = int(rtx_match.group(1))
        if era < NVIDIA_MIN_ERA:
            return False, f"NVIDIA RTX {era}系（{gpu_type}）不满足最低要求（需RTX {NVIDIA_MIN_ERA}系及以上）"
    elif 'gtx' in name_lower:
        # GTX 系列（含 16xx）不满足 RTX 要求
        gtx_match = re.search(r'gtx\s*(\d{3,4})', name_lower)
        if gtx_match:
            model = int(gtx_match.group(1))
            return False, f"NVIDIA GTX {model}（{gpu_type}）不满足最低要求（需RTX {NVIDIA_MIN_ERA}系及以上）"
        return False, f"NVIDIA GTX 系列（{gpu_type}）不满足最低要求（需RTX {NVIDIA_MIN_ERA}系及以上）"
    elif 'quadro' in name_lower or 'tesla' in name_lower:
        # 专业卡/Tesla 通过 VRAM 判断
        pass
    else:
        # 无法识别的 NVIDIA GPU，通过 VRAM 判断
        pass

    # 检查显存（vram_gb=0 表示无法检测，跳过显存检查）
    if vram_gb > 0 and vram_gb < NVIDIA_MIN_VRAM_GB:
        return False, f"显存 {vram_gb}GB 不足（{gpu_type}，需 {NVIDIA_MIN_VRAM_GB}GB 以上）"

    return True, f"满足要求（{gpu_type}）"


def check_integrated_gpu_requirement(name, sys_ram_gb):
    """检查核显是否满足最低要求。

    核显判断标准：
      1. 不在黑名单中（旧型号直接拒绝）
      2. 在支持列表中（已知可用型号直接通过）
      3. Intel: Iris Xe (11代+) / UHD 770 (12代+) / Arc 及以上
      4. AMD: Vega 7+ / RDNA2+ iGPU (Radeon 660M+)
      5. 系统内存 >= 8GB（核显共享 RAM）

    Returns:
        (meets: bool, reason: str)
    """
    # 归一化：去除商标标记 (tm)/(r)/(c)，使 "Radeon(TM) 780M" 能匹配 "radeon 780m"
    name_norm = _norm_gpu_name(name)

    # 1. 检查黑名单（关键词也归一化，保证一致匹配）
    for bl in _INTEL_BLACKLIST:
        if _norm_gpu_name(bl) in name_norm:
            return False, f"Intel 核显型号过旧: {name}"
    for bl in _AMD_BLACKLIST:
        if _norm_gpu_name(bl) in name_norm:
            return False, f"AMD 核显型号过旧: {name}"

    # 2. 检查支持列表
    in_supported = False
    for kw in _INTEL_IGPU_SUPPORTED:
        if _norm_gpu_name(kw) in name_norm:
            in_supported = True
            break
    if not in_supported:
        for kw in _AMD_IGPU_SUPPORTED:
            if _norm_gpu_name(kw) in name_norm:
                in_supported = True
                break

    if not in_supported:
        # 不在支持列表也不在黑名单的未知核显，保守拒绝
        return False, f"未识别的核显型号，不满足最低要求: {name}"

    # 3. 检查系统内存
    if sys_ram_gb < IGPU_MIN_SYS_RAM_GB:
        return False, f"系统内存 {sys_ram_gb}GB 不足（核显需 {IGPU_MIN_SYS_RAM_GB}GB 以上）"

    return True, "满足要求"


def check_gpu_requirement(gpu_info, sys_ram_gb=0):
    """统一 GPU 最低要求检查。

    Args:
        gpu_info: detect_gpu_type() 返回的 dict
        sys_ram_gb: 系统内存（GB），核显检查需要

    Returns:
        (meets: bool, reason: str, backend: str)
        backend 为推荐后端，不满足时为 "cpu"
    """
    vendor = gpu_info.get("vendor", "none")
    name = gpu_info.get("name", "未检测到")
    vram_gb = gpu_info.get("vram_gb", 0)
    is_integrated = gpu_info.get("is_integrated", False)

    if vendor == "none":
        return False, "未检测到 GPU", "cpu"

    if vendor == "nvidia":
        meets, reason = check_nvidia_requirement(name, vram_gb)
        if meets:
            return True, reason, "cuda"
        return False, reason, "cpu"

    if is_integrated:
        meets, reason = check_integrated_gpu_requirement(name, sys_ram_gb)
        if meets:
            return True, reason, "directml"
        return False, reason, "cpu"

    # AMD/Intel 独显（如 Arc A380, Radeon RX 6400 等）允许通过
    return True, "满足要求（独立显卡）", "directml"
