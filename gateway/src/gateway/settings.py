"""Gateway configuration, read from environment variables (and .env)."""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # All variables use the GATEWAY_ prefix, e.g. GATEWAY_BACKEND_URL.
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    # Base URL of the llama.cpp server (inside the Docker network).
    backend_url: str = "http://llm:8080"

    # Accepted client API keys, given as a comma-separated string: "key1,key2".
    # NoDecode: take the raw string instead of expecting a JSON list.
    api_keys: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Timeout for backend requests in seconds (generation can take a while).
    backend_timeout: float = 300.0

    # Rate limit per API key (token bucket): sustained requests per minute, and how many
    # requests may arrive at once on top of that. Set either to 0 to disable the limit.
    rate_limit_per_minute: float = Field(default=60.0, ge=0)
    rate_limit_burst: int = Field(default=10, ge=0)

    @field_validator("api_keys", mode="before")
    @classmethod
    def split_api_keys(cls, value: object) -> object:
        if isinstance(value, str):
            return [key.strip() for key in value.split(",") if key.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton (cached so the environment is read only once)."""
    return Settings()
