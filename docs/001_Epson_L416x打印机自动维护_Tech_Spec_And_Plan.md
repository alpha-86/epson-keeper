# 001 - Epson Keeper 技术规格与开发计划

> 版本: 2.3 | 日期: 2026-06-09 | 状态: Draft
>
> **MVP 范围**：mDNS 自动发现单台 Epson 打印机（手动 IP 作为 fallback），核心维护打印。

## 1. 概述

Epson Keeper 是一个自动化维护工具，针对 Epson L415x/L416x 系列墨仓式打印机，通过每周定时打印维护页来防止喷头堵塞。

**核心目标**：
- 保持所有喷嘴通道（C/M/Y/K）畅通，防止墨水干涸
- 最小化墨水消耗（年消耗 < 总墨量 1.5%）
- 记录打印机健康状态，便于长期追踪

## 2. 支持范围

### 2.1 打印机型号

| 系列 | 型号 | 自动双面 | 维护策略 |
|------|------|----------|----------|
| L415x | L4150, L4152, L4154, L4156, L4158 | 否 | 只打印维护页（无状态页），避免浪费纸 |
| L416x | L4160, L4162, L4164, L4166, L4168 | 是 | 双面打印：正面维护页 + 背面状态页 |

> **型号差异**：L415x 无自动双面硬件，为节省纸张只打印单面维护页（色条+波浪线+点阵图），不打印状态报告。L416x 全系列支持自动双面，正面维护页、背面状态报告。`epson_print_conf` 将 L415x 视为 L4160 的配置别名（EEPROM 参数相同）。

### 2.2 运行环境

- Python >= 3.10
- Linux（依赖 CUPS 打印系统）
- 打印机通过 Wi-Fi 连接同一局域网（自动发现，或手动配置 IP）

## 3. 系统架构

```
epson-keeper/
├── src/epson_keeper/
│   ├── __init__.py
│   ├── cli.py                  # CLI 入口 (click)
│   ├── config.py               # 配置管理
│   ├── discovery.py            # mDNS 自动发现 + 手动 IP fallback
│   ├── printer_info.py         # epson_print_conf 封装
│   ├── pdf_generator.py        # reportlab PDF 生成
│   ├── cups_printer.py         # CUPS 打印封装
│   └── maintenance_image.py    # 维护色条/波浪线/点阵绘制
├── tests/
│   ├── test_config.py
│   ├── test_printer_info.py
│   ├── test_pdf_generator.py
│   ├── test_maintenance_image.py
│   └── test_cups_printer.py
├── config.example.yaml
├── install.sh
├── pyproject.toml
└── docs/
```

> **后续增强**：`assets/sample_photo.jpg`（内置照片）、多台打印机遍历将在 MVP 验证后添加。

## 4. 模块设计

### 4.1 打印机发现 (`discovery.py`)

**策略**：配置 `printer.ip` 手动指定优先；未配置时通过 mDNS 自动发现。不做 SNMP 子网扫描。

```
1. 读取 config.yaml 中的 printer.ip
2. 若 printer.ip 非空：
   a. TCP connect 打印机 IP:9100（超时 3 秒）
   b. 可达 → 使用该 IP
   c. 不可达 → 报错退出（退出码 1），提示检查 IP/网络/电源
3. 若 printer.ip 为空（自动发现）：
   a. mDNS 浏览 _ipp._tcp.local.（超时 10 秒）
   b. 筛选 txt record 中 ty 或 usb_MFG 包含 "EPSON" 的服务
   c. 匹配 0 台 → 报错退出，提示配置 printer.ip
   d. 匹配 1 台 → 使用该 IP（从 service address 解析）
   e. 匹配 >1 台 → 报错退出，列出发现的打印机，提示配置 printer.ip 选择
4. IP 确定后，用 epson_print_conf（SNMP）查询打印机状态（失败不阻塞）
```

**依赖**：`zeroconf`（mDNS 浏览）

