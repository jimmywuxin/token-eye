#!/usr/bin/env python3
"""Token Eye — 单元测试（unittest，零第三方依赖）。

运行:
  /usr/bin/python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "swiftbar"))
import token_eye as te  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# 测试用颜色（键名与 load_colors 返回的 dict 一致）
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
    "display": {"nameColor": {"dark": "#FF375F", "light": "#B3154A"}},
}

MINIMAX_P = {
    "id": "minimax", "name": "MiniMax", "keychainService": "MINIMAX_CN_API_KEY",
    "api": {"url": "https://www.minimaxi.com/v1/token_plan/remains", "method": "GET",
            "authHeader": "Authorization", "authPrefix": "Bearer "},
    "parser": {
        "type": "plan_usage",
        "arrayPath": "model_remains",
        "fields": {
            "model": "model_name", "intervalPct": "current_interval_remaining_percent",
            "intervalStatus": "current_interval_status",
            "intervalTotal": "current_interval_total_count",
            "weeklyPct": "current_weekly_remaining_percent",
            "weeklyStatus": "current_weekly_status",
            "weeklyTotal": "current_weekly_total_count",
            "intervalBoost": "interval_boost_permille",
            "weeklyBoost": "weekly_boost_permille",
            "resetMs": "remains_time",
        },
        "modelLabels": {"general": "M2.7/M3 通用", "video": "视频"},
        "showModels": ["general", "video"],
        "statusMap": {"1": "可用", "2": "耗尽临近", "3": "耗尽"},
        "barLength": 20,
    },
    "display": {"nameColor": "#1D9E75"},
}


def ok_result(data):
    return {"ok": True, "status": 200, "data": data, "error_kind": None, "message": ""}


class TestResolveField(unittest.TestCase):
    def test_nested_dict(self):
        obj = {"balance_infos": [{"total_balance": 13.5}]}
        self.assertEqual(te.resolve_field(obj, "balance_infos.0.total_balance"), 13.5)

    def test_missing_key(self):
        self.assertIsNone(te.resolve_field({"a": 1}, "b.c"))

    def test_list_out_of_range(self):
        self.assertIsNone(te.resolve_field({"a": [1, 2]}, "a.5"))

    def test_non_numeric_index(self):
        self.assertIsNone(te.resolve_field({"a": [1]}, "a.x"))

    def test_none_obj(self):
        self.assertIsNone(te.resolve_field(None, "a.b"))

    def test_empty_path(self):
        self.assertIsNone(te.resolve_field({"a": 1}, ""))


class TestFormatMs(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(te.format_ms(0), "0m")

    def test_minutes_only(self):
        self.assertEqual(te.format_ms(61_000), "1m")

    def test_hours(self):
        self.assertEqual(te.format_ms(3_661_000), "1h1m")
        self.assertEqual(te.format_ms(5_400_000), "1h30m")


class TestSparkline(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(te.sparkline([]), "")

    def test_single(self):
        # 单点数据：lo == hi → span 兜底为 1.0，映射到最低档 ▁
        self.assertEqual(te.sparkline([5.0]), "▁")

    def test_flat(self):
        self.assertEqual(te.sparkline([5.0, 5.0, 5.0]), "▁▁▁")

    def test_rising(self):
        s = te.sparkline([0.0, 1.0])
        self.assertEqual(s, "▁█")

    def test_width_unused(self):
        # width 参数保留兼容（原实现按数据点数输出）
        self.assertEqual(len(te.sparkline([1.0, 2.0, 3.0])), 3)


class TestNameColor(unittest.TestCase):
    def test_string(self):
        d = {"nameColor": "#FF0000"}
        self.assertEqual(te.name_color(d, "dark", "#fff"), "#FF0000")
        self.assertEqual(te.name_color(d, "light", "#fff"), "#FF0000")

    def test_dict(self):
        d = {"nameColor": {"dark": "#111", "light": "#eee"}}
        self.assertEqual(te.name_color(d, "dark", "#fff"), "#111")
        self.assertEqual(te.name_color(d, "light", "#fff"), "#eee")

    def test_dict_missing_appearance(self):
        d = {"nameColor": {"dark": "#111"}}
        self.assertEqual(te.name_color(d, "light", "#fff"), "#111")

    def test_missing_falls_back(self):
        self.assertEqual(te.name_color({}, "dark", "#abc"), "#abc")


class TestParseBalance(unittest.TestCase):
    def test_cny(self):
        r = te.parse_provider(BALANCE_P, ok_result({
            "balance_infos": [{"total_balance": 13.5, "currency": "CNY"}]}), COLORS, "dark")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["menu_bar"], "¥13.5")
        self.assertEqual(r["balance_num"], 13.5)
        self.assertEqual(r["lines"], ["DeepSeek: ¥13.5", "可用"])

    def test_usd(self):
        r = te.parse_provider(BALANCE_P, ok_result({
            "balance_infos": [{"total_balance": 8.0, "currency": "USD"}]}), COLORS, "dark")
        self.assertEqual(r["menu_bar"], "$8.0")

    def test_missing_balance(self):
        r = te.parse_provider(BALANCE_P, ok_result({
            "balance_infos": [{"currency": "CNY"}]}), COLORS, "dark")
        self.assertEqual(r["menu_bar"], "¥?")
        self.assertIsNone(r["balance_num"])

    def test_not_available(self):
        r = te.parse_provider(BALANCE_P, ok_result({
            "balance_infos": [{"total_balance": 1.0, "currency": "CNY"}],
            "is_available": False}), COLORS, "dark")
        self.assertEqual(r["status"], "warn")
        self.assertIn("不可用", r["lines"][1])


class TestParseStatus(unittest.TestCase):
    def test_ok(self):
        p = {"id": "mimo", "name": "MiMo",
             "parser": {"type": "status", "okField": "object", "okValue": "list"},
             "display": {"label": "免费"}}
        r = te.parse_provider(p, ok_result({"object": "list"}), COLORS, "dark")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["menu_bar"], "免费")

    def test_fail(self):
        p = {"id": "mimo", "name": "MiMo",
             "parser": {"type": "status", "okField": "object", "okValue": "list"}}
        r = te.parse_provider(p, ok_result({"object": "other"}), COLORS, "dark")
        self.assertEqual(r["status"], "error")


class TestParsePlanUsage(unittest.TestCase):
    def sample_data(self):
        return {"model_remains": [
            {"model_name": "general",
             "current_interval_remaining_percent": 92, "current_interval_status": 1,
             "current_interval_total_count": 100,
             "current_weekly_remaining_percent": 100, "current_weekly_status": 1,
             "current_weekly_total_count": 1000,
             "interval_boost_permille": 2000, "weekly_boost_permille": 1000,
             "remains_time": 3600000},
            {"model_name": "video",
             "current_interval_remaining_percent": 40, "current_interval_status": 1,
             "current_interval_total_count": 50,
             "current_weekly_remaining_percent": 80, "current_weekly_status": 2,
             "current_weekly_total_count": 200,
             "interval_boost_permille": 1000, "weekly_boost_permille": 1000,
             "remains_time": 5400000},
        ]}

    def test_render(self):
        r = te.parse_provider(MINIMAX_P, ok_result(self.sample_data()), COLORS, "dark")
        self.assertEqual(r["status"], "ok")
        self.assertIn("✅ M2.7/M3 通用 92% 🔥x2.0", r["menu_bar"])
        self.assertEqual(r["min_pct"], 40)
        self.assertIn("M2.7/M3 通用: 5小时窗口 92%（可用）", r["lines"])
        self.assertIn("  周窗口 100%（可用）", r["lines"])
        self.assertIn("  重置: 1h0m", r["lines"])
        self.assertIn("  ██████████████████░░ 92%", r["lines"])

    def test_show_models_filter(self):
        data = {"model_remains": self.sample_data()["model_remains"] +
                [{"model_name": "speech-hd",
                  "current_interval_remaining_percent": 99,
                  "current_interval_status": 1,
                  "current_interval_total_count": 100,
                  "current_weekly_remaining_percent": 99, "current_weekly_status": 1,
                  "current_weekly_total_count": 100,
                  "interval_boost_permille": 1000, "weekly_boost_permille": 1000,
                  "remains_time": 1000}]}
        r = te.parse_provider(MINIMAX_P, ok_result(data), COLORS, "dark")
        self.assertNotIn("speech-hd", r["menu_bar"])

    def test_no_quota_label(self):
        data = {"model_remains": [{
            "model_name": "general",
            "current_interval_remaining_percent": 90, "current_interval_status": 3,
            "current_interval_total_count": 0,
            "current_weekly_remaining_percent": 100, "current_weekly_status": 3,
            "current_weekly_total_count": 0,
            "interval_boost_permille": 1000, "weekly_boost_permille": 1000,
            "remains_time": 3600000}]}
        r = te.parse_provider(MINIMAX_P, ok_result(data), COLORS, "dark")
        # total=0 → 显示「无套餐」而非「耗尽」（子串断言，行内含平台名前缀）
        lines = r["lines"]
        self.assertTrue(any("5小时窗口 90%（无套餐）" in line for line in lines))
        self.assertTrue(any("周窗口 100%（无套餐）" in line for line in lines))

    def test_warning_colors_below_threshold(self):
        data = {"model_remains": [{
            "model_name": "general",
            "current_interval_remaining_percent": 15, "current_interval_status": 2,
            "current_interval_total_count": 100,
            "current_weekly_remaining_percent": 90, "current_weekly_status": 1,
            "current_weekly_total_count": 100,
            "interval_boost_permille": 1000, "weekly_boost_permille": 1000,
            "remains_time": 3600000}]}
        r = te.parse_provider(MINIMAX_P, ok_result(data), COLORS, "dark")
        self.assertIn("⚠️", r["menu_bar"])
        self.assertEqual(r["colors"][-1], COLORS["WARN"])

    def test_empty(self):
        r = te.parse_provider(MINIMAX_P, ok_result({"model_remains": []}), COLORS, "dark")
        self.assertEqual(r["status"], "warn")
        self.assertEqual(r["menu_bar"], "无数据")


class TestRenderError(unittest.TestCase):
    def test_server_warn(self):
        r = te.render_error("x", "X", "server", "HTTP 500", None, COLORS)
        self.assertEqual(r["status"], "error")
        self.assertIn("服务端异常", r["lines"][0])
        self.assertEqual(r["colors"][0], COLORS["WARN"])

    def test_client_err(self):
        r = te.render_error("x", "X", "client", "401", None, COLORS)
        self.assertIn("配置/鉴权错误", r["lines"][0])
        self.assertEqual(r["colors"][0], COLORS["ERR"])

    def test_message_truncated(self):
        r = te.render_error("x", "X", "client", "a" * 200, None, COLORS)
        self.assertLessEqual(len(r["lines"][0]), 100)


class TestAlertCheck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def flag(self, pid):
        return os.path.join(self.dir, f"token-eye-alerted-{pid}.flag")

    def test_below_threshold_notifies_once(self):
        msg = te.alert_check("deepseek", "DeepSeek", 3.0, {"minBalance": 5.0}, self.dir)
        self.assertIn("DeepSeek 余额仅 3.00，低于阈值 5.0", msg)
        self.assertTrue(os.path.exists(self.flag("deepseek")))
        # 去重：第二次不再通知
        self.assertIsNone(te.alert_check("deepseek", "DeepSeek", 3.0, {"minBalance": 5.0}, self.dir))

    def test_above_threshold_clears_flag(self):
        te.alert_check("deepseek", "DeepSeek", 3.0, {"minBalance": 5.0}, self.dir)
        self.assertIsNone(te.alert_check("deepseek", "DeepSeek", 6.0, {"minBalance": 5.0}, self.dir))
        self.assertFalse(os.path.exists(self.flag("deepseek")))

    def test_no_alert_config(self):
        self.assertIsNone(te.alert_check("x", "X", 1.0, None, self.dir))

    def test_unparseable_value(self):
        self.assertIsNone(te.alert_check("x", "X", "abc", {"minBalance": 5.0}, self.dir))


class TestClassifyResponse(unittest.TestCase):
    def test_ok_json(self):
        r = te.classify_response('{"ok":true,"n":1}\n200', 0)
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], 200)
        self.assertEqual(r["data"], {"ok": True, "n": 1})

    def test_ok_empty_body(self):
        r = te.classify_response("\n200", 0)
        self.assertTrue(r["ok"])
        self.assertIsNone(r["data"])

    def test_server_error(self):
        r = te.classify_response('{"e":"boom"}\n503', 0)
        self.assertEqual(r["error_kind"], "server")
        self.assertEqual(r["message"], "服务端异常 HTTP 503")

    def test_client_error_message_extracted(self):
        r = te.classify_response('{"error":{"message":"Invalid API key"}}\n401', 0)
        self.assertEqual(r["error_kind"], "client")
        self.assertEqual(r["message"], "Invalid API key")

    def test_client_error_empty_body(self):
        r = te.classify_response("\n404", 0)
        self.assertEqual(r["error_kind"], "client")
        self.assertEqual(r["message"], "HTTP 404")

    def test_curl_nonzero(self):
        r = te.classify_response("", 7)
        self.assertEqual(r["error_kind"], "network")

    def test_parse_failure(self):
        r = te.classify_response("not json\n200", 0)
        self.assertEqual(r["error_kind"], "parse")


class TestFetchApi(unittest.TestCase):
    def test_timeout(self):
        with mock.patch.object(te.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(cmd=[], timeout=10)):
            r = te.fetch_api("http://x", "GET", "Authorization", "Bearer ", "k")
        self.assertEqual(r["error_kind"], "timeout")

    def test_network_error(self):
        with mock.patch.object(te.subprocess, "run", side_effect=OSError("boom")):
            r = te.fetch_api("http://x", "GET", "Authorization", "Bearer ", "k")
        self.assertEqual(r["error_kind"], "network")

    def test_happy_path(self):
        fake = mock.Mock(returncode=0, stdout='{"ok":true}\n200')
        with mock.patch.object(te.subprocess, "run", return_value=fake) as m:
            r = te.fetch_api("http://x", "GET", "Authorization", "Bearer ", "k",
                             extra_headers={"X-A": "1"})
        self.assertTrue(r["ok"])
        cmd = m.call_args.args[0]
        self.assertIn("-H", cmd)
        self.assertIn("Authorization: Bearer k", cmd)
        self.assertIn("X-A: 1", cmd)


class TestSchemaValidate(unittest.TestCase):
    def test_valid(self):
        cfg = {"providers": [{"id": "a", "name": "A", "keychainService": "A_KEY",
                              "api": {"url": "https://x"}, "parser": {"type": "balance"}}]}
        self.assertEqual(te.schema_validate(cfg), [])

    def test_missing_required_fields(self):
        cfg = {"providers": [{"id": "a"}]}
        errors = te.schema_validate(cfg)
        self.assertTrue(any("缺字段 name" in e for e in errors))
        self.assertTrue(any("缺字段 keychainService" in e for e in errors))

    def test_missing_api_url(self):
        cfg = {"providers": [{"id": "a", "name": "A", "keychainService": "K",
                              "api": {}, "parser": {"type": "balance"}}]}
        self.assertTrue(any("api 缺字段 url" in e for e in te.schema_validate(cfg)))

    def test_invalid_parser_type(self):
        cfg = {"providers": [{"id": "a", "name": "A", "keychainService": "K",
                              "api": {"url": "https://x"}, "parser": {"type": "nope"}}]}
        self.assertTrue(any("parser.type 无效" in e for e in te.schema_validate(cfg)))

    def test_non_dict_provider(self):
        cfg = {"providers": ["oops"]}
        self.assertTrue(any("不是对象" in e for e in te.schema_validate(cfg)))


class TestLoadColors(unittest.TestCase):
    def tearDown(self):
        for k in ["APPEARANCE", "C_DEFAULT", "C_OK", "C_WARN", "C_ERR",
                  "C_HEADER", "C_MUTED", "C_SECONDARY"]:
            os.environ.pop(k, None)

    def test_env_override(self):
        os.environ["APPEARANCE"] = "light"
        os.environ["C_OK"] = "#123456"
        appearance, colors = te.load_colors({"colors": {}})
        self.assertEqual(appearance, "light")
        self.assertEqual(colors["OK"], "#123456")

    def test_config_override(self):
        os.environ["APPEARANCE"] = "dark"
        cfg = {"colors": {"dark": {"ok": "#abcdef", "default": "#111111"}}}
        _, colors = te.load_colors(cfg)
        self.assertEqual(colors["OK"], "#abcdef")
        self.assertEqual(colors["DEFAULT"], "#111111")
        # 未覆盖的用 env fallback（C_WARN 未设置 → 默认 #f39c12）
        self.assertEqual(colors["WARN"], "#f39c12")

    def test_defaults(self):
        appearance, colors = te.load_colors({})
        self.assertEqual(appearance, "dark")
        self.assertEqual(colors["DEFAULT"], "#ffffff")


class TestCacheAndHistory(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_cache_roundtrip(self):
        te.save_cache(self.dir, "deepseek", {"ts": 1, "data": {"x": 1}})
        self.assertEqual(te.load_cache(self.dir, "deepseek"), {"ts": 1, "data": {"x": 1}})
        self.assertIsNone(te.load_cache(self.dir, "nope"))

    def test_history_roundtrip(self):
        te.append_history(self.dir, "deepseek", 13.5)
        te.append_history(self.dir, "deepseek", 12.5)
        hist = te.load_history(self.dir, "deepseek", 24)
        self.assertEqual([v for _, v in hist], [13.5, 12.5])

    def test_history_limit(self):
        for i in range(30):
            te.append_history(self.dir, "deepseek", float(i))
        hist = te.load_history(self.dir, "deepseek", 24)
        self.assertEqual(len(hist), 24)
        self.assertEqual(hist[-1][1], 29.0)


class TestDailySpend(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.day0 = te.start_of_day()

    def write(self, pid, pairs):
        with open(os.path.join(self.dir, f"history-{pid}.jsonl"), "w") as f:
            for ts, v in pairs:
                f.write(f"{ts},{v}\n")

    def test_start_of_day_is_local_midnight(self):
        t = time.localtime(te.start_of_day())
        self.assertEqual((t.tm_hour, t.tm_min, t.tm_sec), (0, 0, 0))

    def test_empty(self):
        self.assertEqual(te.daily_spend(self.dir, "x"), (0.0, 0))

    def test_one_point(self):
        self.write("x", [(self.day0 + 100, 50.0)])
        self.assertEqual(te.daily_spend(self.dir, "x"), (0.0, 1))

    def test_decreasing(self):
        self.write("x", [(self.day0 + 100, 50.0), (self.day0 + 200, 48.0),
                         (self.day0 + 300, 30.0)])
        self.assertEqual(te.daily_spend(self.dir, "x"), (20.0, 3))

    def test_topup_ignored(self):
        # 50→48 消耗 2，充值回 55，55→53 再消耗 2 → 总消耗 4（充值不干扰）
        self.write("x", [(self.day0 + 100, 50.0), (self.day0 + 200, 48.0),
                         (self.day0 + 300, 55.0), (self.day0 + 400, 53.0)])
        self.assertEqual(te.daily_spend(self.dir, "x"), (4.0, 4))

    def test_yesterday_excluded(self):
        # 昨天的下降不计入；今天只剩一个点 → 数据不足
        self.write("x", [(self.day0 - 600, 10.0), (self.day0 - 300, 5.0),
                         (self.day0 + 100, 5.0)])
        self.assertEqual(te.daily_spend(self.dir, "x"), (0.0, 1))

    def test_noise_ignored(self):
        self.write("x", [(self.day0 + 100, 50.0), (self.day0 + 200, 49.999),
                         (self.day0 + 300, 50.0)])
        self.assertEqual(te.daily_spend(self.dir, "x"), (0.0, 3))


class TestVersion(unittest.TestCase):
    def test_ver_gt(self):
        self.assertTrue(te._ver_gt("0.10.0", "0.9.0"))
        self.assertTrue(te._ver_gt("v0.9.1", "v0.9.0"))
        self.assertFalse(te._ver_gt("0.9.0", "0.9.1"))
        self.assertFalse(te._ver_gt("0.9.0", "v0.9.0"))

    def test_check_latest_version_cached(self):
        d = tempfile.mkdtemp()
        fake = mock.Mock(stdout='{"tag_name":"v0.10.0"}')
        with mock.patch.object(te.subprocess, "run", return_value=fake) as m:
            self.assertEqual(te.check_latest_version(d), "v0.10.0")
            self.assertEqual(te.check_latest_version(d), "v0.10.0")
            m.assert_called_once()  # 第二次走 24h 缓存，不再请求网络

    def test_check_latest_version_network_fail(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(te.subprocess, "run", side_effect=OSError("no net")):
            self.assertEqual(te.check_latest_version(d), "")


class TestProcessProvider(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def cache(self, pid, payload):
        with open(os.path.join(self.dir, f"token-eye-cache-{pid}.json"), "w") as f:
            json.dump(payload, f)

    def test_cache_hit_skips_keychain(self):
        self.cache("deepseek", {"ts": int(time.time()),
                                "data": {"balance_infos": [{"total_balance": 8.41, "currency": "CNY"}]}})
        p = dict(BALANCE_P, consoleUrl="https://c")
        r = te.process_provider(p, {"cache": {"balance": 300}}, COLORS, "dark",
                                self.dir, self.dir, "/tmp")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["menu_bar"], "¥8.41")

    def test_cache_error_hit(self):
        self.cache("deepseek", {"ts": int(time.time()), "data": None,
                                "error": "client", "message": "401 bad"})
        r = te.process_provider(BALANCE_P, {"cache": {"balance": 300}}, COLORS, "dark",
                                self.dir, self.dir, "/tmp")
        self.assertEqual(r["status"], "error")
        self.assertIn("配置/鉴权错误", r["lines"][0])

    def test_no_key(self):
        p = dict(BALANCE_P, keychainService="TOKEN_EYE_TEST_NO_SUCH_KEY")
        r = te.process_provider(p, {"cache": {"balance": 300}}, COLORS, "dark",
                                self.dir, self.dir, "/tmp")
        self.assertEqual(r["status"], "no_key")

    def test_plan_usage_notify_and_dedup(self):
        # 缓存命中 pct=10 < minPct=20 → 触发告警（osascript 不存在时静默失败）
        self.cache("minimax", {"ts": int(time.time()), "data": {"model_remains": [
            {"model_name": "general",
             "current_interval_remaining_percent": 10, "current_interval_status": 2,
             "current_interval_total_count": 100,
             "current_weekly_remaining_percent": 90, "current_weekly_status": 1,
             "current_weekly_total_count": 100,
             "interval_boost_permille": 1000, "weekly_boost_permille": 1000,
             "remains_time": 3600000}]}})
        p = dict(MINIMAX_P, alert={"minPct": 20})
        cfg = {"cache": {"plan_usage": 30}, "alerts": {}}
        r = te.process_provider(p, cfg, COLORS, "dark", self.dir, self.dir, "/tmp")
        self.assertEqual(r["status"], "ok")
        flag = os.path.join(self.dir, "token-eye-alerted-minimax.flag")
        self.assertTrue(os.path.exists(flag))
        # 第二次调用：告警已标记，不再重复通知（也不抛异常）
        r2 = te.process_provider(p, cfg, COLORS, "dark", self.dir, self.dir, "/tmp")
        self.assertEqual(r2["status"], "ok")

    def test_balance_daily_spend_line(self):
        """余额类：当日有下降快照 → 详情菜单出现「今日消耗」。"""
        day0 = te.start_of_day()
        with open(os.path.join(self.dir, "history-deepseek.jsonl"), "w") as f:
            f.write(f"{day0 + 100},{50.0}\n")
            f.write(f"{day0 + 200},{48.0}\n")
        self.cache("deepseek", {"ts": int(time.time()),
                                "data": {"balance_infos": [{"total_balance": 48.0, "currency": "CNY"}]}})
        r = te.process_provider(BALANCE_P, {"cache": {"balance": 300}}, COLORS, "dark",
                                self.dir, self.dir, "/tmp")
        self.assertEqual(r["status"], "ok")
        self.assertTrue(any("今日消耗: ¥2.00" in line for line in r["lines"]),
                        f"缺今日消耗行: {r['lines']}")

    def test_plan_usage_trend_line(self):
        """用量类：剩余百分比历史 → 详情菜单出现趋势线。"""
        day0 = te.start_of_day()
        with open(os.path.join(self.dir, "history-minimax.jsonl"), "w") as f:
            f.write(f"{day0 + 100},{80.0}\n")
        self.cache("minimax", {"ts": int(time.time()), "data": {"model_remains": [
            {"model_name": "general",
             "current_interval_remaining_percent": 90, "current_interval_status": 1,
             "current_interval_total_count": 100,
             "current_weekly_remaining_percent": 90, "current_weekly_status": 1,
             "current_weekly_total_count": 100,
             "interval_boost_permille": 1000, "weekly_boost_permille": 1000,
             "remains_time": 3600000}]}})
        r = te.process_provider(MINIMAX_P, {"cache": {"plan_usage": 30}}, COLORS, "dark",
                                self.dir, self.dir, "/tmp")
        self.assertEqual(r["status"], "ok")
        self.assertTrue(any("趋势" in line and "(+10%)" in line for line in r["lines"]),
                        f"缺趋势行: {r['lines']}")

    def test_auto_refresh_recovers_from_401(self):
        """401 自愈：client 错误 + refreshParam → 自动跑刷新脚本 → 重试成功，无需手动干预。"""
        d = tempfile.mkdtemp()
        p = dict(BALANCE_P, refreshParam="refresh-mimo-cookie")
        cfg = {"cache": {"balance": 300}}
        fetch_results = [
            {"ok": False, "status": 401, "data": None,
             "error_kind": "client", "message": "401"},
            {"ok": True, "status": 200,
             "data": {"balance_infos": [{"total_balance": 5.0, "currency": "CNY"}]},
             "error_kind": None, "message": ""},
        ]
        with mock.patch.object(te, "get_key", return_value="thekey"), \
             mock.patch.object(te, "fetch_api", side_effect=fetch_results) as m_fetch, \
             mock.patch.object(te, "auto_refresh_cookie", return_value=(True, "")) as m_refresh, \
             mock.patch.object(te, "send_notify"):
            r = te.process_provider(p, cfg, COLORS, "dark", d, d, REPO_ROOT)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["menu_bar"], "¥5.0")
        m_refresh.assert_called_once()
        self.assertEqual(m_fetch.call_count, 2)  # 刷新后重试了一次

    def test_auto_refresh_failed_falls_back_to_error(self):
        """自愈失败（刷新脚本失败）→ 回退为错误渲染（菜单显示手动刷新入口）。"""
        d = tempfile.mkdtemp()
        p = dict(BALANCE_P, refreshParam="refresh-mimo-cookie")
        cfg = {"cache": {"balance": 300}}
        with mock.patch.object(te, "get_key", return_value="thekey"), \
             mock.patch.object(te, "fetch_api", return_value={
                 "ok": False, "status": 401, "data": None,
                 "error_kind": "client", "message": "401"}), \
             mock.patch.object(te, "auto_refresh_cookie", return_value=(False, "防抖中")):
            r = te.process_provider(p, cfg, COLORS, "dark", d, d, REPO_ROOT)
        self.assertEqual(r["status"], "error")
        self.assertIn("配置/鉴权错误", r["lines"][0])

    def test_auto_refresh_debounce_flag(self):
        # 401 自愈的防抖 flag 应写入 cache_dir
        self.cache("mimo", {"ts": int(time.time()), "data": None,
                            "error": "client", "message": "401"})
        # 让缓存过期：把 ts 改成很久以前，强制走 API 分支
        self.cache("mimo", {"ts": 0, "data": None, "error": "client", "message": "401"})
        p = {"id": "mimo", "name": "MiMo", "keychainService": "TOKEN_EYE_TEST_NO_SUCH_KEY",
             "refreshParam": "refresh-mimo-cookie",
             "api": {"url": "https://platform.xiaomimimo.com/api/v1/balance", "method": "GET",
                     "authHeader": "Cookie", "authPrefix": ""},
             "parser": {"type": "status", "okField": "object", "okValue": "list"}}
        r = te.process_provider(p, {"cache": {"status": 60}}, COLORS, "dark",
                                self.dir, self.dir, self.dir)
        # key 不存在 → no_key（不会走到自愈），此处只验证不抛异常
        self.assertEqual(r["status"], "no_key")


class TestValidateMode(unittest.TestCase):
    def test_real_config_passes(self):
        config_path = os.path.join(REPO_ROOT, "providers.json")
        self.assertTrue(os.path.exists(config_path))
        with mock.patch.dict(os.environ, {"CONFIG_FILE": config_path}):
            rc = te.validate_mode()
        self.assertEqual(rc, 0)

    def test_bad_config_fails(self):
        d = tempfile.mkdtemp()
        bad = os.path.join(d, "bad.json")
        with open(bad, "w") as f:
            json.dump({"providers": [{"id": "x"}]}, f)
        with mock.patch.dict(os.environ, {"CONFIG_FILE": bad}):
            rc = te.validate_mode()
        self.assertEqual(rc, 1)

    def test_invalid_json(self):
        d = tempfile.mkdtemp()
        bad = os.path.join(d, "bad.json")
        with open(bad, "w") as f:
            f.write("{not json")
        with mock.patch.dict(os.environ, {"CONFIG_FILE": bad}):
            rc = te.validate_mode()
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
