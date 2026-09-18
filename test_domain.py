"""儿童电话手表风险召回领域的端到端规则测试。

场景主线：家长委员会投诉后，检测结论变化，对指定版本分阶段停售、
远程关闭高风险能力并发起召回；全流程验证登记、分级开放、流向、
通知、证据、追溯与最小可见。
"""

import dataclasses
import unittest
from datetime import datetime
from types import SimpleNamespace

from recall import (
    CORE_CAPABILITIES,
    AgeSuitability,
    Batch,
    Capability,
    Catalog,
    ConclusionStatus,
    ConsentBook,
    DetectionRegistry,
    DeviceUnit,
    DispositionBoard,
    DispositionType,
    EvidenceKind,
    EvidenceLedger,
    FamilyDirectory,
    FeatureGate,
    Firmware,
    FlowKind,
    InventoryLedger,
    NoticeBoard,
    PaymentRule,
    Phase,
    ProductModel,
    RecallTaskView,
    RiskLevel,
    TraceService,
    VersionScope,
    recall_worklist,
)
from recall.inventory import FlowError

T0 = datetime(2026, 1, 1)    # 生产
T1 = datetime(2026, 1, 5)    # 到店
T2 = datetime(2026, 1, 8)    # 调拨
T3 = datetime(2026, 2, 1)    # 售出
T4 = datetime(2026, 3, 1)    # 盘点
T_DET1 = datetime(2026, 1, 2)   # 首版检测结论
T_DET2 = datetime(2026, 4, 1)   # 复检结论变化
T_DISP = datetime(2026, 4, 2)   # 处置单创建
T_PHASE1 = datetime(2026, 4, 10)  # 停售第一阶段
T_PHASE2 = datetime(2026, 4, 20)  # 停售第二阶段
T_NOTICE = datetime(2026, 4, 3)
T_REVISE = datetime(2026, 4, 5)
T_REFUND = datetime(2026, 4, 6)
T_DECLINE = datetime(2026, 4, 7)
T_DEADLINE = datetime(2026, 5, 1)  # 处置期限
T_NOW = datetime(2026, 5, 10)      # 已超期

RISK_SCOPE = VersionScope(model="W1", batches=frozenset({"B2026A"}), firmwares=frozenset({"1.0.0"}))


