from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_LAYERS = ("PRE_SEED", "SEED", "VERIFIED")
DEV_PHONE_HASH_SECRET = "nextpath-phone-hash-dev"
DEV_PROFILE_KEY_SECRET = "nextpath-profile-key-dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HELLOMYME_", env_file=".env", extra="ignore",
                                      populate_by_name=True)

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
    # Input that never became a member's, and usage events, leave after this (privacy policy §2).
    unclaimed_input_retention_days: int = 365 * 3

    # Taxonomy/policy rows change only through migrations and imports, so the query engine keeps
    # them in process this long instead of re-reading them on every request (0 disables).
    reference_cache_seconds: int = 60

    # Resume / LinkedIn-capture import: a person's own files are read by Claude into career rows
    # they check before anything is kept (before login it prefills the input form). Off without a
    # key; the Anthropic SDK's own variable name is accepted as is. Each read costs money, so
    # reads are limited per account, per anonymous session and, before login, for everyone
    # together per 24 h (the cost ceiling).
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "HELLOMYME_ANTHROPIC_API_KEY",
                                                    "anthropic_api_key"))
    # A key that is not scoped to one workspace must name it on every request (the API refuses
    # it otherwise); a workspace-scoped key needs nothing here.
    anthropic_workspace_id: str | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_WORKSPACE_ID",
                                                    "HELLOMYME_ANTHROPIC_WORKSPACE_ID",
                                                    "anthropic_workspace_id"))
    career_import_model: str = "claude-opus-5-5"
    # Toss Payments (paid cards, migration 0037). Without the secret key paid cards are off.
    # The client key is public and lives in the web app (NEXT_PUBLIC_TOSS_CLIENT_KEY).
    toss_secret_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("TOSS_SECRET_KEY", "HELLOMYME_TOSS_SECRET_KEY",
                                                    "toss_secret_key"))
    toss_api_base: str = "https://api.tosspayments.com"
    # Team alert in Slack (#marketing_alert) when a new member signs up: a Slack Incoming Webhook
    # URL, set on the server only (it lets anyone post to the channel). Unset = no alerts.
    slack_signup_webhook_url: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("SLACK_SIGNUP_WEBHOOK_URL",
                                                    "HELLOMYME_SLACK_SIGNUP_WEBHOOK_URL",
                                                    "slack_signup_webhook_url"))
    public_web_url: str = "https://nextpath.da-sh.io"
    career_import_daily_limit: int = 10  # per account
    career_import_session_limit: int = 3  # per anonymous session
    career_import_client_limit: int = 20  # per client address before login (shared Wi-Fi allowed)
    career_import_anonymous_daily_limit: int = 300  # all anonymous reads together
    career_import_consent_version: str = "career_import_v1"
    # Optional, separate consent: keep what the read showed as anonymous statistics input, also
    # when the person never signs up (migration 0031). Kept this many days, then removed.
    career_import_stats_consent_version: str = "career_import_stats_v1"
    career_import_retention_days: int = 365 * 3

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
    # Job-alert opt-in (/alert): same phone check as the interview, its own consent (migration 0043).
    job_alert_enabled: bool = True
    job_alert_consent_version: str = "job_alert_contact_v1"
    # First-pass fit analysis (/alert, migration 0044): confirmed records to Claude, its own
    # overseas-transfer consent wording; runs per account per day.
    fit_analysis_enabled: bool = True
    fit_analysis_consent_version: str = "fit_analysis_v1"
    fit_analysis_daily_limit: int = 3
    # Coaching requests: product prices live in coaching_product; the phone has its own consent.
    coaching_enabled: bool = True
    coaching_consent_version: str = "coaching_contact_v1"

    # Search ingest (docs/12): public-profile snippets from search APIs, received for review as
    # SEED statistics input. Either key alone works; with both the run alternates per query.
    # Production also needs the legal review flag (docs/09 §9), like the workbook's --legal-reviewed.
    serpapi_key: SecretStr | None = None
    brave_api_key: SecretStr | None = None
    public_profile_legal_basis: str | None = None
    public_profile_legal_reviewed: bool = False
    # Keyed hash of a public profile's slug = the search ingest submission id (dedup across runs).
    # A slug is name-shaped, so an unkeyed hash could be checked against guessed names. Set it
    # once, before the first live run: changing it later breaks dedup against earlier runs.
    profile_key_secret: SecretStr = SecretStr(DEV_PROFILE_KEY_SECRET)

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
        if (self.env in ("staging", "production") and (self.serpapi_key or self.brave_api_key)
                and self.profile_key_secret.get_secret_value() == DEV_PROFILE_KEY_SECRET):
            raise ValueError("set HELLOMYME_PROFILE_KEY_SECRET before running search ingest")
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
