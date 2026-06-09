"""printer_info.py 单元测试"""

from unittest.mock import MagicMock, patch

from epson_keeper.printer_info import PrinterStatus, now_iso8601, query_printer


def _make_mock_printer():
    """创建模拟 EpsonPrinter 实例，匹配真实 epson_print_conf API。"""
    mock = MagicMock()
    mock.get_serial_number.return_value = "X000000000"
    mock.get_firmware_version.return_value = "LF23I6"
    mock.get_printer_head_id.return_value = "HD123"
    mock.get_snmp_info.return_value = {
        "MAC Address": "AA-BB-CC-DD-EE-FF",
        "Model": "L4160 Series",
    }
    mock.stats.return_value = {
        "serial_number": "X000000000",
        "firmware_version": "LF23I6",
        "printer_head_id": "HD123",
        "snmp_info": {"MAC Address": "AA-BB-CC-DD-EE-FF"},
        "printer_status": {"status": "ready"},
        "last_printer_fatal_errors": [],
        "stats": {
            "Total print page counter": 12345,
            "Total print pass counter": 987654,
            "Total scan counter": 234,
            "First TI received time": "2025-03-15",
            "Ink replacement counter - Black": 3,
            "Ink replacement counter - Cyan": 2,
            "Ink replacement counter - Magenta": 2,
            "Ink replacement counter - Yellow": 2,
        },
        "waste_ink_levels": {
            "main_waste": 12.5,
            "borderless_waste": 8.3,
        },
    }
    return mock


class TestPrinterStatus:
    def test_default_fields_are_none(self):
        s = PrinterStatus(query_time="2026-01-01T00:00:00", printer_ip="10.0.0.1")
        assert s.model is None
        assert s.serial_number is None
        assert s.total_print_pages is None
        assert s.fatal_errors is None

    def test_query_time_is_set(self):
        t = now_iso8601()
        assert "T" in t  # ISO 8601


class TestQueryPrinter:
    @patch("epson_keeper.printer_info.EpsonPrinter")
    def test_full_success(self, MockPrinter):
        MockPrinter.return_value = _make_mock_printer()

        status = query_printer("10.0.0.1", "L4160")
        assert status.model == "L4160"
        assert status.serial_number == "X000000000"
        assert status.firmware_version == "LF23I6"
        assert status.printer_head_id == "HD123"
        assert status.mac_address == "AA-BB-CC-DD-EE-FF"
        assert status.total_print_pages == 12345
        assert status.total_print_pass == 987654
        assert status.total_scan_count == 234
        assert status.first_ti_received == "2025-03-15"
        assert status.black_ink_replacements == 3
        assert status.cyan_ink_replacements == 2
        assert status.main_waste_ink_pct == 12.5
        assert status.borderless_waste_ink_pct == 8.3
        assert status.fatal_errors == []
        assert status.snmp_info["MAC Address"] == "AA-BB-CC-DD-EE-FF"

    @patch("epson_keeper.printer_info.EpsonPrinter")
    def test_partial_failure_graceful(self, MockPrinter):
        mock = _make_mock_printer()
        mock.get_serial_number.side_effect = Exception("SNMP timeout")
        MockPrinter.return_value = mock

        status = query_printer("10.0.0.1", "L4160")
        assert status.serial_number is None
        assert status.firmware_version == "LF23I6"
        assert status.total_print_pages == 12345

    @patch("epson_keeper.printer_info.EpsonPrinter")
    def test_stats_returns_none(self, MockPrinter):
        mock = _make_mock_printer()
        mock.stats.return_value = None
        MockPrinter.return_value = mock

        status = query_printer("10.0.0.1", "L4160")
        assert status.serial_number == "X000000000"
        assert status.total_print_pages is None
