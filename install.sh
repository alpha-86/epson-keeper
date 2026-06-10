#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/epson-keeper"
CONFIG_DIR="$HOME/.config/epson-keeper"
# 北京时间 21:50 = UTC 13:50（服务器时区为 UTC）
CRON_SCHEDULE="50 13 * * 3"
DRY_RUN=false
VENV_DIR=""

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
    if [ "$ver" -ge 10 ] 2>/dev/null; then
      PYTHON="$c"
      break
    fi
  fi
done
[ -z "$PYTHON" ] && echo "错误: 需要 Python >= 3.10" && exit 1
echo "使用 Python: $PYTHON ($($PYTHON --version))"

# ── 选择 venv（优先级：--venv > ~/.venv > ~/venv > 创建新 venv）──
validate_venv() {
  local venv="$1"
  [ -f "$venv/pyvenv.cfg" ] || return 1
  "$venv/bin/python" -c "import sys; assert sys.version_info >= (3,10)" 2>/dev/null || return 1
  "$venv/bin/pip" --version &>/dev/null || return 1
  return 0
}

if [ -n "$VENV_DIR" ]; then
  validate_venv "$VENV_DIR" || { echo "错误: $VENV_DIR 不可用（需 Python >= 3.10 + pip）"; exit 1; }
else
  for candidate in "$HOME/.venv" "$HOME/venv"; do
    if validate_venv "$candidate"; then
      VENV_DIR="$candidate"
      echo "复用已有 venv: $VENV_DIR"
      break
    fi
  done
fi
if [ -z "$VENV_DIR" ]; then
  VENV_DIR="$INSTALL_DIR/venv"
  echo "创建新 venv: $VENV_DIR"
  step "$PYTHON" -m venv "$VENV_DIR"
fi

# ── 安装 ──
step mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
step cp -r "$SCRIPT_DIR/src/" "$INSTALL_DIR/"
step cp "$SCRIPT_DIR/pyproject.toml" "$INSTALL_DIR/"
step "$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"
# epson_print_conf (PyPI: epsonprinter)
step "$VENV_DIR/bin/pip" install epsonprinter

if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
  step cp "$SCRIPT_DIR/config.example.yaml" "$CONFIG_DIR/config.yaml"
  echo "已生成配置文件: $CONFIG_DIR/config.yaml"
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
  echo "已安装 crontab 定时任务"
fi

echo ""
echo "安装完成！"
echo "  配置文件: $CONFIG_DIR/config.yaml"
echo "  定时任务: 每周三 21:50 (北京时间)"
echo "  运行日志: $INSTALL_DIR/cron.log"
