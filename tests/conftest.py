"""共享 mock — 在模块级别 mock 外部硬依赖（epson_print_conf, cups）"""

import sys
from unittest.mock import MagicMock

# 在测试模块被收集之前 mock，避免 ImportError
# epson_print_conf 不在 PyPI，需要从 GitHub 安装
if "epson_print_conf" not in sys.modules:
    sys.modules["epson_print_conf"] = MagicMock()

# cups 需要系统 CUPS 开发库（libcups2-dev），测试环境可能没有
if "cups" not in sys.modules:
    sys.modules["cups"] = MagicMock()
