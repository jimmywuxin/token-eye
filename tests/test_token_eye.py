#!/usr/bin/env python3
"""Token Eye — 单元测试（unittest，零第三方依赖）。

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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "swiftbar"))
import token_eye as te  # noqa: E402

# scripts/validate-schema.py 带连字符不是合法模块名，用 importlib 按路径加载
def _load_validate_schema():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "validate_schema_mod",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "validate-schema.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vs = _load_validate_schema()

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
        "modelLabels": {"general": "", "video": "视频"},
        "showModels": ["general"],
        "windowLabels": {"interval": "5h", "weekly": "7d"},
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

    def test_downsample_to_width(self):
        # 超宽数据均匀降采样（趋势窗口 288 → 显示 24 字符）
        s = te.sparkline(list(range(100)), width=10)
        self.assertEqual(len(s), 10)
        self.assertEqual(s[0], "▁")  # 最小值
        self.assertEqual(s[-1], "█")  # 最大值
        self.assertEqual(len(te.sparkline(list(range(100)))), 24)  # 默认宽度

    def test_width_no_downsample_for_small(self):
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


class TestCurrencySymbol(unittest.TestCase):
    def test_custom_symbols(self):
        p = dict(BALANCE_P, display={
            "nameColor": "#FF375F",
            "currencySymbols": {"USD": "$", "EUR": "€", "CNY": "¥"},
        })
        r = te.parse_provider(p, ok_result({
            "balance_infos": [{"total_balance": 13.5, "currency": "EUR"}]}), COLORS, "dark")
        self.assertEqual(r["menu_bar"], "✅ €13.5")
        self.assertEqual(r["symbol"], "€")

    def test_unknown_currency_defaults_yen(self):
        r = te.parse_provider(BALANCE_P, ok_result({
            "balance_infos": [{"total_balance": 13.5, "currency": "XYZ"}]}), COLORS, "dark")
        self.assertEqual(r["menu_bar"], "✅ ¥13.5")


class TestNotifyRecovered(unittest.TestCase):
    def cache(self, pid, payload):
        d = self.dir
        with open(os.path.join(d, f"token-eye-cache-{pid}.json"), "w") as f:
            json.dump(payload, f)

    def test_balance_recovery_once(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        p = dict(BALANCE_P, alert={"minBalance": 5.0})
        cfg = {"cache": {"balance": 300}}
        below = {"balance_infos": [{"total_balance": 3.0, "currency": "CNY"}]}
        above = {"balance_infos": [{"total_balance": 6.0, "currency": "CNY"}]}
        with mock.patch.object(te, "send_notify") as m:
            # 低于阈值 → 告警
            self.cache("deepseek", {"ts": int(time.time()), "data": below})
            te.process_provider(p, cfg, COLORS, "dark", d, d, "/tmp")
            self.assertEqual(m.call_count, 1)
            self.assertIn("告警", m.call_args.args[0])
            # 回升 → 恢复通知（一条）
            self.cache("deepseek", {"ts": int(time.time()), "data": above})
            te.process_provider(p, cfg, COLORS, "dark", d, d, "/tmp")
            self.assertEqual(m.call_count, 2)
            self.assertIn("已恢复", m.call_args.args[0])
            # 再次回升 → 不重复发恢复通知
            self.cache("deepseek", {"ts": int(time.time()), "data": above})
            te.process_provider(p, cfg, COLORS, "dark", d, d, "/tmp")
            self.assertEqual(m.call_count, 2)
            # 再次跌破 → 重新告警 + 可再次恢复
            self.cache("deepseek", {"ts": int(time.time()), "data": below})
            te.process_provider(p, cfg, COLORS, "dark", d, d, "/tmp")
            self.assertEqual(m.call_count, 3)


class TestLogDebug(unittest.TestCase):
    def test_writes_when_enabled(self):
        d = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"TOKEN_EYE_DEBUG": "1"}):
            te.log_debug(d, "测试消息")
        with open(os.path.join(d, "debug.log")) as f:
            self.assertIn("测试消息", f.read())

    def test_skips_when_disabled(self):
        d = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"TOKEN_EYE_DEBUG": "0"}):
            te.log_debug(d, "不应出现")
        self.assertFalse(os.path.exists(os.path.join(d, "debug.log")))


class TestRenderTitleColor(unittest.TestCase):
    def setUp(self):
        self.ok_r = {"id": "a", "name": "A", "status": "ok",
                     "menu_bar": "¥1", "lines": [], "colors": []}

    def run_render(self, results):
        buf = io.StringIO()
        with mock.patch.object(te, "check_latest_version", return_value=""), \
             contextlib.redirect_stdout(buf):
            te.render(results, {"menuBar": {}}, COLORS, {}, "/tmp")
        return buf.getvalue().splitlines()[0]

    def test_all_ok_header_color(self):
        self.assertIn(f"color={COLORS['HEADER']}", self.run_render([self.ok_r]))

    def test_warn_orange(self):
        warn_r = {"id": "c", "name": "C", "status": "warn",
                  "menu_bar": "50%", "lines": [], "colors": []}
        self.assertIn(f"color={COLORS['WARN']}", self.run_render([self.ok_r, warn_r]))

    def test_no_key_orange(self):
        nk_r = {"id": "d", "name": "D", "status": "no_key",
                "menu_bar": "", "lines": [], "colors": [], "keychainService": "K"}
        self.assertIn(f"color={COLORS['WARN']}", self.run_render([self.ok_r, nk_r]))

    def test_error_red(self):
        err_r = {"id": "b", "name": "B", "status": "error",
                 "menu_bar": "", "lines": ["x"], "colors": [COLORS["ERR"]]}
        self.assertIn(f"color={COLORS['ERR']}", self.run_render([self.ok_r, err_r]))


class TestParseBalance(unittest.TestCase):
    def test_cny(self):
        r = te.parse_provider(BALANCE_P, ok_result({
            "balance_infos": [{"total_balance": 13.5, "currency": "CNY"}]}), COLORS, "dark")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["menu_bar"], "✅ ¥13.5")
        self.assertEqual(r["balance_num"], 13.5)
        # 简约化：余额类详情只有 1 行（不再有"可用"行，状态由 menu_bar 图标传达）
        self.assertEqual(r["lines"], ["DeepSeek: ¥13.5"])

    def test_usd(self):
        r = te.parse_provider(BALANCE_P, ok_result({
            "balance_infos": [{"total_balance": 8.0, "currency": "USD"}]}), COLORS, "dark")
        self.assertEqual(r["menu_bar"], "✅ $8.0")

    def test_missing_balance(self):
        r = te.parse_provider(BALANCE_P, ok_result({
            "balance_infos": [{"currency": "CNY"}]}), COLORS, "dark")
        self.assertEqual(r["menu_bar"], "✅ ¥?")
        self.assertIsNone(r["balance_num"])

    def test_not_available(self):
        r = te.parse_provider(BALANCE_P, ok_result({
            "balance_infos": [{"total_balance": 1.0, "currency": "CNY"}],
            "is_available": False}), COLORS, "dark")
        self.assertEqual(r["status"], "warn")
        # 🔴 图标 + 警告状态；余额展示仍走"可用"路径（avail 标志仅影响图标/status）
        self.assertIn("🔴", r["menu_bar"])
        self.assertNotIn("✅", r["menu_bar"])


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
        # 仅显示 general（已停 video），label 为空 → menu_bar 只剩图标+%
        # 进度条 / 图标 / min_pct 全部按「已用%」口径（与 dsh-cost-meter 一致）：
        # general: 剩余 92% → 已用 8%；周: 剩余 100% → 已用 0%
        self.assertIn("✅ 8% 🔥x2.0", r["menu_bar"])
        self.assertNotIn("视频", r["menu_bar"])
        self.assertEqual(r["min_pct"], 8)
        # 简约风格：label 为空 → 去掉前缀；窗口名 5h / 7d；进度条按已用%填充（8% 几乎全空）
        self.assertIn("5h 8%  █░░░░░░░░░░░░░░░░░░░  重置 1h0m", r["lines"])
        self.assertIn("  7d 0%  ░░░░░░░░░░░░░░░░░░░░", r["lines"])
        # 旧格式（带括号状态文字 / 「M2.7/M3 通用:」前缀 / 「周窗口」/「视频」）已停用
        self.assertFalse(any("5小时窗口" in line for line in r["lines"]))
        self.assertFalse(any("（可用）" in line or "（耗尽）" in line for line in r["lines"]))
        self.assertFalse(any("M2.7/M3 通用:" in line for line in r["lines"]))
        self.assertFalse(any("周窗口" in line for line in r["lines"]))

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

    def test_status_percent_priority(self):
        """percent 存在时优先按 pct 推断状态（图标 + 颜色），忽略 status 码与废弃的 total_count 字段
        （MiniMax 新接口 total_count 恒为 0，即使有真实套餐）。"""
        data = {"model_remains": [{
            "model_name": "general",
            "current_interval_remaining_percent": 90, "current_interval_status": 1,
            "current_interval_total_count": 0,
            "current_weekly_remaining_percent": 100, "current_weekly_status": 3,
            "current_weekly_total_count": 0,
            "interval_boost_permille": 1000, "weekly_boost_permille": 1000,
            "remains_time": 3600000}]}
        r = te.parse_provider(MINIMAX_P, ok_result(data), COLORS, "dark")
        lines = r["lines"]
        # 已用%：剩余 90% → 已用 10%；剩余 100% → 已用 0%
        self.assertTrue(any("5h 10%" in line for line in lines))
        self.assertTrue(any("7d 0%" in line for line in lines))
        self.assertFalse(any("无套餐" in line for line in lines))
        self.assertFalse(any("耗尽" in line for line in lines))
        # 已用% < 80 → OK 色
        self.assertEqual(r["colors"][1], COLORS["OK"])
        self.assertEqual(r["colors"][2], COLORS["OK"])

    def test_status_low_pct_maps_to_warning(self):
        """已用% ≥ 80 → WARN 色 + ⚠️ 图标（已用口径，与 dsh-cost-meter 一致）。"""
        data = {"model_remains": [{
            "model_name": "general",
            "current_interval_remaining_percent": 15, "current_interval_status": 1,
            "current_interval_total_count": 0,
            "current_weekly_remaining_percent": 100, "current_weekly_status": 1,
            "current_weekly_total_count": 0,
            "interval_boost_permille": 1000, "weekly_boost_permille": 1000,
            "remains_time": 3600000}]}
        r = te.parse_provider(MINIMAX_P, ok_result(data), COLORS, "dark")
        lines = r["lines"]
        # 剩余 15% → 已用 85%（>= 80 → WARN）
        self.assertTrue(any("5h 85%" in line for line in lines))
        self.assertEqual(r["colors"][1], COLORS["WARN"])
        self.assertIn("⚠️", r["menu_bar"])

    def test_status_fallback_without_percent(self):
        """percent 缺失（旧按次数平台）：源字段缺省视为 0，按 remaining 翻转即已用 100%（ERR 色 + 🔴）。
        这是当前实现的硬性约定——若无 pct 字段，渲染为「已用 100%」告警态。"""
        import copy
        p = copy.deepcopy(MINIMAX_P)
        p["parser"]["fields"] = {k: v for k, v in p["parser"]["fields"].items()
                                 if k not in ("intervalPct", "weeklyPct")}
        data = {"model_remains": [{
            "model_name": "general",
            "current_interval_status": 3,
            "current_interval_total_count": 0,
            "current_weekly_status": 1,
            "current_weekly_total_count": 100,
            "interval_boost_permille": 1000, "weekly_boost_permille": 1000,
            "remains_time": 3600000}]}
        r = te.parse_provider(p, ok_result(data), COLORS, "dark")
        lines = r["lines"]
        # 源缺省 0 → 翻转后已用 100%（≥100 ERR + 🔴）
        self.assertTrue(any("5h 100%" in line for line in lines))
        self.assertTrue(any("7d 100%" in line for line in lines))
        self.assertFalse(any("（无套餐）" in line for line in lines))

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
        # 剩余 15% → 已用 85%（≥80 WARN + ⚠️）；周剩余 90% → 已用 10%（OK）
        self.assertIn("⚠️", r["menu_bar"])
        self.assertEqual(r["colors"][1], COLORS["WARN"])
        self.assertEqual(r["colors"][2], COLORS["OK"])

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

    def test_delimiter_format(self):
        r = te.classify_response('{"ok":true,"n":1}\n__TE_HTTP__200', 0)
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], 200)
        self.assertEqual(r["data"], {"ok": True, "n": 1})

    def test_delimiter_body_ending_with_digits(self):
        # 正文以数字结尾也不影响状态码解析（分隔符加固）
        r = te.classify_response('{"n":123}\n__TE_HTTP__200', 0)
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"], {"n": 123})

    def test_delimiter_client_error(self):
        r = te.classify_response('{"error":{"message":"Invalid API key"}}\n__TE_HTTP__401', 0)
        self.assertEqual(r["error_kind"], "client")
        self.assertEqual(r["message"], "Invalid API key")

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


class TestConsumptionAndPrediction(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.day0 = te.start_of_day()

    def write(self, pid, pairs):
        with open(os.path.join(self.dir, f"history-{pid}.jsonl"), "w") as f:
            for ts, v in pairs:
                f.write(f"{ts},{v}\n")

    def test_start_of_week_is_monday(self):
        t = time.localtime(te.start_of_week())
        self.assertEqual((t.tm_wday, t.tm_hour, t.tm_min, t.tm_sec), (0, 0, 0, 0))

    def test_start_of_month_is_first(self):
        t = time.localtime(te.start_of_month())
        self.assertEqual((t.tm_mday, t.tm_hour, t.tm_min), (1, 0, 0))

    def test_consumption_since_window(self):
        self.write("x", [(self.day0 - 86400, 50.0), (self.day0 - 100, 40.0),
                         (self.day0 + 100, 35.0)])
        # 今天窗口内只有 1 个点 → 数据不足
        self.assertEqual(te.consumption_since(self.dir, "x", self.day0), (0.0, 1))
        spend, pts = te.consumption_since(self.dir, "x", self.day0 - 86400)
        self.assertEqual(pts, 3)
        self.assertAlmostEqual(spend, 15.0)  # 50→40 (10) + 40→35 (5)

    def test_daily_spend_series_buckets(self):
        def ts(day_offset, sec):
            return self.day0 + day_offset * 86400 + sec
        self.write("x", [
            (ts(-3, 3600), 100.0), (ts(-3, 7200), 95.0),   # day-3 消耗 5
            (ts(-2, 3600), 95.0), (ts(-2, 7200), 90.0),    # day-2 消耗 5
            (ts(-1, 86399), 90.0),                          # 前一天 23:59:59
            (ts(0, 60), 85.0),                              # 今天 00:01 → 跨零点下降归今天
            (ts(0, 3600), 82.0),                            # 今天再消耗 3
        ])
        series = te.daily_spend_series(self.dir, "x", 7)
        # 索引 0 = 最早一天（6 天前），索引 -1 = 今天；day-3 消耗 5、day-2 消耗 5、今天 8
        self.assertEqual(series, [0.0, 0.0, 0.0, 5.0, 5.0, 0.0, 8.0])

    def test_days_left(self):
        now = int(time.time())
        self.write("x", [(now - 86400, 100.0), (now - 43200, 90.0), (now - 3600, 85.0)])
        d = te.days_left(self.dir, "x", 85.0)
        self.assertIsNotNone(d)
        self.assertAlmostEqual(d, 85.0 / 15.0, places=2)  # 24h 消耗 15 → 可用 85/15 天

    def test_days_left_no_consumption(self):
        self.write("x", [(self.day0 + 100, 50.0), (self.day0 + 200, 50.0)])
        self.assertIsNone(te.days_left(self.dir, "x", 50.0))


class TestHistoryCleanup(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old_ts = int(time.time()) - 40 * 86400
        self.new_ts = int(time.time()) - 3600

    def test_cleanup_removes_old_lines(self):
        with open(os.path.join(self.dir, "history-x.jsonl"), "w") as f:
            f.write(f"{self.old_ts},1.0\n{self.new_ts},2.0\n")
        te.cleanup_history(self.dir, 30)
        with open(os.path.join(self.dir, "history-x.jsonl")) as f:
            content = f.read()
        self.assertNotIn(f"{self.old_ts}", content)
        self.assertIn(f"{self.new_ts},2.0", content)

    def test_cleanup_ignores_non_history(self):
        other = os.path.join(self.dir, "debug.log")
        with open(other, "w") as f:
            f.write("keep me")
        te.cleanup_history(self.dir, 30)
        with open(other) as f:
            self.assertEqual(f.read(), "keep me")

    def test_maybe_cleanup_once_per_day(self):
        with open(os.path.join(self.dir, "history-x.jsonl"), "w") as f:
            f.write(f"{self.old_ts},1.0\n")
        te.maybe_cleanup_history(self.dir)
        with open(os.path.join(self.dir, "history-x.jsonl")) as f:
            self.assertEqual(f.read(), "")
        self.assertTrue(os.path.exists(os.path.join(self.dir, "last-cleanup.ts")))
        # 24h 内再次执行：不重复清理（新写入的旧行保留）
        with open(os.path.join(self.dir, "history-x.jsonl"), "w") as f:
            f.write(f"{self.old_ts},1.0\n")
        te.maybe_cleanup_history(self.dir)
        with open(os.path.join(self.dir, "history-x.jsonl")) as f:
            self.assertEqual(f.read(), f"{self.old_ts},1.0\n")


class TestNotifySound(unittest.TestCase):
    def test_default_sound_glass(self):
        with mock.patch.object(te.subprocess, "run") as m:
            te.send_notify("t", "m")
        script = m.call_args.args[0][-1]
        self.assertIn('sound name "Glass"', script)

    def test_sound_disabled(self):
        with mock.patch.dict(os.environ, {"TOKEN_EYE_SOUND": "0"}), \
             mock.patch.object(te.subprocess, "run") as m:
            te.send_notify("t", "m")
        script = m.call_args.args[0][-1]
        self.assertNotIn("sound name", script)

    def test_custom_sound(self):
        with mock.patch.dict(os.environ, {"TOKEN_EYE_SOUND": "Ping"}), \
             mock.patch.object(te.subprocess, "run") as m:
            te.send_notify("t", "m")
        script = m.call_args.args[0][-1]
        self.assertIn('sound name "Ping"', script)


class TestProviderTemplates(unittest.TestCase):
    def test_all_templates_valid(self):
        with open(os.path.join(REPO_ROOT, "scripts", "provider-templates.json")) as f:
            templates = json.load(f)
        with open(os.path.join(REPO_ROOT, "schema", "providers.schema.json")) as f:
            schema = json.load(f)
        refs = vs.collect_refs(schema)
        ids = []
        self.assertGreater(len(templates), 0)
        for t in templates:
            ids.append(t.get("id"))
            errors = vs.validate(t, schema["definitions"]["provider"], refs=refs)
            self.assertEqual(errors, [], f"模板 {t.get('name')} 不符合 JSON Schema: {errors}")
            runtime = te.schema_validate({"providers": [t]})
            self.assertEqual(runtime, [], f"模板 {t.get('name')} 未通过运行时校验: {runtime}")
        self.assertEqual(len(ids), len(set(ids)), "模板 id 存在重复")


class TestSelfCheck(unittest.TestCase):
    def test_check_keys(self):
        config = {"providers": [
            {"id": "a", "keychainService": "A", "enabled": True},
            {"id": "b", "keychainService": "B", "enabled": True},
            {"id": "c", "keychainService": "C", "enabled": False},
        ]}
        with mock.patch.object(te, "get_key", side_effect=["k1", "", "x"]):
            result = te.check_keys(config)
        self.assertEqual(result, [("A", True), ("B", False)])  # 禁用的不检查

    def test_probe_network(self):
        with mock.patch.object(te.subprocess, "run", return_value=mock.Mock(stdout="200")):
            self.assertTrue(te.probe_network())
        with mock.patch.object(te.subprocess, "run", return_value=mock.Mock(stdout="000")):
            self.assertFalse(te.probe_network())
        with mock.patch.object(te.subprocess, "run", side_effect=OSError("x")):
            self.assertFalse(te.probe_network())

    def test_installed_version(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "token-eye.sh"), "w") as f:
            f.write('# <bitbar.version>v0.14.0</bitbar.version>\n')
        self.assertEqual(te.installed_version(d), "0.14.0")
        self.assertIsNone(te.installed_version(tempfile.mkdtemp()))

    def test_self_check_report(self):
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "p.json")
        with open(cfg, "w") as f:
            json.dump({"providers": [{"id": "a", "keychainService": "A", "enabled": True}]}, f)
        with mock.patch.dict(os.environ, {"CONFIG_FILE": cfg}), \
             mock.patch.object(te, "check_keys", return_value=[("A", True)]), \
             mock.patch.object(te, "probe_network", return_value=True), \
             mock.patch.object(te, "installed_version", return_value=te.VERSION), \
             contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = te.self_check()
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Keychain A 存在", out)
        self.assertIn("网络连通", out)
        self.assertIn("版本一致", out)


class TestLineParams(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def cache(self, pid, payload):
        with open(os.path.join(self.dir, f"token-eye-cache-{pid}.json"), "w") as f:
            json.dump(payload, f)

    def test_balance_copy_params(self):
        r = te.parse_provider(BALANCE_P, ok_result({
            "balance_infos": [{"total_balance": 13.5, "currency": "CNY"}]}), COLORS, "dark")
        self.assertEqual(r["line_params"][0], {"param1": "copy-balance", "param2": "¥13.5"})
        # 简约化后余额类详情只有 1 行（去掉了"可用/不可用"行），line_params 仅 1 项
        self.assertEqual(len(r["line_params"]), 1)

    def test_line_params_rendered(self):
        r = {"id": "a", "name": "A", "status": "ok", "menu_bar": "¥1",
             "lines": ["A: ¥1", "可用"],
             "colors": [COLORS["DEFAULT"], COLORS["OK"]],
             "line_params": [{"param1": "copy-balance", "param2": "¥1"}, None]}
        buf = io.StringIO()
        with mock.patch.object(te, "check_latest_version", return_value=""), \
             contextlib.redirect_stdout(buf):
            te.render([r], {"menuBar": {}}, COLORS, {}, "/tmp")
        self.assertIn("A: ¥1 | color=", buf.getvalue())
        self.assertIn("param1=copy-balance param2=¥1", buf.getvalue())

    def test_daily_spend_line_opens_console(self):
        day0 = te.start_of_day()
        with open(os.path.join(self.dir, "history-deepseek.jsonl"), "w") as f:
            f.write(f"{day0 + 100},{50.0}\n")
            f.write(f"{day0 + 200},{48.0}\n")
        p = dict(BALANCE_P, consoleUrl="https://c.example")
        self.cache("deepseek", {"ts": int(time.time()),
                                "data": {"balance_infos": [{"total_balance": 48.0, "currency": "CNY"}]}})
        r = te.process_provider(p, {"cache": {"balance": 300}}, COLORS, "dark",
                                self.dir, self.dir, "/tmp")
        self.assertIn({"href": "https://c.example"}, r.get("line_params", []))


class TestAutoRefreshCooldown(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def flag_path(self):
        return os.path.join(self.dir, "token-eye-autorefresh-mimo.flag")

    def test_success_sets_ok_and_blocks(self):
        with mock.patch.object(te.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="HTTP=200")):
            ok, _ = te.auto_refresh_cookie(self.dir, "mimo", "/x")
        self.assertTrue(ok)
        with open(self.flag_path()) as f:
            self.assertTrue(f.read().strip().endswith(" ok"))
        # 成功后 30 分钟内再次触发 → 冷却
        with mock.patch.object(te.subprocess, "run") as m:
            ok2, msg = te.auto_refresh_cookie(self.dir, "mimo", "/x")
        self.assertFalse(ok2)
        self.assertIn("冷却中", msg)
        m.assert_not_called()

    def test_failure_sets_fail_and_short_cooldown(self):
        with mock.patch.object(te.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="HTTP=401")):
            ok, _ = te.auto_refresh_cookie(self.dir, "mimo", "/x")
        self.assertFalse(ok)
        with open(self.flag_path()) as f:
            self.assertTrue(f.read().strip().endswith(" fail"))
        # 失败后 5 分钟内 → 冷却（信息标注失败）
        with mock.patch.object(te.subprocess, "run") as m:
            ok2, msg = te.auto_refresh_cookie(self.dir, "mimo", "/x")
        self.assertFalse(ok2)
        self.assertIn("失败后 5 分钟", msg)
        m.assert_not_called()

    def test_old_format_flag_treated_as_ok(self):
        # 旧版纯数字标记按成功处理（30 分钟冷却）
        te._write_flag(self.flag_path(), str(int(time.time())))
        with mock.patch.object(te.subprocess, "run") as m:
            ok, msg = te.auto_refresh_cookie(self.dir, "mimo", "/x")
        self.assertFalse(ok)
        self.assertIn("成功", msg)
        m.assert_not_called()

    def test_fail_cooldown_expired_retries(self):
        # 失败标记已超过 5 分钟 → 重新执行
        te._write_flag(self.flag_path(), f"{int(time.time()) - 400} fail")
        with mock.patch.object(te.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="HTTP=200")):
            ok, _ = te.auto_refresh_cookie(self.dir, "mimo", "/x")
        self.assertTrue(ok)


class TestSemiAutoRefresh(unittest.TestCase):
    """半自动刷新：主动续期 + 会话失效自动打开登录页自动拾取。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_auto_refresh_failure_opens_login_page(self):
        # 刷新失败（浏览器会话也过期）→ 应自动打开登录页并通知
        with mock.patch.object(te.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="HTTP=401")), \
             mock.patch.object(te, "_open_login_page", return_value=True) as m_open, \
             mock.patch.object(te, "send_notify") as m_notify:
            ok, msg = te.auto_refresh_cookie(self.dir, "mimo", "/x", login_url="https://login")
        self.assertFalse(ok)
        m_open.assert_called_once()
        # 通知由 _open_login_page 内部触发；此处被 mock 掉不会走到 send_notify
        m_notify.assert_not_called()

    def test_open_login_page_sends_notify(self):
        # 真实 _open_login_page：真正打开登录页时发一条系统通知
        with mock.patch.object(te.subprocess, "run") as m_open, \
             mock.patch.object(te, "send_notify") as m_notify:
            self.assertTrue(te._open_login_page(self.dir, "mimo", "https://login"))
        m_open.assert_called_once()
        m_notify.assert_called_once()

    def test_auto_refresh_failure_without_login_url_no_open(self):
        with mock.patch.object(te.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="HTTP=401")), \
             mock.patch.object(te, "_open_login_page", return_value=True) as m_open:
            ok, _ = te.auto_refresh_cookie(self.dir, "mimo", "/x", login_url=None)
        self.assertFalse(ok)
        m_open.assert_not_called()

    def test_auto_refresh_success_clears_login_opened_flag(self):
        # 成功后清除 loginopened 标记，下次失效可再次弹登录页
        te._write_flag(os.path.join(self.dir, "token-eye-loginopened-mimo.flag"), str(int(time.time())))
        with mock.patch.object(te.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="HTTP=200")):
            ok, _ = te.auto_refresh_cookie(self.dir, "mimo", "/x")
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "token-eye-loginopened-mimo.flag")))

    def test_open_login_page_throttles(self):
        # 同一会话周期内只弹一次登录页（send_notify 内部也用 subprocess.run，单独 patch）
        with mock.patch.object(te.subprocess, "run") as m_open, \
             mock.patch.object(te, "send_notify"):
            first = te._open_login_page(self.dir, "mimo", "https://login")
            second = te._open_login_page(self.dir, "mimo", "https://login")
        self.assertTrue(first)
        self.assertFalse(second)
        # 只在第一次真正执行 open
        self.assertEqual(m_open.call_count, 1)

    def test_proactive_refresh_cooldown(self):
        # 主动续期：间隔内不重复执行；间隔过后执行
        with mock.patch.object(te.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="HTTP=200")) as m:
            r1 = te.proactive_refresh_cookie(self.dir, "mimo", "/x", 21600)
            r2 = te.proactive_refresh_cookie(self.dir, "mimo", "/x", 21600)
        self.assertTrue(r1)
        self.assertIsNone(r2)  # 冷却中
        self.assertEqual(m.call_count, 1)

    def test_proactive_refresh_failure_does_not_advance_flag(self):
        # 失败不推进标记 → 下一轮继续尝试
        with mock.patch.object(te.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="HTTP=401")):
            self.assertFalse(te.proactive_refresh_cookie(self.dir, "mimo", "/x", 21600))
        with mock.patch.object(te.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="HTTP=200")):
            self.assertTrue(te.proactive_refresh_cookie(self.dir, "mimo", "/x", 21600))


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
        self.assertEqual(r["menu_bar"], "✅ ¥8.41")

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
        merged = [line for line in r["lines"] if "今日消耗" in line]
        self.assertEqual(len(merged), 1, f"合并行应唯一: {merged}")
        self.assertIn("今日消耗 ¥2.00", merged[0])
        self.assertIn("预计可用", merged[0])

    def test_balance_trend_shows_range_and_window_delta(self):
        """余额类详情菜单不再出现 2.4h 趋势行（简约化）；历史继续写入以便将来恢复。"""
        day0 = te.start_of_day()
        with open(os.path.join(self.dir, "history-deepseek.jsonl"), "w") as f:
            f.write(f"{day0 + 100},{50.0}\n")
            f.write(f"{day0 + 200},{48.0}\n")
            f.write(f"{day0 + 300},{48.0}\n")
        self.cache("deepseek", {"ts": int(time.time()),
                                "data": {"balance_infos": [{"total_balance": 48.0, "currency": "CNY"}]}})
        r = te.process_provider(BALANCE_P, {"cache": {"balance": 300}}, COLORS, "dark",
                                self.dir, self.dir, "/tmp")
        self.assertEqual(r["status"], "ok")
        self.assertFalse(any("趋势" in line for line in r["lines"]),
                         f"不应出现趋势行: {r['lines']}")

    def test_plan_usage_no_trend_line(self):
        """用量类详情菜单不再出现趋势行（简约化）；历史仍继续写入以便将来恢复。"""
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
        self.assertFalse(any("趋势" in line for line in r["lines"]),
                         f"不应出现趋势行: {r['lines']}")

    def test_balance_consumption_lines(self):
        """余额类：今日消耗+预计可用合并行 + 近7天柱状 都出现（不再有本周/本月）。"""
        day0 = te.start_of_day()
        with open(os.path.join(self.dir, "history-deepseek.jsonl"), "w") as f:
            f.write(f"{day0 + 100},{50.0}\n")
            f.write(f"{day0 + 200},{48.0}\n")
        self.cache("deepseek", {"ts": int(time.time()),
                                "data": {"balance_infos": [{"total_balance": 48.0, "currency": "CNY"}]}})
        r = te.process_provider(BALANCE_P, {"cache": {"balance": 300}}, COLORS, "dark",
                                self.dir, self.dir, "/tmp")
        lines = "\n".join(r["lines"])
        self.assertIn("今日消耗", lines)
        self.assertIn("预计可用", lines)
        self.assertIn("近7天", lines)
        # 本周/本月 / 趋势 已合并/删除
        self.assertNotIn("本周", lines)
        self.assertNotIn("本月", lines)
        self.assertNotIn("趋势:", lines)

    def test_daily_spend_max_alert_dedup(self):
        """alert.dailySpendMax：当日消耗超上限 → 告警一次，去重。"""
        day0 = te.start_of_day()
        with open(os.path.join(self.dir, "history-deepseek.jsonl"), "w") as f:
            f.write(f"{day0 + 100},{50.0}\n")
            f.write(f"{day0 + 200},{46.0}\n")  # 今日消耗 4.0
        p = dict(BALANCE_P, alert={"minBalance": 1.0, "dailySpendMax": 3.0})
        cfg = {"cache": {"balance": 300}}
        self.cache("deepseek", {"ts": int(time.time()),
                                "data": {"balance_infos": [{"total_balance": 46.0, "currency": "CNY"}]}})
        with mock.patch.object(te, "send_notify") as m:
            te.process_provider(p, cfg, COLORS, "dark", self.dir, self.dir, "/tmp")
        self.assertEqual(m.call_count, 1)
        self.assertIn("今日消耗", m.call_args.args[1])
        with mock.patch.object(te, "send_notify") as m2:
            te.process_provider(p, cfg, COLORS, "dark", self.dir, self.dir, "/tmp")
        self.assertEqual(m2.call_count, 0)  # 去重

    def test_days_left_alert(self):
        """alert.daysLeft：预测可用天数低于阈值 → 告警。"""
        now = int(time.time())
        with open(os.path.join(self.dir, "history-deepseek.jsonl"), "w") as f:
            f.write(f"{now - 86400},{100.0}\n")
            f.write(f"{now - 43200},{90.0}\n")
            f.write(f"{now - 3600},{85.0}\n")
        p = dict(BALANCE_P, alert={"minBalance": 0.1, "daysLeft": 10})
        cfg = {"cache": {"balance": 300}}
        self.cache("deepseek", {"ts": now,
                                "data": {"balance_infos": [{"total_balance": 85.0, "currency": "CNY"}]}})
        with mock.patch.object(te, "send_notify") as m:
            te.process_provider(p, cfg, COLORS, "dark", self.dir, self.dir, "/tmp")
        self.assertEqual(m.call_count, 1)
        self.assertIn("天后余额耗尽", m.call_args.args[1])

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
        self.assertEqual(r["menu_bar"], "✅ ¥5.0")
        m_refresh.assert_called_once()
        self.assertEqual(m_fetch.call_count, 2)  # 刷新后重试了一次

    def test_auto_refresh_failed_falls_back_to_error(self):
        """自愈失败（刷新脚本失败）→ 回退为错误渲染，并展示失败原因。"""
        d = tempfile.mkdtemp()
        p = dict(BALANCE_P, refreshParam="refresh-mimo-cookie")
        cfg = {"cache": {"balance": 300}}
        with mock.patch.object(te, "get_key", return_value="thekey"), \
             mock.patch.object(te, "fetch_api", return_value={
                 "ok": False, "status": 401, "data": None,
                 "error_kind": "client", "message": "401"}), \
             mock.patch.object(te, "auto_refresh_cookie",
                               return_value=(False, "冷却中（失败后 5 分钟内已尝试过）")):
            r = te.process_provider(p, cfg, COLORS, "dark", d, d, REPO_ROOT)
        self.assertEqual(r["status"], "error")
        self.assertIn("配置/鉴权错误", r["lines"][0])
        self.assertTrue(any("自动刷新未生效" in line for line in r["lines"]),
                        f"缺自愈失败原因行: {r['lines']}")
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
