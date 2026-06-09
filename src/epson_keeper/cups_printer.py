"""CUPS 打印封装 — lp 命令"""

import logging
import re
import subprocess

logger = logging.getLogger(__name__)


def print_pdf(pdf_path: str, printer_name: str, duplex: bool = True) -> int:
    """提交 PDF 到 CUPS 打印，返回 job_id。"""
    cmd = ["lp", "-d", printer_name, "-o", "media=A4"]
    if duplex:
        cmd += ["-o", "sides=two-sided-long-edge"]
    cmd.append(pdf_path)

    logger.info("执行 lp 命令: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    output = result.stdout.strip()
    logger.info("lp 输出: %s", output)

    # 解析 job_id: "request id is EPSON_L4160_Series-123 (1 file(s))"
    m = re.search(r"-(\d+)\s", output)
    job_id = int(m.group(1)) if m else 0
    logger.info("打印任务已提交: job_id=%s", job_id)
    return job_id
