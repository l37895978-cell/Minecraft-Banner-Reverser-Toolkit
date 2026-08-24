import os
import torch
import torch.nn as nn
import torchvision.transforms as transforms
from torch.utils.data import Dataset, DataLoader
import numpy as np

def _sp(msg):
    try:
        print(msg)
    except Exception:
        pass

# ===== 统一图像预处理参数 =====
_IMAGE_SIZE = 224
_NORM_MEAN = [0.485, 0.456, 0.406]
_NORM_STD = [0.229, 0.224, 0.225]


def get_transform(for_pil=False):
    """返回统一的图像预处理 Transform。

    for_pil=False: 输入为 tensor (C,H,W), [0,1] 范围（训练用）
    for_pil=True:  输入为 PIL Image（推理用）
    """
    if for_pil:
        return transforms.Compose([
            transforms.Resize((_IMAGE_SIZE, _IMAGE_SIZE)),
            transforms.ToTensor(),
            transforms.Normalize(mean=_NORM_MEAN, std=_NORM_STD)
        ])
    else:
        return transforms.Compose([
            transforms.Resize((_IMAGE_SIZE, _IMAGE_SIZE)),
            transforms.Normalize(mean=_NORM_MEAN, std=_NORM_STD)
        ])


class BannerDataset(Dataset):
    def __init__(self, banners, transform=None):
        self.banners = banners
        self.transform = transform if transform is not None else get_transform(for_pil=False)

        self._labels = []
        for banner_data in banners:
            label = torch.zeros(1 + 16*2, dtype=torch.long)
            label[0] = banner_data[0]
            for i in range(1, len(banner_data), 2):
                if i + 1 < len(banner_data) and (i-1)//2 < 16:
                    pattern_idx = (i-1)//2
                    label[1 + pattern_idx*2] = banner_data[i]
                    label[2 + pattern_idx*2] = banner_data[i+1]
            self._labels.append(label)

    def __len__(self):
        return len(self.banners)

    def __getitem__(self, idx):
        from utils.banner_utils import generate_banner_image
        banner_data = self.banners[idx]
        image = generate_banner_image(banner_data, size=(200, 400))
        image_rgb = image[:, :, ::-1].copy()
        tensor = torch.tensor(image_rgb, dtype=torch.float32).permute(2, 0, 1) / 255.0
        if self.transform:
            tensor = self.transform(tensor)
        return tensor, self._labels[idx]


class ScreenshotDataset(Dataset):
    """截图训练数据集（Tab2）：从用户截图文件加载图像，标签来自 .mbtlx 标记。

    与 BannerDataset 共享标签构造逻辑，区别仅在于图像来源：
      - BannerDataset: 通过 generate_banner_image 实时渲染（合成数据）
      - ScreenshotDataset: 直接读取用户的截图文件（真实数据）

    训练目标相同：输入图像 → 输出 banner_data（背景色 + 16层图案类型/颜色）。
    """

    def __init__(self, img_paths, banners, transform=None):
        assert len(img_paths) == len(banners), "img_paths 与 banners 数量不一致"
        self.img_paths = img_paths
        self.banners = banners
        self.transform = transform if transform is not None else get_transform(for_pil=False)

        self._labels = []
        for banner_data in banners:
            label = torch.zeros(1 + 16*2, dtype=torch.long)
            label[0] = banner_data[0]
            for i in range(1, len(banner_data), 2):
                if i + 1 < len(banner_data) and (i-1)//2 < 16:
                    pattern_idx = (i-1)//2
                    label[1 + pattern_idx*2] = banner_data[i]
                    label[2 + pattern_idx*2] = banner_data[i+1]
            self._labels.append(label)

    def __len__(self):
        return len(self.img_paths)

    def __getitem__(self, idx):
        from PIL import Image
        img_path = self.img_paths[idx]
        img = Image.open(img_path).convert('RGB')
        tensor = transforms.functional.to_tensor(img)
        if self.transform:
            tensor = self.transform(tensor)
        return tensor, self._labels[idx]


