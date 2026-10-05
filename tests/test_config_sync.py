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

    def test_refresh_param_provider_may_be_absent(self):
        """Android 剔除 Cookie 平台（带 refreshParam）是允许的唯一差异。"""
        self.write_root_providers([provider("alpha"),
                                   provider("mimo", refreshParam="refresh-mimo-cookie")])
        self.write_assets_providers([provider("alpha")])
        self.assertEqual(self.errors(), [])

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
