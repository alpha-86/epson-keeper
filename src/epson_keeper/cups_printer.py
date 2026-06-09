"""CUPS 打印封装 — 选项探测 + 双面降级"""

import logging

logger = logging.getLogger(__name__)

try:
    import cups
except ImportError:
    cups = None  # type: ignore

OPTION_PROBE = {
    "ColorModel": ["RGB", "Color", "CMYK"],
    "print-quality": ["4", "5", "3"],
    "sides": ["two-sided-long-edge"],
    "media": ["A4", "A4 Plain"],
}


def detect_printer_options(conn, printer_name: str) -> dict[str, str]:
    """探测 CUPS 打印机支持的选项，返回最佳匹配。"""
    printers = conn.getPrinters()
    info = printers.get(printer_name)
    if not info:
        raise ValueError(f"打印机 {printer_name} 未在 CUPS 中注册")

    supported: dict[str, str] = {}
    for opt, candidates in OPTION_PROBE.items():
        avail = info.get(f"{opt}-supported", [])
        if isinstance(avail, str):
            avail = [avail]
        for c in candidates:
            if c in avail:
                supported[opt] = c
                break
    return supported


def print_pdf(pdf_path: str, printer_name: str, duplex: bool = True) -> int:
    """提交 PDF 到 CUPS 打印，返回 job_id。"""
    if cups is None:
        raise RuntimeError("pycups 未安装，请运行: pip install pycups")

    logger.info("连接 CUPS，打印机=%s, PDF=%s", printer_name, pdf_path)
    conn = cups.Connection()
    logger.info("探测打印机选项...")
    supported = detect_printer_options(conn, printer_name)
    logger.info("探测到的打印选项: %s", supported)

    options: dict[str, str] = {}
    for key in ("media", "ColorModel", "print-quality"):
        if key in supported:
            options[key] = supported[key]

    actual_duplex = False
    if duplex and "sides" in supported:
        options["sides"] = supported["sides"]
        actual_duplex = True
    elif duplex:
        logger.warning("打印机不支持自动双面，降级为单面打印")
    logger.info("提交打印任务: 选项=%s, 双面=%s", options, actual_duplex)

    job_id = conn.printFile(printer_name, pdf_path, "epson-keeper", options)
    logger.info("打印任务已提交: job_id=%s, duplex=%s", job_id, actual_duplex)
    return job_id