def build_world() -> SimpleNamespace:
    """搭建一个完整的业务世界：登记、流向、检测、处置、通知与证据。"""
    catalog = Catalog()
    catalog.register_model(ProductModel(code="W1", brand="童安", name="童安手表 4G"))
    catalog.register_firmware(Firmware(version="1.0.0", released_at=datetime(2025, 12, 1)))
    catalog.register_firmware(Firmware(version="1.1.0", released_at=datetime(2026, 1, 15)))
    catalog.register_batch(Batch(code="B2026A", model="W1", firmware="1.0.0", produced_at=T0, quantity=5))
    catalog.register_batch(Batch(code="B2026B", model="W1", firmware="1.1.0", produced_at=T0, quantity=1))

    catalog.register_capability(Capability(
        code="social_rank", name="好友排行", risk=RiskLevel.HIGH,
        min_age=8, scenarios=frozenset({"home", "outdoor"}),
    ))
    catalog.register_capability(Capability(
        code="dress_up", name="虚拟装扮", risk=RiskLevel.MEDIUM, min_age=6, paid=True,
    ))
    catalog.register_capability(Capability(
        code="pay", name="支付", risk=RiskLevel.HIGH, min_age=12, paid=True,
    ))
    catalog.register_capability(Capability(
        code="health_score", name="健康评价", risk=RiskLevel.MEDIUM, min_age=10,
    ))
    catalog.register_payment_rule(PaymentRule(
        capability="dress_up", max_per_transaction=2000, max_per_day=5000,
    ))
    catalog.register_payment_rule(PaymentRule(
        capability="pay", max_per_transaction=5000, max_per_day=10000,
    ))

    # 适龄结论先 6 岁起，复检后上调为 8 岁起（历史保留）。
    catalog.record_suitability(AgeSuitability(
        model="W1", firmware="1.0.0", min_age=6,
        summary="初评：6 岁起", assessor="评估员-01", decided_at=datetime(2025, 12, 20),
    ))
    catalog.record_suitability(AgeSuitability(
        model="W1", firmware="1.0.0", min_age=8,
        summary="复检：社交功能上调至 8 岁起", assessor="评估员-02", decided_at=T_DET2,
    ))

    for capability in ("social_rank", "dress_up", "health_score"):
        catalog.set_switch("W1", "1.0.0", capability, True, changed_at=T1, reason="上市默认")

    consent = ConsentBook()
    consent.record("SN001", "social_rank", True, guardian="监护人-G1", at=T3)
    consent.record("SN001", "dress_up", True, guardian="监护人-G1", at=T3)

    inventory = InventoryLedger()
    for serial in ("SN001", "SN002", "SN003", "SN004", "SN005"):
        inventory.register_device(
            DeviceUnit(serial=serial, model="W1", batch="B2026A", firmware="1.0.0"),
            at=T0, actor="工厂-01",
        )
    inventory.register_device(
        DeviceUnit(serial="SN900", model="W1", batch="B2026B", firmware="1.1.0"),
        at=T0, actor="工厂-01",
    )
    for serial in ("SN001", "SN002", "SN003", "SN004", "SN005"):
        inventory.receive(serial, "门店A", at=T1, actor="店员-甲")
    inventory.receive("SN900", "门店B", at=T1, actor="店员-乙")
    inventory.transfer("SN002", "门店A", "门店B", at=T2, actor="调度-丙")
    inventory.sell("SN001", "门店A", sale_id="SALE-1", family_ref="FAM-1", at=T3, actor="店员-甲")
    inventory.sell("SN002", "门店B", sale_id="SALE-2", family_ref="FAM-2", at=T3, actor="店员-乙")
    inventory.sell("SN005", "门店A", sale_id="SALE-3", family_ref="FAM-3", at=T3, actor="店员-甲")

    detection = DetectionRegistry()
    detection.issue(
        VersionScope(model="W1"), ConclusionStatus.PASS,
        summary="首检通过", issued_by="检测中心", at=T_DET1,
    )
    changed = detection.issue(
        RISK_SCOPE, ConclusionStatus.RISK,
        summary="复检：好友排行与健康评价诱导沉迷", issued_by="检测中心", at=T_DET2,
    )

    dispositions = DispositionBoard(catalog)
    stop_sale = dispositions.create_stop_sale(
        RISK_SCOPE, changed.conclusion_id,
        phases=[
            Phase(name="线上停售", channel="online", effective_at=T_PHASE1),
            Phase(name="全渠道停售", channel="all", effective_at=T_PHASE2),
        ],
        at=T_DISP, note="分阶段停售",
    )
    remote_disable = dispositions.create_remote_disable(
        RISK_SCOPE, changed.conclusion_id,
        capabilities={"social_rank", "health_score"},
        at=T_DISP, note="远程关闭高风险能力",
    )
    recall = dispositions.create_recall(
        RISK_SCOPE, changed.conclusion_id, at=T_DISP, note="召回 B2026A 批次",
    )

    notices = NoticeBoard()
    notice = notices.publish(
        recall.order_id, title="召回通知", body="初版：请到店升级固件",
        issued_by="客服中心", at=T_NOTICE,
    )
    notice.revise(title="召回通知（修订）", body="修订版：支持退款或换货", issued_by="客服中心", at=T_REVISE)

    evidence = EvidenceLedger()
    evidence.record(recall.order_id, "SN001", EvidenceKind.REFUND, detail="已退款", at=T_REFUND)
    evidence.record(recall.order_id, "SN002", EvidenceKind.UPGRADE_DECLINED, detail="家庭拒绝升级", at=T_DECLINE)

    directory = FamilyDirectory()
    directory.register("FAM-1", "13800001111")
    directory.register("FAM-2", "13900002222")
    directory.register("FAM-3", "13700003333")

    return SimpleNamespace(
        catalog=catalog, consent=consent, inventory=inventory, detection=detection,
        dispositions=dispositions, notices=notices, evidence=evidence, directory=directory,
        stop_sale=stop_sale, remote_disable=remote_disable, recall=recall, notice=notice,
        changed=changed,
    )


