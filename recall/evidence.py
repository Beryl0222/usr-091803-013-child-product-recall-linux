"""处置证据：退款、换货、拒绝升级与超期未处理，全程留痕。

证据只追加。退款、换货、拒绝升级都属于"已处理"的终态证据；
超过处置期限仍没有任何终态证据的设备，可以推导出"超期未处理"
证据，且同一设备同一处置单只推导一次，不会重复记录。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class EvidenceKind(Enum):
    REFUND = "refund"                        # 退款
    EXCHANGE = "exchange"                    # 换货
    UPGRADE_DECLINED = "upgrade_declined"    # 家庭拒绝升级
    OVERDUE = "overdue"                      # 超期未处理


#: 视为"已处理"的终态证据。
TERMINAL_KINDS = frozenset(
    {EvidenceKind.REFUND, EvidenceKind.EXCHANGE, EvidenceKind.UPGRADE_DECLINED}
)


@dataclass(frozen=True)
class EvidenceRecord:
    """一条处置证据。"""

    evidence_id: str
    order_id: str
    serial: str
    kind: EvidenceKind
    detail: str
    recorded_at: datetime


class EvidenceLedger:
    """证据账本：只追加，可按处置单或序列号还原。"""

    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []
        self._sequence = 0

    def record(
        self,
        order_id: str,
        serial: str,
        kind: EvidenceKind,
        *,
        detail: str,
        at: datetime,
    ) -> EvidenceRecord:
        self._sequence += 1
        entry = EvidenceRecord(
            evidence_id=f"EVD-{self._sequence:05d}",
            order_id=order_id,
            serial=serial,
            kind=kind,
            detail=detail,
            recorded_at=at,
        )
        self._records.append(entry)
        return entry

    def for_order(self, order_id: str) -> tuple[EvidenceRecord, ...]:
        return tuple(entry for entry in self._records if entry.order_id == order_id)

    def for_serial(self, serial: str) -> tuple[EvidenceRecord, ...]:
        return tuple(entry for entry in self._records if entry.serial == serial)

    def is_processed(self, order_id: str, serial: str) -> bool:
        """设备在该处置单下是否已有终态证据（退款/换货/拒绝升级）。"""
        return any(
            entry.order_id == order_id and entry.serial == serial and entry.kind in TERMINAL_KINDS
            for entry in self._records
        )

    def mark_overdue(
        self,
        order_id: str,
        serials: list[str] | tuple[str, ...],
        *,
        deadline: datetime,
        now: datetime,
    ) -> tuple[EvidenceRecord, ...]:
        """对超过期限仍无终态证据的设备补记"超期未处理"，幂等。"""
        if now <= deadline:
            return ()
        created: list[EvidenceRecord] = []
        for serial in serials:
            if self.is_processed(order_id, serial):
                continue
            already = any(
                entry.order_id == order_id
                and entry.serial == serial
                and entry.kind is EvidenceKind.OVERDUE
                for entry in self._records
            )
            if already:
                continue
            created.append(
                self.record(
                    order_id,
                    serial,
                    EvidenceKind.OVERDUE,
                    detail=f"超过处置期限 {deadline.isoformat()} 仍未处理",
                    at=now,
                )
            )
        return tuple(created)
