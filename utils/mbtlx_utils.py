"""MBTLX 标记文件（ZIP：marks.json + images/）读写工具。

与 mbtl_utils.py（纯文本 .mbtl）并列：MBTLX 是含图片截图的标记包，
供 importer（图形标记导入/导出）与 trainer（Tab2 序列训练）共用。
旧版文本格式（'|' 分隔行）也在此处理，保持向后兼容。

格式（ZIP）：
  images/0001.png ...   —— 截图（按导出顺序编号）
  marks.json            —— {"version": "2.0", "items": [{"image", "original_path",
                          "banners": [{"x","y","w","h","data"}]}]}
"""

import json
import os
import shutil
import tempfile
import uuid
import zipfile

MBTLX_VERSION = "2.0"
_IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp')


def is_mbtlx(filepath):
    """检测是否为 MBTLX（ZIP）格式：文件头 b'PK'。"""
    try:
        with open(filepath, 'rb') as f:
            return f.read(2) == b'PK'
    except Exception:
        return False


def export_mbtlx(save_path, marks):
    """将内存标记列表打包为 .mbtlx（ZIP：images/ + marks.json）。

    marks: [(img_path, banner_data), ...]
    返回实际打包的条数（跳过不存在的图片）。
    """
    items = []
    img_counter = 0
    with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for img_path, banner_data in marks:
            if not os.path.exists(img_path):
                continue
            img_counter += 1
            ext = os.path.splitext(img_path)[1].lower() or '.png'
            arc_name = f"images/{img_counter:04d}{ext}"
            zf.write(img_path, arc_name)
            items.append({
                "image": arc_name,
                "original_path": img_path,
                "banners": [{
                    "x": None, "y": None, "w": None, "h": None,
                    "data": list(banner_data)
                }]
            })
        zf.writestr("marks.json", json.dumps(
            {"version": MBTLX_VERSION, "items": items},
            ensure_ascii=False, indent=2))
    return img_counter


def export_mbtlx_from_dir(save_path, extract_dir):
    """从已解压的 MBTLX 目录重新打包（trainer 自动保存用）。

    保留原 marks.json 内容，images/ 按序重排编号。
    返回打包的图片数（无 marks.json 或无图片时返回 0）。
    """
    marks_json_path = os.path.join(extract_dir, "marks.json")
    if not os.path.exists(marks_json_path):
        return 0
    img_counter = 0
    with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        images_dir = os.path.join(extract_dir, "images")
        if os.path.isdir(images_dir):
            for fname in sorted(os.listdir(images_dir)):
                if fname.lower().endswith(_IMAGE_EXTS):
                    img_counter += 1
                    arc = f"images/{img_counter:04d}{os.path.splitext(fname)[1].lower()}"
                    zf.write(os.path.join(images_dir, fname), arc)
        with open(marks_json_path, "r", encoding="utf-8") as mf:
            zf.writestr("marks.json", mf.read())
    return img_counter


def _parse_text_line(line):
    """解析旧文本格式行：'图片路径|背景色;图案色-图案类型/...'"""
    img_path, data_str = line.split('|', 1)
    parts = data_str.split(';')
    bg = int(parts[0])
    banner_data = [bg]
    if len(parts) > 1:
        for pat_str in parts[1].split('/'):
            if '-' in pat_str:
                ci, pi = pat_str.split('-', 1)
                banner_data.extend([int(pi), int(ci)])
    return img_path, banner_data


def import_mbtlx(filepath, extract_dir=None):
    """导入 .mbtlx，自动识别 ZIP / 旧文本格式。

    返回 (banners_list, extract_dir)：
      - banners_list: [[img_path, banner_data], ...]（每图取第一个旗帜，1:1 模式）
      - extract_dir: ZIP 格式的解压目录（文本格式为 None），调用方可后续清理
    """
    if is_mbtlx(filepath):
        extract_dir = extract_dir or os.path.join(
            tempfile.gettempdir(), f"mbtlx_{uuid.uuid4().hex[:8]}")
        with zipfile.ZipFile(filepath, 'r') as zf:
            zf.extractall(extract_dir)
        marks_path = os.path.join(extract_dir, "marks.json")
        if not os.path.exists(marks_path):
            raise ValueError("MBTLX 缺少 marks.json")
        with open(marks_path, 'r', encoding='utf-8') as f:
            marks_data = json.load(f)
        result = []
        for item in marks_data.get("items", []):
            img_rel = item.get("image", "")
            img_path = os.path.join(extract_dir, img_rel) if img_rel else ""
            banners = item.get("banners", [])
            if not banners:
                continue
            result.append([img_path, list(banners[0].get("data", [0]))])
        return result, extract_dir
    # 旧文本格式
    result = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or '|' not in line:
                continue
            img_path, banner_data = _parse_text_line(line)
            result.append([img_path, banner_data])
    return result, None


def cleanup(extract_dir):
    """删除解压临时目录。"""
    if extract_dir and os.path.isdir(extract_dir):
        try:
            shutil.rmtree(extract_dir)
        except Exception:
            pass