class CatalogTest(unittest.TestCase):
    """登记册：先登记后引用，适龄结论只追加。"""

    def setUp(self):
        self.world = build_world()

    def test_duplicate_registration_rejected(self):
        catalog = self.world.catalog
        with self.assertRaises(ValueError):
            catalog.register_model(ProductModel(code="W1", brand="x", name="y"))
        with self.assertRaises(ValueError):
            catalog.register_batch(Batch(code="B2026A", model="W1", firmware="1.0.0",
                                         produced_at=T0, quantity=1))

    def test_references_must_exist(self):
        catalog = self.world.catalog
        with self.assertRaises(KeyError):
            catalog.register_batch(Batch(code="B-X", model="W9", firmware="1.0.0",
                                         produced_at=T0, quantity=1))
        with self.assertRaises(KeyError):
            catalog.register_batch(Batch(code="B-Y", model="W1", firmware="9.9",
                                         produced_at=T0, quantity=1))
        with self.assertRaises(KeyError):
            catalog.register_payment_rule(PaymentRule(capability="unknown",
                                                      max_per_transaction=1, max_per_day=1))

    def test_core_capability_cannot_be_switchable(self):
        for core in CORE_CAPABILITIES:
            with self.assertRaises(ValueError):
                self.world.catalog.register_capability(
                    Capability(code=core, name="核心", risk=RiskLevel.LOW))
            with self.assertRaises(ValueError):
                self.world.catalog.set_switch("W1", "1.0.0", core, False, changed_at=T1)

    def test_payment_rule_requires_paid_capability(self):
        with self.assertRaises(ValueError):
            self.world.catalog.register_payment_rule(PaymentRule(
                capability="health_score", max_per_transaction=1, max_per_day=1))

    def test_suitability_history_is_append_only(self):
        catalog = self.world.catalog
        history = catalog.suitability_history("W1", "1.0.0")
        self.assertEqual([item.min_age for item in history], [6, 8])
        self.assertEqual(history[0].summary, "初评：6 岁起")
        self.assertEqual(catalog.current_suitability("W1", "1.0.0").min_age, 8)

    def test_switch_defaults_off_and_history_kept(self):
        catalog = self.world.catalog
        self.assertFalse(catalog.switch_enabled("W1", "1.0.0", "pay"))
        catalog.set_switch("W1", "1.0.0", "pay", True, changed_at=T2, reason="试点")
        self.assertTrue(catalog.switch_enabled("W1", "1.0.0", "pay"))
        catalog.set_switch("W1", "1.0.0", "pay", False, changed_at=T3, reason="投诉下架")
        self.assertFalse(catalog.switch_enabled("W1", "1.0.0", "pay"))
        reasons = [event.reason for event in catalog.switch_history("W1", "1.0.0")
                   if event.capability == "pay"]
        self.assertEqual(reasons, ["试点", "投诉下架"])


