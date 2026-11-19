#!/usr/bin/env python3
"""Шлюз «ассистент Odoo → Claude Code на claude-vps» (19.11.2026).

Зачем: организация Anthropic API не прошла проверку (HTTP 403 с 16.11), а Антону нужно
опробовать действия ассистента на копии Odoo. Шлюз принимает тот же запрос, что ассистент
Odoo шлёт в Anthropic Messages API (POST /v1/messages), отвечает в том же формате — в Odoo
меняется только адрес API в настройках.

Внутри — `claude -p` (подписка claudeuser). Инструменты Odoo НЕ выполняются здесь: модель
отвечает JSON-ом «вызови инструмент X с …» или «ответ: …», шлюз превращает это в блоки
tool_use / text, а сам инструмент выполняет Odoo своими правами и присылает результат следующим
запросом. Доступа к базе Odoo у claude-vps нет.

Файлы из запроса (скан, PDF) кладутся во временную папку — Claude читает их инструментом Read,
других инструментов у него нет. После ответа папка удаляется.

Слушает 127.0.0.1:8765; с сервера Odoo — через SSH-туннель (пользователь gwtunnel, только этот
порт). Ключ доступа — /home/claudeuser/.config/odoo-claude-gw/secret (тот же — «ключ API» на копии).
"""
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.expanduser("~")
CLAUDE = os.path.join(HOME, ".local/bin/claude")
SECRET_FILE = os.path.join(HOME, ".config/odoo-claude-gw/secret")
WORK = os.path.join(HOME, "work/odoo-gw")
LISTEN = ("127.0.0.1", 8765)
PARALLEL = threading.Semaphore(2)     # одновременно не больше двух запусков Claude Code
TIMEOUT = 170                          # у Odoo READ_TIMEOUT 180 с
MAX_BODY = 40 * 1024 * 1024
MODEL = "claude-opus-5-5"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("odoo-claude-gw")

PROTOCOL = """

# Как отвечать (шлюз Odoo)
Ты работаешь как ассистент внутри Odoo. Инструменты Odoo вызываешь НЕ сам: ответь ОДНИМ JSON-объектом
без пояснений вокруг. Варианты:
1) вызвать инструменты: {"tool_calls": [{"name": "<имя>", "input": {…по схеме…}}]}
2) дать ответ человеку: {"answer": "<текст в Markdown>"}
Результаты инструментов придут следующим сообщением. Файлы, упомянутые как «файл: путь», читай
инструментом Read. Других инструментов у тебя нет.
"""


def _secret():
    with open(SECRET_FILE) as fh:
        return fh.read().strip()


def _text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _render(payload, folder):
    """Messages API → (системная подсказка, текст разговора)."""
    system = payload.get("system")
    system = _text_of(system) if not isinstance(system, str) else system
    tools = payload.get("tools") or []
    if tools:
        system += "\n\n# Инструменты Odoo\n" + "\n".join(
            "- %s: %s\n  схема: %s" % (t.get("name"), t.get("description", ""),
                                      json.dumps(t.get("input_schema") or {}, ensure_ascii=False))
            for t in tools)
    system += PROTOCOL
    choice = (payload.get("tool_choice") or {}).get("type")
    lines, files = [], 0
    for msg in payload.get("messages") or []:
        role = "Человек" if msg.get("role") == "user" else "Ты (ассистент)"
        content = msg.get("content")
        if isinstance(content, str):
            lines.append("## %s\n%s" % (role, content))
            continue
        parts = []
        for block in content or []:
            kind = block.get("type")
            if kind == "text":
                parts.append(block.get("text", ""))
            elif kind in ("image", "document"):
                src = block.get("source") or {}
                if src.get("type") == "base64":
                    files += 1
                    media = src.get("media_type") or ""
                    ext = {"application/pdf": ".pdf", "image/png": ".png", "image/gif": ".gif",
                           "image/webp": ".webp"}.get(media, ".jpg")
                    path = os.path.join(folder, "file%02d%s" % (files, ext))
                    with open(path, "wb") as fh:
                        fh.write(base64.b64decode(src.get("data") or ""))
                    parts.append("файл: %s" % path)
                elif src.get("type") == "text":
                    parts.append(src.get("data", ""))
            elif kind == "tool_use":
                parts.append("[вызов инструмента %s: %s]" % (block.get("name"),
                                                             json.dumps(block.get("input") or {}, ensure_ascii=False)))
            elif kind == "tool_result":
                res = block.get("content")
                parts.append("[результат инструмента]\n%s" % (_text_of(res) if not isinstance(res, str) else res))
        lines.append("## %s\n%s" % (role, "\n".join(p for p in parts if p)))
    if choice == "none":
        lines.append("\n(Инструменты больше вызывать нельзя — дай ответ: {\"answer\": …})")
    return system, "\n\n".join(lines)


