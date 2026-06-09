"""PDF 生成器 — 维护页 + 状态报告页"""

import logging
import re
from typing import Optional

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as canvas_mod

from epson_keeper import __version__
from epson_keeper.maintenance_image import draw_maintenance_page, draw_background_dots
from epson_keeper.paths import next_pdf_path
from epson_keeper.printer_info import PrinterStatus

logger = logging.getLogger(__name__)

PAGE_W, PAGE_H = A4

# 颜色方案
C_TITLE = HexColor("#1a1a2e")  # 深蓝
C_DEVICE_SECTION = HexColor("#00838f")  # 青色
C_PRINT_SECTION = HexColor("#ad1457")  # 品红
C_INK_SECTION = HexColor("#00838f")  # 青色
C_WASTE_SECTION = HexColor("#1a1a2e")  # 深蓝
C_ERROR_SECTION = HexColor("#ad1457")  # 品红
C_LABEL = HexColor("#212121")  # 黑色
C_VALUE_DEVICE = HexColor("#1565c0")  # 深蓝
C_VALUE_INK = HexColor("#880e4f")  # 品红
C_DIVIDER = HexColor("#e0e0e0")  # 灰色
C_FOOTER = HexColor("#9e9e9e")  # 灰色
C_GREEN = HexColor("#2e7d32")
C_RED = HexColor("#c62828")

# 墨水颜色
INK_COLORS = {
    "black": {"cmyk": (0, 0, 0, 1), "hex": "#212121"},
    "cyan": {"cmyk": (1, 0, 0, 0), "hex": "#00838f"},
    "magenta": {"cmyk": (0, 1, 0, 0), "hex": "#ad1457"},
    "yellow": {"cmyk": (0, 0, 1, 0), "hex": "#f9a825"},
}

# 字体名称（尝试注册中文回退字体）
_FONT_REGISTERED = False


