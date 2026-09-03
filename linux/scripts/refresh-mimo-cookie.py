#!/usr/bin/python3
"""
Token Eye — MiMo Cookie 刷新工具（Linux / gnome-keyring 版）

从 Linux 的 Chromium 系浏览器（Edge / Chrome / Chromium）任一已登录的
Cookie 数据库提取 MiMo platform 的 4 个 Cookie（api-platform_ph /
api-platform_serviceToken / api-platform_slh / userId），解密后拼成完整
Cookie 串，写入 gnome-keyring（service=MIMO_PLATFORM_TOKEN，与 tray 的
linux_get_key 读取一致），并调 balance API 验证。

用法:
  python3 refresh-mimo-cookie.py

前置条件:
  - 任一受支持浏览器中已登录 platform.xiaomimimo.com（保持窗口打开）
  - gnome-keyring 已解锁

与 macOS 原版的差异:
  - 浏览器数据目录: ~/.config/{microsoft-edge,google-chrome,chromium}
  - 加密密码来源: gnome-keyring（application=chromium/chrome/microsoft-edge）
  - PBKDF2 iterations: Linux Chromium = 1（macOS = 1003）
  - 写入目标: gnome-keyring（service=MIMO_PLATFORM_TOKEN）
  - cookie 值布局自适应: v10+iv+ct（Linux）与 v10+salt+iv+ct（macOS）均兼容
"""
import os
import sys
import time
import sqlite3
import shutil
import glob
import subprocess

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

KEYCHAIN_SERVICE = "MIMO_PLATFORM_TOKEN"
HOST_FILTER = "%xiaomimimo%"
REQUIRED = ["api-platform_ph", "api-platform_serviceToken", "api-platform_slh", "userId"]
COOKIE_SUFFIXES = ("", "-wal", "-shm", "-journal")
CACHE_FILE = os.path.expanduser("~/.cache/token-eye/token-eye-cache-mimo.json")

# Linux Chromium 系浏览器：Cookie 库路径 + gnome-keyring 密码条目属性
# 注意：Edge Linux 用 application=chromium（不是 microsoft-edge），与 Chromium 共享同一条 keyring
BROWSERS = [
    {"name": "Edge", "db": "~/.config/microsoft-edge",
     "app": "chromium", "label": "Chromium Safe Storage"},
    {"name": "Chrome", "db": "~/.config/google-chrome",
     "app": "chrome", "label": "Chrome Safe Storage"},
    {"name": "Chromium", "db": "~/.config/chromium",
     "app": "chromium", "label": "Chromium Safe Storage"},
]


def get_safe_storage_password(app, label):
    """从 gnome-keyring 读浏览器加密密码：优先 application 属性，兜底 label 匹配。"""
    try:
        import secretstorage
        bus = secretstorage.dbus_init()
        coll = secretstorage.get_default_collection(bus)
        if coll is None or coll.is_locked():
            return None
        # 1) application 属性精确匹配
        for item in coll.search_items({"application": app}):
            s = item.get_secret()
            if s:
                return s.decode("utf-8", "replace")
        # 2) label 关键字匹配（某些发行版属性名不同）
        for item in coll.get_all_items():
            try:
                if item.get_label() == label:
                    s = item.get_secret()
                    if s:
                        return s.decode("utf-8", "replace")
            except Exception:
                continue
    except Exception as e:
        print(f"警告: gnome-keyring 读取失败: {e}")
    return None


def derive_key(password, iterations):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=16,
                     salt=b"saltysalt", iterations=iterations,
                     backend=default_backend())
    return kdf.derive(password.encode())


def decrypt_cookie(enc, password):
    """Chromium cookie 解密，自适应两种格式：
       A) Linux Chrome/Edge/Chromium v10/v11: vNN(3) + AES-CBC 密文
          固定 IV = 16 个空格(0x20)，PBKDF2 iter=1（实测 Edge Linux v11 有效，HTTP 200）
       B) macOS Chrome/Edge v10: v10(3) + salt(16) + iv(16) + 密文，PBKDF2 iter=1003
    注意：不能把 enc[3:19] 当 per-cookie IV——CBC 下那样会静默解出「后半段明文」，
    padding 校验照样通过，属最阴险的错法，故不列入候选。
    """
    if not enc or enc[:2] != b"v1" or not enc[2:3].isdigit():
        return None
    plans = []
    ct_a = enc[3:]
    if len(ct_a) >= 16 and len(ct_a) % 16 == 0:
        plans.append((1, b"\x20" * 16, ct_a))          # A) Linux 固定 IV
    if len(enc) > 35:
        plans.append((1003, enc[19:35], enc[35:]))     # B) macOS 布局
    for iterations, iv, ct in plans:
        try:
            key = derive_key(password, iterations)
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            d = cipher.decryptor()
            pt = d.update(ct) + d.finalize()
            pad = pt[-1]
            if not (1 <= pad <= 16 and len(pt) >= pad
                    and pt[-pad:] == bytes([pad]) * pad):
                continue
            return pt[:-pad].decode("ascii", "replace")
        except Exception:
            continue
    return None


