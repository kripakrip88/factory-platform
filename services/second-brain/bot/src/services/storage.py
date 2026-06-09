import asyncpg
from typing import Optional

_pool: Optional[asyncpg.Pool] = None


async def init_pool(dsn: str) -> None:
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)


async def close_pool() -> None:
    if _pool:
        await _pool.close()


async def save_item(data: dict) -> str:
    row = await _pool.fetchrow(
        """
        INSERT INTO brain.items
            (source_type, source_id, source_chat, raw_text, media_url,
             media_type, original_url, category, summary, tags, importance)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        RETURNING id::text
        """,
        data.get("source_type", "telegram"),
        data.get("source_id"),
        data.get("source_chat"),
        data.get("raw_text"),
        data.get("media_url"),
        data.get("media_type"),
        data.get("original_url"),
        data.get("category", "other"),
        data.get("summary"),
        data.get("tags", []),
        data.get("importance", 3),
    )
    return row["id"]


async def get_unreviewed(limit: int = 5) -> list[dict]:
    rows = await _pool.fetch(
        """
        SELECT id::text, category, summary, tags, importance, raw_text,
               media_url, media_type, created_at
        FROM brain.items
        WHERE reviewed_at IS NULL
        ORDER BY importance DESC, created_at ASC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def get_by_category(category: str, limit: int = 10, offset: int = 0) -> list[dict]:
    rows = await _pool.fetch(
        """
        SELECT id::text, category, summary, tags, importance, raw_text,
               media_url, media_type, created_at
        FROM brain.items
        WHERE category = $1
        ORDER BY created_at DESC
        LIMIT $2 OFFSET $3
        """,
        category, limit, offset,
    )
    return [dict(r) for r in rows]


async def get_item(item_id: str) -> Optional[dict]:
    row = await _pool.fetchrow(
        """
        SELECT id::text, category, summary, tags, importance, raw_text,
               media_url, media_type, created_at, review_score
        FROM brain.items WHERE id = $1::uuid
        """,
        item_id,
    )
    return dict(row) if row else None


async def get_neighbours(item_id: str) -> dict:
    """Возвращает id предыдущего и следующего айтема по дате."""
    prev_row = await _pool.fetchrow(
        "SELECT id::text FROM brain.items WHERE created_at < (SELECT created_at FROM brain.items WHERE id=$1::uuid) ORDER BY created_at DESC LIMIT 1",
        item_id,
    )
    next_row = await _pool.fetchrow(
        "SELECT id::text FROM brain.items WHERE created_at > (SELECT created_at FROM brain.items WHERE id=$1::uuid) ORDER BY created_at ASC LIMIT 1",
        item_id,
    )
    return {
        "prev": prev_row["id"] if prev_row else None,
        "next": next_row["id"] if next_row else None,
    }


async def mark_reviewed(item_id: str, score: int) -> None:
    await _pool.execute(
        """
        UPDATE brain.items
        SET reviewed_at = NOW(), review_score = $1
        WHERE id = $2::uuid
        """,
        score,
        item_id,
    )


async def search(query: str) -> list[dict]:
    rows = await _pool.fetch(
        """
        SELECT id::text, category, summary, tags, importance, raw_text,
               media_url, media_type, created_at
        FROM brain.items
        WHERE to_tsvector('russian', COALESCE(raw_text,'') || ' ' || COALESCE(summary,''))
              @@ plainto_tsquery('russian', $1)
        ORDER BY created_at DESC
        LIMIT 10
        """,
        query,
    )
    return [dict(r) for r in rows]


async def set_user_rating(item_id: str, rating: int) -> None:
    await _pool.execute(
        "UPDATE brain.items SET user_rating=$1 WHERE id=$2::uuid",
        rating, item_id,
    )


async def update_classification(item_id: str, result: dict) -> None:
    await _pool.execute(
        """UPDATE brain.items
           SET category=$1, summary=$2, tags=$3, importance=$4
           WHERE id=$5::uuid""",
        result["category"], result["summary"],
        result["tags"], result["importance"], item_id,
    )


async def update_category(item_id: str, category: str) -> None:
    await _pool.execute(
        "UPDATE brain.items SET category=$1 WHERE id=$2::uuid",
        category, item_id,
    )


async def get_stats() -> dict:
    total = await _pool.fetchval("SELECT COUNT(*) FROM brain.items")
    unreviewed = await _pool.fetchval(
        "SELECT COUNT(*) FROM brain.items WHERE reviewed_at IS NULL"
    )
    by_category = await _pool.fetch(
        "SELECT category, COUNT(*) as cnt FROM brain.items GROUP BY category ORDER BY cnt DESC"
    )
    return {
        "total": total,
        "unreviewed": unreviewed,
        "by_category": [(r["category"], r["cnt"]) for r in by_category],
    }
