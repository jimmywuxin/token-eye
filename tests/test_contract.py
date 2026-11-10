#!/usr/bin/env python3
"""跨端口径契约测试（Mac/Linux 侧）——消费 tests/fixtures/cross_platform_cases.json。

同一份 fixture 也由 Android 的 ContractTest.kt 消费。改判定规则时先改 fixture，
三端一起跑；只改某一端代码会在 CI 里暴露口径漂移（2026-11-10 审查 P1-1）。
"""
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "swiftbar"))
import token_eye as te  # noqa: E402

FIXTURE_PATH = os.path.join(ROOT, "tests", "fixtures", "cross_platform_cases.json")
COLORS = {
    "DEFAULT": "#000000", "SECONDARY": "#666666", "MUTED": "#888888",
    "HEADER": "#0000ff", "OK": "#0072B2", "WARN": "#B86E00", "ERR": "#8E1A4A",
}


def ok_result(data):
    return {"ok": True, "status": 200, "data": data,
            "error_kind": None, "message": ""}


class TestCrossPlatformContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            cls.fixture = json.load(f)
        cls.provider = {
            "id": "deepseek", "name": "DeepSeek", "keychainService": "K",
            "api": {"url": "https://x"},
            "parser": {"type": "balance", "fields": cls.fixture["balance_fields"]},
        }

    def test_fixture_is_well_formed(self):
        self.assertEqual(self.fixture["schema"], 1)
        self.assertTrue(self.fixture["cases"])
        ids = [c["id"] for c in self.fixture["cases"]]
        self.assertEqual(len(ids), len(set(ids)), "case id 不能重复")
        for c in self.fixture["cases"]:
            self.assertIn("python", c["consumers"], c["id"])
            self.assertIn("android", c["consumers"], c["id"])
            self.assertIn(c["kind"], ("business_code", "balance_parse"), c["id"])

    def test_business_code_cases(self):
        for c in self.fixture["cases"]:
            if c["kind"] != "business_code":
                continue
            with self.subTest(case=c["id"]):
                api = {"url": "https://x"}
                if c.get("envelope"):
                    api["envelope"] = c["envelope"]
                r = te.apply_envelope(ok_result(c["data"]), api, default_check=True)
                self.assertEqual(r["ok"], c["expect"]["fetch_ok"],
                                 f"{c['id']}: 期望 fetch_ok={c['expect']['fetch_ok']}")

    def test_balance_parse_cases(self):
        for c in self.fixture["cases"]:
            if c["kind"] != "balance_parse":
                continue
            with self.subTest(case=c["id"]):
                r = te.parse_provider(self.provider, ok_result(c["data"]),
                                      COLORS, "dark")
                if c["expect"]["status_class"] == "ok":
                    self.assertEqual(r["status"], "ok", c["id"])
                    self.assertIn("13.5", r["menu_bar"])
                else:
                    self.assertNotEqual(r["status"], "ok", f"{c['id']} 假绿")
                    self.assertEqual(r["menu_bar"], "", f"{c['id']} 不该有绿色标题")


if __name__ == "__main__":
    unittest.main()
