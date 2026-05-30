#!/usr/bin/env bash
# <bitbar.title>Token Eye</bitbar.title>
# <bitbar.version>v0.3.0</bitbar.version>
# <bitbar.author>wuxin</bitbar.author>
# <bitbar.desc>LLM Token usage monitor — config-driven</bitbar.desc>
# <bitbar.refreshTime>60</bitbar.refreshTime>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/providers.json"
[ -f "$CONFIG_FILE" ] || CONFIG_FILE="${SCRIPT_DIR}/../providers.json"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "👁"
  echo "---"
  echo "providers.json not found | color=#e74c3c"
  exit 0
fi

RESULTS=$(CONFIG_FILE="$CONFIG_FILE" python3 << 'PYEOF'
import json, subprocess, sys, os

config_path = os.environ["CONFIG_FILE"]
with open(config_path) as f:
    config = json.load(f)

def get_key(service):
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except:
        return ""

def resolve_field(obj, path):
    if obj is None or not path:
        return None
    for part in path.split("."):
        if obj is None:
            return None
        if isinstance(obj, list):
            try:
                part = int(part)
            except ValueError:
                return None
        try:
            obj = obj[part]
        except (KeyError, IndexError, TypeError):
            return None
    return obj

def format_ms(ms):
    sec = ms // 1000
    h, m = sec // 3600, (sec % 3600) // 60
    return f"{h}h{m}m" if h > 0 else f"{m}m"

def fetch_api(url, method, auth_header, auth_prefix, key):
    try:
        r = subprocess.run(
            ["curl", "-sf", "--max-time", "10",
             "-H", f"{auth_header}: {auth_prefix}{key}",
             "-X", method, url],
            capture_output=True, text=True, timeout=15
        )
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except:
        return None

results = []
for p in config.get("providers", []):
    pid = p["id"]
    name = p["name"]
    keychain = p["keychainService"]
    api = p["api"]
    parser = p["parser"]
    display = p.get("display", {})

    key = get_key(keychain)
    if not key:
        results.append({"id": pid, "name": name, "status": "no_key", "lines": []})
        continue

    data = fetch_api(api["url"], api.get("method", "GET"),
                     api.get("authHeader", "Authorization"),
                     api.get("authPrefix", "Bearer "), key)

    if data is None:
        results.append({"id": pid, "name": name, "status": "error", "lines": ["API 请求失败"]})
        continue

    ptype = parser["type"]
    fields = parser.get("fields", {})

    if ptype == "balance":
        balance = resolve_field(data, fields.get("balance", ""))
        currency = resolve_field(data, fields.get("currency", "CNY")) or "CNY"
        symbol = "$" if currency == "USD" else "¥"
        avail = data.get("is_available", True)
        status = "ok" if avail else "warn"
        results.append({
            "id": pid, "name": name, "status": status,
            "menu_bar": f"{symbol}{balance}",
            "lines": [f"{name}: {symbol}{balance}", "可用" if avail else "不可用"],
            "colors": ["#ffffff", "#2ecc71" if avail else "#e74c3c"],
        })

    elif ptype == "plan_usage":
        raw = resolve_field(data, parser.get("arrayPath", "")) or []
        show = parser.get("showModels")
        labels = parser.get("modelLabels", {})
        item_lines = []
        item_colors = []
        menu_parts = []
        for item in raw:
            mname = str(resolve_field(item, fields.get("model", "")) or "")
            if show and not any(mname.startswith(s.replace("*", "")) for s in show):
                continue
            total = int(resolve_field(item, fields.get("total", "")) or 0)
            used = int(resolve_field(item, fields.get("used", "")) or 0)
            remaining = total - used
            pct = round(remaining / total * 100) if total > 0 else 0
            reset_ms = int(resolve_field(item, fields.get("resetMs", "")) or 0)
            reset = format_ms(reset_ms)
            label = labels.get(mname, mname)
            filled = pct // 5
            bar = "█" * filled + "░" * (20 - filled)
            color = "#2ecc71"
            if pct < 10: color = "#e74c3c"
            elif pct < 20: color = "#f39c12"
            icon = "✅" if pct >= 20 else ("⚠️" if pct >= 10 else "🔴")
            menu_parts.append(f"{icon} {label} {remaining}/{total}")
            item_lines.extend([
                f"{label}: {remaining}/{total}次",
                f"  重置: {reset}",
                f"  {bar} {pct}%",
            ])
            item_colors.extend(["#ffffff", "#888888", color])

        if menu_parts:
            results.append({
                "id": pid, "name": name, "status": "ok",
                "menu_bar": " | ".join(menu_parts),
                "lines": [f"{name}:"] + item_lines,
                "colors": ["#ffffff"] + item_colors,
            })
        else:
            results.append({"id": pid, "name": name, "status": "warn", "menu_bar": "无数据", "lines": ["无数据"], "colors": ["#888888"]})

    else:
        results.append({
            "id": pid, "name": name, "status": "ok",
            "menu_bar": "raw",
            "lines": [json.dumps(data, ensure_ascii=False)[:200]],
            "colors": ["#888888"],
        })

print(json.dumps(results, ensure_ascii=False))
PYEOF
)

# ---------------------------------------------------------------------------
# Output SwiftBar format
# ---------------------------------------------------------------------------
MENU_BAR=$(echo "$RESULTS" | python3 -c "
import sys, json
results = json.load(sys.stdin)
parts = []
for r in results:
    icon = '🔑' if r['status'] == 'no_key' else ('⚠️' if r['status'] in ('warn','error') else '✅')
    parts.append(f\"{icon} {r.get('menu_bar', r['name'])}\")
print('  |  '.join(parts))
" 2>/dev/null || echo "👁")

echo "👁"
echo "---"
echo "Token Eye | color=#888888"

echo "$RESULTS" | python3 -c "
import sys, json
results = json.load(sys.stdin)
for r in results:
    print('---')
    name = r['name']
    status = r['status']
    if status == 'no_key':
        print(f'🔑 {name}: 未配置 Key | color=#f39c12')
        svc = name.upper().replace(' ','_') + '_API_KEY'
        print(f'  security add-generic-password -s {svc} -w your-key | font=Menlo size=11 color=#888888')
    elif status == 'error':
        print(f'🔴 {name}: 请求失败 | color=#e74c3c')
    else:
        lines = r.get('lines', [])
        colors = r.get('colors', [])
        for i, line in enumerate(lines):
            c = colors[i] if i < len(colors) else '#ffffff'
            print(f'{line} | color={c}')
" 2>/dev/null

echo "---"
echo "刷新 | refresh=true"
echo "上次更新: $(date '+%H:%M:%S') | color=#666666 size=11"

