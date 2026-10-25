# -*- coding: utf-8 -*-
"""Очередь и распознавание счетов — в фоне ассистента (odoo-ai-worker), как разбор почты.

Отбор писем бесплатный (без ассистента): «Входящие» ящика разбора почты
(pmk_ai_mail.account) после pmk_supplier_invoice.since, с вложением, в теме «счёт»
(«Cчет Сч-0029200 от 23.10.26» у Металлсервиса), не от нас. Счёт Металлсервиса —
PDF-картинка без текста: читает ассистент по изображению (вложения — тем же
pmk_ai_mail.tools.parts, что и разбор почты). Ответ — инструмент invoice; дальше
сопоставление и цены считает Odoo (prices.py), ассистент цен не пишет.
"""
import base64
import json
import logging
import os
import re
import time

from odoo import _, api, fields, models
from odoo.tools import html2plaintext

from odoo.addons.pmk_ai.tools import claude
from odoo.addons.pmk_ai_mail.tools import parts

_logger = logging.getLogger(__name__)

RULES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge", "invoice.md")
MAX_TOKENS = 6000
MAX_BODY_CHARS = 4000
JOBS_AT_ONCE = 1           # счёт за раз — остальные потоки фона для чата и почты
BATCH = 20
STUCK_SEC = 600
# «Cчет Сч-0029200…» у Металлсервиса — с ЛАТИНСКОЙ «C» в начале: обе буквы.
SUBJECT_RE = r"([сc]ч[её]т|invoice)"

LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"}, "unit": {"type": "string"},
        "qty": {"type": ["number", "null"]}, "price": {"type": ["number", "null"]},
        "amount": {"type": ["number", "null"]}, "note": {"type": "string"},
        "kind": {"type": "string", "enum": ["metal", "service", "other"]},
        "catalog_name": {"type": "string"}, "grade": {"type": "string"},
        "length_mm": {"type": ["number", "null"]}, "metres": {"type": ["number", "null"]},
    },
    "required": ["name", "unit", "qty", "price", "amount", "kind"],
}
INVOICE_TOOL = {
    "name": "invoice",
    "description": "Распознанный счёт на оплату поставщика: шапка и строки дословно.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_invoice": {"type": "boolean"},
            "reason": {"type": "string"},
            "supplier_name": {"type": "string"}, "supplier_inn": {"type": "string"},
            "number": {"type": "string"}, "date": {"type": "string"},
            "payer": {"type": "string"},
            "total": {"type": ["number", "null"]}, "vat": {"type": ["number", "null"]},
            "vat_rate": {"type": ["number", "null"]},
            "lines": {"type": "array", "items": LINE_SCHEMA},
        },
        "required": ["is_invoice"],
    },
}


def _f(value):
    try:
        return float(str(value).replace(" ", "").replace(" ", "").replace(",", ".")) if value not in (None, "") else 0.0
    except ValueError:
        return 0.0


