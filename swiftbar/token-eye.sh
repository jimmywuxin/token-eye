#!/usr/bin/env bash
# <bitbar.title>Token Eye</bitbar.title>
# <bitbar.version>v0.9.0</bitbar.version>
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
    OUTPUT=$(/usr/bin/python3 "$REFRESH_SCRIPT" 2>&1)
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
        echo "$OUTPUT" | tail -2 | sed 's/|/:/g' | while IFS= read -r line; do
            [ -n "$line" ] && echo "$line | color=$C_MUTED size=11"
        done
        echo "---"
        echo "重试 | param1=refresh-mimo-cookie refresh=true"
        echo "关闭 | refresh=true"
    fi
    exit 0
fi

CONFIG_FILE="$CONFIG_FILE" PROJECT_DIR="$PROJECT_DIR" python3 << 'ENDOFPYTHON'
import json, subprocess, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

config_path = os.environ["CONFIG_FILE"]
project_dir = os.environ.get("PROJECT_DIR", "")
cache_dir = "/tmp"

try:
    with open(config_path) as f:
        config = json.load(f)
except json.JSONDecodeError as e:
    print("👁 | color=#e74c3c")
    print("---")
    print("providers.json 解析失败 | color=#e74c3c")
    print(f"{e} | color=#888 size=11")
    print("---")
    print("刷新 | refresh=true")
    sys.exit(0)
except FileNotFoundError:
    print("👁 | color=#e74c3c")
    print("---")
    print(f"配置文件不存在: {config_path} | color=#e74c3c")
    print("---")
    print("刷新 | refresh=true")
    sys.exit(0)

# Adaptive colors (env fallback -> providers.json override)
APPEARANCE = os.environ.get("APPEARANCE", "dark")
C_DEFAULT = os.environ.get("C_DEFAULT", "#ffffff")
C_SECONDARY = os.environ.get("C_SECONDARY", "#aaaaaa")
C_MUTED = os.environ.get("C_MUTED", "#888888")
C_HEADER = os.environ.get("C_HEADER", "#FFD60A")
C_OK = os.environ.get("C_OK", "#2ecc71")
C_WARN = os.environ.get("C_WARN", "#f39c12")
C_ERR = os.environ.get("C_ERR", "#e74c3c")
_cfg_colors = config.get("colors", {}).get(APPEARANCE)
if _cfg_colors:
    C_DEFAULT = _cfg_colors.get("default", C_DEFAULT)
    C_SECONDARY = _cfg_colors.get("secondary", C_SECONDARY)
    C_MUTED = _cfg_colors.get("muted", C_MUTED)
    C_HEADER = _cfg_colors.get("header", C_HEADER)
    C_OK = _cfg_colors.get("ok", C_OK)
    C_WARN = _cfg_colors.get("warn", C_WARN)
    C_ERR = _cfg_colors.get("err", C_ERR)

# Default cache TTL by parser type (seconds)
DEFAULT_CACHE_TTL = {"balance": 300, "plan_usage": 30, "status": 60}
_cfg_cache = config.get("cache", {})
ERROR_CACHE_TTL = 10  # 失败短缓存，避免连续打 API

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
            try: idx = int(part)
            except ValueError: return None
            try: obj = obj[idx]
            except IndexError: return None
        else:
            try: obj = obj[part]
            except (KeyError, TypeError): return None
    return obj

def format_ms(ms):
    sec = ms // 1000
    h, m = sec // 3600, (sec % 3600) // 60
    return f"{h}h{m}m" if h > 0 else f"{m}m"

def load_cache(pid):
    path = os.path.join(cache_dir, f"token-eye-cache-{pid}.json")
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None

def save_cache(pid, payload):
    path = os.path.join(cache_dir, f"token-eye-cache-{pid}.json")
    try:
        with open(path, "w") as f:
            json.dump(payload, f)
    except Exception:
        pass

# ---- 余额历史（趋势）----
def _history_dir():
    d = os.path.expanduser("~/Library/Caches/token-eye")
    try: os.makedirs(d, exist_ok=True)
    except Exception: pass
    return d

def append_history(pid, value):
    try:
        with open(os.path.join(_history_dir(), f"history-{pid}.jsonl"), "a") as f:
            f.write(f"{int(time.time())},{value}\n")
    except Exception:
        pass

