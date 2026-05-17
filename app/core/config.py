from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "DealScout API"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str
    database_pool_size: int = 10

    # Auth
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # External APIs
    miami_dade_api_key: str = ""
    census_api_key: str = ""
    anthropic_api_key: str = ""
    resend_api_key: str = ""
    mapbox_token: str = ""              # MAPBOX_TOKEN
    next_public_mapbox_token: str = ""  # NEXT_PUBLIC_MAPBOX_TOKEN (fallback)

    # Email alerts (Resend)
    alert_email_to: str = ""          # comma-separated recipient list
    alert_email_from: str = "alerts@prosperradar.com"
    app_url: str = "https://app.prosperradar.com"

    # Redis (Celery broker)
    redis_url: str = "redis://localhost:6379/0"

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore",   # shared .env has Vercel/webapp keys — ignore them
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
