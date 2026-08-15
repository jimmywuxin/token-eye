#!/usr/bin/env python3
"""
Token Eye — SwiftBar 插件核心逻辑（由 token-eye.sh 调用）。

设计原则：
- 顶层只有常量与函数，可被 tests/ 直接 import 做单元测试；
- main() 读取环境变量（CONFIG_FILE / PROJECT_DIR / APPEARANCE / C_*），
  渲染 SwiftBar 菜单格式输出到 stdout；
- 纯函数（resolve_field / parse_provider / classify_response / alert_check ...）
  不依赖全局状态，全部可测。

用法：
  CONFIG_FILE=... PROJECT_DIR=... python3 token_eye.py          # 正常渲染
  python3 token_eye.py --validate                               # 仅校验配置
"""
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

VERSION = "0.15.0"

# 按 parser 类型的默认缓存 TTL（秒）
DEFAULT_CACHE_TTL = {"balance": 300, "plan_usage": 30, "status": 60}
ERROR_CACHE_TTL = 10  # 失败短缓存，避免连续打 API
HISTORY_LEN = 288     # 趋势窗口：最近 288 条快照（30s 采样 ≈ 2.4 小时）

# 环境变量 -> 颜色名（与 token-eye.sh 导出的 C_* 对应）
COLOR_NAMES = ["DEFAULT", "SECONDARY", "MUTED", "HEADER", "OK", "WARN", "ERR"]
ENV_FALLBACK = {
    "DEFAULT": "#ffffff",
    "SECONDARY": "#aaaaaa",
    "MUTED": "#888888",
    "HEADER": "#FFD60A",
    "OK": "#2ecc71",
    "WARN": "#f39c12",
    "ERR": "#e74c3c",
}
CONFIG_COLOR_KEYS = {
    "DEFAULT": "default",
    "SECONDARY": "secondary",
    "MUTED": "muted",
    "HEADER": "header",
    "OK": "ok",
    "WARN": "warn",
    "ERR": "err",
}
VALID_PARSER_TYPES = ("balance", "plan_usage", "status")


# ---------------------------------------------------------------------------
# 配置 / 颜色
# ---------------------------------------------------------------------------

def load_colors(config):
    """env 兜底 -> providers.json colors 覆盖。返回 (appearance, colors dict)。"""
    appearance = os.environ.get("APPEARANCE", "dark")
    colors = {k: os.environ.get("C_" + k, v) for k, v in ENV_FALLBACK.items()}
    cfg = (config.get("colors") or {}).get(appearance)
    if cfg:
        for name, key in CONFIG_COLOR_KEYS.items():
            colors[name] = cfg.get(key, colors[name])
    return appearance, colors


def schema_validate(config):
    """轻量 schema 校验，返回错误列表（空 = 通过）。"""
    errors = []
    for idx, p in enumerate(config.get("providers", [])):
        if not isinstance(p, dict):
            errors.append(f"providers[{idx}] 不是对象")
            continue
        pid = p.get("id", "?")
        for f in ("id", "name", "keychainService"):
            if not p.get(f):
                errors.append(f"providers[{idx}]（{pid}）缺字段 {f}")
        api = p.get("api") or {}
        if not api.get("url"):
            errors.append(f"providers[{idx}]（{pid}）api 缺字段 url")
        ptype = (p.get("parser") or {}).get("type")
        if ptype not in VALID_PARSER_TYPES:
            errors.append(f"providers[{idx}]（{pid}）parser.type 无效: {ptype!r}")
    return errors


# ---------------------------------------------------------------------------
# Keychain / HTTP
# ---------------------------------------------------------------------------

def get_key(service):
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def classify_response(output, returncode):
    """纯函数：把 curl 原始输出分类成 fetch_result。

    curl 以 `\\n__TE_HTTP__%{http_code}` 结尾输出状态码；无分隔符时退回
    解析最后一行（兼容旧格式）。返回 dict：{ok, status, data, error_kind, message}
    """
    marker = "__TE_HTTP__"
    if returncode != 0:
        return {"ok": False, "status": None, "data": None,
                "error_kind": "network", "message": "curl 退出非零"}
    output = output.rstrip("\n")
    if marker in output:
        body, _, code_part = output.rpartition(marker)
        status_str = code_part.strip()
    elif "\n" in output:
        # 旧格式兼容：最后一行是状态码
        status_str = output.rsplit("\n", 1)[-1]
        body = output[:output.rfind("\n")]
    else:
        status_str = output
        body = ""
    try:
        status_code = int(status_str.strip())
    except (ValueError, TypeError):
        return {"ok": False, "status": None, "data": None,
                "error_kind": "parse", "message": "无法解析 HTTP 状态"}
    if status_code >= 500:
        return {"ok": False, "status": status_code, "data": None,
                "error_kind": "server", "message": f"服务端异常 HTTP {status_code}"}
    if status_code >= 400:
        try:
            err = json.loads(body)
            msg = err.get("error", {}).get("message", body[:80]) if isinstance(err, dict) else body[:80]
        except (json.JSONDecodeError, AttributeError):
            msg = body[:80] if body.strip() else f"HTTP {status_code}"
        return {"ok": False, "status": status_code, "data": None,
                "error_kind": "client", "message": msg}
    try:
        data = json.loads(body) if body.strip() else None
    except json.JSONDecodeError as e:
        return {"ok": False, "status": status_code, "data": None,
                "error_kind": "parse", "message": f"JSON 解析失败: {e}"}
    return {"ok": True, "status": status_code, "data": data,
            "error_kind": None, "message": ""}


