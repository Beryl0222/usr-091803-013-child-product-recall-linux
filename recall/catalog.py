"""型号、批次、固件、适龄结论、功能开关与付费规则的登记册。

登记是后续一切处置的锚点：检测结论、停售、远程关闭与召回都按
"型号 + 批次 + 固件"圈定版本，因此这里要求先登记、后引用，
引用不存在的型号、批次或固件一律报错。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class RiskLevel(Enum):
    """功能风险等级，高风险能力需要家长同意并按年龄与场景逐步开放。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


#: 基础通话、紧急求助与必要定位是核心能力：任何开关、远程关闭或
#: 其他功能的停用都不得让它们失效。
CORE_CAPABILITIES = frozenset({"basic_call", "sos", "location"})


@dataclass(frozen=True)
class ProductModel:
    """一个登记在册的手表型号。"""

    code: str
    brand: str
    name: str


@dataclass(frozen=True)
class Firmware:
    """一个固件版本。"""

    version: str
    released_at: datetime


@dataclass(frozen=True)
class Batch:
    """一个生产批次，绑定型号与出厂固件。"""

    code: str
    model: str
    firmware: str
    produced_at: datetime
    quantity: int


@dataclass(frozen=True)
class Capability:
    """一项可开关的功能及其开放门槛。

    ``scenarios`` 为空表示不限场景；``paid`` 为真时必须登记付费规则。
    """

    code: str
    name: str
    risk: RiskLevel
    min_age: int = 0
    scenarios: frozenset[str] = frozenset()
    paid: bool = False


@dataclass(frozen=True)
class PaymentRule:
    """付费功能的金额上限（单位：分）与同意要求。"""

    capability: str
    max_per_transaction: int
    max_per_day: int
    requires_consent: bool = True


@dataclass(frozen=True)
class AgeSuitability:
    """一次适龄结论。结论变化时追加新记录，历史永不覆盖。"""

    model: str
    firmware: str
    min_age: int
    summary: str
    assessor: str
    decided_at: datetime


@dataclass(frozen=True)
class SwitchEvent:
    """一次功能开关变更，留痕以便还原"哪个版本什么时候开了什么"。"""

    model: str
    firmware: str
    capability: str
    enabled: bool
    changed_at: datetime
    reason: str = ""


class Catalog:
    """登记册：所有登记行为与适龄结论、开关变更历史的唯一入口。"""

    def __init__(self) -> None:
        self._models: dict[str, ProductModel] = {}
        self._firmwares: dict[str, Firmware] = {}
        self._batches: dict[str, Batch] = {}
        self._capabilities: dict[str, Capability] = {}
        self._payment_rules: dict[str, PaymentRule] = {}
        self._suitability: list[AgeSuitability] = []
        self._switch_events: list[SwitchEvent] = []

    # ------------------------------------------------------------------
    # 基础登记
    # ------------------------------------------------------------------
    def register_model(self, model: ProductModel) -> None:
        if model.code in self._models:
            raise ValueError(f"型号已登记：{model.code}")
        self._models[model.code] = model

    def register_firmware(self, firmware: Firmware) -> None:
        if firmware.version in self._firmwares:
            raise ValueError(f"固件已登记：{firmware.version}")
        self._firmwares[firmware.version] = firmware

    def register_batch(self, batch: Batch) -> None:
        if batch.code in self._batches:
            raise ValueError(f"批次已登记：{batch.code}")
        if batch.model not in self._models:
            raise KeyError(f"批次引用了未登记的型号：{batch.model}")
        if batch.firmware not in self._firmwares:
            raise KeyError(f"批次引用了未登记的固件：{batch.firmware}")
        self._batches[batch.code] = batch

    def register_capability(self, capability: Capability) -> None:
        if capability.code in CORE_CAPABILITIES:
            raise ValueError(f"核心能力不可作为可开关功能登记：{capability.code}")
        if capability.code in self._capabilities:
            raise ValueError(f"功能已登记：{capability.code}")
        self._capabilities[capability.code] = capability

    def register_payment_rule(self, rule: PaymentRule) -> None:
        capability = self.find_capability(rule.capability)
        if capability is None:
            raise KeyError(f"付费规则引用了未登记的功能：{rule.capability}")
        if not capability.paid:
            raise ValueError(f"功能未声明付费，不能登记付费规则：{rule.capability}")
        self._payment_rules[rule.capability] = rule

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def find_model(self, code: str) -> ProductModel | None:
        return self._models.get(code)

    def find_batch(self, code: str) -> Batch | None:
        return self._batches.get(code)

    def find_firmware(self, version: str) -> Firmware | None:
        return self._firmwares.get(version)

    def find_capability(self, code: str) -> Capability | None:
        return self._capabilities.get(code)

    def payment_rule_for(self, capability: str) -> PaymentRule | None:
        return self._payment_rules.get(capability)

    # ------------------------------------------------------------------
    # 适龄结论：只追加
    # ------------------------------------------------------------------
    def record_suitability(self, conclusion: AgeSuitability) -> int:
        """登记一次适龄结论，返回其修订号（从 1 开始）。"""
        if conclusion.model not in self._models:
            raise KeyError(f"适龄结论引用了未登记的型号：{conclusion.model}")
        if conclusion.firmware not in self._firmwares:
            raise KeyError(f"适龄结论引用了未登记的固件：{conclusion.firmware}")
        self._suitability.append(conclusion)
        return len(self.suitability_history(conclusion.model, conclusion.firmware))

    def suitability_history(self, model: str, firmware: str) -> tuple[AgeSuitability, ...]:
        return tuple(
            item for item in self._suitability if item.model == model and item.firmware == firmware
        )

    def current_suitability(self, model: str, firmware: str) -> AgeSuitability | None:
        history = self.suitability_history(model, firmware)
        return history[-1] if history else None

    # ------------------------------------------------------------------
    # 功能开关：只追加事件，当前状态由最新事件决定
    # ------------------------------------------------------------------
    def set_switch(
        self,
        model: str,
        firmware: str,
        capability: str,
        enabled: bool,
        *,
        changed_at: datetime,
        reason: str = "",
    ) -> SwitchEvent:
        if capability in CORE_CAPABILITIES:
            raise ValueError(f"核心能力不允许设置开关：{capability}")
        if capability not in self._capabilities:
            raise KeyError(f"未登记的功能：{capability}")
        if model not in self._models:
            raise KeyError(f"未登记的型号：{model}")
        if firmware not in self._firmwares:
            raise KeyError(f"未登记的固件：{firmware}")
        event = SwitchEvent(model, firmware, capability, enabled, changed_at, reason)
        self._switch_events.append(event)
        return event

    def switch_enabled(self, model: str, firmware: str, capability: str) -> bool:
        """非核心功能默认关闭，须显式开启后才可能向儿童开放。"""
        for event in reversed(self._switch_events):
            if (
                event.model == model
                and event.firmware == firmware
                and event.capability == capability
            ):
                return event.enabled
        return False

    def switch_history(self, model: str, firmware: str) -> tuple[SwitchEvent, ...]:
        return tuple(
            event
            for event in self._switch_events
            if event.model == model and event.firmware == firmware
        )
