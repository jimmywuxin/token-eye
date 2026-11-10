#!/usr/bin/python3
"""
Token Eye — MiMo Cookie 刷新工具（Linux / gnome-keyring 版）

从 Linux 的 Chromium 系浏览器提取 MiMo platform 的 4 个 Cookie
（api-platform_ph / api-platform_serviceToken / api-platform_slh / userId），
解密后拼成完整 Cookie 串，写入 gnome-keyring（service=MIMO_PLATFORM_TOKEN，
与 tray 的 linux_get_key 读取一致），并调 balance API 验证。

浏览器优先级：Chromium（本机指定）> Edge > Chrome。

用法:
  python3 refresh-mimo-cookie.py

前置条件:
  - Chromium 中已登录 platform.xiaomimimo.com（保持窗口打开）
  - gnome-keyring 已解锁

与 macOS 原版的差异:
  - 浏览器数据目录: ~/.config/{chromium,microsoft-edge,google-chrome}
  - 加密密码来源: gnome-keyring（application=chromium/chrome）
  - PBKDF2 iterations: Linux Chromium = 1（macOS = 1003）
  - 写入目标: gnome-keyring（service=MIMO_PLATFORM_TOKEN）
  - cookie 值布局自适应: v10+iv+ct（Linux）与 v10+salt+iv+ct（macOS）均兼容
"""
import os
import sys
import json
import time
import hashlib
import sqlite3
import shutil
import glob
import pathlib
import subprocess

# cryptography 延迟到 decrypt_cookie / derive_key 内导入：check_cookie 等纯逻辑
# 在无 cryptography 的环境（CI / 单测）也能直接 import，不触发 ImportError。
# 目标机已装 python3-cryptography，真正解密时才用到，运行行为不变。

KEYCHAIN_SERVICE = "MIMO_PLATFORM_TOKEN"


def fail(msg):
    """失败退出：结论打到 stdout 末行再以非零码退出。

    上游 auto_refresh_cookie 从脚本输出里挑「错误:」开头的末行写进 flag/菜单
    （_reason_tail），且优先读 stdout —— 用 sys.exit(str) 只写 stderr 会让菜单
    只剩过程噪音、看不到该怎么办（与 macOS 版 fail() 对齐，2026-10-19 实踩）。
    失败结论必须自带「重新登录」指引，且不得出现 "HTTP=200" 字样（那是成功标记）。
    """
    print(msg)
    sys.exit(1)
HOST_FILTER = "%xiaomimimo%"
REQUIRED = ["api-platform_ph", "api-platform_serviceToken", "api-platform_slh", "userId"]
COOKIE_SUFFIXES = ("", "-wal", "-shm", "-journal")
CACHE_FILE = os.path.expanduser("~/.cache/token-eye/token-eye-cache-mimo.json")