class GatingTest(unittest.TestCase):
    """分级开放：按年龄与场景逐步开放，核心能力永远可用。"""

    def setUp(self):
        self.world = build_world()
        self.gate = FeatureGate(self.world.catalog, self.world.consent)

    def decide(self, serial="SN001", capability="social_rank", age=9, scenario="home"):
        return self.gate.decide(
            serial=serial, model="W1", firmware="1.0.0",
            capability=capability, age=age, scenario=scenario,
        )

    def test_core_capabilities_always_allowed(self):
        for core in CORE_CAPABILITIES:
            decision = self.decide(capability=core, age=3, scenario="school")
            self.assertTrue(decision.allowed, core)

    def test_core_survives_when_everything_else_disabled(self):
        catalog = self.world.catalog
        for capability in ("social_rank", "dress_up", "health_score"):
            catalog.set_switch("W1", "1.0.0", capability, False, changed_at=T_DISP, reason="处置")
        for core in CORE_CAPABILITIES:
            self.assertTrue(self.decide(capability=core).allowed)
        self.assertFalse(self.decide(capability="social_rank").allowed)

    def test_switch_off_denies(self):
        self.assertIn("开关未开启", self.decide(capability="pay", age=15).reason)

    def test_age_ladder(self):
        # 适龄结论复检后 8 岁起：7 岁被适龄结论拦下（功能本身 6 岁起）。
        self.assertIn("适龄结论", self.decide(capability="dress_up", age=7).reason)
        # 好友排行功能门槛 8 岁：8 岁但无同意仍被拦。
        self.assertIn("家长同意", self.decide(serial="SN003", age=8).reason)

    def test_scenario_restriction(self):
        decision = self.decide(scenario="school")
        self.assertFalse(decision.allowed)
        self.assertIn("场景未开放", decision.reason)

    def test_high_risk_requires_consent(self):
        self.assertFalse(self.decide(serial="SN003").allowed)  # SN003 无同意记录
        self.assertTrue(self.decide(serial="SN001").allowed)   # SN001 已同意

    def test_paid_requires_rule_and_consent(self):
        self.assertTrue(self.decide(serial="SN001", capability="dress_up").allowed)
        denied = self.decide(serial="SN003", capability="dress_up")
        self.assertIn("家长同意", denied.reason)

    def test_consent_withdrawal_takes_effect_with_history(self):
        book = self.world.consent
        book.record("SN001", "social_rank", False, guardian="监护人-G1", at=T4)
        self.assertFalse(self.decide(serial="SN001").allowed)
        self.assertTrue(book.is_granted("SN001", "social_rank", at=T3))  # 当时曾同意
        self.assertEqual(len(book.history("SN001", "social_rank")), 2)


class InventoryTest(unittest.TestCase):
    """流向：跨店调拨与离线盘点都保留完整链条。"""

    def setUp(self):
        self.world = build_world()

    def test_full_custody_chain(self):
        inventory = self.world.inventory
        kinds = [event.kind for event in inventory.custody("SN002")]
        self.assertEqual(kinds, [FlowKind.MANUFACTURED, FlowKind.RECEIVED,
                                 FlowKind.TRANSFERRED, FlowKind.SOLD])
        self.assertEqual(inventory.current_location("SN002"), InventoryLedger.FAMILY_LOCATION)
        self.assertEqual(inventory.current_location("SN003"), "门店A")

    def test_transfer_requires_current_store(self):
        with self.assertRaises(FlowError):
            self.world.inventory.transfer("SN003", "门店B", "门店C", at=T4, actor="调度")

    def test_sell_requires_current_store(self):
        with self.assertRaises(FlowError):
            self.world.inventory.sell("SN003", "门店B", sale_id="SALE-X",
                                      family_ref="FAM-9", at=T4, actor="店员")

    def test_duplicate_serial_rejected(self):
        with self.assertRaises(FlowError):
            self.world.inventory.register_device(
                DeviceUnit(serial="SN001", model="W1", batch="B2026A", firmware="1.0.0"),
                at=T4, actor="工厂")

    def test_offline_stocktake_reports_differences_without_breaking_flow(self):
        inventory = self.world.inventory
        record = inventory.stocktake("门店A", {"SN003"}, at=T4, actor="店长")
        self.assertEqual(record.missing, frozenset({"SN004"}))
        self.assertEqual(record.unexpected, frozenset())
        # 盘点不改变归属，流向依旧完整。
        self.assertEqual(inventory.current_location("SN004"), "门店A")
        kinds = [event.kind for event in inventory.custody("SN004")]
        self.assertEqual(kinds, [FlowKind.MANUFACTURED, FlowKind.RECEIVED])

    def test_sale_record_links_family_token(self):
        sale = self.world.inventory.sale_of("SN001")
        self.assertEqual((sale.store, sale.family_ref), ("门店A", "FAM-1"))


