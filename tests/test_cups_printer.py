"""cups_printer.py 单元测试"""

from unittest.mock import patch, MagicMock

from epson_keeper.cups_printer import print_pdf


class TestPrintPdf:
    @patch("epson_keeper.cups_printer.subprocess.run")
    def test_print_with_duplex(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="request id is EPSON_L4160_Series-42 (1 file(s))\n"
        )
        job_id = print_pdf("/tmp/test.pdf", "EPSON_L4160", duplex=True)
        assert job_id == 42
        cmd = mock_run.call_args[0][0]
        assert cmd == ["lp", "-d", "EPSON_L4160", "-o", "sides=two-sided-long-edge", "/tmp/test.pdf"]

    @patch("epson_keeper.cups_printer.subprocess.run")
    def test_print_without_duplex(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="request id is EPSON_L4150-99 (1 file(s))\n"
        )
        job_id = print_pdf("/tmp/test.pdf", "EPSON_L4150", duplex=False)
        assert job_id == 99
        cmd = mock_run.call_args[0][0]
        assert cmd == ["lp", "-d", "EPSON_L4150", "/tmp/test.pdf"]
