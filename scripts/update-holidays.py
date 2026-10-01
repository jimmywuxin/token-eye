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
    """返回 (ok, 说明)：必须是合法 JSON 且含当年 days 列表。"""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return False, f"不是合法 JSON（{e}）"
    days = data.get("days") or []
    if not days:
        return False, "days 为空（该年份可能尚未公告）"
    off = sum(1 for d in days if d.get("isOffDay"))
    return True, f"{len(days)} 条（放假 {off} 天 / 调休上班 {len(days) - off} 天）"


def update(year: int, required: bool) -> bool:
    path = os.path.join(HOLIDAY_DIR, f"{year}.json")
    # 已有本地文件时，下载失败只提示不改动（exit 0），避免断网时误报失败
    fallback = (not required) or os.path.isfile(path)
    raw, info = fetch(year)
    if raw is None:
        print(f"{'⚠️ ' if fallback else '❌ '} {year}：下载失败（{info}）"
              + ("，沿用本地已有数据" if os.path.isfile(path) else ""))
        return fallback
    ok, detail = validate(raw, year)
    if not ok:
        print(f"{'⚠️ ' if fallback else '❌ '} {year}：数据不可用（{detail}）")
        return fallback
    os.makedirs(HOLIDAY_DIR, exist_ok=True)
    old = ""
    if os.path.isfile(path):
        with open(path, "rb") as f:
            old = f.read().decode("utf-8", "replace")
    changed = old.strip() != raw.decode("utf-8", "replace").strip()
    with open(path, "wb") as f:
        f.write(raw)
    print(f"{'✅ 更新' if changed else '✅ 已是最新'} {path} — {detail}")
    return True


def main(argv):
    explicit = [a for a in argv[1:] if a.isdigit()]
    years = [int(y) for y in explicit] or [datetime.now().year, datetime.now().year + 1]
    ok = True
    for y in years:
        # 显式指定 / 当年 → 失败视为错误；默认的「明年」（多半尚未公告）→ 仅提示
        required = bool(explicit) or y == datetime.now().year
        ok = update(y, required) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