# Linux Chromium 系浏览器：Cookie 库路径 + gnome-keyring 密码条目属性
# 顺序即优先级：本机固定用 Chromium（官方版）登录 MiMo，故排首位。
# Edge / Chrome 仅作兜底（换机或 Chromium 未登录时仍有机会提取成功）。
# 注意：Edge Linux 也用 application=chromium（不是 microsoft-edge），与 Chromium 共享同一条 keyring
BROWSERS = [
    {"name": "Chromium", "db": "~/.config/chromium",
     "app": "chromium", "label": "Chromium Safe Storage"},
    {"name": "Edge", "db": "~/.config/microsoft-edge",
     "app": "chromium", "label": "Chromium Safe Storage"},
    {"name": "Chrome", "db": "~/.config/google-chrome",
     "app": "chrome", "label": "Chrome Safe Storage"},
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
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.backends import default_backend
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
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
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
            raw = pt[:-pad]
            # 解密结果必须是可打印 ASCII：Cookie 值（token/数字/base64）都在此范围。
            # 密码/IV 不对时即便碰巧通过 padding 校验，也会解出随机字节；旧实现
            # 用 decode("ascii", "replace") 把非 ASCII 变 '?' 照样收下 → 写入乱码。
            if not all(0x20 <= b < 0x7f for b in raw):
                continue
            return raw.decode("ascii")
        except Exception:
            continue
    return None


def copy_cookie_db(db_path):
    # 临时文件按「进程号 + 库路径」派生：并发跑本脚本时固定路径会互相覆盖、
    # 拷出混拼库 → "no such table: cookies"（2026-10-12 与 Mac 版同修）。
    tag = hashlib.md5(db_path.encode()).hexdigest()[:8]
    tmp = f"/tmp/te_cookies_{os.getpid()}_{tag}.db"
    for suffix in COOKIE_SUFFIXES:
        src, dst = db_path + suffix, tmp + suffix
        try:
            if os.path.exists(src):
                shutil.copy2(src, dst)
                # copy2 会保留源权限（浏览器 Cookie 库常为 0644）：临时库含
                # 加密 Cookie 数据，必须收紧为仅属主可读写（P0-2）。
                try:
                    os.chmod(dst, 0o600)
                except OSError as e:
                    print(f"警告: 收紧临时 Cookie 库权限失败: {e}")
            elif os.path.exists(dst):
                os.unlink(dst)
        except OSError as e:
            print(f"警告: 拷贝 {os.path.basename(src) or 'Cookies'} 失败: {e}")
    return tmp


COOKIE_QUERY = "SELECT host_key, name, encrypted_value FROM cookies WHERE host_key LIKE ?"


def read_rows_direct(db_path):
    """只读直连原库读匹配行（引擎级一致读，不会被浏览器写事务撕裂）。"""
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

    优先只读直连原库（引擎级一致读）；Chromium 用 rollback journal，浏览器写事务
    期间文件级拷贝会得到不一致快照 → "no such table: cookies"（2026-10-14 与 Mac
    版同修）。直连失败才退化为拷贝快照并重试。
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
    base = os.path.expanduser(browser["db"])
    out = []
    for pat in ("Default", "Profile *"):
        for p in sorted(glob.glob(os.path.join(base, pat, "Cookies"))):
            out.append(p)
    return out


def try_extract(browser):
    dbs = find_cookie_dbs(browser)
    if not dbs:
        return None
    password = get_safe_storage_password(browser["app"], browser["label"])
    if password is None:
        print(f"跳过 [{browser['name']}]: gnome-keyring 中未找到安全存储密码"
              f"（application={browser['app']}）")
        return None
    for db_path in dbs:
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


BALANCE_URL = "https://platform.xiaomimimo.com/api/v1/balance"
BALANCE_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def balance_body_ok(body_text):
    """校验 MiMo balance 响应体：HTTP 200 不等于 Cookie 有效。

    业务错误体（如 {"code":401,"msg":"未登录"}）、非 JSON、或缺 data 对象
    都必须判失败；否则会把过期 Cookie 写进 keyring 并标「自愈成功」假绿
    （P0-1）。成功响应形如 {"code":0,"data":{"balance":...,"currency":...}}。
    """
    try:
        d = json.loads(body_text)
    except (ValueError, TypeError):
        return False
    if not isinstance(d, dict):
        return False
    # 业务错误码四个键都要查（只看 code 会放过 {"errcode":401}），
    # 成功值白名单与 Mac 版 cookie_is_valid / token_eye 默认检查完全一致。
    ok_codes = ("0", "200", "ok", "success", "true", "none", "null")
    for key in ("code", "errcode", "error_code", "retcode"):
        val = d.get(key)
        if val is not None and str(val).strip().lower() not in ok_codes:
            return False
    if d.get("success") is False:
        return False
    # 必须有真实余额字段：只有空 data 对象仍会让上游渲染「✅ ¥?」假绿
    data = d.get("data")
    return isinstance(data, dict) and data.get("balance") is not None


def check_cookie(cookie_str):
    """用给定 Cookie 调 balance API，返回 (http_code_str, body, valid)。

    valid 仅当 HTTP 200 **且**响应体通过 balance_body_ok() 时为 True：
    旧实现只判 code==200 就丢弃 body，HTTP 200 + 业务错误体会被当成有效
    Cookie 写入 keyring（Linux/Mac 双端假绿）。

    凭证走 curl `--config -` 的 stdin，不进 argv —— 完整会话 Cookie 出现在
    `ps` / 进程审计日志里等于把账号交出去（P0-2，与 Mac 版同口径）。
    config 内容对反斜杠、双引号、换行/回车做转义。
    """
    headers = ("Cookie: " + cookie_str, "Accept: application/json",
               "User-Agent: " + BALANCE_UA)
    cfg = "\n".join(
        'header = "' + str(h).replace("\\", "\\\\").replace('"', '\\"')
        .replace("\n", " ").replace("\r", " ") + '"'
        for h in headers) + "\n"
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "8", "-w", "|HTTP:%{http_code}",
             "--config", "-", BALANCE_URL],
            input=cfg, capture_output=True, text=True, timeout=12)
    except Exception as e:
        print(f"警告: balance API 请求异常: {e}")
        return "?", "", False
    parts = r.stdout.rsplit("|HTTP:", 1)
    code = parts[1] if len(parts) > 1 else "?"
    text = parts[0] if len(parts) > 1 else ""
    return code, text, (code == "200" and balance_body_ok(text))


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
        # 先校验再用：否则「在 A 浏览器重新登录，B 浏览器还留着过期的完整
        # Cookie」时会拿 B 的旧 Cookie 收工 → 永远试不到 A 的新 Cookie
        # （2026-10-18 与 Mac 版同修）。
        code, body, valid = check_cookie(cookie_str)
        if not valid:
            # 注意用「HTTP 200」（空格）而非「HTTP=200」：后者是上游判定成功的
            # 标记，失败输出里绝不能出现，否则会被 auto_refresh_cookie 误判成功。
            if code == "200":
                stale.append(f"{name}(HTTP 200 但余额响应无效/业务错误)")
            else:
                stale.append(f"{name}(HTTP {code})")
            continue
        found = (name, cookie_str)
        break
    if not found:
        detail = "、".join(stale) if stale else "未提取到完整 Cookie"
        fail(f"错误: 浏览器里的 MiMo Cookie 均无效（{detail}；已按序尝试 "
             f"{', '.join(tried)}）。请在浏览器重新登录 platform.xiaomimimo.com，"
             f"登录完成后等 5 秒再点「重试」")

    browser_name, cookie_str = found
    print(f"提取成功（来源: {browser_name}）: 完整 Cookie 串 {len(cookie_str)} 字符")

    if not store_keyring(cookie_str):
        fail("错误: gnome-keyring 写入失败（MIMO_PLATFORM_TOKEN）——"
             "请确认已登录桌面会话且钥匙环已解锁后重试")
    print(f"已更新 gnome-keyring: {KEYCHAIN_SERVICE}")
    # 只有「Cookie 业务校验通过 + keyring 写入成功」才打印成功标记 HTTP=200
    print("balance API: HTTP=200")
    try:
        os.unlink(CACHE_FILE)
    except OSError:
        pass
    print("✅ Cookie 有效，Token Eye 余额显示已可用")


if __name__ == "__main__":
    main()
