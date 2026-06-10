#!/usr/bin/env python3
"""
Полная автоматизация загрузки переводов в Translation DocType ERPNext.

Шаги:
  1. Очистка старых переводов из файлового кэша
  2. Поиск непереведённых строк из Workspace JSON
  3. Допереводим недостающее через Claude API
  4. Заливаем всё в Translation DocType через REST API
  5. Очищаем кэш

Запуск с хоста (из /opt/factory-platform):
  ANTHROPIC_API_KEY=<key> python3 services/erp-translations/upload-translations.py

Переменные окружения:
  ANTHROPIC_API_KEY   — обязателен
  SITE_NAME           — default: erp.localhost
  ERP_API_KEY         — default: e7da9209a4e1628
  ERP_API_SECRET      — default: f10388310968603
  ERP_BASE_URL        — default: http://localhost:8080
"""

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import anthropic
import requests

# ─── Конфигурация ─────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent
CSV_FILE = SCRIPT_DIR / "ru-metal.csv"
ERP_COMPOSE = f"-f {REPO_ROOT}/services/erp/docker-compose.yml"

SITE_NAME = os.getenv("SITE_NAME", "erp.localhost")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")
if not ERP_API_KEY or not ERP_API_SECRET:
    sys.exit("ERROR: ERP_API_KEY и ERP_API_SECRET обязательны (bench execute frappe.core.doctype.user.user.generate_keys --args \"['Administrator']\")")
ERP_BASE_URL = os.getenv("ERP_BASE_URL", "http://localhost:8080")

BATCH_SIZE = 40
UPLOAD_BATCH_SIZE = 100

