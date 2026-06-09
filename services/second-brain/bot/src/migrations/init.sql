CREATE SCHEMA IF NOT EXISTS brain;
CREATE SCHEMA IF NOT EXISTS n8n;

CREATE TYPE brain.content_category AS ENUM (
    'idea', 'health', 'article', 'inspiration',
    'video', 'image', 'file', 'link', 'other'
);

CREATE TABLE brain.items (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Источник
    source_type  VARCHAR(50) NOT NULL,  -- 'telegram', 'pocket', 'manual'
    source_id    VARCHAR(255),          -- message_id в TG
    source_chat  BIGINT,               -- chat_id TG группы
    -- Контент
    raw_text     TEXT,
    media_url    TEXT,
    media_type   VARCHAR(50),          -- 'photo','video','document','voice','link'
    original_url TEXT,
    -- AI обработка
    category     brain.content_category DEFAULT 'other',
    summary      TEXT,                 -- резюме от Claude (1-2 предложения)
    tags         TEXT[] DEFAULT '{}',
    importance   SMALLINT DEFAULT 3,   -- 1-5
    -- Review
    reviewed_at  TIMESTAMPTZ,
    review_score SMALLINT,             -- -1 skip, 1 liked, 2 saved
    -- Служебное
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX items_fts ON brain.items
    USING GIN(to_tsvector('russian',
        COALESCE(raw_text,'') || ' ' || COALESCE(summary,'')));
CREATE INDEX items_category ON brain.items(category);
CREATE INDEX items_unreviewed ON brain.items(created_at)
    WHERE reviewed_at IS NULL;
CREATE INDEX items_tags ON brain.items USING GIN(tags);
CREATE INDEX items_source ON brain.items(source_chat, source_id);

CREATE TABLE brain.import_progress (
    chat_id     BIGINT PRIMARY KEY,
    last_msg_id BIGINT NOT NULL DEFAULT 0,
    imported_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION brain.touch()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER items_touch
    BEFORE UPDATE ON brain.items
    FOR EACH ROW EXECUTE FUNCTION brain.touch();
