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
#    致命项（缺了托盘起不来）：gi/AppIndicator、secretstorage。
#    软依赖（缺了只降级对应功能）：逐项告警，不阻断安装。
echo "-- 依赖检查 --"
# AppIndicator：部分麒麟只有 AyatanaAppIndicator3，先试它再回退 AppIndicator3
"$PYTHON" -c "
import gi
try:
    gi.require_version('AyatanaAppIndicator3', '0.1')
except (ValueError, ImportError):
    gi.require_version('AppIndicator3', '0.1')
gi.require_version('Gtk', '3.0')
" 2>/dev/null \
  || { echo "❌ 缺 python3-gi / gir1.2-ayatana-appindicator3（或 gir1.2-appindicator3-0.1），先装: sudo apt install python3-gi gir1.2-ayatana-appindicator3"; exit 1; }
"$PYTHON" -c "import secretstorage" 2>/dev/null \
  || { echo "❌ 缺 python3-secretstorage: sudo apt install python3-secretstorage"; exit 1; }
"$PYTHON" -c "import cryptography" 2>/dev/null \
  || echo "⚠️ 缺 python3-cryptography（MiMo Cookie 刷新不可用）: sudo apt install python3-cryptography"
"$PYTHON" -c "import dbus" 2>/dev/null \
  || echo "⚠️ 缺 python3-dbus（部分发行版 secretstorage 需要）: sudo apt install python3-dbus"
command -v curl >/dev/null \
  || echo "⚠️ 缺 curl（余额 API 请求不可用）: sudo apt install curl"
command -v notify-send >/dev/null \
  || echo "⚠️ 缺 notify-send（通知不可用，不影响托盘）"
if ! command -v wl-copy >/dev/null && ! command -v xclip >/dev/null; then
  echo "⚠️ 缺 wl-copy/xclip（菜单「复制余额」不可用）"
fi
if ! command -v chromium-browser >/dev/null && ! command -v chromium >/dev/null \
   && ! command -v chromium-browser-stable >/dev/null; then
  echo "⚠️ 缺 Chromium（MiMo 登录/Cookie 提取不可用，将回退 xdg-open）"
fi
echo "✅ 依赖检查完成（致命项全部满足，软依赖告警见上）"

# 2. 图标落位
ICON_DIR="$HOME/.local/share/icons"
mkdir -p "$ICON_DIR"
for c in ok warn err; do
  cp -f "$LINUX_DIR/icons/token-eye-${c}_22.png" "$ICON_DIR/token-eye-${c}.png" 2>/dev/null || true
done
echo "✅ 图标已复制到 $ICON_DIR"

# 3. systemd user service（常驻 + 崩溃自动重启；优先方案，不要并存 autostart）
mkdir -p "$SERVICE_DIR"
# 由模板注入实际解释器与托盘路径：service 内不再硬编码 /usr/bin/python3 与
# %h/dev/token-eye/，PYTHON / LINUX_DIR 覆盖后服务照样能起来。
_sed_escape() { printf '%s' "$1" | sed 's/[&|]/\\&/g'; }
PY_SED="$(_sed_escape "$PYTHON")"
TRAY_SED="$(_sed_escape "$LINUX_DIR/token-eye-tray.py")"
SERVICE_TMP="$(mktemp "${TMPDIR:-/tmp}/token-eye-service.XXXXXX")"
sed -e "s|@PYTHON@|${PY_SED}|g" \
    -e "s|@TRAY@|${TRAY_SED}|g" \
    "$LINUX_DIR/token-eye.service.in" > "$SERVICE_TMP"
cp -f "$SERVICE_TMP" "$SERVICE_DIR/token-eye.service"
rm -f "$SERVICE_TMP"
echo "✅ 已由 token-eye.service.in 生成 service（PYTHON=$PYTHON，TRAY=$LINUX_DIR/token-eye-tray.py）"

# 三条 systemctl --user 失败不得静默：记录并给出明确降级提示，不能无条件报「已启动」
SVC_OK=1
if ! systemctl --user daemon-reload; then
  echo "⚠️ systemctl --user daemon-reload 失败（用户级 systemd 是否就绪？）"
  SVC_OK=0
fi
if ! systemctl --user enable token-eye.service; then
  echo "⚠️ systemctl --user enable token-eye.service 失败（开机自启未生效）"
  SVC_OK=0
fi
if ! systemctl --user restart token-eye.service; then
  echo "⚠️ systemctl --user restart token-eye.service 失败（托盘未由 service 拉起）"
  SVC_OK=0
fi
if [ "$SVC_OK" -eq 1 ]; then
  echo "✅ systemd service 已装并启动"
else
  echo "⚠️ systemd service 未完全就绪（见上方告警）——文件与图标已装好，可手动拉起："
  echo "   $PYTHON $LINUX_DIR/token-eye-tray.py"
  echo "   排查：systemctl --user status token-eye / journalctl --user -u token-eye"
fi

# 4. 开机自启去重：只保留 systemd，清理两个已知的历史 autostart 模板
#    token-eye.desktop       旧模板，Exec 直接跑 python3 → 真·双实例
#    token-eye-start.desktop 手动兜底，Exec=systemctl start → 关掉也照常启动
#    仅删除这两个固定模板；其余 *token-eye*.desktop 只告警、不删除（避免误删用户自定义项）。
#    备份目录带时分秒 + cp -n：同日重复执行不覆盖前一次备份。
BACKUP_DIR="$HOME/.workbuddy/tmp/token-eye-autostart-$(date +%Y%m%d-%H%M%S)"
FOUND=0
for legacy in token-eye.desktop token-eye-start.desktop; do
  if [ -e "$AUTOSTART/$legacy" ]; then
    FOUND=1
  fi
done
if [ "$FOUND" -eq 1 ]; then
  echo "将移除以下 autostart 条目（先备份到 $BACKUP_DIR，cp -n 不覆盖已有备份）："
  for legacy in token-eye.desktop token-eye-start.desktop; do
    if [ -e "$AUTOSTART/$legacy" ]; then
      echo "  $AUTOSTART/$legacy"
    fi
  done
  mkdir -p "$BACKUP_DIR"
  for legacy in token-eye.desktop token-eye-start.desktop; do
    f="$AUTOSTART/$legacy"
    if [ -e "$f" ]; then
      cp -n "$f" "$BACKUP_DIR/$legacy"
      rm -f "$f"
      echo "⚠️ 已移除 autostart/$legacy（备份 $BACKUP_DIR/$legacy）"
    fi
  done
else
  echo "✅ 无需清理：两个历史 autostart 模板均不存在"
fi
# 其余匹配项：只告警、不删除（与注释/README 口径一致）
if compgen -G "$AUTOSTART/*token-eye*.desktop" >/dev/null; then
  echo "⚠️ autostart 仍残留其它 token-eye 条目（脚本只删两个固定模板，不动这些），请人工确认是否需处理："
  ls -l "$AUTOSTART"/*token-eye*.desktop || true
else
  echo "✅ 无其它 XDG autostart 条目（唯一启动源：systemd user service）"
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
