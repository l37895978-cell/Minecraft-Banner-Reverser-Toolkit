import struct

MBTL_MAGIC = b'MBTL'
MBTL_VERSION = 1


def write_mbtl(filepath, banners):
    with open(filepath, 'wb') as f:
        f.write(MBTL_MAGIC)
        f.write(struct.pack('<H', MBTL_VERSION))
        f.write(struct.pack('<I', len(banners)))
        for banner_data in banners:
            bg_color = banner_data[0] & 0xFF
            layer_count = (len(banner_data) - 1) // 2
            f.write(struct.pack('BB', bg_color, layer_count))
            for i in range(1, len(banner_data), 2):
                if i + 1 < len(banner_data):
                    pattern_type = banner_data[i] & 0xFF
                    pattern_color = banner_data[i + 1] & 0xFF
                    f.write(struct.pack('BB', pattern_type, pattern_color))


def read_mbtl(filepath):
    with open(filepath, 'rb') as f:
        magic = f.read(4)
        if magic != MBTL_MAGIC:
            raise ValueError(f"无效的MBTL文件: 魔数不匹配 (期望 {MBTL_MAGIC!r}, 得到 {magic!r})")
        version = struct.unpack('<H', f.read(2))[0]
        if version > MBTL_VERSION:
            raise ValueError(f"不支持的MBTL版本: {version} (当前支持版本 <= {MBTL_VERSION})")
        count = struct.unpack('<I', f.read(4))[0]
        banners = []
        for _ in range(count):
            bg_color, layer_count = struct.unpack('BB', f.read(2))
            banner_data = [bg_color]
            for _ in range(layer_count):
                pattern_type, pattern_color = struct.unpack('BB', f.read(2))
                # 过滤 pattern_type=0 的"无"图案（不是真实图案）
                if pattern_type == 0:
                    continue
                banner_data.extend([pattern_type, pattern_color])
            banners.append(banner_data)
    return banners


def load_banners_from_file(filepath):
    return read_mbtl(filepath)
