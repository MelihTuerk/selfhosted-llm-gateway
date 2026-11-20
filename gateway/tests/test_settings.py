from gateway.settings import Settings


def test_api_keys_are_split_from_comma_separated_env(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "alpha, beta,,gamma ")
    settings = Settings(_env_file=None)
    assert settings.api_keys == ["alpha", "beta", "gamma"]


def test_defaults_without_env(monkeypatch):
    monkeypatch.delenv("GATEWAY_API_KEYS", raising=False)
    monkeypatch.delenv("GATEWAY_BACKEND_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.api_keys == []
    assert settings.backend_url == "http://llm:8080"
