"""Pytest configuration for maxxtrading-model-training.

Integration tests require TRAINING_DATABASE_URL (a disposable, read-only
credential) and are skipped automatically otherwise.
"""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("TRAINING_DATABASE_URL"):
        return
    skip_integration = pytest.mark.skip(reason="TRAINING_DATABASE_URL not set")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
