# -*- coding: utf-8 -*-
"""demo2：校验器 —— @field_validator / @model_validator(mode="after") 与报错格式
20:35-21:05 校验器

必答问题：单字段规则和跨字段规则分别写在哪，失败时的报错长什么样？
------------------------------------------------------------------------------
1) 单字段：`@field_validator("字段名"[,"字段名2"])` + `@classmethod`，函数签名 `(cls, v)`，
   必须 return 值（不 return 等于把字段变成 None）。默认 `mode="after"` —— 拿到的是**已转换**的值
   （`date` 对象而不是 str）；要拿原始输入做整形就写 `mode="before"`。
2) 跨字段：`@model_validator(mode="after")`，签名 `(self)`，必须 `return self`。
   用它判"结束日期不能早于开始日期"这类字段间关系。报错时 `loc=()`（错误不属于某个字段）。
3) 报错是 `ValidationError`（`ValueError` 子类），有两个层次：
   - `str(exc)`  → 给人看的多行文本
   - `exc.errors()` → 给程序看的结构化列表，每条含 type / loc / msg / input / url
4) 聚合语义：**字段级**失败（Field 约束 + field_validator）会被**一起收集**，报完所有字段的问题；
   但只要有一个字段级失败，`model_validator(mode="after")` 就**不会执行**（实例没构造出来，
   跨字段规则没法判）。所以"多个字段错"和"跨字段错"通常不会同时出现在同一个 errors() 里。
   反过来，同一个 model_validator 内部 raise 也只会报第一条。
5) 自己 raise 的异常会被包一层：`raise ValueError("x")` -> `msg="Value error, x"`，`type="value_error"`。
   想保留干净的 msg，用 `pydantic_core.PydanticCustomError`（这里只提一句，不展开）。

运行：py -3.11 -X utf8 demo2_validators.py
"""

import warnings
from datetime import date

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


# ------------------------------------------------------------------ 业务模型
class MaintenanceWindow(BaseModel):
    """运维窗口：起止日期 + 变更单号 + 影响面。"""

    change_id: str = Field(min_length=3, max_length=32, description="变更单号，如 CHG-20261022")
    started_on: date
    ended_on: date
    impacted_services: list[str] = Field(min_length=1, description="受影响服务，至少 1 个")

    # ---- 单字段：after（默认）拿到的已经是 date 对象 ----
    @field_validator("change_id")
    @classmethod
    def _change_id_format(cls, v: str) -> str:
        upper = v.upper()  # 先规整再判；注意返回值才是最终落库的值
        if not upper.startswith("CHG-"):
            raise ValueError("change_id 必须以 CHG- 开头")
        if not upper[4:].isdigit():
            raise ValueError("change_id 的 CHG- 之后必须全是数字，例如 CHG-20261022")
        return upper

    # ---- 单字段：before 拿到原始输入，适合"先整形" ----
    @field_validator("impacted_services", mode="before")
    @classmethod
    def _split_services(cls, v):
        if isinstance(v, str):  # 允许 "api,db" 这种逗号串
            return [part.strip() for part in v.split(",") if part.strip()]
        return v

    # ---- 跨字段：结束不能早于开始 ----
    @model_validator(mode="after")
    def _check_order(self) -> "MaintenanceWindow":
        if self.ended_on < self.started_on:
            raise ValueError(
                f"结束日期不能早于开始日期（先 {self.started_on} 后 {self.ended_on}）"
            )
        return self


print("== 1) 合法输入：before 整形 + after 规整生效 ==")
ok = MaintenanceWindow(
    change_id="chg-20261022",
    started_on="2026-10-22",
    ended_on=date(2026, 10, 23),
    impacted_services="api, db , cache",
)
print(f"    change_id          : {ok.change_id!r}（validator 里 .upper() 了）")
print(f"    impacted_services  : {ok.impacted_services}（before 把逗号串拆成了 list）")
print(f"    started_on 类型     : {type(ok.started_on).__name__}（lax 转换发生在 before 之后、after 之前）")


# ------------------------------------------------------------ 2) 单字段失败
print("\n== 2) 单字段校验失败：str(exc) 长什么样 ==")
try:
    MaintenanceWindow(
        change_id="TICKET-1",
        started_on="2026-10-22",
        ended_on="2026-10-23",
        impacted_services=["api"],
    )
except ValidationError as exc:
    print("    ---- str(exc) ----")
    for line in str(exc).splitlines():
        print(f"    {line}")


