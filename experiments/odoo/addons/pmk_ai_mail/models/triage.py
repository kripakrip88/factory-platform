# -*- coding: utf-8 -*-
"""Разбор входящих писем ассистентом (Антон 20.10.2026).

«Если ассистент видит, что это потенциальная заявка, пусть кладёт в сделку в
отдельную колонку, Вова будет пока разбирать и комментировать его действия —
так обучим со временем». Ящик — только pmkpark@mail.ru, папка — только
«Входящие» (чеки и рассылки mail.ru и так раскладывает по своим папкам).

Ход письма (фон odoo-ai-worker, страница Odoo не ждёт):
  1. очередь — новые письма «Входящих» после даты включения (pmk_ai_mail.since);
  2. без ассистента, бесплатно: наши же письма — «внутреннее»; роботы
     (noreply, рассылки сервисов) — «автоматическое»; ответ в переписке, у
     которой уже есть сделка, — письмо привязывается к ней;
  3. ассистент (Claude): текст письма + вложения (PDF, сканы, Excel, Word) →
     вид письма и, для заявки, клиент, что нужно, сроки, место, чего не хватает;
  4. заявка → сделка в колонке «Разобрал ассистент», менеджер — проверяющий
     (Голубенко), письмо с файлами — в чате сделки и во вкладке «Письма».
Оценка 👍/👎 и комментарий проверяющего — в этой записи; последние замечания
уходят ассистенту вместе с правилами — так он учится на поправках.

Расход — строкой в pmk.ai.usage (виден в панели ассистента); лимит месяца —
общий с чатом: исчерпан — письма ждут в очереди.
"""
import json
import logging
import os
import re
import time

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.tools import html2plaintext

from odoo.addons.pmk_ai.tools import claude
from ..tools import parts

_logger = logging.getLogger(__name__)

RULES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge", "triage.md")
MAX_BODY_CHARS = 15000
MAX_TOKENS = 1500
JOBS_AT_ONCE = 2           # писем параллельно — остальные потоки фона для чата
BATCH = 40                 # писем в очередь за раз
STUCK_SEC = 600
REMARKS = 40               # последних замечаний проверяющего — в правила
# Пересылка своим сотрудником в ящик заявок — часто заявка клиента с мобильного
# («Fwd: МК ПС Амурская», 20.10.2026): такие письма разбирает ассистент.
TWIN_DAYS = 3                # повтор письма (тот же отправитель и тема) — в ту же сделку
FORWARD_RE = re.compile(r"^\s*(fwd?|пересл[\w.]*)\s*:", re.I)
ROBOT_RE = re.compile(
    r"^(no-?reply|do-?not-?reply|donotreply|mailer-daemon|postmaster|notifications?|informer|"
    r"news(letter)?|robot|bounce|mailing|rassylka|subscribe)\b", re.I)

KINDS = [
    ("request", "Заявка"),
    ("order", "По текущему заказу"),
    ("supplier", "Поставщик"),
    ("finance", "Оплата, документы"),
    ("ad", "Реклама, спам"),
    ("other", "Прочее"),
    ("reply", "Ответ в переписке сделки"),
    ("internal", "Наше же письмо"),
    ("auto", "Автоматическое"),
]

TRIAGE_TOOL = {
    "name": "triage",
    "description": "Результат разбора письма.",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["request", "order", "supplier", "finance", "ad", "other"]},
            "title": {"type": "string", "description": "Название сделки до 60 знаков (для заявки)."},
            "summary": {"type": "string"},
            "reason": {"type": "string"},
            "client": {"type": "object", "properties": {
                "company": {"type": "string"}, "inn": {"type": "string"},
                "contact": {"type": "string"}, "phone": {"type": "string"},
                "position": {"type": "string"}}},
            "items": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "qty": {"type": "string"},
                "unit": {"type": "string"}, "note": {"type": "string"}}}},
            "deadline": {"type": "string"},
            "place": {"type": "string"},
            "attachments": {"type": "array", "items": {"type": "string"}},
            "missing": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["kind", "summary", "reason"],
    },
}


