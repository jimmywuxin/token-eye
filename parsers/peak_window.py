#!/usr/bin/env python3
"""
peak_window.py — 峰/谷时段判定（纯逻辑，零依赖）。

设计目标
--------
DeepSeek 等平台的「峰谷定价」API **不返回当前时段字段**，只能在客户端
按官方公示的时段规则自行判定：

- 高峰：北京时间**周一至周五**（**不含中国法定节假日**）09:00-12:00、14:00-18:00
- 空闲：其余时段 —— 含午休/夜间、**周末**、**中国法定节假日全天**
- 特例：**调休上班的周末**算工作日（落在时段内即高峰）

法定节假日与调休**没有算法规律**（由国务院逐年公告），只能查表：内置
`holidays/<年>.json`（源自 https://github.com/NateScarlet/holiday-cn ，逐条对着
gov.cn 公告），缺表时自动退化为「周一至周五 + 时段」判定。更新用
`scripts/update-holidays.py`。

用法（在 parse_provider 里调用）：

    from parsers.peak_window import classify, load_holidays

    pw = p["parser"].get("peakWindow")
    if pw:
        hd = load_holidays([project_dir], (2026, 2027)) if pw.get("holidays") else None
        info = classify(datetime.now(ZoneInfo("Asia/Shanghai")), pw, hd)
        # info = {"is_peak": bool, "label": str, "window_str": str,
        #         "next_switch_local": datetime, "seconds_to_switch": int}

配置 schema（写入 providers.json 的 parser.peakWindow）：

    {
      "tz": "Asia/Shanghai",                  // 任意 IANA 时区名，缺省 Asia/Shanghai
      "weekdays": [1,2,3,4,5],                // 周一=1 ... 周日=7；缺省 [1..5]（工作日）
      "hours": [[9,12],[14,18]],             // 半开区间 [[start,end),...]，本地小时；24h 制
      "holidays": true,                       // 是否叠加中国法定节假日/调休表（缺省 false）
      "peakLabel": "⚡高峰",
      "offPeakLabel": "🌙空闲"
    }

判定规则：
- 时段以 *本地时间* 小时整数判断（边界左闭右开，如 [9,12) 表示 09:00-12:00）
- 非法定节假日的周末（weekdays 之外）一律返回 off-peak
- 法定节假日（含调休放假）全天 off-peak，展示为「节假日」
- 调休上班的周末按工作日算（时段内 → peak）
- 当前小时落在任意 [start,end) 区间内 → peak；否则 → off-peak
- 倒计时感知节假日与 weekdays：空闲/节假日时向后找下一个「工作日」的第一个区间起点
  （最多找 21 天，覆盖春节 9 连休 + 前后周末），高峰中取当前区间结束（end=24 视为次日 00:00）

零依赖：仅用标准库 datetime + json + zoneinfo（Py3.9+；macOS 系统 Python 3 已带）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

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

# 节假日数据目录名（相对项目根目录），文件形如 holidays/2026.json
HOLIDAY_DIRNAME = "holidays"

# 向后搜索下一个高峰日的天数上限（春节 9 连休 + 前后周末也够用）
_MAX_LOOKAHEAD_DAYS = 21


def _hours_to_ranges(hours):
    """校验 hours 形如 [[start,end), ...]；返回列表用于 in 判断。"""
    ranges: list[tuple[int, int]] = []
    for h in hours or []:
        if not (isinstance(h, (list, tuple)) and len(h) == 2):
            raise ValueError(f"peakWindow.hours 元素必须是 [start,end]：{h!r}")
        start, end = int(h[0]), int(h[1])
        if not (0 <= start < 24 and 0 < end <= 24 and start < end):
            raise ValueError(f"peakWindow.hours 区间非法（应满足 0≤start<end≤24）：{h!r}")
        ranges.append((start, end))
    return ranges


# ---------------------------------------------------------------------------
# 中国法定节假日 / 调休 数据表（可选，纯查表）
# ---------------------------------------------------------------------------

# path -> (mtime, {date: is_off_day})；同进程内多次渲染复用，避免重复读盘
_HOLIDAY_CACHE: dict[str, tuple[float, dict[str, bool]]] = {}


def holiday_path(dirs: Iterable[Optional[str]], year: int) -> Optional[str]:
    """在若干候选根目录下找 `holidays/<year>.json`，返回第一个存在的路径。"""
    for d in dirs:
        if not d:
            continue
        p = os.path.join(d, HOLIDAY_DIRNAME, f"{year}.json")
        if os.path.isfile(p):
            return p
    return None


def load_holiday_file(path: str) -> dict[str, bool]:
    """读单个年份的节假日文件，返回 {ISO 日期: 是否放假}。

    文件格式（holiday-cn）：`{"year":2026, "days":[{"date":"2026-10-01","isOffDay":true}, ...]}`
    - `isOffDay=true`  → 法定节假日/调休放假 → 空闲
    - `isOffDay=false` → 调休上班的周末   → 按工作日算

    文件缺失/损坏时返回空表（调用方退化为 weekdays 规则），不抛异常。
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    cached = _HOLIDAY_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    days: dict[str, bool] = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("days") or []:
            date = str((item or {}).get("date") or "")
            if len(date) == 10:  # 只收 YYYY-MM-DD
                days[date] = bool(item.get("isOffDay"))
    except (OSError, ValueError, AttributeError):
        days = {}
    _HOLIDAY_CACHE[path] = (mtime, days)
    return days


