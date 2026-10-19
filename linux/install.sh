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

# 4. 开机自启去重：只保留 systemd，清掉所有 XDG autostart 条目
#    token-eye.desktop       旧模板，Exec 直接跑 python3 → 真·双实例
#    token-eye-start.desktop 手动兜底，Exec=systemctl start → 关掉也照常启动
BACKUP_DIR="$HOME/.workbuddy/tmp/token-eye-autostart-$(date +%Y%m%d)"
for legacy in token-eye.desktop token-eye-start.desktop; do
  f="$AUTOSTART/$legacy"
  [ -e "$f" ] || continue
  mkdir -p "$BACKUP_DIR"
  cp -f "$f" "$BACKUP_DIR/$legacy"
  rm -f "$f"
  echo "⚠️ 已移除 autostart/$legacy（备份 $BACKUP_DIR/$legacy）"
done
if compgen -G "$AUTOSTART/*token-eye*.desktop" >/dev/null; then
  echo "❌ autostart 仍残留 token-eye 条目，请手动检查："
  ls -l "$AUTOSTART"/*token-eye*.desktop || true
else
  echo "✅ 无 XDG autostart 条目（唯一启动源：systemd user service）"
fi

# 5. 密钥提示
echo ""
echo "下一步：把 API Key 写入 gnome-keyring"
"$PYTHON" "$LINUX_DIR/setup-keys.py" --list || true
echo ""
echo "运行: $PYTHON $LINUX_DIR/setup-keys.py"
echo "（DeepSeek/MiniMax/智谱 填 API key；MiMo 日后在 Chromium 登录后跑 refresh-mimo-cookie.py）"
echo ""
echo "管理: systemctl --user status token-eye"
echo "自启: systemctl --user enable token-eye / disable token-eye（无桌面环境开关，避免两套真相）"
echo "日志: journalctl --user -u token-eye -f"
echo "完成 ✅"
