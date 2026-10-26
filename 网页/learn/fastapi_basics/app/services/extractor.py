# -*- coding: utf-8 -*-
"""规则版抽取器（验收要求：app/services/extractor.py，先写规则版）。

**不 import fastapi** —— 这是分层的硬约束，也是能 `python -m` 直接跑的证明。

规则版做什么：从纯文本里按字段名 + 正则抽值。覆盖最常见的四类字段
（单号 / 日期 / 金额 / 普通文本），不做语义理解 —— 语义理解是下一步接大模型的事，
这一课的重点是**把 HTTP 外壳搭对**，抽取本身越简单越好，"坏掉的时候一眼看得出是
哪一层的问题"。

设计要点：

1. 规则表按字段名的"语义线索"匹配（`invoice_no` / `order_no` / `*_date` / `amount`
   之类），抽不到就 `None`，绝不编造。编造字段值是上一课 ExtractResult 里
   `allowed_fields` 想拦的东西。

2. 置信度是**启发式**：命中字段比例 × 一个惩罚项。真实系统里这个值应来自模型，
   这里只为了让 `response_model` 的 `ge=0, le=1` 有东西可校验。

3. `ResourceRegistry` 是"启动时加载、关闭时释放"的载体（lifespan 用它），
   把词表 / 正则表集中在这里，而不是每次请求重新编译。

4. `RuleExtractReport` 是**服务层自己的返回值类型**，故意不是 pydantic 模型：
   schemas/ 描述对外契约，services/ 描述内部结果，两者解耦。
   api 层负责把 Report 翻译成 ExtractResult。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Mapping

# ---- 字段名 -> 语义类别；决定用哪组正则去抓 ----
FIELD_KIND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (r"(?:invoice|order|contract|doc|ref)(?:_no|_id|_code|no)$", re.compile(r"[A-Z0-9][A-Z0-9\-]{5,31}")),
    (r"(?:amount|total|price|fee|cost|tax)(?:_cny|_usd|_amt)?$", re.compile(r"\d[\d,]*(?:\.\d{1,2})?")),
    (r"date$", re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}")),
    (r"(?:email|mail)$", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
)

_CN_AMOUNT = re.compile(r"(?:金额|合计|总计|税额)\s*[:：]?\s*[¥￥]?\s*(\d[\d,]*(?:\.\d{1,2})?)")
_EN_AMOUNT = re.compile(r"(?:amount|total|price)\s*[:：]\s*[¥￥$]?\s*(\d[\d,]*(?:\.\d{1,2})?)", re.I)
_CN_DATE = re.compile(r"(?:日期|开票日|签订日|到期日)\s*[:：]?\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})")
_CN_NO = re.compile(r"(?:发票号|单号|编号|合同号)\s*[:：]?\s*([A-Z0-9][A-Z0-9\-]{4,31})")


@dataclass
class RuleExtractReport:
    """服务层内部结果（不是对外契约，api 层要翻译成 ExtractResult）。"""

    doc_id: str
    fields: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    confidence: float = 0.0
    model: str = "rule-v1"
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime = field(default_factory=datetime.now)
    # 内部诊断信息：不对外暴露，只用于日志
    debug: dict[str, Any] = field(default_factory=dict)


class ResourceRegistry:
    """启动时加载、关闭时释放的资源容器（lifespan 里创建）。

    现在装的是正则表和一份小词表；将来换成 DB 连接池 / 模型 client，
    生命周期语义完全一样 —— 这也是这节课用 lifespan 的意义：
    资源获取和释放写在同一处，中间件的并发安全由启动时机保证。

    实际做法：**在 __init__ 里就把正则编译好**，请求期间只做匹配，零编译开销。
    """

    def __init__(self, *, max_doc_chars: int, extract_model: str) -> None:
        self.max_doc_chars = max_doc_chars
        self.extract_model = extract_model

        # 编译一次，全程复用
        self.kind_rules: tuple[tuple[str, re.Pattern[str]], ...] = FIELD_KIND_PATTERNS
        self.cn_amount = _CN_AMOUNT
        self.en_amount = _EN_AMOUNT
        self.cn_date = _CN_DATE
        self.cn_no = _CN_NO

        self.closed = False

    @classmethod
    def load(cls, settings: Any) -> "ResourceRegistry":
        """从配置构造。这里故意用 `Any` 而不是 `Settings` 类型 ——
        services 层不 import core 的类型，保持"业务不依赖配置实现"的淡耦合。
        """
        return cls(max_doc_chars=settings.max_doc_chars, extract_model=settings.extract_model)

    def close(self) -> None:
        """lifespan 关闭时调用。幂等 —— 避免重复关闭报错。"""
        if not self.closed:
            self.closed = True

    def summary(self) -> dict[str, Any]:
        """给 /health 用：证明资源确实加载了。"""
        return {
            "max_doc_chars": self.max_doc_chars,
            "rule_groups": len(self.kind_rules),
            "closed": self.closed,
        }

    def __repr__(self) -> str:
        return f"<ResourceRegistry max_doc_chars={self.max_doc_chars} closed={self.closed}>"


class RuleBasedExtractor:
    """规则版抽取器。纯计算，无 IO，无 fastapi。

    用法：
        registry = ResourceRegistry.load(settings)
        ext = RuleBasedExtractor(registry=registry)
        report = ext.run(doc_id="d1", text="...", rules=[...])
        # report.fields / report.missing / report.confidence
    """

    def __init__(self, *, registry: ResourceRegistry, version: str = "rule-v1") -> None:
        self.registry = registry
        self.version = version

    # ------------------------------------------------------------ 对外主入口
    def run(
        self,
        *,
        doc_id: str,
        text: str,
        rules: Iterable[Mapping[str, Any]],
        started_on: date | None = None,
        ended_on: date | None = None,
    ) -> RuleExtractReport:
        """按 rules 抽值。rules 的每项含 name / type / required。

        `started_on` / `ended_on` 对应文档级日期范围，只作为**兜底**：
        字段本身没抓到日期时，若给了范围就填范围下界（常见业务约定），
        并把 confidence 打折 —— 提醒调用方"这是猜的，不是抽的"。
        """
        started_at = datetime.now()
        fields: dict[str, Any] = {}
        missing: list[str] = []
        rule_list = list(rules)

        for rule in rule_list:
            name = str(rule["name"])
            required = bool(rule.get("required", True))
            ftype = str(rule.get("type", "str"))

            value = self._extract_one(name=name, text=text, doc_id=doc_id)

            if value is None and ftype == "date" and started_on is not None:
                value = started_on.isoformat()
                fields[name] = value
                continue

            if value is None:
                fields[name] = None
                if required:
                    missing.append(name)
                continue

            fields[name] = self._coerce(value, ftype, name)

        finished_at = datetime.now()
        confidence = self._confidence(rule_list, fields, missing, started_on, ended_on)

        return RuleExtractReport(
            doc_id=doc_id,
            fields=fields,
            missing=missing,
            confidence=confidence,
            model=self.version,
            started_at=started_at,
            finished_at=finished_at,
        )

    # ------------------------------------------------------------ 内部
    def _extract_one(self, *, name: str, text: str, doc_id: str) -> str | None:
        """单个字段的抽取策略：先中文标签，再英文标签，最后按字段名语义挑正则。

        顺序是有讲究的：中文标签最准（`发票号：XXX`），先试；英文 label 次之；
        最后才用"裸正则"扫全文 —— 那是最容易误抓的兜底。
        """
        lower = name.lower()

        # 1) 中文标签
        if "amount" in lower or "total" in lower or "金额" in name:
            m = self.registry.cn_amount.search(text) or self.registry.en_amount.search(text)
            if m:
                return m.group(1)
        if "date" in lower or "日期" in name:
            m = self.registry.cn_date.search(text)
            if m:
                return m.group(1)
        if re.search(r"(?:no|id|code)$", lower):
            m = self.registry.cn_no.search(text)
            if m:
                return m.group(1)

        # 2) 按字段名匹配语义类别，在全文里找
        for pattern, regex in self.registry.kind_rules:
            if re.search(pattern, lower):
                hit = regex.search(text)
                if hit:
                    return hit.group(0)

        # 3) 兜底：文本里恰好有同名字段（"xxx: value" 形式）
        m = re.search(rf"{re.escape(name)}\s*[:：]\s*(\S+)", text, re.I)
        return m.group(1) if m else None

    def _coerce(self, raw: str, ftype: str, name: str) -> Any:
        """按声明的 type 转换。转不动就保留原串 —— 不丢数据，也不瞎猜。

        注意 datetime 用 `fromisoformat` 之前要统一分隔符，否则 "2026/10/23" 会炸；
        这里直接 replace 成 "-"，因为日期三种写法（- / 年）我们都收。
        """
        if ftype == "str":
            return raw
        cleaned = raw.replace(",", "").strip()
        try:
            if ftype == "int":
                return int(float(cleaned))
            if ftype == "float":
                return float(cleaned)
            if ftype == "date":
                norm = cleaned.replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
                return date.fromisoformat(norm).isoformat()
        except (ValueError, TypeError):
            return raw
        return raw

    def _confidence(
        self,
        rules: list[Mapping[str, Any]],
        fields: Mapping[str, Any],
        missing: list[str],
        started_on: date | None,
        ended_on: date | None,
    ) -> float:
        """启发式置信度：命中率为主，两处打折。

        - 全部必抽字段都缺 → 0.0（宁可报低，也别让上层以为抽成功了）
        - 用了"日期范围兜底" → 打 0.7 折（那是猜的）
        """
        if not rules:
            return 0.0
        total = len(rules)
        hit = sum(1 for r in rules if fields.get(str(r["name"])) is not None)
        if total and hit == 0:
            return 0.0

        score = hit / total

        # 有必抽字段缺失：按缺失比例二次打折
        required_missing = sum(1 for r in rules if r.get("required", True) and str(r["name"]) in missing)
        if required_missing:
            score *= 1 - 0.5 * (required_missing / total)

        # 日期兜底（started_on 被当成了字段值）：标记不确定
        used_fallback = any(
            str(r.get("type")) == "date" and fields.get(str(r["name"])) is not None
            for r in rules
        ) and started_on is not None
        if used_fallback:
            score *= 0.7

        return round(min(1.0, max(0.0, score)), 3)


__all__ = ["FIELD_KIND_PATTERNS", "ResourceRegistry", "RuleBasedExtractor", "RuleExtractReport"]