class DetectionTest(unittest.TestCase):
    """检测结论：变化只追加，版本范围精确圈定。"""

    def setUp(self):
        self.world = build_world()

    def test_conclusion_change_appends_revision(self):
        detection = self.world.detection
        history = detection.history("W1")
        self.assertEqual([item.revision for item in history], [1, 2])
        self.assertEqual(history[0].status, ConclusionStatus.PASS)  # 旧结论保留
        self.assertEqual(detection.current("W1").status, ConclusionStatus.RISK)

    def test_scope_matches_only_designated_versions(self):
        self.assertTrue(RISK_SCOPE.matches(model="W1", batch="B2026A", firmware="1.0.0"))
        self.assertFalse(RISK_SCOPE.matches(model="W1", batch="B2026B", firmware="1.1.0"))
        self.assertFalse(RISK_SCOPE.matches(model="W2", batch="B2026A", firmware="1.0.0"))
        open_scope = VersionScope(model="W1")
        self.assertTrue(open_scope.matches(model="W1", batch="B2026B", firmware="1.1.0"))


class DispositionTest(unittest.TestCase):
    """处置：分阶段停售、远程关闭不碰核心能力、按版本命中。"""

    def setUp(self):
        self.world = build_world()

    def test_staged_stop_sale_activates_over_time(self):
        board = self.world.dispositions
        order_id = self.world.stop_sale.order_id
        self.assertEqual(board.active_phases(order_id, datetime(2026, 4, 15)),
                         (self.world.stop_sale.phases[0],))
        self.assertEqual(len(board.active_phases(order_id, datetime(2026, 4, 25))), 2)

    def test_stop_sale_requires_ordered_phases(self):
        board = self.world.dispositions
        with self.assertRaises(ValueError):
            board.create_stop_sale(RISK_SCOPE, "DC-X", phases=[], at=T_DISP)
        with self.assertRaises(ValueError):
            board.create_stop_sale(RISK_SCOPE, "DC-X", at=T_DISP, phases=[
                Phase(name="一", channel="online", effective_at=T_PHASE2),
                Phase(name="二", channel="all", effective_at=T_PHASE1),  # 早于上一阶段
            ])

    def test_remote_disable_never_touches_core(self):
        board = self.world.dispositions
        with self.assertRaises(ValueError):
            board.create_remote_disable(RISK_SCOPE, "DC-X",
                                        capabilities={"social_rank", "sos"}, at=T_DISP)
        with self.assertRaises(KeyError):
            board.create_remote_disable(RISK_SCOPE, "DC-X",
                                        capabilities={"not_registered"}, at=T_DISP)

    def test_orders_hit_only_designated_versions(self):
        board = self.world.dispositions
        hit = board.orders_affecting(model="W1", batch="B2026A", firmware="1.0.0")
        self.assertEqual({order.type for order in hit},
                         {DispositionType.STOP_SALE, DispositionType.REMOTE_DISABLE,
                          DispositionType.RECALL})
        self.assertEqual(board.orders_affecting(model="W1", batch="B2026B", firmware="1.1.0"),
                         ())
        for order in hit:
            self.assertEqual(order.conclusion_id, self.world.changed.conclusion_id)


class NoticeTest(unittest.TestCase):
    """通知：修订不覆盖旧内容。"""

    def setUp(self):
        self.world = build_world()

    def test_revision_preserves_original(self):
        notice = self.world.notice
        self.assertEqual([item.revision for item in notice.revisions], [1, 2])
        self.assertEqual(notice.revisions[0].body, "初版：请到店升级固件")
        self.assertEqual(notice.current().body, "修订版：支持退款或换货")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            notice.revisions[0].body = "篡改"  # type: ignore[misc]


class EvidenceTest(unittest.TestCase):
    """证据：退款、换货、拒绝升级与超期未处理都有据可查。"""

    def setUp(self):
        self.world = build_world()

    def test_terminal_evidence_marks_processed(self):
        evidence = self.world.evidence
        order_id = self.world.recall.order_id
        self.assertTrue(evidence.is_processed(order_id, "SN001"))  # 退款
        self.assertTrue(evidence.is_processed(order_id, "SN002"))  # 拒绝升级
        self.assertFalse(evidence.is_processed(order_id, "SN005"))

    def test_overdue_derived_once_after_deadline(self):
        evidence = self.world.evidence
        order_id = self.world.recall.order_id
        serials = ("SN001", "SN002", "SN005")
        self.assertEqual(evidence.mark_overdue(order_id, serials,
                                               deadline=T_DEADLINE, now=datetime(2026, 4, 30)),
                         ())  # 期限未到
        created = evidence.mark_overdue(order_id, serials, deadline=T_DEADLINE, now=T_NOW)
        self.assertEqual([entry.serial for entry in created], ["SN005"])
        self.assertEqual(created[0].kind, EvidenceKind.OVERDUE)
        again = evidence.mark_overdue(order_id, serials, deadline=T_DEADLINE, now=T_NOW)
        self.assertEqual(again, ())  # 幂等，不重复记录

    def test_evidence_history_per_serial(self):
        kinds = [entry.kind for entry in self.world.evidence.for_serial("SN001")]
        self.assertEqual(kinds, [EvidenceKind.REFUND])


