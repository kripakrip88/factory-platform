#!/usr/bin/env python3
"""
Генератор улучшенных переводов ERPNext v16 для завода металлоконструкций.

Схема работы:
1. Загружает строки из существующего progress.json (или из контейнера ERPNext)
2. Применяет заводской глоссарий без API-вызовов
3. Остальные строки переводит через Claude Haiku API батчами по 40
4. Сохраняет прогресс в progress-factory.json
5. Экспортирует итоговый CSV совместимый с upload-translations.py

Использование:
    ANTHROPIC_API_KEY=<key> python3 generate-factory-translations.py
"""

import anthropic
import csv
import json
import os
import logging
import subprocess
from datetime import date
from pathlib import Path
from typing import Optional

from factory_glossary import FACTORY_GLOSSARY

# ─── Конфигурация ────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
PROGRESS_FILE = SCRIPT_DIR / "progress-factory.json"
SOURCE_PROGRESS = SCRIPT_DIR / "progress.json"
OUTPUT_CSV = SCRIPT_DIR / f"ru-factory-{date.today()}.csv"
BATCH_SIZE = 40
MODEL = "claude-haiku-4-5-20251001"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — эксперт по локализации ERP-систем для российских промышленных предприятий.
Контекст: Завод металлоконструкций (изготовление профильного металлопроката,
листового металла, сварных конструкций). ERP — ERPNext v16.

ПРАВИЛА ПЕРЕВОДА:
1. Используй профессиональную терминологию российского бухгалтерского учёта и производства.
2. Submit → "Провести" (бухгалтерский термин), НЕ "Отправить"
3. Item → "Номенклатура" (ERP-термин), НЕ "Элемент" или "Товар"
4. Work Order → "Производственный заказ", НЕ "Рабочий заказ"
5. BOM → "Спецификация"
6. В кнопках используй глагол в инфинитиве ("Провести", "Сохранить")
7. В заголовках документов используй существительное в им. падеже ("Заказ покупателя")
8. НЕ переводи: {0}, {1}, %s, %(var)s, {{ var }}, HTML-теги, технические идентификаторы
9. Если строка — технический код, верни без изменений
10. Не добавляй кавычки вокруг перевода

Верни JSON объект где ключи — индексы (числа), значения — переводы.
Только JSON, без markdown, без пояснений."""


# ─── Загрузка строк ───────────────────────────────────────────────────────────

def load_strings_from_progress() -> dict:
    """Загружает строки из progress.json или ru-metal.csv как источник."""
    if SOURCE_PROGRESS.exists():
        with open(SOURCE_PROGRESS, encoding="utf-8") as f:
            return json.load(f)

    # Фолбэк: читаем исходные строки из ru-metal.csv
    ru_metal = SCRIPT_DIR / "ru-metal.csv"
    if ru_metal.exists():
        log.info("progress.json не найден — читаем строки из ru-metal.csv")
        result = {}
        with open(ru_metal, encoding="utf-8") as f:
            for row in csv.reader(f):
                if row and len(row) >= 1:
                    result[row[0]] = row[1] if len(row) >= 2 else ""
        log.info(f"Загружено {len(result)} строк из ru-metal.csv")
        return result

    log.warning("Ни progress.json ни ru-metal.csv не найдены")
    return {}


def extract_strings_from_container() -> Optional[list]:
    """Пытается извлечь строки из Docker-контейнера ERPNext."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=erp.*backend", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10
        )
        container = result.stdout.strip().split("\n")[0]
        if not container:
            return None

        log.info(f"Контейнер: {container}")
        subprocess.run(
            ["docker", "exec", container, "bench", "--site", "erp.localhost", "build-message-files"],
            capture_output=True, timeout=120
        )

        cp = subprocess.run(
            ["docker", "cp",
             f"{container}:/home/frappe/frappe-bench/apps/erpnext/erpnext/translations/ru.csv",
             "/tmp/erpnext-ru.csv"],
            capture_output=True, timeout=30
        )
        if cp.returncode != 0:
            return None

        strings = []
        with open("/tmp/erpnext-ru.csv", encoding="utf-8") as f:
            for row in csv.reader(f):
                if row:
                    strings.append(row[0])
        log.info(f"Извлечено {len(strings)} строк из контейнера")
        return strings
    except Exception as e:
        log.warning(f"Не удалось извлечь из контейнера: {e}")
        return None