def load_holidays(dirs: Iterable[Optional[str]], years: Iterable[int]) -> dict[str, bool]:
    """合并若干年份的节假日表。传入 `(今年, 明年)` 即可覆盖跨年倒计时。"""
    merged: dict[str, bool] = {}
    for year in years:
        p = holiday_path(dirs, int(year))
        if p:
            merged.update(load_holiday_file(p))
    return merged


def is_workday(day, weekdays: Iterable[int] = DEFAULT_WEEKDAYS,
               holidays: Optional[dict[str, bool]] = None) -> bool:
    """某天是否算「工作日」（调休表优先于 weekdays 规则）。"""
    if holidays:
        off = holidays.get(day.isoformat())
        if off is not None:
            return not off
    return day.isoweekday() in tuple(weekdays)


def is_holiday(day, holidays: Optional[dict[str, bool]] = None) -> bool:
    """某天是否是法定节假日/调休放假（仅用于展示文案「节假日」）。"""
    return bool(holidays and holidays.get(day.isoformat()))


def is_peak_hour(local_dt: datetime, ranges: Sequence[tuple[int, int]]) -> bool:
    """当前本地小时是否落在任一区间内（左闭右开）。"""
    h = local_dt.hour
    return any(start <= h < end for start, end in ranges)


def next_switch(local_dt: datetime, ranges: Sequence[tuple[int, int]],
                weekdays: Iterable[int] = DEFAULT_WEEKDAYS,
                holidays: Optional[dict[str, bool]] = None) -> datetime:
    """返回本地时区下「下一次状态翻转」的时刻（峰值↔谷值切换）。

    倒计时语义与展示口径一致：
    - 高峰中（且今天是工作日）→ 当前所在区间的结束时刻（end=24 视为次日 00:00）
    - 空闲/周末/节假日 → 下一个「工作日」的第一个区间起点（最多向后找 21 天）

    找不到任何切换点时返回 local_dt。
    """
    if not ranges:
        return local_dt
    weekdays = tuple(weekdays)
    work_today = is_workday(local_dt.date(), weekdays, holidays)
    if work_today and is_peak_hour(local_dt, ranges):
        # 当前所在区间取最晚的 end（容忍重叠区间配置）；end=24 → 次日 00:00
        cur_end = max(e for s, e in ranges if s <= local_dt.hour < e)
        if cur_end >= 24:
            return datetime.combine(local_dt.date() + timedelta(days=1),
                                    datetime.min.time()).replace(
                tzinfo=local_dt.tzinfo)
        return local_dt.replace(hour=cur_end, minute=0, second=0, microsecond=0)
    # 空闲/周末/节假日：找下一个工作日的第一个区间起点
    starts = sorted({s for s, _ in ranges})
    for offset in range(_MAX_LOOKAHEAD_DAYS + 1):
        day = local_dt.date() + timedelta(days=offset)
        if not is_workday(day, weekdays, holidays):
            continue
        day_starts = starts if offset > 0 else [s for s in starts if s > local_dt.hour]
        if day_starts:
            return datetime.combine(day, datetime.min.time()).replace(
                hour=day_starts[0], minute=0, second=0, microsecond=0,
                tzinfo=local_dt.tzinfo)
    return local_dt


