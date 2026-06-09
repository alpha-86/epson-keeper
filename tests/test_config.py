"""config.py 单元测试"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


def _write_config(tmp_dir: Path, data: dict) -> Path:
    cfg_path = tmp_dir / "config.yaml"
    cfg_path.write_text(yaml.dump(data, allow_unicode=True))
    return cfg_path


class TestGet:
    def test_get_flat_key(self, tmp_path):
        cfg = _write_config(tmp_path, {"printer": {"ip": "10.0.0.1"}})
        with patch("epson_keeper.config.CONFIG_PATH", cfg):
            from epson_keeper.config import get
            assert get("printer.ip") == "10.0.0.1"

    def test_get_missing_returns_default(self, tmp_path):
        cfg = _write_config(tmp_path, {"printer": {"ip": ""}})
        with patch("epson_keeper.config.CONFIG_PATH", cfg):
            from epson_keeper.config import get
            assert get("printer.missing", "fallback") == "fallback"

    def test_get_default_none(self, tmp_path):
        cfg = _write_config(tmp_path, {"printer": {}})
        with patch("epson_keeper.config.CONFIG_PATH", cfg):
            from epson_keeper.config import get
            assert get("printer.no_key") is None


class TestLoadConfig:
    def test_load_returns_dict(self, tmp_path):
        data = {"printer": {"model": "L4160"}}
        cfg = _write_config(tmp_path, data)
        with patch("epson_keeper.config.CONFIG_PATH", cfg):
            from epson_keeper.config import load_config
            result = load_config()
            assert result["printer"]["model"] == "L4160"
