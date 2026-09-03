#!/usr/bin/env python3
"""
Token Eye — Linux 密钥管理（gnome-keyring / secretstorage）

把三个平台的 API Key / Cookie 写入系统钥匙环（替代 macOS Keychain）：
  - DeepSeek   → DEEPSEEK_API_KEY      (Bearer key，platform.deepseek.com → API Keys)
  - MiniMax    → MINIMAX_CN_API_KEY    (Bearer key，platform.minimaxi.com → 开发设置)
  - MiMo       → MIMO_PLATFORM_TOKEN   (完整 Cookie 串，先登录 platform.xiaomimimo.com
                                        再运行 scripts/refresh-mimo-cookie.py 自动提取)

用法：
  python3 setup-keys.py            # 交互式逐个设置
  python3 setup-keys.py --list     # 列出已配置的 key（只显示是否存在，不泄露内容）
  python3 setup-keys.py DEEPSEEK_API_KEY  # 只设置指定 service
"""
import getpass
import os
import sys

SERVICES = [
    ("DEEPSEEK_API_KEY", "DeepSeek 余额监控（Bearer key）"),
    ("MINIMAX_CN_API_KEY", "MiniMax 用量监控（Bearer key）"),
    ("MIMO_PLATFORM_TOKEN", "MiMo 余额监控（完整 Cookie 串，或用刷新脚本自动填）"),
]


def get_collection():
    import secretstorage
    bus = secretstorage.dbus_init()
    coll = secretstorage.get_default_collection(bus)
    if coll is None:
        print("❌ 无法访问 gnome-keyring 默认集合（是否未启动/未解锁？）")
        sys.exit(1)
    if coll.is_locked():
        print("🔒 钥匙环已锁定，尝试解锁…")
        ok = coll.unlock()
        if not ok:
            print("❌ 解锁失败")
            sys.exit(1)
    return coll


def list_keys():
    coll = get_collection()
    print("已配置的 Token Eye 密钥：")
    for svc, desc in SERVICES:
        items = list(coll.search_items({"service": svc}))
        print(f"  {'✅' if items else '❌'} {svc:24s} {desc}")
    print("\n提示：secretstorage 按 attribute service=<名> 存储，与 tray 读取一致。")


def set_key(coll, svc, secret):
    """删除旧条目再写入（保证唯一）。"""
    for it in list(coll.search_items({"service": svc})):
        try:
            it.delete()
        except Exception:
            pass
    coll.create_item(
        svc,
        {"service": svc, "application": "token-eye"},
        secret,
        replace=True,
    )


def set_one(svc, desc):
    coll = get_collection()
    print(f"\n=== {svc} ===\n{desc}")
    # 显示当前状态
    cur = list(coll.search_items({"service": svc}))
    if cur:
        print(f"当前已配置（将覆盖）。")
    else:
        print("当前未配置。")
    val = input("  粘贴密钥/Cookie（直接回车 = 跳过）: ").strip()
    if not val:
        print("  已跳过")
        return False
    set_key(coll, svc, val)
    # 验证读回
    back = list(coll.search_items({"service": svc}))
    ok = bool(back) and bool(back[0].get_secret())
    print(f"  {'✅ 写入成功' if ok else '❌ 写入失败'}")
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--list" in sys.argv:
        list_keys()
        return 0
    if args:
        svc = args[0]
        for s, d in SERVICES:
            if s == svc:
                set_one(s, d)
                return 0
        print(f"❌ 未知 service: {svc}，可选: {', '.join(s for s, _ in SERVICES)}")
        return 1
    # 交互式全部
    print("Token Eye 密钥设置（写入 gnome-keyring）")
    print("按回车跳过任意一项；Ctrl+C 随时退出\n")
    coll = get_collection()
    try:
        for svc, desc in SERVICES:
            cur = list(coll.search_items({"service": svc}))
            state = "已配置" if cur else "未配置"
            val = input(f"[{state}] {svc} — {desc}\n  粘贴值（回车跳过）: ").strip()
            if val:
                set_key(coll, svc, val)
                print("  ✅ 已写入")
    except (KeyboardInterrupt, EOFError):
        print("\n已中断")
        return 130
    print("\n完成。运行 tray 自检确认：")
    print("  python3 ~/dev/token-eye/linux/token-eye-tray.py --check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
