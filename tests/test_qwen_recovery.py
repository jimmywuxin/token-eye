#!/usr/bin/env python3
"""千问 CLI 登录自愈（scripts/qwen-login.py）+ run_recovery 集成单测。

用**假 qianwen 脚本**（按参数打印固定 JSON、把调用记录进日志文件）覆盖
退出码契约（0=已登录 / 3=等待授权 / 1=失败），不联网、不依赖真实 CLI。

回归背景（2026-11-16 Linux 版反馈）：
  ① open_url 只调 macOS `open`，Linux 上静默失败仍谎报「已打开授权页」；
  ② find_cli 候选不全，SwiftBar 窄 PATH 下找不到 CLI → 永久冷却不恢复。

运行:
  /usr/bin/python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "swiftbar"))
import token_eye as te  # noqa: E402

SCRIPT = os.path.join(ROOT, "scripts", "qwen-login.py")
PY = sys.executable or "/usr/bin/python3"

# 假 qianwen CLI：
# - auth status --format json → FAKE_QIANWEN_AUTH=ok 时回 {"authenticated": true,
#   "token": {"expires_at": $FAKE_QIANWEN_EXP}}；否则 {"authenticated": false}
# - login --init-only → 固定 device_code 事件（example.invalid 假 URL）
# - 其余（login --complete / billing …）退出 2
# 每次调用把参数记进 $FAKE_QIANWEN_LOG，供断言「是否重复 init」。
FAKE_CLI = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_QIANWEN_LOG"
case "$1" in
  auth)
    if [ "$FAKE_QIANWEN_AUTH" = "ok" ]; then
      printf 'logged in\\n{"authenticated": true, "token": {"expires_at": %s}}\\n' \\
        "$FAKE_QIANWEN_EXP"
    else
      printf 'not logged in\\n{"authenticated": false}\\n'
    fi
    exit 0
    ;;
  login)
    if [ "$2" = "--init-only" ]; then
      printf '{"events": [{"event": "device_code", "verification_url": "https://example.invalid/authorize", "expires_in_seconds": 300}]}\\n'
      exit 0
    fi
    # --complete：睡 5s 再退，避免后台 poller 抢先把 pending 清掉（测试竞态）
    sleep 5
    exit 1
    ;;
esac
exit 2
"""


def _script_cache_dir(home):
    """与 qwen-login.py 的 CACHE_DIR 口径一致（测试隔离用 HOME=tmp）。"""
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Caches", "token-eye")
    return os.path.join(home, ".cache", "token-eye")


class QwenLoginTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="te-qwen-test-")
        self.cli = os.path.join(self.tmp, "qianwen")
        with open(self.cli, "w") as f:
            f.write(FAKE_CLI)
        os.chmod(self.cli, 0o755)
        self.invocation_log = os.path.join(self.tmp, "invocations.log")

    def env(self, **extra):
        # 快捷参数 auth=ok/false → FAKE_QIANWEN_AUTH（假 CLI 的开关变量）
        auth = extra.pop("auth", None)
        if auth is not None:
            extra["FAKE_QIANWEN_AUTH"] = auth
        env = {
            "HOME": self.tmp,
            "PATH": "/usr/bin:/bin",
            "QIANWEN_CLI": self.cli,
            "FAKE_QIANWEN_LOG": self.invocation_log,
            # 防止测试真拉起浏览器（darwin 走 TOKEN_EYE_BROWSER 分支，
            # linux CI 上同样生效）；/bin/true 两平台都有、静默吞掉参数
            "TOKEN_EYE_BROWSER": "/bin/true",
        }
        env.update(extra)
        return env

    def run_script(self, *args, **env_extra):
        return subprocess.run([PY, SCRIPT, *args], capture_output=True,
                              text=True, timeout=60, env=self.env(**env_extra))

    def invocations(self):
        try:
            with open(self.invocation_log) as f:
                return [ln.strip() for ln in f if ln.strip()]
        except FileNotFoundError:
            return []

    def write_pending(self, expires_at):
        d = _script_cache_dir(self.tmp)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "qwen-login-pending.json"), "w") as f:
            json.dump({"url": "https://example.invalid/pending",
                       "expires_at": expires_at, "created_at": int(time.time()),
                       "poller_pid": 0}, f)  # pid 0 → poller_alive 视为存活，不起真轮询

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestExitCodeContract(QwenLoginTestBase):
    def test_1_authed_exits_0_no_reinit(self):
        """① auth status 已登录 → 退出 0；不发起 init（主流程据 ok 退出码重拉余额）。"""
        r = self.run_script(auth="ok", FAKE_QIANWEN_EXP=str(int(time.time()) + 86400))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("已登录", r.stdout)
        self.assertNotIn("--init-only", " ".join(self.invocations()))

    def test_2_pending_fresh_exits_3_no_reinit(self):
        """② 未登录且 pending 未过期 → 退出 3 且**不重复 init**（复用现有授权会话）。"""
        self.write_pending(int(time.time()) + 300)
        r = self.run_script()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("等待浏览器授权", r.stdout)
        self.assertNotIn("--init-only", " ".join(self.invocations()))

    def test_3_pending_expired_reinit(self):
        """③ pending 过期 → 重新 init 并重写 pending（旧授权 URL 已失效）。"""
        self.write_pending(int(time.time()) - 1)
        r = self.run_script()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("--init-only", " ".join(self.invocations()))
        d = _script_cache_dir(self.tmp)
        with open(os.path.join(d, "qwen-login-pending.json")) as f:
            pending = json.load(f)
        self.assertEqual(pending["url"], "https://example.invalid/authorize")
        self.assertGreater(pending["expires_at"], int(time.time()))
        # 后台轮询进程会 clear_pending()，先收掉它，避免竞态与临时目录残留
        pid = pending.get("poller_pid") or 0
        if pid:
            import signal
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def test_4_cli_missing_exits_1_with_hint(self):
        """④ CLI 不存在 → 退出 1，错误信息含 QIANWEN_CLI 提示（可自行设置路径）。"""
        r = self.run_script(QIANWEN_CLI=os.path.join(self.tmp, "no-such-qianwen"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("QIANWEN_CLI", r.stdout)

    def test_5_failed_open_url_not_claimed_opened(self):
        """TOKEN_EYE_BROWSER 指向不存在的浏览器 → 不谎报「已打开授权页」，
        明确提示手动打开 URL（2026-11-16 缺陷 ① 的直接回归）。"""
        r = self.run_script(TOKEN_EYE_BROWSER=os.path.join(self.tmp, "no-browser"),
                            FAKE_QIANWEN_AUTH="no")
        self.assertEqual(r.returncode, 3)
        self.assertIn("请手动打开", r.stdout)
        self.assertNotIn("已打开授权页，确认后自动恢复", r.stdout)


class TestFindCli(unittest.TestCase):
    """find_cli 单测：显式 QIANWEN_CLI 优先且无效即失败；候选按序命中。"""

    def _load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("qwen_login_mod", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _find(self, env_extra, isfile=None, which=None):
        """候选路径用 mock 固定，测试不依赖本机是否装过真实 qianwen CLI。"""
        mod = self._load()
        env = {"HOME": self.tmp, "PATH": "/usr/bin:/bin",
               "FAKE_QIANWEN_LOG": os.path.join(self.tmp, "log")}
        env.update(env_extra)
        with contextlib.ExitStack() as stack:
            if isfile is not None:
                stack.enter_context(
                    mock.patch.object(mod.os.path, "isfile", side_effect=isfile))
                # find_cli 同时查 isfile + access(X_OK)；mock 掉权限检查
                stack.enter_context(
                    mock.patch.object(mod.os, "access", return_value=True))
            stack.enter_context(
                mock.patch.object(mod.shutil, "which", return_value=which))
            return mod.find_cli(env)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="te-qwen-findcli-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_explicit_valid_wins(self):
        cli = os.path.join(self.tmp, "qianwen")
        self.assertEqual(self._find({"QIANWEN_CLI": cli},
                                    isfile=lambda p: p == cli), cli)

    def test_explicit_invalid_returns_none(self):
        self.assertIsNone(
            self._find({"QIANWEN_CLI": os.path.join(self.tmp, "nope")},
                       isfile=lambda p: False))

    def test_local_bin_candidate(self):
        """无 QIANWEN_CLI 时按候选序命中 ~/.local/bin（排在绝对路径候选之前，
        不依赖本机是否恰好装过真实 CLI）。"""
        cli = os.path.join(self.tmp, ".local", "bin", "qianwen")
        self.assertEqual(self._find({}, isfile=lambda p: p == cli), cli)

    def test_nothing_found_returns_none(self):
        # 全部候选与 PATH 都 mock 成找不到，跨环境恒定
        self.assertIsNone(self._find({}, isfile=lambda p: False))


class TestRunRecoveryIntegration(unittest.TestCase):
    """run_recovery ↔ scripts/qwen-login.py 端到端（仍用假 CLI，不联网）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="te-qwen-rec-")
        self.cli = os.path.join(self.tmp, "qianwen")
        with open(self.cli, "w") as f:
            f.write(FAKE_CLI)
        os.chmod(self.cli, 0o755)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_authed_maps_to_ok(self):
        """脚本退出 0 → run_recovery 返回 ok（process_provider 据此重拉余额）。"""
        overrides = {
            "HOME": self.tmp,                      # 隔离 CACHE_DIR，勿碰真实 pending
            "QIANWEN_CLI": self.cli,
            "TOKEN_EYE_BROWSER": "/bin/true",
            "FAKE_QIANWEN_AUTH": "ok",
            "FAKE_QIANWEN_EXP": str(int(time.time()) + 86400),
        }
        with mock.patch.dict(os.environ, overrides):
            state, msg = te.run_recovery(self.tmp, "qwen", SCRIPT)
        self.assertEqual(state, "ok")
        self.assertIn("已登录", msg)

    def test_failure_maps_to_fail(self):
        overrides = {
            "HOME": self.tmp,
            "QIANWEN_CLI": os.path.join(self.tmp, "no-such-qianwen"),
        }
        with mock.patch.dict(os.environ, overrides):
            state, msg = te.run_recovery(self.tmp, "qwen", SCRIPT)
        self.assertEqual(state, "fail")
        self.assertIn("QIANWEN_CLI", msg)


class TestExpiryWarning(unittest.TestCase):
    """到期预警：_parse_expiry_epoch 兼容秒/毫秒/ISO；<24h 出行、<2h 告警色。"""

    def test_parse_seconds_ms_iso(self):
        now = int(time.time())
        self.assertEqual(te._parse_expiry_epoch(now), now)
        self.assertEqual(te._parse_expiry_epoch(now * 1000), now)
        self.assertEqual(te._parse_expiry_epoch(now * 1000 + 500), now)
        from datetime import datetime
        iso = datetime.fromtimestamp(now).isoformat()
        self.assertEqual(te._parse_expiry_epoch(iso), now)
        self.assertIsNone(te._parse_expiry_epoch("not-a-date"))

    def test_warning_line_within_24h(self):
        d = tempfile.mkdtemp()
        appearance, colors = te.load_colors({})
        p = {"id": "qwen", "name": "千问",
             "parser": {"type": "command", "command": "/bin/echo",
                        "args": [], "recovery": "qwen-login",
                        "fields": {"balance": "availableAmount",
                                   "currency": "currency"}}}
        cfg = {"cache": {"command": 300}}
        data = {"availableAmount": 42.5, "currency": "CNY"}
        exp = int(time.time()) + 3600  # 1h 后到期 → 告警色
        with mock.patch.object(te, "fetch_command",
                               return_value={"ok": True, "status": None,
                                             "data": data, "error_kind": None,
                                             "message": ""}), \
             mock.patch.object(te, "command_token_expiry", return_value=exp), \
             mock.patch.object(te, "send_notify"):
            r = te.process_provider(p, cfg, colors, appearance, d, d, "/tmp")
        self.assertEqual(len(r["lines"]), len(r["colors"]))
        # 到期行补 line_params 占位，三数组必须等长（否则后续行 href 错一位）
        self.assertEqual(len(r["lines"]), len(r["line_params"]))
        warn_lines = [ln for ln in r["lines"] if "到期" in ln]
        self.assertEqual(len(warn_lines), 1)
        self.assertIn("重新授权", warn_lines[0])
        self.assertEqual(r["colors"][r["lines"].index(warn_lines[0])], colors["WARN"])

    def test_no_warning_when_far(self):
        d = tempfile.mkdtemp()
        appearance, colors = te.load_colors({})
        p = {"id": "qwen", "name": "千问",
             "parser": {"type": "command", "command": "/bin/echo",
                        "args": [], "recovery": "qwen-login",
                        "fields": {"balance": "availableAmount",
                                   "currency": "currency"}}}
        cfg = {"cache": {"command": 300}}
        data = {"availableAmount": 42.5, "currency": "CNY"}
        exp = int(time.time()) + 40 * 3600  # 40h 后 → 不出行
        with mock.patch.object(te, "fetch_command",
                               return_value={"ok": True, "status": None,
                                             "data": data, "error_kind": None,
                                             "message": ""}), \
             mock.patch.object(te, "command_token_expiry", return_value=exp), \
             mock.patch.object(te, "send_notify"):
            r = te.process_provider(p, cfg, colors, appearance, d, d, "/tmp")
        self.assertFalse([ln for ln in r["lines"] if "到期" in ln])


class TestWaitingStyle(unittest.TestCase):
    """waiting 可见态：错误行换 🟡「等待浏览器确认授权」，render 用 icon 字段。"""

    def test_apply_waiting_style(self):
        colors = te.load_colors({})[1]
        err = te.render_error("qwen", "千问", "client", "unauthorized",
                              None, colors)
        te._apply_waiting_style(err, colors)
        self.assertEqual(err["icon"], "🟡")
        self.assertEqual(err["colors"][0], colors["WARN"])
        self.assertIn("等待浏览器确认授权", err["lines"][0])

    def test_render_prints_icon(self):
        colors = te.load_colors({})[1]
        err = te.render_error("qwen", "千问", "client", "unauthorized",
                              None, colors)
        te._apply_waiting_style(err, colors)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            te.render([err], {}, colors, {}, tempfile.mkdtemp())
        self.assertIn("🟡 千问", out.getvalue())


class TestRecoveryScriptPath(unittest.TestCase):
    """Linux 端自动自愈接线（2026-11-16 复核发现的 P0 断点）。

    linux/token-eye-tray.py 把 project_dir 传成 linux/（refresh 脚本在
    linux/scripts/），但登录自愈脚本只有仓库根 scripts/ 一份；旧实现拼出
    linux/scripts/qwen-login.py 永远不存在 → 自愈静默不触发。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="te-qwen-path-")
        self.linux_dir = os.path.join(self.tmp, "linux")
        os.makedirs(os.path.join(self.linux_dir, "scripts"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mac_style_direct_hit(self):
        self.assertEqual(te.recovery_script_path(ROOT, "qwen-login"),
                         os.path.join(ROOT, "scripts", "qwen-login.py"))

    def test_linux_style_falls_back_to_repo_root(self):
        path = te.recovery_script_path(self.linux_dir, "qwen-login")
        self.assertEqual(path, os.path.join(ROOT, "scripts", "qwen-login.py"))

    def test_project_dir_script_wins_if_present(self):
        local = os.path.join(self.linux_dir, "scripts", "qwen-login.py")
        with open(local, "w") as f:
            f.write("# placeholder\n")
        self.assertEqual(te.recovery_script_path(self.linux_dir, "qwen-login"), local)

    def test_rejects_path_traversal(self):
        self.assertIsNone(te.recovery_script_path(self.linux_dir, "../etc/passwd"))
        self.assertIsNone(te.recovery_script_path(self.linux_dir, ""))
        self.assertIsNone(te.recovery_script_path(self.linux_dir, "no-such-script"))

    def test_process_provider_calls_recovery_on_linux(self):
        """端到端接线：Linux 风格 project_dir + 命令失败 → run_recovery 真被调用，
        且拿到的是仓库根脚本（不是不存在的 linux/scripts/…）。"""
        d = tempfile.mkdtemp()
        p = {"id": "qwen", "name": "千问",
             "parser": {"type": "command", "command": "/bin/echo",
                        "args": [], "recovery": "qwen-login",
                        "fields": {"balance": "availableAmount",
                                   "currency": "currency"}}}
        fail = {"ok": False, "status": None, "data": None,
                "error_kind": "client", "message": "unauthorized"}
        appearance, colors = te.load_colors({})
        with mock.patch.object(te, "fetch_command", return_value=fail), \
             mock.patch.object(te, "run_recovery",
                               return_value=("waiting", "等待浏览器授权")) as rr, \
             mock.patch.object(te, "send_notify"):
            r = te.process_provider(p, {"cache": {"command": 300}}, colors,
                                    appearance, d, d, self.linux_dir)
        self.assertTrue(rr.called, "Linux 风格 project_dir 也必须触发自动自愈")
        self.assertEqual(rr.call_args.args[2],
                         os.path.join(ROOT, "scripts", "qwen-login.py"))
        self.assertEqual(r["status"], "error")


class TestRecoveryFlagFreshness(unittest.TestCase):
    def test_stale_waiting_flag_ignored(self):
        """重启后残留的旧 waiting 标记不能让菜单一直显示「等待授权」。"""
        d = tempfile.mkdtemp()
        flag = te._flag_path(d, "qwen", "recovery")
        with open(flag, "w") as f:
            f.write(f"{int(time.time()) - 3600} waiting 等待浏览器授权")
        self.assertIsNone(te._recovery_state(d, "qwen"))
        with open(flag, "w") as f:
            f.write(f"{int(time.time())} waiting 等待浏览器授权")
        self.assertEqual(te._recovery_state(d, "qwen"), "waiting")


if __name__ == "__main__":
    unittest.main()
