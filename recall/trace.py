"""监管追溯：从一个序列号还原认证、销售与处置责任。

追溯报告把分散在各模块的记录按序列号聚合：

- 认证责任：型号、批次、固件的登记信息，适龄结论与检测结论的
  完整历史（含评估人、签发人）；
- 销售责任：从生产到售出的完整流向事件链（含经手人）与售出记录；
- 处置责任：精确命中该设备版本的全部处置单及其证据。
"""

from __future__ import annotations

from dataclasses import dataclass

from recall.catalog import AgeSuitability, Batch, Catalog, Firmware, ProductModel
from recall.detection import DetectionConclusion, DetectionRegistry
from recall.disposition import DispositionBoard, DispositionOrder
from recall.evidence import EvidenceLedger, EvidenceRecord
from recall.inventory import DeviceUnit, FlowEvent, InventoryLedger, SaleRecord


@dataclass(frozen=True)
class TraceReport:
    """一个序列号的完整责任链快照。"""

    serial: str
    device: DeviceUnit
    model: ProductModel | None
    batch: Batch | None
    firmware: Firmware | None
    suitability_history: tuple[AgeSuitability, ...]
    conclusions: tuple[DetectionConclusion, ...]
    custody: tuple[FlowEvent, ...]
    sale: SaleRecord | None
    orders: tuple[DispositionOrder, ...]
    evidence: tuple[EvidenceRecord, ...]


class TraceService:
    """面向监管人员的追溯入口。"""

    def __init__(
        self,
        catalog: Catalog,
        inventory: InventoryLedger,
        detection: DetectionRegistry,
        dispositions: DispositionBoard,
        evidence: EvidenceLedger,
    ) -> None:
        self._catalog = catalog
        self._inventory = inventory
        self._detection = detection
        self._dispositions = dispositions
        self._evidence = evidence

    def trace(self, serial: str) -> TraceReport:
        device = self._inventory.device(serial)
        return TraceReport(
            serial=serial,
            device=device,
            model=self._catalog.find_model(device.model),
            batch=self._catalog.find_batch(device.batch),
            firmware=self._catalog.find_firmware(device.firmware),
            suitability_history=self._catalog.suitability_history(device.model, device.firmware),
            conclusions=self._detection.history(device.model),
            custody=self._inventory.custody(serial),
            sale=self._inventory.sale_of(serial),
            orders=self._dispositions.orders_affecting(
                model=device.model, batch=device.batch, firmware=device.firmware
            ),
            evidence=self._evidence.for_serial(serial),
        )
