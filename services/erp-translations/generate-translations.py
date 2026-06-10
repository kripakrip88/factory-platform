#!/usr/bin/env python3
"""
Генератор кастомной русской локализации ERPNext для металлопроизводства.

Запускать внутри контейнера backend:
  cd /home/frappe/frappe-bench
  ANTHROPIC_API_KEY=<key> python generate-translations.py

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
    sys.exit("ERROR: ANTHROPIC_API_KEY не задан")

BATCH_SIZE = 40
SCRIPT_DIR = Path(__file__).parent
OUTPUT_CSV = SCRIPT_DIR / "ru-metal.csv"
PROGRESS_FILE = SCRIPT_DIR / "progress.json"
UNTRANSLATED_FILE = SCRIPT_DIR / "untranslated.txt"

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


# ─── Шаг 1: Получить непереведённые строки ────────────────────────────────────

def get_untranslated_strings() -> list[str]:
    print(f"[1/3] Получение непереведённых строк (bench get-untranslated ru)...")
    result = subprocess.run(
        ["bench", "--site", SITE_NAME, "get-untranslated", "ru", str(UNTRANSLATED_FILE), "--all"],
        capture_output=True,
        text=True,
        cwd="/home/frappe/frappe-bench",
    )
    if result.returncode != 0:
        print(f"WARN: {result.stderr[:300]}")

    if not UNTRANSLATED_FILE.exists():
        print("    Нет непереведённых строк (или файл не создан). Попробуем --all из существующих CSV...")
        return get_all_strings_from_csv()

    with open(UNTRANSLATED_FILE, encoding="utf-8") as f:
        strings = [line.strip() for line in f if line.strip()]

    print(f"    Непереведённых строк: {len(strings)}")
    return strings


def get_all_strings_from_csv() -> list[str]:
    """
    Собирает все строки из стандартных ru.csv ERPNext+Frappe и
    возвращает те, что имеют плохой/машинный перевод (совпадают с source
    или выглядят как не-русские).
    """
    import re
    ru_pattern = re.compile(r'[а-яёА-ЯЁ]')
    strings = []
    csv_paths = [
        Path("/home/frappe/frappe-bench/apps/frappe/frappe/translations/ru.csv"),
        Path("/home/frappe/frappe-bench/apps/erpnext/erpnext/translations/ru.csv"),
    ]
    for p in csv_paths:
        if not p.exists():
            continue
        with open(p, encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 1:
                    source = row[0].strip().strip('"')
                    translation = row[1].strip().strip('"') if len(row) > 1 else ""
                    # Берём строки без перевода или совпадающие с источником
                    if not translation or translation == source or not ru_pattern.search(translation):
                        if source and len(source) > 1:
                            strings.append(source)

    print(f"    Строк для улучшенного перевода: {len(strings)}")
    return list(dict.fromkeys(strings))  # dedup


# ─── Шаг 2: Перевод через Claude API ──────────────────────────────────────────

def build_anchor_hint(batch: list[str]) -> str:
    relevant = {}
    for src in batch:
        for en_term, ru_term in ANCHOR_DICT.items():
            if en_term.lower() in src.lower():
                relevant[en_term] = ru_term
    if not relevant:
        return ""
    lines = "\n".join(f"{k} → {v}" for k, v in relevant.items())
    return f"\nРелевантные якоря для этого батча:\n{lines}\n"


def translate_batch(client: anthropic.Anthropic, batch: list[str], batch_index: int) -> dict[str, str]:
    anchor_hint = build_anchor_hint(batch)
    numbered = {str(i): src for i, src in enumerate(batch)}
    user_prompt = (
        f"Переведи следующие строки интерфейса ERP для завода металлоконструкций.{anchor_hint}\n"
        f"Строки для перевода (JSON):\n{json.dumps(numbered, ensure_ascii=False, indent=2)}\n\n"
        "Верни ТОЛЬКО JSON вида {\"0\": \"перевод\", \"1\": \"перевод\", ...} без пояснений."
    )

    for attempt in range(3):
        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",  # не менять — sonnet на этом ключе недоступен
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = message.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            translations = json.loads(raw)
            result = {}
            for i, src in enumerate(batch):
                result[src] = translations.get(str(i), src)
            return result
        except (json.JSONDecodeError, KeyError, anthropic.APIError) as e:
            print(f"    WARN батч {batch_index}, попытка {attempt + 1}: {e}")
            time.sleep(2 ** attempt)

    return {src: src for src in batch}


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"completed_batches": [], "translations": {}}


def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ─── Шаг 3: Запись CSV для import-translations ────────────────────────────────

def write_csv(translations: dict[str, str]):
    """
    Формат Frappe import-translations: source,translation[,context]
    """
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        for source, translated in translations.items():
            if translated and translated != source:
                writer.writerow([source, translated])
    print(f"\n[✓] CSV сохранён: {OUTPUT_CSV} ({len(translations)} строк)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    strings = get_untranslated_strings()
    if not strings:
        print("Нет строк для перевода. Возможно все уже переведены.")
        return

    progress = load_progress()
    translations = progress["translations"]
    completed = set(progress["completed_batches"])

    untranslated = [s for s in strings if s not in translations]
    batches = [untranslated[i:i + BATCH_SIZE] for i in range(0, len(untranslated), BATCH_SIZE)]

    print(f"[2/3] Перевод через Claude API...")
    print(f"    Осталось: {len(untranslated)} строк / {len(batches)} батчей")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for idx, batch in enumerate(batches):
        batch_key = f"batch_{idx}"
        if batch_key in completed:
            print(f"    [{idx + 1}/{len(batches)}] пропущен (кэш)")
            continue

        print(f"    [{idx + 1}/{len(batches)}] {len(batch)} строк...", end=" ", flush=True)
        result = translate_batch(client, batch, idx)
        translations.update(result)
        completed.add(batch_key)

        progress["completed_batches"] = list(completed)
        progress["translations"] = translations
        save_progress(progress)
        print("OK")

        if idx < len(batches) - 1:
            time.sleep(0.3)

    print(f"[3/3] Запись CSV...")
    write_csv(translations)

    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
    if UNTRANSLATED_FILE.exists():
        UNTRANSLATED_FILE.unlink()

    print("\nГотово! Следующий шаг:")
    print(f"  bench --site {SITE_NAME} import-translations ru {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