def fetch_api(url, method, auth_header, auth_prefix, key, extra_headers=None,
              curl_timeout=5, proc_timeout=10):
    """调用 curl 拉取 API，返回 classify_response 结果。"""
    cmd = ["curl", "-s", "--max-time", str(curl_timeout),
           "-w", "\n__TE_HTTP__%{http_code}",
           "-H", f"{auth_header}: {auth_prefix}{key}"]
    if extra_headers:
        for k, v in extra_headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
    cmd.extend(["-X", method, url])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=proc_timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": None, "data": None,
                "error_kind": "timeout", "message": "请求超时"}
    except Exception as e:
        return {"ok": False, "status": None, "data": None,
                "error_kind": "network", "message": f"网络失败: {e}"}
    return classify_response(r.stdout, r.returncode)


def send_notify(title, message):
    try:
        # 转义双引号
        safe_msg = message.replace('"', '\\"')
        safe_title = title.replace('"', '\\"')
        # 系统提示音：TOKEN_EYE_SOUND 自定义声音名，设为 0 关闭（默认 Glass）
        sound = os.environ.get("TOKEN_EYE_SOUND", "Glass")
        if sound and sound != "0":
            safe_sound = sound.replace('"', '\\"')
            script = (f'display notification "{safe_msg}" with title "{safe_title}" '
                      f'sound name "{safe_sound}"')
        else:
            script = f'display notification "{safe_msg}" with title "{safe_title}"'
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 缓存 / 历史
# ---------------------------------------------------------------------------

def cache_path(cache_dir, pid):
    return os.path.join(cache_dir, f"token-eye-cache-{pid}.json")


def load_cache(cache_dir, pid):
    try:
        with open(cache_path(cache_dir, pid)) as f:
            return json.load(f)
    except Exception:
        return None


def save_cache(cache_dir, pid, payload):
    try:
        with open(cache_path(cache_dir, pid), "w") as f:
            json.dump(payload, f)
    except Exception:
        pass


def append_history(hdir, pid, value):
    try:
        with open(os.path.join(hdir, f"history-{pid}.jsonl"), "a") as f:
            f.write(f"{int(time.time())},{value}\n")
    except Exception:
        pass


def load_history(hdir, pid, n=HISTORY_LEN):
    out = []
    try:
        with open(os.path.join(hdir, f"history-{pid}.jsonl")) as f:
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


HISTORY_RETENTION_DAYS = 30
CLEANUP_INTERVAL = 86400  # 每天最多执行一次清理


def _line_ts(line):
    try:
        return int(line.partition(",")[0])
    except (ValueError, TypeError):
        return 0


def cleanup_history(hdir, retention_days=HISTORY_RETENTION_DAYS):
    """清理超过保留期的历史行（按行时间戳），防 jsonl 无限增长。"""
    cutoff = int(time.time()) - retention_days * 86400
    try:
        names = os.listdir(hdir)
    except Exception:
        return
    for fname in names:
        if not (fname.startswith("history-") and fname.endswith(".jsonl")):
            continue
        path = os.path.join(hdir, fname)
        try:
            with open(path) as f:
                lines = f.readlines()
            keep = [ln for ln in lines if _line_ts(ln) >= cutoff]
            if len(keep) < len(lines):
                with open(path, "w") as f:
                    f.writelines(keep)
        except Exception:
            pass


def maybe_cleanup_history(hdir):
    """每天最多执行一次历史清理（last-cleanup.ts 标记）。"""
    stamp = os.path.join(hdir, "last-cleanup.ts")
    try:
        if os.path.exists(stamp):
            with open(stamp) as f:
                last = int(f.read().strip() or 0)
            if time.time() - last < CLEANUP_INTERVAL:
                return
        cleanup_history(hdir)
        _write_flag(stamp, str(int(time.time())))
    except Exception:
        pass


def start_of_day(ts=None):
    """本地时区当天 0 点的时间戳。"""
    t = time.localtime(ts if ts is not None else time.time())
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def start_of_week(ts=None):
    """本地时区本周一 0 点的时间戳。"""
    t = time.localtime(ts if ts is not None else time.time())
    monday = t.tm_mday - t.tm_wday
    return int(time.mktime((t.tm_year, t.tm_mon, monday, 0, 0, 0, 0, 0, -1)))


def start_of_month(ts=None):
    """本地时区本月 1 日 0 点的时间戳。"""
    t = time.localtime(ts if ts is not None else time.time())
    return int(time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1)))


def consumption_since(hdir, pid, cutoff_ts, epsilon=0.001):
    """[cutoff, now] 窗口内的消耗量：相邻快照下降量之和（充值抬升不干扰）。
    返回 (spend, points)；points < 2 表示窗口内数据不足。"""
    hist = [(ts, val) for ts, val in load_history(hdir, pid, n=10000) if ts >= cutoff_ts]
    if len(hist) < 2:
        return 0.0, len(hist)
    spend = 0.0
    prev = hist[0][1]
    for _, val in hist[1:]:
        if val < prev - epsilon:
            spend += prev - val
        prev = val
    return spend, len(hist)


def daily_spend(hdir, pid, epsilon=0.001):
    """今日消耗估算（当天 0 点至今）。"""
    return consumption_since(hdir, pid, start_of_day(), epsilon)


