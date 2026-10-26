# -*- coding: utf-8 -*-
"""demo4：配置管理 —— pydantic-settings 的 BaseSettings 读 .env
21:30-22:00 配置管理

必答问题：.env、真实环境变量、代码里传参、字段默认值，谁说了算？
------------------------------------------------------------------------------
1) 优先级（从高到低）：**构造参数 > 环境变量 > .env 文件 > 字段默认值**。
   部署时"本地 .env 写 dev、服务器环境变量写 prod"就是靠这个：生产机上不用改代码也不用改 .env。
2) 键名匹配默认**大小写不敏感**（`API_KEY` / `api_key` / `Api_Key` 都认），
   真实环境变量和 init 参数都会走这套匹配。
3) `SecretStr` 是给密钥用的：`repr()`、`model_dump()`、`model_dump_json()`、日志里全是 `**********`，
   要真值必须显式 `.get_secret_value()` —— 防止一把日志把 key 泄出去。
4) 校验失败同样是 `ValidationError`，且发生在**启动时**。这是好事：配错了直接起不来，
   而不是跑到半夜某个请求才 500。缺必填项报 `missing`，取值不在枚举里报 `literal_error`。
5) `extra="ignore"`：.env 里多出来的键（别人留下的）不会让启动失败；
   写成 `extra="forbid"` 就会因为你没声明 `DATABASE_URL` 而拒绝启动 —— 两种风格各有取舍。
6) `@lru_cache` 包一层 `get_settings()`：全进程只解析一次 .env，处处 `get_settings()` 拿到同一个对象。

运行：py -3.11 -X utf8 demo4_settings_config.py
"""

import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ------------------------------------------------------------ 1) 声明 Settings
class Settings(BaseSettings):
    """应用配置。写法同 BaseModel，多了"从哪读"这一层。"""

    model_config = SettingsConfigDict(
        env_file=None,            # 真实项目里指到 app 根目录的 .env；这里由 demo 动态指定
        env_file_encoding="utf-8",
        case_sensitive=False,     # 大小写不敏感：API_KEY / api_key 都行
        extra="ignore",           # .env 里多出来的键不报错
    )

    app_env: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_key: SecretStr = Field(description="第三方 API key，必填且不落日志")
    request_timeout: float = Field(default=30.0, gt=0, le=300, description="单请求超时（秒）")

    # 允许 .env 里写小写 info：规整发生在类型校验之前
    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_level(cls, v):
        return v.upper() if isinstance(v, str) else v

    # 跨字段：生产环境不允许用短 key / 占位 key
    @model_validator(mode="after")
    def _prod_guard(self) -> "Settings":
        if self.app_env == "prod":
            secret = self.api_key.get_secret_value()
            if len(secret) < 16 or secret.startswith("sk-test"):
                raise ValueError("生产环境 API_KEY 必须是长度 >= 16 的真实密钥（不接受 sk-test 占位）")
        return self

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


# ------------------------------------------------------ 2) 从 .env 文件读
sample_env = """\
# 本地开发用的 .env（不要提交真实密钥；模板见 .env.example）
APP_ENV=staging
LOG_LEVEL=info
API_KEY=sk-local-dev-0123456789
REQUEST_TIMEOUT=15
"""

tmpdir = Path(tempfile.mkdtemp(prefix="pyd-demo4-"))
env_file = tmpdir / ".env"
env_file.write_text(sample_env, encoding="utf-8")

print("== 1) 从 .env 文件读取（.env 内容如下）==")
for line in sample_env.strip().splitlines():
    print(f"    {line}")

settings = Settings(_env_file=env_file)
print(f"\n    get()            : {settings.app_env!r}, {settings.log_level!r}, timeout={settings.request_timeout}")
print(f"    LOG_LEVEL=info 被规整: {settings.log_level!r}（before validator 转大写）")
print(f"    SecretStr        : {settings.api_key} / repr={settings.api_key!r}")
print(f"    model_dump()     : {settings.model_dump()}")
print(f"    model_dump_json(): {settings.model_dump_json()}")
print(f"    显式取值          : {settings.api_key.get_secret_value()}")
print(f"    is_prod          : {settings.is_prod}")


# ------------------------------------------- 3) 优先级：init > env > .env > 默认
print("\n== 2) 优先级：构造参数 > 环境变量 > .env > 默认值 ==")
print(f"    .env 说 staging          -> {Settings(_env_file=env_file).app_env}")