### 4.2 打印机信息采集 (`printer_info.py`)

使用 `epson_print_conf.EpsonPrinter` 查询打印机状态。

**重要**：状态查询失败 **不能阻塞** `preview` 或 `run`。所有字段为 `Optional`，查询失败时填充 `None`，PDF 中对应位置显示"未知"。

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class PrinterStatus:
    # 元数据（始终有值）
    query_time: str                       # ISO 8601 含时区
    printer_ip: str

    # 以下全部 Optional，查询失败时为 None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    firmware_version: Optional[str] = None
    mac_address: Optional[str] = None
    printer_head_id: Optional[str] = None
    first_ti_received: Optional[str] = None

    total_print_pages: Optional[int] = None
    total_print_pass: Optional[int] = None
    total_scan_count: Optional[int] = None

    black_ink_replacements: Optional[int] = None
    cyan_ink_replacements: Optional[int] = None
    magenta_ink_replacements: Optional[int] = None
    yellow_ink_replacements: Optional[int] = None

    main_waste_ink_pct: Optional[float] = None
    borderless_waste_ink_pct: Optional[float] = None

    fatal_errors: Optional[list] = None
    printer_status: Optional[dict] = None
    snmp_info: Optional[dict] = None
```

**降级逻辑**：

```python
def query_printer(ip: str, model: str) -> PrinterStatus:
    status = PrinterStatus(query_time=now_iso8601(), printer_ip=ip)
    try:
        printer = EpsonPrinter(model=model, hostname=ip)
        status.model = model
        status.serial_number = printer.get_serial_number()
        # ... 逐字段 try/except
    except Exception as e:
        logger.warning("打印机查询部分失败: %s", e)
    return status  # 始终返回，不抛异常
```

### 4.3 PDF 生成 (`pdf_generator.py`)

使用 `reportlab` 生成 A4 PDF。

**页面策略**：
- L416x（支持双面）：生成 2 页 PDF，第 1 页状态报告、第 2 页维护色条+波浪线+点阵
- L415x（不支持双面）：生成 **1 页 PDF**，仅维护色条+波浪线+点阵（不浪费纸打印状态页）

#### 第 1 页：打印机状态报告

**设计原则**：
- 精确时间戳（含时区，格式：`2026-06-09 21:00:00 +08:00`）
- 黑色 + 彩色混合排版，日常黑色消耗多，信息页用彩色文字平衡
- 字段为 None 时显示"未知"，不隐藏该行

**页面布局**：

```
┌─────────────────────────────────────┐
│  ■ Epson Keeper 维护报告            │ ← 标题：深蓝色
│  生成时间: 2026-06-09 21:00:15      │ ← 灰色小字
│  +08:00                             │
├─────────────────────────────────────┤
│  设备信息                            │ ← 小节标题：青色
│  ┌──────────┬──────────────────────┐ │
│  │ 型号     │ L4160                │ │ ← 标签黑色，值深蓝色
│  │ 序列号   │ X58B240789           │ │
│  │ 固件     │ LF23I6               │ │
│  │ MAC      │ AA:BB:CC:DD:EE:FF    │ │
│  │ 打印头ID │ 未知                  │ │ ← 查询失败时
│  │ 首次使用 │ 2025-03-15           │ │
│  └──────────┴──────────────────────┘ │
├─────────────────────────────────────┤
│  打印统计                            │ ← 小节标题：品红色
│  ┌──────────┬──────────────────────┐ │
│  │ 总页数   │ 12,345               │ │
│  │ 总Pass   │ 987,654              │ │
│  │ 总扫描   │ 234                  │ │
│  └──────────┴──────────────────────┘ │
├─────────────────────────────────────┤
│  墨水系统                            │ ← 小节标题：青色
│  ┌──────────┬───────┬──────────────┐ │
│  │ 颜色     │ 更换  │ 当前状态     │ │
│  ├──────────┼───────┼──────────────┤ │
│  │ ■ 黑色   │ 3次   │ ██████░░ 75% │ │ ← 黑色文字
│  │ ■ 青色   │ 2次   │ ████░░░░ 50% │ │ ← 青色文字
│  │ ■ 品红   │ 2次   │ █████░░░ 65% │ │ ← 品红文字
│  │ ■ 黄色   │ 2次   │ ███░░░░░ 38% │ │ ← 黄色文字
│  └──────────┴───────┴──────────────┘ │
├─────────────────────────────────────┤
│  废墨垫                              │ ← 小节标题：深蓝色
│  ┌──────────┬──────────────────────┐ │
│  │ 主废墨   │ 12.5%                │ │
│  │ 无边距   │ 8.3%                 │ │
│  └──────────┴──────────────────────┘ │
├─────────────────────────────────────┤
│  错误记录                            │ ← 小节标题：品红色
│  最近无致命错误 ✓                    │ ← 绿色；有错误则红色
├─────────────────────────────────────┤
│  epson-keeper v0.1.0 | 自动维护报告  │ ← 页脚灰色
└─────────────────────────────────────┘
```

**颜色方案**：
- 标题/节标题：深蓝 `#1a1a2e`、青色 `#00838f`、品红 `#ad1457` 交替
- 表格标签：黑色 `#212121`
- 表格值：深蓝 `#1565c0`（设备信息）、品红 `#880e4f`（墨水状态）
- 分隔线：灰色 `#e0e0e0`
- 页脚：灰色 `#9e9e9e`

