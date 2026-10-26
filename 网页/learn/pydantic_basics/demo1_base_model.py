# -*- coding: utf-8 -*-
"""demo1：基础模型 —— BaseModel / Field / 可选字段
20:00-20:35 基础模型

必答问题：Field(ge=..., max_length=...) 这类约束，到底在什么时候、由谁执行？
------------------------------------------------------------------------------
结论先放这里：
1) 约束是**声明在类上的**，执行时机是**实例化时**（`Model(...)`、`Model.model_validate(...)`、
   `Model.model_validate_json(...)`）。不是定义类时，也不是访问属性时。
2) 执行者不是 Python 解释器，而是 pydantic-core（Rust）在 `__init__` 里做的一遍校验。
   校验不通过抛 `ValidationError`（它是 `ValueError` 的子类）。
3) 类型检查是 **lax（宽松）模式**：`"42"` 会变成 `42`，`"2026-10-22"` 会变成 `date`，
   但 `"abc"` 转不成 int 依旧报错。宽松 ≠ 不校验。
4) 默认 `extra="ignore"`：多传的字段被**静默丢弃**（demo3 会换成 forbid）。
5) 默认**赋值不校验**：`m.count = -1` 不报错；要管住得开 `validate_assignment=True`。

运行：py -3.11 -X utf8 demo1_base_model.py
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ---------------------------------------------------------------- 1) 最小模型
class DocMeta(BaseModel):
    """最朴素的模型：只声明类型。"""

    doc_id: str
    page_count: int


print("== 1) 最小模型：类型声明 + 实例化时校验 ==")
meta = DocMeta(doc_id="doc-001", page_count=12)
print(f"    repr           : {meta!r}")
print(f"    访问属性        : {meta.doc_id}")
print(f"    model_fields   : {list(DocMeta.model_fields)}")

# lax 模式：字符串能转成 int
print(f"    宽松转换        : DocMeta(doc_id='d', page_count='12').page_count -> "
      f"{DocMeta(doc_id='d', page_count='12').page_count!r}（str -> int）")
try:
    DocMeta(doc_id="d", page_count="十二")
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    转不动就报错    : type={err['type']} loc={err['loc']} msg={err['msg']}")


# ------------------------------------------------------- 2) Field 的约束与文档
class ExtractOptions(BaseModel):
    """Field(...) 一次写两件事：运行时的约束 + 给人和给机器看的文档。"""

    max_chars: int = Field(default=8000, ge=200, le=50000, description="单文档最多处理的字符数")
    temperature: float = Field(default=0.0, ge=0.0, le=1.0, description="抽取温度，越大越发散")
    model_name: str = Field(default="extract-v1", min_length=1, max_length=40, description="模型名")
    tags: list[str] = Field(default_factory=list, description="打标")


print("\n== 2) Field(description=, ge=, le=, min_length=, max_length=) ==")
opts = ExtractOptions(max_chars=4000)
print(f"    默认值生效      : {opts.model_dump()}")

for bad in ({"max_chars": 100}, {"temperature": 1.5}, {"model_name": ""}):
    try:
        ExtractOptions(**bad)
    except ValidationError as exc:
        err = exc.errors()[0]
        print(f"    拒绝 {bad!s:<20} -> loc={err['loc']} type={err['type']:<20} input={err['input']!r}")

# 这些约束同时会出现在 JSON Schema 里 —— 前端表单、OpenAPI 文档都靠它
schema = ExtractOptions.model_json_schema()["properties"]
print(f"    schema.max_chars : {schema['max_chars']}")
print(f"    schema.temperature: min={schema['temperature']['minimum']} max={schema['temperature']['maximum']}")

# 可变默认值必须用 default_factory：直接写 [] 会被所有实例共享（pydantic 会深拷贝兜底，但别赌）
opts_a, opts_b = ExtractOptions(), ExtractOptions()
opts_a.tags.append("shared?")
print(f"    default_factory : a={opts_a.tags}, b={opts_b.tags}（互不影响）")


# --------------------------------------------------------- 3) 可选字段三种写法
class TimeWindow(BaseModel):
    """3.10+ 的 `X | None` 写法；v1 时代是 Optional[X]，别写成 `?` 也别漏 default。"""

    occurred_from: date | None = Field(default=None, description="起始日期，None 表示不限制")
    occurred_to: date | None = Field(default=None, description="结束日期，None 表示不限制")


print("\n== 3) 可选字段 str | None = None ==")
print(f"    都不传          : {TimeWindow().model_dump()}")
print(f"    显式 None       : {TimeWindow(occurred_from=None).model_dump()}")
print(f"    只传一个        : {TimeWindow(occurred_from=date(2026, 10, 22)).model_dump()}")
try:
    TimeWindow(occurred_from="2026/10/22")
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    日期格式不对    : loc={err['loc']} msg={err['msg']}")


# --------------------------------------------------- 4) 默认 extra=ignore 的坑
print("\n== 4) 默认 extra='ignore'：多传的字段被静默丢弃 ==")
with_extra = DocMeta(doc_id="d", page_count=1, typo_pagecount=99)
print(f"    传了 typo_pagecount=99 -> 模型里只有 {with_extra.model_dump()}（拼错字段没人告诉你）")
forbidden = ConfigDict(extra="forbid")  # 预告 demo3


# ------------------------------------------- 5) 默认赋值不校验 vs validate_assignment
class Counter(BaseModel):
    count: int = Field(default=0, ge=0)


class StrictCounter(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    count: int = Field(default=0, ge=0)


print("\n== 5) 赋值校验默认是关的 ==")
c = Counter()
c.count = -5  # 不报错！
print(f"    Counter       : c.count = -5 之后 -> {c.count}（实例已经是非法状态）")
s = StrictCounter()
try:
    s.count = -5
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    StrictCounter : 赋值当场报错 loc={err['loc']} msg={err['msg']}，值仍是 {s.count}")

print("\n[demo1] 全部断言通过。")
assert meta.page_count == 12
assert DocMeta(doc_id="d", page_count="12").page_count == 12
assert opts_b.tags == []
assert TimeWindow().occurred_from is None
assert with_extra.model_dump() == {"doc_id": "d", "page_count": 1}
assert c.count == -5 and s.count == 0
