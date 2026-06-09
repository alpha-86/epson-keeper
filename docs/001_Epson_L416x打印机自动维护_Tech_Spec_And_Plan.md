# 001 - Epson Keeper 技术规格

> 版本: 1.0 | 日期: 2026-06-09 | 状态: Draft

## 1. 概述

Epson Keeper 是一个自动化维护工具，针对 Epson L416x 系列墨仓式打印机，通过每周定时打印维护页来防止喷头堵塞。

**核心目标**：
- 保持所有喷嘴通道（C/M/Y/K）畅通，防止墨水干涸
- 最小化墨水消耗（年消耗 < 总墨量 1.5%）
- 记录打印机健康状态，便于长期追踪

## 2. 支持范围

### 2.1 打印机型号

| 型号 | 自动双面 | 备注 |
|------|----------|------|
| L4150, L4152, L4154, L4156, L4158 | 视具体硬件 | L416x 系列 |
| L4160, L4162, L4164 | 视具体硬件 | L416x 系列 |
| L4166, L4168 | 是 | L416x 系列 |

> 双面打印能力以打印机实际硬件为准，程序通过 CUPS `sides-supported` 属性自动检测。

### 2.2 运行环境

- Python >= 3.10
- Linux（依赖 CUPS 打印系统）
- 打印机通过 Wi-Fi 连接同一局域网

## 3. 系统架构

```
epson-keeper/
├── src/epson_keeper/
│   ├── __init__.py
│   ├── cli.py                  # CLI 入口 (click)
│   ├── config.py               # 配置管理
│   ├── discovery.py            # 打印机网络发现
│   ├── printer_info.py         # epson_print_conf 封装
│   ├── pdf_generator.py        # reportlab PDF 生成
│   ├── cups_printer.py         # CUPS 打印封装
│   └── maintenance_image.py    # 维护色条/波浪线绘制
├── assets/
│   └── sample_photo.jpg        # 内置小尺寸样例照片
├── config.example.yaml         # 配置示例
├── install.sh                  # 安装脚本（venv + crontab）
├── pyproject.toml
└── docs/
```

## 4. 模块设计

### 4.1 打印机自动发现 (`discovery.py`)

**发现策略**：优先读取缓存 → mDNS 发现 → SNMP 扫描 → 失败报错

**缓存文件**：`~/.config/epson-keeper/printer.json`

```json
{
  "ip": "192.168.1.100",
  "model": "L4160",
  "name": "EPSON L4160 Series",
  "discovered_at": "2026-06-09T21:00:00+08:00",
  "mac": "AA:BB:CC:DD:EE:FF"
}
```

**发现流程**：

```
1. 读取 printer.json 缓存
2. 若缓存存在：
   a. 验证 IP 可达性（SNMP get sysDescr 或 TCP port 161/9100）
   b. 可达 → 使用缓存 IP
   c. 不可达 → 清除缓存，进入发现流程
3. mDNS 发现（zeroconf）：
   a. 监听 _ipp._tcp.local. 服务，筛选 usb_MFG=EPSON
   b. 超时 10 秒
4. SNMP 子网扫描（fallback）：
   a. 获取本机子网，遍历 /24 地址段
   b. SNMP get sysDescr（1.3.6.1.2.1.1.1.0），community=public
   c. 并发 50 请求，超时 15 秒
   d. 筛选返回值包含 "EPSON" 的设备
5. 验证找到的打印机：
   a. 匹配型号（L416x 系列）
   b. 测试 SNMP 端口可达
6. 成功 → 写入缓存；失败 → 报错退出
```

**依赖**：`zeroconf`、`puresnmp`

### 4.2 打印机信息采集 (`printer_info.py`)

使用 `epson_print_conf.EpsonPrinter` 获取全部状态数据。

**采集字段**：

```python
@dataclass
class PrinterStatus:
    # 基本信息
    model: str                    # 型号
    serial_number: str            # 序列号
    firmware_version: str         # 固件版本
    mac_address: str              # MAC 地址
    printer_head_id: str          # 打印头 ID
    first_ti_received: str        # 首次使用时间

    # 计数器
    total_print_pages: int        # 总打印页数
    total_print_pass: int         # 总打印 Pass 数
    total_scan_count: int         # 总扫描次数

    # 墨水系统
    black_ink_replacements: int   # 黑色墨水更换次数
    cyan_ink_replacements: int    # 青色墨水更换次数
    magenta_ink_replacements: int # 品红墨水更换次数
    yellow_ink_replacements: int  # 黄色墨水更换次数

    # 废墨垫
    main_waste_ink_pct: float     # 主废墨垫百分比
    borderless_waste_ink_pct: float  # 无边距废墨垫百分比

    # 错误历史
    fatal_errors: list            # 致命错误列表

    # 运行时状态
    printer_status: dict          # 实时状态（墨水量等）
    snmp_info: dict               # SNMP 信息

    # 元数据
    query_time: str               # 查询时间 ISO 8601
    printer_ip: str               # 打印机 IP
```

