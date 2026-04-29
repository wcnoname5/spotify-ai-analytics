"""
conftest.py — pytest common configuration and fixtures。

This script is automatically loaded when pytest starts, affecting the entire `tests/` directory (and its subdirectories).
In this project, it is used to set up logging for tests and provides an automatically applied
`initialize_logging` fixture, which uses a specific log name for tests marked with the `integration` marker.
"""

import pytest
from pathlib import Path
from spotify_core.logging import setup_logging

def pytest_configure(config):
    setup_logging(mode="test", log_name="pytest_session")

@pytest.fixture(scope="function", autouse=True)
def initialize_logging(request):
    if "integration" in request.node.keywords:
        test_file_name = Path(request.node.fspath).stem
        setup_logging(mode="test", log_name=test_file_name)