#### 第 2 页：维护色条 + 波浪线 + 点阵图

**设计原则**：覆盖四色喷嘴，全页利用（无大面积留白），低墨量。reportlab Canvas 直接绘制，不依赖 Pillow。

**页面布局**：

```
┌─────────────────────────────────────┐
│  top margin                         │
│                                     │
│  ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒  │ ← K 渐变条 (8mm)
│  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿ │ ← K 多条细波浪线
│          ← 6-8mm 间距 →             │
│  ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒  │ ← C 渐变条 (8mm)
│  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿ │ ← C 多条细波浪线
│          ← 6-8mm 间距 →             │
│  ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒  │ ← M 渐变条 (8mm)
│  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿ │ ← M 多条细波浪线
│          ← 6-8mm 间距 →             │
│  ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒  │ ← Y 渐变条 (8mm)
│  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿ │ ← Y 多条细波浪线
│                                     │
│  · · · · · · · · · · · · · · · · · │ ← 稀疏 CMYK 点阵区域
│  · · · · · · · · · · · · · · · · · │   （下半页）
│  · · · · · · · · · · · · · · · · · │
└─────────────────────────────────────┘
```

**色条规格**：
- 高度：每条 **8mm**，宽度 **185mm**（居中）
- 渐变：左→右，**20%→80%** 浓度（不铺满，避免大面积高墨量）
- 颜色顺序：K → C → M → Y

**波浪线规格**（每颜色 3-4 条细线）：
- 每条线：sin 曲线，线宽 **0.8-1.0pt**，振幅 **1.5-2.5mm**
- 同一颜色 3-4 条线并排，从浅到深渐变（首条 20% → 末条 80%）
- 线间距约 1mm，整体区域高度约 **8-10mm**
- 每页 4-5 个周期

**点阵图区域**（下半页）：
- 稀疏 CMYK 彩色圆形点阵，随机分布，模拟照片纹理
- 点直径：**1.5-2.5mm**，间距 **8-12mm**
- 四色随机分配，覆盖率 **< 3%**
- 纯 reportlab `canvas.circle()` 绘制，不依赖 Pillow 或真实图片
- 区域高度约 **80mm**，宽度 **185mm**（居中）

**总高度分配**：
- 上半部分（色条+波浪线）：4 × (8mm + 9mm) ≈ **68mm**
- 下半部分（点阵图）：**~80mm**
- 全页利用，无大面积留白

