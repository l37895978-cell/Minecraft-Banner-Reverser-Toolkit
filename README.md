# 我的世界旗帜逆向套件

针对 Minecraft Java 版 / 基岩版旗帜系统的图案识别与训练工具，支持从旗帜图片还原图案与颜色组合，并可训练自定义识别模型。

## 功能

- **旗帜识别**：从图片还原旗帜图案与颜色组合
- **模型训练**：训练 ViT / DeiT 识别模型，支持 CUDA / DirectML / CPU 三种架构
- **数据导入**：旗帜序列文件导入导出，随机旗帜生成与纠偏
- **一键安装**：安装器自动部署 Python 依赖与模型权重

## 环境要求

- Python 3.10.11 及以上（推荐 3.13）
- 训练模式需 NVIDIA 显卡（CUDA）或 DirectX 12（DirectML）

## 快速开始

使用安装器完成一键部署后，双击桌面快捷方式启动；或直接在源码目录运行：

```bash
python start.pyw
```

## 目录结构

| 路径 | 说明 |
| --- | --- |
| **根目录** | |
| `start.pyw` | 启动器（主入口，首次启动自动补全桌面/开始菜单快捷方式） |
| `bdor.pyw` | 旗帜识别器 |
| `trainer.pyw` | 模型训练器（含 Loss 图表） |
| `importer.pyw` | 旗帜数据导入器（随机生成与纠偏） |
| `patch_tool.pyw` | 补丁工具（应用补丁 / 制作补丁） |
| `test.pyw` | 安装完整性自检与稳定性测试 |
| `help.pyw` | 使用说明窗口 |
| `downloader.spec` | PyInstaller 打包配置（下载器） |
| `version_info.txt` | 版本号信息 |
| `build_tag.txt` | 构建身份标识 |
| `requirements.txt` | 依赖清单（按硬件选择 PyTorch 变体） |
| `LICENSE` | 开源许可（GPL-3.0） |
| **`installer/` 安装器** | |
| `installer/demo_installer.pyw` | 安装程序主界面 |
| `installer/real_installer.pyw` | 安装器真正入口（打包为目标 exe） |
| `installer/install.py` | 安装逻辑（注册表、快捷方式、图标） |
| `installer/setup_hardware.py` | GPU 检测与对应 PyTorch 变体安装 |
| `installer/visualcondition.pyw` | 环境模拟器（辅助工具） |
| **`utils/` 公共工具** | |
| `utils/banner_utils.py` | 旗帜颜色与图案常量、处理 |
| `utils/device_backend.py` | 计算后端抽象（cuda / directml / cpu） |
| `utils/mbtl_utils.py` | MBTL 文件读写 |
| `utils/mbtlx_utils.py` | MBTLX 文件读写 |
| `utils/settings_manager.py` | 配置管理 |
| `utils/settings_dialog.py` | 设置对话框 |
| **`scripts/` 子进程脚本** | |
| `scripts/dml_worker.py` | DirectML 训练子进程 |
| `scripts/reverser_dml_worker.py` | DirectML 推理子进程 |
| `scripts/error_reporter.pyw` | 独立报错程序 |
| `scripts/exit.pyw` | 退出确认 / 恢复提示 |
| **`models/` 模型** | |
| `models/structures/vit_model.py` | ViT / DeiT 模型结构与数据集 |
| **`images/` 素材** | |
| `images/banner/` | 安装器侧图 |
| `images/base_and_patterns/` | 旗帜底色与图案 |
| `images/icons/` | 各程序图标 |

## 版本

v0.5 beta1（版本号 1.0.8）

## License

GPL-3.0
