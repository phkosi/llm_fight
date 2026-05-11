import sys
import os
import pytest

# Add the src-layout package directory to sys.path for local test runs.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_root = os.path.join(project_root, "src")
sys.path.insert(0, src_root)


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", default=False, help="run live Ollama integration tests")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="live test requires --run-live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
