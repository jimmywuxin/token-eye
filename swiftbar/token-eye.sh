#!/usr/bin/env bash
# <bitbar.title>Token Eye</bitbar.title>
# <bitbar.version>v0.24.0</bitbar.version>
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
    # 完整转义：反斜杠 / 双引号 / 换行都能改变 AppleScript 语句结构。
    # 消息部分来自刷新脚本 stdout，旧实现只去掉双引号不够。
    local msg
    msg="$(printf '%s' "${1:-}" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n\r' '  ')"
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

# 解释器只解析一次，所有动作分支与正常渲染共用。
# 旧代码点击动作写死系统 Python 绝对路径（未装 Xcode CLT 的 Mac 上不存在），
# 且用 || true 静默吞掉，表现为「点了没反应」。
PY_BIN="$(command -v python3)"
export PY_BIN

# 核心模块取「较新的一个」：项目目录里改了新版而 ~/SwiftBar 存着旧拷贝时用项目那份。
# 两处都不存在时留空，由下面的存在性检查统一报错。
if [ -f "$PROJECT_DIR/swiftbar/token_eye.py" ] && { [ ! -f "$SCRIPT_DIR/token_eye.py" ] || [ "$PROJECT_DIR/swiftbar/token_eye.py" -nt "$SCRIPT_DIR/token_eye.py" ]; }; then
    PY_MODULE="$PROJECT_DIR/swiftbar/token_eye.py"
elif [ -f "$SCRIPT_DIR/token_eye.py" ]; then
    PY_MODULE="$SCRIPT_DIR/token_eye.py"
else
    PY_MODULE=""
fi

if [ -z "$PY_MODULE" ] || [ ! -f "$PY_MODULE" ]; then
    echo "👁 | color=$C_ERR"
    echo "---"
    echo "核心模块缺失: ${PY_MODULE:-$PROJECT_DIR/swiftbar/token_eye.py} | color=$C_ERR"
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
    OUTPUT="$("$PY_BIN" "$REFRESH_SCRIPT" 2>&1 || true)"
    if echo "$OUTPUT" | grep -q "HTTP=200"; then
        # 成功不打扰：主菜单（refresh=true）会自动重渲，余额恢复即反馈
        echo "👁 | color=$C_OK"
        echo "---"
        echo "✅ MiMo Cookie 刷新成功 | color=$C_OK"
        echo "---"
        echo "关闭 | refresh=true"
    else
        # 失败必须说清楚：后台执行看不到 stdout，取脚本关键行发通知
        # 优先取脚本的结论行（「错误: …」）——它带可操作动作；「警告: …」只是过程噪音，
        # 以前的贪婪匹配会先命中「警告: 拷贝 Cookies 失败」，把真正原因挤掉。
        MSG="$(printf '%s\n' "$OUTPUT" | grep -m1 '^错误' || true)"
        [ -n "$MSG" ] || MSG="$(printf '%s\n' "$OUTPUT" | grep -m1 -E '错误|失败|⚠️' || true)"
        [ -n "$MSG" ] || MSG="$(printf '%s\n' "$OUTPUT" | tail -1 || true)"
        if printf '%s' "$MSG" | grep -q "磁盘访问"; then
            # 读不到浏览器 Cookie 库 = TCC 拦了 open()：重登多少次都没用，
            # 必须先授权（macOS 27 起浏览器数据目录算系统策略保护），
            # 通知里直接给出授权路径，别让用户以为是自己没登录（2026-10-19 实报）
            PERM_DENIED=1
            notify "MiMo 刷新失败：系统不让读浏览器 Cookie 库——到「系统设置 → 隐私与安全性 → 完全磁盘访问权限」勾选 SwiftBar（手动运行则勾选终端），再点重试"
        elif printf '%s' "$MSG" | grep -q "重新登录"; then
            # 会话真的失效：直接把「要做什么」写进通知，别让用户从长句里自己找
            notify "MiMo 登录已失效：请在登录页重新登录，完成后点菜单「🔄 登录后重试」"
        else
            notify "MiMo Cookie 刷新失败：$(printf '%s' "$MSG" | sed 's/|/:/g' | cut -c1-120)"
        fi
        echo "👁 | color=$C_ERR"
        echo "---"
        echo "❌ MiMo Cookie 刷新失败 | color=$C_ERR"
        echo "$OUTPUT" | tail -4 | sed 's/|/:/g' | while IFS= read -r line; do
            if [ -n "$line" ]; then
                echo "$line | color=$C_MUTED size=11"
            fi
        done
        echo "---"
        # 失败后的两条出路：先在浏览器重新登录 MiMo（会话过期时只有登录能救），
        # 登录完成后点「重试」重新提取 Cookie。不写这条链接用户只能自己猜。
        if [ "${PERM_DENIED:-0}" = 1 ]; then
            echo "🔧 打开「完全磁盘访问权限」设置 | href=x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AllFiles color=$C_WARN"
        fi
        echo "🌐 打开 MiMo 平台重新登录 | href=https://platform.xiaomimimo.com/console/balance color=$C_WARN"
        echo "🔄 登录后重试（提取新 Cookie） | bash=$SCRIPT_DIR/token-eye.sh param1=refresh-mimo-cookie terminal=false refresh=true"
        echo "关闭 | refresh=true"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# 动作：CLI 型平台的登录自愈（bash=… param1=recover param2=<脚本名>）
