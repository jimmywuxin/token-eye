#!/usr/bin/env bash
# <bitbar.title>Token Eye</bitbar.title>
# <bitbar.version>v0.7.5</bitbar.version>
# <bitbar.author>wuxin</bitbar.author>
# <bitbar.desc>LLM Token usage monitor — config-driven</bitbar.desc>
# <bitbar.refreshTime>30</bitbar.refreshTime>

set -euo pipefail


# Detect appearance for adaptive colors
if [ "$(defaults read -g AppleInterfaceStyle 2>/dev/null)" = "Dark" ]; then
    APPEARANCE="dark"
    C_DEFAULT="#ffffff"    # fallback: white on dark menu bar
    C_SECONDARY="#aaaaaa"  # fallback: light gray
    C_MUTED="#888888"      # fallback: medium gray
    C_HEADER="#FFD60A"     # fallback: bright yellow
else
    APPEARANCE="light"
    C_DEFAULT="#000000"    # pure black for max contrast on light menu bar
    C_SECONDARY="#2c2c2e"  # dark gray, readable on light bg
    C_MUTED="#48484a"      # medium gray
    C_HEADER="#0066CC"     # deep blue, replaces gold for better visibility
fi
export APPEARANCE C_DEFAULT C_SECONDARY C_MUTED C_HEADER
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
  echo "providers.json not found | color=#e74c3c"
  echo "Expected: $CONFIG_FILE | color=$C_MUTED size=11"
  exit 0
fi

RESULTS=$(CONFIG_FILE="$CONFIG_FILE" python3 << 'ENDOFPYTHON'
import json, subprocess, os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

config_path = os.environ["CONFIG_FILE"]
try:
    with open(config_path) as f:
        config = json.load(f)
except json.JSONDecodeError as e:
    print(json.dumps([{"id":"_error","name":"配置错误","status":"error","lines":[f"providers.json 解析失败: {e}"],"menu_bar":"错误","colors":["#e74c3c"]}]))
    sys.exit(0)
except FileNotFoundError:
    print(json.dumps([{"id":"_error","name":"配置错误","status":"error","lines":[f"文件不存在: {config_path}"],"menu_bar":"错误","colors":["#e74c3c"]}]))
    sys.exit(0)

# Adaptive colors from appearance detection
# Falls back to env vars if providers.json has no "colors" section
APPEARANCE = os.environ.get("APPEARANCE", "dark")
C_DEFAULT = os.environ.get("C_DEFAULT", "#ffffff")
C_SECONDARY = os.environ.get("C_SECONDARY", "#aaaaaa")
C_MUTED = os.environ.get("C_MUTED", "#888888")
_cfg_colors = config.get("colors", {}).get(APPEARANCE)
if _cfg_colors:
    C_DEFAULT = _cfg_colors.get("default", C_DEFAULT)
    C_SECONDARY = _cfg_colors.get("secondary", C_SECONDARY)
    C_MUTED = _cfg_colors.get("muted", C_MUTED)

def get_key(service):
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""

def resolve_field(obj, path):
    if obj is None or not path:
        return None
    for part in path.split("."):
        if obj is None:
            return None
        if isinstance(obj, list):
            try: part = int(part)
            except ValueError: return None
        try: obj = obj[part]
        except (KeyError, IndexError, TypeError): return None
    return obj

def format_ms(ms):
    sec = ms // 1000
    h, m = sec // 3600, (sec % 3600) // 60
    return f"{h}h{m}m" if h > 0 else f"{m}m"

def fetch_api(url, method, auth_header, auth_prefix, key):
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "5",
             "-w", "\n%{http_code}",
             "-H", f"{auth_header}: {auth_prefix}{key}",
             "-X", method, url],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            return None
        output = r.stdout.rstrip("\n")
        last_line = output.rsplit("\n", 1)[-1] if "\n" in output else output
        try:
            status_code = int(last_line.strip())
        except (ValueError, TypeError):
            return None
        body = output[:output.rfind("\n")] if "\n" in output else ""
        if status_code >= 400:
            try:
                err = json.loads(body)
                msg = err.get("error", {}).get("message", body)
            except (json.JSONDecodeError, AttributeError):
                msg = body[:100] if body.strip() else f"HTTP {status_code}"
            return {"_error": True, "status_code": status_code, "message": msg}
        return json.loads(body) if body.strip() else None
    except Exception:
        return None

