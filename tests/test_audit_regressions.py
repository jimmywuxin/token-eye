#!/usr/bin/env python3
"""审查回归测试：2026-11-10 全项目审计中 P0 问题的护栏。

覆盖：假绿闭环（字段缺失 / 业务错误码 / 缓存重校验）、凭证不入 argv、
缓存 0600 原子写、菜单文本净化、curl 错误分类、配置脏值、版本检查异步。
这些用例与 Android 侧的 ParserTest / EnvelopeTest 是同一份跨端口径契约的
Python 侧实现（Mac/Linux 共用 token_eye.py）。
"""
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "swiftbar"))
sys.path.insert(0, REPO_ROOT)
import token_eye as te  # noqa: E402

COLORS = {
    "DEFAULT": "#000000", "SECONDARY": "#666666", "MUTED": "#888888",
    "HEADER": "#0000ff", "OK": "#0072B2", "WARN": "#B86E00", "ERR": "#8E1A4A",
}

BALANCE_P = {
    "id": "deepseek", "name": "DeepSeek", "keychainService": "DEEPSEEK_API_KEY",
    "api": {"url": "https://api.deepseek.com/user/balance", "method": "GET",
            "authHeader": "Authorization", "authPrefix": "Bearer "},
    "parser": {"type": "balance", "fields": {
        "balance": "balance_infos.0.total_balance",
        "currency": "balance_infos.0.currency"}},
}


def ok_result(data):
    return {"ok": True, "status": 200, "data": data, "error_kind": None, "message": ""}


class TestFakeGreenClosed(unittest.TestCase):
    """P0-1：任何「拿不到余额」的路径都不能是绿色成功态。"""

    def test_missing_balance_is_error(self):
        r = te.parse_provider(BALANCE_P, ok_result({"balance_infos": [{"currency": "CNY"}]}),
                              COLORS, "dark")
        self.assertEqual(r["status"], "error")
        self.assertEqual(r["menu_bar"], "")
        self.assertIn("余额字段缺失", r["lines"][0])

    def test_unparsable_balance_is_error(self):
        r = te.parse_provider(BALANCE_P, ok_result({
            "balance_infos": [{"total_balance": "N/A"}]}), COLORS, "dark")
        self.assertEqual(r["status"], "error")

    def test_default_business_code_check_catches_401(self):
        # 未配 api.envelope 的平台（DeepSeek/MiniMax/MiMo/千问）也要挡住
        # HTTP 200 + {"code":401,...}，不能只靠智谱那一份 envelope 配置。
        r = te.default_business_code_check(ok_result({"code": 401, "msg": "令牌已过期"}))
        self.assertFalse(r["ok"])
        self.assertEqual(r["error_kind"], "client")
        self.assertIn("令牌已过期", r["message"])

    def test_default_business_code_check_ignores_normal_response(self):
        data = {"balance_infos": [{"total_balance": 13.5, "currency": "CNY"}]}
        result = ok_result(data)
        self.assertIs(te.default_business_code_check(result), result)
        self.assertTrue(te.default_business_code_check(ok_result(data))["ok"])
        for code in (0, 200, "0", "200", "ok", "SUCCESS"):
            self.assertTrue(te.default_business_code_check(ok_result({"code": code}))["ok"],
                            f"成功码 {code!r} 被误判")

    def test_fetch_with_envelope_applies_default_check(self):
        api = {"url": "https://x", "method": "GET", "authHeader": "Authorization",
               "authPrefix": ""}
        with mock.patch.object(te, "fetch_api",
                               return_value=ok_result({"code": 401, "msg": "bad"})):
            r = te.fetch_with_envelope(api, "k")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error_kind"], "client")

    def test_cached_error_body_is_revalidated(self):
        """旧版把业务错误体当成功写进缓存 → 命中缓存后重跑校验，且不假绿。"""
        d = tempfile.mkdtemp()
        te.save_cache(d, "deepseek", {"ts": int(time.time()),
                                      "data": {"code": 401, "msg": "令牌已过期"}})
        with mock.patch.object(te, "get_key", return_value="k"), \
             mock.patch.object(te, "fetch_api") as m_fetch, \
             mock.patch.dict(os.environ, {"TOKEN_EYE_NOTIFY": "0"}):
            r = te.process_provider(BALANCE_P, {"cache": {"balance": 300}},
                                    COLORS, "dark", d, d, d)
            m_fetch.assert_not_called()  # 命中缓存，未重复打 API
        self.assertEqual(r["status"], "error")
        self.assertIn("令牌已过期", r["lines"][0])

    def test_missing_balance_does_not_leave_success_cache(self):
        d = tempfile.mkdtemp()
        good_but_no_balance = ok_result({"balance_infos": [{"currency": "CNY"}]})
        with mock.patch.object(te, "get_key", return_value="k"), \
             mock.patch.object(te, "fetch_api", return_value=good_but_no_balance), \
             mock.patch.dict(os.environ, {"TOKEN_EYE_NOTIFY": "0"}):
            r = te.process_provider(BALANCE_P, {"cache": {"balance": 300}},
                                    COLORS, "dark", d, d, d)
        self.assertEqual(r["status"], "error")
        self.assertFalse(os.path.exists(te.cache_path(d, "deepseek")))


