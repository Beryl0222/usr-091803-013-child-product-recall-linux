"""检测结论的版本化登记。

检测结论会随复检、投诉核查而变化。每次变化都作为新修订追加，
旧结论完整保留，处置单引用具体修订号，从而"哪一版结论触发了
哪一次处置"永远可以还原。结论通过版本范围圈定受影响的设备。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ConclusionStatus(Enum):
    PASS = "pass"  # 未发现风险
    RISK = "risk"  # 发现风险，需要处置


@dataclass(frozen=True)
class VersionScope:
    """圈定受影响版本：型号必填，批次/固件为空集表示不限。"""

    model: str
    batches: frozenset[str] = frozenset()
    firmwares: frozenset[str] = frozenset()

    def matches(self, *, model: str, batch: str, firmware: str) -> bool:
        if model != self.model:
            return False
        if self.batches and batch not in self.batches:
            return False
        if self.firmwares and firmware not in self.firmwares:
            return False
        return True


@dataclass(frozen=True)
class DetectionConclusion:
    """一次检测结论。``revision`` 按型号递增，从 1 开始。"""

    conclusion_id: str
    scope: VersionScope
    status: ConclusionStatus
    summary: str
    issued_by: str
    issued_at: datetime
    revision: int


class DetectionRegistry:
    """结论登记处：同一型号的结论只追加，不覆盖。"""

    def __init__(self) -> None:
        self._conclusions: list[DetectionConclusion] = []
        self._sequence = 0

    def issue(
        self,
        scope: VersionScope,
        status: ConclusionStatus,
        *,
        summary: str,
        issued_by: str,
        at: datetime,
    ) -> DetectionConclusion:
        self._sequence += 1
        revision = len(self.history(scope.model)) + 1
        conclusion = DetectionConclusion(
            conclusion_id=f"DC-{self._sequence:04d}",
            scope=scope,
            status=status,
            summary=summary,
            issued_by=issued_by,
            issued_at=at,
            revision=revision,
        )
        self._conclusions.append(conclusion)
        return conclusion

    def history(self, model: str) -> tuple[DetectionConclusion, ...]:
        return tuple(item for item in self._conclusions if item.scope.model == model)

    def current(self, model: str) -> DetectionConclusion | None:
        history = self.history(model)
        return history[-1] if history else None
