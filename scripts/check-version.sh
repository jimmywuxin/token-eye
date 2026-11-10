#!/usr/bin/env bash
# Token Eye — 版本号一致性 + CHANGELOG 条目检查（零依赖，供 make lint / CI 调用）。
#
# 校验链：
#   token_eye.py 的 VERSION  ↔  token-eye.sh 的 bitbar.version  ↔  CHANGELOG 的 [版本] 条目；
#   并静态确认 Android 的 versionName/versionCode 仍从 token_eye.py 的 VERSION 派生
#   （避免版本号的第三处手工维护漂移，见 AGENTS.md「版本号唯一真源」）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY_VER="$(sed -n 's/^VERSION = "\([0-9.]*\)"/\1/p' swiftbar/token_eye.py | head -1)"
SH_VER="$(sed -n 's/.*<bitbar.version>v\([0-9.]*\)<\/bitbar.version>.*/\1/p' swiftbar/token-eye.sh | head -1)"

echo "token_eye.py VERSION        = ${PY_VER:-<空>}"
echo "token-eye.sh bitbar.version = ${SH_VER:-<空>}"

if [ -z "${PY_VER}" ]; then
    echo "❌ 未能在 swiftbar/token_eye.py 解析出 VERSION" >&2
    exit 1
fi
if [ -z "${SH_VER}" ]; then
    echo "❌ 未能在 swiftbar/token-eye.sh 解析出 bitbar.version" >&2
    exit 1
fi
if [ "${PY_VER}" != "${SH_VER}" ]; then
    echo "❌ 版本号不一致：token_eye.py=${PY_VER} / token-eye.sh=${SH_VER}" >&2
    exit 1
fi
if ! grep -q "\[${PY_VER}\]" CHANGELOG.md; then
    echo "❌ CHANGELOG.md 缺少 [${PY_VER}] 条目（发版要补 CHANGELOG）" >&2
    exit 1
fi
if ! grep -q 'swiftbar/token_eye.py' android/app/build.gradle.kts || \
   ! grep -q 'VERSION = ' android/app/build.gradle.kts; then
    echo "❌ android/app/build.gradle.kts 不再从 token_eye.py 的 VERSION 派生版本号" >&2
    exit 1
fi

echo "✅ 版本号一致（${PY_VER}），CHANGELOG 与 Android 派生口径就位"
