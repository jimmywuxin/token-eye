#!/usr/bin/env python3
"""
Token Eye — Linux (UKUI/麒麟) AppIndicator 常驻托盘

把 macOS SwiftBar 版 token-eye 移植到 UKUI 3.25 (Wayland) 的系统托盘：
- 复用上游 swiftbar/token_eye.py 的全部核心逻辑（fetch/缓存/解析/告警/历史），零改动
- 仅 patch 平台耦合点：get_key -> gnome-keyring(secretstorage)、send_notify -> notify-send、
  _open_login_page -> xdg-open
- 每 REFRESH_SECONDS 秒在后台线程刷新一次，GLib.idle_add 回主线程重建菜单

用法：
  python3 token-eye-tray.py            # 常驻托盘（默认）
  python3 token-eye-tray.py --once     # 拉取一次并打印结构化结果（排障用）
  python3 token-eye-tray.py --check    # 自检：key/网络/配置
"""
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# 路径约定
# ---------------------------------------------------------------------------
LINUX_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(LINUX_DIR)          # ~/dev/token-eye（上游镜像）
SWIFTBAR_DIR = os.path.join(PROJECT_DIR, "swiftbar")
# 配置直接读上游 providers.json（上游加平台/调阈值自动同步，零维护）
CONFIG_FILE = os.path.join(PROJECT_DIR, "providers.json")
# project_dir 传 LINUX_DIR：让 process_provider 里 refresh 脚本定位到 linux/scripts/
RUNTIME_DIR = LINUX_DIR
ICON_DIR = os.path.join(LINUX_DIR, "icons")
CACHE_ROOT = os.path.expanduser("~/.cache/token-eye")
REFRESH_SECONDS = int(os.environ.get("TOKEN_EYE_REFRESH", "30"))
SHOW_LABEL = os.environ.get("TOKEN_EYE_SHOW_LABEL", "0") == "1"
APP_ID = "token-eye"

sys.path.insert(0, SWIFTBAR_DIR)
import token_eye  # 上游核心（只读 import）

# ---------------------------------------------------------------------------
# Linux 平台后端（patch 上游模块级函数）
# ---------------------------------------------------------------------------

def linux_get_key(service):
    """gnome-keyring 读密钥：secretstorage 按 attribute service=<name> 查找。"""
    try:
        import secretstorage
        bus = secretstorage.dbus_init()
        coll = secretstorage.get_default_collection(bus)
        if coll is None or coll.is_locked():
            return ""
        for item in coll.search_items({"service": service}):
            secret = item.get_secret()
            if secret:
                return secret.decode("utf-8", "replace")
    except Exception:
        pass
    return ""


def linux_send_notify(title, message, sound=None):
    """notify-send 发通知（UKUI 走 D-Bus 通知）。"""
    try:
        cmd = ["notify-send", "-a", APP_ID, "-i",
               os.path.join(ICON_DIR, "token-eye-ok_22.png"), title, message]
        subprocess.run(cmd, timeout=5, capture_output=True)
    except Exception:
        pass


def linux_open_login_page(flags_dir, pid, login_url, cooldown=1800):
    """浏览器会话失效时 xdg-open 登录页（保持上游限频语义）。"""
    return token_eye._open_login_page(flags_dir, pid, login_url, cooldown)


# 注入
token_eye.get_key = linux_get_key
token_eye.send_notify = linux_send_notify

# _open_login_page 内部调用 "open" 命令 —— 换成 xdg-open 的等价实现
_orig_open_login = token_eye._open_login_page