# ------------------------------------------------------ 3) 跨字段失败（loc=()）
print("\n== 3) 跨字段校验失败：model_validator(mode='after') 的报错位置 ==")
try:
    MaintenanceWindow(
        change_id="CHG-20261022",
        started_on="2026-10-23",
        ended_on="2026-10-22",  # 结束早于开始
        impacted_services=["api"],
    )
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    error_count()  : {exc.error_count()}")
    print(f"    type           : {err['type']}")
    print(f"    loc            : {err['loc']}   <- 空元组，说明错误不属于任何单字段")
    print(f"    msg            : {err['msg']}")
    print(f"    input          : {err['input']!r}")
    print(f"    url            : {err['url']}")
    print("    ---- str(exc) ----")
    for line in str(exc).splitlines()[:3]:
        print(f"    {line}")


# ------------------------------------------------------ 4) 多条错误一起收集
print("\n== 4) field 级错误会一起收集；但只要有字段级失败，model_validator 就不跑 ==")
try:
    MaintenanceWindow(
        change_id="BAD",
        started_on="2026-10-22",
        ended_on="2026-10-23",
        impacted_services=[],
    )
except ValidationError as exc:
    print(f"    error_count() = {exc.error_count()}（change_id 格式 + impacted_services 为空，两条同时报）")
    for err in exc.errors():
        print(f"    loc={str(err['loc']):<12} type={err['type']:<22} msg={err['msg']}")

print("\n    再试一次：字段全合法 + 日期倒置 -> 只有 model 级那一条")
try:
    MaintenanceWindow(
        change_id="CHG-20261022",
        started_on="2026-10-23",
        ended_on="2026-10-22",
        impacted_services=["api"],
    )
except ValidationError as exc:
    print(f"    error_count() = {exc.error_count()}，唯一一条 loc={exc.errors()[0]['loc']}")

print("    而一旦字段级失败，跨字段规则根本轮不到：")
try:
    MaintenanceWindow(
        change_id="X",  # 字段级失败
        started_on="2026-10-23",
        ended_on="2026-10-22",  # 日期也倒置
        impacted_services=["api"],
    )
except ValidationError as exc:
    print(f"    error_count() = {exc.error_count()}，只报 {[e['loc'] for e in exc.errors()]}"
          f" —— '结束不能早于开始' 这条被跳过了")
    print("    -> 设计含义：跨字段校验依赖字段值可用，字段都不可信时它宁可不跑，也别猜")


# ------------------------------------------------- 5) 把报错翻译成 API 错误体
print("\n== 5) 把 ValidationError 转成对外错误体（前端能直接展示）==")


def to_api_errors(exc: ValidationError) -> list[dict]:
    """loc 元组 -> '字段名' 字符串；loc=() 的 model 级错误归到 '_model'。"""
    out = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "_model"
        msg = err["msg"]
        msg = msg.removeprefix("Value error, ")  # 去掉 pydantic 自己加的前缀
        out.append({"field": field, "reason": msg, "type": err["type"]})
    return out


try:
    MaintenanceWindow(
        change_id="CHG-abc",
        started_on="2026-10-23",
        ended_on="2026-10-22",
        impacted_services=["api"],
    )
except ValidationError as exc:
    print(f"    {to_api_errors(exc)}")


# ------------------------------------------- 6) v1 写法在 v2 里是什么下场
print("\n== 6) 别被旧教程带偏：@validator / class Config 在 v2 里会报警告 ==")
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")

    from pydantic import validator  # v1 名字，v2 只是留了个弃用的壳

    class LegacyModel(BaseModel):
        name: str

        class Config:  # v1 写法
            extra = "forbid"

        @validator("name")  # v1 写法
        def _strip(cls, v):
            return v.strip()

    LegacyModel(name="  hi  ")

for w in caught:
    print(f"    {w.category.__name__}: {str(w.message).splitlines()[0][:110]}")
print("    -> v2 正确写法：@field_validator / @model_validator + model_config = ConfigDict(...)")

# ValidationError 是 ValueError 的子类，所以 `except ValueError` 也能兜住
print(f"\n    ValidationError 是 ValueError 子类: {issubclass(ValidationError, ValueError)}")
try:
    MaintenanceWindow(change_id="CHG-1", started_on="x", ended_on="y", impacted_services=["a"])
except ValueError:  # 更宽的捕获也能兜住
    print("    except ValueError 也能捕获 ValidationError")

print("\n[demo2] 全部断言通过。")
assert ok.change_id == "CHG-20261022"
assert ok.impacted_services == ["api", "db", "cache"]