class MailTriage(models.Model):
    _name = "pmk.ai.mail.triage"
    _description = "Разбор письма ассистентом"
    _order = "id desc"

    message_id = fields.Many2one("mail.client.message", "Письмо", required=True, index=True, ondelete="cascade")
    date = fields.Datetime("Пришло")
    subject = fields.Char("Тема")
    email_from = fields.Char("От кого")
    state = fields.Selection([("queued", "В очереди"), ("running", "Разбирается"), ("done", "Разобрано"),
                              ("skipped", "Без ассистента"), ("error", "Ошибка")],
                             "Состояние", default="queued", required=True, index=True)
    kind = fields.Selection(KINDS, "Вид письма", index=True)
    title = fields.Char("Название сделки")
    summary = fields.Text("Кратко")
    reason = fields.Char("Почему так")
    data_json = fields.Text("Разбор (JSON)")
    files_note = fields.Text("Вложения")
    lead_id = fields.Many2one("crm.lead", "Сделка", index=True, ondelete="set null")
    usage_id = fields.Many2one("pmk.ai.usage", "Расход", ondelete="set null")
    cost = fields.Float("Стоимость, $", related="usage_id.cost")
    seconds = fields.Float("Секунд", digits=(10, 1))
    started = fields.Datetime("Начат")
    error = fields.Text("Ошибка")
    rating = fields.Selection([("good", "👍 Верно"), ("bad", "👎 Ошибся")], "Оценка", index=True)
    feedback = fields.Text("Замечание проверяющего")
    rated_by = fields.Many2one("res.users", "Оценил")
    rated_on = fields.Datetime("Когда оценил")

    _message_uniq = models.Constraint("unique(message_id)", "Письмо уже разобрано.")

    # ─── настройки ───────────────────────────────────────────────────────
    def _param(self, key, default=None):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _enabled(self):
        return self._param("pmk_ai_mail.enabled") in ("1", "True", "true")

    def _reviewer(self):
        """Проверяющий — менеджер сделок от ассистента (по умолчанию Голубенко)."""
        uid = int(self._param("pmk_ai_mail.user_id") or 0)
        user = self.env["res.users"].sudo().browse(uid).exists() if uid else self.env["res.users"]
        return user or self.env["res.users"].sudo().search([("login", "=", "vladimir.golubenko")], limit=1)

    # ─── очередь ─────────────────────────────────────────────────────────
    @api.model
    def _enqueue(self):
        """Новые письма «Входящих» ящика после даты включения — в очередь."""
        email = (self._param("pmk_ai_mail.account") or "pmkpark@mail.ru").strip().lower()
        since = self._param("pmk_ai_mail.since")
        if not since:
            return 0
        self.env.cr.execute("""
            SELECT m.id, m.date, m.subject, m.email_from
              FROM mail_client_message m
              JOIN mail_client_folder f ON f.id = m.folder_id
              JOIN mail_client_account a ON a.id = f.account_id
             WHERE lower(a.email) = %s AND f.role = 'inbox' AND NOT coalesce(m.is_spam, false)
               AND m.date >= %s
               AND NOT EXISTS (SELECT 1 FROM pmk_ai_mail_triage t WHERE t.message_id = m.id)
             ORDER BY m.date LIMIT %s""", (email, since, BATCH))
        rows = self.env.cr.fetchall()
        if rows:
            self.sudo().create([{"message_id": r[0], "date": r[1], "subject": (r[2] or "")[:250],
                                 "email_from": (r[3] or "")[:250]} for r in rows])
        return len(rows)

    @api.model
    def _claim(self, free):
        """Взять до free писем из очереди (FOR UPDATE SKIP LOCKED) → id."""
        stuck = self.sudo().search([("state", "=", "running"),
                                    ("started", "<", fields.Datetime.subtract(fields.Datetime.now(), seconds=STUCK_SEC))])
        if stuck:
            stuck.write({"state": "queued"})
        if free <= 0:
            return []
        self.env.cr.execute("""SELECT id FROM pmk_ai_mail_triage WHERE state = 'queued'
                               ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED""", (free,))
        ids = [r[0] for r in self.env.cr.fetchall()]
        if ids:
            self.sudo().browse(ids).write({"state": "running", "started": fields.Datetime.now()})
        return ids

    # ─── разбор ──────────────────────────────────────────────────────────
    @api.model
    def _process(self, triage_id):
        triage = self.sudo().browse(triage_id).exists()
        if not triage or triage.state != "running":
            return
        reviewer = triage._reviewer()
        me = triage.with_context(lang="ru_RU", tz=reviewer.tz or "Asia/Vladivostok")
        start = time.time()
        try:
            me._run()
        except Exception as exc:  # noqa: BLE001 — одно письмо не валит фон
            _logger.exception("pmk_ai_mail: письмо %s", triage.message_id.id)
            triage.write({"state": "error", "error": "%s: %s" % (exc.__class__.__name__, exc)})
        triage.seconds = time.time() - start

    def _run(self):
        self.ensure_one()
        msg = self.message_id.sudo()
        own = msg._pmk_own_addresses()
        address = (re.search(r"[\w.+-]+@[\w.-]+", msg.email_from or "") or [""])[0].lower()
        # 1. Бесплатно: наше же письмо, робот, ответ в переписке сделки.
        if address and address in own and not FORWARD_RE.match(msg.subject or ""):
            self.write({"state": "skipped", "kind": "internal", "summary": _("Письмо из нашего ящика.")})
            return
        if address and ROBOT_RE.match(address.split("@")[0]):
            self.write({"state": "skipped", "kind": "auto", "summary": _("Автоматическое письмо (%s).") % address})
            return
        lead = self._thread_lead(msg)
        if lead:
            self._link(msg, lead)
            self.write({"state": "skipped", "kind": "reply", "lead_id": lead.id,
                        "summary": _("Ответ в переписке сделки «%s» — письмо привязано к ней.") % lead.name})
            return
        # 2. Лимит месяца — общий с чатом.
        chat = self.env["pmk.ai.chat"].sudo()
        spent = chat._month_usage()[0]
        budget = float(self._param("pmk_ai.budget", "100") or 100)
        if spent >= budget:
            self.write({"state": "queued"})
            return
        # 3. Ассистент.
        result, usage = self._ask(msg)
        data = result or {}
        kind = data.get("kind") if data.get("kind") in dict(KINDS) else "other"
        vals = {"state": "done", "kind": kind, "usage_id": usage.id,
                "title": (data.get("title") or "")[:120] or False,
                "summary": data.get("summary") or False, "reason": (data.get("reason") or "")[:250] or False,
                "data_json": json.dumps(data, ensure_ascii=False)}
        if kind == "request":
            vals["lead_id"] = self._create_lead(msg, data).id
        self.write(vals)

    def _thread_lead(self, msg):
        """Сделка переписки: у письма или у другого письма той же переписки ящика."""
        if msg.pmk_lead_id:
            return msg.pmk_lead_id
        Message = self.env["mail.client.message"].sudo()
        if msg.thread_key:
            other = Message.search([
                ("account_id", "=", msg.account_id.id), ("thread_key", "=", msg.thread_key),
                ("pmk_lead_id", "!=", False), ("id", "!=", msg.id)], limit=1)
            if other:
                return other.pmk_lead_id
        # То же письмо второй раз: тот же отправитель и тема за последние дни
        # («Fwd: МК ПС Амурская» переслали дважды — было две сделки, 20.10.2026).
        if msg.subject and msg.email_from and msg.date:
            twin = Message.search([
                ("account_id", "=", msg.account_id.id), ("email_from", "=", msg.email_from),
                ("subject", "=", msg.subject), ("pmk_lead_id", "!=", False), ("id", "!=", msg.id),
                ("date", ">=", fields.Datetime.subtract(msg.date, days=TWIN_DAYS))], limit=1)
            return twin.pmk_lead_id
        return self.env["crm.lead"]

    def _link(self, msg, lead):
        """Письмо — в чат сделки (как «Привязать к сделке»), если его там ещё нет."""
        posted = bool(msg.message_id) and self.env["mail.message"].sudo().search_count([
            ("message_id", "=", msg.message_id), ("model", "=", "crm.lead"), ("res_id", "=", lead.id)])
        if not posted:
            attachments, failed = msg._pmk_letter_attachments()
            msg._pmk_post_letter(lead, attachments, "mail.mt_comment")
            msg._pmk_note_failed(lead, failed)
        if msg.pmk_lead_id != lead:
            msg.pmk_lead_id = lead.id

    def _system(self):
        with open(RULES_FILE, encoding="utf-8") as fh:
            rules = fh.read()
        remarks = self.sudo().search([("feedback", "!=", False)], order="rated_on desc, id desc", limit=REMARKS)
        if remarks:
            lines = ["\n\n## Замечания проверяющего к прошлым разборам (учитывай их)"]
            labels = dict(KINDS)
            for r in remarks:
                verdict = {"good": "верно", "bad": "ошибка"}.get(r.rating, "замечание")
                lines.append("- «%s» (разобрано как: %s) — %s: %s" % (
                    (r.subject or "")[:90], labels.get(r.kind, r.kind or "?"), verdict, (r.feedback or "")[:400]))
            rules += "\n".join(lines)
        return [{"type": "text", "text": rules, "cache_control": {"type": "ephemeral"}}]

    def _ask(self, msg):
        chat = self.env["pmk.ai.chat"].sudo()
        key = chat._param("pmk_ai.api_key")
        if not key:
            raise claude.ClaudeError(_("Не задан ключ API ассистента."))
        if msg.body_state != "fetched":
            try:
                msg._fetch_body()
            except Exception as exc:  # noqa: BLE001 — без текста разберём по теме и файлам
                _logger.warning("pmk_ai_mail: тело письма %s: %s", msg.id, exc)
        body = html2plaintext(msg._display_body() or msg.body_html or "")[:MAX_BODY_CHARS]
        failed = []
        try:
            got, failed = msg._pmk_letter_attachments()
            files = [item[:2] for item in got if len(item) == 2]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("pmk_ai_mail: вложения письма %s: %s", msg.id, exc)
            files, failed = [], [(_("вложения"), str(exc))]
        blocks, notes = parts.build(files)
        # Не скачалось — так и пишем, иначе ассистент решит «вложения нет» (20.10.2026:
        # счета Металлсервиса разобраны как «без вложения», а файл в письме был).
        notes += ["%s — не скачан с сервера почты" % name for name, _err in failed if name != _("тело письма")]
        listed = msg._pmk_name_list()
        if listed and not files and not failed:
            notes.append("в письме есть файлы (%s), но их содержимое недоступно" % ", ".join(listed[:10]))
        head = "\n".join([
            "Письмо в ящик pmkpark@mail.ru",
            "От: %s" % (msg.email_from or ""),
            "Кому: %s" % (msg.email_to or ""),
            "Дата: %s" % (fields.Datetime.to_string(msg.date) if msg.date else ""),
            "Тема: %s" % (msg.subject or ""),
            "Вложения: %s" % ("; ".join(notes) or "нет"),
            "", "Текст письма:", body or "(текста нет)"])
        model = chat._param("pmk_ai.model") or claude.DEFAULT_MODEL
        payload = {
            "model": model, "max_tokens": MAX_TOKENS, "system": self._system(),
            # tool_choice «tool»/«any» Sonnet 5.5 не принимает (HTTP 400, 20.10.2026) —
            # «auto» и прямое указание в задании; текст вместо вызова — разбираем JSON.
            "tools": [TRIAGE_TOOL], "tool_choice": {"type": "auto"},
            "messages": [{"role": "user", "content": [{"type": "text", "text": head}] + blocks + [
                {"type": "text", "text": "Ответь только вызовом инструмента triage — без текста."}]}],
        }
        start = time.time()
        data, error = {}, False
        try:
            response, _sec = claude.messages(key, payload, chat._param("pmk_ai.api_base") or None)
        except claude.ClaudeError as exc:
            response, error = {}, str(exc)
        usage_raw = (response or {}).get("usage") or {}
        texts = []
        for block in (response or {}).get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == "triage":
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
        reviewer = self._reviewer()
        usage = self.env["pmk.ai.usage"].sudo().create({
            "user_id": (reviewer or self.env.ref("base.user_root")).id,
            "question": ("Почта: %s" % (msg.subject or ""))[:200], "model": model, "calls": 1,
            "input_tokens": int(usage_raw.get("input_tokens") or 0),
            "output_tokens": int(usage_raw.get("output_tokens") or 0),
            "cost": chat._cost(usage_raw, model), "seconds": time.time() - start,
            "ok": bool(data) and not error, "answer": error or json.dumps(data, ensure_ascii=False)[:4000],
            "screen": "Разбор почты"})
        self.files_note = "\n".join(notes) or False
        if error or not data:
            raise claude.ClaudeError(error or _("Ассистент не вернул разбор."))
        return data, usage

    def _create_lead(self, msg, data):
        """Заявка → сделка в колонке «Разобрал ассистент», менеджер — проверяющий.
        Создание — та же функция, что кнопка «Лид» в почте (клиент по адресу и
        ИНН, телефон из подписи, письмо с файлами — в чат сделки)."""
        reviewer = self._reviewer()
        client = data.get("client") or {}
        overrides = {"name": (data.get("title") or msg.subject or _("Заявка из почты"))[:120]}
        if client.get("phone"):
            overrides["phone"] = client["phone"][:60]
        if client.get("contact"):
            overrides["contact_name"] = client["contact"][:120]
        lead = msg.with_user(reviewer).sudo()._pmk_create_lead(overrides) if reviewer \
            else msg.sudo()._pmk_create_lead(overrides)
        stage = self.env.ref("pmk_ai_mail.stage_ai", raise_if_not_found=False)
        vals = {"type": "opportunity", "pmk_ai_triage_id": self.id, "description": self._lead_description(data)}
        # Клиента нет в базе — организация и должность из письма, как написал бы менеджер.
        if not lead.partner_id:
            if client.get("company") and not lead.partner_name:
                vals["partner_name"] = client["company"][:120]
            if client.get("position") and not lead.function:
                vals["function"] = client["position"][:120]
        if stage:
            vals["stage_id"] = stage.id
        lead.sudo().write(vals)
        if msg.pmk_lead_id != lead:
            msg.pmk_lead_id = lead.id
        return lead

    @api.model
    def _lead_description(self, data):
        rows = [Markup("<p><b>Разобрал ассистент.</b> %s</p>") % (data.get("summary") or "")]
        items = data.get("items") or []
        if items:
            rows.append(Markup("<ul>%s</ul>") % Markup("").join(
                Markup("<li>%s</li>") % " · ".join(p for p in (i.get("name"), " ".join(
                    x for x in (i.get("qty"), i.get("unit")) if x), i.get("note")) if p) for i in items))
        for label, key in (("Сроки", "deadline"), ("Объект, место", "place")):
            if data.get(key):
                rows.append(Markup("<p>%s: %s</p>") % (label, data[key]))
        if data.get("missing"):
            rows.append(Markup("<p>Не хватает: %s</p>") % "; ".join(data["missing"]))
        return Markup("").join(rows)

    # ─── оценка проверяющего ─────────────────────────────────────────────
    def _rate(self, rating):
        self.sudo().write({"rating": rating, "rated_by": self.env.uid, "rated_on": fields.Datetime.now()})

    # ─── вид в сделке ────────────────────────────────────────────────────
    def _card_html(self):
        """Блок «Разобрал ассистент» в сделке: что понял, клиент, что нужно, файлы."""
        self.ensure_one()
        try:
            data = json.loads(self.data_json or "{}")
        except ValueError:
            data = {}
        client = data.get("client") or {}
        def row(label, value):
            return Markup("<tr><th>%s</th><td>%s</td></tr>") % (label, value) if value else Markup("")
        who = ", ".join(p for p in (client.get("company"), client.get("inn") and "ИНН %s" % client["inn"],
                                    client.get("contact"), client.get("position"), client.get("phone")) if p)
        items = Markup("").join(
            Markup("<li>%s</li>") % " · ".join(p for p in (i.get("name"), " ".join(
                x for x in (i.get("qty"), i.get("unit")) if x), i.get("note")) if p)
            for i in data.get("items") or [])
        files = Markup("").join(Markup("<li>%s</li>") % line for line in (data.get("attachments") or [])) \
            or Markup("").join(Markup("<li>%s</li>") % line for line in (self.files_note or "").splitlines() if line)
        table = Markup("").join([
            row("Письмо", "«%s» · %s" % (self.subject or "", self.email_from or "")),
            row("Клиент", who),
            row("Что нужно", Markup("<ul>%s</ul>") % items if items else ""),
            row("Сроки", data.get("deadline")),
            row("Объект, место", data.get("place")),
            row("Не хватает", "; ".join(data.get("missing") or [])),
            row("Вложения", Markup("<ul>%s</ul>") % files if files else ""),
            row("Почему заявка", self.reason),
        ])
        return Markup('<p class="pmk-ai-triage__summary">%s</p><table class="pmk-ai-triage__table">%s</table>') % (
            escape(self.summary or ""), table)
