# -*- coding: utf-8 -*-
"""Задача доски «Доработка системы» выложена — автору в личку (19.10.2026).

Антон: «уведомления, когда задача в доработку, которую он публиковал,
переходит в статус «Выложено — проверить»». Автор — пользователь, создавший
задачу (create_uid): через бота задача создаётся от имени привязанного
человека, в Odoo — от вошедшего, так что это один и тот же человек.

Не шлём, если автор сам перенёс свою карточку, и по карточкам, заведённым
скриптом (служебный пользователь — у него нет Телеграма).
"""
import html
import re

from odoo import api, fields, models

from .bot import DEV_ACTION_XMLID

REVIEW_STAGE = "Выложено"          # колонка «Выложено — проверить»
CHECK_MAX = 400
# Поле «Как проверить» (20.10.2026) — инструкция целиком: где и что нажать.
# Сообщение Телеграма до 4096 знаков; 1500 — с запасом на заголовок и кнопку.
CHECK_FIELD_MAX = 1500


def _esc(text):
    return html.escape(text or "", quote=False)


def html_text(value):
    """Html поля → текст сообщения: абзацы и пункты — строками, пункт — «• »."""
    text = re.sub(r"<li[^>]*>", "\n• ", value or "", flags=re.I)
    # </li> не переносит строку: перенос уже даёт «<li>» следующего пункта — иначе
    # между пунктами пустая строка.
    text = re.sub(r"<br\s*/?>|</p>|</h\d>|</div>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def what_to_check(description_html):
    """Текст раздела «Что проверить» из описания карточки (или "")."""
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", description_html or "", flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    m = re.search(r"Что проверить\s*:?\s*(.+?)(?=\n\s*(?:Итог проверки|Что сделано|Задача)\b|$)",
                  text, re.S | re.I)
    if not m:
        return ""
    found = re.sub(r"[ \t]+", " ", m.group(1)).strip()
    found = re.sub(r"\n\s*\n+", "\n", found)
    return found if len(found) <= CHECK_MAX else found[:CHECK_MAX - 1].rstrip() + "…"


class ProjectTask(models.Model):
    _inherit = "project.task"

    # Антон 20.10.2026: «чтоб с уведомлением пришла ещё инструкция, что
    # проверить и где, и так же инструкция была продублирована в саму задачу».
    # Отдельное поле, а не правка описания: описание пишет автор задачи.
    pmk_check_html = fields.Html(
        "Как проверить",
        help="Где и что проверить после выкладки. При переносе карточки в «Выложено — "
             "проверить» уходит автору задачи в Телеграм.")
    pmk_is_dev_task = fields.Boolean(compute="_compute_pmk_is_dev_task")

    @api.depends("project_id")
    def _compute_pmk_is_dev_task(self):
        project = self.env["pmk.telegram.bot"].sudo()._pmk_dev_project()
        for task in self:
            task.pmk_is_dev_task = bool(project) and task.project_id == project

    def write(self, vals):
        before = {t.id: t.stage_id.id for t in self} if "stage_id" in vals else {}
        res = super().write(vals)
        if before:
            self._pmk_notify_review(before)
        return res

    def _pmk_notify_review(self, before):
        bot = self.env["pmk.telegram.bot"].sudo()
        project = bot._pmk_dev_project()
        if not project:
            return
        base = (self.env["ir.config_parameter"].sudo().get_param("web.base.url") or "").rstrip("/")
        for task in self.sudo():
            if (task.project_id != project or task.stage_id.id == before.get(task.id)
                    or REVIEW_STAGE.lower() not in (task.stage_id.name or "").lower()):
                continue
            author = task.create_uid
            if not author.pmk_telegram_id or author == self.env.user:
                continue
            lines = ["✅ <b>Готово к проверке</b>", "«%s»" % _esc(task.name)]
            guide = html_text(task.pmk_check_html)
            if guide:
                if len(guide) > CHECK_FIELD_MAX:
                    guide = guide[:CHECK_FIELD_MAX - 1].rstrip() + "… (целиком — в задаче)"
                lines += ["", "<b>Как проверить:</b>", _esc(guide)]
            else:
                check = what_to_check(task.description)
                if check:
                    lines += ["", "<b>Что проверить:</b> %s" % _esc(check)]
            markup = None
            if base.startswith("https://"):
                markup = {"inline_keyboard": [[{
                    "text": "Открыть задачу",
                    "url": f"{base}/odoo/action-{DEV_ACTION_XMLID}/{task.id}"}]]}
            bot.pmk_send_user(author, "\n".join(lines), markup)