> **后续增强**：`draw_maintenance_page()` 接口预留 `photo_path: Optional[str] = None` 参数，后续可替换为真实小照片。

### 4.4 CUPS 打印 (`cups_printer.py`)

`ColorModel`、`print-quality`、`sides` 等选项名称和可选值均由打印机驱动定义。程序先查询 CUPS 打印机能力，再 best-effort 设置。

```python
import cups
import logging

logger = logging.getLogger(__name__)

OPTION_PROBE = {
    "ColorModel":    ["RGB", "Color", "CMYK"],
    "print-quality": ["4", "5", "3"],
    "sides":         ["two-sided-long-edge"],
    "media":         ["A4", "A4 Plain"],
}

def detect_printer_options(conn, printer_name: str) -> dict:
    printers = conn.getPrinters()
    info = printers.get(printer_name)
    if not info:
        raise ValueError(f"打印机 {printer_name} 未在 CUPS 中注册")

    supported = {}
    for opt, candidates in OPTION_PROBE.items():
        avail = info.get(f"{opt}-supported", [])
        if isinstance(avail, str):
            avail = [avail]
        for c in candidates:
            if c in avail:
                supported[opt] = c
                break
    return supported

def print_pdf(pdf_path: str, printer_name: str, duplex: bool = True):
    conn = cups.Connection()
    supported = detect_printer_options(conn, printer_name)
    logger.info("探测到的打印选项: %s", supported)

    options = {}
    for key in ("media", "ColorModel", "print-quality"):
        if key in supported:
            options[key] = supported[key]

    actual_duplex = False
    if duplex and "sides" in supported:
        options["sides"] = supported["sides"]
        actual_duplex = True
    elif duplex:
        logger.warning("打印机不支持自动双面，降级为单面打印")

    job_id = conn.printFile(printer_name, pdf_path, "epson-keeper", options)
    logger.info("打印任务已提交: job_id=%s, duplex=%s", job_id, actual_duplex)
    return job_id
```

**降级策略**：
- 打印机不支持双面（L415x）→ **只生成 1 页维护页**（不打印状态页，避免浪费纸）
- 驱动不报告 ColorModel → 跳过（大多数驱动默认彩色）
- 打印机离线 → 报错退出，保留 PDF 供手动打印

### 4.5 安装脚本 (`install.sh`)

**用法**：
```bash
./install.sh                    # 自动选择 venv 并安装
./install.sh --venv ~/myenv     # 使用指定 venv
./install.sh --dry-run          # 只打印将执行的操作，不实际修改
```

**功能**：
1. 检测 Python >= 3.10（遍历 python3.12/3.11/3.10/3）
2. **选择 venv**（优先级从高到低）：
   a. `--venv PATH` 参数指定
   b. 已有 `~/.venv` 或 `~/venv`（检查 `pyvenv.cfg` 存在且 Python 版本 >= 3.10）
   c. 都没有 → 创建 `~/.local/share/epson-keeper/venv`
3. `pip install -e .` 安装项目
4. 复制 `config.example.yaml` 到配置目录（若不存在）
5. 安装 crontab 定时任务（marker block 模式）

**Crontab marker block**：

```
# >>> epson-keeper >>>
0 21 * * 4 /path/to/venv/bin/epson-keeper run >> /path/to/cron.log 2>&1
# <<< epson-keeper <<<
```

**安装脚本伪代码**：

