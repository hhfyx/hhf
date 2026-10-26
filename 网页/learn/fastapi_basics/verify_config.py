# -*- coding: utf-8 -*-
"""配置自检：证明 app/core/config.py 读对了，且配置错在启动就炸。

跑法（在 learn/fastapi_basics 下）：

    py -3.11 -X utf8 verify_config.py

这一课的重点不是"能不能读 .env"（上一课已证明），而是**它怎么跟依赖注入配合**：

- `get_settings()` 有 `lru_cache` → 跨请求同一个对象；
- 改环境变量后必须 `cache_clear()` 才生效 —— 否则测试之间会互相污染，
  这是"缓存"的另一面，很多人只记住好处不记住代价。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import ValidationError

from app.core.config import BASE_DIR, Settings, get_settings, reset_settings_cache

PASS = 0
FAIL = 0
FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(f"{name}{(' | ' + detail) if detail else ''}")
        print(f"  [FAIL] {name} {detail}")


def eq(name: str, actual, expected) -> None:
    check(name, actual == expected, f"期望={expected!r} 实际={actual!r}")


def section(t: str) -> None:
    print(f"\n=== {t} ===")


_MINIMAL = {"api_key": "sk-local-dev-0123456789"}


def main() -> int:
    section("A. .env 读取与优先级")
    eq("A1 BASE_DIR 指到课程根", BASE_DIR.name, "fastapi_basics")
    check("A2 .env 存在（先复制 .env.example）", (BASE_DIR / ".env").exists())

    s = get_settings()
    check("A3 读到 api_key", s.api_key.get_secret_value().startswith("sk-"))
    eq("A4 app_name", s.app_name, "extract-api")
    eq("A5 log_level 规整成大写", s.log_level, s.log_level.upper())
    check("A6 max_doc_chars 在合法区间", 200 <= s.max_doc_chars <= 50000, str(s.max_doc_chars))

    # 环境变量盖过 .env
    reset_settings_cache()
    os.environ["MAX_DOC_CHARS"] = "12345"
    try:
        eq("A7 真实环境变量盖过 .env", get_settings().max_doc_chars, 12345)
    finally:
        os.environ.pop("MAX_DOC_CHARS", None)
        reset_settings_cache()
    eq("A8 撤销环境变量后回落 .env", get_settings().max_doc_chars, s.max_doc_chars)

    section("B. lru_cache 单例")
    a, b = get_settings(), get_settings()
    check("B1 两次调用是同一对象", a is b, f"{id(a)} vs {id(b)}")
    eq("B2 id() 稳定", id(a), id(b))
    reset_settings_cache()
    c = get_settings()
    check("B3 cache_clear 后是新对象", c is not a, "缓存没清掉，测试会互相污染")

    section("C. SecretStr 不漏明文")
    eq("C1 repr 是掩码", str(s.api_key), "**********")
    eq("C2 掩码属性", s.api_key_masked, "**********")
    check("C3 model_dump 里没有明文",
          s.api_key.get_secret_value() not in str(s.model_dump()),
          "明文泄露了")
    check("C4 只有 get_secret_value 给明文", s.api_key.get_secret_value().startswith("sk-"))

    section("D. 配置错误在启动就炸")
    # 缺必填
    try:
        Settings(_env_file=None, api_key=None)  # type: ignore[arg-type]
        check("D1 缺 api_key 应报错", False, "居然没报错")
    except (ValidationError, TypeError) as e:
        check("D1 缺 api_key 报错", True)

    # 非法枚举
    try:
        Settings(_env_file=None, api_key="sk-x", app_env="production")  # type: ignore[arg-type]
        check("D2 非法 app_env 应报错", False, "居然没报错")
    except ValidationError as e:
        check("D2 非法 app_env 报错", "app_env" in str(e), str(e)[:120])

    # 越界数值
    try:
        Settings(_env_file=None, api_key="sk-x", request_timeout=0)  # type: ignore[arg-type]
        check("D3 timeout=0 应报错", False, "居然没报错")
    except ValidationError as e:
        check("D3 timeout=0 报错", "request_timeout" in str(e), str(e)[:120])

    # 跨字段：prod + 短密钥
    try:
        Settings(_env_file=None, api_key="sk-short", app_env="prod")  # type: ignore[arg-type]
        check("D4 prod 短密钥应报错", False, "居然没报错")
    except ValidationError as e:
        check("D4 prod 短密钥报错", "生产环境" in str(e), str(e)[:160])

    # 跨字段：prod + sk-test
    try:
        Settings(_env_file=None, api_key="sk-test-0123456789abcdef", app_env="prod")  # type: ignore[arg-type]
        check("D5 prod 测试密钥应报错", False, "居然没报错")
    except ValidationError as e:
        check("D5 prod 测试密钥报错", "sk-test" in str(e), str(e)[:160])

    # 合法 prod 要能通过
    ok = Settings(_env_file=None, api_key="sk-live-0123456789abcdef", app_env="prod")  # type: ignore[arg-type]
    eq("D6 合法 prod 配置通过", ok.app_env, "prod")
    eq("D6 is_prod", ok.is_prod, True)

    # 缺配置时 get_settings 抛错 → 说明"启动即炸"
    reset_settings_cache()
    saved = os.environ.pop("API_KEY", None)
    try:
        # .env 里还有 API_KEY，所以要临时屏蔽 env_file
        try:
            Settings(_env_file=None)  # type: ignore[arg-type]
            check("D7 完全无配置时 get_settings 抛错", False, "居然没报错")
        except ValidationError as e:
            check("D7 完全无配置时抛错（启动即炸）", "api_key" in str(e), str(e)[:120])
    finally:
        if saved is not None:
            os.environ["API_KEY"] = saved
        reset_settings_cache()

    section("E. public_info 对外安全")
    info = s.public_info()
    eq("E1 api_key 是掩码", info["api_key"], "**********")
    eq("E2 config_id 是 id(self)", info["config_id"], id(s))
    check("E3 摘要里没有明文密钥",
          s.api_key.get_secret_value() not in str(info),
          "明文泄露了")

    print("\n" + "=" * 60)
    print(f"通过 {PASS} 项，失败 {FAIL} 项")
    if FAIL:
        print("\n失败清单：")
        for f in FAILS:
            print(f"  - {f}")
        print("=" * 60)
        return 1
    print("全部通过：配置读取、优先级、单例、SecretStr、启动即炸 都成立。")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
