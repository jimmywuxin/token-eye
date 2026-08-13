#!/usr/bin/python3
"""
Token Eye — MiMo Cookie 刷新工具

从 Edge Cookie 数据库提取 MiMo platform 的 4 个 Cookie（api-platform_ph /
api-platform_serviceToken / api-platform_slh / userId），解密后拼成完整
Cookie 串，更新到 Keychain（MIMO_PLATFORM_TOKEN），并调 balance API 验证。

用法:
  /usr/bin/python3 scripts/refresh-mimo-cookie.py

前置条件:
  - Edge 中已登录 https://platform.xiaomimimo.com/（会话 Cookie 有效）
  - 系统 Python 3（/usr/bin/python3）自带 cryptography 库

说明:
  MiMo platform API 鉴权需要完整 Cookie（仅 serviceToken 会 401）。
  Cookie 是会话级，Edge 关闭或长时间不用后会失效，此时重跑本脚本刷新。
"""
import os, sys, time

# 防御：清理 WorkBuddy/Hermes/OpenClaw 注入的 PYTHONPATH 与 sys.path，
# 避免跨版本 venv 包（如 Hermes 的 python3.11 cryptography）污染导致 ImportError
os.environ.pop("PYTHONPATH", None)
os.environ.pop("PYTHONHOME", None)
sys.path = [p for p in sys.path if not any(x in p for x in (".hermes", ".openclaw"))]

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import sqlite3, subprocess, shutil

COOKIE_DB = os.path.expanduser("~/Library/Application Support/Microsoft Edge/Default/Cookies")
COOKIE_TMP = "/tmp/edge_cookies_tmp.db"
KEYCHAIN_SERVICE = "MIMO_PLATFORM_TOKEN"
HOST_FILTER = "%xiaomimimo%"
REQUIRED = ["api-platform_ph", "api-platform_serviceToken", "api-platform_slh", "userId"]
# 拷贝主库时要一起带的伴生文件：Edge 运行中时最新写入常在 -wal/-shm/-journal 里，
# 只拷主库会拿到过期快照（表现为「缺少 Cookie」或旧值 401）
COOKIE_SUFFIXES = ("", "-wal", "-shm", "-journal")


def get_safe_storage_key():
    pw = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", "Microsoft Edge Safe Storage"],
        capture_output=True, text=True).stdout.strip()
    if not pw:
        sys.exit("错误: 无法从 Keychain 读取 Microsoft Edge Safe Storage")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=16, salt=b'saltysalt', iterations=1003)
    return kdf.derive(pw.encode())


def decrypt_cookie(enc, key):
    # Edge v10 格式: "v10"(3) + salt(16) + iv(16) + AES-128-CBC 密文
    assert enc[:3] == b'v10', "Cookie 版本标记非 v10"
    iv = enc[19:35]
    ct = enc[35:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    d = cipher.decryptor()
    pt = d.update(ct) + d.finalize()
    pad = pt[-1] if 1 <= pt[-1] <= 16 else 0
    return (pt[:-pad] if pad else pt).decode('ascii')


def copy_cookie_db():
    """把 Cookie 库连同 -wal/-shm/-journal 一起拷贝到临时目录。"""
    for suffix in COOKIE_SUFFIXES:
        src, dst = COOKIE_DB + suffix, COOKIE_TMP + suffix
        try:
            if os.path.exists(src):
                shutil.copy2(src, dst)
            elif os.path.exists(dst):
                os.unlink(dst)
        except OSError as e:
            print(f"警告: 拷贝 {os.path.basename(src) or 'Cookies'} 失败: {e}")


def extract_cookie_rows():
    """拷贝并读取匹配行；读取失败返回 None。拷贝一致性靠伴生文件 + 调用方重试保证。"""
    copy_cookie_db()
    rows = None
    try:
        conn = sqlite3.connect(COOKIE_TMP)
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
                if os.path.exists(COOKIE_TMP + suffix):
                    os.unlink(COOKIE_TMP + suffix)
            except OSError:
                pass
    return rows


def main():
    if not os.path.exists(COOKIE_DB):
        sys.exit(f"错误: Edge Cookie 数据库不存在: {COOKIE_DB}")

    key = get_safe_storage_key()

    cookies = {}
    missing = REQUIRED[:]
    for attempt in (1, 2):
        rows = extract_cookie_rows()
        if rows:
            for host, name, enc in rows:
                if name in cookies:
                    continue
                try:
                    cookies[name] = decrypt_cookie(enc, key)
                except Exception as e:
                    print(f"警告: {name} 解密失败: {e}")
        missing = [c for c in REQUIRED if c not in cookies]
        if not missing:
            break
        if attempt == 1:
            # Edge 运行中 WAL 可能尚未合并进主库，等一拍重试一次，避免误报「缺少 Cookie」
            print(f"警告: 缺少 Cookie {missing}，1 秒后重试…")
            time.sleep(1)

    if missing:
        sys.exit(f"错误: 缺少 Cookie: {missing}。请先在 Edge 打开并登录 platform.xiaomimimo.com（保持窗口打开），再重试")

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    print(f"提取成功: 完整 Cookie 串 {len(cookie_str)} 字符")

    r = subprocess.run(
        ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", "", "-w", cookie_str],
        capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"Keychain 更新失败: {r.stderr[:200]}")
    print(f"已更新 Keychain: {KEYCHAIN_SERVICE}")

    r2 = subprocess.run(
        ["curl", "-s", "--max-time", "8", "-w", "|HTTP:%{http_code}",
         "-H", "Cookie: " + cookie_str,
         "-H", "Accept: application/json",
         "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
         "https://platform.xiaomimimo.com/api/v1/balance"],
        capture_output=True, text=True)
    body = r2.stdout.rsplit("|HTTP:", 1)
    code = body[1] if len(body) > 1 else "?"
    print(f"balance API: HTTP={code}")
    if code == "200":
        print("✅ Cookie 有效，Token Eye 余额显示已可用")
    else:
        print(f"⚠️ HTTP {code}，Cookie 可能无效或过期: {body[0][:150]}")


if __name__ == "__main__":
    main()
