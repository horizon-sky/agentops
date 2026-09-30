"""pytest 全局配置：默认跳过需要真实网络/外部服务的用例。"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_live = os.getenv("AGENTOPS_LIVE") == "1"
    if run_live:
        return
    skip_live = pytest.mark.skip(reason="需要 AGENTOPS_LIVE=1 才会执行真实外部调用")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
