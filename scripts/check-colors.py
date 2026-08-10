#!/usr/bin/python3
"""
Token Eye — 配色对比度回归检查

读取 providers.json 的 colors 段 + 各 provider 的 display.nameColor（含深浅双套），
按 WCAG AA 标准检查全部颜色对比度 ≥ 4.5:1（浅色对白底、深色对黑底）。

用法:
  /usr/bin/python3 scripts/check-colors.py

退出码: 0 = 全部达标；1 = 有不达标（用于 CI / 改色后回归自检）
"""
import json, sys, os

BGS = {"dark": "#000000", "light": "#ffffff"}


def lum(hexc):
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    def f(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "providers.json")
    with open(path) as f:
        config = json.load(f)

    failures, total = [], 0
    colors = config.get("colors", {})

    for mode in ("dark", "light"):
        bg = BGS[mode]
        for key, val in (colors.get(mode) or {}).items():
            total += 1
            r = contrast(val, bg)
            ok = "OK" if r >= 4.5 else "FAIL"
            print(f"  {mode}.{key:8s} {val}  = {r:5.2f}:1  {ok}")
            if r < 4.5:
                failures.append(f"{mode}.{key} {val} ({r:.2f}:1 < 4.5)")

    for p in config.get("providers", []):
        nc = (p.get("display") or {}).get("nameColor")
        if not nc:
            continue
        if isinstance(nc, dict):
            for mode, val in nc.items():
                if mode not in BGS:
                    continue
                total += 1
                r = contrast(val, BGS[mode])
                ok = "OK" if r >= 4.5 else "FAIL"
                print(f"  {p.get('id'):9s} nameColor[{mode}] {val}  = {r:5.2f}:1  {ok}")
                if r < 4.5:
                    failures.append(f"{p.get('id')}.nameColor[{mode}] {val} ({r:.2f}:1)")
        else:
            # 旧版字符串写法：两种背景下都必须达标（保守检查）
            for mode, bg in BGS.items():
                total += 1
                r = contrast(nc, bg)
                if r < 4.5:
                    failures.append(f"{p.get('id')}.nameColor {nc} vs {bg} ({r:.2f}:1)")

    print(f"\n共检查 {total} 处：", end="")
    if not failures:
        print("全部达标 ✅")
        sys.exit(0)
    print(f"{len(failures)} 处不达标 ❌")
    for f in failures:
        print(f"  ❌ {f}")
    sys.exit(1)


if __name__ == "__main__":
    main()