class ViT(nn.Module):
    """视觉Transformer模型，支持多种ViT架构和DeiT轻量化变体。

    DeiT（Data-efficient Image Transformer）使用 torchvision 的 VisionTransformer 类自定义配置实现，
    每个架构必须有独立的权重文件，不混用。
    """

    # 架构配置表
    # type="torchvision": 从 torchvision 加载，需指定 model/weights
    # type="custom": 用 VisionTransformer 自定义构建，需指定 layers/heads/hidden_dim/mlp_dim
    _ARCH_CONFIG = {
        # ── 标准 ViT（torchvision 预训练） ──
        "vit_b_16":  {"type": "torchvision", "model": "vit_b_16",  "weights": "ViT_B_16_Weights",  "hidden_dim": 768,  "is_deit": False},
        "vit_l_16":  {"type": "torchvision", "model": "vit_l_16",  "weights": "ViT_L_16_Weights",  "hidden_dim": 1024, "is_deit": False},
        "vit_b_32":  {"type": "torchvision", "model": "vit_b_32",  "weights": "ViT_B_32_Weights",  "hidden_dim": 768,  "is_deit": False},
        "vit_l_32":  {"type": "torchvision", "model": "vit_l_32",  "weights": "ViT_L_32_Weights",  "hidden_dim": 1024, "is_deit": False},
        "vit_h_14":  {"type": "torchvision", "model": "vit_h_14",  "weights": "ViT_H_14_Weights",  "hidden_dim": 1280, "is_deit": False},
        # ── DeiT 轻量化变体（自定义配置，需独立权重文件） ──
        "deit_b_16": {"type": "custom", "layers": 12, "heads": 12, "hidden_dim": 768,  "mlp_dim": 3072, "is_deit": True},
        # DeiT-S/16: 轻量版，从头训练
        "deit_s_16": {"type": "custom", "layers": 12, "heads": 6,  "hidden_dim": 384,  "mlp_dim": 1536, "is_deit": True},
        # DeiT-T/16: 极轻量版，从头训练
        "deit_t_16": {"type": "custom", "layers": 12, "heads": 3,  "hidden_dim": 192,  "mlp_dim": 768,  "is_deit": True},
    }

    def __init__(self, num_classes=17, num_patterns=43, num_pattern_slots=16, model_arch="vit_b_16", dropout=0.2):
        super(ViT, self).__init__()
        arch = model_arch if model_arch in self._ARCH_CONFIG else "vit_b_16"
        cfg = self._ARCH_CONFIG[arch]
        hidden_dim = cfg["hidden_dim"]
        is_deit = cfg["is_deit"]

        if cfg["type"] == "torchvision":
            # 从 torchvision 加载预训练模型（优先本地 .pth，离线可用）
            import torchvision.models as tvm
            model_fn = getattr(tvm, cfg["model"])
            weights_cls = getattr(tvm, cfg["weights"])
            _local_pth = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{arch}.pth")
            if os.path.exists(_local_pth) and os.path.getsize(_local_pth) > 1024:
                self.vit = model_fn(weights=None)
                _state = torch.load(_local_pth, map_location='cpu')
                _missing, _unexpected = self.vit.load_state_dict(_state, strict=False)
                if _missing or _unexpected:
                    _sp(f"[{arch}] 权重加载: 缺失 {len(_missing)} 层, 多余 {len(_unexpected)} 层")
            else:
                self.vit = model_fn(weights=weights_cls.DEFAULT)
            # 移除分类头，保留特征提取
            self.vit.heads = nn.Identity()
        else:
            # 用 VisionTransformer 自定义构建 DeiT
            from torchvision.models.vision_transformer import VisionTransformer
            self.vit = VisionTransformer(
                image_size=224,
                patch_size=16,
                num_layers=cfg["layers"],
                num_heads=cfg["heads"],
                hidden_dim=hidden_dim,
                mlp_dim=cfg["mlp_dim"],
                num_classes=1000,  # 临时分类头，之后移除
            )
            # 移除分类头，保留特征提取
            self.vit.heads = nn.Identity()
            # 尝试加载预训练权重
            # 优先：自己的 .pth（DeiT 官方权重，已转换为 torchvision 格式）
            _local_pth = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{arch}.pth")
            if os.path.exists(_local_pth) and os.path.getsize(_local_pth) > 1024:
                try:
                    _state = torch.load(_local_pth, map_location='cpu')
                    own = self.vit.state_dict()
                    loaded = 0
                    for k, v in _state.items():
                        if k in own and own[k].shape == v.shape:
                            own[k].copy_(v)
                            loaded += 1
                    self.vit.load_state_dict(own)
                    _sp(f"[{arch}] 加载了 {loaded}/{len(own)} 层预训练权重")
                except Exception as e:
                    _sp(f"[{arch}] 权重加载失败: {e}，将从头训练")

        self.model_arch = arch
        self.is_deit = is_deit
        self.hidden_dim = hidden_dim
        self.num_pattern_slots = num_pattern_slots

        # 背景颜色分类器
        self.bg_classifier = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, num_classes)
        )

        # 图案分类器（每个图案包括类型和颜色）
        self.pattern_classifiers = nn.ModuleList()
        for _ in range(num_pattern_slots):
            # 图案类型分类器
            pattern_type_classifier = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim // 2),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim // 2, num_patterns)
            )
            # 图案颜色分类器
            pattern_color_classifier = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim // 2),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim // 2, num_classes)
            )
            self.pattern_classifiers.append(nn.ModuleList([pattern_type_classifier, pattern_color_classifier]))

    def _load_pretrained_weights(self, src_arch):
        """从 torchvision 预训练模型加载兼容权重到自定义 DeiT。"""
        try:
            import torchvision.models as tvm
            src_cfg = self._ARCH_CONFIG.get(src_arch)
            if not src_cfg or src_cfg.get("type") != "torchvision":
                return
            model_fn = getattr(tvm, src_cfg["model"])
            weights_cls = getattr(tvm, src_cfg["weights"])
            # 优先从本地 .pth 加载（离线可用，避免重复下载）
            _local_pth = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{src_arch}.pth")
            if os.path.exists(_local_pth) and os.path.getsize(_local_pth) > 1024:
                src_state = torch.load(_local_pth, map_location='cpu')
            else:
                src_model = model_fn(weights=weights_cls.DEFAULT)
                src_state = src_model.state_dict()
                del src_model
            # 只加载形状匹配的参数（跳过分类头）
            own_state = self.vit.state_dict()
            loaded = 0
            for k, v in src_state.items():
                if k in own_state and own_state[k].shape == v.shape:
                    own_state[k].copy_(v)
                    loaded += 1
            _sp(f"[DeiT] 从 {src_arch} 加载了 {loaded}/{len(own_state)} 层预训练权重")
        except Exception as e:
            _sp(f"[DeiT] 预训练权重加载失败: {e}，将从头训练")

    def forward(self, x):
        # 特征提取
        features = self.vit(x)
        # 某些 VisionTransformer 配置可能返回 tuple，取 class token 特征
        if isinstance(features, tuple):
            features = features[0]

        # 预测背景颜色
        bg_pred = self.bg_classifier(features)

        # 预测图案
        pattern_preds = []
        for i, (type_clf, color_clf) in enumerate(self.pattern_classifiers):
            type_pred = type_clf(features)
            color_pred = color_clf(features)
            pattern_preds.extend([type_pred, color_pred])

        return bg_pred, pattern_preds

