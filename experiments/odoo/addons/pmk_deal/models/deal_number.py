# -*- coding: utf-8 -*-
"""Номер сделки «СД-00001 от 27.09.2026» — разбор UX, шаг 48 (06.10.2026).

ЗАЧЕМ. У расчёта номер есть («СМ-00025 от 27 сентября 2026 г.»), у сделки —
только тема письма клиента («Запрос стоимости изготовления МК п. Горный…»).
В строке пути она занимала 400 px и повторяла заголовок листа. Решения
Антона 06.10.2026: «СД-00012 от 29.09.2026» подходит; номер — только
АКТИВНЫМ сделкам, архивные без номера; лидам номер не нужен.

КОГДА ВЫДАЁТСЯ. Когда запись становится сделкой и она активна:
  • создали сразу сделкой (быстрое создание в воронке, «Новое» в списке);
  • лид превратили в сделку (кнопка «Конвертировать в сделку», мастер,
    массовое превращение — все пишут type='opportunity');
  • сделку без номера восстановили из архива («Восстановить», «Разархивировать»
    — пишут active=True);
  • «Дублировать» — новый номер (copy=False) от дня создания копии: дату
    превращения оригинала копия не наследует (copy_data ниже).
Проигранная или архивная сделка свой номер сохраняет. Сделка, которую
вернули в лид, номер хранит, но не показывает (строку пути подменяет только
форма сделки, static/src/js/deal_form_view.js). При объединении номер остаётся
у главной сделки: поля нет в списке объединяемых (CRM_LEAD_FIELDS_TO_MERGE
ядра и _merge_get_fields_specific наших модулей).

ДАТА НОМЕРА — день превращения в сделку (date_conversion; у созданной сразу
сделкой и у копии его нет — день создания), по часовому поясу человека: контекст →
менеджер сделки → текущий пользователь. Пояс задаём явно: миграция идёт от
__system__ без пояса, и сделка №19 (02.10 22:55 UTC = 03.10 08:55 по
Владивостоку) получила бы 02.10.

ИМЯ СДЕЛКИ НЕ МЕНЯЕТСЯ. display_name берёт почта темой письма (mail_thread),
поле «Сделка» расчёта и доборки, уведомления. Номер показывается рядом: в
строке пути формы сделки (подпись подменяет контроллер формы), на карточке
воронки, колонкой списка; ищется в поиске воронки и в поле «Сделка»
(_rec_names_search).
"""

from odoo import api, fields, models

SEQUENCE_CODE = "pmk.deal"


def number_label(number, day):
    """«СД-00001 от 27.09.2026»; без даты — один номер; без номера — пусто."""
    if not number:
        return ""
    if not day:
        return number
    return "%s от %s" % (number, day.strftime("%d.%m.%Y"))


class CrmLeadNumber(models.Model):
    _inherit = "crm.lead"

    # «СД-0…» в поле «Сделка» расчёта и доборки, в упоминаниях — находит и по
    # номеру. Штатно crm.lead ищется только по названию.
    _rec_names_search = ["name", "pmk_number"]

    # Без index=True: ограничение уникальности ниже само строит индекс.
    pmk_number = fields.Char(
        "Номер", readonly=True, copy=False,
        help="Номер сделки (СД-…). Выдаётся, когда запись становится сделкой "
             "и она активна; у лида и архивной сделки номера нет.")
    pmk_number_date = fields.Date(
        "Дата номера", readonly=True, copy=False,
        help="День, когда лид стал сделкой (у созданной сразу сделкой — день "
             "создания).")
    pmk_number_label = fields.Char(
        "Номер сделки", compute="_compute_pmk_number_label",
        help="Номер с датой: «СД-00001 от 27.09.2026».")

    _pmk_number_uniq = models.Constraint(
        "UNIQUE(pmk_number)",
        "Номер сделки уже занят.",
    )

    @api.depends("pmk_number", "pmk_number_date")
    def _compute_pmk_number_label(self):
        for lead in self:
            lead.pmk_number_label = number_label(lead.pmk_number, lead.pmk_number_date)

    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        leads._pmk_assign_number()
        return leads

    def copy_data(self, default=None):
        """Копия — новая сделка, созданная сразу сделкой: без даты превращения.

        Ядро переносит date_conversion в копию (поле без copy=False, его
        copy_data дату не сбрасывает), и номер копии, выданный сегодня,
        датировался бы днём превращения оригинала: «СД-00003 от 27.09.2026»
        после «СД-00002 от 03.10.2026». Дата превращения видна только
        группировкой «Дата превращения» в отчётах, где копия, которая лидом
        не была, ей и не принадлежит. Явно переданную дату не трогаем.
        """
        vals_list = super().copy_data(default=default)
        if "date_conversion" not in (default or {}):
            for vals in vals_list:
                vals["date_conversion"] = False
        return vals_list

    def write(self, vals):
        res = super().write(vals)
        # Номер — только по смене типа или архива: внутренняя запись номера
        # (ниже) этих ключей не содержит, второго круга нет.
        if {"type", "active"} & set(vals):
            self._pmk_assign_number()
        return res

    def _pmk_needs_number(self):
        self.ensure_one()
        return self.type == "opportunity" and self.active and not self.pmk_number

    def _pmk_number_day(self):
        """Местная дата превращения в сделку (или создания)."""
        self.ensure_one()
        moment = self.date_conversion or self.create_date or fields.Datetime.now()
        tz = (self.env.context.get("tz") or self.user_id.tz
              or self.env.user.tz or "UTC")
        return fields.Date.context_today(self.with_context(tz=tz), moment)

    def _pmk_assign_number(self):
        """Выдать номер сделкам без номера — в порядке превращения в сделку.

        Нумератора нет (модуль ставится, данные ещё не загружены) — номер не
        выдаётся, ничего не падает: при установке номера раздаст
        post_init_hook (hooks.py, number_active_deals).
        """
        todo = self.filtered(lambda lead: lead._pmk_needs_number())
        if not todo:
            return
        Sequence = self.env["ir.sequence"].sudo()
        ordered = todo.sorted(lambda lead: (
            lead.date_conversion or lead.create_date or fields.Datetime.now(),
            lead.id,
        ))
        for lead in ordered:
            number = Sequence.next_by_code(SEQUENCE_CODE)
            if not number:
                return
            lead.sudo().write({
                "pmk_number": number,
                "pmk_number_date": lead._pmk_number_day(),
            })
