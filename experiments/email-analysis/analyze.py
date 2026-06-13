#!/usr/bin/env python3
"""
Обезличенный анализ потока писем ящика (разведка под маршрут «письмо → лид»).

ПРИВАТНОСТЬ:
- Тела писем, имена, телефоны, реквизиты НИКОГДА не пишутся в файлы/отчёт.
- Вложения обрабатываются в памяти (BytesIO), на диск не сохраняются.
- В REPORT.md идут ТОЛЬКО агрегаты (числа, распределения, домены).
- Содержимое уходит в Anthropic API (классификация/извлечение) — это явное
  требование ТЗ; ничего больше наружу не уходит.

Запуск ТОЛЬКО на сервере завода:
    cd experiments/email-analysis
    cp .env.example .env   # заполнить IMAP_PASSWORD и ANTHROPIC_API_KEY
    python3 -m venv venv && . venv/bin/activate
    pip install -r requirements.txt
    python3 analyze.py > REPORT.md
"""

import email
import imaplib
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime


def log(msg):
    """Прогресс — только в stderr, чтобы не попасть в REPORT.md (stdout)."""
    print(msg, file=sys.stderr, flush=True)


def load_env():
    path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    cfg = {
        "host": os.environ.get("IMAP_HOST", "imap.mail.ru"),
        "port": int(os.environ.get("IMAP_PORT", "993")),
        "user": os.environ.get("IMAP_USER", ""),
        "password": os.environ.get("IMAP_PASSWORD", ""),
        "window": int(os.environ.get("WINDOW", "400")),
        "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
    }
    missing = [k for k in ("user", "password", "api_key") if not cfg[k]]
    if missing:
        log(f"ОШИБКА: не заданы в .env: {', '.join(missing)}")
        sys.exit(1)
    return cfg


# ----------------------------- IMAP / парсинг -----------------------------

