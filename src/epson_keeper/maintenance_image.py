"""维护页绘制 — reportlab Canvas 直接绘制色条、波浪线、点阵图"""

import math
import random
from typing import Optional

from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas as canvas_mod

# A4 尺寸（points，1pt = 1/72 inch，1mm ≈ 2.835pt）
MM = 2.835
PAGE_W = 210 * MM  # 595.28
PAGE_H = 297 * MM  # 841.89

# 布局参数
TOP_MARGIN = 20 * MM
BAR_WIDTH = 185 * MM
BAR_HEIGHT = 18 * MM
WAVE_AREA_HEIGHT = 10 * MM
DOT_AREA_HEIGHT = 80 * MM
COLOR_SPACING = 6 * MM  # 每组色条+波浪线之间的间距

# CMYK 颜色（纯色，用于渐变）
CMYK_COLORS = {
    "K": (0, 0, 0, 1),
    "C": (1, 0, 0, 0),
    "M": (0, 1, 0, 0),
    "Y": (0, 0, 1, 0),
}

# 颜色顺序
COLOR_ORDER = ["K", "C", "M", "Y"]

# 渐变方向（每次运行随机选择）
_DIRECTIONS = ["lr", "rl", "tb", "bt"]


def _cmyk_color(c: float, m: float, y: float, k: float, alpha: float = 1.0) -> Color:
    """创建 CMYK 颜色（reportlab CMYKColor 通过 setFillColorCMYK 直接使用）。"""
    return Color(c, m, y, k)  # 只是占位，实际用 canvas 方法


def _draw_gradient_bar(
    cv: canvas_mod.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    cmyk: tuple,
    start_pct: float = 0.2,
    end_pct: float = 0.8,
    steps: int = 60,
    direction: str = "lr",
):
    """绘制渐变色条，direction 控制渐变方向：lr/rl/tb/bt。"""
    c, m, y_c, k = cmyk

    if direction in ("lr", "rl"):
        step_size = width / steps
        for i in range(steps):
            t = i / (steps - 1)
            if direction == "rl":
                t = 1 - t
            pct = start_pct + (end_pct - start_pct) * t
            cv.setFillColorCMYK(c * pct, m * pct, y_c * pct, k * pct)
            cv.rect(x + i * step_size, y, step_size + 1, height, stroke=0, fill=1)
    else:
        step_size = height / steps
        for i in range(steps):
            t = i / (steps - 1)
            if direction == "bt":
                t = 1 - t
            pct = start_pct + (end_pct - start_pct) * t
            cv.setFillColorCMYK(c * pct, m * pct, y_c * pct, k * pct)
            cv.rect(x, y + i * step_size, width, step_size + 1, stroke=0, fill=1)


def _draw_sine_waves(
    cv: canvas_mod.Canvas,
    x: float,
    y: float,
    width: float,
    cmyk: tuple,
    num_waves: int = 4,
    line_width: float = 0.9,
    amplitude: float = 2.0 * MM,
    periods: float = 5.0,
    start_pct: float = 0.2,
    end_pct: float = 0.8,
):
    """绘制多条 sin 波浪线，从浅到深渐变。"""
    c, m, y_c, k = cmyk
    wave_spacing = 1.0 * MM  # 线间距

    for i in range(num_waves):
        t = i / max(num_waves - 1, 1)
        pct = start_pct + (end_pct - start_pct) * t
        cv.setStrokeColorCMYK(c * pct, m * pct, y_c * pct, k * pct)
        cv.setLineWidth(line_width)

        p = cv.beginPath()
        num_points = 200
        y_offset = y - i * wave_spacing
        for j in range(num_points + 1):
            px = x + (j / num_points) * width
            phase = (j / num_points) * periods * 2 * math.pi
            py = y_offset + amplitude * math.sin(phase)
            if j == 0:
                p.moveTo(px, py)
            else:
                p.lineTo(px, py)
        cv.drawPath(p, stroke=1, fill=0)


def _draw_dot_matrix(
    cv: canvas_mod.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    density: float = 0.03,
    dot_min: float = 1.5 * MM,
    dot_max: float = 2.5 * MM,
    spacing_min: float = 8 * MM,
    spacing_max: float = 12 * MM,
    seed: Optional[int] = None,
    pct_range: tuple[float, float] = (0.15, 0.6),
):
    """绘制稀疏 CMYK 彩色圆点阵列。seed=None 时每次随机。"""
    if seed is None:
        seed = random.randint(0, 2**31)
    rng = random.Random(seed)

    area = width * height
    avg_dot_area = math.pi * ((dot_min + dot_max) / 4) ** 2
    target_coverage = area * density
    num_dots = max(int(target_coverage / avg_dot_area), 10)

    cmyk_list = list(CMYK_COLORS.values())

    cx = x
    while cx < x + width:
        cy = y
        while cy < y + height:
            jx = rng.uniform(spacing_min * 0.3, spacing_max * 0.8)
            jy = rng.uniform(spacing_min * 0.3, spacing_max * 0.8)
            dx = cx + jx
            dy = cy + jy

            if dx >= x + width or dy >= y + height:
                cy = dy
                continue

            radius = rng.uniform(dot_min, dot_max) / 2
            c, m, yy, k = rng.choice(cmyk_list)
            pct = rng.uniform(*pct_range)
            cv.setFillColorCMYK(c * pct, m * pct, yy * pct, k * pct)
            cv.circle(dx, dy, radius, stroke=0, fill=1)
            cy = dy
        cx += rng.uniform(spacing_min * 0.5, spacing_max * 0.5)


def draw_maintenance_page(
    cv: canvas_mod.Canvas,
    width: float = PAGE_W,
    height: float = PAGE_H,
    photo_path: Optional[str] = None,
):
    """绘制维护页：色条 + 波浪线 + 点阵图。"""
    x_center = (width - BAR_WIDTH) / 2
    y_cursor = height - TOP_MARGIN

    # 渐变方向：固定从下往上
    direction = "bt"

    for color_name in COLOR_ORDER:
        cmyk = CMYK_COLORS[color_name]

        # 渐变色条（随机方向）
        _draw_gradient_bar(cv, x_center, y_cursor - BAR_HEIGHT, BAR_WIDTH, BAR_HEIGHT, cmyk,
                           direction=direction)
        y_cursor -= BAR_HEIGHT + 2 * MM

        # 波浪线
        _draw_sine_waves(cv, x_center, y_cursor, BAR_WIDTH, cmyk)
        y_cursor -= WAVE_AREA_HEIGHT + COLOR_SPACING

    # 点阵图区域（每次随机）
    dot_top = y_cursor
    dot_bottom = 20 * MM
    dot_height = dot_top - dot_bottom
    if dot_height > 10 * MM:
        _draw_dot_matrix(cv, x_center, dot_bottom, BAR_WIDTH, dot_height)

    cv.showPage()


def draw_background_dots(
    cv: canvas_mod.Canvas,
    width: float = PAGE_W,
    height: float = PAGE_H,
):
    """绘制浅色点阵背景（用于报告页）。"""
    _draw_dot_matrix(
        cv, 0, 0, width, height,
        density=0.01,
        dot_min=1.5 * MM,
        dot_max=3.0 * MM,
        spacing_min=10 * MM,
        spacing_max=16 * MM,
        pct_range=(0.10, 0.30),
    )
