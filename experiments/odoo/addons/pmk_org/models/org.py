# -*- coding: utf-8 -*-
"""Справочник «Наши организации» и налоговый режим по датам (шаг 58).

ОРГАНИЗАЦИЯ — ЭТО КОНТРАГЕНТ С НАСТРОЙКАМИ. Реквизиты (название, ИНН, КПП,
ОГРН/ОГРНИП, адрес, телефон, почта) лежат в карточке контрагента
(res.partner), здесь — их зеркала для правки: «Заполнить по ИНН» (pmk_dadata)
работает ровно как у клиента, а когда бухгалтерия переедет в Odoo, у
res.company тот же partner_id — перенос без потерь.

НАЛОГОВЫЙ РЕЖИМ — СТРОКАМИ С ДАТОЙ НАЧАЛА. Налогообложение меняется из года
в год (Антон, 07.10.2026): с 01.01.2027 фирма может уйти с НДС на УСН, а КП
от 15.12.2026 должно печататься по-старому. Поэтому режим не поле, а строки
«с даты — режим», и документ спрашивает «режим на мою дату».
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.pmk_bridge.tools import seller

from ..tools import regime as rg

ORG_TYPES = [("ooo", "ООО"), ("ip", "ИП")]


class PmkOrg(models.Model):
    _name = "pmk.org"
    _description = "Наша организация"
    _inherit = ["mail.thread"]
    _order = "sequence, id"
    _rec_name = "name"

    sequence = fields.Integer("Порядок", default=10)
    active = fields.Boolean("Активна", default=True, tracking=True)
    is_default = fields.Boolean(
        "По умолчанию", tracking=True, copy=False,
        help="Подставляется в новые сделки, расчёты и счета покупателям. "
             "Флажок стоит ровно у одной организации.")

    partner_id = fields.Many2one(
        "res.partner", "Карточка контрагента", required=True, ondelete="restrict",
        index=True, copy=False,
        help="Реквизиты организации живут в карточке контрагента: так "
             "«Заполнить по ИНН» работает, как у клиентов.")
    name = fields.Char(
        "Название", related="partner_id.name", store=True, readonly=False,
        required=True, tracking=True)
    org_type = fields.Selection(
        ORG_TYPES, "Тип", required=True, default="ooo", tracking=True,
        help="От типа зависит подпись номера в печати: у ООО — ОГРН, у ИП — ОГРНИП.")
    reg_label = fields.Char("Подпись номера", compute="_compute_reg_label")

    # ─── Реквизиты: зеркала карточки контрагента ──────────────────────────
    # ИНН — поле vat: в российской локализации inn только для чтения и
    # зеркалит vat (см. pmk_dadata/views/res_partner_views.xml).
    inn = fields.Char("ИНН", related="partner_id.vat", readonly=False)
    kpp = fields.Char("КПП", related="partner_id.kpp", readonly=False)
    ogrn = fields.Char("ОГРН / ОГРНИП", related="partner_id.ogrn", readonly=False)
    legal_address = fields.Text(
        "Юридический адрес", related="partner_id.pmk_legal_address", readonly=False)
    street = fields.Char("Улица, дом", related="partner_id.street", readonly=False)
    city = fields.Char("Город", related="partner_id.city", readonly=False)
    zip = fields.Char("Индекс", related="partner_id.zip", readonly=False)
    phone = fields.Char("Телефон", related="partner_id.phone", readonly=False)
    email = fields.Char("Эл. почта", related="partner_id.email", readonly=False)

    bank_id = fields.Many2one(
        "res.partner.bank", "Банковский счёт", ondelete="set null",
        domain="[('partner_id', '=', partner_id)]",
        help="Счёт для строки «Реквизиты для оплаты» в КП и счёте.")
    signer_name = fields.Char(
        "Подписант (ФИО)", tracking=True,
        help="Полностью: «Чулков Владислав Витальевич». В печать идёт "
             "«Чулков В. В.».")
    signer_position = fields.Char(
        "Должность подписанта", tracking=True,
        help="«Директор», «Индивидуальный предприниматель».")
    accountant_name = fields.Char(
        "Главный бухгалтер", help="Необязательно. Заполнено — в печати вторая подпись.")
    logo = fields.Image("Логотип", max_width=512, max_height=512)

    regime_ids = fields.One2many("pmk.org.regime", "org_id", "Налоговый режим", copy=True)
    regime_today = fields.Char("Режим сегодня", compute="_compute_regime_today")

    @api.depends("org_type")
    def _compute_reg_label(self):
        for org in self:
            org.reg_label = seller.reg_label(org.org_type)

    @api.depends("regime_ids.date_from", "regime_ids.regime")
    @api.depends_context("tz")
    def _compute_regime_today(self):
        today = fields.Date.context_today(self)
        for org in self:
            # Не _pmk_regime_at: у него запасной вариант «раньше первой строки
            # — самая ранняя» (для документов задним числом). Здесь он дал бы
            # «УСН без НДС» рядом со словом «будет» в той же строке.
            org.regime_today = rg.today_label(
                [(r.date_from, r.regime) for r in org.regime_ids], today) or False

    @api.onchange("inn")
    def _onchange_inn_type(self):
        """12 цифр ИНН — предприниматель: предлагаем тип, не навязываем."""
        for org in self:
            if org.inn:
                org.org_type = seller.org_type_by_inn(org.inn)

    # ─── Создание и флажок «по умолчанию» ─────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        # Права — до карточки контрагента: без права на справочник не должно
        # оставаться осиротевших контрагентов.
        self.browse().check_access("create")
        Partner = self.env["res.partner"]
        ru = self.env.ref("base.ru", raise_if_not_found=False)
        for vals in vals_list:
            if not vals.get("partner_id"):
                # Карточка контрагента — первой: реквизиты из vals (ИНН,
                # адрес…) записываются в неё через зеркала после создания.
                partner = Partner.create({
                    "name": vals.get("name") or _("Новая организация"),
                    "is_company": True,
                    "country_id": ru.id if ru else False,
                })
                vals["partner_id"] = partner.id
            elif not vals.get("name"):
                # Название — зеркало карточки, но колонка обязательная: без
                # значения в vals строка вставилась бы с пустым названием до
                # пересчёта зеркала (NOT NULL).
                vals["name"] = Partner.browse(vals["partner_id"]).name
        orgs = super().create(vals_list)
        orgs.filtered("is_default")[-1:]._pmk_make_only_default()
        return orgs

    def write(self, vals):
        res = super().write(vals)
        if vals.get("is_default"):
            self.filtered("is_default")[-1:]._pmk_make_only_default()
        return res

    def _pmk_make_only_default(self):
        """Флажок «по умолчанию» — только у этой организации."""
        if not self:
            return
        others = self.sudo().with_context(active_test=False).search(
            [("is_default", "=", True), ("id", "not in", self.ids)])
        if others:
            others.write({"is_default": False})

    @api.constrains("regime_ids", "partner_id")
    def _check_regime(self):
        # partner_id в списке нарочно: он есть в vals любого создания, иначе
        # организацию без строк режима ядро не проверило бы вовсе. Удалить
        # последнюю строку в форме и сохранить — та же ошибка: проверка идёт
        # после записи всех строк, поэтому «удалил старую, добавил новую»
        # одним сохранением проходит.
        for org in self:
            if not org.regime_ids:
                raise ValidationError(_(
                    "Укажите налоговый режим организации «%s»: без него не "
                    "посчитать налог в КП и счёте.", org.name))

    # ─── Чем пользуются документы ─────────────────────────────────────────
    @api.model
    def _pmk_default(self):
        """Организация по умолчанию: с флажком, иначе первая активная."""
        Org = self.sudo()
        return (Org.search([("is_default", "=", True)], limit=1)
                or Org.search([], limit=1)).with_env(self.env)

    def _pmk_regime_at(self, day):
        """Строка режима на дату (pmk.org.regime) или пустой набор."""
        self.ensure_one()
        # Сами записи, а не номера: в открытой форме у новых строк номер
        # временный (NewId), и browse по нему из другого окружения пуст.
        row = rg.regime_at([(r.date_from, r) for r in self.sudo().regime_ids], day)
        return row.with_env(self.env) if row else self.env["pmk.org.regime"]

    def _pmk_sale_tax_at(self, day, company=None):
        """Налог продаж режима на дату (account.tax) — или пустой набор."""
        self.ensure_one()
        row = self._pmk_regime_at(day)
        if not row:
            return self.env["account.tax"]
        return row._pmk_tax(company)

    def _pmk_tax_line(self, day, total, company=None):
        """Строка налога для печати на дату: (подпись, сумма или None)."""
        self.ensure_one()
        row = self._pmk_regime_at(day)
        if not row:
            # Констрейнт не даст сохранить организацию без режима; сюда
            # попадёт только запись, у которой строки удалили в обход.
            return seller.tax_line(0.0, total)
        tax = row._pmk_tax(company)
        rate = tax.amount if tax and tax.amount_type == "percent" else rg.RATES[row.regime]
        return seller.tax_line(rate, total, usn=rg.is_usn(row.regime))

    def _pmk_print_info(self):
        """Реквизиты для печати — словарём (pmk_bridge/tools/seller.py)."""
        self.ensure_one()
        org = self.sudo()
        partner = org.partner_id
        bank = org.bank_id or partner.bank_ids[:1]
        return seller.seller_info(
            name=org.name,
            inn=org.inn,
            kpp=org.kpp,
            org_type=org.org_type,
            reg_number=org.ogrn,
            address=seller.address_line(org.legal_address, org.city, org.street),
            phone=org.phone,
            email=org.email,
            bank=self.env["pmk.metal.spec"]._pmk_bank_info(bank),
            signer_position=org.signer_position,
            signer_name=org.signer_name,
            accountant_name=org.accountant_name,
        )

    def action_fill_by_inn(self):
        """«Заполнить по ИНН» — тем же запросом, что у карточки контрагента."""
        self.ensure_one()
        result = self.partner_id.action_pmk_fill_by_inn()
        if self.inn:
            self.org_type = seller.org_type_by_inn(self.inn)
        return result

    def action_open_partner(self):
        """Карточка контрагента организации — банковские счета и контакты там."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": self.partner_id.id,
            "views": [(False, "form")],
            "target": "current",
        }


