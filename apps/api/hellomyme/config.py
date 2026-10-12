from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_LAYERS = ("PRE_SEED", "SEED", "VERIFIED")
DEV_PHONE_HASH_SECRET = "nextpath-phone-hash-dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HELLOMYME_", env_file=".env", extra="ignore")

    env: str = Field(default="development", pattern="^(development|test|staging|production)$")
    database_url: str = "postgresql+psycopg://hellomyme:hellomyme@localhost:5432/hellomyme"

    # Which data layers feed Career Map statistics. Decision Q2: PRE_SEED is
    # development/UX/simulation only; production observed Career Map = SEED + VERIFIED.
    career_map_data_layers: list[str] = ["PRE_SEED", "SEED", "VERIFIED"]

    # Login providers enabled for this environment. DEV is a test-only provider.
    # Kakao login goes through HMM ID (the company IdP), never directly to Kakao.
    auth_providers: list[str] = ["DEV"]
    hmm_id_base_url: str = "https://id.da-sh.io"
    hmm_id_timeout_seconds: float = 5.0
    google_tokeninfo_url: str = "https://oauth2.googleapis.com/tokeninfo"
    google_client_id: str | None = None

    cors_origins: list[str] = ["http://localhost:3001"]

    session_ttl_hours: int = 24 * 30
    anonymous_draft_ttl_hours: int = 24 * 7

    # Taxonomy/policy rows change only through migrations and imports, so the query engine keeps
    # them in process this long instead of re-reading them on every request (0 disables).
    reference_cache_seconds: int = 60

    # Team dashboard (/admin): account ids allowed to see the aggregate numbers, e.g.
    # HELLOMYME_ADMIN_ACCOUNT_IDS='["3f0c…-…"]'. A member who is not listed sees their own id.
    admin_account_ids: list[str] = []

    # User-interview opt-in (phone). "none": the number is kept unverified (no SMS sent);
    # "solapi": a 6-digit code is sent and must be entered; "log": development only, the code is
    # written to the server log instead of being sent.
    sms_provider: str = Field(default="none", pattern="^(none|log|solapi)$")
    solapi_api_key: SecretStr | None = None
    solapi_api_secret: SecretStr | None = None
    sms_sender_number: str | None = None  # a sender number registered with the provider
    # Keyed hash for verification/rate-limit rows, so they never hold a readable number.
    # Only used when codes are sent (sms_provider other than "none"); a real secret is required then.
    phone_hash_secret: SecretStr = SecretStr(DEV_PHONE_HASH_SECRET)
    # Off: the invitation is not shown and new applications are refused (withdrawal still works).
    interview_enabled: bool = True
    interview_consent_version: str = "interview_contact_v1"
    # Shown under the invitation only when set (the reward is a business decision).
    interview_reward_text: str | None = None

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, value: str) -> str:
        """Accept URLs exactly as Supabase/Render/Heroku print them (postgres:// or
        postgresql://) and select the psycopg 3 driver this app ships with."""
        value = value.strip()
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

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
            if "HMM_ID" in self.auth_providers and not self.hmm_id_base_url.startswith("https://"):
                raise ValueError("HMM ID must be reached over HTTPS in production")
        # The live demand test runs as staging: real people's numbers, so the same rules as production.
        if self.env in ("staging", "production") and self.sms_provider != "none":
            if self.sms_provider == "log":
                raise ValueError("the log SMS provider writes codes to the log: development only")
            if self.phone_hash_secret.get_secret_value() == DEV_PHONE_HASH_SECRET:
                raise ValueError("set HELLOMYME_PHONE_HASH_SECRET before sending verification codes")
        if self.sms_provider == "solapi" and not (self.solapi_api_key and self.solapi_api_secret
                                                  and self.sms_sender_number):
            raise ValueError("solapi needs api key, api secret and a registered sender number")
        return self

    @property
    def is_simulation(self) -> bool:
        return "PRE_SEED" in self.career_map_data_layers


@lru_cache
def get_settings() -> Settings:
    return Settings()
