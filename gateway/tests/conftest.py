import pytest
from fastapi.testclient import TestClient

from gateway.main import app
from gateway.settings import Settings, get_settings

TEST_KEY = "test-key"


@pytest.fixture
def settings():
    """Settings used by the app during a test; tests may change them before the request."""
    test_settings = Settings(_env_file=None, api_keys=[TEST_KEY])
    app.dependency_overrides[get_settings] = lambda: test_settings
    yield test_settings
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client(settings):
    """Client without credentials. The context manager runs the app's lifespan."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(settings):
    """Client that sends a valid API key with every request."""
    with TestClient(app, headers={"Authorization": f"Bearer {TEST_KEY}"}) as client:
        yield client