class PmkOrgRegime(models.Model):
    _name = "pmk.org.regime"
    _description = "Налоговый режим организации"
    _order = "org_id, date_from desc, id desc"

    org_id = fields.Many2one(
        "pmk.org", "Организация", required=True, ondelete="cascade", index=True)
    date_from = fields.Date(
        "Действует с", required=True, default=fields.Date.context_today,
        help="С этой даты документы организации считаются по этому режиму — "
             "до даты начала следующей строки.")
    regime = fields.Selection(rg.REGIMES, "Режим", required=True, default="vat22")
    tax_id = fields.Many2one(
        "account.tax", "Налог продаж", compute="_compute_tax_id",
        help="Налог, который режим ставит в строки счёта покупателю. Заводится "
             "при установке модуля, ищется по пометке «Режим ПМК» на налоге.")
    state = fields.Selection(
        [("current", "действует"), ("past", "прошёл"), ("future", "будет")],
        "Сейчас", compute="_compute_state")

    _unique_date = models.Constraint(
        "unique(org_id, date_from)",
        "У организации уже есть режим с этой даты.",
    )

    @api.depends("regime")
    @api.depends_context("company")
    def _compute_tax_id(self):
        for row in self:
            row.tax_id = row._pmk_tax()

    @api.depends("date_from", "org_id.regime_ids.date_from")
    @api.depends_context("tz")
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for row in self:
            later = [r.date_from for r in row.org_id.regime_ids
                     if r.date_from and row.date_from and r.date_from > row.date_from]
            row.state = rg.state_of(row.date_from, min(later) if later else None, today)

    def _pmk_tax(self, company=None):
        """Налог продаж режима в компании Odoo (по умолчанию — текущей)."""
        self.ensure_one()
        company = company or self.env.company
        return self.env["account.tax"].sudo().search([
            ("pmk_regime", "=", self.regime),
            ("type_tax_use", "=", "sale"),
            ("company_id", "=", company.id),
        ], limit=1).with_env(self.env)
