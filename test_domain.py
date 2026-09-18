"""领域规则测试：登记、版本化、策略、流向、处置、证据与追溯。"""

import unittest

from recall.policy import evaluate_features
from recall.domain import FeatureSwitch
from recall.store import Conflict, NotFound, Store, Validation


def make_store():
    """构造一条基础链路：型号、批次、固件、两台设备。"""
    store = Store()
    model = store.register_model("星芽", "儿童电话手表 X3", actor="enterprise-qa")
    batch = store.register_batch(model.model_id, "2026-05-01T00:00:00+00:00", 100)
    store.register_firmware(
        model.model_id,
        "1.2.0",
        features=[
            {"feature_id": "basic_call", "name": "基础通话"},
            {"feature_id": "emergency_sos", "name": "紧急求助"},
            {"feature_id": "location", "name": "必要定位"},
            {
                "feature_id": "friends_rank",
                "name": "好友排行",
                "risk": "high",
                "min_age": 8,
                "scenarios": ["home", "outdoor"],
                "needs_consent": True,
            },
            {"feature_id": "payment", "name": "支付", "risk": "high", "min_age": 8, "needs_consent": True},
        ],
        payment_rules=[{"feature_id": "payment", "monthly_limit": 20000}],
    )
    store.register_device("SN-001", model.model_id, batch.batch_id, "1.2.0", store="旗舰店")
    store.register_device("SN-002", model.model_id, batch.batch_id, "1.2.0", store="旗舰店")
    return store


class RegistrationTest(unittest.TestCase):
    def test_register_chain_and_ids(self):
        store = make_store()
        device = store.devices["SN-001"]
        self.assertEqual(device.model_id, "M-1")
        self.assertEqual(device.batch_id, "B-1")
        self.assertEqual(device.location, "旗舰店")
        # 入库登记自动产生流向事件
        self.assertEqual([e.type for e in store.device_flow("SN-001")], ["register"])

    def test_duplicate_serial_rejected(self):
        store = make_store()
        with self.assertRaises(Conflict):
            store.register_device("SN-001", "M-1", "B-1", "1.2.0")

    def test_unknown_references_rejected(self):
        store = make_store()
        with self.assertRaises(NotFound):
            store.register_device("SN-003", "M-9", "B-1", "1.2.0")
        with self.assertRaises(NotFound):
            store.register_device("SN-003", "M-1", "B-9", "1.2.0")
        with self.assertRaises(NotFound):
            store.register_device("SN-003", "M-1", "B-1", "9.9.9")


class AssessmentVersionTest(unittest.TestCase):
    def test_conclusion_change_creates_new_version_and_keeps_old(self):
        store = make_store()
        v1 = store.publish_assessment("M-1", "1.2.0", "pass", 3, 12, "初检合格", "省质检院")
        v2 = store.publish_assessment("M-1", "1.2.0", "conditional", 8, 12, "好友排行需限制", "省质检院")
        self.assertEqual((v1.version, v2.version), (1, 2))
        self.assertEqual(v2.supersedes, v1.assessment_id)
        history = store.assessment_history(model_id="M-1", firmware_version="1.2.0")
        self.assertEqual([item.verdict for item in history], ["pass", "conditional"])

    def test_invalid_verdict_rejected(self):
        store = make_store()
        with self.assertRaises(Validation):
            store.publish_assessment("M-1", "1.2.0", "unknown", 0, 12, "", "省质检院")


class FeaturePolicyTest(unittest.TestCase):
    def test_essential_features_survive_switch_off_and_remote_disable(self):
        features = [
            FeatureSwitch(feature_id="basic_call", name="基础通话", enabled=False),
            FeatureSwitch(feature_id="friends_rank", name="好友排行", risk="high"),
        ]
        result = evaluate_features(features, age=5, scenario="school", disabled_features={"basic_call"})
        self.assertTrue(result["basic_call"]["available"])
        # 固件未登记的紧急求助与定位同样兜底可用
        self.assertTrue(result["emergency_sos"]["available"])
        self.assertTrue(result["location"]["available"])

    def test_age_scenario_and_consent_gating(self):
        store = make_store()
        # 5 岁、校园场景、无同意：高风险能力被多重拦截
        features = store.feature_availability("SN-001", age=5, scenario="school")
        self.assertFalse(features["friends_rank"]["available"])
        self.assertIn("年龄不足（需满 8 岁）", features["friends_rank"]["reasons"])
        self.assertTrue(any("场景受限" in r for r in features["friends_rank"]["reasons"]))
        self.assertIn("待家长同意", features["friends_rank"]["reasons"])
        # 年龄与场景满足且获得同意后开放
        store.record_consent("SN-001", "friends_rank", True, "张敏")
        features = store.feature_availability("SN-001", age=9, scenario="home")
        self.assertTrue(features["friends_rank"]["available"])

    def test_consent_revocation_closes_feature(self):
        store = make_store()
        store.record_consent("SN-001", "payment", True, "张敏")
        self.assertTrue(store.feature_availability("SN-001", age=9)["payment"]["available"])
        store.record_consent("SN-001", "payment", False, "张敏")
        self.assertFalse(store.feature_availability("SN-001", age=9)["payment"]["available"])

    def test_remote_disable_blocks_feature_but_never_essential(self):
        store = make_store()
        store.record_consent("SN-001", "friends_rank", True, "张敏")
        store.create_action(
            "remote_disable", "M-1", "好友排行诱导风险", "regulator-01", feature_id="friends_rank"
        )
        features = store.feature_availability("SN-001", age=9, scenario="home")
        self.assertFalse(features["friends_rank"]["available"])
        self.assertIn("已被远程关闭", features["friends_rank"]["reasons"])
        self.assertTrue(features["basic_call"]["available"])
        self.assertTrue(features["emergency_sos"]["available"])
        self.assertTrue(features["location"]["available"])

    def test_remote_disable_of_essential_feature_rejected(self):
        store = make_store()
        with self.assertRaises(Validation):
            store.create_action(
                "remote_disable", "M-1", "误操作", "regulator-01", feature_id="emergency_sos"
            )