class TraceTest(unittest.TestCase):
    """监管追溯：一个序列号还原认证、销售与处置责任。"""

    def setUp(self):
        self.world = build_world()
        self.trace = TraceService(
            self.world.catalog, self.world.inventory, self.world.detection,
            self.world.dispositions, self.world.evidence,
        )

    def test_trace_reconstructs_full_responsibility(self):
        report = self.trace.trace("SN001")
        # 认证责任：登记信息 + 结论历史（含评估人、签发人）。
        self.assertEqual(report.model.brand, "童安")
        self.assertEqual(report.batch.code, "B2026A")
        self.assertEqual([item.min_age for item in report.suitability_history], [6, 8])
        self.assertEqual(report.suitability_history[-1].assessor, "评估员-02")
        self.assertEqual([item.revision for item in report.conclusions], [1, 2])
        self.assertEqual(report.conclusions[-1].issued_by, "检测中心")
        # 销售责任：完整流向（含经手人）与售出记录。
        self.assertEqual([event.kind for event in report.custody],
                         [FlowKind.MANUFACTURED, FlowKind.RECEIVED, FlowKind.SOLD])
        self.assertEqual(report.custody[1].actor, "店员-甲")
        self.assertEqual(report.sale.sale_id, "SALE-1")
        # 处置责任：命中版本的处置单与证据。
        self.assertEqual({order.type for order in report.orders},
                         {DispositionType.STOP_SALE, DispositionType.REMOTE_DISABLE,
                          DispositionType.RECALL})
        self.assertEqual([entry.kind for entry in report.evidence], [EvidenceKind.REFUND])

    def test_trace_of_unaffected_version_has_no_orders(self):
        report = self.trace.trace("SN900")  # 同型号但批次/固件不在圈定范围
        self.assertEqual(report.orders, ())
        self.assertEqual(report.evidence, ())


class PrivacyTest(unittest.TestCase):
    """最小可见：企业与门店只看到完成召回所必需的家庭信息。"""

    def setUp(self):
        self.world = build_world()
        self.world.evidence.mark_overdue(
            self.world.recall.order_id, ("SN001", "SN002", "SN005"),
            deadline=T_DEADLINE, now=T_NOW,
        )
        self.worklist = recall_worklist(
            self.world.recall.order_id,
            dispositions=self.world.dispositions,
            inventory=self.world.inventory,
            evidence=self.world.evidence,
            directory=self.world.directory,
        )

    def test_worklist_covers_only_affected_sold_devices(self):
        serials = {view.serial for view in self.worklist}
        self.assertEqual(serials, {"SN001", "SN002", "SN005"})  # 未售出与未圈定版本不在内

    def test_worklist_status_reflects_evidence(self):
        status = {view.serial: view.status for view in self.worklist}
        self.assertEqual(status, {"SN001": "done", "SN002": "done", "SN005": "overdue"})

    def test_worklist_exposes_only_minimum_fields(self):
        fields = {field.name for field in dataclasses.fields(RecallTaskView)}
        self.assertEqual(fields, {"serial", "store", "family_ref", "contact", "status"})
        view = next(item for item in self.worklist if item.serial == "SN001")
        self.assertEqual(view.contact, "138****1111")  # 脱敏，无明文手机号
        self.assertEqual(view.store, "门店A")


if __name__ == "__main__":
    unittest.main()