AUTH_HEADERS = {
    "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}",
    "Content-Type": "application/json",
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
BOM → Спецификация
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
Work in Progress → Незавершённое производство
Finished Goods → Готовая продукция
Raw Material → Сырьё и материалы
Scrap → Отходы производства
Routing → Технологический маршрут
Operation → Технологическая операция
Workstation → Рабочий центр"""


# ─── Шаг 1: Очистка файлового кэша переводов ─────────────────────────────────

def step1_clear_translations():
    print("\n[Шаг 1] Очистка старых переводов из файлового кэша...")
    result = subprocess.run(
        f"docker compose {ERP_COMPOSE} exec backend "
        f"bench --site {SITE_NAME} execute frappe.translate.clear_translations "
        f"--args \"['ru']\"",
        shell=True, capture_output=True, text=True, cwd=REPO_ROOT
    )
    if result.returncode == 0:
        print("    OK — переводы из файлового кэша удалены")
    else:
        print(f"    WARN: {result.stderr[:200]}")


# ─── Шаг 2: Загрузка текущего CSV ─────────────────────────────────────────────

def load_csv() -> dict[str, str]:
    """Загружает ru-metal.csv и возвращает словарь source→translation."""
    translations = {}
    if not CSV_FILE.exists():
        print(f"    WARN: {CSV_FILE} не найден")
        return translations
    with open(CSV_FILE, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2 and row[0].strip() and row[1].strip():
                translations[row[0].strip().strip('"')] = row[1].strip().strip('"')
    print(f"    Загружено из CSV: {len(translations)} переводов")
    return translations


# ─── Шаг 2: Поиск непереведённых строк Workspace ─────────────────────────────

def step2_get_workspace_labels(existing: dict[str, str]) -> list[str]:
    print("\n[Шаг 2] Поиск непереведённых строк из Workspace...")

    result = subprocess.run(
        f"docker compose {ERP_COMPOSE} exec backend "
        f"bench --site {SITE_NAME} mariadb "
        f"--execute \"SELECT content FROM tabWorkspace WHERE content IS NOT NULL AND content != '' LIMIT 200\"",
        shell=True, capture_output=True, text=True, cwd=REPO_ROOT
    )

    labels = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("content") or line.startswith("+-"):
            continue
        try:
            data = json.loads(line)
            extract_labels_from_obj(data, labels)
        except json.JSONDecodeError:
            # Строка может быть частью JSON — пробуем найти JSON внутри
            idx = line.find("{")
            if idx >= 0:
                try:
                    data = json.loads(line[idx:])
                    extract_labels_from_obj(data, labels)
                except Exception:
                    pass

    # Дополнительно: стандартные строки которых нет в переводах
    standard_missing = [
        "Accounts", "Stock", "Buying", "Selling", "Manufacturing", "Projects",
        "HR", "CRM", "Assets", "Quality", "Support", "Payroll", "Loan Management",
        "Healthcare", "Agriculture", "Education", "Hospitality", "Retail",
        "Home", "Getting Started", "Build", "Integrations",
        "Dashboard", "Report", "Query Report", "Script Report",
        "List", "Form", "Kanban", "Calendar", "Tree", "Map",
        "Add Widget", "Shortcuts", "My Shortcuts",
        "No. of Rows", "No. of Columns",
    ]
    for s in standard_missing:
        if s not in existing:
            labels.add(s)

    missing = [l for l in labels if l and len(l) > 1 and l not in existing]
    print(f"    Найдено меток в Workspace: {len(labels)}")
    print(f"    Отсутствует в CSV: {len(missing)}")
    return missing


def extract_labels_from_obj(obj, labels: set):
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in ("label", "title", "name") and isinstance(val, str) and val.strip():
                labels.add(val.strip())
            else:
                extract_labels_from_obj(val, labels)
    elif isinstance(obj, list):
        for item in obj:
            extract_labels_from_obj(item, labels)


# ─── Шаг 3: Допереводим недостающее ──────────────────────────────────────────

def translate_batch(client: anthropic.Anthropic, batch: list[str], idx: int) -> dict[str, str]:
    numbered = {str(i): src for i, src in enumerate(batch)}
    user_prompt = (
        f"Переведи следующие строки интерфейса ERP для завода металлоконструкций.\n"
        f"Строки для перевода (JSON):\n{json.dumps(numbered, ensure_ascii=False, indent=2)}\n\n"
        "Верни ТОЛЬКО JSON вида {\"0\": \"перевод\", ...} без пояснений."
    )
    for attempt in range(3):
        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = msg.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            return {batch[int(k)]: v for k, v in result.items() if int(k) < len(batch)}
        except Exception as e:
            print(f"    WARN батч {idx} попытка {attempt + 1}: {e}")
            time.sleep(2 ** attempt)
    return {src: src for src in batch}


def step3_translate_missing(missing: list[str], existing: dict[str, str]) -> dict[str, str]:
    if not missing:
        print("\n[Шаг 3] Нет недостающих строк — пропускаем")
        return {}
    if not ANTHROPIC_API_KEY:
        print("\n[Шаг 3] ANTHROPIC_API_KEY не задан — пропускаем перевод")
        return {}

    print(f"\n[Шаг 3] Перевод {len(missing)} недостающих строк через Claude API...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    new_translations = {}
    batches = [missing[i:i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]

    for idx, batch in enumerate(batches):
        print(f"    [{idx + 1}/{len(batches)}] {len(batch)} строк...", end=" ", flush=True)
        result = translate_batch(client, batch, idx)
        new_translations.update(result)
        print("OK")
        if idx < len(batches) - 1:
            time.sleep(0.3)

    print(f"    Переведено: {len(new_translations)} строк")
    return new_translations


# ─── Шаг 3б: Обновляем CSV ────────────────────────────────────────────────────

def update_csv(existing: dict[str, str], new_translations: dict[str, str]):
    if not new_translations:
        return
    merged = {**existing, **new_translations}
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        for source, translated in merged.items():
            if translated and translated != source:
                writer.writerow([source, translated])
    print(f"    CSV обновлён: {len(merged)} строк → {CSV_FILE}")


# ─── Шаг 4: Заливаем в Translation DocType ────────────────────────────────────

def step4_upload_to_doctype(translations: dict[str, str]):
    print(f"\n[Шаг 4] Загрузка в Translation DocType ({len(translations)} записей)...")

    # Получаем уже существующие записи чтобы не дублировать
    print("    Получаем существующие записи...")
    existing_in_db = set()
    try:
        resp = requests.get(
            f"{ERP_BASE_URL}/api/resource/Translation",
            headers=AUTH_HEADERS,
            params={"filters": json.dumps([["language", "=", "ru"]]), "limit": 10000, "fields": '["source_text"]'},
            timeout=30,
        )
        if resp.status_code == 200:
            for item in resp.json().get("data", []):
                existing_in_db.add(item.get("source_text", ""))
            print(f"    Уже в DocType: {len(existing_in_db)} записей")
    except Exception as e:
        print(f"    WARN: не удалось получить список ({e}), продолжаем...")

    to_upload = {k: v for k, v in translations.items() if k not in existing_in_db and v and v != k}
    print(f"    К загрузке: {len(to_upload)} новых записей")

    if not to_upload:
        print("    Все переводы уже в DocType")
        return 0

    items = list(to_upload.items())
    total = len(items)
    uploaded = 0
    errors = 0

    for i in range(0, total, UPLOAD_BATCH_SIZE):
        batch = items[i:i + UPLOAD_BATCH_SIZE]
        batch_num = i // UPLOAD_BATCH_SIZE + 1
        batch_total = (total + UPLOAD_BATCH_SIZE - 1) // UPLOAD_BATCH_SIZE
        print(f"    Батч {batch_num}/{batch_total} ({len(batch)} записей)...", end=" ", flush=True)

        batch_ok = 0
        for source, translated in batch:
            try:
                resp = requests.post(
                    f"{ERP_BASE_URL}/api/resource/Translation",
                    headers=AUTH_HEADERS,
                    json={"language": "ru", "source_text": source, "translated_text": translated},
                    timeout=10,
                )
                if resp.status_code in (200, 201):
                    batch_ok += 1
                else:
                    errors += 1
            except Exception:
                errors += 1
            time.sleep(0.05)  # небольшая пауза чтобы не перегружать

        uploaded += batch_ok
        print(f"OK ({batch_ok}/{len(batch)})")

    print(f"\n    Итого загружено: {uploaded} / {total}")
    if errors:
        print(f"    Ошибок: {errors}")
    return uploaded


# ─── Шаг 5: Очистка кэша ──────────────────────────────────────────────────────

def step5_clear_cache():
    print("\n[Шаг 5] Очистка кэша ERPNext...")
    result = subprocess.run(
        f"docker compose {ERP_COMPOSE} exec backend bench --site {SITE_NAME} clear-cache",
        shell=True, capture_output=True, text=True, cwd=REPO_ROOT
    )
    if result.returncode == 0:
        print("    OK")
    else:
        print(f"    WARN: {result.stderr[:200]}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("ERPNext Translation Uploader")
    print("=" * 60)

    step1_clear_translations()

    existing = load_csv()
    if not existing:
        print("ERROR: ru-metal.csv пустой или не найден")
        sys.exit(1)

    missing = step2_get_workspace_labels(existing)
    new_translations = step3_translate_missing(missing, existing)

    if new_translations:
        update_csv(existing, new_translations)
        all_translations = {**existing, **new_translations}
    else:
        all_translations = existing

    uploaded = step4_upload_to_doctype(all_translations)
    step5_clear_cache()

    print("\n" + "=" * 60)
    print(f"✅ Готово!")
    print(f"   Всего переводов в CSV: {len(all_translations)}")
    print(f"   Залито в Translation DocType: {uploaded}")
    print(f"   Следующий шаг: открыть Построение → Перевод")
    print("=" * 60)

    return uploaded


if __name__ == "__main__":
    main()
