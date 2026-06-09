from pydantic_settings import BaseSettings, EnvSettingsSource, PydanticBaseSettingsSource
from typing import List, Type, Tuple


class _EnvSource(EnvSettingsSource):
    """Поддерживает запятую-разделённые списки: -100xxx,-100yyy"""

    def prepare_field_value(self, field_name, field, value, value_is_complex):
        if field_name == "telegram_group_ids" and isinstance(value, str):
            s = value.strip()
            if s and not s.startswith("["):
                value = "[" + s + "]"
        return super().prepare_field_value(field_name, field, value, value_is_complex)


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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        secrets_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, _EnvSource(settings_cls), dotenv_settings, secrets_settings)

    class Config:
        env_file = ".env"


settings = Settings()
