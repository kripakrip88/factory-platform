# -*- coding: utf-8 -*-
"""Инструменты ассистента для действий (19.11.2026): найти письмо, прочитать его, файлы сделки,
и две карточки — «сделка из письма» и «расчёт „Конструкции“ по спецификации».

Всё правами спросившего: письма — те, что ему открыты в почте; сделка и файлы — его доступ.
Карточку выполняет человек (proposal.py → execute_proposal), сам ассистент ничего не создаёт.

Спецификация (Excel, PDF, скан) разбирается отдельным вызовом Claude: файл — теми же блоками,
что разбор почты (pmk_ai_mail/tools/parts.py), ответ — инструментом konstr со строками в записи
таблицы «Конструкции» (как вставка из Excel: № поз., наименование, длина, кол-во на изделие, марка).
"""
import base64
import json
import logging
import re
import time
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext

from odoo.addons.pmk_ai.tools import claude
from odoo.addons.pmk_ai_mail.tools import parts

_logger = logging.getLogger(__name__)

LETTERS_LIMIT = 15
BODY_CHARS = 6000
FILES_LIMIT = 30
KONSTR_TOKENS = 8000
PREVIEW_DETAILS = 12        # строк деталей в карточке; остальные — «… ещё N»
INN_RE = re.compile(r"^\d{10}(\d{2})?$")

ACTIONS_RULES = """

## Действия (карточки с подтверждением)
Создавать и менять сам ты НЕ можешь. Можешь подготовить карточку «Сделаю: …» инструментами
propose_deal (сделка и контрагент из письма) и propose_konstr (расчёт «Конструкции» в сделке по
спецификации из её файла). Карточка показывается человеку с кнопкой «Выполнить» — пока он не нажал,
ничего не сделано: так и пиши («подготовил карточку — нажмите «Выполнить»»), не «создал».
- Письмо ищи find_letters (по отправителю — имя или адрес, по теме), читай read_letter. Открыто письмо
  в почте — оно в «Открыт документ», искать не нужно.
- ИНН клиента бери из письма или подписи (10 или 12 цифр); нет ИНН — контрагента не заводим, сделка
  будет с организацией текстом. Контактное лицо — человек из подписи.
- Для расчёта: файлы сделки — deal_files, нужный файл — в propose_konstr. Один файл — одна карточка.
  Из нескольких файлов бери спецификацию (в имени «спецификация», «ведомость», «КМД»), не чертёж.
  Разбор файла не удался — так и скажи и предложи повторить; другой файл без спроса не подставляй.
- После карточки коротко скажи, что в ней и что проверить. Не повторяй её строки целиком.
"""

KONSTR_TOOL = {
    "name": "konstr",
    "description": "Спецификация → изделия и детали для таблицы «Конструкции».",
    "input_schema": {"type": "object", "properties": {
        "products": {"type": "array", "description": "Изделия (сборочные единицы, марки).", "items": {
            "type": "object", "properties": {
                "name": {"type": "string", "description": "Название изделия как в спецификации (марка, «МН 111-1», «Площадка ПО-1»)."},
                "qty": {"type": "integer", "description": "Сколько изделий, шт (нет — 1)."},
                "details": {"type": "array", "items": {"type": "object", "properties": {
                    "pos": {"type": "string", "description": "№ позиции детали."},
                    "name": {"type": "string", "description": "Наименование в записи таблицы: «Уголок 63х5», «Лист 10х60» "
                             "(толщина×ширина, длина отдельно), «Труба 57х3,5», «Швеллер 16П», «Двутавр 20Б1», "
                             "«Арматура А500С 12», «Болт М20х100». Не выдумывай размеров."},
                    "length_mm": {"type": "number", "description": "Длина детали, мм (у листа — длина пластины)."},
                    "qty": {"type": "integer", "description": "Кол-во на одно изделие, шт."},
                    "grade": {"type": "string", "description": "Марка стали как в спецификации (С345, Ст3, 09Г2С), если есть."},
                    "mass_kg": {"type": "number", "description": "Масса одной детали по спецификации, кг, если указана."}},
                    "required": ["name"]}}},
            "required": ["name", "details"]}},
        "unclear": {"type": "array", "items": {"type": "string"},
                    "description": "Строки, которые не удалось понять (с причиной) — не угадывай, перечисли здесь."},
        "note": {"type": "string", "description": "Коротко: что за спецификация, сколько изделий."}},
        "required": ["products"]},
}