# 千问这类「只有 CLI、没有 HTTP 余额接口」的平台没有 cookie 可刷，token 过期只能重走
# 设备码授权。脚本负责「打开浏览器授权页 + 后台轮询」，这里只补一条兜底通知：
# 后台执行看不到 stdout，但脚本自己会发通知，所以这里成功不打扰、失败才回显。
# ---------------------------------------------------------------------------
if [ "${1:-}" = "recover" ]; then
    REC_NAME="${2:-}"
    # 脚本名会被拼进 $PROJECT_DIR/scripts/<name>.py，含 ../ 就能越出目录执行任意 .py
    if [[ ! "$REC_NAME" =~ ^[A-Za-z0-9_-]+$ ]]; then
        notify "登录脚本名非法（只允许字母、数字、下划线、连字符）"
        echo "👁 | color=$C_ERR"
        echo "---"
        echo "登录脚本名非法 | color=$C_ERR"
        echo "---"
        echo "关闭 | refresh=true"
        exit 0
    fi
    REC_SCRIPT="$PROJECT_DIR/scripts/$REC_NAME.py"
    if [ -z "$REC_NAME" ] || [ ! -f "$REC_SCRIPT" ]; then
        notify "登录脚本不存在: $REC_SCRIPT"
        echo "👁 | color=$C_ERR"
        echo "---"
        echo "登录脚本不存在: $REC_SCRIPT | color=$C_ERR"
        echo "---"
        echo "关闭 | refresh=true"
        exit 0
    fi
    OUTPUT="$("$PY_BIN" "$REC_SCRIPT" --force 2>&1 || true)"
    # 脚本三种结局：已登录 / 已发起授权等待确认 / 发起失败。
    # 前两种脚本自己会弹通知（发起授权时），所以这里只为「失败」补一条，避免重复打扰。
    echo "👁"
    echo "---"
    if printf '%s' "$OUTPUT" | grep -q "^错误"; then
        notify "$(printf '%s' "$OUTPUT" | grep -m1 '^错误' | cut -c1-120)"
        echo "❌ 登录发起失败 | color=$C_ERR"
    elif printf '%s' "$OUTPUT" | grep -q "已登录"; then
        echo "✅ 已是登录状态 | color=$C_OK"
    else
        echo "✅ 已打开浏览器授权页，确认后自动恢复 | color=$C_OK"
    fi
    printf '%s\n' "$OUTPUT" | tail -3 | sed 's/|/:/g' | while IFS= read -r line; do
        [ -n "$line" ] && echo "$line | color=$C_MUTED size=11"
    done
    echo "---"
    echo "关闭 | refresh=true"
    exit 0
fi

# ---------------------------------------------------------------------------
# 动作：自检（bash=… param1=self-check）——结果写日志 + 通知回显
# ---------------------------------------------------------------------------
if [ "${1:-}" = "self-check" ]; then
    LOG_DIR="$HOME/Library/Caches/token-eye"
    LOG_FILE="$LOG_DIR/self-check.log"
    mkdir -p "$LOG_DIR" 2>/dev/null || true
    OUT="$(CONFIG_FILE="$CONFIG_FILE" PROJECT_DIR="$PROJECT_DIR" SCRIPT_DIR="$SCRIPT_DIR" "$PY_BIN" "$PY_MODULE" --self-check 2>&1 || true)"
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
# 动作：一键刷新（bash=… param1=refresh-now terminal=false refresh=true）
# 以 --force-refresh 跑一轮核心逻辑：忽略 10s 错误短缓存 + 跳过自愈冷却，
# 在同一轮内完成「刷 Cookie → 重拉余额」并写回缓存。输出被 SwiftBar 丢弃，
# 菜单反馈由随后的 refresh=true 重渲给出（余额直接出现在主菜单）。
# ---------------------------------------------------------------------------
if [ "${1:-}" = "refresh-now" ]; then
    if OUT="$(CONFIG_FILE="$CONFIG_FILE" PROJECT_DIR="$PROJECT_DIR" SCRIPT_DIR="$SCRIPT_DIR" \
        "$PY_BIN" "$PY_MODULE" --force-refresh 2>&1)"; then
        :  # 成功：菜单由随后的 refresh=true 重渲给出反馈
    else
        # 旧实现 >/dev/null + || true 把失败全吞了，用户只看到「点了没反应」
        LOG_DIR="$HOME/Library/Caches/token-eye"
        mkdir -p "$LOG_DIR" 2>/dev/null || true
        printf '%s\n' "$OUT" > "$LOG_DIR/refresh-now.log" 2>/dev/null || true
        notify "一键刷新执行失败，详见 ~/Library/Caches/token-eye/refresh-now.log"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# 正常渲染：交给 Python 核心逻辑（PY_MODULE 已在文件前部解析）
# ---------------------------------------------------------------------------
CONFIG_FILE="$CONFIG_FILE" PROJECT_DIR="$PROJECT_DIR" SCRIPT_DIR="$SCRIPT_DIR" "$PY_BIN" "$PY_MODULE" "$@"
