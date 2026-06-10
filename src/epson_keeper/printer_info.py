"""打印机信息采集 — 使用 epson_print_conf 查询打印机状态"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from epson_print_conf import EpsonPrinter

logger = logging.getLogger(__name__)


@dataclass
class PrinterStatus:
    # 元数据（始终有值）
    query_time: str  # ISO 8601
    printer_ip: str

    # 以下全部 Optional，查询失败时为 None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    firmware_version: Optional[str] = None
    mac_address: Optional[str] = None
    printer_head_id: Optional[str] = None
    first_ti_received: Optional[str] = None

    total_print_pages: Optional[int] = None
    total_print_pass: Optional[int] = None
    total_scan_count: Optional[int] = None

    black_ink_replacements: Optional[int] = None
    cyan_ink_replacements: Optional[int] = None
    magenta_ink_replacements: Optional[int] = None
    yellow_ink_replacements: Optional[int] = None

    main_waste_ink_pct: Optional[float] = None
    borderless_waste_ink_pct: Optional[float] = None

    fatal_errors: Optional[list] = field(default=None)
    printer_status: Optional[dict] = field(default=None)
    snmp_info: Optional[dict] = field(default=None)


def now_iso8601() -> str:
    """返回当前时间的 ISO 8601 字符串（精确到秒）。"""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _safe_call(fn, *args, **kwargs) -> Any:
    """安全调用函数，失败返回 None。"""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        fn_name = getattr(fn, "__name__", str(fn))
        logger.debug("查询失败 (%s): %s", fn_name, e)
        return None


def query_printer(ip: str, model: str) -> PrinterStatus:
    """查询打印机状态。

    调用 epson_print_conf 的 SNMP/EEPROM 接口逐字段查询，
    单个字段失败不阻塞其他字段（填 None，PDF 显示"未知"）。
    """
    status = PrinterStatus(query_time=now_iso8601(), printer_ip=ip)

    logger.info("连接打印机 %s (型号=%s)...", ip, model)
    printer = EpsonPrinter(model=model, hostname=ip)
    status.model = model

    # 基本信息
    logger.info("查询基本信息...")
    status.serial_number = _safe_call(printer.get_serial_number)
    status.firmware_version = _safe_call(printer.get_firmware_version)
    status.printer_head_id = _safe_call(printer.get_printer_head_id)

    # MAC 地址来自 SNMP info
    logger.info("查询 SNMP 信息...")
    snmp_info = _safe_call(printer.get_snmp_info)
    if snmp_info:
        status.snmp_info = snmp_info
        status.mac_address = snmp_info.get("MAC Address")

    # stats() 汇总所有 get_* 方法的结果
    logger.info("查询打印统计 (stats)...")
    all_stats = _safe_call(printer.stats)
    if all_stats:
        # stats 子字典（打印计数等）
        sub_stats = all_stats.get("stats")
        if sub_stats and isinstance(sub_stats, dict):
            status.total_print_pages = sub_stats.get("Total print page counter")
            status.total_print_pass = sub_stats.get("Total print pass counter")
            status.total_scan_count = sub_stats.get("Total scan counter")
            status.first_ti_received = sub_stats.get("First TI received time")

            # 墨水更换计数（在 stats 子字典中）
            status.black_ink_replacements = sub_stats.get("Ink replacement counter - Black")
            status.cyan_ink_replacements = sub_stats.get("Ink replacement counter - Cyan")
            status.magenta_ink_replacements = sub_stats.get("Ink replacement counter - Magenta")
            status.yellow_ink_replacements = sub_stats.get("Ink replacement counter - Yellow")

        # 废墨垫
        waste = all_stats.get("waste_ink_levels")
        if waste and isinstance(waste, dict):
            status.main_waste_ink_pct = waste.get("main_waste")
            status.borderless_waste_ink_pct = waste.get("borderless_waste")

        # 打印机状态和错误
        status.printer_status = all_stats.get("printer_status")
        status.fatal_errors = all_stats.get("last_printer_fatal_errors")

    logger.info("查询完成: 序列号=%s, 总页数=%s, 主废墨=%s%%",
                status.serial_number, status.total_print_pages, status.main_waste_ink_pct)
    return status