def decode_mime(s):
    if not s:
        return ""
    out = []
    for part, enc in decode_header(s):
        if isinstance(part, bytes):
            try:
                out.append(part.decode(enc or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                out.append(part.decode("utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out)


def sender_domain(from_header):
    m = re.search(r"[\w.+-]+@([\w-]+\.[\w.-]+)", from_header or "")
    return m.group(1).lower() if m else "unknown"


def get_body_text(msg):
    """Текст письма (plain; из html вырезаем теги). Возвращаем для анализа в памяти."""
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            if ctype == "text/plain":
                text += _decode_part(part) + "\n"
        if not text:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    text += _strip_html(_decode_part(part)) + "\n"
    else:
        if msg.get_content_type() == "text/html":
            text = _strip_html(_decode_part(msg))
        else:
            text = _decode_part(msg)
    return text.strip()


def _decode_part(part):
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


def _strip_html(html):
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html)


def classify_attachment(filename, content_type):
    ext = (os.path.splitext(filename or "")[1] or "").lower().lstrip(".")
    if ext in ("xlsx", "xls", "xlsm", "csv"):
        return "excel"
    if ext == "pdf":
        return "pdf"
    if ext in ("doc", "docx", "rtf"):
        return "word"
    if ext in ("jpg", "jpeg", "png", "gif", "bmp", "tiff", "heic"):
        return "image"
    if ext in ("dwg", "dxf"):
        return "cad"
    if "pdf" in (content_type or ""):
        return "pdf"
    if "spreadsheet" in (content_type or "") or "excel" in (content_type or ""):
        return "excel"
    return "other"


def pdf_has_text_layer(data):
    """True = текстовый слой (читаемый), False = скан/картинка. None = не смогли определить."""
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        return None
    try:
        text = extract_text(io.BytesIO(data), maxpages=3) or ""
        return len(re.sub(r"\s+", "", text)) > 40
    except Exception:
        return None


def parse_email(raw):
    msg = email.message_from_bytes(raw)
    info = {
        "domain": sender_domain(msg.get("From", "")),
        "date": None,
        "body": get_body_text(msg),
        "attachments": [],  # list of dicts: kind, size, pdf_text(None/True/False)
    }
    try:
        d = parsedate_to_datetime(msg.get("Date"))
        info["date"] = d.date().isoformat() if d else None
    except Exception:
        info["date"] = None

    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get("Content-Disposition") or "")
            fname = decode_mime(part.get_filename())
            if "attachment" in disp or fname:
                payload = part.get_payload(decode=True) or b""
                kind = classify_attachment(fname, part.get_content_type())
                att = {"kind": kind, "size": len(payload), "pdf_text": None}
                if kind == "pdf" and payload:
                    att["pdf_text"] = pdf_has_text_layer(payload)
                info["attachments"].append(att)
    return info


# ----------------------------- Anthropic API -----------------------------

# Пейсер: держим суммарные input-токены под лимитом организации (50k/мин).
# Скользящее окно 60с, потолок с запасом.
_TOKEN_BUDGET_PER_MIN = 42000
_token_log = []  # list of (timestamp, tokens)


def _pace(est_tokens):
    now = time.time()
    # выкинуть всё старше 60с
    while _token_log and now - _token_log[0][0] > 60:
        _token_log.pop(0)
    used = sum(t for _, t in _token_log)
    if used + est_tokens > _TOKEN_BUDGET_PER_MIN and _token_log:
        wait = 60 - (now - _token_log[0][0]) + 1
        if wait > 0:
            log(f"  [пейсер] {used} ток./мин — пауза {wait:.0f}с")
            time.sleep(wait)
    _token_log.append((time.time(), est_tokens))


def call_anthropic(cfg, system, user, max_tokens=1024):
    est = (len(system) + len(user)) // 4 + max_tokens  # грубая оценка input+output
    _pace(est)
    body = json.dumps({
        "model": cfg["model"],
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": cfg["api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
                return "".join(b.get("text", "") for b in data.get("content", []))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 5:
                # лимит per-minute — ждём полную минуту и сбрасываем окно
                log(f"  [429] rate limit — пауза 60с (попытка {attempt+1})")
                _token_log.clear()
                time.sleep(62)
                continue
            if e.code in (529, 500, 503) and attempt < 5:
                time.sleep(2 ** attempt * 3)
                continue
            log(f"Anthropic HTTP {e.code}: {e.read()[:200]}")
            raise
        except Exception as ex:
            if attempt < 5:
                time.sleep(2 ** attempt * 3)
                continue
            raise


def extract_json(text):
    m = re.search(r"\[.*\]|\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


CLASSIFY_SYSTEM = (
    "Ты классифицируешь входящие письма завода металлоконструкций. "
    "Для каждого письма верни JSON-объект: "
    '{"i": <индекс>, "cat": "request"|"spam"|"other", "body_has_request": true|false}. '
    "cat=request — это запрос на изготовление/просчёт/счёт от потенциального "
    "или текущего клиента (КП, заявка, прайс на изготовление). "
    "cat=spam — реклама, рассылка, маркетинг. "
    "cat=other — переписка/ответы, письма от поставщиков, бухгалтерия, служебное, уведомления. "
    "body_has_request=true, если суть заявки (что и сколько изготовить/просчитать) "
    "содержится в ТЕКСТЕ письма, а не только во вложении. "
    "Верни ТОЛЬКО JSON-массив объектов, без пояснений."
)


def classify_batch(cfg, batch):
    """batch: list of (idx, body). Возвращает {idx: {'cat':..., 'body_has_request':bool}}."""
    parts = []
    for idx, body in batch:
        snippet = (body or "")[:900].replace("\n", " ")
        parts.append(f"[Письмо {idx}]\n{snippet}")
    user = "Классифицируй письма:\n\n" + "\n\n".join(parts)
    text = call_anthropic(cfg, CLASSIFY_SYSTEM, user, max_tokens=1500)
    arr = extract_json(text) or []
    res = {}
    for o in arr:
        if isinstance(o, dict) and "i" in o:
            res[int(o["i"])] = {
                "cat": o.get("cat", "other"),
                "body_has_request": bool(o.get("body_has_request", False)),
            }
    return res


EXTRACT_SYSTEM = (
    "Ты проверяешь, насколько надёжно из ТЕКСТА письма-заявки извлекаются данные. "
    "НЕ возвращай само содержимое (ни имён, ни телефонов, ни позиций) — только ОЦЕНКУ. "
    "Верни JSON: "
    '{"contact_found": true|false, "request_clear": true|false, '
    '"positions_parseable": true|false, "positions_count": <int>, '
    '"issue": "none"|"qty_unit_confusion"|"vague_request"|"no_positions"|"mixed_languages"|"other"}. '
    "contact_found — есть ли в тексте контакт (имя/телефон/email/компания). "
    "request_clear — внятно ли, что просят. "
    "positions_parseable — можно ли разбить на позиции списком. "
    "positions_count — сколько позиций распознаётся (0 если нет). "
    "issue — главная проблема извлечения. Только JSON."
)


def extract_quality(cfg, body):
    snippet = (body or "")[:2000]
    text = call_anthropic(cfg, EXTRACT_SYSTEM, "Текст письма:\n\n" + snippet, max_tokens=400)
    o = extract_json(text) or {}
    return {
        "contact_found": bool(o.get("contact_found", False)),
        "request_clear": bool(o.get("request_clear", False)),
        "positions_parseable": bool(o.get("positions_parseable", False)),
        "positions_count": int(o.get("positions_count", 0) or 0),
        "issue": o.get("issue", "other"),
    }


# ----------------------------- Сбор статистики -----------------------------

def main():
    cfg = load_env()
    log(f"Подключение к {cfg['host']}:{cfg['port']} (только чтение)...")
    ctx = ssl.create_default_context()
    M = imaplib.IMAP4_SSL(cfg["host"], cfg["port"], ssl_context=ctx)
    M.login(cfg["user"], cfg["password"])
    M.select("INBOX", readonly=True)  # readonly — ничего не меняем

    typ, data = M.search(None, "ALL")
    ids = data[0].split()
    total_inbox = len(ids)
    window = ids[-cfg["window"]:] if cfg["window"] < len(ids) else ids
    log(f"Во Входящих всего: {total_inbox}. Берём окно: {len(window)}.")

    emails = []
    for n, eid in enumerate(window, 1):
        typ, d = M.fetch(eid, "(RFC822)")
        if d and d[0]:
            try:
                emails.append(parse_email(d[0][1]))
            except Exception as ex:
                log(f"  пропуск письма {eid}: {ex}")
        if n % 50 == 0:
            log(f"  загружено {n}/{len(window)}")
    M.logout()
    log(f"Загружено для анализа: {len(emails)}")

    # --- Блок 2: классификация через Anthropic (батчами) ---
    log("Классификация через Anthropic...")
    batch, BSZ = [], 8
    classif = {}
    for i, em in enumerate(emails):
        batch.append((i, em["body"]))
        if len(batch) == BSZ:
            classif.update(classify_batch(cfg, batch))
            batch = []
            log(f"  классифицировано {len(classif)}/{len(emails)}")
    if batch:
        classif.update(classify_batch(cfg, batch))
    for i, em in enumerate(emails):
        c = classif.get(i, {"cat": "other", "body_has_request": False})
        em["cat"] = c["cat"]
        em["body_has_request"] = c["body_has_request"]

    # --- Блок 4: качество извлечения на выборке заявок ---
    requests = [em for em in emails if em["cat"] == "request"]
    sample = requests[:20]
    log(f"Проверка извлечения на {len(sample)} заявках...")
    quality = []
    for n, em in enumerate(sample, 1):
        try:
            quality.append(extract_quality(cfg, em["body"]))
        except Exception as ex:
            log(f"  извлечение {n}: {ex}")
        if n % 5 == 0:
            log(f"  проверено {n}/{len(sample)}")

    render_report(cfg, total_inbox, emails, requests, quality)


def att_kinds(em):
    return {a["kind"] for a in em["attachments"]}


def render_report(cfg, total_inbox, emails, requests, quality):
    N = len(emails)
    def pct(x):
        return f"{100*x/N:.0f}%" if N else "—"

    # Блок 1
    by_day = Counter(em["date"] for em in emails if em["date"])
    days = len(by_day) or 1
    domains = Counter(em["domain"] for em in emails)
    uniq_senders = len(domains)
    peak_day = max(by_day.values()) if by_day else 0

    # Блок 2
    cats = Counter(em["cat"] for em in emails)

    # Блок 3 — где живёт заявка
    loc = Counter()
    pdf_text_layer = Counter()
    for em in requests:
        kinds = att_kinds(em)
        relevant = kinds & {"excel", "pdf", "word"}
        if em["body_has_request"] and not relevant:
            loc["тело письма"] += 1
        elif em["body_has_request"] and relevant:
            loc["смешанное (тело + вложение)"] += 1
        elif "excel" in kinds:
            loc["вложение Excel"] += 1
        elif "pdf" in kinds:
            loc["вложение PDF"] += 1
        elif "word" in kinds:
            loc["вложение Word"] += 1
        else:
            loc["неопределённо"] += 1
        for a in em["attachments"]:
            if a["kind"] == "pdf":
                if a["pdf_text"] is True:
                    pdf_text_layer["PDF с текстовым слоем"] += 1
                elif a["pdf_text"] is False:
                    pdf_text_layer["PDF-скан/картинка"] += 1
                else:
                    pdf_text_layer["PDF (слой не определён)"] += 1

    # Блок 5 — вложения
    req_with_att = sum(1 for em in requests if em["attachments"])
    all_att = [a for em in requests for a in em["attachments"]]
    att_kind_dist = Counter(a["kind"] for a in all_att)
    avg_att = (len(all_att) / len(requests)) if requests else 0
    sizes = [a["size"] for a in all_att if a["size"]]
    avg_size_kb = (sum(sizes) / len(sizes) / 1024) if sizes else 0

    # Блок 4 — качество извлечения
    q = len(quality) or 1
    contact = sum(1 for x in quality if x["contact_found"])
    clear = sum(1 for x in quality if x["request_clear"])
    pos_ok = sum(1 for x in quality if x["positions_parseable"])
    issues = Counter(x["issue"] for x in quality)

    P = print  # в stdout → REPORT.md
    P("# Отчёт: обезличенный анализ потока писем")
    P("")
    P(f"_Ящик: pmkpark@mail.ru (рабочая почта). Окно анализа: {N} писем из "
      f"{total_inbox} во Входящих. Классификатор: Anthropic {cfg['model']}._")
    P("")
    P("> Отчёт содержит только агрегированную статистику. Тела писем, имена, "
      "телефоны и реквизиты не выгружались и в отчёт не попали.")
    P("")
    P("## Блок 1 — Объём и поток")
    P(f"- Писем в окне: **{N}** (из {total_inbox} во Входящих)")
    P(f"- Дней в окне: {days} → в среднем **{N/days:.1f} писем/день**, пик **{peak_day}**/день")
    P(f"- Уникальных доменов-отправителей: **{uniq_senders}**")
    P("- Топ доменов (без конкретных адресов):")
    for dom, c in domains.most_common(10):
        P(f"  - `{dom}` — {c}")
    P("")
    P("## Блок 2 — Доля заявок (главное)")
    P(f"- **Заявки на просчёт/изготовление: {cats.get('request',0)} ({pct(cats.get('request',0))})**")
    P(f"- Спам/реклама: {cats.get('spam',0)} ({pct(cats.get('spam',0))})")
    P(f"- Прочее (ответы, поставщики, бухгалтерия, служебное): {cats.get('other',0)} ({pct(cats.get('other',0))})")
    P("")
    P("## Блок 3 — Где живёт суть заявки")
    P(f"_Из {len(requests)} писем-заявок:_")
    for k, c in loc.most_common():
        P(f"- {k}: **{c}**")
    if pdf_text_layer:
        P("")
        P("PDF-вложения в заявках по читаемости:")
        for k, c in pdf_text_layer.most_common():
            P(f"  - {k}: {c}")
    P("")
    P("## Блок 4 — Что извлекается из текста (выборка)")
    P(f"_Проверено заявок: {len(quality)}._")
    P(f"- Контакт извлекается: **{contact} из {q}**")
    P(f"- Суть запроса внятна: **{clear} из {q}**")
    P(f"- Позиции разбиваются списком: **{pos_ok} из {q}**")
    P("- Типичные проблемы извлечения:")
    for iss, c in issues.most_common():
        P(f"  - {iss}: {c}")
    P("")
    P("## Блок 5 — Вложения в заявках")
    P(f"- Заявок с вложениями: **{req_with_att} из {len(requests)}**"
      + (f" ({100*req_with_att/len(requests):.0f}%)" if requests else ""))
    P(f"- Среднее число вложений на заявку: {avg_att:.1f}")
    P(f"- Средний размер вложения: {avg_size_kb:.0f} КБ")
    P("- Распределение по типам:")
    for k, c in att_kind_dist.most_common():
        P(f"  - {k}: {c}")
    P("")
    P("---")
    P("_Сгенерировано analyze.py. Временные данные не сохранялись, вложения "
      "обрабатывались в памяти._")


if __name__ == "__main__":
    main()