class TestCredentialAndCacheSafety(unittest.TestCase):
    """P0-2：凭证不进 argv；缓存限权、原子写、脏值当作 miss。"""

    def test_key_not_in_argv(self):
        fake = mock.Mock(returncode=0, stdout='{"ok":true}\n200')
        with mock.patch.object(te.subprocess, "run", return_value=fake) as m:
            te.fetch_api("https://x", "GET", "Authorization", "Bearer ", "SECRET-KEY")
        argv = " ".join(m.call_args.args[0])
        self.assertNotIn("SECRET-KEY", argv)
        self.assertIn("SECRET-KEY", m.call_args.kwargs["input"])

    def test_cache_is_0600_and_atomic(self):
        d = tempfile.mkdtemp()
        te.save_cache(d, "deepseek", {"ts": int(time.time()), "data": {"a": 1}})
        path = te.cache_path(d, "deepseek")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(te.load_cache(d, "deepseek")["data"], {"a": 1})
        # 目录里不能残留 .tmp
        self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(d)))

    def test_dirty_cache_is_miss(self):
        d = tempfile.mkdtemp()
        with open(te.cache_path(d, "deepseek"), "w", encoding="utf-8") as f:
            json.dump({"ts": "oops", "data": {"a": 1}}, f)
        self.assertIsNone(te.load_cache(d, "deepseek"))
        with open(te.cache_path(d, "deepseek"), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(te.load_cache(d, "deepseek"))


class TestRenderHardening(unittest.TestCase):
    """P0-2 / P0-9：菜单注入、curl 分类、配置脏值、AppleScript 转义。"""

    def test_menu_text_cannot_inject_params(self):
        r = {"id": "x", "name": "evil|bash=evil.com", "status": "error",
             "lines": ["line1|href=evil.com\nline2"], "colors": [COLORS["ERR"]],
             "menu_bar": "", "console_url": "javascript:alert(1)"}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            te.render([r], {"menuBar": {}}, COLORS, {}, tempfile.mkdtemp())
        out = buf.getvalue()
        # `|` 被中和成 ¦，SwiftBar 不会再把它当参数分隔符
        self.assertIn("evil¦bash=evil.com", out)
        self.assertIn("line1¦href=evil.com", out)
        self.assertNotIn("evil|bash=evil.com", out)
        self.assertNotIn("line1|href=evil.com", out)
        self.assertNotIn("javascript:alert(1)", out)
        self.assertNotIn("\nline2", out)

    def test_curl_timeout_classified(self):
        self.assertEqual(te.classify_response("", 28)["error_kind"], "timeout")
        self.assertEqual(te.classify_response("", 6)["error_kind"], "network")
        self.assertEqual(te.classify_response("", 7)["error_kind"], "network")

    def test_schema_validate_never_raises_on_dirty_config(self):
        errors = te.schema_validate({"providers": [
            {"id": "x", "parser": "oops", "api": "oops"},
            {"id": "y", "name": "Y", "keychainService": "K",
             "api": {"url": "https://x"},
             "parser": {"type": "command", "command": "cli", "timeout": "oops",
                        "recovery": "../../etc/passwd"}},
        ]})
        self.assertIsInstance(errors, list)
        self.assertTrue(any("timeout" in e for e in errors))
        self.assertTrue(any("recovery" in e for e in errors))

    def test_applescript_literal_escaping(self):
        out = te._as_applescript_literal('a"b\\c\nd')
        self.assertNotIn("\n", out)
        self.assertIn('\\"', out)
        self.assertIn("\\\\", out)

    def test_render_lock_blocks_second_instance(self):
        d = tempfile.mkdtemp()
        first = te.acquire_render_lock(d)
        self.assertTrue(first)
        try:
            self.assertIs(te.acquire_render_lock(d), False)  # 上一轮未结束 → 不再堆进程
        finally:
            first.close()

    def test_render_lock_can_be_skipped_for_tests(self):
        d = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"TOKEN_EYE_NO_LOCK": "1"}):
            self.assertIsNone(te.acquire_render_lock(d))
        self.assertTrue(te.acquire_render_lock(d, force=True) is None)


