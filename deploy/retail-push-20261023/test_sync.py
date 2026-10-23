"""向服务器推送一份零售测试数据并打印响应。

用法::

    python deploy/retail-push-20261023/test_sync.py
    python deploy/retail-push-20261023/test_sync.py --url http://127.0.0.1:8001/open/v1/retail/orders/sync
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
DEFAULT_URL = "http://120.237.174.243:6479/open/v1/retail/orders/sync"


def main() -> None:
    parser = argparse.ArgumentParser(description="推送零售测试数据")
    parser.add_argument("--url", default=DEFAULT_URL, help="接口地址")
    parser.add_argument("--file", default=str(HERE / "test_retail_sync.json"), help="测试数据 JSON")
    args = parser.parse_args()

    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    headers = {"X-Request-ID": str(payload.get("request_id") or "retail-test")}
    with httpx.Client(timeout=60) as client:
        response = client.post(args.url, json=payload, headers=headers)
    print(f"HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except ValueError:
        print(response.text)


if __name__ == "__main__":
    main()
