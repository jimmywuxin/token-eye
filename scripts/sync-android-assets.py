#!/usr/bin/env python3
"""Token Eye — 从根目录生成 Android assets 副本（零依赖，纯标准库）。

背景：Android 读 `android/app/src/main/assets/providers.json` 与 `assets/holidays/`，
历史上靠手工拷贝 + `check-config-sync.py` 事后校验。改根配置忘了拷 → 手机端
一直跑旧规则（2026-10-05 起靠校验脚本兜底）。本脚本把「拷贝」变成构建期动作：

  - Gradle `preBuild` 自动调用本脚本（见 android/app/build.gradle.kts）
  - `make validate` / CI 调用 `--check`（只读，不写文件）确认提交副本是最新的
  - 剔除口径与 scripts/check-config-sync.py 的 ANDROID_EXCLUDED **必须一致**，
    由 tests/test_android_assets_sync.py 断言，防止两份白名单漂移

内容无变化时不写文件，避免每次 Gradle 构建都把工作区弄脏。
用法:
  python3 scripts/sync-android-assets.py            # 生成/更新 assets 副本
  python3 scripts/sync-android-assets.py --check    # 只校验，落后则 exit 1
"""
import argparse
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "android", "app", "src", "main", "assets")

# 与 scripts/check-config-sync.py 的 ANDROID_EXCLUDED 同值（有单测钉住）：
# mimo 依赖浏览器会话 Cookie 刷新，qwen 是 command 型需执行外部 CLI，手机都无法移植。
ANDROID_EXCLUDED = {"mimo", "qwen"}


def generated_providers_text():
    with open(os.path.join(ROOT, "providers.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg = dict(cfg)
    cfg["providers"] = [p for p in cfg["providers"]
                        if p.get("id") not in ANDROID_EXCLUDED]
    # 与现有副本的序列化格式一致，保证 --check 是字节级比对
    return json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"


def sync(check=False):
    """返回 (变更列表, assets 多出的节假日文件)。check=True 时不写任何文件。"""
    changes = []

    target = os.path.join(ASSETS, "providers.json")
    text = generated_providers_text()
    current = ""
    if os.path.isfile(target):
        with open(target, encoding="utf-8") as f:
            current = f.read()
    if current != text:
        changes.append("providers.json")
        if not check:
            os.makedirs(ASSETS, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(text)

    src_dir = os.path.join(ROOT, "holidays")
    dst_dir = os.path.join(ASSETS, "holidays")
    src_files = {n for n in os.listdir(src_dir) if n.endswith(".json")}
    for name in sorted(src_files):
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        same = os.path.isfile(dst) and open(src, "rb").read() == open(dst, "rb").read()
        if not same:
            changes.append("holidays/" + name)
            if not check:
                os.makedirs(dst_dir, exist_ok=True)
                shutil.copyfile(src, dst)

    extra = []
    if os.path.isdir(dst_dir):
        extra = sorted(n for n in os.listdir(dst_dir)
                       if n.endswith(".json") and n not in src_files)
    return changes, extra


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="只校验提交副本是否与根目录一致，不写文件")
    args = ap.parse_args()
    try:
        changes, extra = sync(args.check)
    except (OSError, ValueError) as e:
        print(f"❌ assets 同步失败: {e}")
        return 1
    if extra:
        print("❌ assets/holidays 多出根目录没有的文件: " + ", ".join(extra))
        return 1
    if args.check:
        if changes:
            print("❌ Android assets 副本落后，需同步: " + ", ".join(changes))
            return 1
        print("✅ Android assets 副本已是最新（与根目录一致）")
        return 0
    if changes:
        print("✅ 已同步 Android assets: " + ", ".join(changes))
    else:
        print("✅ Android assets 副本无变化")
    return 0


if __name__ == "__main__":
    sys.exit(main())
