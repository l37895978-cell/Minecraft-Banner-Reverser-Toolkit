"""DirectML 训练子进程入口。

在 dml_env (Python 3.10 embeddable) 中运行，接收主进程通过命令行参数和临时
文件传递的训练配置与旗帜数据，执行训练循环，通过 stdout 以 JSON 行协议回传进度。

调用示例：
    dml_env\\python.exe -E scripts\\dml_worker.py --banners-file tmp.json --epochs 50 ...

stdout JSON 协议（每行一个 JSON）：
    {"type": "info", "python": "3.10.11", "torch": "2.4.1+cpu"}
    {"type": "progress", "value": 5, "detail": "正在加载模型..."}
    {"type": "banner", "banner_idx": 0, "total_banners": 100, "epoch": 0,
     "epochs": 50, "within": 0.01, "loss": 2.3, "progress": 20,
     "detail": "Epoch 1/50 - 旗帜 1/100 | Loss: 2.3000"}
    {"type": "complete", "save_path": "...", "epoch_losses": [...]}
    {"type": "error", "message": "...", "traceback": "..."}
"""
import sys
import os
import json
import argparse
import traceback

# 添加项目根目录到 sys.path（dml_env 默认不包含项目路径）
# 本脚本位于 scripts/，需上溯一级到项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import torch
import torch_directml
import warnings
from torch.utils.data import DataLoader

# 屏蔽 DirectML 算子回退 CPU 的重复 warning（下方输出一次性友好提示）
warnings.filterwarnings("ignore", message=".*not currently supported on the DML backend.*")
from models.structures.vit_model import ViT, BannerTrainer, BannerDataset


def _emit(data):
    """输出一行 JSON 到 stdout 并立即刷新。
    用 ensure_ascii=True 把 Unicode 字符（如 ├──）转义为 \\uXXXX，
    避免 dml_env 的 stdout 用系统编码（GBK）输出时丢失字符。
    主进程 json.loads 会正确还原。
    """
    print(json.dumps(data, ensure_ascii=True), flush=True)


