"""最小可见视图：企业与门店只能看到完成召回所必需的家庭信息。

监管人员通过 ``trace`` 看到全量责任链；而企业与门店执行召回时，
这里只给出：序列号、售出门店、家庭联系令牌、脱敏联系方式和处理
状态。儿童姓名、年龄、位置、使用记录等一律不出现在视图中。
未售出的设备没有家庭信息，也不会出现在召回工作清单里。
"""

from __future__ import annotations

from dataclasses import dataclass

from recall.disposition import DispositionBoard, DispositionOrder
from recall.evidence import EvidenceKind, EvidenceLedger
from recall.inventory import InventoryLedger


def mask_contact(raw: str) -> str:
    """联系方式脱敏：手机号保留前三后四，其余保留首尾各两位。"""
    digits = raw.strip()
    if len(digits) == 11 and digits.isdigit():
        return f"{digits[:3]}****{digits[-4:]}"
    if len(digits) > 4:
        return f"{digits[:2]}***{digits[-2:]}"
    return "****"


class FamilyDirectory:
    """家庭联系信息的唯一持有者，对外只提供脱敏形式。"""

    def __init__(self) -> None:
        self._contacts: dict[str, str] = {}

    def register(self, family_ref: str, contact: str) -> None:
        self._contacts[family_ref] = contact

    def masked_contact(self, family_ref: str) -> str:
        raw = self._contacts.get(family_ref)
        return mask_contact(raw) if raw else "未登记"


@dataclass(frozen=True)
class RecallTaskView:
    """门店/企业可见的召回任务条目——完成召回所必需的最小集合。"""

    serial: str
    store: str
    family_ref: str
    contact: str  # 已脱敏
    status: str   # pending / done / overdue


def recall_worklist(
    order_id: str,
    *,
    dispositions: DispositionBoard,
    inventory: InventoryLedger,
    evidence: EvidenceLedger,
    directory: FamilyDirectory,
) -> tuple[RecallTaskView, ...]:
    """生成一张处置单（如召回）面向门店/企业的工作清单。"""
    order = dispositions.get(order_id)
    return tuple(_task_view(order, unit.serial, inventory=inventory, evidence=evidence, directory=directory)
                 for unit in inventory.devices()
                 if order.scope.matches(model=unit.model, batch=unit.batch, firmware=unit.firmware)
                 and inventory.sale_of(unit.serial) is not None)


def _task_view(
    order: DispositionOrder,
    serial: str,
    *,
    inventory: InventoryLedger,
    evidence: EvidenceLedger,
    directory: FamilyDirectory,
) -> RecallTaskView:
    sale = inventory.sale_of(serial)
    assert sale is not None  # 调用方已过滤未售出设备
    if evidence.is_processed(order.order_id, serial):
        status = "done"
    elif any(
        entry.order_id == order.order_id
        and entry.serial == serial
        and entry.kind is EvidenceKind.OVERDUE
        for entry in evidence.for_serial(serial)
    ):
        status = "overdue"
    else:
        status = "pending"
    return RecallTaskView(
        serial=serial,
        store=sale.store,
        family_ref=sale.family_ref,
        contact=directory.masked_contact(sale.family_ref),
        status=status,
    )
