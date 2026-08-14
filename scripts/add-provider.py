#!/usr/bin/python3
"""
Token Eye — 新平台添加向导（交互式）

按提示输入平台信息，自动生成 provider 配置并追加到 providers.json，
完成后做 schema 校验并提示 Keychain 添加命令。全程零代码。

用法:
  /usr/bin/python3 scripts/add-provider.py            # 修改项目 providers.json
  /usr/bin/python3 scripts/add-provider.py /path/to/providers.json   # 指定配置文件

说明:
  - 配置结构见 schema/providers.schema.json 与 README.md
  - 字段路径支持 . 分隔嵌套与数组索引（如 balance_infos.0.total_balance）
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "..", "providers.json")
TEMPLATES_PATH = os.path.join(HERE, "provider-templates.json")

PTYPE_LABEL = {"balance": "余额型", "plan_usage": "用量型", "status": "状态型"}


def load_templates():
    """读取内置平台模板（脚本同目录 provider-templates.json）。"""
    try:
        with open(TEMPLATES_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"警告: 模板库读取失败（{e}），仅提供手动填写")
        return []

# 引入项目内校验（与运行时同一套）
sys.path.insert(0, os.path.join(HERE, "..", "swiftbar"))
try:
    from token_eye import schema_validate  # noqa: E402
except Exception:
    schema_validate = None


def ask(prompt, default=None, required=False):
    """交互式提问；返回输入值（默认值或 None）。"""
    suffix = f"（默认 {default}）" if default is not None else ""
    while True:
        try:
            raw = input(f"{prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消，未做任何修改")
            sys.exit(1)
        if raw:
            return raw
        if default is not None:
            return default
        if required:
            print("  该项必填，请重新输入")
            continue
        return None


def build_balance(display_name, keychain):
    print("\n▶ balance（余额型）字段映射：")
    url = ask("API URL", required=True)
    method = ask("HTTP 方法", "GET")
    auth_mode = ask("鉴权方式（1=Bearer Token / 2=Cookie）", "1")
    if auth_mode == "2":
        auth_header, auth_prefix = "Cookie", ""
    else:
        auth_header, auth_prefix = "Authorization", "Bearer "
    balance = ask("余额字段路径", "balance")
    currency = ask("货币字段路径", "currency")
    label = ask("展示标签", "余额")
    unit = ask("货币符号（如 ¥ $ €）", "¥")
    min_balance = ask("告警阈值 minBalance（回车跳过）", None)
    provider = {
        "id": "", "name": display_name, "keychainService": keychain,
        "api": {"url": url, "method": method,
                "authHeader": auth_header, "authPrefix": auth_prefix},
        "parser": {"type": "balance",
                   "fields": {"balance": balance, "currency": currency}},
        "display": {"unit": unit, "label": label},
    }
    if min_balance:
        provider["alert"] = {"minBalance": float(min_balance)}
    return provider


def build_plan_usage(display_name, keychain):
    print("\n▶ plan_usage（用量型）字段映射：")
    url = ask("API URL", required=True)
    method = ask("HTTP 方法", "GET")
    auth_mode = ask("鉴权方式（1=Bearer Token / 2=Cookie）", "1")
    if auth_mode == "2":
        auth_header, auth_prefix = "Cookie", ""
    else:
        auth_header, auth_prefix = "Authorization", "Bearer "
    array_path = ask("模型数组字段路径", "model_remains")
    model = ask("模型名字段路径", "model_name")
    interval_pct = ask("5小时窗口剩余百分比字段", "current_interval_remaining_percent")
    interval_status = ask("5小时窗口状态码字段", "current_interval_status")
    weekly_pct = ask("周窗口剩余百分比字段", "current_weekly_remaining_percent")
    weekly_status = ask("周窗口状态码字段", "current_weekly_status")
    reset_ms = ask("重置倒计时字段（毫秒）", "remains_time")
    label = ask("展示标签", "剩余")
    unit = ask("单位", "%")
    min_pct = ask("告警阈值 minPct（回车跳过）", None)
    provider = {
        "id": "", "name": display_name, "keychainService": keychain,
        "api": {"url": url, "method": method,
                "authHeader": auth_header, "authPrefix": auth_prefix},
        "parser": {
            "type": "plan_usage",
            "arrayPath": array_path,
            "fields": {
                "model": model,
                "intervalPct": interval_pct,
                "intervalStatus": interval_status,
                "weeklyPct": weekly_pct,
                "weeklyStatus": weekly_status,
                "resetMs": reset_ms,
            },
            "statusMap": {"1": "可用", "2": "耗尽临近", "3": "耗尽"},
            "barLength": 20,
        },
        "display": {"unit": unit, "label": label},
    }
    if min_pct:
        provider["alert"] = {"minPct": int(min_pct)}
    return provider


def build_status(display_name, keychain):
    print("\n▶ status（状态型）字段映射：")
    url = ask("API URL", required=True)
    method = ask("HTTP 方法", "GET")
    auth_mode = ask("鉴权方式（1=Bearer Token / 2=Cookie）", "1")
    if auth_mode == "2":
        auth_header, auth_prefix = "Cookie", ""
    else:
        auth_header, auth_prefix = "Authorization", "Bearer "
    ok_field = ask("成功判定字段", "object")
    ok_value = ask("成功判定值", "list")
    label = ask("展示标签", "可用")
    provider = {
        "id": "", "name": display_name, "keychainService": keychain,
        "api": {"url": url, "method": method,
                "authHeader": auth_header, "authPrefix": auth_prefix},
        "parser": {"type": "status", "okField": ok_field, "okValue": ok_value},
        "display": {"label": label},
    }
    return provider


def main():
    config_path = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG)
    if not os.path.exists(config_path):
        sys.exit(f"错误: 配置文件不存在: {config_path}")

    with open(config_path) as f:
        config = json.load(f)

    print(f"Token Eye 新平台向导（配置文件: {config_path}）\n")

    # 模板选择
    templates = load_templates()
    provider = None
    if templates:
        print("▶ 内置平台模板（0 = 手动填写）:")
        for i, t in enumerate(templates, 1):
            ttype = PTYPE_LABEL.get((t.get("parser") or {}).get("type", ""), "")
            print(f"  {i} = {t.get('name')}（{ttype}）")
        choice = ask("选择模板", "0")
        if choice != "0":
            try:
                tmpl = templates[int(choice) - 1]
            except (ValueError, IndexError):
                sys.exit("错误: 模板序号无效，终止")
            display_name = ask("平台显示名", tmpl.get("name", ""))
            pid = ask("平台 id", tmpl.get("id", ""))
            keychain = ask("Keychain 服务名", tmpl.get("keychainService", ""))
            provider = copy.deepcopy(tmpl)
            provider["name"], provider["id"], provider["keychainService"] = display_name, pid, keychain
            min_balance = ask("告警阈值 minBalance（回车跳过）", None)
            if min_balance:
                provider.setdefault("alert", {})["minBalance"] = float(min_balance)
            min_pct = ask("告警阈值 minPct（回车跳过）", None)
            if min_pct:
                provider.setdefault("alert", {})["minPct"] = int(min_pct)

    if provider is None:
        # 手动填写
        display_name = ask("平台显示名（如 OpenAI、Kimi）", required=True)
        pid_default = display_name.lower().replace(" ", "-")
        pid = ask("平台 id", pid_default)
        keychain = ask("Keychain 服务名", display_name.upper().replace(" ", "_") + "_API_KEY")
        ptype = ask("parser 类型（1=balance 2=plan_usage 3=status）", "1")
        ptype_map = {"1": "balance", "2": "plan_usage", "3": "status"}
        ptype = ptype_map.get(ptype, ptype)

        builder = {"balance": build_balance, "plan_usage": build_plan_usage,
                   "status": build_status}[ptype]
        provider = builder(display_name, keychain)
        provider["id"] = pid

        print("\n▶ 可选：")
        name_color = ask("平台名颜色 nameColor（十六进制，如 #FF0000，回车跳过）", None)
        if name_color:
            provider["display"]["nameColor"] = name_color
        console_url = ask("控制台地址 consoleUrl（回车跳过）", None)
        if console_url:
            provider["consoleUrl"] = console_url

    print("\n=== 即将添加的配置 ===")
    print(json.dumps(provider, ensure_ascii=False, indent=2))
    confirm = ask("确认添加？（y/N）", "N")
    if confirm.lower() not in ("y", "yes"):
        print("已取消，未做任何修改")
        sys.exit(0)

    providers = config.setdefault("providers", [])
    if any(p.get("id") == pid for p in providers):
        sys.exit(f"错误: id={pid!r} 已存在，终止（未修改文件）")
    providers.append(provider)

    # 校验（先内存后落盘）
    if schema_validate is not None:
        errors = schema_validate(config)
        if errors:
            print("❌ 配置校验未通过:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)

    with open(config_path, "w") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"✅ 已写入 {config_path}（共 {len(providers)} 个 provider）")
    print("\n下一步：把 API Key 加入 Keychain：")
    print(f'  security add-generic-password -s "{keychain}" -a "" -w "your-key"')
    print("\nSwiftBar 下次刷新（30 秒内）自动生效，无需重启。")


if __name__ == "__main__":
    main()