def _format_model_tree(model):
    """生成模型结构树字符串。

    与 trainer.pyw 的 _print_model_tree 输出格式保持一致，
    让 DirectML 模式也能在 trainer_stdout.log 中看到完整的模型结构树。
    """
    lines = []

    def _recurse(module, prefix="", is_root=True):
        if is_root:
            name = module.__class__.__name__
            params = sum(p.numel() for p in module.parameters())
            lines.append(f"{name} ({params:,} params)")
            prefix = ""
        children = list(module.named_children())
        for i, (child_name, child_module) in enumerate(children):
            last = (i == len(children) - 1)
            connector = "└── " if last else "├── "
            child_prefix = "    " if last else "│   "
            params = sum(p.numel() for p in child_module.parameters())
            cls = child_module.__class__.__name__
            detail = ""
            if hasattr(child_module, 'in_features') and hasattr(child_module, 'out_features'):
                detail = f" [{child_module.in_features}→{child_module.out_features}]"
            elif hasattr(child_module, 'kernel_size'):
                detail = f" [kernel={child_module.kernel_size}]"
            elif hasattr(child_module, 'p'):
                detail = f" [p={child_module.p}]"
            sub_children = list(child_module.named_children())
            if sub_children:
                lines.append(f"{prefix}{connector}{child_name}: {cls} ({params:,} params)")
                _recurse(child_module, prefix + child_prefix, is_root=False)
            else:
                lines.append(f"{prefix}{connector}{child_name}: {cls}{detail} ({params:,} params)")

    _recurse(model)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="DirectML 训练子进程")
    parser.add_argument("--banners-file", default=None, help="banners JSON 临时文件路径（--tree-only 模式可省略）")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--arch", default="vit_b_16")
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--train-mode", default="normal", help="normal / peft")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--grad-accum", type=int, default=1, help="梯度累积步数")
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--save-path", default=None, help="模型保存路径（--tree-only 模式可省略）")
    parser.add_argument("--continue-path", default=None, help="继续训练的模型路径")
    parser.add_argument("--train-round", type=int, default=1, help="训练轮次（初始训练=1，继续训练从 .pth 读取后 +1）")
    parser.add_argument("--tree-only", action="store_true", help="仅构建模型并输出结构树后退出（不训练）")
    args = parser.parse_args()

    # --tree-only 模式：训练器启动时为显示模型树而调用，构建模型即退出，不执行训练
    if args.tree_only:
        _emit({"type": "info",
               "python": "%d.%d.%d" % sys.version_info[:3],
               "torch": torch.__version__,
               "torch_directml": getattr(torch_directml, "__version__", "unknown")})
        model = ViT(model_arch=args.arch, dropout=args.dropout)
        total_params = sum(p.numel() for p in model.parameters())
        trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
        _arch_display = {
            "vit_b_16": "ViT-B/16", "vit_l_16": "ViT-L/16",
            "vit_b_32": "ViT-B/32", "vit_l_32": "ViT-L/32",
            "vit_h_14": "ViT-H/14",
            "deit_b_16": "DeiT-B/16", "deit_s_16": "DeiT-S/16",
            "deit_t_16": "DeiT-T/16",
        }
        _emit({"type": "model_info",
               "arch_display": _arch_display.get(args.arch, args.arch),
               "arch": args.arch,
               "total_params": total_params,
               "trainable_params": trainable_params})
        try:
            _emit({"type": "model_tree", "tree": _format_model_tree(model)})
        except Exception:
            pass
        _emit({"type": "complete", "save_path": "", "epoch_losses": [], "train_round": 1})
        return

    # 非 --tree-only 模式必须提供 banners-file 和 save-path
    if not args.banners_file or not args.save_path:
        _emit({"type": "error",
               "message": "缺少必需参数 --banners-file 或 --save-path",
               "traceback": ""})
        return

    # 标识（主进程显示用）
    _emit({
        "type": "info",
        "python": "%d.%d.%d" % sys.version_info[:3],
        "torch": torch.__version__,
        "torch_directml": getattr(torch_directml, "__version__", "unknown"),
    })
    _emit({"type": "progress", "value": 3,
           "detail": "提示: 部分算子不支持 DirectML，将回退 CPU 执行（正常现象，不影响训练正确性）"})

    # PEFT 模式需要 peft 库，dml_env 未安装
    if args.train_mode == "peft":
        _emit({"type": "error",
               "message": "DirectML 模式暂不支持 PEFT 微调，请在设置中切换为普通训练模式",
               "traceback": ""})
        return

    # 读 banners
    with open(args.banners_file, "r", encoding="utf-8-sig") as f:
        banners = json.load(f)
    _emit({"type": "progress", "value": 5, "detail": "正在加载模型..."})

    # 设备
    device_count = torch_directml.device_count()
    if device_count == 0:
        _emit({"type": "error", "message": "未检测到 DirectML 设备", "traceback": ""})
        return
    if args.device_index >= device_count:
        _emit({"type": "error",
               "message": "设备索引 %d 超出范围（共 %d 个设备）" % (args.device_index, device_count),
               "traceback": ""})
        return
    device = torch_directml.device(args.device_index)
    try:
        device_name = torch_directml.device_name(args.device_index)
    except Exception:
        device_name = str(device)

    # 模型
    model = ViT(model_arch=args.arch, dropout=args.dropout)

    # 返回模型信息给主进程（参数量 + 架构名），让用户看到 DML 子环境已成功转接
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    _arch_display = {
        "vit_b_16": "ViT-B/16", "vit_l_16": "ViT-L/16",
        "vit_b_32": "ViT-B/32", "vit_l_32": "ViT-L/32",
        "vit_h_14": "ViT-H/14",
        "deit_b_16": "DeiT-B/16", "deit_s_16": "DeiT-S/16",
        "deit_t_16": "DeiT-T/16",
    }
    _emit({"type": "model_info",
           "arch_display": _arch_display.get(args.arch, args.arch),
           "arch": args.arch,
           "total_params": total_params,
           "trainable_params": trainable_params,
           "detail": "DML 子环境就绪 · %s · %s 万参数" % (
               _arch_display.get(args.arch, args.arch),
               total_params // 10000)})

    # 回传模型结构树给主进程，主进程 print 到 trainer_stdout.log
    # （与 CUDA/CPU 模式 _print_model_tree 行为一致，让 DirectML 也能看到模型树）
    try:
        _emit({"type": "model_tree", "tree": _format_model_tree(model)})
    except Exception:
        pass

    # 训练轮次：优先用命令行传入的（主进程已从 .pth 读取并 +1），
    # 兜底从 continue_path 读取 saved_count + 1
    train_round = args.train_round
    if args.continue_path and os.path.exists(args.continue_path):
        ckpt = torch.load(args.continue_path, map_location="cpu", weights_only=False)
        _state = ckpt["model_state"] if "model_state" in ckpt else ckpt
        _missing, _unexpected = model.load_state_dict(_state, strict=False)
        if _missing or _unexpected:
            _emit({"type": "log", "detail": "权重加载: 缺失 %d 层, 多余 %d 层" % (len(_missing), len(_unexpected))})
        # 如果主进程未传 train_round（默认1），从 .pth 读取
        if train_round <= 1 and isinstance(ckpt, dict):
            saved_count = ckpt.get("train_count", 0)
            train_round = saved_count + 1
        _emit({"type": "progress", "value": 10,
               "detail": "已加载继续训练模型: %s（第%d轮）" % (os.path.basename(args.continue_path), train_round)})

    trainer = BannerTrainer(model, device=device)
    trainer.optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    # 数据
    dataset = BannerDataset(banners)
    dataloader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True)
    _emit({"type": "progress", "value": 15,
           "detail": "数据准备完成: %d 个旗帜 | 设备: %s" % (len(banners), device_name)})

    # 训练回调（通过 stdout JSON 回传进度）
    def on_banner(banner_idx, total_banners, epoch, epochs, loss):
        within = (banner_idx + 1) / total_banners if total_banners > 0 else 1.0
        total_progress = int(15 + ((epoch + within) / epochs) * 80)
        _emit({
            "type": "banner",
            "banner_idx": banner_idx,
            "total_banners": total_banners,
            "epoch": epoch,
            "epochs": epochs,
            "within": within,
            "loss": loss,
            "progress": min(total_progress, 90),
            "detail": "Epoch %d/%d - 旗帜 %d/%d | Loss: %.4f" % (
                epoch + 1, epochs, banner_idx + 1, total_banners, loss),
        })

    # 训练
    trainer.train(dataloader, args.epochs, banner_callback=on_banner, grad_accum=max(1, args.grad_accum))

    # 保存模型
    save_dir = os.path.dirname(args.save_path)
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
    torch.save({
        "model_state_dict": model.state_dict(),
        "model_arch": args.arch,
        "train_count": train_round,  # 写入训练轮次，供下次继续训练识别
    }, args.save_path)
    epoch_losses = list(trainer.epoch_loss_history) if hasattr(trainer, "epoch_loss_history") else []
    _emit({"type": "complete", "save_path": args.save_path, "epoch_losses": epoch_losses,
           "train_round": train_round})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _emit({"type": "error", "message": str(e), "traceback": traceback.format_exc()})
        sys.exit(1)
