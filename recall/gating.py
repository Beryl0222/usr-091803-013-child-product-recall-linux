"""分级开放门禁：高风险能力按年龄与场景逐步开放。

判定顺序固定，任一环节不满足即拒绝并给出中文原因：

1. 核心能力（基础通话、紧急求助、必要定位）永远放行——
   其他功能被停用、被远程关闭都不影响它们；
2. 功能须已登记，且对应型号/固件的开关已显式开启；
3. 儿童年龄须同时满足适龄结论与功能自身的年龄门槛；
4. 使用场景须在功能允许的场景集合内；
5. 高风险或付费功能须取得家长同意；付费功能还须有付费规则。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from recall.catalog import CORE_CAPABILITIES, Catalog, RiskLevel
from recall.consent import ConsentBook


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str


class FeatureGate:
    """面向单台设备、单个儿童的功能开放判定。"""

    def __init__(self, catalog: Catalog, consent: ConsentBook) -> None:
        self._catalog = catalog
        self._consent = consent

    def decide(
        self,
        *,
        serial: str,
        model: str,
        firmware: str,
        capability: str,
        age: int,
        scenario: str,
        at: datetime | None = None,
    ) -> GateDecision:
        if capability in CORE_CAPABILITIES:
            return GateDecision(True, "核心能力（基础通话/紧急求助/必要定位）不受开关与处置影响")

        registered = self._catalog.find_capability(capability)
        if registered is None:
            return GateDecision(False, f"功能未登记：{capability}")

        if not self._catalog.switch_enabled(model, firmware, capability):
            return GateDecision(False, f"功能开关未开启：{capability}")

        suitability = self._catalog.current_suitability(model, firmware)
        if suitability is not None and age < suitability.min_age:
            return GateDecision(False, f"低于适龄结论（{suitability.min_age} 岁起）")

        if age < registered.min_age:
            return GateDecision(False, f"低于功能年龄门槛（{registered.min_age} 岁起）")

        if registered.scenarios and scenario not in registered.scenarios:
            return GateDecision(False, f"场景未开放：{scenario}")

        needs_consent = registered.risk is RiskLevel.HIGH
        if registered.paid:
            rule = self._catalog.payment_rule_for(capability)
            if rule is None:
                return GateDecision(False, f"付费功能缺少付费规则：{capability}")
            needs_consent = needs_consent or rule.requires_consent

        if needs_consent and not self._consent.is_granted(serial, capability, at=at):
            return GateDecision(False, f"未取得家长同意：{capability}")

        return GateDecision(True, "开放")
