#!/usr/bin/env python3
"""
Token Eye — Linux keyring 诊断与修复（桌面运行）
用法：python3 linux/diag-keyring.py
在【桌面终端】运行（不要在该 AI 沙箱里跑），因为它需要连你登录会话的 DBus。
会依次：
  1) 尝试解锁默认钥匙环（自动解锁则直接成功，无需输入）
  2) 列出 3 个 token-eye key 是否存在
  3) 若存在但不完整 → 提示补写
  4) 全程不打印 key 明文
"""
import sys
import os

os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", "")

def die(msg):
    print(f"\n❌ {msg}")
    sys.exit(1)

SERVICES = [
    ("DEEPSEEK_API_KEY", "DeepSeek 余额监控（Bearer key）"),
    ("MINIMAX_CN_API_KEY", "MiniMax 用量监控（Bearer key）"),
    ("MIMO_PLATFORM_TOKEN", "MiMo 余额监控（完整 Cookie 串）"),
]

try:
    import secretstorage
except ImportError:
    die("缺 python3-secretstorage，先装：sudo apt install python3-secretstorage")

# ---- 1) 连 bus ----
try:
    bus = secretstorage.dbus_init()
except Exception as e:
    print(f"⚠️ 连不上 DBus session bus（{e}）")
    print("  原因：此脚本必须在桌面终端跑；或登录会话的 DBus 没起来。")
    print("  若你是 SSH/远程终端，无法访问桌面 keyring。")
    sys.exit(1)

# ---- 2) 默认集合 + 解锁 ----
coll = secretstorage.get_default_collection(bus)
if coll is None:
    die("无法访问默认钥匙环集合（gnome-keyring 未启动？）")

if coll.is_locked():
    print("🔒 默认钥匙环处于【锁定】状态 —— 这通常就是托盘读不到 key 的原因。")
    print("   正在尝试解锁（若设置了登录自动解锁，将无感成功）…")
    try:
        ok = coll.unlock()
        if ok:
            print("✅ 解锁成功")
        else:
            print("❌ 解锁被取消/失败 —— 需要在桌面的密钥弹窗输入钥匙环密码。")
            print("   提示：可在 Seahorse(密钥) 里把默认钥匙环密码设为「空/与登录一致」实现开机自动解锁。")
    except Exception as e:
        print(f"❌ 解锁异常：{e}")
        print("   若频繁要求密码，建议：seahorse → 右键默认钥匙环 → 更改密码 → 设为与登录密码相同（自动解锁）。")
else:
    print("✅ 默认钥匙环已解锁")

# ---- 3) 逐个列出 key ----
print("\n已配置的 Token Eye 密钥：")
found = []
for svc, desc in SERVICES:
    try:
        items = list(coll.search_items({"service": svc}))
        if items:
            sec = items[0].get_secret()
            n = len(sec) if sec else 0
            print(f"  ✅ {svc:20s} 存在（{n} 字符）  {desc}")
            found.append(svc)
        else:
            print(f"  ❌ {svc:20s} 缺失              {desc}")
    except Exception as e:
        print(f"  ⚠️ {svc:20s} 查询出错：{e}")

# ---- 4) 结论 ----
print()
if len(found) == len(SERVICES):
    print("🎉 全部 3 个 key 都已就位且钥匙环已解锁。")
    print("   → 托盘仍读不到？手动重启一次托盘：")
    print("     systemctl --user restart token-eye.service    （若之前用的是 systemd）")
    print("     或直接：python3 ~/dev/token-eye/linux/token-eye-tray.py")
elif found:
    print(f"⚠️ 部分 key 缺失（已有 {len(found)} 个）。")
    print("   补写：python3 ~/dev/token-eye/linux/setup-keys.py")
else:
    print("⚠️ 3 个 key 全部缺失 —— 需要重新写入。")
    print("   逐个写入：python3 ~/dev/token-eye/linux/setup-keys.py DEEPSEEK_API_KEY")
    print("   回车跳过交互即可逐条填。MiMo 建议登录平台后跑 scripts/refresh-mimo-cookie.py 自动提取。")