**调用方式**：

```python
from epson_print_conf import EpsonPrinter

printer = EpsonPrinter(model="L4160", hostname=ip)
status = printer.stats()          # 一次性获取全部
# 或逐项获取更精确的字段
printer.get_serial_number()
printer.get_printer_status()
printer.get_waste_ink_levels()
# ...
```

### 4.3 PDF 生成 (`pdf_generator.py`)

使用 `reportlab` 生成 A4 两页 PDF。

#### 第 1 页：打印机状态报告

**设计原则**：
- 精确时间戳（含时区，格式：`2026-06-09 21:00:00 CST`）
- 黑色 + 彩色混合排版，日常黑色消耗多，信息页用彩色文字平衡
- 结构化表格展示所有数据

**页面布局**：

```
┌─────────────────────────────────────┐
│  ■ Epson Keeper 维护报告            │ ← 标题：深蓝色
│  生成时间: 2026-06-09 21:00:15 CST  │ ← 灰色小字
├─────────────────────────────────────┤
│  设备信息                            │ ← 小节标题：青色
│  ┌──────────┬──────────────────────┐ │
│  │ 型号     │ L4160                │ │ ← 标签黑色，值深蓝色
│  │ 序列号   │ X58B240789           │ │
│  │ 固件     │ LF23I6               │ │
│  │ MAC      │ AA:BB:CC:DD:EE:FF    │ │
│  │ 打印头ID │ ...                   │ │
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

#### 第 2 页：维护色条 + 波浪线 + 小照片

**设计原则**：
- 渐变色条铺满可打印宽度（~195mm），确保所有横向喷嘴被激活
- 波浪线提供连续喷墨运动，练习变速墨滴
- 黑色色条必须包含（日常黑色消耗最多，但维护时仍需确保黑色喷嘴畅通）
- 小尺寸照片（约 1/4 页面）提供真实场景色彩混合
- 整体覆盖率 3-5%，墨水消耗极低

**页面布局**：

```
┌─────────────────────────────────────┐
│                                     │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │ ← 黑色渐变条 (15mm)
│  ░░░▒▒▒▓▓▓███▓▓▓▒▒▒░░░░▒▒▒▓▓▓███  │ ← 黑色渐变波浪线
│                                     │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │ ← 青色渐变条 (15mm)
│  ░░░▒▒▒▓▓▓███▓▓▓▒▒▒░░░░▒▒▒▓▓▓███  │ ← 青色渐变波浪线
│                                     │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │ ← 品红渐变条 (15mm)
│  ░░░▒▒▒▓▓▓███▓▓▓▒▒▒░░░░▒▒▒▓▓▓███  │ ← 品红渐变波浪线
│                                     │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │ ← 黄色渐变条 (15mm)
│  ░░░▒▒▒▓▓▓███▓▓▓▒▒▒░░░░▒▒▒▓▓▓███  │ ← 黄色渐变波浪线
│                                     │
│  ┌───────────┐                      │
│  │           │                      │
│  │  小照片   │  ← 约 100x75mm       │
│  │  (1/4页)  │     左下或居中        │
│  │           │                      │
│  └───────────┘                      │
│                                     │
└─────────────────────────────────────┘
```

**色条规格**：
- 高度：每条 ~15mm，4条共 ~60mm
- 宽度：铺满可打印区域（约 195mm）
- 渐变方向：左到右，从 0% 到 100% 浓度
- 间距：条与条之间 ~15mm（用于波浪线）

**波浪线规格**：
- 使用 `sin(x)` 函数生成正弦波路径
- 线宽：2-3pt，模拟不同墨滴大小
- 振幅：~8mm，频率：每页 3-4 个周期
- 颜色与上方色条一致（黑、青、品红、黄各一条）

**小照片规格**：
- 尺寸：约 100mm x 75mm（明信片大小）
- 位置：页面左下方或居中
- 内容：程序内置 2-3 张样例照片，或用户指定
- 覆盖率：约 15-20%（照片区域）

### 4.4 CUPS 打印 (`cups_printer.py`)

```python
import cups

