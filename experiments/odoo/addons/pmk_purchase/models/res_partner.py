# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ------------------------------------------------------------------
    # участие в запросе прайсов
    # ------------------------------------------------------------------
    pmk_price_supplier = fields.Boolean(
        "Поставщик прайсов",
        help="Участвует в регулярном запросе актуальных цен.",
        index="btree_not_null",
    )
    pmk_supply_ids = fields.Many2many(
        "pmk.supply.category",
        string="Что возит",
        help="По этим группам у поставщика и спрашиваем цены.",
    )
    pmk_has_stock = fields.Boolean(
        "Склад на Дальнем Востоке",
        help="Есть своя площадка, а не только офис. Короткое плечо поставки.",
    )

    # ------------------------------------------------------------------
    # адрес для запроса
    # ------------------------------------------------------------------
    # Держим отдельно от `email` намеренно. Список поставщиков собран из
    # открытых источников: пока адрес не подтверждён, он не должен попадать
    # ни в одну штатную рассылку Odoo. Пустой `email` это гарантирует.
    pmk_price_email = fields.Char(
        "Адрес для запроса прайса",
        help="Куда писать за ценами. В основное поле «Email» переносится "
             "только после подтверждения.",
    )
    pmk_price_email_state = fields.Selection(
        [
            ("draft", "Не подтверждён"),
            ("confirmed", "Подтверждён"),
            ("invalid", "Не работает"),
        ],
        string="Состояние адреса",
        default="draft",
        required=True,
        help="Рассылка уходит только на подтверждённые адреса.",
    )
    pmk_price_email_source = fields.Char(
        "Источник адреса",
        help="Страница, с которой адрес взят. Нужна, чтобы адрес можно было "
             "перепроверить, а не верить на слово.",
    )

    # ------------------------------------------------------------------
    # периодичность
    # ------------------------------------------------------------------
    pmk_price_period_days = fields.Integer(
        "Периодичность, дней",
        default=14,
        help="Как часто просить свежий прайс. Ноль — не просить автоматически.",
    )
    pmk_price_last_date = fields.Date(
        "Последний прайс",
        help="Дата последнего полученного прайса. Заполняется при приёме файла.",
    )
    pmk_price_next_date = fields.Date(
        "Следующий запрос",
        compute="_compute_pmk_price_next_date",
        store=True,
        help="Считается от даты последнего прайса и периодичности.",
    )

    @api.depends("pmk_price_last_date", "pmk_price_period_days", "pmk_price_supplier")
    def _compute_pmk_price_next_date(self):
        for partner in self:
            if not partner.pmk_price_supplier or partner.pmk_price_period_days <= 0:
                partner.pmk_price_next_date = False
                continue
            if not partner.pmk_price_last_date:
                # Прайса ещё не было — запрашивать можно хоть сегодня.
                partner.pmk_price_next_date = fields.Date.context_today(partner)
                continue
            partner.pmk_price_next_date = partner.pmk_price_last_date + relativedelta(
                days=partner.pmk_price_period_days)

    # ------------------------------------------------------------------
    # действия
    # ------------------------------------------------------------------
    def action_pmk_confirm_price_email(self):
        """Подтвердить адрес и перенести его в основное поле.

        Перенос в `email` — это и есть разрешение писать: до него ни одна
        штатная рассылка Odoo до контрагента не дотянется.
        """
        for partner in self:
            if not partner.pmk_price_email:
                continue
            partner.pmk_price_email_state = "confirmed"
            if not partner.email:
                partner.email = partner.pmk_price_email

    def action_pmk_invalidate_price_email(self):
        """Адрес не работает: снимаем подтверждение и убираем из рассылки."""
        for partner in self:
            partner.pmk_price_email_state = "invalid"
            if partner.email and partner.email == partner.pmk_price_email:
                partner.email = False
