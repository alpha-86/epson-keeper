"""cli.py 集成测试 — 端到端 CLI 命令（mock 外部 I/O）"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from epson_keeper.cli import main


def _write_config(tmp_path: Path, overrides: dict = None) -> Path:
    data = {
        "printer": {"ip": "", "model": "L4160", "cups_name": "EPSON_L4160_Series"},
        "schedule": {"cron": "0 21 * * 4"},
        "logging": {"level": "DEBUG", "file": ""},
    }
    if overrides:
        data.update(overrides)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.dump(data, allow_unicode=True))
    return cfg


class TestPreview:
    @patch("epson_keeper.pdf_generator.generate_pdf")
    def test_preview_default(self, mock_gen, tmp_path, monkeypatch):
        cfg = _write_config(tmp_path)
        monkeypatch.setattr("epson_keeper.config.CONFIG_PATH", cfg)
        monkeypatch.chdir(tmp_path)

        def fake_generate(status, include_status_page=True, output_path=None):
            if output_path is None:
                output_path = str(tmp_path / "epson-keeper-preview.pdf")
            Path(output_path).write_bytes(b"%PDF-1.4 test")
            return output_path

        mock_gen.side_effect = fake_generate

        runner = CliRunner()
        result = runner.invoke(main, ["preview"])
        assert result.exit_code == 0, result.output + str(result.exception)
        assert "PDF 已生成" in result.output

    def test_preview_single_page(self, tmp_path, monkeypatch):
        cfg = _write_config(tmp_path)
        monkeypatch.setattr("epson_keeper.config.CONFIG_PATH", cfg)
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(main, ["preview", "--single-page"])
        assert result.exit_code == 0
        assert "页数: 1" in result.output


class TestStatus:
    @patch("epson_keeper.discovery.discover_printer")
    @patch("epson_keeper.printer_info.query_printer")
    def test_status_success(self, mock_query, mock_discover, tmp_path, monkeypatch):
        cfg = _write_config(tmp_path)
        monkeypatch.setattr("epson_keeper.config.CONFIG_PATH", cfg)

        mock_discover.return_value = MagicMock(ip="10.0.0.1", name="EPSON L4160")
        mock_status = MagicMock()
        mock_status.model = "L4160"
        mock_status.serial_number = "X000000000"
        mock_status.firmware_version = "LF23I6"
        mock_status.mac_address = "AA:BB:CC:DD:EE:FF"
        mock_status.printer_head_id = None
        mock_status.first_ti_received = None
        mock_status.total_print_pages = 100
        mock_status.total_print_pass = 500
        mock_status.total_scan_count = 10
        mock_status.main_waste_ink_pct = 5.0
        mock_status.borderless_waste_ink_pct = 3.0
        mock_query.return_value = mock_status

        runner = CliRunner()
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0, result.output + str(result.exception)
        assert "X000000000" in result.output
        assert "未知" in result.output


class TestRun:
    @patch("epson_keeper.cups_printer.print_pdf")
    @patch("epson_keeper.pdf_generator.generate_pdf")
    @patch("epson_keeper.printer_info.query_printer")
    @patch("epson_keeper.discovery.discover_printer")
    def test_run_with_yes(self, mock_discover, mock_query, mock_gen, mock_print,
                          tmp_path, monkeypatch):
        cfg = _write_config(tmp_path)
        monkeypatch.setattr("epson_keeper.config.CONFIG_PATH", cfg)

        mock_discover.return_value = MagicMock(ip="10.0.0.1", name="EPSON L4160")
        mock_query.return_value = MagicMock()
        mock_gen.return_value = "/tmp/test.pdf"
        mock_print.return_value = 42

        runner = CliRunner()
        result = runner.invoke(main, ["run", "--yes"])
        assert result.exit_code == 0, result.output + str(result.exception)
        assert "job_id=42" in result.output


class TestVersion:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output