```bash
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/epson-keeper"
CONFIG_DIR="$HOME/.config/epson-keeper"
CRON_SCHEDULE="0 21 * * 4"
DRY_RUN=false
VENV_DIR=""   # --venv 参数或自动选择后填充

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --venv)    VENV_DIR="$2"; shift 2 ;;
    *)         echo "未知参数: $1"; exit 1 ;;
  esac
done

# 每个步骤显式执行，dry-run 只打印不执行
step() {
  echo ">>> $*"
  if ! $DRY_RUN; then "$@"; fi
}

# ── 检测 Python >= 3.10 ──
PYTHON=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" &>/dev/null; then
    ver=$("$c" -c "import sys;print(sys.version_info.minor)")
    [ "$ver" -ge 10 ] 2>/dev/null && PYTHON="$c" && break
  fi
done
[ -z "$PYTHON" ] && echo "错误: 需要 Python >= 3.10" && exit 1

# ── 选择 venv（优先级：--venv > ~/.venv > ~/venv > 创建新 venv）──
if [ -z "$VENV_DIR" ]; then
  for candidate in "$HOME/.venv" "$HOME/venv"; do
    if [ -f "$candidate/pyvenv.cfg" ]; then
      VENV_DIR="$candidate"
      echo "复用已有 venv: $VENV_DIR"
      break
    fi
  done
fi
if [ -z "$VENV_DIR" ]; then
  VENV_DIR="$INSTALL_DIR/venv"
  step "$PYTHON" -m venv "$VENV_DIR"
fi

# ── 安装 ──
step mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
step cp -r "$SCRIPT_DIR/src/" "$INSTALL_DIR/"
step cp "$SCRIPT_DIR/pyproject.toml" "$INSTALL_DIR/"
step "$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"

if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
  step cp "$SCRIPT_DIR/config.example.yaml" "$CONFIG_DIR/config.yaml"
fi

# ── crontab marker block（保留用户已有条目）──
CRON_CMD="$CRON_SCHEDULE $VENV_DIR/bin/epson-keeper run >> $INSTALL_DIR/cron.log 2>&1"
EXISTING=$(crontab -l 2>/dev/null || true)
CLEANED=$(echo "$EXISTING" | sed '/# >>> epson-keeper >>>/,/# <<< epson-keeper <<</d')
NEW_CRONTAB=$(printf '%s\n%s\n%s\n%s\n' \
  "$CLEANED" \
  "# >>> epson-keeper >>>" \
  "$CRON_CMD" \
  "# <<< epson-keeper <<<")
if $DRY_RUN; then
  echo "[dry-run] crontab 内容:"
  echo "$NEW_CRONTAB"
else
  echo "$NEW_CRONTAB" | crontab -
fi

echo "安装完成！配置: $CONFIG_DIR/config.yaml | 定时: 每周四 21:00"
```

> **后续增强**：`--uninstall` 选项（移除 crontab block + venv）。

## 5. 配置文件 (`config.yaml`)

```yaml
printer:
  ip: ""                 # 可选，留空则自动发现（mDNS）；手动指定 IP 作为 fallback
  model: "L4160"         # 必填，用于 epson_print_conf
  cups_name: "EPSON_L4160_Series"  # 必填，CUPS 队列名称（运行 `lpstat -p` 查看）

schedule:
  cron: "0 21 * * 4"     # 每周四 21:00

logging:
  level: "INFO"
  file: ""               # 留空则只输出到 stderr
```

> L415x 用户无需配置 `duplex`（自动检测不支持双面，只打印维护页）。

## 6. CLI 命令

```bash
# 预览 PDF（生成到当前目录，不打印，不连接打印机）← 首先验证此命令
# 使用空 PrinterStatus 生成，所有字段显示"未知"，验证 PDF 结构和排版
epson-keeper preview

# 仅查询打印机状态（输出到终端）
epson-keeper status

# 执行完整维护（查询 → 生成 PDF → 打印，需用户确认）
epson-keeper run
epson-keeper run --yes          # 跳过确认（cron 定时任务使用）

# 安装定时任务
epson-keeper install
```

**交付验证顺序**：`preview` → `status` → 真实 `run`（需用户确认）。

## 7. 错误处理