class SupplierInvoiceQueue(models.Model):
    _inherit = "pmk.supplier.invoice"

    @api.model
    def _param(self, key, default=None):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    @api.model
    def _enabled(self):
        return self._param("pmk_supplier_invoice.enabled") in ("1", "True", "true")

    @api.model
    def _enqueue(self):
        """Письма со счетами — в очередь. Бесплатно: тема, вложение, не наш ящик."""
        email = (self._param("pmk_ai_mail.account") or "pmkpark@mail.ru").strip().lower()
        since = self._param("pmk_supplier_invoice.since")
        if not since:
            return 0
        self.env.cr.execute("""
            SELECT m.id, m.subject, m.email_from
              FROM mail_client_message m
              JOIN mail_client_folder f ON f.id = m.folder_id
              JOIN mail_client_account a ON a.id = f.account_id
             WHERE lower(a.email) = %s AND f.role = 'inbox' AND NOT coalesce(m.is_spam, false)
               AND m.date >= %s AND coalesce(m.has_attachment, false)
               AND m.subject ~* %s AND m.subject !~* '^\\s*(re|ответ)\\s*:'
               AND NOT EXISTS (SELECT 1 FROM pmk_supplier_invoice s WHERE s.message_id = m.id)
             ORDER BY m.date LIMIT %s""", (email, since, SUBJECT_RE, BATCH))
        rows = self.env.cr.fetchall()
        own = set()
        if rows:
            own = self.env["mail.client.message"].sudo().browse(rows[0][0])._pmk_own_addresses()
        vals = []
        for mid, subject, email_from in rows:
            address = (re.search(r"[\w.+-]+@[\w.-]+", email_from or "") or [""])[0].lower()
            state = "skipped" if address in own else "queued"
            vals.append({"message_id": mid, "subject": (subject or "")[:250],
                         "email_from": (email_from or "")[:250], "state": state,
                         "reason": _("Письмо из нашего ящика.") if state == "skipped" else False})
        if vals:
            self.sudo().create(vals)
        return len(vals)

    @api.model
    def _claim(self, free):
        stuck = self.sudo().search([("state", "=", "running"), (
            "started", "<", fields.Datetime.subtract(fields.Datetime.now(), seconds=STUCK_SEC))])
        if stuck:
            stuck.write({"state": "queued"})
        if free <= 0:
            return []
        self.env.cr.execute("""SELECT id FROM pmk_supplier_invoice WHERE state = 'queued'
                               ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED""", (free,))
        ids = [r[0] for r in self.env.cr.fetchall()]
        if ids:
            self.sudo().browse(ids).write({"state": "running", "started": fields.Datetime.now()})
        return ids

    @api.model
    def _process(self, invoice_id):
        inv = self.sudo().browse(invoice_id).exists()
        if not inv or inv.state != "running":
            return
        start = time.time()
        try:
            inv.with_context(lang="ru_RU")._run()
        except Exception as exc:  # noqa: BLE001 — один счёт не валит фон
            _logger.exception("pmk_supplier_invoice: счёт %s", inv.id)
            inv.write({"state": "error", "error": "%s: %s" % (exc.__class__.__name__, exc)})
        inv.seconds = time.time() - start

    # ─── разбор ──────────────────────────────────────────────────────────
    def _reviewer(self):
        return self.env["pmk.ai.mail.triage"].sudo()._reviewer()

    def _files(self):
        """[(имя, байты)] — загруженный файл или вложения письма."""
        self.ensure_one()
        if self.file:
            return [(self.file_name or "счёт.pdf", base64.b64decode(self.file))], []
        msg = self.message_id.sudo()
        got, failed = msg._pmk_letter_attachments()
        return [item[:2] for item in got if len(item) == 2], failed

    def _run(self):
        self.ensure_one()
        chat = self.env["pmk.ai.chat"].sudo()
        budget = float(self._param("pmk_ai.budget", "100") or 100)
        if chat._month_usage()[0] >= budget:
            self.write({"state": "queued"})
            return
        files, failed = self._files()
        if not files and failed:
            # Не скачалось с почтового сервера — сбой, а не «не счёт»: повторить кнопкой.
            self.write({"state": "error", "error": _("Вложения не скачались с почты: %s. «Распознать заново» — "
                                                     "повторить.") % "; ".join("%s — %s" % f for f in failed)[:500]})
            return
        if not files:
            self.write({"state": "skipped", "reason": _("Файлов счёта нет.")})
            return
        data, usage, error = self._ask(files, failed)
        vals = {"usage_id": usage.id, "data_json": json.dumps(data, ensure_ascii=False)}
        if error:
            self.write(dict(vals, state="error", error=error))
            return
        if not data.get("is_invoice"):
            self.write(dict(vals, state="skipped", reason=data.get("reason") or _("Не счёт на оплату.")))
            return
        if not self.file:
            # Оригинал — к документу: проверяющему не искать письмо.
            pdf = next(((n, b) for n, b in files if n.lower().endswith(".pdf")), files[0])
            vals.update(file=base64.b64encode(pdf[1]), file_name=pdf[0])
        self.write(vals)
        self._fill(data)

    def _fill(self, data):
        """Шапка и строки из ответа ассистента; сопоставление и цены — prices.py."""
        self.ensure_one()
        date = False
        try:
            date = fields.Date.to_date((data.get("date") or "")[:10]) if data.get("date") else False
        except ValueError:
            date = False
        inn = re.sub(r"\D", "", data.get("supplier_inn") or "")
        self.write({
            "supplier_name": (data.get("supplier_name") or "")[:250] or False, "supplier_inn": inn or False,
            "number": (data.get("number") or "").strip()[:60] or False, "date": date,
            "payer": (data.get("payer") or "")[:250] or False,
            "amount_total": _f(data.get("total")), "amount_vat": _f(data.get("vat")),
            "vat_rate": _f(data.get("vat_rate")), "reason": data.get("reason") or False,
        })
        self.partner_id = self._find_partner()
        dup = self.search([("id", "!=", self.id), ("partner_id", "=", self.partner_id.id),
                           ("number", "=", self.number), ("date", "=", self.date),
                           ("state", "not in", ("skipped", "error"))], limit=1) if self.number and self.partner_id else False
        if dup:
            self.write({"state": "skipped", "reason": _("Повтор счёта — уже есть %s.") % dup.name})
            return
        lines = []
        for i, row in enumerate(data.get("lines") or [], 1):
            kind = row.get("kind") if row.get("kind") in ("metal", "service", "other") else "other"
            lines.append({
                "invoice_id": self.id, "sequence": i * 10, "name": (row.get("name") or "?")[:500],
                "unit": (row.get("unit") or "")[:20], "qty": _f(row.get("qty")), "price": _f(row.get("price")),
                "amount": _f(row.get("amount")), "note": (row.get("note") or "")[:250] or False, "kind": kind,
                "catalog_name": (row.get("catalog_name") or "")[:250] or False,
                "grade_text": (row.get("grade") or "")[:60] or False,
                "length_mm": _f(row.get("length_mm")), "metres": _f(row.get("metres")),
            })
        self.line_ids.unlink()
        self.env["pmk.supplier.invoice.line"].create(lines)
        self.line_ids._pmk_match()
        self.state = "review"

    def _find_partner(self):
        """Поставщик — карточка, НА КОТОРОЙ ЛЕЖАТ ЕГО ЦЕНЫ.

        Одна фирма бывает двумя карточками (25.10.2026: цены прайса — у «АО «Металлсервис»,
        филиал Хабаровск» без ИНН, а «ООО «МЕТАЛЛСЕРВИС-ХАБАРОВСК»» с ИНН пришёл из
        МойСклада без цен). Цена на вторую карточку — второй ряд, и прайс действовал бы
        дальше. Порядок: выбор из прошлых счетов с этим ИНН (с записанными ценами) → карточка с ИНН, если у неё
        есть цены → поставщик с ценами, в названии которого слово из счёта («Металлсервис»)
        → карточка с ИНН → адрес отправителя → прошлый счёт того же отправителя."""
        Partner = self.env["res.partner"].sudo()
        SI = self.env["product.supplierinfo"].sudo()
        others = self.search([("id", "!=", self.id), ("partner_id", "!=", False)], order="id desc")
        if self.supplier_inn:
            # Только счета с записанными ценами: там поставщика подтвердил человек.
            prev = others.filtered(lambda i: i.supplier_inn == self.supplier_inn and i.state == "applied")[:1]
            if prev:
                return prev.partner_id
        by_inn = Partner.search([("vat", "=", self.supplier_inn), ("is_company", "=", True)], limit=1) \
            if self.supplier_inn else Partner
        if by_inn and SI.search_count([("partner_id", "=", by_inn.id)]):
            return by_inn
        word = self._supplier_word()
        if word:
            self.env.cr.execute("SELECT DISTINCT partner_id FROM product_supplierinfo WHERE partner_id IS NOT NULL")
            ids = [r[0] for r in self.env.cr.fetchall()]
            named = Partner.browse(ids).filtered(lambda p: p.active).filtered(lambda p: word in (p.name or "").lower().replace("ё", "е"))
            if len(named) == 1:
                return named
        if by_inn:
            return by_inn
        address = (re.search(r"[\w.+-]+@[\w.-]+", self.email_from or "") or [""])[0].lower()
        if address:
            found = Partner.search([("email", "=ilike", address)], limit=1)
            if found:
                return found.commercial_partner_id
            prev = others.filtered(lambda i: address in (i.email_from or "").lower())[:1]
            if prev:
                return prev.partner_id
        return Partner

    def _supplier_word(self):
        """Отличительное слово названия: «ООО "МЕТАЛЛСЕРВИС-ХАБАРОВСК"» → «металлсервис»."""
        name = (self.supplier_name or "").lower().replace("ё", "е")
        name = re.sub(r"\b(ооо|оао|зао|пао|ао|ип|тд|торговый дом|филиал|компания|группа)\b", " ", name)
        words = [w for w in re.split(r"[^\w]+", name) if len(w) >= 5 and not w.isdigit()]
        return words[0] if words else ""

    def _ask(self, files, failed):
        """Ассистент читает счёт. → (data, usage, error)."""
        chat = self.env["pmk.ai.chat"].sudo()
        key = chat._param("pmk_ai.api_key")
        if not key:
            raise claude.ClaudeError(_("Не задан ключ API ассистента."))
        blocks, notes = parts.build(files)
        notes += ["%s — не скачан с сервера почты" % name for name, _err in failed]
        body = ""
        msg = self.message_id.sudo()
        if msg:
            if msg.body_state != "fetched":
                try:
                    msg._fetch_body()
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("pmk_supplier_invoice: тело письма %s: %s", msg.id, exc)
            body = html2plaintext(msg._display_body() or msg.body_html or "")[:MAX_BODY_CHARS]
        head = "\n".join([
            "От: %s" % (self.email_from or ""), "Тема: %s" % (self.subject or ""),
            "Вложения: %s" % ("; ".join(notes) or "нет"), "", "Текст письма:", body or "(нет)"])
        with open(RULES_FILE, encoding="utf-8") as fh:
            rules = fh.read()
        model = chat._param("pmk_ai.model") or claude.DEFAULT_MODEL
        payload = {
            "model": model, "max_tokens": MAX_TOKENS,
            "system": [{"type": "text", "text": rules, "cache_control": {"type": "ephemeral"}}],
            # tool_choice «tool»/«any» Sonnet 5.5 не принимает (pmk_ai_mail, 20.10.2026) — auto + JSON.
            "tools": [INVOICE_TOOL], "tool_choice": {"type": "auto"},
            "messages": [{"role": "user", "content": [{"type": "text", "text": head}] + blocks + [
                {"type": "text", "text": "Ответь только вызовом инструмента invoice — без текста."}]}],
        }
        start = time.time()
        data, error = {}, False
        try:
            response, _sec = claude.messages(key, payload, chat._param("pmk_ai.api_base") or None)
        except claude.ClaudeError as exc:
            response, error = {}, str(exc)
        texts = []
        for block in (response or {}).get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == "invoice":
                data = block.get("input") or {}
            elif block.get("type") == "text":
                texts.append(block.get("text") or "")
        if not data and texts:
            found = re.search(r"\{.*\}", "\n".join(texts), re.S)
            if found:
                try:
                    data = json.loads(found.group(0))
                except ValueError:
                    data = {}
        if not data and not error:
            error = _("Ассистент не вернул разбор счёта.")
        usage_raw = (response or {}).get("usage") or {}
        reviewer = self._reviewer()
        usage = self.env["pmk.ai.usage"].sudo().create({
            "user_id": (reviewer or self.env.ref("base.user_root")).id,
            "question": ("Счёт поставщика: %s" % (self.subject or self.file_name or ""))[:200],
            "model": model, "calls": 1,
            "input_tokens": int(usage_raw.get("input_tokens") or 0),
            "output_tokens": int(usage_raw.get("output_tokens") or 0),
            "cost": chat._cost(usage_raw, model), "seconds": time.time() - start,
            "ok": bool(data) and not error, "answer": error or json.dumps(data, ensure_ascii=False)[:4000],
            "screen": "Счета поставщиков",
        })
        return data, usage, error
