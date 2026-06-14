"""
Прогон классификатора ПРОМПТОМ v2 — только по УЖЕ ОЦЕНЁННЫМ письмам, в отдельные
поля (custom_claude_classification_v2 / custom_claude_reason_v2). v1-ответы и
оценки менеджера НЕ трогаются.

Цель: честное сравнение v1 vs v2 на тех же письмах, где есть эталон (оценка
менеджера). Ошибочные письма (verdict=Неверно) идут ПЕРВЫМИ.

ЗАПУСК (на сервере, ключ Claude через -e):
  docker cp classify_batch_v2.py erp-backend-1:/home/frappe/frappe-bench/apps/frappe/frappe/_classify_v2.py
  docker exec -e ANTHROPIC_API_KEY='sk-ant-...' -e EMAIL_ACCOUNT='PMK Park входящие (тест)' \
    erp-backend-1 bash -c 'cd /home/frappe/frappe-bench && bench --site erp.localhost execute frappe._classify_v2.execute'
  docker exec erp-backend-1 rm -f /home/frappe/frappe-bench/apps/frappe/frappe/_classify_v2.py
"""

import json, os, re, sys, time, urllib.request, urllib.error
from collections import Counter
import frappe

SHELVES = ["Новая заявка", "Вопрос по заказу", "Поставщик", "Спам", "Прочее"]

# --- ПРОМПТ v2 (синхронно с prompt-v2.md) ---
SYSTEM = (
    "Ты классифицируешь входящие письма завода металлоконструкций (изготовление "
    "на заказ: просчёт → счёт → производство). Сначала определи РОЛЬ отправителя: "
    "это КЛИЕНТ (хочет, чтобы МЫ изготовили) или ПОСТАВЩИК/сторонний (предлагает "
    "НАМ товар/услугу)? Разложи письмо строго в ОДНУ из 5 полок.\n\n"
    "1. Новая заявка — КЛИЕНТ просит просчитать/выставить счёт/спрашивает о "
    "возможности изготовления (запрос КП, цены, позиции на просчёт).\n"
    "2. Вопрос по заказу — КЛИЕНТ про СВОЙ уже идущий заказ у нас («когда готово», "
    "ссылка на свой счёт/спецификацию). Только от клиента про его заказ.\n"
    "3. Поставщик — письмо ОТ поставщика: предлагает НАМ металл/трубы/прокат/"
    "метизы/комплектующие/услуги для производства («наличие», «прайс», «остатки», "
    "приглашение присылать ЕМУ заявки на закупку).\n"
    "4. Спам — массовая реклама/рассылки НЕ по нашему производству (реклама, SEO, "
    "банки, обучение, маркетинг, маркетплейсы), нерелевантные предложения.\n"
    "5. Прочее — служебное, ответы в переписке не про заявки, бухгалтерия, "
    "неопределённое.\n\n"
    "Жёсткие разграничения:\n"
    "- Поставщик vs Вопрос по заказу: письмо ОТ поставщика (наличие/прайс, "
    "приглашает присылать ему заявки) — это Поставщик, даже если есть слово "
    "«заявка»/«заказ». «Вопрос по заказу» — только клиент про СВОЙ заказ у нас.\n"
    "- Поставщик vs Спам: Поставщик — только профильный (металл/трубы/прокат/"
    "метизы/услуги для металлопроизводства). Нерелевантная реклама (продвижение, "
    "IT, банки, обучение, маркетинг) — Спам, даже если формально «что-то "
    "предлагают».\n"
    "- Игнорируй рекламные вставки внутри тела, если суть — реальный запрос "
    "клиента. Вложения ты НЕ видишь; классифицируй по теме+тексту. Если не уверен "
    "— «Прочее» с пометкой.\n\n"
    'Ответ строго JSON: {"shelf":"<одна из 5 точь-в-точь>","reason":"<1-2 фразы, укажи роль отправителя>"}'
)

_BUDGET = 42000
_log = []
def _pace(est):
    now = time.time()
    while _log and now - _log[0][0] > 60: _log.pop(0)
    used = sum(t for _, t in _log)
    if used + est > _BUDGET and _log:
        wait = 60 - (now - _log[0][0]) + 1
        if wait > 0:
            print(f"  [пейсер] {used} ток./мин — пауза {wait:.0f}с", file=sys.stderr, flush=True)
            time.sleep(wait)
    _log.append((time.time(), est))

def call_claude(api_key, model, user, max_tokens=300):
    _pace((len(SYSTEM) + len(user)) // 4 + max_tokens)
    body = json.dumps({"model": model, "max_tokens": max_tokens, "system": SYSTEM,
                       "messages": [{"role": "user", "content": user}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
                return "".join(b.get("text", "") for b in data.get("content", []))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 5:
                print("  [429] пауза 60с", file=sys.stderr, flush=True); _log.clear(); time.sleep(62); continue
            if e.code in (500, 503, 529) and attempt < 5: time.sleep(2 ** attempt * 3); continue
            raise
        except Exception:
            if attempt < 5: time.sleep(2 ** attempt * 3); continue
            raise

def strip_html(html):
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html or "")
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()

def parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m: return None
    try: o = json.loads(m.group(0))
    except Exception: return None
    shelf = o.get("shelf", "")
    if shelf not in SHELVES:
        shelf = next((s for s in SHELVES if s.lower() in str(shelf).lower()), "Прочее")
    return {"shelf": shelf, "reason": (o.get("reason") or "")[:500]}

def execute():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    account = os.environ.get("EMAIL_ACCOUNT", "PMK Park входящие (тест)")
    if not api_key:
        print("ОШИБКА: нет ANTHROPIC_API_KEY", file=sys.stderr); return

    # только ОЦЕНЁННЫЕ письма, ошибочные (Неверно) первыми, без уже сделанных v2
    comms = frappe.get_all("Communication",
        filters={"email_account": account, "custom_manager_verdict": ["in", ["Верно", "Неверно"]]},
        or_filters=[["custom_claude_classification_v2", "is", "not set"], ["custom_claude_classification_v2", "=", ""]],
        fields=["name", "subject", "content", "custom_manager_verdict"],
        order_by="custom_manager_verdict asc", limit_page_length=0)  # 'Неверно' < 'Верно' по алфавиту

    print(f"К прогону v2 (оценённые): {len(comms)}", file=sys.stderr, flush=True)
    counts = Counter(); done = 0
    for c in comms:
        user = f"Тема: {c.subject or ''}\n\nТекст:\n{strip_html(c.content)[:2500]}"
        try:
            res = parse(call_claude(api_key, model, user))
        except Exception as ex:
            print(f"  ОСТАНОВ (API): {str(ex)[:120]}", file=sys.stderr, flush=True); break
        if not res: res = {"shelf": "Прочее", "reason": "не распарсилось"}
        frappe.db.set_value("Communication", c.name, {
            "custom_claude_classification_v2": res["shelf"],
            "custom_claude_reason_v2": res["reason"]}, update_modified=False)
        frappe.db.commit()
        counts[res["shelf"]] += 1; done += 1
        if done % 10 == 0:
            print(f"  обработано {done}/{len(comms)}", file=sys.stderr, flush=True)
    print(f"\nГотово v2: {done}. Распределение:", file=sys.stderr, flush=True)
    for s in SHELVES:
        print(f"  {s}: {counts.get(s,0)}", file=sys.stderr, flush=True)
