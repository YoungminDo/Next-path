from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_LAYERS = ("PRE_SEED", "SEED", "VERIFIED")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HELLOMYME_", env_file=".env", extra="ignore")

    env: str = Field(default="development", pattern="^(development|test|staging|production)$")
    database_url: str = "postgresql+psycopg://hellomyme:hellomyme@localhost:5432/hellomyme"

    # Which data layers feed Career Map statistics. Decision Q2: PRE_SEED is
    # development/UX/simulation only; production observed Career Map = SEED + VERIFIED.
    career_map_data_layers: list[str] = ["PRE_SEED", "SEED", "VERIFIED"]

    # Login providers enabled for this environment. DEV is a test-only provider.
    auth_providers: list[str] = ["DEV"]
    kakao_user_info_url: str = "https://kapi.kakao.com/v2/user/me"
    google_tokeninfo_url: str = "https://oauth2.googleapis.com/tokeninfo"
    google_client_id: str | None = None

    cors_origins: list[str] = ["http://localhost:3000"]

    session_ttl_hours: int = 24 * 30
    anonymous_draft_ttl_hours: int = 24 * 7

    @model_validator(mode="after")
    def _guard_production(self) -> "Settings":
        unknown = set(self.career_map_data_layers) - set(DATA_LAYERS)
        if unknown:
            raise ValueError(f"unknown data layers: {sorted(unknown)}")
        if self.env == "production":
            if "PRE_SEED" in self.career_map_data_layers:
                raise ValueError("PRE_SEED must never feed production Career Map statistics")
            if "DEV" in self.auth_providers:
                raise ValueError("DEV auth provider is not allowed in production")
        return self

    @property
    def is_simulation(self) -> bool:
        return "PRE_SEED" in self.career_map_data_layers


@lru_cache
def get_settings() -> Settings:
    return Settings()
