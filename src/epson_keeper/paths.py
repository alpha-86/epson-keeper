"""统一输出目录管理 — 所有运行时产物（PDF、日志）放在 /tmp/epson-keeper/"""

from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("/tmp/epson-keeper")
LOG_FILE = OUTPUT_DIR / "epson-keeper.log"


def ensure_output_dir() -> Path:
    """确保输出目录存在，返回路径。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def next_pdf_path(prefix: str = "maintenance") -> str:
    """生成带日期时间的 PDF 路径，如 /tmp/epson-keeper/maintenance-20260609-214500.pdf。"""
    ensure_output_dir()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return str(OUTPUT_DIR / f"{prefix}-{ts}.pdf")
