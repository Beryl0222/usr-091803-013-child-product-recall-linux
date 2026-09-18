"""角色视图：监管全量可见，企业与门店仅见完成召回所必需的家庭信息。"""

from __future__ import annotations

import copy

from .domain import ROLES


def mask_name(name: str) -> str:
    if not name:
        return ""
    return name[0] + "*" * max(len(name) - 1, 1)


def mask_phone(phone: str) -> str:
    if len(phone) >= 7:
        return phone[:3] + "****" + phone[-4:]
    return "***"


def mask_family(family: dict) -> dict:
    """保留召回联络所需的最小信息：姓氏、脱敏电话、城市与儿童年龄。"""
    if not family:
        return family
    return {
        "guardian_name": mask_name(family.get("guardian_name", "")),
        "phone": mask_phone(family.get("phone", "")),
        "city": family.get("city", ""),
        "child_age": family.get("child_age", 0),
        "address": "（详细地址仅监管可见）",
    }


def view_for_role(payload: dict, role: str) -> dict:
    """按角色返回视图；非监管角色的家庭信息被脱敏。"""
    if role not in ROLES:
        raise ValueError(f"未知角色：{role}（可选 {', '.join(ROLES)}）")
    data = copy.deepcopy(payload)
    if role == "regulator":
        return data
    _mask_in_place(data)
    return data


def _mask_in_place(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "family" and isinstance(value, dict):
                node[key] = mask_family(value)
            else:
                _mask_in_place(value)
    elif isinstance(node, list):
        for item in node:
            _mask_in_place(item)
