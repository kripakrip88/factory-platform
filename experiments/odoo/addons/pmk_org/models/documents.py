# -*- coding: utf-8 -*-
"""«Наша организация» на документах (шаг 58).

Сделка → расчёт → счёт покупателю: организация выбирается на сделке
(подставляется по умолчанию), расчёт и счёт берут её со сделки. Менеджер
может поменять её в любом документе — решение «фирму выбирает менеджер
каждый раз сам» (Антон, 07.10.2026). Обязательной нигде не делаем: сигнал,
а не запрет — пустое поле печатает компанию Odoo, как до шага 58.
"""

from odoo import api, fields, models


def _default_org(env):
    return env["pmk.org"]._pmk_default()


def _org_from_deal(records, deal_field):
    """Организация документа — со сделки, иначе уже стоящая, иначе по
    умолчанию."""
    default = None
    for rec in records:
        org = rec[deal_field].pmk_org_id
        if org:
            rec.pmk_org_id = org
        elif not rec.pmk_org_id:
            if default is None:
                default = _default_org(records.env)
            rec.pmk_org_id = default


class CrmLeadOrg(models.Model):
    _inherit = "crm.lead"

    # БЕЗ default=: при установке модуля ядро заполнило бы колонку значением
    # по умолчанию для всех строк crm_lead (_init_column) — в момент, когда
    # таблицы справочника может ещё не быть. Значение по умолчанию ставит
    # default_get, а существующие сделки заполняет хук установки.
    pmk_org_id = fields.Many2one(
        "pmk.org", "Наша организация", index=True, tracking=True,
        ondelete="restrict",
        help="От чьего имени работаем по сделке: её реквизиты пойдут в КП, "
             "налог — по её налоговому режиму на дату документа. Расчёты и "
             "счета покупателям берут организацию отсюда.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "pmk_org_id" in fields_list and not res.get("pmk_org_id"):
            res["pmk_org_id"] = _default_org(self.env).id or False
        return res

    def _pmk_spec_defaults(self):
        res = super()._pmk_spec_defaults()
        # Только заполненную: default_pmk_org_id=False попал бы в vals
        # расчёта, и вычисление (_org_from_deal: «иначе по умолчанию») уже
        # не сработало бы — КП молча печатало бы компанию Odoo.
        if self.pmk_org_id:
            res["default_pmk_org_id"] = self.pmk_org_id.id
        return res


class MetalSpecOrg(models.Model):
    _inherit = "pmk.metal.spec"

    # Зависимость только от самой сделки, а не от её организации: смена
    # организации на сделке не переписывает уже посчитанные (и, может быть,
    # отправленные клиенту) расчёты. Сменили сделку в расчёте — организация
    # приходит с новой сделкой.
    pmk_org_id = fields.Many2one(
        "pmk.org", "Наша организация", index=True, tracking=True,
        ondelete="restrict", copy=True,
        compute="_compute_pmk_org_id", store=True, readonly=False, precompute=True,
        help="От чьего имени КП: реквизиты, банк и подпись в печати, строка "
             "налога — по налоговому режиму организации на дату расчёта. "
             "Приходит со сделки.")

    # Компания Odoo остаётся служебной: на ней держатся валюта и правила
    # доступа. С шага 58 на форме её место заняла «Наша организация», а
    # подпись меняем, чтобы в фильтрах и выгрузке не было двух «Организаций».
    company_id = fields.Many2one(string="Компания (служебное)")

    @api.depends("opportunity_id")
    def _compute_pmk_org_id(self):
        _org_from_deal(self, "opportunity_id")

    # ─── Печать КП: продавец и налог из организации ───────────────────────
    def pmk_print_seller(self):
        self.ensure_one()
        if not self.pmk_org_id:
            return super().pmk_print_seller()
        return self.pmk_org_id._pmk_print_info()

    def pmk_print_tax(self, total):
        self.ensure_one()
        if not self.pmk_org_id:
            return super().pmk_print_tax(total)
        return self.pmk_org_id._pmk_tax_line(self.date, total, self.company_id)


class SaleOrderOrg(models.Model):
    """Заказ клиента — по-заводски «Счёт покупателю» (просьба Антона
    08.10.2026: пункт меню и заголовок окна — «Счета покупателям», pmk_theme).
    Печать счёта с реквизитами организации — отдельной задачей: пока
    печатается компания Odoo, а налог строк уже идёт по режиму организации."""

    _inherit = "sale.order"

    pmk_org_id = fields.Many2one(
        "pmk.org", "Наша организация", index=True, tracking=True,
        ondelete="restrict", copy=True,
        compute="_compute_pmk_org_id", store=True, readonly=False, precompute=True,
        help="От чьего имени счёт. Налог строк — по налоговому режиму "
             "организации на дату счёта. Приходит со сделки. Печать счёта "
             "пока идёт с реквизитами компании Odoo.")

    @api.depends("opportunity_id")
    def _compute_pmk_org_id(self):
        _org_from_deal(self, "opportunity_id")


class SaleOrderLineOrg(models.Model):
    _inherit = "sale.order.line"

    # Ядро собирает зависимости вычисляемого поля со всех переопределений
    # метода (по MRO), штатные product_id / company_id остаются.
    # ⚠️ НЕ от order_id.date_order: «Подтвердить» переписывает дату заказа
    # (sale.order.action_confirm), и налоги, поправленные в строках руками,
    # пересчитались бы молча. Дата берётся в момент расчёта налога.
    @api.depends("order_id.pmk_org_id")
    def _compute_tax_ids(self):
        super()._compute_tax_ids()
        cache = {}
        for line in self:
            order = line.order_id
            org = order.pmk_org_id
            if (not org or not line.product_id or line.display_type
                    or line.product_type == "combo"):
                continue
            day = fields.Date.to_date(order.date_order) if order.date_order else fields.Date.context_today(line)
            key = (org.id, day, line.company_id.id)
            if key not in cache:
                cache[key] = org._pmk_sale_tax_at(day, line.company_id)
            tax = cache[key]
            if tax:
                # Налог режима — поверх налога товара: у всех 753 товаров
                # стоит «НДС 22%», а у фирмы на УСН в счёте его быть не должно.
                line.tax_ids = order.fiscal_position_id.map_tax(tax)
