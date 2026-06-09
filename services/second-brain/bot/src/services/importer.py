"""
Заглушка модуля импорта. Реальный импорт — через scripts/import_history.py
"""


async def handle_import_command() -> str:
    return (
        "Для импорта истории групп используй отдельный скрипт:\n\n"
        "<code>cd services/second-brain/bot\n"
        "TELEGRAM_API_ID=xxx TELEGRAM_API_HASH=yyy \\\n"
        "python -m src.scripts.import_history</code>\n\n"
        "Получи <code>API_ID</code> и <code>API_HASH</code> на "
        "<a href='https://my.telegram.org/apps'>my.telegram.org/apps</a>"
    )
