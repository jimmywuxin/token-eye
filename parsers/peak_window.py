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
      "offPeakLabel": "🌙空闲",
      "unknownLabel": "⏱待定"
    }

判定规则：
- 时段以 *本地时间* 小时整数判断（边界左闭右开，如 [9,12) 表示 09:00-12:00）
- 周末（weekdays 之外）一律返回 off-peak
- 当前小时落在任意 [start,end) 区间内 → peak；否则 → off-peak
- 若当前本地小时不在 hours 任何区间内但「下一次区间开始时间 < 1 小时」，
  返回 unknownLabel（给提示用户「快进高峰」之类的过渡感），可选行为
  默认关闭，调用方可通过 `warnWithinMinutes` 开启

零依赖：仅用标准库 datetime + zoneinfo（Py3.9+；macOS 系统 Python 3 已带）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def next_switch(local_dt: datetime, ranges: Sequence[tuple[int, int]]) -> datetime:
    """返回本地时区下「下一次状态翻转」的时刻（峰值↔谷值切换）。

    用于菜单显示「距下次切换还有 X 分钟」。找不到下一个切换点时返回 local_dt。
    """
    if not ranges:
        return local_dt
    now_h = local_dt.hour
    in_peak = is_peak_hour(local_dt, ranges)
    # 收集所有区间边界（按小时排序，去重）
    edges = sorted({s for s, _ in ranges} | {e for _, e in ranges})
    # 候选切换点：从 now_h+1 到 24，再加次日所有边界
    candidates: list[int] = [e for e in edges if e > now_h]
    candidates += [24 + e for e in edges]
    if not candidates:
        return local_dt
    next_h_abs = candidates[0]
    # 构造本地时间（保留分钟/秒）并对齐到整点
    base_date = local_dt.date()
    if next_h_abs >= 24:
        next_dt = datetime.combine(base_date + timedelta(days=1),
                                   datetime.min.time()).replace(
            hour=next_h_abs - 24, minute=0, second=0, microsecond=0,
            tzinfo=local_dt.tzinfo)
    else:
        next_dt = datetime.combine(base_date, datetime.min.time()).replace(
            hour=next_h_abs, minute=0, second=0, microsecond=0,
            tzinfo=local_dt.tzinfo)
    return next_dt


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
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        # fallback：按固定 UTC+8 处理（兼容性兜底，Py3.8- 无 zoneinfo）
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
    unknown_label = cfg.get("unknownLabel", "⏱待定")

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

    nxt = next_switch(local_dt, ranges)
    seconds = max(0, int((nxt - local_dt).total_seconds()))

    return {
        "is_peak": is_peak,
        "label": label,
        "window_str": window_str,
        "tz": tz.key if hasattr(tz, "key") else str(tz),
        "next_switch_local": nxt,
        "seconds_to_switch": seconds,
        "_unknown_label": unknown_label,  # 供调用方按需触发
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