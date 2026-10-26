# -*- coding: utf-8 -*-
"""应用配置（验收要求：app/core/config.py）。

设计要点：
1. 一处声明、全局复用：`get_settings()` 用 lru_cache 保证全进程只解析一次 .env。
2. 优先级：构造参数 > 真实环境变量 > .env 文件 > 字段默认值（pydantic-settings 内建）。
   —— 所以生产机上 `export APP_ENV=prod` 就能盖掉仓库里的 .env，不用改代码。
3. 配置错误必须在**启动时**炸：缺 API_KEY、APP_ENV 拼错、超时 <= 0，都会在
   `get_settings()` 第一次被调用时抛 ValidationError，而不是等到半夜某个请求。
4. 密钥用 SecretStr：repr / model_dump / model_dump_json / 日志里都是 `**********`，
   只有显式 `.get_secret_value()` 才拿得到明文。
5. `extra="ignore"`：.env 里遗留的旧键（DATABASE_URL 之类）不会让启动失败；
   想让拼错的键 / 未声明的键直接失败就换成 `extra="forbid"`。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/core/config.py -> app/core -> app -> 项目根（learn/pydantic_basics）
BASE_DIR = Path(__file__).resolve().parents[2]

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
AppEnv = Literal["dev", "staging", "prod"]


class Settings(BaseSettings):
    """全局配置。字段名即环境变量名（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 运行环境 ----
    app_env: AppEnv = Field(default="dev", description="运行环境：dev / staging / prod")
    log_level: LogLevel = Field(default="INFO", description="日志级别")
    log_sql: bool = Field(default=False, description="是否打印 SQL（仅 dev 建议开）")

    # ---- 第三方凭证 ----
    api_key: SecretStr = Field(description="大模型 / 第三方 API key，必填；不会出现在日志里")

    # ---- 业务参数 ----
    request_timeout: float = Field(default=30.0, gt=0, le=300, description="单次请求超时（秒）")
    max_doc_chars: int = Field(default=8000, ge=200, le=50000, description="单文档最大字符数")
    extract_model: str = Field(default="extract-v1", min_length=1, max_length=40, description="默认抽取模型")

    # ---------------- 规整 ----------------
    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, v):
        """允许 .env 里写 info / Info，统一转大写再交给 Literal 校验。"""
        return v.upper() if isinstance(v, str) else v

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_app_env(cls, v):
        return v.lower().strip() if isinstance(v, str) else v

    # ---------------- 跨字段 ----------------
    @model_validator(mode="after")
    def _guard_prod(self) -> "Settings":
        if self.app_env == "prod":
            secret = self.api_key.get_secret_value()
            if len(secret) < 16:
                raise ValueError("生产环境 API_KEY 长度必须 >= 16")
            if secret.startswith("sk-test"):
                raise ValueError("生产环境不接受 sk-test 开头的测试密钥")
            if self.log_sql:
                raise ValueError("生产环境不允许开启 log_sql（会泄露数据）")
        return self

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """全进程单例。测试里若需重载：`get_settings.cache_clear()`。"""
    return Settings()


__all__ = ["Settings", "get_settings", "BASE_DIR"]