# ─── Прогресс ────────────────────────────────────────────────────────────────

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress: dict[str, str]) -> None:
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ─── API-перевод ─────────────────────────────────────────────────────────────

def translate_batch(client: anthropic.Anthropic, batch: list) -> dict:
    payload = {str(i): s for i, s in enumerate(batch)}
    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Переведи строки на русский язык:\n{json.dumps(payload, ensure_ascii=False)}"
        }]
    )
    text = message.content[0].text.strip()
    # Убираем markdown-блок если есть
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def translate_via_api(strings: list[str], progress: dict[str, str]) -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY не задан")
        return 0

    client = anthropic.Anthropic(api_key=api_key)
    translated = 0

    for i in range(0, len(strings), BATCH_SIZE):
        batch = strings[i:i + BATCH_SIZE]
        try:
            results = translate_batch(client, batch)
            for idx, translation in results.items():
                src = batch[int(idx)]
                progress[src] = translation
            save_progress(progress)
            translated += len(results)
            log.info(f"API: {i + len(batch)}/{len(strings)} строк ({translated} переведено)")
        except Exception as e:
            log.error(f"Ошибка батча {i}: {e}")

    return translated


# ─── Экспорт CSV ─────────────────────────────────────────────────────────────

def export_csv(progress: dict[str, str]) -> None:
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        for source, translation in progress.items():
            if source and translation and source != translation:
                writer.writerow([source, translation])
    log.info(f"CSV сохранён: {OUTPUT_CSV} ({len(progress)} строк)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Генерация заводских переводов ERPNext v16 ===")

    # 1. Загрузить источник строк
    container_strings = extract_strings_from_container()
    if container_strings:
        all_strings = container_strings
    else:
        log.info("Фолбэк: используем ключи из progress.json")
        all_strings = list(load_strings_from_progress().keys())

    log.info(f"Всего строк для обработки: {len(all_strings)}")

    # 2. Загрузить прогресс
    progress = load_progress()
    log.info(f"Уже переведено (из прогресса): {len(progress)}")

    # 3. Применить глоссарий
    glossary_count = 0
    need_api = []

    for s in all_strings:
        if s in progress:
            continue
        if s in FACTORY_GLOSSARY:
            progress[s] = FACTORY_GLOSSARY[s]
            glossary_count += 1
        else:
            need_api.append(s)

    # Также добавить все термины глоссария которых нет в источнике
    for src, tgt in FACTORY_GLOSSARY.items():
        if src not in progress:
            progress[src] = tgt
            glossary_count += 1

    save_progress(progress)
    log.info(f"Из глоссария: {glossary_count} строк")
    log.info(f"Требуют API: {len(need_api)} строк")

    # 4. Перевести через API
    if need_api:
        api_count = translate_via_api(need_api, progress)
        log.info(f"Переведено через API: {api_count}")
    else:
        log.info("API не требуется — все строки покрыты глоссарием или прогрессом")

    # 5. Экспортировать CSV
    export_csv(progress)

    # 6. Статистика
    log.info("=== Итог ===")
    log.info(f"  Всего в CSV: {len(progress)}")
    log.info(f"  Из глоссария: {glossary_count}")
    log.info(f"  Через API: {len(need_api)}")
    log.info(f"  Выходной файл: {OUTPUT_CSV}")
    log.info("")
    log.info("Следующий шаг: залить CSV через upload-translations.py")
    log.info("  ERP_API_KEY=<key> ERP_API_SECRET=<secret> python3 upload-translations.py")


if __name__ == "__main__":
    main()
