# -*- coding: utf-8 -*-
"""业务模型（验收要求的 3 个模型）。

- ExtractRequest：抽取请求。规则：至少 1 个抽取字段；起止日期不能倒置；extra 禁止。
- ExtractResult ：抽取结果。规则：confidence ∈ [0,1]；fields 的 key 必须⊆请求里的 rules；
                  finished_at >= started_at。
- ErrorResponse ：统一错误体。规则：code 非空且大写；message 长度受限；
                  retryable=True 时必须给 retry_after_s；details 最多 20 条。

每个模型至少 1 条校验规则（Field 约束或 validator），见各类的 docstring。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FieldType = Literal["str", "int", "float", "date"]


# ============================================================== 1) 抽取请求
class ExtractRequest(BaseModel):
    """文档抽取请求。

    校验规则：
    1. `doc_id` 1-64 字符；`rules` 至少 1 条（Field 约束）。
    2. `rules[].name` 不允许重复（跨字段，model_validator）。
    3. `started_on`/`ended_on` 可空，但两者都给时"结束日期不能早于开始日期"（跨字段）。
       必须是 `date | None` 而不是 `str | None` —— 声明成 str 的话 "2026/10/01" 这种脏值
       会被原样放过去，"结束早于开始"也只能按字符串字典序比，跨年就出错了。
       （本文件第一版正是写成了 str，被 verify_rejects.py 当场揪出来。）
    4. `extra="forbid"`：不接受未声明字段，拼错就报错。
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1, max_length=64, description="文档 id")
    rules: list["FieldRule"] = Field(min_length=1, description="至少一个抽取字段")
    started_on: date | None = Field(default=None, description="文档日期下界（lax 转换，'2026-10-01' 也行）")
    ended_on: date | None = Field(default=None, description="文档日期上界")

    @model_validator(mode="after")
    def _no_duplicate_rule(self) -> "ExtractRequest":
        names = [r.name for r in self.rules]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise ValueError(f"rules 中存在重复字段名：{', '.join(dup)}")
        return self

    @model_validator(mode="after")
    def _date_range(self) -> "ExtractRequest":
        if self.started_on and self.ended_on and self.ended_on < self.started_on:
            raise ValueError(
                f"结束日期不能早于开始日期：started_on={self.started_on}, ended_on={self.ended_on}"
            )
        return self


class FieldRule(BaseModel):
    """单个抽取字段定义。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64, description="字段名，如 invoice_no")
    type: FieldType = Field(default="str", description="目标类型")
    required: bool = Field(default=True, description="是否必抽")

    @field_validator("name")
    @classmethod
    def _snake_case(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError("name 只能包含字母、数字和下划线")
        if v != v.lower():
            raise ValueError("name 必须是小写 snake_case")
        return v


# ============================================================== 2) 抽取结果
class ExtractResult(BaseModel):
    """文档抽取结果。

    校验规则：
    1. `confidence` ∈ [0, 1]（Field 约束）。
    2. `started_at` 必须有值；`finished_at >= started_at`（跨字段）。
    3. 可选 `allowed_fields`：给出时，`fields` 的 key 必须都在其中（跨字段），
       防止模型幻觉出不存在的字段。
    4. 必抽字段（required=True）缺失时由调用方用 `missing_required()` 检查 —— 需要请求上下文，
       所以不放进模型自身的 validator（模型只管自洽，业务交叉在 service 层）。
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1, max_length=64)
    fields: dict[str, str | int | float | None] = Field(
        default_factory=dict, description="抽出来的字段名 -> 值"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="整体置信度")
    started_at: datetime = Field(description="开始处理时间")
    finished_at: datetime = Field(description="结束处理时间")
    allowed_fields: set[str] | None = Field(
        default=None, exclude=True, description="内部校验用：允许出现的字段名集合"
    )

    @model_validator(mode="after")
    def _time_order(self) -> "ExtractResult":
        if self.finished_at < self.started_at:
            raise ValueError(
                f"finished_at 不能早于 started_at："
                f"{self.started_at.isoformat()} -> {self.finished_at.isoformat()}"
            )
        return self

    @model_validator(mode="after")
    def _fields_whitelist(self) -> "ExtractResult":
        if self.allowed_fields is not None:
            unknown = sorted(set(self.fields) - self.allowed_fields)
            if unknown:
                raise ValueError(f"fields 含未声明的字段（疑似幻觉）：{', '.join(unknown)}")
        return self

    def missing_required(self, rules: list[FieldRule]) -> list[str]:
        """业务层交叉校验：必抽字段有没有抽到。需要 request，故不放进模型。"""
        return [r.name for r in rules if r.required and not self.fields.get(r.name)]


# ============================================================== 3) 统一错误体
class ErrorResponse(BaseModel):
    """对外统一错误体。

    校验规则：
    1. `code` 必须是大写、下划线分隔的错误码（field_validator）。
    2. `message` 1-500 字符（Field 约束）。
    3. `retryable=True` 时必须给 `retry_after_s` 且 > 0（跨字段）。
    4. `details` 最多 20 条（Field 约束）。
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, description="错误码，如 INVALID_INPUT")
    message: str = Field(min_length=1, max_length=500, description="给人看的说明")
    retryable: bool = Field(default=False, description="调用方是否可重试")
    retry_after_s: float | None = Field(default=None, gt=0, description="建议重试间隔（秒）")
    details: list[dict[str, Any]] = Field(default_factory=list, max_length=20, description="字段级明细")

    @field_validator("code")
    @classmethod
    def _code_format(cls, v: str) -> str:
        if v != v.upper():
            raise ValueError("code 必须全大写")
        if not all(ch.isalnum() or ch == "_" for ch in v):
            raise ValueError("code 只能包含大写字母、数字和下划线")
        return v

    @model_validator(mode="after")
    def _retry_after_required(self) -> "ErrorResponse":
        if self.retryable and self.retry_after_s is None:
            raise ValueError("retryable=True 时必须给出 retry_after_s")
        return self

    @classmethod
    def from_validation_error(cls, exc: Exception, code: str = "INVALID_INPUT") -> "ErrorResponse":
        """把 pydantic 的 ValidationError 翻译成对外错误体（demo5 会用）。"""
        from pydantic import ValidationError as PydanticValidationError

        if not isinstance(exc, PydanticValidationError):
            return cls(code=code, message=str(exc)[:500])
        details = []
        for err in exc.errors():
            field = ".".join(str(p) for p in err["loc"]) or "_model"
            details.append(
                {
                    "field": field,
                    "reason": err["msg"].removeprefix("Value error, "),
                    "type": err["type"],
                }
            )
        first = details[0]["reason"] if details else "输入非法"
        return cls(code=code, message=f"{len(details)} 个字段校验失败：{first}"[:500], details=details)


ExtractRequest.model_rebuild()

__all__ = ["ExtractRequest", "ExtractResult", "ErrorResponse", "FieldRule", "FieldType"]
