"""配置管理 — 读取 ~/.config/epson-keeper/config.yaml"""

import os
import sys
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path.home() / ".config" / "epson-keeper"
CONFIG_PATH = CONFIG_DIR / "config.yaml"
DEFAULT_CONFIG = {
    "printer": {"ip": "", "model": "L4160", "cups_name": "EPSON_L4160_Series"},
    "schedule": {"cron": "0 21 * * 4"},
    "logging": {"level": "INFO", "file": ""},
}


def _ensure_config_exists() -> Path:
    """配置文件不存在时自动生成模板并退出。"""
    if CONFIG_PATH.exists():
        return CONFIG_PATH
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        yaml.dump(DEFAULT_CONFIG, default_flow_style=False, allow_unicode=True)
    )
    print(f"已生成默认配置: {CONFIG_PATH}", file=sys.stderr)
    print("请编辑配置文件填写 printer.model 和 printer.cups_name 后重试", file=sys.stderr)
    sys.exit(1)


def load_config() -> dict[str, Any]:
    """加载配置文件，返回字典。"""
    _ensure_config_exists()
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        print(f"配置文件格式错误: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    return cfg


def get(key: str, default: Any = None) -> Any:
    """用点分路径读取配置值，如 'printer.ip'。"""
    cfg = load_config()
    parts = key.split(".")
    node = cfg
    for part in parts:
        if not isinstance(node, dict):
            return default
        node = node.get(part, default)
    return node
