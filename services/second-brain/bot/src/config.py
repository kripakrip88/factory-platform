from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    telegram_bot_token: str
    telegram_group_ids: List[int]
    owner_user_id: int

    anthropic_api_key: str

    postgres_db: str
    postgres_user: str
    postgres_password: str

    redis_password: str

    review_cron: str = "0 20 * * *"
    review_batch_size: int = 5

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@brain-db:5432/{self.postgres_db}"
        )

    @property
    def asyncpg_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@brain-db:5432/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@brain-redis:6379"

    class Config:
        env_file = ".env"


settings = Settings()
