"""SQLite: состояние сборщика, письма, вложения, полнотекстовый индекс (FTS5 trigram — ищет по части слова,
русская морфология не нужна: «закладн» найдёт «закладные», «закладных»)."""
import sqlite3

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS folders (
    path TEXT PRIMARY KEY,          -- имя папки на сервере (modified UTF-7)
    name TEXT,                      -- человекочитаемое имя
    uidvalidity INTEGER,
    last_uid INTEGER DEFAULT 0,
    last_sync TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    key TEXT PRIMARY KEY,           -- Message-ID или sha1 сырого письма
    message_id TEXT,
    in_reply_to TEXT,
    refs TEXT,                      -- References через пробел
    date TEXT,                      -- ISO, местное время
    from_addr TEXT, from_name TEXT,
    to_addrs TEXT, cc_addrs TEXT,
    subject TEXT,
    direction TEXT,                 -- out (мы написали) / in
    counterpart TEXT,               -- адрес собеседника
    body_new TEXT,                  -- текст без цитат и подписи
    quote TEXT,                     -- отрезанная цитата (нужна, если оригинала нет в архиве)
    quote_kind TEXT,                -- '', 'quote', 'inline', 'forward'
    signature TEXT,
    has_attachments INTEGER DEFAULT 0,
    size INTEGER,
    eml_path TEXT,
    thread_id TEXT,
    parsed_version INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS messages_msgid ON messages(message_id);
CREATE INDEX IF NOT EXISTS messages_thread ON messages(thread_id);
CREATE INDEX IF NOT EXISTS messages_date ON messages(date);
CREATE TABLE IF NOT EXISTS locations (
    key TEXT, folder TEXT, uid INTEGER,
    PRIMARY KEY (folder, uid)
);
CREATE TABLE IF NOT EXISTS attachments (
    key TEXT, idx INTEGER, filename TEXT, content_type TEXT, size INTEGER,
    text_path TEXT, text_chars INTEGER, note TEXT,
    PRIMARY KEY (key, idx)
);
CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT PRIMARY KEY, subject TEXT, counterpart TEXT,
    first_date TEXT, last_date TEXT, count INTEGER, last_direction TEXT, md_path TEXT,
    sig TEXT                        -- хэш состава цепочки: не изменился — файл не перерисовываем
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    key UNINDEXED, subject, sender, body, attachments, tokenize='trigram'
);
"""


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=60)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db
