#!/usr/bin/env python3
"""Token Eye — Linux 钥匙环公共逻辑（解锁语义统一，P0-3）。

背景：三个脚本对 secretstorage.Collection.unlock() 返回值的解读互相矛盾——
  - token-eye-tray.py 旧注释/单测：True=用户取消 / False=解锁成功
  - setup-keys.py 旧代码：ok = unlock(); if not ok → 判失败（成功 False 被误判）
  - diag-keyring.py 旧代码：ok = unlock(); if ok → 判成功（与 tray 完全相反）
目标机（银河麒麟）所用 secretstorage 版本的 unlock() 返回语义无法离线确认，
因此**一律不靠返回值判定成败**：解锁调用后统一用 coll.is_locked() 复核。
is_locked() 是唯一可靠的事实来源，这样无论 unlock() 返回 True/False 各自代表
什么，结论都正确，三处口径自然一致。

本模块只提供两个薄封装；secretstorage 延迟到函数内导入，便于在无 D-Bus 环境
下被单测以合成模块名加载（不污染 sys.modules）。
"""


def open_collection():
    """连接会话 D-Bus 并取默认钥匙环集合，不解锁、不弹框。

    返回 (coll, err)：成功时 err=""，失败时 coll=None 且 err 为可读原因。
    各脚本（setup-keys.py / diag-keyring.py / tray）负责各自的错误呈现。
    """
    try:
        import secretstorage
    except Exception as e:
        return None, f"无法导入 secretstorage：{e}"
    try:
        bus = secretstorage.dbus_init()
    except Exception as e:
        return None, f"连不上 DBus session bus：{e}"
    try:
        coll = secretstorage.get_default_collection(bus)
    except Exception as e:
        return None, f"读取默认钥匙环集合失败：{e}"
    if coll is None:
        return None, "无法访问 gnome-keyring 默认集合（未启动/未解锁？）"
    return coll, ""


def unlock_and_verify(coll):
    """解锁钥匙环，并用 is_locked() 复核判定成败——**不依赖 unlock() 返回值语义**。

    返回 (ok, msg)：
      - 本来就是解锁态        → (True, "")，且不会调用 unlock()
      - unlock() 抛异常        → (False, "解锁调用失败: ...")
      - unlock() 后仍锁定      → (False, "仍未解锁（密码不对/已取消）")
      - unlock() 后已解锁      → (True, "")

    unlock() 的返回值被刻意忽略：不同 secretstorage 版本语义相反（True 可能
    代表「已取消」，也可能代表「成功」），据此判断必然在某一版本上出错。
    """
    try:
        if not coll.is_locked():
            return True, ""
    except Exception as e:
        return False, f"读取钥匙环状态失败: {e}"
    try:
        coll.unlock()   # 返回值语义不确定，刻意不接收
    except Exception as e:
        return False, f"解锁调用失败: {e}"
    try:
        if coll.is_locked():
            return False, "仍未解锁（密码不对/已取消）"
    except Exception as e:
        return False, f"复核钥匙环状态失败: {e}"
    return True, ""
