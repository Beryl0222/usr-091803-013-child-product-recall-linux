"""演示数据：一条从登记到召回处置的完整链路，便于本地联调。"""

from __future__ import annotations

from .store import Store


def seed(store: Store) -> Store:
    model = store.register_model("星芽", "儿童电话手表 X3", actor="enterprise-qa")
    batch = store.register_batch(model.model_id, "2026-05-01T00:00:00+00:00", 5000)
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
            {
                "feature_id": "virtual_dress",
                "name": "虚拟装扮",
                "risk": "medium",
                "min_age": 6,
                "needs_consent": True,
            },
            {"feature_id": "payment", "name": "支付", "risk": "high", "min_age": 8, "needs_consent": True},
        ],
        payment_rules=[{"feature_id": "payment", "monthly_limit": 20000, "requires_consent": True}],
    )
    assessment = store.publish_assessment(
        model.model_id, "1.2.0", "conditional", 6, 12, "好友排行存在诱导点亮风险，建议 8 岁以上开放", "省质检院"
    )
    store.register_device("SN-DEMO-0001", model.model_id, batch.batch_id, "1.2.0", store="旗舰店")
    store.record_flow("transfer", serial="SN-DEMO-0001", from_store="旗舰店", to_store="城东店", actor="store-a")
    store.record_flow(
        "sale",
        serial="SN-DEMO-0001",
        actor="城东店",
        family={
            "guardian_name": "张敏",
            "phone": "13812345678",
            "city": "杭州",
            "address": "西湖区文三路 100 号",
            "child_age": 7,
        },
    )
    store.record_consent("SN-DEMO-0001", "friends_rank", True, "张敏")
    action = store.create_action(
        "recall",
        model.model_id,
        "检测结论变化：好友排行诱导风险升级，召回固件 1.2.0 设备",
        "regulator-01",
        firmware_versions=["1.2.0"],
        assessment_id=assessment.assessment_id,
        phases=[
            {"name": "通知家庭", "start_at": "2026-09-01T00:00:00+00:00", "deadline": "2026-09-10T00:00:00+00:00"},
            {"name": "退款换货", "start_at": "2026-09-10T00:00:00+00:00", "deadline": "2026-10-01T00:00:00+00:00"},
        ],
    )
    notice = store.publish_notice(action.action_id, "X3 手表 1.2.0 召回通知", "请家长尽快联系门店办理退款或换货。", "enterprise-qa")
    store.revise_notice(notice.notice_id, "X3 手表 1.2.0 召回通知（修订）", "补充：拒绝升级的家庭可保留基础通话与定位。", "enterprise-qa")
    return store
