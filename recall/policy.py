"""功能开放策略：高风险能力按年龄与场景逐步开放。

不变量：基础通话、紧急求助、必要定位为基础能力，
不因开关、远程关闭或其他功能停用而失效。
"""

from __future__ import annotations

from .domain import ESSENTIAL_FEATURES, FeatureSwitch


def evaluate_feature(feature: FeatureSwitch, *, age, scenario, consented_scopes, disabled_features):
    """评估单个能力对某台设备是否可用，返回 (可用, 原因列表)。"""
    if feature.essential:
        return True, ["基础能力，始终可用"]

    reasons = []
    if not feature.enabled:
        reasons.append("厂商已关闭")
    if feature.feature_id in disabled_features:
        reasons.append("已被远程关闭")
    if age is not None and age < feature.min_age:
        reasons.append(f"年龄不足（需满 {feature.min_age} 岁）")
    if scenario and scenario not in feature.scenarios:
        reasons.append(f"场景受限（{scenario} 不可用）")
    if feature.needs_consent and feature.feature_id not in consented_scopes:
        reasons.append("待家长同意")
    return not reasons, reasons


def evaluate_features(features, *, age=None, scenario="home", consented_scopes=(), disabled_features=()):
    """逐项评估固件的能力清单，返回 {feature_id: {available, reasons, essential}}。"""
    consented = set(consented_scopes)
    disabled = set(disabled_features)
    result = {}
    for feature in features:
        available, reasons = evaluate_feature(
            feature,
            age=age,
            scenario=scenario,
            consented_scopes=consented,
            disabled_features=disabled,
        )
        result[feature.feature_id] = {
            "available": available,
            "essential": feature.essential,
            "risk": feature.risk,
            "reasons": reasons,
        }
    # 固件未登记的基础能力同样必须可用，按兜底补齐。
    for essential_id in ESSENTIAL_FEATURES:
        if essential_id not in result:
            result[essential_id] = {
                "available": True,
                "essential": True,
                "risk": "low",
                "reasons": ["基础能力，始终可用"],
            }
    return result
