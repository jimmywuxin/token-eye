#!/usr/bin/env bash
# <bitbar.title>Token Eye</bitbar.title>
# <bitbar.version>v0.10.0</bitbar.version>
# <bitbar.author>wuxin</bitbar.author>
# <bitbar.desc>LLM Token usage monitor — config-driven, with caching & alerts</bitbar.desc>
# <bitbar.refreshTime>30</bitbar.refreshTime>

set -euo pipefail


# Detect appearance for adaptive colors
if [ "$(defaults read -g AppleInterfaceStyle 2>/dev/null)" = "Dark" ]; then
    APPEARANCE="dark"
    C_DEFAULT="#ffffff"
    C_SECONDARY="#aaaaaa"
    C_MUTED="#888888"
    C_HEADER="#FFD60A"
    C_OK="#56B4E9"
    C_WARN="#E69F00"
    C_ERR="#CC79A7"
else
    APPEARANCE="light"
    C_DEFAULT="#000000"
    C_SECONDARY="#2c2c2e"
    C_MUTED="#48484a"
    C_HEADER="#0066CC"
    C_OK="#0072B2"
    C_WARN="#8A5A00"
    C_ERR="#8E1A4A"
fi
export APPEARANCE C_DEFAULT C_SECONDARY C_MUTED C_HEADER C_OK C_WARN C_ERR

# ---------------------------------------------------------------------------
# Auto-detect project directory
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/providers.json" ]; then
    PROJECT_DIR="$SCRIPT_DIR"
elif [ -f "$(dirname "$SCRIPT_DIR")/providers.json" ]; then
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
else
    PROJECT_DIR="$HOME/dev/token-eye"
fi

CONFIG_FILE="$PROJECT_DIR/providers.json"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "👁"
  echo "---"
  echo "providers.json not found | color=$C_ERR"
  echo "Expected: $CONFIG_FILE | color=$C_MUTED size=11"
  exit 0
fi

# ---------------------------------------------------------------------------
# SwiftBar 点击动作（param1 触发）：一键刷新 MiMo Cookie
# ---------------------------------------------------------------------------
if [ "${1:-}" = "refresh-mimo-cookie" ]; then
    REFRESH_SCRIPT="$PROJECT_DIR/scripts/refresh-mimo-cookie.py"
    if [ ! -f "$REFRESH_SCRIPT" ]; then
        echo "👁 | color=$C_ERR"
        echo "---"
        echo "刷新脚本不存在: $REFRESH_SCRIPT | color=$C_ERR"
        echo "---"
        echo "关闭 | refresh=true"
        exit 0
    fi
    # 注意：刷新脚本失败时退出码非零，set -e 会中断脚本，
    # 所以这里必须用 || true 吞掉退出码，由下面的分支决定展示成功还是失败。
    OUTPUT="$(/usr/bin/python3 "$REFRESH_SCRIPT" 2>&1 || true)"
    if echo "$OUTPUT" | grep -q "HTTP=200"; then
        echo "👁 | color=$C_OK"
        echo "---"
        echo "✅ MiMo Cookie 刷新成功 | color=$C_OK"
        echo "---"
        echo "关闭 | refresh=true"
    else
        echo "👁 | color=$C_ERR"
        echo "---"
        echo "❌ MiMo Cookie 刷新失败 | color=$C_ERR"
        echo "$OUTPUT" | tail -4 | sed 's/|/:/g' | while IFS= read -r line; do
            if [ -n "$line" ]; then
                echo "$line | color=$C_MUTED size=11"
            fi
        done
        echo "---"
        echo "重试 | param1=refresh-mimo-cookie refresh=true"
        echo "关闭 | refresh=true"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# Python 核心逻辑（token_eye.py，与 providers.json 一样从项目目录读取）
# ---------------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "👁 | color=$C_ERR"
    echo "---"
    echo "python3 未找到 | color=$C_ERR"
    echo "---"
    echo "刷新 | refresh=true"
    exit 0
fi

PY_MODULE="$PROJECT_DIR/swiftbar/token_eye.py"
if [ ! -f "$PY_MODULE" ]; then
    echo "👁 | color=$C_ERR"
    echo "---"
    echo "核心模块缺失: $PY_MODULE | color=$C_ERR"
    echo "---"
    echo "刷新 | refresh=true"
    exit 0
fi

CONFIG_FILE="$CONFIG_FILE" PROJECT_DIR="$PROJECT_DIR" python3 "$PY_MODULE" "$@"