class BannerTrainer:
    def __init__(self, model, device=None):
        if device is None:
            from utils.device_backend import get_device
            device = get_device()
        self.model = model
        self.device = device
        self.model.to(self.device)

        self.criterion = nn.CrossEntropyLoss()

        self.optimizer = torch.optim.AdamW(self.model.parameters(), lr=1e-4, weight_decay=0.01)

        self.scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(self.optimizer, T_0=50, T_mult=2, eta_min=1e-6)

    def freeze_backbone(self):
        for param in self.model.vit.parameters():
            param.requires_grad = False

    def unfreeze_backbone(self, num_layers=4):
        for param in self.model.vit.parameters():
            param.requires_grad = True
        if num_layers > 0:
            encoder_blocks = list(self.model.vit.encoder.layers)
            for block in encoder_blocks[:-num_layers]:
                for param in block.parameters():
                    param.requires_grad = False

    def train(self, dataloader, epochs, val_dataloader=None, patience=5, max_gpu_temp=80, batch_callback=None, banner_callback=None, grad_accum=1):
        self.model.train()
        self.epoch_loss_history = []

        from utils.device_backend import supports_mixed_precision, empty_cache_for_backend
        use_amp = supports_mixed_precision(str(self.device))
        scaler = torch.amp.GradScaler('cuda') if use_amp else None

        best_val_loss = float('inf')
        early_stop_counter = 0
        num_batches = len(dataloader)

        # 动态清理频率：数据量越大清理间隔越长（清理本身有开销）
        # 小数据(<50 batch): 每 5 batch — 内存压力小但频繁清理无害
        # 中数据(50-500): 每 20 batch
        # 大数据(>500): 每 50 batch — 避免频繁 del 影响吞吐
        if num_batches <= 50:
            cache_interval = max(5, num_batches // 5)
        elif num_batches <= 500:
            cache_interval = 20
        else:
            cache_interval = 50

        freeze_epochs = max(epochs // 3, 1)
        # DirectML（torch_directml）autograd 对"requires_grad 从 False 变 True 的解冻参数"
        # 首次 backward 会进程级崩溃（RuntimeError 空消息）。DirectML 设备全程不冻结，
        # 规避解冻 backward；CUDA/CPU 保持原冻结-解冻迁移学习流程。
        from utils.device_backend import get_compute_backend
        _skip_freeze = (get_compute_backend() == "directml")
        if _skip_freeze:
            freeze_epochs = -1  # 永不触发 unfreeze（全程可训练）
        else:
            self.freeze_backbone()
        if batch_callback:
            batch_callback(-1, epochs, 0, 1, 0.0)

        total_banners = len(dataloader.dataset)
        for epoch in range(epochs):
            if epoch == freeze_epochs:
                self.unfreeze_backbone(num_layers=4)
                for g in self.optimizer.param_groups:
                    g['lr'] = 1e-5

            running_loss = 0.0
            banner_idx = 0
            self.optimizer.zero_grad()

            for batch_idx, (images, labels) in enumerate(dataloader):
                from utils.device_backend import supports_gpu_temp_monitoring
                if supports_gpu_temp_monitoring(str(self.device)):
                    try:
                        import pynvml
                        pynvml.nvmlInit()
                        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                        if temp > max_gpu_temp:
                            _sp(f"GPU温度过高: {temp}°C，停止训练")
                            return
                    except Exception:
                        pass

                images = images.to(self.device)
                labels = labels.to(self.device)

                if scaler:
                    with torch.amp.autocast('cuda'):
                        bg_pred, pattern_preds = self.model(images)
                        loss = self.criterion(bg_pred, labels[:, 0])
                        for i in range(self.model.num_pattern_slots):
                            if 1 + i*2 < labels.shape[1]:
                                loss += self.criterion(pattern_preds[2*i], labels[:, 1 + i*2])
                                loss += self.criterion(pattern_preds[2*i+1], labels[:, 2 + i*2])
                else:
                    bg_pred, pattern_preds = self.model(images)
                    loss = self.criterion(bg_pred, labels[:, 0])
                    for i in range(self.model.num_pattern_slots):
                        if 1 + i*2 < labels.shape[1]:
                            loss += self.criterion(pattern_preds[2*i], labels[:, 1 + i*2])
                            loss += self.criterion(pattern_preds[2*i+1], labels[:, 2 + i*2])

                # 梯度累积：缩放 loss 后反向传播，每 grad_accum 步更新一次参数
                # 效果等效于 batch_size * grad_accum，但显存仅占 batch_size 水平
                scaled_loss = loss / grad_accum
                if scaler:
                    scaler.scale(scaled_loss).backward()
                else:
                    scaled_loss.backward()

                is_accum_step = ((batch_idx + 1) % grad_accum == 0) or (batch_idx == num_batches - 1)
                if is_accum_step:
                    if scaler:
                        scaler.step(self.optimizer)
                        scaler.update()
                    else:
                        self.optimizer.step()
                    self.optimizer.zero_grad()

                running_loss += loss.item()

                if batch_callback:
                    batch_callback(epoch, epochs, batch_idx, num_batches, loss.item())

                if banner_callback:
                    batch_size = images.size(0)
                    for b in range(batch_size):
                        banner_callback(banner_idx + b, total_banners, epoch, epochs, loss.item())
                    banner_idx += batch_size

                # 定期清理显存（频率根据数据量动态调整）
                if (batch_idx + 1) % cache_interval == 0:
                    try:
                        del loss, scaled_loss, bg_pred, pattern_preds
                    except (NameError, UnboundLocalError):
                        pass
                    empty_cache_for_backend()

            # 每个 epoch 结束后深度清理（防止跨 epoch 碎片累积）
            empty_cache_for_backend()
            self.scheduler.step()

            epoch_loss = running_loss / num_batches
            self.epoch_loss_history.append(epoch_loss)
            phase = "冻结" if epoch < freeze_epochs else "微调"
            _sp(f"Epoch {epoch+1}/{epochs} [{phase}], Loss: {epoch_loss:.4f}, LR: {self.optimizer.param_groups[0]['lr']:.6f}")

            if val_dataloader:
                val_loss = self.evaluate_loss(val_dataloader)
                _sp(f"Validation Loss: {val_loss:.4f}")

                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    early_stop_counter = 0
                else:
                    early_stop_counter += 1
                    if early_stop_counter >= patience:
                        _sp(f"Early stopping at epoch {epoch+1}")
                        break
    
    def evaluate_loss(self, dataloader):
        self.model.eval()
        total_loss = 0.0
        
        with torch.no_grad():
            for images, labels in dataloader:
                images = images.to(self.device)
                labels = labels.to(self.device)
                
                bg_pred, pattern_preds = self.model(images)
                
                # 计算损失
                loss = self.criterion(bg_pred, labels[:, 0])
                
                # 计算图案损失
                for i in range(self.model.num_pattern_slots):
                    if 1 + i*2 < labels.shape[1]:
                        loss += self.criterion(pattern_preds[2*i], labels[:, 1 + i*2])
                        loss += self.criterion(pattern_preds[2*i+1], labels[:, 2 + i*2])
                
                total_loss += loss.item()
        
        return total_loss / len(dataloader)
    
    def evaluate(self, dataloader):
        self.model.eval()
        correct = 0
        total = 0
        
        with torch.no_grad():
            for images, labels in dataloader:
                images = images.to(self.device)
                labels = labels.to(self.device)
                
                bg_pred, pattern_preds = self.model(images)
                
                # 背景颜色准确率
                bg_pred = torch.argmax(bg_pred, dim=1)
                correct += (bg_pred == labels[:, 0]).sum().item()
                total += labels.size(0)
                
                # 图案准确率
                for i in range(self.model.num_pattern_slots):
                    if 1 + i*2 < labels.shape[1]:
                        pattern_type_pred = torch.argmax(pattern_preds[2*i], dim=1)
                        pattern_color_pred = torch.argmax(pattern_preds[2*i+1], dim=1)
                        correct += (pattern_type_pred == labels[:, 1 + i*2]).sum().item()
                        correct += (pattern_color_pred == labels[:, 2 + i*2]).sum().item()
                        total += 2 * labels.size(0)
        
        accuracy = correct / total
        _sp(f"Accuracy: {accuracy:.4f}")
        return accuracy
    
    def save_model(self, path):
        # 保存模型状态（含架构信息，防止加载时用错架构）
        checkpoint = {
            'model_state_dict': self.model.state_dict(),
            'model_arch': self.model.model_arch,
            'num_pattern_slots': self.model.num_pattern_slots,
            'optimizer_state_dict': self.optimizer.state_dict(),
            'scheduler_state_dict': self.scheduler.state_dict()
        }
        torch.save(checkpoint, path)
        _sp(f"Model saved to {path}")

    def load_model(self, path):
        """加载模型状态，兼容新旧两种格式。

        新格式：{"model_state_dict": ..., "model_arch": ..., ...}
        旧格式：直接是 state_dict（如仅有模型权重的 .pth 文件）

        当 pattern_classifiers 数量不匹配时（如旧模型 8 个 vs 当前 16 个），
        使用 strict=False 加载匹配的部分，不匹配的层保持随机初始化。
        """
        checkpoint = torch.load(path, map_location=self.device)

        # 兼容旧格式：直接是 state_dict（OrderedDict）
        if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint:
            state = checkpoint['model_state_dict']
        else:
            state = checkpoint

        # strict=False 允许 pattern_classifiers 数量不匹配
        missing, unexpected = self.model.load_state_dict(state, strict=False)
        if missing:
            _sp(f"[load_model] 缺失键（随机初始化）: {len(missing)} 个")
            pat_missing = [k for k in missing if 'pattern_classifiers' in k]
            if pat_missing:
                _sp(f"  其中 pattern_classifiers: {len(pat_missing)} 个"
                    f"（旧模型图层少于当前模型）")
        if unexpected:
            _sp(f"[load_model] 多余键（已忽略）: {len(unexpected)} 个")

        # 加载优化器/调度器状态（仅新格式）
        if isinstance(checkpoint, dict):
            if 'optimizer_state_dict' in checkpoint:
                try:
                    self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
                except Exception as e:
                    _sp(f"[load_model] 优化器状态加载失败: {e}")
            if 'scheduler_state_dict' in checkpoint:
                try:
                    self.scheduler.load_state_dict(checkpoint['scheduler_state_dict'])
                except Exception as e:
                    _sp(f"[load_model] 调度器状态加载失败: {e}")

        _sp(f"Model loaded from {path}")
    
    def predict(self, image):
        self.model.eval()

        # 统一使用 get_transform 确保训练/推理预处理一致
        transform = get_transform(for_pil=False)
        
        with torch.no_grad():
            # 应用变换
            image = transform(image)
            image = image.to(self.device)
            bg_pred, pattern_preds = self.model(image)
            
            # 预测背景颜色
            bg_color = torch.argmax(bg_pred, dim=1).item()
            
            # 预测图案
            patterns = []
            for i in range(self.model.num_pattern_slots):
                pattern_type = torch.argmax(pattern_preds[2*i], dim=1).item()
                pattern_color = torch.argmax(pattern_preds[2*i+1], dim=1).item()
                if pattern_type > 0:  # 跳过"no"图案
                    patterns.extend([pattern_type, pattern_color])
            
            return [bg_color] + patterns