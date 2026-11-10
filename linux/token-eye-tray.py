#!/usr/bin/env python3
"""
Token Eye — Linux (UKUI/麒麟) AppIndicator 常驻托盘

把 macOS SwiftBar 版 token-eye 移植到 UKUI 3.25 (Wayland) 的系统托盘：
- 复用上游 swiftbar/token_eye.py 的全部核心逻辑（fetch/缓存/解析/告警/历史），零改动
- 仅 patch 平台耦合点：get_key -> gnome-keyring(secretstorage)、send_notify -> notify-send、
  _open_login_page -> 优先 Chromium 打开（兜底 xdg-open）
- 每 REFRESH_SECONDS 秒在后台线程刷新一次，GLib.idle_add 回主线程重建菜单

用法：
  python3 token-eye-tray.py            # 常驻托盘（默认）
  python3 token-eye-tray.py --once     # 拉取一次并打印结构化结果（排障用）
  python3 token-eye-tray.py --check    # 自检：key/网络/配置
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout

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

# 让同级 helper 在「直接运行」和「被测试以合成模块名加载」两种情况下都能导入
if LINUX_DIR not in sys.path:
    sys.path.insert(0, LINUX_DIR)
import keyring_common  # 解锁语义统一（P0-3）

# ---------------------------------------------------------------------------
# Linux 平台后端（patch 上游模块级函数）
# ---------------------------------------------------------------------------

# 版本自检结果（后台线程写、经 GLib.idle_add 回主线程；rebuild_menu 只读）
_version_info = {"latest": ""}


def _log_debug(msg):
    """调试留痕：复用上游 log_debug（TOKEN_EYE_DEBUG=1 时写 ~/.cache/token-eye/debug.log）。"""
    try:
        token_eye.log_debug(CACHE_ROOT, msg)
    except Exception:
        pass


def _import_appindicator():
    """返回 AppIndicator 模块：优先 AyatanaAppIndicator3（部分麒麟只有它），回退 AppIndicator3。"""
    import gi
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator
    except (ValueError, ImportError):
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator
    return AppIndicator

KEYRING_LOCKED = "__TOKEN_EYE_KEYRING_LOCKED__"  # 哨兵：collect() 用，不经过 get_key

# 钥匙环状态（collect()/rebuild_menu 间传递）：'ok' | 'locked' | 'unavailable'
_last_keyring_state = "ok"

# 解锁请求进行中标记：防止连点菜单堆出多个等待线程（2026-10-19）
_unlock_in_progress = False

# B4：刷新重入锁——30 秒定时器无条件触发，若某轮卡住，线程会逐轮堆积
_refresh_lock = threading.Lock()


def linux_get_key(service):
    """gnome-keyring 读密钥：secretstorage 按 attribute service=<name> 查找。

    B2-b：这里**只读不解锁**。默认钥匙环重启后常处于锁定态，若在读路径里
    解锁，unlock() 内部的 exec_prompt_glib 会嵌套跑一个 GLib 主循环且无超时，
    提示框不关闭就永久阻塞刷新线程。锁定时直接返回空，由 collect() 的
    probe_keyring_state() 统一识别锁定态，菜单给出「点击解锁」入口。
    """
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


def probe_keyring_state():
    """只读探测钥匙环状态，不解锁、不弹框。

    返回 'ok' / 'locked' / 'unavailable'（D-Bus 或 keyring 服务未就绪）。
    """
    try:
        import secretstorage
        bus = secretstorage.dbus_init()
        coll = secretstorage.get_default_collection(bus)
        if coll is None:
            return "unavailable"
        return "locked" if coll.is_locked() else "ok"
    except Exception:
        return "unavailable"


def ensure_keyring_unlocked(timeout=60.0):
    """带超时的解锁尝试（用户点击菜单项时调用，返回 (ok, msg)）。

    P0-3：secretstorage 各版本 Collection.unlock() 返回值语义相反（True 可能
    是「已取消」也可能是「成功」），故这里不再解读返回值——统一交给
    keyring_common.unlock_and_verify() 在解锁后复核 coll.is_locked() 判定成败，
    对两种语义都正确。超时线程与 (ok, msg) 返回契约保持不变。

    超时后底层线程可能仍挂着（等提示框关闭），属已接受的取舍：解锁是用户
    主动触发、低频路径。2026-10-19 超时从 10s 放宽到 60s：gcr-prompter 首次
    经 D-Bus 激活本身就要几秒，加上用户输密码的时间，10s 经常在密码框刚
    出现时就被放弃，表现为「点了没反应」。
    """
    def _try():
        # 解锁判定统一走 keyring_common：忽略 unlock() 返回值，只用 is_locked()
        # 复核（P0-3）。超时线程与 (ok, msg) 返回契约保持不变。
        try:
            coll, err = keyring_common.open_collection()
            if coll is None:
                return False, err or "密钥服务不可用"
            return keyring_common.unlock_and_verify(coll)
        except Exception as e:
            return False, str(e)

    ex = ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(_try).result(timeout=timeout)
    except FuturesTimeout:
        return False, "解锁超时（密码框可能未弹出），请重试"
    finally:
        ex.shutdown(wait=False)


def linux_send_notify(title, message, sound=None):
    """notify-send 发通知（UKUI 走 D-Bus 通知）；失败写 debug 日志留痕，不静默吞掉。"""
    try:
        cmd = ["notify-send", "-a", APP_ID, "-i",
               os.path.join(ICON_DIR, "token-eye-ok_22.png"), title, message]
        r = subprocess.run(cmd, timeout=5, capture_output=True)
        if r.returncode != 0:
            detail = (r.stderr or b"").decode("utf-8", "replace").strip()[:120]
            _log_debug(f"notify-send 返回 {r.returncode}: {detail}")
    except Exception as e:
        _log_debug(f"notify-send 调用失败: {e}")


# ---------------------------------------------------------------------------
# 浏览器偏好：打开平台链接（登录页 / 控制台）时优先 Chromium
# ---------------------------------------------------------------------------
# 原因：MiMo 的 Cookie 只能从 Chromium 系浏览器解密提取（linux/scripts/
# refresh-mimo-cookie.py，Chromium 优先），而本机系统默认浏览器是 360 安全浏览器
# （browser360-cn.desktop）。若用默认浏览器打开登录页，用户会在 360 里登录，
# 刷新脚本仍然读不到新 Cookie，形成「登录了却一直 401」的死循环。
# 故凡 token-eye 打开链接，一律优先 Chromium；没装才回退系统默认。
# 覆盖：环境变量 TOKEN_EYE_BROWSER=<可执行名或绝对路径>；=default 强制走系统默认。
CHROMIUM_CANDIDATES = ("chromium-browser", "chromium", "chromium-browser-stable")
DEFAULT_BROWSER_LABEL = "系统默认浏览器"

_browser_cmd_cache = None  # None=未探测；[]=无偏好（走默认）；[path]=Chromium 路径


def _detect_browser_cmd():
    """返回优先浏览器的可执行路径；None 表示走系统默认（xdg-open）。"""
    global _browser_cmd_cache
    if _browser_cmd_cache is not None:
        return _browser_cmd_cache[0] if _browser_cmd_cache else None
    pref = (os.environ.get("TOKEN_EYE_BROWSER") or "").strip()
    if pref:
        if pref.lower() in ("default", "system", "xdg-open"):
            _browser_cmd_cache = []
            return None
        cmd = shutil.which(pref)
        if not cmd and os.path.isabs(pref) and os.access(pref, os.X_OK):
            cmd = pref
        if cmd:
            _browser_cmd_cache = [cmd]
            return cmd
        # 指定的浏览器不存在：落回自动探测，不静默失联
    for name in CHROMIUM_CANDIDATES:
        cmd = shutil.which(name)
        if cmd:
            _browser_cmd_cache = [cmd]
            return cmd
    _browser_cmd_cache = []
    return None


def open_in_browser(url):
    """打开 URL，优先 Chromium，回退系统默认浏览器。

    返回 (是否发起成功, 浏览器标识)：标识用于通知文案说明实际用了哪个浏览器。
    用 Popen 非阻塞——本函数可能在 GTK 主线程（菜单点击）里调用，不能卡 UI。
    """
    if not url:
        return False, ""
    browser = _detect_browser_cmd()
    attempts = []
    if browser:
        attempts.append(([browser, "--new-window", url], f"Chromium（{os.path.basename(browser)}）"))
    attempts.append((["xdg-open", url], DEFAULT_BROWSER_LABEL))
    for argv, label in attempts:
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, label
        except Exception:
            continue
    return False, ""


# 注入
token_eye.get_key = linux_get_key
token_eye.send_notify = linux_send_notify

# _open_login_page 内部调用 "open" 命令 —— 换成 Chromium 优先的等价实现
def _linux_open_login(flags_dir, pid, login_url, cooldown=1800):
    """打开登录页；**成功后才写冷却 flag**（旧代码先写 flag 再打开且吞失败，
    打不开也会留下 30 分钟冷却并发「已打开」假通知，P2 错误处理）。"""
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
    ok, label = open_in_browser(login_url)
    if not ok:
        _log_debug(f"打开登录页失败（不写冷却 flag，下轮可重试）: {pid}")
        token_eye.send_notify("Token Eye: 登录已过期",
                              f"{pid} 会话失效，自动打开登录页失败，请手动打开控制台重新登录")
        return False
    # 发起浏览器成功之后才写冷却 flag；写失败留痕但不影响本次结论
    try:
        with open(flag, "w") as f:
            f.write(str(now))
    except Exception as e:
        _log_debug(f"写登录冷却 flag 失败: {e}")
    token_eye.send_notify("Token Eye: 登录已过期",
                          f"{pid} 会话失效，已用{label or '浏览器'}打开登录页，登录后自动续期")
    return True

token_eye._open_login_page = _linux_open_login

# 单位机网络偏慢（信创机直连各平台 API 偶发超时），放宽 curl/进程超时
_orig_fetch = token_eye.fetch_api

def _fetch_api_relaxed(*args, **kwargs):
    """透传上游 fetch_api，仅把单位机偏慢场景的 curl/进程超时放宽。

    用 *args/**kwargs 而非固定 6 个位置参数转发：上游一旦增删参数或调整签名，
    这里不会立刻崩，只是把新参数原样带过去（P1-4）。两个超时用 setdefault，
    调用方显式指定时以其为准。
    """
    kwargs.setdefault("curl_timeout", 20)
    kwargs.setdefault("proc_timeout", 35)
    return _orig_fetch(*args, **kwargs)

token_eye.fetch_api = _fetch_api_relaxed


# ---------------------------------------------------------------------------
# 数据收集（复用上游 process_provider / 并行逻辑）
# ---------------------------------------------------------------------------

def _notify_keyring_locked_once():
    """锁定态通知限频：标记文件 1 小时内只提醒一次，避免每 30 秒刷屏。"""
    flag = "/tmp/token-eye-keyring-notified.flag"
    try:
        if os.path.exists(flag) and time.time() - os.path.getmtime(flag) < 3600:
            return
        linux_send_notify("Token Eye 钥匙环未解锁",
                          "点击托盘菜单「解锁钥匙环」以恢复余额显示")
        with open(flag, "w") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass


def _config_error_result(colors, lines):
    """合成一条配置错误结果，让菜单显示错误横幅而不是整轮崩溃。"""
    return {"id": "_config", "name": "配置", "status": "error",
            "lines": lines, "colors": [colors.get("ERR", "#e74c3c")],
            "menu_bar": "", "console_url": None}


def collect(config_path, project_dir):
    """与上游 run() 相同的并行收集，返回 (results, config, colors, appearance)。

    配置读取与 schema 校验都带兜底（上游 run() 有，Linux 版曾完全跳过
    schema_validate 且读配置无 try —— 脏配置会让后台线程异常、菜单一直停在
    「启动中」）。锁定/不可用态快捷路径（B2-b/B3）：钥匙环锁定或密钥服务不可用时
    所有 key 都读不出，拉网络毫无意义，直接合成结果并给解锁入口；用独立 status
    与「真·未配置 Key」(no_key) 区分，避免把服务故障误导成「去加 Key」。
    """
    global _last_keyring_state
    try:
        # 缓存含完整 API 响应明文：目录仅属主可访问（0700）。
        # exist_ok=True 时 makedirs 不收紧已有目录权限，故再显式 chmod 一次。
        os.makedirs(CACHE_ROOT, mode=0o700, exist_ok=True)
        try:
            os.chmod(CACHE_ROOT, 0o700)
        except OSError as e:
            _log_debug(f"收紧缓存目录权限失败: {e}")
        # 历史保留期清理（上游 run() 里有，Linux 版曾漏掉 → history-*.jsonl 无限增长）
        token_eye.maybe_cleanup_history(CACHE_ROOT)
    except Exception as e:
        _log_debug(f"缓存目录/历史清理失败: {e}")

    config = {}
    try:
        with open(config_path) as f:
            config = json.load(f)
    except Exception as e:
        appearance, colors = token_eye.load_colors({})
        return ([_config_error_result(colors, [f"配置读取失败: {e}"])],
                config, colors, appearance)

    appearance, colors = token_eye.load_colors(config)
    try:
        schema_errors = token_eye.schema_validate(config)
    except Exception as e:
        schema_errors = [f"schema_validate 异常: {e}"]
    if schema_errors:
        lines = ["providers.json 配置错误"] + [f"  {e}" for e in schema_errors[:8]]
        return ([_config_error_result(colors, lines)], config, colors, appearance)

    providers_list = [p for p in config.get("providers", []) if p.get("enabled", True)]

    _last_keyring_state = probe_keyring_state()
    if _last_keyring_state in ("locked", "unavailable"):
        if _last_keyring_state == "locked":
            _notify_keyring_locked_once()
        # 独立 status：worst_status 会把它当未知态落 warn，rebuild_menu 按
        # _last_keyring_state 渲染对应横幅；不再复用 no_key 以免与缺 Key 混淆。
        state_status = ("keyring_locked" if _last_keyring_state == "locked"
                        else "keyring_unavailable")
        results = [{
            "id": p.get("id", "?"), "name": p.get("name", "?"),
            "status": state_status, "lines": [],
            "colors": [colors.get("WARN", "#e67e22")],
            "menu_bar": "", "console_url": p.get("console_url"),
        } for p in providers_list]
        return results, config, colors, appearance

    results = [None] * len(providers_list)
    if providers_list:
        with ThreadPoolExecutor(max_workers=max(1, len(providers_list))) as executor:
            futures = {
                executor.submit(
                    token_eye.process_provider,
                    p=p, config=config, colors=colors, appearance=appearance,
                    cache_dir=CACHE_ROOT, hdir=CACHE_ROOT, project_dir=project_dir,
                    force=False): i
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
    """最差状态：error=3 / warn|no_key=2 / ok=0；未知状态按 warn(2) 处理并留痕。

    旧实现把任何非 error/warn/no_key 的状态静默映射成 0(ok) —— 上游新增状态
    或本端自定义状态（如 keyring_unavailable）会被当成「一切正常」显示绿勾，
    属假绿。未知态一律降级为 warn 并写 debug 日志，便于发现口径漂移。
    """
    def _rank(r):
        s = r.get("status")
        if s == "error":
            return 3
        if s in ("warn", "no_key"):
            return 2
        if s == "ok":
            return 0
        _log_debug(f"worst_status: 未知状态 {s!r} 按 warn 处理")
        return 2
    return max((_rank(r) for r in results if r), default=0)


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
    _import_appindicator()   # 校验/选定 AppIndicator 命名空间（Ayatana 优先）
    from gi.repository import Gtk, GLib, Gdk
    return Gtk, GLib, Gdk


Gtk = GLib = Gdk = None


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

    if _last_keyring_state == "locked":
        # B3：锁定态要有明确 UI 出口，与「真未配置 Key」区分
        menu_add_label(menu, "🔒 钥匙环未解锁", color=colors["WARN"], bold=True)
        menu_add_label(menu, "点击解锁钥匙环并刷新 →", color=colors["OK"],
                       on_activate=unlock_and_refresh)
        menu_add_label(menu, "（解锁前无法读取任何 Key，数据不可用）",
                       color=colors["MUTED"], size="small")
    elif _last_keyring_state == "unavailable":
        # 与「未配置 Key」/「已锁定」都区分开：这是密钥服务本身没起来，
        # 让用户去加 Key 或输密码都是误导，只提示确认会话后刷新。
        menu_add_label(menu, "⚠️ 密钥服务不可用", color=colors["WARN"], bold=True)
        menu_add_label(menu, "（D-Bus / gnome-keyring 未就绪，数据不可用；"
                       "确认已登录桌面会话后点「立即刷新」重试）",
                       color=colors["MUTED"], size="small")
    else:
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
    # 版本检查不再在 GTK 主线程同步跑（旧实现 check_latest_version 冷启动最多
    # 约 24s 的 curl，会冻结菜单）；结果由后台线程经 GLib.idle_add 写入全局，
    # 这里只读缓存值，零阻塞。
    latest = _version_info.get("latest", "")
    if latest:
        menu_add_label(menu, f"⬆ 新版本 {latest} 可用", color=colors["HEADER"],
                       size="small", on_activate=lambda: open_url(
                           "https://github.com/jimmywuxin/token-eye/releases/latest"))
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
    """后台线程执行：拉取数据，回主线程重建菜单。

    B4：非阻塞重入锁——上一轮未结束时定时器再触发直接跳过，防止线程逐轮堆积。
    """
    if not _refresh_lock.acquire(blocking=False):
        return

    def _work():
        try:
            results, config, colors, appearance = collect(CONFIG_FILE, RUNTIME_DIR)
            GLib.idle_add(lambda: _apply(results, config, colors))
        except Exception as e:
            GLib.idle_add(lambda: _apply_error(str(e)))
        finally:
            _refresh_lock.release()

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


def _check_version_async():
    """后台线程跑版本自检，冷启动的多次 curl 不再阻塞 GTK 主线程。

    结果经 GLib.idle_add 回主线程写入 _version_info，rebuild_menu 只读全局。
    check_latest_version 自带 86400s 文件缓存，故只在托盘启动时跑一次即可。
    """
    def _work():
        try:
            latest = token_eye.check_latest_version(CACHE_ROOT)
            if latest and token_eye._ver_gt(latest, "v" + token_eye.VERSION):
                if GLib is not None:
                    GLib.idle_add(_apply_version_result, latest)
        except Exception as e:
            _log_debug(f"版本检查失败: {e}")
    threading.Thread(target=_work, daemon=True).start()


def _apply_version_result(latest):
    """GLib 主线程回调：只记下新版本号（菜单由下一次常规刷新渲染）。"""
    _version_info["latest"] = latest
    return False  # idle_add 单次执行


def unlock_and_refresh():
    """菜单「解锁钥匙环」入口：后台线程解锁（带超时），回主线程刷新或提示。

    2026-10-19 单位机实报「点了没反应」：① gcr-prompter 首次 D-Bus 激活
    往往超过旧 10s 超时，密码框还没出现线程就被放弃；② 菜单点击后立即
    收起，用户拿不到任何「正在处理」的反馈。改为 60s 超时 + 点击即通知 +
    防重入（连点不会堆出多个等待线程）。
    """
    global _unlock_in_progress
    if _unlock_in_progress:
        return
    _unlock_in_progress = True
    linux_send_notify("Token Eye 钥匙环", "正在请求解锁，请在弹出的窗口中输入密码…")

    def _work():
        ok, msg = False, "未知错误"
        try:
            ok, msg = ensure_keyring_unlocked(timeout=60.0)
        except Exception as e:  # 线程内异常不能让刷新回调丢失
            msg = str(e)
        GLib.idle_add(lambda: _after_unlock(ok, msg))
    threading.Thread(target=_work, daemon=True).start()


def _after_unlock(ok, msg):
    global _unlock_in_progress
    _unlock_in_progress = False
    try:
        if ok:
            try:
                os.remove("/tmp/token-eye-keyring-notified.flag")
            except OSError:
                pass
            request_refresh()
        else:
            linux_send_notify("Token Eye 钥匙环", f"解锁未成功：{msg or '未知原因'}")
    except Exception:
        pass
    return False  # GLib.idle_add 单次执行


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
    """菜单里的控制台跳转：同样优先 Chromium（保证 cookie 会话与刷新脚本同源）。"""
    open_in_browser(url)


_indicator = None
_menu = None


def main_tray():
    _init_gtk()
    global _indicator, _menu
    from gi.repository import Gtk, GLib
    AppIndicator = _import_appindicator()

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
    _check_version_async()   # 版本自检移出主线程，结果经 idle_add 回传
    # 上游 check_latest_version 现仅读 24h 缓存、永不联网：需在启动时另起后台
    # 刷新把新版本写进缓存，后续刷新/启动才能读到（本调用只发线程、不等待）。
    try:
        kick = getattr(token_eye, "maybe_refresh_version_async", None)
        if callable(kick):
            kick(CACHE_ROOT)
    except Exception as e:
        _log_debug(f"触发版本后台刷新失败: {e}")
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
    config = {}   # 读取失败时下方遍历不会 UnboundLocalError
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
    state = probe_keyring_state()
    if state == "locked":
        print("⚠️ 钥匙环处于锁定态，下方 key 读取结果不准（重启后常见）；"
              "解锁后重跑本命令，或点托盘菜单「解锁钥匙环」")
    elif state == "unavailable":
        print("⚠️ 密钥服务（D-Bus/gnome-keyring）未就绪，key 读取结果可能不准")
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
