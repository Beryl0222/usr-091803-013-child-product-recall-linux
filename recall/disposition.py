"""处置：检测结论变化后，对指定版本分阶段停售、远程关闭或召回。

每张处置单都引用触发它的检测结论修订，并按版本范围圈定设备，
因此可以精确回答"哪个版本的哪些设备被如何处置"。远程关闭只能
针对非核心能力——基础通话、紧急求助与必要定位在任何处置下
都必须保持可用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from recall.catalog import CORE_CAPABILITIES, Catalog
from recall.detection import VersionScope


class DispositionType(Enum):
    STOP_SALE = "stop_sale"            # 分阶段停售
    REMOTE_DISABLE = "remote_disable"  # 远程关闭高风险能力
    RECALL = "recall"                  # 召回


@dataclass(frozen=True)
class Phase:
    """停售的一个阶段：到达生效时间后关闭对应渠道。"""

    name: str
    channel: str  # 如 "online"、"offline"、"all"
    effective_at: datetime


@dataclass(frozen=True)
class DispositionOrder:
    """一张处置单。``phases`` 仅停售使用；``capabilities`` 仅远程关闭使用。"""

    order_id: str
    type: DispositionType
    scope: VersionScope
    conclusion_id: str
    created_at: datetime
    note: str = ""
    phases: tuple[Phase, ...] = ()
    capabilities: frozenset[str] = frozenset()


class DispositionBoard:
    """处置单的创建与查询。所有处置按版本范围精确生效。"""

    def __init__(self, catalog: Catalog | None = None) -> None:
        self._catalog = catalog
        self._orders: list[DispositionOrder] = []
        self._sequence = 0

    def create_stop_sale(
        self,
        scope: VersionScope,
        conclusion_id: str,
        *,
        phases: list[Phase] | tuple[Phase, ...],
        at: datetime,
        note: str = "",
    ) -> DispositionOrder:
        """分阶段停售：至少一个阶段，且阶段须按生效时间先后排列。"""
        ordered = tuple(phases)
        if not ordered:
            raise ValueError("分阶段停售至少需要一个阶段")
        for earlier, later in zip(ordered, ordered[1:]):
            if later.effective_at < earlier.effective_at:
                raise ValueError("停售阶段必须按生效时间先后排列")
        return self._append(
            DispositionType.STOP_SALE, scope, conclusion_id, at, note=note, phases=ordered
        )

    def create_remote_disable(
        self,
        scope: VersionScope,
        conclusion_id: str,
        *,
        capabilities: set[str] | frozenset[str],
        at: datetime,
        note: str = "",
    ) -> DispositionOrder:
        """远程关闭高风险能力。核心能力永远不在关闭范围内。"""
        targets = frozenset(capabilities)
        if not targets:
            raise ValueError("远程关闭至少需要一个目标能力")
        blocked = targets & CORE_CAPABILITIES
        if blocked:
            raise ValueError(f"核心能力不可远程关闭：{sorted(blocked)}")
        if self._catalog is not None:
            for code in sorted(targets):
                if self._catalog.find_capability(code) is None:
                    raise KeyError(f"远程关闭引用了未登记的功能：{code}")
        return self._append(
            DispositionType.REMOTE_DISABLE,
            scope,
            conclusion_id,
            at,
            note=note,
            capabilities=targets,
        )

    def create_recall(
        self,
        scope: VersionScope,
        conclusion_id: str,
        *,
        at: datetime,
        note: str = "",
    ) -> DispositionOrder:
        return self._append(DispositionType.RECALL, scope, conclusion_id, at, note=note)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get(self, order_id: str) -> DispositionOrder:
        for order in self._orders:
            if order.order_id == order_id:
                return order
        raise KeyError(f"处置单不存在：{order_id}")

    def orders(self) -> tuple[DispositionOrder, ...]:
        return tuple(self._orders)

    def orders_affecting(self, *, model: str, batch: str, firmware: str) -> tuple[DispositionOrder, ...]:
        """精确命中指定版本的处置单，未圈定该版本的不在内。"""
        return tuple(
            order
            for order in self._orders
            if order.scope.matches(model=model, batch=batch, firmware=firmware)
        )

    def active_phases(self, order_id: str, now: datetime) -> tuple[Phase, ...]:
        """停售单在指定时刻已生效的阶段。"""
        order = self.get(order_id)
        if order.type is not DispositionType.STOP_SALE:
            raise ValueError(f"处置单不是分阶段停售：{order_id}")
        return tuple(phase for phase in order.phases if phase.effective_at <= now)

    # ------------------------------------------------------------------
    def _append(
        self,
        type_: DispositionType,
        scope: VersionScope,
        conclusion_id: str,
        at: datetime,
        **kwargs,
    ) -> DispositionOrder:
        self._sequence += 1
        order = DispositionOrder(
            order_id=f"DISP-{self._sequence:04d}",
            type=type_,
            scope=scope,
            conclusion_id=conclusion_id,
            created_at=at,
            **kwargs,
        )
        self._orders.append(order)
        return order
