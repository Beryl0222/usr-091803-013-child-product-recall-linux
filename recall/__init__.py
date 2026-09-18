"""儿童产品风险召回领域核心。

围绕儿童电话手表的登记、分级开放、流向、处置、证据与追溯：

- ``catalog``      型号、批次、固件、适龄结论、功能开关与付费规则的登记册；
- ``consent``      家长同意账本，只追加、可撤回、全程留痕；
- ``gating``       高风险能力按年龄与场景逐步开放，核心能力不受开关影响；
- ``inventory``    生产、到店、跨店调拨、销售与离线盘点的完整流向；
- ``detection``    检测结论版本化登记，结论变化只追加不覆盖；
- ``disposition``  分阶段停售、远程关闭与召回，按指定版本圈定；
- ``notices``      面向家庭的通知，修订只追加、旧内容永久保留；
- ``evidence``     退款、换货、拒绝升级与超期未处理的证据；
- ``trace``        监管从一个序列号还原认证、销售与处置责任；
- ``privacy``      企业与门店仅可见完成召回所必需的家庭信息。
"""

from recall.catalog import (
    CORE_CAPABILITIES,
    AgeSuitability,
    Batch,
    Capability,
    Catalog,
    Firmware,
    PaymentRule,
    ProductModel,
    RiskLevel,
)
from recall.consent import ConsentBook, ConsentRecord
from recall.detection import ConclusionStatus, DetectionConclusion, DetectionRegistry, VersionScope
from recall.disposition import DispositionBoard, DispositionOrder, DispositionType, Phase
from recall.evidence import EvidenceKind, EvidenceLedger, EvidenceRecord
from recall.gating import FeatureGate, GateDecision
from recall.inventory import DeviceUnit, FlowEvent, FlowKind, InventoryLedger, SaleRecord
from recall.notices import Notice, NoticeBoard, NoticeRevision
from recall.privacy import FamilyDirectory, RecallTaskView, recall_worklist
from recall.trace import TraceReport, TraceService

__all__ = [
    "CORE_CAPABILITIES",
    "AgeSuitability",
    "Batch",
    "Capability",
    "Catalog",
    "ConclusionStatus",
    "ConsentBook",
    "ConsentRecord",
    "DetectionConclusion",
    "DetectionRegistry",
    "DeviceUnit",
    "DispositionBoard",
    "DispositionOrder",
    "DispositionType",
    "EvidenceKind",
    "EvidenceLedger",
    "EvidenceRecord",
    "FamilyDirectory",
    "FeatureGate",
    "Firmware",
    "FlowEvent",
    "FlowKind",
    "GateDecision",
    "InventoryLedger",
    "Notice",
    "NoticeBoard",
    "NoticeRevision",
    "PaymentRule",
    "Phase",
    "ProductModel",
    "RecallTaskView",
    "RiskLevel",
    "SaleRecord",
    "TraceReport",
    "TraceService",
    "VersionScope",
    "recall_worklist",
]