C_OK = "#0072B2"
C_WARN = "#B86E00"
C_ERR = "#8E1A4A"

def process_provider(p):
    pid, name = p["id"], p["name"]
    keychain, api, parser = p["keychainService"], p["api"], p["parser"]
    display = p.get("display", {})

    key = get_key(keychain)
    if not key:
        return {"id": pid, "name": name, "status": "no_key", "lines": []}

    data = fetch_api(api["url"], api.get("method", "GET"),
                     api.get("authHeader", "Authorization"),
                     api.get("authPrefix", "Bearer "), key)

    if data is None:
        return {"id": pid, "name": name, "status": "error", "lines": ["API 请求失败"]}

    if data.get("_error"):
        msg = str(data.get("message", ""))[:80]
        return {"id": pid, "name": name, "status": "error", "lines": [f"API 错误: {msg}"]}

    ptype = parser["type"]

    if ptype == "balance":
        fields = parser.get("fields", {})
        balance = resolve_field(data, fields.get("balance", ""))
        currency = resolve_field(data, fields.get("currency", "CNY")) or "CNY"
        symbol = "$" if currency == "USD" else "¥"
        avail = data.get("is_available", True)
        status = "ok" if avail else "warn"
        if balance is not None:
            try:
                balance_str = str(round(float(balance), 2))
            except (ValueError, TypeError):
                balance_str = str(balance)
        else:
            balance_str = "?"
        return {
            "id": pid, "name": name, "status": status,
            "menu_bar": f"{symbol}{balance_str}",
            "lines": [f"{name}: {symbol}{balance_str}", "可用" if avail else "不可用"],
            "colors": [display.get("nameColor", C_DEFAULT), C_OK if avail else C_ERR],
        }

    elif ptype == "status":
        ok_field = parser.get("okField", "")
        ok_value = parser.get("okValue", "")
        actual = resolve_field(data, ok_field) if ok_field else data
        is_ok = (str(actual) == str(ok_value)) if ok_value else (actual is not None)
        label = display.get("label", "可用")
        color = C_OK if is_ok else C_ERR
        return {
            "id": pid, "name": name, "status": "ok" if is_ok else "error",
            "menu_bar": f"{label}",
            "lines": [f"{name}: {label}", "API Key 有效" if is_ok else "API Key 无效"],
            "colors": [color, C_SECONDARY],
        }

    elif ptype == "plan_usage":
        fields = parser.get("fields", {})
        raw = resolve_field(data, parser.get("arrayPath", "")) or []
        show = parser.get("showModels")
        labels = parser.get("modelLabels", {})
        item_lines, item_colors, menu_parts, boost_texts = [], [], [], []
        for item in raw:
            mname = str(resolve_field(item, fields.get("model", "")) or "")
            if show and mname not in show:
                continue
            try:
                pct = int(resolve_field(item, fields.get("intervalPct", "")) or 0)
            except (ValueError, TypeError):
                pct = 0
            try:
                interval_status = int(resolve_field(item, fields.get("intervalStatus", "")) or 0)
            except (ValueError, TypeError):
                interval_status = 0
            try:
                weekly_pct = int(resolve_field(item, fields.get("weeklyPct", "")) or 0)
            except (ValueError, TypeError):
                weekly_pct = 0
            try:
                weekly_status = int(resolve_field(item, fields.get("weeklyStatus", "")) or 0)
            except (ValueError, TypeError):
                weekly_status = 0
            try:
                interval_boost = int(resolve_field(item, fields.get("intervalBoost", "")) or 1000)
            except (ValueError, TypeError):
                interval_boost = 1000
            try:
                weekly_boost = int(resolve_field(item, fields.get("weeklyBoost", "")) or 1000)
            except (ValueError, TypeError):
                weekly_boost = 1000
            try:
                reset_ms = int(resolve_field(item, fields.get("resetMs", "")) or 0)
            except (ValueError, TypeError):
                reset_ms = 0
            reset = format_ms(reset_ms)
            label = labels.get(mname, mname)
            filled = max(1, pct // 5) if pct > 0 else 0
            bar = "█" * filled + "░" * (20 - filled)
            color = C_OK
            if pct < 10: color = C_ERR
            elif pct < 20: color = C_WARN
            icon = "✅" if pct >= 20 else ("⚠️" if pct >= 10 else "🔴")
            max_boost = max(interval_boost, weekly_boost)
            boost_tag = f" 🔥x{max_boost/1000:.1f}" if max_boost > 1000 else ""
            if boost_tag and boost_tag not in boost_texts:
                boost_texts.append(boost_tag)
            status_map = {1: "可用", 2: "耗尽临近", 3: "耗尽"}
            interval_state = status_map.get(interval_status, "未知")
            weekly_state = status_map.get(weekly_status, "未知")
            menu_parts.append(f"{icon} {label} {pct}%{boost_tag}")
            item_lines.extend([
                f"{label}: 5小时窗口 {pct}%（{interval_state}）",
                f"  周窗口 {weekly_pct}%（{weekly_state}）",
                f"  重置: {reset}",
                f"  {bar} {pct}%",
            ])
            item_colors.extend([display.get("nameColor", C_DEFAULT), C_SECONDARY, C_SECONDARY, color])

        if menu_parts:
            return {
                "id": pid, "name": name, "status": "ok",
                "menu_bar": " | ".join(menu_parts),
                "lines": [f"{name}:"] + item_lines,
                "colors": [display.get("nameColor", C_DEFAULT)] + item_colors,
            }
        else:
            return {"id": pid, "name": name, "status": "warn", "menu_bar": "无数据", "lines": ["无数据"], "colors": [C_SECONDARY]}

    else:
        return {
            "id": pid, "name": name, "status": "ok",
            "menu_bar": "raw",
            "lines": [json.dumps(data, ensure_ascii=False)[:200]],
            "colors": [C_SECONDARY],
        }

providers_list = [p for p in config.get("providers", []) if p.get("enabled", True)]
results = [None] * len(providers_list)
if providers_list:
    with ThreadPoolExecutor(max_workers=len(providers_list)) as executor:
        futures = {executor.submit(process_provider, p): i for i, p in enumerate(providers_list)}
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()

print(json.dumps(results, ensure_ascii=False))

ENDOFPYTHON
)

