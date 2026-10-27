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

Вопрос — в фоне (18.10.2026, правило Антона «доработка не должна замедлять систему»): Odoo
только ставит вопрос в очередь pmk.ai.request и сразу освобождает процесс (у боевого их 2, а
вопрос к API идёт 10–60 с); отвечает отдельный контейнер odoo-ai-worker (worker/ai_worker.py,
до WORKER_THREADS вопросов параллельно), панель раз в 1,5 с спрашивает poll(). У одного
человека — один вопрос за раз.
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
WORKER_THREADS = 4          # вопросов параллельно в фоновом процессе
WORKER_ALIVE_SEC = 60       # нет отметки фонового процесса дольше — «ассистент не запущен»
STUCK_SEC = 300             # вопрос «в работе» дольше — ошибка (процесс перезапускали)
MAX_CALLS = 6               # вызовов API на вопрос; последний — без инструментов, только ответ
TIME_BUDGET = 170           # секунд на вопрос: limit_time_real у Odoo — 240
MAX_TOKENS = 2000
HISTORY = 6                 # последних пар «вопрос–ответ» диалога в историю для модели
USER_INFLIGHT = 3           # вопросов в работе у одного человека (по разным диалогам)
# Цены Anthropic, $ за 1 млн токенов: вход, выход, запись в кэш (5 мин), чтение из кэша.
# Сверено с platform.claude.com/docs/en/about-claude/pricing 18.10.2026. Модель не из
# таблицы — цены входа/выхода из «Настройки → Ассистент».
MODEL_PRICES = {
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.10),
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}

# Что ассистент может искать: ключ → модель, домен, подпись, поля строки, сумма, стадия, дата.
# Поля строки — суммы, сроки, просрочка: без них выводы «по названиям» (разбор 18.10).
KINDS = {
    "deal": ("crm.lead", [], "сделка / лид",
             ["partner_id", "stage_id", "expected_revenue", "user_id", "create_date"], "expected_revenue", "stage_id", "create_date"),
    "spec": ("pmk.metal.spec", [], "расчёт металлопроката (СМ-…)",
             ["partner_id", "date", "total_weight_t", "price_customer_total", "total_cost_fact"], "price_customer_total", None, "date"),
    "order": ("project.task", [("pmk_is_order", "=", True)], "заказ в работе",
              ["partner_id", "stage_id", "pmk_date_due", "pmk_overdue"], None, "stage_id", "pmk_date_due"),
    "metal_request": ("purchase.order", [("pmk_tech_spec_id", "!=", False)], "заявка на металл",
                      ["partner_id", "state", "amount_total", "date_planned", "pmk_metal_date"], "amount_total", "state", "date_order"),
    "purchase": ("purchase.order", [], "заказ поставщику",
                 ["partner_id", "state", "amount_total", "date_planned"], "amount_total", "state", "date_order"),
    "invoice": ("sale.order", [], "счёт покупателю",
                ["partner_id", "state", "amount_total", "date_order", "user_id"], "amount_total", "state", "date_order"),
    "partner": ("res.partner", [], "контрагент", ["city", "phone", "email", "user_id"], None, None, "create_date"),
    "product": ("product.template", [], "номенклатура", ["default_code", "categ_id"], None, None, None),
    "laser_task": ("pmk.laser.task", [], "задание лазеру (ЗР-…)",
                   ["partner_id", "state", "date_due", "sheets_total", "sheets_cut"], None, "state", "date_due"),
}
SEARCH_LIMIT = 50
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
    # Для разбора качества (Антон 18.10: «посмотри запрос и его ответ»): что ответил и где спросили.
    answer = fields.Text("Ответ")
    screen = fields.Char("Экран")
    # Оценка ответа (Антон 18.10: «записываешь все замечания… чтоб его можно было обучить») —
    # 👍/👎 и комментарий под ответом; разбор переносится в knowledge/90_remarks.md.
    rating = fields.Selection([("good", "👍"), ("bad", "👎")], "Оценка")
    feedback = fields.Text("Замечание")