class FlowTest(unittest.TestCase):
    def test_transfer_chain_and_sale(self):
        store = make_store()
        store.record_flow("transfer", serial="SN-001", from_store="旗舰店", to_store="城东店", actor="store-a")
        store.record_flow(
            "sale",
            serial="SN-001",
            actor="城东店",
            family={"guardian_name": "张敏", "phone": "13812345678", "city": "杭州", "child_age": 7},
        )
        flow = store.device_flow("SN-001")
        self.assertEqual([e.type for e in flow], ["register", "transfer", "sale"])
        self.assertEqual(store.devices["SN-001"].status, "sold")

    def test_transfer_from_wrong_store_rejected(self):
        store = make_store()
        with self.assertRaises(Conflict):
            store.record_flow("transfer", serial="SN-001", from_store="城西店", to_store="城东店", actor="store-a")

    def test_offline_stocktake_keeps_original_time(self):
        store = make_store()
        event = store.record_flow(
            "stocktake",
            serial="SN-001",
            to_store="旗舰店",
            actor="store-a",
            recorded_at="2026-09-01T08:00:00+00:00",
            note="离线盘点后补录",
        )
        self.assertEqual(event.recorded_at, "2026-09-01T08:00:00+00:00")
        self.assertNotEqual(event.uploaded_at, event.recorded_at)
        # 盘点不改变设备所在门店
        self.assertEqual(store.devices["SN-001"].location, "旗舰店")

    def test_stocktake_by_batch_quantity(self):
        store = make_store()
        event = store.record_flow(
            "stocktake", batch_id="B-1", quantity=2, to_store="旗舰店", actor="store-a"
        )
        self.assertEqual(event.quantity, 2)


class StopSaleTest(unittest.TestCase):
    def test_stop_sale_blocks_covered_device_only(self):
        store = make_store()
        store.create_action("stop_sale", "M-1", "检测存疑", "regulator-01", batch_ids=["B-1"])
        with self.assertRaises(Conflict):
            store.record_flow(
                "sale",
                serial="SN-001",
                actor="旗舰店",
                family={"guardian_name": "张敏", "phone": "13812345678", "city": "杭州"},
            )
        # 其他型号设备不受影响
        other = store.register_model("星芽", "故事机 S1", actor="enterprise-qa")
        batch = store.register_batch(other.model_id, "2026-06-01T00:00:00+00:00", 10)
        store.register_firmware(other.model_id, "1.0.0", features=[])
        store.register_device("SN-101", other.model_id, batch.batch_id, "1.0.0", store="旗舰店")
        store.record_flow(
            "sale",
            serial="SN-101",
            actor="旗舰店",
            family={"guardian_name": "李雷", "phone": "13900000000", "city": "杭州"},
        )
        self.assertEqual(store.devices["SN-101"].status, "sold")


def make_recall_fixture():
    """两台已售设备 + 一个截止 2026-09-10 的召回动作。"""
    store = make_store()
    for serial, name in (("SN-001", "张敏"), ("SN-002", "李雷")):
        store.record_flow(
            "sale",
            serial=serial,
            actor="旗舰店",
            family={"guardian_name": name, "phone": "13812345678", "city": "杭州", "child_age": 7},
        )
    action = store.create_action(
        "recall",
        "M-1",
        "好友排行诱导风险升级",
        "regulator-01",
        firmware_versions=["1.2.0"],
        phases=[{"name": "退款换货", "start_at": "2026-09-01T00:00:00+00:00", "deadline": "2026-09-10T00:00:00+00:00"}],
    )
    return store, action


class RecallEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.store, self.action = make_recall_fixture()

    def test_recall_creates_task_per_affected_device(self):
        tasks = self.store.action_tasks(self.action.action_id)
        self.assertEqual(sorted(task.serial for task in tasks), ["SN-001", "SN-002"])
        self.assertTrue(all(task.deadline == "2026-09-10T00:00:00+00:00" for task in tasks))

    def test_refund_and_exchange_leave_evidence(self):
        self.store.record_evidence(self.action.action_id, "SN-001", "refund", "全额退款 499 元", "旗舰店")
        self.store.record_evidence(self.action.action_id, "SN-002", "exchange", "更换为 X5", "旗舰店")
        tasks = {task.serial: task for task in self.store.action_tasks(self.action.action_id)}
        self.assertEqual(tasks["SN-001"].status, "refunded")
        self.assertEqual(tasks["SN-002"].status, "exchanged")
        self.assertEqual(self.store.devices["SN-001"].status, "refunded")

    def test_upgrade_refused_is_recorded(self):
        self.store.record_evidence(self.action.action_id, "SN-001", "upgrade_refused", "家庭拒绝升级固件", "旗舰店")
        task = self.store._task_for(self.action.action_id, "SN-001")
        self.assertEqual(task.status, "upgrade_refused")

    def test_overdue_scan_generates_evidence_once(self):
        created = self.store.scan_overdue(now="2026-09-11T00:00:00+00:00")
        self.assertEqual(len(created), 2)
        self.assertTrue(all(item.type == "overdue" for item in created))
        # 幂等：再次扫描不重复生成
        self.assertEqual(self.store.scan_overdue(now="2026-09-12T00:00:00+00:00"), [])
        # 截止前扫描不生成
        fresh_store, _ = make_recall_fixture()
        self.assertEqual(fresh_store.scan_overdue(now="2026-09-09T00:00:00+00:00"), [])

    def test_evidence_outside_action_scope_rejected(self):
        store = make_store()
        store.register_device("SN-003", "M-1", "B-1", "1.2.0")
        with self.assertRaises(NotFound):
            store.record_evidence(self.action.action_id, "SN-404", "refund", "", "旗舰店")


class NoticeVersionTest(unittest.TestCase):
    def test_revision_keeps_old_content(self):
        store = make_store()
        action = store.create_action(
            "recall",
            "M-1",
            "风险升级",
            "regulator-01",
            phases=[{"name": "处置", "start_at": "2026-09-01T00:00:00+00:00", "deadline": "2026-09-10T00:00:00+00:00"}],
        )
        notice = store.publish_notice(action.action_id, "召回通知", "第一版内容", "enterprise-qa")
        revised = store.revise_notice(notice.notice_id, "召回通知（修订）", "第二版内容", "enterprise-qa")
        self.assertEqual(revised.version, 2)
        self.assertEqual(revised.supersedes, 1)
        history = store.notice_history(notice.notice_id)
        self.assertEqual([item.body for item in history], ["第一版内容", "第二版内容"])


class TraceTest(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.store.publish_assessment("M-1", "1.2.0", "conditional", 8, 12, "限制高风险能力", "省质检院")
        self.store.record_flow("transfer", serial="SN-001", from_store="旗舰店", to_store="城东店", actor="store-a")
        self.store.record_flow(
            "sale",
            serial="SN-001",
            actor="城东店",
            family={
                "guardian_name": "张敏",
                "phone": "13812345678",
                "city": "杭州",
                "address": "西湖区文三路 100 号",
                "child_age": 7,
            },
        )
        self.action = self.store.create_action(
            "recall",
            "M-1",
            "风险升级",
            "regulator-01",
            phases=[{"name": "处置", "start_at": "2026-09-01T00:00:00+00:00", "deadline": "2026-09-10T00:00:00+00:00"}],
        )
        self.store.record_evidence(self.action.action_id, "SN-001", "refund", "全额退款", "城东店")

    def test_trace_restores_certification_sales_and_disposal(self):
        trace = self.store.trace("SN-001")
        self.assertEqual(trace["responsibility"]["registered_by"], "enterprise-qa")
        self.assertEqual(trace["responsibility"]["certified_by"], ["省质检院"])
        self.assertEqual(trace["responsibility"]["sold_by"], "城东店")
        self.assertEqual(trace["responsibility"]["action_created_by"], ["regulator-01"])
        self.assertEqual(trace["responsibility"]["evidence_recorded_by"], ["城东店"])
        self.assertEqual([e["type"] for e in trace["flow"]], ["register", "transfer", "sale"])
        self.assertEqual(trace["actions"][0]["evidence"][0]["type"], "refund")

    def test_unknown_serial_raises(self):
        with self.assertRaises(NotFound):
            self.store.trace("SN-404")


if __name__ == "__main__":
    unittest.main()
