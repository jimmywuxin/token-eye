#!/usr/bin/env python3
"""千问 CLI 登录自愈（设备码 / device flow）——供 token-eye 的 command 型 provider 用。

背景：千问 CLI 的登录态约 2 天过期，且**没有 refresh token**，过期后只能人工重走一次
设备码授权。token-eye 每 30 秒渲染一次菜单，绝不能在这里阻塞轮询，所以拆成三段：

  1. `auth status` 显示已登录 → 退出 0（主流程重跑 billing 命令，余额自然回来）
  2. 已有未过期的待授权会话 → 复用（必要时重新打开浏览器）→ 退出 3
  3. 否则发起新会话：`login --init-only` 拿授权 URL → 打开浏览器 →
     **detached** 起一个 `--poll` 子进程跑 `login --complete` → 退出 3

退出码契约（与 swiftbar/token_eye.py 的 run_recovery 对应）：
  0 = 已登录    3 = 等待浏览器授权    其他 = 失败

用户视角：token 过期后菜单变红的同时浏览器自动弹出授权页，点一下「确认」即可，
无需记命令；授权完成后下一轮（≤30 秒）自动恢复显示余额。

用法：
  python3 scripts/qwen-login.py            # 自愈入口（token-eye 调用）
  python3 scripts/qwen-login.py --force    # 强制重新发起授权（菜单「重新登录」）
  python3 scripts/qwen-login.py --poll 300 # 内部使用：后台轮询等待授权完成
"""
import json
import os
import shutil
import subprocess
import sys
import time

CACHE_DIR = os.path.expanduser("~/Library/Caches/token-eye")
PENDING_FILE = os.path.join(CACHE_DIR, "qwen-login-pending.json")
LOG_FILE = os.path.join(CACHE_DIR, "qwen-login.log")

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_WAITING = 3

# 设备码有效期（CLI 返回 300 秒）；留 10 秒余量给网络
POLL_TIMEOUT = 300


def log(msg):
    """追加到 cache 目录下的日志（后台轮询进程看不到终端）。"""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [pid {os.getpid()}] {msg}\n")
    except Exception:
        pass


def notify(msg, title="Token Eye"):
    try:
        safe = msg.replace('"', "\\'")
        subprocess.run(["osascript", "-e",
                        f'display notification "{safe}" with title "{title}"'],
                       timeout=5, capture_output=True)
    except Exception:
        pass


def find_cli():
    """定位 qianwen CLI：环境变量 > npm 全局安装的常规位置 > PATH。"""
    cands = [os.environ.get("QIANWEN_CLI", ""),
             os.path.expanduser("~/.local/bin/qianwen")]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return shutil.which("qianwen")


def cli_env(cli):
    """PATH 里补上 CLI 所在目录：它多是 `#!/usr/bin/env node`，SwiftBar 的窄 PATH
    找不到 node 就会 `env: node: No such file or directory`（见 AGENTS.md）。"""
    env = dict(os.environ)
    d = os.path.dirname(cli)
    if d:
        env["PATH"] = d + os.pathsep + env.get("PATH", "/usr/bin:/bin")
    return env


def run_cli(cli, args, timeout=12):
    try:
        r = subprocess.run([cli] + args, capture_output=True, text=True,
                           timeout=timeout, env=cli_env(cli))
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "命令超时"
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)


def parse_json(text):
    """CLI 会在 JSON 前打印提示行（如 'Open the URL to authorize...'），从首个 { 起解析。"""
    i = (text or "").find("{")
    if i < 0:
        return None
    try:
        return json.loads(text[i:])
    except json.JSONDecodeError:
        return None


def auth_ok(cli):
    code, out, err = run_cli(cli, ["auth", "status", "--format", "json"], timeout=12)
    data = parse_json(out) or parse_json(err) or {}
    return bool(data.get("authenticated"))


