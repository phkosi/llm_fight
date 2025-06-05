import sys
import os

# Add the project root directory to sys.path
# This allows pytest to find the 'src' module
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

import asyncio
import pytest

from src.agents import close_session


@pytest.fixture(autouse=True)
def cleanup_aiohttp_session():
    """Ensure the module-level ClientSession is closed after each test."""
    yield
    asyncio.run(close_session())
