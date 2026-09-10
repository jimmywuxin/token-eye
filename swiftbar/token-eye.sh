#!/usr/bin/env bash
# <bitbar.title>Token Eye</bitbar.title>
# <bitbar.version>v0.20.0</bitbar.version>
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
# 系统通知：点击动作由 SwiftBar 以 bash= + terminal=false 在后台执行，
# stdout 会被丢弃（菜单看不到），所以动作结果统一走通知回显。
# ---------------------------------------------------------------------------
notify() {
    local msg="${1//\"/}"
    osascript -e "display notification \"$msg\" with title \"Token Eye\"" >/dev/null 2>&1 || true
}


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
# Python 解释器与核心模块定位（点击动作分支与正常渲染共用）
# ---------------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "👁 | color=$C_ERR"
    echo "---"
    echo "python3 未找到 | color=$C_ERR"
    echo "---"
    echo "刷新 | refresh=true"
    exit 0
fi

if [ -f "$PROJECT_DIR/swiftbar/token_eye.py" ] && { [ ! -f "$SCRIPT_DIR/token_eye.py" ] || [ "$PROJECT_DIR/swiftbar/token_eye.py" -nt "$SCRIPT_DIR/token_eye.py" ]; }; then
    PY_MODULE="$PROJECT_DIR/swiftbar/token_eye.py"
elif [ -f "$SCRIPT_DIR/token_eye.py" ]; then
    PY_MODULE="$SCRIPT_DIR/token_eye.py"
else
    PY_MODULE="$PROJECT_DIR/swiftbar/token_eye.py"
fi

if [ ! -f "$PY_MODULE" ]; then
    echo "👁 | color=$C_ERR"
    echo "---"
    echo "核心模块缺失: $PY_MODULE | color=$C_ERR"
    echo "---"
    echo "刷新 | refresh=true"
    exit 0
fi

# ---------------------------------------------------------------------------
# SwiftBar 点击动作（bash=… param1=… terminal=false）——注意：
# param1/param2 只作为本脚本的入参传递，插件本身不会收到参数。
# ---------------------------------------------------------------------------
# 动作：一键刷新 MiMo Cookie
# ---------------------------------------------------------------------------
if [ "${1:-}" = "refresh-mimo-cookie" ]; then
    REFRESH_SCRIPT="$PROJECT_DIR/scripts/refresh-mimo-cookie.py"
    if [ ! -f "$REFRESH_SCRIPT" ]; then
        notify "刷新脚本不存在: $REFRESH_SCRIPT"
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
        # 成功不打扰：主菜单（refresh=true）会自动重渲，余额恢复即反馈
        echo "👁 | color=$C_OK"
        echo "---"
        echo "✅ MiMo Cookie 刷新成功 | color=$C_OK"
        echo "---"
        echo "关闭 | refresh=true"
    else
        # 失败必须说清楚：后台执行看不到 stdout，取脚本关键行发通知
        MSG="$(printf '%s\n' "$OUTPUT" | grep -m1 -E '错误|失败|⚠️' || true)"
        [ -n "$MSG" ] || MSG="$(printf '%s\n' "$OUTPUT" | tail -1 || true)"
        notify "MiMo Cookie 刷新失败：$(printf '%s' "$MSG" | sed 's/|/:/g' | cut -c1-120)"
        echo "👁 | color=$C_ERR"
        echo "---"
        echo "❌ MiMo Cookie 刷新失败 | color=$C_ERR"
        echo "$OUTPUT" | tail -4 | sed 's/|/:/g' | while IFS= read -r line; do
            if [ -n "$line" ]; then
                echo "$line | color=$C_MUTED size=11"
            fi
        done
        echo "---"
        echo "重试 | bash=$SCRIPT_DIR/token-eye.sh param1=refresh-mimo-cookie terminal=false refresh=true"
        echo "关闭 | refresh=true"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# 动作：自检（bash=… param1=self-check）——结果写日志 + 通知回显
