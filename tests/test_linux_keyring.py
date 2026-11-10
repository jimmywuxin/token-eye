#!/usr/bin/env python3
"""Linux 注入层单测（钥匙环语义 / collect 三态 / 刷新脚本假绿）。

覆盖：
  - B1 语义修正 / B2-b 只读不解锁 / B4 重入锁（历史 12 例）
  - P0-3 unlock_and_verify 忽略 unlock() 返回值，只用 is_locked() 复核
  - collect() 在 keyring unavailable 时与 no_key 可区分
  - Linux 版 check_cookie 对 HTTP 200 + 业务错误体判失败（P0-1）

不依赖真机 D-Bus：注入假 secretstorage 模块模拟「解锁/锁定/取消」三态，刷新脚本
用 unittest.mock 替换 subprocess.run，绝不发真实请求、不写任何密钥/Cookie 明文。
托盘模块会 monkey-patch 共享的 token_eye（get_key/send_notify/_open_login_page/
fetch_api）并可能污染 sys.modules["secretstorage"]——每个测试结束必须恢复，
否则殃及 test_token_eye（v0.23.11 开发期间实测踩过）。

运行:
  /usr/bin/python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")
TRAY = os.path.join(REPO, "linux", "token-eye-tray.py")
KEYRING_COMMON = os.path.join(REPO, "linux", "keyring_common.py")
MIMO_REFRESH = os.path.join(REPO, "linux", "scripts", "refresh-mimo-cookie.py")

# 托盘模块会改写的 token_eye 属性（恢复用）
_PATCHED_ATTRS = ("get_key", "send_notify", "_open_login_page", "fetch_api")


def _install_fake_secretstorage(coll):
    """注入假 secretstorage，返回恢复函数（幂等）。"""
    saved_ss = sys.modules.get("secretstorage")

    m = types.ModuleType("secretstorage")
    m.dbus_init = lambda: object()
    m.get_default_collection = lambda bus: coll
    sys.modules["secretstorage"] = m

    # 快照 token_eye 被 patch 的属性（托盘模块 import 时即执行 patch）
    te = sys.modules.get("token_eye")
    saved_attrs = {a: getattr(te, a) for a in _PATCHED_ATTRS} if te else None

    spec = importlib.util.spec_from_file_location("token_eye_tray_test", TRAY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def _restore():
        if saved_ss is not None:
            sys.modules["secretstorage"] = saved_ss
        else:
            sys.modules.pop("secretstorage", None)
        if te is not None and saved_attrs:
            for a, v in saved_attrs.items():
                setattr(te, a, v)
    return mod, _restore


def _load_module(name, path):
    """按文件路径加载模块（不写 sys.modules，避免污染发现顺序）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_coll(locked_before, locked_after, unlock_return):
    """用 unittest.mock 造假集合：unlock() 调用后按 locked_after 翻转状态，
    返回值由 unlock_return 指定（模拟两种相反的返回值语义）。"""
    state = {"locked": locked_before}
    coll = Mock()

    def _is_locked():
        return state["locked"]

    def _unlock():
        state["locked"] = locked_after
        return unlock_return

    coll.is_locked.side_effect = _is_locked
    coll.unlock.side_effect = _unlock
    return coll


class _FakeCollection:
    def __init__(self, locked=True, unlock_return=True, unlock_calls=None,
                 items=None):
        self._locked = locked
        self._unlock_return = unlock_return   # secretstorage 2.3.x: True=用户取消
        self.unlock_calls = unlock_calls if unlock_calls is not None else []
        self._items = items or []

    def is_locked(self):
        # 解锁成功后变为未锁定（模拟真实行为）
        return self._locked

    def unlock(self):
        self.unlock_calls.append(1)
        if not self._unlock_return:      # False = 解锁成功
            self._locked = False
        return self._unlock_return

    def search_items(self, attributes):
        return self._items


class _FakeItem:
    def __init__(self, secret=b"sk-test"):
        self._secret = secret

    def get_secret(self):
        return self._secret


