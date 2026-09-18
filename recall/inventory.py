"""设备流向：生产、到店、跨店调拨、销售与离线盘点的完整留痕。

每台设备（按序列号）的每一次移动都是一条不可变事件，追加到账本中。
跨店调拨与售出都会校验设备当前所在位置，保证流向链条不断裂；
离线盘点只做核对并留下差异记录，不改变任何设备的归属，
因此盘点之后流向依然完整可还原。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class FlowError(ValueError):
    """流向校验失败（如设备不在调出门店、重复登记序列号）。"""


class FlowKind(Enum):
    MANUFACTURED = "manufactured"  # 生产入库
    RECEIVED = "received"          # 门店收货
    TRANSFERRED = "transferred"    # 跨店调拨
    SOLD = "sold"                  # 售出给家庭
    RETURNED = "returned"          # 召回退回


@dataclass(frozen=True)
class DeviceUnit:
    """一台按序列号登记的设备。"""

    serial: str
    model: str
    batch: str
    firmware: str


@dataclass(frozen=True)
class SaleRecord:
    """售出记录：家庭只保存联系令牌，不保存明文信息。"""

    sale_id: str
    store: str
    sold_at: datetime
    family_ref: str


@dataclass(frozen=True)
class FlowEvent:
    """一次流向事件。售出时附带 ``sale``，其余时候为 None。"""

    serial: str
    kind: FlowKind
    at: datetime
    from_location: str | None
    to_location: str | None
    actor: str
    note: str = ""
    sale: SaleRecord | None = None


@dataclass(frozen=True)
class StocktakeRecord:
    """一次离线盘点的核对结果，只记录差异，不改动归属。"""

    store: str
    counted: frozenset[str]
    expected: frozenset[str]
    missing: frozenset[str]      # 账面在店但盘点未见
    unexpected: frozenset[str]   # 盘点见到但账面不在店
    taken_at: datetime
    actor: str


class InventoryLedger:
    """流向账本：事件只追加，当前位置由事件链推导。"""

    FAMILY_LOCATION = "family"

    def __init__(self) -> None:
        self._devices: dict[str, DeviceUnit] = {}
        self._events: list[FlowEvent] = []
        self._sales: dict[str, SaleRecord] = {}
        self._stocktakes: list[StocktakeRecord] = []

    # ------------------------------------------------------------------
    # 登记与事件
    # ------------------------------------------------------------------
    def register_device(self, unit: DeviceUnit, *, at: datetime, actor: str) -> FlowEvent:
        if unit.serial in self._devices:
            raise FlowError(f"序列号已登记：{unit.serial}")
        self._devices[unit.serial] = unit
        return self._append(
            FlowEvent(unit.serial, FlowKind.MANUFACTURED, at, None, "factory", actor)
        )

    def receive(self, serial: str, store: str, *, at: datetime, actor: str) -> FlowEvent:
        self._require_device(serial)
        if self.current_location(serial) != "factory":
            raise FlowError(f"设备不在工厂，无法入店：{serial}")
        return self._append(
            FlowEvent(serial, FlowKind.RECEIVED, at, "factory", store, actor)
        )

    def transfer(
        self, serial: str, from_store: str, to_store: str, *, at: datetime, actor: str
    ) -> FlowEvent:
        """跨店调拨：必须确在调出门店，调拨事件进入完整流向。"""
        self._require_device(serial)
        if self.current_location(serial) != from_store:
            raise FlowError(f"设备不在门店 {from_store}，无法调出：{serial}")
        return self._append(
            FlowEvent(serial, FlowKind.TRANSFERRED, at, from_store, to_store, actor)
        )

    def sell(
        self,
        serial: str,
        store: str,
        *,
        sale_id: str,
        family_ref: str,
        at: datetime,
        actor: str,
    ) -> FlowEvent:
        self._require_device(serial)
        if self.current_location(serial) != store:
            raise FlowError(f"设备不在门店 {store}，无法售出：{serial}")
        sale = SaleRecord(sale_id, store, at, family_ref)
        self._sales[serial] = sale
        return self._append(
            FlowEvent(serial, FlowKind.SOLD, at, store, self.FAMILY_LOCATION, actor, sale=sale)
        )

    def mark_returned(self, serial: str, *, at: datetime, actor: str, note: str = "") -> FlowEvent:
        self._require_device(serial)
        return self._append(
            FlowEvent(serial, FlowKind.RETURNED, at, self.current_location(serial), "factory", actor, note)
        )

    # ------------------------------------------------------------------
    # 离线盘点：只核对，不改归属
    # ------------------------------------------------------------------
    def stocktake(
        self, store: str, counted: set[str] | frozenset[str], *, at: datetime, actor: str
    ) -> StocktakeRecord:
        counted_set = frozenset(counted)
        expected = frozenset(
            serial for serial in self._devices if self.current_location(serial) == store
        )
        record = StocktakeRecord(
            store=store,
            counted=counted_set,
            expected=expected,
            missing=expected - counted_set,
            unexpected=counted_set - expected,
            taken_at=at,
            actor=actor,
        )
        self._stocktakes.append(record)
        return record

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def device(self, serial: str) -> DeviceUnit:
        return self._require_device(serial)

    def devices(self) -> tuple[DeviceUnit, ...]:
        return tuple(self._devices.values())

    def custody(self, serial: str) -> tuple[FlowEvent, ...]:
        self._require_device(serial)
        return tuple(event for event in self._events if event.serial == serial)

    def current_location(self, serial: str) -> str:
        chain = self.custody(serial)
        return chain[-1].to_location or "factory"

    def sale_of(self, serial: str) -> SaleRecord | None:
        return self._sales.get(serial)

    def stocktakes(self, store: str) -> tuple[StocktakeRecord, ...]:
        return tuple(record for record in self._stocktakes if record.store == store)

    # ------------------------------------------------------------------
    def _append(self, event: FlowEvent) -> FlowEvent:
        self._events.append(event)
        return event

    def _require_device(self, serial: str) -> DeviceUnit:
        try:
            return self._devices[serial]
        except KeyError:
            raise FlowError(f"序列号未登记：{serial}") from None
