#!/usr/bin/env python3
"""生成 Daily Audio Pipeline 应用图标"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math

SIZE = 1024
BG = (6, 6, 12)
CYAN = (0, 240, 255)
CYAN_DIM = (0, 160, 180)
CYAN_GLOW = (0, 240, 255, 60)
WHITE = (255, 255, 255)

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# ── 圆角方形底座 ──────────────────────────────────────
corner = 200
draw.rounded_rectangle(
    [(80, 80), (SIZE - 80, SIZE - 80)],
    radius=corner, fill=BG,
)

# ── 外发光边框 ────────────────────────────────────────
for i in range(30, 0, -1):
    alpha = max(0, int(20 - i * 0.7))
    if alpha <= 0:
        continue
    glow = (0, 240, 255, alpha)
    b = 80 - i
    draw.rounded_rectangle(
        [(b, b), (SIZE - b, SIZE - b)],
        radius=corner, outline=glow, width=2,
    )

# ── 内圈 ──────────────────────────────────────────────
cx, cy = SIZE // 2, SIZE // 2
inner_r = 280
for i in range(8, 0, -1):
    alpha = max(0, int(18 - i * 2))
    draw.ellipse(
        [cx - inner_r - i, cy - inner_r - i, cx + inner_r + i, cy + inner_r + i],
        outline=(0, 240, 255, alpha), width=1,
    )

# ── 声波图标 ──────────────────────────────────────────
bars = 7
bar_width = 28
bar_gap = 18
total_w = bars * bar_width + (bars - 1) * bar_gap
start_x = cx - total_w // 2
bar_bottom = cy + 180
heights = [50, 110, 180, 240, 180, 110, 50]

for i, h in enumerate(heights):
    x = start_x + i * (bar_width + bar_gap)
    y_top = bar_bottom - h

    # 霓虹发光（多层）
    for glow_i in range(4, 0, -1):
        g_alpha = max(0, 20 - glow_i * 4)
        draw.rounded_rectangle(
            [x - glow_i, y_top - glow_i, x + bar_width + glow_i, bar_bottom + glow_i],
            radius=4, fill=(0, 240, 255, g_alpha),
        )

    # 主体渐变（从亮到暗）
    for yy in range(y_top, bar_bottom):
        t = (yy - y_top) / (bar_bottom - y_top)
        r = int(CYAN[0] * (1 - t) + CYAN_DIM[0] * t)
        g = int(CYAN[1] * (1 - t) + CYAN_DIM[1] * t)
        b = int(CYAN[2] * (1 - t) + CYAN_DIM[2] * t)
        draw.line([(x, yy), (x + bar_width, yy)], fill=(r, g, b, 255))

# ── 顶部光晕 ──────────────────────────────────────────
for i in range(60, 0, -2):
    alpha = max(0, 40 - i)
    draw.ellipse(
        [cx - i, cy - 300 - i, cx + i, cy - 300 + i],
        fill=(0, 240, 255, alpha),
    )

# ── 底部"每日播报"小标注 ──────────────────────────────
try:
    font_small = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 40)
except:
    font_small = ImageFont.load_default()

label = "DAILY AUDIO"
label_x = cx - 190
label_y = cy + 280
draw.text((label_x + 2, label_y + 2), label, fill=(0, 0, 0, 120), font=font_small)
draw.text((label_x, label_y), label, fill=(0, 240, 255, 200), font=font_small)

# ── 最终光泽效果 ──────────────────────────────────────
gloss = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
gdraw = ImageDraw.Draw(gloss)
gdraw.rounded_rectangle(
    [(80, 80), (SIZE - 80, SIZE - 80)],
    radius=corner, fill=(255, 255, 255, 12),
)
img = Image.alpha_composite(img, gloss)

# ── 应用圆角蒙版 ──────────────────────────────────────
mask = Image.new("L", (SIZE, SIZE), 0)
mdraw = ImageDraw.Draw(mask)
mdraw.rounded_rectangle(
    [(80, 80), (SIZE - 80, SIZE - 80)],
    radius=corner, fill=255,
)
img.putalpha(mask)

# ── 保存 ──────────────────────────────────────────────
img.save("/tmp/icon_final.png", "PNG")
print("✅ 图标已生成: /tmp/icon_final.png")
print(f"   尺寸: {img.size}")
print(f"   模式: {img.mode}")