# -*- coding: utf-8 -*-
"""应用配置（验收要求：app/core/config.py）。

上一课（learn/pydantic_basics/app/core/config.py）已经证明「BaseSettings 能正确读 .env，
配置错在启动就炸」。这一课换一个问法：**这份配置怎么被"注入"到路由里？**

三个要点：

1. **不在 import 时解析。** `get_settings()` 外面套了 `lru_cache`，第一次调用发生在
   lifespan（启动）阶段。所以 `import app.main` 永远不会因为缺 API_KEY 而失败，
   但 `uvicorn app.main:app` 会在启动阶段明确报错 —— 早炸好过半夜炸。

2. **两层缓存正好互补**（本课依赖注入的核心收获）：
   - `lru_cache` → 进程级单例：整个进程只有一个 Settings 实例（`id()` 不变）；
   - FastAPI 依赖缓存（`Depends(..., use_cache=True)`，默认开）→ 请求级复用：
     同一请求里不管几处 `Depends(get_settings)`，只求值一次。
   实测对照见 verify_api.py 的 [D] 组。

3. **密钥永远不出明文。** 对外一律走 `public_info()`，api_key 恒为 `**********`。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/core/config.py -> app/core -> app -> 课程根（learn/fastapi_basics）
BASE_DIR = Path(__file__).resolve().parents[2]

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
AppEnv = Literal["dev", "staging", "prod"]


class Settings(BaseSettings):
    """全局配置。字段名即环境变量名（大小写不敏感）。

    优先级（pydantic-settings 内建）：
    构造参数 > 真实环境变量 > .env 文件 > 字段默认值。
    """

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 服务标识（喂给 /openapi.json 的 title / version）----
    app_name: str = Field(default="extract-api", min_length=1, max_length=40)
    app_version: str = Field(default="0.1.0", min_length=1, max_length=20)

    # ---- 运行环境 ----
    app_env: AppEnv = Field(default="dev", description="运行环境：dev / staging / prod")
    log_level: LogLevel = Field(default="INFO", description="日志级别")

    # ---- 第三方凭证 ----
    api_key: SecretStr = Field(description="第三方 / 大模型 API key，必填；日志与响应里只有掩码")

    # ---- 业务参数 ----
    request_timeout: float = Field(default=30.0, gt=0, le=300, description="单次请求超时（秒）")
    max_doc_chars: int = Field(default=8000, ge=200, le=50000, description="单文档最大字符数")
    extract_model: str = Field(default="extract-v1", min_length=1, max_length=40, description="默认抽取器版本")

    # ---------------- 规整（mode="before"：拿到原始值）----------------
    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, v: Any) -> Any:
        """允许 .env 里写 info / Info，统一转大写再交给 Literal 校验。"""
        return v.upper() if isinstance(v, str) else v

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_app_env(cls, v: Any) -> Any:
        return v.lower().strip() if isinstance(v, str) else v

    # ---------------- 跨字段（mode="after"：拿到已转换的实例）----------------
    @model_validator(mode="after")
    def _guard_prod(self) -> "Settings":
        if self.app_env == "prod":
            secret = self.api_key.get_secret_value()
            if len(secret) < 16:
                raise ValueError("生产环境 API_KEY 长度必须 >= 16")
            if secret.startswith("sk-test"):
                raise ValueError("生产环境不接受 sk-test 开头的测试密钥")
        return self

    # ---------------- 只读派生 ----------------
    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def api_key_masked(self) -> str:
        """`str(SecretStr)` 就是 `**********`；明文只能 .get_secret_value()。"""
        return str(self.api_key)

    def public_info(self) -> dict[str, Any]:
        """对外可暴露的配置摘要（喂给 GET /api/v1/config）。

        `config_id` 是故意暴露的：它是 `id(self)`，用来在验证脚本里证明
        "全进程只有一个 Settings 实例"。
        """
        return {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "app_env": self.app_env,
            "log_level": self.log_level,
            "extract_model": self.extract_model,
            "max_doc_chars": self.max_doc_chars,
            "request_timeout": self.request_timeout,
            "api_key": self.api_key_masked,  # 永远 **********
            "config_id": id(self),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """全进程单例。这个函数本身就是"配置依赖"：

        SettingsDep = Annotated[Settings, Depends(get_settings)]

    测试里要重载：`get_settings.cache_clear()`。
    """
    return Settings()


def reset_settings_cache() -> None:
    """显式重置（改完环境变量后想重新解析时用）。"""
    get_settings.cache_clear()


__all__ = [
    "Settings",
    "get_settings",
    "reset_settings_cache",
    "BASE_DIR",
    "AppEnv",
    "LogLevel",
]
