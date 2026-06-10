#!/usr/bin/env python3
"""
Генератор кастомной русской локализации ERPNext для металлопроизводства.

Запускать внутри контейнера backend:
  docker compose -f services/erp/docker-compose.yml exec backend \
    python /path/to/generate-translations.py

Или с хоста (если смонтирован):
  docker compose -f services/erp/docker-compose.yml exec backend \
    python /home/frappe/frappe-bench/sites/erp-translations/generate-translations.py

Переменные окружения:
  ANTHROPIC_API_KEY  — обязателен
  SITE_NAME          — default: erp.localhost
"""

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import anthropic

# ─── Конфигурация ─────────────────────────────────────────────────────────────

SITE_NAME = os.getenv("SITE_NAME", "erp.localhost")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    sys.exit("ERROR: ANTHROPIC_API_KEY не задан в переменных окружения")

BATCH_SIZE = 40
OUTPUT_CSV = Path(__file__).parent / "ru-metal.csv"
PROGRESS_FILE = Path(__file__).parent / "progress.json"

ANCHOR_DICT = {
    "Item": "Номенклатура",
    "Work Order": "Производственный заказ",
    "Bill of Materials": "Спецификация",
    "BOM": "Спецификация",
    "Quotation": "Коммерческое предложение",
    "Submit": "Провести",
    "Cancel": "Аннулировать",
    "Warehouse": "Склад",
    "Purchase Order": "Заказ поставщику",
    "Sales Order": "Заказ покупателя",
    "Lead": "Лид",
    "Customer": "Покупатель",
    "Supplier": "Поставщик",
    "Stock": "Запасы",
    "Work in Progress": "Незавершённое производство",
    "Finished Goods": "Готовая продукция",
    "Raw Material": "Сырьё и материалы",
    "Scrap": "Отходы производства",
    "Routing": "Технологический маршрут",
    "Operation": "Технологическая операция",
    "Workstation": "Рабочий центр",
}

SYSTEM_PROMPT = """Ты — эксперт по локализации ERP-систем для российских промышленных предприятий.
Контекст: завод металлоконструкций, b2b, производство на заказ.

ПРАВИЛА:
1. Используй профессиональную терминологию металлопроизводства
2. Никогда не переводи: {{name}}, {0}, %s, <теги>, технические коды
3. Падежи: названия полей — именительный, кнопки действий — инфинитив или повелительное
4. Консистентность: используй словарь якорей из контекста
5. Отвечай строго JSON: {"0": "перевод", "1": "перевод", ...}

СЛОВАРЬ ЯКОРЕЙ (обязателен к соблюдению):
Item → Номенклатура
Work Order → Производственный заказ
Bill of Materials → Спецификация
Quotation → Коммерческое предложение
Submit → Провести
Cancel → Аннулировать
Warehouse → Склад
Purchase Order → Заказ поставщику
Sales Order → Заказ покупателя
Lead → Лид
Customer → Покупатель
Supplier → Поставщик
Stock → Запасы
BOM → Спецификация
Work in Progress → Незавершённое производство
Finished Goods → Готовая продукция
Raw Material → Сырьё и материалы
Scrap → Отходы производства
Routing → Технологический маршрут
Operation → Технологическая операция
Workstation → Рабочий центр"""


# ─── Шаг 1: Извлечение строк через bench ──────────────────────────────────────

