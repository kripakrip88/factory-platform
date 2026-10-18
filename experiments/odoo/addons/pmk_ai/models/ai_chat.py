# -*- coding: utf-8 -*-
"""Панель ассистента (18.10.2026): вопрос → Claude → ответ, только чтение.

Антон 18.10: «ассистент давай попробуем сделать сейчас»; прототип панели принят («кайф. пусть
сотрудники видят лимиты и расходы»). Правила — из knowledge/00_core.md, он целиком идёт в
системную подсказку; тематические документы добавятся туда же.

Что умеет первая версия:
  • видит открытый документ (модель и id приходят из браузера, читаем от имени человека);
  • инструменты только на чтение: поиск по сделкам, расчётам, заказам, заявкам, счетам,
    контрагентам, номенклатуре, заданиям лазеру; карточка записи; цены поставщиков;
  • всё — правами спросившего (без sudo): нет доступа — инструмент так и отвечает;
  • расход: строка pmk.ai.usage на вопрос (токены, $), месячный лимит из настроек.

Один вопрос за раз на весь сервер: у Odoo 2 рабочих процесса, а вопрос держит процесс
10–60 с (канал к API медленный). Второй одновременный вопрос получает «ассистент занят».
"""
import json
import logging
import os
import time
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..tools import claude

_logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge")
LOCK_KEY = 7718001          # pg_advisory: один вопрос за раз
MAX_CALLS = 5               # вызовов API на вопрос (с инструментами)
TIME_BUDGET = 170           # секунд на вопрос: limit_time_real у Odoo — 240
MAX_TOKENS = 2000
HISTORY = 10                # последних реплик из браузера

# Что ассистент может искать: ключ инструмента → (модель, домен, подпись).
KINDS = {
    "deal": ("crm.lead", [], "сделка / лид"),
    "spec": ("pmk.metal.spec", [], "расчёт металлопроката (СМ-…)"),
    "order": ("project.task", [("pmk_is_order", "=", True)], "заказ в работе"),
    "metal_request": ("purchase.order", [("pmk_tech_spec_id", "!=", False)], "заявка на металл"),
    "purchase": ("purchase.order", [], "заказ поставщику"),
    "invoice": ("sale.order", [], "счёт покупателю"),
    "partner": ("res.partner", [], "контрагент"),
    "product": ("product.template", [], "номенклатура"),
    "laser_task": ("pmk.laser.task", [], "задание лазеру (ЗР-…)"),
}
SKIP_FIELDS = {"id", "display_name", "create_uid", "write_uid", "write_date", "__last_update",
               "company_id", "currency_id", "access_token", "access_url", "color", "sequence"}
SKIP_PREFIX = ("message_", "activity_", "website_", "_", "rating_", "pmk_ai_")
SCALAR = ("char", "selection", "many2one", "monetary", "float", "integer", "date", "datetime", "boolean", "text")


def _text(value, limit=300):
    value = "" if value is None else str(value)
    return value if len(value) <= limit else value[:limit] + "…"


class PmkAiUsage(models.Model):
    _name = "pmk.ai.usage"
    _description = "Расход ассистента"
    _order = "id desc"

    user_id = fields.Many2one("res.users", "Кто спросил", required=True, index=True, ondelete="cascade")
    question = fields.Char("Вопрос")
    model = fields.Char("Модель")
    calls = fields.Integer("Вызовов API")
    input_tokens = fields.Integer("Токенов на входе")
    output_tokens = fields.Integer("Токенов на выходе")
    cost = fields.Float("Стоимость, $", digits=(10, 4))
    seconds = fields.Float("Секунд", digits=(10, 1))
    ok = fields.Boolean("Ответ получен")


