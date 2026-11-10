#!/usr/bin/env python3
"""Token Eye — 跨端配置同步校验的单测（unittest，零第三方依赖）。

运行:
  /usr/bin/python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")


def _load_module():
    """scripts/check-config-sync.py 带连字符不是合法模块名，按路径加载。"""
    spec = importlib.util.spec_from_file_location(
        "check_config_sync", os.path.join(REPO, "scripts", "check-config-sync.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sync = _load_module()


def provider(pid, **extra):
    p = {"id": pid, "name": pid.title(), "keychainService": f"{pid.upper()}_KEY",
         "api": {"url": f"https://api.{pid}.test/v1"},
         "parser": {"type": "balance", "fields": {"balance": "data.balance"}}}
    p.update(extra)
    return p


class TestConfigSync(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.assets = os.path.join(self.root, "assets")
        self.holidays_dir = os.path.join(self.root, "holidays")
        self.assets_holidays = os.path.join(self.assets, "holidays")
        os.makedirs(self.holidays_dir)
        os.makedirs(self.assets_holidays)
        self.write_holiday("2026.json", '{"year": 2026, "days": [{"date": "2026-10-01", '
                                        '"isOffDay": true}]}')
        self.write_root_providers([provider("alpha"), provider("beta")])
        self.write_assets_providers([provider("alpha"), provider("beta")])

    # -- fixture helpers -------------------------------------------------
    def write_holiday(self, name, text, where="both"):
        targets = {"root": (self.holidays_dir,), "assets": (self.assets_holidays,),
                   "both": (self.holidays_dir, self.assets_holidays)}[where]
        for d in targets:
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(text)

    def write_root_providers(self, providers, **extra):
        with open(os.path.join(self.root, "providers.json"), "w", encoding="utf-8") as f:
            json.dump({"providers": providers, **extra}, f, ensure_ascii=False)

    def write_assets_providers(self, providers, **extra):
        with open(os.path.join(self.assets, "providers.json"), "w", encoding="utf-8") as f:
            json.dump({"providers": providers, **extra}, f, ensure_ascii=False)

    def errors(self):
        return sync.check(os.path.join(self.root, "providers.json"), self.assets)

    # -- cases -----------------------------------------------------------
    def test_identical_passes(self):
        self.assertEqual(self.errors(), [])

    def test_missing_provider_reported(self):
        self.write_assets_providers([provider("alpha")])
        self.assertTrue(any("缺少 provider「beta」" in e for e in self.errors()))

    def test_extra_provider_reported(self):
        self.write_assets_providers([provider("alpha"), provider("beta"), provider("gamma")])
        self.assertTrue(any("多出 provider「gamma」" in e for e in self.errors()))

    # -- 显式白名单（ANDROID_EXCLUDED） -----------------------------------
    def test_whitelist_is_explicit_constant(self):
        """白名单必须是按 id 的显式常量，不能再退回按字段动态剔除。"""
        self.assertEqual(sync.ANDROID_EXCLUDED, {"mimo", "qwen"})

    def test_explicit_whitelist_mimo_may_be_absent(self):
        """mimo（Cookie 会话鉴权，refreshParam）在显式白名单内，Android 侧应缺失。"""
        self.write_root_providers([provider("alpha"),
                                   provider("mimo", refreshParam="refresh-mimo-cookie")])
        self.write_assets_providers([provider("alpha")])
        self.assertEqual(self.errors(), [])

    def test_explicit_whitelist_qwen_may_be_absent(self):
        """qwen（command CLI）在显式白名单内，Android 侧应缺失。"""
        cmd = provider("qwen")
        cmd.pop("api", None)
        cmd.pop("keychainService", None)
        cmd["parser"] = {"type": "command", "command": "~/.local/bin/qianwen",
                         "args": ["billing", "balance", "summary", "--format", "json"]}
        self.write_root_providers([provider("alpha"), cmd])
        self.write_assets_providers([provider("alpha")])
        self.assertEqual(self.errors(), [])

    def test_new_non_whitelisted_provider_must_be_synced(self):
        """白名单外的新平台（哪怕是 command / refreshParam 型）必须同步进 assets。

        旧的动态白名单会把这类平台静默视为「Android 理应没有」而绕过比对，CI 全绿。
        显式白名单下必须报「缺少」，否则新平台永远进不了手机。"""
        newcmd = provider("newcmd")
        newcmd.pop("api", None)
        newcmd.pop("keychainService", None)
        newcmd["parser"] = {"type": "command", "command": "/usr/bin/true", "args": []}
        self.write_root_providers([provider("alpha"), provider("beta"), newcmd])
        self.write_assets_providers([provider("alpha"), provider("beta")])
        self.assertTrue(any("缺少 provider「newcmd」" in e for e in self.errors()))

    def test_excluded_platform_drift_in_assets_is_reported(self):
        """白名单内平台被误放进 assets（含字段漂移）必须显式报错，不能当同步。"""
        root = [provider("alpha"), provider("mimo", refreshParam="refresh-mimo-cookie")]
        drifted = provider("mimo", refreshParam="refresh-mimo-cookie")
        drifted["parser"] = {"type": "balance", "fields": {"balance": "data.total"}}
        self.write_root_providers(root)
        self.write_assets_providers([provider("alpha"), drifted])
        errs = self.errors()
        self.assertTrue(any("含已剔除平台「mimo」" in e for e in errs))
        # 白名单内平台本身不参与逐字段比对，不应出现「字段与根目录不一致」这类结论
        self.assertFalse(any("provider「mimo」" in e and "不一致" in e for e in errs))

    def test_excluded_platform_left_in_assets_after_root_removal(self):
        """白名单内平台从根目录误删、assets 仍残留 → 必须报错，不能静默通过。"""
        self.write_root_providers([provider("alpha")])
        self.write_assets_providers([provider("alpha"), provider("mimo")])
        self.assertTrue(any("含已剔除平台「mimo」" in e for e in self.errors()))

    def test_sync_counts_reflects_real_comparison(self):
        """成功信息用真实计数：根 N - 剔除 K == 已同步 M（不再取根目录全量数）。"""
        self.write_root_providers([provider("alpha"), provider("beta"),
                                   provider("mimo", refreshParam="refresh-mimo-cookie")])
        self.write_assets_providers([provider("alpha"), provider("beta")])
        n, k, m = sync.sync_counts(os.path.join(self.root, "providers.json"), self.assets)
        self.assertEqual((n, k, m), (3, 1, 2))
        self.assertEqual(n - k, m)

    def test_real_repo_counts_satisfy_invariant(self):
        """真实仓库当前必须满足 根 N - 剔除 K == 已同步 M。"""
        n, k, m = sync.sync_counts()
        self.assertEqual(n - k, m)

    # -- 既有回归 ---------------------------------------------------------
    def test_field_drift_reported_with_key(self):
        drifted = provider("alpha")
        drifted["parser"] = {"type": "balance", "fields": {"balance": "data.total"}}
        self.write_assets_providers([drifted, provider("beta")])
        self.assertTrue(any("provider「alpha」" in e and "parser" in e for e in self.errors()))

    def test_top_level_drift_reported(self):
        self.write_root_providers([provider("alpha"), provider("beta")],
                                  colors={"dark": {"header": "#FFD60A"}})
        self.write_assets_providers([provider("alpha"), provider("beta")])
        self.assertTrue(any("顶层「colors」" in e for e in self.errors()))

    def test_holiday_content_drift_reported(self):
        self.write_holiday("2026.json", '{"year": 2026, "days": []}', where="assets")
        self.assertTrue(any("2026.json" in e for e in self.errors()))

    def test_missing_holiday_file_reported(self):
        self.write_holiday("2027.json", '{"year": 2027, "days": []}', where="root")
        self.assertTrue(any("缺少 2027.json" in e for e in self.errors()))

    def test_unexpected_holiday_file_reported(self):
        with open(os.path.join(self.assets_holidays, "2028.json"), "w", encoding="utf-8") as f:
            f.write('{"year": 2028, "days": []}')
        self.assertTrue(any("多出 2028.json" in e for e in self.errors()))

    def test_real_repo_is_in_sync(self):
        """护栏：真实仓库当前必须同步（改根配置忘了拷 assets 会在这里报）。"""
        self.assertEqual(sync.check(), [])
