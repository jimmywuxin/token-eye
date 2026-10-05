#!/usr/bin/python3
"""
Token Eye — 跨端配置同步校验（零依赖，纯标准库）。

背景：Android 端读的是 `android/app/src/main/assets/` 下的**手工副本**，
macOS / Linux 直接读项目根目录。改了根配置忘了同步 → 手机上的 App 一直跑旧规则
（DeepSeek 峰谷时段、配色、告警阈值都可能悄悄不同步），且没有任何检查兜底。

校验两处副本：
  1. `providers.json` ↔ `android/app/src/main/assets/providers.json`
     允许的**唯一**差异：带 `refreshParam` 的 provider 在 Android 侧被剔除
     （Cookie 刷新依赖浏览器会话，无法移植，见 android/README.md「已知差异」）。
  2. `holidays/<年>.json` ↔ `android/app/src/main/assets/holidays/<年>.json`
     文件集合与内容都必须一致（`make holidays` 更新后要手工拷贝，新增年份同理）。

用法:
  /usr/bin/python3 scripts/check-config-sync.py

退出码: 0 = 同步；1 = 不一致（供 Makefile / CI 使用）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "android", "app", "src", "main", "assets")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _changed_paths(expected, actual, prefix=""):
    """列出取值不同的叶子路径（dict 逐层展开成 a.b.c，list/标量当叶子）。"""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out = []
        for k in sorted(set(expected) | set(actual)):
            out += _changed_paths(expected.get(k), actual.get(k),
                                  f"{prefix}.{k}" if prefix else k)
        return out
    return [] if expected == actual else [prefix or "(整体)"]


def check_providers(providers_path, android_path, errors):
    """providers.json ↔ assets 副本；带 refreshParam 的平台在 Android 侧应缺失。"""
    root = _load(providers_path)
    android = _load(android_path)
    expected = {p["id"]: p for p in root.get("providers", [])
                if not p.get("refreshParam")}
    actual = {p["id"]: p for p in android.get("providers", []) if p.get("id")}

    for pid in sorted(set(expected) - set(actual)):
        errors.append(f"assets/providers.json 缺少 provider「{pid}」")
    for pid in sorted(set(actual) - set(expected)):
        errors.append(f"assets/providers.json 多出 provider「{pid}」（根目录没有，Android 不该自造平台）")
    for pid in sorted(set(expected) & set(actual)):
        for path in _changed_paths(expected[pid], actual[pid]):
            errors.append(f"provider「{pid}」的 {path} 与根目录不一致")
    top_root = {k: v for k, v in root.items() if k != "providers"}
    top_android = {k: v for k, v in android.items() if k != "providers"}
    for path in _changed_paths(top_root, top_android):
        errors.append(f"providers.json 顶层「{path}」与 assets 副本不一致")


def _json_files(d):
    try:
        return {f for f in os.listdir(d) if f.endswith(".json")}
    except FileNotFoundError:
        return None


def check_holidays(src_dir, dst_dir, errors):
    """holidays/*.json ↔ assets/holidays/*.json：文件集合 + 逐字节内容。"""
    src, dst = _json_files(src_dir), _json_files(dst_dir)
    if src is None:
        errors.append(f"缺少节假日目录 {src_dir}")
        return
    if dst is None:
        errors.append(f"缺少 Android 节假日目录 {dst_dir}（把 holidays/ 下的 .json 拷过去）")
        return
    for name in sorted(src - dst):
        errors.append(f"assets/holidays 缺少 {name}（make holidays 更新后需手工拷贝）")
    for name in sorted(dst - src):
        errors.append(f"assets/holidays 多出 {name}（根目录没有）")
    for name in sorted(src & dst):
        with open(os.path.join(src_dir, name), "rb") as a, \
                open(os.path.join(dst_dir, name), "rb") as b:
            if a.read() != b.read():
                errors.append(f"节假日数据 {name} 与根目录内容不一致（make holidays 更新后需手工拷贝）")


def check(providers_path=None, assets_dir=ASSETS):
    """返回错误列表（空 = 三端配置同步）。路径可传，便于单测用临时目录。"""
    providers_path = providers_path or os.path.join(ROOT, "providers.json")
    errors = []
    check_providers(providers_path, os.path.join(assets_dir, "providers.json"), errors)
    check_holidays(os.path.join(os.path.dirname(providers_path), "holidays"),
                   os.path.join(assets_dir, "holidays"), errors)
    return errors


def main():
    try:
        errors = check()
    except (OSError, json.JSONDecodeError) as e:
        print(f"❌ 配置读取失败: {e}")
        return 1
    if errors:
        print(f"❌ 跨端配置不同步（{len(errors)} 处）—— 改根目录配置后需同步到 Android assets：")
        for e in errors:
            print(f"  - {e}")
        return 1
    n = len(_load(os.path.join(ROOT, "providers.json")).get("providers", []))
    print(f"✅ 跨端配置同步（providers.json ↔ assets，holidays ↔ assets/holidays；{n} 个 provider）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