class TestPeakWindowTimezone(unittest.TestCase):
    """P29：classify() 契约要求 aware datetime，非北京时间系统不能错位。"""

    def test_aware_datetime_is_converted_to_config_tz(self):
        import datetime
        from parsers import peak_window
        # 2026-11-10 是周二；PST 01:00 = Asia/Shanghai 17:00，落在 14-18 高峰段
        pst = datetime.timezone(datetime.timedelta(hours=-8))
        now = datetime.datetime(2026, 11, 10, 1, 0, tzinfo=pst)
        cfg = {"tz": "Asia/Shanghai", "hours": [[9, 12], [14, 18]],
               "weekdays": [1, 2, 3, 4, 5], "holidays": False}
        info = peak_window.classify(now, cfg)
        self.assertEqual(info["tz"], "Asia/Shanghai")
        self.assertTrue(info["is_peak"], "aware 输入应换算到 17:00 判为高峰")

    def test_parse_provider_passes_aware_now(self):
        """渲染路径不能再传 naive now（旧实现会被重新解释成目标时区钟点）。"""
        import inspect
        src = inspect.getsource(te.parse_provider)
        self.assertIn("_dt.now().astimezone()", src)


class TestMiMoCookieValidation(unittest.TestCase):
    """P0-1：Mac/Linux 刷新脚本对「HTTP 200 + 业务错误体」必须同口径判失败。

    Linux 版已把 cryptography 改为延迟导入，可在无 D-Bus / 无 crypto 的 CI 里
    直接 import 纯函数；Mac 版同口径由源码审阅 + 本机系统 Python 验证保证。
    """

    @classmethod
    def setUpClass(cls):
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "linux", "scripts", "refresh-mimo-cookie.py")
        spec = importlib.util.spec_from_file_location("linux_refresh_mimo", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls.mod = mod

    def test_good_body(self):
        self.assertTrue(self.mod.balance_body_ok(
            '{"code":0,"data":{"balance":9.9,"currency":"CNY"}}'))

    def test_all_business_error_keys_rejected(self):
        for key in ("code", "errcode", "error_code", "retcode"):
            with self.subTest(key=key):
                self.assertFalse(self.mod.balance_body_ok(
                    '{"%s":401,"data":{"balance":9.9}}' % key))

    def test_missing_balance_field_rejected(self):
        self.assertFalse(self.mod.balance_body_ok(
            '{"code":0,"data":{"currency":"CNY"}}'))
        self.assertFalse(self.mod.balance_body_ok('{"code":0,"data":{}}'))

    def test_success_codes_allowed(self):
        for code in ("0", 0, 200, "200", "ok", "SUCCESS", "true", "none", "null"):
            with self.subTest(code=code):
                body = json.dumps({"code": code, "data": {"balance": 1.0}})
                self.assertTrue(self.mod.balance_body_ok(body))

    def test_explicit_success_false_rejected(self):
        self.assertFalse(self.mod.balance_body_ok(
            '{"code":0,"success":false,"data":{"balance":1.0}}'))


if __name__ == "__main__":
    unittest.main()