| 场景 | 处理方式 |
|------|----------|
| 配置文件不存在 | 自动生成默认 config.yaml 模板，退出（退出码 1），提示填写 model/cups_name |
| model 或 cups_name 为空 | 报错退出，提示编辑 config.yaml |
| mDNS 发现 0 台打印机 | 报错退出，提示检查打印机电源/网络，或手动配置 printer.ip |
| mDNS 发现 >1 台打印机 | 报错退出，列出发现的打印机 IP，提示配置 printer.ip 选择 |
| 手动 IP 不可达 | 报错退出（退出码 1），提示检查 IP/网络/电源 |
| epson_print_conf SNMP 查询失败 | 不阻塞，字段填 None，PDF 显示"未知" |
| CUPS 打印失败 | 保留 PDF 到 `/tmp/epson-keeper-<timestamp>.pdf`，输出路径 |

## 8. 依赖管理

**方案**：`pyproject.toml`-only（PEP 621），无 `requirements.txt`。`pip install -e .` 直接安装。

```toml
[project]
name = "epson-keeper"
version = "0.1.0"
requires-python = ">=3.10"

dependencies = [
    "epson-print-conf>=1.0.0",
    "pysnmp>=6.0.0",
    "zeroconf>=0.130.0",
    "reportlab>=4.0",
    "pycups>=2.0.0",
    "click>=8.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "ruff>=0.4.0",
]

[project.scripts]
epson-keeper = "epson_keeper.cli:main"
```

> `Pillow` 在 MVP 中不需要（色条用 reportlab Canvas 直接绘制）。后续添加照片功能时再引入。

---

## 9. 非功能需求

- **可靠性**：打印机离线时不阻塞 crontab，静默失败并记录日志
- **安全性**：不写入打印机 EEPROM，不修改废墨计数器（只读查询）
- **可降级**：状态查询失败不阻塞 PDF 生成和打印

---

## 10. 测试策略

### 10.1 测试分层

| 层级 | 范围 | Mock 对象 |
|------|------|-----------|
| 单元测试 | 各模块独立逻辑 | epson_print_conf / CUPS |
| 集成测试 | CLI 端到端（mock 外部 I/O） | 网络 / 打印机 |
| PDF 结构测试 | 页数、内容、时间戳 | 无 |
| 手工验收 | 真实打印机端到端 | 无 |

### 10.2 Mock 策略

```python
# epson_print_conf mock
@pytest.fixture
def mock_printer(monkeypatch):
    class FakePrinter:
        def stats(self):
            return {"serial_number": "X58B240789", ...}
        def get_serial_number(self):
            return "X58B240789"
    monkeypatch.setattr(
        "epson_print_conf.EpsonPrinter", lambda **kw: FakePrinter()
    )

# CUPS mock
@pytest.fixture
def mock_cups(monkeypatch):
    class FakeConn:
        def getPrinters(self):
            return {"EPSON_L4160": {
                "sides-supported": ["two-sided-long-edge"],
                "ColorModel-supported": ["RGB"],
            }}
        def printFile(self, *args):
            return 42
    monkeypatch.setattr("cups.Connection", FakeConn)
```

### 10.3 PDF 结构测试

```python
def test_pdf_has_two_pages(tmp_path):
    pdf_path = generate_pdf(fake_status())
    reader = PdfReader(pdf_path)
    assert len(reader.pages) == 2

def test_status_page_contains_serial(tmp_path):
    pdf_path = generate_pdf(fake_status())
    text = extract_text(pdf_path, page=0)
    assert "X58B240789" in text

def test_status_page_contains_timestamp(tmp_path):
    pdf_path = generate_pdf(fake_status())
    text = extract_text(pdf_path, page=0)
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text)

def test_none_fields_show_unknown(tmp_path):
    """preview 模式使用空 PrinterStatus，所有字段应显示'未知'。"""
    status = PrinterStatus(query_time=now(), printer_ip="")  # 空状态
    pdf_path = generate_pdf(status)
    text = extract_text(pdf_path, page=0)
    assert "未知" in text
```

### 10.4 手工验收

