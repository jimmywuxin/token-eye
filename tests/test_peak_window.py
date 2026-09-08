#!/usr/bin/env python3
"""peak_window 单元测试（unittest，零依赖）。"""
import os
import sys
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from parsers import peak_window as pw  # noqa: E402

CST = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")


def at(hour, minute=0, weekday=1, tz=CST):
    """构造指定工作日（isoweekday）+ 时刻的本地时间。weekday=1 是周一。"""
    # 找一个确切的周一（2026-01-05 是周一）
    base = datetime(2026, 1, 5, hour, minute, tzinfo=tz)
    return base + timedelta(days=weekday - 1)


# DeepSeek 默认配置（用户口径）：北京时间 周一-周五 09:00-12:00、14:00-18:00
DEEPSEEK_CFG = {
    "tz": "Asia/Shanghai",
    "weekdays": [1, 2, 3, 4, 5],
    "hours": [[9, 12], [14, 18]],
    "peakLabel": "⚡高峰",
    "offPeakLabel": "🌙空闲",
}


class TestIsPeakHour(unittest.TestCase):
    def test_in_first_window(self):
        self.assertTrue(pw.is_peak_hour(at(9, 30), [(9, 12), (14, 18)]))
        self.assertTrue(pw.is_peak_hour(at(11, 59), [(9, 12), (14, 18)]))

    def test_gap_between_windows(self):
        # 12:00-13:59 是午休低谷
        self.assertFalse(pw.is_peak_hour(at(12, 0), [(9, 12), (14, 18)]))
        self.assertFalse(pw.is_peak_hour(at(13, 59), [(9, 12), (14, 18)]))

    def test_in_second_window(self):
        self.assertTrue(pw.is_peak_hour(at(14, 0), [(9, 12), (14, 18)]))
        self.assertTrue(pw.is_peak_hour(at(17, 59), [(9, 12), (14, 18)]))

    def test_after_second_window(self):
        self.assertFalse(pw.is_peak_hour(at(18, 0), [(9, 12), (14, 18)]))

    def test_early_morning(self):
        self.assertFalse(pw.is_peak_hour(at(8, 59), [(9, 12), (14, 18)]))
        self.assertFalse(pw.is_peak_hour(at(0, 0), [(9, 12), (14, 18)]))


class TestClassifyBasics(unittest.TestCase):
    def test_weekday_peak(self):
        info = pw.classify(at(10, 30, weekday=1), DEEPSEEK_CFG)
        self.assertTrue(info["is_peak"])
        self.assertEqual(info["label"], "⚡高峰")
        self.assertEqual(info["window_str"], "高峰")  # 详情菜单 token_eye 拼「高峰 距空闲 X」

    def test_weekday_gap(self):
        info = pw.classify(at(13, 0, weekday=2), DEEPSEEK_CFG)
        self.assertFalse(info["is_peak"])
        self.assertEqual(info["label"], "🌙空闲")
        self.assertEqual(info["window_str"], "空闲")

    def test_weekday_off_hours(self):
        info = pw.classify(at(20, 0, weekday=3), DEEPSEEK_CFG)
        self.assertFalse(info["is_peak"])
        self.assertEqual(info["label"], "🌙空闲")
        self.assertEqual(info["window_str"], "空闲")

    def test_weekend_is_offpeak_even_in_window(self):
        # 周六 10:30 = 落在 09-12 区间但周末一律空闲
        info = pw.classify(at(10, 30, weekday=6), DEEPSEEK_CFG)
        self.assertFalse(info["is_peak"])
        self.assertEqual(info["window_str"], "周末")

    def test_sunday_evening(self):
        info = pw.classify(at(22, 0, weekday=7), DEEPSEEK_CFG)
        self.assertFalse(info["is_peak"])
        self.assertEqual(info["window_str"], "周末")

    def test_boundary_exclusive_end(self):
        # 12:00 不算在 [9,12) 内（左闭右开）
        info = pw.classify(at(12, 0, weekday=1), DEEPSEEK_CFG)
        self.assertFalse(info["is_peak"])
        # 09:00 算
        info2 = pw.classify(at(9, 0, weekday=1), DEEPSEEK_CFG)
        self.assertTrue(info2["is_peak"])

    def test_boundary_exclusive_end_second_window(self):
        info = pw.classify(at(18, 0, weekday=1), DEEPSEEK_CFG)
        self.assertFalse(info["is_peak"])
        info2 = pw.classify(at(17, 59, weekday=1), DEEPSEEK_CFG)
        self.assertTrue(info2["is_peak"])


