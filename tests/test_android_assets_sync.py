#!/usr/bin/env python3
"""构建期 assets 同步护栏：白名单一致 + 提交副本最新 + 生成器确实跟随根配置。"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAndroidAssetsSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sync = load("scripts/sync-android-assets.py", "sync_android_assets")
        cls.check = load("scripts/check-config-sync.py", "check_config_sync")

    def test_whitelists_match(self):
        """两份白名单漂移会让「生成器剔除」与「校验器期望」互相打架。"""
        self.assertEqual(self.sync.ANDROID_EXCLUDED, self.check.ANDROID_EXCLUDED)
        self.assertEqual(self.sync.ANDROID_EXCLUDED, {"mimo", "qwen"})

    def test_committed_assets_are_current(self):
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "sync-android-assets.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("已是最新", r.stdout)

    def test_generator_follows_root_config_and_excludes_mobile_unsupported(self):
        with tempfile.TemporaryDirectory() as d:
            assets = os.path.join(d, "android", "app", "src", "main", "assets")
            os.makedirs(os.path.join(assets, "holidays"))
            os.makedirs(os.path.join(d, "holidays"))
            with open(os.path.join(ROOT, "providers.json"), encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.setdefault("menuBar", {})["showSummary"] = True
            with open(os.path.join(d, "providers.json"), "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False)

            old_root, old_assets = self.sync.ROOT, self.sync.ASSETS
            self.sync.ROOT, self.sync.ASSETS = d, assets
            try:
                text = self.sync.generated_providers_text()
                generated = json.loads(text)
                self.assertIn('"showSummary": true', text)
                ids = {p["id"] for p in generated["providers"]}
                self.assertFalse(ids & self.sync.ANDROID_EXCLUDED,
                                 "移动端不支持的平台必须被剔除")
                self.assertEqual(len(ids), len(cfg["providers"]) - len(self.sync.ANDROID_EXCLUDED))
                changes, extra = self.sync.sync(check=True)
                self.assertIn("providers.json", changes)
                self.assertEqual(extra, [])
            finally:
                self.sync.ROOT, self.sync.ASSETS = old_root, old_assets


if __name__ == "__main__":
    unittest.main()