def print_pdf(pdf_path: str, printer_name: str, duplex: bool):
    conn = cups.Connection()

    # 检测打印机是否支持双面
    printers = conn.getPrinters()
    printer_info = printers.get(printer_name, {})
    sides_supported = printer_info.get("sides-supported", [])
    can_duplex = "two-sided-long-edge" in sides_supported

    options = {
        "media": "A4",
        "ColorModel": "RGB",
        "print-quality": "4",       # 高质量（增加喷墨量，利于维护）
    }

    if duplex and can_duplex:
        options["sides"] = "two-sided-long-edge"
    elif duplex and not can_duplex:
        # 不支持自动双面时，降级为单面 2 页
        import logging
        logging.warning("打印机不支持自动双面，降级为单面打印")

    job_id = conn.printFile(printer_name, pdf_path, "epson-keeper", options)
    return job_id
```

**打印选项**：
- `media=A4`
- `ColorModel=RGB`（彩色模式，确保所有通道激活）
- `print-quality=4`（高质量，增加墨水流通）
- `sides=two-sided-long-edge`（双面，长边翻转）

**降级策略**：
- 打印机不支持双面 → 单面打印（2张纸，第1页状态，第2页色条）
- 打印机离线 → 报错退出，保留 PDF 供手动打印

### 4.5 安装脚本 (`install.sh`)

**功能**：
1. 创建 Python venv
2. 安装项目依赖
3. 生成示例配置（若不存在）
4. 安装 crontab 定时任务

**Crontab 默认配置**：
```
# 每周四 21:00 执行维护打印
0 21 * * 4 /path/to/venv/bin/epson-keeper run
```

**安装脚本伪代码**：

```bash
#!/bin/bash
set -e

INSTALL_DIR="$HOME/.local/share/epson-keeper"
VENV_DIR="$INSTALL_DIR/venv"
CONFIG_DIR="$HOME/.config/epson-keeper"

# 1. 创建安装目录
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"

# 2. 复制项目文件
cp -r src/ pyproject.toml "$INSTALL_DIR/"

# 3. 创建 venv 并安装
python3.10 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"

# 4. 生成默认配置（若不存在）
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    cp config.example.yaml "$CONFIG_DIR/config.yaml"
fi

# 5. 安装 crontab
CRON_CMD="0 21 * * 4 $VENV_DIR/bin/epson-keeper run >> $INSTALL_DIR/cron.log 2>&1"
(crontab -l 2>/dev/null | grep -v "epson-keeper"; echo "$CRON_CMD") | crontab -

echo "安装完成！"
echo "配置文件: $CONFIG_DIR/config.yaml"
echo "定时任务: 每周四 21:00 执行"
```

## 5. 配置文件 (`config.yaml`)

```yaml
printer:
  # 留空则自动发现，填写 IP 则跳过发现
  ip: ""
  model: "L4160"       # 可选，用于 epson_print_conf

print:
  duplex: true         # 双面打印（自动检测是否支持）
  quality: "high"      # draft / normal / high
  photo_path: ""       # 自定义照片路径，留空使用内置样例

schedule:
  cron: "0 21 * * 4"   # 每周四 21:00

logging:
  level: "INFO"
  file: ""             # 留空则只输出到 stderr
```

## 6. CLI 命令

```bash
# 执行完整维护（发现 → 查询 → 生成 PDF → 打印）
epson-keeper run

# 仅查询打印机状态（输出到终端）
epson-keeper status

# 预览 PDF（生成到当前目录，不打印）
epson-keeper preview

# 重新发现打印机（清除缓存）
epson-keeper discover

# 安装定时任务
epson-keeper install
```

## 7. 错误处理

| 场景 | 处理方式 |
|------|----------|
| 打印机未发现 | 打印错误日志，退出码 1，不重试（下周自动重试） |
| SNMP 查询失败 | 用已有数据生成 PDF，标注 "部分数据缺失" |
| CUPS 打印失败 | 保留 PDF 到 `/tmp/epson-keeper-<timestamp>.pdf`，输出路径 |
| 配置文件缺失 | 自动生成默认配置 |
| venv 损坏 | install.sh 支持重新安装 |

## 8. 依赖清单

```
# 核心
epson-print-conf >= 1.0.0    # 打印机信息查询
pysnmp >= 6.0.0              # SNMP 协议（epson_print_conf 依赖）
puresnmp >= 3.0.0            # 轻量 SNMP（自动发现用）
zeroconf >= 0.100.0          # mDNS 发现
reportlab >= 4.0             # PDF 生成
Pillow >= 10.0               # 图像处理
pycups >= 2.0.0              # CUPS 打印接口
click >= 8.0                 # CLI 框架
pyyaml >= 6.0                # 配置文件