def days_left(hdir, pid, current_balance, window_hours=24, epsilon=0.001):
    """按最近 window_hours 的消耗速率外推余额可用天数；数据不足/无消耗返回 None。"""
    cutoff = int(time.time()) - window_hours * 3600
    consumed, pts = consumption_since(hdir, pid, cutoff, epsilon)
    if pts < 2 or consumed <= epsilon:
        return None
    try:
        bal = float(current_balance)
    except (ValueError, TypeError):
        return None
    if bal <= 0:
        return 0.0
    # window_hours 内消耗 consumed → 每天速率 consumed*24/window_hours → 可用天数
    return bal * window_hours / (consumed * 24)


def daily_spend_series(hdir, pid, days=7, epsilon=0.001):
    """近 days 天（含今天）每日消耗，索引 0 = 最早一天，索引 -1 = 今天。
    跨零点下降归到后一天。"""
    now = int(time.time())
    today0 = start_of_day(now)
    start = today0 - (days - 1) * 86400
    hist = [(ts, val) for ts, val in load_history(hdir, pid, n=10000) if ts >= start]
    buckets = [0.0] * days
    for (t1, v1), (t2, v2) in zip(hist, hist[1:]):
        if v2 < v1 - epsilon:
            idx = days - 1 - int((today0 - start_of_day(t2)) // 86400)
            if 0 <= idx < days:
                buckets[idx] += v1 - v2
    return buckets


def sparkline(values, width=24):
    """迷你走势图：values 均匀降采样到 width 个点（默认 24 字符宽），
    窗口内 min→max 归一化到 8 档字符。"""
    if not values:
        return ""
    if len(values) > width:
        idxs = [int(i * (len(values) - 1) / (width - 1)) for i in range(width)]
        values = [values[i] for i in idxs]
    lo, hi = min(values), max(values)
    span = hi - lo if hi > lo else 1.0
    chars = "▁▂▃▄▅▆▇█"
    return "".join(chars[min(len(chars) - 1, int((v - lo) / span * (len(chars) - 1)))] for v in values)


# ---------------------------------------------------------------------------
# 版本自检
# ---------------------------------------------------------------------------

def _ver_gt(a, b):
    pa = [int(x) for x in re.findall(r"\d+", a)]
    pb = [int(x) for x in re.findall(r"\d+", b)]
    return pa > pb


def check_latest_version(hdir):
    cache_file = os.path.join(hdir, "latest-release.json")
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


# ---------------------------------------------------------------------------
# 字段解析 / 渲染
# ---------------------------------------------------------------------------

def resolve_field(obj, path):
    if obj is None or not path:
        return None
    for part in path.split("."):
        if obj is None:
            return None
        if isinstance(obj, list):
            try:
                idx = int(part)
            except ValueError:
                return None
            try:
                obj = obj[idx]
            except IndexError:
                return None
        else:
            try:
                obj = obj[part]
            except (KeyError, TypeError):
                return None
    return obj


def format_ms(ms):
    sec = ms // 1000
    h, m = sec // 3600, (sec % 3600) // 60
    return f"{h}h{m}m" if h > 0 else f"{m}m"


DEFAULT_CURRENCY_SYMBOLS = {"USD": "$"}


def currency_symbol(display, currency):
    """货币符号：display.currencySymbols 可自定义（如 {"USD":"$","EUR":"€"}），
    未配置时默认 USD→$，其余 →¥。"""
    sym_map = display.get("currencySymbols") or {}
    return sym_map.get(currency, DEFAULT_CURRENCY_SYMBOLS.get(currency, "¥"))


def name_color(display, appearance, default_color):
    """display.nameColor 支持深浅双套：字符串（旧版兼容）或 {"dark":..., "light":...}"""
    nc = display.get("nameColor", default_color)
    if isinstance(nc, dict):
        return nc.get(appearance, nc.get("dark", default_color))
    return nc


def parse_provider(p, fetch_result, colors, appearance):
    pid, name = p["id"], p["name"]
    parser = p["parser"]
    display = p.get("display", {})
    console_url = p.get("consoleUrl")
    data = fetch_result["data"]
    ptype = parser["type"]
    NC = name_color(display, appearance, colors["DEFAULT"])

    if ptype == "balance":
        fields = parser.get("fields", {})
        balance = resolve_field(data, fields.get("balance", ""))
        currency = resolve_field(data, fields.get("currency", "CNY")) or "CNY"
        symbol = currency_symbol(display, currency)
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
            "colors": [NC, colors["OK"] if avail else colors["ERR"]],
            "console_url": console_url,
            "balance_num": balance_num,
            "currency": currency,
            "symbol": symbol,
            # 行级交互：第一行点击复制余额到剪贴板
            "line_params": [{"param1": "copy-balance", "param2": f"{symbol}{balance_str}"}, None],
        }

    elif ptype == "status":
        ok_field = parser.get("okField", "")
        ok_value = parser.get("okValue", "")
        actual = resolve_field(data, ok_field) if ok_field else data
        is_ok = (str(actual) == str(ok_value)) if ok_value else (actual is not None)
        label = display.get("label", "可用")
        color = colors["OK"] if is_ok else colors["ERR"]
        return {
            "id": pid, "name": name, "status": "ok" if is_ok else "error",
            "menu_bar": f"{label}",
            "lines": [f"{name}: {label}", "API Key 有效" if is_ok else "API Key 无效"],
            "colors": [color, colors["SECONDARY"]],
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
                try:
                    return int(resolve_field(item, fields.get(v, "")) or default)
                except (ValueError, TypeError):
                    return default

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
            color = colors["OK"]
            if pct < 10:
                color = colors["ERR"]
            elif pct < 20:
                color = colors["WARN"]
            icon = "✅" if pct >= 20 else ("⚠️" if pct >= 10 else "🔴")
            max_boost = max(interval_boost, weekly_boost)
            boost_tag = f" 🔥x{max_boost/1000:.1f}" if max_boost > 1000 else ""
            if boost_tag and boost_tag not in boost_texts:
                boost_texts.append(boost_tag)
            # 状态推导：percent 字段存在时优先按 pct 推断（与图标阈值一致）；
            # percent 缺失（旧按次数平台）时用 statusMap，total=0 视为无套餐。
            # 注意：total_count 字段在 MiniMax 新接口中已废弃、恒为 0，不能用于判断有无套餐。
            no_quota_label = parser.get("noQuotaLabel", "无套餐")

            def _state(pct_raw, status_val, total_val):
                if pct_raw is not None:
                    p = int(pct_raw)
                    if p >= 20:
                        return "可用"
                    if p >= 10:
                        return "耗尽临近"
                    return "耗尽"
                state = status_map.get(str(status_val), "未知")
                if total_val == 0:
                    return no_quota_label
                return state

            interval_state = _state(resolve_field(item, fields.get("intervalPct", "")),
                                    interval_status, _int_or_none("intervalTotal"))
            weekly_state = _state(resolve_field(item, fields.get("weeklyPct", "")),
                                  weekly_status, _int_or_none("weeklyTotal"))
            menu_parts.append(f"{icon} {label} {pct}%{boost_tag}")
            item_lines.extend([
                f"{label}: 5小时窗口 {pct}%（{interval_state}）",
                f"  周窗口 {weekly_pct}%（{weekly_state}）",
                f"  重置: {reset}",
                f"  {bar} {pct}%",
            ])
            item_colors.extend([NC, colors["SECONDARY"], colors["SECONDARY"], color])
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
                    "lines": ["无数据"], "colors": [colors["SECONDARY"]],
                    "console_url": console_url}

    else:
        return {
            "id": pid, "name": name, "status": "ok",
            "menu_bar": "raw",
            "lines": [json.dumps(data, ensure_ascii=False)[:200]],
            "colors": [colors["SECONDARY"]],
            "console_url": console_url,
        }