def _linux_open_login(flags_dir, pid, login_url, cooldown=1800):
    if not login_url:
        return False
    flag = os.path.join(flags_dir, f"token-eye-loginopened-{pid}.flag")
    now = int(time.time())
    try:
        if os.path.exists(flag):
            with open(flag) as f:
                last = int(f.read().strip() or 0)
            if now - last < cooldown:
                return False
    except Exception:
        pass
    try:
        with open(flag, "w") as f:
            f.write(str(now))
    except Exception:
        pass
    try:
        subprocess.Popen(["xdg-open", login_url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    token_eye.send_notify("Token Eye: 登录已过期",
                          f"{pid} 会话失效，已在浏览器打开登录页，登录后自动续期")
    return True

token_eye._open_login_page = _linux_open_login

# 手机热点 curl 超时：原版 curl_timeout=5/proc_timeout=10，放宽到 12/20
_orig_fetch = token_eye.fetch_api

def _fetch_api_relaxed(url, method, auth_header, auth_prefix, key, extra_headers=None,
                        curl_timeout=20, proc_timeout=35):
    return _orig_fetch(url, method, auth_header, auth_prefix, key, extra_headers,
                       curl_timeout=curl_timeout, proc_timeout=proc_timeout)

token_eye.fetch_api = _fetch_api_relaxed


# ---------------------------------------------------------------------------
# 数据收集（复用上游 process_provider / 并行逻辑）
# ---------------------------------------------------------------------------

def collect(config_path, project_dir):
    """与上游 run() 相同的并行收集，返回 (results, config, colors, appearance)。"""
    os.makedirs(CACHE_ROOT, exist_ok=True)
    with open(config_path) as f:
        config = json.load(f)
    appearance, colors = token_eye.load_colors(config)
    providers_list = [p for p in config.get("providers", []) if p.get("enabled", True)]
    results = [None] * len(providers_list)
    if providers_list:
        with ThreadPoolExecutor(max_workers=max(1, len(providers_list))) as executor:
            futures = {
                executor.submit(token_eye.process_provider, p, config, colors,
                                appearance, CACHE_ROOT, CACHE_ROOT, project_dir): i
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
    return results, config, colors, appearance


def worst_status(results):
    """最差状态：error=3 / warn|no_key=2 / ok=0。"""
    return max((3 if r.get("status") == "error"
                else 2 if r.get("status") in ("warn", "no_key") else 0
                for r in results if r), default=0)


def summary_text(results):
    """图标旁可显示的汇总（仅 SHOW_LABEL 时用）。"""
    parts = [r["menu_bar"] for r in results
             if r and r.get("status") in ("ok", "warn") and r.get("menu_bar")]
    return " 👁 " + " | ".join(parts) if parts else "👁"


# ---------------------------------------------------------------------------
# GTK / AppIndicator 托盘
# ---------------------------------------------------------------------------

def build_ui():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import Gtk, GLib, Gdk
    return Gtk, GLib, Gdk


Gtk = GLib = Gdk = None
_ui_lock = threading.Lock()


def _init_gtk():
    global Gtk, GLib, Gdk
    Gtk, GLib, Gdk = build_ui()
    if not Gtk.init_check(None):
        print("Gtk 初始化失败：无显示环境？", file=sys.stderr)
        sys.exit(1)


# 本机无字体字形的 emoji（fc-list 逐一验证 0 覆盖）：菜单渲染前直接删除，
# 连同其后的空格，显示为纯文字。上游数据行（🔴 错误 / 🔑 无 key / 🔥 boost）
# 同样生效，不改上游一字。
BAD_GLYPHS = "\U0001F504\U0001F534\U0001F527\U0001F511\U0001F525\U0001F7E0\U0001F7E1"  # 🔄🔴🔧🔑🔥🟠🟡


def fix_glyphs(text):
    for ch in BAD_GLYPHS:
        text = text.replace(ch + " ", "").replace(ch, "")
    return text


def menu_add_label(menu, text, color=None, bold=False, size=None,
                   on_activate=None, tooltip=None):
    """菜单信息行 / 动作行。信息行保持 enabled 以保留彩色 markup；
    动作行连接 activate。"""
    from gi.repository import Pango
    text = fix_glyphs(text)
    esc = GLib.markup_escape_text(text)
    style = []
    if color:
        style.append(f'color="{color}"')
    if bold:
        style.append('weight="bold"')
    if size:
        style.append(f'size="{size}"')
    markup = f"<span {' '.join(style)}>{esc}</span>" if style else esc
    lbl = Gtk.Label(label=markup)
    lbl.set_use_markup(True)
    lbl.set_xalign(0.0)
    item = Gtk.MenuItem()
    item.add(lbl)
    if on_activate:
        item.connect("activate", lambda *_: on_activate())
    if tooltip:
        item.set_tooltip_text(tooltip)
    item.show_all()
    menu.append(item)
    return item


def menu_add_sep(menu):
    sep = Gtk.SeparatorMenuItem()
    sep.show()
    menu.append(sep)


def rebuild_menu(results, config, colors, appearance):
    """把上游结构化 results 渲染成 AppIndicator 菜单。"""
    from gi.repository import Gtk
    menu = Gtk.Menu()

    # 标题行
    menu_add_label(menu, "👁 Token Eye", color=colors["HEADER"], bold=True)
    menu_add_sep(menu)

    worst = worst_status(results)
    for r in results:
        if not r:
            continue
        name = r["name"]
        status = r["status"]
        lines = r.get("lines", [])
        cu = r.get("console_url")

        if status == "no_key":
            menu_add_label(menu, f"🔑 {name}: 未配置 Key", color=colors["WARN"])
            svc = r.get("keychainService", "")
            if svc:
                menu_add_label(menu, f"  运行 setup-keys.py 添加 {svc}",
                               color=colors["MUTED"], size="small")
        elif status == "error":
            msg = lines[0] if lines else "请求失败"
            c = (r.get("colors") or [colors["ERR"]])[0]
            menu_add_label(menu, f"🔴 {name}: {msg}", color=c)
        else:
            rcolors = r.get("colors", [])
            line_params = r.get("line_params") or []
            for i, line in enumerate(lines):
                c = rcolors[i] if i < len(rcolors) else colors["DEFAULT"]
                lp = line_params[i] if i < len(line_params) else None
                action = None
                tip = None
                if lp and lp.get("param1") == "copy-balance":
                    payload = lp.get("param2", "")
                    action = lambda p=payload: copy_to_clipboard(p)
                    tip = "点击复制余额"
                elif lp and lp.get("href"):
                    url = lp["href"]
                    action = lambda u=url: open_url(u)
                    tip = "打开控制台"
                menu_add_label(menu, line, color=c, on_activate=action, tooltip=tip)
        if cu:
            menu_add_label(menu, f"  → 打开 {name} 控制台", color=colors["MUTED"],
                           size="small", on_activate=lambda u=cu: open_url(u))
        menu_add_sep(menu)

    # 手动刷新
    menu_add_label(menu, "🔄 立即刷新", color=colors["OK"],
                   on_activate=request_refresh)
    menu_add_label(menu, f"上次更新: {time.strftime('%H:%M:%S')}",
                   color=colors["MUTED"], size="small")
    try:
        latest = token_eye.check_latest_version(CACHE_ROOT)
        if latest and token_eye._ver_gt(latest, "v" + token_eye.VERSION):
            menu_add_label(menu, f"⬆ 新版本 {latest} 可用", color=colors["HEADER"],
                           size="small", on_activate=lambda: open_url(
                               "https://github.com/jimmywuxin/token-eye/releases/latest"))
    except Exception:
        pass
    menu_add_label(menu, f"v{token_eye.VERSION} (linux)", color=colors["MUTED"],
                   size="small")
    menu_add_sep(menu)
    menu_add_label(menu, "退出", on_activate=lambda: Gtk.main_quit())

    menu.show_all()
    return menu


def icon_for_worst(worst):
    return {0: "token-eye-ok", 1: "token-eye-ok",
            2: "token-eye-warn", 3: "token-eye-err"}.get(worst, "token-eye-ok")


def refresh_once():
    """后台线程执行：拉取数据，回主线程重建菜单。"""
    def _work():
        try:
            results, config, colors, appearance = collect(CONFIG_FILE, RUNTIME_DIR)
            GLib.idle_add(lambda: _apply(results, config, colors))
        except Exception as e:
            GLib.idle_add(lambda: _apply_error(str(e)))

    def _apply(results, config, colors):
        global _indicator, _menu
        if _indicator is None:
            return False
        worst = worst_status(results)
        _indicator.set_icon(icon_for_worst(worst))
        if SHOW_LABEL:
            _indicator.set_label(summary_text(results), "👁")
        if _menu is not None:
            _menu.destroy()
        _menu = rebuild_menu(results, config, colors, None)
        _indicator.set_menu(_menu)
        return False

    def _apply_error(err):
        global _indicator, _menu
        if _indicator is None:
            return False
        _indicator.set_icon("token-eye-err")
        if _menu is not None:
            _menu.destroy()
        m = Gtk.Menu()
        menu_add_label(m, "Token Eye 渲染失败", color="#e74c3c", bold=True)
        menu_add_label(m, str(err), color="#888888", size="small")
        menu_add_sep(m)
        menu_add_label(m, "🔄 重试", on_activate=request_refresh)
        m.show_all()
        _menu = m
        _indicator.set_menu(m)
        return False

    t = threading.Thread(target=_work, daemon=True)
    t.start()


def request_refresh():
    refresh_once()
    return True  # 供 GLib timeout 复用


def copy_to_clipboard(text):
    """剪贴板：优先 wl-copy(Wayland)，回退 xclip。"""
    try:
        if os.environ.get("WAYLAND_DISPLAY"):
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            p.communicate(text.encode())
            if p.returncode == 0:
                return
    except Exception:
        pass
    try:
        subprocess.Popen(["xclip", "-selection", "clipboard"],
                         stdin=subprocess.PIPE).communicate(text.encode())
    except Exception:
        pass


def open_url(url):
    try:
        subprocess.Popen(["xdg-open", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


_indicator = None
_menu = None


def main_tray():
    _init_gtk()
    global _indicator, _menu
    from gi.repository import Gtk, GLib, AppIndicator3 as AppIndicator

    _indicator = AppIndicator.Indicator.new(
        APP_ID, "token-eye-ok", AppIndicator.IndicatorCategory.SYSTEM_SERVICES)
    _indicator.set_icon_theme_path(ICON_DIR)
    _indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
    if SHOW_LABEL:
        _indicator.set_label("👁", "👁")

    # 空菜单占位，避免无菜单
    _menu = Gtk.Menu()
    menu_add_label(_menu, "Token Eye 启动中…", color="#888888")
    _menu.show_all()
    _indicator.set_menu(_menu)

    refresh_once()
    GLib.timeout_add_seconds(REFRESH_SECONDS, request_refresh)
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    return 0


def main_once():
    """--once：拉取一次并打印结构化结果（排障）。"""
    results, config, colors, appearance = collect(CONFIG_FILE, RUNTIME_DIR)
    worst = worst_status(results)
    print(f"最差状态: {worst} → 图标 {icon_for_worst(worst)}")
    print(f"汇总: {summary_text(results)}")
    print("-" * 60)
    for r in results:
        if not r:
            continue
        print(f"[{r['id']}] {r['name']}  status={r['status']}  menu_bar={r.get('menu_bar', '')}")
        for ln in r.get("lines", []):
            print(f"    {ln}")
        if r.get("console_url"):
            print(f"    → {r['console_url']}")
    return 0


def main_check():
    """--check：自检 key / 配置 / 网络。"""
    cfg_ok = True
    try:
        with open(CONFIG_FILE) as f:
            config = json.load(f)
        errs = token_eye.schema_validate(config)
        if errs:
            cfg_ok = False
            for e in errs:
                print(f"❌ 配置: {e}")
        else:
            print(f"✅ 配置校验通过（{len([p for p in config['providers'] if p.get('enabled', True)])} 个 provider）")
    except Exception as e:
        cfg_ok = False
        print(f"❌ 配置读取失败: {e}")
    for p in config.get("providers", []):
        svc = p.get("keychainService", "")
        key = linux_get_key(svc) if svc else ""
        print(f"{'✅' if key else '❌'} key {svc}: {'存在' if key else '缺失（运行 setup-keys.py 添加）'}")
    net = token_eye.probe_network()
    print(f"{'✅' if net else '⚠️'} 网络探测 api.github.com: {'通' if net else '不通（不影响余额 API）'}")
    return 0 if cfg_ok else 1


if __name__ == "__main__":
    if "--once" in sys.argv:
        sys.exit(main_once())
    if "--check" in sys.argv:
        sys.exit(main_check())
    sys.exit(main_tray())
