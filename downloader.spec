# -*- mode: python ; coding: utf-8 -*-
# ============================================================
# 开发环境标记文件（请勿删除！）
# ------------------------------------------------------------
# 此文件兼具两个用途：
#   1. 开发环境标记——安装器通过 downloader.spec + installer/
#      + _inject_icon.py 三重特征判断当前是否为开发者运行
#      安装包。三缺一即判定为非开发者，演示模式入口会消失。
#   2. PyInstaller 打包配置——入口点为 installer/real_installer.pyw
#      打包命令：pyinstaller downloader.spec --distpath exe --workpath build --noconfirm
# ============================================================

block_cipher = None

import os


def _collect(src_dir, dest_dir, exts=('.py', '.pyw')):
    """递归收集 src_dir 下指定扩展名的文件，跳过 __pycache__ 缓存目录。"""
    items = []
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            if f.endswith(exts):
                full = os.path.join(root, f)
                rel = os.path.relpath(root, src_dir)
                dst = dest_dir if rel == '.' else os.path.join(dest_dir, rel)
                items.append((full, dst))
    return items


# 只打包 models/structures/ 下的 .py 文件（权重 .pth 需联网下载，不打包）
_structures_py = _collect('models/structures', 'models/structures')

# 不打包 config 目录：软件首次启动时由 settings_manager._default_settings() 自动生成
# 避免开发环境的配置值带到用户机器

a = Analysis(
    ['installer/real_installer.pyw'],
    pathex=[],
    binaries=[],
    datas=[
        ('start.pyw', '.'),
        ('trainer.pyw', '.'),
        ('importer.pyw', '.'),
        ('bdor.pyw', '.'),
        ('help.pyw', '.'),
        ('test.pyw', '.'),
        ('patch_tool.pyw', '.'),
        *_collect('utils', 'utils'),
        *_collect('scripts', 'scripts'),
        ('models/__init__.py', 'models'),
        *_structures_py,
        ('images', 'images'),
        ('log/.gitkeep', 'log'),
        ('LICENSE', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='旗帜逆向套件下载器',
    debug=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon='images/icons/downloader.ico',
    version='version_info.txt',
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
