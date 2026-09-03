#!/usr/bin/env bash
# Token Eye — Linux (UKUI/麒麟) 一键安装
# 用法: bash install.sh   （幂等，可重复执行）
set -euo pipefail

LINUX_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$LINUX_DIR")"
PYTHON="${PYTHON:-/usr/bin/python3}"
AUTOSTART="$HOME/.config/autostart"
SERVICE_DIR="$HOME/.config/systemd/user"

echo "== Token Eye Linux 安装 =="
echo "项目:    $PROJECT_DIR"
echo "Linux层: $LINUX_DIR"

# 1. 依赖检查
echo "-- 依赖检查 --"
"$PYTHON" -c "import gi; gi.require_version('AppIndicator3','0.1'); gi.require_version('Gtk','3.0')" 2>/dev/null \
  || { echo "❌ 缺 python3-gi / gir1.2-appindicator3，先装: sudo apt install python3-gi gir1.2-appindicator3-0.1"; exit 1; }
"$PYTHON" -c "import secretstorage" 2>/dev/null \
  || { echo "❌ 缺 python3-secretstorage: sudo apt install python3-secretstorage"; exit 1; }
command -v notify-send >/dev/null || echo "⚠️ 缺 notify-send（通知不可用，不影响托盘）"
echo "✅ 依赖 OK"

# 2. 图标落位
ICON_DIR="$HOME/.local/share/icons"
mkdir -p "$ICON_DIR"
for c in ok warn err; do
  cp -f "$LINUX_DIR/icons/token-eye-${c}_22.png" "$ICON_DIR/token-eye-${c}.png" 2>/dev/null || true
done
echo "✅ 图标已复制到 $ICON_DIR"

# 3. systemd user service（常驻 + 崩溃自动重启；优先方案，不要并存 autostart）
mkdir -p "$SERVICE_DIR"
cp -f "$LINUX_DIR/token-eye.service" "$SERVICE_DIR/token-eye.service"
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable token-eye.service 2>/dev/null || true
systemctl --user restart token-eye.service 2>/dev/null || true
echo "✅ systemd service 已装并启动"

# 4. 删 autostart 兜底（与 systemd 双启动会出 2 个图标）
if [ -f "$AUTOSTART/token-eye.desktop" ]; then
  rm -f "$AUTOSTART/token-eye.desktop"
  echo "⚠️ 已删 autostart/token-eye.desktop（避免双启动）"
fi

# 5. 密钥提示
echo ""
echo "下一步：把 API Key 写入 gnome-keyring"
"$PYTHON" "$LINUX_DIR/setup-keys.py" --list || true
echo ""
echo "运行: $PYTHON $LINUX_DIR/setup-keys.py"
echo "（DeepSeek/MiniMax 填 Bearer key；MiMo 日后在 Chromium 登录后跑 refresh-mimo-cookie.py）"
echo ""
echo "管理: systemctl --user status token-eye"
echo "日志: journalctl --user -u token-eye -f"
echo "完成 ✅"
