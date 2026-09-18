"""领域存储与业务规则。

内存仓储 + 追加式事件日志：每次状态变化都留痕，
支撑检测结论版本化、流向追踪、分级处置与责任还原。
"""

from __future__ import annotations

from . import domain
from .domain import (
    ACTION_TYPES,
    ESSENTIAL_FEATURES,
    EVIDENCE_TYPES,
    FLOW_TYPES,
    RISK_LEVELS,
    VERDICTS,
    Assessment,
    Batch,
    Consent,
    Device,
    Evidence,
    FeatureSwitch,
    Firmware,
    FlowEvent,
    HandlingTask,
    Model,
    Notice,
    PaymentRule,
    Phase,
    RecallAction,
)


class Validation(Exception):
    """请求数据不合法。"""


class NotFound(Exception):
    """引用的对象不存在。"""


class Conflict(Exception):
    """与当前状态冲突（重复登记、流向断链、停售拦截等）。"""


class Store:
    def __init__(self):
        self.models = {}
        self.batches = {}
        self.firmwares = {}
        self.assessments = {}
        self.devices = {}
        self.consents = {}
        self.flow_events = {}
        self.actions = {}
        self.notices = {}  # notice_id -> [Notice 各版本]
        self.tasks = {}
        self.evidence = {}
        self.events = []
        self._counters = {}

    # ---- 基础设施 ----

    def _next_id(self, prefix):
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}-{self._counters[prefix]}"

    def _log(self, kind, ref, summary, at=None):
        self.events.append(
            {
                "seq": len(self.events) + 1,
                "kind": kind,
                "ref": ref,
                "summary": summary,
                "at": at or domain.now_iso(),
            }
        )

    @staticmethod
    def _require(payload, *fields):
        missing = [name for name in fields if payload.get(name) in (None, "")]
        if missing:
            raise Validation(f"缺少字段：{', '.join(missing)}")

    # ---- 登记：型号、批次、固件、检测结论、设备 ----

    def register_model(self, brand, name, actor, at=None):
        self._require({"brand": brand, "name": name, "actor": actor}, "brand", "name", "actor")
        model = Model(
            model_id=self._next_id("M"),
            brand=brand,
            name=name,
            registered_by=actor,
            registered_at=at or domain.now_iso(),
        )
        self.models[model.model_id] = model
        self._log("register", model.model_id, f"登记型号 {brand} {name}", model.registered_at)
        return model

    def register_batch(self, model_id, produced_at, quantity, at=None):
        model = self.models.get(model_id)
        if not model:
            raise NotFound(f"型号不存在：{model_id}")
        if not isinstance(quantity, int) or quantity <= 0:
            raise Validation("quantity 必须为正整数")
        batch = Batch(
            batch_id=self._next_id("B"),
            model_id=model_id,
            produced_at=produced_at or domain.now_iso(),
            quantity=quantity,
        )
        self.batches[batch.batch_id] = batch
        self._log("register", batch.batch_id, f"登记批次 {batch.batch_id}（{model_id}，{quantity} 台）", at)
        return batch

    def register_firmware(self, model_id, version, features, payment_rules=None, at=None):
        if not self.models.get(model_id):
            raise NotFound(f"型号不存在：{model_id}")
        self._require({"version": version}, "version")
        switches = []
        seen = set()
        for raw in features or []:
            self._require(raw, "feature_id", "name")
            if raw.get("risk", "low") not in RISK_LEVELS:
                raise Validation(f"未知风险等级：{raw.get('risk')}")
            if raw["feature_id"] in seen:
                raise Validation(f"能力重复登记：{raw['feature_id']}")
            seen.add(raw["feature_id"])
            switches.append(
                FeatureSwitch(
                    feature_id=raw["feature_id"],
                    name=raw["name"],
                    risk=raw.get("risk", "low"),
                    min_age=int(raw.get("min_age", 0)),
                    scenarios=list(raw.get("scenarios") or domain.SCENARIOS),
                    needs_consent=bool(raw.get("needs_consent", False)),
                    enabled=bool(raw.get("enabled", True)),
                )
            )
        rules = []
        for raw in payment_rules or []:
            self._require(raw, "feature_id", "monthly_limit")
            rules.append(
                PaymentRule(
                    feature_id=raw["feature_id"],
                    monthly_limit=int(raw["monthly_limit"]),
                    requires_consent=bool(raw.get("requires_consent", True)),
                )
            )
        firmware = Firmware(
            firmware_id=self._next_id("FW"),
            model_id=model_id,
            version=version,
            features=[domain.to_dict(item) for item in switches],
            payment_rules=[domain.to_dict(item) for item in rules],
            registered_at=at or domain.now_iso(),
        )
        self.firmwares[firmware.firmware_id] = firmware
        self._log(
            "register",
            firmware.firmware_id,
            f"登记固件 {model_id}@{version}（能力 {len(switches)} 项，付费规则 {len(rules)} 条）",
            firmware.registered_at,
        )
        return firmware

    def publish_assessment(
        self, model_id, firmware_version, verdict, min_age, max_age, summary, issued_by, at=None
    ):
        """发布检测与适龄结论；同一范围再次发布生成新版本，旧版本保留。"""
        if not self.models.get(model_id):
            raise NotFound(f"型号不存在：{model_id}")
        if verdict not in VERDICTS:
            raise Validation(f"未知结论：{verdict}（可选 {', '.join(VERDICTS)}）")
        self._require({"issued_by": issued_by}, "issued_by")
        scope = [
            item
            for item in self.assessments.values()
            if item.model_id == model_id and item.firmware_version == firmware_version
        ]
        previous = max(scope, key=lambda item: item.version, default=None)
        assessment = Assessment(
            assessment_id=self._next_id("AS"),
            model_id=model_id,
            firmware_version=firmware_version or "*",
            verdict=verdict,
            min_age=int(min_age),
            max_age=int(max_age),
            summary=summary or "",
            issued_by=issued_by,
            issued_at=at or domain.now_iso(),
            version=(previous.version + 1) if previous else 1,
            supersedes=previous.assessment_id if previous else "",
        )
        self.assessments[assessment.assessment_id] = assessment
        self._log(
            "assessment",
            assessment.assessment_id,
            f"发布检测结论 {model_id}@{firmware_version or '*'} v{assessment.version}：{verdict}",
            assessment.issued_at,
        )
        return assessment

    def assessment_history(self, model_id=None, firmware_version=None):
        items = sorted(
            self.assessments.values(), key=lambda item: (item.model_id, item.firmware_version, item.version)
        )
        if model_id:
            items = [item for item in items if item.model_id == model_id]
        if firmware_version:
            items = [item for item in items if item.firmware_version == firmware_version]
        return items

    def register_device(self, serial, model_id, batch_id, firmware_version, store="", at=None):
        self._require({"serial": serial}, "serial")
        if serial in self.devices:
            raise Conflict(f"序列号已登记：{serial}")
        if not self.models.get(model_id):
            raise NotFound(f"型号不存在：{model_id}")
        batch = self.batches.get(batch_id)
        if not batch:
            raise NotFound(f"批次不存在：{batch_id}")
        if batch.model_id != model_id:
            raise Validation(f"批次 {batch_id} 不属于型号 {model_id}")
        firmware = self._find_firmware(model_id, firmware_version)
        if not firmware:
            raise NotFound(f"固件不存在：{model_id}@{firmware_version}")
        device = Device(
            serial=serial,
            model_id=model_id,
            batch_id=batch_id,
            firmware_version=firmware_version,
            location=store,
            registered_at=at or domain.now_iso(),
        )
        self.devices[serial] = device
        self._log("register", serial, f"登记设备 {serial}（{model_id}/{batch_id}@{firmware_version}）", at)
        if store:
            self._record_flow(
                FlowEvent(
                    event_id=self._next_id("FL"),
                    type="register",
                    serial=serial,
                    to_store=store,
                    actor="enterprise",
                    recorded_at=device.registered_at,
                    uploaded_at=device.registered_at,
                    note="入库登记",
                )
            )
        return device

    def _find_firmware(self, model_id, version):
        for firmware in self.firmwares.values():
            if firmware.model_id == model_id and firmware.version == version:
                return firmware
        return None

    # ---- 家长同意 ----

    def record_consent(self, serial, scope, granted, granted_by, at=None):
        device = self.devices.get(serial)
        if not device:
            raise NotFound(f"设备不存在：{serial}")
        self._require({"scope": scope, "granted_by": granted_by}, "scope", "granted_by")
        consent = Consent(
            consent_id=self._next_id("C"),
            serial=serial,
            scope=scope,
            granted=bool(granted),
            granted_by=granted_by,
            at=at or domain.now_iso(),
        )
        self.consents[consent.consent_id] = consent
        state = "同意" if consent.granted else "撤回"
        self._log("consent", consent.consent_id, f"家长{state} {serial} 的 {scope}", consent.at)
        return consent

    def active_consents(self, serial):
        """设备当前有效的同意范围（取每个 scope 最新一条记录）。"""
        latest = {}
        for consent in self.consents.values():
            if consent.serial == serial:
                latest[consent.scope] = consent  # consent_id 递增，后者覆盖前者
        return {scope for scope, consent in latest.items() if consent.granted}

    # ---- 流向：入库、跨店调拨、销售、离线盘点、退回 ----

    def _record_flow(self, event):
        self.flow_events[event.event_id] = event
        self._log("flow", event.event_id, f"流向[{event.type}] {event.serial or event.batch_id}", event.uploaded_at)
        return event

    def record_flow(
        self,
        type,
        actor,
        serial="",
        batch_id="",
        quantity=0,
        from_store="",
        to_store="",
        recorded_at=None,
        note="",
        family=None,
    ):
        if type not in FLOW_TYPES:
            raise Validation(f"未知流向类型：{type}（可选 {', '.join(FLOW_TYPES)}）")
        self._require({"actor": actor}, "actor")
        now = domain.now_iso()
        event = FlowEvent(
            event_id=self._next_id("FL"),
            type=type,
            actor=actor,
            serial=serial,
            batch_id=batch_id,
            quantity=int(quantity or 0),
            from_store=from_store,
            to_store=to_store,
            recorded_at=recorded_at or now,
            uploaded_at=now,
            note=note,
        )
        if type == "stocktake":
            # 离线盘点：按序列号或批次数量盘点， recorded_at 可早于上传时间，不改变流向。
            if not serial and not (batch_id and quantity):
                raise Validation("盘点需指定 serial 或 batch_id + quantity")
            if not to_store:
                raise Validation("盘点需指定所在门店 to_store")
            if serial and serial not in self.devices:
                raise NotFound(f"设备不存在：{serial}")
            return self._record_flow(event)

        device = self.devices.get(serial)
        if not device:
            raise NotFound(f"设备不存在：{serial}")

        if type == "transfer":
            if device.location != from_store:
                raise Conflict(
                    f"流向不连续：{serial} 当前在 {device.location or '（已售出）'}，不能从 {from_store} 调出"
                )
            if not to_store:
                raise Validation("调拨需指定调入门店 to_store")
            device.location = to_store
        elif type == "sale":
            self._assert_saleable(device)
            if not family:
                raise Validation("销售需登记家庭信息 family")
            self._require(family, "guardian_name", "phone", "city")
            device.family = {
                "guardian_name": family["guardian_name"],
                "phone": family["phone"],
                "city": family["city"],
                "address": family.get("address", ""),
                "child_age": int(family.get("child_age", 0)),
            }
            device.status = "sold"
            device.location = ""
        elif type in ("return", "recall_return"):
            if not to_store:
                raise Validation("退回需指定接收门店 to_store")
            device.location = to_store
        return self._record_flow(event)

    def _assert_saleable(self, device):
        for action in self.actions.values():
            if action.type == "stop_sale" and action.status == "active" and self._covers(action, device):
                raise Conflict(f"{device.serial} 处于停售处置 {action.action_id} 中，禁止销售")

    def device_flow(self, serial):
        if serial not in self.devices:
            raise NotFound(f"设备不存在：{serial}")
        events = [item for item in self.flow_events.values() if item.serial == serial]
        return sorted(events, key=lambda item: (item.recorded_at, item.event_id))

    # ---- 处置动作：分阶段停售、远程关闭、召回 ----

    def _covers(self, action, device):
        if device.model_id != action.model_id:
            return False
        if action.batch_ids and device.batch_id not in action.batch_ids:
            return False
        if action.firmware_versions and device.firmware_version not in action.firmware_versions:
            return False
        return True

    def affected_devices(self, action):
        return [device for device in self.devices.values() if self._covers(action, device)]

    def create_action(
        self,
        type,
        model_id,
        reason,
        created_by,
        batch_ids=None,
        firmware_versions=None,
        feature_id="",
        assessment_id="",
        phases=None,
        at=None,
    ):
        if type not in ACTION_TYPES:
            raise Validation(f"未知处置类型：{type}（可选 {', '.join(ACTION_TYPES)}）")
        if not self.models.get(model_id):
            raise NotFound(f"型号不存在：{model_id}")
        self._require({"reason": reason, "created_by": created_by}, "reason", "created_by")
        if assessment_id and assessment_id not in self.assessments:
            raise NotFound(f"检测结论不存在：{assessment_id}")
        if type == "remote_disable":
            if not feature_id:
                raise Validation("远程关闭需指定 feature_id")
            if feature_id in ESSENTIAL_FEATURES:
                raise Validation(f"{feature_id} 是基础能力，不可远程关闭")
        phase_objs = []
        for raw in phases or []:
            self._require(raw, "name", "deadline")
            phase_objs.append(
                Phase(name=raw["name"], start_at=raw.get("start_at") or domain.now_iso(), deadline=raw["deadline"])
            )
        if type == "recall" and not phase_objs:
            raise Validation("召回需至少一个处置阶段（含截止时间）")
        action = RecallAction(
            action_id=self._next_id("AC"),
            type=type,
            model_id=model_id,
            reason=reason,
            created_by=created_by,
            created_at=at or domain.now_iso(),
            batch_ids=list(batch_ids or []),
            firmware_versions=list(firmware_versions or []),
            feature_id=feature_id,
            assessment_id=assessment_id,
            phases=[domain.to_dict(item) for item in phase_objs],
        )
        self.actions[action.action_id] = action
        self._log(
            "action",
            action.action_id,
            f"发起处置[{type}] {model_id}（{len(action.phases)} 个阶段）：{reason}",
            action.created_at,
        )
        if type == "recall":
            deadline = max(item["deadline"] for item in action.phases)
            for device in self.affected_devices(action):
                task = HandlingTask(
                    task_id=self._next_id("T"),
                    action_id=action.action_id,
                    serial=device.serial,
                    deadline=deadline,
                    updated_at=action.created_at,
                )
                self.tasks[task.task_id] = task
            self._log(
                "action",
                action.action_id,
                f"召回覆盖 {len(self.action_tasks(action.action_id))} 台设备，截止 {deadline}",
                action.created_at,
            )
        return action

    def action_tasks(self, action_id):
        return [task for task in self.tasks.values() if task.action_id == action_id]

    def disabled_features_for(self, serial):
        """设备当前被远程关闭的能力集合（基础能力永远不会进入该集合）。"""
        device = self.devices.get(serial)
        if not device:
            raise NotFound(f"设备不存在：{serial}")
        disabled = set()
        for action in self.actions.values():
            if action.type == "remote_disable" and action.status == "active" and self._covers(action, device):
                disabled.add(action.feature_id)
        return disabled

    def feature_availability(self, serial, age=None, scenario="home"):
        from .policy import evaluate_features

        device = self.devices.get(serial)
        if not device:
            raise NotFound(f"设备不存在：{serial}")
        firmware = self._find_firmware(device.model_id, device.firmware_version)
        features = [FeatureSwitch(**raw) for raw in firmware.features] if firmware else []
        if age is None and device.family:
            age = device.family.get("child_age")
        return evaluate_features(
            features,
            age=age,
            scenario=scenario,
            consented_scopes=self.active_consents(serial),
            disabled_features=self.disabled_features_for(serial),
        )

    # ---- 通知：发布与修订，旧版本不被覆盖 ----

    def publish_notice(self, action_id, title, body, issued_by, at=None):
        action = self.actions.get(action_id)
        if not action:
            raise NotFound(f"处置动作不存在：{action_id}")
        self._require({"title": title, "issued_by": issued_by}, "title", "issued_by")
        notice = Notice(
            notice_id=self._next_id("N"),
            action_id=action_id,
            version=1,
            title=title,
            body=body or "",
            issued_by=issued_by,
            issued_at=at or domain.now_iso(),
        )
        self.notices[notice.notice_id] = [notice]
        self._log("notice", notice.notice_id, f"发布通知《{title}》v1（{action_id}）", notice.issued_at)
        return notice

    def revise_notice(self, notice_id, title, body, issued_by, at=None):
        history = self.notices.get(notice_id)
        if not history:
            raise NotFound(f"通知不存在：{notice_id}")
        self._require({"title": title, "issued_by": issued_by}, "title", "issued_by")
        previous = history[-1]
        notice = Notice(
            notice_id=notice_id,
            action_id=previous.action_id,
            version=previous.version + 1,
            title=title,
            body=body or "",
            issued_by=issued_by,
            issued_at=at or domain.now_iso(),
            supersedes=previous.version,
        )
        history.append(notice)
        self._log("notice", notice_id, f"修订通知《{title}》v{notice.version}（替代 v{previous.version}）", notice.issued_at)
        return notice

    def notice_history(self, notice_id):
        history = self.notices.get(notice_id)
        if not history:
            raise NotFound(f"通知不存在：{notice_id}")
        return list(history)

    # ---- 证据：退款、换货、拒绝升级、超期未处理 ----

    def record_evidence(self, action_id, serial, type, detail, recorded_by, at=None):
        action = self.actions.get(action_id)
        if not action:
            raise NotFound(f"处置动作不存在：{action_id}")
        if type not in EVIDENCE_TYPES:
            raise Validation(f"未知证据类型：{type}（可选 {', '.join(EVIDENCE_TYPES)}）")
        if type == "overdue":
            raise Validation("超期证据由系统扫描生成，请使用 scan_overdue")
        device = self.devices.get(serial)
        if not device:
            raise NotFound(f"设备不存在：{serial}")
        if not self._covers(action, device):
            raise Validation(f"{serial} 不在处置 {action_id} 范围内")
        self._require({"recorded_by": recorded_by}, "recorded_by")
        evidence = self._append_evidence(action_id, serial, type, detail, recorded_by, at)
        task = self._task_for(action_id, serial)
        if task and task.status == "pending":
            task.status = {"refund": "refunded", "exchange": "exchanged"}.get(type, type)
            task.updated_at = evidence.recorded_at
        if type == "refund":
            device.status = "refunded"
        elif type == "exchange":
            device.status = "exchanged"
        return evidence

    def _append_evidence(self, action_id, serial, type, detail, recorded_by, at=None):
        evidence = Evidence(
            evidence_id=self._next_id("EV"),
            action_id=action_id,
            serial=serial,
            type=type,
            detail=detail or "",
            recorded_by=recorded_by,
            recorded_at=at or domain.now_iso(),
        )
        self.evidence[evidence.evidence_id] = evidence
        self._log("evidence", evidence.evidence_id, f"证据[{type}] {serial}（{action_id}）", evidence.recorded_at)
        return evidence

    def _task_for(self, action_id, serial):
        for task in self.tasks.values():
            if task.action_id == action_id and task.serial == serial:
                return task
        return None

    def scan_overdue(self, action_id=None, now=None):
        """扫描超期未处理的召回任务并生成证据；幂等，可重复执行。"""
        moment = domain.parse_time(now) if now else domain.parse_time(domain.now_iso())
        created = []
        for task in self.tasks.values():
            if task.status != "pending":
                continue
            if action_id and task.action_id != action_id:
                continue
            if domain.parse_time(task.deadline) >= moment:
                continue
            task.status = "overdue"
            task.updated_at = domain.now_iso()
            created.append(
                self._append_evidence(
                    task.action_id,
                    task.serial,
                    "overdue",
                    f"超过截止时间 {task.deadline} 未处理",
                    "system",
                )
            )
        return created

    # ---- 追溯：一个序列号还原认证、销售与处置责任 ----

    def trace(self, serial):
        device = self.devices.get(serial)
        if not device:
            raise NotFound(f"设备不存在：{serial}")
        model = self.models.get(device.model_id)
        batch = self.batches.get(device.batch_id)
        firmware = self._find_firmware(device.model_id, device.firmware_version)
        assessments = [
            item
            for item in self.assessment_history(model_id=device.model_id)
            if item.firmware_version in ("*", device.firmware_version)
        ]
        actions = [item for item in self.actions.values() if self._covers(item, device)]
        action_views = []
        for action in actions:
            notices = [domain.to_dict(n) for n in self.notices_for_action(action.action_id)]
            task = self._task_for(action.action_id, serial)
            records = [domain.to_dict(e) for e in self.evidence.values() if e.action_id == action.action_id and e.serial == serial]
            action_views.append(
                {
                    **domain.to_dict(action),
                    "notices": notices,
                    "task": domain.to_dict(task) if task else None,
                    "evidence": records,
                }
            )
        consents = [domain.to_dict(c) for c in self.consents.values() if c.serial == serial]
        flow = [domain.to_dict(e) for e in self.device_flow(serial)]
        sale_events = [e for e in flow if e["type"] == "sale"]
        return {
            "serial": serial,
            "device": domain.to_dict(device),
            "model": domain.to_dict(model) if model else None,
            "batch": domain.to_dict(batch) if batch else None,
            "firmware": domain.to_dict(firmware) if firmware else None,
            "assessments": [domain.to_dict(item) for item in assessments],
            "consents": consents,
            "flow": flow,
            "actions": action_views,
            "responsibility": {
                "registered_by": model.registered_by if model else "",
                "certified_by": sorted({item.issued_by for item in assessments}),
                "sold_by": sale_events[-1]["actor"] if sale_events else "",
                "action_created_by": sorted({item.created_by for item in actions}),
                "evidence_recorded_by": sorted(
                    {e.recorded_by for e in self.evidence.values() if e.serial == serial}
                ),
            },
        }

    def notices_for_action(self, action_id):
        versions = []
        for history in self.notices.values():
            versions.extend(n for n in history if n.action_id == action_id)
        return sorted(versions, key=lambda n: (n.notice_id, n.version))
