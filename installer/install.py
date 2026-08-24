import os
import sys
import ctypes
import winreg


# 项目根目录（本文件位于 installer/ 子目录）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_ico():
    ico_path = os.path.join(_PROJECT_ROOT, "images", "icons", "mbtl.ico")
    if os.path.exists(ico_path):
        return ico_path
    print(f"[错误] 找不到图标文件: {ico_path}")
    return None


def _register_filetype(ext, type_name, description, ico_path):
    """注册一种文件类型到 Windows 注册表。

    Args:
        ext: 扩展名（含点，如 ".mbtl"）
        type_name: ProgID（如 "BannerTrainer.MBTL"）
        description: 文件类型描述
        ico_path: 图标文件路径
    Returns: True/False
    """
    importer_path = os.path.join(_PROJECT_ROOT, "importer.pyw")
    python_exe = sys.executable

    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{ext}")
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, type_name)
        winreg.CloseKey(key)
    except OSError as e:
        print(f"[错误] 注册{ext}扩展名失败: {e}")
        return False

    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{type_name}")
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, description)
        winreg.CloseKey(key)
    except OSError as e:
        print(f"[错误] 注册{type_name}失败: {e}")
        return False

    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{type_name}\DefaultIcon")
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, ico_path)
        winreg.CloseKey(key)
    except OSError as e:
        print(f"[错误] 注册DefaultIcon失败: {e}")
        return False

    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{type_name}\shell\open\command")
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{python_exe}" "{importer_path}" --open-file "%1"')
        winreg.CloseKey(key)
    except OSError as e:
        print(f"[错误] 注册打开命令失败: {e}")
        return False

    return True


def _unregister_filetype(ext, type_name):
    """卸载一种文件类型的注册。"""
    keys_to_delete = [
        rf"Software\Classes\{type_name}\shell\open\command",
        rf"Software\Classes\{type_name}\shell\open",
        rf"Software\Classes\{type_name}\shell",
        rf"Software\Classes\{type_name}\DefaultIcon",
        rf"Software\Classes\{type_name}",
        rf"Software\Classes\{ext}",
    ]
    for k in keys_to_delete:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, k)
        except OSError:
            pass


# 要注册的文件类型列表
_FILETYPES = [
    (".mbtl",  "BannerTrainer.MBTL",  "旗帜训练器 MBTL 文件"),
    (".mbtlx", "BannerTrainer.MBTLX", "旗帜训练器 MBTLX 标记文件"),
]


def main():
    if not sys.platform.startswith("win"):
        print("[错误] 此脚本仅支持Windows系统")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--uninstall":
        print("正在卸载文件关联...")
        for ext, type_name, _ in _FILETYPES:
            _unregister_filetype(ext, type_name)
            print(f"  已卸载 {ext}")
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)
        print("[完成] 文件关联已卸载")
        input("按回车键退出...")
        return

    print("=" * 50)
    print("  旗帜训练器 - 文件关联安装")
    print("=" * 50)
    print()

    print("[1/2] 检查图标文件...")
    ico_path = _ensure_ico()
    if not ico_path:
        print("\n安装失败：找不到图标文件")
        input("按回车键退出...")
        return

    print(f"  图标路径: {ico_path}")
    print()

    print(f"[2/2] 注册 {len(_FILETYPES)} 种文件类型...")
    all_ok = True
    for ext, type_name, desc in _FILETYPES:
        if _register_filetype(ext, type_name, desc, ico_path):
            print(f"  [OK] {ext} → {type_name}")
        else:
            print(f"  [失败] {ext}")
            all_ok = False

    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)

    if all_ok:
        print()
        print("[完成] 文件关联安装成功！")
        print(f"       已注册 {len(_FILETYPES)} 种格式：{', '.join(e for e, _, _ in _FILETYPES)}")
        print("       双击文件可使用旗帜训练导入器打开。")
    else:
        print("\n部分文件类型注册失败，请检查错误信息")

    print()
    input("按回车键退出...")


if __name__ == "__main__":
    main()
