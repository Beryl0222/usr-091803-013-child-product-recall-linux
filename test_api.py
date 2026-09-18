"""接口测试：HTTP 端到端验证登记、处置、通知版本与角色视图。"""

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from recall.api import make_handler
from recall.store import Store


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Store()))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def call(self, method, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(f"{self.base_url}{path}", data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            body = json.load(error)
            error.close()
            return error.code, body

    def test_full_chain_and_role_views(self):
        status, model = self.call("POST", "/models", {"brand": "星芽", "name": "手表 X3", "actor": "ent-1"})
        self.assertEqual(status, 201)
        status, batch = self.call(
            "POST", "/batches", {"model_id": model["model_id"], "produced_at": "2026-05-01T00:00:00+00:00", "quantity": 100}
        )
        self.assertEqual(status, 201)
        status, firmware = self.call(
            "POST",
            "/firmwares",
            {
                "model_id": model["model_id"],
                "version": "1.2.0",
                "features": [
                    {"feature_id": "basic_call", "name": "基础通话"},
                    {"feature_id": "friends_rank", "name": "好友排行", "risk": "high", "min_age": 8, "needs_consent": True},
                ],
                "payment_rules": [{"feature_id": "payment", "monthly_limit": 20000}],
            },
        )
        self.assertEqual(status, 201)
        status, device = self.call(
            "POST",
            "/devices",
            {"serial": "SN-API-1", "model_id": model["model_id"], "batch_id": batch["batch_id"], "firmware_version": "1.2.0", "store": "旗舰店"},
        )
        self.assertEqual(status, 201)

        # 销售登记家庭信息
        status, _ = self.call(
            "POST",
            "/flow",
            {
                "type": "sale",
                "serial": "SN-API-1",
                "actor": "旗舰店",
                "family": {"guardian_name": "张敏", "phone": "13812345678", "city": "杭州", "address": "文三路 100 号", "child_age": 7},
            },
        )
        self.assertEqual(status, 201)

        # 检测结论变化 → 分阶段召回 → 通知发布与修订
        status, assessment = self.call(
            "POST",
            "/assessments",
            {"model_id": model["model_id"], "firmware_version": "1.2.0", "verdict": "conditional", "min_age": 8, "max_age": 12, "summary": "限制高风险能力", "issued_by": "省质检院"},
        )
        self.assertEqual(status, 201)
        status, action = self.call(
            "POST",
            "/actions",
            {
                "type": "recall",
                "model_id": model["model_id"],
                "reason": "风险升级",
                "created_by": "regulator-01",
                "firmware_versions": ["1.2.0"],
                "assessment_id": assessment["assessment_id"],
                "phases": [{"name": "退款换货", "start_at": "2026-09-01T00:00:00+00:00", "deadline": "2026-09-10T00:00:00+00:00"}],
            },
        )
        self.assertEqual(status, 201)
        status, notice = self.call(
            "POST", f"/actions/{action['action_id']}/notices", {"title": "召回通知", "body": "第一版", "issued_by": "ent-1"}
        )
        self.assertEqual(status, 201)
        status, revised = self.call(
            "POST", f"/notices/{notice['notice_id']}/revisions", {"title": "召回通知（修订）", "body": "第二版", "issued_by": "ent-1"}
        )
        self.assertEqual(status, 201)
        status, history = self.call("GET", f"/notices/{notice['notice_id']}")
        self.assertEqual([item["body"] for item in history["versions"]], ["第一版", "第二版"])

        # 退款证据与超期扫描
        status, evidence = self.call(
            "POST",
            "/evidence",
            {"action_id": action["action_id"], "serial": "SN-API-1", "type": "refund", "detail": "全额退款", "recorded_by": "旗舰店"},
        )
        self.assertEqual(status, 201)
        status, overdue = self.call("POST", f"/actions/{action['action_id']}/scan-overdue", {"now": "2026-09-11T00:00:00+00:00"})
        self.assertEqual(status, 200)
        self.assertEqual(overdue["overdue"], [])  # 已退款，无超期

        # 监管全量可见
        status, trace = self.call("GET", "/trace/SN-API-1?role=regulator")
        self.assertEqual(status, 200)
        self.assertEqual(trace["device"]["family"]["phone"], "13812345678")
        self.assertEqual(trace["responsibility"]["sold_by"], "旗舰店")

        # 门店只见召回必需的脱敏家庭信息
        status, masked = self.call("GET", "/trace/SN-API-1?role=store")
        self.assertEqual(status, 200)
        family = masked["device"]["family"]
        self.assertEqual(family["guardian_name"], "张*")
        self.assertEqual(family["phone"], "138****5678")
        self.assertEqual(family["city"], "杭州")
        self.assertNotIn("文三路", family["address"])

    def test_health_and_unknown_route(self):
        status, payload = self.call("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "child-product-recall")
        status, _ = self.call("GET", "/unknown")
        self.assertEqual(status, 404)

    def test_validation_and_conflict_errors(self):
        status, body = self.call("POST", "/models", {"brand": "星芽"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        status, _ = self.call("GET", "/trace/SN-404")
        self.assertEqual(status, 404)
        status, model = self.call("POST", "/models", {"brand": "星芽", "name": "手表 X5", "actor": "ent-1"})
        self.assertEqual(status, 201)
        status, body = self.call(
            "POST",
            "/actions",
            {"type": "remote_disable", "model_id": model["model_id"], "reason": "x", "created_by": "r", "feature_id": "basic_call"},
        )
        self.assertEqual(status, 400)
        self.assertIn("基础能力", body["error"])


if __name__ == "__main__":
    unittest.main()
