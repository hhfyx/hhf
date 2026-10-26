# -*- coding: utf-8 -*-
"""demo3：嵌套 + 序列化 —— list[Model] / model_dump / model_dump_json / model_validate_json
21:05-21:30 嵌套 + 序列化

必答问题：嵌套模型的错误定位、dump 的两种模式、JSON 往返，各自要注意什么？
------------------------------------------------------------------------------
1) 嵌套校验失败时，`errors()[i]["loc"]` 是**完整路径元组**，例如 `('items', 0, 'name')`
   —— 外层字段名 + 列表下标 + 内层字段名。前端要显示到具体某一行就靠这个 path。
2) `model_dump()` 默认 `mode="python"`：`datetime` 还是 `datetime`、`Decimal` 还是 `Decimal`，
   直接丢给 `json.dumps` 会炸。要发 HTTP / 写 JSON 文件用 `model_dump(mode="json")`
   或干脆 `model_dump_json()`（后者直接出 str，中间不产生 dict，更快）。
3) `model_validate_json(s)` 直接在 JSON 文本上校验，不经过 `json.loads` -> dict -> 校验 三步，
   官方基准里明显快于 `model_validate(json.loads(s))`。脏数据入口就该用这个。
4) `ConfigDict(extra="forbid")` 写在**哪个模型**上就管哪一层，**不会**自动往下传；
   想让整棵嵌套树都拒绝多余字段，每个子模型都得写（或者抽个 Base 基类继承）。
5) `extra="ignore"`（默认）静默丢字段，`extra="forbid"` 报错，`extra="allow"` 保留到 `__pydantic_extra__`。

运行：py -3.11 -X utf8 demo3_nested_serialize.py
"""

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ------------------------------------------------------------- 叶子模型（严格）
class FieldRule(BaseModel):
    """要从文档里抽的字段定义。extra="forbid" —— 拼错 name 会当场报错。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64, description="字段名，如 invoice_no")
    type: str = Field(default="str", description="目标类型：str/int/float/date")
    required: bool = Field(default=True, description="是否必抽")


# ------------------------------------------------------------- 中间层（严格）
class ExtractOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str = Field(default="extract-v1", min_length=1, max_length=40)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)


# ------------------------------------------------------------- 顶层（严格）
class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1, max_length=64, description="文档 id")
    rules: list[FieldRule] = Field(min_length=1, description="至少一个抽取字段")
    options: ExtractOptions = Field(default_factory=ExtractOptions)


# ------------------------------------------------------------------ 1) 合法嵌套
print("== 1) 嵌套模型 + list[Model]：构造与访问 ==")
req = ExtractRequest(
    doc_id="doc-001",
    rules=[
        {"name": "invoice_no", "type": "str"},
        {"name": "total_amount", "type": "float", "required": False},
    ],
)
print(f"    req.doc_id              : {req.doc_id}")
print(f"    type(req.rules[0])      : {type(req.rules[0]).__name__}")
print(f"    req.rules[1].required   : {req.rules[1].required}")
print(f"    options 走 default_factory: {req.options!r}")


# ------------------------------------------------------ 2) 嵌套错误：loc 是路径
print("\n== 2) 嵌套校验失败：loc 给出完整路径 ==")
bad_payload = {
    "doc_id": "doc-002",
    "rules": [
        {"name": "invoice_no"},              # ok
        {"name": ""},                        # 违反 min_length=1
        {"name": "x", "typo_field": 1},      # extra="forbid" 在子模型上生效
    ],
}
try:
    ExtractRequest.model_validate(bad_payload)
except ValidationError as exc:
    print(f"    error_count() = {exc.error_count()}")
    for err in exc.errors():
        print(f"    loc={str(err['loc']):<22} type={err['type']:<18} msg={err['msg']}")


# ------------------------------------------------- 3) extra 不会自动往下传
print("\n== 3) extra='forbid' 只管自己那一层（不会自动继承给嵌套子模型）==")


class LooseChild(BaseModel):  # 没写 model_config -> 默认 ignore
    a: int


class StrictParent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child: LooseChild


try:
    StrictParent.model_validate({"child": {"a": 1}, "extra_on_parent": 1})
except ValidationError as exc:
    print(f"    父层多传字段 -> 报错 {exc.errors()[0]['loc']} / {exc.errors()[0]['type']}")

loose_ok = StrictParent.model_validate({"child": {"a": 1, "extra_on_child": 1}})
print(f"    子层多传字段 -> 静默丢弃：{loose_ok.model_dump()}"
      f"（子模型是默认 ignore，父模型的 forbid 管不到它）")


# ------------------------------------------------------- 4) 两种 dump 模式
class ExtractResult(BaseModel):
    doc_id: str
    fields: dict[str, str | int | float | None]
    confidence: float = Field(ge=0.0, le=1.0)
    finished_at: datetime


result = ExtractResult(
    doc_id="doc-001",
    fields={"invoice_no": "INV-2026-001", "total_amount": 1299.5, "note": None},
    confidence=0.93,
    finished_at=datetime(2026, 10, 22, 21, 20, 0),
)

print("\n== 4) model_dump() 默认 mode='python' vs mode='json' ==")
py_dump = result.model_dump()
json_dump = result.model_dump(mode="json")
print(f"    python 模式 finished_at : {py_dump['finished_at']!r}（还是 datetime 对象）")
print(f"    json   模式 finished_at : {json_dump['finished_at']!r}（ISO 8601 字符串）")
try:
    json.dumps(py_dump)  # 直接丢给标准库 json 会炸
except TypeError as exc:
    print(f"    json.dumps(python_dump) -> TypeError: {exc}")
print(f"    json.dumps(json_dump)   -> {json.dumps(json_dump, ensure_ascii=False)}")

print("\n    model_dump_json() 直接出字符串（推荐，中间不生成 dict）：")
as_json = result.model_dump_json(indent=2)
print("    " + as_json.replace("\n", "\n    "))

print("    常用裁剪：exclude_none / include / exclude")
print(f"    exclude_none=True      : {result.model_dump(mode='json', exclude_none=True)['fields']}")
print("        ^ 注意：fields 里的 'note': None 还在 —— exclude_none 只作用于**模型字段**，"
      "\n          不会钻进 dict 内部替你去掉 None 值")
print(f"    include={{'doc_id','confidence'}} : {result.model_dump(mode='json', include={'doc_id', 'confidence'})}")


# --------------------------------------------- 5) model_validate_json 往返
print("\n== 5) model_dump_json -> model_validate_json 往返 ==")
payload = result.model_dump_json()
back = ExtractResult.model_validate_json(payload)
print(f"    往返后相等            : {back == result}")
print(f"    finished_at 还原成    : {back.finished_at!r}")
print(f"    也接受 bytes          : {ExtractResult.model_validate_json(payload.encode()).doc_id}")

print("\n    错误定位在 JSON 上同样精确：")
try:
    ExtractResult.model_validate_json(
        '{"doc_id":"d","fields":{},"confidence":1.5,"finished_at":"2026-10-22T21:20:00"}'
    )
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    loc={err['loc']} type={err['type']} msg={err['msg']}")

print("    非法 JSON 文本本身也会抛 ValidationError（不是 json.JSONDecodeError）：")
try:
    ExtractResult.model_validate_json('{"doc_id": ')
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    type={err['type']} loc={err['loc']} msg={err['msg']}")


# ------------------------------------------------- 6) dict 字段的类型联合
print("\n== 6) dict[str, str|int|float|None]：值类型由联合校验 ==")
mixed = ExtractResult(
    doc_id="d",
    fields={"a": "text", "b": 42, "c": 1.5, "d": None},
    confidence=1,
    finished_at="2026-10-22T21:20:00",  # lax：字符串转 datetime
)
print(f"    允许的值类型           : {mixed.fields}")
try:
    ExtractResult(
        doc_id="d",
        fields={"bad": ["list", "not", "allowed"]},
        confidence=1,
        finished_at="2026-10-22T21:20:00",
    )
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    loc={err['loc']} type={err['type']}")
    print(f"    msg（联合类型会把每个分支都列出来）: {err['msg']}")


# --------------------------------------------- 7) 别名：内部 snake / 对外 camel
print("\n== 7) 对外 camelCase、内部 snake_case（alias）==")


class CamelModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    doc_id: str = Field(alias="docId", description="对外用 docId")
    page_size: int = Field(default=10, alias="pageSize")


camel = CamelModel.model_validate({"docId": "d", "pageSize": 20})  # 只认别名
print(f"    从 camel 入参构造      : {camel!r}")
print(f"    populate_by_name=True 时也认字段名: {CamelModel(doc_id='d').doc_id}")
print(f"    model_dump() 默认用字段名 : {camel.model_dump()}")
print(f"    model_dump(by_alias=True) : {camel.model_dump(by_alias=True)}")
print(f"    model_dump_json(by_alias=True): {camel.model_dump_json(by_alias=True)}")

print("\n[demo3] 全部断言通过。")
assert back == result
assert isinstance(py_dump["finished_at"], datetime)
assert isinstance(json_dump["finished_at"], str)
assert req.rules[1].required is False
assert mixed.fields["b"] == 42
