"""Настройки из окружения. Пароль — только из /etc/mail-index/imap.env (systemd EnvironmentFile), не из кода."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _list(name, default):
    raw = os.environ.get(name)
    return [x.strip() for x in raw.split(",") if x.strip()] if raw else list(default)


@dataclass
class Config:
    user: str = field(default_factory=lambda: os.environ.get("MAIL_USER", ""))
    password: str = field(default_factory=lambda: os.environ.get("MAIL_PASS", ""), repr=False)
    host: str = field(default_factory=lambda: os.environ.get("MAIL_HOST", "imap.mail.ru"))
    port: int = field(default_factory=lambda: int(os.environ.get("MAIL_PORT", "993")))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("MAIL_INDEX_DIR", "/srv/mail-index")))
    # Первая загрузка: с какой даты (ГГГГ-ММ-ДД). Пусто — вся история.
    since: str = field(default_factory=lambda: os.environ.get("MAIL_SINCE", ""))
    # Папки по SPECIAL-USE, которые не берём: спам, корзина, черновики.
    skip_flags: list = field(default_factory=lambda: _list("MAIL_SKIP_FLAGS", ["\\Junk", "\\Trash", "\\Drafts"]))
    # Папки по имени (после декодирования), которые не берём.
    skip_names: list = field(default_factory=lambda: _list("MAIL_SKIP_NAMES", ["Спам", "Корзина", "Черновики"]))
    batch: int = field(default_factory=lambda: int(os.environ.get("MAIL_BATCH", "40")))
    max_message_mb: int = field(default_factory=lambda: int(os.environ.get("MAIL_MAX_MB", "60")))
    tz: str = field(default_factory=lambda: os.environ.get("MAIL_TZ", "Asia/Vladivostok"))

    @property
    def own_addresses(self):
        extra = _list("MAIL_OWN_ADDRESSES", [])
        return {a.lower() for a in [self.user, *extra] if a}

    @property
    def db_path(self):
        return self.data_dir / "index.sqlite"

    @property
    def eml_dir(self):
        return self.data_dir / "eml"

    @property
    def md_dir(self):
        return self.data_dir / "md"