KONSTR_SYSTEM = """Ты разбираешь спецификацию металлоконструкций завода в Хабаровске (КМД, ведомость деталей,
таблица заказчика) в строки таблицы «Конструкции» расчёта. Изделие — сборочная единица (марка), под ним
детали. Количество детали — на ОДНО изделие (если в спецификации «всего» — раздели на число изделий).
Длины и размеры — в мм. Наименования пиши коротко, как в прайсе: «Уголок 63х5», «Лист 10х60» + длина,
«Труба профильная 60х40х3», «Швеллер 16П». Ничего не выдумывай: непонятное — в unclear.
Ответь только вызовом инструмента konstr."""


class PmkAiChatActions(models.AbstractModel):
    _inherit = "pmk.ai.chat"

    # ─── подсказка и инструменты ────────────────────────────────────────
    def _system(self, context):
        blocks = super()._system(context)
        # Постоянный блок (с кэшем) — первый: правила действий дописываем к нему, а прежнее
        # «инструменты только читают — опиши, что нажать» заменяем: теперь есть карточки.
        text = blocks[0]["text"].replace(
            "Инструменты только читают: если нужно что-то создать или изменить — опиши, что нажать человеку.",
            "Инструменты читают; создать можно только карточкой (раздел «Действия»), иначе опиши, что нажать человеку.")
        blocks[0] = dict(blocks[0], text=text + ACTIONS_RULES)
        return blocks

    def _tools(self):
        return super()._tools() + [
            {"name": "find_letters",
             "description": "Найти письма в почте Odoo (что человеку открыто): по отправителю (имя или адрес) и/или "
                            "теме. Свежие первыми.",
             "input_schema": {"type": "object", "properties": {
                 "who": {"type": "string", "description": "Отправитель: «Лыкова», «alena@…»"},
                 "text": {"type": "string", "description": "Слова из темы или текста"},
                 "days": {"type": "integer", "minimum": 1, "maximum": 365, "description": "За сколько дней (по умолчанию 60)"}}}},
            {"name": "read_letter",
             "description": "Письмо целиком: от кого, кому, тема, текст, вложения, привязанная сделка.",
             "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
            {"name": "deal_files",
             "description": "Файлы сделки (вложения писем в сделке и прикреплённые): id, имя, размер.",
             "input_schema": {"type": "object", "properties": {"deal_id": {"type": "integer"}}, "required": ["deal_id"]}},
            {"name": "propose_deal",
             "description": "Карточка «завести сделку из письма»: контрагент (по ИНН — из справочника, или найденный в "
                            "базе), контактное лицо, сделка, письмо с файлами — в сделку. Выполняет человек.",
             "input_schema": {"type": "object", "properties": {
                 "letter_id": {"type": "integer"},
                 "title": {"type": "string", "description": "Название сделки: что и сколько («Закладные МН 111-1, 240 шт»)"},
                 "inn": {"type": "string", "description": "ИНН клиента из письма/подписи, если есть"},
                 "company": {"type": "string", "description": "Организация из письма, если ИНН нет"},
                 "contact": {"type": "string", "description": "Контактное лицо (ФИО)"},
                 "phone": {"type": "string"}},
                 "required": ["letter_id", "title"]}},
            {"name": "propose_konstr",
             "description": "Карточка «расчёт „Конструкции“ по спецификации из файла сделки»: файл разбирается в "
                            "изделия и детали (Excel, PDF, скан). Выполняет человек.",
             "input_schema": {"type": "object", "properties": {
                 "deal_id": {"type": "integer"},
                 "attachment_id": {"type": "integer", "description": "id файла из deal_files"},
                 "hint": {"type": "string", "description": "Уточнение человека: какие листы/изделия брать"}},
                 "required": ["deal_id", "attachment_id"]}},
        ]

    def _run_tool(self, name, args):
        handlers = {"find_letters": self._tool_letters, "read_letter": self._tool_read_letter,
                    "deal_files": self._tool_deal_files, "propose_deal": self._tool_propose_deal,
                    "propose_konstr": self._tool_propose_konstr}
        if name not in handlers:
            return super()._run_tool(name, args)
        try:
            return handlers[name](args or {})
        except AccessError:
            return {"ошибка": "нет доступа"}
        except UserError as exc:
            return {"ошибка": str(exc)}
        except Exception as exc:  # noqa: BLE001 — инструмент не должен ронять ответ
            _logger.warning("pmk_ai_actions: инструмент %s упал: %s", name, exc)
            return {"ошибка": "инструмент не сработал: %s" % exc.__class__.__name__}

    # ─── письма ─────────────────────────────────────────────────────────
    def _letter(self, letter_id):
        msg = self.env["mail.client.message"].browse(int(letter_id or 0)).exists()
        if not msg:
            raise UserError(_("Письмо не найдено."))
        msg.check_access("read")
        return msg

    def _letter_row(self, msg):
        return {"id": msg.id, "дата": fields.Datetime.to_string(msg.date) if msg.date else "",
                "от": msg.email_from or "", "тема": msg.subject or "",
                "файлы": msg._pmk_name_list()[:10] if hasattr(msg, "_pmk_name_list") else [],
                "сделка": {"model": "crm.lead", "id": msg.pmk_lead_id.id, "название": msg.pmk_lead_id.display_name}
                if msg.pmk_lead_id else "нет"}

    def _tool_letters(self, args):
        who, text = (args.get("who") or "").strip(), (args.get("text") or "").strip()
        days = int(args.get("days") or 60)
        domain = [("date", ">=", fields.Datetime.now() - timedelta(days=days))]
        if who:
            domain += [("email_from", "ilike", who)]
        if text:
            domain += ["|", ("subject", "ilike", text), ("preview", "ilike", text)]
        found = self.env["mail.client.message"].search(domain, order="date desc, id desc", limit=LETTERS_LIMIT)
        if not found:
            return {"результат": "писем не найдено (или ящик вам не открыт)"}
        return {"писем": len(found), "письма": [self._letter_row(m) for m in found]}

    def _tool_read_letter(self, args):
        msg = self._letter(args.get("id"))
        if msg.body_state != "fetched":
            try:
                msg._fetch_body()
            except Exception as exc:  # noqa: BLE001 — нет текста — хотя бы шапка
                _logger.info("pmk_ai_actions: тело письма %s: %s", msg.id, exc)
        body = html2plaintext(msg._display_body() or msg.body_html or "")
        row = self._letter_row(msg)
        row.update({"кому": msg.email_to or "", "текст": body[:BODY_CHARS] + ("…" if len(body) > BODY_CHARS else "")})
        return row

    # ─── файлы сделки ───────────────────────────────────────────────────
    def _deal(self, deal_id):
        deal = self.env["crm.lead"].browse(int(deal_id or 0)).exists()
        if not deal:
            raise UserError(_("Сделка не найдена."))
        deal.check_access("read")
        return deal

    def _deal_attachments(self, deal):
        return self.env["ir.attachment"].search(
            [("res_model", "=", "crm.lead"), ("res_id", "=", deal.id)], order="id desc", limit=FILES_LIMIT)

    def _tool_deal_files(self, args):
        deal = self._deal(args.get("deal_id"))
        files = self._deal_attachments(deal)
        if not files:
            return {"результат": "у сделки нет файлов"}
        return {"сделка": deal.display_name, "файлы": [
            {"id": f.id, "имя": f.name, "КБ": round((f.file_size or 0) / 1024)} for f in files]}

    # ─── карточка: сделка из письма ─────────────────────────────────────
    def _tool_propose_deal(self, args):
        msg = self._letter(args.get("letter_id"))
        if msg.pmk_lead_id:
            return {"ошибка": "письмо уже в сделке %s — новую не заводим" % msg.pmk_lead_id.display_name,
                    "сделка": {"model": "crm.lead", "id": msg.pmk_lead_id.id}}
        title = (args.get("title") or msg.subject or "").strip()[:120]
        inn = re.sub(r"\D", "", args.get("inn") or "")
        company = (args.get("company") or "").strip()
        contact = (args.get("contact") or "").strip()
        lines, warn = [], ""
        payload = {"letter_id": msg.id, "title": title, "contact": contact, "phone": (args.get("phone") or "").strip()}
        if inn and not INN_RE.match(inn):
            warn = "ИНН «%s» не похож на ИНН — контрагента не завожу" % inn
            inn = ""
        partner = self.env["res.partner"]
        if inn:
            partner = partner.search([("vat", "=", inn), ("is_company", "=", True)], limit=1)
            if partner:
                payload["partner_id"] = partner.id
                lines.append(["Контрагент", "%s, ИНН %s — уже в базе" % (partner.display_name, inn)])
            else:
                try:
                    data = self.env["res.partner"]._pmk_dadata_find(inn)
                    values, _state = self.env["res.partner"]._pmk_dadata_values(data)
                    payload.update(inn=inn, company=values.get("name") or company)
                    lines.append(["Контрагент", "%s, ИНН %s — заведу новым (из справочника)" % (
                        values.get("name") or company or "?", inn)])
                except UserError as exc:
                    warn = "Справочник по ИНН %s: %s" % (inn, exc)
                    payload["company"] = company
                    lines.append(["Контрагент", "%s — текстом в сделке (справочник не ответил)" % (company or "?")])
        else:
            payload["company"] = company
            lines.append(["Контрагент", "%s — текстом в сделке, без карточки (нет ИНН)" % company if company
                          else "по адресу письма, как кнопка «Лид» в почте"])
        if contact:
            lines.append(["Контакт", ", ".join(x for x in (contact, msg.email_from or "", payload["phone"]) if x)])
        lines.append(["Сделка", title or _("по теме письма")])
        files = msg._pmk_name_list() if hasattr(msg, "_pmk_name_list") else []
        lines.append(["Письмо", "привяжу к сделке" + (", файлы (%d) — в сделку" % len(files) if files else "")])
        return self._new_proposal("deal", _("Сделка из письма «%s»") % (msg.subject or "")[:80], lines, payload, warn)

    @api.model
    def _do_deal(self, payload):
        msg = self._letter(payload.get("letter_id"))
        if msg.pmk_lead_id:
            raise UserError(_("Письмо уже в сделке %s.") % msg.pmk_lead_id.display_name)
        Partner = self.env["res.partner"]
        company = Partner.browse(int(payload.get("partner_id") or 0)).exists()
        if not company and payload.get("inn"):
            company = Partner.search([("vat", "=", payload["inn"]), ("is_company", "=", True)], limit=1)
            if not company:
                values, _state = Partner._pmk_dadata_values(Partner._pmk_dadata_find(payload["inn"]))
                values = {k: v for k, v in values.items() if v and k in Partner._fields}
                company = Partner.create(dict(values, is_company=True, vat=payload["inn"],
                                              name=values.get("name") or payload.get("company") or payload["inn"]))
        person = Partner
        if company and payload.get("contact"):
            from odoo.addons.pmk_mail_ui.tools import lead_text
            _sender, address = lead_text.split_sender(msg.email_from)
            person = company.child_ids.filtered(lambda p: address and (p.email or "").lower() == address.lower())[:1]
            if not person:
                person = Partner.create({"name": payload["contact"], "parent_id": company.id, "type": "contact",
                                         "email": address or False, "phone": payload.get("phone") or False})
        overrides = {"name": payload.get("title") or msg.subject}
        if company:
            overrides["partner_id"] = (person or company).id
        if payload.get("phone"):
            overrides["phone"] = payload["phone"]
        if payload.get("contact"):
            overrides["contact_name"] = payload["contact"]
        lead = msg._pmk_create_lead(overrides)
        vals = {"type": "opportunity"}
        if not company and payload.get("company") and not lead.partner_id:
            vals["partner_name"] = payload["company"][:120]
        lead.write(vals)
        if msg.pmk_lead_id != lead:
            msg.pmk_lead_id = lead.id
        lead.message_post(body=_("Сделку завёл ассистент по просьбе %s (карточка подтверждена).") % self.env.user.name,
                          message_type="comment", subtype_xmlid="mail.mt_note")
        return "crm.lead", lead.id, lead.display_name

    # ─── карточка: расчёт «Конструкции» по спецификации ──────────────────
    def _tool_propose_konstr(self, args):
        deal = self._deal(args.get("deal_id"))
        att = self.env["ir.attachment"].browse(int(args.get("attachment_id") or 0)).exists()
        if not att or att.res_model != "crm.lead" or att.res_id != deal.id:
            return {"ошибка": "это не файл этой сделки — возьми id из deal_files"}
        att.check_access("read")
        blob = base64.b64decode(att.datas or b"")
        if not blob:
            return {"ошибка": "файл пустой"}
        # Сколько изделий — часто только в заявке («блоки Бб1 30 компл.»), в самой спецификации нет.
        hint = "; ".join(x for x in ((args.get("hint") or "").strip(), "сделка: %s" % deal.name) if x)
        data = self._konstr_extract(att.name or "spec", blob, hint)
        if not (data.get("products") or []):
            data = self._konstr_extract(att.name or "spec", blob, hint)   # разовый сбой ответа — ещё раз
        products = [p for p in (data.get("products") or []) if (p.get("name") or "").strip()]
        if not products:
            return {"ошибка": "в файле не нашлось изделий и деталей", "не понял": data.get("unclear") or []}
        lines, shown, total = [], 0, 0
        for prod in products:
            details = prod.get("details") or prod.get("parts") or []
            prod["details"] = details
            total += len(details)
            lines.append([prod["name"][:60], "%s шт · деталей %d" % (int(prod.get("qty") or 1), len(details))])
            for det in details:
                if shown >= PREVIEW_DETAILS:
                    continue
                shown += 1
                bits = [det.get("name") or "?"]
                if det.get("length_mm"):
                    bits.append("L=%s" % _num(det["length_mm"]))
                bits.append("%s шт" % int(det.get("qty") or 1))
                if det.get("grade"):
                    bits.append(det["grade"])
                lines.append(["  " + (det.get("pos") or "·"), " · ".join(bits)])
        if total > shown:
            lines.append(["", "… ещё %d строк — все попадут в расчёт" % (total - shown)])
        unclear = data.get("unclear") or []
        warn = ("Не понял %d стр.: %s" % (len(unclear), "; ".join(unclear[:3]))) if unclear else ""
        payload = {"deal_id": deal.id, "file": att.name, "products": products, "unclear": unclear}
        title = _("Расчёт «Конструкции» по %s: изделий %d, строк %d") % (att.name, len(products), total)
        return self._new_proposal("konstr", title, lines, payload, warn)

    def _konstr_extract(self, name, blob, hint=""):
        """Файл → {products, unclear, note} отдельным вызовом Claude; расход — в pmk.ai.usage."""
        key = self._param("pmk_ai.api_key")
        if not key:
            raise UserError(_("Не задан ключ API ассистента."))
        blocks, notes = parts.build([(name, blob)])
        if not blocks:
            raise UserError(_("Файл не читается: %s") % ("; ".join(notes) or name))
        ask = "Спецификация из файла «%s» (%s). Разбери её в изделия и детали." % (name, "; ".join(notes))
        if hint:
            ask += ("\nКонтекст: %s. Количество изделий бери отсюда, если в файле его нет." % hint)
        model = self._param("pmk_ai.model") or claude.DEFAULT_MODEL
        payload = {"model": model, "max_tokens": KONSTR_TOKENS,
                   "system": [{"type": "text", "text": KONSTR_SYSTEM}],
                   "tools": [KONSTR_TOOL], "tool_choice": {"type": "auto"},
                   "messages": [{"role": "user", "content": [{"type": "text", "text": ask}] + blocks}]}
        started, data, error = time.time(), {}, ""
        try:
            response, _sec = claude.messages(key, payload, base=self._param("pmk_ai.api_base") or None)
        except claude.ClaudeError as exc:
            response, error = {}, str(exc)
        for block in (response or {}).get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == "konstr":
                data = block.get("input") or {}
        if not data:
            text = "".join(b.get("text", "") for b in (response or {}).get("content") or [] if b.get("type") == "text")
            found = re.search(r"\{.*\}", text, re.S)
            if found:
                try:
                    data = json.loads(found.group(0))
                except ValueError:
                    data = {}
        usage = (response or {}).get("usage") or {}
        self.env["pmk.ai.usage"].sudo().create({
            "user_id": self.env.uid, "question": ("Спецификация: %s" % name)[:200], "model": model, "calls": 1,
            "input_tokens": int(usage.get("input_tokens") or 0), "output_tokens": int(usage.get("output_tokens") or 0),
            "cost": self._cost(usage, model), "seconds": time.time() - started, "ok": bool(data) and not error,
            "answer": (error or json.dumps(data, ensure_ascii=False))[:4000], "screen": "Расчёт по спецификации"})
        if error:
            raise UserError(error)
        return data

    @api.model
    def _do_konstr(self, payload):
        deal = self._deal(payload.get("deal_id"))
        deal.check_access("write")
        Spec = self.env["pmk.metal.spec"].with_context(**deal._pmk_spec_defaults())
        spec = Spec.create({})
        Product = self.env["pmk.metal.spec.product"]
        for number, prod in enumerate(payload.get("products") or [], 1):
            product = Product.create({"spec_id": spec.id, "name": (prod.get("name") or _("Изделие %d") % number)[:120],
                                      "qty": max(int(prod.get("qty") or 1), 1), "sequence": number * 10})
            rows = []
            for det in prod.get("details") or []:
                name = (det.get("name") or "").strip()
                if not name:
                    continue
                if det.get("mass_kg") and "кг" not in name:
                    # Масса по КМ — токеном «14,2кг» (pmk_butik/tools/parse.py, MASS_RE): слитно.
                    name = "%s %sкг" % (name, _num(det["mass_kg"]))
                rows.append({"pos": det.get("pos") or "", "name": name,
                             "length_mm": _num(det["length_mm"]) if det.get("length_mm") else "",
                             "qty": str(max(int(det.get("qty") or 1), 1)), "grade": det.get("grade") or ""})
            if rows:
                spec.konstr_insert_rows("p%d" % product.id, rows)
        note = [_("Расчёт %s создал ассистент по файлу «%s» (карточка подтверждена %s).") % (
            spec.name, payload.get("file") or "", self.env.user.name)]
        if payload.get("unclear"):
            note.append(_("Не понял: %s") % "; ".join(payload["unclear"][:10]))
        spec.message_post(body=Markup("<br/>").join(note), message_type="comment", subtype_xmlid="mail.mt_note")
        return "pmk.metal.spec", spec.id, spec.display_name


def _num(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(value)) if value == int(value) else ("%g" % value).replace(".", ",")