class PmkAiThread(models.Model):
    _name = "pmk.ai.thread"
    _description = "Ассистент: диалог"
    _order = "last_date desc, id desc"

    # Диалоги (Антон 18.10: «нужно чтоб подгружала и можно было вернуться к старому диалогу…
    # менеджер может весь день вести диалог с ассистентом параллельно по нескольким вопросам»).
    user_id = fields.Many2one("res.users", "Чей", required=True, index=True, ondelete="cascade")
    name = fields.Char("Диалог", required=True)
    last_date = fields.Datetime("Последний вопрос", index=True)
    active = fields.Boolean(default=True)
    request_ids = fields.One2many("pmk.ai.request", "thread_id", "Вопросы")


class PmkAiRequest(models.Model):
    _name = "pmk.ai.request"
    _description = "Ассистент: вопрос в очереди"
    _order = "id desc"

    user_id = fields.Many2one("res.users", "Кто спросил", required=True, index=True, ondelete="cascade")
    question = fields.Text("Вопрос", required=True)
    history = fields.Text("История (JSON)")
    context_json = fields.Text("Экран (JSON)")
    state = fields.Selection([("queued", "В очереди"), ("running", "Отвечает"), ("done", "Готово"),
                              ("error", "Ошибка")], default="queued", required=True, index=True)
    answer = fields.Text("Ответ")
    seconds = fields.Float("Секунд", digits=(10, 1))
    started = fields.Datetime("Начат")
    usage_id = fields.Many2one("pmk.ai.usage", "Расход", ondelete="set null")
    thread_id = fields.Many2one("pmk.ai.thread", "Диалог", index=True, ondelete="cascade")
    # 27.10.2026: «Связь с ИИ плохая — пробую ещё…» — пишет фон, пока идёт повтор; видно в окне.
    note = fields.Char("Состояние связи")


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

    def _cost(self, usage, model=None):
        prices = MODEL_PRICES.get(model or "")
        if not prices:
            pin = float(self._param("pmk_ai.price_in", "2") or 2)
            pout = float(self._param("pmk_ai.price_out", "10") or 10)
            prices = (pin, pout, pin * 1.25, pin * 0.05)
        pin, pout, pwrite, pread = prices
        return (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout
                + usage.get("cache_creation_input_tokens", 0) * pwrite
                + usage.get("cache_read_input_tokens", 0) * pread) / 1e6

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
        """Два блока: постоянный (знания + формат) — с кэшем Anthropic, повтор стоит 5 % цены
        входа; переменный (дата, кто спрашивает, открытый экран) — без кэша."""
        today = fields.Date.context_today(self)
        screen = ""
        if context and context.get("model") and context.get("id"):
            brief = self._brief(context["model"], int(context["id"]))
            screen = "\n\n## Открыт документ\n" + json.dumps(brief, ensure_ascii=False)
        elif context and context.get("title"):
            screen = "\n\n## Открыт экран\n" + _text(context.get("title"), 120)
        static = (self._knowledge()
                + "\n\n## Формат ответа\nMarkdown: **жирный**, списки «- », таблицы «| … |» (не шире 4 колонок — панель узкая). Ссылку на документ пиши так: "
                  "[СД-0112](rec:crm.lead:12) — модель и id бери из результатов инструментов. "
                  "Инструменты только читают: если нужно что-то создать или изменить — опиши, что "
                  "нажать человеку. Не выдумывай данных: нет в инструментах — так и скажи.")
        now = "## Сейчас\nСегодня %s. Спрашивает: %s." % (today.strftime("%d.%m.%Y"), self.env.user.name) + screen
        return [{"type": "text", "text": static, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": now}]

    # ─── чтение записей (права спросившего) ─────────────────────────────
    def _form_fields(self, Model):
        """Поля, которые человек видит на форме записи. Всё прочее — служебное Odoo
        («есть сообщение», «чёрный список», «смещение часового пояса»): ассистенту оно
        только забивает внимание и съедает токены (разбор ответа 18.10)."""
        try:
            from lxml import etree
            arch = etree.fromstring(Model.get_view(view_type="form")["arch"])
            names = []
            for node in arch.iter("field"):
                name = node.get("name")
                if name and name not in names and node.get("invisible") not in ("1", "True"):
                    names.append(name)
            return names
        except Exception:
            return []

    def _readable_fields(self, Model):
        on_form = set(self._form_fields(Model))
        out = []
        for name, field in Model._fields.items():
            if on_form and name not in on_form:
                continue
            if field.type == "boolean" and name not in on_form:
                continue
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
            if value in (False, None, "", 0, 0.0):
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
             "description": "Найти записи (до 50) с суммами и сроками. «всего» — сколько подходит во всей "
                            "базе: если больше показанных, уточни отбор или возьми summary. Виды: " + kinds,
             "input_schema": {"type": "object", "properties": {
                 "kind": {"type": "string", "enum": list(KINDS)},
                 "text": {"type": "string", "description": "Номер, название, клиент. Пусто — все."},
                 "stage": {"type": "string", "description": "Стадия/статус словом: «металл», «чертежи», «выиграно», «черновик»…"},
                 "overdue": {"type": "boolean", "description": "Только просроченные (заказы в работе)"},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
                 "required": ["kind"]}},
            {"name": "summary",
             "description": "Сводка по ВСЕЙ базе без лимита: количество и сумма по группам. Для вопросов "
                            "«сколько», «на какую сумму», «по стадиям/клиентам/менеджерам/месяцам».",
             "input_schema": {"type": "object", "properties": {
                 "kind": {"type": "string", "enum": list(KINDS)},
                 "group_by": {"type": "string", "enum": ["stage", "partner", "user", "month"]},
                 "stage": {"type": "string", "description": "Отбор по стадии словом (необязательно)"},
                 "overdue": {"type": "boolean"}},
                 "required": ["kind", "group_by"]}},
            {"name": "read_record",
             "description": "Карточка записи: поля и связанные строки. Модель и id — из search_records.",
             "input_schema": {"type": "object", "properties": {
                 "model": {"type": "string"}, "id": {"type": "integer"}}, "required": ["model", "id"]}},
            {"name": "partner_overview",
             "description": "Сводка по контрагенту (клиент или поставщик): сделки по этапам и суммам, "
                            "счета, заказы в работе, расчёты, последние письма. id — из search_records (partner).",
             "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
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
                return self._tool_search(args.get("kind"), args.get("text") or "", int(args.get("limit") or 20),
                                         stage=args.get("stage") or "", overdue=bool(args.get("overdue")))
            if name == "summary":
                return self._tool_summary(args.get("kind"), args.get("group_by") or "stage",
                                          stage=args.get("stage") or "", overdue=bool(args.get("overdue")))
            if name == "read_record":
                if args.get("model") not in {v[0] for v in KINDS.values()}:
                    return {"ошибка": "этот раздел ассистенту не открыт"}
                return self._brief(args.get("model"), int(args.get("id") or 0))
            if name == "supplier_prices":
                return self._tool_prices(args.get("text") or "")
            if name == "partner_overview":
                return self._tool_partner(int(args.get("id") or 0))
        except AccessError:
            return {"ошибка": "нет доступа"}
        except Exception as exc:  # инструмент не должен ронять ответ
            _logger.warning("pmk_ai: инструмент %s упал: %s", name, exc)
            return {"ошибка": "инструмент не сработал: %s" % exc.__class__.__name__}
        return {"ошибка": "нет такого инструмента"}

    def _kind_domain(self, kind, stage="", overdue=False):
        """(Model, домен, описание вида) или (None, ошибка)."""
        if kind not in KINDS:
            return None, {"ошибка": "нет такого вида"}
        model, domain, _label, _f, _amount, stage_field, _date = KINDS[kind]
        if model not in self.env:
            return None, {"ошибка": "раздел не установлен"}
        Model = self.env[model]
        if not Model.has_access("read"):
            return None, {"ошибка": "нет доступа"}
        domain = [d for d in domain if d[0] in Model._fields]
        if stage and stage_field in Model._fields:
            field = Model._fields[stage_field]
            if field.type == "many2one":
                domain.append((stage_field + ".name", "ilike", stage))
            elif field.type == "selection":
                labels = dict(field._description_selection(self.env))
                values = [v for v, l in labels.items() if stage.lower() in (l or "").lower() or stage.lower() == v]
                domain.append((stage_field, "in", values or ["__нет__"]))
        if overdue and "pmk_overdue" in Model._fields:
            domain.append(("pmk_overdue", "=", True))
        return Model, domain

    def _value(self, rec, name):
        value = rec[name]
        field = rec._fields[name]
        if field.type == "many2one":
            return value.display_name
        if field.type == "selection":
            return dict(field._description_selection(self.env)).get(value, value)
        if field.type in ("date", "datetime"):
            return fields.Date.to_string(value) if field.type == "date" else fields.Datetime.to_string(value)[:16]
        if field.type in ("float", "monetary"):
            return round(value, 2)
        return _text(value, 80)

    def _tool_search(self, kind, text, limit, stage="", overdue=False):
        Model, domain = self._kind_domain(kind, stage, overdue)
        if Model is None:
            return domain
        limit = max(1, min(limit, SEARCH_LIMIT))
        row_fields = [f for f in KINDS[kind][3] if f in Model._fields and not (
            Model._fields[f].groups and not self.env.user.has_groups(Model._fields[f].groups))]
        if text:
            # Совпадения по названию — все (до 2000), а не первые limit: иначе «всего»
            # считалось бы по обрезанной выдаче (разбор 18.10: «ждут металл» 2 из 5).
            ids = [r[0] for r in Model.name_search(text, domain, limit=2000)]
            if not ids and "partner_id" in Model._fields:
                domain = domain + [("partner_id", "ilike", text)]
            else:
                domain = domain + [("id", "in", ids)]
        total = Model.search_count(domain)
        recs = Model.search(domain, limit=limit, order="write_date desc, id desc")
        out = []
        for rec in recs:
            row = {"model": Model._name, "id": rec.id, "название": rec.display_name}
            for f in row_fields:
                if rec[f] not in (False, None, "", 0, 0.0) or Model._fields[f].type == "boolean" and rec[f]:
                    row[Model._fields[f]._description_string(self.env)] = self._value(rec, f)
            out.append(row)
        result = {"всего в базе по отбору": total, "показано": len(out), "записи": out}
        if total > len(out):
            result["подсказка"] = "Показаны не все — для подсчёта и сумм возьми summary, для списка уточни отбор."
        return result

    def _tool_summary(self, kind, group_by, stage="", overdue=False):
        Model, domain = self._kind_domain(kind, stage, overdue)
        if Model is None:
            return domain
        _m, _d, label, _f, amount, stage_field, date_field = KINDS[kind]
        group = {"stage": stage_field, "partner": "partner_id", "user": "user_id",
                 "month": (date_field + ":month") if date_field else None}.get(group_by)
        if not group or group.split(":")[0] not in Model._fields:
            return {"ошибка": "по этому признаку «%s» не группируется" % label}
        aggs = ["__count"] + (["%s:sum" % amount] if amount and amount in Model._fields else [])
        rows = Model._read_group(domain, [group], aggs, order=None)
        out, total_n, total_sum = [], 0, 0.0
        for row in rows:
            key = row[0]
            key = key.display_name if hasattr(key, "display_name") else (
                dict(Model._fields[group]._description_selection(self.env)).get(key, key)
                if Model._fields.get(group) and Model._fields[group].type == "selection" else key)
            item = {"группа": str(key) if key else "—", "количество": row[1]}
            total_n += row[1]
            if len(row) > 2:
                item["сумма"] = round(row[2] or 0.0, 2)
                total_sum += row[2] or 0.0
            out.append(item)
        out.sort(key=lambda r: -r["количество"])
        result = {"вид": label, "всего": total_n, "группы": out[:40]}
        if amount and amount in Model._fields:
            result["сумма всего (%s)" % Model._fields[amount]._description_string(self.env)] = round(total_sum, 2)
        return result

    def _tool_partner(self, partner_id):
        Partner = self.env["res.partner"]
        partner = Partner.browse(partner_id).exists()
        if not partner:
            return {"ошибка": "контрагент не найден"}
        partner.check_access("read")
        company = partner.commercial_partner_id
        family = Partner.search([("commercial_partner_id", "=", company.id)])
        out = {"контрагент": company.display_name, "model": "res.partner", "id": company.id}
        for key, val in (("ИНН", company.vat), ("Город", company.city), ("Телефон", company.phone),
                         ("Почта", company.email), ("Контактные лица", ", ".join(company.child_ids[:6].mapped("name")))):
            if val:
                out[key] = val

        def section(model, domain, fields_, order="id desc", limit=8):
            if model not in self.env or not self.env[model].has_access("read"):
                return None
            Model = self.env[model]
            domain = [d for d in domain if d[0] in Model._fields or "." in d[0]]
            recs = Model.search(domain, order=order, limit=limit)
            total = Model.search_count(domain)
            rows = []
            for rec in recs:
                row = {"id": rec.id, "название": rec.display_name}
                for f in fields_:
                    if f in rec._fields and rec[f]:
                        v = rec[f]
                        row[rec._fields[f]._description_string(self.env)] = (
                            v.display_name if hasattr(v, "display_name") else
                            (fields.Date.to_string(v) if hasattr(v, "isoformat") else v))
                rows.append(row)
            return {"всего": total, "model": model, "последние": rows}

        out["сделки"] = section("crm.lead", [("partner_id", "in", family.ids)],
                                ["stage_id", "expected_revenue", "user_id", "create_date"])
        out["счета покупателю"] = section("sale.order", [("partner_id", "in", family.ids)],
                                          ["state", "amount_total", "date_order"])
        out["заказы в работе"] = section("project.task", [("pmk_is_order", "=", True), ("partner_id", "in", family.ids)],
                                         ["stage_id", "pmk_date_due"])
        out["расчёты"] = section("pmk.metal.spec", [("partner_id", "in", family.ids)],
                                 ["date", "total_weight_t", "price_customer_total"], limit=6)
        out["заказы поставщику (если это поставщик)"] = section("purchase.order", [("partner_id", "in", family.ids)],
                                                               ["state", "amount_total", "date_order"], limit=5)
        if "mail.client.message" in self.env and self.env["mail.client.message"].has_access("read"):
            mails = self.env["mail.client.message"].search(
                ["|", ("email_from", "ilike", company.email or "@@нет@@"), ("partner_id", "in", family.ids)]
                if "partner_id" in self.env["mail.client.message"]._fields else
                [("email_from", "ilike", company.email or "@@нет@@")], order="date desc", limit=5)
            out["письма"] = [{"тема": m.subject, "дата": fields.Datetime.to_string(m.date)} for m in mails]
        return {k: v for k, v in out.items() if v not in (None, [], {})}

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
    def ask(self, question, thread_id=False, context=None):
        """Поставить вопрос в очередь диалога → {request_id, thread_id} или {error}.
        Процесс Odoo ответа не ждёт; история — из сохранённого диалога на сервере."""
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
        if not self._worker_alive():
            return {"error": "Фоновый процесс ассистента не запущен — сообщите администратору.", "status": status}
        Thread = self.env["pmk.ai.thread"].sudo()
        Request = self.env["pmk.ai.request"].sudo()
        thread = Thread.browse(int(thread_id)).exists() if thread_id and not isinstance(thread_id, (dict, list)) else Thread
        if thread and thread.user_id != self.env.user:
            thread = Thread
        busy = Request.search([("user_id", "=", self.env.uid), ("state", "in", ("queued", "running"))])
        if thread and busy.filtered(lambda r: r.thread_id == thread):
            return {"error": "В этом диалоге ассистент ещё отвечает — подождите или начните новый диалог.",
                    "status": status}
        if len(busy) >= USER_INFLIGHT:
            return {"error": "У вас уже %d вопроса в работе — дождитесь ответа." % len(busy), "status": status}
        now = fields.Datetime.now()
        if not thread:
            thread = Thread.create({"user_id": self.env.uid, "name": _text(question, 60), "last_date": now})
        else:
            thread.last_date = now
        req = Request.create({"user_id": self.env.uid, "question": question, "thread_id": thread.id,
                              "context_json": json.dumps(context or {}, ensure_ascii=False)})
        return {"request_id": req.id, "thread_id": thread.id, "thread_name": thread.name, "status": status}

    @api.model
    def threads(self):
        """Мои диалоги — для списка в панели."""
        out = []
        for t in self.env["pmk.ai.thread"].sudo().search([("user_id", "=", self.env.uid)], limit=40):
            when = fields.Datetime.context_timestamp(self, t.last_date) if t.last_date else None
            out.append({"id": t.id, "name": t.name, "count": len(t.request_ids),
                        "when": when.strftime("%d.%m %H:%M") if when else ""})
        return out

    @api.model
    def thread_messages(self, thread_id):
        """Реплики диалога по порядку; вопрос в работе — с request_id, чтобы панель дождалась ответа."""
        thread = self.env["pmk.ai.thread"].sudo().browse(int(thread_id)).exists()
        if not thread or thread.user_id != self.env.user:
            return {"error": "Диалог не найден."}
        items = []
        for req in thread.request_ids.sorted("id"):
            items.append({"role": "user", "text": req.question})
            if req.state == "done":
                items.append({"role": "assistant", "text": req.answer or "", "seconds": round(req.seconds, 1),
                              "usage": req.usage_id.id, "rated": req.usage_id.rating or False})
            elif req.state == "error":
                items.append({"role": "assistant", "text": req.answer or "Ошибка.", "error": True})
            else:
                items.append({"role": "assistant", "pending": req.id})
        return {"id": thread.id, "name": thread.name, "items": items, "status": self.get_status()}

    @api.model
    def archive_thread(self, thread_id):
        thread = self.env["pmk.ai.thread"].sudo().browse(int(thread_id)).exists()
        if thread and thread.user_id == self.env.user:
            thread.active = False
            return True
        return False

    @api.model
    def poll(self, request_id):
        """Состояние своего вопроса: {state, answer|error, seconds, status}."""
        req = self.env["pmk.ai.request"].sudo().browse(int(request_id)).exists()
        if not req or req.user_id != self.env.user:
            return {"state": "error", "error": "Вопрос не найден."}
        out = {"state": req.state, "note": req.note or ""}
        if req.state == "done":
            out.update(answer=req.answer, seconds=round(req.seconds, 1), status=self.get_status(),
                       usage_id=req.usage_id.id)
        elif req.state == "error":
            out.update(error=req.answer or "Ошибка.", status=self.get_status())
        return out

    # ─── фоновый процесс (worker/ai_worker.py) ──────────────────────────
    def _worker_alive(self):
        # Мимо кэша get_param: отметку пишет другой процесс (odoo-ai-worker), и кэш настроек
        # в процессах Odoo о ней не узнаёт — страница видела старую отметку и через минуту
        # говорила «не запущен», хотя фон работал (18.10.2026).
        self.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'pmk_ai.worker_alive'")
        row = self.env.cr.fetchone()
        stamp = row and row[0]
        try:
            return bool(stamp) and time.time() - float(stamp) < WORKER_ALIVE_SEC
        except ValueError:
            return False

    @api.model
    def _worker_tick(self, free):
        """Отметка «жив», зависшие → ошибка, взять до free вопросов → их id (state=running)."""
        # Отметка «жив» — прямой записью, без кэша и без сброса кэша у всех процессов.
        self.env.cr.execute("""
            INSERT INTO ir_config_parameter (key, value, create_uid, write_uid, create_date, write_date)
            VALUES ('pmk_ai.worker_alive', %s, 1, 1, now() at time zone 'utc', now() at time zone 'utc')
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = EXCLUDED.write_date
        """, ("%.0f" % time.time(),))
        Request = self.env["pmk.ai.request"].sudo()
        stuck = Request.search([("state", "=", "running"),
                                ("started", "<", fields.Datetime.subtract(fields.Datetime.now(), seconds=STUCK_SEC))])
        if stuck:
            stuck.write({"state": "error", "answer": "Ответ не получен — повторите вопрос."})
        if free <= 0:
            return []
        self.env.cr.execute("""SELECT id FROM pmk_ai_request WHERE state = 'queued'
                               ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED""", (free,))
        ids = [r[0] for r in self.env.cr.fetchall()]
        if ids:
            Request.browse(ids).write({"state": "running", "started": fields.Datetime.now()})
        return ids

    @api.model
    def _worker_jobs(self, free):
        """Работы фона: [(модель, метод, id)]. Вопросы чата — первыми; модули
        дописывают свои (pmk_ai_mail — разбор почты) в оставшиеся потоки."""
        return [("pmk.ai.chat", "_process_request", rid) for rid in self._worker_tick(free)]

    @api.model
    def _process_request(self, request_id):
        """Ответить на вопрос из очереди — от имени спросившего (его права)."""
        req = self.env["pmk.ai.request"].sudo().browse(request_id).exists()
        if not req or req.state != "running":
            return
        try:
            context = json.loads(req.context_json or "{}")
        except ValueError:
            context = {}
        # История — из сохранённого диалога: последние HISTORY пар «вопрос–ответ» до этого вопроса.
        history = []
        if req.thread_id:
            before = req.thread_id.request_ids.filtered(lambda r: r.id < req.id and r.state == "done").sorted("id")
            for prev in before[-HISTORY:]:
                history += [{"role": "user", "text": prev.question}, {"role": "assistant", "text": prev.answer or ""}]
        chat = self.with_user(req.user_id).with_context(lang=req.user_id.lang or "ru_RU",
                                                         tz=req.user_id.tz or "Asia/Vladivostok")
        retried = []

        def on_retry(text):
            # Своим курсором с фиксацией: транзакция вопроса закрепится только в конце, а
            # страница опрашивает состояние сейчас.
            retried.append(text)
            with self.env.registry.cursor() as cr:
                cr.execute("UPDATE pmk_ai_request SET note = %s WHERE id = %s", (text, req.id))

        try:
            res = chat._answer(req.question, history, context, on_retry=on_retry)
        except Exception as exc:  # фон не должен падать от одного вопроса
            _logger.exception("pmk_ai: вопрос %s", req.id)
            res = {"error": "Ошибка при ответе: %s" % exc.__class__.__name__, "seconds": 0}
        if retried:
            # Строку вопроса уже менял другой курсор (on_retry): в REPEATABLE READ запись ниже
            # упала бы «could not serialize access» — фиксируем и пишем в новом снимке.
            self.env.cr.commit()
        req.write({"state": "error" if res.get("error") else "done", "note": False,
                   "answer": res.get("error") or res.get("answer"), "seconds": res.get("seconds") or 0,
                   "usage_id": res.get("usage_id") or False})

    @api.model
    def rate(self, usage_id, rating, note=""):
        """👍/👎 своему ответу (и комментарий) — для разбора и обучения ассистента."""
        usage = self.env["pmk.ai.usage"].sudo().browse(int(usage_id)).exists()
        if not usage or usage.user_id != self.env.user or rating not in ("good", "bad"):
            return False
        usage.write({"rating": rating, "feedback": _text(note or "", 2000) or False})
        return True

    def _answer(self, question, history=None, context=None, on_retry=None):
        """Сам ответ: Claude + инструменты. Зовёт фоновый процесс, не страница."""
        messages = []
        for item in (history or [])[-2 * HISTORY:]:
            if item.get("role") in ("user", "assistant") and item.get("text"):
                messages.append({"role": item["role"], "content": _text(item["text"], 4000)})
        messages.append({"role": "user", "content": question})
        model = self._param("pmk_ai.model") or claude.DEFAULT_MODEL
        payload = {"model": model, "max_tokens": MAX_TOKENS, "system": self._system(context or {}),
                   "tools": self._tools(), "messages": messages}
        totals = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 0}
        started, calls, answer, error, said = time.time(), 0, "", "", ""
        try:
            while calls < MAX_CALLS:
                if calls == MAX_CALLS - 1 or time.time() - started > TIME_BUDGET:
                    # Последний заход — только ответ: иначе человек видит обрывок сбора данных
                    # вместо вывода (разбор 18.10: «расскажи о заказчике» упёрся в лимит вызовов).
                    payload["tool_choice"] = {"type": "none"}
                data, _sec = claude.messages(self._param("pmk_ai.api_key"), payload,
                                             base=self._param("pmk_ai.api_base"), on_retry=on_retry)
                calls += 1
                usage = data.get("usage") or {}
                for key in totals:
                    totals[key] += int(usage.get(key) or 0)
                content = data.get("content") or []
                answer = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
                said = answer or said
                uses = [b for b in content if b.get("type") == "tool_use"]
                if data.get("stop_reason") != "tool_use" or not uses:
                    break
                payload["messages"].append({"role": "assistant", "content": content})
                payload["messages"].append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": b["id"],
                     "content": json.dumps(self._run_tool(b.get("name"), b.get("input") or {}),
                                           ensure_ascii=False, default=str)[:20000]} for b in uses]})
        except claude.ClaudeError as exc:
            error = str(exc)
        # Последний заход вернулся пустым (Голубенко 27.10, «Ответ пустой» после 4 минут) — отдать
        # текст, сказанный по ходу сбора данных, он лучше, чем ничего.
        answer = answer or said
        seconds = time.time() - started
        usage = self.env["pmk.ai.usage"].sudo().create({
            "user_id": self.env.uid, "question": _text(question, 200), "model": model, "calls": calls,
            "input_tokens": totals["input_tokens"], "output_tokens": totals["output_tokens"],
            "cost": self._cost(totals, model), "seconds": seconds, "ok": bool(answer) and not error,
            "answer": error or answer, "screen": _text((context or {}).get("title") or "", 120)})
        result = {"seconds": round(seconds, 1), "usage_id": usage.id}
        if error:
            result["error"] = error
        else:
            result["answer"] = answer or "Ответ пустой — переформулируйте вопрос."
        return result
