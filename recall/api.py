"""HTTP 接口层：JSON 路由、错误映射与角色视图。"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from . import health_payload
from .domain import ROLES, to_dict
from .privacy import view_for_role
from .store import Conflict, NotFound, Store, Validation


def _created(obj):
    return 201, to_dict(obj)


def _ok(payload):
    return 200, payload


# ---- 各路由处理函数 ----

def _health(store, match, query, body):
    return _ok(health_payload())


def _register_model(store, match, query, body):
    return _created(store.register_model(body.get("brand"), body.get("name"), body.get("actor")))


def _register_batch(store, match, query, body):
    return _created(
        store.register_batch(body.get("model_id"), body.get("produced_at"), body.get("quantity"))
    )


def _register_firmware(store, match, query, body):
    return _created(
        store.register_firmware(
            body.get("model_id"),
            body.get("version"),
            body.get("features"),
            body.get("payment_rules"),
        )
    )


def _publish_assessment(store, match, query, body):
    return _created(
        store.publish_assessment(
            body.get("model_id"),
            body.get("firmware_version") or "*",
            body.get("verdict"),
            body.get("min_age", 0),
            body.get("max_age", 99),
            body.get("summary"),
            body.get("issued_by"),
        )
    )


def _list_assessments(store, match, query, body):
    items = store.assessment_history(
        model_id=_first(query, "model_id"), firmware_version=_first(query, "firmware_version")
    )
    return _ok({"assessments": [to_dict(item) for item in items]})


def _register_device(store, match, query, body):
    return _created(
        store.register_device(
            body.get("serial"),
            body.get("model_id"),
            body.get("batch_id"),
            body.get("firmware_version"),
            store=body.get("store", ""),
        )
    )


def _record_consent(store, match, query, body):
    return _created(
        store.record_consent(
            body.get("serial"),
            body.get("scope"),
            body.get("granted"),
            body.get("granted_by"),
        )
    )


def _record_flow(store, match, query, body):
    return _created(
        store.record_flow(
            body.get("type"),
            body.get("actor"),
            serial=body.get("serial", ""),
            batch_id=body.get("batch_id", ""),
            quantity=body.get("quantity", 0),
            from_store=body.get("from_store", ""),
            to_store=body.get("to_store", ""),
            recorded_at=body.get("recorded_at"),
            note=body.get("note", ""),
            family=body.get("family"),
        )
    )


def _device_flow(store, match, query, body):
    events = store.device_flow(match.group("serial"))
    return _ok({"flow": [to_dict(item) for item in events]})


def _device_features(store, match, query, body):
    age = _first(query, "age")
    result = store.feature_availability(
        match.group("serial"),
        age=int(age) if age else None,
        scenario=_first(query, "scenario") or "home",
    )
    return _ok({"features": result})


def _create_action(store, match, query, body):
    return _created(
        store.create_action(
            body.get("type"),
            body.get("model_id"),
            body.get("reason"),
            body.get("created_by"),
            batch_ids=body.get("batch_ids"),
            firmware_versions=body.get("firmware_versions"),
            feature_id=body.get("feature_id", ""),
            assessment_id=body.get("assessment_id", ""),
            phases=body.get("phases"),
        )
    )


def _get_action(store, match, query, body):
    action_id = match.group("action_id")
    action = store.actions.get(action_id)
    if not action:
        raise NotFound(f"处置动作不存在：{action_id}")
    tasks = [to_dict(task) for task in store.action_tasks(action_id)]
    notices = [to_dict(item) for item in store.notices_for_action(action_id)]
    evidence = [to_dict(item) for item in store.evidence.values() if item.action_id == action_id]
    return _ok({**to_dict(action), "tasks": tasks, "notices": notices, "evidence": evidence})


def _publish_notice(store, match, query, body):
    return _created(
        store.publish_notice(
            match.group("action_id"), body.get("title"), body.get("body"), body.get("issued_by")
        )
    )


def _revise_notice(store, match, query, body):
    return _created(
        store.revise_notice(
            match.group("notice_id"), body.get("title"), body.get("body"), body.get("issued_by")
        )
    )


def _notice_history(store, match, query, body):
    history = store.notice_history(match.group("notice_id"))
    return _ok({"notice_id": match.group("notice_id"), "versions": [to_dict(item) for item in history]})


def _record_evidence(store, match, query, body):
    return _created(
        store.record_evidence(
            body.get("action_id"),
            body.get("serial"),
            body.get("type"),
            body.get("detail"),
            body.get("recorded_by"),
        )
    )


def _scan_overdue(store, match, query, body):
    created = store.scan_overdue(action_id=match.group("action_id"), now=(body or {}).get("now"))
    return _ok({"overdue": [to_dict(item) for item in created]})


def _trace(store, match, query, body):
    role = _first(query, "role") or "regulator"
    if role not in ROLES:
        raise Validation(f"未知角色：{role}（可选 {', '.join(ROLES)}）")
    return _ok(view_for_role(store.trace(match.group("serial")), role))


def _events(store, match, query, body):
    return _ok({"events": store.events})


def _first(query, name):
    values = query.get(name)
    return values[0] if values else None


ROUTES = [
    ("GET", r"/health", _health),
    ("POST", r"/models", _register_model),
    ("POST", r"/batches", _register_batch),
    ("POST", r"/firmwares", _register_firmware),
    ("POST", r"/assessments", _publish_assessment),
    ("GET", r"/assessments", _list_assessments),
    ("POST", r"/devices", _register_device),
    ("POST", r"/consents", _record_consent),
    ("POST", r"/flow", _record_flow),
    ("GET", r"/devices/(?P<serial>[^/]+)/flow", _device_flow),
    ("GET", r"/devices/(?P<serial>[^/]+)/features", _device_features),
    ("POST", r"/actions", _create_action),
    ("GET", r"/actions/(?P<action_id>[^/]+)", _get_action),
    ("POST", r"/actions/(?P<action_id>[^/]+)/notices", _publish_notice),
    ("POST", r"/actions/(?P<action_id>[^/]+)/scan-overdue", _scan_overdue),
    ("POST", r"/notices/(?P<notice_id>[^/]+)/revisions", _revise_notice),
    ("GET", r"/notices/(?P<notice_id>[^/]+)", _notice_history),
    ("POST", r"/evidence", _record_evidence),
    ("GET", r"/trace/(?P<serial>[^/]+)", _trace),
    ("GET", r"/events", _events),
]

_STATUS_BY_ERROR = {Validation: 400, NotFound: 404, Conflict: 409}


def make_handler(store=None):
    """构造绑定指定存储的 Handler；默认使用全新内存存储。"""
    bound_store = store or Store()

    class Handler(BaseHTTPRequestHandler):
        """领域接口与健康检查的统一入口。"""

        store = bound_store

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            for route_method, pattern, func in ROUTES:
                if route_method != method:
                    continue
                match = re.fullmatch(pattern, parsed.path)
                if not match:
                    continue
                try:
                    body = self._read_body() if method == "POST" else {}
                    status, payload = func(self.store, match, query, body)
                except tuple(_STATUS_BY_ERROR) as error:
                    status = _STATUS_BY_ERROR[type(error)]
                    payload = {"error": str(error)}
                except (ValueError, KeyError, TypeError) as error:
                    status, payload = 400, {"error": f"请求不合法：{error}"}
                self._send(status, payload)
                return
            self._send(404, {"error": "未知路径"})

        def _read_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except json.JSONDecodeError as error:
                raise Validation(f"请求体不是合法 JSON：{error}") from error

        def _send(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    return Handler


Handler = make_handler()