class TestLinuxGetKeyReadOnly(unittest.TestCase):
    """B2-b：linux_get_key 只读不解锁。"""

    def setUp(self):
        self.coll = _FakeCollection(locked=False)
        self.mod, self._restore = _install_fake_secretstorage(self.coll)
        self.addCleanup(self._restore)

    def test_locked_returns_empty_and_never_unlocks(self):
        self.coll._locked = True
        calls = self.coll.unlock_calls
        self.assertEqual(self.mod.linux_get_key("DEEPSEEK_API_KEY"), "")
        self.assertEqual(calls, [], "读路径绝不允许触发 unlock")

    def test_unlocked_reads_secret(self):
        self.coll._items = [_FakeItem(b"sk-abc")]
        self.assertEqual(self.mod.linux_get_key("DEEPSEEK_API_KEY"), "sk-abc")

    def test_service_unavailable_returns_empty(self):
        self.mod.sys.modules["secretstorage"] = types.ModuleType("secretstorage_bad")
        del self.mod.sys.modules["secretstorage"]  # 触发真实 import 路径
        # 临时替换为 import 即抛错的假模块
        class _Boom:
            def __getattr__(self, name):
                raise RuntimeError("no dbus")
        boom = types.ModuleType("secretstorage")
        boom.dbus_init = lambda: (_ for _ in ()).throw(RuntimeError("no dbus"))
        self.mod.sys.modules["secretstorage"] = boom
        self.assertEqual(self.mod.linux_get_key("X"), "")


class TestProbeKeyringState(unittest.TestCase):
    def setUp(self):
        self.coll = _FakeCollection(locked=False)
        self.mod, self._restore = _install_fake_secretstorage(self.coll)
        self.addCleanup(self._restore)

    def test_ok(self):
        self.assertEqual(self.mod.probe_keyring_state(), "ok")

    def test_locked(self):
        self.coll._locked = True
        self.assertEqual(self.mod.probe_keyring_state(), "locked")

    def test_unavailable(self):
        boom = types.ModuleType("secretstorage")
        boom.dbus_init = lambda: (_ for _ in ()).throw(RuntimeError("no dbus"))
        self.mod.sys.modules["secretstorage"] = boom
        self.assertEqual(self.mod.probe_keyring_state(), "unavailable")


class TestEnsureKeyringUnlocked(unittest.TestCase):
    """B1：unlock() 返回 True=用户取消、False=解锁成功（secretstorage 2.3.x）。"""

    def setUp(self):
        self.coll = _FakeCollection(locked=True)
        self.mod, self._restore = _install_fake_secretstorage(self.coll)
        self.addCleanup(self._restore)

    def test_unlock_success_false_return(self):
        # 旧代码的 bug 场景：unlock() 返回 False（成功）却被当成失败
        self.coll._unlock_return = False
        ok, msg = self.mod.ensure_keyring_unlocked(timeout=3.0)
        self.assertTrue(ok, "解锁成功必须返回 ok=True（旧代码在这里误判）")
        self.assertEqual(msg, "")

    def test_dismissed_true_return(self):
        self.coll._unlock_return = True
        ok, msg = self.mod.ensure_keyring_unlocked(timeout=3.0)
        self.assertFalse(ok)
        self.assertIn("取消", msg)

    def test_still_locked_after_unlock(self):
        # unlock() 返回 False 但 is_locked() 仍为 True（密码不对等异常流）
        self.coll._unlock_return = False
        self.coll.is_locked = lambda: True   # 覆盖：解锁后仍锁定
        ok, msg = self.mod.ensure_keyring_unlocked(timeout=3.0)
        self.assertFalse(ok)
        self.assertIn("仍未解锁", msg)

    def test_already_unlocked_no_call(self):
        self.coll._locked = False
        ok, _ = self.mod.ensure_keyring_unlocked(timeout=3.0)
        self.assertTrue(ok)
        self.assertEqual(self.coll.unlock_calls, [])

    def test_timeout(self):
        def hang_unlock():
            time.sleep(5)   # 模拟提示框不关闭
            return True
        self.coll.unlock = hang_unlock
        t0 = time.monotonic()
        ok, msg = self.mod.ensure_keyring_unlocked(timeout=1.0)
        elapsed = time.monotonic() - t0
        self.assertFalse(ok)
        self.assertIn("超时", msg)
        self.assertLess(elapsed, 3.0, "超时必须生效，不能被嵌套主循环挂死")


