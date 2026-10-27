# -*- coding: utf-8 -*-
"""Клиент Anthropic Messages API для Odoo (без пакета anthropic — на requests).

Соединение держится открытым на процесс (requests.Session): рукопожатие TLS с нашего VPS
занимает 4–10 с (замер 17.10.2026), повторять его на каждый вопрос нельзя. Ответ API с
ошибкой — сразу ошибка с текстом Anthropic.

27.10.2026: с VPS до api.anthropic.com теряется 50–75 % пакетов (только этот адрес; Google —
0 %), новое соединение в 2 из 5 попыток висит 25 с. Поэтому: (1) фон раз в KEEPALIVE_SEC
дёргает бесплатный GET /v1/models — соединение не остывает, вопрос идёт по готовому;
(2) не удалось соединиться — запрос ещё не ушёл, повтор бесплатный: до CONNECT_TRIES раз с
коротким ожиданием, человеку — «связь плохая, пробую ещё» (on_retry).
"""
import time

import requests

DEFAULT_BASE = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-sonnet-5-5"
API_VERSION = "2023-06-01"
CONNECT_TIMEOUT = 15     # TCP + TLS: удачные рукопожатия 27.10 — 3–10 с
CONNECT_TRIES = 4        # попыток соединиться (запрос не ушёл — токены не тратятся)
READ_TIMEOUT = 180
KEEPALIVE_SEC = 50       # фон держит соединение тёплым (worker/ai_worker.py)

_session = None


class ClaudeError(Exception):
    """Понятная ошибка для человека: текст — по-русски или от Anthropic."""


def _http():
    global _session
    if _session is None:
        _session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=2, pool_maxsize=4)
        _session.mount("https://", adapter)
    return _session


def _headers(api_key):
    return {"x-api-key": api_key.strip(), "anthropic-version": API_VERSION, "content-type": "application/json"}


def messages(api_key, payload, base=None, retries=1, on_retry=None):
    """POST /v1/messages → (ответ JSON, секунд). Ошибки — ClaudeError.

    on_retry(текст) — сообщить человеку, что связь плохая и идёт повтор."""
    if not api_key:
        raise ClaudeError("Ключ API не задан: Настройки → Ассистент.")
    url = (base or DEFAULT_BASE).rstrip("/") + "/v1/messages"
    started = time.time()
    connect_fails = read_fails = 0
    while True:
        tried = time.time()
        try:
            resp = _http().post(url, json=payload, headers=_headers(api_key),
                                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            break
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = exc
        # «ReadTimeout» раньше READ_TIMEOUT — сорвалось рукопожатие TLS (Голубенко 27.10: через
        # 43 с), запрос не ушёл. Настоящий таймаут чтения — запрос ушёл, повтор стоит токенов:
        # только retries раз. Остальное (не соединились, остывшее соединение закрыто) — повтор.
        if isinstance(last, requests.ReadTimeout) and time.time() - tried >= READ_TIMEOUT - 5:
            read_fails += 1
            failed = read_fails > retries
        else:
            connect_fails += 1
            failed = connect_fails >= CONNECT_TRIES
        if failed:
            raise ClaudeError("Нет связи с ИИ (Anthropic): сервер не смог соединиться за %d попыток (%s). "
                              "Повторите через минуту." % (connect_fails + read_fails, last.__class__.__name__)) from last
        if on_retry:
            on_retry("Связь с ИИ плохая — пробую ещё (попытка %d)…" % (connect_fails + read_fails + 1))
        time.sleep(1)
    seconds = time.time() - started
    try:
        data = resp.json()
    except ValueError:
        raise ClaudeError("API ответил не JSON (HTTP %s)." % resp.status_code)
    if resp.status_code >= 400:
        err = (data.get("error") or {}) if isinstance(data, dict) else {}
        kind, text = err.get("type", ""), err.get("message", "")
        human = {
            "authentication_error": "Ключ не принят — проверьте, что вставлен целиком и не отозван.",
            "permission_error": "У ключа нет доступа к этой модели или организации.",
            "billing_error": "Не хватает средств на счёте API (console.anthropic.com → Billing).",
            "rate_limit_error": "Слишком много запросов — подождите минуту.",
            "overloaded_error": "Anthropic перегружен — повторите через минуту.",
            "not_found_error": "Нет такой модели — проверьте поле «Модель».",
        }.get(kind, "")
        raise ClaudeError("%s (HTTP %s: %s)" % (human or "Ошибка API", resp.status_code, text or kind))
    return data, seconds


def keepalive(api_key, base=None):
    """Бесплатный запрос (список моделей) по тому же соединению — чтобы не остывало. → HTTP-код."""
    url = (base or DEFAULT_BASE).rstrip("/") + "/v1/models?limit=1"
    resp = _http().get(url, headers=_headers(api_key), timeout=(CONNECT_TIMEOUT, 30))
    resp.content  # дочитать — иначе соединение не вернётся в пул
    return resp.status_code


def ping(api_key, model=None, base=None):
    """Проверка связи: короткий вопрос, ответ в одно слово. → текст для человека."""
    data, seconds = messages(api_key, {
        # Запас: новые модели сначала «думают» — на 16 токенов текста не оставалось (17.10).
        "model": model or DEFAULT_MODEL, "max_tokens": 400,
        "messages": [{"role": "user", "content": "Ответь одним словом по-русски: связь есть?"}],
    }, base=base)
    text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text").strip()
    usage = data.get("usage") or {}
    return "Связь есть: «%s» · модель %s · %.1f с · токенов %s/%s" % (
        text or "ответ получен", data.get("model"), seconds, usage.get("input_tokens"), usage.get("output_tokens"))
