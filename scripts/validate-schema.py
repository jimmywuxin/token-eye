#!/usr/bin/python3
"""
Token Eye — providers.json JSON Schema 校验（零依赖，纯标准库）

实现 schema/providers.schema.json 用到的 draft-07 子集：
  type / required / properties / items / additionalProperties / enum /
  oneOf / minLength / minimum / $ref / definitions($defs)

用法:
  /usr/bin/python3 scripts/validate-schema.py [providers.json] [schema.json]

退出码: 0 = 通过；1 = 有错误（供 Makefile / CI 使用）
"""
import json
import os
import sys

TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}
NUMERIC_TYPES = ("number", "integer")


def is_type(value, t):
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "null":
        return value is None
    return isinstance(value, TYPE_MAP.get(t, object))


def validate(instance, schema, path="$", refs=None):
    """返回错误消息列表（空 = 通过）。"""
    errors = []
    refs = refs or {}

    # $ref: 仅支持 "#/definitions/<name>" 或 "#/$defs/<name>"
    if "$ref" in schema:
        target = schema["$ref"]
        if not target.startswith("#/"):
            errors.append(f"{path}: 不支持的 $ref {target!r}")
            return errors
        name = target.rsplit("/", 1)[-1]
        if name not in refs:
            errors.append(f"{path}: $ref 未找到 {target!r}")
            return errors
        return validate(instance, refs[name], path, refs)

    if "oneOf" in schema:
        matches = [i for i, sub in enumerate(schema["oneOf"])
                   if not validate(instance, sub, path, refs)]
        if len(matches) != 1:
            errors.append(f"{path}: 必须恰好满足 oneOf 中的一个分支（实际 {len(matches)} 个）")
        return errors

    t = schema.get("type")
    if t is not None:
        if t in NUMERIC_TYPES:
            if not is_type(instance, t):
                errors.append(f"{path}: 期望 {t}，实际 {type(instance).__name__}")
                return errors
        elif not is_type(instance, t):
            errors.append(f"{path}: 期望 {t}，实际 {type(instance).__name__}")
            return errors

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: 值 {instance!r} 不在允许列表 {schema['enum']}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: 长度 {len(instance)} 小于 minLength {schema['minLength']}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: 值 {instance} 小于 minimum {schema['minimum']}")

    if isinstance(instance, dict):
        if "required" in schema:
            for r in schema["required"]:
                if r not in instance:
                    errors.append(f"{path}: 缺少必填字段 {r!r}")
        props = schema.get("properties", {})
        for k, sub in props.items():
            if k in instance:
                errors.extend(validate(instance[k], sub, f"{path}.{k}", refs))
        add = schema.get("additionalProperties", True)
        if add is not True:
            for k in instance:
                if k in props:
                    continue
                if add is False:
                    errors.append(f"{path}: 未定义的字段 {k!r}")
                else:
                    errors.extend(validate(instance[k], add, f"{path}.{k}", refs))

    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            errors.extend(validate(item, schema["items"], f"{path}[{i}]", refs))

    return errors


def collect_refs(schema, refs=None):
    refs = refs or {}
    for key in ("definitions", "$defs"):
        for name, sub in (schema.get(key) or {}).items():
            refs[name] = sub
    return refs


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    args = sys.argv[1:]
    data_path = args[0] if len(args) > 0 else os.path.join(here, "..", "providers.json")
    schema_path = args[1] if len(args) > 1 else os.path.join(here, "..", "schema", "providers.schema.json")

    for p in (data_path, schema_path):
        if not os.path.exists(p):
            print(f"❌ 文件不存在: {p}")
            sys.exit(1)

    try:
        with open(data_path) as f:
            instance = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ {data_path} JSON 解析失败: {e}")
        sys.exit(1)

    with open(schema_path) as f:
        schema = json.load(f)

    refs = collect_refs(schema)
    errors = validate(instance, schema, refs=refs)

    if errors:
        print(f"❌ {data_path} 不符合 {schema_path}（{len(errors)} 处）:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    n = len(instance.get("providers", [])) if isinstance(instance, dict) else 0
    print(f"✅ {data_path} 通过 JSON Schema 校验（{n} 个 provider）")
    sys.exit(0)


if __name__ == "__main__":
    main()
