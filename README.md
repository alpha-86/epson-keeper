# Epson Keeper

Epson L415x/L416x 系列打印机自动维护工具。每周定时打印彩色维护页，防止喷头堵塞。

## 功能

- 自动发现打印机（mDNS）或手动配置 IP
- 查询打印机状态（墨水量、打印计数、废墨垫等）
- 生成彩色维护页（色条 + 波浪线 + 点阵图，覆盖四色通道）
- L416x 双面打印（正面维护页，背面状态报告）；L415x 单面维护页
- 支持 cron 定时执行

## 支持型号

| 系列 | 型号 | 双面 | 维护策略 |
|------|------|------|----------|
| L415x | L4150, L4152, L4154, L4156, L4158 | 否 | 单面维护页 |
| L416x | L4160, L4162, L4164, L4166, L4168 | 是 | 双面：维护页 + 状态页 |

## 快速开始

```bash
# 克隆项目
git clone <repo-url>
cd epson-keeper

# 安装到已有 venv
./install.sh --venv ~/.venv

# 或自动创建 venv
./install.sh

# 预览（无需打印机）
epson-keeper preview
```

## 安装

### 方式一：install.sh（推荐）

```bash
./install.sh                    # 自动选择 venv 并安装
./install.sh --venv ~/myenv     # 使用指定 venv
./install.sh --dry-run          # 只打印操作，不实际执行
```

脚本会：
1. 检测 Python >= 3.10
2. 选择或创建 venv
3. 安装项目
4. 生成配置文件模板
5. 安装 crontab 定时任务（每周四 21:00）

### 方式二：手动安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 配置

配置文件：`~/.config/epson-keeper/config.yaml`

```yaml
printer:
  ip: ""                        # 可选，留空则自动发现（mDNS）；手动指定 IP
  model: "L4160"                # 必填，打印机型号
  cups_name: "EPSON_L4160_Series"  # 必填，CUPS 队列名称

schedule:
  cron: "0 21 * * 4"            # 每周四 21:00

logging:
  level: "INFO"
  file: ""                      # 留空则只输出到 stderr
```

### 查看 CUPS 队列名称

```bash
lpstat -p
# 输出示例: printer EPSON_L4160_Series is idle.
```

## CLI 命令

```bash
# 预览 PDF（默认 2 页：维护页 + 状态页，状态字段显示"未知"）
epson-keeper preview
epson-keeper preview --single-page   # L415x 模式，仅维护页

# 查询打印机状态
epson-keeper status

# 执行完整维护（查询 → 生成 PDF → 打印）
epson-keeper run
epson-keeper run --yes               # 跳过确认（cron 使用）

# 安装定时任务
epson-keeper install
epson-keeper install --dry-run
```

## 依赖

- Python >= 3.10
- Linux + CUPS 打印系统
- 打印机通过 Wi-Fi 连接局域网

核心依赖（自动安装）：
- `zeroconf` — mDNS 打印机发现
- `reportlab` — PDF 生成
- `click` — CLI 框架
- `pyyaml` — 配置文件解析
- `pycups` — CUPS 打印接口

必须从 GitHub 安装（不在 PyPI）：
- `epson-print-conf` — 打印机 EEPROM/SNMP 状态查询（[GitHub](https://github.com/Ircama/epson_print_conf)）
- `install.sh` 会自动执行安装，或手动：`pip install "epson-print-conf @ git+https://github.com/Ircama/epson_print_conf"`

## 故障排查

**打印机未发现**
```bash
# 检查打印机是否开机并连接同一网络
# 手动配置 IP：
#   编辑 ~/.config/epson-keeper/config.yaml，设置 printer.ip
```

**CUPS 打印失败**
```bash
# 检查 CUPS 队列名
lpstat -p
# 确保 cups_name 与输出一致
```

**状态查询返回"未知"**
```bash
# 安装可选依赖（需 epson-print-conf 支持）
pip install epson-print-conf pysnmp
```

## 许可证

MIT
