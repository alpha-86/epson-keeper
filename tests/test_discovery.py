"""discovery.py 单元测试"""

from unittest.mock import MagicMock, patch

import pytest

from epson_keeper.discovery import DiscoveredPrinter, _check_tcp, _is_epson, discover_printer


class TestIsEpson:
    def test_ty_match(self):
        assert _is_epson({"ty": b"EPSON L4160 Series"}) is True

    def test_usb_MFG_match(self):
        assert _is_epson({"usb_MFG": b"EPSON"}) is True

    def test_no_match(self):
        assert _is_epson({"ty": b"HP LaserJet"}) is False

    def test_empty(self):
        assert _is_epson({}) is False

    def test_case_insensitive(self):
        assert _is_epson({"ty": b"Epson L4160"}) is True

    def test_bytes_keys(self):
        """zeroconf 0.130+ 使用 bytes 作为 txt record key。"""
        assert _is_epson({b"ty": b"EPSON L4160 Series"}) is True
        assert _is_epson({b"usb_MFG": b"EPSON"}) is True
        assert _is_epson({b"ty": b"HP LaserJet"}) is False


class TestDiscoverPrinterManualIP:
    @patch("epson_keeper.discovery._check_tcp", return_value=True)
    def test_manual_ip_success(self, mock_tcp):
        result = discover_printer("192.168.1.100")
        assert result.ip == "192.168.1.100"
        assert result.name == "manual"
        assert result.model_hint is None

    @patch("epson_keeper.discovery._check_tcp", return_value=False)
    def test_manual_ip_unreachable(self, mock_tcp):
        with pytest.raises(SystemExit, match="不可达"):
            discover_printer("192.168.1.999")


class TestDiscoverPrinterMDNS:
    @patch("epson_keeper.discovery._check_tcp", return_value=True)
    def test_manual_ip_takes_priority(self, mock_tcp):
        result = discover_printer("10.0.0.1")
        assert result.ip == "10.0.0.1"
        mock_tcp.assert_called_once_with("10.0.0.1")