class PmkAiChat(models.AbstractModel):
    _name = "pmk.ai.chat"
    _description = "Ассистент: вопросы и ответы"

    # ─── настройки и расход ─────────────────────────────────────────────
    def _param(self, key, default=None):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _month_usage(self):
        today = fields.Date.context_today(self)
        start = date(today.year, today.month, 1)
        rows = self.env["pmk.ai.usage"].sudo().search_read(
            [("create_date", ">=", fields.Datetime.to_datetime(start))], ["cost", "user_id"])
        return (sum(r["cost"] for r in rows), len(rows),
                len([r for r in rows if r["user_id"] and r["user_id"][0] == self.env.uid]))

    @api.model
    def get_status(self):
        spent, total, mine = self._month_usage()
        budget = float(self._param("pmk_ai.budget", "100") or 100)
        months = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь",
                  "октябрь", "ноябрь", "декабрь")
        return {"configured": bool(self._param("pmk_ai.api_key")), "spent": round(spent, 2),
                "budget": budget, "questions": total, "mine": mine,
                "month": months[fields.Date.context_today(self).month - 1],
                "over": spent >= budget}

    def _cost(self, usage):
        pin = float(self._param("pmk_ai.price_in", "3") or 3)
        pout = float(self._param("pmk_ai.price_out", "15") or 15)
        return (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout) / 1e6

    # ─── системная подсказка ────────────────────────────────────────────
    def _knowledge(self):
        parts = []
        if os.path.isdir(KNOWLEDGE_DIR):
            for name in sorted(os.listdir(KNOWLEDGE_DIR)):
                if name.endswith(".md"):
                    with open(os.path.join(KNOWLEDGE_DIR, name), encoding="utf-8") as fh:
                        parts.append(fh.read())
        return "\n\n".join(parts)

    def _system(self, context):
        today = fields.Date.context_today(self)
        screen = ""
        if context and context.get("model") and context.get("id"):
            brief = self._brief(context["model"], int(context["id"]))
            screen = "\n\n## Открыт документ\n" + json.dumps(brief, ensure_ascii=False)
        elif context and context.get("title"):
            screen = "\n\n## Открыт экран\n" + _text(context.get("title"), 120)
        return (self._knowledge()
                + "\n\n## Сейчас\nСегодня %s. Спрашивает: %s." % (today.strftime("%d.%m.%Y"), self.env.user.name)
                + "\n\n## Формат ответа\nMarkdown: **жирный**, списки «- », таблицы «| … |» (не шире 4 колонок — панель узкая). Ссылку на документ пиши так: "
                  "[СД-0112](rec:crm.lead:12) — модель и id бери из результатов инструментов. "
                  "Инструменты только читают: если нужно что-то создать или изменить — опиши, что "
                  "нажать человеку. Не выдумывай данных: нет в инструментах — так и скажи."
                + screen)

    # ─── чтение записей (права спросившего) ─────────────────────────────
    def _readable_fields(self, Model):
        out = []
        for name, field in Model._fields.items():
            if name in SKIP_FIELDS or name.startswith(SKIP_PREFIX) or field.type not in SCALAR + ("one2many", "many2many"):
                continue
            if field.groups and not self.env.user.has_groups(field.groups):
                continue
            if field.type in ("one2many", "many2many") and not field.store:
                continue
            out.append(name)
        return out

    def _brief(self, model, res_id):
        if model not in self.env:
            return {"ошибка": "нет такого раздела"}
        Model = self.env[model]
        try:
            rec = Model.browse(res_id).exists()
            if not rec:
                return {"ошибка": "запись не найдена"}
            rec.check_access("read")
        except AccessError:
            return {"ошибка": "нет доступа"}
        brief = {"модель": model, "id": rec.id, "название": rec.display_name}
        for name in self._readable_fields(Model):
            field = Model._fields[name]
            try:
                value = rec[name]
            except AccessError:
                continue
            if field.type in ("one2many", "many2many"):
                if value:
                    names = value[:15].mapped("display_name")
                    brief[field._description_string(self.env)] = names + (["… ещё %d" % (len(value) - 15)] if len(value) > 15 else [])
                continue
            if value in (False, None, "", 0, 0.0) and field.type != "boolean":
                continue
            if field.type == "many2one":
                value = value.display_name
            elif field.type == "selection":
                value = dict(field._description_selection(self.env)).get(value, value)
            elif field.type in ("date", "datetime"):
                value = fields.Date.to_string(value) if field.type == "date" else fields.Datetime.to_string(value)
            brief[field._description_string(self.env)] = _text(value)
            if len(brief) > 60:
                break
        return brief

    # ─── инструменты ────────────────────────────────────────────────────
    def _tools(self):
        kinds = ", ".join("%s — %s" % (k, v[2]) for k, v in KINDS.items())
        return [
            {"name": "search_records",
             "description": "Найти записи по названию/номеру или последние изменённые. Виды: " + kinds,
             "input_schema": {"type": "object", "properties": {
                 "kind": {"type": "string", "enum": list(KINDS)},
                 "text": {"type": "string", "description": "Номер, название, клиент. Пусто — последние."},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                 "required": ["kind"]}},
            {"name": "read_record",
             "description": "Карточка записи: поля и связанные строки. Модель и id — из search_records.",
             "input_schema": {"type": "object", "properties": {
                 "model": {"type": "string"}, "id": {"type": "integer"}}, "required": ["model", "id"]}},
            {"name": "supplier_prices",
             "description": "Цены поставщиков по позиции номенклатуры (прокат, лист, метизы): поставщик, "
                            "цена за единицу и за тонну, дата прайса. Нет строк — в прайсах Хабаровска нет.",
             "input_schema": {"type": "object", "properties": {
                 "text": {"type": "string", "description": "Например «уголок 63x5» или «лист 10 мм»"}},
                 "required": ["text"]}},
        ]

    def _run_tool(self, name, args):
        try:
            if name == "search_records":
                return self._tool_search(args.get("kind"), args.get("text") or "", int(args.get("limit") or 8))
            if name == "read_record":
                if args.get("model") not in {v[0] for v in KINDS.values()}:
                    return {"ошибка": "этот раздел ассистенту не открыт"}
                return self._brief(args.get("model"), int(args.get("id") or 0))
            if name == "supplier_prices":
                return self._tool_prices(args.get("text") or "")
        except AccessError:
            return {"ошибка": "нет доступа"}
        except Exception as exc:  # инструмент не должен ронять ответ
            _logger.warning("pmk_ai: инструмент %s упал: %s", name, exc)
            return {"ошибка": "инструмент не сработал: %s" % exc.__class__.__name__}
        return {"ошибка": "нет такого инструмента"}

    def _tool_search(self, kind, text, limit):
        if kind not in KINDS:
            return {"ошибка": "нет такого вида"}
        model, domain, _label = KINDS[kind]
        if model not in self.env:
            return {"ошибка": "раздел не установлен"}
        Model = self.env[model]
        if not Model.has_access("read"):
            return {"ошибка": "нет доступа"}
        limit = max(1, min(limit, 20))
        if any(f not in Model._fields for f, *_x in domain):
            domain = []
        if text:
            recs = Model.browse([r[0] for r in Model.name_search(text, domain, limit=limit)])
            if not recs and "partner_id" in Model._fields:
                recs = Model.search(domain + [("partner_id", "ilike", text)], limit=limit, order="write_date desc")
        else:
            recs = Model.search(domain, limit=limit, order="write_date desc")
        out = []
        for rec in recs:
            row = {"model": model, "id": rec.id, "название": rec.display_name}
            for f in ("partner_id", "stage_id", "state", "user_id", "amount_total", "expected_revenue", "date_deadline"):
                if f in rec._fields and rec[f]:
                    value = rec[f]
                    row[rec._fields[f]._description_string(self.env)] = value.display_name if hasattr(value, "display_name") else _text(value, 60)
            out.append(row)
        return {"найдено": len(out), "записи": out}

    def _tool_prices(self, text):
        Tmpl = self.env["product.template"]
        tmpls = Tmpl.browse([r[0] for r in Tmpl.name_search(text, [("purchase_ok", "=", True)], limit=5)])
        today = fields.Date.context_today(self)
        out = []
        for tmpl in tmpls:
            sellers = tmpl.seller_ids.filtered(
                lambda s: (not s.date_start or s.date_start <= today) and (not s.date_end or s.date_end >= today)
                and not s.min_qty)
            rows = []
            for s in sellers.sorted("price_discounted")[:6]:
                row = {"поставщик": s.partner_id.display_name, "цена": round(s.price, 2),
                       "единица": s.product_uom_id.name, "прайс от": fields.Date.to_string(s.date_start)}
                if "pmk_price_ton" in s._fields and s.pmk_price_ton:
                    row["₽/т"] = round(s.pmk_price_ton)
                rows.append(row)
            out.append({"позиция": tmpl.display_name, "model": "product.template", "id": tmpl.id,
                        "цены": rows or "нет в прайсах — в городе не возят"})
        return {"позиций": len(out), "результат": out} if out else {"результат": "в номенклатуре не найдено"}

    # ─── вопрос ─────────────────────────────────────────────────────────
    @api.model
    def ask(self, question, history=None, context=None):
        question = (question or "").strip()
        if not question:
            raise UserError(_("Пустой вопрос."))
        status = self.get_status()
        if not status["configured"]:
            return {"error": "Ассистент не подключён: администратор вписывает ключ в «Настройки → Ассистент».",
                    "status": status}
        if status["over"]:
            return {"error": "Лимит месяца исчерпан: %.2f $ из %.0f $. Новый месяц — новый лимит; поднять — "
                             "«Настройки → Ассистент»." % (status["spent"], status["budget"]), "status": status}
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK_KEY,))
        if not self.env.cr.fetchone()[0]:
            return {"error": "Ассистент сейчас отвечает другому сотруднику — повторите через минуту.",
                    "status": status}

        messages = []
        for item in (history or [])[-HISTORY:]:
            if item.get("role") in ("user", "assistant") and item.get("text"):
                messages.append({"role": item["role"], "content": _text(item["text"], 4000)})
        messages.append({"role": "user", "content": question})
        model = self._param("pmk_ai.model") or claude.DEFAULT_MODEL
        payload = {"model": model, "max_tokens": MAX_TOKENS, "system": self._system(context or {}),
                   "tools": self._tools(), "messages": messages}
        totals = {"input_tokens": 0, "output_tokens": 0}
        started, calls, answer, error = time.time(), 0, "", ""
        try:
            while calls < MAX_CALLS:
                data, _sec = claude.messages(self._param("pmk_ai.api_key"), payload,
                                             base=self._param("pmk_ai.api_base"))
                calls += 1
                usage = data.get("usage") or {}
                for key in totals:
                    totals[key] += int(usage.get(key) or 0)
                content = data.get("content") or []
                answer = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
                uses = [b for b in content if b.get("type") == "tool_use"]
                if data.get("stop_reason") != "tool_use" or not uses:
                    break
                if time.time() - started > TIME_BUDGET:
                    answer = (answer + "\n\n" if answer else "") + "_Не успел досмотреть всё — уточните вопрос._"
                    break
                payload["messages"].append({"role": "assistant", "content": content})
                payload["messages"].append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": b["id"],
                     "content": json.dumps(self._run_tool(b.get("name"), b.get("input") or {}),
                                           ensure_ascii=False, default=str)[:20000]} for b in uses]})
        except claude.ClaudeError as exc:
            error = str(exc)
        seconds = time.time() - started
        self.env["pmk.ai.usage"].sudo().create({
            "user_id": self.env.uid, "question": _text(question, 200), "model": model, "calls": calls,
            "input_tokens": totals["input_tokens"], "output_tokens": totals["output_tokens"],
            "cost": self._cost(totals), "seconds": seconds, "ok": bool(answer) and not error})
        result = {"status": self.get_status(), "seconds": round(seconds, 1)}
        if error:
            result["error"] = error
        else:
            result["answer"] = answer or "Ответ пустой — переформулируйте вопрос."
        return result