def build_message_files():
    print(f"[1/3] Генерация message-файлов для сайта {SITE_NAME}...")
    result = subprocess.run(
        ["bench", "--site", SITE_NAME, "build-message-files"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"WARN: build-message-files завершился с кодом {result.returncode}")
        print(result.stderr[:500])
    else:
        print("    OK")


def find_messages_file():
    """Ищет сгенерированный messages.json в стандартных местах Frappe."""
    candidates = [
        Path(f"/home/frappe/frappe-bench/sites/{SITE_NAME}/messages.json"),
        Path(f"/home/frappe/frappe-bench/apps/frappe/frappe/locale/messages.json"),
    ]
    for p in candidates:
        if p.exists():
            return p
    # Fallback: найти в apps
    found = list(Path("/home/frappe/frappe-bench/apps").rglob("messages.json"))
    if found:
        return found[0]
    return None


def load_strings_from_messages(path: Path) -> list[dict]:
    """Читает messages.json и возвращает список {source, context}."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    strings = []
    if isinstance(data, dict):
        for ctx, entries in data.items():
            if isinstance(entries, list):
                for entry in entries:
                    src = entry if isinstance(entry, str) else entry.get("source", "")
                    if src:
                        strings.append({"source": src, "context": ctx})
            elif isinstance(entries, str):
                strings.append({"source": entries, "context": ctx})
    elif isinstance(data, list):
        for entry in data:
            if isinstance(entry, str):
                strings.append({"source": entry, "context": ""})
            elif isinstance(entry, dict):
                strings.append({
                    "source": entry.get("source", entry.get("msgid", "")),
                    "context": entry.get("context", entry.get("doctype", "")),
                })

    # Убираем пустые и уже кириллические строки
    filtered = [
        s for s in strings
        if s["source"].strip()
        and not all(c in "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ .,!?" for c in s["source"])
    ]
    return filtered


# ─── Шаг 2: Группировка по контексту ──────────────────────────────────────────

def group_by_context(strings: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for s in strings:
        ctx = s["context"] or "general"
        groups.setdefault(ctx, []).append(s)
    return groups


def build_anchor_context(batch: list[dict]) -> str:
    relevant = {}
    for item in batch:
        for en_term, ru_term in ANCHOR_DICT.items():
            if en_term.lower() in item["source"].lower():
                relevant[en_term] = ru_term
    if not relevant:
        return ""
    lines = "\n".join(f"{k} → {v}" for k, v in relevant.items())
    return f"\nРелевантные якоря для этого батча:\n{lines}\n"


# ─── Шаг 3: Перевод через Claude API ──────────────────────────────────────────

def translate_batch(client: anthropic.Anthropic, batch: list[dict], batch_index: int) -> dict[str, str]:
    anchor_hint = build_anchor_context(batch)
    numbered = {str(i): item["source"] for i, item in enumerate(batch)}
    user_prompt = (
        f"Переведи следующие строки интерфейса ERP для завода металлоконструкций.{anchor_hint}\n"
        f"Строки для перевода (JSON):\n{json.dumps(numbered, ensure_ascii=False, indent=2)}\n\n"
        "Верни ТОЛЬКО JSON вида {\"0\": \"перевод\", \"1\": \"перевод\", ...} без пояснений."
    )

    for attempt in range(3):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = message.content[0].text.strip()
            # Вырезаем JSON если обёрнут в markdown
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            translations = json.loads(raw)
            result = {}
            for i, item in enumerate(batch):
                result[item["source"]] = translations.get(str(i), item["source"])
            return result
        except (json.JSONDecodeError, KeyError, anthropic.APIError) as e:
            print(f"    WARN батч {batch_index}, попытка {attempt + 1}: {e}")
            time.sleep(2 ** attempt)

    # Если все попытки провалились — возвращаем оригиналы
    return {item["source"]: item["source"] for item in batch}


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"completed_batches": [], "translations": {}}


def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ─── Запись CSV ───────────────────────────────────────────────────────────────

def write_csv(translations: dict[str, str]):
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source_text", "translated_text", "context", "language"])
        for source, translated in translations.items():
            writer.writerow([source, translated, "", "ru"])
    print(f"\n[✓] CSV сохранён: {OUTPUT_CSV} ({len(translations)} строк)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    build_message_files()

    msg_file = find_messages_file()
    if not msg_file:
        sys.exit("ERROR: messages.json не найден. Убедитесь что bench build-message-files отработал.")

    print(f"[2/3] Загрузка строк из {msg_file}...")
    strings = load_strings_from_messages(msg_file)
    print(f"    Найдено строк для перевода: {len(strings)}")

    progress = load_progress()
    translations = progress["translations"]
    completed = set(progress["completed_batches"])

    untranslated = [s for s in strings if s["source"] not in translations]
    batches = [untranslated[i:i + BATCH_SIZE] for i in range(0, len(untranslated), BATCH_SIZE)]

    print(f"[3/3] Перевод через Claude API ({len(batches)} батчей по {BATCH_SIZE})...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for idx, batch in enumerate(batches):
        batch_key = f"batch_{idx}"
        if batch_key in completed:
            print(f"    Батч {idx + 1}/{len(batches)} — пропущен (уже переведён)")
            continue

        print(f"    Батч {idx + 1}/{len(batches)} ({len(batch)} строк)...", end=" ", flush=True)
        result = translate_batch(client, batch, idx)
        translations.update(result)
        completed.add(batch_key)

        progress["completed_batches"] = list(completed)
        progress["translations"] = translations
        save_progress(progress)
        print("OK")

        # Пауза чтобы не превысить rate limit
        if idx < len(batches) - 1:
            time.sleep(0.5)

    write_csv(translations)

    # Удаляем файл прогресса после успешного завершения
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        print("[✓] progress.json удалён")


if __name__ == "__main__":
    main()