def copy_cookie_db(db_path):
    tmp = "/tmp/te_cookies_tmp.db"
    for suffix in COOKIE_SUFFIXES:
        src, dst = db_path + suffix, tmp + suffix
        try:
            if os.path.exists(src):
                shutil.copy2(src, dst)
            elif os.path.exists(dst):
                os.unlink(dst)
        except OSError as e:
            print(f"警告: 拷贝 {os.path.basename(src) or 'Cookies'} 失败: {e}")
    return tmp


def extract_cookie_rows(db_path):
    tmp = copy_cookie_db(db_path)
    rows = None
    try:
        conn = sqlite3.connect(tmp)
        try:
            rows = conn.execute(
                "SELECT host_key, name, encrypted_value FROM cookies WHERE host_key LIKE ?",
                (HOST_FILTER,)).fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        print(f"警告: Cookie 库读取失败: {e}")
    finally:
        for suffix in COOKIE_SUFFIXES:
            try:
                if os.path.exists(tmp + suffix):
                    os.unlink(tmp + suffix)
            except OSError:
                pass
    return rows


def find_cookie_dbs(browser):
    base = os.path.expanduser(browser["db"])
    out = []
    for pat in ("Default", "Profile *"):
        for p in sorted(glob.glob(os.path.join(base, pat, "Cookies"))):
            out.append(p)
    return out


def try_extract(browser):
    password = get_safe_storage_password(browser["app"], browser["label"])
    if password is None:
        return None
    for db_path in find_cookie_dbs(browser):
        for attempt in (1, 2):
            rows = extract_cookie_rows(db_path)
            if not rows:
                break
            cookies = {}
            for host, name, enc in rows:
                if name in cookies:
                    continue
                try:
                    v = decrypt_cookie(enc, password)
                    if v is not None:
                        cookies[name] = v
                except Exception as e:
                    print(f"警告: [{browser['name']}] {name} 解密失败: {e}")
            missing = [c for c in REQUIRED if c not in cookies]
            if not missing:
                return browser["name"], cookies
            if attempt == 1:
                time.sleep(0.8)
    return None


def store_keyring(cookie_str):
    """写入 gnome-keyring：service=MIMO_PLATFORM_TOKEN（与 tray linux_get_key 一致）。"""
    import secretstorage
    bus = secretstorage.dbus_init()
    coll = secretstorage.get_default_collection(bus)
    if coll is None or coll.is_locked():
        return False
    for it in list(coll.search_items({"service": KEYCHAIN_SERVICE})):
        try:
            it.delete()
        except Exception:
            pass
    coll.create_item(KEYCHAIN_SERVICE,
                     {"service": KEYCHAIN_SERVICE, "application": "token-eye"},
                     cookie_str, replace=True)
    back = list(coll.search_items({"service": KEYCHAIN_SERVICE}))
    return bool(back) and bool(back[0].get_secret())


def main():
    found = None
    tried = []
    for browser in BROWSERS:
        tried.append(browser["name"])
        result = try_extract(browser)
        if result:
            found = result
            break
    if not found:
        sys.exit(f"错误: 未找到完整 Cookie（已尝试 {', '.join(tried)}）。"
                 f"请先在任一浏览器登录 platform.xiaomimimo.com（保持窗口打开），"
                 f"并确认 gnome-keyring 未锁，再重试")

    browser_name, cookies = found
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    print(f"提取成功（来源: {browser_name}）: 完整 Cookie 串 {len(cookie_str)} 字符")

    if not store_keyring(cookie_str):
        sys.exit("gnome-keyring 写入失败（MIMO_PLATFORM_TOKEN）")
    print(f"已更新 gnome-keyring: {KEYCHAIN_SERVICE}")

    r2 = subprocess.run(
        ["curl", "-s", "--max-time", "8", "-w", "|HTTP:%{http_code}",
         "-H", "Cookie: " + cookie_str,
         "-H", "Accept: application/json",
         "-H", "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
         "https://platform.xiaomimimo.com/api/v1/balance"],
        capture_output=True, text=True)
    body = r2.stdout.rsplit("|HTTP:", 1)
    code = body[1] if len(body) > 1 else "?"
    print(f"balance API: HTTP={code}")
    if code == "200":
        try:
            os.unlink(CACHE_FILE)
        except OSError:
            pass
        print("✅ Cookie 有效，Token Eye 余额显示已可用")
    else:
        print(f"⚠️ HTTP {code}，Cookie 可能无效或过期: {body[0][:150]}")


if __name__ == "__main__":
    main()