# 开发
pytest >= 7.0
ruff >= 0.4.0
```

## 9. 非功能需求

- **墨水经济性**：每次维护打印消耗 < 0.1ml，年消耗 < 5ml（总量 337ml 的 1.5%）
- **可靠性**：打印机离线时不阻塞 crontab，静默失败并记录日志
- **可维护性**：配置与代码分离，支持用户自定义照片/色条
- **安全性**：不写入打印机 EEPROM，不修改废墨计数器（只读查询）

---

## 10. 开发任务计划

### 任务总览

```
阶段 1: 项目脚手架        ← 可并行
阶段 2: 核心模块开发      ← 有依赖关系
阶段 3: 集成 & 端到端
阶段 4: 安装 & 交付
```

### 阶段 1：项目脚手架

#### Task 1.1: 初始化项目结构

**目标**：创建 Python 包结构和元数据

- [ ] 创建 `pyproject.toml`（包名、版本、依赖、入口点）
- [ ] 创建 `src/epson_keeper/__init__.py`
- [ ] 创建 `src/epson_keeper/cli.py` 骨架（click 命令组）
- [ ] 创建 `config.example.yaml`
- [ ] 创建 `tests/` 目录结构
- [ ] 添加 `.gitignore`（venv、__pycache__、*.pyc、.config/）

**输出**：可执行的 `epson-keeper --help`
**依赖**：无

---

#### Task 1.2: 配置管理模块

**目标**：实现配置文件读写

- [ ] `src/epson_keeper/config.py`
- [ ] 默认配置定义
- [ ] `~/.config/epson-keeper/config.yaml` 读写
- [ ] 配置文件不存在时自动生成
- [ ] 单元测试：`tests/test_config.py`

**输出**：`config.get("printer.ip")` 等访问接口
**依赖**：Task 1.1

---

### 阶段 2：核心模块开发

#### Task 2.1: 打印机自动发现

**目标**：局域网自动发现 Epson L416x 打印机，缓存结果

- [ ] `src/epson_keeper/discovery.py`
- [ ] 缓存文件：`~/.config/epson-keeper/printer.json`
- [ ] mDNS 发现（`zeroconf` 监听 `_ipp._tcp`，筛选 `usb_MFG=EPSON`）
- [ ] SNMP 扫描（`puresnmp` 并发查询 sysDescr，筛选 EPSON）
- [ ] 缓存验证：读缓存 → 验证可达 → 不可达则重新发现
- [ ] 集成到 CLI：`epson-keeper discover` 命令
- [ ] 单元测试：`tests/test_discovery.py`（mock SNMP/mDNS）

**输出**：`discover()` → `{"ip": "...", "model": "...", "name": "..."}`
**依赖**：Task 1.1

---

#### Task 2.2: 打印机信息采集

**目标**：通过 epson_print_conf 获取打印机全部状态

- [ ] `src/epson_keeper/printer_info.py`
- [ ] `PrinterStatus` 数据类定义
- [ ] `query_printer(ip, model)` 函数，返回 `PrinterStatus`
- [ ] 处理连接失败（超时、SNMP 错误）的降级逻辑
- [ ] 单元测试：`tests/test_printer_info.py`（mock EpsonPrinter）

**输出**：`query_printer("192.168.1.100", "L4160")` → `PrinterStatus` 实例
**依赖**：Task 1.2

---

#### Task 2.3: 维护色条 & 波浪线绘制

**目标**：生成维护用的渐变色条和波浪线图像

- [ ] `src/epson_keeper/maintenance_image.py`
- [ ] 渐变色条：4 条（黑、青、品红、黄），每条 15mm 高，铺满 195mm 宽
- [ ] 渐变波浪线：`sin(x)` 路径，线宽 2-3pt，振幅 8mm
- [ ] 使用 `reportlab` Canvas 直接绘制（无需 Pillow 中间文件）
- [ ] 小照片嵌入：居中或左下，约 100x75mm
- [ ] 内置样例照片：`assets/sample_photo.jpg`（低覆盖率自然图片）
- [ ] 单元测试：`tests/test_maintenance_image.py`

**输出**：`draw_maintenance_page(canvas, width, height, photo_path=None)`
**依赖**：无（纯绘制）

---

#### Task 2.4: PDF 生成器

**目标**：生成 2 页 A4 PDF（状态页 + 维护页）

- [ ] `src/epson_keeper/pdf_generator.py`
- [ ] 第 1 页：打印机状态报告（精确时间戳、彩色混合排版）
- [ ] 第 2 页：调用 `maintenance_image.draw_maintenance_page()`
- [ ] 单元测试：`tests/test_pdf_generator.py`

**输出**：`generate_pdf(status, photo_path=None) -> str`
**依赖**：Task 2.2, Task 2.3

---

#### Task 2.5: CUPS 打印模块

**目标**：将 PDF 发送到打印机，支持自动双面

- [ ] `src/epson_keeper/cups_printer.py`
- [ ] 检测打印机 `sides-supported` 属性
- [ ] 支持双面：`sides=two-sided-long-edge`
- [ ] 降级：不支持双面 → 单面打印 + 日志警告
- [ ] 打印选项：`media=A4, ColorModel=RGB, print-quality=4`
- [ ] 单元测试：`tests/test_cups_printer.py`（mock cups.Connection）

**输出**：`print_pdf(pdf_path, printer_name, duplex=True) -> job_id`
**依赖**：Task 2.4

---

### 阶段 3：集成 & 端到端

#### Task 3.1: CLI 完整集成

**目标**：将所有模块串联到 CLI 命令

- [ ] `cli.py` 完整实现：`run` / `status` / `preview` / `discover` / `install`
- [ ] 日志配置（INFO/WARNING/ERROR）
- [ ] 错误处理：每个阶段失败的降级策略
- [ ] 集成测试：`tests/integration/test_full_flow.py`

**输出**：`epson-keeper run` 端到端可执行
**依赖**：Task 1.2, 2.1, 2.2, 2.3, 2.4, 2.5

---

#### Task 3.2: 内置样例照片

**目标**：提供开箱即用的维护照片

- [ ] `assets/sample_photo.jpg` — 自然风景照片（覆盖率适中）
- [ ] 确保色彩均衡（包含 C/M/Y/K 各通道色彩）
- [ ] 尺寸适合 A4 100x75mm 区域（约 1200x900px，150dpi）

**依赖**：无（可并行）

---

### 阶段 4：安装 & 交付

#### Task 4.1: 安装脚本

**目标**：一键安装，包含 venv 和 crontab

- [ ] `install.sh`
- [ ] 检测 Python >= 3.10
- [ ] 创建 `$HOME/.local/share/epson-keeper/venv`
- [ ] `pip install -e` 安装项目
- [ ] 生成默认配置到 `$HOME/.config/epson-keeper/config.yaml`
- [ ] 安装 crontab：`0 21 * * 4`（每周四 21:00）
- [ ] crontab 幂等（不重复添加）

**输出**：`bash install.sh` 一键完成
**依赖**：Task 1.1

---

#### Task 4.2: 文档 & README 更新

**目标**：完善项目文档

- [ ] 更新 `README.md`：快速开始、配置说明、CLI 命令、故障排查

**依赖**：所有任务完成

---

### 依赖关系图

```
Task 1.1 ──┬──→ Task 1.2 ──→ Task 2.2 ──┐
            │                              │
            ├──→ Task 2.1 ──────────────→ Task 3.1
            │                              │
            └──→ Task 2.3 ──→ Task 2.4 ──┘
                                   │
                               Task 2.5 ──→ Task 3.1

Task 3.2（独立，可并行）

Task 1.1 ──→ Task 4.1（安装脚本）
```

### 里程碑

| 里程碑 | 完成标准 | 包含任务 |
|--------|----------|----------|
| **M1: 脚手架** | 项目可安装，CLI --help 工作 | 1.1, 1.2 |
| **M2: 核心能力** | 各模块独立可测试 | 2.1, 2.2, 2.3, 2.4, 2.5, 3.2 |
| **M3: 端到端** | `epson-keeper run` 完整流程 | 3.1 |
| **M4: 可交付** | 安装脚本 + 文档齐全 | 4.1, 4.2 |

### 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| epson_print_conf 不支持目标固件版本 | 状态查询失败 | 降级：跳过查询，用空数据生成 PDF |
| 局域网无 mDNS 响应 | 自动发现慢 | SNMP 扫描作为 fallback |
| CUPS 未安装 | 无法打印 | preview 命令始终可用，PDF 可手动打印 |
| 打印机不支持自动双面 | 双面失败 | 自动检测 + 降级为单面 |
| Python 版本低于 3.10 | 安装失败 | install.sh 检测版本并报错 |