def load_history(pid, n=24):
    out = []
    try:
        with open(os.path.join(_history_dir(), f"history-{pid}.jsonl")) as f:
            lines = f.read().strip().splitlines()
        for line in lines[-n:]:
            ts, _, val = line.partition(",")
            try:
                out.append((int(ts), float(val)))
            except (ValueError, TypeError):
                continue
    except Exception:
        pass
    return out

def sparkline(values, width=12):
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = hi - lo if hi > lo else 1.0
    chars = "▁▂▃▄▅▆▇█"
    return "".join(chars[min(len(chars) - 1, int((v - lo) / span * (len(chars) - 1)))] for v in values)

# ---- 版本自检 ----
VERSION = "0.9.0"

def _ver_gt(a, b):
    import re
    pa = [int(x) for x in re.findall(r"\d+", a)]
    pb = [int(x) for x in re.findall(r"\d+", b)]
    return pa > pb

def check_latest_version():
    cache_file = os.path.join(_history_dir(), "latest-release.json")
    now = int(time.time())
    try:
        if os.path.exists(cache_file):
            with open(cache_file) as f:
                d = json.load(f)
            if now - d.get("ts", 0) < 86400:
                return d.get("tag_name", "")
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "4",
             "https://api.github.com/repos/jimmywuxin/token-eye/releases/latest"],
            capture_output=True, text=True, timeout=6)
        d = json.loads(r.stdout)
        tag = d.get("tag_name", "")
        if tag:
            try:
                with open(cache_file, "w") as f:
                    json.dump({"ts": now, "tag_name": tag}, f)
            except Exception:
                pass
        return tag
    except Exception:
        return ""

def fetch_api(url, method, auth_header, auth_prefix, key, extra_headers=None):
    """Returns {ok, status, data, error_kind, message}."""
    cmd = ["curl", "-s", "--max-time", "5",
           "-w", "\n%{http_code}",
           "-H", f"{auth_header}: {auth_prefix}{key}"]
    if extra_headers:
        for k, v in extra_headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
    cmd.extend(["-X", method, url])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": None, "data": None, "error_kind": "timeout", "message": "请求超时"}
    except Exception as e:
        return {"ok": False, "status": None, "data": None, "error_kind": "network", "message": f"网络失败: {e}"}
    if r.returncode != 0:
        return {"ok": False, "status": None, "data": None, "error_kind": "network", "message": "curl 退出非零"}
    output = r.stdout.rstrip("\n")
    last_line = output.rsplit("\n", 1)[-1] if "\n" in output else output
    try:
        status_code = int(last_line.strip())
    except (ValueError, TypeError):
        return {"ok": False, "status": None, "data": None, "error_kind": "parse", "message": "无法解析 HTTP 状态"}
    body = output[:output.rfind("\n")] if "\n" in output else ""
    if status_code >= 500:
        return {"ok": False, "status": status_code, "data": None, "error_kind": "server", "message": f"服务端异常 HTTP {status_code}"}
    if status_code >= 400:
        try:
            err = json.loads(body)
            msg = err.get("error", {}).get("message", body[:80]) if isinstance(err, dict) else body[:80]
        except (json.JSONDecodeError, AttributeError):
            msg = body[:80] if body.strip() else f"HTTP {status_code}"
        return {"ok": False, "status": status_code, "data": None, "error_kind": "client", "message": msg}
    try:
        data = json.loads(body) if body.strip() else None
    except json.JSONDecodeError as e:
        return {"ok": False, "status": status_code, "data": None, "error_kind": "parse", "message": f"JSON 解析失败: {e}"}
    return {"ok": True, "status": status_code, "data": data, "error_kind": None, "message": ""}

def send_notify(title, message):
    try:
        # 转义双引号
        safe_msg = message.replace('"', '\\"')
        safe_title = title.replace('"', '\\"')
        subprocess.run([
            "osascript", "-e",
            f'display notification "{safe_msg}" with title "{safe_title}"'
        ], timeout=5, capture_output=True)
    except Exception:
        pass

