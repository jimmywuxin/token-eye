#!/usr/bin/env python3
"""
peak_window.py — 峰/谷时段判定（纯逻辑，零依赖）。

设计目标
--------
DeepSeek 等平台的「峰谷定价」API **不返回当前时段字段**，只能在客户端
按官方公示的时段规则自行判定（官方 UTC 周一至周五 01:00-04:00 + 06:00-10:00，
等价于 **北京时间周一至周五 09:00-12:00、14:00-18:00**）。本模块专门负责
这段判定逻辑，纯函数、可单测、可被任何 provider 复用。

用法（在 parse_provider 里调用）：

    from parsers.peak_window import classify
    pw = p["parser"].get("peakWindow")
    if pw:
        info = classify(datetime.now(ZoneInfo("Asia/Shanghai")), pw)
        # info = {"is_peak": bool, "label": str, "window_str": str,
        #         "next_switch_local": datetime, "seconds_to_switch": int}

配置 schema（写入 providers.json 的 parser.peakWindow）：

    {
      "tz": "Asia/Shanghai",                  // 任意 IANA 时区名，缺省 Asia/Shanghai
      "weekdays": [1,2,3,4,5],                // 周一=1 ... 周日=7；缺省 [1..5]（工作日）
      "hours": [[9,12],[14,18]],             // 半开区间 [[start,end),...]，本地小时；24h 制
      "peakLabel": "⚡高峰",
      "offPeakLabel": "🌙空闲"
    }

判定规则：
- 时段以 *本地时间* 小时整数判断（边界左闭右开，如 [9,12) 表示 09:00-12:00）
- 周末（weekdays 之外）一律返回 off-peak
- 当前小时落在任意 [start,end) 区间内 → peak；否则 → off-peak
- 倒计时感知 weekdays：空闲/周末时向后找下一个「高峰日」的第一个区间起点
  （最多找 7 天），高峰中取当前区间结束（end=24 视为次日 00:00）

零依赖：仅用标准库 datetime + zoneinfo（Py3.9+；macOS 系统 Python 3 已带）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Sequence

try:  # Python ≥ 3.9：标准库 zoneinfo
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    _NO_ZONEINFO = False
except ImportError:  # Python 3.8-（如麒麟 /usr/bin/python3）：无 zoneinfo
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception
    # 麒麟 py3.8 的 datetime.tzinfo 不可子类化（C 限制），改用内置固定偏移
    from datetime import timezone as _timezone
    _UTC_P8 = _timezone(timedelta(hours=8))
    _NO_ZONEINFO = True

# 默认时区：北京时间（UTC+8，中国不实行夏令时，固定无 DST 偏移）
DEFAULT_TZ = "Asia/Shanghai"

# 默认工作日：周一至周五（isoweekday 1-5）
DEFAULT_WEEKDAYS: tuple[int, ...] = (1, 2, 3, 4, 5)


def _hours_to_ranges(hours):
    """校验 hours 形如 [[start,end), ...]；返回 frozenset 用于 in 判断。"""
    ranges: list[tuple[int, int]] = []
    for h in hours or []:
        if not (isinstance(h, (list, tuple)) and len(h) == 2):
            raise ValueError(f"peakWindow.hours 元素必须是 [start,end]：{h!r}")
        start, end = int(h[0]), int(h[1])
        if not (0 <= start < 24 and 0 < end <= 24 and start < end):
            raise ValueError(f"peakWindow.hours 区间非法（应满足 0≤start<end≤24）：{h!r}")
        ranges.append((start, end))
    return ranges


def is_peak_hour(local_dt: datetime, ranges: Sequence[tuple[int, int]]) -> bool:
    """当前本地小时是否落在任一区间内（左闭右开）。"""
    h = local_dt.hour
    return any(start <= h < end for start, end in ranges)


def next_switch(local_dt: datetime, ranges: Sequence[tuple[int, int]],
                weekdays: Iterable[int] = DEFAULT_WEEKDAYS) -> datetime:
    """返回本地时区下「下一次状态翻转」的时刻（峰值↔谷值切换）。

    倒计时语义与展示口径一致：
    - 高峰中（且今天是高峰日）→ 当前所在区间的结束时刻（end=24 视为次日 00:00）
    - 空闲/周末 → 下一个「高峰日」的第一个区间起点（最多向后找 7 天）

    找不到任何切换点时返回 local_dt。
    """
    if not ranges:
        return local_dt
    weekdays = tuple(weekdays)
    in_peak_today = is_peak_hour(local_dt, ranges) and local_dt.isoweekday() in weekdays
    if in_peak_today:
        # 当前所在区间取最晚的 end（容忍重叠区间配置）；end=24 → 次日 00:00
        cur_end = max(e for s, e in ranges if s <= local_dt.hour < e)
        if cur_end >= 24:
            return datetime.combine(local_dt.date() + timedelta(days=1),
                                    datetime.min.time()).replace(
                tzinfo=local_dt.tzinfo)
        return local_dt.replace(hour=cur_end, minute=0, second=0, microsecond=0)
    # 空闲/周末：找下一个高峰日的第一个区间起点
    starts = sorted({s for s, _ in ranges})
    for offset in range(8):
        day = local_dt.date() + timedelta(days=offset)
        if day.isoweekday() not in weekdays:
            continue
        day_starts = starts if offset > 0 else [s for s in starts if s > local_dt.hour]
        if day_starts:
            return datetime.combine(day, datetime.min.time()).replace(
                hour=day_starts[0], minute=0, second=0, microsecond=0,
                tzinfo=local_dt.tzinfo)
    return local_dt


def classify(local_dt: datetime, cfg: dict) -> dict:
    """核心判定入口。

    参数：
        local_dt: 本地时区的 datetime（必须带 tzinfo）
        cfg: providers.json 中 parser.peakWindow 的配置块

    返回：
        {
          "is_peak": bool,
          "label": str,                  # 直接展示文本（如 "⚡高峰"）
          "window_str": str,             # 当前所在时段的人类可读描述
          "tz": str,                     # 实际使用的时区名
          "next_switch_local": datetime, # 下一次切换的本地时刻
          "seconds_to_switch": int,      # 距下次切换的秒数（≥0）
        }
    """
    tz_name = cfg.get("tz") or DEFAULT_TZ
    if _NO_ZONEINFO:  # Py3.8-：固定 UTC+8（中国无 DST，等价）
        tz = _UTC_P8
    else:
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            # fallback：按固定 UTC+8 处理（tz 名非法兜底）
            tz = ZoneInfo(DEFAULT_TZ)
    # 把入参转换到目标时区
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=tz)
    else:
        local_dt = local_dt.astimezone(tz)

    weekdays = tuple(cfg.get("weekdays") or DEFAULT_WEEKDAYS)
    if any(not (1 <= int(d) <= 7) for d in weekdays):
        raise ValueError(f"peakWindow.weekdays 取值应在 1-7（isoweekday）：{weekdays!r}")

    ranges = _hours_to_ranges(cfg.get("hours") or [])
    peak_label = cfg.get("peakLabel", "⚡高峰")
    off_label = cfg.get("offPeakLabel", "🌙空闲")

    is_weekday = local_dt.isoweekday() in weekdays
    in_window = is_peak_hour(local_dt, ranges)
    is_peak = is_weekday and in_window

    # window_str：单行紧凑文案，直接由 token_eye 渲染（详见 token_eye.render_menu 集成）
    # - 高峰 → "高峰 距空闲 {countdown}"  （到当前高峰段结束 = 距空闲）
    # - 空闲（工作日）→ "空闲 距高峰 {countdown}"（到下一个峰段开始 = 距高峰）
    # - 周末 → "周末 距高峰 {countdown}"（到下一个工作日峰段开始 = 距高峰）
    if is_peak:
        label = peak_label
        window_str = "高峰"
    elif not is_weekday:
        label = off_label
        window_str = "周末"
    else:
        label = off_label
        window_str = "空闲"

    nxt = next_switch(local_dt, ranges, weekdays)
    seconds = max(0, int((nxt - local_dt).total_seconds()))

    return {
        "is_peak": is_peak,
        "label": label,
        "window_str": window_str,
        # 无 zoneinfo（Py3.8-）时 tz 是固定偏移对象，无 .key；展示请求的 tz 名保持一致
        "tz": (tz.key if hasattr(tz, "key") else str(tz)) if not _NO_ZONEINFO else tz_name,
        "next_switch_local": nxt,
        "seconds_to_switch": seconds,
    }


def format_countdown(seconds: int) -> str:
    """把秒数格式化成简短剩余时间文案。"""
    if seconds <= 0:
        return ""
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h and m:
        return f"{h}h{m}m"
    if h:
        return f"{h}h"
    return f"{m}m"