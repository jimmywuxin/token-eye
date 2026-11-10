#!/usr/bin/env python3
"""
update-holidays.py — 更新内置的中国法定节假日 / 调休表（零依赖，纯标准库）。

为什么需要它
------------
峰谷判定里的「法定节假日全天空闲、调休上班的周末按工作日算」没有算法规律：
放假与调休安排由国务院**逐年公告**（通常在上一年的 11-12 月，如 2026 年安排见于
gov.cn 2025-11 的《关于 2026 年部分节假日安排的通知》）。所以只能查表，
本脚本负责把表拉下来放进 `holidays/<年>.json`。

数据源：NateScarlet/holiday-cn（逐条对照 gov.cn 公告维护，含调休上班日）。
GitHub 直连国内常不通，脚本按顺序尝试直连 + 国内镜像，任一成功即用。

用法：
    python3 scripts/update-holidays.py            # 更新 今年 + 明年（明年通常尚未公告）
    python3 scripts/update-holidays.py 2027       # 指定年份
    make holidays                                 # 同上（包装）

退出码语义（与旧版「失败也 exit 0」不同）：
  * 上游合法但 days 为空（尚未公告）→ 打印「未生成 <年>.json（未公告）」警告，可 exit 0；
  * 下载全部失败 / 数据校验不通过（非法 JSON、年份不符、日期越界、投毒）→ **非 0**；
  * 必需年份（显式指定 / 当年）既无上游数据又无本地文件 → 非 0。
新一年公告后跑一次即可；缺失年份会自动退化为「周一至周五 + 时段」判定，
不会报错、不影响余额显示。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLIDAY_DIR = os.path.join(REPO_ROOT, "holidays")

RAW = "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json"
# 与 token-eye.sh 一键升级同样的国内镜像（前缀式代理）
MIRRORS = ("https://gh-proxy.com/", "https://ghfast.top/", "https://ghproxy.net/")
TIMEOUT = 20


def sources(year: int):
    yield RAW.format(year=year)
    for m in MIRRORS:
        yield m + RAW.format(year=year)


def fetch(year: int):
    """返回 (原始字节, 命中的 URL)；全部失败返回 (None, 最后一次错误说明)。"""
    last = ""
    for url in sources(year):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "token-eye"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read(), url
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
    return None, last


def validate(raw: bytes, year: int):
    """返回 (status, 说明)，status ∈ {"ok", "not_announced", "invalid"}。

    * not_announced：上游合法但 days 为空（该年份尚未公告）—— 允许 exit 0；
    * invalid：数据不可用（非法 JSON / 年份不符 / 日期越界 / 投毒）—— 必须非 0；
    * ok：可写入。

    年份与日期归属校验用于防止「错年份文件」或投毒数据被写入 holidays/<年>.json
    （旧版只校验 JSON 合法与 days 非空，年份字段与日期前缀完全不看）。
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return "invalid", f"不是合法 JSON（{e}）"
    if not isinstance(data, dict):
        return "invalid", "顶层不是 JSON 对象"
    # year 字段必须与目标年份一致（容忍数字/字符串两种写法）；否则疑似错年份/投毒数据
    if str(data.get("year")) != str(year):
        return "invalid", (f"数据 year={data.get('year')!r} 与目标 {year} 不符"
                           f"（疑似错年份/投毒数据，拒绝写入）")
    days = data.get("days") or []
    if not isinstance(days, list):
        return "invalid", "days 不是数组"
    if not days:
        return "not_announced", "days 为空（该年份可能尚未公告）"
    prefix = f"{year}-"
    for d in days:
        if not isinstance(d, dict):
            return "invalid", "days 含非对象元素"
        date = d.get("date")
        if not isinstance(date, str) or not date.startswith(prefix):
            return "invalid", (f"日期 {date!r} 不属于 {year} 年"
                               f"（疑似错年份/投毒数据，拒绝写入）")
    off = sum(1 for d in days if d.get("isOffDay"))
    return "ok", f"{len(days)} 条（放假 {off} 天 / 调休上班 {len(days) - off} 天）"


def update(year: int, required: bool):
    """返回 (是否成功, 状态)。状态 ∈ generated / latest / not_announced / failed。

    关键：把「上游尚未公告」与「下载/校验失败」分开——只有前者允许 exit 0，
    后者一律非 0。旧版用 fallback = (not required) or 本地已有文件 把两类都吞成成功。
    """
    path = os.path.join(HOLIDAY_DIR, f"{year}.json")
    has_local = os.path.isfile(path)
    raw, info = fetch(year)
    if raw is None:
        # 下载全失败：即使本地已有数据也不静默成功（断网沿用旧数据必须让用户看见）
        print(f"❌ {year}：下载失败（{info}）"
              + ("，本地已有数据但未更新" if has_local else "，本地无数据"))
        return False, "failed"
    status, detail = validate(raw, year)
    if status == "not_announced":
        if required and not has_local:
            print(f"❌ {year} 是必需年份：上游尚未公告（{detail}），且无本地文件，"
                  f"无法生成 {year}.json")
            return False, "failed"
        print(f"⚠️ 未生成 {year}.json（未公告：{detail}）"
              + ("，沿用本地已有数据" if has_local else "，节假日判定将退化为纯 weekdays"))
        return True, "not_announced"
    if status == "invalid":
        print(f"❌ {year}：数据校验失败（{detail}），未写入"
              + ("，沿用本地已有数据" if has_local else ""))
        return False, "failed"
    os.makedirs(HOLIDAY_DIR, exist_ok=True)
    old = ""
    if has_local:
        with open(path, "rb") as f:
            old = f.read().decode("utf-8", "replace")
    changed = old.strip() != raw.decode("utf-8", "replace").strip()
    with open(path, "wb") as f:
        f.write(raw)
    print(f"{'✅ 更新' if changed else '✅ 已是最新'} {path} — {detail}")
    return True, "generated" if changed else "latest"


def main(argv):
    explicit = [a for a in argv[1:] if a.isdigit()]
    years = [int(y) for y in explicit] or [datetime.now().year, datetime.now().year + 1]
    ok = True
    for y in years:
        # 显式指定 / 当年 → 视为必需年份（缺数据必须非 0）；默认的「明年」多半尚未公告
        required = bool(explicit) or y == datetime.now().year
        year_ok, _state = update(y, required)
        ok = year_ok and ok
    # 打印实际生成 / 已存在的文件清单，避免「静默成功」却不知道产出了什么
    try:
        present = sorted(f for f in os.listdir(HOLIDAY_DIR) if f.endswith(".json"))
    except FileNotFoundError:
        present = []
    print(f"📁 holidays/ 实际文件清单（{len(present)} 个）："
          + ("、".join(present) if present else "（空）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
