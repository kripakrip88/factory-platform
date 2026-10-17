# -*- coding: utf-8 -*-
"""Клиент Anthropic Messages API для Odoo (без пакета anthropic — на requests).

Соединение держится открытым на процесс (requests.Session): рукопожатие TLS с нашего VPS
занимает 4–10 с (замер 17.10.2026), повторять его на каждый вопрос нельзя. Обрыв
соединения — один повтор; ответ API с ошибкой — сразу ошибка с текстом Anthropic.
"""
import time

import requests

DEFAULT_BASE = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-sonnet-5-5"
API_VERSION = "2023-06-01"
CONNECT_TIMEOUT = 20
READ_TIMEOUT = 180

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


def messages(api_key, payload, base=None, retries=1):
    """POST /v1/messages → (ответ JSON, секунд). Ошибки — ClaudeError."""
    if not api_key:
        raise ClaudeError("Ключ API не задан: Настройки → Ассистент.")
    url = (base or DEFAULT_BASE).rstrip("/") + "/v1/messages"
    headers = {"x-api-key": api_key.strip(), "anthropic-version": API_VERSION,
               "content-type": "application/json"}
    started = time.time()
    for attempt in range(retries + 1):
        try:
            resp = _http().post(url, json=payload, headers=headers, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            break
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt >= retries:
                raise ClaudeError("Нет связи с API Anthropic (%s). Повторите или проверьте адрес API."
                                  % exc.__class__.__name__) from exc
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