# ---------------------------------------------------------------------------
if [ "${1:-}" = "self-check" ]; then
    LOG_DIR="$HOME/Library/Caches/token-eye"
    LOG_FILE="$LOG_DIR/self-check.log"
    mkdir -p "$LOG_DIR" 2>/dev/null || true
    OUT="$(CONFIG_FILE="$CONFIG_FILE" PROJECT_DIR="$PROJECT_DIR" SCRIPT_DIR="$SCRIPT_DIR" /usr/bin/python3 "$PY_MODULE" --self-check 2>&1 || true)"
    printf '%s\n' "$OUT" > "$LOG_FILE" 2>/dev/null || true
    BAD="$(printf '%s\n' "$OUT" | grep -c '❌' || true)"
    WARN="$(printf '%s\n' "$OUT" | grep -c '⚠️' || true)"
    if [ "${BAD:-0}" -gt 0 ]; then
        FIRST="$(printf '%s\n' "$OUT" | grep -m1 '❌' | sed 's/|/:/g' | cut -c1-100 || true)"
        notify "自检发现 ${BAD} 处问题：${FIRST}（详见 self-check.log）"
    elif [ "${WARN:-0}" -gt 0 ]; then
        notify "自检通过，但有 ${WARN} 处提醒（详见 self-check.log）"
    else
        notify "自检全部通过"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# SwiftBar 点击动作（param1=upgrade, param2=版本）：一键升级
