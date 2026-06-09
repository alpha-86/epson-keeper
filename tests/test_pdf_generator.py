"""pdf_generator.py 单元测试 — PDF 结构验证"""

import re
import tempfile
from pathlib import Path

import pytest

from epson_keeper.pdf_generator import generate_pdf
from epson_keeper.printer_info import PrinterStatus, now_iso8601


def _empty_status() -> PrinterStatus:
    return PrinterStatus(query_time=now_iso8601(), printer_ip="")


def _full_status() -> PrinterStatus:
    return PrinterStatus(
        query_time="2026-06-09T21:00:15",
        printer_ip="192.168.1.100",
        model="L4160",
        serial_number="X000000000",
        firmware_version="LF23I6",
        mac_address="AA:BB:CC:DD:EE:FF",
        total_print_pages=12345,
        fatal_errors=[],
    )


def _extract_text(pdf_path: str, page: int = 0) -> str:
    """提取 PDF 指定页的文本内容。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader
    reader = PdfReader(pdf_path)
    return reader.pages[page].extract_text() or ""


class TestPDFStructure:
    def test_two_pages(self, tmp_path):
        pdf_path = str(tmp_path / "test.pdf")
        generate_pdf(_empty_status(), include_status_page=True, output_path=pdf_path)
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(pdf_path)
        assert len(reader.pages) == 2

    def test_single_page(self, tmp_path):
        pdf_path = str(tmp_path / "test.pdf")
        generate_pdf(_empty_status(), include_status_page=False, output_path=pdf_path)
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(pdf_path)
        assert len(reader.pages) == 1

    def test_status_page_contains_serial(self, tmp_path):
        pdf_path = str(tmp_path / "test.pdf")
        generate_pdf(_full_status(), include_status_page=True, output_path=pdf_path)
        text = _extract_text(pdf_path, page=0)
        assert "X000000000" in text

    def test_status_page_contains_timestamp(self, tmp_path):
        pdf_path = str(tmp_path / "test.pdf")
        generate_pdf(_full_status(), include_status_page=True, output_path=pdf_path)
        text = _extract_text(pdf_path, page=0)
        assert re.search(r"\d{4}-\d{2}-\d{2}", text)

    def test_none_fields_show_unknown(self, tmp_path):
        """preview 模式使用空 PrinterStatus，所有字段应显示'未知'。"""
        pdf_path = str(tmp_path / "test.pdf")
        generate_pdf(_empty_status(), include_status_page=True, output_path=pdf_path)
        text = _extract_text(pdf_path, page=0)
        # "未知" 应出现多次（每个 None 字段）
        assert text.count("未知") >= 5
