"""儿童产品风险召回的运行入口。

健康检查身份保持稳定；业务接口由 recall 包提供。
"""

import argparse

from recall import SERVICE_ID, SERVICE_NAME, health_payload
from recall.api import Handler, make_handler
from recall.seed import seed
from recall.store import Store

__all__ = ["Handler", "SERVICE_ID", "SERVICE_NAME", "health_payload"]


def main():
    parser = argparse.ArgumentParser(description=SERVICE_NAME)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--seed", action="store_true", help="载入演示数据，便于本地联调")
    args = parser.parse_args()
    if args.check:
        assert health_payload()["service"] == SERVICE_ID
        print("基础检查通过")
        return
    from http.server import ThreadingHTTPServer

    handler = make_handler(seed(Store())) if args.seed else Handler
    ThreadingHTTPServer(("0.0.0.0", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
