"""
Загружает фото из Telegram Desktop экспорта в Telegram и обновляет file_id в БД.

Запуск:
    python3 upload_photos.py <path_to_result.json> [<path_to_result2.json> ...]

Пример:
    python3 upload_photos.py ~/Downloads/Завод/result.json ~/Downloads/Здоровье/result.json
"""
import asyncio
import json
import os
import sys
import logging
from pathlib import Path

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_USER_ID = int(os.environ.get("OWNER_USER_ID", "0"))
DB_DSN = os.environ.get("DB_DSN", "postgresql://brain_user:password@brain-db:5432/second_brain")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def send_photo(client: httpx.AsyncClient, photo_path: Path) -> str | None:
    """Загружает фото в Telegram, возвращает file_id."""
    if not photo_path.exists():
        return None
    try:
        with open(photo_path, "rb") as f:
            resp = await client.post(
                f"{TG_API}/sendPhoto",
                data={"chat_id": OWNER_USER_ID},
                files={"photo": (photo_path.name, f, "image/jpeg")},
                timeout=30,
            )
        data = resp.json()
        if not data.get("ok"):
            logger.warning("sendPhoto failed: %s", data)
            return None
        sizes = data["result"]["photo"]
        return sizes[-1]["file_id"]
    except Exception as e:
        logger.warning("Upload error %s: %s", photo_path, e)
        return None


async def delete_uploaded_message(client: httpx.AsyncClient, message_id: int) -> None:
    """Удаляет техническое сообщение из чата."""
    try:
        await client.post(
            f"{TG_API}/deleteMessage",
            json={"chat_id": OWNER_USER_ID, "message_id": message_id},
            timeout=10,
        )
    except Exception:
        pass


async def process_file(json_path: str, pool: asyncpg.Pool, client: httpx.AsyncClient) -> int:
    path = Path(json_path)
    export_dir = path.parent

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    messages = [m for m in data.get("messages", []) if m.get("type") == "message"]
    photo_msgs = [m for m in messages if m.get("photo") or m.get("media_type") == "photo"]
    logger.info("'%s': %d сообщений с фото", data.get("name", json_path), len(photo_msgs))

    updated = 0
    for msg in photo_msgs:
        source_id = str(msg.get("id", ""))
        photo_rel = msg.get("photo", "")

        # Проверяем что запись есть в БД и media_url пустой
        row = await pool.fetchrow(
            "SELECT id FROM brain.items WHERE source_type='tg_export' AND source_id=$1 AND media_url IS NULL",
            source_id,
        )
        if not row:
            continue

        if not photo_rel:
            continue

        photo_path = export_dir / photo_rel
        file_id = await send_photo(client, photo_path)
        if not file_id:
            logger.warning("Не удалось загрузить: %s", photo_path)
            continue

        await pool.execute(
            "UPDATE brain.items SET media_url=$1 WHERE id=$2",
            file_id, row["id"],
        )
        updated += 1
        if updated % 10 == 0:
            logger.info("  Загружено %d фото...", updated)
        await asyncio.sleep(0.3)  # антифлуд

    logger.info("  Обновлено записей: %d", updated)
    return updated


async def main(paths: list[str]) -> None:
    if not BOT_TOKEN or not OWNER_USER_ID:
        print("Нужны переменные: TELEGRAM_BOT_TOKEN, OWNER_USER_ID, DB_DSN")
        sys.exit(1)

    pool = await asyncpg.create_pool(DB_DSN, min_size=2, max_size=5)
    async with httpx.AsyncClient() as client:
        total = 0
        for p in paths:
            total += await process_file(p, pool, client)

    await pool.close()
    logger.info("Готово. Всего обновлено: %d", total)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python3 upload_photos.py <result.json> [...]")
        sys.exit(1)
    asyncio.run(main(sys.argv[1:]))
