"""cups_printer.py 单元测试"""

from unittest.mock import MagicMock, patch

import pytest

from epson_keeper.cups_printer import detect_printer_options, print_pdf


class TestDetectPrinterOptions:
    def test_detects_supported(self):
        mock_conn = MagicMock()
        mock_conn.getPrinters.return_value = {
            "EPSON_L4160": {
                "sides-supported": ["two-sided-long-edge"],
                "ColorModel-supported": ["RGB"],
                "print-quality-supported": ["4", "5"],
                "media-supported": ["A4"],
            }
        }
        result = detect_printer_options(mock_conn, "EPSON_L4160")
        assert result["sides"] == "two-sided-long-edge"
        assert result["ColorModel"] == "RGB"
        assert result["media"] == "A4"
        assert result["print-quality"] == "4"

    def test_printer_not_found(self):
        mock_conn = MagicMock()
        mock_conn.getPrinters.return_value = {}
        with pytest.raises(ValueError, match="未在 CUPS 中注册"):
            detect_printer_options(mock_conn, "MISSING")

    def test_no_sides_support(self):
        mock_conn = MagicMock()
        mock_conn.getPrinters.return_value = {
            "EPSON_L4150": {
                "ColorModel-supported": ["RGB"],
                "media-supported": ["A4"],
            }
        }
        result = detect_printer_options(mock_conn, "EPSON_L4150")
        assert "sides" not in result


class TestPrintPdf:
    @patch("epson_keeper.cups_printer.cups")
    def test_print_with_duplex(self, mock_cups_mod):
        mock_conn = MagicMock()
        mock_conn.getPrinters.return_value = {
            "EPSON_L4160": {
                "sides-supported": ["two-sided-long-edge"],
                "ColorModel-supported": ["RGB"],
                "print-quality-supported": ["4"],
                "media-supported": ["A4"],
            }
        }
        mock_conn.printFile.return_value = 42
        mock_cups_mod.Connection.return_value = mock_conn

        job_id = print_pdf("/tmp/test.pdf", "EPSON_L4160", duplex=True)
        assert job_id == 42
        mock_conn.printFile.assert_called_once()
        call_opts = mock_conn.printFile.call_args[0][3]
        assert call_opts["sides"] == "two-sided-long-edge"

    @patch("epson_keeper.cups_printer.cups")
    def test_print_without_duplex(self, mock_cups_mod):
        mock_conn = MagicMock()
        mock_conn.getPrinters.return_value = {
            "EPSON_L4150": {
                "ColorModel-supported": ["RGB"],
                "media-supported": ["A4"],
            }
        }
        mock_conn.printFile.return_value = 99
        mock_cups_mod.Connection.return_value = mock_conn

        job_id = print_pdf("/tmp/test.pdf", "EPSON_L4150", duplex=False)
        assert job_id == 99
        call_opts = mock_conn.printFile.call_args[0][3]
        assert "sides" not in call_opts