def _parse(text):
    """Ответ Claude → JSON-объект протокола (первый целый {…})."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    while start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


def _ask(payload):
    os.makedirs(WORK, exist_ok=True)
    folder = tempfile.mkdtemp(prefix="q-", dir=WORK)
    try:
        system, prompt = _render(payload, folder)
        # Подсказка и разговор — файлом и через stdin: аргумент командной строки в Linux не длиннее
        # 128 КБ, а правила ассистента со знаниями и историей бывают больше.
        sys_file = os.path.join(folder, ".system.md")
        with open(sys_file, "w", encoding="utf-8") as fh:
            fh.write(system)
        # Модель — явно (Антон 19.11.2026: «пусть всё опус будет»), чтобы обновление Claude Code её не сменило.
        cmd = [CLAUDE, "-p", "--model", MODEL, "--output-format", "json", "--system-prompt-file", sys_file,
               "--tools", "Read", "--strict-mcp-config", "--permission-mode", "auto", "--max-turns", "6"]
        with PARALLEL:
            started = time.time()
            proc = subprocess.run(cmd, cwd=folder, capture_output=True, text=True, timeout=TIMEOUT,
                                  input=prompt)
        seconds = time.time() - started
        try:
            res = json.loads(proc.stdout)
        except ValueError:
            raise RuntimeError("Claude Code: %s" % (proc.stderr or proc.stdout)[-300:])
        text = res.get("result") or ""
        obj = _parse(text)
        tools = {t.get("name") for t in payload.get("tools") or []}
        content, stop = [], "end_turn"
        calls = (obj or {}).get("tool_calls") or []
        if calls and (payload.get("tool_choice") or {}).get("type") != "none":
            for call in calls:
                if call.get("name") in tools:
                    content.append({"type": "tool_use", "id": "toolu_gw_%s" % uuid.uuid4().hex[:16],
                                    "name": call["name"], "input": call.get("input") or {}})
            if content:
                stop = "tool_use"
        if not content:
            answer = (obj or {}).get("answer") if obj else None
            content = [{"type": "text", "text": answer if answer is not None else text}]
        log.info("ответ за %.1f с: %s", seconds, stop)
        if stop != "tool_use" and payload.get("tools") and not (obj or {}).get("answer"):
            # Ждали вызова инструмента, а пришёл не протокол — в журнал, чтобы видеть почему.
            log.info("не протокол: %s", text[:400].replace("\n", " "))
        return {"id": "msg_gw_%s" % uuid.uuid4().hex[:16], "type": "message", "role": "assistant",
                "model": MODEL, "content": content, "stop_reason": stop,
                "usage": {"input_tokens": 0, "output_tokens": 0}}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        return (self.headers.get("x-api-key") or "").strip() == _secret()

    def do_GET(self):  # «Проверить связь» и keepalive ассистента: GET /v1/models
        if not self._authorized():
            return self._send(401, {"error": {"type": "authentication_error", "message": "bad key"}})
        self._send(200, {"data": [{"id": "claude-code-gw"}]})

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/messages":
            return self._send(404, {"error": {"type": "not_found_error", "message": "only /v1/messages"}})
        if not self._authorized():
            return self._send(401, {"error": {"type": "authentication_error", "message": "bad key"}})
        size = int(self.headers.get("Content-Length") or 0)
        if size > MAX_BODY:
            return self._send(413, {"error": {"type": "invalid_request_error", "message": "too large"}})
        try:
            payload = json.loads(self.rfile.read(size))
            return self._send(200, _ask(payload))
        except subprocess.TimeoutExpired:
            return self._send(529, {"error": {"type": "overloaded_error", "message": "Claude Code не уложился во время"}})
        except Exception as exc:  # noqa: BLE001
            log.exception("ошибка")
            return self._send(500, {"error": {"type": "api_error", "message": str(exc)[:300]}})

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


if __name__ == "__main__":
    log.info("шлюз слушает %s:%s", *LISTEN)
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