def classify(local_dt: datetime, cfg: dict,
             holidays: Optional[dict[str, bool]] = None) -> dict:
    """核心判定入口。

    参数：
        local_dt: 本地时区的 datetime（必须带 tzinfo）
        cfg: providers.json 中 parser.peakWindow 的配置块
        holidays: 可选的节假日表 {ISO 日期: 是否放假}（见 load_holidays）；
                  为 None 时只按 weekdays 规则判定

    返回：
        {
          "is_peak": bool,
          "label": str,                  # 直接展示文本（如 "⚡高峰"）
          "window_str": str,             # 当前所在时段的人类可读描述（高峰/空闲/周末/节假日）
          "tz": str,                     # 实际使用的时区名
          "next_switch_local": datetime, # 下一次切换的本地时刻
          "seconds_to_switch": int,      # 距下次切换的秒数（≥0）
          "is_holiday": bool,            # 当前是否法定节假日/调休放假
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

    is_work = is_workday(local_dt.date(), weekdays, holidays)
    on_holiday = is_holiday(local_dt.date(), holidays)
    in_window = is_peak_hour(local_dt, ranges)
    is_peak = is_work and in_window

    # window_str：单行紧凑文案，直接由 token_eye 渲染（详见 token_eye.render_menu 集成）
    # - 高峰 → "高峰 距空闲 {countdown}"  （到当前高峰段结束 = 距空闲）
    # - 工作日空闲 → "空闲 距高峰 {countdown}"（到下一个峰段开始 = 距高峰）
    # - 周末 → "周末 距高峰 {countdown}"；节假日 → "节假日 距高峰 {countdown}"
    if is_peak:
        label = peak_label
        window_str = "高峰"
    elif not is_work:
        label = off_label
        window_str = "节假日" if on_holiday else "周末"
    else:
        # 调休上班的周末也走这里：算工作日，非时段内即「空闲」
        label = off_label
        window_str = "空闲"

    nxt = next_switch(local_dt, ranges, weekdays, holidays)
    seconds = max(0, int((nxt - local_dt).total_seconds()))

    return {
        "is_peak": is_peak,
        "label": label,
        "window_str": window_str,
        "is_holiday": on_holiday,
        # 无 zoneinfo（Py3.8-）时 tz 是固定偏移对象，无 .key；展示请求的 tz 名保持一致
        "tz": (tz.key if hasattr(tz, "key") else str(tz)) if not _NO_ZONEINFO else tz_name,
        "next_switch_local": nxt,
        "seconds_to_switch": seconds,
    }


def format_countdown(seconds: int) -> str:
    """把秒数格式化成简短剩余时间文案。

    取两级单位（够短又够读）：
    - ≥ 1 天 → `6d9h`（整点时省略小时 → `6d`）；跨整段假期时 `153h18m` 这种没法读
    - < 1 天 → `1h30m` / `2h` / `45m`（分钟为 0 时省略）
    """
    if seconds <= 0:
        return ""
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h >= 24:
        d, hh = divmod(h, 24)
        return f"{d}d{hh}h" if hh else f"{d}d"
    if h and m:
        return f"{h}h{m}m"
    if h:
        return f"{h}h"
    return f"{m}m"
