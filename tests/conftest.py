import os
from pathlib import Path

import pytest

_TEST_CONFIG_CREATED = False
_TEST_CONFIG_PATH = Path(__file__).resolve().parents[1] / "llmfight.ini"


def pytest_configure(config):
    """Provide CI with the ignored local config that developer machines often have."""
    global _TEST_CONFIG_CREATED
    if _TEST_CONFIG_PATH.exists():
        return
    _TEST_CONFIG_PATH.write_text("[General]\nollama_default_model = qwen3.6:35b\n", encoding="utf-8")
    _TEST_CONFIG_CREATED = True


def pytest_sessionfinish(session, exitstatus):
    if _TEST_CONFIG_CREATED and _TEST_CONFIG_PATH.exists():
        _TEST_CONFIG_PATH.unlink()


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", default=False, help="run live Ollama integration tests")
    parser.addoption("--run-perf", action="store_true", default=False, help="run heavyweight performance tests")


def pytest_collection_modifyitems(config, items):
    run_live = config.getoption("--run-live")
    run_perf = config.getoption("--run-perf")
    has_api_url = bool(os.environ.get("API_URL"))

    skip_live = pytest.mark.skip(reason="live test requires --run-live")
    skip_live_api = pytest.mark.skip(reason="live test requires API_URL")
    skip_perf = pytest.mark.skip(reason="performance test requires --run-perf")

    for item in items:
        if "perf" in item.keywords and not run_perf:
            item.add_marker(skip_perf)
            continue
        if "live" in item.keywords and not run_live:
            item.add_marker(skip_live)
            continue
        if "live" in item.keywords and not has_api_url:
            item.add_marker(skip_live_api)