def load_pending():
    try:
        with open(PENDING_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def save_pending(data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(PENDING_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def clear_pending():
    try:
        os.unlink(PENDING_FILE)
    except Exception:
        pass


def open_url(url):
    try:
        subprocess.run(["open", url], timeout=10, capture_output=True)
        return True
    except Exception:
        return False


def poller_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def spawn_poller(cli, timeout_s):
    """后台起 `--poll`，把 device flow 的阻塞轮询挪出 SwiftBar 渲染路径。"""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(LOG_FILE, "a") as logf:
            proc = subprocess.Popen(
                [sys.executable or "/usr/bin/python3", os.path.abspath(__file__),
                 "--poll", str(timeout_s)],
                stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True, env=cli_env(cli), cwd="/tmp")
        return proc.pid
    except Exception as e:  # noqa: BLE001
        log(f"起后台轮询失败: {e}")
        return 0


def do_poll(cli, timeout_s):
    """后台模式：等用户在浏览器完成授权，然后收尾（清 pending + 通知）。"""
    log(f"开始轮询授权，超时 {timeout_s}s")
    code, out, err = run_cli(cli, ["login", "--complete", "--timeout", str(timeout_s)],
                             timeout=timeout_s + 30)
    # 退出码不可全信：以「凭据是否真的可用」为准（CLI 在已授权时可能返回非零）
    ok = code == 0 or auth_ok(cli)
    clear_pending()
    log(f"轮询结束: code={code} ok={ok}")
    if ok:
        notify("千问登录成功，余额监控已恢复")
    else:
        tail = (err or out or "").strip().splitlines()
        notify(f"千问登录未完成{('：' + tail[-1][:60]) if tail else ''}，可点菜单「🔑 重新登录 千问」重试")
    return EXIT_OK if ok else EXIT_FAIL


def main(argv):
    if "--poll" in argv:
        idx = argv.index("--poll")
        try:
            timeout_s = int(argv[idx + 1])
        except (IndexError, ValueError):
            timeout_s = POLL_TIMEOUT
        cli = find_cli()
        if not cli:
            log("找不到 qianwen CLI")
            return EXIT_FAIL
        return do_poll(cli, timeout_s)

    force = "--force" in argv
    cli = find_cli()
    if not cli:
        print("错误: 找不到 qianwen CLI（可设 QIANWEN_CLI 指定路径）")
        return EXIT_FAIL

    # 1. 已登录 → 让主流程直接重拉余额
    if auth_ok(cli):
        clear_pending()
        print("千问已登录")
        return EXIT_OK

    # 2. 复用未过期的待授权会话（用户可能在别的窗口关掉了授权页）
    pending = load_pending()
    now = int(time.time())
    if pending and not force and pending.get("expires_at", 0) > now + 15:
        if not poller_alive(pending.get("poller_pid") or 0):
            pending["poller_pid"] = spawn_poller(cli, max(120, int(pending["expires_at"] - now)))
            save_pending(pending)
        if pending.get("url"):
            open_url(pending["url"])
        print("等待浏览器授权（已打开授权页，确认后自动恢复）")
        return EXIT_WAITING

    # 3. 发起新授权会话
    code, out, err = run_cli(cli, ["login", "--init-only", "--format", "json"], timeout=15)
    data = parse_json(out) or parse_json(err)
    url = None
    expires_in = POLL_TIMEOUT
    for ev in (data or {}).get("events") or []:
        if ev.get("event") == "device_code" and ev.get("verification_url"):
            url = ev["verification_url"]
            expires_in = int(ev.get("expires_in_seconds") or ev.get("expires_in") or POLL_TIMEOUT)
            break
    # 授权窗口至少给 3 分钟：CLI 有时只报很短的 expires_in，用户根本来不及点确认，
    # 轮询提前退出会白等一场（设备码真正过期时 complete 自己会报错退出，多轮询无害）。
    expires_in = max(expires_in, 180)
    if not url:
        tail = (err or out or "").strip().splitlines()
        print(f"错误: 发起授权失败{('：' + tail[-1][:80]) if tail else f'（退出码 {code}）'}")
        return EXIT_FAIL

    open_url(url)
    save_pending({"url": url, "expires_at": now + expires_in,
                  "created_at": now,
                  "poller_pid": spawn_poller(cli, expires_in)})
    notify("千问登录已过期，已在浏览器打开授权页，确认后自动恢复")
    print("等待浏览器授权（已打开授权页，确认后自动恢复）")
    return EXIT_WAITING


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