# ---------------------------------------------------------------------------
if [ "${1:-}" = "upgrade" ]; then
    UP_TAG="${2:-}"
    if [ -z "$UP_TAG" ]; then
        notify "升级失败：缺少版本号参数"
        echo "👁 | color=$C_ERR"
        echo "---"
        echo "❌ 升级失败：缺少版本号参数 | color=$C_ERR"
        echo "---"
        echo "关闭 | refresh=true"
        exit 0
    fi
    if [ -d "$PROJECT_DIR/.git" ]; then
        # 项目目录是 git 仓库：拉取最新 main 并同步插件（保持当前分支，ff-only 拒绝分叉）
        # SwiftBar 环境通常无代理，GitHub 直连常不通：
        # 1) 直连 fetch 加低速超时快速失败（约 8s），避免点击后无限挂起
        # 2) 直连失败后依次尝试国内镜像 fetch（main + tags）
        GIT_TIMEOUT=(-c http.lowSpeedLimit=1000 -c http.lowSpeedTime=8)
        MIRRORS=("https://gh-proxy.com/https://github.com/jimmywuxin/token-eye" "https://ghfast.top/https://github.com/jimmywuxin/token-eye" "https://ghproxy.net/https://github.com/jimmywuxin/token-eye")
        set +e
        FETCH_ERR="$(git "${GIT_TIMEOUT[@]}" -C "$PROJECT_DIR" fetch --tags origin 2>&1)"
        FETCH_RC=$?
        MERGE_ERR=""
        MERGE_RC=1
        if [ "$FETCH_RC" -ne 0 ]; then
            FETCH_ERR="直连失败，尝试镜像..."
            for M in "${MIRRORS[@]}"; do
                FETCH_ERR="$(git "${GIT_TIMEOUT[@]}" -C "$PROJECT_DIR" fetch "$M" "refs/heads/main:refs/remotes/origin/main" "refs/tags/*:refs/tags/*" 2>&1)"
                FETCH_RC=$?
                [ "$FETCH_RC" -eq 0 ] && break
            done
        fi
        if [ "$FETCH_RC" -eq 0 ]; then
            MERGE_ERR="$(git -C "$PROJECT_DIR" merge --ff-only origin/main 2>&1)"
            MERGE_RC=$?
        fi
        set -e
        if [ "$FETCH_RC" -eq 0 ] && [ "$MERGE_RC" -eq 0 ]; then
            if [ "$PROJECT_DIR/swiftbar/token-eye.sh" != "$SCRIPT_DIR/token-eye.sh" ]; then
                cp "$PROJECT_DIR/swiftbar/token-eye.sh" "$SCRIPT_DIR/token-eye.sh"
                chmod +x "$SCRIPT_DIR/token-eye.sh"
            fi
            echo "👁 | color=$C_OK"
            echo "---"
            echo "✅ 升级完成（项目已更新到最新 main，插件已同步）| color=$C_OK"
            echo "---"
            echo "关闭 | refresh=true"
            notify "已升级到最新 main，插件已同步"
        else
            notify "升级失败（git 拉取/合并出错）：$(printf '%s' "$FETCH_ERR" | tail -1 | cut -c1-100)"
            echo "👁 | color=$C_ERR"
            echo "---"
            echo "❌ 升级失败（git 拉取/合并出错）| color=$C_ERR"
            { echo "$FETCH_ERR"; echo "$MERGE_ERR"; } | tail -3 | sed 's/|/:/g' | while IFS= read -r line; do
                if [ -n "$line" ]; then
                    echo "$line | color=$C_MUTED size=11"
                fi
            done
            echo "---"
            echo "重试 | bash=$SCRIPT_DIR/token-eye.sh param1=upgrade param2=$UP_TAG terminal=false refresh=true"
            echo "关闭 | refresh=true"
        fi
    else
        # 非 git 仓库：下载 release tarball 替换插件文件（含核心逻辑副本）
        # 直连失败时依次尝试国内镜像
        TARBALL="/tmp/token-eye-${UP_TAG}.tar.gz"
        EXTRACT="/tmp/token-eye-upgrade-${UP_TAG}"
        URLS=("https://github.com/jimmywuxin/token-eye/archive/refs/tags/${UP_TAG}.tar.gz"
              "https://gh-proxy.com/https://github.com/jimmywuxin/token-eye/archive/refs/tags/${UP_TAG}.tar.gz"
              "https://ghfast.top/https://github.com/jimmywuxin/token-eye/archive/refs/tags/${UP_TAG}.tar.gz"
              "https://ghproxy.net/https://github.com/jimmywuxin/token-eye/archive/refs/tags/${UP_TAG}.tar.gz")
        DL_OK=0
        for U in "${URLS[@]}"; do
            if curl -fsSL --max-time 20 -o "$TARBALL" "$U" 2>/dev/null; then
                DL_OK=1
                break
            fi
        done
        if [ "$DL_OK" -eq 0 ]; then
            notify "升级失败：下载失败（网络或版本号错误）"
            echo "👁 | color=$C_ERR"
            echo "---"
            echo "❌ 升级失败：下载失败（网络或版本号错误）| color=$C_ERR"
            echo "   https://github.com/jimmywuxin/token-eye/releases/latest | href=https://github.com/jimmywuxin/token-eye/releases/latest color=$C_MUTED size=11"
            echo "---"
            echo "关闭 | refresh=true"
            exit 0
        fi
        rm -rf "$EXTRACT"
        mkdir -p "$EXTRACT"
        tar -xzf "$TARBALL" -C "$EXTRACT" 2>/dev/null
        NEW_SH="$(find "$EXTRACT" -path '*/swiftbar/token-eye.sh' | head -1)"
        if [ -z "$NEW_SH" ]; then
            notify "升级失败：压缩包内未找到插件脚本"
            echo "👁 | color=$C_ERR"
            echo "---"
            echo "❌ 升级失败：压缩包内未找到插件脚本 | color=$C_ERR"
            echo "---"
            echo "关闭 | refresh=true"
            exit 0
        fi
        cp "$NEW_SH" "$SCRIPT_DIR/token-eye.sh"
        chmod +x "$SCRIPT_DIR/token-eye.sh"
        NEW_PY="$(find "$EXTRACT" -path '*/swiftbar/token_eye.py' | head -1)"
        if [ -n "$NEW_PY" ]; then
            cp "$NEW_PY" "$SCRIPT_DIR/token_eye.py"
        fi
        echo "👁 | color=$C_OK"
        echo "---"
        echo "✅ 升级到 $UP_TAG 完成 | color=$C_OK"
        echo "---"
        echo "关闭 | refresh=true"
        notify "已升级到 $UP_TAG"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# 动作：复制余额到剪贴板（bash=… param1=copy-balance param2=内容）
# ---------------------------------------------------------------------------
if [ "${1:-}" = "copy-balance" ]; then
    printf '%s' "${2:-}" | pbcopy
    notify "已复制到剪贴板：${2:-}"
    echo "✅ 已复制到剪贴板: ${2:-} | color=$C_OK"
    echo "---"
    echo "关闭 | refresh=true"
    exit 0
fi

# ---------------------------------------------------------------------------
# 正常渲染：交给 Python 核心逻辑（PY_MODULE 已在文件前部解析）
# ---------------------------------------------------------------------------
CONFIG_FILE="$CONFIG_FILE" PROJECT_DIR="$PROJECT_DIR" SCRIPT_DIR="$SCRIPT_DIR" python3 "$PY_MODULE" "$@"
