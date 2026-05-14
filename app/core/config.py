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

    # Redis (Celery broker)
    redis_url: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
