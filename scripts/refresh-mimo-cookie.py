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
import sqlite3, subprocess, shutil, hashlib, pathlib

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
    """把 Cookie 库连同 -wal/-shm/-journal 一起拷贝到临时目录。

    临时文件按「进程号 + 库路径」派生：自愈与主动续期可能并发跑本脚本
    （多浏览器、refreshallplugins 与定时渲染并存），固定路径会让两个进程
    互相覆盖同一个 tmp，拷出混拼库 → sqlite 报 "no such table: cookies"，
    表现为余额莫名断显、下轮重试又自愈（2026-10-09 / 10-12 两次实踩）。
    """
    tag = hashlib.md5(db_path.encode()).hexdigest()[:8]
    tmp = f"/tmp/mimo_cookies_{os.getpid()}_{tag}.db"
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


COOKIE_QUERY = "SELECT host_key, name, encrypted_value FROM cookies WHERE host_key LIKE ?"


def read_rows_direct(db_path):
    """只读直连原库读匹配行（引擎级一致读，不会被浏览器写事务撕裂）。

    连不上或读不出时抛异常，由调用方兜底到拷贝路径。
    """
    uri = pathlib.Path(db_path).as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        return conn.execute(COOKIE_QUERY, (HOST_FILTER,)).fetchall()
    finally:
        conn.close()


def read_rows_via_copy(db_path):
    """拷贝快照后读取；返回 (rows, err)，rows=None 表示失败。"""
    tmp = copy_cookie_db(db_path)
    rows, err = None, None
    try:
        conn = sqlite3.connect(tmp)
        try:
            rows = conn.execute(COOKIE_QUERY, (HOST_FILTER,)).fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        err = str(e)
    finally:
        for suffix in COOKIE_SUFFIXES:
            try:
                if os.path.exists(tmp + suffix):
                    os.unlink(tmp + suffix)
            except OSError:
                pass
    return rows, err


def extract_cookie_rows(db_path):
    """读取匹配行；读取失败返回 None。

    **优先只读直连原库**：Chromium 系用 rollback journal 模式，浏览器写事务进行中
    时主库处于半更新状态，文件级 shutil 拷贝会拷出不一致副本 → SQLite 打开时报
    "no such table: cookies"（schema 页读不出）。这是 2026-10-09 / 10-12 / 10-14
    三次 MiMo「余额断显」的真实根因。直连由 SQLite 引擎保证一致，且 WAL/回滚日志
    并发读是安全的。

    直连失败（hot journal 需要写权限、库被独占锁、库不存在）才退化为拷贝快照，
    并重试数次 —— 撕裂只在写事务窗口内出现，重试即可命中一致状态。
    """
    try:
        return read_rows_direct(db_path)
    except (sqlite3.Error, OSError, ValueError) as e:
        print(f"警告: Cookie 库直连失败（退化为拷贝快照）: {e}")
    err = None
    for attempt in range(3):
        rows, err = read_rows_via_copy(db_path)
        if rows is not None:
            return rows
        if attempt < 2:
            time.sleep(0.15)
    print(f"警告: Cookie 库读取失败: {err}")
    return None


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


BALANCE_URL = "https://platform.xiaomimimo.com/api/v1/balance"
BALANCE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0")


def check_cookie(cookie_str):
    """用给定 Cookie 调 balance API，返回 (http_code_str, body)。"""
    r = subprocess.run(
        ["curl", "-s", "--max-time", "5", "-w", "|HTTP:%{http_code}",
         "-H", "Cookie: " + cookie_str,
         "-H", "Accept: application/json",
         "-H", "User-Agent: " + BALANCE_UA,
         BALANCE_URL],
        capture_output=True, text=True)
    body = r.stdout.rsplit("|HTTP:", 1)
    return (body[1] if len(body) > 1 else "?"), (body[0] if len(body) > 1 else "")


def main():
    found = None
    stale = []     # 提取到完整 Cookie 但 API 校验未通过（多半是过期会话）
    tried = []
    for browser in BROWSERS:
        tried.append(browser["name"])
        result = try_extract(browser)
        if not result:
            continue
        name, cookies = result
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        # **先校验再用**：旧实现只要凑齐 4 个 Cookie 就直接收工，导致
        # 「在 A 浏览器重新登录 MiMo，但 B 浏览器还留着过期的完整 Cookie」
        # 时，脚本拿 B 的旧 Cookie 去验 → 401 → 报刷新失败，永远不会试到
        # A 的新 Cookie（2026-10-18 用户实报）。
        code, _ = check_cookie(cookie_str)
        if code != "200":
            stale.append(f"{name}(HTTP {code})")
            continue
        found = (name, cookie_str)
        break
    if not found:
        detail = "、".join(stale) if stale else "未提取到完整 Cookie"
        sys.exit(f"错误: 浏览器里的 MiMo Cookie 均无效（{detail}；已尝试 "
                 f"{', '.join(tried)}）。请在浏览器重新登录 platform.xiaomimimo.com，"
                 f"登录完成后等 5 秒再点「重试」")

    browser_name, cookie_str = found
    print(f"提取成功（来源: {browser_name}）: 完整 Cookie 串 {len(cookie_str)} 字符")

    r = subprocess.run(
        ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", "", "-w", cookie_str],
        capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"Keychain 更新失败: {r.stderr[:200]}")
    print(f"已更新 Keychain: {KEYCHAIN_SERVICE}")
    print("balance API: HTTP=200")
    # 刷新成功 → 清掉 Token Eye 的错误短缓存（路径约定见 swiftbar/token_eye.py cache_path），
    # 让下一次渲染（菜单点击自带的 refresh=true）立即重拉余额，不用等 10s 错误缓存过期
    try:
        os.unlink("/tmp/token-eye-cache-mimo.json")
    except OSError:
        pass
    print("✅ Cookie 有效，Token Eye 余额显示已可用")


if __name__ == "__main__":
    main()
