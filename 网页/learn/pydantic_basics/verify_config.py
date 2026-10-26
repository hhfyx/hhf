# -*- coding: utf-8 -*-
"""证明 app/core/config.py 能正确读 .env（21:30-22:00 配置管理段的验收）。

不依赖仓库里是否有 .env：本脚本用临时 .env + `_env_file` 覆盖来验证，
跑完即删，不会在你的工作区留下密钥。

运行：py -3.11 -X utf8 verify_config.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings, get_settings

PASSED = 0
FAILED: list[str] = []


def check(cond: bool, desc: str, detail: str = "") -> None:
    global PASSED
    if cond:
        PASSED += 1
        print(f"  [OK  ] {desc}" + (f"  -> {detail}" if detail else ""))
    else:
        FAILED.append(f"{desc}  {detail}")
        print(f"  [FAIL] {desc}  -> {detail}")


tmpdir = Path(tempfile.mkdtemp(prefix="pyd-verify-config-"))
env_path = tmpdir / ".env"
env_path.write_text(
    "APP_ENV=dev\nLOG_LEVEL=debug\nAPI_KEY=sk-local-dev-0123456789\nREQUEST_TIMEOUT=12\n",
    encoding="utf-8",
)

print("== 1) 读 .env：三个必填/关注项 ==")
s = Settings(_env_file=env_path)
check(s.app_env == "dev", "APP_ENV 读到了", s.app_env)
check(s.log_level == "DEBUG", "LOG_LEVEL=debug 被规整成大写", s.log_level)
check(s.api_key.get_secret_value() == "sk-local-dev-0123456789", "API_KEY 读到了", s.api_key.get_secret_value()[:8] + "...")
check(s.request_timeout == 12.0, "REQUEST_TIMEOUT 转成了 float", str(s.request_timeout))

print("\n== 2) SecretStr 不会泄进日志 / dump ==")
check("sk-local-dev" not in repr(s), "repr 里没有明文 key", repr(s)[:60])
check("sk-local-dev" not in s.model_dump_json(), "model_dump_json 里没有明文 key", s.model_dump_json())
check(s.model_dump_json().count("**********") == 1, "密钥位打码成 **********")

print("\n== 3) 优先级：构造参数 > 环境变量 > .env ==")
os.environ["APP_ENV"] = "staging"
try:
    check(Settings(_env_file=env_path).app_env == "staging", "环境变量压过 .env")
    check(
        Settings(_env_file=env_path, app_env="prod", api_key="a" * 20).app_env == "prod",
        "构造参数压过环境变量",
    )
finally:
    os.environ.pop("APP_ENV", None)
check(Settings(_env_file=env_path).app_env == "dev", "去掉环境变量后回到 .env 的值")

print("\n== 4) 非法配置在启动时被拒 ==")


def expect_fail(payload_env: str, desc: str, *, expect_loc) -> None:
    p = tmpdir / f"bad-{expect_loc[0] if expect_loc else 'model'}-{len(FAILED)}.env"
    p.write_text(payload_env, encoding="utf-8")
    try:
        Settings(_env_file=p)
    except ValidationError as exc:
        locs = [e["loc"] for e in exc.errors()]
        check(expect_loc in locs, desc, f"loc={locs}")
    else:
        check(False, desc, "本应失败却通过了")
    finally:
        p.unlink(missing_ok=True)


expect_fail("APP_ENV=dev\n", "缺 API_KEY", expect_loc=("api_key",))
expect_fail("APP_ENV=dev\nAPI_KEY=sk-abcdefghijklmnop\nLOG_LEVEL=verbose\n", "LOG_LEVEL 不在枚举内", expect_loc=("log_level",))
expect_fail("APP_ENV=prod\nAPI_KEY=sk-test-1234567890\n", "prod 拒绝 sk-test 密钥", expect_loc=())
expect_fail("APP_ENV=dev\nAPI_KEY=sk-abcdefghijklmnop\nREQUEST_TIMEOUT=0\n", "REQUEST_TIMEOUT=0 越界", expect_loc=("request_timeout",))
expect_fail(
    "APP_ENV=prod\nAPI_KEY=sk-abcdefghijklmnop1234\nLOG_SQL=true\n",
    "prod 不允许 LOG_SQL=true",
    expect_loc=(),
)

print("\n== 5) get_settings() 是单例 ==")
get_settings.cache_clear()
os.environ.setdefault("API_KEY", "sk-unittest-0123456789")
try:
    # get_settings 读模块级 .env（仓库根），若不存在则全靠环境变量 -> 这里只验单例语义
    a, b = get_settings(), get_settings()
    check(a is b, "两次调用返回同一对象")
    get_settings.cache_clear()
    check(get_settings() is not a, "cache_clear() 之后是新对象")
finally:
    if os.environ.get("API_KEY") == "sk-unittest-0123456789":
        os.environ.pop("API_KEY", None)
    get_settings.cache_clear()

env_path.unlink()
tmpdir.rmdir()

print("\n" + "=" * 60)
print(f"通过 {PASSED} 项，失败 {len(FAILED)} 项")
if FAILED:
    for f in FAILED:
        print(f"  [失败] {f}")
    sys.exit(1)
print("配置管理全部通过。")
