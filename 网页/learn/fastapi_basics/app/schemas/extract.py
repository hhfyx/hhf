# -*- coding: utf-8 -*-
"""对外契约（请求体 / 响应体）。

**本文件最重要的一个知识点（实测踩出来的）：**

    请求模型用 extra="forbid"  → 客户端多传字段 = 422，好事；
    响应模型用 extra="forbid"  → 服务层多返回字段 = ResponseValidationError = 500！

因为 `response_model` 不是"注释"，它是一次**真实的校验**。`forbid` 让这次校验
在遇到多余键时直接失败，而 `ignore` 才是"悄悄裁掉"。所以本文件里：

- `ExtractRequest` / `FieldRule`（入参）：`extra="forbid"` —— 拼错字段立刻报错；
- `ExtractResult` / `HealthResponse` / `ConfigInfo`（出参）：`extra="ignore"`
  —— 这才是 `response_model` 被当作"出参过滤器"用的正确前提。
- `ErrorResponse` / `ErrorDetail`（出参）：同为出参，用 `ignore`。

代价：出参模型自己写错字段名时不会报错，只会得到一个 `null`。
所以**出参模型要靠 verify_api.py 断言键集合**，不能靠 forbid。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FieldType = Literal["str", "int", "float", "date"]

# 两类配置，名字写清楚，避免以后有人"顺手统一"
REQUEST_CONFIG = ConfigDict(extra="forbid")   # 入参：严格，多一个都不行
RESPONSE_CONFIG = ConfigDict(extra="ignore")  # 出参：宽松，多出来的裁掉


# ============================================================== 请求
class FieldRule(BaseModel):
    """单个抽取字段定义（入参）。"""

    model_config = REQUEST_CONFIG

    name: str = Field(min_length=1, max_length=64, description="字段名，如 invoice_no")
    type: FieldType = Field(default="str", description="目标类型")
    required: bool = Field(default=True, description="是否必抽")

    @field_validator("name")
    @classmethod
    def _snake_case(cls, v: str) -> str:
        """只允许小写 snake_case —— 规则表按名字匹配语义，名字脏了匹配就乱。"""
        if not v.replace("_", "").isalnum():
            raise ValueError("name 只能包含字母、数字和下划线")
        if v != v.lower():
            raise ValueError("name 必须是小写 snake_case")
        return v


class ExtractRequest(BaseModel):
    """文档抽取请求（入参）。

    这一课的重点不是校验规则（上一课已经练过），而是它**会怎样出现在 /docs 里**：
    `doc_id` / `text` / `rules` 的 description 会直接变成 Swagger UI 的输入提示。
    去 /docs 点开 POST /api/v1/extract → Try it out，看到的就是这些字。
    """

    model_config = REQUEST_CONFIG

    doc_id: str = Field(min_length=1, max_length=64, description="文档 id，由调用方生成")
    text: str = Field(min_length=1, description="待抽取的正文纯文本")
    rules: list[FieldRule] = Field(min_length=1, description="至少要声明一个抽取字段")
    started_on: date | None = Field(default=None, description="文档日期下界，可空")
    ended_on: date | None = Field(default=None, description="文档日期上界，可空")

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


# ============================================================== 响应
class ExtractResult(BaseModel):
    """文档抽取结果（出参，`response_model` 卡这个形状）。

    因为 `extra="ignore"`，服务层多返回的键会被**裁掉**而不是报错 ——
    这才是"`response_model` 是出参过滤器"的正确配置。见 /api/v1/extract/raw 的对照。
    """

    model_config = RESPONSE_CONFIG

    doc_id: str = Field(description="原样回传的文档 id")
    fields: dict[str, str | int | float | None] = Field(
        default_factory=dict, description="抽出来的字段名 -> 值；抽不到为 None"
    )
    missing: list[str] = Field(default_factory=list, description="必抽但没抽到的字段名")
    confidence: float = Field(ge=0.0, le=1.0, description="整体置信度（规则版是启发式）")
    model: str = Field(description="产出这份结果的抽取器版本")
    started_at: datetime = Field(description="开始处理时间")
    finished_at: datetime = Field(description="结束处理时间")

    @model_validator(mode="after")
    def _time_order(self) -> "ExtractResult":
        if self.finished_at < self.started_at:
            raise ValueError(
                f"finished_at 不能早于 started_at："
                f"{self.started_at.isoformat()} -> {self.finished_at.isoformat()}"
            )
        return self


class ErrorDetail(BaseModel):
    """字段级错误明细（422 时逐条给出，前端靠 `field` 高亮输入框）。"""

    model_config = RESPONSE_CONFIG

    field: str = Field(description="出错字段路径，如 rules.1.name；跨字段错误为 _model")
    reason: str = Field(description="给人看的原因")


class ErrorResponse(BaseModel):
    """统一错误响应体 —— 所有非 2xx 都是这个形状。

    任务点名的三件套 `{code, message, request_id}` 就在这里。
    `request_id` 由中间件塞进 `request.state`，异常处理器再取出来，
    所以**报错响应里也有它**，拿它去日志里能捞到这一次请求的完整链路。
    """

    model_config = RESPONSE_CONFIG

    code: str = Field(description="错误码，如 INVALID_INPUT / NOT_FOUND / INTERNAL_ERROR")
    message: str = Field(description="给人看的一句话")
    request_id: str = Field(description="本次请求 id，报障时报这个")
    details: list[ErrorDetail] = Field(default_factory=list, description="字段级明细，可为空")


class HealthResponse(BaseModel):
    """健康检查。`resources` 证明 lifespan 里加载的资源确实活着。"""

    model_config = RESPONSE_CONFIG

    status: Literal["ok", "degraded"] = Field(description="整体状态")
    uptime_s: float = Field(description="进程已运行秒数")
    resources: dict[str, Any] = Field(default_factory=dict, description="lifespan 加载的资源摘要")


class ConfigInfo(BaseModel):
    """`GET /api/v1/config` 的出参：配置摘要，密钥永远是掩码。"""

    model_config = RESPONSE_CONFIG

    app_name: str = Field(description="服务名")
    app_version: str = Field(description="版本")
    app_env: str = Field(description="运行环境")
    log_level: str = Field(description="日志级别")
    extract_model: str = Field(description="默认抽取器版本")
    max_doc_chars: int = Field(description="单文档最大字符数")
    request_timeout: float = Field(description="单次请求超时（秒）")
    api_key: str = Field(description="掩码后的密钥，恒为 **********")
    config_id: int = Field(description="Settings 实例 id，用来验证进程内单例")


__all__ = [
    "ConfigInfo",
    "ErrorDetail",
    "ErrorResponse",
    "ExtractRequest",
    "ExtractResult",
    "FieldRule",
    "FieldType",
    "HealthResponse",
    "REQUEST_CONFIG",
    "RESPONSE_CONFIG",
]
