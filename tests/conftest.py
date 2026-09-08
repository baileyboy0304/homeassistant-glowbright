"""Use Home Assistant's real Recorder test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def enable_custom_integrations_fixture(recorder_mock, enable_custom_integrations):
    yield
