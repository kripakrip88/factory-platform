"""
Разовый batch-прогон классификации писем (холостой режим).

Берёт Communication-письма ящика (≈100), у которых ещё нет классификации,
прогоняет текст (тема+тело, БЕЗ вложений) через Claude по промпту v1 и пишет
результат в Custom Fields карточки письма:
  custom_claude_classification, custom_claude_reason.

НИЧЕГО не создаёт (ни лидов, ни ответов), вложения не трогает.
Резюмируемость: результат пишется в карточку сразу → повторный запуск
продолжит с непроклассифицированных.

ЗАПУСК (на сервере, ключ Claude — через -e, в git/чат не попадает):
  1) скопировать этот файл в контейнер как frappe-модуль:
     docker cp classify_batch.py erp-backend-1:/home/frappe/frappe-bench/apps/frappe/frappe/_classify_batch.py
  2) запустить с ключом в окружении:
     docker exec -e ANTHROPIC_API_KEY='sk-ant-...' -e EMAIL_ACCOUNT='PMK Park входящие (тест)' \
       erp-backend-1 bash -c 'cd /home/frappe/frappe-bench && bench --site erp.localhost execute frappe._classify_batch.execute'

ПРИВАТНОСТЬ: тела писем уходят в Anthropic API (требование задачи). В лог/файлы
тела не пишутся — только счётчики по полкам.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from collections import Counter

import frappe

SHELVES = ["Новая заявка", "Вопрос по заказу", "Поставщик", "Спам", "Прочее"]

SYSTEM = (
    "Ты классифицируешь входящие письма завода металлоконструкций (изготовление "
    "на заказ: просчёт → счёт → производство). Разложи письмо строго в ОДНУ из 5 "
    "полок и дай короткое обоснование.\n\n"
    "Полки:\n"
    "1. Новая заявка — клиент просит просчитать/выставить счёт/спрашивает о "
    "возможности изготовления (запрос КП, цены, список позиций на просчёт). Из "
    "этого родится лид.\n"
    "2. Вопрос по заказу — про УЖЕ идущий заказ («что с заказом», «когда готово», "
    "ссылка на номер счёта/спецификации). НЕ новая заявка, лид не нужен.\n"
    "3. Поставщик — входящие ОТ поставщиков (предлагают НАМ трубы/металл/прайсы/"
    "рекламу поставщика), а не просят изготовить.\n"
    "4. Спам — массовая реклама не по делу, нерелевантные рассылки, маркетинг.\n"
    "5. Прочее — служебное, ответы в переписке не про заявки, бухгалтерия, "
    "неопределённое.\n\n"
    "Правила: различай «Новая заявка» и «Вопрос по заказу». Игнорируй рекламные "
    "вставки внутри тела (капс, «низкие цены», баннеры-подписи) — они не делают "
    "письмо спамом, если суть — реальный запрос. Вложения ты НЕ видишь; "
    "классифицируй по теме+тексту; отсутствие деталей (они во вложении) не "
    "понижает «Новую заявку» до «Прочего», если виден запрос на просчёт/счёт. Если "
    "не уверен — «Прочее» с пометкой неуверенности.\n\n"
    'Ответ строго JSON: {"shelf": "<одна из 5 полок точь-в-точь>", "reason": "<1-2 фразы>"}'
)

# --- пейсер токенов (под лимит организации, как в email-analysis) ---
_BUDGET = 42000
_log = []

def _pace(est):
    now = time.time()
    while _log and now - _log[0][0] > 60:
        _log.pop(0)
    used = sum(t for _, t in _log)
    if used + est > _BUDGET and _log:
        wait = 60 - (now - _log[0][0]) + 1
        if wait > 0:
            print(f"  [пейсер] {used} ток./мин — пауза {wait:.0f}с", file=sys.stderr, flush=True)
            time.sleep(wait)
    _log.append((time.time(), est))


def call_claude(api_key, model, user, max_tokens=300):
    _pace((len(SYSTEM) + len(user)) // 4 + max_tokens)
    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "system": SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
                return "".join(b.get("text", "") for b in data.get("content", []))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 5:
                print("  [429] пауза 60с", file=sys.stderr, flush=True)
                _log.clear(); time.sleep(62); continue
            if e.code in (500, 503, 529) and attempt < 5:
                time.sleep(2 ** attempt * 3); continue
            raise
        except Exception:
            if attempt < 5:
                time.sleep(2 ** attempt * 3); continue
            raise


def strip_html(html):
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html or "")
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def parse_result(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        o = json.loads(m.group(0))
    except Exception:
        return None
    shelf = o.get("shelf", "")
    if shelf not in SHELVES:
        # нормализация: ищем ближайшую полку по подстроке
        shelf = next((s for s in SHELVES if s.lower() in str(shelf).lower()), "Прочее")
    return {"shelf": shelf, "reason": (o.get("reason") or "")[:500]}


def execute():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    account = os.environ.get("EMAIL_ACCOUNT", "PMK Park входящие (тест)")
    if not api_key:
        print("ОШИБКА: нет ANTHROPIC_API_KEY в окружении. Запусти с -e ANTHROPIC_API_KEY=...",
              file=sys.stderr)
        return

    comms = frappe.get_all(
        "Communication",
        filters={"email_account": account,
                 "communication_type": "Communication",
                 "sent_or_received": "Received"},
        or_filters=[["custom_claude_classification", "is", "not set"],
                    ["custom_claude_classification", "=", ""]],
        fields=["name", "subject", "content"], limit_page_length=0)

    print(f"К классификации: {len(comms)} писем (ящик: {account})", file=sys.stderr, flush=True)
    counts = Counter()
    done = 0
    for c in comms:
        subject = c.subject or ""
        body = strip_html(c.content)[:2500]
        user = f"Тема: {subject}\n\nТекст:\n{body}"
        try:
            res = parse_result(call_claude(api_key, model, user))
        except Exception as ex:
            print(f"  ОСТАНОВ (API): {str(ex)[:120]}", file=sys.stderr, flush=True)
            break
        if not res:
            res = {"shelf": "Прочее", "reason": "не удалось распарсить ответ"}
        frappe.db.set_value("Communication", c.name, {
            "custom_claude_classification": res["shelf"],
            "custom_claude_reason": res["reason"],
        }, update_modified=False)
        frappe.db.commit()
        counts[res["shelf"]] += 1
        done += 1
        if done % 10 == 0:
            print(f"  обработано {done}/{len(comms)}", file=sys.stderr, flush=True)

    print(f"\nГотово: {done} писем. Распределение по полкам:", file=sys.stderr, flush=True)
    for shelf in SHELVES:
        print(f"  {shelf}: {counts.get(shelf, 0)}", file=sys.stderr, flush=True)