class TestRefreshReentryLock(unittest.TestCase):
    """B4：上轮未结束时，定时器再触发 refresh_once 必须被跳过。"""

    def test_no_thread_pileup(self):
        self.coll = _FakeCollection(locked=False)
        mod, self._restore = _install_fake_secretstorage(self.coll)
        self.addCleanup(self._restore)

        calls = {"n": 0}
        lock = threading.Lock()

        def slow_collect(*a, **k):
            with lock:
                calls["n"] += 1
            time.sleep(0.4)
            return [], {}, {}, None

        class _FakeGLib:
            @staticmethod
            def idle_add(fn, *a):
                fn(*a)
                return False

        mod.collect = slow_collect
        mod.GLib = _FakeGLib

        mod.refresh_once()              # 第 1 轮：拿到锁，进入 slow_collect
        mod.refresh_once()              # 第 2 轮：应被锁挡掉
        mod.refresh_once()              # 第 3 轮：同样被挡掉
        time.sleep(0.7)                 # 等第 1 轮结束（含 finally 释放锁）
        self.assertEqual(calls["n"], 1, "卡住的一轮期间不允许堆积新线程")

        mod.refresh_once()              # 锁已释放：应正常进入
        time.sleep(0.6)
        self.assertEqual(calls["n"], 2)


class TestUnlockAndVerify(unittest.TestCase):
    """P0-3：unlock_and_verify 忽略 unlock() 返回值，一律用 is_locked() 复核。

    对 unlock() 返回 True 与 False 两种情形，结论都必须只由解锁后的 is_locked()
    决定——这样无论目标机 secretstorage 把 True/False 解释成什么，判定都正确。
    """
    def setUp(self):
        self.kc = _load_module("keyring_common_test", KEYRING_COMMON)

    def test_return_false_and_unlocked_is_success(self):
        # 返回 False（tray 旧语义的「成功」）且确实解锁 → 成功
        ok, msg = self.kc.unlock_and_verify(_fake_coll(True, False, False))
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_return_true_and_unlocked_is_success(self):
        # 返回 True（diag 旧语义的「成功」）且确实解锁 → 仍成功（不靠返回值）
        ok, msg = self.kc.unlock_and_verify(_fake_coll(True, False, True))
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_return_false_but_still_locked_is_failure(self):
        # 返回 False 却没解锁（密码错）：不能因返回值想当然判成功
        ok, msg = self.kc.unlock_and_verify(_fake_coll(True, True, False))
        self.assertFalse(ok)
        self.assertIn("仍未解锁", msg)

    def test_return_true_and_still_locked_is_failure(self):
        # 返回 True 且仍锁定（用户取消）：判失败
        ok, msg = self.kc.unlock_and_verify(_fake_coll(True, True, True))
        self.assertFalse(ok)
        self.assertIn("仍未解锁", msg)

    def test_already_unlocked_does_not_call_unlock(self):
        coll = _fake_coll(False, False, False)
        ok, msg = self.kc.unlock_and_verify(coll)
        self.assertTrue(ok)
        self.assertEqual(msg, "")
        coll.unlock.assert_not_called()


