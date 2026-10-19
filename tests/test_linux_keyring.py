#!/usr/bin/env python3
"""Linux 托盘钥匙环路径单测（B1 语义修正 / B2-b 只读不解锁 / B4 重入锁）。

不依赖真机 D-Bus：注入假 secretstorage 模块模拟「解锁/锁定/取消」三态。
托盘模块会 monkey-patch 共享的 token_eye（get_key/send_notify/_open_login_page/
fetch_api）并可能污染 sys.modules["secretstorage"]——每个测试结束必须恢复，
否则殃及 test_token_eye（v0.23.11 开发期间实测踩过）。

运行:
  /usr/bin/python3 -m unittest discover -s tests -v
"""
import importlib.util
import os
import sys
import threading
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")
TRAY = os.path.join(REPO, "linux", "token-eye-tray.py")

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


if __name__ == "__main__":
    unittest.main()