# 再造一份"生产机上误留测试 key"的 .env 来演示跨字段拦截
prod_env = tmpdir / "prod.env"
prod_env.write_text(
    "APP_ENV=staging\nAPI_KEY=sk-test-PLACEHOLDER\nREQUEST_TIMEOUT=15\n", encoding="utf-8"
)
os.environ["APP_ENV"] = "prod"
try:
    # 环境变量压过 .env：想用 prod 跑，但 .env 里还是测试 key -> model_validator 拦下
    Settings(_env_file=prod_env)
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    环境变量改成 prod        -> 被拦截 loc={err['loc']} msg={err['msg']}")
print(f"    再显式传参覆盖           -> {Settings(_env_file=prod_env, app_env='dev').app_env}"
      f"（构造参数赢过环境变量）")
os.environ.pop("APP_ENV", None)
print(f"    去掉环境变量又回到        -> {Settings(_env_file=env_file).app_env}")

print("\n    大小写不敏感：")
print(f"    APP_ENV=... 与 app_env=... 等价 -> {Settings(_env_file=env_file, APP_ENV='dev').app_env}")


# ----------------------------------------------- 4) 校验失败：启动就炸，不等到运行时
print("\n== 3) 配置错误在启动时暴露 ==")

missing_env = tmpdir / "missing.env"
missing_env.write_text("APP_ENV=dev\n", encoding="utf-8")  # 故意没有 API_KEY
try:
    Settings(_env_file=missing_env)
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    缺 API_KEY   -> loc={err['loc']} type={err['type']} msg={err['msg']}")

bad_env = tmpdir / "bad.env"
bad_env.write_text("APP_ENV=dev\nAPI_KEY=sk-abcdefghijklmnop\nLOG_LEVEL=verbose\n", encoding="utf-8")
try:
    Settings(_env_file=bad_env)
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    LOG_LEVEL 写错 -> loc={err['loc']} type={err['type']}")
    print(f"                     msg={err['msg']}")

bad_timeout = tmpdir / "timeout.env"
bad_timeout.write_text("APP_ENV=dev\nAPI_KEY=sk-abcdefghijklmnop\nREQUEST_TIMEOUT=0\n", encoding="utf-8")
try:
    Settings(_env_file=bad_timeout)
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    timeout=0     -> loc={err['loc']} type={err['type']} msg={err['msg']}")


# --------------------------------------------- 5) extra=ignore vs forbid
print("\n== 4) .env 里有未声明的键时 ==")
extra_env = tmpdir / "extra.env"
extra_env.write_text(
    "APP_ENV=dev\nAPI_KEY=sk-abcdefghijklmnop\nLEGACY_DB_URL=postgres://old\n", encoding="utf-8"
)
print(f"    extra='ignore' -> 正常启动：{Settings(_env_file=extra_env).app_env}"
      f"（LEGACY_DB_URL 被无视）")


class StrictSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="forbid")

    app_env: str = "dev"
    api_key: str = ""  # 声明齐了，这样报错才只会来自 LEGACY_DB_URL


try:
    StrictSettings(_env_file=extra_env)
except ValidationError as exc:
    err = exc.errors()[0]
    print(f"    extra='forbid' -> 启动失败：loc={err['loc']} type={err['type']} msg={err['msg']}")
    print("        ^ 报的是未知键本身的位置，适合'宁可起不来也别带着错配置跑'的项目")


# --------------------------------------------- 6) 单例：get_settings + lru_cache
print("\n== 5) 用 @lru_cache 做配置单例 ==")
from functools import lru_cache


@lru_cache(maxsize=1)
def get_settings(env_path: str | None = None) -> Settings:
    return Settings(_env_file=env_path)


a, b = get_settings(str(env_file)), get_settings(str(env_file))
print(f"    两次调用返回同一对象: {a is b}")
print(f"    环境里改了也不影响已缓存实例: ", end="")
os.environ["APP_ENV"] = "prod"
print(f"{get_settings(str(env_file)).app_env}")
os.environ.pop("APP_ENV", None)
get_settings.cache_clear()
print(f"    cache_clear() 后重新解析  : {get_settings(str(env_file)).app_env}"
      f"（测试里常用；生产不调）")

print("\n    真实项目的 config.py 见 app/core/config.py（同一套写法 + 指向 app 根目录的 .env）")

# 清理
for p in tmpdir.iterdir():
    p.unlink()
tmpdir.rmdir()

print("\n[demo4] 全部断言通过。")
assert settings.log_level == "INFO"
assert settings.app_env == "staging"
assert a is b