# ---------------------------------------------------------------------------
# Output SwiftBar format
# ---------------------------------------------------------------------------
echo "👁"
echo "---"
echo "Token Eye | color=$C_HEADER"

echo "$RESULTS" | python3 -c "
import sys, json
C_OK = '#2ecc71'; C_WARN = '#f39c12'; C_ERR = '#e74c3c'
results = json.load(sys.stdin)
for r in results:
    print('---')
    name = r['name']
    status = r['status']
    lines = r.get('lines', [])
    if status == 'no_key':
        print(f'🔑 {name}: 未配置 Key | color={C_WARN}')
        svc = name.upper().replace(' ','_') + '_API_KEY'
        print(f'  security add-generic-password -s {svc} -w your-key | font=Menlo size=11 color=$C_MUTED')
    elif status == 'error':
        msg = lines[0] if lines else '请求失败'
        print(f'🔴 {name}: {msg} | color={C_ERR}')
    else:
        colors = r.get('colors', [])
        for i, line in enumerate(lines):
            c = colors[i] if i < len(colors) else C_DEFAULT
            print(f'{line} | color={c}')
" 2>/dev/null || true

echo "---"
echo "刷新 | refresh=true"
echo "上次更新: $(date '+%H:%M:%S') | color=$C_MUTED size=11"
