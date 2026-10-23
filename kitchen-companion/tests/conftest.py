import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Eval tests call the real Anthropic API; skip them cleanly when no key is set."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    skip = pytest.mark.skip(reason="needs ANTHROPIC_API_KEY")
    for item in items:
        if "eval" in item.keywords:
            item.add_marker(skip)