class TestNextSwitch(unittest.TestCase):
    def test_during_first_window(self):
        info = pw.classify(at(10, 0, weekday=1), DEEPSEEK_CFG)
        # 10:00 → 12:00 切换，剩 2h
        self.assertEqual(info["seconds_to_switch"], 2 * 3600)

    def test_during_gap(self):
        info = pw.classify(at(13, 0, weekday=1), DEEPSEEK_CFG)
        # 13:00 → 14:00 切换，剩 1h
        self.assertEqual(info["seconds_to_switch"], 3600)

    def test_after_last_window(self):
        info = pw.classify(at(20, 0, weekday=1), DEEPSEEK_CFG)
        # 20:00 → 次日 09:00，剩 13h
        self.assertEqual(info["seconds_to_switch"], 13 * 3600)

    def test_format_countdown(self):
        self.assertEqual(pw.format_countdown(0), "")
        self.assertEqual(pw.format_countdown(59), "0m")
        self.assertEqual(pw.format_countdown(60), "1m")
        self.assertEqual(pw.format_countdown(3600), "1h")
        self.assertEqual(pw.format_countdown(3660), "1h1m")
        self.assertEqual(pw.format_countdown(7320), "2h2m")


class TestTimezoneConversion(unittest.TestCase):
    def test_naive_datetime_treated_as_local(self):
        # 没有 tzinfo 的输入会被当作 cfg.tz 处理
        naive = datetime(2026, 1, 5, 10, 30)  # 周一 10:30
        info = pw.classify(naive, DEEPSEEK_CFG)
        self.assertTrue(info["is_peak"])

    def test_aware_datetime_converted(self):
        # 给一个 UTC 时间 02:30 = 北京时间 10:30（峰值时段）
        utc = datetime(2026, 1, 5, 2, 30, tzinfo=UTC)  # 周一
        info = pw.classify(utc, DEEPSEEK_CFG)
        self.assertTrue(info["is_peak"])
        self.assertEqual(info["tz"], "Asia/Shanghai")


class TestCustomConfig(unittest.TestCase):
    def test_only_morning_peak(self):
        cfg = {"hours": [[9, 12]], "weekdays": [1, 2, 3, 4, 5]}
        self.assertTrue(pw.classify(at(10, 0), cfg)["is_peak"])
        self.assertFalse(pw.classify(at(14, 0), cfg)["is_peak"])

    def test_all_day_peak_on_weekday(self):
        cfg = {"hours": [[0, 24]], "weekdays": [1, 2, 3, 4, 5]}
        for h in [0, 6, 12, 18, 23]:
            self.assertTrue(pw.classify(at(h), cfg)["is_peak"])

    def test_invalid_hours(self):
        with self.assertRaises(ValueError):
            pw.classify(at(10), {"hours": [[12, 9]]})  # start >= end
        with self.assertRaises(ValueError):
            pw.classify(at(10), {"hours": [[9, 25]]})  # end > 24
        with self.assertRaises(ValueError):
            pw.classify(at(10), {"hours": [[-1, 9]]})  # start < 0

    def test_invalid_weekdays(self):
        with self.assertRaises(ValueError):
            pw.classify(at(10), {"hours": [[9, 12]], "weekdays": [0, 8]})


class TestIntegrationWithDeepSeekConfig(unittest.TestCase):
    """模拟完整菜单渲染所需的字段完整性。"""

    def test_result_keys(self):
        info = pw.classify(at(10, 30), DEEPSEEK_CFG)
        for k in ("is_peak", "label", "window_str", "tz",
                  "next_switch_local", "seconds_to_switch"):
            self.assertIn(k, info)

    def test_window_str_three_states(self):
        # 用户口径：高峰/空闲/周末 三态单字
        self.assertEqual(pw.classify(at(10, 30), DEEPSEEK_CFG)["window_str"], "高峰")
        self.assertEqual(pw.classify(at(13, 0), DEEPSEEK_CFG)["window_str"], "空闲")
        self.assertEqual(pw.classify(at(10, 30, weekday=6), DEEPSEEK_CFG)["window_str"], "周末")


if __name__ == "__main__":
    unittest.main()