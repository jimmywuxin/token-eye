#!/usr/bin/env python3
"""peak_window 单元测试（unittest，零依赖）。"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from parsers import peak_window as pw  # noqa: E402

# 麒麟 py3.8 无 zoneinfo；用固定偏移等价时区（UTC+8 / UTC）跑测试
try:  # Python ≥ 3.9
    from zoneinfo import ZoneInfo
    CST = ZoneInfo("Asia/Shanghai")
    UTC = ZoneInfo("UTC")
except ImportError:  # Python 3.8-：固定偏移（中国无 DST，等价）
    CST = timezone(timedelta(hours=8), "Asia/Shanghai")
    UTC = timezone.utc


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
    "holidays": True,
    "peakLabel": "⚡高峰",
    "offPeakLabel": "🌙空闲",
}

# 项目内置节假日表（holidays/<年>.json，源自 holiday-cn）
REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HOLIDAYS = pw.load_holidays([REPO_ROOT], (2025, 2026, 2027))


def on(date_str, hour, minute=0, tz=CST):
    """按具体日期构造本地时间（用于节假日用例，如 on("2026-10-01", 10, 30)）。"""
    return (datetime.strptime(date_str, "%Y-%m-%d")
            .replace(hour=hour, minute=minute, tzinfo=tz))


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

    def test_friday_evening_skips_weekend(self):
        # 周五 20:00 → 下一个高峰是周一 09:00（61h），不是周六 09:00
        info = pw.classify(at(20, 0, weekday=5), DEEPSEEK_CFG)
        self.assertEqual(info["seconds_to_switch"], 61 * 3600)

    def test_friday_gap_end_skips_weekend(self):
        # 周五 18:30（下班后）→ 周一 09:00
        info = pw.classify(at(18, 30, weekday=5), DEEPSEEK_CFG)
        self.assertEqual(info["seconds_to_switch"], (62 * 3600 + 30 * 60))

    def test_saturday_morning_skips_to_monday(self):
        # 周六 09:30（落在时段内但周末）→ 周一 09:00 = 47h30m
        info = pw.classify(at(9, 30, weekday=6), DEEPSEEK_CFG)
        self.assertEqual(info["window_str"], "周末")
        self.assertEqual(info["seconds_to_switch"], (47 * 3600 + 30 * 60))

    def test_sunday_evening_to_monday(self):
        # 周日 23:00 → 周一 09:00 = 10h
        info = pw.classify(at(23, 0, weekday=7), DEEPSEEK_CFG)
        self.assertEqual(info["seconds_to_switch"], 10 * 3600)

    def test_allday_peak_crosses_midnight(self):
        # 全天高峰（[[0,24]]）周五 23:00 高峰中 → 次日 00:00 翻转
        cfg = {"hours": [[0, 24]], "weekdays": [1, 2, 3, 4, 5]}
        info = pw.classify(at(23, 0, weekday=5), cfg)
        self.assertTrue(info["is_peak"])
        self.assertEqual(info["seconds_to_switch"], 3600)

    def test_format_countdown(self):
        self.assertEqual(pw.format_countdown(0), "")
        self.assertEqual(pw.format_countdown(59), "0m")
        self.assertEqual(pw.format_countdown(60), "1m")
        self.assertEqual(pw.format_countdown(3600), "1h")
        self.assertEqual(pw.format_countdown(3660), "1h1m")
        self.assertEqual(pw.format_countdown(7320), "2h2m")

    def test_format_countdown_days(self):
        # ≥ 1 天取 d+h 两级（跨整段假期时 153h18m 没法读）
        self.assertEqual(pw.format_countdown(86399), "23h59m")
        self.assertEqual(pw.format_countdown(86400), "1d")
        self.assertEqual(pw.format_countdown(86400 + 3600), "1d1h")
        self.assertEqual(pw.format_countdown(599400), "6d22h")   # 国庆 10-01 10:30 → 10-08 09:00
        self.assertEqual(pw.format_countdown(551880), "6d9h")    # 153h18m
        self.assertEqual(pw.format_countdown(824400), "9d13h")   # 春节长空窗


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


class TestHolidayTable(unittest.TestCase):
    """内置节假日表（holidays/<年>.json）加载与查表。"""

    def test_bundled_files_load(self):
        table = pw.load_holidays([REPO_ROOT], (2025, 2026))
        self.assertTrue(table, "holidays/ 内置数据未加载")
        self.assertGreater(len(table), 50)
        # 法定节假日 → True（放假）
        self.assertTrue(table.get("2026-10-01"), "2026 国庆应放假")
        self.assertTrue(table.get("2025-01-01"), "2025 元旦应放假")
        # 调休上班的周末 → False（不是放假）
        self.assertIs(table.get("2026-09-20"), False, "2026-09-20 应为调休上班日")
        self.assertIs(table.get("2026-02-14"), False)

    def test_missing_dir_yields_empty_table(self):
        self.assertEqual(pw.load_holidays(["/nonexistent-token-eye-xyz"], (2026,)), {})

    def test_malformed_file_is_ignored(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "holidays"))
            with open(os.path.join(tmp, "holidays", "2026.json"), "w") as f:
                f.write("{ not json")
            self.assertEqual(pw.load_holidays([tmp], (2026,)), {})

    def test_is_workday_and_is_holiday(self):
        d_holiday = datetime(2026, 10, 1).date()   # 周四，国庆
        d_makeup = datetime(2026, 9, 20).date()    # 周日，调休上班
        d_weekend = datetime(2026, 9, 19).date()   # 周六，普通周末
        weekdays = (1, 2, 3, 4, 5)
        self.assertFalse(pw.is_workday(d_holiday, weekdays, HOLIDAYS))
        self.assertTrue(pw.is_holiday(d_holiday, HOLIDAYS))
        self.assertTrue(pw.is_workday(d_makeup, weekdays, HOLIDAYS))
        self.assertFalse(pw.is_holiday(d_makeup, HOLIDAYS))
        self.assertFalse(pw.is_workday(d_weekend, weekdays, HOLIDAYS))
        # 传 None 时退回纯 weekdays 规则
        self.assertTrue(pw.is_workday(d_holiday, weekdays, None))
        self.assertFalse(pw.is_workday(d_makeup, weekdays, None))


class TestHolidayClassify(unittest.TestCase):
    """叠加节假日表后的峰谷判定（DeepSeek 口径）。"""

    def test_national_day_is_offpeak_all_day(self):
        info = pw.classify(on("2026-10-01", 10, 30), DEEPSEEK_CFG, HOLIDAYS)
        self.assertFalse(info["is_peak"])
        self.assertTrue(info["is_holiday"])
        self.assertEqual(info["window_str"], "节假日")
        self.assertEqual(info["label"], "🌙空闲")

    def test_holiday_countdown_skips_whole_holiday(self):
        # 2026 国庆 10-01..10-07 放假 → 下一个工作日 10-08（周四）09:00
        info = pw.classify(on("2026-10-01", 10, 30), DEEPSEEK_CFG, HOLIDAYS)
        self.assertEqual(info["seconds_to_switch"], 599400)  # 6d22h30m

    def test_holiday_late_night(self):
        info = pw.classify(on("2026-10-01", 23, 0), DEEPSEEK_CFG, HOLIDAYS)
        self.assertEqual(info["window_str"], "节假日")
        self.assertEqual(info["seconds_to_switch"], 554400)  # 6d10h

    def test_makeup_saturday_counts_as_workday(self):
        # 2026-10-10（周六）是国庆调休上班日 → 时段内算高峰
        info = pw.classify(on("2026-10-10", 10, 30), DEEPSEEK_CFG, HOLIDAYS)
        self.assertTrue(info["is_peak"])
        self.assertEqual(info["window_str"], "高峰")

    def test_makeup_saturday_off_hours_is_idle(self):
        info = pw.classify(on("2026-10-10", 20, 0), DEEPSEEK_CFG, HOLIDAYS)
        self.assertFalse(info["is_peak"])
        self.assertEqual(info["window_str"], "空闲")  # 调休日算工作日，不是「周末」

    def test_makeup_sunday_morning(self):
        info = pw.classify(on("2026-09-20", 10, 0), DEEPSEEK_CFG, HOLIDAYS)
        self.assertTrue(info["is_peak"])
        self.assertEqual(info["seconds_to_switch"], 2 * 3600)

    def test_plain_weekend_still_weekend(self):
        info = pw.classify(on("2026-09-19", 10, 30), DEEPSEEK_CFG, HOLIDAYS)
        self.assertFalse(info["is_peak"])
        self.assertEqual(info["window_str"], "周末")

    def test_normal_weekday_unaffected(self):
        info = pw.classify(on("2026-09-21", 10, 30), DEEPSEEK_CFG, HOLIDAYS)
        self.assertTrue(info["is_peak"])
        self.assertEqual(info["window_str"], "高峰")

    def test_spring_festival_long_gap_lookahead(self):
        # 2026 春节 02-15..02-23 放假；02-14（周六）是调休上班日 → 20:00 后
        # 下一个工作日是 02-24（周二），间隔 9d13h（超出旧版 7 天搜索窗口）
        info = pw.classify(on("2026-02-14", 20, 0), DEEPSEEK_CFG, HOLIDAYS)
        self.assertEqual(info["window_str"], "空闲")
        self.assertEqual(info["seconds_to_switch"], 824400)

    def test_without_table_behaves_as_before(self):
        # holidays=False（未传表）时保持旧口径：国庆当天照旧算高峰
        info = pw.classify(on("2026-10-01", 10, 30), DEEPSEEK_CFG, None)
        self.assertTrue(info["is_peak"])
        self.assertFalse(info["is_holiday"])

    def test_synthetic_table(self):
        table = {"2026-01-05": True}  # 周一放假
        info = pw.classify(at(10, 30, weekday=1), DEEPSEEK_CFG, table)
        self.assertFalse(info["is_peak"])
        self.assertEqual(info["window_str"], "节假日")

    def test_result_keys_include_is_holiday(self):
        info = pw.classify(at(10, 30), DEEPSEEK_CFG, HOLIDAYS)
        self.assertIn("is_holiday", info)


if __name__ == "__main__":
    unittest.main()