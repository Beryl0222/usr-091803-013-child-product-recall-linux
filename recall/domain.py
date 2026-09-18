"""领域对象与常量：登记、适龄结论、功能开关、流向、召回与证据。

所有实体以 dataclass 表达，便于 JSON 序列化与测试断言；
业务不变量（基础能力不可停用、通知修订留痕等）由 store 层保证。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# 基础能力：通话、紧急求助、必要定位。
# 任何功能开关、远程关闭或召回处置都不能让这三项失效。
ESSENTIAL_FEATURES = ("basic_call", "emergency_sos", "location")

RISK_LEVELS = ("low", "medium", "high")
SCENARIOS = ("home", "school", "outdoor")
VERDICTS = ("pass", "conditional", "fail")

# 流向事件：register 入库、transfer 跨店调拨、sale 销售、
# stocktake 离线盘点、return 退回、recall_return 召回退回。
FLOW_TYPES = ("register", "transfer", "sale", "stocktake", "return", "recall_return")

# 处置动作：stop_sale 停售、remote_disable 远程关闭、recall 召回。
ACTION_TYPES = ("stop_sale", "remote_disable", "recall")

# 证据类型：退款、换货、拒绝升级、超期未处理。
EVIDENCE_TYPES = ("refund", "exchange", "upgrade_refused", "overdue")

# 查看角色：regulator 监管（全量）、enterprise 企业、store 门店（召回必需的最小家庭信息）。
ROLES = ("regulator", "enterprise", "store")

TASK_STATUSES = ("pending", "refunded", "exchanged", "upgrade_refused", "overdue")


def now_iso() -> str:
    """当前 UTC 时间的 ISO 字符串，统一秒级精度。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    """解析 ISO 时间；无时区信息时按 UTC 处理。"""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def to_dict(obj) -> dict:
    return asdict(obj)


@dataclass
class FeatureSwitch:
    """功能开关：高风险能力带适龄门槛、场景限制与家长同意要求。"""

    feature_id: str
    name: str
    risk: str = "low"
    min_age: int = 0
    scenarios: list = field(default_factory=lambda: list(SCENARIOS))
    needs_consent: bool = False
    enabled: bool = True

    @property
    def essential(self) -> bool:
        return self.feature_id in ESSENTIAL_FEATURES


@dataclass
class PaymentRule:
    """付费规则：绑定付费能力，约定月度限额与同意要求。"""

    feature_id: str
    monthly_limit: int
    requires_consent: bool = True


@dataclass
class Model:
    model_id: str
    brand: str
    name: str
    registered_by: str
    registered_at: str


@dataclass
class Batch:
    batch_id: str
    model_id: str
    produced_at: str
    quantity: int


@dataclass
class Firmware:
    firmware_id: str
    model_id: str
    version: str
    features: list = field(default_factory=list)
    payment_rules: list = field(default_factory=list)
    registered_at: str = ""


@dataclass
class Assessment:
    """检测与适龄结论。结论变化产生新版本，旧版本保留可溯。"""

    assessment_id: str
    model_id: str
    firmware_version: str  # "*" 表示该型号全部固件
    verdict: str
    min_age: int
    max_age: int
    summary: str
    issued_by: str
    issued_at: str
    version: int = 1
    supersedes: str = ""  # 被替代的上一版 assessment_id


@dataclass
class Family:
    """销售时登记的家庭信息，召回联络所需；对企业与门店脱敏。"""

    guardian_name: str
    phone: str
    city: str
    address: str = ""
    child_age: int = 0


@dataclass
class Device:
    serial: str
    model_id: str
    batch_id: str
    firmware_version: str
    location: str = ""  # 当前所在门店；售出后为 ""
    status: str = "in_stock"  # in_stock | sold | refunded | exchanged
    family: dict = None
    registered_at: str = ""


@dataclass
class Consent:
    """家长同意记录；同一 (serial, scope) 取最新一条为当前状态。"""

    consent_id: str
    serial: str
    scope: str  # feature_id 或 "payment"
    granted: bool
    granted_by: str
    at: str


@dataclass
class FlowEvent:
    """流向事件。离线盘点允许 recorded_at 早于 uploaded_at，流向不断链。"""

    event_id: str
    type: str
    actor: str
    serial: str = ""
    batch_id: str = ""
    quantity: int = 0
    from_store: str = ""
    to_store: str = ""
    recorded_at: str = ""
    uploaded_at: str = ""
    note: str = ""


@dataclass
class Phase:
    """处置阶段：分阶段停售/召回的时间窗与截止线。"""

    name: str
    start_at: str
    deadline: str


@dataclass
class RecallAction:
    action_id: str
    type: str
    model_id: str
    reason: str
    created_by: str
    created_at: str
    batch_ids: list = field(default_factory=list)
    firmware_versions: list = field(default_factory=list)
    feature_id: str = ""  # remote_disable 的目标能力
    assessment_id: str = ""
    phases: list = field(default_factory=list)
    status: str = "active"  # active | closed


@dataclass
class Notice:
    """召回通知。修订生成新版本，旧版本内容不被覆盖。"""

    notice_id: str
    action_id: str
    version: int
    title: str
    body: str
    issued_by: str
    issued_at: str
    supersedes: int = 0  # 被替代的上一版版本号


@dataclass
class HandlingTask:
    """召回下每台受影响设备的处置任务，超期未处理会形成证据。"""

    task_id: str
    action_id: str
    serial: str
    deadline: str
    status: str = "pending"
    updated_at: str = ""


@dataclass
class Evidence:
    """退款、换货、拒绝升级、超期未处理的处理证据。"""

    evidence_id: str
    action_id: str
    serial: str
    type: str
    detail: str
    recorded_by: str
    recorded_at: str
