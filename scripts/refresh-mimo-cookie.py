#!/usr/bin/python3
"""
Token Eye — MiMo Cookie 刷新工具（多浏览器支持）

从 Edge / Chrome / Brave / Arc 任一已登录的浏览器 Cookie 数据库提取 MiMo
platform 的 4 个 Cookie（api-platform_ph / api-platform_serviceToken /
api-platform_slh / userId），解密后拼成完整 Cookie 串，更新到 Keychain
（MIMO_PLATFORM_TOKEN），并调 balance API 验证。

用法:
  /usr/bin/python3 scripts/refresh-mimo-cookie.py

前置条件:
  - 任一受支持浏览器（Edge/Chrome/Brave/Arc）中已登录 platform.xiaomimimo.com
  - 系统 Python 3（/usr/bin/python3）自带 cryptography 库

说明:
  MiMo platform API 鉴权需要完整 Cookie（仅 serviceToken 会 401）。
  Cookie 是会话级，过期后重跑本脚本刷新。浏览器运行中时最新 Cookie 写入在
  -wal/-shm/-journal 伴生文件里，拷贝时会一并带走并自动重试，避免旧快照误报。
"""
import os, sys, time, glob

# 防御：清理 WorkBuddy/Hermes/OpenClaw 注入的 PYTHONPATH 与 sys.path，
# 避免跨版本 venv 包（如 Hermes 的 python3.11 cryptography）污染导致 ImportError
os.environ.pop("PYTHONPATH", None)
os.environ.pop("PYTHONHOME", None)
sys.path = [p for p in sys.path if not any(x in p for x in (".hermes", ".openclaw"))]

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import sqlite3, subprocess, shutil

KEYCHAIN_SERVICE = "MIMO_PLATFORM_TOKEN"
HOST_FILTER = "%xiaomimimo%"
REQUIRED = ["api-platform_ph", "api-platform_serviceToken", "api-platform_slh", "userId"]
# 拷贝主库时要一起带的伴生文件：浏览器运行中时最新写入常在 -wal/-shm/-journal 里
COOKIE_SUFFIXES = ("", "-wal", "-shm", "-journal")

# 受支持的 Chromium 系浏览器：Cookie 库路径 + Keychain 加密密钥服务名
BROWSERS = [
    {"name": "Edge",   "db": "~/Library/Application Support/Microsoft Edge",
     "keychain": "Microsoft Edge Safe Storage"},
    {"name": "Chrome", "db": "~/Library/Application Support/Google/Chrome",
     "keychain": "Chrome Safe Storage"},
    {"name": "Brave",  "db": "~/Library/Application Support/BraveSoftware/Brave-Browser",
     "keychain": "Brave Safe Storage"},
    {"name": "Arc",    "db": "~/Library/Application Support/Arc/User Data",
     "keychain": "Arc Safe Storage"},
]


def get_safe_storage_key(keychain_service):
    pw = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", keychain_service],
        capture_output=True, text=True).stdout.strip()
    if not pw:
        return None
    kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=16, salt=b'saltysalt', iterations=1003)
    return kdf.derive(pw.encode())


def decrypt_cookie(enc, key):
    # Chromium v10 格式: "v10"(3) + salt(16) + iv(16) + AES-128-CBC 密文
    assert enc[:3] == b'v10', "Cookie 版本标记非 v10"
    iv = enc[19:35]
    ct = enc[35:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    d = cipher.decryptor()
    pt = d.update(ct) + d.finalize()
    pad = pt[-1] if 1 <= pt[-1] <= 16 else 0
    return (pt[:-pad] if pad else pt).decode('ascii')


def copy_cookie_db(db_path):
    """把 Cookie 库连同 -wal/-shm/-journal 一起拷贝到临时目录。"""
    tmp = "/tmp/edge_cookies_tmp.db"
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
    """拷贝并读取匹配行；读取失败返回 None。拷贝一致性靠伴生文件 + 调用方重试保证。"""
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
    """返回该浏览器所有配置档（Default / Profile *）的 Cookies 库路径。"""
    base = os.path.expanduser(browser["db"])
    out = []
    for pat in ("Default", "Profile *"):
        for p in sorted(glob.glob(os.path.join(base, pat, "Cookies"))):
            out.append(p)
    return out


def try_extract(browser):
    """尝试从某个浏览器提取完整 Cookie。成功返回 (name, cookies)，否则 None。"""
    key = get_safe_storage_key(browser["keychain"])
    if key is None:
        return None
    for db_path in find_cookie_dbs(browser):
        for attempt in (1, 2):
            rows = extract_cookie_rows(db_path)
            if not rows:
                break  # 库读不到/无匹配，换下一个库
            cookies = {}
            for host, name, enc in rows:
                if name in cookies:
                    continue
                try:
                    cookies[name] = decrypt_cookie(enc, key)
                except Exception as e:
                    print(f"警告: [{browser['name']}] {name} 解密失败: {e}")
            missing = [c for c in REQUIRED if c not in cookies]
            if not missing:
                return browser["name"], cookies
            if attempt == 1:
                # 浏览器运行中 WAL 可能尚未合并进主库，等一拍重试一次
                time.sleep(0.8)
    return None


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
                 f"请先在任一浏览器登录 platform.xiaomimimo.com（保持窗口打开），再重试")

    browser_name, cookies = found
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    print(f"提取成功（来源: {browser_name}）: 完整 Cookie 串 {len(cookie_str)} 字符")

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
        # 刷新成功 → 清掉 Token Eye 的错误短缓存（路径约定见 swiftbar/token_eye.py cache_path），
        # 让下一次渲染（菜单点击自带的 refresh=true）立即重拉余额，不用等 10s 错误缓存过期
        try:
            os.unlink("/tmp/token-eye-cache-mimo.json")
        except OSError:
            pass
        print("✅ Cookie 有效，Token Eye 余额显示已可用")
    else:
        print(f"⚠️ HTTP {code}，Cookie 可能无效或过期: {body[0][:150]}")


if __name__ == "__main__":
    main()