> 必须在真实 Epson L416x 打印机上手动执行，不可 mock。

| # | 测试项 | 验收标准 |
|---|--------|----------|
| H1 | `epson-keeper preview`（无打印机） | 生成 A4 PDF，状态页字段显示"未知"，维护页色条+波浪线+点阵完整 |
| H2 | mDNS 自动发现（不配置 printer.ip） | 自动找到局域网 Epson 打印机，输出 IP |
| H3 | `epson-keeper status` | 输出打印机状态信息 |
| H4 | `epson-keeper run` L416x（双面） | 双面 1 张：正面维护页，背面状态页 |
| H5 | `epson-keeper run` L415x（单面） | 单面 1 张：仅维护页（无状态页） |
| H6 | `install.sh --venv PATH --dry-run` | 输出操作预览，使用指定 venv |
| H7 | `install.sh` | venv 选择/创建正确，crontab marker block 可见 |

---

## 11. 开发任务计划

### 交付顺序

```
M1: preview 跑通（生成 PDF，无打印机连接也能工作）
 ↓
M2: status 跑通（连接真实打印机查询状态）
 ↓
M3: run 跑通（真实打印，用户确认后执行）
 ↓
M4: install 跑通（venv + crontab）
```

### 阶段 1：脚手架

#### Task 1.1: 初始化项目结构

- [ ] `pyproject.toml`（PEP 621）
- [ ] `src/epson_keeper/__init__.py` + `cli.py` 骨架
- [ ] `config.example.yaml`
- [ ] `tests/` 目录
- [ ] `.gitignore`

**输出**：`epson-keeper --help`
**依赖**：无

#### Task 1.2: 配置管理

- [ ] `src/epson_keeper/config.py`
- [ ] `~/.config/epson-keeper/config.yaml` 读写，文件缺失时自动生成模板后退出提示填写
- [ ] 单元测试：`tests/test_config.py`

**输出**：`config.get("printer.ip")` 等接口
**依赖**：Task 1.1

#### Task 1.3: 打印机自动发现

- [ ] `src/epson_keeper/discovery.py`
- [ ] mDNS 浏览 `_ipp._tcp.local.`，筛选 EPSON 设备（txt `ty` 或 `usb_MFG`）
- [ ] `discover_printer(config_ip: str | None) -> str`：手动 IP 优先，mDNS 兜底
- [ ] 0 台 / >1 台 → 报错退出并给出清晰提示
- [ ] 单元测试（mock zeroconf）

**输出**：`discover_printer()` 返回打印机 IP
**依赖**：Task 1.2

### 阶段 2：核心模块

#### Task 2.1: 维护色条 & 波浪线 & 点阵绘制

- [ ] `src/epson_keeper/maintenance_image.py`
- [ ] 4 条渐变色条（黑、青、品红、黄），reportlab Canvas 直接绘制
- [ ] 每颜色 3-4 条细 sin 波浪线（0.8-1.0pt，振幅 1.5-2.5mm，浅→深渐变）
- [ ] 下半页稀疏 CMYK 点阵图（`canvas.circle()`，覆盖率 < 3%）
- [ ] 接口预留 `photo_path: Optional[str] = None`
- [ ] 单元测试

**输出**：`draw_maintenance_page(canvas, width, height)`
**依赖**：无（可并行）

#### Task 2.2: 打印机信息采集

- [ ] `src/epson_keeper/printer_info.py`
- [ ] `PrinterStatus` dataclass（全 Optional 字段）
- [ ] `query_printer()` 失败不抛异常，字段填 None
- [ ] 单元测试（mock EpsonPrinter）

**输出**：`query_printer(ip, model) -> PrinterStatus`
**依赖**：Task 1.2

#### Task 2.3: PDF 生成器

- [ ] `src/epson_keeper/pdf_generator.py`
- [ ] 第 1 页：状态报告（含时间戳、彩色排版、None → "未知"）
- [ ] 第 2 页：调用 `draw_maintenance_page()`
- [ ] PDF 结构测试

