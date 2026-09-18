"""儿童产品风险召回领域包。

服务身份保持与运行入口一致，便于健康检查与运维巡检。
"""

SERVICE_ID = "child-product-recall"
SERVICE_NAME = "儿童产品风险召回"


def health_payload():
    """返回稳定的服务身份信息。"""
    return {"status": "ok", "service": SERVICE_ID, "name": SERVICE_NAME}
