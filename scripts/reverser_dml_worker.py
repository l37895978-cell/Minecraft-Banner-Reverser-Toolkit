# -*- coding: utf-8 -*-
"""识别器 DirectML 推理子进程（由 dml_env python 3.10 运行）。

背景：识别器 UI 固定由主环境（3.13）渲染，但主环境没有 torch_directml
（DirectML 的 torch 全家桶安装在 dml_env 便携环境）。因此当用户选择
DirectML 架构时，识别器的推理委托给本子进程完成：
加载模型 → 图片预处理 → 前向 → 输出 banner_data（一行 JSON 到 stdout）。

用法（由 bdor.pyw 内部调用）:
    dml_env/python.exe scripts/reverser_dml_worker.py --image <图片路径> --model <模型路径>

输出（最后一行）:
    {"banner_data": [bg, p1_t, p1_c, ...]} 或 {"error": "..."}
"""
import os
import sys
import json
import argparse

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="输入旗帜图片路径")
    ap.add_argument("--model", required=True, help="模型 .pth 路径")
    args = ap.parse_args()
    result = {"banner_data": None}

    try:
        import torch
        import torch_directml
        from PIL import Image
        from models.structures.vit_model import ViT, get_transform

        if not torch_directml.is_available():
            result["error"] = "torch_directml 不可用（未检测到支持 DirectML 的设备）"
        else:
            device = torch_directml.device()

            checkpoint = torch.load(args.model, map_location="cpu", weights_only=False)
            if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
                arch = checkpoint.get("model_arch", "vit_b_16")
                model = ViT(model_arch=arch)
                state = checkpoint["model_state_dict"]
            else:
                # 旧格式：直接是 state_dict，使用默认架构
                model = ViT()
                state = checkpoint
            model.load_state_dict(state, strict=False)
            model.to(device)
            model.eval()

            img = Image.open(args.image).convert("RGB")
            tensor = get_transform(for_pil=True)(img).unsqueeze(0).to(device)

            with torch.no_grad():
                bg_pred, pattern_preds = model(tensor)

            bg_color_idx = int(torch.argmax(bg_pred, dim=1).item())
            num_slots = getattr(model, "num_pattern_slots", 16)
            patterns = []
            for i in range(num_slots):
                p_type_idx = int(torch.argmax(pattern_preds[2 * i], dim=1).item())
                p_color_idx = int(torch.argmax(pattern_preds[2 * i + 1], dim=1).item())
                if p_type_idx > 0:
                    patterns.append((p_type_idx, p_color_idx))

            banner = [bg_color_idx]
            for p_type, p_color in patterns:
                banner.extend([p_type, p_color])
            result["banner_data"] = banner
    except Exception as e:
        import traceback
        result["error"] = "%s\n%s" % (e, traceback.format_exc())

    # 单行 JSON 输出（UI 解析最后一行）
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