**输出**：`generate_pdf(status) -> str`
**依赖**：Task 2.1, Task 2.2

#### Task 2.4: CUPS 打印

- [ ] `src/epson_keeper/cups_printer.py`
- [ ] `detect_printer_options()` best-effort 探测
- [ ] 双面检测：支持 → 2 页双面；不支持 → **只打印维护页**（不打印状态页）
- [ ] 单元测试（mock cups.Connection）

**输出**：`print_pdf(path, name, duplex) -> job_id`
**依赖**：Task 2.3

### 阶段 3：集成

#### Task 3.1: CLI 完整集成

- [ ] `cli.py` 实现：`preview` / `status` / `run` / `install`
- [ ] `run` 命令打印前需用户确认（`--yes` 跳过）
- [ ] 日志配置
- [ ] 错误处理：每阶段失败的降级策略
- [ ] 集成测试

**输出**：五个子命令端到端可执行
**依赖**：Task 1.2, 1.3, 2.1, 2.2, 2.3, 2.4

### 阶段 4：安装 & 交付

#### Task 4.1: 安装脚本

- [ ] `install.sh`（install + `--venv PATH` + `--dry-run` + crontab marker block）
- [ ] 检测 Python >= 3.10
- [ ] venv 优先级：--venv > ~/.venv > ~/venv > 创建新 venv
- [ ] 复制 config.example.yaml 到 ~/.config/

**输出**：`bash install.sh` 一键完成
**依赖**：Task 1.1

#### Task 4.2: README

- [ ] 快速开始、配置说明（含 `lpstat -p` 查 CUPS 队列名）、CLI 命令、故障排查

**依赖**：全部完成

---

### 依赖关系图

```
Task 1.1 ──┬──→ Task 1.2 ──┬──→ Task 1.3 ──┐
            │                │                │
            │                ├──→ Task 2.2 ──┐│
            │                │               ││
            ├──→ Task 2.1 ──→│→ Task 2.3 ──→ Task 3.1
            │                │    ↑           │
            │                │  Task 2.4 ────┘
            │
            └──→ Task 4.1

Task 4.2（依赖全部）
```

### 里程碑

| 里程碑 | 完成标准 | 包含任务 |
|--------|----------|----------|
| **M1: preview** | `epson-keeper preview` 生成正确 PDF（无打印机也能工作） | 1.1, 1.2, 2.1, 2.2, 2.3 |
| **M2: status** | mDNS 发现打印机 + 查询状态 | 1.3 |
| **M3: run** | 真实打印（用户确认后），L416x 双面 / L415x 单面维护页 | 2.4, 3.1 |
| **M4: install** | `install.sh`（含 `--venv`）+ crontab + README | 4.1, 4.2 |

### 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| mDNS 发现不到打印机 | 自动发现失败 | 报错提示配置 printer.ip 手动指定 |
| mDNS 发现多台打印机 | 无法确定使用哪台 | 列出打印机，提示配置 printer.ip 选择 |
| epson_print_conf 不支持目标固件 | 状态查询失败 | 全 Optional 字段，PDF 显示"未知"，不阻塞打印 |
| CUPS 驱动选项名称不一致 | 打印选项设置失败 | best-effort 探测，不支持则跳过 |
| CUPS 未安装 | 无法打印 | `preview` 始终可用，PDF 可手动打印 |
| 打印机 IP 变更（手动配置时） | 连接失败 | 报错提示更新 config.yaml 或改用自动发现 |

---

## 附录：后续增强

以下功能在 MVP 验证后规划，不纳入当前开发计划：

- **内置样例照片**：`assets/sample_photo.jpg`，替换点阵图
- **uninstall 命令**：`install.sh --uninstall`，移除 crontab block + venv
- **CUPS 队列名自动发现**：从 mDNS 结果推导 CUPS 队列名，减少手动配置