def render_error(pid, name, error_kind, message, console_url, colors):
    label_map = {"timeout": "请求超时", "network": "网络失败", "server": "服务端异常",
                 "client": "配置/鉴权错误", "parse": "解析失败"}
    label = label_map.get(error_kind, "请求失败")
    # 临时故障（网络/服务端）用 warn 色提醒；配置错误用 err 色
    color = colors["WARN"] if error_kind in ("timeout", "network", "server") else colors["ERR"]
    return {
        "id": pid, "name": name, "status": "error", "error_kind": error_kind,
        "lines": [f"{label}: {str(message)[:80]}"],
        "colors": [color],
        "menu_bar": "",
        "console_url": console_url,
    }


# ---------------------------------------------------------------------------
# 告警 / 自愈 / 调试日志
# ---------------------------------------------------------------------------

def _flag_path(flags_dir, pid, kind):
    return os.path.join(flags_dir, f"token-eye-{kind}-{pid}.flag")


def _write_flag(path, content=""):
    try:
        with open(path, "w") as f:
            f.write(content)
    except Exception:
        pass


def _clear_flag(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def log_debug(hdir, msg):
    """TOKEN_EYE_DEBUG=1 时追加调试日志到 ~/Library/Caches/token-eye/debug.log。"""
    if os.environ.get("TOKEN_EYE_DEBUG", "0") != "1":
        return
    try:
        with open(os.path.join(hdir, "debug.log"), "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def alert_check(pid, name, balance_val, alert_cfg, flags_dir):
    """余额告警（去重）：低于阈值且未标记过 → 返回通知文案并打标记。"""
    if not alert_cfg:
        return None
    min_bal = alert_cfg.get("minBalance")
    if min_bal is None:
        return None
    try:
        bal = float(balance_val)
    except (ValueError, TypeError):
        return None
    flag = _flag_path(flags_dir, pid, "alerted")
    if bal >= min_bal:
        _clear_flag(flag)
        return None
    if os.path.exists(flag):
        return None
    _write_flag(flag, str(bal))
    return f"{name} 余额仅 {bal:.2f}，低于阈值 {min_bal}"


def notify_recovered(pid, name, kind_label, current_str, flags_dir, was_alerted=False):
    """告警恢复通知（去重）：曾告警且未发过恢复 → 发一条「已恢复」。"""
    if not was_alerted:
        return
    recovered = _flag_path(flags_dir, pid, "recovered")
    if os.path.exists(recovered):
        return
    _write_flag(recovered, "1")
    send_notify("Token Eye 已恢复", f"{name} {kind_label}已恢复（当前 {current_str}）")


def auto_refresh_cookie(flags_dir, pid, refresh_script, fail_cooldown=300, success_cooldown=1800):
    """自动刷新 Cookie（401 自愈）。

    - 失败后 fail_cooldown（默认 5 分钟）即可重试——会话可能很快恢复（如 Edge 重新打开）
    - 成功后 30 分钟防抖，避免反复打脚本
    标记内容：`<ts> ok|fail`（旧版纯数字视为 ok）
    """
    flag = _flag_path(flags_dir, pid, "autorefresh")
    now = int(time.time())
    try:
        if os.path.exists(flag):
            with open(flag) as f:
                parts = f.read().strip().split()
            last = int(parts[0])
            kind = parts[1] if len(parts) > 1 else "ok"
            cooldown = success_cooldown if kind == "ok" else fail_cooldown
            if now - last < cooldown:
                return False, f"冷却中（{'成功' if kind == 'ok' else '失败'}后 {cooldown // 60} 分钟内已尝试过）"
    except Exception:
        pass
    try:
        r = subprocess.run(["/usr/bin/python3", refresh_script],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and "HTTP=200" in r.stdout:
            _write_flag(flag, f"{now} ok")
            return True, ""
        _write_flag(flag, f"{now} fail")
        return False, (r.stdout or r.stderr).strip()[-150:]
    except Exception as e:
        _write_flag(flag, f"{now} fail")
        return False, str(e)


# ---------------------------------------------------------------------------
# provider 处理（缓存 -> 拉取 -> 自愈 -> 渲染 -> 趋势 -> 告警）
# ---------------------------------------------------------------------------

def process_provider(p, config, colors, appearance, cache_dir, hdir, project_dir):
    pid, name = p["id"], p["name"]
    keychain, api, parser = p["keychainService"], p["api"], p["parser"]
    ptype = parser["type"]
    console_url = p.get("consoleUrl")
    refresh_param = p.get("refreshParam")
    alert_cfg = p.get("alert") or config.get("alerts", {}).get(pid)
    t0 = time.time()
    log_debug(hdir, f"[{pid}] 开始处理（parser={ptype}）")

    # Cache check
    ttl = p.get("cacheTtl", config.get("cache", {}).get(ptype, DEFAULT_CACHE_TTL.get(ptype, 30)))
    cached = load_cache(cache_dir, pid)
    now = int(time.time())
    is_err_cache = bool(cached and cached.get("data") is None and cached.get("error"))
    effective_ttl = ERROR_CACHE_TTL if is_err_cache else ttl

    if cached and (now - cached.get("ts", 0)) < effective_ttl:
        if is_err_cache:
            log_debug(hdir, f"[{pid}] 命中错误缓存（{cached.get('error')}），跳过 API")
            return render_error(pid, name, cached.get("error"),
                                cached.get("message", ""), console_url, colors)
        # 命中成功缓存，跳过 API
        log_debug(hdir, f"[{pid}] 命中成功缓存，跳过 API")
        fetch_result = {"ok": True, "status": 200, "data": cached["data"],
                        "error_kind": None, "message": ""}
    else:
        key = get_key(keychain)
        if not key:
            log_debug(hdir, f"[{pid}] Keychain 无密钥（{keychain}）")
            return {"id": pid, "name": name, "status": "no_key", "lines": [],
                    "menu_bar": "", "console_url": console_url,
                    "keychainService": keychain}
        fetch_result = fetch_api(
            api["url"], api.get("method", "GET"),
            api.get("authHeader", "Authorization"),
            api.get("authPrefix", "Bearer "), key,
            api.get("headers")
        )
        log_debug(hdir, f"[{pid}] 请求完成: ok={fetch_result['ok']} "
                        f"status={fetch_result.get('status')} "
                        f"kind={fetch_result.get('error_kind')} "
                        f"耗时={time.time() - t0:.2f}s")

        # 自动自愈：client 鉴权错误 + 配置了 refreshParam → 刷新 Cookie 后重试一次
        self_heal_err = None
        if (not fetch_result["ok"] and fetch_result.get("error_kind") == "client"
                and refresh_param):
            script = os.path.join(project_dir, "scripts", refresh_param + ".py")
            if os.path.exists(script):
                refreshed, err = auto_refresh_cookie(hdir, pid, script)
                log_debug(hdir, f"[{pid}] 自愈刷新: ok={refreshed} {err}")
                if refreshed:
                    key2 = get_key(keychain)
                    if key2:
                        fetch_result = fetch_api(
                            api["url"], api.get("method", "GET"),
                            api.get("authHeader", "Authorization"),
                            api.get("authPrefix", "Bearer "), key2,
                            api.get("headers")
                        )
                        log_debug(hdir, f"[{pid}] 自愈重试: ok={fetch_result['ok']} "
                                        f"status={fetch_result.get('status')}")
                elif err:
                    self_heal_err = err

        if fetch_result["ok"]:
            save_cache(cache_dir, pid, {"ts": now, "data": fetch_result["data"]})
        else:
            save_cache(cache_dir, pid, {"ts": now, "data": None,
                                        "error": fetch_result["error_kind"],
                                        "message": fetch_result["message"]})

    if not fetch_result["ok"]:
        err_render = render_error(pid, name, fetch_result["error_kind"],
                                  fetch_result["message"], console_url, colors)
        if self_heal_err:
            # 自愈失败原因展示在错误菜单里，用户知道为什么需要手动
            err_render.setdefault("lines", []).append(f"  ↻ 自动刷新未生效: {self_heal_err[:60]}")
            err_render.setdefault("colors", []).append(colors["MUTED"])
        return err_render

    render = parse_provider(p, fetch_result, colors, appearance)

    # Balance history（趋势 + 当日变化 + 消耗统计与预测）
    if ptype == "balance" and render.get("balance_num") is not None:
        append_history(hdir, pid, render["balance_num"])
        hist = load_history(hdir, pid, HISTORY_LEN)
        if len(hist) >= 2:
            first_val, last_val = hist[0][1], hist[-1][1]
            diff = last_val - first_val
            symbol = render.get("symbol", "¥")
            change = f"{'+' if diff > 0 else ''}{diff:.2f}"
            trend = sparkline([v for _, v in hist])
            render.setdefault("lines", []).append(
                f"  趋势: {trend}  {symbol}{first_val:.2f}→{last_val:.2f} ({change})")
            render.setdefault("colors", []).append(colors["SECONDARY"])
            render.setdefault("line_params", []).append(None)
        symbol = render.get("symbol", "¥")
        # 今日消耗估算：相邻余额快照下降量之和（充值会抬升余额，下降量不受干扰）
        spend, pts = daily_spend(hdir, pid)
        render["_daily_spend"] = spend
        if pts >= 2 and spend > 0:
            render.setdefault("lines", []).append(f"  今日消耗: {symbol}{spend:.2f}")
            render.setdefault("colors", []).append(colors["SECONDARY"])
            # 行级交互：点今日消耗行 → 打开控制台（充值/账单）
            render.setdefault("line_params", []).append(
                {"href": console_url} if console_url else None)
        # 预计可用天数（按最近 24h 消耗速率外推）
        days = days_left(hdir, pid, render["balance_num"])
        render["_days_left"] = days
        if days is not None:
            text = f"  预计可用: ~{days:.1f} 天" if days < 30 else f"  预计可用: 充足（>{days:.0f} 天）"
            render.setdefault("lines", []).append(text)
            render.setdefault("colors", []).append(colors["SECONDARY"])
            render.setdefault("line_params", []).append(None)
        # 本周 / 本月消耗
        wk, wp = consumption_since(hdir, pid, start_of_week())
        mo, mp = consumption_since(hdir, pid, start_of_month())
        if (wp >= 2 and wk > 0) or (mp >= 2 and mo > 0):
            render.setdefault("lines", []).append(
                f"  本周 {symbol}{wk:.2f} · 本月 {symbol}{mo:.2f}")
            render.setdefault("colors", []).append(colors["SECONDARY"])
            render.setdefault("line_params", []).append(None)
        # 近 7 天每日消耗柱状图（右 = 今天）
        series = daily_spend_series(hdir, pid, 7)
        if any(v > 0 for v in series):
            bars = sparkline(series) if max(series) > 0 else "·" * 7
            render.setdefault("lines", []).append(f"  近7天: {bars}")
            render.setdefault("colors", []).append(colors["SECONDARY"])
            render.setdefault("line_params", []).append(None)

    # plan_usage 趋势（剩余百分比历史）
    elif ptype == "plan_usage" and render.get("min_pct") is not None:
        append_history(hdir, pid, render["min_pct"])
        hist = load_history(hdir, pid, HISTORY_LEN)
        if len(hist) >= 2:
            first_val, last_val = hist[0][1], hist[-1][1]
            diff = last_val - first_val
            change = f"{'+' if diff > 0 else ''}{diff:.0f}"
            trend = sparkline([v for _, v in hist])
            render.setdefault("lines", []).append(
                f"  趋势: {trend}  {first_val:.0f}%→{last_val:.0f}% ({change}%)")
            render.setdefault("colors", []).append(colors["SECONDARY"])
            render.setdefault("line_params", []).append(None)

    # Alert check (balance 余额 / plan_usage 用量百分比) + 恢复通知
    if os.environ.get("TOKEN_EYE_NOTIFY", "1") != "0":
        if ptype == "balance" and render.get("balance_num") is not None:
            alerted = _flag_path(hdir, pid, "alerted")
            was_alerted = os.path.exists(alerted)
            notify_msg = alert_check(pid, name, render["balance_num"], alert_cfg, hdir)
            if notify_msg:
                _clear_flag(_flag_path(hdir, pid, "recovered"))
                send_notify("Token Eye 告警", notify_msg)
                log_debug(hdir, f"[{pid}] 触发告警: {notify_msg}")
            elif (was_alerted and alert_cfg and alert_cfg.get("minBalance") is not None
                    and render["balance_num"] >= float(alert_cfg["minBalance"])):
                symbol = render.get("symbol", "¥")
                notify_recovered(pid, name, "余额",
                                 f"{symbol}{render['balance_num']:.2f}", hdir,
                                 was_alerted=was_alerted)
                log_debug(hdir, f"[{pid}] 余额已恢复，发送恢复通知")
            # 当日消耗上限告警（alert.dailySpendMax）
            max_spend = (alert_cfg or {}).get("dailySpendMax")
            if max_spend is not None and render.get("_daily_spend", 0) > max_spend:
                spend_flag = _flag_path(hdir, pid, "spendalerted")
                if not os.path.exists(spend_flag):
                    _write_flag(spend_flag, "1")
                    symbol = render.get("symbol", "¥")
                    send_notify("Token Eye 告警",
                                f"{name} 今日消耗 {symbol}{render['_daily_spend']:.2f}，超过上限 {max_spend}")
                    log_debug(hdir, f"[{pid}] 当日消耗超上限告警（{render['_daily_spend']:.2f} > {max_spend}）")
            else:
                _clear_flag(_flag_path(hdir, pid, "spendalerted"))
            # 余额耗尽天数预警（alert.daysLeft）
            min_days = (alert_cfg or {}).get("daysLeft")
            dl = render.get("_days_left")
            if min_days is not None and dl is not None and dl < min_days:
                days_flag = _flag_path(hdir, pid, "daysalerted")
                if not os.path.exists(days_flag):
                    _write_flag(days_flag, "1")
                    send_notify("Token Eye 告警",
                                f"{name} 预计 {dl:.1f} 天后余额耗尽（阈值 {min_days} 天）")
                    log_debug(hdir, f"[{pid}] 耗尽天数预警（{dl:.1f} < {min_days}）")
            else:
                _clear_flag(_flag_path(hdir, pid, "daysalerted"))
        elif ptype == "plan_usage" and render.get("min_pct") is not None and alert_cfg:
            min_pct = alert_cfg.get("minPct")
            if min_pct is not None:
                alerted = _flag_path(hdir, pid, "alerted")
                was_alerted = os.path.exists(alerted)
                if render["min_pct"] < int(min_pct):
                    if not was_alerted:
                        _write_flag(alerted, str(render["min_pct"]))
                        send_notify("Token Eye 告警",
                                    f"{name} 用量剩余仅 {render['min_pct']}%，低于阈值 {min_pct}%")
                        log_debug(hdir, f"[{pid}] 触发用量告警（{render['min_pct']}% < {min_pct}%）")
                    _clear_flag(_flag_path(hdir, pid, "recovered"))
                else:
                    _clear_flag(alerted)
                    if was_alerted:
                        notify_recovered(pid, name, "用量",
                                         f"剩余 {render['min_pct']}%", hdir,
                                         was_alerted=was_alerted)

    log_debug(hdir, f"[{pid}] 完成，总耗时 {time.time() - t0:.2f}s")
    return render


# ---------------------------------------------------------------------------
# 渲染 SwiftBar 输出
# ---------------------------------------------------------------------------

def render(results, config, colors, refresh_map, hdir):
    try:
        menu_cfg = config.get("menuBar", {})
        show_cfg = menu_cfg.get("showSummary", False)
        if isinstance(show_cfg, list):
            allowed_ids = set(show_cfg)

            def want_summary(r):
                return r.get("id") in allowed_ids
        elif show_cfg:

            def want_summary(r):
                return True
        else:

            def want_summary(r):
                return False

        summary = " | ".join(
            r["menu_bar"] for r in results
            if r and want_summary(r) and r.get("status") in ("ok", "warn") and r.get("menu_bar")
        )
        # 菜单栏标题按最差状态整体着色：任一错误 → 红；任一告警/缺 Key → 橙；否则标题色
        worst = max((3 if r.get("status") == "error"
                     else 2 if r.get("status") in ("warn", "no_key") else 0
                     for r in results if r), default=0)
        title_color = colors["ERR"] if worst == 3 else (colors["WARN"] if worst >= 2 else colors["HEADER"])
        if summary:
            print(f"👁 {summary} | color={title_color}")
        else:
            print(f"👁 | color={title_color}")

        print("---")
        print(f"Token Eye | color={colors['HEADER']}")
        print("---")

        for r in results:
            if not r:
                continue
            name = r["name"]
            status = r["status"]
            lines = r.get("lines", [])
            if status == "no_key":
                svc = r.get("keychainService", "")
                print(f"🔑 {name}: 未配置 Key | color={colors['WARN']}")
                if svc:
                    print(f"  security add-generic-password -s {svc} -w your-key | font=Menlo size=11 color={colors['MUTED']}")
            elif status == "error":
                msg = lines[0] if lines else '请求失败'
                c = (r.get("colors") or [colors["ERR"]])[0]
                print(f"🔴 {name}: {msg} | color={c}")
                rp = refresh_map.get(r.get("id"))
                if rp:
                    print(f"  🔄 刷新 {name} Cookie | param1={rp} color={colors['WARN']} size=11")
            else:
                rcolors = r.get("colors", [])
                line_params = r.get("line_params") or []
                for i, line in enumerate(lines):
                    c = rcolors[i] if i < len(rcolors) else colors["DEFAULT"]
                    extra = ""
                    if i < len(line_params) and line_params[i]:
                        extra = " " + " ".join(f"{k}={v}" for k, v in line_params[i].items())
                    print(f"{line} | color={c}{extra}")
            # Console link
            cu = r.get("console_url")
            if cu:
                print(f"  → 打开 {name} 控制台 | href={cu} color={colors['MUTED']} size=11")
            print("---")

        print("刷新 | refresh=true")
        print(f"上次更新: {time.strftime('%H:%M:%S')} | color={colors['MUTED']} size=11")

        # 版本自检：GitHub 最新 release（24h 缓存），有新版本时提示 + 一键升级
        try:
            latest = check_latest_version(hdir)
            if latest and _ver_gt(latest, "v" + VERSION):
                print(f"⬆ 新版本 {latest} 可用 | href=https://github.com/jimmywuxin/token-eye/releases/latest color={colors['HEADER']} size=11")
                print(f"  一键升级到 {latest} | param1=upgrade param2={latest} refresh=true color={colors['OK']} size=11")
            else:
                print(f"v{VERSION} | color={colors['MUTED']} size=11")
        except Exception:
            print(f"v{VERSION} | color={colors['MUTED']} size=11")
        print(f"🔧 自检 | param1=self-check refresh=true color={colors['MUTED']} size=11")

    except Exception as e:
        # 最后兜底，绝不让菜单空白
        print("👁 | color=#e74c3c")
        print("---")
        print("Token Eye 渲染失败 | color=#e74c3c")
        print(f"{e} | color=#888 size=11")
        print("---")
        print("刷新 | refresh=true")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def probe_network(url="https://api.github.com", timeout=4):
    """快速网络连通性探测（200 视为通）。"""
    try:
        r = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "--max-time", str(timeout),
             "-w", "%{http_code}", url],
            capture_output=True, text=True, timeout=timeout + 2)
        return r.stdout.strip() == "200"
    except Exception:
        return False


def check_keys(config):
    """检查各 provider 的 Keychain 密钥是否存在。返回 [(service, ok)]。"""
    out = []
    for p in config.get("providers", []):
        if not p.get("enabled", True):
            continue
        svc = p.get("keychainService", "")
        if svc:
            out.append((svc, bool(get_key(svc))))
    return out


def installed_version(plugin_dir=None):
    """读取已安装插件（默认 ~/SwiftBar/token-eye.sh）的 bitbar.version。"""
    base = plugin_dir or os.path.expanduser("~/SwiftBar")
    path = os.path.join(base, "token-eye.sh")
    try:
        with open(path) as f:
            for line in f:
                m = re.search(r"bitbar\.version>v([\d.]+)", line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


def self_check():
    """--self-check：Keychain Key / 网络 / 版本一致性，输出 SwiftBar 菜单。"""
    config_path = os.environ.get("CONFIG_FILE") or "providers.json"
    fail = 0
    print("🔧 Token Eye 自检 | color=#FFD60A")
    print("---")
    try:
        with open(config_path) as f:
            config = json.load(f)
    except Exception as e:
        print(f"❌ 配置读取失败: {config_path}（{e}） | color=#e74c3c")
        print("---")
        print("关闭 | refresh=true")
        return 1
    # Keychain
    keys = check_keys(config)
    for svc, ok in keys:
        if ok:
            print(f"✅ Keychain {svc} 存在 | color=#2ecc71")
        else:
            fail = 1
            print(f"❌ Keychain {svc} 缺失 | color=#e74c3c")
            print(f"   security add-generic-password -s {svc} -w your-key | font=Menlo size=11 color=#888")
    # 网络
    if probe_network():
        print("✅ 网络连通 (api.github.com) | color=#2ecc71")
    else:
        fail = 1
        print("❌ 网络不通 (api.github.com) | color=#e74c3c")
    # 版本一致性
    installed = installed_version()
    if installed is None:
        fail = 1
        print(f"❌ 未找到已安装插件 (~/SwiftBar/token-eye.sh) | color=#e74c3c")
    elif installed == VERSION:
        print(f"✅ 版本一致 v{installed} | color=#2ecc71")
    else:
        fail = 1
        print(f"⚠️ 版本不一致：项目 v{VERSION} vs 已安装 v{installed} | color=#e67e22")
        print("   执行 make install 同步 | color=#888 size=11")
    print("---")
    print("关闭 | refresh=true")
    return 0 if fail == 0 else 1


def validate_mode():
    """--validate：只校验配置（供 Makefile / CI / 手动使用），不渲染菜单。"""
    config_path = os.environ.get("CONFIG_FILE") or "providers.json"
    try:
        with open(config_path) as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ {config_path} JSON 解析失败: {e}")
        return 1
    except OSError as e:
        print(f"❌ 无法读取 {config_path}: {e}")
        return 1
    errors = schema_validate(config)
    if errors:
        print(f"❌ {config_path} 配置错误（{len(errors)} 处）:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"✅ {config_path} 校验通过（{len(config.get('providers', []))} 个 provider）")
    return 0


def run(args):
    config_path = os.environ["CONFIG_FILE"]
    project_dir = os.environ.get("PROJECT_DIR", "")
    cache_dir = "/tmp"
    hdir = os.path.join(os.path.expanduser("~/Library/Caches"), "token-eye")
    try:
        os.makedirs(hdir, exist_ok=True)
    except Exception:
        pass
    # 历史自动清理（每天一次，保留 30 天）
    maybe_cleanup_history(hdir)

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
        return 0
    except FileNotFoundError:
        print("👁 | color=#e74c3c")
        print("---")
        print(f"配置文件不存在: {config_path} | color=#e74c3c")
        print("---")
        print("刷新 | refresh=true")
        return 0

    appearance, colors = load_colors(config)

    # Schema 校验（与 --validate 共用同一逻辑）
    schema_errors = schema_validate(config)
    if schema_errors:
        print("👁 | color=#e74c3c")
        print("---")
        print("providers.json 配置错误 | color=#e74c3c")
        for e in schema_errors[:8]:
            print(f"  {e} | color=#888 size=11")
        print("---")
        print("刷新 | refresh=true")
        return 0

    # Process all providers in parallel
    providers_list = [p for p in config.get("providers", []) if p.get("enabled", True)]
    refresh_map = {p.get("id"): p.get("refreshParam")
                   for p in providers_list if p.get("refreshParam")}
    results = [None] * len(providers_list)
    if providers_list:
        with ThreadPoolExecutor(max_workers=max(1, len(providers_list))) as executor:
            futures = {
                executor.submit(process_provider, p, config, colors, appearance,
                                cache_dir, hdir, project_dir): i
                for i, p in enumerate(providers_list)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    results[idx] = {"id": "_err", "name": "?", "status": "error",
                                    "lines": [f"处理异常: {e}"], "colors": [colors["ERR"]],
                                    "menu_bar": "", "console_url": None}

    render(results, config, colors, refresh_map, hdir)
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--validate" in args:
        return validate_mode()
    if "--self-check" in args or (args and args[0] == "self-check"):
        return self_check()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
