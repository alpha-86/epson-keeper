"""CLI 入口 — click 命令定义"""

import logging
import sys
from pathlib import Path

import click

from epson_keeper import __version__
from epson_keeper.paths import ensure_output_dir, LOG_FILE, next_pdf_path

logger = logging.getLogger(__name__)


def _setup_logging(level: str = "INFO", log_file: str = ""):
    """配置日志：始终写 stderr + /tmp/epson-keeper/epson-keeper.log。"""
    ensure_output_dir()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger()
    # 清除已有 handlers，避免 basicConfig no-op
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    stderr_h = logging.StreamHandler(sys.stderr)
    stderr_h.setFormatter(fmt)
    root.addHandler(stderr_h)

    file_h = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    file_h.setFormatter(fmt)
    root.addHandler(file_h)

    if log_file:
        extra_h = logging.FileHandler(log_file, encoding="utf-8")
        extra_h.setFormatter(fmt)
        root.addHandler(extra_h)

    logger.info("日志文件: %s", LOG_FILE)


@click.group()
@click.version_option(__version__)
def main():
    """Epson Keeper — Epson 打印机自动维护工具"""


@main.command()
@click.option("--single-page", is_flag=True, help="只生成维护页（L415x 模式），不包含状态页")
def preview(single_page: bool):
    """预览 PDF（不连接打印机）"""
    from epson_keeper.config import load_config
    from epson_keeper.pdf_generator import generate_pdf
    from epson_keeper.printer_info import PrinterStatus, now_iso8601

    cfg = load_config()
    _setup_logging(cfg.get("logging", {}).get("level", "INFO"),
                   cfg.get("logging", {}).get("file", ""))

    logger.info("=== 开始预览 ===")
    include_status = not single_page
    status = PrinterStatus(query_time=now_iso8601(), printer_ip="preview")

    out_path = next_pdf_path("maintenance")
    logger.info("生成 PDF: %s (状态页=%s)", out_path, include_status)
    pdf_path = generate_pdf(status, include_status_page=include_status, output_path=out_path)
    logger.info("=== 预览完成 ===")
    click.echo(f"PDF 已生成: {pdf_path}")
    click.echo(f"  页数: {1 if single_page else 2}")


@main.command()
def status():
    """查询打印机状态（输出到终端）"""
    from epson_keeper.config import get
    from epson_keeper.discovery import discover_printer
    from epson_keeper.printer_info import query_printer

    cfg_ip = get("printer.ip") or None
    model = get("printer.model")
    if not model:
        click.echo("错误: 请在 config.yaml 中配置 printer.model", err=True)
        sys.exit(1)

    _setup_logging()
    logger.info("=== 查询打印机状态 ===")

    printer = discover_printer(cfg_ip)
    click.echo(f"发现打印机: {printer.name} ({printer.ip})")

    logger.info("开始查询打印机详细信息...")
    info = query_printer(printer.ip, model)
    logger.info("查询完成: 序列号=%s, 总页数=%s", info.serial_number, info.total_print_pages)

    click.echo("\n── 设备信息 ──")
    click.echo(f"  型号:       {_v(info.model)}")
    click.echo(f"  序列号:     {_v(info.serial_number)}")
    click.echo(f"  固件:       {_v(info.firmware_version)}")
    click.echo(f"  MAC:        {_v(info.mac_address)}")
    click.echo(f"  打印头ID:   {_v(info.printer_head_id)}")
    click.echo(f"  首次使用:   {_v(info.first_ti_received)}")

    click.echo("\n── 打印统计 ──")
    click.echo(f"  总页数:     {_v(info.total_print_pages)}")
    click.echo(f"  总Pass:     {_v(info.total_print_pass)}")
    click.echo(f"  总扫描:     {_v(info.total_scan_count)}")

    click.echo("\n── 废墨垫 ──")
    click.echo(f"  主废墨:     {_v(info.main_waste_ink_pct, '%')}")
    click.echo(f"  无边距:     {_v(info.borderless_waste_ink_pct, '%')}")

    logger.info("=== 状态查询完成 ===")


def _v(value, suffix: str = "") -> str:
    if value is None:
        return "未知"
    if isinstance(value, (int, float)):
        return f"{value:,}{suffix}"
    return str(value)


@main.command()
def run():
    """执行完整维护（查询 → 生成 PDF → 打印）"""
    from epson_keeper.config import get
    from epson_keeper.discovery import discover_printer, save_printer_ip
    from epson_keeper.printer_info import query_printer
    from epson_keeper.pdf_generator import generate_pdf
    from epson_keeper.cups_printer import print_pdf as cups_print

    model = get("printer.model")
    cups_name = get("printer.cups_name")
    if not model or not cups_name:
        click.echo("错误: 请在 config.yaml 中配置 printer.model 和 printer.cups_name", err=True)
        sys.exit(1)

    _setup_logging()
    logger.info("=== 开始维护流程 === 型号=%s, CUPS=%s", model, cups_name)

    is_l415x = model.startswith("L415")
    include_status = not is_l415x
    logger.info("机型判断: %s, 双面=%s", model, include_status)

    # 1. 发现打印机
    logger.info("[阶段 1/4] 发现打印机...")
    cfg_ip = get("printer.ip") or None
    printer = discover_printer(cfg_ip)
    click.echo(f"发现打印机: {printer.name} ({printer.ip})")
    logger.info("打印机已发现: %s (%s)", printer.name, printer.ip)

    # mDNS 发现后保存 IP，下次直接用，避免重复扫描
    if printer.name != "manual" and printer.ip:
        save_printer_ip(printer.ip)

    # 2. 查询状态
    logger.info("[阶段 2/4] 查询打印机状态...")
    info = query_printer(printer.ip, model)
    logger.info("状态查询完成: 序列号=%s, 总页数=%s, 主废墨=%s%%",
                info.serial_number, info.total_print_pages, info.main_waste_ink_pct)

    # 3. 生成 PDF
    logger.info("[阶段 3/4] 生成 PDF...")
    pdf_path = generate_pdf(info, include_status_page=include_status)
    click.echo(f"PDF 已生成: {pdf_path}")
    logger.info("PDF 生成完成: %s", pdf_path)

    # 4. 打印
    logger.info("[阶段 4/4] 提交打印任务...")
    try:
        job_id = cups_print(pdf_path, cups_name, duplex=include_status)
        click.echo(f"打印任务已提交: job_id={job_id}")
        logger.info("打印任务提交成功: job_id=%s", job_id)
    except Exception as e:
        logger.error("打印失败: %s", e)
        click.echo(f"打印失败，PDF 已保留: {pdf_path}", err=True)
        sys.exit(1)

    logger.info("=== 维护流程完成 ===")


@main.command("install")
@click.option("--venv", "venv_path", default="", help="指定 venv 路径")
@click.option("--dry-run", is_flag=True, help="只打印操作，不实际执行")
def install_cmd(venv_path: str, dry_run: bool):
    """安装定时任务（调用 install.sh）"""
    candidates = [
        Path.cwd() / "install.sh",
        Path(__file__).resolve().parent.parent.parent / "install.sh",
    ]
    script = None
    for p in candidates:
        if p.exists():
            script = p
            break
    if script is None:
        click.echo("错误: 找不到 install.sh，请在项目源码目录下运行此命令", err=True)
        sys.exit(1)

    cmd = ["bash", str(script)]
    if venv_path:
        cmd += ["--venv", venv_path]
    if dry_run:
        cmd.append("--dry-run")

    import subprocess
    result = subprocess.run(cmd)
    sys.exit(result.returncode)