def alert_check(pid, name, balance_val, alert_cfg):
    """Returns notify message or None."""
    if not alert_cfg:
        return None
    min_bal = alert_cfg.get("minBalance")
    if min_bal is None:
        return None
    try:
        bal = float(balance_val)
    except (ValueError, TypeError):
        return None
    flag = os.path.join(cache_dir, f"token-eye-alerted-{pid}.flag")
    if bal >= min_bal:
        if os.path.exists(flag):
            try: os.remove(flag)
            except Exception: pass
        return None
    if os.path.exists(flag):
        return None
    try:
        with open(flag, "w") as f:
            f.write(str(bal))
    except Exception:
        pass
    return f"{name} 余额仅 {bal:.2f}，低于阈值 {min_bal}"

def name_color(display):
    """display.nameColor 支持深浅双套：字符串（旧版兼容）或 {"dark":..., "light":...}"""
    nc = display.get("nameColor", C_DEFAULT)
    if isinstance(nc, dict):
        return nc.get(APPEARANCE, nc.get("dark", C_DEFAULT))
    return nc


def parse_provider(p, fetch_result):
    pid, name = p["id"], p["name"]
    parser = p["parser"]
    display = p.get("display", {})
    console_url = p.get("consoleUrl")
    data = fetch_result["data"]
    ptype = parser["type"]
    NC = name_color(display)

    if ptype == "balance":
        fields = parser.get("fields", {})
        balance = resolve_field(data, fields.get("balance", ""))
        currency = resolve_field(data, fields.get("currency", "CNY")) or "CNY"
        symbol = "$" if currency == "USD" else "¥"
        avail = data.get("is_available", True) if isinstance(data, dict) else True
        status = "ok" if avail else "warn"
        balance_num = None
        if balance is not None:
            try:
                balance_num = float(balance)
                balance_str = str(round(balance_num, 2))
            except (ValueError, TypeError):
                balance_str = str(balance)
        else:
            balance_str = "?"
        return {
            "id": pid, "name": name, "status": status,
            "menu_bar": f"{symbol}{balance_str}",
            "lines": [f"{name}: {symbol}{balance_str}", "可用" if avail else "不可用"],
            "colors": [NC, C_OK if avail else C_ERR],
            "console_url": console_url,
            "balance_num": balance_num,
            "currency": currency,
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
            "console_url": console_url,
        }

    elif ptype == "plan_usage":
        fields = parser.get("fields", {})
        raw = resolve_field(data, parser.get("arrayPath", "")) or []
        show = parser.get("showModels")
        labels = parser.get("modelLabels", {})
        # status_map 兼容 int/str key
        raw_status_map = parser.get("statusMap", {"1": "可用", "2": "耗尽临近", "3": "耗尽"})
        status_map = {str(k): v for k, v in raw_status_map.items()}
        bar_length = parser.get("barLength", 20)
        item_lines, item_colors, menu_parts, boost_texts = [], [], [], []
        min_pct = None
        for item in raw:
            mname = str(resolve_field(item, fields.get("model", "")) or "")
            if show and mname not in show:
                continue
            def _int(v, default=0):
                try: return int(resolve_field(item, fields.get(v, "")) or default)
                except (ValueError, TypeError): return default
            def _int_or_none(v):
                val = resolve_field(item, fields.get(v, ""))
                try:
                    return int(val) if val is not None and str(val).strip() != "" else None
                except (ValueError, TypeError):
                    return None
            pct = _int("intervalPct", 0)
            interval_status = _int("intervalStatus", 0)
            weekly_pct = _int("weeklyPct", 0)
            weekly_status = _int("weeklyStatus", 0)
            interval_boost = _int("intervalBoost", 1000)
            weekly_boost = _int("weeklyBoost", 1000)
            reset_ms = _int("resetMs", 0)
            reset = format_ms(reset_ms)
            label = labels.get(mname, mname)
            filled = max(1, pct * bar_length // 100) if pct > 0 else 0
            bar = "█" * filled + "░" * (bar_length - filled)
            color = C_OK
            if pct < 10: color = C_ERR
            elif pct < 20: color = C_WARN
            icon = "✅" if pct >= 20 else ("⚠️" if pct >= 10 else "🔴")
            max_boost = max(interval_boost, weekly_boost)
            boost_tag = f" 🔥x{max_boost/1000:.1f}" if max_boost > 1000 else ""
            if boost_tag and boost_tag not in boost_texts:
                boost_texts.append(boost_tag)
            interval_state = status_map.get(str(interval_status), "未知")
            weekly_state = status_map.get(str(weekly_status), "未知")
            # total=0 表示该窗口无套餐配额，状态显示「无套餐」而非「耗尽」
            no_quota_label = parser.get("noQuotaLabel", "无套餐")
            if _int_or_none("intervalTotal") == 0:
                interval_state = no_quota_label
            if _int_or_none("weeklyTotal") == 0:
                weekly_state = no_quota_label
            menu_parts.append(f"{icon} {label} {pct}%{boost_tag}")
            item_lines.extend([
                f"{label}: 5小时窗口 {pct}%（{interval_state}）",
                f"  周窗口 {weekly_pct}%（{weekly_state}）",
                f"  重置: {reset}",
                f"  {bar} {pct}%",
            ])
            item_colors.extend([NC, C_SECONDARY, C_SECONDARY, color])
            if min_pct is None or pct < min_pct:
                min_pct = pct

        if menu_parts:
            return {
                "id": pid, "name": name, "status": "ok",
                "menu_bar": " | ".join(menu_parts),
                "lines": [f"{name}:"] + item_lines,
                "colors": [NC] + item_colors,
                "console_url": console_url,
                "min_pct": min_pct,
            }
        else:
            return {"id": pid, "name": name, "status": "warn", "menu_bar": "无数据",
                    "lines": ["无数据"], "colors": [C_SECONDARY], "console_url": console_url}

    else:
        return {
            "id": pid, "name": name, "status": "ok",
            "menu_bar": "raw",
            "lines": [json.dumps(data, ensure_ascii=False)[:200]],
            "colors": [C_SECONDARY],
            "console_url": console_url,
        }

def render_error(pid, name, error_kind, message, console_url):
    label_map = {"timeout": "请求超时", "network": "网络失败", "server": "服务端异常",
                 "client": "配置/鉴权错误", "parse": "解析失败"}
    label = label_map.get(error_kind, "请求失败")
    # 临时故障（网络/服务端）用 warn 色提醒；配置错误用 err 色
    color = C_WARN if error_kind in ("timeout", "network", "server") else C_ERR
    return {
        "id": pid, "name": name, "status": "error", "error_kind": error_kind,
        "lines": [f"{label}: {str(message)[:80]}"],
        "colors": [color],
        "menu_bar": "",
        "console_url": console_url,
    }

def auto_refresh_cookie(pid, refresh_script):
    """自动刷新 Cookie（401 自愈）。带 30 分钟防抖，避免反复打脚本。返回 (ok, 输出)"""
    flag = os.path.join(cache_dir, f"token-eye-autorefresh-{pid}.flag")
    now = int(time.time())
    try:
        if os.path.exists(flag):
            with open(flag) as f:
                last = int(f.read().strip() or 0)
            if now - last < 1800:
                return False, "防抖中（30 分钟内已自动尝试过）"
    except Exception:
        pass
    try:
        with open(flag, "w") as f:
            f.write(str(now))
    except Exception:
        pass
    try:
        r = subprocess.run(["/usr/bin/python3", refresh_script],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and "HTTP=200" in r.stdout:
            return True, ""
        return False, (r.stdout or r.stderr).strip()[-150:]
    except Exception as e:
        return False, str(e)

def process_provider(p):
    pid, name = p["id"], p["name"]
    keychain, api, parser = p["keychainService"], p["api"], p["parser"]
    ptype = parser["type"]
    console_url = p.get("consoleUrl")
    refresh_param = p.get("refreshParam")
    alert_cfg = p.get("alert") or config.get("alerts", {}).get(pid)

    # Cache check
    ttl = p.get("cacheTtl", _cfg_cache.get(ptype, DEFAULT_CACHE_TTL.get(ptype, 30)))
    cached = load_cache(pid)
    now = int(time.time())
    is_err_cache = bool(cached and cached.get("data") is None and cached.get("error"))
    effective_ttl = ERROR_CACHE_TTL if is_err_cache else ttl

    if cached and (now - cached.get("ts", 0)) < effective_ttl:
        if is_err_cache:
            return render_error(pid, name, cached.get("error"), cached.get("message", ""), console_url)
        # 命中成功缓存，跳过 API
        fetch_result = {"ok": True, "status": 200, "data": cached["data"], "error_kind": None, "message": ""}
    else:
        key = get_key(keychain)
        if not key:
            return {"id": pid, "name": name, "status": "no_key", "lines": [],
                    "menu_bar": "", "console_url": console_url,
                    "keychainService": keychain}
        fetch_result = fetch_api(
            api["url"], api.get("method", "GET"),
            api.get("authHeader", "Authorization"),
            api.get("authPrefix", "Bearer "), key,
            api.get("headers")
        )

        # 自动自愈：client 鉴权错误 + 配置了 refreshParam → 刷新 Cookie 后重试一次
        if (not fetch_result["ok"] and fetch_result.get("error_kind") == "client"
                and refresh_param):
            script = os.path.join(project_dir, "scripts", refresh_param + ".py")
            if os.path.exists(script):
                refreshed, _ = auto_refresh_cookie(pid, script)
                if refreshed:
                    key2 = get_key(keychain)
                    if key2:
                        fetch_result = fetch_api(
                            api["url"], api.get("method", "GET"),
                            api.get("authHeader", "Authorization"),
                            api.get("authPrefix", "Bearer "), key2,
                            api.get("headers")
                        )

        if fetch_result["ok"]:
            save_cache(pid, {"ts": now, "data": fetch_result["data"]})
        else:
            save_cache(pid, {"ts": now, "data": None,
                             "error": fetch_result["error_kind"],
                             "message": fetch_result["message"]})

    if not fetch_result["ok"]:
        return render_error(pid, name, fetch_result["error_kind"], fetch_result["message"], console_url)

    render = parse_provider(p, fetch_result)

    # Balance history（趋势 + 当日变化）
    if ptype == "balance" and render.get("balance_num") is not None:
        append_history(pid, render["balance_num"])
        hist = load_history(pid, 24)
        if len(hist) >= 2:
            prev_val = hist[-2][1]
            diff = render["balance_num"] - prev_val
            change = f"{'+' if diff > 0 else ''}{diff:.2f}"
            trend = sparkline([v for _, v in hist])
            render.setdefault("lines", []).append(f"  趋势: {trend}  ({change})")
            render.setdefault("colors", []).append(C_SECONDARY)

    # Alert check (balance 余额 / plan_usage 用量百分比)
    if os.environ.get("TOKEN_EYE_NOTIFY", "1") != "0":
        if ptype == "balance" and render.get("balance_num") is not None:
            notify_msg = alert_check(pid, name, render["balance_num"], alert_cfg)
            if notify_msg:
                send_notify("Token Eye 告警", notify_msg)
        elif ptype == "plan_usage" and render.get("min_pct") is not None and alert_cfg:
            min_pct = alert_cfg.get("minPct")
            if min_pct is not None and render["min_pct"] < int(min_pct):
                flag = os.path.join(cache_dir, f"token-eye-alerted-{pid}.flag")
                if not os.path.exists(flag):
                    try:
                        with open(flag, "w") as f:
                            f.write(str(render["min_pct"]))
                    except Exception:
                        pass
                    send_notify("Token Eye 告警",
                                f"{name} 用量剩余仅 {render['min_pct']}%，低于阈值 {min_pct}%")
            else:
                try:
                    if os.path.exists(flag := os.path.join(cache_dir, f"token-eye-alerted-{pid}.flag")):
                        os.remove(flag)
                except Exception:
                    pass

    return render

# ---- Schema 校验 ----
schema_errors = []
for idx, p in enumerate(config.get("providers", [])):
    if not isinstance(p, dict):
        schema_errors.append(f"providers[{idx}] 不是对象")
        continue
    pid = p.get("id", "?")
    for f in ("id", "name", "keychainService"):
        if not p.get(f):
            schema_errors.append(f"providers[{idx}]（{pid}）缺字段 {f}")
    api = p.get("api") or {}
    if not api.get("url"):
        schema_errors.append(f"providers[{idx}]（{pid}）api 缺字段 url")
    ptype = (p.get("parser") or {}).get("type")
    if ptype not in ("balance", "plan_usage", "status"):
        schema_errors.append(f"providers[{idx}]（{pid}）parser.type 无效: {ptype!r}")
if schema_errors:
    print("👁 | color=#e74c3c")
    print("---")
    print("providers.json 配置错误 | color=#e74c3c")
    for e in schema_errors[:8]:
        print(f"  {e} | color=#888 size=11")
    print("---")
    print("刷新 | refresh=true")
    sys.exit(0)

# Process all providers in parallel
providers_list = [p for p in config.get("providers", []) if p.get("enabled", True)]
refresh_map = {p.get("id"): p.get("refreshParam") for p in providers_list if p.get("refreshParam")}
results = [None] * len(providers_list)
if providers_list:
    with ThreadPoolExecutor(max_workers=max(1, len(providers_list))) as executor:
        futures = {executor.submit(process_provider, p): i for i, p in enumerate(providers_list)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {"id": "_err", "name": "?", "status": "error",
                                "lines": [f"处理异常: {e}"], "colors": [C_ERR],
                                "menu_bar": "", "console_url": None}

# ---------------------------------------------------------------------------
# Render SwiftBar output (merged — no second Python process)
# ---------------------------------------------------------------------------
try:
    menu_cfg = config.get("menuBar", {})
    show_cfg = menu_cfg.get("showSummary", False)
    if isinstance(show_cfg, list):
        allowed_ids = set(show_cfg)
        def want_summary(r): return r.get("id") in allowed_ids
    elif show_cfg:
        def want_summary(r): return True
    else:
        def want_summary(r): return False

    summary = " | ".join(
        r["menu_bar"] for r in results
        if r and want_summary(r) and r.get("status") in ("ok", "warn") and r.get("menu_bar")
    )
    if summary:
        print(f"👁 {summary} | color={C_HEADER}")
    else:
        print(f"👁 | color={C_HEADER}")

    print("---")
    print(f"Token Eye | color={C_HEADER}")
    print("---")

    for r in results:
        if not r: continue
        name = r["name"]
        status = r["status"]
        lines = r.get("lines", [])
        if status == "no_key":
            svc = r.get("keychainService", "")
            print(f"🔑 {name}: 未配置 Key | color={C_WARN}")
            if svc:
                print(f"  security add-generic-password -s {svc} -w your-key | font=Menlo size=11 color={C_MUTED}")
        elif status == "error":
            msg = lines[0] if lines else '请求失败'
            c = (r.get("colors") or [C_ERR])[0]
            print(f"🔴 {name}: {msg} | color={c}")
            rp = refresh_map.get(r.get("id"))
            if rp:
                print(f"  🔄 刷新 {name} Cookie | param1={rp} color={C_WARN} size=11")
        else:
            colors = r.get("colors", [])
            for i, line in enumerate(lines):
                c = colors[i] if i < len(colors) else C_DEFAULT
                print(f"{line} | color={c}")
        # Console link
        cu = r.get("console_url")
        if cu:
            print(f"  → 打开 {name} 控制台 | href={cu} color={C_MUTED} size=11")
        print("---")

    print("刷新 | refresh=true")
    print(f"上次更新: {time.strftime('%H:%M:%S')} | color={C_MUTED} size=11")

    # 版本自检：GitHub 最新 release（24h 缓存），有新版本时提示
    try:
        latest = check_latest_version()
        if latest and _ver_gt(latest, "v" + VERSION):
            print(f"⬆ 新版本 {latest} 可用 | href=https://github.com/jimmywuxin/token-eye/releases/latest color={C_HEADER} size=11")
        else:
            print(f"v{VERSION} | color={C_MUTED} size=11")
    except Exception:
        print(f"v{VERSION} | color={C_MUTED} size=11")

except Exception as e:
    # 最后兜底，绝不让菜单空白
    print("👁 | color=#e74c3c")
    print("---")
    print(f"Token Eye 渲染失败 | color=#e74c3c")
    print(f"{e} | color=#888 size=11")
    print("---")
    print("刷新 | refresh=true")

ENDOFPYTHON
