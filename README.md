# epson-keeper

Epson L416x 系列打印机自动化维护工具。每周定时打印彩色测试页，防止墨水干涸堵塞喷头。

## 功能

- 自动查询打印机状态（墨水量、打印计数、废墨垫等）
- 生成彩色测试图案（覆盖所有颜色通道）
- 正面打印彩色照片，背面打印打印机状态信息
- 支持定时执行（cron / GitHub Actions）
- 支持 Epson Connect API 和本地 CUPS 两种打印方式

## 支持型号

L4150, L4152, L4154, L4156, L4158, **L4160**, L4162, L4164, L4166, L4168

## 安装

```bash
pip install epson-keeper
```

或从源码安装：

```bash
git clone https://github.com/<your-username>/epson-keeper.git
cd epson-keeper
pip install -e .
```

## 配置

复制示例配置文件并编辑：

```bash
cp config.example.yaml config.yaml
```

```yaml
printer:
  ip: "192.168.1.100"       # 打印机 IP（SNMP 查询用）
  model: "L4160"            # 打印机型号
  name: "EPSON L4160 Series" # CUPS 打印机名称

print:
  mode: "cups"              # cups 或 epson-connect
  image: "photo"            # photo（随机照片）或 test-pattern（色块测试页）
  duplex: true              # 是否双面打印（背面打印信息）

epson_connect:              # mode 为 epson-connect 时需要
  printer_email: ""
  client_id: ""
  client_secret: ""
```

## 使用

```bash
# 执行一次维护打印
epson-keeper run

# 仅查询打印机状态
epson-keeper status

# 预览本次要打印的内容（不实际打印）
epson-keeper preview

# 安装每周定时任务（Linux/macOS）
epson-keeper install-cron
```

## 定时执行

### 方式一：系统 cron

```bash
# 每周一早上 9 点执行
epson-keeper install-cron --schedule "0 9 * * 1"
```

### 方式二：GitHub Actions

本项目内置了 GitHub Actions workflow，fork 后在 Settings > Secrets 中配置打印机信息即可每周自动执行。

## 许可证

MIT
