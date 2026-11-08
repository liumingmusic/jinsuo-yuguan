#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_icons.py — 生成站点图标（favicon / apple-touch-icon）。

图标与首页顶栏那个 `.mark` 标识完全同形：28×28 圆角 8px 的墨青渐变方块里，
一个白色细线罗盘（环 + 南北针 + 淡东西针 + 铜金中心点）。
几何直接抄 `theme/page.html` 里那段 `<svg viewBox="0 0 16 16">`，
配色抄 `theme/style.css` 的 `.logo .mark`（`--brand` → `#26525f`）与 `--gold-2`。

16px 单独一套几何：把 header 原样缩到 16，环与针在 16 格网格上会粘成一团，
所以最小档缩短针长、去掉东西针、略加粗环与点，保住「环 + 短针 + 铜点」三层结构。

用 64 倍超采样画再缩，避免 PIL 直接画小图出锯齿。

用法：
  python3 _工具/make_icons.py
产物写到 `_工具/theme/图标/`，由 build.py 复制到 `站点/` 根目录。
"""

import os
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "theme", "图标")

# 与 style.css 的 .logo .mark 保持一致
GRAD_A = (27, 58, 70)         # --brand  #1b3a46
GRAD_B = (38, 82, 95)         # #26525f
GOLD = (201, 168, 106)        # --gold-2 铜金
WHITE = (255, 255, 255)

SS = 64                       # 每 1 个 viewBox 单位 = 64px，即 16 单位 → 1024px

RADIUS = 8 / 28 * 16          # .mark 28×28 上圆角 8px，折算到 16 网格是 4.571
GRAD_ANGLE = (0.5, 0.866)     # CSS 150deg 的方向向量（屏幕 y 向下）

# header 里那段 svg 是 16×16 画在 28×28 方块里的，四周各留 6px。
# 图标要跟着这个留白，图形区只占 16/28——否则环会贴到圆角边上，比 header 大一圈。
FIG = 16 / 28
FIG_TINY = 0.78               # 16px 档图形缩到 0.78，环才不会贴到圆角边上

# header 那段 svg 的原始坐标，一个数都不改
RING_R = 6.1
RING_W = 1.2
NEEDLE_N = [(8, 2.1), (9.3, 8), (8, 13.9), (6.7, 8)]
NEEDLE_E = [(2.1, 8), (8, 6.7), (13.9, 8), (8, 9.3)]
EAST_OPACITY = 0.38
DOT_R = 1.2

# 16px 专用：针长从 5.9 缩到 3.9，上下留出空隙才不和环粘住；
# 东西针在这个尺寸下只是脏点，去掉；环加粗一档、铜点收小一点，
# 这样「白环 / 竖直短针 / 铜点」三层在 16 格网格上还能分得开。
T_RING_W = 1.6
T_NEEDLE_W = 2.2
T_NEEDLE_LEN = 3.9
T_DOT_R = 1.15


def bg_gradient(S):
    """150deg 线性渐变，左上 → 右下。"""
    ax, ay = GRAD_ANGLE
    half = (abs(ax) * S + abs(ay) * S) / 2
    xs = (np.arange(S) - (S - 1) / 2)[None, :]
    ys = (np.arange(S) - (S - 1) / 2)[:, None]
    t = np.clip(0.5 + (xs * ax + ys * ay) / (2 * half), 0, 1)
    arr = np.zeros((S, S, 4), dtype=np.uint8)
    for i in range(3):
        arr[:, :, i] = (GRAD_A[i] + (GRAD_B[i] - GRAD_A[i]) * t).astype(np.uint8)
    arr[:, :, 3] = 255
    return Image.fromarray(arr, "RGBA")


def rounded_mask(S, radius):
    """圆角矩形遮罩，4 倍超采样再缩，边缘干净。radius 以 viewBox 单位传入。"""
    k = 4
    big = Image.new("L", (S * k, S * k), 0)
    d = ImageDraw.Draw(big)
    d.rounded_rectangle([0, 0, S * k - 1, S * k - 1], radius=radius * SS * k, fill=255)
    return big.resize((S, S), Image.LANCZOS)


def master(simple=False, square=False):
    """画 1024×1024 母版（4 通道）。
    simple=True 出 16px 用的简化版；square=True 出满版方角（给 iOS 自己切圆角）。"""
    S = 16 * SS
    base = bg_gradient(S)
    base.putalpha(Image.new("L", (S, S), 255) if square else rounded_mask(S, RADIUS))

    lay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)

    def P(points):
        return [(x * SS, y * SS) for x, y in points]

    fig = FIG_TINY if simple else FIG

    def Z(points):
        """把 viewBox 坐标缩进图形区（绕中心 8 缩放）。"""
        return [(8 + (x - 8) * fig, 8 + (y - 8) * fig) for x, y in points]

    def widen(points, w, w0):
        """按针宽比例沿 x 方向缩放（针关于 x=8 对称）。"""
        f = w / w0
        return [(8 + (x - 8) * f, y) for x, y in points]

    if simple:
        nw, nl, ring_w, dot_r = T_NEEDLE_W, T_NEEDLE_LEN, T_RING_W, T_DOT_R
        # 上下各一个尖角三角，合起来是一根带尖的短针
        d.polygon(P(Z([(8, 8 - nl), (8 + nw / 2, 8), (8 - nw / 2, 8)])), fill=WHITE + (255,))
        d.polygon(P(Z([(8, 8 + nl), (8 + nw / 2, 8), (8 - nw / 2, 8)])), fill=WHITE + (255,))
    else:
        ring_w, dot_r = RING_W, DOT_R
        d.polygon(P(Z(NEEDLE_E)), fill=WHITE + (int(255 * EAST_OPACITY),))
        d.polygon(P(Z(NEEDLE_N)), fill=WHITE + (255,))

    # 罗盘环。注意 PIL 的 width 是从 bbox 边界**向内**画的，
    # 而 SVG 的 stroke 是居中画——所以 bbox 要放到 r + w/2，外沿才和 svg 对齐。
    r = RING_R * fig
    w = ring_w * fig * SS
    R = r * SS
    d.ellipse([8 * SS - R - w / 2, 8 * SS - R - w / 2,
               8 * SS + R + w / 2, 8 * SS + R + w / 2],
              outline=WHITE + (255,), width=max(1, int(round(w))))

    # 铜金中心点
    rc = dot_r * fig * SS
    d.ellipse([8 * SS - rc, 8 * SS - rc, 8 * SS + rc, 8 * SS + rc], fill=GOLD + (255,))

    # 裁到圆角方块内
    lay.putalpha(Image.composite(lay.getchannel("A"), Image.new("L", (S, S), 0),
                                 base.getchannel("A")))
    return Image.alpha_composite(base, lay)


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
    big = master()
    tiny = master(simple=True)
    flat = master(square=True)     # 方角满版，给 iOS

    for n in (16, 32, 48, 64, 180, 192, 512):
        resized(tiny if n <= 16 else big, n).save(os.path.join(OUT, f"favicon-{n}.png"))

    # apple-touch-icon：180×180，不带圆角（iOS 自己切），底色必须不透明
    resized(flat, 180).save(os.path.join(OUT, "apple-touch-icon.png"))

    write_ico(os.path.join(OUT, "favicon.ico"), [
        (16, resized(tiny, 16)),
        (32, resized(big, 32)),
        (48, resized(big, 48)),
        (64, resized(big, 64)),
        (256, resized(big, 256)),
    ])

    # SVG 版：现代浏览器优先用，任意 DPI 都清晰
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
<defs><linearGradient id="b" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#1b3a46"/><stop offset="1" stop-color="#26525f"/>
</linearGradient></defs>
<rect width="16" height="16" rx="{RADIUS:.3f}" fill="url(#b)"/>
<g transform="translate(8 8) scale({FIG:.4f}) translate(-8 -8)">
<circle cx="8" cy="8" r="{RING_R}" fill="none" stroke="#fff" stroke-width="{RING_W}"/>
<path d="M8 2.1 9.3 8 8 13.9 6.7 8Z" fill="#fff"/>
<path d="M2.1 8 8 6.7 13.9 8 8 9.3Z" fill="#fff" opacity="{EAST_OPACITY}"/>
<circle cx="8" cy="8" r="{DOT_R}" fill="#c9a86a"/>
</g>
</svg>
"""
    open(os.path.join(OUT, "favicon.svg"), "w", encoding="utf-8").write(svg)

    for f in sorted(os.listdir(OUT)):
        p = os.path.join(OUT, f)
        print(f"  {f:24s} {os.path.getsize(p):>7d} B")


if __name__ == "__main__":
    main()
