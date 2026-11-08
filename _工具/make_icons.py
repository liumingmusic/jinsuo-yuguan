#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_icons.py — 生成站点图标（favicon / apple-touch-icon）。

图标就是顶栏那个标识的缩小版：墨青圆底、白罗盘环、南北白针、东西淡针、铜金中心点。
用 8 倍超采样画再缩，避免 PIL 直接画小图出锯齿。

用法：
  python3 _工具/make_icons.py
产物写到 `_工具/theme/图标/`，由 build.py 复制到 `站点/` 根目录。
"""

import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "theme", "图标")

# 与 style.css 的 :root 保持一致
INK_BRAND = (27, 58, 70)      # --brand  墨青
WHITE = (255, 255, 255)
GOLD = (201, 168, 106)        # --gold-2 铜金
SS = 64                       # 每 1 个 viewBox 单位 = 64px，即 16 单位 → 1024px

# viewBox 0 0 16 16 上的坐标
R_OUT = 8.0
R_RING = 5.4          # 环半径：放太大会挤掉针尖，放小又显空
RING_W = 1.0
NEEDLE_N = [(8, 2.55), (9.35, 8), (8, 13.45), (6.65, 8)]
NEEDLE_E = [(2.55, 8), (8, 6.65), (13.45, 8), (8, 9.35)]
R_DOT = 0.85          # 铜点只是点个心，太大就变成主角、把针的交叉盖住了

# 16px 专用简化版。实测：完整罗盘缩到 16 会糊成齿轮；只留菱形针会退化成竖条（像「0」）；
# 双箭头像沙漏；环+点内部糊掉。四种里只有「实心指北三角」在 16×16 还立得住，
# 所以最小档只画一个白三角，其余一概不放。32px 起用完整罗盘。
ARROW_N = [(8, 2.6), (11.5, 12.6), (4.5, 12.6)]


def px(v):
    return v * SS


def master(simple=False):
    """画 1024×1024 母版（4 通道）。simple=True 出 16px 用的简化版。"""
    size_scale = SS
    S = 16 * size_scale
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    def P(points):
        return [(x * size_scale, y * size_scale) for x, y in points]

    r_ring = R_RING
    ring_w = RING_W

    # 圆底
    d.ellipse([0, 0, S - 1, S - 1], fill=INK_BRAND)

    if simple:
        # 16px：只画指北三角
        d.polygon(P(ARROW_N), fill=WHITE)
        return im

    # 东西针（淡）先画，压在南北针下面
    d.polygon(P(NEEDLE_E), fill=WHITE + (82,))    # ≈ 32%，深底上再淡一档才不跟南北针抢
    # 南北针
    d.polygon(P(NEEDLE_N), fill=WHITE)

    # 罗盘环
    w = ring_w * size_scale
    d.ellipse(
        [px(R_OUT - r_ring) + w / 2, px(R_OUT - r_ring) + w / 2,
         px(R_OUT + r_ring) - w / 2, px(R_OUT + r_ring) - w / 2],
        outline=(255, 255, 255, 235), width=max(1, int(round(w))),
    )

    # 铜金中心点
    rc = R_DOT * size_scale
    cx = cy = px(R_OUT)
    d.ellipse([cx - rc, cy - rc, cx + rc, cy + rc], fill=GOLD)
    return im


def resized(im, n):
    return im.resize((n, n), Image.LANCZOS)


def write_ico(path, entries):
    """自己拼 ICO（各帧内嵌 PNG），这样每个尺寸能用不同的母版。
    PIL 的 save(sizes=...) 只能从同一张图缩，没法给 16px 换一套简化画法。"""
    import struct, io
    blobs = []
    for n, im in entries:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        blobs.append((n, buf.getvalue()))
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    dirs = b""
    for n, data in blobs:
        w = 0 if n >= 256 else n          # 0 表示 256
        dirs += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + dirs + b"".join(d for _, d in blobs))


def main():
    os.makedirs(OUT, exist_ok=True)
    big = master()              # 完整版：圆底 + 环 + 四角针 + 铜点
    tiny = master(simple=True)  # 16px 简化版

    # 单尺寸 PNG（16 用简化版）
    for n in (16, 32, 48, 64, 180, 192, 512):
        src = tiny if n <= 16 else big
        resized(src, n).save(os.path.join(OUT, f"favicon-{n}.png"))

    # apple-touch-icon 要 180×180 且不透明底（iOS 会自己切圆角）
    apple = resized(big, 180)
    flat = Image.new("RGB", apple.size, INK_BRAND)
    flat.paste(apple, (0, 0), apple)
    flat.save(os.path.join(OUT, "apple-touch-icon.png"))

    # favicon.ico：16 走简化版，其余走完整版
    write_ico(os.path.join(OUT, "favicon.ico"), [
        (16, resized(tiny, 16)),
        (32, resized(big, 32)),
        (48, resized(big, 48)),
        (64, resized(big, 64)),
        (256, resized(big, 256)),
    ])

    # SVG 版：现代浏览器优先用，任意 DPI 都清晰
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
<circle cx="8" cy="8" r="8" fill="#1b3a46"/>
<path d="M2.55 8 8 6.65 13.45 8 8 9.35Z" fill="#fff" opacity=".32"/>
<path d="M8 2.55 9.35 8 8 13.45 6.65 8Z" fill="#fff"/>
<circle cx="8" cy="8" r="5.4" fill="none" stroke="#fff" stroke-width="1" opacity=".92"/>
<circle cx="8" cy="8" r=".85" fill="#c9a86a"/>
</svg>
"""
    open(os.path.join(OUT, "favicon.svg"), "w", encoding="utf-8").write(svg)

    for f in sorted(os.listdir(OUT)):
        p = os.path.join(OUT, f)
        print(f"  {f:24s} {os.path.getsize(p):>7d} B")


if __name__ == "__main__":
    main()
