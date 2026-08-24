from PIL import Image
import os

color = {
    "white": [249, 255, 254],
    "orange": [249, 128, 29],
    "magenta": [199, 78, 189],
    "light_blue": [58, 179, 218],
    "yellow": [254, 216, 61],
    "lime": [128, 199, 31],
    "pink": [243, 139, 170],
    "gray": [71, 79, 82],
    "light_gray": [157, 157, 151],
    "cyan": [22, 156, 156],
    "purple": [137, 50, 184],
    "blue": [60, 68, 170],
    "brown": [131, 84, 50],
    "green": [94, 124, 22],
    "red": [176, 46, 38],
    "black": [29, 29, 33],
    "none": [255, 255, 255]
}

color_name_order = ["white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray", "light_gray", "cyan", "purple", "blue", "brown", "green", "red", "black"]
color_name = color_name_order + ["none"]

type = [
    "no", "bl", "br", "tl", "tr", "bs",
    "ts", "ls", "rs", "cs", "ms", "drs",
    "dls", "ss", "cr", "sc", "bt", "tt",
    "bts", "tts", "ld", "rd", "lud", "rud",
    "mc", "mr", "vh", "hh", "vhr", "hhb",
    "bo", "cbo", "gra", "gru", "bri", "flo",
    "cre", "sku", "moj", "glb", "pig", "gus",
    "flw"
]

type_zh = [
    "无", "右顶方", "左顶方", "右底方", "左底方", "底横条",
    "顶横条", "右竖条", "左竖条", "中竖条", "中横条", "右斜条",
    "左斜条", "竖条纹", "斜十字", "正十字", "底三角", "顶三角",
    "底波纹", "顶波纹", "右上三角形", "左上三角形", "右下三角形", "左下三角形",
    "圆形", "菱形", "右半方形", "上半方形", "左半方形", "下半方形",
    "方框边", "波纹边", "自上渐淡", "自下渐淡", "砖纹", "花朵盾徽",
    "苦力怕盾徽", "头颅盾徽", "mojang徽标", "地球", "猪鼻", "旋风",
    "涡流"
]

icon = {}
_shade_map = None


def load_icons():
    import numpy as np
    import cv2
    global icon, _shade_map
    if icon == {}:
        img_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images")
        img_dir = os.path.normpath(img_dir)

        pattern_dir = os.path.join(img_dir, "base_and_patterns")
        if os.path.exists(pattern_dir):
            existing_patterns = [f[:-4] for f in os.listdir(pattern_dir) if f.endswith('.png') and f != "base.png"]
            for name in type:
                if name in existing_patterns:
                    try:
                        image_path = os.path.join(pattern_dir, f"{name}.png")
                        with Image.open(image_path) as img:
                            img = img.convert('RGBA')
                            arr = np.array(img)
                            if arr.shape[0] >= 41 and arr.shape[1] >= 21 and arr.shape[2] >= 4:
                                L = arr[1:41, 1:21, 0].astype(np.float32) / 255.0
                                A = arr[1:41, 1:21, 3].astype(np.float32) / 255.0
                                icon[name] = (L, A)
                    except Exception:
                        pass

        base_path = os.path.join(img_dir, "base_and_patterns", "base.png")
        if not os.path.exists(base_path):
            base_path = os.path.join(img_dir, "Banner_base_(texture)_JE1_BE1.png")
        if os.path.exists(base_path):
            try:
                with Image.open(base_path) as base_img:
                    base_arr = np.array(base_img.convert('RGBA'))
                    if base_arr.shape[0] >= 41 and base_arr.shape[1] >= 21:
                        shade_region = base_arr[1:41, 1:21, :3].astype(np.float32) / 255.0
                        _shade_map = shade_region[:, :, 0]
            except Exception:
                pass

        if _shade_map is None:
            _shade_map = np.ones((40, 20), dtype=np.float32)

def generate_banner_image(banner_data, size=(200, 400)):
    import numpy as np
    import cv2
    global _shade_map
    if _shade_map is None:
        load_icons()
    image = np.ones((size[1], size[0], 3), dtype=np.uint8) * 255
    if len(banner_data) > 0:
        bg_color_idx = banner_data[0]
        if bg_color_idx < len(color_name):
            bg_color = color[color_name[bg_color_idx]]
            bg_color = [bg_color[2], bg_color[1], bg_color[0]]
            image[:] = bg_color

    shade_scaled = cv2.resize(
        _shade_map,
        (size[0], size[1]),
        interpolation=cv2.INTER_NEAREST
    )
    shade_3d = shade_scaled[:, :, np.newaxis]
    image = np.clip(image.astype(np.float64) * shade_3d, 0, 255).astype(np.uint8)

    for i in range(1, len(banner_data), 2):
        if i + 1 < len(banner_data):
            pattern_idx = banner_data[i]
            color_idx = banner_data[i + 1]

            if pattern_idx < len(type) and color_idx < len(color_name):
                pattern_name = type[pattern_idx]
                if pattern_name == "no":
                    continue

                pattern_color = color[color_name[color_idx]]
                pattern_color_bgr = np.array([pattern_color[2], pattern_color[1], pattern_color[0]], dtype=np.float64)

                if pattern_name in icon:
                    pattern_L, pattern_A = icon[pattern_name]

                    if pattern_L.shape == (40, 20) and pattern_A.shape == (40, 20):
                        scaled_L = cv2.resize(
                            pattern_L,
                            (size[0], size[1]),
                            interpolation=cv2.INTER_NEAREST
                        )
                        scaled_A = cv2.resize(
                            pattern_A,
                            (size[0], size[1]),
                            interpolation=cv2.INTER_NEAREST
                        )

                        L_3d = scaled_L[:, :, np.newaxis]
                        A_3d = scaled_A[:, :, np.newaxis]
                        image_float = image.astype(np.float64)
                        blended = image_float * (1 - A_3d) + (L_3d * pattern_color_bgr) * A_3d
                        image = np.clip(blended, 0, 255).astype(np.uint8)

    return image


def generate_random_banner(min_colors=1, max_colors=5, min_patterns=0, max_patterns=16, allow_duplicate_colors=True):
    import numpy as np
    bg_color = np.random.randint(0, 16)
    pattern_count = np.random.randint(min_patterns, max_patterns + 1)
    actual_min_colors = max(1, min(min_colors, pattern_count + 1))
    actual_max_colors = max(1, min(max_colors, pattern_count + 1))
    if actual_min_colors > actual_max_colors:
        actual_min_colors = actual_max_colors
    target_color_count = np.random.randint(actual_min_colors, actual_max_colors + 1)
    banner_data = [bg_color]
    used_colors = {bg_color}
    if pattern_count == 0:
        return banner_data
    needed_pattern_colors = target_color_count - 1
    available_colors = [c for c in range(16) if c != bg_color]
    pattern_colors = []
    if needed_pattern_colors > 0:
        pattern_colors = list(np.random.choice(available_colors, min(needed_pattern_colors, len(available_colors)), replace=False))
    while len(pattern_colors) < pattern_count:
        if pattern_colors:
            pattern_colors.append(np.random.choice(pattern_colors))
        else:
            pattern_colors.append(np.random.choice(available_colors))
    for i in range(pattern_count):
        pattern = np.random.randint(1, len(type))
        color_idx = pattern_colors[i]
        banner_data.extend([pattern, color_idx])
        used_colors.add(color_idx)
    return banner_data