def _register_fonts():
    """注册 CJK 字体（优先 CID 字体），失败则使用 Helvetica。"""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return

    # 优先使用 reportlab 内置 CID 字体（中文+ASCII 都能正确提取）
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        _FONT_REGISTERED = True
        return
    except Exception:
        pass

    # 尝试常见中文字体路径（TTC 需要 subfontIndex）
    candidates = [
        ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", None),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ]
    for path, subfont in candidates:
        if Path(path).exists():
            try:
                if subfont is not None:
                    pdfmetrics.registerFont(TTFont("CJK", path, subfontIndex=subfont))
                else:
                    pdfmetrics.registerFont(TTFont("CJK", path))
                _FONT_REGISTERED = True
                return
            except Exception:
                continue

    _FONT_REGISTERED = True  # 不再尝试


def _font() -> str:
    """返回可用字体名。"""
    _register_fonts()
    if "STSong-Light" in pdfmetrics.getRegisteredFontNames():
        return "STSong-Light"
    for f in pdfmetrics.getRegisteredFontNames():
        if "CJK" in f:
            return f
    return "Helvetica"


def _fmt(value, suffix: str = "", unknown: str = "未知") -> str:
    """格式化 Optional 值。"""
    if value is None:
        return unknown
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    if isinstance(value, float):
        return f"{value:,.1f}{suffix}"
    return str(value)


def _draw_divider(cv: canvas_mod.Canvas, y: float, margin: float = 30 * mm):
    """绘制水平分隔线。"""
    cv.setStrokeColor(C_DIVIDER)
    cv.setLineWidth(0.5)
    cv.line(margin, y, PAGE_W - margin, y)


def _draw_section_header(
    cv: canvas_mod.Canvas, y: float, title: str, color, font_name: str
) -> float:
    """绘制小节标题。"""
    cv.setFillColor(color)
    cv.setFont(font_name, 11)
    cv.drawString(30 * mm, y, title)
    return y - 5 * mm


def _draw_table_row(
    cv: canvas_mod.Canvas,
    y: float,
    label: str,
    value: str,
    font_name: str,
    label_color=C_LABEL,
    value_color=C_VALUE_DEVICE,
) -> float:
    """绘制一行表格数据。"""
    cv.setFillColor(label_color)
    cv.setFont(font_name, 9)
    cv.drawString(35 * mm, y, label)
    cv.setFillColor(value_color)
    cv.drawString(80 * mm, y, value)
    return y - 5 * mm


def _draw_ink_row(
    cv: canvas_mod.Canvas,
    y: float,
    color_name: str,
    label: str,
    replacements,
    font_name: str,
) -> float:
    """绘制墨水表格行（含颜色指示）。"""
    x_label = 35 * mm
    x_count = 80 * mm

    # 颜色方块
    c, m, yy, k = INK_COLORS[color_name]["cmyk"]
    cv.setFillColorCMYK(c, m, yy, k)
    cv.rect(x_label - 4 * mm, y - 1 * mm, 3 * mm, 3 * mm, stroke=0, fill=1)

    cv.setFillColor(C_LABEL)
    cv.setFont(font_name, 9)
    cv.drawString(x_label, y, label)

    cv.setFillColor(C_VALUE_INK)
    cv.drawString(x_count, y, _fmt(replacements, "次"))
    return y - 5.5 * mm


def draw_status_page(cv: canvas_mod.Canvas, status: PrinterStatus):
    """绘制打印机状态报告页（含浅色点阵背景）。"""
    # 先画浅色点阵背景
    draw_background_dots(cv, PAGE_W, PAGE_H)
    font_name = _font()
    y = PAGE_H - 25 * mm

    # 标题
    cv.setFillColor(C_TITLE)
    cv.setFont(font_name, 16)
    cv.drawString(30 * mm, y, "Epson Keeper 维护报告")
    y -= 7 * mm

    # 时间戳
    cv.setFillColor(C_FOOTER)
    cv.setFont(font_name, 8)
    cv.drawString(30 * mm, y, f"生成时间: {status.query_time}")
    y -= 10 * mm

    # ── 设备信息 ──
    y = _draw_section_header(cv, y, "设备信息", C_DEVICE_SECTION, font_name)
    _draw_divider(cv, y + 2 * mm)
    y -= 2 * mm
    y = _draw_table_row(cv, y, "型号", _fmt(status.model), font_name)
    y = _draw_table_row(cv, y, "序列号", _fmt(status.serial_number), font_name)
    y = _draw_table_row(cv, y, "固件", _fmt(status.firmware_version), font_name)
    y = _draw_table_row(cv, y, "MAC", _fmt(status.mac_address), font_name)
    y = _draw_table_row(cv, y, "打印头ID", _fmt(status.printer_head_id), font_name)
    y = _draw_table_row(cv, y, "首次使用", _fmt(status.first_ti_received), font_name)
    y -= 5 * mm

    # ── 打印统计 ──
    y = _draw_section_header(cv, y, "打印统计", C_PRINT_SECTION, font_name)
    _draw_divider(cv, y + 2 * mm)
    y -= 2 * mm
    y = _draw_table_row(cv, y, "总页数", _fmt(status.total_print_pages), font_name)
    y = _draw_table_row(cv, y, "总Pass", _fmt(status.total_print_pass), font_name)
    y = _draw_table_row(cv, y, "总扫描", _fmt(status.total_scan_count), font_name)
    y -= 5 * mm

    # ── 墨水系统 ──
    y = _draw_section_header(cv, y, "墨水系统", C_INK_SECTION, font_name)
    _draw_divider(cv, y + 2 * mm)
    y -= 2 * mm

    # 表头
    cv.setFillColor(C_LABEL)
    cv.setFont(font_name, 8)
    cv.drawString(35 * mm, y, "颜色")
    cv.drawString(80 * mm, y, "更换次数")
    y -= 6 * mm

    y = _draw_ink_row(cv, y, "black", "黑色", status.black_ink_replacements, font_name)
    y = _draw_ink_row(cv, y, "cyan", "青色", status.cyan_ink_replacements, font_name)
    y = _draw_ink_row(cv, y, "magenta", "品红", status.magenta_ink_replacements, font_name)
    y = _draw_ink_row(cv, y, "yellow", "黄色", status.yellow_ink_replacements, font_name)
    y -= 3 * mm

    # ── 废墨垫 ──
    y = _draw_section_header(cv, y, "废墨垫", C_WASTE_SECTION, font_name)
    _draw_divider(cv, y + 2 * mm)
    y -= 2 * mm
    y = _draw_table_row(cv, y, "主废墨", _fmt(status.main_waste_ink_pct, "%"), font_name)
    y = _draw_table_row(cv, y, "无边距", _fmt(status.borderless_waste_ink_pct, "%"), font_name)
    y -= 5 * mm

    # ── 错误记录 ──
    y = _draw_section_header(cv, y, "错误记录", C_ERROR_SECTION, font_name)
    _draw_divider(cv, y + 2 * mm)
    y -= 2 * mm
    if status.fatal_errors:
        cv.setFillColor(C_RED)
        cv.setFont(font_name, 9)
        cv.drawString(35 * mm, y, f"发现 {len(status.fatal_errors)} 个致命错误")
    else:
        cv.setFillColor(C_GREEN)
        cv.setFont(font_name, 9)
        cv.drawString(35 * mm, y, "最近无致命错误 ✓")
    y -= 10 * mm

    # 页脚
    cv.setFillColor(C_FOOTER)
    cv.setFont(font_name, 7)
    cv.drawString(30 * mm, 15 * mm, f"epson-keeper v{__version__} | 自动维护报告")

    cv.showPage()


def generate_pdf(
    status: PrinterStatus,
    include_status_page: bool = True,
    output_path: Optional[str] = None,
) -> str:
    """生成 PDF 文件，返回文件路径。

    Args:
        status: 打印机状态（preview 模式可传空 PrinterStatus）
        include_status_page: 是否包含状态页（L416x=True, L415x=False）
        output_path: 输出路径，None 则生成到临时目录
    """
    if output_path is None:
        output_path = next_pdf_path("maintenance")

    cv = canvas_mod.Canvas(output_path, pagesize=A4)
    cv.setTitle("Epson Keeper 维护报告")

    # 第 1 页（可选）：状态报告（含浅色点阵背景）
    if include_status_page:
        draw_status_page(cv, status)

    # 第 2 页：维护色条 + 波浪线 + 点阵
    draw_maintenance_page(cv)

    cv.save()
    logger.info("PDF 已生成: %s", output_path)
    return output_path