class TestCollectKeyringUnavailable(unittest.TestCase):
    """collect() 在 keyring unavailable 时结果必须能与 no_key 区分。

    密钥服务没起来 ≠ 用户没配 Key；两者用不同 status 标记，菜单也分别给横幅。
    """
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg_path = os.path.join(self.tmp.name, "providers.json")
        with open(self.cfg_path, "w") as f:
            json.dump({"providers": [
                {"id": "a", "name": "A", "enabled": True, "keychainService": "K_A",
                 "api": {"url": "https://example.invalid/a"},
                 "parser": {"type": "balance", "fields": {"balance": "x"}}},
            ]}, f)
        self.mod, self._restore = _install_fake_secretstorage(
            _FakeCollection(locked=False))
        self.addCleanup(self._restore)
        self.mod.CACHE_ROOT = os.path.join(self.tmp.name, "cache")

    def test_unavailable_distinct_from_no_key(self):
        # dbus_init 抛错 → probe_keyring_state() == "unavailable"
        boom = types.ModuleType("secretstorage")
        boom.dbus_init = lambda: (_ for _ in ()).throw(RuntimeError("no dbus"))
        boom.get_default_collection = lambda bus: None
        sys.modules["secretstorage"] = boom
        # 强制 schema 校验通过（上游可能被并行改动），确保走到钥匙环状态判定
        with patch.object(self.mod.token_eye, "schema_validate", return_value=[]):
            self.assertEqual(self.mod.probe_keyring_state(), "unavailable")
            results, _config, _colors, _appearance = self.mod.collect(
                self.cfg_path, self.mod.RUNTIME_DIR)
        statuses = {r["status"] for r in results if r}
        self.assertNotIn("no_key", statuses, "服务不可用不能退化成「未配置 Key」")
        self.assertEqual(statuses, {"keyring_unavailable"})
        self.assertEqual(self.mod._last_keyring_state, "unavailable")
        # 未知状态按 warn(2) 处理，不能被当成 ok(0) 显示绿勾
        self.assertEqual(self.mod.worst_status(results), 2)


class TestLinuxCheckCookie(unittest.TestCase):
    """P0-1：Linux 版 check_cookie 对 HTTP 200 + 业务错误体必须判失败。

    刷新脚本用 unittest.mock 替换 subprocess.run，不发真实请求、不碰 D-Bus，
    也不在输出里写任何 Cookie 明文。
    """
    def setUp(self):
        # cryptography 在模块内延迟导入，无该库的环境也能加载
        self.m = _load_module("mimo_refresh_test", MIMO_REFRESH)

    def _check_with(self, stdout):
        fake = Mock()
        fake.stdout = stdout
        fake.stderr = ""
        fake.returncode = 0
        with patch.object(self.m.subprocess, "run", return_value=fake) as p:
            result = self.m.check_cookie("k=v")
        return result, p

    def test_http200_business_error_is_failure(self):
        biz = '{"code":401,"msg":"not login"}'
        (code, _body, valid), p = self._check_with(biz + "|HTTP:200")
        self.assertEqual(code, "200")
        self.assertFalse(valid, "HTTP 200 + 业务错误体必须判失败，避免假绿")
        self.assertIsNotNone(p.call_args.kwargs.get("timeout"),
                             "subprocess.run 必须带 timeout")
        self.assertFalse(self.m.balance_body_ok(biz))
        # P0-2：Cookie 只能走 curl --config - 的 stdin，绝不进 argv
        args, kwargs = p.call_args
        argv = args[0]
        self.assertIn("--config", argv)
        self.assertIn("-", argv)
        self.assertFalse(any(a == "-H" or a.startswith("Cookie:") for a in argv),
                         "curl argv 里不得出现 Cookie header")
        cfg = kwargs.get("input", "")
        self.assertIn('header = "Cookie:', cfg, "Cookie 应经 stdin config 传入")

    def test_http200_good_body_is_success(self):
        good = '{"code":0,"data":{"balance":12.5,"currency":"CNY"}}'
        (code, _body, valid), _p = self._check_with(good + "|HTTP:200")
        self.assertEqual(code, "200")
        self.assertTrue(valid)

    def test_non_200_is_failure(self):
        (_code, _body, valid), _p = self._check_with("unauthorized|HTTP:401")
        self.assertFalse(valid)


if __name__ == "__main__":
    unittest.main()
